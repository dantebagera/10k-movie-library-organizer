import unittest

from services.player_config import (
    DEFAULT_KEYBOARD_SHORTCUTS,
    PlayerConfig,
    PlayerConfigError,
)


class PlayerConfigTests(unittest.TestCase):
    def test_existing_installations_default_to_os_player(self):
        config = PlayerConfig()

        self.assertEqual(config.public_payload()["mode"], "os_default")
        self.assertEqual(config.public_payload()["completion_threshold"], 0.92)
        self.assertEqual(config.public_payload()["minimum_resume_seconds"], 120)
        self.assertFalse(config.public_payload()["auto_subtitle_search"])

    def test_credentials_are_stored_but_never_returned(self):
        config = PlayerConfig()
        public = config.update({
            "providers": {
                "opensubtitles": {
                    "enabled": True,
                    "username": "dante",
                    "api_key": "open-secret",
                    "password": "account-secret",
                },
                "subdl": {
                    "enabled": True,
                    "api_key": "subdl-secret",
                },
            },
        })

        serialized_public = str(public)
        self.assertNotIn("dante", serialized_public)
        self.assertNotIn("open-secret", serialized_public)
        self.assertNotIn("account-secret", serialized_public)
        self.assertNotIn("subdl-secret", serialized_public)
        self.assertTrue(public["providers"]["opensubtitles"]["api_key_configured"])
        self.assertTrue(public["providers"]["opensubtitles"]["username_configured"])
        self.assertTrue(public["providers"]["opensubtitles"]["password_configured"])
        self.assertEqual(
            public["providers"]["opensubtitles"]["authentication_mode"],
            "account",
        )
        self.assertTrue(public["providers"]["subdl"]["api_key_configured"])
        stored = config.storage_payload()
        self.assertEqual(stored["providers"]["opensubtitles"]["api_key"], "open-secret")
        self.assertEqual(stored["providers"]["opensubtitles"]["username"], "dante")
        self.assertEqual(stored["providers"]["subdl"]["api_key"], "subdl-secret")

    def test_blank_write_only_credentials_preserve_saved_values(self):
        config = PlayerConfig({
            "providers": {
                "opensubtitles": {"api_key": "keep-me"},
            },
        })

        config.update({"providers": {"opensubtitles": {"api_key": ""}}})

        self.assertEqual(
            config.storage_payload()["providers"]["opensubtitles"]["api_key"],
            "keep-me",
        )

    def test_credentials_require_explicit_clear(self):
        config = PlayerConfig({
            "providers": {
                "opensubtitles": {"api_key": "remove-me"},
            },
        })

        config.update({
            "providers": {
                "opensubtitles": {"clear_secrets": ["api_key"]},
            },
        })

        self.assertFalse(
            config.public_payload()["providers"]["opensubtitles"]["api_key_configured"]
        )

    def test_api_key_only_mode_clears_account_credentials_but_keeps_key(self):
        config = PlayerConfig({
            "providers": {
                "opensubtitles": {
                    "authentication_mode": "account",
                    "username": "dante",
                    "api_key": "keep-api-key",
                    "password": "account-secret",
                },
            },
        })

        public = config.update({
            "providers": {
                "opensubtitles": {
                    "authentication_mode": "api_key_only",
                },
            },
        })

        stored = config.storage_payload()["providers"]["opensubtitles"]
        self.assertEqual(stored["authentication_mode"], "api_key_only")
        self.assertEqual(stored["api_key"], "keep-api-key")
        self.assertEqual(stored["username"], "")
        self.assertEqual(stored["password"], "")
        self.assertFalse(public["providers"]["opensubtitles"]["username_configured"])
        self.assertFalse(public["providers"]["opensubtitles"]["password_configured"])

    def test_existing_account_credentials_migrate_to_explicit_account_mode(self):
        config = PlayerConfig({
            "providers": {
                "opensubtitles": {
                    "username": "dante",
                    "api_key": "api-key",
                    "password": "account-secret",
                },
            },
        })

        provider = config.storage_payload()["providers"]["opensubtitles"]

        self.assertEqual(provider["authentication_mode"], "account")
        self.assertEqual(provider["username"], "dante")
        self.assertEqual(provider["password"], "account-secret")

    def test_explicit_api_key_only_storage_drops_stale_account_credentials(self):
        config = PlayerConfig({
            "providers": {
                "opensubtitles": {
                    "authentication_mode": "api_key_only",
                    "username": "stale-user",
                    "api_key": "api-key",
                    "password": "stale-password",
                },
            },
        })

        provider = config.storage_payload()["providers"]["opensubtitles"]

        self.assertEqual(provider["authentication_mode"], "api_key_only")
        self.assertEqual(provider["username"], "")
        self.assertEqual(provider["password"], "")

    def test_rejects_unknown_opensubtitles_authentication_mode(self):
        config = PlayerConfig()

        with self.assertRaises(PlayerConfigError):
            config.update({
                "providers": {
                    "opensubtitles": {
                        "authentication_mode": "automatic_fallback",
                    },
                },
            })

    def test_preferences_validate_ranges_and_enums(self):
        config = PlayerConfig()

        with self.assertRaises(PlayerConfigError):
            config.update({"mode": "parallel-player"})
        with self.assertRaises(PlayerConfigError):
            config.update({"completion_threshold": 0.2})
        with self.assertRaises(PlayerConfigError):
            config.update({"minimum_resume_seconds": -1})
        self.assertEqual(config.public_payload()["mode"], "os_default")

    def test_shortcut_update_uses_known_actions_only(self):
        config = PlayerConfig()

        payload = config.update({"keyboard_shortcuts": {"play_pause": "K"}})

        self.assertEqual(payload["keyboard_shortcuts"]["play_pause"], "K")
        self.assertEqual(
            payload["keyboard_shortcuts"]["subtitle_search"],
            DEFAULT_KEYBOARD_SHORTCUTS["subtitle_search"],
        )
        with self.assertRaises(PlayerConfigError):
            config.update({"keyboard_shortcuts": {"launch_iptv": "T"}})

    def test_subtitle_style_is_bounded_and_preserved_as_one_config_owner(self):
        config = PlayerConfig()
        payload = config.update({
            "subtitle_style": {
                "font": "Noto Sans Arabic",
                "size": 54,
                "position": 92,
                "color": "#FFEEDDCC",
                "border_size": 3.5,
                "border_color": "#FF000000",
                "background_color": "#66000000",
            },
        })
        self.assertEqual(payload["subtitle_style"]["font"], "Noto Sans Arabic")
        self.assertEqual(payload["subtitle_style"]["size"], 54)
        with self.assertRaises(PlayerConfigError):
            config.update({"subtitle_style": {"color": "red"}})

    def test_premium_audio_hdr_and_window_state_are_bounded(self):
        config = PlayerConfig()
        payload = config.update({
            "tone_mapping": "mobius",
            "audio_downmix": "stereo",
            "window_state": {
                "x": -1600,
                "y": 80,
                "width": 1100,
                "height": 700,
                "screen": "DISPLAY2",
                "maximized": False,
                "always_on_top": True,
                "positioned": True,
            },
        })

        self.assertEqual(payload["tone_mapping"], "mobius")
        self.assertEqual(payload["audio_downmix"], "stereo")
        self.assertEqual(payload["window_state"]["x"], -1600)
        self.assertTrue(payload["window_state"]["always_on_top"])
        with self.assertRaises(PlayerConfigError):
            config.update({"window_state": {"width": 100}})
        with self.assertRaises(PlayerConfigError):
            config.update({"tone_mapping": "unbounded-filter"})

    def test_reset_restores_os_default_and_clears_provider_secrets(self):
        config = PlayerConfig()
        config.update({
            "mode": "built_in",
            "providers": {"subdl": {"api_key": "secret"}},
        })

        payload = config.reset()

        self.assertEqual(payload["mode"], "os_default")
        self.assertFalse(payload["providers"]["subdl"]["api_key_configured"])


if __name__ == "__main__":
    unittest.main()
