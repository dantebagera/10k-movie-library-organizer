import tempfile
import unittest
from pathlib import Path

import app


class SystemListsApiTest(unittest.TestCase):
    def setUp(self):
        self.original_user_data = app._user_data_dir
        self.original_dirs = app._movies_dirs
        self.original_dir = app._movies_dir

    def tearDown(self):
        app._user_data_dir = self.original_user_data
        app._movies_dirs = self.original_dirs
        app._movies_dir = self.original_dir

    def test_toggle_returns_independent_system_states(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as movies_tmp:
            movie_path = Path(movies_tmp) / "Alien.1979.mkv"
            movie_path.write_bytes(b"movie")
            app._user_data_dir = tmp
            app._movies_dirs = [movies_tmp]
            app._movies_dir = movies_tmp
            client = app.app.test_client()
            movie = {"tmdb_id": "348", "title": "Alien", "year": "1979", "path": str(movie_path)}

            watched = client.post("/api/user/system-lists/watched/toggle", json={"movie": movie, "active": True})
            watchlisted = client.post("/api/user/system-lists/watchlist/toggle", json={"movie": movie, "active": True})
            states = client.get("/api/user/system-lists/state", query_string=movie)

        self.assertEqual(watched.status_code, 200)
        self.assertEqual(watchlisted.status_code, 200)
        payload = states.get_json()
        self.assertEqual({"watched": payload["watched"], "watchlist": payload["watchlist"]}, {"watched": True, "watchlist": True})
        self.assertGreater(watched.get_json()["curation_generation"], 0)
        self.assertGreater(watchlisted.get_json()["curation_generation"], watched.get_json()["curation_generation"])
        self.assertEqual(payload["curation_generation"], watchlisted.get_json()["curation_generation"])

    def test_unowned_movie_cannot_be_marked_watched_but_can_be_watchlisted(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as movies_tmp:
            app._user_data_dir = tmp
            app._movies_dirs = [movies_tmp]
            app._movies_dir = movies_tmp
            client = app.app.test_client()
            movie = {"tmdb_id": "999", "title": "Not Owned", "year": "2026"}

            watched = client.post("/api/user/system-lists/watched/toggle", json={"movie": movie, "active": True})
            watchlisted = client.post("/api/user/system-lists/watchlist/toggle", json={"movie": movie, "active": True})

        self.assertEqual(watched.status_code, 400)
        self.assertEqual(watchlisted.status_code, 200)

    def test_unknown_system_list_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            app._user_data_dir = tmp
            response = app.app.test_client().post(
                "/api/user/system-lists/favorites/toggle",
                json={"movie": {"tmdb_id": "348", "title": "Alien"}, "active": True},
            )

        self.assertEqual(response.status_code, 404)

    def test_user_lists_projects_legacy_owned_membership_to_canonical_movie_key_without_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as movies_tmp:
            movie_path = Path(movies_tmp) / "Michael.2026.mkv"
            movie_path.write_bytes(b"movie")
            app._user_data_dir = tmp
            app._movies_dirs = [movies_tmp]
            app._movies_dir = movies_tmp
            metadata_store = app.AppMetadataStore(Path(tmp))
            metadata_store.apply_tmdb_match(str(movie_path), {
                "tmdb_id": "936075",
                "imdb_id": "tt11378946",
                "title": "Michael",
                "year": "2026",
            })
            metadata_store.update_file_record(str(movie_path), {
                "filename": movie_path.name,
                "parsed_title": "Michael",
                "parsed_year": "2026",
            })
            store = app._curation_store()
            legacy = {
                "lists": [{
                    "id": "watched",
                    "name": "Watched",
                    "system_type": "watched",
                    "movies": [{
                        "title": "Michael",
                        "year": "2026",
                        "path": str(movie_path),
                    }],
                }],
            }
            store.catalog.replace_document("user_lists.json", legacy)

            response = app.app.test_client().get("/api/user/lists")
            persisted = store.catalog.read_document("user_lists.json", {})

        self.assertEqual(response.status_code, 200)
        watched = next(item for item in response.get_json()["lists"] if item["id"] == "watched")
        self.assertEqual(watched["movies"][0]["movie_key"], "tmdb:936075")
        self.assertEqual(watched["movies"][0]["imdb_id"], "tt11378946")
        self.assertNotIn("movie_key", persisted["lists"][0]["movies"][0])
