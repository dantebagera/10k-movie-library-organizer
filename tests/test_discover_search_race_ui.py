from pathlib import Path
import re
import unittest
from tests.frontend_source import read_frontend_source


ROOT = Path(__file__).resolve().parents[1]
APP = read_frontend_source()


class DiscoverSearchRaceUiTest(unittest.TestCase):
    def test_fresh_discover_search_clears_stale_results_before_fetching(self):
        load_start = APP.index("async function loadDiscover")
        fetch_start = APP.index("const data = await fetchJson(url);", load_start)
        pre_fetch = APP[load_start:fetch_start]

        self.assertIn("if (!append) {", pre_fetch)
        self.assertIn("setDiscoverResults([]);", pre_fetch)
        self.assertIn("setDiscoverContext(null);", pre_fetch)
        self.assertIn("setDiscoverHistory([]);", pre_fetch)

    def test_discover_search_ignores_stale_in_flight_responses(self):
        self.assertIn("useRef", APP)
        self.assertIn("discoverRequestSeq", APP)
        self.assertRegex(
            APP,
            re.compile(
                r"const requestSeq = discoverRequestSeq\.current \+ 1;.*"
                r"discoverRequestSeq\.current = requestSeq;.*"
                r"if \(requestSeq !== discoverRequestSeq\.current\) return;",
                re.S,
            ),
        )

    def test_discover_result_card_keys_include_position_to_handle_duplicate_tmdb_rows(self):
        self.assertIn("visibleDiscoverResults.map((movie, index)", APP)
        self.assertIn('key={`${movie.tmdb_id || movie.title}-${movie.year}-${index}`}', APP)


if __name__ == "__main__":
    unittest.main()
