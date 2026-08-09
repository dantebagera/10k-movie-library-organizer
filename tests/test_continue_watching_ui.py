from pathlib import Path
import unittest


class ContinueWatchingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app = (root / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.home = (
            root / "src" / "features" / "home" / "HomeWorkspace.jsx"
        ).read_text(encoding="utf-8")
        cls.card = (
            root / "src" / "components" / "movie-card" / "MovieCard.jsx"
        ).read_text(encoding="utf-8")
        cls.card_styles = (
            root / "src" / "components" / "movie-card" / "movieCard.css"
        ).read_text(encoding="utf-8")
        cls.styles = (root / "src" / "styles.css").read_text(encoding="utf-8")

    def test_home_places_full_width_trailers_then_continue_in_main_stack(self):
        hero_end = self.home.index("</section>")
        health = self.home.index("<HealthPanel")
        releases = self.home.index("<ReleasePanel")
        continue_rail = self.home.index("<ContinueWatchingRail")
        self.assertLess(hero_end, health)
        self.assertLess(health, releases)
        self.assertLess(releases, continue_rail)
        self.assertIn('className="home-status-grid"', self.home)
        trailers = self.home.index("<HomeTrailersPanel")
        main_grid = self.home.index('className="home-main-grid"')
        self.assertLess(trailers, main_grid)
        self.assertLess(main_grid, continue_rail)
        self.assertIn('className="home-media-grid"', self.home)
        self.assertIn('className="home-main-stack"', self.home)
        self.assertIn("<HomeTrailersPanel", self.home)
        self.assertIn(".home-status-grid,\n.home-main-grid", self.styles)
        self.assertIn(".home-media-grid,\n.home-main-stack", self.styles)
        self.assertIn("grid-template-columns: minmax(0, 1.1fr) minmax(340px, 0.72fr);", self.styles)
        self.assertIn("movies.slice(0, 6)", self.home)
        self.assertIn("target: 5, max: 5", self.home)

    def test_compact_variant_is_owned_by_shared_movie_card_system(self):
        self.assertIn("export function ContinueMovieCard", self.card)
        self.assertIn("<UnifiedMoviePoster", self.card)
        self.assertIn('className="continue-movie-poster"', self.card)
        self.assertIn("width: 156px;", self.card_styles)
        self.assertIn("height: 234px;", self.card_styles)
        self.assertIn("object-fit: contain;", self.card_styles)

    def test_tile_contains_only_resume_progress_title_remaining_and_menu(self):
        self.assertIn("showPlayOverlay", self.card)
        self.assertIn('role="progressbar"', self.card)
        self.assertIn("remainingLabel", self.card)
        self.assertIn("> Restart", self.card)
        self.assertIn("> Remove", self.card)
        for forbidden in ("rating={", "quality", "plot", "cast"):
            self.assertNotIn(forbidden, self.card[self.card.index("export function ContinueMovieCard"):])

    def test_home_actions_use_centralized_player_and_progress_routes(self):
        self.assertIn("/api/player/continue-watching?limit=50", self.app)
        self.assertIn("/api/player/play", self.app)
        self.assertIn("/api/player/progress/clear", self.app)
        self.assertIn("restart: Boolean(options.restart)", self.app)


if __name__ == "__main__":
    unittest.main()
