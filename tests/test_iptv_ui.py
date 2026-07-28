import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IPTVUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.workspace_source = (ROOT / "src" / "features" / "iptv" / "IPTVWorkspace.jsx").read_text(encoding="utf-8")
        cls.lists_source = (ROOT / "src" / "features" / "iptv" / "IPTVListsWorkspace.jsx").read_text(encoding="utf-8")
        cls.api_source = (ROOT / "src" / "api" / "iptv.js").read_text(encoding="utf-8")
        cls.player_source = (ROOT / "src" / "features" / "iptv" / "IPTVPlayer.jsx").read_text(encoding="utf-8")
        cls.sync_policy_source = (ROOT / "src" / "features" / "iptv" / "iptvSyncPolicy.js").read_text(encoding="utf-8")
        cls.settings_source = (ROOT / "src" / "features" / "settings" / "SettingsWorkspace.jsx").read_text(encoding="utf-8")

    def test_iptv_is_a_first_class_lazy_workspace(self):
        self.assertIn("const IPTVWorkspace = lazy", self.app_source)
        self.assertIn("id: 'iptv'", self.app_source)
        self.assertIn("<IPTVWorkspace notify={notify}", self.app_source)

    def test_workspace_keeps_provider_sections_and_ownership_actions_separate(self):
        for label in ("Live TV", "Movies", "Series", "Favorites", "My Lists"):
            self.assertIn(label, self.workspace_source)
        self.assertIn("All provider categories", self.workspace_source)
        self.assertNotIn("Owned", self.workspace_source)
        self.assertNotIn("Find Torrent", self.workspace_source)

    def test_favorites_are_visible_and_support_a_mixed_default_view(self):
        self.assertIn("useState('all')", self.workspace_source)
        self.assertIn("['all', 'All']", self.workspace_source)
        self.assertIn("cornerControls={<div className=\"iptv-movie-corner-actions\"", self.workspace_source)
        self.assertIn("function FavoritesView", self.workspace_source)
        self.assertIn("No favorites yet", self.workspace_source)

    def test_custom_lists_support_mixed_media_crud_and_manual_order(self):
        for label in ("New list", "Rename", "Delete", "Channels", "Movies", "Series"):
            self.assertIn(label, self.lists_source)
        self.assertIn("IPTVListPickerModal", self.workspace_source)
        self.assertIn("moveListItem", self.api_source)
        self.assertIn("setListItem", self.api_source)
        self.assertIn("Unavailable from provider", self.lists_source)

    def test_saved_iptv_credentials_are_loaded_redacted(self):
        self.assertIn("username_hint", self.settings_source)
        self.assertIn("password: ''", self.settings_source)
        self.assertIn("Allow invalid provider TLS certificate", self.settings_source)
        self.assertIn("IPTV Providers", self.settings_source)
        self.assertIn("Save & Test", self.settings_source)
        self.assertIn("settings-provider-rail", self.settings_source)

    def test_live_player_keeps_headroom_and_recovers_bounded_failures(self):
        self.assertIn("initialLiveManifestSize: 1", self.player_source)
        self.assertIn("bufferedSeconds >= 12", self.player_source)
        self.assertIn("tryStartLivePlayback(true), 15000", self.player_source)
        self.assertIn("The provider is not sending enough data", self.player_source)
        self.assertIn("liveSyncDuration: 12", self.player_source)
        self.assertIn("liveMaxLatencyDuration: 30", self.player_source)
        self.assertIn("maxBufferLength: 30", self.player_source)
        self.assertIn("networkRecoveryAttempts < 3", self.player_source)
        self.assertIn("mediaRecoveryAttempts < 2", self.player_source)
        self.assertIn("hls?.startLoad()", self.player_source)
        self.assertIn("hls.recoverMediaError()", self.player_source)

    def test_stale_provider_catalog_is_refreshed_once_on_workspace_open(self):
        self.assertIn("24 * 60 * 60 * 1000", self.sync_policy_source)
        self.assertIn("shouldAutoSyncIPTVCatalog(data)", self.workspace_source)
        self.assertIn("autoSyncRequestedRef.current.add(activeProviderId)", self.workspace_source)
        self.assertIn("const result = await iptvApi.sync(activeProviderId)", self.workspace_source)

    def test_provider_categories_follow_catalog_generation_changes(self):
        self.assertIn("iptvApi.categories(activeProviderId, activeTab)", self.workspace_source)
        self.assertIn("[activeProviderId, activeTab, status?.configured, status?.generation]", self.workspace_source)
        self.assertIn("category.category_id === selectedCategory", self.workspace_source)
        self.assertIn("setCategoryId('')", self.workspace_source)
        self.assertNotIn("if (!categories[browseKind]?.length)", self.workspace_source)

    def test_every_frontend_iptv_data_method_requires_a_provider(self):
        self.assertIn("function providerPath(providerId", self.api_source)
        self.assertIn("if (!providerId) throw new Error", self.api_source)
        self.assertNotIn("'/api/iptv/status'", self.api_source)
        self.assertNotIn("'/api/iptv/config'", self.settings_source)

    def test_provider_switch_stops_playback_and_resets_provider_state(self):
        self.assertIn("async function switchProvider(providerId)", self.workspace_source)
        self.assertIn("resetProviderState()", self.workspace_source)
        self.assertIn("iptvApi.stopPlayback(previousPlayback.provider_id", self.workspace_source)
        self.assertIn("iptvApi.selectProvider(providerId)", self.workspace_source)
        self.assertIn("activeProviderRef.current !== requestedProviderId", self.workspace_source)


if __name__ == "__main__":
    unittest.main()
