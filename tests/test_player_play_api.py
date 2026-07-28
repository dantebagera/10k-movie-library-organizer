import unittest
from unittest.mock import patch

import app
from services.player_catalog import PlayerMediaError
from services.player_manager import PlayerLaunchError


class PlayerPlayApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_play_accepts_only_catalog_identity(self):
        with patch.object(
            app._player_manager,
            "play",
            return_value={"ok": True, "mode": "os_default", "fallback": False},
        ) as play:
            response = self.client.post(
                "/api/player/play",
                json={"path_key": r"E:\Movies\Movie.mkv"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mode"], "os_default")
        play.assert_called_once_with(r"E:\Movies\Movie.mkv")

    def test_play_rejects_arbitrary_path_field_before_manager(self):
        with patch.object(app._player_manager, "play") as play:
            response = self.client.post(
                "/api/player/play",
                json={
                    "path_key": r"E:\Movies\Movie.mkv",
                    "path": r"C:\Windows\System32\calc.exe",
                },
            )

        self.assertEqual(response.status_code, 400)
        play.assert_not_called()

    def test_play_maps_catalog_and_launch_failures_without_exposing_paths(self):
        with patch.object(
            app._player_manager,
            "play",
            side_effect=PlayerMediaError("The selected library file is missing"),
        ):
            missing = self.client.post(
                "/api/player/play",
                json={"path_key": "missing-key"},
            )
        with patch.object(
            app._player_manager,
            "play",
            side_effect=PlayerLaunchError("Operating-system playback is unavailable"),
        ):
            unavailable = self.client.post(
                "/api/player/play",
                json={"path_key": "catalog-key"},
            )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(unavailable.status_code, 503)
        self.assertNotIn("C:\\", str(unavailable.get_json()))

    def test_obsolete_open_file_route_is_removed(self):
        response = self.client.post(
            "/api/open-file",
            json={"path": r"E:\Movies\Movie.mkv"},
        )

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
