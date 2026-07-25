import json
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from services.catalog_repository import CatalogRepository

from tools.catalog_migration_backup import (
    BackupError,
    create_backup,
    restore_backup,
    verify_backup,
)
from tools.build_shadow_catalog import build_shadow_catalog


class CatalogMigrationBackupTest(unittest.TestCase):
    def _project(self, root, external_user_data=True):
        project = Path(root) / "project"
        project.mkdir()
        user_data = Path(root) / "user-data" if external_user_data else project / "data"
        metadata = user_data / "app_metadata"
        metadata.mkdir(parents=True)
        (project / "package.json").write_text(json.dumps({"version": "2.7.0"}), encoding="utf-8")
        (project / "config.json").write_text(json.dumps({
            "user_data_dir": str(user_data),
            "tmdb_key": "secret-key",
        }), encoding="utf-8")
        (metadata / "files.json").write_text(json.dumps({"files": {"one": {}, "two": {}}}), encoding="utf-8")
        (metadata / "tmdb_metadata.json").write_text(json.dumps({"movies": {"1": {}}}), encoding="utf-8")
        (metadata / "plex_metadata.json").write_text(json.dumps({"files": {"one": {}}}), encoding="utf-8")
        (metadata / "manual_matches.json").write_text(json.dumps({"matches": {"one": {}}}), encoding="utf-8")
        (user_data / "user_lists.json").write_text(json.dumps({
            "lists": [{"id": "watched", "movies": [{"tmdb_id": "1"}]}],
        }), encoding="utf-8")
        (user_data / "user_collections.json").write_text(json.dumps({"overrides": {"10": {}}}), encoding="utf-8")
        (user_data / "followed_releases.json").write_text(json.dumps({"movies": [{"tmdb_id": "2"}]}), encoding="utf-8")
        qbt = user_data / "qbittorrent"
        qbt.mkdir()
        (qbt / "jobs.json").write_text(json.dumps({"jobs": {"hash": {}}}), encoding="utf-8")
        (qbt / "runtime.json").write_text(json.dumps({"version": "5.2.2"}), encoding="utf-8")
        (qbt / "versions").mkdir()
        (qbt / "versions" / "qbittorrent.exe").write_bytes(b"large runtime")
        performance_backup = user_data / "catalog-performance-final" / "backups"
        performance_backup.mkdir(parents=True)
        (performance_backup / "recursive.zip").write_bytes(b"do not recursively archive backups")
        return project, user_data

    def test_backup_uses_configured_user_data_and_records_counts(self):
        with tempfile.TemporaryDirectory() as root:
            project, _ = self._project(root)
            archive, manifest = create_backup(
                project,
                Path(root) / "backups",
                now=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
            )

            names = {item["archive_path"] for item in manifest["files"]}

        self.assertEqual(archive.name, "cp-catalog-migration-20260713T100000Z.zip")
        self.assertIn("project/config.json", names)
        self.assertIn("user-data/app_metadata/files.json", names)
        self.assertIn("user-data/qbittorrent/jobs.json", names)
        self.assertNotIn("user-data/qbittorrent/versions/qbittorrent.exe", names)
        self.assertNotIn("user-data/catalog-performance-final/backups/recursive.zip", names)
        self.assertEqual(manifest["semantic_counts"]["file_records"], 2)
        self.assertEqual(manifest["semantic_counts"]["manual_matches"], 1)
        self.assertEqual(manifest["semantic_counts"]["list_movies"], 1)
        self.assertEqual(manifest["semantic_counts"]["qbittorrent_jobs"], 1)

    def test_verify_checks_hashes_and_semantic_counts(self):
        with tempfile.TemporaryDirectory() as root:
            project, _ = self._project(root)
            archive, expected = create_backup(project, Path(root) / "backups")

            verified = verify_backup(archive)

        self.assertEqual(verified["totals"], expected["totals"])
        self.assertEqual(verified["semantic_counts"], expected["semantic_counts"])

    def test_backup_includes_consistent_sqlite_catalog_snapshot(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"LOCALAPPDATA": str(Path(root) / "local")}):
            project, user_data = self._project(root)
            asset = Path(root) / "local" / "Cinema Paradiso" / "Metadata" / "assets" / "aa" / ("a" * 64)
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"local artwork")
            repository = CatalogRepository(user_data)
            try:
                repository.activate_from_json()
                with repository.store.transaction() as connection:
                    connection.execute("""
                        INSERT INTO media_assets(
                            asset_key,asset_type,provider,source_url,local_path,checksum,
                            status,retention_class,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    """, ("asset", "poster", "custom", "https://local.invalid/asset", str(asset),
                          "a" * 64, "ready", "custom", 1, 1))
                archive, manifest = create_backup(project, Path(root) / "backups")
            finally:
                repository.close(flush=False)
            names = {item["archive_path"] for item in manifest["files"]}
            verified = verify_backup(archive)

        self.assertIn("catalog/catalog.sqlite", names)
        self.assertIn(f"metadata/assets/aa/{'a' * 64}", names)
        self.assertEqual(verified["semantic_counts"]["metadata_asset_files"], 1)
        self.assertEqual(verified["semantic_counts"]["metadata_asset_bytes"], len(b"local artwork"))
        self.assertEqual(verified["semantic_counts"]["file_records"], 2)
        self.assertEqual(verified["semantic_counts"]["user_lists"], 1)

    def test_backup_generates_rollback_json_from_sql_authority(self):
        with tempfile.TemporaryDirectory() as root, patch.dict("os.environ", {"LOCALAPPDATA": str(Path(root) / "local")}):
            project, user_data = self._project(root)
            repository = CatalogRepository(user_data)
            try:
                repository.activate_from_json()
                repository.upsert_record("app_metadata/files.json", "three", {"path": "E:/Movies/Three.mkv"})
                archive, manifest = create_backup(project, Path(root) / "backups")
                shadow_path, report = build_shadow_catalog(archive, Path(root) / "shadow.sqlite")
                with zipfile.ZipFile(archive) as contents:
                    rollback_files = json.loads(contents.read("user-data/app_metadata/files.json"))
            finally:
                repository.close(flush=False)
            self.assertEqual(manifest["semantic_counts"]["file_records"], 3)
            self.assertIn("three", rollback_files["files"])
            self.assertTrue(shadow_path.is_file())
            self.assertTrue(report["passed"])

    def test_shadow_imports_all_direct_metadata_documents_and_movie_overrides(self):
        with tempfile.TemporaryDirectory() as root:
            project, user_data = self._project(root)
            metadata = user_data / "app_metadata"
            (metadata / "metadata_authority.json").write_text(
                json.dumps({"authority": "fixture"}),
                encoding="utf-8",
            )
            (metadata / "poster_overrides.json").write_text(json.dumps({
                "overrides": [{
                    "id": "poster-1",
                    "identity": {"tmdb_id": "1", "title": "Fixture", "year": "2026"},
                    "identity_keys": ["tmdb:1"],
                    "poster_url": "/api/library/posters/image/fixture.jpg",
                    "source": "upload",
                    "locked": True,
                    "updated_at": 10,
                }],
            }), encoding="utf-8")

            archive, _ = create_backup(project, Path(root) / "backups")
            shadow_path, report = build_shadow_catalog(archive, Path(root) / "shadow.sqlite")
            connection = sqlite3.connect(shadow_path)
            try:
                source_names = {
                    row[0]
                    for row in connection.execute("SELECT name FROM source_documents")
                }
                override_count = connection.execute(
                    "SELECT COUNT(*) FROM movie_overrides"
                ).fetchone()[0]
                identity_key_count = connection.execute(
                    "SELECT COUNT(*) FROM movie_override_identity_keys"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertTrue(report["passed"])
        self.assertIn("app_metadata/metadata_authority.json", source_names)
        self.assertIn("app_metadata/poster_overrides.json", source_names)
        self.assertEqual(override_count, 1)
        self.assertEqual(identity_key_count, 1)

    def test_backup_requires_a_passing_temporary_shadow_catalog(self):
        with tempfile.TemporaryDirectory() as root:
            project, _ = self._project(root)
            with patch("tools.build_shadow_catalog.build_shadow_catalog", return_value=(Path(root) / "shadow.sqlite", {"passed": True})) as shadow:
                create_backup(project, Path(root) / "backups")

        shadow.assert_called_once()

    def test_verify_rejects_modified_archived_state(self):
        with tempfile.TemporaryDirectory() as root:
            project, _ = self._project(root)
            archive, _ = create_backup(project, Path(root) / "backups")
            tampered = Path(root) / "tampered.zip"
            with zipfile.ZipFile(archive, "r") as source, zipfile.ZipFile(tampered, "w") as target:
                for info in source.infolist():
                    payload = source.read(info.filename)
                    if info.filename == "user-data/app_metadata/files.json":
                        payload = b'{"files": {}}'
                    target.writestr(info, payload)

            with self.assertRaisesRegex(BackupError, "size mismatch|hash mismatch"):
                verify_backup(tampered)

    def test_restore_writes_only_to_empty_rehearsal_directory(self):
        with tempfile.TemporaryDirectory() as root:
            project, _ = self._project(root)
            archive, manifest = create_backup(project, Path(root) / "backups")
            destination = Path(root) / "restore"

            restored, restored_manifest = restore_backup(archive, destination)

            self.assertEqual(restored, destination.resolve())
            self.assertEqual(restored_manifest["semantic_counts"], manifest["semantic_counts"])
            self.assertTrue((destination / "project" / "config.json").is_file())
            self.assertTrue((destination / "user-data" / "app_metadata" / "files.json").is_file())
            with self.assertRaisesRegex(BackupError, "not empty"):
                restore_backup(archive, destination)


if __name__ == "__main__":
    unittest.main()
