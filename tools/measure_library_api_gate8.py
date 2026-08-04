"""Measure the final Gate 8 SQL Movie View path in an isolated catalog."""

import gzip
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app


def _percentile(values, percentile):
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def main():
    if os.environ.get("CP_TEST_MODE") != "1":
        raise RuntimeError("CP_TEST_MODE=1 is required")
    test_root = Path(os.environ["CP_TEST_ROOT"]).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if test_root == temporary or temporary not in test_root.parents:
        raise RuntimeError("CP_TEST_ROOT must be a unique OS-temp child")
    movies = test_root / "movies"
    data = test_root / "user-data"
    movies.mkdir(parents=True, exist_ok=True)
    data.mkdir(parents=True, exist_ok=True)
    for configured_root in app.get_movies_dirs():
        resolved_root = Path(configured_root).resolve()
        if resolved_root != test_root and test_root not in resolved_root.parents:
            raise RuntimeError(f"Configured media root escaped CP_TEST_ROOT: {resolved_root}")

    app._movies_dirs = [str(movies)]
    app._movies_dir = str(movies)
    app._user_data_dir = str(data)
    app._library_cache = {}
    app._stats_cache = {}
    app._maintenance_audit_cache = {"generation": None, "audit": None}
    app._maintenance_upgrade_key_cache = {"generation": None, "paths": set()}
    store = app.AppMetadataStore(data)
    files = {}
    tmdb = {}
    for index in range(1555):
        path = movies / f"Fixture.Movie.{index:04d}.2026.1080p.mkv"
        path.write_bytes(b"isolated fixture")
        key = store._key(path)
        record = {
            "path": str(path), "filename": path.name, "library_root": str(movies),
            "size": path.stat().st_size, "added_time": 10_000 - index,
            "modified_time": 9_000 - index, "resolution": "1080p", "rip_source": "WEB-DL",
            "parsed_title": f"Fixture Movie {index:04d}", "parsed_year": "2026",
        }
        if index < 55:
            tmdb_id = str(920000 + index)
            record.update({
                "identity_status": "accepted", "identity_title": f"Fixture Movie {index:04d}",
                "identity_year": "2026", "identity_source": "isolated_benchmark",
                "metadata_status": "accepted", "metadata_accepted": True,
                "display_provider": "tmdb", "tmdb_id": tmdb_id,
            })
            tmdb[tmdb_id] = {
                "tmdb_id": tmdb_id, "title": f"Fixture Movie {index:04d}", "year": "2026",
                "plot": "Isolated SQL projection benchmark metadata.", "genres": ["Drama"],
                "language": "English", "country": "United States", "country_flag": "US",
                "tmdb_rating": "7.5", "cast": [], "directors": [], "writers": [],
                "certification": "", "keywords": [],
            }
        else:
            record.update({
                "identity_status": "review", "metadata_status": "review",
                "metadata_accepted": False,
            })
        files[key] = record
    store.catalog.replace_document("app_metadata/tmdb_metadata.json", {"movies": tmdb})
    store.catalog.replace_document("app_metadata/files.json", {"files": files})

    repository = store.catalog
    original_connect = repository.store.connect
    statement_sink = []

    def traced_connect():
        connection = original_connect()
        connection.set_trace_callback(statement_sink.append)
        return connection

    repository.store.connect = traced_connect
    route = "/api/library?view=cards&page=1&page_size=40&sort=added"
    client = app.app.test_client()

    filesystem_walks = 0
    isfile_calls = 0
    probe_calls = 0
    provider_calls = 0

    def counted_walk(*args, **kwargs):
        nonlocal filesystem_walks
        filesystem_walks += 1
        return iter(())

    def counted_isfile(*args, **kwargs):
        nonlocal isfile_calls
        isfile_calls += 1
        return False

    def counted_probe(*args, **kwargs):
        nonlocal probe_calls
        probe_calls += 1
        raise AssertionError("Movie View invoked a media probe")

    def counted_provider(*args, **kwargs):
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("Movie View invoked a provider")

    with patch("app.os.walk", side_effect=counted_walk), patch(
        "app.os.path.isfile", side_effect=counted_isfile
    ), patch("app.probe_media_file", side_effect=counted_probe), patch(
        "app.urllib.request.urlopen", side_effect=counted_provider
    ):
        cold_samples = []
        cold_statement_counts = []
        cold_response = None
        for _index in range(10):
            app._library_cache = {}
            app._maintenance_audit_cache = {"generation": None, "audit": None}
            app._maintenance_upgrade_key_cache = {"generation": None, "paths": set()}
            repository.store._library_summary_cache = None
            statement_sink.clear()
            started = time.perf_counter()
            cold_response = client.get(route)
            cold_samples.append((time.perf_counter() - started) * 1000)
            cold_statement_counts.append(len(statement_sink))
        warm_samples = []
        warm_statement_counts = []
        for _index in range(30):
            statement_sink.clear()
            started = time.perf_counter()
            response = client.get(route)
            warm_samples.append((time.perf_counter() - started) * 1000)
            warm_statement_counts.append(len(statement_sink))

    payload = cold_response.get_data()
    gzip_response = client.get(route, headers={"Accept-Encoding": "gzip"})
    gzip_encoded = gzip_response.headers.get("Content-Encoding") == "gzip"
    gzip_roundtrip_valid = (
        gzip.decompress(gzip_response.get_data()) == payload
        if gzip_encoded else gzip_response.get_data() == payload
    )
    result = {
        "isolation": {
            "cp_test_mode": True, "test_root": str(test_root),
            "test_root_is_os_temp_child": True, "catalog": str(repository.database_path),
            "media_root": str(movies), "fixture_files": 1555, "accepted_cards": 55,
        },
        "route": route,
        "cold": {
            "request_count": len(cold_samples),
            "latency_p50_ms": round(statistics.median(cold_samples), 3),
            "latency_p95_ms": round(_percentile(cold_samples, 0.95), 3),
            "latency_max_ms": round(max(cold_samples), 3),
            "sql_statements_min": min(cold_statement_counts),
            "sql_statements_p50": statistics.median(cold_statement_counts),
            "sql_statements_max": max(cold_statement_counts),
        },
        "warm": {
            "request_count": len(warm_samples),
            "latency_p50_ms": round(statistics.median(warm_samples), 3),
            "latency_p95_ms": round(_percentile(warm_samples, 0.95), 3),
            "latency_max_ms": round(max(warm_samples), 3),
            "sql_statements_min": min(warm_statement_counts),
            "sql_statements_p50": statistics.median(warm_statement_counts),
            "sql_statements_max": max(warm_statement_counts),
        },
        "payload_bytes": len(payload),
        "gzip_bytes": len(gzip_response.get_data()),
        "gzip_encoded": gzip_encoded,
        "gzip_roundtrip_valid": gzip_roundtrip_valid,
        "returned_cards": len(cold_response.get_json()["items"]),
        "total_cards": cold_response.get_json()["total"],
        "filesystem_walks": filesystem_walks,
        "isfile_calls": isfile_calls,
        "probe_calls": probe_calls,
        "provider_calls": provider_calls,
    }
    baseline = {"cold_p50": 223.9, "cold_p95": 223.9, "warm_p50": 16.732, "warm_p95": 17.842}
    result["budgets"] = {
        "cold_p50": result["cold"]["latency_p50_ms"] <= baseline["cold_p50"] + max(baseline["cold_p50"] * 0.05, 50),
        "cold_p95": result["cold"]["latency_p95_ms"] <= baseline["cold_p95"] + max(baseline["cold_p95"] * 0.05, 50),
        "warm_p50": result["warm"]["latency_p50_ms"] <= baseline["warm_p50"] + max(baseline["warm_p50"] * 0.05, 50),
        "warm_p95": result["warm"]["latency_p95_ms"] <= baseline["warm_p95"] + max(baseline["warm_p95"] * 0.05, 50),
        "zero_walks": filesystem_walks == 0,
        "zero_isfile": isfile_calls == 0,
        "zero_probe": probe_calls == 0,
        "zero_provider": provider_calls == 0,
        "warm_sql_not_increased": max(warm_statement_counts) <= 13,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
