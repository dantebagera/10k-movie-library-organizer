import tempfile
import unittest
from pathlib import Path

import app


class LibraryOwnershipTest(unittest.TestCase):
    def test_library_check_matches_et_title_variant_without_saved_external_id(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_library_cache = dict(app._library_cache)
        original_plex_cache = dict(app._plex_cache)
        original_plex_by_fname = dict(app._plex_matched_by_fname)
        original_plex_token = app._plex_token

        original_user_data_dir = app._user_data_dir
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_path = Path(tmp) / "E.T.The.Extra-Terrestrial.1982.1080p.mkv"
            movie_path.write_bytes(b"")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._user_data_dir = data_tmp
                app._library_cache = {}
                app._plex_cache = {
                    app._norm(str(movie_path)): {
                        "plex_title": "E.T.",
                        "plex_year": "1982",
                    }
                }
                app._plex_matched_by_fname = {}
                app._plex_token = ""
                app.AppMetadataStore(Path(data_tmp)).apply_plex_match(str(movie_path), {
                    "plex_title": "E.T.",
                    "plex_year": "1982",
                })

                response = app.app.test_client().post("/api/library/check", json={
                    "movies": [{
                        "tmdb_id": "601",
                        "imdb_id": "tt0083866",
                        "title": "E.T. the Extra-Terrestrial",
                        "year": "1982",
                    }]
                })
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data_dir
                app._library_cache = original_library_cache
                app._plex_cache = original_plex_cache
                app._plex_matched_by_fname = original_plex_by_fname
                app._plex_token = original_plex_token

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["results"][0]["found"])

    def test_library_check_matches_by_tmdb_id_before_title(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_user_data_dir = app._user_data_dir
        original_library_cache = dict(app._library_cache)
        original_plex_cache = dict(app._plex_cache)
        original_plex_by_fname = dict(app._plex_matched_by_fname)
        original_plex_token = app._plex_token

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_path = Path(tmp) / "ET.1982.1080p.mkv"
            movie_path.write_bytes(b"")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._user_data_dir = data_tmp
                app._library_cache = {}
                app._plex_cache = {}
                app._plex_matched_by_fname = {}
                app._plex_token = ""
                app.AppMetadataStore(Path(data_tmp)).apply_tmdb_match(str(movie_path), {
                    "tmdb_id": "601",
                    "title": "E.T.",
                    "year": "1982",
                })

                response = app.app.test_client().post("/api/library/check", json={
                    "movies": [{
                        "tmdb_id": "601",
                        "title": "E.T. the Extra-Terrestrial",
                        "year": "1982",
                    }]
                })
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data_dir
                app._library_cache = original_library_cache
                app._plex_cache = original_plex_cache
                app._plex_matched_by_fname = original_plex_by_fname
                app._plex_token = original_plex_token

        self.assertEqual(response.status_code, 200)
        result = response.get_json()["results"][0]
        self.assertTrue(result["found"])
        self.assertEqual(result["tmdb_id"], "601")
        self.assertEqual(result["path"], str(movie_path))

    def test_library_check_can_include_movie_list_card_item(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_library_cache = dict(app._library_cache)
        original_plex_token = app._plex_token
        original_user_data_dir = app._user_data_dir

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_path = Path(tmp) / "Alien.1979.1080p.mkv"
            movie_path.write_bytes(b"movie")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._user_data_dir = data_tmp
                app._plex_token = ""
                app._library_cache = {}
                metadata_store = app.AppMetadataStore(Path(data_tmp))
                metadata_store.apply_tmdb_match(str(movie_path), {
                    "tmdb_id": "348",
                    "title": "Alien",
                    "year": "1979",
                    "cast": [{"id": index, "name": f"Actor {index}", "extra": "drop"} for index in range(10)],
                })
                metadata_store.update_file_record(str(movie_path), {
                    "filename": movie_path.name,
                    "parsed_title": "Alien",
                    "parsed_year": "1979",
                    "resolution": "1080p",
                    "size": 5,
                })

                response = app.app.test_client().post("/api/library/check", json={
                    "include_items": True,
                    "movies": [{"tmdb_id": "348", "title": "Alien", "year": "1979"}],
                })
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data_dir
                app._library_cache = original_library_cache
                app._plex_token = original_plex_token

        self.assertEqual(response.status_code, 200)
        result = response.get_json()["results"][0]
        self.assertTrue(result["found"])
        self.assertEqual(result["library_item"]["path"], str(movie_path))
        self.assertEqual(len(result["library_item"]["canonical_metadata"]["cast"]), 8)
        self.assertNotIn("extra", result["library_item"]["canonical_metadata"]["cast"][0])

    def test_library_check_resolves_legacy_title_through_exact_owned_path_to_movie_key(self):
        original_dirs = app._movies_dirs
        original_dir = app._movies_dir
        original_library_cache = dict(app._library_cache)
        original_user_data_dir = app._user_data_dir

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie_path = Path(tmp) / "A.Serbian.Film.2010.mkv"
            movie_path.write_bytes(b"movie")
            try:
                app._movies_dirs = [tmp]
                app._movies_dir = tmp
                app._user_data_dir = data_tmp
                app._library_cache = {}
                metadata_store = app.AppMetadataStore(Path(data_tmp))
                metadata_store.apply_tmdb_match(str(movie_path), {
                    "tmdb_id": "73861",
                    "imdb_id": "tt1273235",
                    "title": "A Serbian Film",
                    "year": "2010",
                })
                metadata_store.update_file_record(str(movie_path), {
                    "filename": movie_path.name,
                    "parsed_title": "A Serbian Film",
                    "parsed_year": "2010",
                })

                response = app.app.test_client().post("/api/library/check", json={
                    "movies": [{
                        "title": "Film Postcards: Serbia",
                        "year": "2012",
                        "path": str(movie_path),
                    }],
                })
            finally:
                app._movies_dirs = original_dirs
                app._movies_dir = original_dir
                app._user_data_dir = original_user_data_dir
                app._library_cache = original_library_cache

        self.assertEqual(response.status_code, 200)
        result = response.get_json()["results"][0]
        self.assertTrue(result["found"])
        self.assertEqual(result["movie_key"], "tmdb:73861")
        self.assertEqual(result["imdb_id"], "tt1273235")


if __name__ == "__main__":
    unittest.main()
