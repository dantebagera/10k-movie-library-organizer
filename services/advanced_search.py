import hashlib
import json
import math


QUERY_VERSION = 1
MAX_TOTAL_VALUES = 24
MAX_GROUP_VALUES = 10
MAX_TITLE_CHARACTERS = 100
MAX_PAGE_SIZE = 100
MAX_SUGGESTIONS = 20
DEBOUNCE_MS = 300

SUPPORTED_CRITERIA = {
    "library": {
        "title", "genre", "person", "keyword", "year", "rating",
        "language", "country", "runtime", "viewing_status", "movie_list",
        "resolution", "library_source",
    },
    "discover": {
        "title", "genre", "person", "keyword", "year", "rating",
        "minimum_votes", "language", "country", "runtime", "viewing_status",
        "movie_list", "availability",
    },
}
REPEATABLE_CRITERIA = {"genre", "person", "keyword", "movie_list", "resolution", "library_source"}
OR_ONLY_CRITERIA = {"resolution", "library_source"}
PERSON_ROLES = {"actor", "director", "writer"}
NUMERIC_OPERATORS = {"exactly", "at_least", "at_most", "between"}
RUNTIME_PRESETS = {"short", "feature", "long", "custom"}
DISCOVER_FEEDS = {
    "trending_week", "catalog", "trending_today", "now_playing", "upcoming",
    "popular", "top_rated", "best_all_time",
}
SORT_KEYS = {
    "library": {"added", "title", "rating", "year-desc", "year-asc", "quality"},
    "discover": {"auto", "popularity.desc", "vote_average.desc", "vote_count.desc", "primary_release_date.desc", "title.asc"},
}
CRITERION_ORDER = [
    "title", "genre", "person", "keyword", "year", "rating", "minimum_votes",
    "language", "country", "runtime", "viewing_status", "movie_list",
    "resolution", "library_source", "availability",
]


class AdvancedSearchValidationError(ValueError):
    pass


def _fail(message):
    raise AdvancedSearchValidationError(message)


def _text(value, label, maximum=160):
    normalized = str(value or "").strip()
    if len(normalized) > maximum:
        _fail(f"{label} exceeds {maximum} characters")
    return normalized


def _number(value, label):
    if isinstance(value, bool):
        _fail(f"{label} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        _fail(f"{label} must be a number")
    if not math.isfinite(number):
        _fail(f"{label} must be finite")
    return number


def _integer(value, label, minimum, maximum):
    number = _number(value, label)
    if not number.is_integer() or number < minimum or number > maximum:
        _fail(f"{label} must be between {minimum} and {maximum}")
    return int(number)


def _identity_value(value, criterion_type):
    if not isinstance(value, dict):
        _fail(f"{criterion_type} value must be an object")
    allowed = {"id", "label", "role"} if criterion_type == "person" else {"id", "label"}
    if criterion_type == "genre":
        allowed = allowed | {"exclude"}
    unknown = set(value) - allowed
    if unknown:
        _fail(f"Unknown {criterion_type} value fields: {', '.join(sorted(unknown))}")
    identity = _text(value.get("id"), f"{criterion_type} id", 120)
    label = _text(value.get("label"), f"{criterion_type} label", 160)
    if not identity or not label:
        _fail(f"{criterion_type} requires a controlled identity")
    normalized = {"id": identity, "label": label}
    if criterion_type == "genre" and "exclude" in value:
        if not isinstance(value["exclude"], bool):
            _fail("Genre exclusion must be true or false")
        if value["exclude"]:
            normalized["exclude"] = True
    if criterion_type == "person":
        role = _text(value.get("role"), "person role", 20).lower()
        if role not in PERSON_ROLES:
            _fail("Person role must be actor, director, or writer")
        normalized["role"] = role
    return normalized


def _numeric_value(value, criterion_type):
    if not isinstance(value, dict):
        _fail(f"{criterion_type} value must be an object")
    operator = _text(value.get("operator"), f"{criterion_type} operator", 20).lower()
    if operator not in NUMERIC_OPERATORS:
        _fail(f"Unknown {criterion_type} operator")
    expected = {"operator", "from", "to"} if operator == "between" else {"operator", "value"}
    if set(value) != expected:
        _fail(f"{criterion_type} {operator} has invalid fields")
    if criterion_type == "year":
        read = lambda candidate, label: _integer(candidate, label, 1888, 2100)
    else:
        def read(candidate, label):
            number = _number(candidate, label)
            if number < 0 or number > 10:
                _fail(f"{label} must be between 0 and 10")
            return round(number, 1)
    if operator == "between":
        lower = read(value.get("from"), f"{criterion_type} from")
        upper = read(value.get("to"), f"{criterion_type} to")
        if lower > upper:
            _fail(f"{criterion_type} range cannot be reversed")
        return {"operator": operator, "from": lower, "to": upper}
    return {"operator": operator, "value": read(value.get("value"), criterion_type)}


def _runtime_value(value):
    if not isinstance(value, dict):
        _fail("runtime value must be an object")
    preset = _text(value.get("preset"), "runtime preset", 20).lower()
    if preset not in RUNTIME_PRESETS:
        _fail("Unknown runtime preset")
    if preset != "custom":
        if set(value) != {"preset"}:
            _fail("Runtime preset has invalid fields")
        return {"preset": preset}
    if set(value) != {"preset", "from", "to"}:
        _fail("Custom runtime has invalid fields")
    lower = _integer(value.get("from"), "Runtime from", 0, 1440)
    upper = _integer(value.get("to"), "Runtime to", 0, 1440)
    if lower > upper:
        _fail("Runtime range cannot be reversed")
    return {"preset": preset, "from": lower, "to": upper}


def _normalize_value(criterion_type, value):
    if criterion_type == "title":
        if not isinstance(value, dict) or set(value) != {"text"}:
            _fail("Title value must contain only text")
        title = _text(value.get("text"), "Title", MAX_TITLE_CHARACTERS)
        if not title:
            _fail("Title cannot be empty")
        return {"text": title}
    if criterion_type in {"genre", "person", "keyword", "language", "country", "movie_list"}:
        return _identity_value(value, criterion_type)
    if criterion_type in {"year", "rating"}:
        return _numeric_value(value, criterion_type)
    if criterion_type == "minimum_votes":
        if not isinstance(value, dict) or set(value) != {"value"}:
            _fail("Minimum votes value is invalid")
        return {"value": _integer(value.get("value"), "Minimum votes", 0, 10_000_000)}
    if criterion_type == "runtime":
        return _runtime_value(value)
    if criterion_type in {"viewing_status", "resolution", "library_source", "availability"}:
        normalized = _identity_value(value, criterion_type)
        allowed = {
            "viewing_status": {"watched", "unwatched", "watchlist"},
            "resolution": {"upgrade", "4k", "1080p", "720p", "below-720p"},
            "availability": {"owned", "unowned"},
        }.get(criterion_type)
        if allowed is not None and normalized["id"] not in allowed:
            _fail(f"Unknown {criterion_type} value")
        return normalized
    _fail(f"Unsupported criterion type: {criterion_type}")


def _value_key(criterion_type, value):
    if criterion_type == "title":
        return value["text"].casefold()
    if criterion_type == "person":
        return f'{value["id"]}|{value["role"]}'
    if "id" in value:
        return str(value["id"])
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def normalize_query(query, expected_scope=None):
    if not isinstance(query, dict):
        _fail("Search query must be an object")
    allowed_top = {"version", "scope", "mode", "groups", "sort", "feed"}
    unknown_top = set(query) - allowed_top
    if unknown_top:
        _fail(f"Unknown search query fields: {', '.join(sorted(unknown_top))}")
    if query.get("version") != QUERY_VERSION:
        _fail("Search query version must be 1")
    scope = _text(query.get("scope"), "Search scope", 20).lower()
    if scope not in SUPPORTED_CRITERIA or (expected_scope and scope != expected_scope):
        _fail("Search query scope is invalid")
    mode = _text(query.get("mode") or "advanced", "Search mode", 20).lower()
    if mode not in {"simple", "advanced"}:
        _fail("Search query mode is invalid")
    raw_groups = query.get("groups")
    if not isinstance(raw_groups, list):
        _fail("Search query groups must be an array")
    groups = []
    seen_types = set()
    total_values = 0
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            _fail("Search query group must be an object")
        unknown_group = set(raw_group) - {"type", "join", "values"}
        if unknown_group:
            _fail(f"Unknown search group fields: {', '.join(sorted(unknown_group))}")
        criterion_type = _text(raw_group.get("type"), "Criterion type", 40).lower()
        if criterion_type not in SUPPORTED_CRITERIA[scope]:
            _fail(f"Criterion {criterion_type or '(missing)'} is not supported in {scope}")
        if criterion_type in seen_types:
            _fail(f"Duplicate {criterion_type} group")
        seen_types.add(criterion_type)
        raw_values = raw_group.get("values")
        if not isinstance(raw_values, list) or not raw_values:
            _fail(f"{criterion_type} requires at least one value")
        if len(raw_values) > MAX_GROUP_VALUES:
            _fail(f"{criterion_type} exceeds the per-group limit")
        values = []
        seen_values = {}
        for raw_value in raw_values:
            value = _normalize_value(criterion_type, raw_value)
            key = _value_key(criterion_type, value)
            if key in seen_values:
                if criterion_type == "genre" and bool(seen_values[key].get("exclude")) != bool(value.get("exclude")):
                    _fail("A genre cannot be both included and excluded")
                continue
            seen_values[key] = value
            values.append(value)
        if criterion_type not in REPEATABLE_CRITERIA and len(values) != 1:
            _fail(f"{criterion_type} accepts one value")
        values.sort(key=lambda item: (bool(item.get("exclude")), _value_key(criterion_type, item)))
        group = {"type": criterion_type, "values": values}
        if criterion_type in REPEATABLE_CRITERIA:
            join = _text(raw_group.get("join") or "or", f"{criterion_type} join", 10).lower()
            if join not in {"and", "or"}:
                _fail(f"{criterion_type} join must be and or or")
            if criterion_type in OR_ONLY_CRITERIA and join != "or":
                _fail(f"{criterion_type} supports OR only")
            group["join"] = join
        groups.append(group)
        total_values += len(values)
    if total_values > MAX_TOTAL_VALUES:
        _fail("Search query exceeds the total value limit")
    order = {name: index for index, name in enumerate(CRITERION_ORDER)}
    groups.sort(key=lambda item: order[item["type"]])

    raw_sort = query.get("sort") or {}
    if not isinstance(raw_sort, dict) or set(raw_sort) - {"key", "direction"}:
        _fail("Search sort is invalid")
    default_sort = "added" if scope == "library" else "auto"
    sort_key = _text(raw_sort.get("key") or default_sort, "Sort key", 40)
    if sort_key not in SORT_KEYS[scope]:
        _fail(f"Sort {sort_key} is not supported in {scope}")
    direction = _text(raw_sort.get("direction") or "desc", "Sort direction", 10).lower()
    if direction not in {"asc", "desc"}:
        _fail("Sort direction must be asc or desc")
    normalized = {
        "version": QUERY_VERSION,
        "scope": scope,
        "mode": mode,
        "groups": groups,
        "sort": {"key": sort_key, "direction": direction},
    }
    if scope == "discover":
        feed = _text(query.get("feed") or "trending_week", "Discover feed", 40)
        if feed not in DISCOVER_FEEDS:
            _fail("Discover feed is invalid")
        normalized["feed"] = feed
    elif "feed" in query:
        _fail("Library queries cannot contain a Discover feed")
    return normalized


def query_signature(query, expected_scope=None):
    normalized = normalize_query(query, expected_scope)
    execution = {
        key: value for key, value in normalized.items()
        if key != "mode"
    }
    execution["groups"] = [
        {
            **{key: value for key, value in group.items() if key != "values"},
            "values": [
                {key: value for key, value in item.items() if key != "label"}
                for item in group["values"]
            ],
        }
        for group in normalized["groups"]
    ]
    encoded = json.dumps(execution, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def group_map(query, expected_scope=None):
    normalized = normalize_query(query, expected_scope)
    return normalized, {group["type"]: group for group in normalized["groups"]}
