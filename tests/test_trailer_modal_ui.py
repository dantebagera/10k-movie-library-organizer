from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TrailerModalUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "src" / "App.jsx").read_text(encoding="utf-8")

    def test_trailer_buttons_use_shared_modal_instead_of_youtube_tabs(self):
        self.assertIn("function TrailerModal(", self.app_source)
        self.assertIn("toYouTubeEmbedUrl", self.app_source)
        self.assertIn("openTrailerModal", self.app_source)
        self.assertNotIn("window.open(details.trailer_url", self.app_source)
        self.assertNotIn("window.open(`https://www.youtube.com/results?search_query=", self.app_source)

    def test_home_playlist_videos_reuse_the_same_youtube_modal(self):
        self.assertIn("function openYouTubeVideo(", self.app_source)
        self.assertIn("function openHomeTrailerVideo(", self.app_source)
        self.assertIn("openYouTubeVideo({", self.app_source)
        self.assertEqual(self.app_source.count("function TrailerModal("), 1)
        self.assertIn("function TrailerRecommendationGrid(", self.app_source)
        self.assertIn("loadYouTubeIframeApi()", self.app_source)
        self.assertIn("setShowEndRecommendations(true)", self.app_source)
        self.assertIn("setActiveVideo(video)", self.app_source)
        self.assertIn("homeTrailerSession: true", self.app_source)
        self.assertIn("activeVideo?.source_name || 'New Trailers'", self.app_source)
        self.assertNotIn("More from Rotten Tomatoes", self.app_source)

    def test_missing_tmdb_trailer_searches_youtube_only_inside_shared_modal(self):
        self.assertIn("searchYouTubeMovieTrailers({ title: requestedMovie.title, year: requestedMovie.year }", self.app_source)
        self.assertIn("Finding an embeddable trailer", self.app_source)
        self.assertIn("Choose the correct trailer", self.app_source)
        self.assertIn("setFallbackVideo(video)", self.app_source)
        self.assertIn("Search YouTube manually", self.app_source)

    def test_movie_trailer_player_recovers_from_youtube_embed_errors(self):
        self.assertIn("onError: ({ data })", self.app_source)
        self.assertIn("requestTrailerAlternatives();", self.app_source)
        self.assertIn("Try another trailer", self.app_source)
        self.assertIn("Cinema Paradiso only keeps this choice for this open trailer session.", self.app_source)

    def test_trailer_modal_embeds_youtube_player_with_fullscreen_controls(self):
        self.assertIn("function TrailerModal(", self.app_source)
        modal_source = self.app_source.split("function TrailerModal(", 1)[1].split("function ", 1)[0]

        self.assertIn("<iframe", modal_source)
        self.assertIn("allowFullScreen", modal_source)
        self.assertIn("enablejsapi=1", modal_source)
        self.assertIn(
            'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"',
            modal_source,
        )
        self.assertIn("Stop trailer", modal_source)


if __name__ == "__main__":
    unittest.main()
