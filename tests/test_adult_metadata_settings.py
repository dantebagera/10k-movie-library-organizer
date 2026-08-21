import json
import unittest
from unittest.mock import patch

import app


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class AdultMetadataSettingsTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.original_tmdb_key = app._tmdb_key
        self.original_tmdb_include_adult = getattr(app, "_tmdb_include_adult", False)
        self.original_library_show_adult = getattr(app, "_library_show_adult", True)
        self.original_movies_dirs = list(app._movies_dirs)
        self.original_movies_dir = app._movies_dir
        self.original_tmdb_genres = dict(app._tmdb_genres)

    def tearDown(self):
        app._tmdb_key = self.original_tmdb_key
        app._tmdb_include_adult = self.original_tmdb_include_adult
        app._library_show_adult = self.original_library_show_adult
        app._movies_dirs = self.original_movies_dirs
        app._movies_dir = self.original_movies_dir
        app._tmdb_genres = self.original_tmdb_genres

    def test_tmdb_config_saves_adult_metadata_search_setting(self):
        with patch.object(app, "_save_config") as save_config:
            response = self.client.post(
                "/api/tmdb/config",
                json={"key": "abc123", "include_adult": True},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(app._tmdb_include_adult)
        self.assertTrue(save_config.called)
        self.assertTrue(self.client.get("/api/tmdb/config").get_json()["include_adult"])

    def test_library_config_saves_movie_view_adult_visibility_setting(self):
        with patch.object(app.os.path, "isdir", return_value=True), patch.object(app, "_save_config") as save_config:
            response = self.client.post(
                "/api/config",
                json={"directories": [r"E:\Movies"], "show_adult_movies": False},
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(app._library_show_adult)
        self.assertTrue(save_config.called)
        self.assertFalse(self.client.get("/api/config").get_json()["show_adult_movies"])

    def test_tmdb_search_uses_saved_adult_setting_by_default(self):
        app._tmdb_key = "tmdb-key"
        app._tmdb_include_adult = True
        app._tmdb_genres = {}
        seen_urls = []

        def fake_urlopen(request, timeout=0):
            seen_urls.append(request.full_url)
            return FakeResponse({"results": [], "total_pages": 1, "total_results": 0})

        with patch.object(app, "_ensure_tmdb_genres"), patch.object(app.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.get("/api/tmdb/search?q=shining+sex&page=1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(seen_urls)
        self.assertIn("include_adult=true", seen_urls[0])

    def test_tmdb_search_can_force_discover_safe_adult_setting(self):
        app._tmdb_key = "tmdb-key"
        app._tmdb_include_adult = True
        app._tmdb_genres = {}
        seen_urls = []

        def fake_urlopen(request, timeout=0):
            seen_urls.append(request.full_url)
            return FakeResponse({"results": [], "total_pages": 1, "total_results": 0})

        with patch.object(app, "_ensure_tmdb_genres"), patch.object(app.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.get("/api/tmdb/search?q=shining+sex&page=1&include_adult=false")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(seen_urls)
        self.assertIn("include_adult=false", seen_urls[0])

    def test_tmdb_search_forwards_year_as_structured_parameter(self):
        app._tmdb_key = "tmdb-key"
        app._tmdb_include_adult = True
        app._tmdb_genres = {}
        seen_urls = []

        def fake_urlopen(request, timeout=0):
            seen_urls.append(request.full_url)
            return FakeResponse({"results": [], "total_pages": 1, "total_results": 0})

        with patch.object(app, "_ensure_tmdb_genres"), patch.object(app.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.get("/api/tmdb/search?q=Shining+Sex&page=1&year=1976")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(seen_urls)
        self.assertIn("query=Shining+Sex", seen_urls[0])
        self.assertIn("year=1976", seen_urls[0])
        self.assertNotIn("query=Shining+Sex+1976", seen_urls[0])

    def test_tmdb_search_refines_title_results_with_discover_criteria(self):
        app._tmdb_key = "tmdb-key"
        app._tmdb_genres = {16: "Animation", 18: "Drama"}
        seen_urls = []

        def fake_urlopen(request, timeout=0):
            seen_urls.append(request.full_url)
            return FakeResponse({
                "total_pages": 1,
                "total_results": 5,
                "results": [
                    {"id": 1, "title": "Tom Cartoon", "genre_ids": [16], "release_date": "1997-01-01", "vote_average": 7.2, "vote_count": 200, "popularity": 3, "original_language": "en", "origin_country": ["GB"]},
                    {"id": 2, "title": "Tom Cartoon Returns", "genre_ids": [16], "release_date": "1999-01-01", "vote_average": 8.5, "vote_count": 400, "popularity": 2, "original_language": "en", "origin_country": ["GB"]},
                    {"id": 3, "title": "Tom Drama", "genre_ids": [18], "release_date": "1999-01-01", "vote_average": 9.0, "vote_count": 500, "popularity": 4, "original_language": "en", "origin_country": ["GB"]},
                    {"id": 4, "title": "Old Tom Cartoon", "genre_ids": [16], "release_date": "1980-01-01", "vote_average": 9.0, "vote_count": 500, "popularity": 4, "original_language": "en", "origin_country": ["GB"]},
                    {"id": 5, "title": "Low Rated Tom Cartoon", "genre_ids": [16], "release_date": "1998-01-01", "vote_average": 6.0, "vote_count": 500, "popularity": 4, "original_language": "en", "origin_country": ["GB"]},
                ],
            })

        with patch.object(app, "_ensure_tmdb_genres"), patch.object(app.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.get(
                "/api/tmdb/search?q=tom&genre=16&language=en&country=GB&year_from=1990&year_to=2000&min_rating=7&min_votes=100&sort=vote_average.desc"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([movie["title"] for movie in payload["results"]], ["Tom Cartoon Returns", "Tom Cartoon"])
        self.assertTrue(payload["criteria_applied"])
        self.assertIn("query=tom", seen_urls[0])
        self.assertNotIn("with_genres", seen_urls[0])

    def test_tmdb_people_search_returns_selectable_people_with_known_for_titles(self):
        app._tmdb_key = "tmdb-key"
        seen_urls = []

        def fake_urlopen(request, timeout=0):
            seen_urls.append(request.full_url)
            return FakeResponse({
                "page": 1,
                "total_pages": 1,
                "total_results": 1,
                "results": [{
                    "id": 6941,
                    "name": "Mel Gibson",
                    "profile_path": "/mel.jpg",
                    "known_for_department": "Acting",
                    "popularity": 9.5,
                    "known_for": [
                        {"title": "Braveheart"},
                        {"title": "Mad Max"},
                    ],
                }],
            })

        with patch.object(app.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.get("/api/tmdb/people/search?q=melgibson&page=1&include_adult=false")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["results"][0]["tmdb_id"], "6941")
        self.assertEqual(payload["results"][0]["known_for"], ["Braveheart", "Mad Max"])
        self.assertIn("/search/person?", seen_urls[0])
        self.assertIn("query=melgibson", seen_urls[0])

    def test_tmdb_people_search_recovers_an_unspaced_exact_name(self):
        app._tmdb_key = "tmdb-key"
        seen_urls = []

        def fake_urlopen(request, timeout=0):
            seen_urls.append(request.full_url)
            if "query=mel+gibson" in request.full_url:
                return FakeResponse({
                    "page": 1,
                    "total_pages": 1,
                    "total_results": 1,
                    "results": [{"id": 6941, "name": "Mel Gibson", "known_for": []}],
                })
            return FakeResponse({"page": 1, "total_pages": 1, "total_results": 0, "results": []})

        with patch.object(app.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.get("/api/tmdb/people/search?q=melgibson&page=1")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual([person["name"] for person in payload["results"]], ["Mel Gibson"])
        self.assertEqual(payload["total_results"], 1)
        self.assertTrue(any("query=mel+gibson" in url for url in seen_urls))

    def test_tmdb_catalog_uses_discover_endpoint_without_a_feed_preset(self):
        app._tmdb_key = "tmdb-key"
        app._tmdb_genres = {}
        seen_urls = []

        def fake_urlopen(request, timeout=0):
            seen_urls.append(request.full_url)
            return FakeResponse({"results": [], "total_pages": 1, "total_results": 0})

        with patch.object(app, "_ensure_tmdb_genres"), patch.object(app.urllib.request, "urlopen", side_effect=fake_urlopen):
            response = self.client.get("/api/tmdb/discover?list=catalog&page=1")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(seen_urls)
        self.assertIn("/discover/movie?", seen_urls[0])
        self.assertIn("sort_by=popularity.desc", seen_urls[0])

    def test_canonical_tmdb_metadata_preserves_adult_flag(self):
        canonical = app._build_canonical_metadata(
            {"parsed_title": "Shining Sex", "parsed_year": "1976"},
            tmdb_data={
                "tmdb_id": "346011",
                "title": "Shining Sex",
                "year": "1976",
                "adult": True,
                "match_source": "auto_tmdb",
            },
        )

        self.assertTrue(canonical["accepted"])
        self.assertTrue(canonical["adult"])


if __name__ == "__main__":
    unittest.main()
