"""Copied-provider rehearsal for IPTV Movies.

This script never opens the source provider databases in write mode and never
prints provider credentials or raw payloads.
"""

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from services.iptv_movie_store import source_key
from services.iptv_provider_manager import IPTVProviderManager
from services.iptv_tmdb import normalize_tmdb_movie


def _copy_database(source, target):
    source = Path(source).resolve()
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    reader = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    writer = sqlite3.connect(target)
    try:
        reader.execute("PRAGMA query_only=ON")
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()


def _encoded(value):
    if value is None:
        return b"N"
    if isinstance(value, bytes):
        return b"B" + value
    return (type(value).__name__ + ":" + str(value)).encode("utf-8", "surrogatepass")


def _query_digest(connection, query, parameters=()):
    digest = hashlib.sha256()
    for row in connection.execute(query, parameters):
        for value in row:
            digest.update(_encoded(value) + b"\x1f")
        digest.update(b"\x1e")
    return digest.hexdigest()


def _raw_facts(path):
    connection = sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        return {
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "items": dict(connection.execute("SELECT kind,COUNT(*) FROM items GROUP BY kind")),
            "categories": dict(connection.execute("SELECT kind,COUNT(*) FROM categories GROUP BY kind")),
            "details": dict(connection.execute("SELECT kind,COUNT(*) FROM details GROUP BY kind")),
            "list_items": dict(connection.execute("SELECT kind,COUNT(*) FROM iptv_list_items GROUP BY kind")),
            "history": dict(connection.execute("SELECT kind,COUNT(*) FROM watch_history GROUP BY kind")),
            "logical_digest": _query_digest(
                connection,
                """SELECT kind,item_id,category_id,name,position,channel_num,image_url,backdrop_url,
                          container_extension,tmdb_id,year,rating,plot,cast_names,director,genre,
                          duration,epg_channel_id,added,raw_json
                   FROM items ORDER BY kind,item_id""",
            ),
            "nonmovie_digest": hashlib.sha256((
                _query_digest(connection, "SELECT * FROM items WHERE kind<>'movie' ORDER BY kind,item_id")
                + _query_digest(connection, "SELECT * FROM categories WHERE kind<>'movie' ORDER BY kind,category_id")
                + _query_digest(connection, "SELECT * FROM details WHERE kind<>'movie' ORDER BY kind,item_id")
                + _query_digest(connection, "SELECT * FROM iptv_list_items WHERE kind<>'movie' ORDER BY list_id,kind,item_id")
                + _query_digest(connection, "SELECT * FROM watch_history WHERE kind<>'movie' ORDER BY kind,item_id")
            ).encode("ascii")).hexdigest(),
        }
    finally:
        connection.close()


def _snapshot(tmdb_id):
    return normalize_tmdb_movie({
        "id": int(tmdb_id),
        "title": "Copied Provider Isolation Fixture",
        "original_title": "Copied Provider Isolation Fixture",
        "overview": "Disposable copied-provider rehearsal metadata.",
        "release_date": "2024-01-01",
        "runtime": 100,
        "vote_average": 8,
        "vote_count": 1,
        "original_language": "en",
        "genres": [{"id": 18, "name": "Drama"}],
        "spoken_languages": [{"iso_639_1": "en", "english_name": "English"}],
        "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
        "credits": {"crew": [], "cast": []},
        "keywords": {"keywords": []},
        "release_dates": {"results": []},
    })


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Expected the source user-data directory")
    source_user_data = Path(sys.argv[1]).resolve()
    source_iptv = source_user_data / "iptv"
    registry = json.loads((source_iptv / "providers.json").read_text(encoding="utf-8-sig"))
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cp-iptv-movie-rehearsal-") as temporary:
        copied_user_data = Path(temporary) / "user-data"
        copied_iptv = copied_user_data / "iptv"
        copied_iptv.mkdir(parents=True)
        shutil.copy2(source_iptv / "providers.json", copied_iptv / "providers.json")
        source_facts = {}
        for provider in registry.get("providers") or []:
            provider_id = str(provider["provider_id"])
            source_root = source_iptv / "providers" / provider_id
            copied_root = copied_iptv / "providers" / provider_id
            copied_root.mkdir(parents=True)
            shutil.copy2(source_root / "provider.json", copied_root / "provider.json")
            _copy_database(source_root / "iptv.sqlite", copied_root / "iptv.sqlite")
            source_facts[provider_id] = _raw_facts(copied_root / "iptv.sqlite")

        manager = IPTVProviderManager(copied_user_data, migrate_legacy=False)
        results = []
        isolation_keys = []
        try:
            for provider in manager.list_providers()["providers"]:
                provider_id = provider["provider_id"]
                raw_service = manager.service(provider_id)
                movie_service = manager.movie_service(provider_id)
                before = _raw_facts(raw_service.store.database_path)
                page = movie_service.list_movies(page=1, page_size=1)
                after_projection = _raw_facts(raw_service.store.database_path)
                if before != after_projection:
                    raise RuntimeError("Raw copied provider changed during read-only projection")
                status = movie_service.enrichment_status()
                if status["sources"] != before["items"].get("movie", 0):
                    raise RuntimeError("Copied provider movie source count changed during projection")
                with movie_service.store.connection() as connection:
                    projected_memberships = connection.execute(
                        "SELECT COUNT(*) FROM movie_list_memberships"
                    ).fetchone()[0]
                    first_source = connection.execute(
                        "SELECT source_id FROM movie_sources WHERE available=1 ORDER BY position,source_key LIMIT 1"
                    ).fetchone()
                if first_source:
                    key = f"source:{source_key(first_source[0])}"
                    matched_key = movie_service.store.apply_match(key, _snapshot(990001))
                    isolation_keys.append((provider_id, matched_key, str(movie_service.database_path)))
                results.append({
                    "provider_id": provider_id,
                    "name": provider["name"],
                    "raw_movies": before["items"].get("movie", 0),
                    "raw_movie_favorites_and_lists": before["list_items"].get("movie", 0),
                    "raw_movie_history": before["history"].get("movie", 0),
                    "projected_sources": status["sources"],
                    "projected_memberships": int(projected_memberships),
                    "raw_projection_unchanged": before == after_projection,
                })

            if len(isolation_keys) >= 2:
                if isolation_keys[0][1] != isolation_keys[1][1]:
                    raise RuntimeError("Same TMDB fixture did not retain the same provider-local identity")
                if isolation_keys[0][2] == isolation_keys[1][2]:
                    raise RuntimeError("Two providers shared one movie database")

            first_provider = manager.list_providers()["providers"][0]
            raw_service = manager.service(first_provider["provider_id"])
            movie_service = manager.movie_service(first_provider["provider_id"])
            nonmovie_before = _raw_facts(raw_service.store.database_path)["nonmovie_digest"]
            custom = raw_service.create_list("Copied rehearsal movie list")
            candidate = next(
                row for row in movie_service.list_movies(page=1, page_size=100)["items"]
                if row["movie_key"] != "tmdb:990001"
            )
            movie_service.set_list_membership(candidate["movie_key"], custom["list_id"], True)
            matched = movie_service.store.apply_match(candidate["movie_key"], _snapshot(990002), manual=True)
            if movie_service.list_movies({"list_id": custom["list_id"]})["total"] != 1:
                raise RuntimeError("Movie list membership was lost during copied-provider matching")
            movie_service.set_list_membership(matched, custom["list_id"], False)
            nonmovie_after = _raw_facts(raw_service.store.database_path)["nonmovie_digest"]
            if nonmovie_before != nonmovie_after:
                raise RuntimeError("Live TV or Series state changed during copied-provider rehearsal")
        finally:
            manager.close()

        print(json.dumps({
            "providers": results,
            "same_tmdb_id_isolated": len(isolation_keys) >= 2,
            "live_series_unchanged": True,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }, separators=(",", ":")))


if __name__ == "__main__":
    main()
