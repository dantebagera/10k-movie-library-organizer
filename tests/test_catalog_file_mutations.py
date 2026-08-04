import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from services.media_file_facts import MediaFileFacts


class CatalogFileMutationTest(unittest.TestCase):
    def test_delete_preview_reports_complete_folder_without_mutating_it(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_user_data = app._user_data_dir
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_folder = Path(movies_tmp) / "Project Hail Mary (2026)"
            movie_folder.mkdir()
            movie_path = movie_folder / "Project.Hail.Mary.2026.mkv"
            movie_path.write_bytes(b"movie")
            (movie_folder / "Project.Hail.Mary.2026.srt").write_text("subtitles", encoding="utf-8")
            try:
                app._movies_dirs = [movies_tmp]
                app._movies_dir = movies_tmp
                app._user_data_dir = data_tmp
                response = app.app.test_client().post("/api/delete", json={
                    "paths": [str(movie_path)],
                    "trash": True,
                    "preview": True,
                })
                movie_still_exists = movie_path.exists()
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data

        self.assertEqual(response.status_code, 200)
        self.assertTrue(movie_still_exists)
        self.assertEqual(response.get_json()["folder_count"], 1)
        self.assertEqual(response.get_json()["actions"][0]["target"], str(movie_folder.resolve()))

    def test_fix_path_refuses_to_move_a_correctly_nested_movie_folder_outside_library(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_plex_cache = dict(app._plex_cache)
        original_plex_by_filename = dict(app._plex_matched_by_fname)
        with tempfile.TemporaryDirectory() as parent_tmp:
            library_root = Path(parent_tmp) / "Library"
            movie_folder = library_root / "Example Movie (2020)"
            movie_folder.mkdir(parents=True)
            movie_path = movie_folder / "Example.Movie.2020.mkv"
            movie_path.write_bytes(b"movie")
            escaped_folder = Path(parent_tmp) / movie_folder.name
            try:
                app._movies_dirs = [str(library_root)]
                app._movies_dir = str(library_root)
                app._plex_cache = {}
                app._plex_matched_by_fname = {}
                with patch("app._migrate_library_path") as migrate, patch("app._plex_rescan") as plex_rescan:
                    response = app.app.test_client().post("/api/fix-path", json={"path": str(movie_path)})
                movie_still_exists = movie_path.exists()
                escaped_exists = escaped_folder.exists()
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._plex_cache = original_plex_cache
                app._plex_matched_by_fname = original_plex_by_filename

        self.assertEqual(response.status_code, 409)
        self.assertIn("already at the correct depth", response.get_json()["error"])
        self.assertTrue(movie_still_exists)
        self.assertFalse(escaped_exists)
        migrate.assert_not_called()
        plex_rescan.assert_not_called()

    def test_rename_and_delete_refresh_catalog_without_rescan(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_user_data = app._user_data_dir
        original_library_cache = dict(app._library_cache)
        original_plex_token = app._plex_token
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_path = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie_path.write_bytes(b"movie")
            store = app.AppMetadataStore(Path(data_tmp))
            store.apply_tmdb_match(str(movie_path), {
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
            })
            store.update_file_record(str(movie_path), {
                "filename": movie_path.name,
                "library_root": movies_tmp,
                "parsed_title": "Alien",
                "parsed_year": "1979",
                "resolution": "1080p",
                "rip_source": "BluRay",
                "size": movie_path.stat().st_size,
            })
            try:
                app._movies_dirs = [movies_tmp]
                app._movies_dir = movies_tmp
                app._user_data_dir = data_tmp
                app._library_cache = {}
                app._plex_token = ""
                client = app.app.test_client()

                initial = client.get("/api/library").get_json()
                measured = MediaFileFacts(
                    video_width=1800,
                    video_height=960,
                    video_codec="HEVC",
                    video_profile="Main 10",
                    video_bit_depth=10,
                    duration_ms=5_780_917,
                    audio_codec="AAC",
                    audio_channels=2,
                    filename_quality_claim="1080p",
                    quality_class="1080p",
                    quality_source="measured",
                    quality_nonstandard=True,
                    probe_status="ok",
                    probe_size=movie_path.stat().st_size,
                    probe_modified_time=movie_path.stat().st_mtime,
                )
                with patch("app._plex_rescan"), patch(
                    "app.probe_media_file",
                    return_value=measured,
                ) as probe:
                    renamed_response = client.post("/api/rename-file", json={
                        "path": str(movie_path),
                        "title": "Alien",
                        "year": "1979",
                    })
                renamed_path = Path(renamed_response.get_json()["new_path"])
                after_rename = client.get("/api/library").get_json()
                deleted_response = client.post("/api/delete", json={"path": str(renamed_path), "trash": False})
                after_delete = client.get("/api/library").get_json()
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data
                app._library_cache = original_library_cache
                app._plex_token = original_plex_token

        self.assertEqual(initial["count"], 1)
        self.assertEqual(renamed_response.status_code, 200)
        self.assertEqual(after_rename["count"], 1)
        self.assertEqual(after_rename["items"][0]["path"], str(renamed_path))
        self.assertEqual(after_rename["items"][0]["video_width"], 1800)
        self.assertEqual(after_rename["items"][0]["video_height"], 960)
        self.assertEqual(after_rename["items"][0]["quality_class"], "1080p")
        self.assertEqual(
            after_rename["items"][0]["quality_display"],
            "1080-class - 1800 x 960",
        )
        probe.assert_called_once_with(str(renamed_path))
        self.assertEqual(deleted_response.status_code, 200)
        self.assertEqual(after_delete["count"], 0)

    def test_only_shared_helpers_own_path_metadata_mutation(self):
        source = Path(app.__file__).read_text(encoding="utf-8")

        self.assertEqual(source.count(".migrate_path_records("), 2)
        self.assertNotIn("_metadata_store().remove_path_records(", source)
        self.assertIn("return _delete_library_file(path, use_trash=True)", source)
        mutation_source = (Path(app.__file__).parent / "services" / "library_mutations.py").read_text(encoding="utf-8")
        self.assertEqual(mutation_source.count("metadata_store.remove_path_records("), 1)
        self.assertIn("_migrate_library_path(abs_path, new_path)", source)
        self.assertIn("_migrate_library_path(old_path, new_path)", source)

    def test_prune_removes_only_paths_missing_from_complete_inventory(self):
        with tempfile.TemporaryDirectory() as data_tmp:
            store = app.AppMetadataStore(Path(data_tmp))
            store.update_file_record("E:/Movies/Alien.mkv", {"title": "Alien"})
            store.update_file_record("E:/Movies/Aliens.mkv", {"title": "Aliens"})

            removed = store.prune_missing_path_records(["E:/Movies/Alien.mkv"])
            files = store.snapshot()["files"]

        self.assertEqual(removed, 1)
        self.assertIn(store._key("E:/Movies/Alien.mkv"), files)
        self.assertNotIn(store._key("E:/Movies/Aliens.mkv"), files)

    def test_reconcile_refreshes_changed_facts_without_rematching_accepted_identity(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_user_data = app._user_data_dir
        original_library_cache = dict(app._library_cache)
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_path = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie_path.write_bytes(b"changed-size")
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_tmdb_metadata({
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "poster_url": "alien.jpg",
                "plot": "Stored detail.",
                "cast": [],
                "directors": [],
            })
            store.update_file_record(str(movie_path), {
                "identity_status": "accepted",
                "identity_title": "Alien",
                "identity_year": "1979",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "348",
                "decision_origin": app.DECISION_ORIGIN_LIBRARY_RECONCILE,
                "identity_evidence_fingerprint": app._identity_evidence_fingerprint(
                    str(movie_path), app._metadata_file_facts(str(movie_path)), {}
                ),
                "size": 0,
                "modified_time": 0,
            })
            try:
                app._movies_dirs = [movies_tmp]
                app._movies_dir = movies_tmp
                app._user_data_dir = data_tmp
                app._library_cache = {}

                with patch("app._revalidate_accepted_identity") as revalidate, patch(
                    "app._file_copy_is_stable",
                    return_value=True,
                ):
                    result = app._reconcile_library_files()
                refreshed = app.AppMetadataStore(Path(data_tmp)).snapshot()["files"][store._key(movie_path)]
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data
                app._library_cache = original_library_cache

        self.assertEqual(result["checked"], 0)
        revalidate.assert_not_called()
        self.assertEqual(refreshed["size"], len(b"changed-size"))
        self.assertEqual(refreshed["resolution"], "1080p")
        self.assertEqual(refreshed["identity_title"], "Alien")

    def test_reconcile_fingerprint_uses_persisted_plex_snapshot_without_churn(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_user_data = app._user_data_dir
        original_tmdb_key = app._tmdb_key
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_path = Path(movies_tmp) / "Unknown.1995.1080p.mkv"
            movie_path.write_bytes(b"movie")
            store = app.AppMetadataStore(Path(data_tmp))
            facts = app._metadata_file_facts(str(movie_path))
            store.save_plex_metadata(str(movie_path), {
                "plex_title": "Unknown",
                "plex_year": "1995",
                "plex_guid": "plex://movie/unknown",
            })
            store.update_file_record(str(movie_path), {
                **facts,
                "identity_status": "unmatched",
                "metadata_status": "unmatched",
                "metadata_accepted": False,
                "identity_decision_version": app.IDENTITY_DECISION_VERSION,
                "identity_evidence_fingerprint": app._identity_evidence_fingerprint(str(movie_path), facts, {}),
            })
            try:
                app._movies_dirs = [movies_tmp]
                app._movies_dir = movies_tmp
                app._user_data_dir = data_tmp
                app._tmdb_key = "test-key"
                stat_result = movie_path.stat()
                accepted_probe = MediaFileFacts(
                    probe_status="ok",
                    probe_size=stat_result.st_size,
                    probe_modified_time=stat_result.st_mtime,
                    quality_class="1080p",
                    quality_source="measured",
                )
                with patch("app._active_metadata_provider", return_value="tmdb"), \
                        patch("app._resolve_tmdb_identity", return_value=app._identity_resolution("unmatched")), \
                        patch("app.probe_media_file", return_value=accepted_probe), \
                        patch("app._file_copy_is_stable", return_value=True):
                    first = app._reconcile_library_files()
                    second = app._reconcile_library_files()
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data
                app._tmdb_key = original_tmdb_key

        self.assertEqual(first["checked"], 1)
        self.assertEqual(second["checked"], 0)


if __name__ == "__main__":
    unittest.main()
