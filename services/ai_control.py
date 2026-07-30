import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path


CAPABILITIES_PATH = Path(__file__).with_name("ai_control_capabilities.json")
GB = 1024 ** 3
PREVIEW_PAGE_SIZE = 20
LARGE_DELETE_CONFIRMATION_THRESHOLD = 50
DOWNLOAD_PREPARE_WORKERS = 4


def load_capabilities():
    with CAPABILITIES_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def default_config():
    return {
        "enabled": True,
        "trusted_indexers": [],
        "download_quality": "1080p",
        "ollama_curated_lists": False,
        "delete_mode": "recycle_bin",
    }


def coerce_config(raw=None):
    raw = raw or {}
    config = default_config()
    config["enabled"] = _coerce_bool(raw.get("enabled"), config["enabled"])
    config["trusted_indexers"] = [
        str(value).strip()
        for value in raw.get("trusted_indexers", config["trusted_indexers"]) or []
        if str(value).strip()
    ]
    config["download_quality"] = "1080p"
    config["ollama_curated_lists"] = _coerce_bool(
        raw.get("ollama_curated_lists"),
        config["ollama_curated_lists"],
    )
    config["delete_mode"] = "recycle_bin"
    return config


def preview_command(
    prompt,
    *,
    config=None,
    library_items=None,
    library_roots=None,
    plan_store=None,
    ollama_chat=None,
    tmdb_discover=None,
    tmdb_search=None,
    person_movies=None,
    owned_movies_lookup=None,
):
    prompt = str(prompt or "").strip()
    config = coerce_config(config)
    if not prompt:
        return _state("needs_clarification", "Enter a command using find, create list, download, or delete.")
    vague = _vague_prompt_message(prompt)
    if vague:
        return _state("needs_clarification", vague)
    if not config.get("enabled", True):
        return _state("unsupported", "AI Control is disabled in Settings.")

    intent = _parse_intent(
        prompt,
        config=config,
        ollama_chat=ollama_chat,
    )
    if intent.get("action") == "needs_clarification":
        return _state("needs_clarification", intent.get("clarification") or "Clarify the command.")
    valid = _validate_intent(intent)
    if valid and "invalid filter" in valid.get("message", "").lower():
        fallback_intent = _heuristic_intent(prompt, config)
        fallback_valid = _validate_intent(fallback_intent)
        if not fallback_valid:
            intent = fallback_intent
            valid = None
    if valid:
        return valid

    action = intent["action"]
    if action == "delete":
        return _preview_delete(prompt, intent, library_items or [], library_roots or [], plan_store)
    if action == "find":
        return _preview_find(prompt, intent, library_items or [], config, plan_store, tmdb_discover, tmdb_search, person_movies, owned_movies_lookup)
    if action == "create_list":
        return _preview_create_list(prompt, intent, library_items or [], config, plan_store, tmdb_discover, tmdb_search, person_movies, owned_movies_lookup)
    if action == "download":
        return _preview_download(prompt, intent, library_items or [], config, plan_store, tmdb_discover, tmdb_search, person_movies, owned_movies_lookup)
    return _state("unsupported", f"{action} is not supported in AI Control v1.")


def execute_plan(
    plan_id,
    *,
    plan_store,
    confirmation_phrase="",
    selected_keys=None,
    reviewed_downloads=None,
    library_roots=None,
    delete_file=None,
    create_list=None,
    prepare_download=None,
    submit_download=None,
):
    plan, claim_error = plan_store.claim(
        plan_id,
        confirmation_phrase=confirmation_phrase,
        selected_keys=selected_keys,
    )
    if not plan:
        if claim_error == "confirmation_required":
            return _state("unsafe", "The confirmation phrase does not match the reviewed plan.")
        if claim_error == "empty_selection":
            return _state("unsafe", "Select at least one reviewed result before confirming.")
        if claim_error == "invalid_selection":
            return _state("unsafe", "The selected results do not belong to the reviewed plan.")
        return _state("unsafe", "The reviewed plan is missing or expired. Preview the command again.")
    action = plan.get("action")
    if action == "find":
        return _execute_find(plan)
    if action == "delete":
        return _execute_delete(plan, library_roots or [], delete_file)
    if action == "create_list":
        return _execute_create_list(plan, create_list)
    if action == "download":
        return _execute_download(
            plan,
            prepare_download,
            submit_download,
            reviewed_downloads=reviewed_downloads,
        )
    return _state("unsupported", f"{action or 'This action'} cannot be executed.")


class PlanStore:
    def __init__(self, ttl_seconds=900):
        self.ttl_seconds = ttl_seconds
        self._plans = {}
        self._lock = threading.RLock()

    def put(self, plan):
        plan_id = uuid.uuid4().hex
        stored = deepcopy(plan)
        stored["plan_id"] = plan_id
        stored["created_at"] = time.time()
        with self._lock:
            self._plans[plan_id] = stored
        return deepcopy(stored)

    def get(self, plan_id):
        with self._lock:
            stored = self._active_plan(str(plan_id or ""))
            return deepcopy(stored) if stored else None

    def claim(self, plan_id, *, confirmation_phrase="", selected_keys=None):
        plan_id = str(plan_id or "")
        with self._lock:
            stored = self._active_plan(plan_id)
            if not stored:
                return None, "missing"
            selected, selection_error = _selected_plan(stored, selected_keys)
            if not selected:
                return None, selection_error
            selected_count = len(selected.get("items") or [])
            needs_confirmation = selected.get("action") == "delete" and selected_count > LARGE_DELETE_CONFIRMATION_THRESHOLD
            expected_phrase = f"DELETE {selected_count} FILES" if needs_confirmation else ""
            if needs_confirmation and str(confirmation_phrase or "").strip() != expected_phrase:
                return None, "confirmation_required"
            self._plans.pop(plan_id, None)
            selected["requires_extra_confirmation"] = needs_confirmation
            selected["confirmation_phrase"] = expected_phrase
            selected["total_matches"] = selected_count
            return deepcopy(selected), ""

    def _active_plan(self, plan_id):
        stored = self._plans.get(plan_id)
        if not stored:
            return None
        if time.time() - float(stored.get("created_at") or 0) > self.ttl_seconds:
            self._plans.pop(plan_id, None)
            return None
        return stored


def _parse_intent(prompt, *, config, ollama_chat=None):
    if ollama_chat:
        messages = _intent_messages(prompt, config)
        first = ""
        try:
            first = ollama_chat(messages)
            return _canonical_intent(_json_object(first), prompt, config)
        except Exception:
            try:
                repaired = ollama_chat([
                    {
                        "role": "system",
                        "content": "Repair the prior response. Return one valid JSON object only, with no markdown.",
                    },
                    {"role": "user", "content": json.dumps({"prompt": prompt, "invalid_response": first})},
                ])
                return _canonical_intent(_json_object(repaired), prompt, config)
            except Exception:
                return _state("needs_clarification", "I could not read the command. Try a more specific prompt.")
    return _canonical_intent(_heuristic_intent(prompt, config), prompt, config)


def _intent_messages(prompt, config):
    return [
        {
            "role": "system",
            "content": (
                "You extract movie-library command meaning. Return only JSON, no markdown. "
                "Fill exactly these flat keys, use empty string when absent: "
                "action, subject, subject_type, list_name, owned, quality, genre, year_from, year_to, sort, size_gb, comparison. "
                "Allowed: action=find/create_list/download/delete/unclear. "
                "subject_type=actor/director/title/genre/library/unknown. "
                "owned=owned/unowned/either. sort=top_rated/popular/newest. "
                "Examples: "
                "\"Alan Rickman movies\" => subject Alan Rickman, subject_type actor. "
                "\"unowned Jim Carrey movies in 1080p\" => action download, subject Jim Carrey, subject_type actor, owned unowned, quality 1080p. "
                "\"Nolan movies\" => subject Christopher Nolan, subject_type director. "
                "\"high rated sci fi from the 80s\" => genre Science Fiction, year_from 1980, year_to 1989, sort top_rated. "
                "\"larger than 10 GB\" => size_gb 10, comparison over."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"prompt": prompt, "settings": config}, separators=(",", ":")),
        },
    ]


def _canonical_intent(payload, prompt, config):
    if not isinstance(payload, dict):
        return payload
    if _looks_like_semantic_intent(payload):
        return _compile_semantic_intent(payload, prompt, config)
    return _normalize_canonical_intent(payload, prompt)


def _looks_like_semantic_intent(payload):
    return any(
        key in payload
        for key in (
            "target",
            "constraints",
            "list_name",
            "subject",
            "subject_type",
            "year_from",
            "year_to",
            "sort",
        )
    )


def _compile_semantic_intent(payload, prompt, config):
    action = _normalize_action(payload.get("action"))
    if action in {"", "unclear", "needs_clarification"}:
        return {"action": "needs_clarification", "clarification": "I need a clearer AI Control action."}
    intent = {
        "action": action,
        "filters": [],
    }
    if action == "create_list":
        intent["name"] = str(payload.get("list_name") or payload.get("name") or _list_name(prompt)).strip()
        intent["source"] = "tmdb"
    elif action in {"find", "download"}:
        intent["source"] = "tmdb" if action == "download" else "library"
    constraints = _semantic_constraints(payload)
    sort = str(constraints.get("sort") or "").strip().lower()
    if sort in {"top_rated", "popular", "newest"}:
        intent["sort"] = sort
    if not intent.get("sort") and str(constraints.get("rating") or "").strip().lower() in {"high", "high_rated", "top_rated"}:
        intent["sort"] = "top_rated"
    target_filter = _filter_from_semantic_target(_semantic_target(payload), prompt)
    if target_filter:
        intent["filters"].append(target_filter)
        if action in {"find", "create_list", "download"}:
            intent["source"] = "tmdb"
    for filter_item in _normalize_filters(payload.get("filters"), prompt):
        if filter_item not in intent["filters"]:
            intent["filters"].append(filter_item)
            if filter_item.get("field") in {"actor", "director", "genre", "year", "title"} and action in {"find", "create_list", "download"}:
                intent["source"] = "tmdb"
    for filter_item in _filters_from_semantic_constraints(constraints):
        intent["filters"].append(filter_item)
        if filter_item.get("field") in {"genre", "year"} and action in {"find", "create_list"}:
            intent["source"] = "tmdb"
    if action == "download":
        intent["download_policy"] = {"quality": "1080p"}
    return _normalize_canonical_intent(intent, prompt)


def _semantic_target(payload):
    target = payload.get("target")
    if isinstance(target, dict):
        return target
    subject = str(payload.get("subject") or "").strip()
    subject_type = str(payload.get("subject_type") or "").strip().lower()
    if subject_type in {"actor", "director"} and subject:
        return {"type": "person", "name": subject, "role": subject_type}
    if subject_type == "title" and subject:
        return {"type": "title", "name": subject}
    if subject_type == "genre":
        return {"type": "genre", "name": subject or payload.get("genre") or ""}
    if subject_type == "library":
        return {"type": "library", "name": subject}
    return {}


def _semantic_constraints(payload):
    constraints = payload.get("constraints")
    if isinstance(constraints, dict):
        merged = dict(constraints)
    else:
        merged = {}
    for key in ("owned", "quality", "year", "year_from", "year_to", "genre", "rating", "sort", "size_gb", "comparison"):
        if key in payload and payload.get(key) not in (None, ""):
            merged[key] = payload.get(key)
    return merged


def _normalize_action(value):
    action = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "list": "create_list",
        "create": "create_list",
        "create_list": "create_list",
        "find": "find",
        "search": "find",
        "download": "download",
        "delete": "delete",
        "remove": "delete",
        "unclear": "unclear",
        "needs_clarification": "needs_clarification",
    }.get(action, action)


def _filter_from_semantic_target(target, prompt):
    if not isinstance(target, dict):
        return None
    target_type = str(target.get("type") or "").strip().lower()
    name = str(target.get("name") or target.get("value") or "").strip()
    if target_type == "person" and name:
        role = str(target.get("role") or "").strip().lower()
        field = "director" if role == "director" or "director" in str(prompt).lower() or _looks_like_director_prompt(str(prompt).lower()) else "actor"
        return {"field": field, "op": "equals", "value": _normalize_person_name(name)}
    if target_type == "genre" and name:
        return {"field": "genre", "op": "equals", "value": _normalize_genre_name(name)}
    if target_type == "year":
        year_range = _year_range_from_text(name)
        if year_range and year_range[0] != year_range[1]:
            return {"field": "year", "op": "between", "value": [str(year_range[0]), str(year_range[1])]}
        if year_range:
            return {"field": "year", "op": "=", "value": str(year_range[0])}
    if target_type == "title" and name:
        return {"field": "title", "op": "contains", "value": name}
    return None


def _filters_from_semantic_constraints(constraints):
    if not isinstance(constraints, dict):
        return []
    filters = []
    year = str(constraints.get("year") or "").strip()
    year_from = str(constraints.get("year_from") or "").strip()
    year_to = str(constraints.get("year_to") or "").strip()
    if year_from or year_to:
        start, end = _coerce_year_range(year_from, year_to)
        if start and end and start != end:
            filters.append({"field": "year", "op": "between", "value": [str(start), str(end)]})
        elif start:
            filters.append({"field": "year", "op": "=", "value": str(start)})
    elif year:
        year_range = _year_range_from_text(year)
        if year_range and year_range[0] != year_range[1]:
            filters.append({"field": "year", "op": "between", "value": [str(year_range[0]), str(year_range[1])]})
        elif year_range:
            filters.append({"field": "year", "op": "=", "value": str(year_range[0])})
    genre = str(constraints.get("genre") or "").strip()
    if genre:
        filters.append({"field": "genre", "op": "equals", "value": _normalize_genre_name(genre)})
    size_gb = str(constraints.get("size_gb") or "").strip()
    if size_gb:
        comparison = str(constraints.get("comparison") or "equals").strip().lower()
        op = {"over": ">", "under": "<", "equals": "="}.get(comparison, "=")
        filters.append({"field": "size_gb", "op": op, "value": size_gb})
    owned = str(constraints.get("owned") or "").strip().lower()
    if owned in {"owned", "unowned"}:
        filters.append({"field": "owned", "op": "true" if owned == "owned" else "false", "value": owned == "owned"})
    quality = str(constraints.get("quality") or "").strip().lower()
    if quality and quality != "unknown":
        filters.append({"field": "resolution", "op": "equals", "value": quality})
    return filters


def _coerce_year_range(year_from, year_to):
    start_match = re.search(r"(?:19|20)\d{2}", str(year_from or ""))
    end_match = re.search(r"(?:19|20)\d{2}", str(year_to or ""))
    start = int(start_match.group(0)) if start_match else 0
    end = int(end_match.group(0)) if end_match else 0
    if start and not end:
        end = start
    if end and not start:
        start = end
    if start and end and start > end:
        start, end = end, start
    return start, end


def _year_range_from_text(value):
    text = str(value or "").strip().lower()
    if not text:
        return None
    explicit = re.findall(r"(?:19|20)\d{2}", text)
    if len(explicit) >= 2:
        start, end = int(explicit[0]), int(explicit[1])
        return (min(start, end), max(start, end))
    if len(explicit) == 1:
        year = int(explicit[0])
        if re.search(r"\b(?:19|20)\d0s\b", text):
            return (year, year + 9)
        return (year, year)
    decade = re.search(r"\b([5-9]0)s\b", text)
    if decade:
        start = 1900 + int(decade.group(1))
        return (start, start + 9)
    return None


def _normalize_genre_name(value):
    genre = str(value or "").strip()
    clean = re.sub(r"[^a-z0-9]+", " ", genre.lower()).strip()
    if clean in {"sci fi", "scifi", "sci fiction", "science fiction"}:
        return "Science Fiction"
    if clean == "rom com":
        return "Romance"
    return genre


def _normalize_canonical_intent(intent, prompt):
    if not isinstance(intent, dict):
        return intent
    normalized = dict(intent)
    normalized["action"] = _normalize_action(normalized.get("action"))
    if normalized.get("action") == "needs_clarification":
        normalized["clarification"] = normalized.get("clarification") or normalized.get("message") or "Clarify the command."
        return normalized
    if normalized.get("list_name") and not normalized.get("name"):
        normalized["name"] = normalized.get("list_name")
    normalized["filters"] = _normalize_filters(normalized.get("filters"), prompt)
    return _apply_prompt_ownership_hint(normalized, prompt)


def _apply_prompt_ownership_hint(intent, prompt):
    filters = list(intent.get("filters") or [])
    text = str(prompt or "").lower()
    owned_value = None
    if re.search(r"\b(?:unowned|not\s+in\s+my\s+library|missing\s+from\s+my\s+library|do\s+not\s+own|don't\s+own|dont\s+own)\b", text):
        owned_value = False
    elif re.search(r"\b(?:i\s+own|owned|in\s+my\s+library|i\s+have|my\s+collection)\b", text):
        owned_value = True
    if owned_value is None:
        return intent
    filters = [item for item in filters if not (isinstance(item, dict) and item.get("field") == "owned")]
    filters.append({"field": "owned", "op": "true" if owned_value else "false", "value": owned_value})
    return {**intent, "filters": filters}


def _normalize_filters(filters, prompt):
    if filters is None:
        return []
    if isinstance(filters, list):
        result = []
        for item in filters:
            normalized = _normalize_filter_item(item, prompt)
            if normalized:
                result.append(normalized)
        return result
    if isinstance(filters, dict):
        normalized = _normalize_filter_item(filters, prompt)
        return [normalized] if normalized else _normalize_filter_object(filters, prompt)
    return []


def _normalize_filter_object(filters, prompt):
    result = []
    for field, raw_value in filters.items():
        field = str(field or "").strip()
        if field not in load_capabilities()["filters"]:
            continue
        if isinstance(raw_value, dict):
            op, value = next(iter(raw_value.items()), ("equals", ""))
        else:
            op, value = "equals", raw_value
        result.append({"field": field, "op": str(op), "value": value})
    return result


def _normalize_filter_item(item, prompt):
    if isinstance(item, str):
        person = _normalize_person_name(item)
        if person:
            field = "director" if "director" in str(prompt).lower() or _looks_like_director_prompt(str(prompt).lower()) else "actor"
            return {"field": field, "op": "equals", "value": person}
        return None
    if not isinstance(item, dict):
        return None
    if "field" in item:
        return {
            "field": item.get("field"),
            "op": item.get("op") or item.get("operator") or "equals",
            "value": item.get("value"),
        }
    object_filters = _normalize_filter_object(item, prompt)
    return object_filters[0] if len(object_filters) == 1 else None


def _heuristic_intent(prompt, config):
    text = prompt.lower()
    filters = []
    size_match = re.search(r"(?:over|larger than|bigger than|above|>\s*)(\d+(?:\.\d+)?)\s*(?:gb|gigs|gigabytes)", text)
    if size_match:
        filters.append({"field": "size_gb", "op": ">", "value": float(size_match.group(1))})
    year_match = re.search(r"\b(?:from|in)\s*((?:19|20)\d{2})\b", text)
    if year_match:
        filters.append({"field": "year", "op": "=", "value": year_match.group(1)})
    genre_match = re.search(r"\b(action|adventure|animation|comedy|crime|documentary|drama|family|fantasy|horror|mystery|romance|sci-fi|science fiction|thriller|war)\b", text)
    if genre_match:
        filters.append({"field": "genre", "op": "equals", "value": genre_match.group(1).replace("science fiction", "sci-fi")})
    person = _person_from_prompt(prompt)
    if person:
        filters.append({"field": "director" if "director" in text or _looks_like_director_prompt(text) else "actor", "op": "equals", "value": person})
    if "delete" in text or "remove" in text:
        return {"action": "delete", "filters": filters}
    if "download" in text:
        return {"action": "download", "filters": filters, "download_policy": {"quality": "1080p"}}
    if "list" in text:
        return {"action": "create_list", "name": _list_name(prompt), "filters": filters, "source": "tmdb"}
    return {"action": "find", "filters": filters, "source": "library"}


def _preview_delete(prompt, intent, library_items, library_roots, plan_store):
    items = _filter_library_items(library_items, intent.get("filters") or [])
    candidates = []
    for item in items:
        path = str(item.get("path") or "")
        if not path or not _path_in_roots(path, library_roots) or not os.path.isfile(path):
            continue
        try:
            observed_size = os.path.getsize(path)
        except OSError:
            continue
        size = int(item.get("size") or observed_size)
        candidates.append({
            **_movie_preview_item(item),
            "title": item.get("title") or item.get("plex_title") or os.path.basename(path),
            "path": path,
            "size": size,
            "size_gb": round(size / GB, 2),
            "size_human": f"{size / GB:.1f} GB",
            "observed_size": observed_size,
            "status": "ready",
        })
    if not candidates:
        return _state("no_matches", "No library files matched this delete command.")
    requires_extra_confirmation = len(candidates) > LARGE_DELETE_CONFIRMATION_THRESHOLD
    plan = {
        "state": "valid_plan",
        "action": "delete",
        "message": f"Review {len(candidates)} file{'s' if len(candidates) != 1 else ''} before moving to Recycle Bin.",
        "summary": f"Move {len(candidates)} file{'s' if len(candidates) != 1 else ''} to Recycle Bin",
        "prompt": prompt,
        "items": _plan_items(candidates),
        "blocked": [],
        "warnings": [],
        "total_matches": len(candidates),
        "page_size": PREVIEW_PAGE_SIZE,
        "requires_extra_confirmation": requires_extra_confirmation,
        "confirmation_phrase": f"DELETE {len(candidates)} FILES" if requires_extra_confirmation else "",
    }
    return _store_or_return(plan, plan_store)


def _preview_find(prompt, intent, library_items, config, plan_store, tmdb_discover, tmdb_search, person_movies, owned_movies_lookup=None):
    source = str(intent.get("source") or "").lower()
    owned_filter = _ownership_filter_value(intent)
    if owned_filter is True:
        movies = _filter_library_items(library_items, intent.get("filters") or [])
        source = "library"
    elif owned_filter is False or _online_intent(intent, prompt):
        movies = _resolve_online_movies(intent, config, tmdb_discover, tmdb_search, person_movies)
        movies = _apply_online_ownership_filter(movies, intent, library_items, owned_movies_lookup)
    else:
        movies = _filter_library_items(library_items, intent.get("filters") or [])
    items = [_movie_preview_item(movie) for movie in movies]
    if not items:
        return _state("no_matches", "No movies matched this find command.")
    total = len(items)
    plan = {
        "state": "valid_plan",
        "action": "find",
        "message": f"Found {total} movie{'s' if total != 1 else ''}.",
        "summary": "Find results",
        "source": source or "library",
        "items": _plan_items(items),
        "blocked": [],
        "warnings": [],
        "total_matches": total,
        "page_size": PREVIEW_PAGE_SIZE,
    }
    return _store_or_return(plan, plan_store)


def _preview_create_list(prompt, intent, library_items, config, plan_store, tmdb_discover, tmdb_search, person_movies, owned_movies_lookup=None):
    if not _create_list_has_grounded_source(prompt, intent):
        return _state(
            "needs_clarification",
            "Tell me what should go in the list: actor, director, genre, year, owned movies, or a clear discovery type.",
        )
    owned_filter = _ownership_filter_value(intent)
    if owned_filter is True:
        movies = _filter_library_items(library_items, intent.get("filters") or [])
    elif owned_filter is False or _online_intent(intent, prompt):
        movies = _resolve_online_movies(intent, config, tmdb_discover, tmdb_search, person_movies)
        movies = _apply_online_ownership_filter(movies, intent, library_items, owned_movies_lookup)
    else:
        movies = _filter_library_items(library_items, intent.get("filters") or [])
    items = [_movie_preview_item(movie) for movie in movies]
    if not items:
        return _state("no_matches", "No movies matched this list command.")
    total = len(items)
    plan = {
        "state": "valid_plan",
        "action": "create_list",
        "message": f"Review {total} movie{'s' if total != 1 else ''} before creating the list.",
        "summary": f"Create list: {intent.get('name') or _list_name(prompt)}",
        "list_name": intent.get("name") or _list_name(prompt),
        "prompt": prompt,
        "items": _plan_items(items),
        "blocked": [],
        "warnings": [],
        "total_matches": total,
        "page_size": PREVIEW_PAGE_SIZE,
    }
    return _store_or_return(plan, plan_store)


def _preview_download(
    prompt,
    intent,
    library_items,
    config,
    plan_store,
    tmdb_discover,
    tmdb_search,
    person_movies,
    owned_movies_lookup=None,
):
    if not config.get("trusted_indexers"):
        return _state("integration_missing", "Choose AI Control trusted indexers in Settings before planning downloads.")
    movies = _resolve_online_movies(intent, config, tmdb_discover, tmdb_search, person_movies)
    movies = _apply_online_ownership_filter(movies, intent, library_items, owned_movies_lookup)
    if not movies:
        return _state("no_matches", "No online movies matched this download command.")
    items = _plan_items([_movie_preview_item(movie) for movie in movies])
    total_matches = len(items)
    plan = {
        "state": "valid_plan",
        "action": "download",
        "message": (
            f"{total_matches} movie{'s' if total_matches != 1 else ''} matched. "
            "Every result is selected. Confirm to find trusted sources and submit every available download to qBittorrent."
        ),
        "summary": f"Download {total_matches} movie{'s' if total_matches != 1 else ''} in 1080p",
        "prompt": prompt,
        "items": items,
        "blocked": [],
        "warnings": [],
        "total_matches": total_matches,
        "page_size": PREVIEW_PAGE_SIZE,
    }
    return _store_or_return(plan, plan_store)


def _execute_delete(plan, library_roots, delete_file):
    if not delete_file:
        return _state("unsafe", "Delete execution is unavailable.")
    deleted = []
    for item in plan.get("items") or []:
        path = str(item.get("path") or "")
        if not _path_in_roots(path, library_roots):
            return _state("unsafe", "A planned file is outside the library folders.")
        if not os.path.isfile(path):
            return _state("unsafe", "A planned file is no longer available.")
        try:
            current_size = os.path.getsize(path)
        except OSError:
            return _state("unsafe", "A planned file can no longer be read.")
        if current_size != int(item.get("observed_size") or -1):
            return _state("unsafe", "A planned file changed after preview. Preview the command again.")
        deleted.append(delete_file(path))
    return {
        "state": "executed",
        "action": "delete",
        "summary": "Files moved to Recycle Bin",
        "message": f"Moved {len(deleted)} file{'s' if len(deleted) != 1 else ''} to Recycle Bin.",
        "total_matches": len(deleted),
        "executed": deleted,
    }


def _execute_find(plan):
    count = len(plan.get("items") or [])
    return {
        "state": "executed",
        "action": "find",
        "summary": "Find selection confirmed",
        "message": f"Confirmed {count} selected movie{'s' if count != 1 else ''}.",
        "total_matches": count,
        "items": list(plan.get("items") or []),
    }


def _execute_create_list(plan, create_list):
    if not create_list:
        return _state("unsafe", "List creation is unavailable.")
    created = create_list(plan.get("list_name") or "AI Control List", plan.get("items") or [])
    if not isinstance(created, dict) or not created.get("id"):
        return _state("unsafe", "List creation did not return a persisted list.")
    count = int(created.get("count", len(created.get("movies") or [])) or 0)
    name = str(created.get("name") or plan.get("list_name") or "AI Control List")
    return {
        "state": "executed",
        "action": "create_list",
        "summary": f"List created: {name}",
        "message": f"Created {name} with {count} movie{'s' if count != 1 else ''}.",
        "total_matches": count,
        "created": created,
    }


def _execute_download(plan, prepare_download, submit_download, *, reviewed_downloads=None):
    if not prepare_download or not submit_download:
        return _state("unsafe", "Download submission is unavailable.")
    items = list(plan.get("items") or [])
    reviewed_by_key = {
        str(row.get("selection_key") or ""): row
        for row in reviewed_downloads or []
        if isinstance(row, dict) and str(row.get("selection_key") or "")
    }
    prepared = [None] * len(items)
    pending = []
    for index, item in enumerate(items):
        selection_key = str(item.get("selection_key") or "")
        if selection_key in reviewed_by_key:
            prepared[index] = deepcopy(reviewed_by_key[selection_key])
        else:
            pending.append((index, item))

    if pending:
        worker_count = max(1, min(DOWNLOAD_PREPARE_WORKERS, len(pending)))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(prepare_download, deepcopy(item)): index
                for index, item in pending
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    prepared[index] = future.result()
                except Exception as error:
                    prepared[index] = {
                        **items[index],
                        "status": "blocked",
                        "selected": False,
                        "variant": None,
                        "reason": str(error),
                    }

    submitted = []
    unavailable = []
    failed = []
    for item, row in zip(items, prepared):
        row = row if isinstance(row, dict) else {}
        row = {**item, **row}
        for field in ("selection_key", "tmdb_id", "imdb_id", "title", "year", "path"):
            if field in item:
                row[field] = item.get(field)
        if row.get("selected", True) is False or row.get("status") != "ready" or not row.get("variant"):
            unavailable.append({
                "movie": item.get("title", ""),
                "selection_key": item.get("selection_key", ""),
                "reason": row.get("reason") or "No selected trusted source",
            })
            continue
        try:
            submitted.append({
                "movie": item.get("title", ""),
                "selection_key": item.get("selection_key", ""),
                "result": submit_download(row),
            })
        except Exception as error:
            failed.append({
                "movie": item.get("title", ""),
                "selection_key": item.get("selection_key", ""),
                "error": str(error),
            })
    submitted_count = len(submitted)
    return {
        "state": "executed",
        "action": "download",
        "summary": "Downloads submitted",
        "message": (
            f"Submitted {submitted_count} download{'s' if submitted_count != 1 else ''} to qBittorrent. "
            f"{len(unavailable)} unavailable and {len(failed)} failed."
        ),
        "total_matches": len(items),
        "submitted_count": submitted_count,
        "unavailable_count": len(unavailable),
        "failed_count": len(failed),
        "submitted": submitted,
        "unavailable": unavailable,
        "failed": failed,
    }


def _validate_intent(intent):
    schema = load_capabilities()
    if not isinstance(intent, dict):
        return _state("needs_clarification", "I could not understand the command.")
    action = str(intent.get("action") or "").strip()
    if action not in schema["actions"] and action != "needs_clarification":
        return _state("unsupported", f"{action or 'That action'} is not supported in AI Control v1.")
    filters = intent.get("filters") or []
    if not isinstance(filters, list):
        return _state("needs_clarification", "The AI returned an invalid filter shape. Try a more specific command.")
    for filter_item in filters:
        if not isinstance(filter_item, dict):
            return _state("needs_clarification", "The AI returned an invalid filter. Try a more specific command.")
        field = str(filter_item.get("field") or "").strip()
        op = str(filter_item.get("op") or "").strip()
        if field not in schema["filters"]:
            return _state("unsupported", f"The filter '{field}' is not supported in AI Control v1.")
        allowed_ops = schema["filters"][field]
        if op and op not in allowed_ops:
            return _state("unsupported", f"The filter '{field} {op}' is not supported in AI Control v1.")
    return None


def _filter_library_items(items, filters):
    result = []
    for item in items:
        if all(_matches_filter(item, filter_item) for filter_item in filters):
            result.append(item)
    return result


def _matches_filter(item, filter_item):
    field = str(filter_item.get("field") or "").strip()
    op = str(filter_item.get("op") or "").strip()
    value = filter_item.get("value")
    if field == "size_gb":
        size_gb = int(item.get("size") or 0) / GB
        return _compare_number(size_gb, op, value)
    if field == "year":
        year = _first_year(item)
        return _compare_number(int(year or 0), op or "=", value)
    if field == "title":
        title = str(item.get("title") or item.get("plex_title") or item.get("filename") or "").lower()
        needle = str(value or "").lower()
        return title == needle if op == "equals" else needle in title
    if field == "genre":
        genres = item.get("genres") or item.get("plex_genres") or item.get("canonical_metadata", {}).get("genres") or []
        genre_text = " ".join(str(genre).lower() for genre in genres)
        return str(value or "").lower() in genre_text
    if field in {"actor", "director"}:
        people = _people_text(item, field)
        return str(value or "").lower() in people
    if field == "resolution":
        return str(value or "").lower() in str(item.get("resolution") or item.get("quality") or "").lower()
    if field == "owned":
        return bool(item.get("path")) is bool(value)
    return False


def _apply_online_ownership_filter(movies, intent, library_items, owned_movies_lookup=None):
    owned_filter = _ownership_filter_value(intent)
    if owned_filter is None:
        return movies
    owned_by_key = {}
    for item in library_items or []:
        for key in _movie_keys(item):
            owned_by_key.setdefault(key, item)
    movies = list(movies or [])
    matches = [_owned_movie_match(movie, owned_by_key) for movie in movies]
    unresolved_indexes = [index for index, match in enumerate(matches) if not match]
    if unresolved_indexes and owned_movies_lookup:
        try:
            fallback_matches = owned_movies_lookup([movies[index] for index in unresolved_indexes])
        except Exception:
            fallback_matches = []
        if isinstance(fallback_matches, (list, tuple)):
            for index, match in zip(unresolved_indexes, fallback_matches):
                if isinstance(match, dict) and match.get("found", True):
                    matches[index] = match
    result = []
    for movie, owned_match in zip(movies, matches):
        if owned_filter and owned_match:
            merged = {**movie, **owned_match}
            merged["source"] = "Library"
            result.append(merged)
        elif owned_filter is False and not owned_match:
            result.append(movie)
    return result


def _ownership_filter_value(intent):
    for item in intent.get("filters") or []:
        if isinstance(item, dict) and item.get("field") == "owned":
            return bool(item.get("value"))
    return None


def _owned_movie_match(movie, owned_by_key):
    for key in _movie_keys(movie):
        if key in owned_by_key:
            return owned_by_key[key]
    return None


def _resolve_online_movies(intent, config, tmdb_discover, tmdb_search, person_movies):
    filters = intent.get("filters") or []
    person_filter = next((item for item in filters if item.get("field") in {"actor", "director"}), None)
    if person_filter and person_movies:
        return person_movies(str(person_filter.get("value") or ""), person_filter.get("field"), config) or []
    query = str(intent.get("query") or intent.get("title") or "").strip()
    if query and tmdb_search:
        return tmdb_search(query, config) or []
    if tmdb_discover:
        return tmdb_discover(intent, config) or []
    return []


def _create_list_has_grounded_source(prompt, intent):
    filters = intent.get("filters") or []
    if any(item.get("field") in {"actor", "director", "genre", "year", "title", "owned"} for item in filters if isinstance(item, dict)):
        return True
    if str(intent.get("query") or intent.get("title") or "").strip():
        return True
    text = str(prompt or "").lower()
    return any(word in text for word in ("trending", "popular", "top rated", "best all time", "now playing", "upcoming"))


def _plan_items(items):
    return [
        {
            **deepcopy(item),
            "selection_key": f"item-{index + 1}",
        }
        for index, item in enumerate(items or [])
    ]


def _selected_plan(plan, selected_keys):
    items = list(plan.get("items") or [])
    if selected_keys is None:
        selected_items = items
    else:
        if not isinstance(selected_keys, (list, tuple, set)):
            return None, "invalid_selection"
        requested = [str(value or "").strip() for value in selected_keys]
        if not requested or any(not value for value in requested):
            return None, "empty_selection"
        requested_set = set(requested)
        available = {str(item.get("selection_key") or "") for item in items}
        if not requested_set.issubset(available):
            return None, "invalid_selection"
        selected_items = [
            item for item in items
            if str(item.get("selection_key") or "") in requested_set
        ]
    if not selected_items:
        return None, "empty_selection"
    selected = deepcopy(plan)
    selected["items"] = deepcopy(selected_items)
    selected["total_matches"] = len(selected_items)
    return selected, ""


def _store_or_return(plan, plan_store):
    if not plan_store:
        return {**plan, "plan_id": ""}
    return plan_store.put(plan)


def _state(state, message):
    return {
        "state": state,
        "plan_id": "",
        "action": "",
        "message": message,
        "summary": "",
        "items": [],
        "blocked": [],
        "warnings": [],
    }


def _json_object(content):
    text = str(content or "").strip()
    text = re.sub(r"^\s*```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("AI response did not contain JSON")
    payload = json.loads(text[start:end + 1])
    if not isinstance(payload, dict):
        raise ValueError("AI response must be a JSON object")
    return payload


def _vague_prompt_message(prompt):
    text = prompt.lower().strip()
    if text in {"clean my movies", "clean my library", "fix my movies", "organize my movies"}:
        return "I need a specific action: find, create list, download, or delete."
    if (
        re.search(r"\ball\s+movies\b", text)
        and re.search(r"\b(?:from|in)\s+(?:the\s+)?(?:(?:19|20)\d0s|[5-9]0s|(?:19|20)\d{2})\b", text)
        and not re.search(r"\b(?:owned|unowned|i\s+own|i\s+have|my\s+library|in\s+my\s+library|online|tmdb|download|delete|actor|director|with|by|sci[\s-]?fi|science fiction|action|adventure|animation|comedy|crime|documentary|drama|family|fantasy|horror|mystery|romance|thriller|war|top rated|high rated|popular)\b", text)
    ):
        return "Clarify whether you mean your local library or online TMDB results before asking for all movies in that date range."
    if re.search(r"\bdelete\b.*\b(?:bad|junk|trash|crap)\b", text):
        return "Define what to delete: low quality, large files, duplicates, unmatched metadata, or a specific filter."
    if re.search(r"\b(download|find|list)\b.*\b(everything|all movies ever)\b", text):
        return "That command is too broad. Add a genre, year, person, or limit."
    return ""


def _path_in_roots(path, roots):
    if not path or not roots:
        return False
    try:
        real_path = os.path.realpath(path)
        for root in roots:
            if not root:
                continue
            real_root = os.path.realpath(root)
            try:
                if os.path.commonpath([real_path, real_root]) == real_root:
                    return True
            except ValueError:
                continue
    except OSError:
        return False
    return False


def _compare_number(current, op, value):
    if op == "between" and isinstance(value, (list, tuple)) and len(value) == 2:
        return float(value[0]) <= current <= float(value[1])
    target = float(value)
    if op == ">":
        return current > target
    if op == "<":
        return current < target
    return current == target


def _movie_preview_item(movie):
    canonical = movie.get("canonical_metadata") or {}
    item = {
        "title": movie.get("title") or movie.get("plex_title") or movie.get("filename") or "",
        "year": str(movie.get("year") or movie.get("plex_year") or ""),
        "tmdb_id": str(movie.get("tmdb_id") or ""),
        "imdb_id": str(movie.get("imdb_id") or ""),
        "plex_guid": str(movie.get("plex_guid") or canonical.get("plex_guid") or ""),
        "path": movie.get("path") or "",
        "poster_url": movie.get("poster_url") or "",
        "source": movie.get("source") or ("Library" if movie.get("path") else "TMDB"),
        "status": movie.get("status") or "ready",
    }
    rich_fields = {
        "genres": movie.get("genres") or movie.get("plex_genres") or canonical.get("genres") or [],
        "tmdb_rating": movie.get("tmdb_rating") or movie.get("rating") or movie.get("plex_rating") or canonical.get("rating") or "",
        "tmdb_vote_count": movie.get("tmdb_vote_count") or canonical.get("tmdb_vote_count") or 0,
        "plot": movie.get("plot") or movie.get("summary") or movie.get("plex_summary") or canonical.get("summary") or canonical.get("plot") or "",
        "language": movie.get("language") or movie.get("plex_language") or canonical.get("language") or "",
        "country": movie.get("country") or movie.get("plex_country") or canonical.get("country") or "",
        "country_flag": movie.get("country_flag") or movie.get("plex_country_flag") or canonical.get("country_flag") or "",
        "release_date": movie.get("release_date") or canonical.get("release_date") or "",
        "resolution": movie.get("resolution") or movie.get("quality") or "",
        "size_human": movie.get("size_human") or "",
        "directors": movie.get("directors") or movie.get("plex_directors") or canonical.get("directors") or [],
        "director": movie.get("director") or canonical.get("director") or {},
        "cast": movie.get("cast") or movie.get("plex_cast") or canonical.get("cast") or [],
        "runtime": movie.get("runtime") or canonical.get("runtime") or "",
        "tagline": movie.get("tagline") or canonical.get("tagline") or "",
    }
    for key, value in rich_fields.items():
        if value not in ("", None, [], {}):
            item[key] = value
    return item


def _online_intent(intent, prompt):
    source = str(intent.get("source") or "").lower()
    text = str(prompt or "").lower()
    return source in {"tmdb", "online", "ollama"} or any(word in text for word in ("trending", "popular", "top rated", "best all time", "download"))


def _movie_key(movie):
    keys = _movie_keys(movie)
    return next(iter(keys), "")


def _movie_keys(movie):
    keys = []
    if movie.get("tmdb_id"):
        keys.append(f"tmdb:{movie.get('tmdb_id')}")
    title = str(movie.get("title") or movie.get("plex_title") or "").strip().lower()
    year = str(movie.get("year") or movie.get("plex_year") or "").strip()
    if title:
        keys.append(f"title:{title}|{year}")
    return keys


def _first_year(item):
    value = str(item.get("year") or item.get("plex_year") or item.get("title") or item.get("filename") or "")
    match = re.search(r"(?:19|20)\d{2}", value)
    return match.group(0) if match else ""


def _people_text(item, role):
    canonical = item.get("canonical_metadata") or {}
    values = []
    if role == "director":
        values.extend(item.get("directors") or item.get("plex_directors") or canonical.get("directors") or [])
    else:
        values.extend(item.get("cast") or item.get("plex_cast") or canonical.get("cast") or [])
    names = []
    for value in values:
        if isinstance(value, dict):
            names.append(str(value.get("name") or value.get("tag") or ""))
        else:
            names.append(str(value))
    return " ".join(names).lower()


def _person_from_prompt(prompt):
    match = re.search(r"\b(?:by|from|with|actor|director)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,3})", prompt, flags=re.I)
    if match:
        return _normalize_person_name(match.group(1))
    match = re.search(r"\b(?:include\s+)?all\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})\s+movies\b", prompt, flags=re.I)
    if match:
        return _normalize_person_name(match.group(1))
    match = re.search(r"^\s*(?:find|download|list|create\s+(?:a\s+)?list\s+of)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){1,3})\s+movies\b", prompt, flags=re.I)
    if match:
        return _normalize_person_name(match.group(1))
    return ""


def _normalize_person_name(value):
    tokens = [token for token in re.split(r"\s+", str(value or "").strip()) if token]
    while tokens and tokens[0].lower() in {"all", "any", "every", "the", "owned", "unowned"}:
        tokens.pop(0)
    while tokens and tokens[-1].lower() in {"film", "films", "movie", "movies"}:
        tokens.pop()
    cleaned = " ".join(tokens).strip()
    aliases = {
        "nolan": "Christopher Nolan",
        "spielberg": "Steven Spielberg",
        "kubrick": "Stanley Kubrick",
        "villeneuve": "Denis Villeneuve",
        "scorsese": "Martin Scorsese",
    }
    return aliases.get(cleaned.lower(), cleaned)


def _looks_like_director_prompt(text):
    return any(name in text for name in ("nolan", "spielberg", "kubrick", "villeneuve", "scorsese"))


def _list_name(prompt):
    named = re.search(r"\b(?:named|called)\s+[\"']([^\"']+)[\"']", str(prompt), flags=re.I)
    if named:
        return named.group(1).strip()[:80] or "AI Control List"
    text = re.sub(r"^\s*create\s+(?:a\s+)?list\s+(?:of|for)?\s*", "", str(prompt), flags=re.I).strip()
    return text[:80] or "AI Control List"


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default
