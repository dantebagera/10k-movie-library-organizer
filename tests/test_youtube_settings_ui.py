from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class YouTubeSettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = (ROOT / "src" / "features" / "settings" / "SettingsWorkspace.jsx").read_text(encoding="utf-8")

    def test_settings_has_a_masked_youtube_key_card(self):
        self.assertIn('id="settings-youtube"', self.settings)
        self.assertIn('label="YouTube API key"', self.settings)
        self.assertIn("fetchJson('/api/youtube/config')", self.settings)
        self.assertIn("youtube: '/api/youtube/config'", self.settings)
        self.assertIn("youtube: '/api/youtube/test'", self.settings)
        self.assertIn("The full value is never returned to this page.", self.settings)

    def test_blank_save_preserves_and_clear_is_explicit(self):
        self.assertIn("youtube: { key: forms.youtube.key }", self.settings)
        self.assertIn("body: JSON.stringify({ clear: true })", self.settings)
        self.assertIn('label="Clear key"', self.settings)


if __name__ == "__main__":
    unittest.main()
