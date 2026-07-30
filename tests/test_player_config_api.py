import unittest
from unittest.mock import call, patch

import app
from services.player_config import PlayerConfig


class PlayerConfigApiTests(unittest.TestCase):
    def setUp(self):
        self.original_payload = app._player_config.storage_payload()
        self.player_config = PlayerConfig()
        app._player_config._config = self.player_config._config
        self.client = app.app.test_client()
        self.save_patch = patch.object(app, "_save_config")
        self.save_config = self.save_patch.start()

    def tearDown(self):
        self.save_patch.stop()
        app._player_config._config = PlayerConfig(self.original_payload)._config

    def test_get_returns_os_default_and_no_secrets(self):
        response = self.client.get("/api/player/config")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mode"], "os_default")
        self.assertNotIn("api_key", payload["providers"]["subdl"])

    def test_put_persists_redacted_configuration(self):
        response = self.client.put("/api/player/config", json={
            "mode": "built_in",
            "preferred_audio_languages": ["ar", "en"],
            "providers": {
                "subdl": {"enabled": True, "api_key": "never-return-this"},
            },
        })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["mode"], "built_in")
        self.assertNotIn("never-return-this", str(payload))
        self.assertTrue(payload["providers"]["subdl"]["api_key_configured"])
        self.save_config.assert_called_once()
        stored = self.save_config.call_args.args[0]["player"]
        self.assertEqual(stored["providers"]["subdl"]["api_key"], "never-return-this")

    def test_put_rejects_invalid_threshold_without_saving(self):
        response = self.client.put(
            "/api/player/config",
            json={"completion_threshold": 0.1},
        )

        self.assertEqual(response.status_code, 400)
        self.save_config.assert_not_called()

    def test_put_api_key_only_mode_clears_account_credentials(self):
        self.client.put("/api/player/config", json={
            "providers": {
                "opensubtitles": {
                    "enabled": True,
                    "authentication_mode": "account",
                    "username": "account-user",
                    "api_key": "consumer-key",
                    "password": "account-password",
                },
            },
        })
        self.save_config.reset_mock()

        response = self.client.put("/api/player/config", json={
            "providers": {
                "opensubtitles": {
                    "enabled": True,
                    "authentication_mode": "api_key_only",
                },
            },
        })

        self.assertEqual(response.status_code, 200)
        public = response.get_json()["providers"]["opensubtitles"]
        self.assertEqual(public["authentication_mode"], "api_key_only")
        self.assertTrue(public["api_key_configured"])
        self.assertFalse(public["username_configured"])
        self.assertFalse(public["password_configured"])
        stored = self.save_config.call_args.args[0]["player"]["providers"]["opensubtitles"]
        self.assertEqual(stored["api_key"], "consumer-key")
        self.assertEqual(stored["username"], "")
        self.assertEqual(stored["password"], "")

    def test_reset_restores_install_default(self):
        self.client.put("/api/player/config", json={"mode": "built_in"})
        self.save_config.reset_mock()

        response = self.client.put("/api/player/config", json={"reset": True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["mode"], "os_default")
        self.save_config.assert_called_once()

    def test_status_is_quick_and_verify_hashes_every_file(self):
        ready = {
            "state": "ready",
            "ready": True,
            "os_fallback_available": True,
        }
        with patch.object(app._player_runtime, "status", return_value=ready) as status:
            quick = self.client.get("/api/player/status")
            verified = self.client.post("/api/player/verify")

        self.assertEqual(quick.status_code, 200)
        self.assertEqual(verified.status_code, 200)
        self.assertIn("subtitles", quick.get_json())
        self.assertNotIn("secret", str(quick.get_json()).lower())
        self.assertEqual(
            status.call_args_list,
            [
                call(verify_hashes=False),
                call(verify_hashes=True),
            ],
        )


if __name__ == "__main__":
    unittest.main()
