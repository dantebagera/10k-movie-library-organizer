import json
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from services.iptv_provider_manager import IPTVProviderManager
from services.iptv_routes import register_iptv_routes
from services.iptv_xtream import XtreamError


CATALOG = {
    "live": {"categories": [{"category_id": "1", "category_name": "Live"}], "items": [{"stream_id": "7", "category_id": "1", "name": "Channel"}]},
    "movie": {"categories": [{"category_id": "1", "category_name": "Movies"}], "items": [{"stream_id": "7", "category_id": "1", "name": "Movie"}]},
    "series": {"categories": [{"category_id": "1", "category_name": "Series"}], "items": [{"series_id": "7", "category_id": "1", "name": "Series"}]},
}


class IPTVRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.manager = IPTVProviderManager(self.temporary.name, migrate_legacy=False)
        app = Flask(__name__)
        register_iptv_routes(app, lambda: self.manager)
        self.client = app.test_client()

    def tearDown(self):
        self.manager.close()
        self.temporary.cleanup()

    def create_provider(self, name="Provider A", username="user-a"):
        response = self.client.post("/api/iptv/providers", json={
            "name": name,
            "server_url": "https://provider.example",
            "username": username,
            "password": "fake-password",
            "allow_insecure_tls": True,
        })
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def test_provider_crud_is_redacted_and_old_singular_routes_are_absent(self):
        created = self.create_provider()
        provider_id = created["provider_id"]
        listed = self.client.get("/api/iptv/providers")
        updated = self.client.patch(f"/api/iptv/providers/{provider_id}", json={
            "name": "Renamed",
            "server_url": "https://provider.example",
            "username": "",
            "password": "",
            "allow_insecure_tls": True,
        })

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(updated.status_code, 200)
        payload = json.dumps([created, listed.get_json(), updated.get_json()])
        self.assertNotIn("fake-password", payload)
        self.assertNotIn("user-a", payload)
        self.assertNotIn('"password"', payload)
        self.assertNotIn('"username"', payload)
        self.assertEqual(updated.get_json()["name"], "Renamed")
        self.assertEqual(self.client.get("/api/iptv/status").status_code, 404)
        self.assertEqual(self.client.get("/api/iptv/config").status_code, 404)

    def test_provider_required_catalog_and_user_state_routes_are_isolated(self):
        first = self.create_provider()
        second = self.create_provider("Provider B", "user-b")
        first_id = first["provider_id"]
        second_id = second["provider_id"]
        self.manager.service(first_id).store.replace_catalog(CATALOG)
        second_catalog = {
            **CATALOG,
            "movie": {
                **CATALOG["movie"],
                "items": [{"stream_id": "7", "category_id": "1", "name": "Other Movie"}],
            },
        }
        self.manager.service(second_id).store.replace_catalog(second_catalog)

        self.client.post(f"/api/iptv/providers/{first_id}/favorites/movie/7", json={"favorite": True})
        self.client.post(f"/api/iptv/providers/{first_id}/history/movie/7", json={"position_seconds": 12})
        created_list = self.client.post(f"/api/iptv/providers/{first_id}/lists", json={"name": "Keep"}).get_json()
        self.client.post(f"/api/iptv/providers/{first_id}/lists/{created_list['list_id']}/items/movie/7")

        first_items = self.client.get(f"/api/iptv/providers/{first_id}/items?kind=movie").get_json()
        second_items = self.client.get(f"/api/iptv/providers/{second_id}/items?kind=movie").get_json()
        first_favorites = self.client.get(f"/api/iptv/providers/{first_id}/favorites").get_json()
        second_favorites = self.client.get(f"/api/iptv/providers/{second_id}/favorites").get_json()
        first_recent = self.client.get(f"/api/iptv/providers/{first_id}/recent").get_json()
        second_recent = self.client.get(f"/api/iptv/providers/{second_id}/recent").get_json()
        second_lists = self.client.get(f"/api/iptv/providers/{second_id}/lists").get_json()

        self.assertEqual(first_items["items"][0]["name"], "Movie")
        self.assertEqual(second_items["items"][0]["name"], "Other Movie")
        self.assertEqual(first_favorites["total"], 1)
        self.assertEqual(second_favorites["total"], 0)
        self.assertEqual(len(first_recent["items"]), 1)
        self.assertEqual(second_recent["items"], [])
        self.assertEqual(second_lists["items"], [])

    def test_unknown_provider_is_404_and_errors_redact_credentials(self):
        created = self.create_provider()
        provider_id = created["provider_id"]
        missing = self.client.get("/api/iptv/providers/not-a-provider/status")
        with patch.object(
            self.manager,
            "test_provider",
            side_effect=XtreamError("username=user-a&password=fake-password"),
        ):
            failed = self.client.post(f"/api/iptv/providers/{provider_id}/test")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(failed.status_code, 400)
        body = failed.get_data(as_text=True)
        self.assertNotIn("user-a", body)
        self.assertNotIn("fake-password", body)
        self.assertIn("[redacted]", body)

    def test_selection_and_removal_are_explicit_and_isolated(self):
        first = self.create_provider()
        second = self.create_provider("Provider B", "user-b")
        selected = self.client.post("/api/iptv/providers/selection", json={"provider_id": second["provider_id"]})
        wrong = self.client.delete(f"/api/iptv/providers/{first['provider_id']}", json={"confirm_name": "wrong"})
        removed = self.client.delete(f"/api/iptv/providers/{first['provider_id']}", json={"confirm_name": "Provider A"})

        self.assertEqual(selected.status_code, 200)
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(removed.status_code, 200)
        registry = self.client.get("/api/iptv/providers").get_json()
        self.assertEqual([row["provider_id"] for row in registry["providers"]], [second["provider_id"]])
        self.assertEqual(registry["last_selected_provider_id"], second["provider_id"])


if __name__ == "__main__":
    unittest.main()
