from pathlib import Path
import unittest

from tools.generate_player_theme import expected_outputs, load_theme


class PlayerThemeTests(unittest.TestCase):
    def test_generated_react_and_qml_theme_outputs_are_current(self):
        for path, expected in expected_outputs().items():
            self.assertEqual(path.read_text(encoding="utf-8"), expected)

    def test_one_theme_source_owns_required_player_tokens(self):
        theme = load_theme()

        self.assertEqual(theme["colors"]["projectorGold"], "#d4af37")
        self.assertEqual(theme["colors"]["archiveBlack"], "#0a0a0b")
        self.assertEqual(theme["timing"]["controlsHideMs"], 2500)

    def test_global_css_imports_generated_theme_before_application_styles(self):
        root = Path(__file__).resolve().parents[1]
        main = (root / "src" / "main.jsx").read_text(encoding="utf-8")
        styles = (root / "src" / "styles.css").read_text(encoding="utf-8")

        self.assertLess(
            main.index("'./styles/playerTheme.css'"),
            main.index("'./styles.css'"),
        )
        self.assertNotIn("--projector-gold: #", styles)
        self.assertNotIn("--archive-black: #", styles)


if __name__ == "__main__":
    unittest.main()
