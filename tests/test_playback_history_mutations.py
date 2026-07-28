import tempfile
import unittest
from pathlib import Path

from services.catalog_repository import CatalogRepository
from services.playback_history import PlaybackHistoryService, PlaybackHistoryStore
from services.player_config import PlayerConfig


class UnwatchedCuration:
    def system_states_for_movie(self, movie):
        return {"watched": False, "watchlist": False}

    def set_system_list_state(self, system_type, movie, active):
        return {"active": active}


class PlaybackHistoryMutationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.old_path = self.root / "Alien.mkv"
        self.new_path = self.root / "Alien Renamed.mkv"
        self.copy_path = self.root / "Alien Copy.mkv"
        for path in (self.old_path, self.new_path, self.copy_path):
            path.write_bytes(b"fixture")
        self.old_key = str(self.old_path).lower()
        self.new_key = str(self.new_path).lower()
        self.copy_key = str(self.copy_path).lower()
        self.repository = CatalogRepository(
            self.root,
            database_path=self.root / "catalog.sqlite",
        )
        self.documents = {
            "app_metadata/files.json": {"files": {
                self.old_key: self.file_record(self.old_path, "348"),
            }},
            "app_metadata/tmdb_metadata.json": {"movies": {
                "348": {"tmdb_id": "348", "title": "Alien", "year": "1979"},
                "603": {"tmdb_id": "603", "title": "The Matrix", "year": "1999"},
            }},
            "app_metadata/manual_matches.json": {"matches": {}},
            "app_metadata/plex_metadata.json": {"files": {}},
        }
        self.repository.store.import_documents(self.documents, {})
        self.clock = 100.0
        self.history = PlaybackHistoryStore(
            self.repository.store,
            clock=lambda: self.clock,
        )

    def tearDown(self):
        self.repository.close()
        self.temporary.cleanup()

    @staticmethod
    def file_record(path, tmdb_id):
        return {
            "path": str(path),
            "filename": path.name,
            "identity_status": "accepted",
            "metadata_status": "accepted",
            "metadata_accepted": True,
            "tmdb_id": tmdb_id,
        }

    def save_progress(self, path_key, movie_key="tmdb:348", position=4000):
        row = self.history.begin_session(path_key, movie_key)
        self.history.save(
            path_key,
            row["revision"],
            position_ms=position,
            duration_ms=10000,
            completion_threshold=0.92,
        )

    def test_rename_migrates_progress_through_repository_owner(self):
        self.save_progress(self.old_key)

        changed = self.repository.migrate_path_records(
            self.old_key,
            self.new_key,
            self.new_path,
        )

        self.assertTrue(changed)
        self.assertIsNone(self.history.get(self.old_key))
        migrated = self.history.get(self.new_key)
        self.assertEqual(migrated["position_ms"], 4000)
        self.assertEqual(migrated["movie_key"], "tmdb:348")

    def test_remove_path_deletes_only_that_file_progress(self):
        self.repository.upsert_record(
            "app_metadata/files.json",
            self.copy_key,
            self.file_record(self.copy_path, "348"),
        )
        self.save_progress(self.old_key, position=3000)
        self.save_progress(self.copy_key, position=5000)

        self.repository.remove_path_records([self.old_key])

        self.assertIsNone(self.history.get(self.old_key))
        self.assertEqual(self.history.get(self.copy_key)["position_ms"], 5000)

    def test_metadata_correction_rebinds_movie_without_losing_file_progress(self):
        self.save_progress(self.old_key)

        self.repository.upsert_record(
            "app_metadata/manual_matches.json",
            self.old_key,
            {
                "path": str(self.old_path),
                "provider": "tmdb",
                "source": "manual",
                "tmdb_id": "603",
                "title": "The Matrix",
                "year": "1999",
                "accepted": True,
            },
        )
        self.repository.upsert_record(
            "app_metadata/files.json",
            self.old_key,
            {
                **self.file_record(self.old_path, "603"),
                "identity_title": "The Matrix",
                "identity_year": "1999",
                "identity_source": "manual_tmdb",
                "manual_lock": True,
                "manual_locked": True,
            },
        )

        corrected = self.history.get(self.old_key)
        self.assertEqual(corrected["position_ms"], 4000)
        self.assertEqual(corrected["movie_key"], "tmdb:603")

    def test_full_file_refresh_preserves_survivors_and_prunes_removed_paths(self):
        self.repository.upsert_record(
            "app_metadata/files.json",
            self.copy_key,
            self.file_record(self.copy_path, "348"),
        )
        self.save_progress(self.old_key, position=3000)
        self.save_progress(self.copy_key, position=5000)

        self.repository.replace_document(
            "app_metadata/files.json",
            {"files": {
                self.copy_key: self.file_record(self.copy_path, "348"),
            }},
        )

        self.assertIsNone(self.history.get(self.old_key))
        self.assertEqual(self.history.get(self.copy_key)["position_ms"], 5000)

    def test_duplicate_copies_keep_file_progress_but_collapse_presentation(self):
        self.repository.upsert_record(
            "app_metadata/files.json",
            self.copy_key,
            self.file_record(self.copy_path, "348"),
        )
        self.save_progress(self.old_key, position=3000)
        self.clock += 10
        self.save_progress(self.copy_key, position=6000)
        config = PlayerConfig({
            "minimum_resume_seconds": 2,
            "completion_threshold": 0.92,
        })
        service = PlaybackHistoryService(
            self.history,
            config,
            lambda: UnwatchedCuration(),
        )

        items = service.continue_watching()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["path_key"], self.copy_key)
        self.assertEqual(items[0]["position_ms"], 6000)
        self.assertEqual(self.history.get(self.old_key)["position_ms"], 3000)


if __name__ == "__main__":
    unittest.main()
