import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.catalog_store import CATALOG_SCHEMA_VERSION, CatalogError, CatalogStore
from tests.catalog_schema_fixtures import (
    downgrade_catalog_to_v7,
    use_historical_v7_credit_column_order,
)


def _digest_rows(connection, table, columns=None, where="", parameters=()):
    columns = columns or [
        row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    query = f"SELECT {', '.join(columns)} FROM {table}"
    if where:
        query += f" WHERE {where}"
    query += " ORDER BY " + ", ".join(columns)
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(query, parameters):
        digest.update(json.dumps(
            list(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


class CatalogSchemaV8Test(unittest.TestCase):
    def _documents(self):
        path = "e:/movies/writer-keyword.mkv"
        return {
            "app_metadata/files.json": {"files": {path: {
                "path": "E:/Movies/Writer Keyword.mkv",
                "filename": "Writer Keyword.mkv",
                "identity_status": "accepted",
                "identity_title": "Writer Keyword",
                "identity_year": "2026",
                "identity_source": "verified_tmdb",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "100",
            }}},
            "app_metadata/tmdb_metadata.json": {"movies": {"100": {
                "tmdb_id": "100",
                "title": "Writer Keyword",
                "year": "2026",
                "cast": [
                    {"id": "20", "name": "Multi Role", "character": "Lead"},
                ],
                "directors": [
                    {"id": "10", "name": "Director"},
                ],
                "writers": [
                    {"id": "20", "name": "Multi Role", "job": "Writer"},
                    {"id": "30", "name": "Dual Job", "job": "Screenplay"},
                    {"id": "30", "name": "Dual Job", "job": "Screenplay"},
                    {"id": "30", "name": "Dual Job", "job": "Story"},
                    {"name": "No Identifier", "job": "Novel"},
                    {"id": "40", "name": "Wrong Department", "job": "Producer"},
                    "malformed",
                    {"id": "50", "name": "Same Name", "job": "Writer"},
                    {"id": "51", "name": "Same Name", "job": "Writer"},
                ],
                "keywords": [
                    " Space  Opera ",
                    "space opera",
                    "Café",
                    "رحلة",
                    {"id": "900", "name": "Future"},
                    {},
                ],
                "updated_at": 50,
            }}},
            "app_metadata/plex_metadata.json": {"files": {}},
            "app_metadata/manual_matches.json": {"matches": {}},
            "user_lists.json": {"lists": []},
            "user_collections.json": {"overrides": {}},
            "followed_releases.json": {"movies": []},
        }

    def _v7_store(self, root):
        store = CatalogStore(Path(root) / "catalog.sqlite")
        store.import_documents(self._documents(), {})
        downgrade_catalog_to_v7(store)
        return store

    def test_fresh_database_creates_exact_version_8_search_schema(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("schema migration must remain offline"),
            ):
                store.initialize()
            connection = store.connect()
            try:
                version = int(connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0])
                credit_columns = [
                    row[1] for row in connection.execute("PRAGMA table_info(movie_credits)")
                ]
                keyword_columns = [
                    row[1] for row in connection.execute("PRAGMA table_info(keywords)")
                ]
                relationship_columns = [
                    row[1] for row in connection.execute("PRAGMA table_info(movie_keywords)")
                ]
            finally:
                connection.close()

        self.assertEqual(CATALOG_SCHEMA_VERSION, 8)
        self.assertEqual(version, 8)
        self.assertEqual(credit_columns, [
            "snapshot_key", "credit_type", "position", "person_key",
            "credited_name", "character", "profile_url", "job",
        ])
        self.assertEqual(keyword_columns, [
            "keyword_key", "tmdb_id", "name", "normalized_name",
        ])
        self.assertEqual(relationship_columns, [
            "snapshot_key", "position", "keyword_key",
        ])

    def test_realistic_v7_upgrade_preserves_existing_rows_and_projects_search_relations(self):
        with tempfile.TemporaryDirectory() as root:
            store = self._v7_store(root)
            connection = store.connect()
            try:
                source_json = connection.execute(
                    "SELECT source_json FROM provider_movie_snapshots WHERE snapshot_key='tmdb:100'"
                ).fetchone()[0]
                before_credits = _digest_rows(connection, "movie_credits")
                before_people = {
                    row["person_key"]: tuple(row)
                    for row in connection.execute("SELECT * FROM people ORDER BY person_key")
                }
                preserved_tables = [
                    row[0]
                    for row in connection.execute("""
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name NOT LIKE 'sqlite_%'
                          AND name NOT IN ('catalog_meta', 'people', 'movie_credits')
                        ORDER BY name
                    """)
                ]
                preserved = {
                    table: _digest_rows(connection, table)
                    for table in preserved_tables
                }
                preserved_meta = _digest_rows(
                    connection,
                    "catalog_meta",
                    where="key <> 'schema_version'",
                )
            finally:
                connection.close()

            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("schema migration must remain offline"),
            ):
                store.initialize()
            report = store.last_migration_report
            connection = store.connect()
            try:
                version = int(connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0])
                after_credits = _digest_rows(
                    connection,
                    "movie_credits",
                    [
                        "snapshot_key", "credit_type", "position", "person_key",
                        "credited_name", "character", "profile_url",
                    ],
                    "credit_type IN ('cast', 'director')",
                )
                writers = [
                    tuple(row)
                    for row in connection.execute("""
                        SELECT mc.position, p.person_key, p.name, mc.job
                        FROM movie_credits mc
                        JOIN people p ON p.person_key=mc.person_key
                        WHERE mc.snapshot_key='tmdb:100' AND mc.credit_type='writer'
                        ORDER BY mc.position
                    """)
                ]
                keywords = [
                    tuple(row)
                    for row in connection.execute("""
                        SELECT mk.position, k.tmdb_id, k.name, k.normalized_name
                        FROM movie_keywords mk
                        JOIN keywords k ON k.keyword_key=mk.keyword_key
                        WHERE mk.snapshot_key='tmdb:100'
                        ORDER BY mk.position
                    """)
                ]
                after_source_json = connection.execute(
                    "SELECT source_json FROM provider_movie_snapshots WHERE snapshot_key='tmdb:100'"
                ).fetchone()[0]
                after_people = {
                    row["person_key"]: tuple(row)
                    for row in connection.execute("SELECT * FROM people ORDER BY person_key")
                }
                after_preserved = {
                    table: _digest_rows(connection, table)
                    for table in preserved
                }
                after_preserved_meta = _digest_rows(
                    connection,
                    "catalog_meta",
                    where="key <> 'schema_version'",
                )
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                connection.close()

        self.assertEqual(version, 8)
        self.assertEqual(after_credits, before_credits)
        self.assertEqual(source_json, after_source_json)
        self.assertEqual(after_preserved, preserved)
        self.assertEqual(after_preserved_meta, preserved_meta)
        for key, row in before_people.items():
            self.assertEqual(after_people[key], row)
        self.assertEqual(writers, [
            (0, "tmdb:20", "Multi Role", "Writer"),
            (1, "tmdb:30", "Dual Job", "Screenplay"),
            (3, "tmdb:30", "Dual Job", "Story"),
            (4, writers[3][1], "No Identifier", "Novel"),
            (7, "tmdb:50", "Same Name", "Writer"),
            (8, "tmdb:51", "Same Name", "Writer"),
        ])
        self.assertTrue(writers[3][1].startswith("tmdb-credit:"))
        self.assertEqual(keywords, [
            (0, "", "Space  Opera", "space opera"),
            (2, "", "Café", "café"),
            (3, "", "رحلة", "رحلة"),
            (4, "900", "Future", "future"),
        ])
        self.assertEqual(report["writer_entries_processed"], 9)
        self.assertEqual(report["writer_entries_inserted"], 6)
        self.assertEqual(report["writer_entries_deduplicated"], 1)
        self.assertEqual(report["writer_entries_rejected"], 2)
        self.assertEqual(report["keyword_entries_processed"], 6)
        self.assertEqual(report["keyword_relationships_inserted"], 4)
        self.assertEqual(report["keyword_entries_deduplicated"], 1)
        self.assertEqual(report["keyword_entries_rejected"], 1)
        self.assertEqual(integrity, "ok")
        self.assertEqual(foreign_keys, [])

    def test_historical_v7_credit_column_order_migrates_without_data_change(self):
        with tempfile.TemporaryDirectory() as root:
            store = self._v7_store(root)
            use_historical_v7_credit_column_order(store)
            connection = store.connect()
            try:
                historical_columns = [
                    row[1] for row in connection.execute(
                        "PRAGMA table_info(movie_credits)"
                    )
                ]
                before_credits = _digest_rows(
                    connection,
                    "movie_credits",
                    [
                        "snapshot_key", "credit_type", "position", "person_key",
                        "credited_name", "character", "profile_url",
                    ],
                )
            finally:
                connection.close()

            with patch(
                "urllib.request.urlopen",
                side_effect=AssertionError("schema migration must remain offline"),
            ):
                store.initialize()

            connection = store.connect()
            try:
                version = int(connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0])
                after_credits = _digest_rows(
                    connection,
                    "movie_credits",
                    [
                        "snapshot_key", "credit_type", "position", "person_key",
                        "credited_name", "character", "profile_url",
                    ],
                    "credit_type IN ('cast', 'director')",
                )
                integrity = connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
                foreign_keys = connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(historical_columns, [
            "snapshot_key", "credit_type", "position", "person_key",
            "character", "profile_url", "credited_name",
        ])
        self.assertEqual(version, 8)
        self.assertEqual(after_credits, before_credits)
        self.assertEqual(integrity, "ok")
        self.assertEqual(foreign_keys, [])

    def test_missing_and_empty_writer_keyword_arrays_are_counted_without_aborting(self):
        with tempfile.TemporaryDirectory() as root:
            store = self._v7_store(root)
            with store.transaction() as connection:
                movie_key = connection.execute(
                    "SELECT movie_key FROM canonical_movies LIMIT 1"
                ).fetchone()[0]
                values = (
                    ("tmdb:101", "101", json.dumps({"writers": [], "keywords": []})),
                    ("tmdb:102", "102", json.dumps({})),
                )
                for snapshot_key, provider_id, source_json in values:
                    connection.execute("""
                        INSERT INTO provider_movie_snapshots(
                            snapshot_key, movie_key, provider, provider_id, source_json
                        ) VALUES(?, ?, 'tmdb', ?, ?)
                    """, (snapshot_key, movie_key, provider_id, source_json))

            store.initialize()
            report = store.last_migration_report

        self.assertGreaterEqual(report["writer_snapshots_empty"], 1)
        self.assertGreaterEqual(report["keyword_snapshots_empty"], 1)
        self.assertGreaterEqual(report["writer_snapshots_missing"], 1)
        self.assertGreaterEqual(report["keyword_snapshots_missing"], 1)

    def test_opening_version_8_again_is_a_relational_no_op(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})
            connection = store.connect()
            try:
                before = {
                    table: _digest_rows(connection, table)
                    for table in (
                        "people", "movie_credits", "keywords", "movie_keywords",
                        "provider_movie_snapshots",
                    )
                }
            finally:
                connection.close()

            with patch.object(store, "_migrate_v7_to_v8") as migration:
                store.initialize()
            connection = store.connect()
            try:
                after = {
                    table: _digest_rows(connection, table)
                    for table in before
                }
            finally:
                connection.close()

        migration.assert_not_called()
        self.assertIsNone(store.last_migration_report)
        self.assertEqual(after, before)

    def test_version_8_constraints_reject_invalid_credit_and_duplicate_keyword_identity(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})
            connection = store.connect()
            try:
                snapshot_key = "tmdb:100"
                person_key = connection.execute(
                    "SELECT person_key FROM people ORDER BY person_key LIMIT 1"
                ).fetchone()[0]
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("""
                        INSERT INTO movie_credits(
                            snapshot_key, credit_type, position, person_key,
                            credited_name, character, profile_url, job
                        ) VALUES(?, 'producer', 99, ?, '', '', '', '')
                    """, (snapshot_key, person_key))
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("""
                        INSERT INTO keywords(keyword_key, tmdb_id, name, normalized_name)
                        VALUES('different-key', '', 'Different Display', 'space opera')
                    """)
                connection.rollback()
            finally:
                connection.close()

    def test_unknown_newer_missing_and_partial_schemas_fail_closed(self):
        cases = ("older", "newer", "missing", "partial")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as root:
                store = self._v7_store(root)
                with store.transaction() as connection:
                    if case == "older":
                        connection.execute(
                            "UPDATE catalog_meta SET value='5' WHERE key='schema_version'"
                        )
                    elif case == "newer":
                        connection.execute(
                            "UPDATE catalog_meta SET value='9' WHERE key='schema_version'"
                        )
                    elif case == "missing":
                        connection.execute(
                            "DELETE FROM catalog_meta WHERE key='schema_version'"
                        )
                    else:
                        connection.execute(
                            "CREATE TABLE keywords(keyword_key TEXT PRIMARY KEY)"
                        )
                with self.assertRaises(CatalogError):
                    store.initialize()
                connection = store.connect()
                try:
                    objects = {
                        row[0] for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    credit_columns = [
                        row[1] for row in connection.execute("PRAGMA table_info(movie_credits)")
                    ]
                finally:
                    connection.close()
                self.assertNotIn("movie_credits_v8_new", objects)
                self.assertNotIn("job", credit_columns)
                if case != "partial":
                    self.assertNotIn("keywords", objects)

    def test_each_injected_migration_failure_rolls_back_every_change(self):
        checkpoints = (
            "before_table_creation",
            "during_existing_credit_copy",
            "during_writer_backfill",
            "during_keyword_backfill",
            "before_index_creation",
            "before_schema_version_update",
            "during_final_validation",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as root:
                store = self._v7_store(root)
                connection = store.connect()
                try:
                    before_credits = _digest_rows(connection, "movie_credits")
                    before_people = _digest_rows(connection, "people")
                    before_snapshots = _digest_rows(connection, "provider_movie_snapshots")
                finally:
                    connection.close()

                def fail_at(name):
                    if name == checkpoint:
                        raise RuntimeError(f"injected:{name}")

                with patch.object(store, "_migration_checkpoint", side_effect=fail_at):
                    with self.assertRaisesRegex(RuntimeError, f"injected:{checkpoint}"):
                        store.initialize()

                connection = store.connect()
                try:
                    version = int(connection.execute(
                        "SELECT value FROM catalog_meta WHERE key='schema_version'"
                    ).fetchone()[0])
                    objects = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    after_credits = _digest_rows(connection, "movie_credits")
                    after_people = _digest_rows(connection, "people")
                    after_snapshots = _digest_rows(connection, "provider_movie_snapshots")
                    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                finally:
                    connection.close()

                self.assertEqual(version, 7)
                self.assertEqual(after_credits, before_credits)
                self.assertEqual(after_people, before_people)
                self.assertEqual(after_snapshots, before_snapshots)
                self.assertNotIn("movie_credits_v8_new", objects)
                self.assertNotIn("keywords", objects)
                self.assertNotIn("movie_keywords", objects)
                self.assertEqual(integrity, "ok")
                self.assertEqual(foreign_keys, [])

    def test_failure_after_migration_validation_still_rolls_back_and_emits_no_report(self):
        with tempfile.TemporaryDirectory() as root:
            store = self._v7_store(root)
            connection = store.connect()
            try:
                before_credits = _digest_rows(connection, "movie_credits")
            finally:
                connection.close()

            with patch.object(
                store.canonical,
                "initialize",
                side_effect=RuntimeError("injected:post-migration-initialize"),
            ):
                with self.assertRaisesRegex(RuntimeError, "post-migration-initialize"):
                    store.initialize()

            connection = store.connect()
            try:
                version = int(connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0])
                after_credits = _digest_rows(connection, "movie_credits")
                objects = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            finally:
                connection.close()

        self.assertEqual(version, 7)
        self.assertEqual(after_credits, before_credits)
        self.assertNotIn("keywords", objects)
        self.assertIsNone(store.last_migration_report)

    def test_repeat_keyword_ingestion_upgrades_name_only_identity_without_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})
            with store.transaction() as connection:
                store.canonical._replace_snapshot_keywords(
                    connection,
                    "tmdb:100",
                    [{"id": "901", "name": "Café"}],
                )
                store.canonical._replace_snapshot_keywords(
                    connection,
                    "tmdb:100",
                    [{"id": "901", "name": "Café"}],
                )
            connection = store.connect()
            try:
                rows = connection.execute("""
                    SELECT k.tmdb_id, k.name, k.normalized_name
                    FROM movie_keywords mk
                    JOIN keywords k ON k.keyword_key=mk.keyword_key
                    WHERE mk.snapshot_key='tmdb:100'
                """).fetchall()
            finally:
                connection.close()

        self.assertEqual([tuple(row) for row in rows], [("901", "Café", "café")])


if __name__ == "__main__":
    unittest.main()
