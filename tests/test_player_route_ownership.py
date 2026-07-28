from pathlib import Path
import unittest


class PlayerRouteOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app_source = (root / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.backend = (root / "app.py").read_text(encoding="utf-8")
        cls.iptv = (
            root / "src" / "features" / "iptv" / "IPTVWorkspace.jsx"
        ).read_text(encoding="utf-8")

    def test_one_frontend_local_play_action_owns_player_route(self):
        self.assertEqual(self.app_source.count("'/api/player/play'"), 1)
        self.assertIn(
            "body: JSON.stringify({ path_key: path, restart: Boolean(options.restart) })",
            self.app_source,
        )
        self.assertNotIn("'/api/open-file'", self.app_source)
        self.assertNotIn("@app.route('/api/open-file'", self.backend)

    def test_iptv_and_streaming_players_are_not_migrated(self):
        self.assertNotIn("/api/player/play", self.iptv)
        self.assertIn("<IPTVWorkspace notify={notify} />", self.app_source)
        stream_modal = self.app_source.split(
            "function StreamPlayerModal(",
            1,
        )[1]
        self.assertIn("<iframe", stream_modal)
        self.assertNotIn("/api/player/play", stream_modal)

    def test_local_play_fallback_is_explained_without_duplicate_routes(self):
        self.assertIn(
            "Cinema Paradiso Player was unavailable. Opened the OS player.",
            self.app_source,
        )
        self.assertIn("result.mode === 'built_in'", self.app_source)


if __name__ == "__main__":
    unittest.main()
