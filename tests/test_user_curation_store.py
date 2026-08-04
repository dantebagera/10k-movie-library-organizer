import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        import json
        return json.dumps(self.payload).encode("utf-8")


class UserCurationStoreTest(unittest.TestCase):
    def test_list_reads_reuse_store_json_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            store.list_all()

            with patch("builtins.open", side_effect=AssertionError("cached list read should not reopen JSON")):
                lists = store.list_all()

            self.assertEqual([item["id"] for item in lists[:2]], ["watched", "watchlist"])

    def test_app_curation_store_is_reused_per_user_data_dir(self):
        original_user_data_dir = app._user_data_dir
        original_cache = dict(app._curation_store_cache)
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            try:
                app._user_data_dir = first
                first_store = app._curation_store()
                self.assertIs(first_store, app._curation_store())

                app._user_data_dir = second
                second_store = app._curation_store()
                self.assertIsNot(first_store, second_store)
                self.assertIs(second_store, app._curation_store())
            finally:
                app._user_data_dir = original_user_data_dir
                app._curation_store_cache = original_cache

    def test_system_lists_are_created_and_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))

            lists = store.list_all()

            self.assertEqual([item["id"] for item in lists[:2]], ["watched", "watchlist"])
            self.assertEqual(lists[0]["system_type"], "watched")
            self.assertEqual(lists[1]["system_type"], "watchlist")
            with self.assertRaises(ValueError):
                store.rename_list("watched", "Seen")
            with self.assertRaises(ValueError):
                store.delete_list("watchlist")

    def test_repeated_list_reads_do_not_mutate_generation_for_sql_ordering(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            store.catalog.replace_document('user_lists.json', {'lists': [{
                'id': 'created-first',
                'name': 'Created First',
                'movies': [],
                'created_at': 1,
                'updated_at': 1,
            }]})

            first = store.list_all()
            generation = store.catalog.generation('curation')
            second = store.list_all()
            third = store.list_all()

            self.assertEqual([item['id'] for item in first], ['watched', 'watchlist', 'created-first'])
            self.assertEqual(second, first)
            self.assertEqual(third, first)
            self.assertEqual(store.catalog.generation('curation'), generation)

    def test_system_list_toggle_is_idempotent_and_states_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            movie = {"tmdb_id": "348", "title": "Alien", "year": "1979"}

            watched = store.set_system_list_state("watched", movie, True)
            watched_again = store.set_system_list_state("watched", movie, True)
            watchlisted = store.set_system_list_state("watchlist", movie, True)

            self.assertTrue(watched["active"])
            self.assertTrue(watched_again["active"])
            self.assertTrue(watchlisted["active"])
            self.assertEqual(len(next(item for item in store.list_all() if item["id"] == "watched")["movies"]), 1)
            self.assertTrue(store.system_states_for_movie(movie)["watched"])
            self.assertTrue(store.system_states_for_movie(movie)["watchlist"])
            store.set_system_list_state("watched", movie, False)
            states = store.system_states_for_movie(movie)
            self.assertFalse(states["watched"])
            self.assertTrue(states["watchlist"])

    def test_system_state_uses_shared_provider_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            store.set_system_list_state(
                "watched",
                {"tmdb_id": "348", "title": "Alien", "year": "1979", "path": "E:/Movies/Alien-a.mkv"},
                True,
            )

            states = store.system_states_for_movie({
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "path": "F:/Movies/Alien-b.mkv",
            })

            self.assertTrue(states["watched"])

    def test_system_state_falls_back_to_title_year_but_rejects_conflicting_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            store.set_system_list_state(
                "watched",
                {"tmdb_id": "348", "title": "Alien", "year": "1979"},
                True,
            )

            fallback = store.system_states_for_movie({"title": "Alien", "year": "1979"})
            conflict = store.system_states_for_movie({"tmdb_id": "999", "title": "Alien", "year": "1979"})

            self.assertTrue(fallback["watched"])
            self.assertFalse(conflict["watched"])

    def test_collection_override_supersedes_tmdb_and_reset_restores_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            tmdb_collection = {
                "id": "8091",
                "name": "Alien Collection",
                "parts": [
                    {"tmdb_id": "348", "title": "Alien", "year": "1979"},
                    {"tmdb_id": "679", "title": "Aliens", "year": "1986"},
                ],
            }
            romulus = {"tmdb_id": "945961", "title": "Alien: Romulus", "year": "2024"}

            edited = store.save_collection_override("8091", tmdb_collection, [tmdb_collection["parts"][0], romulus])

            self.assertEqual(edited["source"], "User")
            self.assertEqual([m["title"] for m in edited["parts"]], ["Alien", "Alien: Romulus"])
            self.assertTrue(store.reset_collection("8091"))
            restored = store.effective_collection(tmdb_collection)
            self.assertEqual(restored["source"], "TMDB")
            self.assertEqual([m["title"] for m in restored["parts"]], ["Alien", "Aliens"])

    def test_user_lists_store_movies_separately_from_collections(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            movie = {"tmdb_id": "348", "title": "Alien", "year": "1979", "path": "E:/Movies/Alien.mkv"}

            created = store.create_list("My Best")
            updated = store.add_movie_to_list(created["id"], movie)

            self.assertEqual(updated["name"], "My Best")
            self.assertEqual(updated["movies"][0]["title"], "Alien")
            self.assertEqual(store.lists_for_movie(movie)[0]["name"], "My Best")
            store.remove_movie_from_list(created["id"], movie)
            self.assertEqual(store.lists_for_movie(movie), [])

    def test_bulk_add_movies_to_list_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            created = store.create_list("Childhood")
            alien = {"tmdb_id": "348", "title": "Alien", "year": "1979", "path": "E:/Movies/Alien.mkv"}
            aliens = {"tmdb_id": "679", "title": "Aliens", "year": "1986", "path": "E:/Movies/Aliens.mkv"}

            updated = store.add_movies_to_list(created["id"], [alien, aliens, {**alien, "path": "F:/Copies/Alien.mkv"}])

            self.assertEqual([movie["title"] for movie in updated["movies"]], ["Alien", "Aliens"])

    def test_create_list_with_movies_persists_once_and_returns_actual_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            store.list_all()
            alien = {"tmdb_id": "348", "title": "Alien", "year": "1979"}
            aliens = {"tmdb_id": "679", "title": "Aliens", "year": "1986"}

            with patch.object(store, "_save_lists", wraps=store._save_lists) as save_lists:
                created = store.create_list(
                    "AI Sci-Fi",
                    movies=[alien, aliens, {**alien, "path": "E:/Copies/Alien.mkv"}],
                )

            self.assertEqual(save_lists.call_count, 1)
            self.assertEqual([movie["title"] for movie in created["movies"]], ["Alien", "Aliens"])
            persisted = next(item for item in store.list_all() if item["id"] == created["id"])
            self.assertEqual(persisted["movies"], created["movies"])

    def test_copy_export_job_copies_local_movies_and_skips_unsafe_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "library"
            destination = root / "usb"
            source.mkdir()
            destination.mkdir()
            alien = source / "Alien.mkv"
            aliens = source / "Aliens.mkv"
            alien.write_bytes(b"alien")
            aliens.write_bytes(b"aliens")
            (destination / "Aliens.mkv").write_bytes(b"already here")

            job = app._create_copy_export_job(
                [
                    {"title": "Alien", "year": "1979", "path": str(alien)},
                    {"title": "Aliens", "year": "1986", "path": str(aliens)},
                    {"title": "Remote only", "year": "1984", "tmdb_id": "1"},
                    {"title": "Missing", "year": "1999", "path": str(source / "Missing.mkv")},
                ],
                str(destination),
                start=False,
            )

            app._run_copy_export_job(job["id"])
            snapshot = app._copy_export_job_snapshot(job["id"])

            self.assertEqual(snapshot["status"], "completed")
            self.assertEqual(snapshot["copied_count"], 1)
            self.assertEqual(snapshot["skipped_count"], 3)
            self.assertEqual(snapshot["failed_count"], 0)
            self.assertEqual((destination / "Alien.mkv").read_bytes(), b"alien")
            self.assertEqual((destination / "Aliens.mkv").read_bytes(), b"already here")

    def test_user_lists_can_be_renamed_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            created = store.create_list("My Best")

            renamed = store.rename_list(created["id"], "Better Picks")
            self.assertEqual(renamed["name"], "Better Picks")
            self.assertTrue(store.delete_list(created["id"]))
            self.assertEqual([item["id"] for item in store.list_all()], ["watched", "watchlist"])

    def test_source_review_preview_uses_quality_and_trusted_indexer_defaults(self):
        previous_quality = getattr(app, "_download_default_quality", "1080p")
        previous_mode = getattr(app, "_download_indexer_mode", "release")
        previous_trusted = list(getattr(app, "_download_trusted_indexers", []))
        app._download_default_quality = "1080p"
        app._download_indexer_mode = "release"
        app._download_trusted_indexers = []
        movie = {"tmdb_id": "680", "title": "Pulp Fiction", "year": "1994"}

        try:
            with patch("app._curated_movie_is_owned", return_value=False), patch(
                "app._effective_download_trusted_indexer_ids", return_value=["7"]
            ), patch(
                "app._ai_control_source_search",
                return_value=[
                    {"title": "Pulp Fiction 1994 4K", "resolution": "4K", "indexer": "Trusted", "indexer_id": "7", "seeders": 50},
                    {"title": "Pulp Fiction 1994 1080p", "resolution": "1080p", "indexer": "Trusted", "indexer_id": "7", "seeders": 30},
                ],
            ):
                response = app.app.test_client().post(
                    "/api/sources/review/preview",
                    json={"movies": [movie]},
                )
        finally:
            app._download_default_quality = previous_quality
            app._download_indexer_mode = previous_mode
            app._download_trusted_indexers = previous_trusted

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["defaults"]["quality"], "1080p")
        self.assertEqual(data["rows"][0]["quality"], "1080p")
        self.assertEqual(data["rows"][0]["variant"]["resolution"], "1080p")
        self.assertEqual(data["rows"][0]["variants_by_quality"]["1080p"]["resolution"], "1080p")
        self.assertEqual(data["rows"][0]["variants_by_quality"]["4K"]["resolution"], "4K")
        self.assertFalse(data["rows"][0]["upgrade"])
        self.assertEqual(data["rows"][0]["status"], "ready")

    def test_source_review_never_places_lower_or_unknown_releases_in_the_1080p_bucket(self):
        movie = {"tmdb_id": "294254", "title": "Maze Runner: The Scorch Trials", "year": "2015"}
        variants = [
            {
                "title": "Maze Runner The Scorch Trials 2015 720p BRRip",
                "resolution": "720p",
                "indexer": "YTS",
                "indexer_id": "7",
                "seeders": 500,
            },
            {
                "title": "Maze Runner The Scorch Trials 2015",
                "resolution": "Unknown",
                "indexer": "YTS",
                "indexer_id": "7",
                "seeders": 900,
            },
            {
                "title": "Maze Runner The Scorch Trials 2015 1080p BluRay",
                "resolution": "1080p",
                "indexer": "YTS",
                "indexer_id": "7",
                "seeders": 5,
            },
            {
                "title": "Maze Runner The Scorch Trials 2015 2160p BluRay",
                "resolution": "4K",
                "indexer": "YTS",
                "indexer_id": "7",
                "seeders": 2,
            },
        ]

        with patch("app._curated_movie_is_owned", return_value=True), patch(
            "app._effective_download_trusted_indexer_ids",
            return_value=["7"],
        ), patch("app._ai_control_source_search", return_value=variants):
            response = app.app.test_client().post(
                "/api/sources/review/preview",
                json={"movies": [movie], "quality": "1080p"},
            )

        self.assertEqual(response.status_code, 200)
        row = response.get_json()["rows"][0]
        self.assertEqual(row["variant"]["resolution"], "1080p")
        self.assertIn("1080p", row["variant"]["title"])
        self.assertEqual(row["variants_by_quality"]["1080p"]["resolution"], "1080p")
        self.assertEqual(row["variants_by_quality"]["4K"]["resolution"], "4K")
        self.assertTrue(row["upgrade"])

    def test_source_review_blocks_1080p_when_yts_only_returns_720p(self):
        movie = {"tmdb_id": "294254", "title": "Maze Runner: The Scorch Trials", "year": "2015"}
        lower_quality = [{
            "title": "Maze Runner The Scorch Trials 2015 720p BRRip",
            "resolution": "720p",
            "indexer": "YTS",
            "indexer_id": "7",
            "seeders": 500,
        }]

        with patch("app._curated_movie_is_owned", return_value=True), patch(
            "app._effective_download_trusted_indexer_ids",
            return_value=["7"],
        ), patch("app._ai_control_source_search", return_value=lower_quality):
            response = app.app.test_client().post(
                "/api/sources/review/preview",
                json={"movies": [movie], "quality": "1080p"},
            )

        self.assertEqual(response.status_code, 200)
        row = response.get_json()["rows"][0]
        self.assertEqual(row["quality"], "1080p")
        self.assertEqual(row["status"], "blocked")
        self.assertFalse(row["selected"])
        self.assertIsNone(row["variant"])
        self.assertIsNone(row["variants_by_quality"]["1080p"])
        self.assertIsNone(row["variants_by_quality"]["4K"])
        self.assertEqual(row["reason"], "No trusted 1080p source found")

    def test_source_review_submit_only_downloads_selected_ready_rows(self):
        ready = {
            "selected": True,
            "status": "ready",
            "title": "Pulp Fiction",
            "year": "1994",
            "tmdb_id": "680",
            "variant": {"title": "Pulp Fiction 1080p", "resolution": "1080p", "magnet_url": "magnet:?xt=urn:btih:abc"},
        }
        skipped = {
            "selected": False,
            "status": "ready",
            "title": "Heat",
            "year": "1995",
            "variant": {"title": "Heat 1080p", "magnet_url": "magnet:?xt=urn:btih:def"},
        }

        with patch("app._curated_movie_is_owned", return_value=False), patch(
            "app._ai_control_submit_download", return_value={"hash": "abc", "name": "Pulp Fiction"}
        ) as submit:
            response = app.app.test_client().post(
                "/api/sources/review/submit",
                json={"rows": [ready, skipped]},
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["submitted_count"], 1)
        self.assertEqual(len(data["results"]), 1)
        submit.assert_called_once()

    def test_followed_releases_can_be_added_updated_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = app.UserCurationStore(Path(tmp))
            movie = {
                "tmdb_id": "945961",
                "title": "Alien: Romulus",
                "year": "2024",
                "release_date": "2024-08-13",
                "poster_url": "poster-a",
            }

            followed = store.follow_movie(movie)
            updated = store.follow_movie({**movie, "poster_url": "poster-b"})

            self.assertEqual(followed["status"], "watching")
            self.assertEqual(updated["poster_url"], "poster-b")
            self.assertEqual(updated["release_date"], "2024-08-13")
            self.assertEqual(len(store.followed_all()), 1)
            self.assertTrue(store.unfollow_movie(movie))
            self.assertEqual(store.followed_all(), [])

    def test_followed_release_check_backfills_missing_release_date(self):
        original_user_data_dir = app._user_data_dir
        with tempfile.TemporaryDirectory() as tmp:
            app._user_data_dir = tmp
            try:
                store = app._curation_store()
                store.follow_movie({
                    "tmdb_id": "1368337",
                    "title": "The Odyssey",
                    "year": "2026",
                    "poster_url": "poster-a",
                })

                with patch("app._find_owned_movies", return_value=[None]), \
                     patch("app._find_best_followed_release", return_value=None), \
                     patch("app._fetch_tmdb_metadata_by_id", return_value={"release_date": "2026-07-15"}):
                    checked = app._check_followed_releases()
            finally:
                app._user_data_dir = original_user_data_dir

        self.assertEqual(checked["movies"][0]["release_date"], "2026-07-15")
        self.assertEqual(checked["movies"][0]["status"], "watching")

    def test_followed_ownership_reconcile_removes_only_committed_library_movies(self):
        original_user_data_dir = app._user_data_dir
        with tempfile.TemporaryDirectory() as tmp:
            app._user_data_dir = tmp
            try:
                store = app._curation_store()
                store.follow_movie({"tmdb_id": "100", "title": "Downloaded", "year": "2026"})
                store.follow_movie({"tmdb_id": "200", "title": "Still Following", "year": "2026"})
                owned = {"found": True, "path": "E:/Movies/Downloaded.mkv", "resolution": "1080p"}
                with patch("app._find_owned_movies", return_value=[None, owned]):
                    reconciled = app._reconcile_followed_release_ownership()
            finally:
                app._user_data_dir = original_user_data_dir

        self.assertEqual([movie["title"] for movie in reconciled["movies"]], ["Still Following"])
        self.assertEqual([movie["title"] for movie in reconciled["removed_owned"]], ["Downloaded"])

    def test_followed_releases_get_backfills_missing_release_date_without_release_check(self):
        original_user_data_dir = app._user_data_dir
        with tempfile.TemporaryDirectory() as tmp:
            app._user_data_dir = tmp
            try:
                store = app._curation_store()
                store.follow_movie({
                    "tmdb_id": "1368337",
                    "title": "The Odyssey",
                    "year": "2026",
                    "poster_url": "poster-a",
                })

                with patch("app._fetch_tmdb_metadata_by_id", return_value={"release_date": "2026-07-15"}):
                    response = app.app.test_client().get("/api/user/followed-releases")
            finally:
                app._user_data_dir = original_user_data_dir

        self.assertEqual(response.status_code, 200)
        movie = response.get_json()["movies"][0]
        self.assertEqual(movie["release_date"], "2026-07-15")

    def test_curation_routes_expose_the_generation_that_their_mutations_advance(self):
        original_user_data_dir = app._user_data_dir
        with tempfile.TemporaryDirectory() as tmp:
            app._user_data_dir = tmp
            try:
                client = app.app.test_client()
                initial = client.get('/api/user/lists').get_json()
                created = client.post('/api/user/lists', json={'name': 'Generation Test'}).get_json()
                followed = client.post('/api/user/followed-releases', json={
                    'movie': {'tmdb_id': '42', 'title': 'Generation Movie', 'year': '2026'}
                }).get_json()
                collection = client.post('/api/user/collection', json={
                    'collection_id': '7001',
                    'original': {'id': '7001', 'name': 'Generation Collection'},
                    'parts': [],
                }).get_json()
            finally:
                app._user_data_dir = original_user_data_dir

        self.assertGreater(created['curation_generation'], initial['curation_generation'])
        self.assertGreater(followed['curation_generation'], created['curation_generation'])
        self.assertGreater(collection['curation_generation'], followed['curation_generation'])

    def test_repeated_user_list_gets_are_read_only(self):
        original_user_data_dir = app._user_data_dir
        original_cache = dict(app._curation_store_cache)
        with tempfile.TemporaryDirectory() as tmp:
            app._user_data_dir = tmp
            app._curation_store_cache = {}
            try:
                client = app.app.test_client()
                first = client.get('/api/user/lists').get_json()
                second = client.get('/api/user/lists').get_json()
                third = client.get('/api/user/lists').get_json()
            finally:
                app._user_data_dir = original_user_data_dir
                app._curation_store_cache = original_cache

        self.assertEqual([item['id'] for item in first['lists'][:2]], ['watched', 'watchlist'])
        self.assertEqual(second['lists'], first['lists'])
        self.assertEqual(third['lists'], first['lists'])
        self.assertEqual(second['curation_generation'], first['curation_generation'])
        self.assertEqual(third['curation_generation'], first['curation_generation'])

    def test_followed_release_quality_gate_rejects_camera_rips(self):
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p HDCAM"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p TELESYNC"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p TELE-SYNC WEBRip"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p TELE.SYNC BluRay"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p Tele Sync BDRip"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p TELESYNC265 WEBRip"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p TELESYNCx264 BluRay"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p TELE-SYNCHEVC BDRip"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 720p WEB-DL"))

    def test_followed_release_quality_gate_accepts_only_approved_sources(self):
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p WEB-DL"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p Remux"))
        self.assertIsNone(app._proper_release_from_title("New Movie 2026 1080p BDRemux"))
        self.assertEqual(app._proper_release_from_title("New Movie 2026 1080p WEBRip")["source"], "WEBRip")
        self.assertEqual(app._proper_release_from_title("New Movie 2026 1080p BluRay")["source"], "Blu-ray")
        self.assertEqual(app._proper_release_from_title("New Movie 2026 1080p BDRip")["source"], "BDRip")
        self.assertEqual(app._proper_release_from_title("New Movie 2026 1080p BRRip")["source"], "BDRip")

    def test_followed_release_requires_trusted_indexer_for_availability(self):
        original = (
            app._prowlarr_url,
            app._prowlarr_key,
            app._trusted_release_indexers,
            app._trusted_release_indexers_configured,
        )
        app._prowlarr_url = "http://prowlarr.test"
        app._prowlarr_key = "key"
        app._trusted_release_indexers = []
        app._trusted_release_indexers_configured = True

        def fake_urlopen(_request, timeout=0):
            return _FakeResponse([
                {"title": "Disclosure Day 2026 1080p WEBRip LAMA", "indexer": "YTS", "seeders": 50, "size": 1000}
            ])

        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                self.assertIsNone(app._find_best_followed_release({"title": "Disclosure Day", "year": "2026"}))
        finally:
            (
                app._prowlarr_url,
                app._prowlarr_key,
                app._trusted_release_indexers,
                app._trusted_release_indexers_configured,
            ) = original

    def test_prowlarr_config_defaults_trusted_release_indexer_to_yts(self):
        original = (
            app._prowlarr_url,
            app._prowlarr_key,
            app._trusted_release_indexers,
            app._trusted_release_indexers_configured,
        )
        app._prowlarr_url = "http://prowlarr.test"
        app._prowlarr_key = "key"
        app._trusted_release_indexers = []
        app._trusted_release_indexers_configured = False

        def fake_urlopen(request, timeout=0):
            self.assertTrue(request.full_url.endswith("/api/v1/indexer"))
            return _FakeResponse([
                {"id": 1, "name": "NoNaMe Club", "enable": True},
                {"id": 2, "name": "YTS", "enable": True},
            ])

        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                response = app.app.test_client().get("/api/prowlarr/config")
        finally:
            (
                app._prowlarr_url,
                app._prowlarr_key,
                app._trusted_release_indexers,
                app._trusted_release_indexers_configured,
            ) = original

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["trusted_release_indexers"], ["2"])

    def test_followed_release_uses_only_selected_trusted_indexers(self):
        original = (
            app._prowlarr_url,
            app._prowlarr_key,
            app._trusted_release_indexers,
            app._trusted_release_indexers_configured,
        )
        app._prowlarr_url = "http://prowlarr.test"
        app._prowlarr_key = "key"
        app._trusted_release_indexers = ["1"]
        app._trusted_release_indexers_configured = True

        def fake_urlopen(request, timeout=0):
            url = request.full_url
            if url.endswith("/api/v1/indexer"):
                return _FakeResponse([
                    {"id": 1, "name": "YTS", "enable": True},
                    {"id": 2, "name": "Fake Tracker", "enable": True},
                ])
            self.assertIn("indexerIds=1", url)
            self.assertNotIn("indexerIds=2", url)
            return _FakeResponse([
                {"title": "Disclosure Day 2026 2160p WEBRip FAKE", "indexer": "Fake Tracker", "seeders": 500, "size": 4000},
                {"title": "Disclosure Day 2026 1080p WEBRip YTS", "indexer": "YTS", "seeders": 5, "size": 1000},
            ])

        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                release = app._find_best_followed_release({"title": "Disclosure Day", "year": "2026"})
        finally:
            (
                app._prowlarr_url,
                app._prowlarr_key,
                app._trusted_release_indexers,
                app._trusted_release_indexers_configured,
            ) = original

        self.assertIsNotNone(release)
        self.assertEqual(release["indexer"], "YTS")


if __name__ == "__main__":
    unittest.main()
