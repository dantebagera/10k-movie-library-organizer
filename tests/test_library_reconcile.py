import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app
from services.media_file_facts import MediaFileFacts


class LibraryReconcileTest(unittest.TestCase):
    def setUp(self):
        self.original_dirs = app._movies_dirs
        self.original_dir = app._movies_dir
        self.original_user_data = app._user_data_dir
        self.original_tmdb_key = app._tmdb_key
        self.original_library_cache = dict(app._library_cache)
        self.original_plex_cache = dict(app._plex_cache)

    def tearDown(self):
        app._movies_dirs = self.original_dirs
        app._movies_dir = self.original_dir
        app._user_data_dir = self.original_user_data
        app._tmdb_key = self.original_tmdb_key
        app._library_cache = self.original_library_cache
        app._plex_cache = self.original_plex_cache

    def configure(self, movies_dir, data_dir):
        app._movies_dirs = [movies_dir]
        app._movies_dir = movies_dir
        app._user_data_dir = data_dir
        app._tmdb_key = "tmdb-key"

    def test_stable_new_file_is_probed_once_and_persists_complete_facts(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "The.Monkey.2025.1080p.x265.10bit.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            measured = MediaFileFacts(
                video_width=1800,
                video_height=960,
                video_codec="HEVC",
                video_profile="Main 10",
                video_bit_depth=10,
                video_bitrate=2_000_527,
                duration_ms=5_780_917,
                audio_codec="AAC",
                audio_channels=2,
                audio_bitrate=132_300,
                filename_quality_claim="1080p",
                quality_class="1080p",
                quality_source="measured",
                quality_nonstandard=True,
                probe_status="ok",
                probe_size=movie.stat().st_size,
                probe_modified_time=movie.stat().st_mtime,
            )
            candidate = {
                "tmdb_id": "1124620",
                "title": "The Monkey",
                "year": "2025",
                "match_source": "auto_tmdb",
            }

            with patch("app._file_copy_is_stable", return_value=True), patch(
                "app.probe_media_file",
                return_value=measured,
            ) as probe, patch(
                "app._resolve_tmdb_identity",
                return_value=app._identity_resolution(
                    "accepted",
                    candidate,
                    {"status": "accepted", "outcome": "accepted"},
                    source="auto_tmdb",
                ),
            ):
                outcome = app._reconcile_library_path(
                    str(movie),
                    "tmdb",
                    store=store,
                )
            record = store.snapshot()["files"][store._key(movie)]

        self.assertEqual(outcome, "matched")
        probe.assert_called_once_with(str(movie))
        self.assertEqual((record["video_width"], record["video_height"]), (1800, 960))
        self.assertEqual(record["video_codec"], "HEVC")
        self.assertEqual(record["video_bit_depth"], 10)
        self.assertEqual(record["quality_class"], "1080p")
        self.assertEqual(record["resolution"], "1080p")
        self.assertEqual(record["probe_status"], "ok")
        app._library_cache = {}

    def test_stable_scent_of_a_woman_is_matched_during_reconcile(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Scent.of.a.Woman.1992.1080p.BluRay.x264.YIFY.mp4"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            candidate = {
                "tmdb_id": "9475",
                "title": "Scent of a Woman",
                "year": "1992",
                "match_source": "auto_tmdb",
            }

            with patch("app._file_copy_is_stable", return_value=True), \
                    patch("app._resolve_tmdb_identity", return_value=app._identity_resolution(
                        "accepted", candidate, {"status": "accepted", "outcome": "accepted"}, source="auto_tmdb"
                    )):
                result = app._reconcile_library_files()
            record = store.snapshot()["files"][app._norm(str(movie))]

        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(record["metadata_status"], "accepted")
        self.assertEqual(record["tmdb_id"], "9475")
        self.assertEqual(record["parsed_title"], "scent of a woman")
        self.assertEqual(record["parsed_year"], "1992")
        self.assertEqual(record["decision_origin"], app.DECISION_ORIGIN_LIBRARY_RECONCILE)
        self.assertEqual(record["identity_decision_outcome"], "accepted")
        self.assertTrue(record["identity_evidence_fingerprint"])

    def test_changing_new_file_stays_pending_until_later_recheck(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Copying.Movie.2026.1080p.mkv"
            movie.write_bytes(b"partial")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})

            with patch("app._file_copy_is_stable", return_value=False):
                result = app._reconcile_library_files()
            record = store.snapshot()["files"][app._norm(str(movie))]

        self.assertEqual(result["pending"], 1)
        self.assertEqual(record["metadata_status"], "pending")
        self.assertEqual(record["ingest_status"], "pending")

    def test_reconcile_skips_already_accepted_files(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_tmdb_metadata({
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "poster_url": "alien.jpg",
                "plot": "Stored detail.",
                "cast": [],
                "directors": [],
                "writers": [],
                "certification": "",
                "keywords": [],
            })
            store.update_file_record(str(movie), {
                "identity_status": "accepted",
                "identity_title": "Alien",
                "identity_year": "1979",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "348",
                "size": movie.stat().st_size,
                "modified_time": movie.stat().st_mtime,
            })

            with patch("app._reconcile_library_path") as reconcile_path:
                result = app._reconcile_library_files()

        self.assertEqual(result["checked"], 0)
        reconcile_path.assert_not_called()

    def test_reconcile_repairs_accepted_identity_with_missing_enrichment(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            store.update_file_record(str(movie), {
                "identity_status": "accepted",
                "identity_title": "Alien",
                "identity_year": "1979",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "348",
                "size": movie.stat().st_size,
                "modified_time": movie.stat().st_mtime,
            })
            metadata = {
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "poster_url": "alien.jpg",
                "match_source": "saved_tmdb_id",
            }

            with patch("app._file_copy_is_stable", return_value=True), \
                    patch("app._resolve_tmdb_identity", return_value=app._identity_resolution(
                        "accepted", metadata, {"status": "accepted", "outcome": "accepted"}, source="saved_tmdb_id"
                    )):
                result = app._reconcile_library_files()
            snapshot = store.snapshot()
            record = snapshot["files"][app._norm(str(movie))]

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(record["display_provider"], "tmdb")
        self.assertEqual(snapshot["tmdb_movies"]["348"]["poster_url"], "alien.jpg")

    def test_filename_authority_does_not_report_unmatched_file_as_identified(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Unknown.Movie.2026.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "filename"})

            with patch("app._file_copy_is_stable", return_value=True):
                result = app._reconcile_library_files()
            record = store.snapshot()["files"][app._norm(str(movie))]

        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["review"], 1)
        self.assertEqual(record["metadata_status"], "unmatched")

    def test_plex_authority_falls_back_to_tmdb_when_plex_has_not_indexed_file(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "plex"})
            candidate = {
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "match_source": "auto_tmdb",
            }

            with patch("app._file_copy_is_stable", return_value=True), \
                    patch("app._resolve_tmdb_identity", return_value=app._identity_resolution(
                        "accepted", candidate, {"status": "accepted", "outcome": "accepted"}, source="auto_tmdb"
                    )):
                outcome = app._reconcile_library_path(str(movie), "plex", store=store)
            record = store.snapshot()["files"][app._norm(str(movie))]

        self.assertEqual(outcome, "matched")
        self.assertEqual(record["identity_status"], "accepted")
        self.assertEqual(record["tmdb_id"], "348")
        self.assertEqual(record["display_provider"], "tmdb")

    def test_inventory_bootstrap_processes_historical_unrecorded_files(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Historical.Movie.1990.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})

            with patch("app._library_inventory_bootstrap_cutoff", return_value=1000), \
                    patch("app.os.path.getctime", return_value=500), \
                    patch("app._reconcile_library_path") as reconcile_path:
                result = app._reconcile_library_files()
            inventory = store.get_library_inventory()

        self.assertEqual(result["checked"], 1)
        reconcile_path.assert_called_once()
        self.assertIn(app._norm(str(movie)), inventory)

    def test_inventory_entry_without_authoritative_record_is_reconciled(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Recovered.Movie.1998.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            store.save_library_inventory({
                app._norm(str(movie)): {
                    "path": str(movie),
                    "size": movie.stat().st_size,
                    "modified_time": movie.stat().st_mtime,
                },
            })

            with patch("app._reconcile_library_path", return_value="matched") as reconcile_path:
                result = app._reconcile_library_files()

        self.assertEqual(result["checked"], 1)
        reconcile_path.assert_called_once()

    def test_ordinary_startup_skips_full_scan_when_inventory_is_current(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_library_inventory({})
            before_generation = store.catalog.generation('media')

            with patch("app._iter_video_files") as iter_files:
                first = app._startup_reconcile_decision()
                second = app._startup_reconcile_decision()
            after_generation = store.catalog.generation('media')

        self.assertFalse(first["run"])
        self.assertEqual(first["reason"], "bootstrapped_existing_inventory")
        self.assertFalse(second["run"])
        self.assertEqual(second["reason"], "current_inventory")
        self.assertEqual(after_generation, before_generation)
        iter_files.assert_not_called()

    def test_startup_requests_scan_when_library_root_revision_changes(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_library_inventory({})
            self.assertFalse(app._startup_reconcile_decision()["run"])
            (Path(movies_tmp) / "New.Movie.2026.mkv").write_bytes(b"movie")

            decision = app._startup_reconcile_decision()

        self.assertTrue(decision["run"])
        self.assertEqual(decision["reason"], "library_root_changed")

    def test_startup_runs_detail_backfill_when_inventory_is_current_but_tmdb_snapshot_is_stale(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_tmdb_metadata({
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "plot": "Stored detail.",
                "cast": [],
                "directors": [],
            })
            store.update_file_record(str(movie), {
                "identity_status": "accepted",
                "identity_title": "Alien",
                "identity_year": "1979",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "348",
            })
            store.save_library_inventory({
                app._norm(str(movie)): {
                    "path": str(movie),
                    "size": movie.stat().st_size,
                    "modified_time": movie.stat().st_mtime,
                },
            })
            store.catalog.set_operational_meta("last_library_root_signature", app._library_root_signature())
            store.catalog.set_operational_meta("last_library_reconcile_generation", store.catalog.generation("media"))

            decision = app._startup_reconcile_decision()

        self.assertTrue(decision["run"])
        self.assertFalse(decision["run_inventory"])
        self.assertTrue(decision["run_detail_backfill"])
        self.assertEqual(decision["reason"], "metadata_contract_upgrade")
        self.assertEqual(decision["detail_backfill_remaining"], 1)

    def test_detail_backfill_updates_each_tmdb_snapshot_and_is_resumable(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_tmdb_metadata({
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "plot": "Stored detail.",
                "cast": [],
                "directors": [],
            })
            store.update_file_record(str(movie), {
                "identity_status": "accepted",
                "identity_title": "Alien",
                "identity_year": "1979",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "348",
            })
            completed = {
                **store.get_tmdb_metadata("348"),
                "writers": [{"id": "1", "name": "Dan O'Bannon", "job": "Writer"}],
                "certification": "R",
                "keywords": ["space", "alien"],
            }

            with patch("app._metadata_store", return_value=store), patch(
                    "app._fetch_tmdb_metadata_by_id",
                    side_effect=lambda *args, **kwargs: store.save_tmdb_metadata(completed),
            ) as fetch:
                result = app._run_tmdb_detail_contract_backfill()

            details = app._relational_canonical_for_path(str(movie), store=store)

        fetch.assert_called_once_with("348", store=store, refresh=False)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(details["certification"], "R")
        self.assertEqual(details["writers"][0]["name"], "Dan O'Bannon")
        self.assertEqual(details["keywords"], ["space", "alien"])

    def test_explicit_reconcile_bypasses_startup_skip_decision(self):
        with patch("app._startup_reconcile_decision") as decision, \
                patch("app.threading.Thread") as thread:
            app._library_reconcile_thread = None
            state = app._start_library_reconcile(force=True)
            app._library_reconcile_thread = None

        decision.assert_not_called()
        thread.assert_called_once()
        self.assertEqual(state["reason"], "explicit")
        self.assertFalse(state["skipped"])

    def test_stale_review_record_is_retried_after_decision_rule_upgrade(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Cujo.1983.1080p.BluRay.x264.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            fingerprint = {
                "path": str(movie),
                "size": movie.stat().st_size,
                "modified_time": movie.stat().st_mtime,
            }
            store.save_library_inventory({app._norm(str(movie)): fingerprint})
            store.update_file_record(str(movie), {
                "metadata_status": "needs_review",
                "identity_status": "review",
                "metadata_accepted": False,
                "candidate_tmdb_id": "10489",
                "candidate_title": "Cujo",
                "candidate_year": "1983",
                "size": fingerprint["size"],
                "modified_time": fingerprint["modified_time"],
            })
            candidate = {
                "tmdb_id": "10489",
                "title": "Cujo",
                "year": "1983",
                "match_source": "auto_tmdb",
            }

            with patch("app._file_copy_is_stable", return_value=True), \
                    patch("app._resolve_tmdb_identity", return_value=app._identity_resolution(
                        "accepted", candidate, {"status": "accepted", "outcome": "accepted"}, source="auto_tmdb"
                    )):
                result = app._reconcile_library_files()
            record = store.snapshot()["files"][app._norm(str(movie))]

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["matched"], 1)
        self.assertEqual(record["metadata_status"], "accepted")
        self.assertEqual(record["tmdb_id"], "10489")
        self.assertEqual(record["identity_decision_version"], app.IDENTITY_DECISION_VERSION)

    def test_version_three_review_record_is_retried_after_subtitle_rule_upgrade(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Black Box 2026 1080p WEB-DL HEVC x265 5.1 BONE.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            fingerprint = {
                "path": str(movie),
                "size": movie.stat().st_size,
                "modified_time": movie.stat().st_mtime,
            }
            store.save_library_inventory({app._norm(str(movie)): fingerprint})
            store.update_file_record(str(movie), {
                "metadata_status": "needs_review",
                "identity_status": "review",
                "metadata_accepted": False,
                "identity_decision_version": 3,
                "candidate_tmdb_id": "1321008",
                "candidate_title": "Black Box (Flight 298)",
                "candidate_year": "2026",
                "size": fingerprint["size"],
                "modified_time": fingerprint["modified_time"],
            })

            with patch("app._reconcile_library_path", return_value="matched") as reconcile_path:
                result = app._reconcile_library_files()

        self.assertEqual(result["checked"], 1)
        reconcile_path.assert_called_once()

    def test_current_review_record_is_not_retried_on_every_normal_reconcile(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Actually.Ambiguous.2026.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            fingerprint = {
                "path": str(movie),
                "size": movie.stat().st_size,
                "modified_time": movie.stat().st_mtime,
            }
            store.save_library_inventory({app._norm(str(movie)): fingerprint})
            store.update_file_record(str(movie), {
                "metadata_status": "needs_review",
                "identity_status": "review",
                "metadata_accepted": False,
                "identity_decision_version": app.IDENTITY_DECISION_VERSION,
                "candidate_tmdb_id": "123",
                "candidate_title": "Actually Ambiguous",
                "candidate_year": "2026",
                "size": fingerprint["size"],
                "modified_time": fingerprint["modified_time"],
            })

            with patch("app._reconcile_library_path") as reconcile_path:
                result = app._reconcile_library_files()

        self.assertEqual(result["checked"], 0)
        reconcile_path.assert_not_called()

    def test_current_review_record_is_retried_when_provider_evidence_changes(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Obsession.2025.1080p.WEBRip.x264.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            fingerprint = {
                "path": str(movie),
                "size": movie.stat().st_size,
                "modified_time": movie.stat().st_mtime,
            }
            store.save_library_inventory({app._norm(str(movie)): fingerprint})
            store.update_file_record(str(movie), {
                "metadata_status": "needs_review",
                "identity_status": "review",
                "metadata_accepted": False,
                "identity_decision_version": app.IDENTITY_DECISION_VERSION,
                "identity_evidence_fingerprint": "filename:obsession:2025",
                "candidate_tmdb_id": "1436161",
                "candidate_title": "Obsession",
                "candidate_year": "2025",
                "size": fingerprint["size"],
                "modified_time": fingerprint["modified_time"],
            })
            app._plex_cache[app._norm(str(movie))] = {
                "plex_title": "Obsession",
                "plex_year": "2026",
                "tmdb_id": "1339713",
                "imdb_id": "tt3000000",
                "plex_guid": "plex://movie/obsession",
            }

            with patch("app._reconcile_library_path", return_value="matched") as reconcile_path:
                result = app._reconcile_library_files()

        self.assertEqual(result["checked"], 1)
        reconcile_path.assert_called_once()

    def test_inventory_bootstrap_processes_files_newer_than_metadata_checkpoint(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "New.Movie.2026.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})

            with patch("app._library_inventory_bootstrap_cutoff", return_value=1000), \
                    patch("app.os.path.getctime", return_value=1500), \
                    patch("app._reconcile_library_path", return_value="matched") as reconcile_path:
                result = app._reconcile_library_files()

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["matched"], 1)
        reconcile_path.assert_called_once()

    def test_ambiguous_new_file_remains_unmatched(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Ambiguous.Movie.2026.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            candidate = {"tmdb_id": "123", "title": "Ambiguous Movie", "year": "2025"}

            with patch("app._file_copy_is_stable", return_value=True), \
                    patch("app._resolve_tmdb_identity", return_value=app._identity_resolution(
                        "ambiguous",
                        candidate,
                        {"status": "review", "outcome": "ambiguous", "reasons": ["multiple releases are plausible"]},
                        source="candidate_tmdb",
                    )):
                outcome = app._reconcile_library_path(str(movie), "tmdb", store=store)
            record = store.snapshot()["files"][store._key(movie)]

        self.assertEqual(outcome, "review")
        self.assertEqual(record["identity_status"], "unmatched")
        self.assertEqual(record["metadata_status"], "unmatched")
        self.assertFalse(record["metadata_accepted"])
        self.assertEqual(record["candidate_tmdb_id"], "123")
        self.assertEqual(record["identity_decision_outcome"], "ambiguous")

    def test_contradicted_new_file_is_blocked_as_conflict(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Conflicted.Movie.2026.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            candidate = {"tmdb_id": "456", "title": "Another Movie", "year": "2026"}

            with patch("app._file_copy_is_stable", return_value=True), \
                    patch("app._resolve_tmdb_identity", return_value=app._identity_resolution(
                        "contradicted",
                        candidate,
                        {"status": "conflict", "outcome": "contradicted", "reasons": ["provider ID conflict"]},
                        source="candidate_tmdb",
                    )):
                outcome = app._reconcile_library_path(str(movie), "tmdb", store=store)
            record = store.snapshot()["files"][store._key(movie)]

        self.assertEqual(outcome, "review")
        self.assertEqual(record["identity_status"], "conflict")
        self.assertEqual(record["metadata_status"], "conflict")
        self.assertFalse(record["metadata_accepted"])
        self.assertEqual(record["candidate_tmdb_id"], "456")
        self.assertEqual(record["identity_decision_outcome"], "contradicted")

    def test_changed_automatic_identity_is_revalidated_incrementally(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Alien.1979.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            store.save_tmdb_metadata({"tmdb_id": "348", "title": "Alien", "year": "1979"})
            facts = app._metadata_file_facts(str(movie))
            store.update_file_record(str(movie), {
                **facts,
                "identity_status": "accepted",
                "identity_title": "Alien",
                "identity_year": "1979",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "display_provider": "tmdb",
                "tmdb_id": "348",
                "decision_origin": app.DECISION_ORIGIN_LIBRARY_RECONCILE,
                "identity_evidence_fingerprint": app._identity_evidence_fingerprint(str(movie), facts, {}),
                "identity_evidence_changed": True,
            })

            with patch("app._file_copy_is_stable", return_value=True), \
                    patch("app._revalidate_accepted_identity", return_value="matched") as revalidate:
                result = app._reconcile_library_files()

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["matched"], 1)
        revalidate.assert_called_once()

    def test_changed_manual_identity_is_never_revalidated(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Wrong.Name.1979.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.save_authority_state({"active_provider": "tmdb"})
            store.apply_tmdb_match(str(movie), {
                "tmdb_id": "348",
                "title": "Alien",
                "year": "1979",
                "plot": "Stored detail.",
                "cast": [],
                "directors": [],
            }, facts=app._metadata_file_facts(str(movie)))
            store.update_file_record(str(movie), {"identity_evidence_changed": True})

            with patch("app._revalidate_accepted_identity") as revalidate:
                result = app._reconcile_library_files()
            record = store.snapshot()["files"][store._key(movie)]

        self.assertEqual(result["checked"], 0)
        revalidate.assert_not_called()
        self.assertEqual(record["identity_status"], "accepted")
        self.assertEqual(record["tmdb_id"], "348")
        self.assertTrue(record["manual_lock"])

    def test_revalidation_conflict_preserves_old_id_without_accepting_replacement(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Splice.2009.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            facts = app._metadata_file_facts(str(movie))
            store.update_file_record(str(movie), {
                **facts,
                "identity_status": "accepted",
                "identity_title": "SPLICE",
                "identity_year": "2009",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "tmdb_id": "1629337",
                "decision_origin": app.DECISION_ORIGIN_LIBRARY_RECONCILE,
            })
            current = store.snapshot()["files"][store._key(movie)]

            with patch("app._process_identity_audit_path", return_value={
                "outcome": "actionable",
                "candidate": {"tmdb_id": "37707", "title": "Splice", "year": "2010"},
                "reasons": ["independent provider content contradicts the accepted identity"],
            }):
                outcome = app._revalidate_accepted_identity(
                    str(movie), "tmdb", store, current, facts, {}
                )
            record = store.snapshot()["files"][store._key(movie)]

        self.assertEqual(outcome, "review")
        self.assertEqual(record["identity_status"], "conflict")
        self.assertFalse(record["metadata_accepted"])
        self.assertEqual(record["tmdb_id"], "1629337")
        self.assertEqual(record["candidate_tmdb_id"], "37707")

    def test_revalidation_ambiguity_demotes_automatic_identity_to_unmatched(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Shared.Title.2026.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            facts = app._metadata_file_facts(str(movie))
            store.update_file_record(str(movie), {
                **facts,
                "identity_status": "accepted",
                "identity_title": "Shared Title",
                "identity_year": "2026",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "tmdb_id": "111",
                "decision_origin": app.DECISION_ORIGIN_LIBRARY_RECONCILE,
            })
            current = store.snapshot()["files"][store._key(movie)]

            with patch("app._process_identity_audit_path", return_value={
                "outcome": "ambiguous",
                "candidate": {"tmdb_id": "222", "title": "Shared Title", "year": "2026"},
                "reasons": ["multiple provider identities are plausible"],
            }):
                outcome = app._revalidate_accepted_identity(
                    str(movie), "tmdb", store, current, facts, {}
                )
            record = store.snapshot()["files"][store._key(movie)]

        self.assertEqual(outcome, "review")
        self.assertEqual(record["identity_status"], "unmatched")
        self.assertEqual(record["metadata_status"], "unmatched")
        self.assertFalse(record["metadata_accepted"])
        self.assertEqual(record["tmdb_id"], "111")
        self.assertEqual(record["identity_decision_outcome"], "ambiguous")

    def test_manual_rescan_runs_reconcile_before_returning_library(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Scent.of.a.Woman.1992.1080p.mkv"
            movie.write_bytes(b"movie")
            self.configure(movies_tmp, data_tmp)
            with patch("app._reconcile_library_files", return_value={
                "checked": 1, "matched": 1, "review": 0, "pending": 0, "failed": 0
            }) as reconcile:
                response = app.app.test_client().get("/api/library?force_scan=1")

        self.assertEqual(response.status_code, 200)
        reconcile.assert_called_once_with(force_unresolved=True)
        self.assertEqual(response.get_json()["metadata_matched"], 1)


if __name__ == "__main__":
    unittest.main()
