from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "src" / "App.jsx").read_text(encoding="utf-8")
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
        self.assertIn("--workspace-content-base-max-width: 1640px;", STYLES)
        self.assertIn(
            "--workspace-content-max-width: var(--workspace-content-base-max-width);",
            STYLES,
        )

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

    def test_desktop_sidebar_collapses_without_changing_workspace_padding(self):
        self.assertIn("--sidebar-width: 280px;", STYLES)
        self.assertIn("--sidebar-collapsed-width: 84px;", STYLES)
        self.assertIn(
            "grid-template-columns: var(--sidebar-width) minmax(0, 1fr);",
            selector_rule(STYLES, ".app-shell"),
        )
        self.assertIn(
            ".app-shell-sidebar-collapsed {\n"
            "    --workspace-content-max-width: calc(",
            STYLES,
        )
        self.assertIn(
            "+ var(--sidebar-width)\n"
            "      - var(--sidebar-collapsed-width)",
            STYLES,
        )
        self.assertIn(
            "    grid-template-columns: var(--sidebar-collapsed-width) minmax(0, 1fr);",
            STYLES,
        )
        self.assertIn("SIDEBAR_COLLAPSED_STORAGE_KEY", APP)
        self.assertIn("aria-expanded={!collapsed}", APP)
        self.assertIn("collapsed={sidebarCollapsed}", APP)
        self.assertIn(
            ".sidebar-collapsed .brand-lockup > div {\n"
            "    flex: 0 0 0;",
            STYLES,
        )
        self.assertIn("padding: 24px;", selector_rule(STYLES, ".workspace"))


if __name__ == "__main__":
    unittest.main()
