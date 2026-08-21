import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.catalog_store import (
    CATALOG_SCHEMA_VERSION,
    MEDIA_FILE_V8_COLUMNS,
    MEDIA_FILE_V9_COLUMNS,
    MEDIA_FILE_V11_COLUMNS,
    CatalogError,
    CatalogStore,
)
from tests.catalog_schema_fixtures import downgrade_catalog_to_v8


def digest_table(connection, table, columns=None):
    columns = columns or [
        row[1] for row in connection.execute(f"PRAGMA table_info({table})")
    ]
    query = f"SELECT {', '.join(columns)} FROM {table} ORDER BY {', '.join(columns)}"
    digest = hashlib.sha256()
    rows = 0
    for row in connection.execute(query):
        digest.update(json.dumps(
            list(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8"))
        digest.update(b"\n")
        rows += 1
    return rows, digest.hexdigest()


def digest_catalog_meta_without_schema_version(connection):
    digest = hashlib.sha256()
    rows = 0
    for row in connection.execute(
        "SELECT key, value FROM catalog_meta "
        "WHERE key<>'schema_version' ORDER BY key, value"
    ):
        digest.update(json.dumps(
            list(row), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8"))
        digest.update(b"\n")
        rows += 1
    return rows, digest.hexdigest()


class CatalogSchemaV9Test(unittest.TestCase):
    def documents(self):
        path = "e:/movies/the.monkey.2025.mkv"
        return {
            "app_metadata/files.json": {"files": {path: {
                "path": "E:/Movies/The Monkey 2025.mkv",
                "filename": "The.Monkey.2025.1080p.mkv",
                "size": 123,
                "modified_time": 456,
                "resolution": "720p",
                "identity_status": "accepted",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "tmdb_id": "1124620",
            }}},
            "app_metadata/tmdb_metadata.json": {"movies": {"1124620": {
                "tmdb_id": "1124620", "title": "The Monkey", "year": "2025",
                "writers": [], "keywords": [],
            }}},
            "app_metadata/plex_metadata.json": {"files": {}},
            "app_metadata/manual_matches.json": {"matches": {}},
            "user_lists.json": {"lists": []},
            "user_collections.json": {"overrides": {}},
            "followed_releases.json": {"movies": []},
        }

    def v8_store(self, root):
        store = CatalogStore(Path(root) / "catalog.sqlite")
        store.import_documents(self.documents(), {})
        downgrade_catalog_to_v8(store)
        return store

    def all_table_digests(self, connection):
        tables = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name <> 'playback_history' ORDER BY name"
            )
        ]
        return {
            table: (
                digest_catalog_meta_without_schema_version(connection)
                if table == "catalog_meta"
                else digest_table(
                    connection,
                    table,
                    MEDIA_FILE_V8_COLUMNS if table == "media_files" else None,
                )
            )
            for table in tables
        }

    def test_fresh_schema_has_exact_version_9_media_file_shape(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.initialize()
            connection = store.connect()
            try:
                version = int(connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0])
                columns = [
                    row[1] for row in connection.execute("PRAGMA table_info(media_files)")
                ]
                indexes = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    )
                }
            finally:
                connection.close()
        self.assertEqual(CATALOG_SCHEMA_VERSION, 11)
        self.assertEqual(version, 11)
        self.assertEqual(columns, MEDIA_FILE_V11_COLUMNS)
        self.assertIn("idx_media_files_facts_stale", indexes)

    def test_valid_v8_migration_is_data_shape_only_and_preserves_every_table(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.v8_store(root)
            connection = store.connect()
            try:
                before = self.all_table_digests(connection)
            finally:
                connection.close()

            with (
                patch("urllib.request.urlopen", side_effect=AssertionError("provider call")),
                patch("services.media_file_facts.probe_media_file", side_effect=AssertionError("file probe")),
            ):
                store.initialize()

            connection = store.connect()
            try:
                after = self.all_table_digests(connection)
                row = dict(connection.execute("SELECT * FROM media_files").fetchone())
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                connection.close()

        self.assertEqual(before, after)
        self.assertEqual(row["resolution"], "720p")
        self.assertEqual(row["probe_status"], "unprobed")
        self.assertEqual(row["file_facts_version"], 0)
        self.assertEqual(row["video_width"], 0)
        self.assertEqual(integrity, "ok")
        self.assertEqual(foreign_keys, [])
        self.assertEqual(store.last_migration_report["from_version"], 8)
        self.assertEqual(store.last_migration_report["to_version"], 11)

    def test_each_v9_failure_checkpoint_rolls_back_schema_and_all_data(self):
        checkpoints = (
            "before_v9_schema_changes",
            "during_v9_column_creation",
            "before_v9_index_creation",
            "before_v9_schema_version_update",
            "during_v9_final_validation",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as root:
                store = self.v8_store(root)
                connection = store.connect()
                try:
                    before = self.all_table_digests(connection)
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
                    columns = [
                        row[1] for row in connection.execute("PRAGMA table_info(media_files)")
                    ]
                    after = self.all_table_digests(connection)
                    partial_index = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='idx_media_files_facts_stale'"
                    ).fetchone()
                    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                finally:
                    connection.close()

                self.assertEqual(version, 8)
                self.assertEqual(columns, MEDIA_FILE_V8_COLUMNS)
                self.assertEqual(after, before)
                self.assertIsNone(partial_index)
                self.assertEqual(integrity, "ok")
                self.assertEqual(foreign_keys, [])
                self.assertIsNone(store.last_migration_report)

    def test_partial_version_9_column_on_version_8_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.v8_store(root)
            with store.transaction() as connection:
                connection.execute(
                    "ALTER TABLE media_files ADD COLUMN video_width INTEGER NOT NULL DEFAULT 0"
                )
            with self.assertRaisesRegex(CatalogError, "approved source"):
                store.initialize()
            connection = store.connect()
            try:
                version = int(connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0])
                columns = [
                    row[1] for row in connection.execute("PRAGMA table_info(media_files)")
                ]
            finally:
                connection.close()
        self.assertEqual(version, 8)
        self.assertIn("video_width", columns)
        self.assertNotIn("video_height", columns)

    def test_failure_after_v9_migration_before_initialize_completes_rolls_back(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.v8_store(root)
            connection = store.connect()
            try:
                before = self.all_table_digests(connection)
            finally:
                connection.close()

            with patch.object(
                store.canonical,
                "initialize",
                side_effect=RuntimeError("injected:post_v9_migration"),
            ):
                with self.assertRaisesRegex(RuntimeError, "post_v9_migration"):
                    store.initialize()

            connection = store.connect()
            try:
                version = int(connection.execute(
                    "SELECT value FROM catalog_meta WHERE key='schema_version'"
                ).fetchone()[0])
                columns = [
                    row[1] for row in connection.execute("PRAGMA table_info(media_files)")
                ]
                after = self.all_table_digests(connection)
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                connection.close()

        self.assertEqual(version, 8)
        self.assertEqual(columns, MEDIA_FILE_V8_COLUMNS)
        self.assertEqual(after, before)
        self.assertEqual(integrity, "ok")
        self.assertEqual(foreign_keys, [])
        self.assertIsNone(store.last_migration_report)

    def test_second_version_9_open_does_no_migration_or_probe(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self.documents(), {})
            connection = store.connect()
            try:
                before = self.all_table_digests(connection)
            finally:
                connection.close()
            with (
                patch.object(store, "_migrate_v8_to_v9") as migration,
                patch.object(store, "_migrate_v9_to_v10") as playback_migration,
                patch("services.media_file_facts.probe_media_file") as probe,
            ):
                store.initialize()
            connection = store.connect()
            try:
                after = self.all_table_digests(connection)
            finally:
                connection.close()
        migration.assert_not_called()
        playback_migration.assert_not_called()
        probe.assert_not_called()
        self.assertEqual(before, after)
        self.assertIsNone(store.last_migration_report)


if __name__ == "__main__":
    unittest.main()
