import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .iptv_movie_store import ACCEPTED_STATES, MATCHER_VERSION, MOVIE_SCHEMA_VERSION, IPTVMovieStore, source_key, validate_movie_key
from .iptv_tmdb import (
    IPTVTMDBClient,
    IPTVTMDBError,
    bounded_search_candidates,
    choose_automatic_match,
    clean_provider_title,
    extract_year,
    normalize_tmdb_movie,
    parse_provider_title,
    provider_id_matches,
    score_candidate,
)
from .iptv_xtream import XtreamError


class IPTVMovieService:
    """Provider-local orchestration for raw IPTV movies and enriched metadata."""

    _process_lock = threading.RLock()
    _processes = {}
    _instances = {}
    GLOBAL_WORKER_LIMIT = 1
    PROJECTION_BATCH_SIZE = 500
    WORKER_BATCH_LIMIT = 100

    def __init__(self, provider_root, provider_id, raw_service, metadata_settings, *, tmdb_client_factory=None, process_factory=None):
        self.provider_id = str(provider_id or "")
        self.root = Path(provider_root).resolve()
        self.raw_service = raw_service
        self.metadata_settings = metadata_settings
        self.tmdb_client_factory = tmdb_client_factory or (lambda: IPTVTMDBClient(self.metadata_settings))
        self.process_factory = process_factory or subprocess.Popen
        self._store = None
        self._store_lock = threading.RLock()
        self._projection_lock = threading.RLock()
        self._projection_thread = None
        with self._process_lock:
            self._instances[self.provider_id] = self

    @property
    def database_path(self):
        return self.root / "movies.sqlite"

    @property
    def store(self):
        with self._store_lock:
            if self._store is None:
                version = IPTVMovieStore.inspect_schema_version(self.database_path)
                if version not in {0, MOVIE_SCHEMA_VERSION}:
                    raise RuntimeError("This provider's IPTV Movies database requires an approved schema migration")
                self._store = IPTVMovieStore(self.root, self.provider_id)
            return self._store

    def _ready_store(self):
        if not self.database_path.is_file():
            return None
        if IPTVMovieStore.inspect_schema_version(self.database_path) != MOVIE_SCHEMA_VERSION:
            return None
        return self.store

    def _raw_connection(self):
        database_path = Path(self.raw_service.store.database_path).resolve()
        connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        return connection

    def _raw_state(self, connection=None):
        owned = connection is None
        connection = connection or self._raw_connection()
        try:
            meta = {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM meta")}
            favorite = connection.execute(
                "SELECT list_id FROM iptv_lists WHERE provider_key=? AND system_type='favorites' ORDER BY created_at LIMIT 1",
                (self.raw_service.provider_key(),),
            ).fetchone()
            return {
                "generation": int(float(meta.get("generation", 0) or 0)),
                "favorite_list_id": str(favorite[0]) if favorite else "",
            }
        finally:
            if owned:
                connection.close()

    @staticmethod
    def _batch_placeholders(values):
        return ",".join("?" for _ in values)

    def _project_raw_movies(self, connection, generation, total, lease_token):
        cursor = connection.execute(
            """SELECT i.*,COALESCE(c.name,'') playlist_name
               FROM items i LEFT JOIN categories c ON c.kind='movie' AND c.category_id=i.category_id
               WHERE i.kind='movie' ORDER BY i.position,i.item_id"""
        )
        while True:
            raw_rows = cursor.fetchmany(self.PROJECTION_BATCH_SIZE)
            if not raw_rows:
                break
            rows = []
            source_ids = []
            for row in raw_rows:
                item = dict(row)
                raw_json = item.pop("raw_json", "{}")
                try:
                    item["raw"] = json.loads(raw_json)
                except json.JSONDecodeError:
                    item["raw"] = {}
                rows.append(item)
                source_ids.append(str(item["item_id"]))
            placeholders = self._batch_placeholders(source_ids)
            history = {
                str(row["item_id"]): dict(row)
                for row in connection.execute(
                    f"SELECT * FROM watch_history WHERE kind='movie' AND item_id IN ({placeholders})",
                    source_ids,
                )
            }
            memberships = []
            for membership_row in connection.execute(
                f"""SELECT li.list_id,li.item_id source_id,li.position,li.added_at,li.snapshot_json
                    FROM iptv_list_items li JOIN iptv_lists l ON l.list_id=li.list_id
                    WHERE li.kind='movie' AND li.item_id IN ({placeholders})
                    ORDER BY l.position,li.position,li.item_id""",
                source_ids,
            ):
                membership = dict(membership_row)
                try:
                    membership["snapshot"] = json.loads(membership.pop("snapshot_json") or "{}")
                except json.JSONDecodeError:
                    membership["snapshot"] = {}
                memberships.append(membership)
            self.store.project_source_batch(
                rows, generation, memberships=memberships, history=history, lease_token=lease_token
            )
        self.store.finish_projection(generation, lease_token=lease_token)

    def _projection_worker(self, generation, total, lease_token):
        connection = self._raw_connection()
        try:
            self._project_raw_movies(connection, generation, total, lease_token)
        except Exception as error:
            self.store.projection_failed(lease_token, str(error))
        finally:
            connection.close()

    def start_projection(self, *, wait=False):
        with self._projection_lock:
            connection = self._raw_connection()
            try:
                state = self._raw_state(connection)
                total = connection.execute("SELECT COUNT(*) FROM items WHERE kind='movie'").fetchone()[0]
            finally:
                connection.close()
            store = self.store
            if store.source_generation() == state["generation"]:
                return store.projection_status()
            active = self._projection_thread
            if active is not None and active.is_alive():
                return store.projection_status()
            token = store.begin_projection(state["generation"], total)
            if not token:
                return store.projection_status()
            thread = threading.Thread(
                target=self._projection_worker,
                args=(state["generation"], int(total), token),
                name=f"cp-iptv-movie-projection-{self.provider_id[:8]}",
                daemon=True,
            )
            self._projection_thread = thread
            thread.start()
        if wait:
            thread.join()
        return store.projection_status()

    def ensure_projected(self):
        self.start_projection(wait=True)
        connection = self._raw_connection()
        try:
            return self._raw_state(connection)
        finally:
            connection.close()

    def projection_status(self):
        store = self._ready_store()
        if store is None:
            return {
                "state": "migration-required" if self.database_path.is_file() else "not-started",
                "phase": "", "source_generation": 0, "previous_generation": 0,
                "total": 0, "processed": 0, "published": 0, "error": "",
            }
        return store.projection_status()

    def retry_projection(self):
        return self.start_projection(wait=False)

    def list_movies(self, filters=None, page=1, page_size=30):
        store = self._ready_store()
        if store is None:
            return {"items": [], "page": max(1, int(page or 1)), "page_size": min(100, max(1, int(page_size or 30))), "total": 0, "generation": 0, "projection": self.projection_status()}
        snapshot = self._raw_state()
        result = store.list_movies(
            filters,
            page=page,
            page_size=page_size,
            favorite_list_id=snapshot["favorite_list_id"],
        )
        result["projection"] = store.projection_status()
        return result

    def facets(self):
        store = self._ready_store()
        result = store.facets() if store else {"playlists": [], "genres": [], "languages": [], "countries": [], "qualities": []}
        result["lists"] = self._raw_lists_readonly()
        result["projection"] = self.projection_status()
        return result

    def _raw_lists_readonly(self, *, include_system=False):
        connection = self._raw_connection()
        try:
            system_clause = "" if include_system else " AND l.system_type=''"
            rows = connection.execute(
                f"""SELECT l.*,
                           COUNT(li.item_id) AS item_count,
                           SUM(CASE WHEN li.kind='live' THEN 1 ELSE 0 END) AS live_count,
                           SUM(CASE WHEN li.kind='movie' THEN 1 ELSE 0 END) AS movie_count,
                           SUM(CASE WHEN li.kind='series' THEN 1 ELSE 0 END) AS series_count,
                           0 AS included
                    FROM iptv_lists l LEFT JOIN iptv_list_items li ON li.list_id=l.list_id
                    WHERE l.provider_key=?{system_clause}
                    GROUP BY l.list_id
                    ORDER BY CASE WHEN l.system_type='favorites' THEN -1 ELSE l.position END,l.created_at""",
                (self.raw_service.provider_key(),),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                for key in ("item_count", "live_count", "movie_count", "series_count"):
                    item[key] = int(item.get(key) or 0)
                item["system"] = bool(item.get("system_type"))
                item["included"] = False
                result.append(item)
            return result
        finally:
            connection.close()

    def movie(self, movie_key):
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        snapshot = self._raw_state()
        return store.movie(validate_movie_key(movie_key), snapshot["favorite_list_id"])

    def sources(self, movie_key):
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        return store.sources(validate_movie_key(movie_key))

    def _raw_list(self, list_id):
        lists = self.raw_service.lists(include_system=True)
        target = next((row for row in lists if row["list_id"] == str(list_id)), None)
        if target is None:
            raise KeyError("IPTV list was not found")
        return target

    def set_favorite(self, movie_key, favorite):
        movie_key = validate_movie_key(movie_key)
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        sources = store.sources(movie_key)
        available = [source for source in sources if source.get("available")]
        if not available:
            raise ValueError("This IPTV movie has no available source")
        if favorite:
            self.raw_service.set_favorite("movie", available[0]["item_id"], True)
        else:
            for source in sources:
                self.raw_service.set_favorite("movie", source["item_id"], False)
        favorite_list = next(
            (row for row in self.raw_service.lists(include_system=True) if row.get("system_type") == "favorites"),
            None,
        )
        if not favorite_list:
            raise RuntimeError("The provider Favorites list is unavailable")
        store.set_list_membership(
            favorite_list["list_id"], movie_key, bool(favorite), snapshot=available[0]
        )
        return bool(favorite)

    def set_list_membership(self, movie_key, list_id, included):
        movie_key = validate_movie_key(movie_key)
        target = self._raw_list(list_id)
        if target.get("system_type"):
            raise ValueError("Use the Favorite action for the provider Favorites list")
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        sources = store.sources(movie_key)
        available = [source for source in sources if source.get("available")]
        if included and not available:
            raise ValueError("This IPTV movie has no available source")
        if included:
            self.raw_service.set_list_item(list_id, "movie", available[0]["item_id"], True)
        else:
            for source in sources:
                self.raw_service.set_list_item(list_id, "movie", source["item_id"], False)
        store.set_list_membership(
            list_id, movie_key, bool(included), snapshot=(available or sources or [{}])[0]
        )
        return bool(included)

    def manual_search(self, movie_key, query="", year=0):
        movie = self.movie(movie_key)
        raw_title = str(query or movie.get("provider_title") or movie.get("name") or "").strip()
        target_year = (
            extract_year(year)
            or extract_year(raw_title)
            or extract_year(movie.get("provider_year") or movie.get("year") or 0)
        )
        parsed = parse_provider_title(raw_title, target_year)
        candidates, attempts = bounded_search_candidates(self.tmdb_client_factory(), parsed)
        items = []
        for row in candidates:
            score = score_candidate(parsed, target_year, row)
            candidate_year = extract_year(row.get("release_date") or row.get("year"))
            year_agreement = not target_year or not candidate_year or abs(target_year - candidate_year) <= 1
            result_class = "validated" if score >= 94 and year_agreement else "plausible" if score >= 78 and year_agreement else "low-relevance"
            items.append({
                "tmdb_id": int(row.get("id") or 0),
                "title": str(row.get("title") or row.get("original_title") or "Untitled"),
                "original_title": str(row.get("original_title") or ""),
                "year": str(row.get("release_date") or "")[:4],
                "plot": str(row.get("overview") or ""),
                "poster_url": f"https://image.tmdb.org/t/p/w342/{str(row.get('poster_path')).lstrip('/')}" if row.get("poster_path") else "",
                "score": score, "result_class": result_class,
                "matching_alias": row.get("search_alias") or parsed.get("primary_alias"),
                "year_agreement": year_agreement,
                "warnings": [] if year_agreement else ["Release year conflicts with the provider source"],
            })
        items.sort(key=lambda row: ({"validated": 0, "plausible": 1, "low-relevance": 2}[row["result_class"]], -row["score"], row["tmdb_id"]))
        return {
            "query": parsed.get("primary_alias") or raw_title,
            "year": target_year,
            "parsed": parsed,
            "attempts": attempts,
            "items": items,
        }

    def manual_match(self, movie_key, tmdb_id):
        movie_key = validate_movie_key(movie_key)
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        client = self.tmdb_client_factory()
        snapshot = client.normalized_movie(tmdb_id)
        next_key = store.apply_match(
            movie_key,
            snapshot,
            manual=True,
            method="manual",
            confidence=100,
            evidence={"tmdb_id": int(tmdb_id)},
        )
        if snapshot.get("original_language") == "ar":
            store.save_localization(tmdb_id, "ar-SA", client.normalized_movie(tmdb_id, language="ar-SA"))
        return next_key

    def remove_match(self, movie_key, reprocess=False):
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        return store.remove_match(validate_movie_key(movie_key), reprocess=bool(reprocess))

    def enrich_source(self, source_key_value, *, tmdb_client=None):
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        source = store.source(source_key_value)
        if not source:
            raise KeyError("IPTV movie source was not found")
        if not source.get("available"):
            return "unmatched"
        with store.connection() as connection:
            match = connection.execute(
                "SELECT * FROM source_matches WHERE source_key=?", (source_key_value,)
            ).fetchone()
        if match and match["manual_lock"]:
            return match["state"]
        client = tmdb_client or self.tmdb_client_factory()
        store.set_match_state([source_key_value], "provider-id-pending", method="provider-detail")
        detail = self.raw_service.enrichment_movie_detail(source["source_id"])
        store.update_provider_detail(source_key_value, detail)
        source = store.source(source_key_value) or source
        raw_parsed = parse_provider_title(source["provider_title"], source.get("provider_year"))
        detail_parsed = parse_provider_title(detail.get("name") or "", detail.get("year") or source.get("provider_year"))
        parsed = {
            "raw_title": source["provider_title"],
            "year": detail_parsed.get("year") or raw_parsed.get("year"),
            "latin_aliases": list(dict.fromkeys([*raw_parsed.get("latin_aliases", []), *detail_parsed.get("latin_aliases", [])])),
            "arabic_aliases": list(dict.fromkeys([*raw_parsed.get("arabic_aliases", []), *detail_parsed.get("arabic_aliases", [])])),
            "parser_version": raw_parsed.get("parser_version"),
        }
        parsed["aliases"] = list(dict.fromkeys([*parsed["latin_aliases"], *parsed["arabic_aliases"]]))
        parsed["primary_alias"] = (parsed["latin_aliases"] or parsed["arabic_aliases"] or [""])[0]
        provider_tmdb_id = int(detail.get("tmdb_id") or source.get("provider_tmdb_id") or 0)
        if provider_tmdb_id:
            payload = client.movie(provider_tmdb_id)
            valid, confidence = provider_id_matches(
                parsed,
                parsed["year"],
                payload,
            )
            if valid:
                key = f"source:{source_key_value}"
                snapshot = normalize_tmdb_movie(payload)
                store.apply_match(
                    key,
                    snapshot,
                    manual=False,
                    method="provider-tmdb-id",
                    confidence=confidence,
                    evidence={"provider_id_validation": {"provider_tmdb_id": provider_tmdb_id, "validated": True, "score": confidence, "parsed": parsed}},
                )
                if snapshot.get("original_language") == "ar":
                    store.save_localization(provider_tmdb_id, "ar-SA", client.normalized_movie(provider_tmdb_id, language="ar-SA"))
                return "matched-auto"
        provider_evidence = {"provider_tmdb_id": provider_tmdb_id, "validated": False, "parsed": parsed}
        store.set_match_state([source_key_value], "search-pending", method="title-year-search", evidence={"provider_id_validation": provider_evidence})
        candidates, attempts = bounded_search_candidates(client, parsed)
        decision = choose_automatic_match(parsed, parsed["year"], candidates)
        if decision["accepted"]:
            accepted = decision["accepted"]
            snapshot = client.normalized_movie(accepted["id"])
            store.apply_match(
                f"source:{source_key_value}",
                snapshot,
                manual=False,
                method="strict-title-year",
                confidence=accepted["match_score"],
                evidence={
                    "provider_id_validation": provider_evidence,
                    "fallback_search": {"parsed": parsed, "attempts": attempts, "candidate_count": len(decision["candidates"])},
                },
            )
            if snapshot.get("original_language") == "ar":
                store.save_localization(accepted["id"], "ar-SA", client.normalized_movie(accepted["id"], language="ar-SA"))
            return "matched-auto"
        evidence = {
            "provider_id_validation": provider_evidence,
            "fallback_search": {
                "parsed": parsed, "attempts": attempts,
                "candidates": [{"tmdb_id": int(row.get("id") or 0), "score": row.get("match_score", 0), "alias": row.get("search_alias"), "phase": row.get("search_phase")} for row in decision["candidates"][:5]],
            },
        }
        store.set_match_state(
            [source_key_value], decision["state"], method="strict-title-year", evidence=evidence
        )
        return decision["state"]

    def localization(self, movie_key, locale):
        movie = self.movie(movie_key)
        tmdb_id = int(movie.get("tmdb_id") or 0)
        if not tmdb_id:
            raise ValueError("Unmatched provider movies do not have TMDB localization")
        locale = str(locale or "")
        stored = self.store.localization(tmdb_id, locale)
        if stored:
            return self.store.merge_localization_display(movie, stored, locale)
        if locale != "ar-SA":
            raise ValueError("Unsupported IPTV movie localization")
        # Non-Arabic movies fetch Arabic only after an explicit user switch and
        # do not persist that transient presentation choice.
        localized = self.tmdb_client_factory().normalized_movie(tmdb_id, language=locale)
        return {**self.store.merge_localization_display(movie, localized, locale), "transient": True}

    def repair_missing_arabic_localizations(self, *, limit=100, tmdb_client=None):
        """Backfill display-only Arabic snapshots without changing accepted identities."""
        store = self._ready_store()
        if store is None:
            raise RuntimeError("Provider movies are still being prepared")
        tmdb_ids = store.missing_arabic_localizations(limit=limit)
        client = tmdb_client or self.tmdb_client_factory()
        saved = []
        failed = []
        for tmdb_id in tmdb_ids:
            try:
                store.save_localization(tmdb_id, "ar-SA", client.normalized_movie(tmdb_id, language="ar-SA"))
                saved.append(tmdb_id)
            except Exception as error:
                failed.append({"tmdb_id": tmdb_id, "error": str(error)[:300]})
        return {"requested": len(tmdb_ids), "saved": saved, "failed": failed}

    @staticmethod
    def _pid_alive(pid):
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False

    @property
    def _scheduler_path(self):
        return self.metadata_settings.root / "metadata-worker-scheduler.json"

    def _claim_global_capacity(self, token):
        path = self._scheduler_path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"provider_id": self.provider_id, "token": token, "pid": os.getpid()})
        for _attempt in range(2):
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(payload)
                return True
            except FileExistsError:
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    current = {}
                if self._pid_alive(current.get("pid")):
                    return False
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        return False

    def _update_global_capacity_pid(self, token, pid):
        try:
            current = json.loads(self._scheduler_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if current.get("provider_id") == self.provider_id and current.get("token") == token:
            temporary = self._scheduler_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(json.dumps({**current, "pid": int(pid)}), encoding="utf-8")
            os.replace(temporary, self._scheduler_path)

    def _release_global_capacity(self, token):
        try:
            current = json.loads(self._scheduler_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if current.get("provider_id") == self.provider_id and current.get("token") == token:
            try:
                self._scheduler_path.unlink()
            except FileNotFoundError:
                pass

    def _monitor_worker(self, process, token):
        try:
            process.wait()
        except Exception:
            while process.poll() is None:
                time.sleep(0.25)
        self._release_global_capacity(token)
        with self._process_lock:
            if self._processes.get(self.provider_id) is process:
                self._processes.pop(self.provider_id, None)
            waiting = [service for service in self._instances.values() if service.provider_id != self.provider_id]
        for service in waiting:
            try:
                if service.enrichment_status().get("state") == "waiting-capacity":
                    service.resume_enrichment()
                    break
            except Exception:
                continue

    def _existing_local_worker_start(self):
        """Keep repeated start/resume requests from replacing a live lease.

        A worker can record its terminal database state just before its OS
        process exits. During that short window, issuing Start again must not
        mint a new token for a process that was launched with the old token.
        """
        with self._process_lock:
            process = self._processes.get(self.provider_id)
            if process is None:
                return None
            if process.poll() is not None:
                self._processes.pop(self.provider_id, None)
                return None
        status = self.enrichment_status()
        if status.get("command") == "run" and status.get("state") in {
            "starting", "running", "waiting-capacity",
        }:
            return status
        raise RuntimeError(
            "The previous IPTV metadata worker is still shutting down; try again in a moment"
        )

    def _spawn_worker(self, token, *, diagnostic_limit=0):
        with self._process_lock:
            active = {
                provider_id: process
                for provider_id, process in self._processes.items()
                if process.poll() is None
            }
            self._processes = active
            current = active.get(self.provider_id)
            if current is not None:
                return current
            if len(active) >= self.GLOBAL_WORKER_LIMIT or not self._claim_global_capacity(token):
                self.store.worker_waiting_for_capacity(token)
                return None
            environment = os.environ.copy()
            environment.update({
                "CP_IPTV_WORKER_PROVIDER_ID": self.provider_id,
                "CP_IPTV_WORKER_PROVIDER_ROOT": str(self.root),
                "CP_IPTV_WORKER_USER_DATA_DIR": str(self.metadata_settings.root.parent),
                "CP_IPTV_WORKER_LEASE_TOKEN": token,
                "CP_IPTV_WORKER_MAX_JOBS": str(max(0, int(diagnostic_limit or 0))),
                "CP_IPTV_WORKER_SCHEDULER_PATH": str(self._scheduler_path),
            })
            try:
                process = self.process_factory(
                    [sys.executable, "-m", "services.iptv_enrichment_worker"],
                    cwd=str(Path(__file__).resolve().parents[1]), env=environment,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except Exception:
                self._release_global_capacity(token)
                raise
            self._processes[self.provider_id] = process
            self._update_global_capacity_pid(token, process.pid)
            self.store.worker_started(process.pid, token)
            threading.Thread(target=self._monitor_worker, args=(process, token), name=f"cp-iptv-worker-monitor-{self.provider_id[:8]}", daemon=True).start()
            return process

    def start_enrichment(self, *, consent=False, diagnostic=False):
        if self._ready_store() is None or self.projection_status().get("state") != "complete":
            raise RuntimeError("Finish preparing provider movies before starting metadata enrichment")
        existing = self._existing_local_worker_start()
        if existing is not None:
            return existing
        self.metadata_settings.credential()
        limit = self.WORKER_BATCH_LIMIT if diagnostic else 0
        token = self.store.prepare_enrichment(consent=bool(consent), diagnostic_limit=limit)
        self._spawn_worker(token, diagnostic_limit=limit)
        return self.enrichment_status()

    def pause_enrichment(self):
        self.store.worker_command("pause")
        return self.enrichment_status()

    def resume_enrichment(self, *, continue_after_restart=False):
        existing = self._existing_local_worker_start()
        if existing is not None:
            return existing
        self.metadata_settings.credential()
        token = self.store.resume_worker(continue_after_restart=bool(continue_after_restart))
        self._spawn_worker(token, diagnostic_limit=self.store.worker_status().get("diagnostic_limit", 0))
        return self.enrichment_status()

    def cancel_enrichment(self):
        with self._process_lock:
            process = self._processes.get(self.provider_id)
            if process is not None and process.poll() is not None:
                self._processes.pop(self.provider_id, None)
                process = None
        if process is None:
            self.store.cancel_enrichment()
        else:
            self.store.worker_command("cancel")
        return self.enrichment_status()

    def enrichment_status(self):
        if not self.database_path.is_file():
            return {
                "state": "idle", "command": "idle", "pid": 0, "error": "",
                "started_at": 0, "finished_at": 0, "generation": 0,
                "source_generation": 0, "sources": 0, "queue": {}, "matches": {},
                "batch_limit": self.WORKER_BATCH_LIMIT,
            }
        return {**self.store.worker_status(), "batch_limit": self.WORKER_BATCH_LIMIT, "projection": self.projection_status()}

    def metadata_status(self):
        return self.enrichment_status()

    def metadata_review(self, view="needs-review", page=1, page_size=50):
        store = self._ready_store()
        if store is None:
            return {"view": view, "items": [], "page": page, "page_size": page_size, "total": 0}
        return store.review_queue(view, page=page, page_size=page_size)

    def prioritize_movies(self, movie_keys):
        store = self._ready_store()
        if store is None:
            return 0
        source_keys = []
        for movie_key in list(movie_keys or [])[:100]:
            source_keys.extend(store.source_keys_for_movie(validate_movie_key(movie_key)))
        return store.prioritize_sources(source_keys)

    def retry_failures(self):
        count = self.store.retry_failures()
        return {**self.enrichment_status(), "retried": count}

    def re_evaluate_stale(self):
        self.store.mark_stale_automatic_results()
        count = self.store.re_evaluate_stale()
        return {**self.enrichment_status(), "requeued": count}

    def close(self):
        with self._process_lock:
            process = self._processes.pop(self.provider_id, None)
        if process is not None and process.poll() is None:
            if self.database_path.is_file():
                self.store.worker_command("cancel")
            process.terminate()
        with self._process_lock:
            self._instances.pop(self.provider_id, None)


def classify_enrichment_error(error):
    if isinstance(error, IPTVTMDBError):
        if error.status == 401:
            return "error-terminal", "authentication", False, 0
        if error.status == 429:
            return "error-retryable", "rate-limit", True, max(1, error.retry_after)
        return (
            "error-retryable" if error.retryable else "error-terminal",
            "tmdb",
            bool(error.retryable),
            30 if error.retryable else 0,
        )
    if isinstance(error, (XtreamError, TimeoutError, OSError)):
        return "error-retryable", "provider", True, 30
    return "error-terminal", "unexpected", False, 0
