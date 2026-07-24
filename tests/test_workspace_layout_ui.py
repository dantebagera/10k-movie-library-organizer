from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
STYLES = (ROOT / "src" / "styles.css").read_text(encoding="utf-8")
IPTV_STYLES = (ROOT / "src" / "features" / "iptv" / "iptv.css").read_text(encoding="utf-8")


def selector_rule(source, selector):
    match = re.search(
        rf"^{re.escape(selector)}\s*\{{(?P<body>.*?)\}}",
        source,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"Missing CSS rule for {selector}")
    return match.group("body")


class WorkspaceLayoutUiTest(unittest.TestCase):
    def test_production_workspaces_share_discover_content_width(self):
        self.assertIn("--workspace-content-max-width: 1640px;", STYLES)

        selectors = [
            ".downloads-workspace",
            ".ai-control-workspace",
            ".help-workspace",
            ".topbar",
            ".home-grid",
            ".library-workspace",
            ".movie-lists-workspace",
            ".cleanup-workspace",
            ".settings-workspace",
            ".discover-workspace",
        ]
        for selector in selectors:
            with self.subTest(selector=selector):
                self.assertIn(
                    "max-width: var(--workspace-content-max-width);",
                    selector_rule(STYLES, selector),
                )

        self.assertIn(
            "max-width: var(--workspace-content-max-width);",
            selector_rule(IPTV_STYLES, ".iptv-workspace"),
        )

    def test_shared_workspace_keeps_discover_outer_padding(self):
        workspace = selector_rule(STYLES, ".workspace")
        self.assertIn("padding: 24px;", workspace)
        self.assertIn("scrollbar-gutter: stable;", workspace)


if __name__ == "__main__":
    unittest.main()
