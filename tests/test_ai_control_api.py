import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import app


class AiControlApiTest(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_config_endpoint_returns_experimental_policy_defaults(self):
        response = self.client.get("/api/ai-control/config")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["download_quality"], "1080p")
        self.assertEqual(data["delete_mode"], "recycle_bin")
        self.assertFalse(data["ollama_curated_lists"])
        self.assertNotIn("max_matched_movies", data)
        self.assertNotIn("max_download_searches", data)

    def test_config_defaults_ai_control_trusted_indexers_to_yts_when_unconfigured(self):
        previous_configured = app._ai_control_trusted_indexers_configured
        previous_config = dict(app._ai_control_config)
        app._ai_control_trusted_indexers_configured = False
        app._ai_control_config = app.ai_control.coerce_config({
            **previous_config,
            "trusted_indexers": [],
        })
        try:
            with patch("app._ai_control_available_indexers", return_value=[
                {"id": "1", "name": "YTS"},
                {"id": "2", "name": "1337x"},
            ]):
                response = self.client.get("/api/ai-control/config")
        finally:
            app._ai_control_trusted_indexers_configured = previous_configured
            app._ai_control_config = previous_config

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["trusted_indexers"], ["1"])
        self.assertFalse(data["trusted_indexers_configured"])

    def test_preview_delete_uses_ollama_intent_and_returns_review_plan(self):
        with tempfile.TemporaryDirectory() as root:
            movie = os.path.join(root, "Huge Movie.mkv")
            with open(movie, "wb") as handle:
                handle.write(b"x")

            with patch("app._ai_control_library_items", return_value=[
                {"path": movie, "title": "Huge Movie", "year": "2009", "size": 14 * 1024**3}
            ]), patch("app.get_movies_dirs", return_value=[root]), patch(
                "app._ollama_chat_content",
                return_value=json.dumps({"action": "delete", "filters": [{"field": "size_gb", "op": ">", "value": 10}]}),
            ):
                response = self.client.post("/api/ai-control/preview", json={"prompt": "delete files over 10 GB"})

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data["state"], "valid_plan")
            self.assertEqual(data["action"], "delete")
            self.assertTrue(data["plan_id"])
            self.assertEqual(data["items"][0]["title"], "Huge Movie")

    def test_execute_rejects_delete_plan_when_file_changed_after_preview(self):
        with tempfile.TemporaryDirectory() as root:
            movie = os.path.join(root, "Huge Movie.mkv")
            with open(movie, "wb") as handle:
                handle.write(b"x")

            with patch("app._ai_control_library_items", return_value=[
                {"path": movie, "title": "Huge Movie", "year": "2009", "size": 14 * 1024**3}
            ]), patch("app.get_movies_dirs", return_value=[root]), patch(
                "app._ollama_chat_content",
                return_value=json.dumps({"action": "delete", "filters": [{"field": "size_gb", "op": ">", "value": 10}]}),
            ):
                preview = self.client.post("/api/ai-control/preview", json={"prompt": "delete files over 10 GB"}).get_json()

            with open(movie, "ab") as handle:
                handle.write(b"changed")

            with patch("app.get_movies_dirs", return_value=[root]):
                response = self.client.post("/api/ai-control/execute", json={"plan_id": preview["plan_id"]})

            self.assertEqual(response.status_code, 409)
            data = response.get_json()
            self.assertEqual(data["state"], "unsafe")
            self.assertIn("changed", data["message"].lower())

    def test_execute_create_list_returns_receipt_and_rejects_replay(self):
        plan = app._ai_control_plan_store.put({
            "state": "valid_plan",
            "action": "create_list",
            "list_name": "AI Sci-Fi",
            "items": [{"tmdb_id": "348", "title": "Alien", "year": "1979"}],
        })
        created = {
            "id": "ai-sci-fi",
            "name": "AI Sci-Fi",
            "movies": plan["items"],
            "count": 1,
        }

        with patch("app._ai_control_create_list", return_value=created) as create_list:
            first = self.client.post("/api/ai-control/execute", json={"plan_id": plan["plan_id"]})
            second = self.client.post("/api/ai-control/execute", json={"plan_id": plan["plan_id"]})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["state"], "executed")
        self.assertEqual(first.get_json()["total_matches"], 1)
        self.assertEqual(second.status_code, 409)
        create_list.assert_called_once()

    def test_execute_create_list_applies_only_server_validated_selected_keys(self):
        plan = app._ai_control_plan_store.put({
            "state": "valid_plan",
            "action": "create_list",
            "list_name": "Custom Selection",
            "items": [
                {"selection_key": "item-1", "tmdb_id": "1", "title": "One"},
                {"selection_key": "item-2", "tmdb_id": "2", "title": "Two"},
                {"selection_key": "item-3", "tmdb_id": "3", "title": "Three"},
            ],
        })

        with patch("app._ai_control_create_list", return_value={
            "id": "custom-selection",
            "name": "Custom Selection",
            "count": 2,
            "movies": [],
        }) as create_list:
            response = self.client.post("/api/ai-control/execute", json={
                "plan_id": plan["plan_id"],
                "selected_keys": ["item-1", "item-3"],
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total_matches"], 2)
        selected_movies = create_list.call_args.args[1]
        self.assertEqual([movie["title"] for movie in selected_movies], ["One", "Three"])

    def test_preview_nonsense_prompt_returns_clarification(self):
        response = self.client.post("/api/ai-control/preview", json={"prompt": "clean my movies"})

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["state"], "needs_clarification")
        self.assertEqual(data["plan_id"], "")

    def test_ai_control_library_items_include_card_ready_plex_metadata(self):
        previous_cache = dict(app._library_cache)
        previous_plex_cache = dict(app._plex_cache)
        previous_user_data = app._user_data_dir
        with tempfile.TemporaryDirectory() as movies_root, tempfile.TemporaryDirectory() as data_root:
            path = str(Path(movies_root) / "Mission Impossible 1996.1080p.mkv")
            Path(path).write_bytes(b"movie")
            plex_record = {
                "plex_title": "Mission: Impossible",
                "plex_year": "1996",
                "plex_genres": ["Action", "Thriller"],
                "plex_summary": "Ethan Hunt races to expose a mole.",
                "plex_rating": "7.0",
                "plex_language": "English",
                "plex_country": "United States",
                "plex_country_flag": "US",
                "plex_directors": [{"name": "Brian De Palma"}],
                "plex_cast": [{"name": "Tom Cruise", "character": "Ethan Hunt"}],
                "tmdb_id": "954",
                "imdb_id": "tt0117060",
                "plex_guid": "plex://movie/1",
                "plex_poster": "/api/plex/image?path=poster",
            }
            app._library_cache = {}
            app._plex_cache = {app._norm(path): plex_record}
            app._user_data_dir = data_root
            store = app.AppMetadataStore(Path(data_root))
            store.apply_plex_match(path, plex_record, facts={
                "path": path,
                "filename": os.path.basename(path),
                "library_root": movies_root,
                "size": Path(path).stat().st_size,
                "modified_time": Path(path).stat().st_mtime,
                "resolution": "1080p",
                "quality_class": "1080p",
                "quality_source": "filename_fallback",
                "filename_quality_claim": "1080p",
                "rip_source": "Unknown",
            })
            try:
                item = app._ai_control_library_items()[0]
            finally:
                app._library_cache = previous_cache
                app._plex_cache = previous_plex_cache
                app._user_data_dir = previous_user_data

        self.assertEqual(item["title"], "Mission: Impossible")
        self.assertEqual(item["year"], "1996")
        self.assertEqual(item["genres"], ["Action", "Thriller"])
        self.assertEqual(item["plot"], "Ethan Hunt races to expose a mole.")
        self.assertEqual(item["tmdb_rating"], "7.0")
        self.assertEqual(item["language"], "English")
        self.assertEqual(item["country_flag"], "US")
        self.assertEqual(item["directors"], [{"name": "Brian De Palma"}])
        self.assertEqual(item["cast"], [{"name": "Tom Cruise", "character": "Ethan Hunt"}])
        self.assertEqual(item["poster_url"], "/api/plex/image?path=poster")
        self.assertEqual(item["resolution"], app.get_resolution(os.path.basename(path)))
        self.assertTrue(item["size_human"])

    def test_person_credit_filter_keeps_released_feature_roles_only(self):
        previous_genres = dict(app._tmdb_genres)
        app._tmdb_genres = {
            16: "Animation",
            35: "Comedy",
            99: "Documentary",
        }
        try:
            rows = app._ai_control_filter_person_credit_rows([
                {
                    "id": 1,
                    "title": "Sonic the Hedgehog 4",
                    "release_date": "2027-03-19",
                    "genre_ids": [16],
                    "character": "Dr. Robotnik",
                    "popularity": 100,
                },
                {
                    "id": 2,
                    "title": "The Many Faces of Jim Carrey",
                    "release_date": "2023-01-01",
                    "genre_ids": [99],
                    "character": "Self",
                    "popularity": 90,
                },
                {
                    "id": 3,
                    "title": "Behind the Scenes of Kidding",
                    "release_date": "2018-01-01",
                    "genre_ids": [99],
                    "character": "Self",
                    "popularity": 80,
                },
                {
                    "id": 4,
                    "title": "Liar Liar",
                    "release_date": "1997-03-21",
                    "genre_ids": [35],
                    "character": "Fletcher Reede",
                    "popularity": 30,
                },
                {
                    "id": 5,
                    "title": "Sonic the Hedgehog",
                    "release_date": "2020-02-12",
                    "genre_ids": [16, 35],
                    "character": "Dr. Robotnik",
                    "popularity": 50,
                },
            ], "actor")
        finally:
            app._tmdb_genres = previous_genres

        self.assertEqual([row["title"] for row in rows], ["Sonic the Hedgehog", "Liar Liar"])

    def test_tmdb_discover_uses_genre_year_range_and_top_rated_sort(self):
        previous_key = app._tmdb_key
        previous_genres = dict(app._tmdb_genres)
        captured_urls = []

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "results": [
                        {
                            "id": 78,
                            "title": "Blade Runner",
                            "release_date": "1982-06-25",
                            "poster_path": "/blade.jpg",
                        }
                    ]
                }).encode()

        def fake_urlopen(req, timeout=10):
            captured_urls.append(req.full_url)
            return FakeResponse()

        app._tmdb_key = "test-key"
        app._tmdb_genres = {878: "Science Fiction"}
        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                result = app._ai_control_tmdb_discover({
                    "filters": [
                        {"field": "genre", "op": "equals", "value": "Science Fiction"},
                        {"field": "year", "op": "between", "value": ["1980", "1989"]},
                    ],
                    "sort": "top_rated",
                }, app.ai_control.default_config())
        finally:
            app._tmdb_key = previous_key
            app._tmdb_genres = previous_genres

        self.assertEqual(result[0]["title"], "Blade Runner")
        self.assertIn("with_genres=878", captured_urls[0])
        self.assertIn("primary_release_date.gte=1980-01-01", captured_urls[0])
        self.assertIn("primary_release_date.lte=1989-12-31", captured_urls[0])
        self.assertIn("sort_by=vote_average.desc", captured_urls[0])
        self.assertIn("vote_count.gte=500", captured_urls[0])

    def test_tmdb_search_reaches_every_provider_page_and_deduplicates_identity(self):
        previous_key = app._tmdb_key
        captured_pages = []

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        def fake_urlopen(req, timeout=10):
            page = int(req.full_url.split("page=", 1)[1].split("&", 1)[0])
            captured_pages.append(page)
            rows = {
                1: [
                    {"id": 1, "title": "One", "release_date": "2001-01-01"},
                    {"id": 2, "title": "Two", "release_date": "2002-01-01"},
                ],
                2: [
                    {"id": 2, "title": "Two", "release_date": "2002-01-01"},
                    {"id": 3, "title": "Three", "release_date": "2003-01-01"},
                ],
            }
            return FakeResponse({"page": page, "total_pages": 2, "results": rows[page]})

        app._tmdb_key = "test-key"
        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                result = app._ai_control_tmdb_search("complete", app.ai_control.default_config())
        finally:
            app._tmdb_key = previous_key

        self.assertEqual(captured_pages, [1, 2])
        self.assertEqual([movie["tmdb_id"] for movie in result], ["1", "2", "3"])

    def test_tmdb_search_fetches_remaining_pages_concurrently_and_preserves_page_order(self):
        previous_key = app._tmdb_key
        lock = threading.Lock()
        active = 0
        max_active = 0
        captured_pages = []

        def fake_fetch(page_url):
            nonlocal active, max_active
            page = int(page_url.split("page=", 1)[1].split("&", 1)[0])
            with lock:
                captured_pages.append(page)
                active += 1
                max_active = max(max_active, active)
            if page > 1:
                time.sleep(0.02)
            with lock:
                active -= 1
            return {
                "page": page,
                "total_pages": 4,
                "results": [{"id": page, "title": f"Movie {page}", "release_date": f"200{page}-01-01"}],
            }

        app._tmdb_key = "test-key"
        try:
            with patch("app._tmdb_fetch_provider_page", side_effect=fake_fetch):
                result = app._ai_control_tmdb_search("complete", app.ai_control.default_config())
        finally:
            app._tmdb_key = previous_key

        self.assertEqual(sorted(captured_pages), [1, 2, 3, 4])
        self.assertGreater(max_active, 1)
        self.assertEqual([movie["tmdb_id"] for movie in result], ["1", "2", "3", "4"])

    def test_batch_owned_movie_lookup_reuses_one_snapshot_and_catalog_query(self):
        snapshot = Mock(return_value={"files": {}})
        ownership_candidates = Mock(return_value=[{"path": "E:\\Movies\\Owned.mkv"}])
        owned_path_candidates = Mock(return_value=[])
        store = SimpleNamespace(
            snapshot=snapshot,
            catalog=SimpleNamespace(store=SimpleNamespace(
                ownership_candidates=ownership_candidates,
                owned_path_candidates=owned_path_candidates,
            )),
        )
        movies = [
            {"tmdb_id": "1", "title": "Owned", "year": "2001"},
            {"tmdb_id": "2", "title": "Missing", "year": "2002"},
        ]

        def fake_owned_movie(movie, **kwargs):
            if movie["tmdb_id"] != "1":
                return None
            return {
                "item": {
                    "path": "E:\\Movies\\Owned.mkv",
                    "filename": "Owned.mkv",
                    "resolution": "1080p",
                    "size_human": "2.0 GB",
                }
            }

        with patch("app._iter_movie_roots", return_value=iter(["E:\\Movies"])), \
                patch("app._metadata_store", return_value=store), \
                patch("app._catalog_owned_entries", return_value=[{"item": {}}]), \
                patch("app._catalog_owned_movie", side_effect=fake_owned_movie) as owned_movie:
            result = app._find_owned_movies(movies)

        snapshot.assert_called_once_with()
        ownership_candidates.assert_called_once()
        owned_path_candidates.assert_called_once_with([])
        self.assertEqual(owned_movie.call_count, 2)
        self.assertEqual(result[0]["path"], "E:\\Movies\\Owned.mkv")
        self.assertIsNone(result[1])

    def test_ai_control_source_review_prepares_every_requested_movie_without_total_cap(self):
        movies = [
            {"selection_key": f"item-{index}", "tmdb_id": str(index), "title": f"Movie {index}"}
            for index in range(1, 13)
        ]

        def prepared_row(movie, quality, trusted_ids):
            return {
                **movie,
                "quality": quality,
                "status": "ready",
                "selected": True,
                "variant": {"title": f"{movie['title']} 1080p"},
                "variants_by_quality": {},
                "upgrade": False,
                "reason": "",
            }

        with patch("app._effective_ai_control_config", return_value={
            **app.ai_control.default_config(),
            "trusted_indexers": ["1"],
        }), patch("app._source_review_movie_row", side_effect=prepared_row) as prepare:
            response = self.client.post("/api/sources/review/preview", json={
                "movies": movies,
                "policy": "ai_control",
            })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["rows"]), 12)
        self.assertEqual([row["selection_key"] for row in data["rows"]], [
            f"item-{index}" for index in range(1, 13)
        ])
        self.assertEqual(prepare.call_count, 12)
        self.assertEqual(data["defaults"]["policy"], "ai_control")


if __name__ == "__main__":
    unittest.main()
