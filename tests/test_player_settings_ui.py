from pathlib import Path
import unittest


class PlayerSettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.settings = (
            root / "src" / "features" / "settings" / "SettingsWorkspace.jsx"
        ).read_text(encoding="utf-8")
        cls.styles = (root / "src" / "styles.css").read_text(encoding="utf-8")
        cls.backend = (root / "app.py").read_text(encoding="utf-8")

    def test_existing_settings_workspace_owns_complete_player_card(self):
        self.assertIn('title="Cinema Paradiso Player"', self.settings)
        self.assertIn("Local Library playback mode", self.settings)
        self.assertIn("Operating-system default player", self.settings)
        self.assertIn("Minimum resume position", self.settings)
        self.assertIn("Completion threshold", self.settings)
        self.assertIn("Hardware decoding", self.settings)
        self.assertIn("Tone mapping", self.settings)
        self.assertIn("Audio channel layout", self.settings)
        self.assertIn("Subtitle font", self.settings)
        self.assertIn("Downloaded subtitle storage", self.settings)
        self.assertIn("Keyboard shortcuts", self.settings)

    def test_settings_use_dedicated_player_apis(self):
        for endpoint in (
            "/api/player/config",
            "/api/player/status",
            "/api/player/verify",
        ):
            self.assertIn(endpoint, self.settings)

    def test_runtime_status_exposes_versions_not_local_paths(self):
        for label in ("CP Player", "libmpv", "Qt", "Architecture", "Verify player"):
            self.assertIn(label, self.settings)
        self.assertNotIn("bundle_root", self.settings)
        self.assertNotIn("executable_path", self.settings)

    def test_provider_credentials_are_write_only_password_fields(self):
        self.assertIn("Credentials stay in the backend", self.settings)
        self.assertIn("Saved — enter a value to replace", self.settings)
        self.assertIn("type={revealed ? 'text' : 'password'}", self.settings)
        self.assertIn("api_key: ''", self.settings)
        self.assertIn("playerForm(saved)", self.settings)

    def test_player_scope_explicitly_excludes_iptv_and_streaming(self):
        self.assertIn(
            "IPTV and movie-card streaming keep their existing players.",
            self.settings,
        )
        self.assertNotIn("/api/open-file", self.backend)

    def test_player_card_has_desktop_two_column_layout(self):
        self.assertIn(".player-settings-columns", self.styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", self.styles)


if __name__ == "__main__":
    unittest.main()
