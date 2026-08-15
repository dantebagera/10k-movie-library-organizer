import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from services.canonical_catalog import (
    CANONICAL_CONTRACT_VERSION,
    CanonicalCatalog,
    normalize_keyword_name,
)
from services.movie_identity import normalize_movie_title, ownership_keys
from services.media_file_facts import (
    FILE_FACTS_VERSION,
    QUALITY_CLASSIFIER_VERSION,
    quality_display,
)
from services.smart_match import parse_release_filename


CATALOG_SCHEMA_VERSION = 10

PLAYBACK_HISTORY_COLUMNS = [
    "path_key", "movie_key", "position_ms", "duration_ms", "last_played_at",
    "completed_at", "audio_track_fingerprint", "subtitle_track_fingerprint",
    "subtitle_delay_ms", "revision",
]

MEDIA_FILE_V8_COLUMNS = [
    "path_key", "path", "filename", "library_root", "size", "added_time",
    "modified_time", "resolution", "rip_source", "parsed_title", "parsed_year",
    "identity_status", "identity_title", "identity_year", "identity_source",
    "identity_revision", "identity_decision_version",
    "identity_evidence_fingerprint", "tmdb_id", "imdb_id", "plex_guid",
    "plex_rating_key", "display_provider", "metadata_status", "metadata_source",
    "metadata_accepted", "enrichment_status", "ingest_status", "manual_lock",
    "manual_locked", "raw_json",
]

MEDIA_FILE_FACT_COLUMNS = [
    "video_width", "video_height", "video_codec", "video_profile",
    "video_bit_depth", "video_bitrate", "video_frame_rate", "duration_ms",
    "display_aspect_ratio", "rotation_degrees", "audio_codec",
    "audio_channels", "audio_bitrate", "filename_quality_claim",
    "quality_class", "quality_source", "quality_conflict",
    "quality_nonstandard", "file_facts_version", "classifier_version",
    "probe_status", "probed_at", "probe_error", "probe_size",
    "probe_modified_time",
]

MEDIA_FILE_MEASUREMENT_COLUMNS = [
    "video_width", "video_height", "video_codec", "video_profile",
    "video_bit_depth", "video_bitrate", "video_frame_rate", "duration_ms",
    "display_aspect_ratio", "rotation_degrees", "audio_codec",
    "audio_channels", "audio_bitrate", "filename_quality_claim",
    "quality_class", "quality_conflict", "quality_nonstandard",
    "file_facts_version", "classifier_version",
]

MEDIA_FILE_V9_COLUMNS = MEDIA_FILE_V8_COLUMNS + MEDIA_FILE_FACT_COLUMNS


class CatalogError(RuntimeError):
    pass


def _json_text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _text(value):
    return str(value or "").strip()


def _bool(value):
    return 1 if bool(value) else 0


def _keyword_prefix_bounds(value):
    normalized = normalize_keyword_name(value)
    return normalized, f"{normalized}{chr(0x10FFFF)}"


def _execute_schema(connection, script):
    statement = ""
    for line in str(script or "").splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise CatalogError("Incomplete catalogue schema statement")


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _catalog_sort_key(value):
    """Mirror the browser's localeCompare ordering used by Library title sorts."""
    decomposed = unicodedata.normalize("NFKD", _text(value)).casefold()
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    punctuation = {
        "_": 2, "-": 3, ",": 4, ";": 5, ":": 6, "!": 7, "¡": 8,
        "?": 9, ".": 10, "'": 11, '"': 12, "(": 13, "[": 14,
        "@": 15, "*": 16, "/": 17, "&": 18, "#": 19, "+": 20,
    }
    key = []
    for char in without_marks:
        if char.isspace():
            key.append(chr(1))
        elif char in punctuation:
            key.append(chr(punctuation[char]))
        elif char.isdigit():
            key.append(chr(30 + int(char)))
        elif "a" <= char <= "z":
            key.append(chr(100 + ord(char) - ord("a")))
        elif char.isalnum():
            key.append(chr(200) + char)
        else:
            key.append(chr(20) + char)
    return "".join(key)


def _identity_key(movie):
    movie = movie or {}
    if _text(movie.get("tmdb_id")):
        return f"tmdb:{_text(movie.get('tmdb_id'))}"
    if _text(movie.get("imdb_id")):
        return f"imdb:{_text(movie.get('imdb_id')).lower()}"
    if _text(movie.get("plex_guid")):
        return f"plex:{_text(movie.get('plex_guid')).lower()}"
    if _text(movie.get("path")):
        return f"path:{_text(movie.get('path')).lower()}"
    title = normalize_movie_title(movie.get("title"))
    year = _text(movie.get("year"))
    return f"title:{title}|{year}" if title and year else ""


class CatalogStore:
    def __init__(self, database_path):
        self.database_path = Path(database_path).resolve()
        self.canonical = CanonicalCatalog()
        self._library_summary_cache = None
        self.last_migration_report = None

    def connect(self):
        if str(os.environ.get("CP_TEST_MODE", "") or "").strip() == "1":
            temporary_root = Path(tempfile.gettempdir()).resolve()
            if self.database_path != temporary_root and temporary_root not in self.database_path.parents:
                raise CatalogError(
                    "Test-mode catalogue access is restricted to the operating-system temporary directory: "
                    f"{self.database_path}"
                )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.create_function("cp_sort_key", 1, _catalog_sort_key, deterministic=True)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _catalog_schema_version(connection):
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        if not tables:
            return None
        if "catalog_meta" not in tables:
            raise CatalogError("Catalogue schema is partial: catalog_meta is missing")
        row = connection.execute(
            "SELECT value FROM catalog_meta WHERE key='schema_version'"
        ).fetchone()
        if not row:
            raise CatalogError("Catalogue schema is partial: schema_version is missing")
        try:
            return int(row[0])
        except (TypeError, ValueError) as error:
            raise CatalogError(f"Invalid catalogue schema version: {row[0]!r}") from error

    @staticmethod
    def _table_columns(connection, table):
        return [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]

    @staticmethod
    def _logical_digest(connection, table, columns, where="", parameters=()):
        encoded_columns = ", ".join(columns)
        query = f"SELECT {encoded_columns} FROM {table}"
        if where:
            query += f" WHERE {where}"
        query += " ORDER BY " + ", ".join(columns)
        digest = hashlib.sha256()
        count = 0
        for row in connection.execute(query, parameters):
            digest.update(_json_text(list(row)).encode("utf-8"))
            digest.update(b"\n")
            count += 1
        return {"rows": count, "sha256": digest.hexdigest()}

    @staticmethod
    def _migration_checkpoint(name):
        del name

    def _validate_v7_migration_source(self, connection):
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise CatalogError("Version 7 catalogue failed integrity validation")
        approved_column_orders = {
            (
                "snapshot_key", "credit_type", "position", "person_key",
                "credited_name", "character", "profile_url",
            ),
            (
                "snapshot_key", "credit_type", "position", "person_key",
                "character", "profile_url", "credited_name",
            ),
        }
        if tuple(self._table_columns(connection, "movie_credits")) not in approved_column_orders:
            raise CatalogError("Version 7 movie_credits schema does not match the approved source")
        partial_objects = {
            row[0]
            for row in connection.execute("""
                SELECT name FROM sqlite_master
                WHERE name IN (
                    'movie_credits_v8_new', 'keywords', 'movie_keywords',
                    'idx_keywords_tmdb', 'idx_keywords_normalized_name',
                    'idx_movie_keywords_keyword'
                )
            """).fetchall()
        }
        if partial_objects:
            raise CatalogError(
                "Version 7 catalogue contains partial version 8 objects: "
                + ", ".join(sorted(partial_objects))
            )
        invalid_credit = connection.execute("""
            SELECT credit_type FROM movie_credits
            WHERE credit_type NOT IN ('cast', 'director')
            LIMIT 1
        """).fetchone()
        if invalid_credit:
            raise CatalogError(f"Version 7 contains unsupported credit type: {invalid_credit[0]}")

    def _validate_v8_schema(self, connection, *, require_version=True):
        if require_version and self._catalog_schema_version(connection) != 8:
            raise CatalogError("Catalogue schema version is not 8")
        media_columns = self._table_columns(connection, "media_files")
        if media_columns != MEDIA_FILE_V8_COLUMNS:
            partial = sorted(set(media_columns) & set(MEDIA_FILE_FACT_COLUMNS))
            detail = f": {', '.join(partial)}" if partial else ""
            raise CatalogError(
                "Version 8 media_files schema does not match the approved source"
                + detail
            )
        expected_credit_columns = [
            "snapshot_key", "credit_type", "position", "person_key",
            "credited_name", "character", "profile_url", "job",
        ]
        if self._table_columns(connection, "movie_credits") != expected_credit_columns:
            raise CatalogError("Version 8 movie_credits schema is incomplete")
        if self._table_columns(connection, "keywords") != [
            "keyword_key", "tmdb_id", "name", "normalized_name",
        ]:
            raise CatalogError("Version 8 keywords schema is incomplete")
        if self._table_columns(connection, "movie_keywords") != [
            "snapshot_key", "position", "keyword_key",
        ]:
            raise CatalogError("Version 8 movie_keywords schema is incomplete")
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='movie_credits'"
        ).fetchone()
        if not table_sql or "'writer'" not in str(table_sql[0] or "").lower():
            raise CatalogError("Version 8 movie_credits constraint does not allow writers")
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        required_indexes = {
            "idx_media_files_quality",
            "idx_movie_credits_person",
            "idx_keywords_tmdb",
            "idx_keywords_normalized_name",
            "idx_movie_keywords_keyword",
        }
        if not required_indexes.issubset(indexes):
            raise CatalogError(
                "Version 8 search indexes are incomplete: "
                + ", ".join(sorted(required_indexes - indexes))
            )
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='movie_credits_v8_new'"
        ).fetchone():
            raise CatalogError("Version 8 catalogue contains a partial movie_credits table")
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='idx_media_files_facts_stale'"
        ).fetchone():
            raise CatalogError("Version 8 catalogue contains a partial file-facts index")

    def _validate_v9_schema(self, connection, *, require_version=True):
        if require_version and self._catalog_schema_version(connection) != 9:
            raise CatalogError("Catalogue schema version is not 9")
        if self._table_columns(connection, "media_files") != MEDIA_FILE_V9_COLUMNS:
            raise CatalogError("Version 9 media_files schema is incomplete")
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        required = {"idx_media_files_quality", "idx_media_files_facts_stale"}
        if not required.issubset(indexes):
            raise CatalogError(
                "Version 9 file-facts indexes are incomplete: "
                + ", ".join(sorted(required - indexes))
            )
        self._validate_v8_schema_relations(connection)

    def _validate_v10_schema(self, connection, *, require_version=True):
        if require_version and self._catalog_schema_version(connection) != 10:
            raise CatalogError("Catalogue schema version is not 10")
        self._validate_v9_schema(connection, require_version=False)
        if self._table_columns(connection, "playback_history") != PLAYBACK_HISTORY_COLUMNS:
            raise CatalogError("Version 10 playback history schema is incomplete")
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        required = {
            "idx_playback_history_movie",
            "idx_playback_history_recent",
        }
        if not required.issubset(indexes):
            raise CatalogError(
                "Version 10 playback history indexes are incomplete: "
                + ", ".join(sorted(required - indexes))
            )

    def _validate_v8_schema_relations(self, connection):
        expected_credit_columns = [
            "snapshot_key", "credit_type", "position", "person_key",
            "credited_name", "character", "profile_url", "job",
        ]
        if self._table_columns(connection, "movie_credits") != expected_credit_columns:
            raise CatalogError("Version 8 movie_credits schema is incomplete")
        if self._table_columns(connection, "keywords") != [
            "keyword_key", "tmdb_id", "name", "normalized_name",
        ]:
            raise CatalogError("Version 8 keywords schema is incomplete")
        if self._table_columns(connection, "movie_keywords") != [
            "snapshot_key", "position", "keyword_key",
        ]:
            raise CatalogError("Version 8 movie_keywords schema is incomplete")
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='movie_credits'"
        ).fetchone()
        if not table_sql or "'writer'" not in str(table_sql[0] or "").lower():
            raise CatalogError("Version 8 movie_credits constraint does not allow writers")
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        required_indexes = {
            "idx_movie_credits_person",
            "idx_keywords_tmdb",
            "idx_keywords_normalized_name",
            "idx_movie_keywords_keyword",
        }
        if not required_indexes.issubset(indexes):
            raise CatalogError(
                "Version 8 search indexes are incomplete: "
                + ", ".join(sorted(required_indexes - indexes))
            )
        if connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='movie_credits_v8_new'"
        ).fetchone():
            raise CatalogError("Version 8 catalogue contains a partial movie_credits table")

    def _migrate_v8_to_v9(self, connection):
        if self._catalog_schema_version(connection) != 8:
            raise CatalogError("Version 8 to 9 migration received the wrong source version")
        self._validate_v8_schema(connection)
        before = self._logical_digest(connection, "media_files", MEDIA_FILE_V8_COLUMNS)
        self._migration_checkpoint("before_v9_schema_changes")
        additions = (
            ("video_width", "INTEGER NOT NULL DEFAULT 0"),
            ("video_height", "INTEGER NOT NULL DEFAULT 0"),
            ("video_codec", "TEXT NOT NULL DEFAULT ''"),
            ("video_profile", "TEXT NOT NULL DEFAULT ''"),
            ("video_bit_depth", "INTEGER NOT NULL DEFAULT 0"),
            ("video_bitrate", "INTEGER NOT NULL DEFAULT 0"),
            ("video_frame_rate", "REAL NOT NULL DEFAULT 0"),
            ("duration_ms", "INTEGER NOT NULL DEFAULT 0"),
            ("display_aspect_ratio", "REAL NOT NULL DEFAULT 0"),
            ("rotation_degrees", "REAL NOT NULL DEFAULT 0"),
            ("audio_codec", "TEXT NOT NULL DEFAULT ''"),
            ("audio_channels", "REAL NOT NULL DEFAULT 0"),
            ("audio_bitrate", "INTEGER NOT NULL DEFAULT 0"),
            ("filename_quality_claim", "TEXT NOT NULL DEFAULT ''"),
            ("quality_class", "TEXT NOT NULL DEFAULT ''"),
            ("quality_source", "TEXT NOT NULL DEFAULT 'legacy_unprobed'"),
            ("quality_conflict", "INTEGER NOT NULL DEFAULT 0"),
            ("quality_nonstandard", "INTEGER NOT NULL DEFAULT 0"),
            ("file_facts_version", "INTEGER NOT NULL DEFAULT 0"),
            ("classifier_version", "INTEGER NOT NULL DEFAULT 0"),
            ("probe_status", "TEXT NOT NULL DEFAULT 'unprobed'"),
            ("probed_at", "REAL NOT NULL DEFAULT 0"),
            ("probe_error", "TEXT NOT NULL DEFAULT ''"),
            ("probe_size", "INTEGER NOT NULL DEFAULT 0"),
            ("probe_modified_time", "REAL NOT NULL DEFAULT 0"),
        )
        for index, (column, definition) in enumerate(additions):
            connection.execute(
                f'ALTER TABLE media_files ADD COLUMN "{column}" {definition}'
            )
            if index == 0:
                self._migration_checkpoint("during_v9_column_creation")
        self._migration_checkpoint("before_v9_index_creation")
        connection.execute("DROP INDEX idx_media_files_quality")
        connection.execute(
            "CREATE INDEX idx_media_files_quality "
            "ON media_files(quality_class, resolution, rip_source)"
        )
        connection.execute(
            "CREATE INDEX idx_media_files_facts_stale "
            "ON media_files(probe_status, file_facts_version, classifier_version, path_key)"
        )
        self._migration_checkpoint("before_v9_schema_version_update")
        connection.execute(
            "UPDATE catalog_meta SET value='9' WHERE key='schema_version'"
        )
        self._migration_checkpoint("during_v9_final_validation")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise CatalogError(
                f"Version 9 final integrity failed: integrity={integrity}, "
                f"foreign_keys={len(foreign_keys)}"
            )
        self._validate_v9_schema(connection)
        after = self._logical_digest(connection, "media_files", MEDIA_FILE_V8_COLUMNS)
        if after != before:
            raise CatalogError("Version 9 migration changed pre-existing media file data")
        return {
            "from_version": 8,
            "to_version": 9,
            "media_files_digest_before": before,
            "media_files_digest_after": after,
            "unprobed_rows": int(connection.execute(
                "SELECT COUNT(*) FROM media_files WHERE probe_status='unprobed'"
            ).fetchone()[0]),
            "integrity_check": integrity,
            "foreign_key_violations": len(foreign_keys),
        }

    def _migrate_v9_to_v10(self, connection):
        if self._catalog_schema_version(connection) != 9:
            raise CatalogError("Version 9 to 10 migration received the wrong source version")
        self._validate_v9_schema(connection)
        before = self._logical_digest(connection, "media_files", MEDIA_FILE_V9_COLUMNS)
        self._migration_checkpoint("before_v10_playback_history")
        # This table intentionally has no media_files foreign key. The repository's
        # full-document refresh replaces media rows in place, while playback history
        # must survive for path keys that remain present. Repository path mutations
        # explicitly migrate or remove history in the same transaction.
        _execute_schema(connection, """
            CREATE TABLE playback_history (
                path_key TEXT PRIMARY KEY,
                movie_key TEXT,
                position_ms INTEGER NOT NULL DEFAULT 0 CHECK(position_ms >= 0),
                duration_ms INTEGER NOT NULL DEFAULT 0 CHECK(duration_ms >= 0),
                last_played_at REAL NOT NULL DEFAULT 0 CHECK(last_played_at >= 0),
                completed_at REAL,
                audio_track_fingerprint TEXT,
                subtitle_track_fingerprint TEXT,
                subtitle_delay_ms INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
            );
            CREATE INDEX idx_playback_history_movie
                ON playback_history(movie_key, last_played_at DESC);
            CREATE INDEX idx_playback_history_recent
                ON playback_history(last_played_at DESC, path_key);
        """)
        self._migration_checkpoint("before_v10_schema_version_update")
        connection.execute(
            "UPDATE catalog_meta SET value='10' WHERE key='schema_version'"
        )
        self._migration_checkpoint("during_v10_final_validation")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise CatalogError(
                f"Version 10 final integrity failed: integrity={integrity}, "
                f"foreign_keys={len(foreign_keys)}"
            )
        self._validate_v10_schema(connection)
        after = self._logical_digest(connection, "media_files", MEDIA_FILE_V9_COLUMNS)
        if after != before:
            raise CatalogError("Version 10 migration changed pre-existing media file data")
        return {
            "from_version": 9,
            "to_version": 10,
            "media_files_digest_before": before,
            "media_files_digest_after": after,
            "playback_history_rows": 0,
            "integrity_check": integrity,
            "foreign_key_violations": len(foreign_keys),
        }

    def _migrate_v6_to_v7(self, connection):
        if self._catalog_schema_version(connection) != 6:
            raise CatalogError("Version 6 to 7 migration received the wrong source version")
        self.canonical.upgrade_v6_additive_columns(connection)
        self._initialize_asset_schema(connection)
        connection.execute(
            "UPDATE catalog_meta SET value='7' WHERE key='schema_version'"
        )

    def _migrate_v7_to_v8(self, connection):
        if self._catalog_schema_version(connection) != 7:
            raise CatalogError("Version 7 to 8 migration received the wrong source version")
        self._validate_v7_migration_source(connection)
        source_columns = [
            "snapshot_key", "credit_type", "position", "person_key",
            "credited_name", "character", "profile_url",
        ]
        before = self._logical_digest(connection, "movie_credits", source_columns)
        self._migration_checkpoint("before_table_creation")
        self.canonical.create_movie_credits_v8(
            connection,
            "movie_credits_v8_new",
            if_not_exists=False,
        )
        self.canonical.create_keyword_schema(connection, if_not_exists=False)
        connection.execute("""
            INSERT INTO movie_credits_v8_new(
                snapshot_key, credit_type, position, person_key,
                credited_name, character, profile_url, job
            )
            SELECT snapshot_key, credit_type, position, person_key,
                   credited_name, character, profile_url, ''
            FROM movie_credits
            ORDER BY snapshot_key, credit_type, position
        """)
        self._migration_checkpoint("during_existing_credit_copy")
        copied = self._logical_digest(
            connection,
            "movie_credits_v8_new",
            source_columns,
            "credit_type IN ('cast', 'director')",
        )
        if copied != before:
            raise CatalogError(
                f"Version 8 credit copy mismatch: source={before}, copied={copied}"
            )

        relation_report = self.canonical.backfill_search_relations(
            connection,
            "movie_credits_v8_new",
            checkpoint=self._migration_checkpoint,
        )
        copied_after_backfill = self._logical_digest(
            connection,
            "movie_credits_v8_new",
            source_columns,
            "credit_type IN ('cast', 'director')",
        )
        if copied_after_backfill != before:
            raise CatalogError("Writer backfill changed existing cast/director credits")

        connection.execute("DROP TABLE movie_credits")
        connection.execute("ALTER TABLE movie_credits_v8_new RENAME TO movie_credits")
        self._migration_checkpoint("before_index_creation")
        self.canonical.create_search_indexes(connection, if_not_exists=False)
        self._migration_checkpoint("before_schema_version_update")
        connection.execute(
            "UPDATE catalog_meta SET value='8' WHERE key='schema_version'"
        )
        self._migration_checkpoint("during_final_validation")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise CatalogError(
                f"Version 8 final integrity failed: integrity={integrity}, foreign_keys={len(foreign_keys)}"
            )
        self._validate_v8_schema(connection)
        after = self._logical_digest(
            connection,
            "movie_credits",
            source_columns,
            "credit_type IN ('cast', 'director')",
        )
        if after != before:
            raise CatalogError("Version 8 final credit digest does not match version 7")
        return {
            "from_version": 7,
            "to_version": 8,
            "existing_credit_digest_before": before,
            "existing_credit_digest_after": after,
            **relation_report,
            "people": int(connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]),
            "credits": int(connection.execute("SELECT COUNT(*) FROM movie_credits").fetchone()[0]),
            "writer_credits": int(connection.execute(
                "SELECT COUNT(*) FROM movie_credits WHERE credit_type='writer'"
            ).fetchone()[0]),
            "keywords": int(connection.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]),
            "movie_keywords": int(connection.execute("SELECT COUNT(*) FROM movie_keywords").fetchone()[0]),
            "integrity_check": integrity,
            "foreign_key_violations": len(foreign_keys),
        }

    def initialize(self):
        self.last_migration_report = None
        migration_reports = []
        with self.transaction() as connection:
            starting_schema = self._catalog_schema_version(connection)
            if starting_schema is not None:
                if starting_schema == 6:
                    self._migrate_v6_to_v7(connection)
                    starting_schema = 7
                if starting_schema == 7:
                    migration_reports.append(self._migrate_v7_to_v8(connection))
                    starting_schema = 8
                if starting_schema == 8:
                    migration_reports.append(self._migrate_v8_to_v9(connection))
                    starting_schema = 9
                if starting_schema == 9:
                    migration_reports.append(self._migrate_v9_to_v10(connection))
                    starting_schema = 10
                elif starting_schema != 10:
                    raise CatalogError(
                        f"Unsupported catalogue schema version {starting_schema}; "
                        "expected 6, 7, 8, 9, or 10"
                    )
                self._validate_v10_schema(connection)

            _execute_schema(connection, """
                CREATE TABLE IF NOT EXISTS catalog_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS source_documents (
                    name TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS media_files (
                    path_key TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    filename TEXT NOT NULL DEFAULT '',
                    library_root TEXT NOT NULL DEFAULT '',
                    size INTEGER NOT NULL DEFAULT 0,
                    added_time REAL NOT NULL DEFAULT 0,
                    modified_time REAL NOT NULL DEFAULT 0,
                    resolution TEXT NOT NULL DEFAULT '',
                    rip_source TEXT NOT NULL DEFAULT '',
                    parsed_title TEXT NOT NULL DEFAULT '',
                    parsed_year TEXT NOT NULL DEFAULT '',
                    identity_status TEXT NOT NULL DEFAULT '',
                    identity_title TEXT NOT NULL DEFAULT '',
                    identity_year TEXT NOT NULL DEFAULT '',
                    identity_source TEXT NOT NULL DEFAULT '',
                    identity_revision INTEGER NOT NULL DEFAULT 0,
                    identity_decision_version INTEGER NOT NULL DEFAULT 0,
                    identity_evidence_fingerprint TEXT NOT NULL DEFAULT '',
                    tmdb_id TEXT NOT NULL DEFAULT '',
                    imdb_id TEXT NOT NULL DEFAULT '',
                    plex_guid TEXT NOT NULL DEFAULT '',
                    plex_rating_key TEXT NOT NULL DEFAULT '',
                    display_provider TEXT NOT NULL DEFAULT '',
                    metadata_status TEXT NOT NULL DEFAULT '',
                    metadata_source TEXT NOT NULL DEFAULT '',
                    metadata_accepted INTEGER NOT NULL DEFAULT 0,
                    enrichment_status TEXT NOT NULL DEFAULT '',
                    ingest_status TEXT NOT NULL DEFAULT '',
                    manual_lock INTEGER NOT NULL DEFAULT 0,
                    manual_locked INTEGER NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL,
                    video_width INTEGER NOT NULL DEFAULT 0,
                    video_height INTEGER NOT NULL DEFAULT 0,
                    video_codec TEXT NOT NULL DEFAULT '',
                    video_profile TEXT NOT NULL DEFAULT '',
                    video_bit_depth INTEGER NOT NULL DEFAULT 0,
                    video_bitrate INTEGER NOT NULL DEFAULT 0,
                    video_frame_rate REAL NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    display_aspect_ratio REAL NOT NULL DEFAULT 0,
                    rotation_degrees REAL NOT NULL DEFAULT 0,
                    audio_codec TEXT NOT NULL DEFAULT '',
                    audio_channels REAL NOT NULL DEFAULT 0,
                    audio_bitrate INTEGER NOT NULL DEFAULT 0,
                    filename_quality_claim TEXT NOT NULL DEFAULT '',
                    quality_class TEXT NOT NULL DEFAULT '',
                    quality_source TEXT NOT NULL DEFAULT 'legacy_unprobed',
                    quality_conflict INTEGER NOT NULL DEFAULT 0,
                    quality_nonstandard INTEGER NOT NULL DEFAULT 0,
                    file_facts_version INTEGER NOT NULL DEFAULT 0,
                    classifier_version INTEGER NOT NULL DEFAULT 0,
                    probe_status TEXT NOT NULL DEFAULT 'unprobed',
                    probed_at REAL NOT NULL DEFAULT 0,
                    probe_error TEXT NOT NULL DEFAULT '',
                    probe_size INTEGER NOT NULL DEFAULT 0,
                    probe_modified_time REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS media_identity_keys (
                    path_key TEXT NOT NULL,
                    identity_key TEXT NOT NULL,
                    key_source TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (path_key, identity_key),
                    FOREIGN KEY (path_key) REFERENCES media_files(path_key) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS tmdb_movies (
                    tmdb_id TEXT PRIMARY KEY,
                    imdb_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    year TEXT NOT NULL DEFAULT '',
                    poster_url TEXT NOT NULL DEFAULT '',
                    release_date TEXT NOT NULL DEFAULT '',
                    adult INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS plex_files (
                    path_key TEXT PRIMARY KEY,
                    path TEXT NOT NULL DEFAULT '',
                    plex_title TEXT NOT NULL DEFAULT '',
                    plex_year TEXT NOT NULL DEFAULT '',
                    tmdb_id TEXT NOT NULL DEFAULT '',
                    imdb_id TEXT NOT NULL DEFAULT '',
                    plex_guid TEXT NOT NULL DEFAULT '',
                    rating_key TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS manual_matches (
                    path_key TEXT PRIMARY KEY,
                    path TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    tmdb_id TEXT NOT NULL DEFAULT '',
                    imdb_id TEXT NOT NULL DEFAULT '',
                    plex_guid TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    year TEXT NOT NULL DEFAULT '',
                    accepted INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS identity_audit_fingerprints (
                    path_key TEXT PRIMARY KEY,
                    path TEXT NOT NULL DEFAULT '',
                    provider TEXT NOT NULL DEFAULT '',
                    provider_id TEXT NOT NULL DEFAULT '',
                    rule_version INTEGER NOT NULL DEFAULT 0,
                    verified_at REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_lists (
                    list_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    system_type TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS list_items (
                    list_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    identity_key TEXT NOT NULL DEFAULT '',
                    tmdb_id TEXT NOT NULL DEFAULT '',
                    imdb_id TEXT NOT NULL DEFAULT '',
                    path TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    year TEXT NOT NULL DEFAULT '',
                    poster_url TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL,
                    PRIMARY KEY (list_id, position),
                    FOREIGN KEY (list_id) REFERENCES user_lists(list_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS collection_overrides (
                    collection_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS followed_releases (
                    position INTEGER PRIMARY KEY,
                    identity_key TEXT NOT NULL DEFAULT '',
                    tmdb_id TEXT NOT NULL DEFAULT '',
                    imdb_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    year TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playback_history (
                    path_key TEXT PRIMARY KEY,
                    movie_key TEXT,
                    position_ms INTEGER NOT NULL DEFAULT 0 CHECK(position_ms >= 0),
                    duration_ms INTEGER NOT NULL DEFAULT 0 CHECK(duration_ms >= 0),
                    last_played_at REAL NOT NULL DEFAULT 0 CHECK(last_played_at >= 0),
                    completed_at REAL,
                    audio_track_fingerprint TEXT,
                    subtitle_track_fingerprint TEXT,
                    subtitle_delay_ms INTEGER NOT NULL DEFAULT 0,
                    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0)
                );

                CREATE INDEX IF NOT EXISTS idx_media_files_tmdb_id ON media_files(tmdb_id);
                CREATE INDEX IF NOT EXISTS idx_media_files_imdb_id ON media_files(imdb_id);
                CREATE INDEX IF NOT EXISTS idx_media_files_plex_guid ON media_files(plex_guid);
                CREATE INDEX IF NOT EXISTS idx_media_files_title_year ON media_files(identity_title, identity_year);
                CREATE INDEX IF NOT EXISTS idx_media_files_status ON media_files(identity_status, metadata_status);
                CREATE INDEX IF NOT EXISTS idx_media_files_quality ON media_files(quality_class, resolution, rip_source);
                CREATE INDEX IF NOT EXISTS idx_media_files_facts_stale
                    ON media_files(probe_status, file_facts_version, classifier_version, path_key);
                CREATE INDEX IF NOT EXISTS idx_media_files_added ON media_files(added_time DESC);
                CREATE INDEX IF NOT EXISTS idx_media_identity_key ON media_identity_keys(identity_key);
                CREATE INDEX IF NOT EXISTS idx_list_items_identity ON list_items(identity_key);
                CREATE INDEX IF NOT EXISTS idx_list_items_tmdb ON list_items(tmdb_id);
                CREATE INDEX IF NOT EXISTS idx_followed_identity ON followed_releases(identity_key);
                CREATE INDEX IF NOT EXISTS idx_playback_history_movie
                    ON playback_history(movie_key, last_played_at DESC);
                CREATE INDEX IF NOT EXISTS idx_playback_history_recent
                    ON playback_history(last_played_at DESC, path_key);
            """)
            connection.execute("DROP TABLE IF EXISTS download_jobs")
            if not connection.execute(
                "SELECT 1 FROM identity_audit_fingerprints LIMIT 1"
            ).fetchone():
                source = connection.execute(
                    "SELECT payload_json FROM source_documents WHERE name = ?",
                    ("app_metadata/identity_audit_fingerprints.json",),
                ).fetchone()
                if source:
                    try:
                        self._import_identity_audit_fingerprints(
                            connection,
                            json.loads(source[0]),
                        )
                    except ValueError:
                        pass
            previous_schema = connection.execute(
                "SELECT value FROM catalog_meta WHERE key='schema_version'"
            ).fetchone()
            self.canonical.initialize(connection)
            self._initialize_asset_schema(connection)
            media_generation = connection.execute(
                "SELECT value FROM catalog_meta WHERE key='media_generation'"
            ).fetchone()
            canonical_generation = connection.execute(
                "SELECT value FROM catalog_meta WHERE key='canonical_media_generation'"
            ).fetchone()
            canonical_contract = connection.execute(
                "SELECT value FROM catalog_meta WHERE key='canonical_contract_version'"
            ).fetchone()
            canonical_rows = int(connection.execute(
                "SELECT COUNT(*) FROM canonical_movie_files"
            ).fetchone()[0])
            accepted_rows = int(connection.execute(
                "SELECT COUNT(*) FROM media_files WHERE identity_status='accepted' OR metadata_accepted=1"
            ).fetchone()[0])
            projection_current = (
                previous_schema
                and int(previous_schema[0]) >= 6
                and canonical_contract
                and str(canonical_contract[0]) == str(CANONICAL_CONTRACT_VERSION)
                and str(canonical_generation[0] if canonical_generation else '0')
                    == str(media_generation[0] if media_generation else '0')
                and canonical_rows == accepted_rows
            )
            if not projection_current:
                self.canonical.rebuild(connection)
                connection.execute(
                    "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('canonical_media_generation', ?)",
                    (str(media_generation[0] if media_generation else '0'),),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('canonical_contract_version', ?)",
                    (str(CANONICAL_CONTRACT_VERSION),),
                )
            if not previous_schema:
                connection.execute(
                    "INSERT INTO catalog_meta(key, value) VALUES('schema_version', ?)",
                    (str(CATALOG_SCHEMA_VERSION),),
                )
                self._validate_v10_schema(connection)
        if migration_reports:
            report = {
                **migration_reports[0],
                **migration_reports[-1],
                "from_version": migration_reports[0]["from_version"],
                "to_version": migration_reports[-1]["to_version"],
                "steps": migration_reports,
            }
            self.last_migration_report = report

    @staticmethod
    def _initialize_asset_schema(connection):
        _execute_schema(connection, """
            CREATE TABLE IF NOT EXISTS media_assets (
                asset_key TEXT PRIMARY KEY,
                asset_type TEXT NOT NULL CHECK(asset_type IN ('poster','portrait','discover_poster')),
                provider TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                local_path TEXT NOT NULL DEFAULT '',
                checksum TEXT NOT NULL DEFAULT '',
                mime_type TEXT NOT NULL DEFAULT '',
                byte_size INTEGER NOT NULL DEFAULT 0,
                width INTEGER NOT NULL DEFAULT 0,
                height INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'queued',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                downloaded_at REAL NOT NULL DEFAULT 0,
                last_verified_at REAL NOT NULL DEFAULT 0,
                last_accessed_at REAL NOT NULL DEFAULT 0,
                retention_class TEXT NOT NULL DEFAULT 'temporary',
                created_at REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0,
                UNIQUE(asset_type, provider, source_url)
            );

            CREATE TABLE IF NOT EXISTS movie_assets (
                movie_key TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                selected INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(movie_key, asset_type, asset_key),
                FOREIGN KEY(movie_key) REFERENCES canonical_movies(movie_key) ON DELETE CASCADE,
                FOREIGN KEY(asset_key) REFERENCES media_assets(asset_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS person_assets (
                person_key TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                selected INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(person_key, asset_type, asset_key),
                FOREIGN KEY(person_key) REFERENCES people(person_key) ON DELETE CASCADE,
                FOREIGN KEY(asset_key) REFERENCES media_assets(asset_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS curated_asset_refs (
                curated_identity_key TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                asset_key TEXT NOT NULL,
                PRIMARY KEY(curated_identity_key, asset_type, asset_key),
                FOREIGN KEY(asset_key) REFERENCES media_assets(asset_key) ON DELETE CASCADE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_movie_assets_selected
                ON movie_assets(movie_key, asset_type) WHERE selected=1;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_person_assets_selected
                ON person_assets(person_key, asset_type) WHERE selected=1;
            CREATE INDEX IF NOT EXISTS idx_media_assets_checksum ON media_assets(checksum);
            CREATE INDEX IF NOT EXISTS idx_media_assets_status ON media_assets(status, attempt_count, updated_at);
            CREATE INDEX IF NOT EXISTS idx_curated_asset_key ON curated_asset_refs(asset_key);
            INSERT OR IGNORE INTO catalog_meta(key, value) VALUES('asset_generation', '0');
        """)

    def import_documents(self, documents, backup_manifest):
        self._library_summary_cache = None
        self.initialize()
        documents = dict(documents or {})
        with self.transaction() as connection:
            for table in (
                "source_documents", "list_items", "user_lists", "collection_overrides",
                "followed_releases", "identity_audit_fingerprints",
                "manual_matches", "plex_files",
                "tmdb_movies", "media_identity_keys", "media_files",
            ):
                connection.execute(f"DELETE FROM {table}")

            for name, document in sorted(documents.items()):
                connection.execute(
                    "INSERT INTO source_documents(name, payload_json) VALUES(?, ?)",
                    (name, _json_text(document)),
                )

            self._import_media_files(connection, documents.get("app_metadata/files.json", {}))
            self._import_tmdb_movies(connection, documents.get("app_metadata/tmdb_metadata.json", {}))
            self._import_plex_files(connection, documents.get("app_metadata/plex_metadata.json", {}))
            self._import_manual_matches(connection, documents.get("app_metadata/manual_matches.json", {}))
            self._import_identity_audit_fingerprints(
                connection,
                documents.get("app_metadata/identity_audit_fingerprints.json", {}),
            )
            self._import_lists(connection, documents.get("user_lists.json", {}))
            self._import_collections(connection, documents.get("user_collections.json", {}))
            self._import_followed(connection, documents.get("followed_releases.json", {}))
            self._import_media_identity_keys(connection)
            self.canonical.rebuild(connection)
            media_generation = connection.execute(
                "SELECT value FROM catalog_meta WHERE key='media_generation'"
            ).fetchone()
            connection.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('canonical_media_generation', ?)",
                (str(media_generation[0] if media_generation else '0'),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('canonical_contract_version', ?)",
                (str(CANONICAL_CONTRACT_VERSION),),
            )

            connection.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('backup_manifest', ?)",
                (_json_text(backup_manifest or {}),),
            )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_meta(key, value) VALUES('imported_at', ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

    @staticmethod
    def _media_file_values(path_key, record):
        record = record if isinstance(record, dict) else {}
        facts_version = int(_number(record.get("file_facts_version")))
        quality_class = _text(record.get("quality_class"))
        resolution = quality_class if facts_version > 0 and quality_class else _text(record.get("resolution"))
        return (
                _text(path_key), _text(record.get("path") or path_key), _text(record.get("filename")),
                _text(record.get("library_root")), int(_number(record.get("size"))),
                _number(record.get("added_time")), _number(record.get("modified_time")),
                resolution, _text(record.get("rip_source")),
                _text(record.get("parsed_title")), _text(record.get("parsed_year")),
                _text(record.get("identity_status")), _text(record.get("identity_title") or record.get("accepted_title")),
                _text(record.get("identity_year") or record.get("accepted_year")), _text(record.get("identity_source")),
                int(_number(record.get("identity_revision"))), int(_number(record.get("identity_decision_version"))),
                _text(record.get("identity_evidence_fingerprint")), _text(record.get("tmdb_id")),
                _text(record.get("imdb_id")), _text(record.get("plex_guid")), _text(record.get("plex_rating_key") or record.get("rating_key")),
                _text(record.get("display_provider")), _text(record.get("metadata_status")),
                _text(record.get("metadata_source")), _bool(record.get("metadata_accepted")),
                _text(record.get("enrichment_status")), _text(record.get("ingest_status")),
                _bool(record.get("manual_lock")), _bool(record.get("manual_locked")), _json_text(record),
                int(_number(record.get("video_width"))), int(_number(record.get("video_height"))),
                _text(record.get("video_codec")), _text(record.get("video_profile")),
                int(_number(record.get("video_bit_depth"))), int(_number(record.get("video_bitrate"))),
                _number(record.get("video_frame_rate")), int(_number(record.get("duration_ms"))),
                _number(record.get("display_aspect_ratio")), _number(record.get("rotation_degrees")),
                _text(record.get("audio_codec")), _number(record.get("audio_channels")),
                int(_number(record.get("audio_bitrate"))), _text(record.get("filename_quality_claim")),
                quality_class, _text(record.get("quality_source") or "legacy_unprobed"),
                _bool(record.get("quality_conflict")), _bool(record.get("quality_nonstandard")),
                facts_version, int(_number(record.get("classifier_version"))),
                _text(record.get("probe_status") or "unprobed"), _number(record.get("probed_at")),
                _text(record.get("probe_error"))[:80], int(_number(record.get("probe_size"))),
                _number(record.get("probe_modified_time")),
        )

    @classmethod
    def _upsert_media_file(cls, connection, path_key, record):
        values = cls._media_file_values(path_key, record)
        placeholders = ",".join("?" for _ in values)
        columns = ",".join(MEDIA_FILE_V9_COLUMNS)
        connection.execute(
            f"INSERT OR REPLACE INTO media_files({columns}) VALUES ({placeholders})",
            values,
        )

    @classmethod
    def _import_media_files(cls, connection, document):
        records = document.get("files", {}) if isinstance(document, dict) else {}
        for path_key, record in records.items():
            cls._upsert_media_file(connection, path_key, record)

    @staticmethod
    def _import_tmdb_movies(connection, document):
        records = document.get("movies", {}) if isinstance(document, dict) else {}
        for tmdb_id, record in records.items():
            record = record if isinstance(record, dict) else {}
            connection.execute(
                "INSERT INTO tmdb_movies VALUES(?,?,?,?,?,?,?,?,?)",
                (_text(tmdb_id), _text(record.get("imdb_id")), _text(record.get("title")),
                 _text(record.get("year")), _text(record.get("poster_url")), _text(record.get("release_date")),
                 _bool(record.get("adult")), _number(record.get("updated_at")), _json_text(record)),
            )

    @staticmethod
    def _import_plex_files(connection, document):
        records = document.get("files", {}) if isinstance(document, dict) else {}
        for path_key, record in records.items():
            record = record if isinstance(record, dict) else {}
            connection.execute(
                "INSERT INTO plex_files VALUES(?,?,?,?,?,?,?,?,?,?)",
                (_text(path_key), _text(record.get("path") or path_key), _text(record.get("plex_title")),
                 _text(record.get("plex_year")), _text(record.get("tmdb_id")), _text(record.get("imdb_id")),
                 _text(record.get("plex_guid")), _text(record.get("rating_key")),
                 _number(record.get("updated_at")), _json_text(record)),
            )

    @staticmethod
    def _import_manual_matches(connection, document):
        records = document.get("matches", {}) if isinstance(document, dict) else {}
        for path_key, record in records.items():
            record = record if isinstance(record, dict) else {}
            connection.execute(
                "INSERT INTO manual_matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (_text(path_key), _text(record.get("path") or path_key), _text(record.get("provider")),
                 _text(record.get("source")), _text(record.get("tmdb_id")), _text(record.get("imdb_id")),
                 _text(record.get("plex_guid") or record.get("guid")), _text(record.get("title") or record.get("plex_title")),
                 _text(record.get("year") or record.get("plex_year")), _bool(record.get("accepted")),
                 _number(record.get("updated_at")), _json_text(record)),
            )

    @staticmethod
    def _import_identity_audit_fingerprints(connection, document):
        records = document.get("files", {}) if isinstance(document, dict) else {}
        for path_key, record in records.items():
            record = record if isinstance(record, dict) else {}
            connection.execute(
                "INSERT OR REPLACE INTO identity_audit_fingerprints VALUES(?,?,?,?,?,?,?)",
                (
                    _text(path_key),
                    _text(record.get("path") or path_key),
                    _text(record.get("provider")),
                    _text(record.get("provider_id")),
                    int(_number(record.get("rule_version"))),
                    _number(record.get("verified_at")),
                    _json_text(record),
                ),
            )

    @staticmethod
    def _import_lists(connection, document):
        lists = document.get("lists", []) if isinstance(document, dict) else []
        for list_row in lists if isinstance(lists, list) else []:
            if not isinstance(list_row, dict) or not _text(list_row.get("id")):
                continue
            list_id = _text(list_row.get("id"))
            connection.execute(
                "INSERT INTO user_lists VALUES(?,?,?,?,?,?)",
                (list_id, _text(list_row.get("name")), _text(list_row.get("system_type")),
                 _number(list_row.get("created_at")), _number(list_row.get("updated_at")), _json_text(list_row)),
            )
            movies = list_row.get("movies", [])
            for position, movie in enumerate(movies if isinstance(movies, list) else []):
                movie = movie if isinstance(movie, dict) else {}
                connection.execute(
                    "INSERT INTO list_items VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (list_id, position, _identity_key(movie), _text(movie.get("tmdb_id")),
                     _text(movie.get("imdb_id")), _text(movie.get("path")), _text(movie.get("title")),
                     _text(movie.get("year")), _text(movie.get("poster_url")), _json_text(movie)),
                )

    @staticmethod
    def _import_collections(connection, document):
        records = document.get("overrides", {}) if isinstance(document, dict) else {}
        for collection_id, record in records.items():
            record = record if isinstance(record, dict) else {}
            connection.execute(
                "INSERT INTO collection_overrides VALUES(?,?,?,?)",
                (_text(collection_id), _text(record.get("name")), _number(record.get("updated_at")), _json_text(record)),
            )

    @staticmethod
    def _import_followed(connection, document):
        movies = document.get("movies", []) if isinstance(document, dict) else []
        for position, movie in enumerate(movies if isinstance(movies, list) else []):
            movie = movie if isinstance(movie, dict) else {}
            connection.execute(
                "INSERT INTO followed_releases VALUES(?,?,?,?,?,?,?,?,?)",
                (position, _identity_key(movie), _text(movie.get("tmdb_id")), _text(movie.get("imdb_id")),
                 _text(movie.get("title")), _text(movie.get("year")), _text(movie.get("status")),
                 _number(movie.get("updated_at")), _json_text(movie)),
            )

    @staticmethod
    def _import_media_identity_keys(connection, path_key=None):
        where = "WHERE mf.path_key = ?" if path_key else ""
        parameters = (path_key,) if path_key else ()
        rows = connection.execute(f"""
            SELECT mf.path_key, mf.raw_json AS file_json,
                   pf.raw_json AS plex_json, mm.raw_json AS manual_json
            FROM media_files mf
            LEFT JOIN plex_files pf ON pf.path_key = mf.path_key
            LEFT JOIN manual_matches mm ON mm.path_key = mf.path_key
            {where}
        """, parameters).fetchall()
        for row in rows:
            file_record = json.loads(row["file_json"])
            authoritative = {
                **file_record,
                "title": file_record.get("identity_title") or file_record.get("accepted_title") or "",
                "year": file_record.get("identity_year") or file_record.get("accepted_year") or "",
            }
            candidates = [(authoritative, "authoritative")]
            if row["plex_json"]:
                candidates.append((json.loads(row["plex_json"]), "plex_snapshot"))
            if row["manual_json"]:
                candidates.append((json.loads(row["manual_json"]), "manual_match"))
            parsed_fallback = parse_release_filename(
                file_record.get("filename") or Path(file_record.get("path") or row["path_key"]).name
            )
            parsed = {
                "title": file_record.get("parsed_title") or parsed_fallback.get("title", ""),
                "year": file_record.get("parsed_year") or parsed_fallback.get("year", ""),
            }
            candidates.append((parsed, "parsed_filename"))
            for candidate, source in candidates:
                for identity_key in ownership_keys(candidate):
                    connection.execute(
                        "INSERT OR IGNORE INTO media_identity_keys(path_key, identity_key, key_source) VALUES(?, ?, ?)",
                        (row["path_key"], identity_key, source),
                    )

    def ownership_candidates(self, identity_keys):
        keys = list(dict.fromkeys(_text(key) for key in identity_keys if _text(key)))
        if not keys:
            return []
        placeholders = ",".join("?" for _ in keys)
        connection = self.connect()
        try:
            rows = connection.execute(f"""
                SELECT DISTINCT mf.*, pf.raw_json AS plex_json,
                       mm.raw_json AS manual_json, tm.raw_json AS tmdb_json
                FROM media_identity_keys mik
                JOIN media_files mf ON mf.path_key = mik.path_key
                LEFT JOIN plex_files pf ON pf.path_key = mf.path_key
                LEFT JOIN manual_matches mm ON mm.path_key = mf.path_key
                LEFT JOIN tmdb_movies tm ON tm.tmdb_id = mf.tmdb_id
                WHERE mik.identity_key IN ({placeholders})
                  AND (mf.identity_status = 'accepted' OR mf.metadata_accepted = 1)
                ORDER BY mf.added_time DESC
            """, keys).fetchall()
            return self._decode_media_rows(connection, rows, include_identity_keys=True)
        finally:
            connection.close()

    def owned_path_candidates(self, path_keys):
        """Return accepted owned candidates for exact normalized file paths."""
        keys = list(dict.fromkeys(_text(key) for key in path_keys if _text(key)))
        if not keys:
            return []
        connection = self.connect()
        try:
            rows = []
            for offset in range(0, len(keys), 400):
                chunk = keys[offset:offset + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows.extend(connection.execute(f"""
                    SELECT DISTINCT mf.*, pf.raw_json AS plex_json,
                           mm.raw_json AS manual_json, tm.raw_json AS tmdb_json
                    FROM media_files mf
                    LEFT JOIN plex_files pf ON pf.path_key = mf.path_key
                    LEFT JOIN manual_matches mm ON mm.path_key = mf.path_key
                    LEFT JOIN tmdb_movies tm ON tm.tmdb_id = mf.tmdb_id
                    WHERE mf.path_key IN ({placeholders})
                      AND (mf.identity_status = 'accepted' OR mf.metadata_accepted = 1)
                    ORDER BY mf.added_time DESC
                """, chunk).fetchall())
            return self._decode_media_rows(connection, rows, include_identity_keys=True)
        finally:
            connection.close()

    def owned_identity_candidates(self, identity_keys=(), path_keys=()):
        """Return lightweight canonical identities for accepted owned movies.

        Curation only needs the catalog identity graph. It must not decode full
        provider documents or stat every media file while a user toggles a list.
        """
        keys = list(dict.fromkeys(_text(key) for key in identity_keys if _text(key)))
        paths = list(dict.fromkeys(_text(key) for key in path_keys if _text(key)))
        if not keys and not paths:
            return []
        connection = self.connect()
        try:
            rows = connection.execute("""
                WITH requested_paths(value) AS (
                    SELECT value FROM json_each(?)
                ),
                requested_keys(value) AS (
                    SELECT value FROM json_each(?)
                ),
                matched_paths(path_key) AS (
                    SELECT value FROM requested_paths
                    UNION
                    SELECT mik.path_key
                    FROM media_identity_keys mik
                    JOIN requested_keys rk ON rk.value = mik.identity_key
                    UNION
                    SELECT cmf.path_key
                    FROM canonical_movie_files cmf
                    JOIN requested_keys rk ON rk.value = cmf.movie_key
                )
                SELECT DISTINCT
                       mf.path_key, mf.path, mf.filename, mf.size,
                       mf.resolution, mf.quality_class, mf.added_time,
                       cm.movie_key, cm.title, cm.year,
                       cm.tmdb_id, cm.imdb_id, cm.plex_guid
                FROM matched_paths mp
                JOIN media_files mf ON mf.path_key = mp.path_key
                JOIN canonical_movie_files cmf ON cmf.path_key = mf.path_key
                JOIN canonical_movies cm ON cm.movie_key = cmf.movie_key
                WHERE (mf.identity_status = 'accepted' OR mf.metadata_accepted = 1)
                ORDER BY mf.added_time DESC, mf.path_key
            """, (_json_text(paths), _json_text(keys))).fetchall()
            path_keys_found = [row["path_key"] for row in rows]
            identity_keys_by_path = {}
            if path_keys_found:
                for key_row in connection.execute("""
                    SELECT path_key, identity_key
                    FROM media_identity_keys
                    WHERE path_key IN (SELECT value FROM json_each(?))
                    ORDER BY path_key, identity_key
                """, (_json_text(path_keys_found),)).fetchall():
                    identity_keys_by_path.setdefault(key_row["path_key"], []).append(
                        key_row["identity_key"]
                    )
            result = []
            for row in rows:
                item = dict(row)
                item["identity_keys"] = list(identity_keys_by_path.get(item["path_key"], ()))
                result.append(item)
            return result
        finally:
            connection.close()

    def owned_movie_candidate(self, *, path_key="", movie_key=""):
        """Return one owned file/movie graph for production detail projection.

        This is intentionally bounded by one normalized path or canonical movie key.
        Full-catalog provider-document decoding is confined to the explicitly named
        ``audit_library_candidates`` reader and is not available to production routes.
        """
        path_key = _text(path_key)
        movie_key = _text(movie_key)
        if not path_key and not movie_key:
            return None
        connection = self.connect()
        try:
            if path_key:
                row = connection.execute("""
                    SELECT mf.* FROM media_files mf
                    WHERE mf.path_key = ?
                    LIMIT 1
                """, (path_key,)).fetchone()
            else:
                row = connection.execute("""
                    SELECT mf.*
                    FROM canonical_movie_files cmf
                    JOIN media_files mf ON mf.path_key = cmf.path_key
                    WHERE cmf.movie_key = ?
                    ORDER BY mf.added_time DESC, mf.path_key
                    LIMIT 1
                """, (movie_key,)).fetchone()
            if not row:
                return None
            item = dict(row)
            item["relational_canonical"] = self.canonical.project_paths(
                connection, [item["path_key"]], include_details=True
            ).get(item["path_key"], {})
            return item
        finally:
            connection.close()

    @staticmethod
    def _library_effective_cte():
        return """
            WITH resolved AS (
                SELECT
                    mf.path_key, mf.path, mf.filename, mf.library_root, mf.size,
                    mf.added_time, mf.modified_time, mf.resolution, mf.rip_source,
                    mf.parsed_title, mf.parsed_year, mf.metadata_status,
                    mf.metadata_accepted, mf.identity_status,
                    cm.movie_key, cm.title AS canonical_title, cm.year AS canonical_year,
                    cm.tmdb_id, cm.imdb_id, cm.plex_guid, cm.selected_provider,
                    COALESCE(
                        (
                            SELECT selected.snapshot_key
                            FROM provider_movie_snapshots selected
                            WHERE selected.movie_key = cm.movie_key
                              AND selected.provider = cm.selected_provider
                              AND selected.path_key = mf.path_key
                            ORDER BY selected.updated_at DESC, selected.snapshot_key
                            LIMIT 1
                        ),
                        (
                            SELECT selected.snapshot_key
                            FROM provider_movie_snapshots selected
                            WHERE selected.movie_key = cm.movie_key
                              AND selected.provider = cm.selected_provider
                            ORDER BY selected.updated_at DESC, selected.snapshot_key
                            LIMIT 1
                        ),
                        (
                            SELECT fallback.snapshot_key
                            FROM provider_movie_snapshots fallback
                            WHERE fallback.movie_key = cm.movie_key
                              AND fallback.provider <> cm.selected_provider
                              AND fallback.path_key = mf.path_key
                            ORDER BY CASE fallback.provider WHEN 'tmdb' THEN 0 ELSE 1 END,
                                fallback.updated_at DESC,
                                fallback.snapshot_key
                            LIMIT 1
                        ),
                        (
                            SELECT fallback.snapshot_key
                            FROM provider_movie_snapshots fallback
                            WHERE fallback.movie_key = cm.movie_key
                              AND fallback.provider <> cm.selected_provider
                            ORDER BY CASE fallback.provider WHEN 'tmdb' THEN 0 ELSE 1 END,
                                fallback.updated_at DESC,
                                fallback.snapshot_key
                            LIMIT 1
                        )
                    ) AS snapshot_key,
                    COALESCE((
                        SELECT mo.title
                        FROM movie_overrides mo
                        JOIN movie_override_identity_keys mk ON mk.override_id = mo.override_id
                        WHERE mo.override_type = 'metadata'
                          AND (
                            mk.identity_key = cm.movie_key
                            OR (cm.tmdb_id <> '' AND mk.identity_key = 'tmdb:' || cm.tmdb_id)
                            OR (cm.imdb_id <> '' AND mk.identity_key = 'imdb:' || LOWER(cm.imdb_id))
                            OR (cm.plex_guid <> '' AND mk.identity_key = 'plex:' || LOWER(cm.plex_guid))
                            OR mk.identity_key = 'path:' || LOWER(mf.path)
                          )
                        ORDER BY mo.updated_at DESC, mo.override_id DESC
                        LIMIT 1
                    ), '') AS override_title,
                    COALESCE((
                        SELECT mo.year
                        FROM movie_overrides mo
                        JOIN movie_override_identity_keys mk ON mk.override_id = mo.override_id
                        WHERE mo.override_type = 'metadata'
                          AND (
                            mk.identity_key = cm.movie_key
                            OR (cm.tmdb_id <> '' AND mk.identity_key = 'tmdb:' || cm.tmdb_id)
                            OR (cm.imdb_id <> '' AND mk.identity_key = 'imdb:' || LOWER(cm.imdb_id))
                            OR (cm.plex_guid <> '' AND mk.identity_key = 'plex:' || LOWER(cm.plex_guid))
                            OR mk.identity_key = 'path:' || LOWER(mf.path)
                          )
                        ORDER BY mo.updated_at DESC, mo.override_id DESC
                        LIMIT 1
                    ), '') AS override_year
                FROM media_files mf
                JOIN canonical_movie_files cmf ON cmf.path_key = mf.path_key
                JOIN canonical_movies cm ON cm.movie_key = cmf.movie_key
                WHERE (mf.identity_status = 'accepted' OR mf.metadata_accepted = 1)
                  AND (
                    json_type(mf.raw_json, '$.movie_view_publication') IS NULL
                    OR json_extract(mf.raw_json, '$.movie_view_publication') = 'ready'
                  )
            ),
            effective AS (
                SELECT
                    resolved.*,
                    pms.poster_url,
                    pms.plot,
                    pms.rating,
                    pms.language,
                    pms.country,
                    pms.country_flag,
                    pms.release_date,
                    COALESCE(NULLIF(resolved.override_title, ''), NULLIF(resolved.canonical_title, ''),
                             NULLIF(pms.title, ''), NULLIF(resolved.parsed_title, ''), resolved.filename) AS display_title,
                    COALESCE(NULLIF(resolved.override_year, ''), NULLIF(resolved.canonical_year, ''),
                             NULLIF(pms.year, ''), resolved.parsed_year) AS display_year,
                    CASE
                        WHEN LOWER(resolved.resolution) LIKE '%2160%' OR LOWER(resolved.resolution) LIKE '%4k%' THEN 4
                        WHEN LOWER(resolved.resolution) LIKE '%1080%' THEN 3
                        WHEN LOWER(resolved.resolution) LIKE '%720%' THEN 2
                        WHEN LOWER(resolved.resolution) LIKE '%480%' THEN 1
                        ELSE 0
                    END AS resolution_rank
                FROM resolved
                LEFT JOIN provider_movie_snapshots pms ON pms.snapshot_key = resolved.snapshot_key
            )
        """

    @staticmethod
    def _library_filter_sql(filters):
        filters = dict(filters or {})
        clauses = []
        parameters = []
        query = _text(filters.get("query")).lower()
        if query:
            clauses.append("""
                LOWER(
                    COALESCE(e.display_title, '') || ' ' || COALESCE(e.display_year, '') || ' ' ||
                    COALESCE(e.filename, '') || ' ' || COALESCE(e.path, '') || ' ' ||
                    COALESCE(e.plot, '') || ' ' || COALESCE((
                        SELECT GROUP_CONCAT(g.name, ' ')
                        FROM movie_genres mg JOIN genres g ON g.genre_key = mg.genre_key
                        WHERE mg.snapshot_key = e.snapshot_key
                    ), '')
                ) LIKE ?
            """)
            parameters.append(f"%{query}%")
        resolution = _text(filters.get("resolution")) or "all"
        if resolution == "upgrade":
            clauses.append("e.path_key IN (SELECT value FROM json_each(?))")
            parameters.append(_json_text(list(filters.get("upgrade_path_keys") or [])))
        elif resolution == "4k":
            clauses.append("e.resolution_rank = 4")
        elif resolution == "1080p":
            clauses.append("e.resolution_rank = 3")
        elif resolution == "720p":
            clauses.append("e.resolution_rank = 2")
        elif resolution == "below-720p":
            clauses.append("e.resolution_rank < 2")
        source = _text(filters.get("source")) or "all"
        if source != "all":
            clauses.append("e.rip_source = ?")
            parameters.append(source)
        genre = _text(filters.get("genre")) or "all"
        if genre != "all":
            clauses.append("""
                EXISTS(
                    SELECT 1 FROM movie_genres mg JOIN genres g ON g.genre_key = mg.genre_key
                    WHERE mg.snapshot_key = e.snapshot_key AND g.name = ?
                )
            """)
            parameters.append(genre)
        language = _text(filters.get("language")) or "all"
        if language != "all":
            clauses.append("e.language = ?")
            parameters.append(language)
        country = _text(filters.get("country")) or "all"
        if country != "all":
            clauses.append("COALESCE(NULLIF(e.country_flag, ''), e.country) = ?")
            parameters.append(country)
        year_from = _text(filters.get("year_from"))
        if year_from:
            clauses.append("CAST(COALESCE(NULLIF(e.display_year, ''), '0') AS INTEGER) >= ?")
            parameters.append(int(year_from))
        year_to = _text(filters.get("year_to"))
        if year_to:
            clauses.append("CAST(COALESCE(NULLIF(e.display_year, ''), '0') AS INTEGER) <= ?")
            parameters.append(int(year_to))
        min_rating = _text(filters.get("min_rating")) or "all"
        if min_rating != "all":
            clauses.append("CAST(COALESCE(NULLIF(e.rating, ''), '0') AS REAL) >= ?")
            parameters.append(float(min_rating))
        role = _text(filters.get("role"))
        person_id = _text(filters.get("person_id"))
        person_name = _text(filters.get("person_name")).lower()
        if role and (person_id or person_name):
            credit_type = {"director": "director", "writer": "writer"}.get(role, "cast")
            person_clause = "COALESCE(NULLIF(p.tmdb_id, ''), p.provider_id) = ?" if person_id else "LOWER(p.name) = ?"
            clauses.append(f"""
                EXISTS(
                    SELECT 1 FROM movie_credits mc JOIN people p ON p.person_key = mc.person_key
                    WHERE mc.snapshot_key = e.snapshot_key AND mc.credit_type = ? AND {person_clause}
                )
            """)
            parameters.extend((credit_type, person_id or person_name))
        keyword_id = _text(filters.get("keyword_id"))
        keyword_name = normalize_keyword_name(filters.get("keyword_name"))
        keyword_query = normalize_keyword_name(filters.get("keyword_query"))
        if keyword_id:
            clauses.append("""
                e.snapshot_key IN (
                    SELECT mk.snapshot_key
                    FROM keywords AS k INDEXED BY idx_keywords_tmdb
                    JOIN movie_keywords AS mk INDEXED BY idx_movie_keywords_keyword
                      ON mk.keyword_key = k.keyword_key
                    WHERE k.tmdb_id <> '' AND k.tmdb_id = ?
                )
            """)
            parameters.append(keyword_id)
        elif keyword_name:
            clauses.append("""
                e.snapshot_key IN (
                    SELECT mk.snapshot_key
                    FROM keywords AS k INDEXED BY idx_keywords_normalized_name
                    JOIN movie_keywords AS mk INDEXED BY idx_movie_keywords_keyword
                      ON mk.keyword_key = k.keyword_key
                    WHERE k.normalized_name = ?
                )
            """)
            parameters.append(keyword_name)
        elif keyword_query:
            lower_bound, upper_bound = _keyword_prefix_bounds(keyword_query)
            clauses.append("""
                e.snapshot_key IN (
                    SELECT mk.snapshot_key
                    FROM keywords AS k INDEXED BY idx_keywords_normalized_name
                    JOIN movie_keywords AS mk INDEXED BY idx_movie_keywords_keyword
                      ON mk.keyword_key = k.keyword_key
                    WHERE k.normalized_name >= ? AND k.normalized_name < ?
                )
            """)
            parameters.extend((lower_bound, upper_bound))
        collection_paths = list(filters.get("collection_path_keys") or [])
        collection_id = _text(filters.get("collection_id"))
        if collection_paths:
            clauses.append("e.path_key IN (SELECT value FROM json_each(?))")
            parameters.append(_json_text(collection_paths))
        elif collection_id:
            clauses.append("""
                EXISTS(
                    SELECT 1 FROM movie_collections mc
                    JOIN collections c ON c.collection_key = mc.collection_key
                    WHERE mc.snapshot_key = e.snapshot_key AND c.provider_id = ?
                )
            """)
            parameters.append(collection_id)

        def list_membership_clause(system_type=False):
            list_constraint = "ul.system_type = ?" if system_type else "li.list_id = ?"
            return f"""
                EXISTS(
                    SELECT 1 FROM list_items li
                    JOIN user_lists ul ON ul.list_id = li.list_id
                    WHERE {list_constraint}
                      AND (
                        (li.tmdb_id <> '' AND li.tmdb_id = e.tmdb_id)
                        OR (li.imdb_id <> '' AND LOWER(li.imdb_id) = LOWER(e.imdb_id))
                        OR (li.path <> '' AND LOWER(li.path) = LOWER(e.path))
                        OR li.identity_key IN (
                            SELECT identity_key FROM media_identity_keys WHERE path_key = e.path_key
                        )
                      )
                )
            """

        list_id = _text(filters.get("list_id"))
        if list_id:
            clauses.append(list_membership_clause())
            parameters.append(list_id)
        viewing_state = _text(filters.get("viewing_state")) or "all"
        if viewing_state in {"watched", "watchlist"}:
            clauses.append(list_membership_clause(system_type=True))
            parameters.append(viewing_state)
        elif viewing_state == "unwatched":
            clauses.append("NOT " + list_membership_clause(system_type=True))
            parameters.append("watched")
        return (" WHERE " + " AND ".join(f"({clause})" for clause in clauses)) if clauses else "", parameters

    @staticmethod
    def _library_sort_sql(sort_mode):
        title = (
            "cp_sort_key(e.display_title), e.display_title COLLATE NOCASE, "
            "e.added_time DESC, e.parsed_title COLLATE NOCASE, e.path_key"
        )
        return {
            "rating": title,
            "added": f"COALESCE(NULLIF(e.added_time, 0), e.modified_time, 0) DESC, {title}",
            "year-desc": f"CAST(COALESCE(NULLIF(e.display_year, ''), '0') AS INTEGER) DESC, {title}",
            "year-asc": f"CAST(COALESCE(NULLIF(e.display_year, ''), '0') AS INTEGER), {title}",
            "quality": f"e.resolution_rank DESC, {title}",
            "size": "e.size DESC, e.filename COLLATE NOCASE, e.path_key",
            "identity": "e.metadata_accepted DESC, e.filename COLLATE NOCASE, e.path_key",
            "plex": "e.metadata_accepted DESC, e.filename COLLATE NOCASE, e.path_key",
            "source": "e.rip_source COLLATE NOCASE, e.filename COLLATE NOCASE, e.path_key",
            "filename": "e.filename COLLATE NOCASE, e.path_key",
            "title": title,
        }.get(_text(sort_mode), title)

    def _candidates_for_path_keys(self, connection, path_keys):
        path_keys = list(dict.fromkeys(_text(key) for key in path_keys if _text(key)))
        if not path_keys:
            return []
        rows = connection.execute("""
            SELECT mf.* FROM media_files mf
            WHERE mf.path_key IN (SELECT value FROM json_each(?))
        """, (_json_text(path_keys),)).fetchall()
        canonical = self.canonical.project_paths(connection, path_keys, include_details=False)
        decoded = []
        for row in rows:
            item = dict(row)
            item["relational_canonical"] = canonical.get(item["path_key"], {})
            decoded.append(item)
        by_path = {row["path_key"]: row for row in decoded}
        return [by_path[key] for key in path_keys if key in by_path]

    def library_page(self, filters=None, *, page=1, page_size=40):
        filters = dict(filters or {})
        page_size = min(max(int(page_size or 40), 1), 200)
        page = max(int(page or 1), 1)
        cte = self._library_effective_cte()
        where, parameters = self._library_filter_sql(filters)
        connection = self.connect()
        try:
            total = int(connection.execute(
                f"{cte} SELECT COUNT(*) FROM effective e{where}", parameters
            ).fetchone()[0])
            total_pages = max(1, (total + page_size - 1) // page_size)
            page = min(page, total_pages)
            offset = (page - 1) * page_size
            path_keys = [
                row[0]
                for row in connection.execute(
                    f"{cte} SELECT e.path_key FROM effective e{where} "
                    f"ORDER BY {self._library_sort_sql(filters.get('sort'))} LIMIT ? OFFSET ?",
                    [*parameters, page_size, offset],
                ).fetchall()
            ]
            candidates = self._candidates_for_path_keys(connection, path_keys)
            generation_row = connection.execute(
                "SELECT value FROM catalog_meta WHERE key='media_generation'"
            ).fetchone()
            generation = int(generation_row[0]) if generation_row else 0
            summary = self._library_summary_cache
            if not summary or summary["generation"] != generation:
                facets = {
                    "genres": [row[0] for row in connection.execute(
                        f"{cte} SELECT DISTINCT g.name FROM effective e "
                        "JOIN movie_genres mg ON mg.snapshot_key=e.snapshot_key "
                        "JOIN genres g ON g.genre_key=mg.genre_key ORDER BY g.name COLLATE NOCASE"
                    ).fetchall() if row[0]],
                    "sources": [row[0] for row in connection.execute(
                        "SELECT DISTINCT rip_source FROM media_files WHERE rip_source<>'' ORDER BY rip_source COLLATE NOCASE"
                    ).fetchall() if row[0]],
                    "languages": [row[0] for row in connection.execute(
                        f"{cte} SELECT DISTINCT e.language FROM effective e WHERE e.language<>'' ORDER BY e.language COLLATE NOCASE"
                    ).fetchall() if row[0]],
                    "countries": [row[0] for row in connection.execute(
                        f"{cte} SELECT DISTINCT COALESCE(NULLIF(e.country_flag,''),e.country) value "
                        "FROM effective e WHERE COALESCE(NULLIF(e.country_flag,''),e.country)<>'' "
                        "ORDER BY value COLLATE NOCASE"
                    ).fetchall() if row[0]],
                }
                stats_row = connection.execute("""
                    SELECT COUNT(*) AS total,
                        SUM(CASE WHEN LOWER(resolution) NOT LIKE '%1080%'
                                       AND LOWER(resolution) NOT LIKE '%2160%'
                                       AND LOWER(resolution) NOT LIKE '%4k%' THEN 1 ELSE 0 END) AS low,
                        SUM(CASE WHEN identity_status='accepted' OR metadata_accepted=1 THEN 1 ELSE 0 END) AS matched,
                        SUM(CASE WHEN metadata_status='pending' THEN 1 ELSE 0 END) AS pending,
                        SUM(CASE WHEN NOT(identity_status='accepted' OR metadata_accepted=1)
                                       AND metadata_status<>'pending' THEN 1 ELSE 0 END) AS unmatched
                    FROM media_files
                """).fetchone()
                summary = {
                    "generation": generation,
                    "facets": facets,
                    "stats": {key: int(stats_row[key] or 0) for key in ("total", "low", "matched", "pending", "unmatched")},
                }
                self._library_summary_cache = summary
            return {
                "candidates": candidates,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "page_start": offset if total else 0,
                "page_end": min(offset + len(candidates), total),
                "facets": summary["facets"],
                "stats": summary["stats"],
            }
        finally:
            connection.close()

    def library_selection_paths(self, filters=None):
        filters = dict(filters or {})
        cte = self._library_effective_cte()
        where, parameters = self._library_filter_sql(filters)
        connection = self.connect()
        try:
            return [
                row[0]
                for row in connection.execute(
                    f"{cte} SELECT e.path FROM effective e{where} "
                    f"ORDER BY {self._library_sort_sql(filters.get('sort'))}",
                    parameters,
                ).fetchall()
            ]
        finally:
            connection.close()

    @staticmethod
    def _library_keyword_counts_cte():
        return """
            WITH ranked_effective AS MATERIALIZED (
                SELECT
                    mf.path_key,
                    pms.snapshot_key,
                    ROW_NUMBER() OVER (
                        PARTITION BY mf.path_key
                        ORDER BY
                            CASE
                                WHEN pms.provider = cm.selected_provider
                                     AND pms.path_key = mf.path_key THEN 0
                                WHEN pms.provider = cm.selected_provider THEN 1
                                WHEN pms.provider <> cm.selected_provider
                                     AND pms.path_key = mf.path_key THEN 2
                                ELSE 3
                            END,
                            CASE
                                WHEN pms.provider <> cm.selected_provider
                                THEN CASE pms.provider WHEN 'tmdb' THEN 0 ELSE 1 END
                                ELSE 0
                            END,
                            pms.updated_at DESC,
                            pms.snapshot_key
                    ) AS choice_rank
                FROM media_files AS mf
                JOIN canonical_movie_files AS cmf ON cmf.path_key = mf.path_key
                JOIN canonical_movies AS cm ON cm.movie_key = cmf.movie_key
                JOIN provider_movie_snapshots AS pms ON pms.movie_key = cm.movie_key
                WHERE (mf.identity_status = 'accepted' OR mf.metadata_accepted = 1)
                  AND (
                    json_type(mf.raw_json, '$.movie_view_publication') IS NULL
                    OR json_extract(mf.raw_json, '$.movie_view_publication') = 'ready'
                  )
            ),
            effective AS MATERIALIZED (
                SELECT path_key, snapshot_key
                FROM ranked_effective
                WHERE choice_rank = 1
            ),
            matching_keywords AS MATERIALIZED (
                SELECT keyword_key, tmdb_id, name, normalized_name
                FROM keywords INDEXED BY idx_keywords_normalized_name
                WHERE normalized_name >= ? AND normalized_name < ?
            ),
            keyword_counts AS (
                SELECT
                    k.keyword_key,
                    k.tmdb_id,
                    k.name,
                    k.normalized_name,
                    COUNT(DISTINCT e.path_key) AS movie_count
                FROM matching_keywords AS k
                JOIN movie_keywords AS mk INDEXED BY idx_movie_keywords_keyword
                  ON mk.keyword_key = k.keyword_key
                JOIN effective AS e ON e.snapshot_key = mk.snapshot_key
                GROUP BY k.keyword_key, k.tmdb_id, k.name, k.normalized_name
            )
        """

    def _library_keywords_page_sql(self):
        return f"""
            {self._library_keyword_counts_cte()}
            SELECT keyword_key, tmdb_id, name, normalized_name, movie_count
            FROM keyword_counts
            ORDER BY
                CASE WHEN normalized_name = ? THEN 0 ELSE 1 END,
                movie_count DESC,
                name COLLATE NOCASE,
                keyword_key
            LIMIT ? OFFSET ?
        """

    def library_keywords(self, query="", *, page=1, page_size=50):
        normalized, upper_bound = _keyword_prefix_bounds(query)
        try:
            page = max(int(page or 1), 1)
        except (TypeError, ValueError):
            page = 1
        try:
            page_size = min(max(int(page_size or 50), 1), 50)
        except (TypeError, ValueError):
            page_size = 50

        connection = self.connect()
        try:
            if not normalized:
                generation_row = connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='media_generation'"
                ).fetchone()
                return {
                    "items": [],
                    "page": 1,
                    "page_size": page_size,
                    "total_pages": 1,
                    "total_results": 0,
                    "catalog_generation": int(generation_row[0]) if generation_row else 0,
                }

            connection.execute("BEGIN")
            total_row = connection.execute(
                f"""
                    {self._library_keyword_counts_cte()}
                    SELECT
                        COUNT(*) AS total_results,
                        COALESCE((
                            SELECT CAST(value AS INTEGER)
                            FROM catalog_meta
                            WHERE key = 'media_generation'
                        ), 0) AS catalog_generation
                    FROM keyword_counts
                """,
                (normalized, upper_bound),
            ).fetchone()
            total_results = int(total_row["total_results"] or 0)
            total_pages = max(1, (total_results + page_size - 1) // page_size)
            page = min(page, total_pages)
            offset = (page - 1) * page_size
            items = [
                {
                    "keyword_key": row["keyword_key"],
                    "tmdb_id": row["tmdb_id"],
                    "name": row["name"],
                    "normalized_name": row["normalized_name"],
                    "movie_count": int(row["movie_count"] or 0),
                }
                for row in connection.execute(
                    self._library_keywords_page_sql(),
                    (normalized, upper_bound, normalized, page_size, offset),
                ).fetchall()
            ]
            return {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages,
                "total_results": total_results,
                "catalog_generation": int(total_row["catalog_generation"] or 0),
            }
        finally:
            try:
                if connection.in_transaction:
                    connection.rollback()
            finally:
                connection.close()

    def candidates_for_paths(self, path_keys):
        connection = self.connect()
        try:
            return self._candidates_for_path_keys(connection, path_keys)
        finally:
            connection.close()

    def library_projection(self, *, include_details=False):
        """Return the complete normalized library without decoding source documents."""
        connection = self.connect()
        try:
            rows = [dict(row) for row in connection.execute("""
                SELECT mf.path_key, mf.path, mf.filename, mf.library_root,
                       mf.size, mf.added_time, mf.modified_time, mf.resolution,
                       mf.rip_source, mf.parsed_title, mf.parsed_year,
                       mf.identity_status, mf.identity_title, mf.identity_year,
                       mf.identity_source, mf.identity_revision,
                       mf.identity_decision_version, mf.identity_evidence_fingerprint,
                       mf.tmdb_id, mf.imdb_id, mf.plex_guid, mf.plex_rating_key,
                       mf.display_provider, mf.metadata_status, mf.metadata_source,
                       mf.metadata_accepted, mf.enrichment_status, mf.ingest_status,
                       mf.manual_lock, mf.manual_locked,
                       mf.video_width, mf.video_height, mf.video_codec,
                       mf.video_profile, mf.video_bit_depth, mf.video_bitrate,
                       mf.video_frame_rate, mf.duration_ms,
                       mf.display_aspect_ratio, mf.rotation_degrees,
                       mf.audio_codec, mf.audio_channels, mf.audio_bitrate,
                       mf.filename_quality_claim, mf.quality_class,
                       mf.quality_source, mf.quality_conflict,
                       mf.quality_nonstandard, mf.file_facts_version,
                       mf.classifier_version, mf.probe_status, mf.probed_at,
                       mf.probe_error, mf.probe_size, mf.probe_modified_time
                FROM media_files mf
                ORDER BY mf.added_time DESC, cp_sort_key(mf.identity_title), mf.path_key
            """).fetchall()]
            projections = self.canonical.project_paths(
                connection,
                [row["path_key"] for row in rows],
                include_details=include_details,
            )
            for row in rows:
                row["relational_canonical"] = projections.get(row["path_key"], {})
            return rows
        finally:
            connection.close()

    def file_inventory(self):
        """Return the normalized file/statistics contract in one SQL statement."""
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute("""
                SELECT mf.path, mf.filename, mf.library_root, mf.size,
                       mf.resolution, mf.rip_source, mf.parsed_title, mf.parsed_year,
                       mf.tmdb_id, mf.imdb_id, mf.identity_title, mf.identity_year,
                       mf.metadata_status, mf.metadata_accepted,
                       mf.video_width, mf.video_height, mf.video_codec,
                       mf.video_profile, mf.video_bit_depth, mf.video_bitrate,
                       mf.video_frame_rate, mf.duration_ms,
                       mf.display_aspect_ratio, mf.rotation_degrees,
                       mf.audio_codec, mf.audio_channels, mf.audio_bitrate,
                       mf.filename_quality_claim, mf.quality_class,
                       mf.quality_source, mf.quality_conflict,
                       mf.quality_nonstandard, mf.file_facts_version,
                       mf.classifier_version, mf.probe_status, mf.probed_at,
                       mf.probe_error, mf.probe_size, mf.probe_modified_time,
                       pf.plex_title, pf.plex_year
                FROM media_files mf
                LEFT JOIN plex_files pf ON pf.path_key=mf.path_key
                ORDER BY mf.path_key
            """).fetchall()]
        finally:
            connection.close()

    def file_facts_backfill_candidates(self, limit=8, *, retry_failed=False):
        """Return one bounded batch of stale SQL rows without touching files."""
        limit = min(max(int(limit or 8), 1), 100)
        retry_clause = (
            " OR probe_status NOT IN ('ok', 'unprobed')"
            if retry_failed else ""
        )
        connection = self.connect()
        try:
            fact_columns = ", ".join(MEDIA_FILE_FACT_COLUMNS)
            rows = connection.execute(f"""
                SELECT path_key, path, filename, library_root, size, modified_time,
                       {fact_columns}
                FROM media_files
                WHERE file_facts_version < ?
                   OR classifier_version < ?
                   OR probe_status='unprobed'
                   OR (
                       probe_status='ok'
                       AND (
                           probe_size<>size
                           OR ABS(probe_modified_time-modified_time)>0.001
                       )
                   )
                   {retry_clause}
                ORDER BY
                    CASE
                        WHEN quality_conflict=1 THEN 0
                        WHEN probe_status='unprobed' THEN 1
                        ELSE 2
                    END,
                    path_key
                LIMIT ?
            """, (FILE_FACTS_VERSION, QUALITY_CLASSIFIER_VERSION, limit)).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    def file_facts_backfill_remaining(self, *, retry_failed=False):
        retry_clause = (
            " OR probe_status NOT IN ('ok', 'unprobed')"
            if retry_failed else ""
        )
        connection = self.connect()
        try:
            return int(connection.execute(f"""
                SELECT COUNT(*) FROM media_files
                WHERE file_facts_version < ?
                   OR classifier_version < ?
                   OR probe_status='unprobed'
                   OR (
                       probe_status='ok'
                       AND (
                           probe_size<>size
                           OR ABS(probe_modified_time-modified_time)>0.001
                       )
                   )
                   {retry_clause}
            """, (FILE_FACTS_VERSION, QUALITY_CLASSIFIER_VERSION)).fetchone()[0])
        finally:
            connection.close()

    @staticmethod
    def apply_file_facts_batch(connection, updates):
        """Atomically apply complete fact objects; return changed/rejected counts."""
        changed = 0
        rejected = 0
        fields = [
            *MEDIA_FILE_FACT_COLUMNS,
            "resolution",
            "raw_json",
        ]
        assignments = ", ".join(f"{field}=?" for field in fields)
        for update in updates or []:
            path_key = _text(update.get("path_key"))
            row = connection.execute(
                "SELECT * FROM media_files WHERE path_key=?",
                (path_key,),
            ).fetchone()
            if not row:
                rejected += 1
                continue
            expected_size = int(_number(update.get("expected_size")))
            expected_modified = _number(update.get("expected_modified_time"))
            if (
                int(row["size"] or 0) != expected_size
                or abs(float(row["modified_time"] or 0) - expected_modified) > 0.001
            ):
                rejected += 1
                continue
            facts = dict(update.get("facts") or {})
            incoming_status = _text(facts.get("probe_status"))
            same_stored_file = (
                _text(row["probe_status"]) == "ok"
                and int(row["probe_size"] or 0) == int(row["size"] or 0)
                and abs(
                    float(row["probe_modified_time"] or 0)
                    - float(row["modified_time"] or 0)
                ) <= 0.001
            )
            same_failed_probe_file = (
                int(_number(facts.get("probe_size"))) == int(row["size"] or 0)
                and abs(
                    _number(facts.get("probe_modified_time"))
                    - float(row["modified_time"] or 0)
                ) <= 0.001
            )
            if (
                incoming_status
                and incoming_status != "ok"
                and same_stored_file
                and same_failed_probe_file
            ):
                failure_state = {
                    field: facts.get(field)
                    for field in (
                        "probe_status", "probed_at", "probe_error",
                        "probe_size", "probe_modified_time",
                    )
                }
                facts.update({
                    field: row[field]
                    for field in MEDIA_FILE_MEASUREMENT_COLUMNS
                })
                facts.update(failure_state)
                facts["quality_source"] = "last_measured_probe_failed"
            raw = json.loads(row["raw_json"]) if row["raw_json"] else {}
            raw.update(facts)
            raw["resolution"] = _text(facts.get("quality_class")) or "Unknown"
            raw["quality_display"] = quality_display(facts)
            values = []
            for field in MEDIA_FILE_FACT_COLUMNS:
                value = facts.get(field)
                if field in {
                    "video_width", "video_height", "video_bit_depth",
                    "video_bitrate", "duration_ms", "audio_bitrate",
                    "file_facts_version", "classifier_version", "probe_size",
                }:
                    value = int(_number(value))
                elif field in {
                    "video_frame_rate", "display_aspect_ratio",
                    "rotation_degrees", "audio_channels", "probed_at",
                    "probe_modified_time",
                }:
                    value = _number(value)
                elif field in {"quality_conflict", "quality_nonstandard"}:
                    value = _bool(value)
                else:
                    value = _text(value)
                if field == "probe_error":
                    value = value[:80]
                values.append(value)
            values.extend([
                _text(facts.get("quality_class")) or "Unknown",
                _json_text(raw),
                path_key,
            ])
            current = [row[field] for field in fields[:-1]]
            proposed = values[:-2]
            normalized_raw = _json_text(raw)
            current_raw = _json_text(
                json.loads(row["raw_json"]) if row["raw_json"] else {}
            )
            if current == proposed and current_raw == normalized_raw:
                continue
            cursor = connection.execute(
                f"UPDATE media_files SET {assignments} WHERE path_key=?",
                values,
            )
            changed += int(cursor.rowcount or 0)
        return {"changed": changed, "rejected": rejected}

    def audit_library_candidates(self):
        """Decode source evidence only for explicit parity, identity, and rollback audits."""
        connection = self.connect()
        try:
            rows = connection.execute("""
                SELECT mf.*, pf.raw_json AS plex_json,
                       mm.raw_json AS manual_json, tm.raw_json AS tmdb_json
                FROM media_files mf
                LEFT JOIN plex_files pf ON pf.path_key = mf.path_key
                LEFT JOIN manual_matches mm ON mm.path_key = mf.path_key
                LEFT JOIN tmdb_movies tm ON tm.tmdb_id = mf.tmdb_id
                ORDER BY mf.added_time DESC, mf.identity_title COLLATE NOCASE
            """).fetchall()
            return self._decode_media_rows(connection, rows, include_identity_keys=False)
        finally:
            connection.close()

    def maintenance_candidates(self):
        """Project maintenance evidence from normalized SQL columns only."""
        connection = self.connect()
        try:
            rows = connection.execute("""
                SELECT mf.*,
                       pf.path AS normalized_plex_path,
                       pf.plex_title AS normalized_plex_title,
                       pf.plex_year AS normalized_plex_year,
                       pf.tmdb_id AS normalized_plex_tmdb_id,
                       pf.imdb_id AS normalized_plex_imdb_id,
                       pf.plex_guid AS normalized_plex_guid,
                       pf.rating_key AS normalized_plex_rating_key,
                       mm.provider AS normalized_manual_provider,
                       mm.source AS normalized_manual_source,
                       mm.tmdb_id AS normalized_manual_tmdb_id,
                       mm.imdb_id AS normalized_manual_imdb_id,
                       mm.plex_guid AS normalized_manual_plex_guid,
                       mm.title AS normalized_manual_title,
                       mm.year AS normalized_manual_year,
                       mm.accepted AS normalized_manual_accepted,
                       tm.tmdb_id AS normalized_tmdb_id,
                       tm.imdb_id AS normalized_tmdb_imdb_id,
                       tm.title AS normalized_tmdb_title,
                       tm.year AS normalized_tmdb_year,
                       tm.release_date AS normalized_tmdb_release_date
                FROM media_files mf
                LEFT JOIN plex_files pf ON pf.path_key = mf.path_key
                LEFT JOIN manual_matches mm ON mm.path_key = mf.path_key
                LEFT JOIN tmdb_movies tm ON tm.tmdb_id = mf.tmdb_id
                ORDER BY mf.added_time DESC, mf.identity_title COLLATE NOCASE
            """).fetchall()
        finally:
            connection.close()

        candidates = []
        for source in rows:
            item = dict(source)
            item.pop("raw_json", None)
            normalized = {
                key: value
                for key, value in item.items()
                if not key.startswith("normalized_")
            }
            plex = {}
            if item.get("normalized_plex_path"):
                plex = {
                    "path": item.get("normalized_plex_path"),
                    "plex_title": item.get("normalized_plex_title"),
                    "plex_year": item.get("normalized_plex_year"),
                    "tmdb_id": item.get("normalized_plex_tmdb_id"),
                    "imdb_id": item.get("normalized_plex_imdb_id"),
                    "plex_guid": item.get("normalized_plex_guid"),
                    "rating_key": item.get("normalized_plex_rating_key"),
                }
            manual = {}
            if item.get("normalized_manual_provider"):
                manual = {
                    "provider": item.get("normalized_manual_provider"),
                    "source": item.get("normalized_manual_source"),
                    "tmdb_id": item.get("normalized_manual_tmdb_id"),
                    "imdb_id": item.get("normalized_manual_imdb_id"),
                    "plex_guid": item.get("normalized_manual_plex_guid"),
                    "title": item.get("normalized_manual_title"),
                    "year": item.get("normalized_manual_year"),
                    "accepted": bool(item.get("normalized_manual_accepted")),
                }
            tmdb = {}
            if item.get("normalized_tmdb_id"):
                tmdb = {
                    "tmdb_id": item.get("normalized_tmdb_id"),
                    "imdb_id": item.get("normalized_tmdb_imdb_id"),
                    "title": item.get("normalized_tmdb_title"),
                    "year": item.get("normalized_tmdb_year"),
                    "release_date": item.get("normalized_tmdb_release_date"),
                }
            candidates.append({
                **normalized,
                "raw_json": dict(normalized),
                "plex_json": plex,
                "manual_json": manual,
                "tmdb_json": tmdb,
            })
        return candidates

    def _decode_media_rows(self, connection, rows, include_identity_keys):
        identity_keys_by_path = {}
        if include_identity_keys:
            path_keys = list(dict.fromkeys(
                _text(row["path_key"])
                for row in rows
                if _text(row["path_key"])
            ))
            if path_keys:
                for key_row in connection.execute(
                    """
                    SELECT path_key, identity_key
                    FROM media_identity_keys
                    WHERE path_key IN (SELECT value FROM json_each(?))
                    ORDER BY path_key, identity_key
                    """,
                    (_json_text(path_keys),),
                ).fetchall():
                    identity_keys_by_path.setdefault(key_row["path_key"], []).append(
                        key_row["identity_key"]
                    )

        result = []
        for row in rows:
            item = dict(row)
            for column in ("raw_json", "plex_json", "manual_json", "tmdb_json"):
                item[column] = json.loads(item[column]) if item.get(column) else {}
            if include_identity_keys:
                item["identity_keys"] = list(identity_keys_by_path.get(item["path_key"], ()))
            result.append(item)
        return result

    def canonical_report(self, max_errors=100):
        connection = self.connect()
        try:
            return self.canonical.strict_report(connection, max_errors=max_errors)
        finally:
            connection.close()

    def parity_report(self, expected_counts):
        table_map = {
            "file_records": "media_files",
            "tmdb_movies": "tmdb_movies",
            "plex_files": "plex_files",
            "manual_matches": "manual_matches",
            "user_lists": "user_lists",
            "list_movies": "list_items",
            "collection_overrides": "collection_overrides",
            "followed_releases": "followed_releases",
        }
        connection = self.connect()
        try:
            counts = {
                name: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for name, table in table_map.items()
            }
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = [dict(row) for row in connection.execute("PRAGMA foreign_key_check").fetchall()]
            schema_version = int(connection.execute(
                "SELECT value FROM catalog_meta WHERE key='schema_version'"
            ).fetchone()[0])
            mismatches = {
                name: {"expected": int(expected_counts.get(name, 0)), "actual": counts[name]}
                for name in table_map
                if counts[name] != int(expected_counts.get(name, 0))
            }
            return {
                "passed": integrity == "ok" and not foreign_keys and not mismatches and schema_version == CATALOG_SCHEMA_VERSION,
                "schema_version": schema_version,
                "integrity": integrity,
                "foreign_key_errors": foreign_keys,
                "counts": counts,
                "mismatches": mismatches,
            }
        finally:
            connection.close()
