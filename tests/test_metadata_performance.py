import tempfile
import unittest
import gzip
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import app


class MetadataPerformanceTest(unittest.TestCase):
    def test_unittest_runner_refuses_to_import_app_without_test_mode(self):
        environment = os.environ.copy()
        environment.pop("CP_TEST_MODE", None)
        environment.pop("CP_TEST_ROOT", None)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "unittest",
                "tests.test_metadata_performance.MetadataPerformanceTest.test_api_response_exposes_route_timing_headers",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python tests require CP_TEST_MODE=1", result.stderr)

    def test_production_audit_import_is_not_mistaken_for_a_test_runner(self):
        environment = os.environ.copy()
        environment.pop("CP_TEST_MODE", None)
        environment.pop("CP_TEST_ROOT", None)
        result = subprocess.run(
            [sys.executable, "-c", "import tools.catalog_parity_audit"],
            cwd=Path(__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_test_runtime_paths_are_all_isolated_under_declared_temporary_root(self):
        self.assertTrue(app._TEST_MODE, "Python tests must run with CP_TEST_MODE=1")
        declared_root = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        self.assertIn(temporary_root, (declared_root, *declared_root.parents))
        runtime_paths = [
            Path(app._CONFIG_FILE).resolve(),
            Path(app._user_data_dir).resolve(),
            Path(app._tmdb_cache_dir).resolve(),
            Path(app._RES_CACHE_FILE).resolve(),
            *(Path(path).resolve() for path in app._movies_dirs),
        ]
        for runtime_path in runtime_paths:
            self.assertIn(declared_root, (runtime_path, *runtime_path.parents), str(runtime_path))

    @staticmethod
    def _seed_file_record(store, movie_path, title, year, tmdb_id=""):
        store.update_file_record(str(movie_path), {
            "filename": movie_path.name,
            "library_root": str(movie_path.parent),
            "parsed_title": title,
            "parsed_year": year,
            "identity_status": "accepted",
            "identity_title": title,
            "identity_year": year,
            "identity_source": "test",
            "metadata_status": "accepted",
            "metadata_accepted": True,
            "tmdb_id": tmdb_id,
            "resolution": "1080p",
            "size": movie_path.stat().st_size,
        })

    def test_api_response_exposes_route_timing_headers(self):
        repository = Mock()
        repository.generation.return_value = 1
        with patch("app._catalog_repository", return_value=repository):
            response = app.app.test_client().get("/api/library/status")

        self.assertEqual(response.status_code, 200)
        self.assertIn("app;dur=", response.headers.get("Server-Timing", ""))
        self.assertRegex(response.headers.get("X-CP-Route-MS", ""), r"^\d+\.\d$")

    def test_large_json_responses_use_gzip_when_requested(self):
        with app.app.test_request_context("/api/test", headers={"Accept-Encoding": "gzip"}):
            app.request._cp_started_at = app.time.perf_counter()
            response = app._finish_route_timer(app.jsonify({"items": ["x" * 1024] * 300}))

        self.assertEqual(response.headers.get("Content-Encoding"), "gzip")
        self.assertGreater(len(gzip.decompress(response.data)), len(response.data))

    def test_catalog_database_is_isolated_by_user_data_directory(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_path = app.AppMetadataStore(Path(first)).catalog.database_path
            second_path = app.AppMetadataStore(Path(second)).catalog.database_path

        self.assertNotEqual(first_path, second_path)

    def test_tmdb_metadata_for_file_does_not_fetch_by_plex_id_without_refresh(self):
        original_key = app._tmdb_key
        app._tmdb_key = "tmdb-key"
        try:
            store = app.AppMetadataStore(Path(tempfile.mkdtemp()))
            with patch("app.urllib.request.urlopen") as urlopen:
                result = app._tmdb_metadata_for_file(
                    {"path": "E:/Movies/Alien.mkv", "parsed_title": "alien", "parsed_year": "1979"},
                    plex_data={"tmdb_id": "348"},
                    store=store,
                    refresh=False,
                )
        finally:
            app._tmdb_key = original_key

        self.assertEqual(result, {})
        urlopen.assert_not_called()

    def test_tmdb_metadata_refresh_repairs_an_accepted_identity_with_no_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.AppMetadataStore(Path(tmp))
            path = "E:/Movies/Alien.1979.mkv"
            store.update_file_record(path, {
                "identity_status": "accepted",
                "identity_title": "Alien",
                "identity_year": "1979",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "348",
            })
            expected = {
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "poster_url": "alien.jpg",
            }

            with patch("app._fetch_tmdb_metadata_by_id", return_value=expected) as fetch:
                result = app._tmdb_metadata_for_file(
                    {"path": path, "parsed_title": "alien", "parsed_year": "1979"},
                    store=store,
                    snapshot=store.snapshot(),
                    refresh=True,
                )

        self.assertEqual(result, expected)
        fetch.assert_called_once_with(
            "348",
            store=store,
            refresh=True,
            match_source="saved_tmdb_id",
        )

    def test_library_read_path_does_not_write_metadata_per_file(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_library_cache = dict(app._library_cache)
        original_plex_cache = dict(app._plex_cache)
        original_plex_by_fname = dict(app._plex_matched_by_fname)
        original_plex_token = app._plex_token
        original_user_data = app._user_data_dir

        with tempfile.TemporaryDirectory() as tmp:
            movie_path = Path(tmp) / "Alien.1979.1080p.mkv"
            movie_path.write_bytes(b"")
            store = app.AppMetadataStore(Path(tmp) / "data")
            self._seed_file_record(store, movie_path, "Alien", "1979")
            store.save_plex_metadata = Mock(side_effect=AssertionError("library read must not save plex metadata"))
            store.record_file = Mock(side_effect=AssertionError("library read must not persist file records"))

            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._user_data_dir = str(Path(tmp) / "data")
                app._library_cache = {}
                app._plex_cache = {
                    app._norm(str(movie_path)): {
                        "plex_title": "Alien",
                        "plex_year": "1979",
                        "plex_genres": ["Horror"],
                    }
                }
                app._plex_matched_by_fname = {}
                app._plex_token = ""
                with patch("app._metadata_store", return_value=store):
                    response = app.app.test_client().get("/api/library")
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data
                app._library_cache = original_library_cache
                app._plex_cache = original_plex_cache
                app._plex_matched_by_fname = original_plex_by_fname
                app._plex_token = original_plex_token

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 1)
        store.save_plex_metadata.assert_not_called()
        store.record_file.assert_not_called()

    def test_library_read_path_loads_manual_matches_once(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_library_cache = dict(app._library_cache)
        original_plex_cache = dict(app._plex_cache)
        original_plex_by_fname = dict(app._plex_matched_by_fname)
        original_plex_token = app._plex_token

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "Alien.1979.1080p.mkv").write_bytes(b"")
            Path(tmp, "Aliens.1986.1080p.mkv").write_bytes(b"")
            store = app.AppMetadataStore(Path(tmp) / "data")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._library_cache = {}
                app._plex_cache = {}
                app._plex_matched_by_fname = {}
                app._plex_token = ""
                with patch("app._metadata_store", return_value=store), \
                        patch.object(store, "_read_json", wraps=store._read_json) as read_json:
                    response = app.app.test_client().get("/api/library")
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._library_cache = original_library_cache
                app._plex_cache = original_plex_cache
                app._plex_matched_by_fname = original_plex_by_fname
                app._plex_token = original_plex_token

        manual_reads = [
            call for call in read_json.call_args_list
            if call.args and Path(call.args[0]) == store.manual_matches_file
        ]
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(manual_reads), 1)

    def test_catalog_library_read_does_not_compute_directory_revision(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_library_cache = dict(app._library_cache)
        original_plex_token = app._plex_token
        original_user_data = app._user_data_dir

        with tempfile.TemporaryDirectory() as tmp:
            movie_path = Path(tmp) / "Alien.1979.1080p.mkv"
            movie_path.write_bytes(b"movie")
            store = app.AppMetadataStore(Path(tmp) / "data")
            self._seed_file_record(store, movie_path, "Alien", "1979")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._user_data_dir = str(Path(tmp) / "data")
                app._plex_token = ""
                app._library_cache = {}
                with patch("app._metadata_store", return_value=store), \
                        patch("app._library_directory_revision", side_effect=AssertionError("full directory revision should not run")):
                    response = app.app.test_client().get("/api/library")
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data
                app._library_cache = original_library_cache
                app._plex_token = original_plex_token

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["cached"])
        self.assertEqual(payload["count"], 1)

    def test_library_card_projection_defers_people_payload(self):
        item = {
            "title": "Alien (1979)",
            "filename": "Alien.1979.1080p.mkv",
            "path": "E:/Movies/Alien.1979.1080p.mkv",
            "resolution": "1080p",
            "rip_source": "BluRay",
            "canonical_metadata": {
                "title": "Alien",
                "year": "1979",
                "accepted": True,
                "cast": [{"id": index, "name": f"Actor {index}", "extra": "drop"} for index in range(12)],
                "directors": [{"id": index, "name": f"Director {index}", "extra": "drop"} for index in range(6)],
            },
            "plex_cast": [{"id": index, "name": f"Plex Actor {index}", "extra": "drop"} for index in range(12)],
            "plex_directors": [{"id": index, "name": f"Plex Director {index}", "extra": "drop"} for index in range(6)],
            "resolution_rank": 3,
            "rip_rank": 4,
        }

        projected = app._movie_list_library_item(item)
        card = app._library_card_item(item)
        people = app._library_people_item(item)

        self.assertNotIn("resolution_rank", projected)
        self.assertNotIn("rip_rank", projected)
        self.assertNotIn("cast", projected["canonical_metadata"])
        self.assertNotIn("directors", projected["canonical_metadata"])
        self.assertEqual(projected["plex_cast"], [])
        self.assertEqual(projected["plex_directors"], [])
        self.assertEqual(len(people["canonical_metadata"]["cast"]), 8)
        self.assertEqual(len(people["canonical_metadata"]["directors"]), 4)
        self.assertEqual(len(people["plex_cast"]), 8)
        self.assertEqual(len(people["plex_directors"]), 4)
        self.assertNotIn("extra", people["canonical_metadata"]["cast"][0])
        self.assertNotIn("plex_genres", card)
        self.assertNotIn("plex_title", card)
        self.assertEqual(card["canonical_metadata"]["title"], "Alien")

    def test_library_cache_key_changes_when_manual_metadata_changes(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir

        with tempfile.TemporaryDirectory() as tmp:
            store = app.AppMetadataStore(Path(tmp) / "data")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                with patch("app._metadata_store", return_value=store):
                    before = app._library_cache_key()
                    store.apply_tmdb_match(
                        str(Path(tmp) / "Alien.1979.1080p.mkv"),
                        {"tmdb_id": "348", "title": "Alien", "year": "1979"},
                    )
                    after = app._library_cache_key()
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir

        self.assertNotEqual(before, after)

    def test_library_cache_key_changes_when_file_is_added(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir

        with tempfile.TemporaryDirectory() as tmp:
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                before = app._library_cache_key(metadata_revision=('test-catalog', 1))
                Path(tmp, "Alien.1979.1080p.mkv").write_bytes(b"movie")
                after = app._library_cache_key(metadata_revision=('test-catalog', 1))
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir

        self.assertNotEqual(before, after)

    def test_force_scan_bypasses_fresh_library_cache(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_library_cache = dict(app._library_cache)
        original_plex_token = app._plex_token
        original_user_data = app._user_data_dir

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as data_tmp:
            first_movie = Path(tmp, "Alien.1979.1080p.mkv")
            first_movie.write_bytes(b"movie")
            self._seed_file_record(app.AppMetadataStore(Path(data_tmp)), first_movie, "Alien", "1979")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._user_data_dir = data_tmp
                app._library_cache = {}
                app._plex_token = ""
                client = app.app.test_client()
                initial = client.get("/api/library")
                second_movie = Path(tmp, "Aliens.1986.1080p.mkv")
                second_movie.write_bytes(b"movie")
                refreshed = client.get("/api/library")
                third_movie = Path(tmp, "Alien.3.1992.1080p.mkv")
                third_movie.write_bytes(b"movie")
                forced = client.get("/api/library?force_scan=1")
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data
                app._library_cache = original_library_cache
                app._plex_token = original_plex_token

        self.assertEqual(initial.get_json()["count"], 1)
        self.assertEqual(refreshed.get_json()["count"], 1)
        self.assertTrue(refreshed.get_json()["cached"])
        self.assertEqual(forced.get_json()["count"], 3)
        self.assertFalse(forced.get_json()["cached"])
        self.assertEqual(forced.get_json()["new_files"], 2)


if __name__ == "__main__":
    unittest.main()
