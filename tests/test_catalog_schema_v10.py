import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.catalog_store import (
    CATALOG_SCHEMA_VERSION,
    PLAYBACK_HISTORY_COLUMNS,
    CatalogStore,
)
from tests.catalog_schema_fixtures import downgrade_catalog_to_v9


def table_digest(connection, table):
    columns = [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
    digest = hashlib.sha256()
    count = 0
    for row in connection.execute(
        f"SELECT {', '.join(columns)} FROM {table} ORDER BY {', '.join(columns)}"
    ):
        digest.update(json.dumps(list(row), separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


class CatalogSchemaV10Tests(unittest.TestCase):
    @staticmethod
    def store_with_movie(root):
        store = CatalogStore(Path(root) / "catalog.sqlite")
        store.import_documents({
            "app_metadata/files.json": {"files": {
                "e:\\movies\\alien.mkv": {
                    "path": "E:\\Movies\\Alien.mkv",
                    "filename": "Alien.mkv",
                    "identity_status": "accepted",
                    "metadata_status": "accepted",
                    "metadata_accepted": True,
                    "tmdb_id": "348",
                },
            }},
            "app_metadata/tmdb_metadata.json": {"movies": {
                "348": {"tmdb_id": "348", "title": "Alien", "year": "1979"},
            }},
        }, {})
        return store

    def test_fresh_catalog_has_exact_additive_playback_schema(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.initialize()
            connection = store.connect()
            try:
                version = store._catalog_schema_version(connection)
                columns = store._table_columns(connection, "playback_history")
                indexes = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='index'"
                    )
                }
                foreign_keys = connection.execute(
                    "PRAGMA foreign_key_list(playback_history)"
                ).fetchall()
            finally:
                connection.close()

        self.assertEqual(CATALOG_SCHEMA_VERSION, 10)
        self.assertEqual(version, 10)
        self.assertEqual(columns, PLAYBACK_HISTORY_COLUMNS)
        self.assertIn("idx_playback_history_movie", indexes)
        self.assertIn("idx_playback_history_recent", indexes)
        self.assertEqual(foreign_keys, [])

    def test_version_9_upgrade_preserves_existing_tables_and_adds_empty_history(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.store_with_movie(root)
            downgrade_catalog_to_v9(store)
            connection = store.connect()
            try:
                before = table_digest(connection, "media_files")
            finally:
                connection.close()

            store.initialize()

            connection = store.connect()
            try:
                after = table_digest(connection, "media_files")
                history_count = connection.execute(
                    "SELECT COUNT(*) FROM playback_history"
                ).fetchone()[0]
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                connection.close()

        self.assertEqual(before, after)
        self.assertEqual(history_count, 0)
        self.assertEqual(integrity, "ok")
        self.assertEqual(foreign_keys, [])
        self.assertEqual(store.last_migration_report["from_version"], 9)
        self.assertEqual(store.last_migration_report["to_version"], 10)

    def test_every_v10_failure_checkpoint_rolls_back_table_version_and_data(self):
        checkpoints = (
            "before_v10_playback_history",
            "before_v10_schema_version_update",
            "during_v10_final_validation",
        )
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as root:
                store = self.store_with_movie(root)
                downgrade_catalog_to_v9(store)
                connection = store.connect()
                try:
                    before = table_digest(connection, "media_files")
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
                    version = store._catalog_schema_version(connection)
                    history = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='playback_history'"
                    ).fetchone()
                    after = table_digest(connection, "media_files")
                finally:
                    connection.close()
                self.assertEqual(version, 9)
                self.assertIsNone(history)
                self.assertEqual(before, after)
                self.assertIsNone(store.last_migration_report)

    def test_second_version_10_open_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            store = self.store_with_movie(root)
            with patch.object(store, "_migrate_v9_to_v10") as migration:
                store.initialize()
        migration.assert_not_called()
        self.assertIsNone(store.last_migration_report)


if __name__ == "__main__":
    unittest.main()
