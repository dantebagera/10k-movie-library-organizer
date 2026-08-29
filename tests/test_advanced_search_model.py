import unittest

from services.advanced_search import (
    AdvancedSearchValidationError,
    MAX_PAGE_SIZE,
    MAX_TOTAL_VALUES,
    normalize_query,
    query_signature,
)


def empty_query(scope="library"):
    query = {
        "version": 1,
        "scope": scope,
        "mode": "advanced",
        "groups": [],
        "sort": {"key": "added" if scope == "library" else "auto", "direction": "desc"},
    }
    if scope == "discover":
        query["feed"] = "trending_week"
    return query


class AdvancedSearchModelTest(unittest.TestCase):
    def test_normalizes_reordering_and_exact_duplicates(self):
        query = empty_query()
        query["groups"] = [
            {"type": "year", "values": [{"operator": "between", "from": 2000, "to": 2020}]},
            {
                "type": "genre",
                "join": "or",
                "values": [
                    {"id": "53", "label": "Thriller"},
                    {"id": "18", "label": "Drama"},
                    {"id": "53", "label": "Thriller"},
                ],
            },
        ]
        normalized = normalize_query(query)
        reordered = dict(normalized)
        reordered["groups"] = list(reversed(normalized["groups"]))
        self.assertEqual(query_signature(normalized), query_signature(reordered))
        self.assertEqual(len(normalized["groups"][0]["values"]), 2)

    def test_same_person_different_roles_remains_distinct(self):
        query = empty_query()
        query["groups"] = [{
            "type": "person",
            "join": "and",
            "values": [
                {"id": "500", "label": "Example", "role": "actor"},
                {"id": "500", "label": "Example", "role": "director"},
            ],
        }]
        values = normalize_query(query)["groups"][0]["values"]
        self.assertEqual([value["role"] for value in values], ["actor", "director"])

    def test_genre_exclusion_is_individual_strict_and_part_of_execution_identity(self):
        query = empty_query("discover")
        query["groups"] = [{
            "type": "genre",
            "join": "and",
            "values": [
                {"id": "27", "label": "Horror"},
                {"id": "878", "label": "Sci-Fi"},
                {"id": "16", "label": "Animation", "exclude": True},
                {"id": "35", "label": "Comedy", "exclude": True},
            ],
        }]
        normalized = normalize_query(query)
        values = normalized["groups"][0]["values"]
        self.assertEqual({value["id"] for value in values if not value.get("exclude")}, {"27", "878"})
        self.assertEqual({value["id"] for value in values if value.get("exclude")}, {"16", "35"})

        without_not = empty_query("discover")
        without_not["groups"] = [{
            "type": "genre", "join": "and",
            "values": [{"id": "27", "label": "Horror"}, {"id": "878", "label": "Sci-Fi"}],
        }]
        self.assertNotEqual(query_signature(query), query_signature(without_not))

        malformed = empty_query("discover")
        malformed["groups"] = [{
            "type": "genre", "join": "or",
            "values": [{"id": "35", "label": "Comedy", "exclude": "yes"}],
        }]
        with self.assertRaisesRegex(AdvancedSearchValidationError, "true or false"):
            normalize_query(malformed)

        contradictory = empty_query("discover")
        contradictory["groups"] = [{
            "type": "genre", "join": "or",
            "values": [
                {"id": "35", "label": "Comedy"},
                {"id": "35", "label": "Comedy", "exclude": True},
            ],
        }]
        with self.assertRaisesRegex(AdvancedSearchValidationError, "both included and excluded"):
            normalize_query(contradictory)

    def test_library_rejects_vote_count_and_producer(self):
        query = empty_query()
        query["groups"] = [{"type": "minimum_votes", "values": [{"value": 1}]}]
        with self.assertRaisesRegex(AdvancedSearchValidationError, "not supported"):
            normalize_query(query)
        query["groups"] = [{
            "type": "person", "join": "or",
            "values": [{"id": "1", "label": "Producer", "role": "producer"}],
        }]
        with self.assertRaisesRegex(AdvancedSearchValidationError, "actor, director, or writer"):
            normalize_query(query)

    def test_rejects_unknown_fields_ranges_and_limits(self):
        query = empty_query()
        query["sql"] = "DROP TABLE movies"
        with self.assertRaisesRegex(AdvancedSearchValidationError, "Unknown"):
            normalize_query(query)
        query = empty_query()
        query["groups"] = [{"type": "year", "values": [{"operator": "between", "from": 2020, "to": 2000}]}]
        with self.assertRaisesRegex(AdvancedSearchValidationError, "reversed"):
            normalize_query(query)
        query = empty_query("discover")
        query["groups"] = [
            {"type": "genre", "join": "or", "values": [{"id": str(index), "label": f"Genre {index}"}]}
            for index in range(MAX_TOTAL_VALUES + 1)
        ]
        with self.assertRaises(AdvancedSearchValidationError):
            normalize_query(query)

    def test_runtime_boundaries_and_missing_fact_contract_shape(self):
        query = empty_query()
        query["groups"] = [{"type": "runtime", "values": [{"preset": "custom", "from": 60, "to": 149}]}]
        self.assertEqual(normalize_query(query)["groups"][0]["values"][0]["to"], 149)

    def test_execution_signature_ignores_editor_mode_and_display_labels(self):
        advanced = empty_query()
        advanced["groups"] = [{
            "type": "genre", "join": "or",
            "values": [{"id": "18", "label": "Drama"}],
        }]
        simple = {
            **advanced,
            "mode": "simple",
            "groups": [{
                "type": "genre", "join": "or",
                "values": [{"id": "18", "label": "Localized Drama Label"}],
            }],
        }
        self.assertEqual(query_signature(advanced), query_signature(simple))

    def test_shared_logical_page_limit_is_100(self):
        self.assertEqual(MAX_PAGE_SIZE, 100)


if __name__ == "__main__":
    unittest.main()
