import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from services.library_startup_catchup import LibraryStartupCatchup
from services.media_file_facts import MediaFileFacts


class LibraryIngestionPathsTest(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CP_TEST_MODE") != "1":
            raise RuntimeError("Gate 2 tests require CP_TEST_MODE=1")
        declared = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if declared != temporary and temporary not in declared.parents:
            raise RuntimeError("CP_TEST_ROOT must be inside the system temporary directory")
        self.workspace = tempfile.TemporaryDirectory(dir=declared)
        self.root = Path(self.workspace.name)
        self.movies_a = self.root / "movies-a"
        self.movies_b = self.root / "movies-b"
        self.data = self.root / "user-data"
        self.movies_a.mkdir()
        self.movies_b.mkdir()
        self.data.mkdir()
        self.original = (
            app._movies_dirs,
            app._movies_dir,
            app._user_data_dir,
            app._tmdb_key,
            app._library_ingestion_coordinator_instance,
        )
        app._movies_dirs = [str(self.movies_a), str(self.movies_b)]
        app._movies_dir = str(self.movies_a)
        app._user_data_dir = str(self.data)
        app._tmdb_key = "isolated-test-key"
        app._library_ingestion_coordinator_instance = None

    def tearDown(self):
        coordinator = app._library_ingestion_coordinator_instance
        if coordinator is not None:
            coordinator.shutdown(timeout_seconds=2)
        (
            app._movies_dirs,
            app._movies_dir,
            app._user_data_dir,
            app._tmdb_key,
            app._library_ingestion_coordinator_instance,
        ) = self.original
        self.workspace.cleanup()

    @staticmethod
    def _probe(movie):
        stat_result = movie.stat()
        return MediaFileFacts(
            probe_status="ok",
            probe_size=stat_result.st_size,
            probe_modified_time=stat_result.st_mtime,
            quality_class="1080p",
            quality_source="measured",
        )

    def test_exact_path_reconciliation_never_walks_either_library_root(self):
        movie = self.movies_a / "Target.2026.1080p.mkv"
        movie.write_bytes(b"isolated fixture")
        os.utime(movie, (time.time() - 30, time.time() - 30))
        sentinel = self.movies_b / "must-not-be-seen.mkv"
        sentinel.write_bytes(b"sentinel")
        measured = self._probe(movie)

        with patch("app._file_copy_is_stable", return_value=True), patch(
            "app._migrate_metadata_path", return_value="matched"
        ), patch("app.probe_media_file", return_value=measured), patch(
            "services.library_ingestion.os.walk",
            side_effect=AssertionError("known path caused a filesystem walk"),
        ):
            result = app._library_ingestion_coordinator().reconcile_paths_now([movie])

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["matched"], 1)
        inventory = app.AppMetadataStore(self.data).get_library_inventory()
        self.assertIn(app._norm(str(movie)), inventory)
        self.assertNotIn(app._norm(str(sentinel)), inventory)

    def test_directory_reconciliation_walks_only_the_named_directory(self):
        bounded = self.movies_a / "Bounded Movie 2026"
        bounded.mkdir()
        movie = bounded / "Bounded.Movie.2026.mkv"
        movie.write_bytes(b"isolated fixture")
        os.utime(movie, (time.time() - 30, time.time() - 30))
        measured = self._probe(movie)
        walks = []

        def bounded_walk(directory):
            walks.append(os.path.abspath(str(directory)))
            yield str(bounded), [], [movie.name]

        with patch("app._file_copy_is_stable", return_value=True), patch(
            "app._migrate_metadata_path", return_value="matched"
        ), patch("app.probe_media_file", return_value=measured), patch(
            "services.library_ingestion.os.walk", side_effect=bounded_walk
        ):
            result = app._library_ingestion_coordinator().reconcile_directories_now(
                [bounded]
            )

        self.assertEqual(walks, [os.path.abspath(str(bounded))])
        self.assertEqual(result["matched"], 1)

    def test_path_outside_configured_roots_fails_before_stat_or_probe(self):
        external = self.root / "outside.mkv"
        external.write_bytes(b"outside")
        with patch("services.library_ingestion.os.stat") as stat_call, patch(
            "app.probe_media_file"
        ) as probe:
            with self.assertRaisesRegex(ValueError, "outside configured library roots"):
                app._library_ingestion_coordinator().reconcile_paths_now([external])
        stat_call.assert_not_called()
        probe.assert_not_called()

    def test_targeted_then_full_reconcile_is_idempotent_for_unchanged_file(self):
        movie = self.movies_a / "Parity.2026.1080p.mkv"
        movie.write_bytes(b"isolated fixture")
        os.utime(movie, (time.time() - 30, time.time() - 30))
        measured = self._probe(movie)

        with patch("app._file_copy_is_stable", return_value=True), patch(
            "app._migrate_metadata_path", return_value="matched"
        ), patch("app.probe_media_file", return_value=measured):
            targeted = app._library_ingestion_coordinator().reconcile_paths_now([movie])
            before = app.AppMetadataStore(self.data).snapshot()["files"][app._norm(str(movie))]
            full = app._library_ingestion_coordinator().reconcile_all_now()
            after = app.AppMetadataStore(self.data).snapshot()["files"][app._norm(str(movie))]

        self.assertEqual(targeted["matched"], 1)
        self.assertEqual(full["checked"], 0)
        self.assertEqual(before, after)

    def test_library_inventory_bookkeeping_never_advances_catalog_generations(self):
        store = app.AppMetadataStore(self.data)
        repository = store.catalog
        before = {
            "global": repository.generation(),
            "media": repository.generation("media"),
            "canonical": repository.catalog_meta("canonical_media_generation"),
        }
        inventory = {
            app._norm(str(self.movies_a / "Operational.2026.mkv")): {
                "path": str(self.movies_a / "Operational.2026.mkv"),
                "size": 123,
                "modified_time": 456,
            }
        }

        store.save_library_inventory(inventory)
        store.save_library_inventory(inventory)

        after = {
            "global": repository.generation(),
            "media": repository.generation("media"),
            "canonical": repository.catalog_meta("canonical_media_generation"),
        }
        self.assertEqual(after, before)
        self.assertTrue(store.has_library_inventory())
        self.assertEqual(store.get_library_inventory(), inventory)

    def test_populated_upgrade_startup_does_not_reprobe_or_reenrich_unchanged_card(self):
        movie = self.movies_a / "Legacy.Accepted.2009.1080p.mkv"
        movie.write_bytes(b"unchanged legacy fixture")
        os.utime(movie, (time.time() - 30, time.time() - 30))
        stat_result = movie.stat()
        store = app.AppMetadataStore(self.data)
        store.save_authority_state({"active_provider": "tmdb"})
        store.update_file_record(str(movie), {
            "filename": movie.name,
            "identity_status": "accepted",
            "identity_title": "Legacy Accepted",
            "identity_year": "2009",
            "identity_source": "manual_tmdb",
            "manual_lock": True,
            "metadata_status": "accepted",
            "metadata_accepted": True,
            "display_provider": "tmdb",
            "tmdb_id": "1208922",
            "enrichment_status": "complete",
            "ingest_status": "stable",
            "size": stat_result.st_size,
            "modified_time": stat_result.st_mtime,
        })
        store.save_library_inventory({
            app._norm(str(movie)): {
                "path": str(movie),
                "size": stat_result.st_size,
                "modified_time": stat_result.st_mtime,
            }
        })
        repository = store.catalog
        self.assertEqual(repository.catalog_meta(
            LibraryStartupCatchup.META_KEY, ""
        ), "")
        before = {
            "global": repository.generation(),
            "media": repository.generation("media"),
            "canonical": repository.catalog_meta("canonical_media_generation"),
        }

        with patch("app.probe_media_file") as probe, patch(
            "app._reconcile_library_path"
        ) as reconcile_path, patch("app.urllib.request.urlopen") as provider:
            result = LibraryStartupCatchup(
                lambda: [str(self.movies_a)],
                app._library_ingestion_coordinator(),
                repository,
            ).run_once()

        after = {
            "global": repository.generation(),
            "media": repository.generation("media"),
            "canonical": repository.catalog_meta("canonical_media_generation"),
        }
        self.assertEqual(result["result"]["checked"], 0)
        self.assertEqual(after, before)
        self.assertTrue(repository.catalog_meta(LibraryStartupCatchup.META_KEY, ""))
        probe.assert_not_called()
        reconcile_path.assert_not_called()
        provider.assert_not_called()

    def test_bounded_directory_reconciliation_prunes_deleted_file_only_in_scope(self):
        directory = self.movies_a / "Offline Delete"
        directory.mkdir()
        movie = directory / "Offline.Delete.2026.mkv"
        movie.write_bytes(b"isolated fixture")
        os.utime(movie, (time.time() - 30, time.time() - 30))
        outside = self.movies_b / "Preserve.2025.mkv"
        outside.write_bytes(b"outside fixture")
        os.utime(outside, (time.time() - 30, time.time() - 30))
        measured_movie = self._probe(movie)
        measured_outside = self._probe(outside)

        with patch("app._file_copy_is_stable", return_value=True), patch(
            "app._migrate_metadata_path", return_value="matched"
        ), patch(
            "app.probe_media_file",
            side_effect=[measured_movie, measured_outside],
        ):
            coordinator = app._library_ingestion_coordinator()
            coordinator.reconcile_paths_now([movie, outside])

        movie.unlink()
        result = coordinator.reconcile_directories_now(
            [directory],
            enrich_accepted=False,
        )
        snapshot = app.AppMetadataStore(self.data).snapshot()["files"]
        inventory = app.AppMetadataStore(self.data).get_library_inventory()

        self.assertEqual(result["removed"], 1)
        self.assertNotIn(app._norm(str(movie)), snapshot)
        self.assertNotIn(app._norm(str(movie)), inventory)
        self.assertIn(app._norm(str(outside)), snapshot)
        self.assertIn(app._norm(str(outside)), inventory)


if __name__ == "__main__":
    unittest.main()
