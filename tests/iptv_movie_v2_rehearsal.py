"""Schema-v2 migration and relationship-repair rehearsal on provider copies.

The source files are copied byte-for-byte and never opened as SQLite databases.
The copied provider databases are not connected to credentials or network owners.
"""

import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.iptv_movie_store import IPTVMovieStore


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def facts(path):
    connection = sqlite3.connect(Path(path))
    connection.row_factory = sqlite3.Row
    try:
        version_row = connection.execute("SELECT value FROM movie_meta WHERE key='schema_version'").fetchone()
        matches = connection.execute(
            """SELECT source_key,state,tmdb_id,method,confidence,manual_lock,evidence_json,
                      error_code,error_message,updated_at FROM source_matches ORDER BY source_key"""
        ).fetchall()
        durable_digest = hashlib.sha256()
        for row in matches:
            durable_digest.update(json.dumps(list(row), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        return {
            "schema_version": int(version_row[0]) if version_row else 0,
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "sources": connection.execute("SELECT COUNT(*) FROM movie_sources").fetchone()[0],
            "accepted": connection.execute("SELECT COUNT(*) FROM source_matches WHERE state IN ('matched-auto','matched-manual') AND tmdb_id IS NOT NULL").fetchone()[0],
            "manual_locks": connection.execute("SELECT COUNT(*) FROM source_matches WHERE manual_lock=1").fetchone()[0],
            "snapshots": connection.execute("SELECT COUNT(*) FROM tmdb_movies").fetchone()[0],
            "memberships": connection.execute("SELECT COUNT(*) FROM movie_list_memberships").fetchone()[0],
            "queue_done": connection.execute("SELECT COUNT(*) FROM enrichment_queue WHERE status='done'").fetchone()[0],
            "durable_match_digest": durable_digest.hexdigest(),
        }
    finally:
        connection.close()


def raw_continuity(path):
    connection = sqlite3.connect(Path(path))
    try:
        return {
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "movie_list_items": connection.execute("SELECT COUNT(*) FROM iptv_list_items WHERE kind='movie'").fetchone()[0],
            "movie_history": connection.execute("SELECT COUNT(*) FROM watch_history WHERE kind='movie'").fetchone()[0],
            "nonmovie_items": connection.execute("SELECT COUNT(*) FROM items WHERE kind<>'movie'").fetchone()[0],
        }
    finally:
        connection.close()


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Expected the source user-data directory")
    source_user_data = Path(sys.argv[1]).resolve()
    source_iptv = source_user_data / "iptv"
    registry = json.loads((source_iptv / "providers.json").read_text(encoding="utf-8-sig"))
    reports = []
    with tempfile.TemporaryDirectory(prefix="cp-iptv-v2-rehearsal-") as temporary:
        disposable = Path(temporary)
        for provider in registry.get("providers") or []:
            provider_id = str(provider["provider_id"])
            source_root = source_iptv / "providers" / provider_id
            copy_root = disposable / provider_id
            copy_root.mkdir()
            source_movies = source_root / "movies.sqlite"
            source_raw = source_root / "iptv.sqlite"
            copied_movies = copy_root / "movies.sqlite"
            copied_raw = copy_root / "iptv.sqlite"
            shutil.copy2(source_movies, copied_movies)
            shutil.copy2(source_raw, copied_raw)
            if file_hash(source_movies) != file_hash(copied_movies) or file_hash(source_raw) != file_hash(copied_raw):
                raise RuntimeError("Provider copy hash verification failed")

            before = facts(copied_movies)
            raw_before = raw_continuity(copied_raw)
            store = IPTVMovieStore(copy_root, provider_id)
            after = facts(copied_movies)
            raw_after = raw_continuity(copied_raw)
            if after["schema_version"] != 2 or after["integrity"] != "ok":
                raise RuntimeError("Disposable provider migration failed")
            for key in ("sources", "accepted", "manual_locks", "snapshots", "memberships", "queue_done", "durable_match_digest"):
                if before[key] != after[key]:
                    raise RuntimeError(f"Durable provider fact changed during migration: {key}")
            if raw_before != raw_after:
                raise RuntimeError("Raw provider continuity changed during movie migration")
            backup = Path(store.migration_report()["backup"])
            if not backup.is_file():
                raise RuntimeError("Provider-local migration backup is missing")
            store.rollback_migration()
            rolled_back = facts(copied_movies)
            if rolled_back != before:
                raise RuntimeError("Provider-local rollback did not restore the schema-v1 copy")
            reports.append({
                "provider_id": provider_id,
                "name": str(provider.get("name") or ""),
                "before": before,
                "after": after,
                "rollback_exact": True,
                "raw_continuity": raw_after,
                "network_calls": 0,
            })
    print(json.dumps({"providers": reports, "network_calls": 0}, separators=(",", ":")))


if __name__ == "__main__":
    main()
