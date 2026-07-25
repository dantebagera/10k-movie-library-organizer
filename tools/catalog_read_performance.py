import argparse
import json
import statistics
import sys
import threading
import time
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app
from services.catalog_store import CatalogStore
from tools.catalog_migration_backup import resolve_backup_sources


def _percentile(values, percentile):
    values = sorted(float(value) for value in values)
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, round((len(values) - 1) * percentile)))
    return values[index]


def _timing_summary(values):
    values = [float(value) for value in values]
    return {
        "samples": len(values),
        "min_ms": round(min(values), 3) if values else 0,
        "median_ms": round(statistics.median(values), 3) if values else 0,
        "p95_ms": round(_percentile(values, 0.95), 3),
        "max_ms": round(max(values), 3) if values else 0,
    }


class SqlTrace:
    def __init__(self):
        self.statements = []
        self._lock = threading.Lock()

    def callback(self, statement):
        normalized = str(statement or "").strip()
        if not normalized or normalized.upper().startswith("PRAGMA"):
            return
        with self._lock:
            self.statements.append(normalized)

    def reset(self):
        with self._lock:
            self.statements.clear()

    def count(self):
        with self._lock:
            return len(self.statements)


@contextmanager
def traced_catalog_connections(trace):
    original = CatalogStore.connect

    def connect(store):
        connection = original(store)
        connection.set_trace_callback(trace.callback)
        return connection

    with patch.object(CatalogStore, "connect", connect):
        yield


def _catalog_inventory(database_path):
    store = CatalogStore(database_path)
    connection = store.connect()
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        counts = {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
        }
        meta = {
            str(row[0]): str(row[1])
            for row in connection.execute("SELECT key, value FROM catalog_meta ORDER BY key")
        }
        representative = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT mf.path
                FROM media_files mf
                JOIN canonical_movie_files cmf ON cmf.path_key = mf.path_key
                JOIN canonical_movies cm ON cm.movie_key = cmf.movie_key
                ORDER BY
                    CASE WHEN mf.resolution IN ('4K', '2160p') THEN 0 ELSE 1 END,
                    CASE WHEN mf.resolution IN ('720p', '480p', 'Unknown') THEN 0 ELSE 1 END,
                    CASE WHEN EXISTS(
                        SELECT 1 FROM provider_movie_snapshots pms
                        JOIN movie_collections mc ON mc.snapshot_key = pms.snapshot_key
                        WHERE pms.movie_key = cm.movie_key
                    ) THEN 0 ELSE 1 END,
                    CASE WHEN EXISTS(
                        SELECT 1 FROM provider_movie_snapshots pms
                        JOIN movie_credits cr ON cr.snapshot_key = pms.snapshot_key
                        WHERE pms.movie_key = cm.movie_key
                    ) THEN 0 ELSE 1 END,
                    mf.added_time DESC,
                    mf.path_key
                LIMIT 10
                """
            )
        ]
        writer_row = connection.execute("""
            SELECT COALESCE(NULLIF(p.tmdb_id, ''), p.provider_id) AS person_id, p.name
            FROM movie_credits mc
            JOIN people p ON p.person_key = mc.person_key
            WHERE mc.credit_type = 'writer'
            ORDER BY p.name COLLATE NOCASE, person_id
            LIMIT 1
        """).fetchone()
        keyword_row = connection.execute("""
            SELECT k.tmdb_id, k.name, k.normalized_name
            FROM keywords k
            JOIN movie_keywords mk ON mk.keyword_key = k.keyword_key
            ORDER BY k.name COLLATE NOCASE, k.keyword_key
            LIMIT 1
        """).fetchone()
        search_representatives = {
            "writer": dict(writer_row) if writer_row else {},
            "keyword": dict(keyword_row) if keyword_row else {},
        }
        cte = store._library_effective_cte()
        query_plans = {}
        plan_filters = {
            "first_page_added": {"sort": "added"},
            "combined_search_genre_year": {
                "query": "avatar", "genre": "Science Fiction", "year_from": "2000", "sort": "year-desc",
            },
        }
        if writer_row:
            plan_filters["writer_search"] = {
                "role": "writer",
                "person_id": str(writer_row["person_id"] or ""),
                "person_name": str(writer_row["name"] or ""),
                "sort": "title",
            }
        if keyword_row:
            plan_filters["keyword_search"] = {
                "keyword_id": str(keyword_row["tmdb_id"] or ""),
                "keyword_name": str(keyword_row["name"] or ""),
                "sort": "title",
            }
        for name, filters in plan_filters.items():
            where, parameters = store._library_filter_sql(filters)
            rows = connection.execute(
                f"EXPLAIN QUERY PLAN {cte} SELECT e.path_key FROM effective e{where} "
                f"ORDER BY {store._library_sort_sql(filters.get('sort'))} LIMIT 40",
                parameters,
            ).fetchall()
            query_plans[name] = [str(row[3]) for row in rows]
        return {
            "database_path": str(Path(database_path).resolve()),
            "database_bytes": Path(database_path).stat().st_size,
            "integrity": str(connection.execute("PRAGMA integrity_check").fetchone()[0]),
            "foreign_key_violations": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
            "meta": meta,
            "row_counts": counts,
            "representative_paths": representative,
            "search_representatives": search_representatives,
            "query_plans": query_plans,
        }
    finally:
        connection.close()


def _route_probe(paths, search_representatives=None):
    repository = app._catalog_repository()
    repository._cache.clear()
    client = app.app.test_client()
    trace = SqlTrace()
    provider_calls = []

    def blocked_provider(request, *args, **kwargs):
        url = getattr(request, "full_url", None) or str(request)
        provider_calls.append(url)
        raise AssertionError(f"Provider request attempted during owned catalog benchmark: {url}")

    details = []
    searches = {}
    with traced_catalog_connections(trace), patch("app.urllib.request.urlopen", side_effect=blocked_provider):
        for index, movie_path in enumerate(paths):
            if index == 0:
                repository._cache.clear()
            trace.reset()
            started = time.perf_counter()
            response = client.get("/api/library/details", query_string={"path": movie_path})
            elapsed = (time.perf_counter() - started) * 1000
            payload = response.get_json(silent=True) or {}
            details.append({
                "path": movie_path,
                "status": response.status_code,
                "elapsed_ms": round(elapsed, 3),
                "route_ms": float(response.headers.get("X-CP-Route-MS") or 0),
                "query_count": trace.count(),
                "title": ((payload.get("item") or {}).get("canonical_metadata") or {}).get("title", ""),
                "cast_count": len(((payload.get("item") or {}).get("canonical_metadata") or {}).get("cast") or []),
                "director_count": len(((payload.get("item") or {}).get("canonical_metadata") or {}).get("directors") or []),
            })

        original_cache = dict(app._library_cache)
        try:
            app._library_cache = {}
            trace.reset()
            started = time.perf_counter()
            cold = client.get("/api/library", query_string={"view": "cards"})
            cold_elapsed = (time.perf_counter() - started) * 1000
            cold_queries = trace.count()
            trace.reset()
            started = time.perf_counter()
            warm = client.get("/api/library", query_string={"view": "cards"})
            warm_elapsed = (time.perf_counter() - started) * 1000
            warm_queries = trace.count()
        finally:
            app._library_cache = original_cache

        writer = dict((search_representatives or {}).get("writer") or {})
        keyword = dict((search_representatives or {}).get("keyword") or {})
        search_requests = {}
        if writer:
            search_requests["writer_cards"] = {
                "view": "cards",
                "role": "writer",
                "person_id": writer.get("person_id", ""),
                "person_name": writer.get("name", ""),
            }
        if keyword:
            search_requests["keyword_entities"] = {
                "view": "keywords",
                "q": keyword.get("normalized_name") or keyword.get("name", ""),
            }
            search_requests["keyword_cards"] = {
                "view": "cards",
                "keyword_id": keyword.get("tmdb_id", ""),
                "keyword_name": keyword.get("name", ""),
            }
        for name, query in search_requests.items():
            trace.reset()
            started = time.perf_counter()
            response = client.get("/api/library", query_string=query)
            elapsed = (time.perf_counter() - started) * 1000
            payload = response.get_json(silent=True) or {}
            searches[name] = {
                "status": response.status_code,
                "elapsed_ms": round(elapsed, 3),
                "route_ms": float(response.headers.get("X-CP-Route-MS") or 0),
                "query_count": trace.count(),
                "returned": len(payload.get("items") or []),
                "total": int(payload.get("total", payload.get("count", 0)) or 0),
            }

    detail_times = [row["elapsed_ms"] for row in details]
    detail_queries = [row["query_count"] for row in details]
    return {
        "details": details,
        "details_timing": _timing_summary(detail_times),
        "details_query_count": {
            "min": min(detail_queries) if detail_queries else 0,
            "max": max(detail_queries) if detail_queries else 0,
        },
        "provider_calls": provider_calls,
        "searches": searches,
        "library": {
            "cold": {
                "status": cold.status_code,
                "elapsed_ms": round(cold_elapsed, 3),
                "route_ms": float(cold.headers.get("X-CP-Route-MS") or 0),
                "query_count": cold_queries,
                "returned": len((cold.get_json(silent=True) or {}).get("items") or []),
            },
            "warm": {
                "status": warm.status_code,
                "elapsed_ms": round(warm_elapsed, 3),
                "route_ms": float(warm.headers.get("X-CP-Route-MS") or 0),
                "query_count": warm_queries,
                "returned": len((warm.get_json(silent=True) or {}).get("items") or []),
            },
        },
    }


def _live_probe(base_url, paths):
    results = {"health": [], "library": [], "details": []}
    requests = [
        ("health", "/api/library/status"),
        ("library", "/api/library?view=cards"),
    ]
    requests.extend(
        ("details", f"/api/library/details?path={urllib.parse.quote(path)}")
        for path in paths
    )
    for kind, suffix in requests:
        started = time.perf_counter()
        with urllib.request.urlopen(f"{base_url.rstrip('/')}{suffix}", timeout=30) as response:
            payload = response.read()
            elapsed = (time.perf_counter() - started) * 1000
            results[kind].append({
                "elapsed_ms": round(elapsed, 3),
                "route_ms": float(response.headers.get("X-CP-Route-MS") or 0),
                "status": response.status,
                "bytes": len(payload),
            })
    for kind in ("health", "library", "details"):
        results[f"{kind}_timing"] = _timing_summary(row["elapsed_ms"] for row in results[kind])
    return results


def build_report(project_root, base_url=""):
    sources = resolve_backup_sources(project_root)
    inventory = _catalog_inventory(sources["catalog_path"])
    paths = inventory["representative_paths"]
    report = {
        "captured_at": time.time(),
        "project_root": str(Path(project_root).resolve()),
        "catalog": inventory,
        "in_process": _route_probe(paths, inventory.get("search_representatives")),
    }
    if base_url:
        report["live_http"] = _live_probe(base_url, paths)
    return report


def main():
    parser = argparse.ArgumentParser(description="Measure bounded catalog reads, SQL query counts, and provider calls.")
    parser.add_argument("--project-root", default=PROJECT_ROOT)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = build_report(args.project_root, args.base_url)
    rendered = json.dumps(report, indent=2)
    if args.output:
        output = Path(args.output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
