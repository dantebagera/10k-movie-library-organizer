import unittest
from unittest.mock import patch

import app


class HomeTrailersApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_home_trailers_returns_the_fixed_sanitized_feed(self):
        payload = {
            "playlist_id": app.HOME_TRAILERS_PLAYLIST_ID,
            "title": "HOT New Trailers & Exclusives",
            "source_url": (
                "https://www.youtube.com/playlist?list="
                f"{app.HOME_TRAILERS_PLAYLIST_ID}"
            ),
            "items": [{
                "video_id": "abc_DEF-123",
                "title": "Example Trailer",
                "url": "https://www.youtube.com/watch?v=abc_DEF-123",
                "thumbnail_url": "https://i.ytimg.com/vi/abc_DEF-123/hqdefault.jpg",
                "published_at": "2026-07-28T12:00:00+00:00",
                "views": 10,
            }],
            "stale": False,
        }
        with patch.object(app._home_trailers_feed, "get", return_value=payload):
            response = self.client.get("/api/home/trailers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)

    def test_home_trailers_does_not_accept_a_caller_supplied_playlist(self):
        with patch.object(app._home_trailers_feed, "get", return_value={
            "playlist_id": app.HOME_TRAILERS_PLAYLIST_ID,
            "title": "HOT New Trailers & Exclusives",
            "source_url": "",
            "items": [],
            "stale": False,
        }) as mocked_get:
            response = self.client.get("/api/home/trailers?playlist_id=attacker-value")

        self.assertEqual(response.status_code, 200)
        mocked_get.assert_called_once_with()
        self.assertEqual(response.get_json()["playlist_id"], app.HOME_TRAILERS_PLAYLIST_ID)

    def test_home_trailers_returns_a_stable_error_contract(self):
        with patch.object(
            app._home_trailers_feed,
            "get",
            side_effect=app.YouTubePlaylistError("YouTube playlist is temporarily unavailable"),
        ):
            response = self.client.get("/api/home/trailers")

        self.assertEqual(response.status_code, 502)
        payload = response.get_json()
        self.assertEqual(payload["items"], [])
        self.assertEqual(payload["playlist_id"], app.HOME_TRAILERS_PLAYLIST_ID)
        self.assertIn("temporarily unavailable", payload["error"])


if __name__ == "__main__":
    unittest.main()
