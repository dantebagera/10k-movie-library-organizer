import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
from services.catalog_writer_lease import CatalogWriterLease, CatalogWriterLeaseError


class LibraryIngestionOwnershipTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("CP_TEST_MODE") != "1":
            raise RuntimeError("Gate 2 tests require CP_TEST_MODE=1")
        cls.declared_root = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if cls.declared_root != temporary and temporary not in cls.declared_root.parents:
            raise RuntimeError("CP_TEST_ROOT must be inside system temporary storage")

    def test_reconciliation_algorithms_have_one_service_owner(self):
        repository = Path(__file__).resolve().parents[1]
        application = (repository / "app.py").read_text(encoding="utf-8")
        coordinator = (repository / "services" / "library_ingestion.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("class LibraryIngestionCoordinator", coordinator)
        self.assertIn("def reconcile_all_now", coordinator)
        self.assertIn("def reconcile_paths_now", coordinator)
        self.assertIn("def reconcile_directories_now", coordinator)
        self.assertNotIn("_library_reconcile_run_lock", application)
        self.assertNotIn("current_inventory = {}", application)
        self.assertIn("Delegate legacy private call sites", application)

    def test_qbittorrent_completion_uses_the_shared_targeted_owner_after_gate_six(self):
        source = Path(app.__file__).read_text(encoding="utf-8")
        completion_start = source.index("def _handle_completed_qbittorrent_imports")
        completion_end = source.index("\ndef ", completion_start + 5)
        completion = source[completion_start:completion_end]
        self.assertIn("_library_ingestion_coordinator()", completion)
        self.assertIn("reconcile_paths_now", completion)
        self.assertIn("reconcile_paths", completion)
        self.assertNotIn("_start_library_reconcile(force=True)", completion)

    def test_movie_view_upgrade_projection_does_not_restat_catalog_paths(self):
        original_cache = dict(app._maintenance_audit_cache)
        app._maintenance_audit_cache = {'generation': None, 'audit': None}
        repository = Mock()
        repository.generation.return_value = 7
        candidate = {
            'path': 'Z:/isolated/catalog-only.mkv',
            'quality_class': '720p',
            'filename_quality_claim': '1080p',
        }
        try:
            with patch("app._catalog_repository", return_value=repository), patch(
                "app._catalog_maintenance_candidates",
                return_value=[candidate],
            ), patch("app.os.path.isfile") as isfile:
                app._maintenance_audit_from_catalog()
            isfile.assert_not_called()
        finally:
            app._maintenance_audit_cache = original_cache

    def test_status_endpoint_is_read_only_and_redacts_configured_paths(self):
        with tempfile.TemporaryDirectory(dir=self.declared_root) as workspace:
            root = Path(workspace)
            movies = root / "movies"
            data = root / "user-data"
            movies.mkdir()
            data.mkdir()
            original = (
                app._movies_dirs,
                app._movies_dir,
                app._user_data_dir,
                app._library_ingestion_coordinator_instance,
            )
            app._movies_dirs = [str(movies)]
            app._movies_dir = str(movies)
            app._user_data_dir = str(data)
            app._library_ingestion_coordinator_instance = None
            try:
                app._catalog_repository_for(data)
                with patch("app._catalog_repository_for") as initialize, patch(
                    "app.os.walk"
                ) as walk, patch(
                    "app.probe_media_file"
                ) as probe, patch("app.urllib.request.urlopen") as provider:
                    response = app.app.test_client().get(
                        "/api/library/ingestion/status"
                    )
                payload_text = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(str(movies), payload_text)
                self.assertNotIn(str(data), payload_text)
                walk.assert_not_called()
                probe.assert_not_called()
                provider.assert_not_called()
                initialize.assert_not_called()
                self.assertTrue(response.get_json()["writer"]["lease_acquired"])
            finally:
                coordinator = app._library_ingestion_coordinator_instance
                if coordinator is not None:
                    coordinator.shutdown(timeout_seconds=2)
                (
                    app._movies_dirs,
                    app._movies_dir,
                    app._user_data_dir,
                    app._library_ingestion_coordinator_instance,
                ) = original

    def test_app_acquires_lease_before_catalog_repository_initialization(self):
        with tempfile.TemporaryDirectory(dir=self.declared_root) as workspace:
            data = Path(workspace) / "user-data"
            data.mkdir()
            database = data / ".catalog-test.sqlite"
            external = CatalogWriterLease(
                database,
                self.declared_root / "catalog-leases",
            ).acquire()
            original_user_data = app._user_data_dir
            app._user_data_dir = str(data)
            try:
                with self.assertRaises(CatalogWriterLeaseError):
                    app._catalog_repository_for(data)
                self.assertFalse(database.exists())
            finally:
                app._user_data_dir = original_user_data
                external.close()


if __name__ == "__main__":
    unittest.main()
