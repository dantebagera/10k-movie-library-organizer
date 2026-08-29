import unittest
from unittest.mock import patch

import app


class HomeTrailersApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_home_trailers_returns_the_fixed_sanitized_multi_source_feed(self):
        payload = {
            "title": "New Trailers",
            "sources": [{"id": "rotten-tomatoes", "name": "Rotten Tomatoes Trailers", "source_url": "https://youtube.test/rt"}],
            "items": [{
                "video_id": "abc_DEF-123",
                "title": "Example Trailer",
                "url": "https://www.youtube.com/watch?v=abc_DEF-123",
                "thumbnail_url": "https://i.ytimg.com/vi/abc_DEF-123/hqdefault.jpg",
                "published_at": "2026-07-28T12:00:00+00:00",
                "views": 10,
                "source_id": "rotten-tomatoes",
                "source_name": "Rotten Tomatoes Trailers",
            }],
            "next_cursor": "cursor",
            "has_more": True,
            "stale": False,
            "fallback": False,
        }
        with patch.object(app._youtube_service, "get_home_trailers", return_value=payload):
            response = self.client.get("/api/home/trailers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)

    def test_home_trailers_does_not_accept_a_caller_supplied_playlist(self):
        with patch.object(app._youtube_service, "get_home_trailers", return_value={
            "title": "New Trailers",
            "sources": [],
            "items": [],
            "next_cursor": "",
            "has_more": False,
            "stale": False,
            "fallback": False,
        }) as mocked_get:
            response = self.client.get("/api/home/trailers?playlist_id=attacker-value")

        self.assertEqual(response.status_code, 200)
        mocked_get.assert_called_once_with(cursor="", source_filter="all")

    def test_home_trailers_returns_a_stable_error_contract(self):
        with patch.object(
            app._youtube_service,
            "get_home_trailers",
            side_effect=app.YouTubePlaylistError("YouTube playlist is temporarily unavailable"),
        ):
            response = self.client.get("/api/home/trailers")

        self.assertEqual(response.status_code, 502)
        payload = response.get_json()
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["items"], [])
        self.assertEqual(len(payload["sources"]), 2)
        self.assertIn("temporarily unavailable", payload["error"])

    def test_youtube_config_never_returns_the_saved_key(self):
        original = app._youtube_api_key
        original_region = app._youtube_trailer_region
        try:
            with patch.object(app, "_save_config"):
                response = self.client.post("/api/youtube/config", json={"key": "test-secret-value", "trailer_region": "eg"})
                self.assertEqual(response.status_code, 200)
                saved = response.get_json()
                self.assertTrue(saved["configured"])
                self.assertNotIn("test-secret-value", str(saved))
                self.assertEqual(saved["trailer_region"], "EG")

                loaded = self.client.get("/api/youtube/config").get_json()
                self.assertTrue(loaded["configured"])
                self.assertNotIn("test-secret-value", str(loaded))
                self.assertNotIn("key", loaded)
                self.assertEqual(loaded["trailer_region"], "EG")
        finally:
            app._youtube_api_key = original
            app._youtube_trailer_region = original_region
            app._youtube_service.set_api_key(original)
            app._youtube_service.set_trailer_region(original_region)

    def test_missing_trailer_search_uses_the_authoritative_youtube_service(self):
        result = {"status": "choose", "video": None, "candidates": [{"video_id": "abc123DEF45"}]}
        with patch.object(app._youtube_service, "search_trailers", return_value=result) as search:
            response = self.client.post("/api/youtube/trailer-search", json={"title": "Example", "year": "2027"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), result)
        search.assert_called_once_with("Example", "2027")


if __name__ == "__main__":
    unittest.main()
