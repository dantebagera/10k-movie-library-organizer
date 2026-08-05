import unittest
from unittest.mock import patch

import app


class ReactRouteTest(unittest.TestCase):
    def test_react_sections_serve_built_index(self):
        client = app.app.test_client()

        responses = [client.get(path) for path in ("/discover", "/ai-control", "/downloads", "/help", "/card-lab")]

        for response in responses:
            self.assertEqual(response.status_code, 200)
            self.assertIn(b'<div id="root">', response.data)
            self.assertIn(b'class="app-bootstrap"', response.data)

    def test_qbittorrent_webui_has_a_separate_proxy_route(self):
        class FakeManager:
            paths = []

            def ensure_running(self):
                return True

            def proxy(self, path, method="GET", headers=None, body=None):
                self.paths.append(path)
                return 200, {"Content-Type": "text/html"}, b"<html><title>qBittorrent WebUI</title></html>"

        client = app.app.test_client()
        manager = FakeManager()
        with patch.object(app, "_get_qbittorrent_manager", return_value=manager):
            response = client.get("/qbittorrent/")
            nested = client.get("/qbittorrent/api/v2/sync/maindata?rid=0")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"qBittorrent WebUI", response.data)
        self.assertNotIn(b"cp-qbt-sidebar", response.data)
        self.assertEqual(nested.status_code, 200)
        self.assertIn("api/v2/sync/maindata", manager.paths)

    def test_root_does_not_fall_back_to_legacy_template_when_frontend_missing(self):
        client = app.app.test_client()

        with patch.object(app.os.path, "exists", return_value=False):
            response = client.get("/")

        self.assertEqual(response.status_code, 503)
        self.assertIn(b"React frontend has not been built", response.data)

    def test_legacy_route_is_not_public(self):
        client = app.app.test_client()

        response = client.get("/legacy")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
