import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
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
        play.assert_called_once_with(r"E:\Movies\Movie.mkv", restart=False)

    def test_player_manager_wires_the_managed_poster_resolver(self):
        repository = object()
        with (
            patch.object(app, "_catalog_repository", return_value=repository),
            patch.object(app, "get_movies_dirs", return_value=[r"E:\Movies"]),
            patch.object(app, "resolve_library_media", return_value={}) as resolve,
        ):
            app._player_manager.media_resolver("catalog-key")

        resolve.assert_called_once_with(
            repository,
            "catalog-key",
            [r"E:\Movies"],
            local_poster_resolver=app._resolve_player_local_poster,
        )

    def test_managed_asset_reference_resolves_only_inside_the_asset_root(self):
        checksum = "c" * 64
        with tempfile.TemporaryDirectory() as root:
            asset_root = Path(root) / "assets"
            asset_root.mkdir()
            poster = asset_root / f"{checksum}.jpg"
            poster.write_bytes(b"poster")
            service = SimpleNamespace(
                assets_root=asset_root,
                lookup=lambda **kwargs: {
                    "local_path": str(poster),
                } if kwargs.get("checksum") == checksum else None,
            )
            with patch.object(app, "_media_asset_service", return_value=service):
                resolved = app._resolve_player_local_poster(
                    f"/api/assets/{checksum}"
                )

        self.assertEqual(resolved, poster.resolve())

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

    def test_restart_is_explicit_and_forwarded_to_the_single_player_route(self):
        with patch.object(
            app._player_manager,
            "play",
            return_value={"ok": True, "mode": "built_in", "fallback": False},
        ) as play:
            response = self.client.post(
                "/api/player/play",
                json={"path_key": "catalog-key", "restart": True},
            )

        self.assertEqual(response.status_code, 200)
        play.assert_called_once_with("catalog-key", restart=True)

        invalid = self.client.post(
            "/api/player/play",
            json={"path_key": "catalog-key", "restart": "yes"},
        )
        self.assertEqual(invalid.status_code, 400)

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

    def test_continue_watching_and_clear_use_playback_history_owner(self):
        item = {
            "path_key": r"e:\movies\movie.mkv",
            "title": "Movie",
            "position_ms": 5000,
            "duration_ms": 10000,
        }
        with patch.object(
            app._playback_history,
            "continue_watching",
            return_value=[item],
        ) as listing:
            response = self.client.get("/api/player/continue-watching?limit=12")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"], [item])
        listing.assert_called_once_with(limit=12)

        with patch.object(app._playback_history, "clear", return_value=True) as clear:
            removed = self.client.post(
                "/api/player/progress/clear",
                json={"path_key": item["path_key"]},
            )
        self.assertEqual(removed.status_code, 200)
        self.assertTrue(removed.get_json()["removed"])
        clear.assert_called_once_with(item["path_key"])


if __name__ == "__main__":
    unittest.main()
