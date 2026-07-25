import json
import unittest
from unittest.mock import patch

import app


class FakeOllamaResponse:
    def __init__(self, recommendations=None):
        self.recommendations = recommendations or [
            {"title": f"Movie {index}", "year": "2000", "reason": "Matches the prompt."}
            for index in range(10)
        ]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps({
            "message": {
                "content": json.dumps({
                    "recommendations": self.recommendations
                })
            }
        }).encode()


class FakeJsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class OllamaRecommendTest(unittest.TestCase):
    def test_config_exposes_and_saves_candidate_limit(self):
        original_url = app._ollama_url
        original_model = app._ollama_model
        original_limit = app._ollama_candidate_limit
        app._ollama_url = "http://ollama.test"
        app._ollama_model = "local-model"
        app._ollama_candidate_limit = app.OLLAMA_CANDIDATE_LIMIT_DEFAULT
        client = app.app.test_client()

        try:
            response = client.get("/api/ollama/config")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["candidate_limit"], 15)

            with patch("app._save_config"):
                response = client.post(
                    "/api/ollama/config",
                    json={"url": "http://new-ollama.test/", "model": "new-model", "candidate_limit": 7}
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(app._ollama_url, "http://new-ollama.test")
            self.assertEqual(app._ollama_model, "new-model")
            self.assertEqual(app._ollama_candidate_limit, 7)
        finally:
            app._ollama_url = original_url
            app._ollama_model = original_model
            app._ollama_candidate_limit = original_limit

    def test_config_rejects_invalid_candidate_limit(self):
        original_limit = app._ollama_candidate_limit
        app._ollama_candidate_limit = app.OLLAMA_CANDIDATE_LIMIT_DEFAULT
        try:
            response = app.app.test_client().post(
                "/api/ollama/config",
                json={"url": "http://ollama.test", "model": "local-model", "candidate_limit": 51}
            )
        finally:
            app._ollama_candidate_limit = original_limit

        self.assertEqual(response.status_code, 400)
        self.assertIn("candidate_limit", response.get_json()["error"])

    def test_config_preserves_candidate_limit_when_omitted(self):
        original_url = app._ollama_url
        original_model = app._ollama_model
        original_limit = app._ollama_candidate_limit
        app._ollama_url = "http://ollama.test"
        app._ollama_model = "local-model"
        app._ollama_candidate_limit = 6

        try:
            with patch("app._save_config"):
                response = app.app.test_client().post(
                    "/api/ollama/config",
                    json={"url": "http://new-ollama.test", "model": "new-model"}
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(app._ollama_candidate_limit, 6)
        finally:
            app._ollama_url = original_url
            app._ollama_model = original_model
            app._ollama_candidate_limit = original_limit

    def test_model_choices_include_only_free_cloud_recommendations_and_local_models(self):
        original_model = app._ollama_model
        app._ollama_model = "gemma4:31b-cloud"

        def fake_urlopen(request, timeout=0):
            if request.full_url.endswith("/api/tags"):
                return FakeJsonResponse({
                    "models": [
                        {"model": "gemma3:12b", "details": {"parameter_size": "12B"}},
                        {"name": "gemma3:12b", "details": {"parameter_size": "12B"}},
                        {"model": "pulled-cloud:cloud"},
                        {"model": "gemma4:31b-cloud"},
                    ]
                })
            if request.full_url.endswith("/api/experimental/model-recommendations"):
                return FakeJsonResponse({
                    "recommendations": [
                        {"model": "minimax-m3:cloud", "required_plan": "free", "description": "Free model"},
                        {"model": "gemma4:31b-cloud", "required_plan": "free", "description": "Free Gemma model"},
                        {"model": "glm-5.2:cloud", "required_plan": "pro", "description": "Paid model"},
                        {"model": "qwen3.6", "description": "Local recommendation"},
                    ]
                })
            raise AssertionError(request.full_url)

        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                response = app.app.test_client().get("/api/ollama/models?url=http://ollama.test")
        finally:
            app._ollama_model = original_model

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["configured_model"], "gemma4:31b-cloud")
        self.assertEqual(
            [item["model"] for item in data["free_cloud_models"]],
            ["gemma4:31b-cloud", "minimax-m3:cloud"],
        )
        self.assertEqual([item["model"] for item in data["local_models"]], ["gemma3:12b"])
        self.assertEqual(data["warnings"], [])
        self.assertTrue(data["reachable"])

    def test_model_choices_preserve_partial_results_when_cloud_discovery_fails(self):
        def fake_urlopen(request, timeout=0):
            if request.full_url.endswith("/api/tags"):
                return FakeJsonResponse({"models": [{"model": "gemma3:4b"}]})
            raise OSError("experimental endpoint unavailable")

        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
            response = app.app.test_client().get("/api/ollama/models?url=http://ollama.test")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([item["model"] for item in data["local_models"]], ["gemma3:4b"])
        self.assertEqual(data["free_cloud_models"], [])
        self.assertIn("Free cloud model list unavailable", data["warnings"][0])
        self.assertTrue(data["reachable"])

    def test_model_test_generates_and_validates_json_with_selected_model(self):
        captured = {}

        def fake_urlopen(request, timeout=0):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode())
            return FakeJsonResponse({"message": {"content": json.dumps({"ok": True})}})

        with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
            response = app.app.test_client().get(
                "/api/ollama/test?url=http://ollama.test&model=minimax-m3:cloud"
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["model"], "minimax-m3:cloud")
        self.assertEqual(captured["url"], "http://ollama.test/api/chat")
        self.assertEqual(captured["body"]["model"], "minimax-m3:cloud")
        self.assertEqual(captured["body"]["format"], "json")

    def test_model_test_rejects_a_response_that_breaks_the_json_contract(self):
        with patch(
            "app.urllib.request.urlopen",
            return_value=FakeJsonResponse({"message": {"content": "not json"}}),
        ):
            response = app.app.test_client().get(
                "/api/ollama/test?url=http://ollama.test&model=unreliable-model"
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("did not return the required JSON", response.get_json()["error"])

    def test_model_test_accepts_one_complete_json_markdown_fence(self):
        with patch(
            "app.urllib.request.urlopen",
            return_value=FakeJsonResponse({"message": {"content": "```json\n{\"ok\":true}\n```"}}),
        ):
            response = app.app.test_client().get(
                "/api/ollama/test?url=http://ollama.test&model=gemma4:31b-cloud"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["model"], "gemma4:31b-cloud")

    def test_prompt_uses_candidate_limit_and_caps_deduped_results(self):
        captured = {}
        original_url = app._ollama_url
        original_model = app._ollama_model
        original_limit = app._ollama_candidate_limit
        original_tmdb_key = app._tmdb_key
        app._ollama_url = "http://ollama.test"
        app._ollama_model = "local-model"
        app._ollama_candidate_limit = 3
        app._tmdb_key = ""

        recommendations = [
            {"title": "Carrie", "year": "1976", "reason": "King adaptation."},
            {"title": "carrie", "year": "1976", "reason": "Duplicate casing."},
            {"title": "The Shining", "year": "1980", "reason": "Haunted hotel."},
            {"title": "Misery", "year": "1990", "reason": "Psychological thriller."},
            {"title": "The Mist", "year": "2007", "reason": "Creature horror."},
        ]

        def fake_urlopen(request, timeout=0):
            captured["body"] = json.loads(request.data.decode())
            return FakeOllamaResponse(recommendations)

        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen), \
                 patch("app._ollama_enrich_with_tmdb", return_value=None):
                response = app.app.test_client().post(
                    "/api/ollama/recommend",
                    json={"prompt": "warm crime movie"}
                )
        finally:
            app._ollama_url = original_url
            app._ollama_model = original_model
            app._ollama_candidate_limit = original_limit
            app._tmdb_key = original_tmdb_key

        self.assertEqual(response.status_code, 200)
        system_message = captured["body"]["messages"][0]["content"]
        self.assertIn("Return at most 3 feature-length movie candidates.", system_message)
        self.assertIn("Exclude TV series, miniseries, episodes, books, games, and unreleased films.", system_message)
        self.assertNotIn("Give exactly 10 recommendations.", system_message)
        results = response.get_json()["results"]
        self.assertEqual([item["title"] for item in results], ["Carrie", "The Shining", "Misery"])


if __name__ == "__main__":
    unittest.main()
