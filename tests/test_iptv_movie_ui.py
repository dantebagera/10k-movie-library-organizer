import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class IPTVMovieUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = (ROOT / "src" / "features" / "iptv" / "IPTVWorkspace.jsx").read_text(encoding="utf-8")
        cls.api = (ROOT / "src" / "api" / "iptv.js").read_text(encoding="utf-8")
        cls.css = (ROOT / "src" / "features" / "iptv" / "iptv.css").read_text(encoding="utf-8")

    def test_movie_toolbar_keeps_provider_playlists_lists_and_filters_separate(self):
        for label in (
            "Provider playlist", "All provider playlists", "My list", "All movies",
            "Genre", "Language", "Country", "Metadata", "Claimed quality", "Watched", "Sort",
        ):
            self.assertIn(label, self.workspace)
        self.assertIn("iptvMovieQuery(movieFilters, page, browsePageSize)", self.workspace)
        self.assertNotIn("createList(activeProviderId, filters", self.workspace)

    def test_unmatched_grouped_sources_and_manual_matching_have_complete_actions(self):
        for label in ("Match metadata", "Correct match", "Remove match", "Choose source", "Favorite", "Add to list"):
            self.assertIn(label, self.workspace)
        self.assertIn("movie.source_count", self.workspace)
        self.assertIn("current.sources", self.workspace)
        self.assertIn("iptvApi.movieFavorite", self.workspace)
        self.assertIn("iptvApi.setMovieList", self.workspace)

    def test_metadata_key_is_password_style_blank_and_never_loaded_from_main_settings(self):
        self.assertIn('type="password"', self.workspace)
        self.assertIn("setMetadataCredential('')", self.workspace)
        self.assertIn("IPTV TMDB credential", self.workspace)
        self.assertIn("IPTV TMDB stored on this device", self.workspace)
        self.assertIn("Test saved credential", self.workspace)
        self.assertIn("Replace credential", self.workspace)
        self.assertIn("saveMetadataSettings", self.api)
        self.assertNotIn("tmdb_key", self.workspace)
        self.assertNotIn("tmdb_key", self.api)

    def test_metadata_is_a_provider_scoped_dashboard_with_continuous_controls(self):
        self.assertIn("{ id: 'metadata', label: 'Metadata'", self.workspace)
        self.assertIn("provider sources evaluated", self.workspace)
        self.assertIn("Improve this provider", self.workspace)
        self.assertIn("Continue metadata improvement", self.workspace)
        self.assertIn("Cancel future work", self.workspace)
        self.assertIn("Retry failures", self.workspace)
        self.assertIn("Re-evaluate stale automatic results", self.workspace)
        self.assertIn("start-diagnostic", self.workspace)
        self.assertIn("Run next {formatCount(worker?.batch_limit || 100)}", self.workspace)

    def test_projection_never_uses_a_false_empty_finished_view(self):
        self.assertIn("Preparing provider movies", self.workspace)
        self.assertIn("Retry projection", self.workspace)
        self.assertIn("catalog.projection", self.workspace)
        self.assertIn("movieProjectionStatus", self.api)

    def test_card_status_and_playback_extension_contract(self):
        self.assertIn("iptv-metadata-badge", self.workspace)
        self.assertIn("is-matched-auto", self.css)
        movie_view = self.workspace.split("function MovieView", 1)[1].split("function SeriesView", 1)[0]
        self.assertNotIn("container_extension.toUpperCase", movie_view)
        self.assertIn("extension: source.container_extension", self.workspace)

    def test_rich_people_localization_and_external_links_are_iptv_owned(self):
        movie_view = self.workspace.split("function MovieView", 1)[1].split("function SeriesView", 1)[0]
        self.assertIn("function IPTVPeopleCredits", self.workspace)
        self.assertIn("Director &amp; top cast", self.workspace)
        self.assertIn("movie-expanded-people-grid", self.workspace)
        self.assertNotIn("function PeopleCredits", self.workspace)
        self.assertNotIn("TMDB {person.id}", self.workspace)
        self.assertIn("movieLocalization", self.api)
        self.assertIn("العربية", self.workspace)
        self.assertIn("current.external_url", self.workspace)
        self.assertIn("headerActions={", movie_view)
        self.assertIn("metadataActions={", movie_view)
        self.assertIn("expandedFooter={", movie_view)
        self.assertIn("voteCount={formatVoteCount(current.vote_count)}", movie_view)
        self.assertIn("title={mediaTitle(current)}", movie_view)
        self.assertIn("movieWithDisplay(state, state.base_display)", self.workspace)
        self.assertIn("movieWithDisplay({ ...state, arabic_display: localized }, localized)", self.workspace)
        self.assertIn("result.original_language === 'ar'", self.workspace)
        self.assertIn("await iptvApi.movieLocalization(requestedProviderId, result.movie_key, 'ar-SA')", self.workspace)
        self.assertIn("detailRequestRef.current !== requestId", self.workspace)
        self.assertIn("<MovieExpandedFacts movie={current} details={current} />", movie_view)
        self.assertNotIn("iptv-localization-actions", movie_view)
        self.assertNotIn("iptv-expanded-content", movie_view)

    def test_manual_match_prefill_separates_provider_title_and_year(self):
        self.assertIn("iptvMovieIdentity", self.workspace)
        self.assertIn("setMatchQuery(identity.title)", self.workspace)
        self.assertIn("setMatchYear(identity.year)", self.workspace)

    def test_all_new_movie_ui_css_is_iptv_scoped(self):
        new_selectors = [
            ".iptv-movie-toolbar", ".iptv-metadata-panel", ".iptv-metadata-badge",
            ".iptv-modal-backdrop", ".iptv-source-dialog", ".iptv-match-dialog",
            ".iptv-metadata-dashboard", ".iptv-expanded-provider-facts", ".iptv-tmdb-link",
        ]
        for selector in new_selectors:
            self.assertIn(f".iptv-workspace {selector}", self.css)


if __name__ == "__main__":
    unittest.main()
