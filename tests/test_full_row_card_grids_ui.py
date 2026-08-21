from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FullRowCardGridUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.home = (ROOT / "src" / "features" / "home" / "HomeWorkspace.jsx").read_text(encoding="utf-8")
        cls.library = (ROOT / "src" / "features" / "library" / "LibraryWorkspace.jsx").read_text(encoding="utf-8")
        cls.ai_control = (ROOT / "src" / "features" / "ai-control" / "AIControlWorkspace.jsx").read_text(encoding="utf-8")
        cls.movie_lists = (ROOT / "src" / "features" / "movie-lists" / "MovieListsWorkspace.jsx").read_text(encoding="utf-8")
        cls.iptv = (ROOT / "src" / "features" / "iptv" / "IPTVWorkspace.jsx").read_text(encoding="utf-8")
        cls.discover = (ROOT / "src" / "features" / "discover" / "DiscoverWorkspace.jsx").read_text(encoding="utf-8")
        cls.grid = (ROOT / "src" / "components" / "DiscoverResultGrid.jsx").read_text(encoding="utf-8")

    def test_home_preview_uses_six_cards_for_three_rows(self):
        self.assertIn("movies.slice(0, 6)", self.home)
        self.assertNotIn("movies.slice(0, 8)", self.home)
        self.assertNotIn("movies.slice(0, 5)", self.home)

    def test_home_new_previews_measure_and_render_only_complete_rows(self):
        self.assertIn("useCardGridMetrics({ target: 5, max: 5, bias: 'lower' })", self.home)
        self.assertIn("useCardGridMetrics({ target: 6, min: 6, max: 6 })", self.home)
        self.assertIn("/api/tmdb/discover?list=upcoming&page=1&page_size=100", self.app)
        self.assertIn("items.slice(safePage * pageSize, safePage * pageSize + pageSize)", self.home)
        self.assertIn("(movies || []).slice(0, pageSize)", self.home)
        self.assertIn('className="home-trailer-grid" ref={gridRef}', self.home)
        self.assertIn('className="coming-soon-grid" ref={gridRef}', self.home)

    def test_library_uses_measured_full_row_page_size(self):
        self.assertIn("useCardGridMetrics({ target: 40, max: 100, bias: 'lower' })", self.library)
        self.assertIn("ref={mode === 'movie' ? libraryMovieGridRef : undefined}", self.library)
        self.assertIn("activeLibraryQueryRef.current = activeLibraryQuery", self.library)
        self.assertIn("[currentPage, notify, pageSize]", self.library)

    def test_ai_control_uses_measured_client_page_size(self):
        self.assertIn("useCardGridMetrics({ target: targetPageSize, max: 200, bias: 'lower' })", self.ai_control)
        self.assertIn("gridRef={aiControlGridRef}", self.ai_control)
        self.assertIn("<DiscoverResultGrid gridRef={gridRef}", self.ai_control)

    def test_discover_grid_accepts_shared_measurement_ref(self):
        self.assertIn("className, gridRef, children", self.grid)
        self.assertGreaterEqual(self.grid.count("ref={gridRef}"), 2)

    def test_movie_lists_paginate_the_measured_grid(self):
        self.assertIn("useCardGridMetrics({ target: 40, max: 200, bias: 'lower' })", self.movie_lists)
        self.assertIn("ref={movieListsGridRef}", self.movie_lists)
        self.assertIn("visibleMovieListRows.map((row)", self.movie_lists)

    def test_iptv_sends_the_measured_page_size_to_the_existing_api(self):
        self.assertIn("page_size: browsePageSize", self.iptv)
        self.assertIn("ref={gridRef} className=\"discover-grid iptv-movie-grid\"", self.iptv)
        self.assertIn("ref={gridRef} className=\"iptv-poster-grid\"", self.iptv)
        self.assertIn("favoriteKind === 'all'", self.iptv)

    def test_iptv_movies_reuse_the_discover_and_library_grid_owner(self):
        iptv_css = (ROOT / "src" / "features" / "iptv" / "iptv.css").read_text(encoding="utf-8")
        self.assertNotIn(".iptv-movie-grid", iptv_css)

    def test_discover_uses_measured_counts_for_every_remote_card_grid(self):
        self.assertIn("page_size: discoverMoviePageSize", self.discover)
        self.assertIn("page_size=${discoverPeoplePageSize}", self.discover)
        self.assertIn("page_size=${discoverKeywordPageSize}", self.discover)
        self.assertIn("gridRef={discoverMovieGridRef}", self.discover)
        self.assertIn("gridRef={discoverPeopleGridRef}", self.discover)
        self.assertIn("gridRef={discoverKeywordGridRef}", self.discover)
        self.assertIn("gridRef={pickMovieGridRef}", self.discover)

    def test_finite_discover_contexts_are_client_paginated(self):
        self.assertIn("visibleDiscoverResults.map((movie, index)", self.discover)
        self.assertIn("visiblePickResults.map((movie)", self.discover)
        self.assertIn("ariaLabel: 'Local Discover result pagination'", self.discover)
        self.assertIn("ariaLabel: 'Local AI Pick pagination'", self.discover)
        self.assertIn("pagination={exploreMoviePagination}", self.discover)
        self.assertIn("pagination={pickMoviePagination}", self.discover)


if __name__ == "__main__":
    unittest.main()
