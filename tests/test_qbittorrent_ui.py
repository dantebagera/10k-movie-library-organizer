from pathlib import Path
import json
import unittest
from tests.frontend_source import read_frontend_source


class QBittorrentUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source = read_frontend_source()
        cls.help_source = (root / "src" / "features" / "help" / "HelpWorkspace.jsx").read_text(encoding="utf-8")
        cls.backend_source = (root / "app.py").read_text(encoding="utf-8")

    def test_sidebar_has_downloads_navigation(self):
        self.assertIn("id: 'downloads'", self.source)
        self.assertNotIn("if (id === 'downloads')", self.source)
        self.assertIn("activeSection === 'downloads'", self.source)

    def test_sidebar_has_help_navigation(self):
        self.assertIn("id: 'help'", self.source)
        self.assertIn("label: 'Help'", self.source)
        self.assertIn("mountedSections.has('help')", self.source)
        self.assertIn("hidden={activeSection !== 'help'}", self.source)

    def test_help_workspace_documents_optional_integrations(self):
        self.assertIn("function HelpWorkspace()", self.help_source)
        for text in ["Plex", "Prowlarr", "TMDB", "Ollama", "qBittorrent", "Open Settings"]:
            self.assertIn(text, self.help_source)

    def test_help_workspace_contains_medium_cp_manual(self):
        self.assertIn("Cinema Paradiso Manual", self.help_source)
        for text in [
            "Quick Start",
            "Home dashboard",
            "Library workspace",
            "Library Maintenance workspace",
            "Discover workspace",
            "Downloads workspace",
            "Settings workspace",
            "Safety rules",
            "What CP does",
            "What CP will not do"
        ]:
            self.assertIn(text, self.help_source)

    def test_downloads_workspace_keeps_cp_shell_and_frames_qbittorrent(self):
        self.assertIn("function DownloadsWorkspace()", self.source)
        self.assertIn('title="qBittorrent Downloads"', self.source)
        self.assertIn('src="/qbittorrent/"', self.source)
        self.assertIn("@app.route('/qbittorrent/')", self.backend_source)

    def test_downloads_workspace_has_no_migration_only_import_audit(self):
        root = Path(__file__).resolve().parents[1]
        downloads_source = (root / "src" / "features" / "downloads" / "DownloadsWorkspace.jsx").read_text(encoding="utf-8")

        self.assertNotIn("/api/qbittorrent/import-audit", downloads_source)
        self.assertNotIn("Legacy import audit", downloads_source)
        self.assertNotIn("@app.route('/api/qbittorrent/import-audit')", self.backend_source)
        self.assertNotIn("verify_legacy_qbittorrent_imports", self.backend_source)

    def test_downloads_header_credits_qbittorrent_with_official_icon(self):
        self.assertIn('src="/qbittorrent/images/qbittorrent32.png"', self.source)
        self.assertIn("Powered by qBittorrent", self.source)
        self.assertIn("downloads-title-credit", self.source)

    def test_torrent_results_submit_to_embedded_api(self):
        self.assertIn("'/api/qbittorrent/submit'", self.source)
        self.assertIn("{mode === 'system' ? 'Open magnet' : 'Download'}", self.source)
        self.assertNotIn("Send to qBittorrent", self.source)

    def test_torrent_submission_reports_existing_imported_jobs(self):
        self.assertIn("job.already_exists", self.source)
        self.assertIn("already imported", self.source)

    def test_indexer_cards_receive_notify_for_torrent_submission(self):
        component = self.source.split("function IndexerMovieCard({", 1)[1].split("}) {", 1)[0]
        self.assertIn("notify,", component)

    def test_prowlarr_download_url_is_not_opened_in_new_tab(self):
        self.assertNotIn("href={actionUrl} target=\"_blank\"", self.source)
        self.assertIn("Open source page", self.source)
        self.assertIn("Open externally", self.source)

    def test_qbittorrent_dynamic_views_are_proxied(self):
        self.assertIn("@app.route('/views/<path:filename>')", self.backend_source)

    def test_settings_expose_torrent_mode_and_storage_paths(self):
        self.assertIn("Torrent handling", self.source)
        self.assertIn("Movie download folder", self.source)
        self.assertIn("Incomplete downloads folder", self.source)

    def test_settings_updates_the_embedded_portable_qbittorrent_runtime(self):
        self.assertNotIn('label="Install qBittorrent"', self.source)
        self.assertIn('label="Update qBittorrent"', self.source)
        self.assertIn("fetchJson('/api/qbittorrent/update'", self.source)
        self.assertIn("forms.qbittorrent.mode === 'embedded'", self.source)

    def test_settings_show_portable_qbittorrent_runtime_text(self):
        self.assertIn("Portable qBittorrent", self.source)
        self.assertIn("Open Downloads", self.source)

    def test_settings_exposes_configurable_streaming_link(self):
        self.assertIn("Streaming Link", self.source)
        self.assertIn("streaming_url_template", self.backend_source)
        self.assertIn("https://streamimdb.ru/embed/movie/{tmdb_id}", self.source)
        self.assertIn("StreamPlayerModal", self.source)
        self.assertNotIn("playimdb.com", self.source)

    def test_streaming_modal_shows_loading_feedback_until_iframe_loads(self):
        modal_source = self.source.split("function StreamPlayerModal(", 1)[1].split("function ", 1)[0]
        self.assertIn("streamStatusVisible", modal_source)
        self.assertIn("streamLoaded", modal_source)
        self.assertIn("streamSlow", modal_source)
        self.assertIn("onLoad={() => setStreamLoaded(true)}", modal_source)
        self.assertIn("Loading stream", modal_source)
        self.assertIn("Preparing stream", modal_source)
        self.assertIn("This stream is taking longer than usual", modal_source)

    def test_readme_and_changelog_match_package_release_version(self):
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
        package = json.loads((root / "package.json").read_text(encoding="utf-8"))
        release_version = package["version"]

        self.assertIn(f"**Current release: v{release_version}**", readme)
        self.assertIn("Help", readme)
        self.assertIn("bundled qbittorrent", readme.lower())
        self.assertIn(f"## v{release_version}", changelog)
        self.assertIn("Help", changelog)


if __name__ == "__main__":
    unittest.main()
