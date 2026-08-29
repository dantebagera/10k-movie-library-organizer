import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.qbittorrent import (
    BUNDLED_QBT_VERSION,
    QBittorrentClient,
    QBittorrentError,
    QBittorrentJobStore,
    QBittorrentManager,
    TorrentIdentityMismatch,
    bundled_runtime_root,
    build_downloads_html,
    is_allowed_prowlarr_url,
    is_path_within,
    normalize_architecture,
    process_launch_kwargs,
    select_release_asset,
    validate_torrent_manifest,
    validate_magnet_url,
)


def movie_manifest(name="Movie.2026.mkv", size=1024 * 1024 * 1024, extras=None, info_hash=""):
    files = [{"path": name, "length": size}, *(extras or [])]
    manifest = {"info": {"name": "Movie 2026", "length": sum(item["length"] for item in files), "files": files}}
    if info_hash:
        manifest["hash"] = info_hash
    return [manifest]


class QBittorrentPlatformTests(unittest.TestCase):
    def test_magnet_metadata_handoff_stops_before_payload_download_and_can_resume(self):
        client = QBittorrentClient("http://127.0.0.1:8686")
        client.request = MagicMock()

        client.add_magnet("magnet:?xt=urn:btih:abc", "C:/staging", stop_after_metadata=True)
        client.resume("abc")

        self.assertEqual(client.request.call_args_list[0].args, (
            "/api/v2/torrents/add",
            {
                "urls": "magnet:?xt=urn:btih:abc",
                "savepath": "C:/staging",
                "tags": "cinema-paradiso",
                "paused": "false",
                "root_folder": "true",
                "stopCondition": "MetadataReceived",
            },
        ))
        self.assertEqual(client.request.call_args_list[1].args, ("/api/v2/torrents/start", {"hashes": "abc"}))

    def test_normalizes_supported_architectures(self):
        self.assertEqual(normalize_architecture("AMD64"), "x86_64")
        self.assertEqual(normalize_architecture("x86_64"), "x86_64")
        self.assertEqual(normalize_architecture("arm64"), "arm64")

    def test_selects_official_assets_by_platform(self):
        assets = [
            {"name": "qbittorrent_5.2.2_x64_setup.exe", "browser_download_url": "win"},
            {"name": "qbittorrent-5.2.2.dmg", "browser_download_url": "mac"},
            {"name": "qbittorrent-5.2.2_x86_64.AppImage", "browser_download_url": "linux"},
        ]
        self.assertEqual(select_release_asset(assets, "windows", "x86_64")["browser_download_url"], "win")
        self.assertEqual(select_release_asset(assets, "darwin", "x86_64")["browser_download_url"], "mac")
        self.assertEqual(select_release_asset(assets, "linux", "x86_64")["browser_download_url"], "linux")
        self.assertIsNone(select_release_asset(assets, "linux", "arm64"))

    def test_status_remains_available_when_github_is_offline(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            manager._github_release = lambda _url: (_ for _ in ()).throw(OSError("offline"))

            status = manager.status()

            self.assertFalse(status["installed"])
            self.assertIn("supported", status)

    @unittest.skipUnless(os.name == "nt", "Windows bundled runtime path")
    def test_manager_detects_bundled_runtime_when_runtime_state_is_missing(self):
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            bundled = bundled_runtime_root(root_path) / "qbittorrent.exe"
            bundled.parent.mkdir(parents=True)
            bundled.touch()
            manager = QBittorrentManager(root_path / "data", {}, [], app_root=root_path)
            manager.client.version = MagicMock(side_effect=OSError("offline test runtime"))

            self.assertEqual(manager.active_executable(), bundled)
            self.assertEqual(manager.status()["version"], BUNDLED_QBT_VERSION)

    def test_status_does_not_query_github_until_the_user_requests_an_update(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            manager._github_release = lambda _url: (_ for _ in ()).throw(AssertionError("network update check should not run"))

            status = manager.status()

            self.assertFalse(status["update_available"])
            self.assertEqual(status["update_policy"], "manual_github")

    def test_update_latest_returns_without_replacing_an_already_current_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            executable = Path(root) / "qbittorrent.exe"
            executable.touch()
            manager._save_runtime_state({"version": "5.2.3", "executable": str(executable)})
            manager.client.version = MagicMock(return_value="v5.2.3")
            manager.latest_release = MagicMock(return_value={
                "version": "5.2.3",
                "asset": {"name": "qbittorrent_5.2.3_x64_setup.exe"},
            })
            manager._download_verified = MagicMock()

            result = manager.update_latest()

            self.assertEqual(result["update_result"], "current")
            self.assertEqual(result["version"], "5.2.3")
            manager._download_verified.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows portable runtime update")
    def test_update_latest_switches_to_the_extracted_portable_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            previous = Path(root) / "previous" / "qbittorrent.exe"
            previous.parent.mkdir()
            previous.touch()
            manager._save_runtime_state({"version": "5.2.2", "executable": str(previous)})
            manager.latest_release = MagicMock(return_value={
                "version": "5.2.3",
                "asset": {"name": "qbittorrent_5.2.3_x64_setup.exe"},
            })

            def download(_asset, destination):
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_bytes(b"package")

            def extract(_package, destination):
                executable = Path(destination) / "qbittorrent.exe"
                executable.write_bytes(b"updated")
                return executable

            manager._download_verified = MagicMock(side_effect=download)
            manager._windows_extract = MagicMock(side_effect=extract)
            manager._stop_running = MagicMock()
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.version = MagicMock(side_effect=["v5.2.2", "v5.2.3", "v5.2.3"])

            result = manager.update_latest()

            state = manager._runtime_state()
            self.assertEqual(result["update_result"], "updated")
            self.assertEqual(result["version"], "5.2.3")
            self.assertEqual(state["version"], "5.2.3")
            self.assertTrue(Path(state["executable"]).is_file())
            self.assertEqual(state["previous"]["version"], "5.2.2")

    @unittest.skipUnless(os.name == "nt", "Windows portable runtime update")
    def test_update_latest_restores_the_previous_runtime_when_restart_fails(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            previous = Path(root) / "previous" / "qbittorrent.exe"
            previous.parent.mkdir()
            previous.touch()
            previous_state = {"version": "5.2.2", "executable": str(previous)}
            manager._save_runtime_state(previous_state)
            manager.latest_release = MagicMock(return_value={
                "version": "5.2.3",
                "asset": {"name": "qbittorrent_5.2.3_x64_setup.exe"},
            })

            def download(_asset, destination):
                Path(destination).parent.mkdir(parents=True, exist_ok=True)
                Path(destination).write_bytes(b"package")

            def extract(_package, destination):
                executable = Path(destination) / "qbittorrent.exe"
                executable.write_bytes(b"updated")
                return executable

            manager._download_verified = MagicMock(side_effect=download)
            manager._windows_extract = MagicMock(side_effect=extract)
            manager._stop_running = MagicMock()
            manager.ensure_running = MagicMock(side_effect=[False, True])
            manager.client.version = MagicMock(return_value="v5.2.2")

            with self.assertRaisesRegex(QBittorrentError, "previous runtime was restored"):
                manager.update_latest()

            self.assertEqual(manager._runtime_state(), previous_state)
            self.assertEqual(manager.ensure_running.call_count, 2)

    @unittest.skipUnless(os.name == "nt", "Windows-specific process startup behavior")
    def test_windows_launch_hides_native_qbittorrent_window(self):
        import subprocess

        kwargs = process_launch_kwargs("nt")

        self.assertEqual(kwargs["startupinfo"].wShowWindow, subprocess.SW_HIDE)
        self.assertTrue(kwargs["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertTrue(kwargs["creationflags"] & subprocess.DETACHED_PROCESS)

    @unittest.skipUnless(os.name == "nt", "Windows-specific process window behavior")
    def test_manager_hides_qbittorrent_window_after_webui_is_ready(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            executable = Path(root) / "qbittorrent.exe"
            executable.touch()
            manager._save_runtime_state({"version": "test", "executable": str(executable)})
            manager.client.version = MagicMock(side_effect=[OSError("stopped"), "v5.2.2"])
            process = MagicMock(pid=1234)

            with (
                patch.object(manager, "_write_profile"),
                patch("services.qbittorrent.subprocess.Popen", return_value=process),
                patch("services.qbittorrent.hide_process_windows") as hide,
                patch("services.qbittorrent.time.sleep"),
            ):
                self.assertTrue(manager.ensure_running())

            hide.assert_called_once_with(1234)


class QBittorrentSafetyTests(unittest.TestCase):
    def test_shutdown_never_targets_a_system_managed_client(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {"mode": "system"}, [])
            manager._stop_running = MagicMock()

            with self.assertRaisesRegex(QBittorrentError, "system-managed"):
                manager.shutdown()

            manager._stop_running.assert_not_called()

    def test_validates_only_btih_or_btmh_magnets(self):
        self.assertTrue(validate_magnet_url("magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"))
        self.assertTrue(validate_magnet_url("magnet:?xt=urn:btmh:1220" + ("a" * 64)))
        self.assertFalse(validate_magnet_url("https://example.test/file.torrent"))
        self.assertFalse(validate_magnet_url("magnet:?dn=missing-hash"))

    def test_constrains_torrent_fetch_to_configured_prowlarr_origin(self):
        self.assertTrue(is_allowed_prowlarr_url(
            "http://127.0.0.1:9696/download?id=5",
            "http://127.0.0.1:9696",
        ))
        self.assertFalse(is_allowed_prowlarr_url(
            "http://127.0.0.1:9697/download?id=5",
            "http://127.0.0.1:9696",
        ))
        self.assertFalse(is_allowed_prowlarr_url(
            "http://127.0.0.1:9696.evil.test/download",
            "http://127.0.0.1:9696",
        ))

    def test_path_containment_uses_real_path_boundaries(self):
        with tempfile.TemporaryDirectory() as root:
            child = Path(root) / "child"
            sibling = Path(f"{root}-other")
            self.assertTrue(is_path_within(child, root))
            self.assertFalse(is_path_within(sibling, root))

    def test_manifest_accepts_a_movie_with_small_supporting_files(self):
        result = validate_torrent_manifest(movie_manifest(
            size=1_000_000_000,
            extras=[{"path": "Movie.2026.srt", "length": 100_000}],
        ), expected_size=1_000_100_000)

        self.assertEqual(result["video_size"], 1_000_000_000)
        self.assertEqual(result["file_count"], 2)

    def test_manifest_allows_a_harmless_support_file_with_a_dangerous_intermediate_suffix(self):
        result = validate_torrent_manifest(movie_manifest(
            size=1_000_000_000,
            extras=[{"path": "YTSProxies.com.txt", "length": 100_000}],
        ), expected_size=1_000_100_000)

        self.assertEqual(result["video_size"], 1_000_000_000)
        self.assertEqual(result["file_count"], 2)

    def test_manifest_rejects_executable_payload_before_submission(self):
        with self.assertRaisesRegex(QBittorrentError, "unsafe torrent payload"):
            validate_torrent_manifest([{"info": {
                "name": "random",
                "files": [{"path": "0088F5556.exe", "length": 877_597_184}],
            }}])

    def test_manifest_rejects_a_substituted_hash_before_inspecting_its_payload(self):
        expected_hash = "a" * 40
        with self.assertRaisesRegex(TorrentIdentityMismatch, "does not match the selected release"):
            validate_torrent_manifest([{
                "hash": "b" * 40,
                "info": {
                    "name": "random",
                    "files": [{"path": "0088F5556.exe", "length": 877_597_184}],
                },
            }], expected_hash=expected_hash)

    def test_manifest_accepts_matching_release_identity_and_safe_movie_payload(self):
        info_hash = "d4b719ed66754116dc6c656303172ba96abfcae1"
        result = validate_torrent_manifest(movie_manifest(info_hash=info_hash), expected_hash=info_hash.upper())

        self.assertEqual(result["info_hash"], info_hash)

    def test_manifest_rejects_materially_substituted_size(self):
        with self.assertRaisesRegex(QBittorrentError, "does not match the advertised size"):
            validate_torrent_manifest(movie_manifest(size=877_597_184), expected_size=1_717_986_918)

    def test_manifest_rejects_paths_that_escape_the_torrent_root(self):
        with self.assertRaisesRegex(QBittorrentError, "unsafe file path"):
            validate_torrent_manifest(movie_manifest(name="../Movie.2026.mkv"))


class QBittorrentJobStoreTests(unittest.TestCase):
    def test_persists_jobs_atomically(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "jobs.json"
            store = QBittorrentJobStore(path)
            store.upsert("ABC", {"title": "Movie", "state": "downloading"})

            reopened = QBittorrentJobStore(path)
            self.assertEqual(reopened.get("abc")["title"], "Movie")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["jobs"]["abc"]["state"], "downloading")

    def test_import_moves_payload_unchanged_and_marks_job(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            source = staging / "Movie.2026.1080p-GROUP"
            source.mkdir(parents=True)
            (source / "Movie.2026.1080p-GROUP.mkv").write_bytes(b"movie")
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "title": "Movie",
                "state": "completed",
                "payload_paths": [str(source)],
                "destination": str(destination),
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            moved = destination / source.name
            self.assertEqual(result["state"], "payload_imported")
            self.assertTrue((moved / "Movie.2026.1080p-GROUP.mkv").exists())
            self.assertFalse(source.exists())

    def test_import_resumes_after_one_payload_was_already_moved(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            first = staging / "Movie.CD1"
            second = staging / "Movie.CD2"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "part1.mkv").write_bytes(b"one")
            (second / "part2.mkv").write_bytes(b"two")
            destination.mkdir()
            os.replace(first, destination / first.name)
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "state": "moving",
                "payload_paths": [str(first), str(second)],
                "destination": str(destination),
                "transfer_plan": [{
                    "source": str(first),
                    "target": str(destination / first.name),
                    "action": "move",
                    "status": "started",
                }],
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            self.assertEqual(result["state"], "payload_imported")
            self.assertTrue((destination / first.name / "part1.mkv").exists())
            self.assertTrue((destination / second.name / "part2.mkv").exists())

    def test_import_does_not_assume_an_unjournaled_existing_target_was_moved(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            missing = staging / "Movie.2026.1080p-GROUP"
            target = destination / missing.name
            target.mkdir(parents=True)
            (target / "movie.mkv").write_bytes(b"existing movie")
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "state": "finalizing",
                "payload_paths": [str(missing)],
                "destination": str(destination),
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            self.assertEqual(result["state"], "destination_conflict")
            self.assertIn("no CP transfer journal", result["collision"][0]["reason"])
            self.assertTrue(target.exists())

    def test_import_deduplicates_only_when_existing_payload_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            source = staging / "Movie.2026.1080p-GROUP"
            target = destination / source.name
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "movie.mkv").write_bytes(b"same movie")
            (target / "movie.mkv").write_bytes(b"same movie")
            (target / "movie.nfo").write_bytes(b"library metadata")
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "state": "finalizing",
                "payload_paths": [str(source)],
                "destination": str(destination),
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            self.assertEqual(result["state"], "payload_imported")
            self.assertTrue(result["already_in_library"])
            self.assertFalse(source.exists())
            self.assertEqual((target / "movie.mkv").read_bytes(), b"same movie")
            self.assertEqual((target / "movie.nfo").read_bytes(), b"library metadata")

    def test_import_preserves_both_payloads_when_existing_content_differs(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            source = staging / "Movie.2026.1080p-GROUP"
            target = destination / source.name
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "movie.mkv").write_bytes(b"new movie")
            (target / "movie.mkv").write_bytes(b"different movie")
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "state": "finalizing",
                "payload_paths": [str(source)],
                "destination": str(destination),
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            self.assertEqual(result["state"], "destination_conflict")
            self.assertTrue(source.exists())
            self.assertTrue(target.exists())
            self.assertEqual((source / "movie.mkv").read_bytes(), b"new movie")
            self.assertEqual((target / "movie.mkv").read_bytes(), b"different movie")

    def test_upgrade_import_uses_numbered_sibling_when_existing_content_differs(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            source = staging / "Movie.2026.1080p-GROUP"
            target = destination / source.name
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "movie.mkv").write_bytes(b"new movie")
            (target / "movie.mkv").write_bytes(b"old movie")
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "state": "finalizing",
                "upgrade": True,
                "payload_paths": [str(source)],
                "destination": str(destination),
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            numbered = destination / f"{source.name} (2)"
            self.assertEqual(result["state"], "payload_imported")
            self.assertEqual(result["resolved_targets"][str(source)], str(numbered))
            self.assertEqual((numbered / "movie.mkv").read_bytes(), b"new movie")
            self.assertEqual((target / "movie.mkv").read_bytes(), b"old movie")

    def test_upgrade_single_file_places_number_before_video_extension(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            source = staging / "Movie.2026.mkv"
            target = destination / source.name
            source.parent.mkdir(parents=True)
            destination.mkdir(parents=True)
            source.write_bytes(b"new movie")
            target.write_bytes(b"old movie")
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "state": "finalizing",
                "upgrade": True,
                "payload_paths": [str(source)],
                "destination": str(destination),
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            self.assertEqual(result["state"], "payload_imported")
            self.assertTrue((destination / "Movie.2026 (2).mkv").is_file())

    def test_upgrade_import_reuses_a_journaled_numbered_target(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            source = staging / "Movie.2026.1080p-GROUP"
            default_target = destination / source.name
            numbered_target = destination / f"{source.name} (2)"
            source.mkdir(parents=True)
            default_target.mkdir(parents=True)
            (source / "movie.mkv").write_bytes(b"new movie")
            (default_target / "movie.mkv").write_bytes(b"old movie")
            store = QBittorrentJobStore(Path(root) / "jobs.json")
            store.upsert("abc", {
                "state": "move_failed",
                "upgrade": True,
                "payload_paths": [str(source)],
                "destination": str(destination),
                "resolved_targets": {str(source): str(numbered_target)},
                "transfer_plan": [{
                    "source": str(source),
                    "target": str(numbered_target),
                    "action": "move",
                    "status": "started",
                }],
            })

            result = store.move_completed_payload("abc", allowed_staging_root=staging)

            self.assertEqual(result["state"], "payload_imported")
            self.assertTrue((numbered_target / "movie.mkv").is_file())
            self.assertFalse((destination / f"{source.name} (3)").exists())

    def test_manager_recovers_finalizing_job_after_torrent_was_removed(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            payload = staging / "Movie.2026.1080p-GROUP"
            payload.mkdir(parents=True)
            (payload / "movie.mkv").write_bytes(b"movie")
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {
                "state": "finalizing",
                "payload_paths": [str(payload)],
                "destination": str(destination),
            })
            manager.ensure_running = lambda: True
            manager.client.torrents = lambda: []

            results = manager.process_completed()

            self.assertEqual(results[0]["state"], "imported")
            self.assertTrue((destination / payload.name / "movie.mkv").exists())

    def test_manager_marks_confirmed_missing_download_as_cancelled_without_error(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            manager.jobs.upsert("abc", {
                "state": "downloading",
                "tmdb_id": "100",
                "identity_handoff": {"state": "pending"},
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])
            manager.jobs.move_completed_payload = MagicMock()

            with patch("services.qbittorrent.time.time", return_value=100):
                self.assertEqual(manager.process_completed(), [])
            with patch("services.qbittorrent.time.time", return_value=105):
                self.assertEqual(manager.process_completed(), [])
            with patch("services.qbittorrent.time.time", return_value=111):
                results = manager.process_completed()

            job = manager.jobs.get("abc")
            self.assertEqual(results[0]["state"], "cancelled")
            self.assertEqual(job["state"], "cancelled")
            self.assertEqual(job["last_error"], "")
            self.assertEqual(job["identity_handoff"]["state"], "not_required")
            manager.jobs.move_completed_payload.assert_not_called()

    def test_manager_clears_missing_marker_when_torrent_reappears_during_grace_period(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            manager.jobs.upsert("abc", {"state": "downloading"})
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])

            with patch("services.qbittorrent.time.time", return_value=100):
                manager.process_completed()
            manager.client.torrents.return_value = [{"hash": "abc", "progress": 0.5}]
            manager.process_completed()

            job = manager.jobs.get("abc")
            self.assertEqual(job["state"], "downloading")
            self.assertIsNone(job["missing_since"])
            self.assertEqual(job["missing_checks"], 0)

    def test_manager_reactivates_cancelled_job_when_torrent_reappears(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            manager.jobs.upsert("abc", {
                "state": "cancelled",
                "tmdb_id": "100",
                "identity_handoff": {"state": "not_required"},
                "cancelled_at": 100,
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{"hash": "abc", "progress": 0.5}])

            self.assertEqual(manager.process_completed(), [])

            job = manager.jobs.get("abc")
            self.assertEqual(job["state"], "downloading")
            self.assertEqual(job["identity_handoff"]["state"], "pending")
            self.assertIsNone(job["cancelled_at"])

    def test_manager_abandons_missing_failed_job_only_after_grace_period(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            manager.jobs.upsert("abc", {"state": "move_failed", "last_error": "old failure"})
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])

            with patch("services.qbittorrent.time.time", return_value=100):
                manager.process_completed()
            with patch("services.qbittorrent.time.time", return_value=105):
                manager.process_completed()
            with patch("services.qbittorrent.time.time", return_value=111):
                results = manager.process_completed()

            job = manager.jobs.get("abc")
            self.assertEqual(results[0]["state"], "abandoned")
            self.assertEqual(job["state"], "abandoned")
            self.assertEqual(job["last_error"], "")

    def test_manager_removes_torrent_only_after_payload_import_succeeds(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            payload = staging / "Movie.2026.1080p-GROUP"
            payload.mkdir(parents=True)
            (payload / "movie.mkv").write_bytes(b"movie")
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {"state": "downloading", "destination": str(destination)})
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{
                "hash": "abc", "progress": 1, "save_path": str(staging),
            }])
            manager.client.files = MagicMock(return_value=[{"name": payload.name + "/movie.mkv"}])
            manager.client.pause = MagicMock()
            manager.client.remove_without_files = MagicMock()

            results = manager.process_completed()

            self.assertEqual(results[0]["state"], "imported")
            self.assertTrue((destination / payload.name / "movie.mkv").exists())
            manager.client.remove_without_files.assert_called_once_with("abc")

    def test_manager_keeps_torrent_when_destination_conflicts(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            payload = staging / "Movie.2026.1080p-GROUP"
            target = destination / payload.name
            payload.mkdir(parents=True)
            target.mkdir(parents=True)
            (payload / "movie.mkv").write_bytes(b"new movie")
            (target / "movie.mkv").write_bytes(b"different movie")
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {"state": "downloading", "destination": str(destination)})
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{
                "hash": "abc", "progress": 1, "save_path": str(staging),
            }])
            manager.client.files = MagicMock(return_value=[{"name": payload.name + "/movie.mkv"}])
            manager.client.pause = MagicMock()
            manager.client.remove_without_files = MagicMock()

            results = manager.process_completed()

            self.assertEqual(results[0]["state"], "destination_conflict")
            self.assertTrue(payload.exists())
            self.assertTrue(target.exists())
            manager.client.pause.assert_called_once_with("abc")
            manager.client.remove_without_files.assert_not_called()

    def test_manager_keeps_torrent_when_filesystem_move_fails(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            payload = staging / "Movie.2026.1080p-GROUP"
            payload.mkdir(parents=True)
            (payload / "movie.mkv").write_bytes(b"movie")
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {"state": "downloading", "destination": str(destination)})
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{
                "hash": "abc", "progress": 1, "save_path": str(staging),
            }])
            manager.client.files = MagicMock(return_value=[{"name": payload.name + "/movie.mkv"}])
            manager.client.pause = MagicMock()
            manager.client.remove_without_files = MagicMock()

            with patch("services.qbittorrent.shutil.move", side_effect=OSError("disk error")):
                results = manager.process_completed()

            self.assertEqual(results[0]["state"], "move_failed")
            self.assertTrue(payload.exists())
            manager.client.remove_without_files.assert_not_called()

    def test_manager_retries_torrent_cleanup_without_moving_payload_twice(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            imported = destination / "Movie.2026.1080p-GROUP"
            imported.mkdir(parents=True)
            (imported / "movie.mkv").write_bytes(b"movie")
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {
                "state": "cleanup_failed",
                "destination": str(destination),
                "imported_paths": [str(imported)],
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{"hash": "abc", "progress": 1}])
            manager.client.remove_without_files = MagicMock()
            manager.jobs.move_completed_payload = MagicMock()

            results = manager.process_completed()

            self.assertEqual(results[0]["state"], "imported")
            manager.client.remove_without_files.assert_called_once_with("abc")
            manager.jobs.move_completed_payload.assert_not_called()

    def test_manager_replays_imported_job_with_pending_library_scan_after_restart(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            imported = destination / "Movie.2026.1080p-GROUP"
            imported.mkdir(parents=True)
            (imported / "movie.mkv").write_bytes(b"movie")
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {
                "state": "imported",
                "library_scan_pending": True,
                "identity_handoff": {"state": "pending"},
                "imported_paths": [str(imported)],
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])

            results = manager.process_completed()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["state"], "imported")
            self.assertTrue(results[0]["library_scan_pending"])
            self.assertEqual(results[0]["identity_handoff"]["state"], "pending")

    def test_manager_does_not_replay_imported_job_after_identity_handoff_completes(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {
                "state": "imported",
                "library_scan_pending": False,
                "identity_handoff": {"state": "applied"},
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])

            results = manager.process_completed()

            self.assertEqual(results, [])

    def test_manager_replays_legacy_imported_job_without_handoff_markers_once(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            manager.jobs.upsert("abc", {"state": "imported"})
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])

            results = manager.process_completed()

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["state"], "imported")
            self.assertNotIn("identity_handoff", results[0])

    def test_manager_does_not_resubmit_already_imported_magnet(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            magnet = "magnet:?xt=urn:btih:48373C3569751AA5C51072E826DD43FFB350BA84&dn=Movie"
            manager.jobs.upsert("48373c3569751aa5c51072e826dd43ffb350ba84", {
                "title": "Movie",
                "state": "imported",
                "imported_paths": [str(destination / "Movie.mkv")],
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.add_magnet = MagicMock()

            result = manager.submit_magnet(magnet, {"title": "Movie", "year": "2026"})

            self.assertEqual(result["state"], "imported")
            self.assertTrue(result["already_exists"])
            self.assertEqual(result["imported_paths"], [str(destination / "Movie.mkv")])
            manager.ensure_running.assert_not_called()
            manager.client.add_magnet.assert_not_called()

    def test_manager_resubmits_stale_downloading_job_missing_from_qbittorrent(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            magnet = "magnet:?xt=urn:btih:48373C3569751AA5C51072E826DD43FFB350BA84&dn=Movie"
            torrent_hash = "48373c3569751aa5c51072e826dd43ffb350ba84"
            manager.jobs.upsert(torrent_hash, {
                "title": "Movie",
                "state": "downloading",
                "last_error": "old error",
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])
            manager.client.add_magnet = MagicMock()

            result = manager.submit_magnet(magnet, {"title": "Movie", "year": "2026"})

            self.assertEqual(result["state"], "validating")
            self.assertFalse(result.get("already_exists", False))
            self.assertTrue(result["resubmitted_at"])
            manager.client.add_magnet.assert_called_once_with(magnet, str(staging), stop_after_metadata=True)

    def test_manager_resubmission_resets_cancelled_terminal_state(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            manager = QBittorrentManager(root, {"incomplete_dir": str(staging)}, [])
            magnet = "magnet:?xt=urn:btih:48373C3569751AA5C51072E826DD43FFB350BA84&dn=Movie"
            torrent_hash = "48373c3569751aa5c51072e826dd43ffb350ba84"
            manager.jobs.upsert(torrent_hash, {
                "state": "cancelled",
                "cancelled_at": 100,
                "missing_since": 90,
                "missing_checks": 3,
                "terminal_reason": "Removed from qBittorrent before completion",
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])
            manager.client.add_magnet = MagicMock()

            result = manager.submit_magnet(magnet, {
                "title": "Movie",
                "tmdb_id": "100",
                "identity_handoff": {"state": "pending"},
            })

            self.assertEqual(result["state"], "validating")
            self.assertIsNone(result["cancelled_at"])
            self.assertIsNone(result["missing_since"])
            self.assertEqual(result["missing_checks"], 0)
            self.assertEqual(result["terminal_reason"], "")
            self.assertEqual(result["identity_handoff"]["state"], "pending")

    def test_manager_blocks_unsafe_torrent_before_qbittorrent_adds_it(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.parse_torrent_metadata = MagicMock(return_value=[{"info": {
                "name": "random",
                "files": [{"path": "random.exe", "length": 877_597_184}],
            }}])
            manager.client.add_torrent = MagicMock()

            with self.assertRaisesRegex(QBittorrentError, "unsafe torrent payload"):
                manager.submit_torrent(b"torrent", "movie.torrent", {"expected_size": 1_700_000_000})

            manager.client.add_torrent.assert_not_called()

    def test_manager_adds_magnet_immediately_then_resumes_after_manifest_validation(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            magnet = "magnet:?xt=urn:btih:58373C3569751AA5C51072E826DD43FFB350BA84&dn=Movie"
            torrent_hash = "58373c3569751aa5c51072e826dd43ffb350ba84"
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{"hash": torrent_hash, "name": "Movie 2026"}])
            manager.client.files = MagicMock(return_value=[{"name": "Movie.2026.mkv", "size": 1_000_000_000}])
            manager.client.add_magnet = MagicMock()
            manager.client.resume = MagicMock()

            queued = manager.submit_magnet(magnet, {"title": "Movie", "expected_size": 1_000_000_000})
            processed = manager.process_completed()

            self.assertEqual(queued["state"], "validating")
            self.assertEqual(processed[0]["state"], "downloading")
            self.assertEqual(processed[0]["validated_manifest"]["total_size"], 1_000_000_000)
            manager.client.add_magnet.assert_called_once_with(magnet, str(manager.staging_dir), stop_after_metadata=True)
            manager.client.resume.assert_called_once_with(torrent_hash)

    def test_manager_keeps_an_added_magnet_stopped_until_its_metadata_is_available(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            torrent_hash = "68373c3569751aa5c51072e826dd43ffb350ba84"
            magnet = f"magnet:?xt=urn:btih:{torrent_hash}&dn=Movie"
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{"hash": torrent_hash, "name": "Movie 2026"}])
            manager.client.files = MagicMock(side_effect=[[], [{"name": "Movie.2026.mkv", "size": 1_000_000_000}]])
            manager.client.add_magnet = MagicMock()
            manager.client.resume = MagicMock()

            queued = manager.submit_magnet(magnet, {"title": "Movie", "expected_size": 1_000_000_000})
            waiting = manager.process_completed()
            processed = manager.process_completed()

            self.assertEqual(queued["state"], "validating")
            self.assertEqual(waiting[0]["state"], "validating")
            self.assertEqual(processed[0]["state"], "downloading")
            self.assertEqual(manager.jobs.get(torrent_hash)["state"], "downloading")
            manager.client.add_magnet.assert_called_once_with(magnet, str(manager.staging_dir), stop_after_metadata=True)
            manager.client.resume.assert_called_once_with(torrent_hash)

    def test_manager_removes_an_unsafe_magnet_before_resuming_it(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            torrent_hash = "78373c3569751aa5c51072e826dd43ffb350ba84"
            magnet = f"magnet:?xt=urn:btih:{torrent_hash}&dn=Movie"
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{"hash": torrent_hash, "name": "random"}])
            manager.client.files = MagicMock(return_value=[{"name": "random.exe", "size": 877_597_184}])
            manager.client.add_magnet = MagicMock()
            manager.client.remove_without_files = MagicMock()
            manager.client.resume = MagicMock()

            manager.submit_magnet(magnet, {"title": "Movie"})
            processed = manager.process_completed()

            self.assertEqual(processed[0]["state"], "validation_failed")
            self.assertIn("unsafe torrent payload", processed[0]["last_error"])
            manager.client.add_magnet.assert_called_once_with(magnet, str(manager.staging_dir), stop_after_metadata=True)
            manager.client.remove_without_files.assert_called_once_with(torrent_hash)
            manager.client.resume.assert_not_called()

    def test_manager_keeps_active_job_when_qbittorrent_confirms_hash(self):
        with tempfile.TemporaryDirectory() as root:
            manager = QBittorrentManager(root, {}, [])
            magnet = "magnet:?xt=urn:btih:48373C3569751AA5C51072E826DD43FFB350BA84&dn=Movie"
            torrent_hash = "48373c3569751aa5c51072e826dd43ffb350ba84"
            manager.jobs.upsert(torrent_hash, {"title": "Movie", "state": "downloading"})
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[{"hash": torrent_hash, "progress": 0.5}])
            manager.client.add_magnet = MagicMock()

            result = manager.submit_magnet(magnet, {"title": "Movie"})

            self.assertTrue(result["already_exists"])
            self.assertEqual(result["state"], "downloading")
            manager.client.add_magnet.assert_not_called()

    def test_manager_does_not_resubmit_job_with_recoverable_payload(self):
        with tempfile.TemporaryDirectory() as root:
            staging = Path(root) / "incomplete"
            destination = Path(root) / "library"
            payload = staging / "Movie.2026.1080p-GROUP"
            payload.mkdir(parents=True)
            manager = QBittorrentManager(
                root,
                {"incomplete_dir": str(staging), "download_dir": str(destination)},
                [str(destination)],
            )
            magnet = "magnet:?xt=urn:btih:48373C3569751AA5C51072E826DD43FFB350BA84&dn=Movie"
            torrent_hash = "48373c3569751aa5c51072e826dd43ffb350ba84"
            manager.jobs.upsert(torrent_hash, {
                "title": "Movie",
                "state": "move_failed",
                "payload_paths": [str(payload)],
                "destination": str(destination),
            })
            manager.ensure_running = MagicMock(return_value=True)
            manager.client.torrents = MagicMock(return_value=[])
            manager.client.add_magnet = MagicMock()

            result = manager.submit_magnet(magnet, {"title": "Movie"})

            self.assertTrue(result["already_exists"])
            self.assertTrue(result["recovery_pending"])
            manager.client.add_magnet.assert_not_called()


class QBittorrentProxyTests(unittest.TestCase):
    def test_embedded_html_preserves_qbt_without_copying_cp_navigation(self):
        original = "<html><head><title>qBittorrent WebUI</title></head><body><main>QBT</main></body></html>"

        rendered = build_downloads_html(original)

        self.assertIn('id="cp-qbt-frame-bridge"', rendered)
        self.assertIn('Object.defineProperty(window.parent, "qBittorrent"', rendered)
        self.assertIn("<main>QBT</main>", rendered)
        self.assertNotIn('id="cp-qbt-sidebar"', rendered)
        self.assertNotIn("<iframe", rendered)


if __name__ == "__main__":
    unittest.main()
