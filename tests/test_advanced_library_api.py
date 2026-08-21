import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import app
from services.catalog_repository import CatalogRepository


def library_query(groups=None):
    return {
        "version": 1,
        "scope": "library",
        "mode": "advanced",
        "groups": groups or [],
        "sort": {"key": "added", "direction": "desc"},
    }


class AdvancedLibraryApiTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_transport_delegates_normalized_query_to_catalog_owner(self):
        catalog = Mock()
        catalog.library_page.return_value = {
            "candidates": [], "total": 0, "page": 1, "page_size": 40,
            "total_pages": 1, "page_start": 0, "page_end": 0,
            "facets": {"genres": [], "sources": [], "languages": [], "countries": []},
            "stats": {"total": 0, "low": 0, "matched": 0, "pending": 0, "unmatched": 0},
        }
        catalog.generation.return_value = 7
        store = Mock(catalog=catalog)
        query = library_query([{
            "type": "genre", "join": "or",
            "values": [{"id": "18", "label": "Drama"}],
        }])
        with patch.object(app, "_metadata_store", return_value=store), patch.object(
            app, "_maintenance_upgrade_path_keys", return_value=set()
        ):
            response = self.client.post(
                "/api/library/search/advanced",
                json={"query": query, "page": 1, "page_size": 40},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["catalog_generation"], 7)
        delegated = catalog.library_page.call_args.kwargs
        self.assertEqual(delegated["query"]["groups"][0]["type"], "genre")
        self.assertEqual(delegated["page_size"], 40)

    def test_selection_consumes_the_same_normalized_query(self):
        repository = Mock()
        repository.library_selection_paths.return_value = ["E:/Movies/Alien.mkv"]
        repository.generation.return_value = 9
        query = library_query([{
            "type": "runtime", "values": [{"preset": "feature"}],
        }])
        with patch.object(app, "_catalog_repository", return_value=repository), patch.object(
            app, "_maintenance_upgrade_path_keys", return_value=set()
        ):
            response = self.client.post("/api/library/selection", json={"query": query})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["paths"], ["E:/Movies/Alien.mkv"])
        self.assertEqual(
            repository.library_selection_paths.call_args.kwargs["query"]["groups"][0]["type"],
            "runtime",
        )

    def test_invalid_roles_unknown_fields_and_page_bounds_return_400(self):
        producer = library_query([{
            "type": "person", "join": "or",
            "values": [{"id": "1", "label": "Producer", "role": "producer"}],
        }])
        responses = [
            self.client.post("/api/library/search/advanced", json={"query": producer}),
            self.client.post("/api/library/search/advanced", json={"query": library_query(), "raw_sql": "x"}),
            self.client.post("/api/library/search/advanced", json={"query": library_query(), "page_size": 101}),
            self.client.post("/api/library/search/advanced", json={"query": library_query(), "page": "wrong"}),
            self.client.post("/api/library/search/advanced", json={"query": library_query(), "page_size": "wrong"}),
        ]
        self.assertEqual([response.status_code for response in responses], [400, 400, 400, 400, 400])

    def test_person_identity_lookup_is_bounded_and_controlled(self):
        catalog = Mock()
        catalog.library_people_identities.return_value = {
            "items": [{"id": "31", "label": "Tom Hanks", "roles": ["actor"]}],
            "count": 1,
            "catalog_generation": 4,
        }
        store = Mock(catalog=catalog)
        with patch.object(app, "_metadata_store", return_value=store):
            response = self.client.get("/api/library/search/identities?type=person&q=tom&limit=20")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["items"], [{"id": "31", "label": "Tom Hanks", "roles": ["actor"]}])
        catalog.library_people_identities.assert_called_once_with("tom", limit=20)

    def test_runtime_repository_adapter_forwards_to_catalog_query_owner(self):
        with tempfile.TemporaryDirectory() as root:
            repository = CatalogRepository(
                root,
                database_path=Path(root) / "catalog.sqlite",
                export_delay=0,
            )
            try:
                store = Mock(catalog=repository)
                with patch.object(app, "_metadata_store", return_value=store), patch.object(
                    app, "_maintenance_upgrade_path_keys", return_value=set()
                ):
                    response = self.client.post(
                        "/api/library/search/advanced",
                        json={"query": library_query(), "page": 1, "page_size": 40},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["total"], 0)
            finally:
                repository.close()


if __name__ == "__main__":
    unittest.main()
