import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.iptv_routes import _iter_upstream_chunks
from services.iptv_service import IPTVService
from services.iptv_store import IPTVStore
from services.iptv_xtream import XtreamClient, XtreamError, normalize_server_url


class XtreamClientTests(unittest.TestCase):
    def test_normalizes_server_and_builds_encoded_stream_url(self):
        client = XtreamClient("https://provider.example:2096/", "user name", "p/a ss")

        self.assertEqual(normalize_server_url("https://provider.example:2096/"), "https://provider.example:2096")
        self.assertEqual(
            client.stream_url("live", "42"),
            "https://provider.example:2096/live/user%20name/p%2Fa%20ss/42.ts",
        )

    def test_rejects_non_http_server_urls(self):
        with self.assertRaises(ValueError):
            normalize_server_url("javascript:alert(1)")

    def test_array_actions_reject_non_array_payloads(self):
        client = XtreamClient("https://provider.example", "user", "secret")
        with patch.object(client, "_request_json", return_value={"error": "bad"}):
            with self.assertRaises(XtreamError):
                client.live_streams()


class IPTVUpstreamRelayTests(unittest.TestCase):
    def test_relay_uses_available_short_reads_and_closes_upstream(self):
        upstream = MagicMock()
        upstream.read1.side_effect = [b"first", b"second", b""]

        chunks = list(_iter_upstream_chunks(upstream))

        self.assertEqual(chunks, [b"first", b"second"])
        upstream.read1.assert_called_with(64 * 1024)
        upstream.read.assert_not_called()
        upstream.close.assert_called_once_with()

    def test_relay_falls_back_to_read_when_short_reads_are_unavailable(self):
        class ReadOnlyUpstream:
            def __init__(self):
                self.responses = [b"chunk", b""]
                self.sizes = []
                self.closed = False

            def read(self, size):
                self.sizes.append(size)
                return self.responses.pop(0)

            def close(self):
                self.closed = True

        upstream = ReadOnlyUpstream()

        self.assertEqual(list(_iter_upstream_chunks(upstream)), [b"chunk"])
        self.assertEqual(upstream.sizes, [64 * 1024, 64 * 1024])
        self.assertTrue(upstream.closed)


class IPTVStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = IPTVStore(Path(self.temporary.name) / "iptv.sqlite")
        self.catalog = {
            "live": {
                "categories": [
                    {"category_id": "arabic", "category_name": "القنوات العربية"},
                    {"category_id": "actors", "category_name": "Actor Channels"},
                ],
                "items": [
                    {"stream_id": "11", "name": "القاهرة الإخبارية", "category_id": "arabic", "num": 7, "stream_icon": "https://images.example/11.png"},
                    {"stream_id": "12", "name": "Brad Pitt Movies", "category_id": "actors", "num": 18},
                ],
            },
            "movie": {
                "categories": [{"category_id": "new", "category_name": "New Releases"}],
                "items": [
                    {"stream_id": "21", "name": "The Test Movie ( 2026 )", "category_id": "new", "container_extension": "mkv", "rating": "7.5"},
                ],
            },
            "series": {
                "categories": [{"category_id": "drama", "category_name": "Drama"}],
                "items": [{"series_id": "31", "name": "مسلسل الاختبار", "category_id": "drama", "cover": "https://images.example/31.jpg"}],
            },
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_catalog_preserves_provider_order_counts_and_unicode_search(self):
        counts = self.store.replace_catalog(self.catalog)

        self.assertEqual(counts, {"live": 2, "movie": 1, "series": 1})
        self.assertEqual([row["category_id"] for row in self.store.categories("live")], ["arabic", "actors"])
        result = self.store.list_items("live", query="القاهرة")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["item_id"], "11")
        self.assertEqual(result["items"][0]["channel_num"], 7)
        self.assertEqual(self.store.get_item("movie", "21")["year"], "2026")

    def test_sync_preserves_valid_favorites_and_history(self):
        self.store.replace_catalog(self.catalog)
        self.store.set_favorite("movie", "21", True)
        self.store.update_history("movie", "21", 95, 600, False)

        self.store.replace_catalog(self.catalog)

        movie = self.store.get_item("movie", "21")
        self.assertTrue(movie["favorite"])
        recent = self.store.recent()
        self.assertEqual(recent[0]["position_seconds"], 95)
        self.assertTrue(recent[0]["favorite"])

    def test_favorites_can_be_listed_across_media_types_or_filtered(self):
        self.store.replace_catalog(self.catalog)
        self.store.set_favorite("live", "11", True)
        self.store.set_favorite("movie", "21", True)

        combined = self.store.list_favorites()
        movies = self.store.list_favorites(kind="movie")

        self.assertEqual(combined["total"], 2)
        self.assertEqual({item["kind"] for item in combined["items"]}, {"live", "movie"})
        self.assertTrue(all(item["favorite"] for item in combined["items"]))
        self.assertEqual([item["item_id"] for item in movies["items"]], ["21"])

    def test_custom_lists_are_mixed_ordered_and_provider_scoped(self):
        self.store.replace_catalog(self.catalog)
        created = self.store.create_list("provider-a", "Weekend")
        self.store.add_list_item("provider-a", created["list_id"], "movie", "21")
        self.store.add_list_item("provider-a", created["list_id"], "live", "11")

        self.store.move_list_item("provider-a", created["list_id"], "live", "11", -1)
        entries = self.store.list_entries("provider-a", created["list_id"])

        self.assertEqual([item["item_id"] for item in entries["items"]], ["11", "21"])
        self.assertEqual(self.store.lists("provider-a")[0]["item_count"], 2)
        self.assertEqual(self.store.lists("provider-b"), [])

    def test_list_snapshot_survives_provider_catalog_removal(self):
        self.store.replace_catalog(self.catalog)
        created = self.store.create_list("provider-a", "Keep this")
        self.store.add_list_item("provider-a", created["list_id"], "movie", "21")
        without_movie = {**self.catalog, "movie": {"categories": [], "items": []}}

        self.store.replace_catalog(without_movie)
        missing = self.store.list_entries("provider-a", created["list_id"])["items"][0]

        self.assertFalse(missing["available"])
        self.assertEqual(missing["name"], "The Test Movie ( 2026 )")
        self.store.replace_catalog(self.catalog)
        self.assertTrue(self.store.list_entries("provider-a", created["list_id"])["items"][0]["available"])

    def test_legacy_favorites_are_migrated_into_system_list(self):
        database_path = Path(self.temporary.name) / "legacy.sqlite"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute("CREATE TABLE favorites(kind TEXT, item_id TEXT, created_at REAL, PRIMARY KEY(kind, item_id))")
            connection.execute("INSERT INTO favorites VALUES ('movie', '21', 123.0)")
            connection.commit()
        finally:
            connection.close()
        store = IPTVStore(database_path)
        store.replace_catalog(self.catalog)

        favorites = store.list_favorites(provider_key="provider-a")
        connection = sqlite3.connect(database_path)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()

        self.assertEqual([item["item_id"] for item in favorites["items"]], ["21"])
        self.assertNotIn("favorites", tables)
        self.assertNotIn("legacy_favorites", tables)

    def test_detail_cache_round_trip_keeps_arabic_text(self):
        payload = {"info": {"plot": "حبكة عربية"}}
        self.store.cache_detail("series", "31", payload)
        self.assertEqual(self.store.get_cached_detail("series", "31"), payload)


class IPTVServiceConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = IPTVService(self.temporary.name, "test-provider")

    def tearDown(self):
        self.temporary.cleanup()

    def test_credentials_are_saved_but_redacted_from_public_config(self):
        public = self.service.save_config("https://provider.example:2096", "sample-user", "sample-password")

        self.assertTrue(public["configured"])
        self.assertNotIn("password", public)
        self.assertNotIn("username", public)
        self.assertNotIn("sample-user", json.dumps(public))
        self.assertFalse(public["allow_insecure_tls"])
        saved = json.loads(self.service.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["username"], "sample-user")
        self.assertEqual(saved["password"], "sample-password")

    def test_insecure_tls_is_explicit_and_provider_scoped(self):
        public = self.service.save_config("https://provider.example", "sample-user", "sample-password", allow_insecure_tls=True)

        self.assertTrue(public["allow_insecure_tls"])
        self.assertFalse(self.service.client().verify_tls)

    def test_playback_session_keeps_its_provider_tls_choice_after_config_edit(self):
        self.service.save_config("https://provider.example", "sample-user", "sample-password", allow_insecure_tls=True)
        self.service._sessions["token"] = {
            "source_url": "https://provider.example/live",
            "allow_insecure_tls": True,
        }
        self.service.save_config("https://provider.example", "", "", allow_insecure_tls=False)
        response = MagicMock()
        try:
            with patch("services.iptv_service.urllib.request.urlopen", return_value=response) as urlopen:
                self.assertIs(self.service.open_upstream("token"), response)
            self.assertIsNotNone(urlopen.call_args.kwargs["context"])
        finally:
            self.service._sessions.pop("token", None)

    def test_blank_secret_fields_preserve_saved_credentials(self):
        self.service.save_config("https://provider.example", "sample-user", "sample-password")
        self.service.save_config("https://other.example", "", "")

        saved = json.loads(self.service.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["server_url"], "https://other.example")
        self.assertEqual(saved["username"], "sample-user")
        self.assertEqual(saved["password"], "sample-password")

    def test_provider_key_changes_with_xtream_account_without_exposing_credentials(self):
        self.service.save_config("https://provider.example", "first-user", "sample-password")
        first = self.service.provider_key()
        self.service.save_config("https://provider.example", "second-user", "sample-password")

        self.assertNotEqual(first, self.service.provider_key())
        self.assertNotIn("first-user", first)

    def test_sync_errors_and_status_never_expose_credentials(self):
        self.service.save_config("https://provider.example", "sample-user", "sample-password")
        with patch.object(
            self.service,
            "client",
            side_effect=XtreamError("username=sample-user&password=sample-password"),
        ):
            self.service._sync_worker()

        payload = json.dumps(self.service.status())
        self.assertNotIn("sample-user", payload)
        self.assertNotIn("sample-password", payload)
        self.assertIn("[redacted]", payload)

    def test_running_sync_cannot_be_started_twice(self):
        self.service.save_config("https://provider.example", "sample-user", "sample-password")
        with patch("services.iptv_service.threading.Thread") as thread_class:
            self.assertTrue(self.service.start_sync())
            self.assertFalse(self.service.start_sync())
        thread_class.return_value.start.assert_called_once_with()

    def test_image_proxy_rejects_provider_supplied_private_network_url(self):
        self.service.save_config("https://provider.example", "sample-user", "sample-password")
        self.service.store.replace_catalog({
            "live": {"categories": [], "items": []},
            "movie": {"categories": [], "items": [{"stream_id": "9", "name": "Unsafe", "stream_icon": "http://127.0.0.1/private"}]},
            "series": {"categories": [], "items": []},
        })

        with self.assertRaisesRegex(ValueError, "private network"):
            self.service.cached_image("movie", "9")

    def test_startup_only_removes_old_orphaned_playback_directories(self):
        recent = self.service.playback_root / "recent-session"
        stale = self.service.playback_root / "stale-session"
        recent.mkdir()
        stale.mkdir()
        old = time.time() - self.service.ORPHANED_PLAYBACK_MAX_AGE - 60
        os.utime(stale, (old, old))

        replacement = IPTVService(self.temporary.name, "test-provider")
        try:
            self.assertTrue(recent.is_dir())
            self.assertFalse(stale.exists())
        finally:
            replacement.close()

    def test_stop_waits_for_killed_ffmpeg_before_removing_session_directory(self):
        token = "test-session"
        session_dir = self.service.playback_root / token
        session_dir.mkdir()
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("ffmpeg", 2), 0]
        self.service._sessions[token] = {
            "token": token,
            "directory": session_dir,
            "process": process,
            "created_at": time.time(),
            "stopping": False,
        }

        self.assertTrue(self.service.stop_playback(token))

        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 2)
        self.assertFalse(session_dir.exists())
        self.assertNotIn(token, self.service._sessions)

    def test_slow_ffmpeg_kill_defers_directory_removal_until_process_exits(self):
        token = "slow-stop-session"
        session_dir = self.service.playback_root / token
        session_dir.mkdir()
        process = MagicMock()
        process.poll.return_value = None
        process.wait.side_effect = [
            subprocess.TimeoutExpired("ffmpeg", 2),
            subprocess.TimeoutExpired("ffmpeg", 5),
            0,
        ]
        session = {
            "token": token,
            "directory": session_dir,
            "process": process,
            "created_at": time.time(),
            "stopping": False,
        }
        self.service._sessions[token] = session

        with patch("services.iptv_service.threading.Thread") as thread_class:
            self.assertTrue(self.service.stop_playback(token))
            self.assertTrue(session_dir.exists())
            self.assertIn(token, self.service._sessions)
            thread_class.return_value.start.assert_called_once_with()
            worker = thread_class.call_args.kwargs["target"]
            worker_args = thread_class.call_args.kwargs["args"]
            worker(*worker_args)

        self.assertFalse(session_dir.exists())
        self.assertNotIn(token, self.service._sessions)

    def test_live_hls_command_can_catch_up_and_uses_a_rolling_playlist(self):
        self.service.ffmpeg_path = "ffmpeg.exe"
        session_dir = self.service.playback_root / "command-session"
        manifest = session_dir / "index.m3u8"

        command = self.service._hls_command("http://127.0.0.1/upstream", session_dir, manifest, True)

        self.assertNotIn("-re", command)
        self.assertEqual(command[command.index("-hls_list_size") + 1], "16")
        self.assertEqual(command[command.index("-hls_delete_threshold") + 1], "4")
        flags = command[command.index("-hls_flags") + 1]
        self.assertIn("delete_segments", flags)
        self.assertIn("split_by_time", flags)
        self.assertNotIn("append_list", flags)


class IPTVAppDataBindingTests(unittest.TestCase):
    def test_app_data_change_rebinds_iptv_routes_without_restart(self):
        import app

        original_user_data = app._user_data_dir
        original_cache_dir = app._tmdb_cache_dir
        original_manager = app._iptv_provider_manager
        original_tmdb_cache_dir = app._TMDB_CACHE_DIR
        original_library_cache_file = app._TMDB_LIBRARY_CACHE_FILE
        original_collection_cache_file = app._TMDB_COLLECTION_CACHE_FILE
        original_library_cache = app._tmdb_library_cache
        original_collection_cache = app._tmdb_collection_cache
        with tempfile.TemporaryDirectory() as user_tmp, tempfile.TemporaryDirectory() as cache_tmp:
            try:
                with patch.object(app, "_save_config", return_value=None):
                    changed = app.app.test_client().post("/api/app-data/config", json={
                        "user_data_dir": user_tmp,
                        "tmdb_cache_dir": cache_tmp,
                    })
                bound_root = Path(app._iptv_provider_manager.root)
                public = app.app.test_client().get("/api/iptv/providers").get_json()
            finally:
                app._iptv_provider_manager.close()
                app._user_data_dir = original_user_data
                app._tmdb_cache_dir = original_cache_dir
                app._TMDB_CACHE_DIR = original_tmdb_cache_dir
                app._TMDB_LIBRARY_CACHE_FILE = original_library_cache_file
                app._TMDB_COLLECTION_CACHE_FILE = original_collection_cache_file
                app._tmdb_library_cache = original_library_cache
                app._tmdb_collection_cache = original_collection_cache
                app._iptv_provider_manager = original_manager

        self.assertEqual(changed.status_code, 200)
        self.assertEqual(bound_root, Path(user_tmp) / "iptv")
        self.assertEqual(public["providers"], [])


if __name__ == "__main__":
    unittest.main()
