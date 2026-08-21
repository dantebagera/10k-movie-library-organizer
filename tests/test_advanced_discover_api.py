import unittest
from unittest.mock import patch

import app
from services.advanced_search import AdvancedSearchValidationError
from services.tmdb_advanced_search import build_discover_plan, movie_matches_summary


def discover_query(groups=None, *, feed="catalog", sort="auto"):
    return {
        "version": 1,
        "scope": "discover",
        "mode": "advanced",
        "groups": groups or [],
        "sort": {"key": sort, "direction": "desc"},
        "feed": feed,
    }


class DiscoverPlannerTest(unittest.TestCase):
    def test_compiles_and_or_provider_parameters_and_boundaries(self):
        plan = build_discover_plan(discover_query([
            {"type": "genre", "join": "and", "values": [
                {"id": "18", "label": "Drama"},
                {"id": "878", "label": "Science Fiction"},
            ]},
            {"type": "keyword", "join": "or", "values": [
                {"id": "456", "label": "dystopia"},
                {"id": "123", "label": "future"},
            ]},
            {"type": "year", "values": [{"operator": "between", "from": 1990, "to": 1999}]},
            {"type": "rating", "values": [{"operator": "at_most", "value": 8.5}]},
            {"type": "runtime", "values": [{"preset": "feature"}]},
        ]))

        self.assertEqual(plan.endpoint, "/discover/movie")
        self.assertEqual(plan.provider_params["with_genres"], "18,878")
        self.assertEqual(plan.provider_params["with_keywords"], "123|456")
        self.assertEqual(plan.provider_params["primary_release_date.gte"], "1990-01-01")
        self.assertEqual(plan.provider_params["primary_release_date.lte"], "1999-12-31")
        self.assertEqual(plan.provider_params["vote_average.lte"], 8.5)
        self.assertEqual(plan.provider_params["with_runtime.gte"], 60)
        self.assertEqual(plan.provider_params["with_runtime.lte"], 149)

    def test_title_rejects_filters_tmdb_summaries_cannot_prove(self):
        title = {"type": "title", "values": [{"text": "Alien"}]}
        for unsupported in (
            {"type": "keyword", "join": "or", "values": [{"id": "1", "label": "space"}]},
            {"type": "runtime", "values": [{"preset": "short"}]},
        ):
            with self.subTest(unsupported=unsupported["type"]), self.assertRaises(AdvancedSearchValidationError):
                build_discover_plan(discover_query([title, unsupported]))

    def test_summary_missing_facts_fail_active_numeric_filter(self):
        groups = build_discover_plan(discover_query([
            {"type": "year", "values": [{"operator": "at_least", "value": 2000}]},
            {"type": "rating", "values": [{"operator": "at_least", "value": 7}]},
        ])).summary_groups
        self.assertFalse(movie_matches_summary({"release_date": "", "vote_average": None}, groups))
        self.assertTrue(movie_matches_summary({"release_date": "2001-01-01", "vote_average": 7.0}, groups))


class AdvancedDiscoverApiTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_role_filter_resolves_complete_credit_sets_before_logical_paging(self):
        query = discover_query([
            {"type": "genre", "join": "or", "values": [{"id": "18", "label": "Drama"}]},
            {"type": "person", "join": "and", "values": [
                {"id": "10", "label": "Actor", "role": "actor"},
                {"id": "20", "label": "Director", "role": "director"},
            ]},
        ])
        actor_credits = [
            {"id": index, "title": f"Actor {index}", "genre_ids": [18], "release_date": "2020-01-01", "popularity": 200-index}
            for index in range(1, 61)
        ]
        director_credits = [
            {"id": index, "title": f"Directed {index}", "genre_ids": [18], "release_date": "2020-01-01", "popularity": 200-index}
            for index in range(21, 61)
        ]
        with patch.object(app, "_tmdb_key", "test-key"), patch.object(
            app, "_tmdb_genres", {18: "Drama"}
        ), patch.object(app, "_ensure_tmdb_genres"), patch.object(
            app, "_tmdb_fetch_page_window"
        ) as page_fetch, patch.object(
            app, "_tmdb_person_credit_ids", side_effect=[
                ({str(movie["id"]) for movie in actor_credits}, actor_credits),
                ({str(movie["id"]) for movie in director_credits}, director_credits),
            ]
        ) as credit_fetch:
            response = self.client.post(
                "/api/tmdb/discover/advanced",
                json={"query": query, "page": 1, "page_size": 39},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["results"]), 39)
        self.assertEqual([movie["tmdb_id"] for movie in payload["results"][:3]], ["21", "22", "23"])
        self.assertEqual(page_fetch.call_count, 0)
        self.assertEqual(credit_fetch.call_count, 2)
        self.assertEqual(payload["total_scope"], "exact")
        self.assertEqual(payload["total_results"], 40)
        self.assertEqual(payload["total_pages"], 2)

    def test_title_summary_filter_builds_a_dense_39_card_page_across_provider_pages(self):
        query = discover_query([
            {"type": "title", "values": [{"text": "space"}]},
            {"type": "genre", "join": "or", "values": [{"id": "18", "label": "Drama"}]},
        ])
        provider_pages = {}
        for page in range(1, 6):
            provider_pages[page] = {
                "results": [
                    {"id": page * 100 + index, "title": f"Space {page}-{index}", "genre_ids": [18] if index % 2 == 0 else [28], "release_date": "2020-01-01"}
                    for index in range(20)
                ],
                "total_results": 100,
                "total_pages": 5,
            }

        def fetch_page(url):
            from urllib.parse import parse_qs, urlparse
            page = int(parse_qs(urlparse(url).query)["page"][0])
            return provider_pages[page]

        with patch.object(app, "_tmdb_key", "test-key"), patch.object(
            app, "_tmdb_genres", {18: "Drama", 28: "Action"}
        ), patch.object(app, "_ensure_tmdb_genres"), patch.object(
            app, "_tmdb_fetch_provider_page", side_effect=fetch_page
        ) as page_fetch:
            app._tmdb_dense_window_cache.clear()
            response = self.client.post(
                "/api/tmdb/discover/advanced",
                json={"query": query, "page": 1, "page_size": 39},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload["results"]), 39)
        self.assertEqual(page_fetch.call_count, 4)
        self.assertEqual(payload["total_scope"], "bounded")
        self.assertIsNone(payload["total_results"])
        self.assertTrue(payload["has_next"])

    def test_local_criteria_are_applied_before_logical_paging(self):
        query = discover_query([
            {"type": "availability", "values": [{"id": "owned", "label": "Owned"}]},
        ])
        page = {"results": [{"id": index, "title": f"Movie {index}"} for index in range(1, 21)], "total_results": 20, "total_pages": 1}
        with patch.object(app, "_tmdb_key", "test-key"), patch.object(app, "_ensure_tmdb_genres"), patch.object(
            app, "_tmdb_fetch_provider_page", return_value=page
        ), patch.object(
            app, "_tmdb_filter_local_movies", side_effect=lambda movies, groups: [movie for movie in movies if int(movie["id"]) % 2 == 0]
        ):
            app._tmdb_dense_window_cache.clear()
            response = self.client.post("/api/tmdb/discover/advanced", json={"query": query})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total_scope"], "exact")
        self.assertEqual(payload["total_results"], 10)
        self.assertEqual(payload["local_criteria"][0]["type"], "availability")

    def test_scan_budget_exhaustion_is_unknown_total_and_retryable(self):
        query = discover_query([
            {"type": "title", "values": [{"text": "rare"}]},
            {"type": "genre", "join": "or", "values": [{"id": "18", "label": "Drama"}]},
        ])

        def fetch_page(url):
            from urllib.parse import parse_qs, urlparse
            page = int(parse_qs(urlparse(url).query)["page"][0])
            return {
                "results": [{"id": page, "title": f"Rare {page}", "genre_ids": [18]}],
                "total_results": 500,
                "total_pages": 25,
            }

        with patch.object(app, "_tmdb_key", "test-key"), patch.object(
            app, "_tmdb_genres", {18: "Drama"}
        ), patch.object(app, "_ensure_tmdb_genres"), patch.object(
            app, "_tmdb_fetch_provider_page", side_effect=fetch_page
        ) as page_fetch:
            app._tmdb_dense_window_cache.clear()
            response = self.client.post(
                "/api/tmdb/discover/advanced",
                json={"query": query, "page": 1, "page_size": 39},
            )

        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(page_fetch.call_count, app.TMDB_DENSE_SCAN_PAGE_BUDGET)
        self.assertTrue(payload["budget_exhausted"])
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["total_scope"], "bounded")
        self.assertIsNone(payload["total_results"])
        self.assertIsNone(payload["total_pages"])

    def test_unknown_body_field_and_uncontrolled_ids_are_rejected(self):
        bad_id = discover_query([
            {"type": "genre", "join": "or", "values": [{"id": "Drama", "label": "Drama"}]},
        ])
        with patch.object(app, "_tmdb_key", "test-key"):
            responses = [
                self.client.post("/api/tmdb/discover/advanced", json={"query": discover_query(), "crawl": True}),
                self.client.post("/api/tmdb/discover/advanced", json={"query": bad_id}),
            ]
        self.assertEqual([response.status_code for response in responses], [400, 400])

    def test_page_contract_rejects_invalid_values_instead_of_clamping(self):
        with patch.object(app, "_tmdb_key", "test-key"):
            responses = [
                self.client.post("/api/tmdb/discover/advanced", json={"query": discover_query(), "page": "wrong"}),
                self.client.post("/api/tmdb/discover/advanced", json={"query": discover_query(), "page_size": 0}),
                self.client.post("/api/tmdb/discover/advanced", json={"query": discover_query(), "page_size": 101}),
            ]
        self.assertEqual([response.status_code for response in responses], [400, 400, 400])

    def test_unexpected_provider_failures_are_sanitized(self):
        with patch.object(app, "_tmdb_key", "test-key"), patch.object(
            app, "_ensure_tmdb_genres", side_effect=RuntimeError("secret provider detail")
        ):
            response = self.client.post(
                "/api/tmdb/discover/advanced",
                json={"query": discover_query()},
            )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json(), {"error": "TMDB request failed"})


if __name__ == "__main__":
    unittest.main()
