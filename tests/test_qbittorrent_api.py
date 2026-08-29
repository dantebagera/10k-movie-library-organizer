import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import app


class FakeManager:
    def __init__(self):
        self.submitted = []
        self.installed = False
        self.existing_jobs = {}
        self.completed_results = [{"hash": "abc", "state": "imported"}]

    def configuration(self):
        return {
            "mode": app._qbt_mode,
            "download_dir": app._qbt_download_dir,
            "effective_download_dir": app._qbt_download_dir or app._movies_dirs[0],
            "download_dir_in_library": not bool(app._qbt_download_dir),
            "incomplete_dir": app._qbt_incomplete_dir,
            "effective_incomplete_dir": app._qbt_incomplete_dir or "data/qbittorrent/incomplete",
            "incomplete_dir_in_library": False,
            "webui_port": app._qbt_webui_port,
        }

    def status(self):
        return {
            **self.configuration(),
            "installed": self.installed,
            "running": self.installed,
            "supported": True,
            "version": "5.2.2",
        }

    def update_latest(self):
        self.installed = True
        return {**self.status(), "version": "5.2.3", "update_result": "updated"}

    def submit_magnet(self, magnet, metadata):
        self.submitted.append(("magnet", magnet, metadata))
        return {"hash": "abc", "state": "downloading", **metadata}

    def submit_torrent(self, content, filename, metadata):
        self.submitted.append(("torrent", content, filename, metadata))
        return {"hash": "def", "state": "downloading", **metadata}

    def process_completed(self):
        return self.completed_results

    @property
    def jobs(self):
        manager = self

        class Jobs:
            def all(self):
                return manager.existing_jobs or {"abc": {"state": "downloading"}}

            def get(self, torrent_hash):
                return manager.existing_jobs.get(str(torrent_hash or "").lower())

            def upsert(self, torrent_hash, values):
                key = str(torrent_hash or "").lower()
                manager.existing_jobs[key] = {**manager.existing_jobs.get(key, {}), **values, "hash": key}
                return manager.existing_jobs[key]

        return Jobs()


class QBittorrentApiTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "mode": app._qbt_mode,
            "download": app._qbt_download_dir,
            "incomplete": app._qbt_incomplete_dir,
            "port": app._qbt_webui_port,
            "dirs": list(app._movies_dirs),
            "dir": app._movies_dir,
            "prowlarr_url": app._prowlarr_url,
            "prowlarr_key": app._prowlarr_key,
            "user_data_dir": app._user_data_dir,
            "catalog_repositories": dict(app._catalog_repository_cache),
        }
        self.temp = tempfile.TemporaryDirectory()
        app._user_data_dir = self.temp.name
        app._catalog_repository_cache.clear()
        app._movies_dirs = [self.temp.name]
        app._movies_dir = self.temp.name
        app._qbt_mode = "embedded"
        app._qbt_download_dir = ""
        app._qbt_incomplete_dir = ""
        app._qbt_webui_port = 8686
        app._prowlarr_url = "http://prowlarr.test"
        app._prowlarr_key = "prowlarr-key"
        self.manager = FakeManager()
        self.client = app.app.test_client()
        self.manager_patch = patch.object(app, "_get_qbittorrent_manager", return_value=self.manager)
        self.save_patch = patch.object(app, "_save_config")
        self.manager_patch.start()
        self.save_patch.start()

    def tearDown(self):
        self.manager_patch.stop()
        self.save_patch.stop()
        app._qbt_mode = self.original["mode"]
        app._qbt_download_dir = self.original["download"]
        app._qbt_incomplete_dir = self.original["incomplete"]
        app._qbt_webui_port = self.original["port"]
        app._movies_dirs = self.original["dirs"]
        app._movies_dir = self.original["dir"]
        app._prowlarr_url = self.original["prowlarr_url"]
        app._prowlarr_key = self.original["prowlarr_key"]
        app._catalog_repository_cache.clear()
        app._catalog_repository_cache.update(self.original["catalog_repositories"])
        app._user_data_dir = self.original["user_data_dir"]
        self.temp.cleanup()

    def test_migration_only_import_audit_routes_are_removed(self):
        self.assertEqual(self.client.get("/api/qbittorrent/import-audit").status_code, 404)
        self.assertEqual(self.client.post("/api/qbittorrent/import-audit/verify", json={}).status_code, 404)

    def test_config_defaults_to_embedded_and_primary_library(self):
        response = self.client.get("/api/qbittorrent/config")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["mode"], "embedded")
        self.assertEqual(data["effective_download_dir"], self.temp.name)

    def test_config_allows_external_destination_with_warning(self):
        external = str(Path(self.temp.name).parent / "external-downloads")
        response = self.client.post("/api/qbittorrent/config", json={
            "mode": "embedded",
            "download_dir": external,
            "incomplete_dir": str(Path(self.temp.name).parent / "incomplete"),
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["download_dir_in_library"])

    def test_config_rejects_incomplete_folder_inside_library(self):
        response = self.client.post("/api/qbittorrent/config", json={
            "mode": "embedded",
            "incomplete_dir": str(Path(self.temp.name) / "incomplete"),
        })

        self.assertEqual(response.status_code, 400)

    def test_submit_magnet_uses_embedded_manager(self):
        magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        response = self.client.post("/api/qbittorrent/submit", json={
            "magnet_url": magnet,
            "title": "Movie",
            "year": "2026",
            "tmdb_id": "800",
            "imdb_id": "tt0000800",
            "expected_size": 1_234_567_890,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.submitted[0][0], "magnet")
        self.assertEqual(self.manager.submitted[0][2]["title"], "Movie")
        self.assertEqual(self.manager.submitted[0][2]["tmdb_id"], "800")
        self.assertEqual(self.manager.submitted[0][2]["imdb_id"], "tt0000800")
        self.assertEqual(self.manager.submitted[0][2]["expected_size"], 1_234_567_890)
        self.assertEqual(self.manager.submitted[0][2]["identity_handoff"]["state"], "pending")

    def test_submit_prefers_a_hash_verifiable_torrent_file_when_both_transports_exist(self):
        info_hash = "d4b719ed66754116dc6c656303172ba96abfcae1"
        magnet = f"magnet:?xt=urn:btih:{info_hash}&dn=Movie"
        with patch("app._resolve_prowlarr_download", return_value={
            "kind": "torrent", "content": b"torrent", "filename": "movie.torrent",
        }):
            response = self.client.post("/api/qbittorrent/submit", json={
                "magnet_url": magnet,
                "download_url": "http://prowlarr.test/prowlarr/1/download?id=5",
                "info_hash": info_hash,
                "title": "Movie",
                "tmdb_id": "800",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.submitted[0][0], "torrent")
        self.assertEqual(self.manager.submitted[0][3]["expected_info_hash"], info_hash)

    def test_submit_falls_back_to_the_original_magnet_when_torrent_identity_is_substituted(self):
        info_hash = "e4b719ed66754116dc6c656303172ba96abfcae1"
        magnet = f"magnet:?xt=urn:btih:{info_hash}&dn=Movie"
        self.manager.submit_torrent = Mock(side_effect=app.TorrentIdentityMismatch(
            "Blocked torrent because its infohash does not match the selected release"
        ))
        with patch("app._resolve_prowlarr_download", return_value={
            "kind": "torrent", "content": b"poisoned-torrent", "filename": "movie.torrent",
        }):
            response = self.client.post("/api/qbittorrent/submit", json={
                "magnet_url": magnet,
                "download_url": "http://prowlarr.test/prowlarr/1/download?id=6",
                "info_hash": info_hash,
                "title": "Movie",
                "tmdb_id": "800",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.submitted[0][0], "magnet")
        self.assertEqual(self.manager.submitted[0][1], magnet)

    def test_prowlarr_resolver_preserves_a_magnet_redirect_with_its_trackers(self):
        info_hash = "a4b719ed66754116dc6c656303172ba96abfcae1"
        magnet = f"magnet:?xt=urn:btih:{info_hash}&dn=Movie&tr=udp%3A%2F%2Ftracker.example%2Fannounce"
        headers = Message()
        headers["Location"] = magnet
        redirect = urllib.error.HTTPError("http://prowlarr.test/download", 301, "Moved", headers, None)

        with patch("app.urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = redirect
            transport = app._resolve_prowlarr_download("http://prowlarr.test/download")

        self.assertEqual(transport, {"kind": "magnet", "magnet": magnet})

    def test_prowlarr_resolver_returns_a_torrent_file_without_following_external_urls(self):
        response = MagicMock()
        response.read.return_value = b"torrent"
        response.headers.get.return_value = "attachment; filename=movie.torrent"
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response

        with patch("app.urllib.request.build_opener", return_value=opener):
            transport = app._resolve_prowlarr_download("http://prowlarr.test/download")

        self.assertEqual(transport, {"kind": "torrent", "content": b"torrent", "filename": "movie.torrent"})

    def test_submit_uses_a_hash_matching_prowlarr_redirect_magnet(self):
        info_hash = "b4b719ed66754116dc6c656303172ba96abfcae1"
        magnet = f"magnet:?xt=urn:btih:{info_hash}&dn=Movie&tr=udp%3A%2F%2Ftracker.example%2Fannounce"
        with patch("app._resolve_prowlarr_download", return_value={"kind": "magnet", "magnet": magnet}):
            response = self.client.post("/api/qbittorrent/submit", json={
                "download_url": "http://prowlarr.test/download",
                "info_hash": info_hash,
                "title": "Movie",
                "tmdb_id": "800",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.submitted[0][0], "magnet")
        self.assertEqual(self.manager.submitted[0][1], magnet)

    def test_submit_blocks_a_mismatched_prowlarr_redirect_magnet(self):
        with patch("app._resolve_prowlarr_download", return_value={
            "kind": "magnet",
            "magnet": "magnet:?xt=urn:btih:c4b719ed66754116dc6c656303172ba96abfcae1&dn=Other",
        }):
            response = self.client.post("/api/qbittorrent/submit", json={
                "download_url": "http://prowlarr.test/download",
                "info_hash": "d4b719ed66754116dc6c656303172ba96abfcae1",
                "title": "Movie",
                "tmdb_id": "800",
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not match the selected release", response.get_json()["error"])
        self.assertEqual(self.manager.submitted, [])

    def test_prowlarr_result_links_do_not_fabricate_a_trackerless_magnet(self):
        links = app._prowlarr_result_links({
            "infoHash": "e4b719ed66754116dc6c656303172ba96abfcae1",
            "downloadUrl": "http://prowlarr.test/download",
        })

        self.assertEqual(links["magnet_url"], "")
        self.assertEqual(links["download_url"], "http://prowlarr.test/download")

    def test_submit_blocks_a_magnet_that_disagrees_with_the_selected_release_identity(self):
        response = self.client.post("/api/qbittorrent/submit", json={
            "magnet_url": "magnet:?xt=urn:btih:f4b719ed66754116dc6c656303172ba96abfcae1&dn=Other",
            "info_hash": "e4b719ed66754116dc6c656303172ba96abfcae1",
            "title": "Movie",
            "tmdb_id": "800",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not match the selected release", response.get_json()["error"])
        self.assertEqual(self.manager.submitted, [])

    def test_submit_blocks_owned_movies_unless_the_request_is_an_upgrade(self):
        magnet = "magnet:?xt=urn:btih:1123456789abcdef0123456789abcdef01234567"
        payload = {
            "magnet_url": magnet,
            "title": "Movie",
            "year": "2026",
            "tmdb_id": "800",
        }

        with patch("app._curated_movie_is_owned", return_value=True):
            blocked = self.client.post("/api/qbittorrent/submit", json=payload)
            upgrade = self.client.post("/api/qbittorrent/submit", json={**payload, "upgrade": True})

        self.assertEqual(blocked.status_code, 409)
        self.assertIn("already in the library", blocked.get_json()["error"])
        self.assertEqual(upgrade.status_code, 200)
        self.assertEqual(len(self.manager.submitted), 1)
        self.assertTrue(self.manager.submitted[0][2]["upgrade"])

    def test_bulk_upgrade_submission_journals_upgrade_and_exact_release(self):
        release_title = "Movie 2026 2160p BluRay REMUX"
        result = app._ai_control_submit_download({
            "title": "Movie",
            "year": "2026",
            "tmdb_id": "800",
            "imdb_id": "tt0000800",
            "upgrade": True,
            "variant": {
                "title": release_title,
                "indexer": "Trusted",
                "resolution": "4K",
                "size_bytes": 12_345_678_900,
                "magnet_url": "magnet:?xt=urn:btih:2123456789abcdef0123456789abcdef01234567",
            },
        })

        self.assertEqual(result["state"], "downloading")
        metadata = self.manager.submitted[0][2]
        self.assertTrue(metadata["upgrade"])
        self.assertEqual(metadata["release_title"], release_title)
        self.assertEqual(metadata["expected_size"], 12_345_678_900)
        self.assertEqual(metadata["identity_handoff"]["state"], "pending")

    def test_bulk_submission_rejects_a_variant_below_the_selected_quality(self):
        response = self.client.post("/api/sources/review/submit", json={"rows": [{
            "title": "Maze Runner: The Death Cure",
            "year": "2018",
            "tmdb_id": "336843",
            "quality": "1080p",
            "upgrade": True,
            "selected": True,
            "status": "ready",
            "variant": {
                "title": "Maze Runner The Death Cure 2018 720p BRRip",
                "indexer": "YTS",
                "resolution": "720p",
                "magnet_url": "magnet:?xt=urn:btih:3123456789abcdef0123456789abcdef01234567",
            },
        }]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["submitted_count"], 0)
        self.assertIn("Selected 1080p source is actually 720p", response.get_json()["results"][0]["error"])
        self.assertEqual(self.manager.submitted, [])

    def test_submit_rejects_title_only_jobs(self):
        response = self.client.post("/api/qbittorrent/submit", json={
            "magnet_url": "magnet:?xt=urn:btih:2123456789abcdef0123456789abcdef01234567",
            "title": "Unidentified Movie",
            "year": "2026",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("TMDB or IMDb identity", response.get_json()["error"])
        self.assertEqual(self.manager.submitted, [])

    def test_submit_rejects_arbitrary_download_url(self):
        response = self.client.post("/api/qbittorrent/submit", json={
            "download_url": "https://evil.test/file.torrent",
            "title": "Movie",
        })

        self.assertEqual(response.status_code, 400)

    def test_submit_uses_magnet_when_prowlarr_download_redirects_to_magnet(self):
        magnet = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Movie"
        headers = Message()
        headers["Location"] = magnet

        with patch("app.urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = urllib.error.HTTPError(
                "http://prowlarr.test/prowlarr/6/download?id=1", 301, "Moved Permanently", headers, None,
            )
            response = self.client.post("/api/qbittorrent/submit", json={
                "download_url": "http://prowlarr.test/prowlarr/6/download?id=1",
                "title": "Movie",
                "tmdb_id": "800",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.submitted[0][0], "magnet")
        self.assertEqual(self.manager.submitted[0][1], magnet)

    def test_submit_blocks_a_prowlarr_redirect_to_a_different_release_hash(self):
        selected_hash = "0123456789abcdef0123456789abcdef01234567"
        redirect_magnet = "magnet:?xt=urn:btih:1123456789abcdef0123456789abcdef01234567&dn=Other"
        headers = Message()
        headers["Location"] = redirect_magnet

        with patch("app.urllib.request.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = urllib.error.HTTPError(
                "http://prowlarr.test/prowlarr/6/download?id=2", 301, "Moved Permanently", headers, None,
            )
            response = self.client.post("/api/qbittorrent/submit", json={
                "download_url": "http://prowlarr.test/prowlarr/6/download?id=2",
                "info_hash": selected_hash,
                "title": "Movie",
                "tmdb_id": "800",
            })

        self.assertEqual(response.status_code, 400)
        self.assertIn("does not match the selected release", response.get_json()["error"])
        self.assertEqual(self.manager.submitted, [])

    def test_submit_duplicate_magnet_conflict_returns_existing_job(self):
        magnet = "magnet:?xt=urn:btih:48373C3569751AA5C51072E826DD43FFB350BA84&dn=Movie"
        torrent_hash = "48373c3569751aa5c51072e826dd43ffb350ba84"
        self.manager.existing_jobs[torrent_hash] = {
            "hash": torrent_hash,
            "state": "imported",
            "title": "Movie",
        }

        def duplicate_magnet(_magnet, _metadata):
            raise urllib.error.HTTPError(
                "http://127.0.0.1:8686/api/v2/torrents/add",
                409,
                "Conflict",
                Message(),
                None,
            )

        self.manager.submit_magnet = duplicate_magnet

        response = self.client.post("/api/qbittorrent/submit", json={
            "magnet_url": magnet,
            "title": "Movie",
            "tmdb_id": "800",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["state"], "imported")
        self.assertTrue(response.get_json()["already_exists"])

    def test_update_route_updates_the_embedded_portable_runtime(self):
        installed = self.client.post("/api/qbittorrent/install")
        updated = self.client.post("/api/qbittorrent/update")

        self.assertEqual(installed.status_code, 404)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["version"], "5.2.3")
        self.assertEqual(updated.get_json()["update_result"], "updated")

    def test_update_route_requires_embedded_mode(self):
        app._qbt_mode = "system"

        response = self.client.post("/api/qbittorrent/update")

        self.assertEqual(response.status_code, 409)
        self.assertIn("embedded qBittorrent", response.get_json()["error"])

    def test_finalize_route_remains_available(self):
        finalized = self.client.post("/api/qbittorrent/finalize")

        self.assertEqual(finalized.get_json()["results"][0]["state"], "imported")

    def test_finalize_keeps_invalid_cleanup_payload_pending_without_a_global_scan(self):
        imported = Path(self.temp.name) / "Splice.2009"
        imported.mkdir()
        self.manager.completed_results = [{
            "hash": "abc",
            "state": "cleanup_failed",
            "imported_paths": [str(imported)],
            "library_scan_pending": True,
        }]

        with patch.object(app, "_start_library_reconcile") as reconcile:
            response = self.client.post("/api/qbittorrent/finalize")

        self.assertEqual(response.status_code, 200)
        reconcile.assert_not_called()
        job = self.manager.existing_jobs["abc"]
        self.assertTrue(job["library_scan_pending"])
        self.assertEqual(job["identity_handoff"]["state"], "deferred")
        self.assertEqual(job["identity_handoff"]["reason"], "The download job has no stable identity")

    def test_completed_video_uses_exact_path_coordinator_and_keeps_journal_pending_until_commit(self):
        movie = Path(self.temp.name) / "Movie.2026.mkv"
        movie.write_bytes(b"fixture")
        item = {"hash": "abc", "state": "imported", "imported_paths": [str(movie)], "library_scan_pending": True}
        coordinator = Mock()
        coordinator.reconcile_paths.return_value = {"accepted": 1, "rejected": 0}
        repository = Mock()
        repository.final_card_publication.return_value = []
        handoff = {"state": "ready", "paths": [str(movie)], "tmdb_id": "1", "metadata": {"tmdb_id": "1"}}
        with (
            patch.object(app, "_library_ingestion_coordinator", return_value=coordinator),
            patch.object(app, "_catalog_repository", return_value=repository),
            patch.object(app, "_apply_completed_download_identity", return_value=handoff),
            patch.object(app, "_prepare_final_card_assets"),
            patch.object(app, "_start_library_reconcile") as full_scan,
        ):
            self.assertTrue(app._handle_completed_qbittorrent_imports(self.manager, [item]))
        full_scan.assert_not_called()
        coordinator.reconcile_paths.assert_called_once()
        args, kwargs = coordinator.reconcile_paths.call_args
        self.assertEqual(args[0], [str(movie)])
        self.assertEqual(kwargs["reason"], "qbittorrent")
        self.assertTrue(self.manager.existing_jobs["abc"]["library_scan_pending"])


if __name__ == "__main__":
    unittest.main()
