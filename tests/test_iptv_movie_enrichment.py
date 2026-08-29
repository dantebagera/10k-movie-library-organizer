import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from services.iptv_enrichment_worker import run_worker
from services.iptv_metadata_settings import IPTVMetadataSettings
from services.iptv_movie_service import IPTVMovieService
from services.iptv_movie_store import IPTVMovieStore, source_key
from services.iptv_provider_manager import IPTVProviderManager
from services.iptv_routes import register_iptv_routes
from services.iptv_tmdb import (
    IPTVTMDBClient,
    IPTVTMDBError,
    choose_automatic_match,
    clean_provider_title,
    normalize_tmdb_movie,
    provider_id_matches,
)
from tests.iptv_movie_fixtures import (
    FakeHTTPResponse,
    FakeTMDBClient,
    create_raw_service,
    tmdb_payload,
)


PROVIDER_A = "a" * 32
PROVIDER_B = "b" * 32


class IPTVMetadataSettingsTests(unittest.TestCase):
    def test_settings_are_lazy_atomic_blank_preserving_and_redacted(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = IPTVMetadataSettings(temporary)
            self.assertFalse(settings.path.exists())
            self.assertEqual(settings.public(), {
                "tmdb_configured": False,
                "credential_type": "bearer",
                "ollama_enabled": False,
                "ollama_url": "http://127.0.0.1:11434",
                "ollama_model": "",
            })

            saved = settings.save("fixture-secret-value", "bearer")
            before = settings.path.read_bytes()
            preserved = settings.save("", "bearer")
            redacted = settings.redact(
                "Authorization: Bearer fixture-secret-value api_key=fixture-secret-value"
            )

            self.assertEqual(saved, {
                "tmdb_configured": True,
                "credential_type": "bearer",
                "ollama_enabled": False,
                "ollama_url": "http://127.0.0.1:11434",
                "ollama_model": "",
            })
            self.assertEqual(preserved, saved)
            self.assertEqual(settings.path.read_bytes(), before)
            self.assertNotIn("fixture-secret-value", redacted)
            self.assertNotIn('"credential":', json.dumps(saved))
            self.assertEqual(settings.save(clear=True)["tmdb_configured"], False)


class IPTVMovieStoreTests(unittest.TestCase):
    def test_movie_store_is_lazy_and_live_or_series_access_never_creates_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A)
            settings = IPTVMetadataSettings(temporary)
            movie_service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            try:
                self.assertFalse(movie_service.database_path.exists())
                self.assertEqual(raw.list_items("live")["total"], 1)
                self.assertEqual(raw.list_items("series")["total"], 1)
                self.assertFalse(movie_service.database_path.exists())
                first = movie_service.list_movies()
                self.assertEqual(first["total"], 0)
                self.assertIn(first["projection"]["state"], {"not-started", "running"})
                movie_service.start_projection(wait=True)
                self.assertEqual(movie_service.list_movies()["total"], 1)
                self.assertTrue(movie_service.database_path.exists())
            finally:
                raw.close()

    def test_raw_projection_uses_bounded_batches(self):
        rows = [
            {"stream_id": str(index), "category_id": "movies-a", "name": f"Movie {index}"}
            for index in range(1, 8)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A, movie_rows=rows)
            settings = IPTVMetadataSettings(temporary)
            movie_service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            movie_service.PROJECTION_BATCH_SIZE = 2
            store = movie_service.store
            try:
                with patch.object(store, "project_source_batch", wraps=store.project_source_batch) as batches:
                    movie_service.start_projection(wait=True)
                    result = movie_service.list_movies(page_size=20)
                self.assertEqual(result["total"], 7)
                self.assertEqual([len(call.args[0]) for call in batches.call_args_list], [2, 2, 2, 1])
            finally:
                raw.close()

    def test_same_generation_projection_completion_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IPTVMovieStore(Path(temporary) / PROVIDER_A, PROVIDER_A)
            store.begin_projection(7)
            store.project_source_batch([{"item_id": "1", "name": "Race-safe Movie"}], 7)
            store.finish_projection(7)
            store.finish_projection(7)
            self.assertEqual(store.source_generation(), 7)

    def test_projection_derives_provider_year_from_spaced_title_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IPTVMovieStore(Path(temporary) / PROVIDER_A, PROVIDER_A)
            store.project_sources([{"item_id": "1", "name": "ssss ( 2026 )"}], 1)
            card = store.list_movies()["items"][0]
            self.assertEqual(card["provider_year"], 2026)

    def test_provider_path_confinement_and_independent_same_tmdb_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "iptv" / "providers"
            first = IPTVMovieStore(base / PROVIDER_A, PROVIDER_A)
            second = IPTVMovieStore(base / PROVIDER_B, PROVIDER_B)
            with self.assertRaisesRegex(ValueError, "provider root"):
                IPTVMovieStore(base / PROVIDER_A, PROVIDER_B)
            first.project_sources([{"item_id": "1", "name": "First Movie", "year": 2024}], 1)
            second.project_sources([{"item_id": "1", "name": "Second Movie", "year": 2024}], 1)
            first.apply_classification([source_key("1")], "film", method="test-fixture", confidence=1)
            second.apply_classification([source_key("1")], "film", method="test-fixture", confidence=1)
            snapshot = normalize_tmdb_movie(tmdb_payload(550, "Shared Identity", 2024))
            first.apply_match(f"source:{source_key('1')}", snapshot)
            second.apply_match(f"source:{source_key('1')}", snapshot)

            self.assertEqual(first.list_movies({"view": "cp"})["items"][0]["movie_key"], "tmdb:550")
            self.assertEqual(second.list_movies({"view": "cp"})["items"][0]["movie_key"], "tmdb:550")
            self.assertNotEqual(first.database_path, second.database_path)
            self.assertEqual(first.integrity(), "ok")
            self.assertEqual(second.integrity(), "ok")

    def test_arabic_localization_repair_preserves_the_accepted_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A)
            settings = IPTVMetadataSettings(temporary)
            movie_service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            try:
                movie_service.start_projection(wait=True)
                base_payload = tmdb_payload(550, "Arabic transliteration", 2024)
                base_payload.update({
                    "original_language": "ar",
                    "original_title": "\u0639\u0646\u0648\u0627\u0646 \u0639\u0631\u0628\u064a",
                    "overview": "English fallback plot",
                    "credits": {
                        "crew": [{"id": 1, "name": "English Director", "job": "Director", "profile_path": "/director.jpg"}],
                        "cast": [{"id": 3, "name": "English Actor", "character": "Lead", "profile_path": "/actor.jpg"}],
                    },
                })
                movie_service.store.apply_match(
                    f"source:{source_key('10')}",
                    normalize_tmdb_movie(base_payload),
                    manual=True,
                )
                localized_payload = {
                    **base_payload,
                    "title": "\u0639\u0646\u0648\u0627\u0646 \u0639\u0631\u0628\u064a",
                    "overview": "",
                    "credits": {
                        "crew": [{"id": 1, "name": "\u0645\u062e\u0631\u062c \u0639\u0631\u0628\u064a", "job": "Director"}],
                        "cast": [{"id": 3, "name": "\u0645\u0645\u062b\u0644 \u0639\u0631\u0628\u064a", "character": "\u0627\u0644\u0628\u0637\u0644"}],
                    },
                }
                client = FakeTMDBClient(movies={550: localized_payload})
                movie_service.tmdb_client_factory = lambda: client
                transient = movie_service.localization("tmdb:550", "ar-SA")
                self.assertEqual(transient["directors"][0]["name"], "\u0645\u062e\u0631\u062c \u0639\u0631\u0628\u064a")
                self.assertTrue(transient["directors"][0]["profile_url"].endswith("/director.jpg"))
                self.assertEqual(transient["cast"][0]["name"], "\u0645\u0645\u062b\u0644 \u0639\u0631\u0628\u064a")
                self.assertTrue(transient["cast"][0]["profile_url"].endswith("/actor.jpg"))
                self.assertEqual(movie_service.store.missing_arabic_localizations(), [550])
                result = movie_service.repair_missing_arabic_localizations(
                    tmdb_client=client
                )

                self.assertEqual(result, {"requested": 1, "saved": [550], "failed": []})
                self.assertEqual(movie_service.store.missing_arabic_localizations(), [])
                detail = movie_service.movie("tmdb:550")
                self.assertEqual(detail["name"], "\u0639\u0646\u0648\u0627\u0646 \u0639\u0631\u0628\u064a")
                self.assertEqual(detail["plot"], "English fallback plot")
                with movie_service.store.connection() as connection:
                    match = connection.execute(
                        "SELECT state,manual_lock,tmdb_id FROM source_matches WHERE source_key=?",
                        (source_key("10"),),
                    ).fetchone()
                self.assertEqual(tuple(match), ("matched-manual", 1, 550))
            finally:
                raw.close()

    def test_raw_fallback_grouping_filters_paging_and_list_membership_survive_merge(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "iptv" / "providers" / PROVIDER_A
            store = IPTVMovieStore(root, PROVIDER_A)
            rows = [
                {"item_id": "1", "category_id": "a", "playlist_name": "Playlist A", "name": "Same Movie (2024) 1080p", "year": 2024, "position": 1},
                {"item_id": "2", "category_id": "b", "playlist_name": "Playlist B", "name": "Same Movie (2024) 4K", "year": 2024, "position": 2},
                {"item_id": "3", "category_id": "a", "playlist_name": "Playlist A", "name": "Other Movie", "position": 3},
            ]
            store.project_sources(rows, 1, memberships=[
                {"list_id": "list-a", "source_id": "1", "position": 2, "added_at": 20},
                {"list_id": "list-a", "source_id": "2", "position": 1, "added_at": 10},
            ])
            fallback = store.list_movies({"playlist_id": "a"}, page=1, page_size=1)
            self.assertEqual(fallback["total"], 2)
            self.assertEqual(len(fallback["items"]), 1)
            self.assertFalse(fallback["items"][0]["matched"])

            snapshot = normalize_tmdb_movie(tmdb_payload(550, "Same Movie", 2024))
            store.apply_classification(
                [source_key("1"), source_key("2")],
                "film",
                method="test-fixture",
                confidence=1,
            )
            store.apply_match(f"source:{source_key('1')}", snapshot)
            store.apply_match(f"source:{source_key('2')}", snapshot)
            grouped = store.list_movies({"view": "cp", "list_id": "list-a", "genre_id": 18})

            self.assertEqual(grouped["total"], 1)
            self.assertEqual(grouped["items"][0]["source_count"], 2)
            self.assertEqual(grouped["items"][0]["movie_key"], "tmdb:550")
            with store.connection() as connection:
                membership = connection.execute(
                    "SELECT position,added_at FROM movie_list_memberships WHERE list_id='list-a'"
                ).fetchall()
            self.assertEqual([(row[0], row[1]) for row in membership], [(1, 10.0)])

            store.project_sources(rows[:1] + rows[2:], 2)
            retained = store.list_movies({"view": "cp", "list_id": "list-a"})
            self.assertEqual(retained["items"][0]["source_count"], 1)

    def test_manual_match_lock_correction_and_remove_are_transactional(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IPTVMovieStore(Path(temporary) / PROVIDER_A, PROVIDER_A)
            store.project_sources([{"item_id": "1", "name": "Manual Movie"}], 1)
            first = normalize_tmdb_movie(tmdb_payload(100, "First Match", 2020))
            second = normalize_tmdb_movie(tmdb_payload(200, "Corrected Match", 2021))
            key = f"source:{source_key('1')}"
            matched = store.apply_match(key, first, manual=True)
            corrected = store.apply_match(matched, second, manual=True)
            with store.connection() as connection:
                row = connection.execute("SELECT state,tmdb_id,manual_lock FROM source_matches").fetchone()
            self.assertEqual((row[0], row[1], row[2]), ("matched-manual", 200, 1))
            store.remove_match(corrected)
            with store.connection() as connection:
                row = connection.execute("SELECT state,tmdb_id,manual_lock FROM source_matches").fetchone()
            self.assertEqual((row[0], row[1], row[2]), ("unmatched", None, 1))
            store.remove_match(key, reprocess=True)
            with store.connection() as connection:
                row = connection.execute("SELECT state,manual_lock FROM source_matches").fetchone()
            self.assertEqual((row[0], row[1]), ("unprocessed", 0))


class IPTVMatchEngineTests(unittest.TestCase):
    def test_provider_id_validation_strict_matching_and_credible_rival_rejection(self):
        candidate = tmdb_payload(550, "The Exact Movie", 2024)
        valid, score = provider_id_matches("The Exact Movie (2024)", 2024, candidate)
        invalid, _ = provider_id_matches("A Different Movie (2024)", 2024, candidate)
        accepted = choose_automatic_match("The Exact Movie (2024)", 2024, [candidate])
        rival = tmdb_payload(551, "The Exact Movie", 2024)
        ambiguous = choose_automatic_match("The Exact Movie (2024)", 2024, [candidate, rival])

        self.assertTrue(valid)
        self.assertGreaterEqual(score, 94)
        self.assertFalse(invalid)
        self.assertEqual(accepted["state"], "matched-auto")
        self.assertEqual(ambiguous["state"], "ambiguous")

    def test_spaced_year_alternative_titles_and_provider_translation_suffixes_are_validated(self):
        self.assertEqual(clean_provider_title("ssss ( 2026 ) 4K"), "ssss")
        alternative = tmdb_payload(700, "International Title", 2026)
        alternative["alternative_titles"] = {
            "titles": [{"iso_3166_1": "US", "title": "ssss", "type": ""}]
        }
        translated = tmdb_payload(701, "A Loud House Christmas: The Movie", 2025)

        alternative_valid, alternative_score = provider_id_matches(
            "ssss ( 2026 )", 2026, alternative
        )
        translated_valid, translated_score = provider_id_matches(
            "A Loud House Christmas: The Movie (2025) مدبلج عربي", 2025, translated
        )
        unsafe_prefix, _ = provider_id_matches(
            "A Loud House Christmas: The Movie Part Two (2025)", 2025, translated
        )

        self.assertTrue(alternative_valid)
        self.assertGreaterEqual(alternative_score, 94)
        self.assertTrue(translated_valid)
        self.assertGreaterEqual(translated_score, 94)
        self.assertFalse(unsafe_prefix)

    def test_manual_search_separates_title_year_before_tmdb_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(
                temporary,
                PROVIDER_A,
                movie_rows=[{"stream_id": "10", "category_id": "movies-a", "name": "ssss ( 2026 )"}],
            )
            settings = IPTVMetadataSettings(temporary)
            captured = {}

            class CapturingClient(FakeTMDBClient):
                def search_movies(self, title, year=0, page=1):
                    captured.update({"title": title, "year": year, "page": page})
                    return [tmdb_payload(700, "ssss", 2026)]

            service = IPTVMovieService(
                raw.root, PROVIDER_A, raw, settings,
                tmdb_client_factory=lambda: CapturingClient(),
            )
            try:
                service.start_projection(wait=True)
                card = service.list_movies({"view": "cp"})["items"][0]
                result = service.manual_search(card["movie_key"], "ssss ( 2026 )", "")
                self.assertEqual(captured, {"title": "ssss", "year": 2026, "page": 1})
                self.assertEqual(result["year"], 2026)
            finally:
                raw.close()

    def test_automatic_enrichment_prefers_valid_provider_id_and_preserves_raw_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A)
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-token", "bearer")
            client = FakeTMDBClient({550: tmdb_payload(550, "Fixture Movie", 2024)})
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings, tmdb_client_factory=lambda: client)
            def detail(kind, item_id):
                value = raw.store.get_item(kind, item_id, provider_key=raw.provider_key())
                value.update({"name": "Fixture Movie", "year": 2024, "tmdb_id": 550})
                return value

            try:
                service.ensure_projected()
                service.store.apply_classification(
                    [source_key("10")], "film", method="test-fixture", confidence=1
                )
                with patch.object(raw, "enrichment_movie_detail", side_effect=lambda item_id: detail("movie", item_id)):
                    state = service.enrich_source(source_key("10"))
                card = service.list_movies({"view": "cp"})["items"][0]
                self.assertEqual(state, "matched-auto")
                self.assertEqual(card["movie_key"], "tmdb:550")
                self.assertEqual(card["item_id"], "10")
                self.assertEqual(card["title"], "Fixture Movie")
            finally:
                raw.close()

    def test_full_provider_release_date_is_normalized_before_recording_match_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A)
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-token", "bearer")
            candidate = tmdb_payload(550, "Fixture Movie", 2024)
            client = FakeTMDBClient(search_results=[candidate])
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            detail = raw.store.get_item("movie", "10", provider_key=raw.provider_key())
            detail.update({"name": "Fixture Movie", "year": "2024-02-03", "tmdb_id": ""})
            try:
                service.ensure_projected()
                service.store.apply_classification(
                    [source_key("10")], "film", method="test-fixture", confidence=1
                )
                with patch.object(raw, "enrichment_movie_detail", return_value=detail):
                    self.assertEqual(
                        service.enrich_source(source_key("10"), tmdb_client=client),
                        "matched-auto",
                    )
                with service.store.connection() as connection:
                    evidence = json.loads(
                        connection.execute("SELECT evidence_json FROM source_matches").fetchone()[0]
                    )
                self.assertEqual(evidence["fallback_search"]["parsed"]["year"], 2024)
            finally:
                raw.close()


class IPTVTMDBClientTests(unittest.TestCase):
    def test_bearer_validation_keeps_secret_out_of_url_and_public_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-bearer-secret", "bearer")
            captured = {}

            def open_url(request, timeout=0):
                captured["url"] = request.full_url
                captured["authorization"] = request.headers.get("Authorization")
                captured["timeout"] = timeout
                return FakeHTTPResponse({"images": {"base_url": "https://images.example"}})

            client = IPTVTMDBClient(settings, open_url=open_url)
            self.assertTrue(client.validate())
            self.assertNotIn("fixture-bearer-secret", captured["url"])
            self.assertEqual(captured["authorization"], "Bearer fixture-bearer-secret")

    def test_401_429_timeout_and_5xx_are_typed_without_secret_exposure(self):
        with tempfile.TemporaryDirectory() as temporary:
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-api-secret", "api_key")

            def failure(status, headers=None):
                def open_url(request, timeout=0):
                    raise urllib.error.HTTPError(request.full_url, status, "failed", headers or {}, None)
                return open_url

            for status, retryable in ((401, False), (429, True), (500, True)):
                client = IPTVTMDBClient(settings, open_url=failure(status, {"Retry-After": "3"}))
                with self.assertRaises(IPTVTMDBError) as raised:
                    client.validate()
                self.assertEqual(raised.exception.status, status)
                self.assertEqual(raised.exception.retryable, retryable)
                self.assertNotIn("fixture-api-secret", str(raised.exception))

            client = IPTVTMDBClient(settings, open_url=lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError()))
            with self.assertRaises(IPTVTMDBError) as raised:
                client.validate()
            self.assertTrue(raised.exception.retryable)


class IPTVWorkerTests(unittest.TestCase):
    def test_repeated_start_cannot_replace_a_live_or_exiting_worker_lease(self):
        class ProcessFixture:
            return_code = None

            def poll(self):
                return self.return_code

        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A)
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-token", "bearer")
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            process = ProcessFixture()
            try:
                service.ensure_projected()
                first_token = service.store.prepare_enrichment(consent=True)
                service.store.worker_started(12345, first_token)
                with service._process_lock:
                    service._processes[PROVIDER_A] = process

                repeated = service.start_enrichment(consent=True)
                self.assertEqual(repeated["state"], "running")
                self.assertEqual(service.store.current_worker_token(), first_token)

                service.store.cancel_enrichment()
                with self.assertRaisesRegex(RuntimeError, "still shutting down"):
                    service.start_enrichment(consent=True)
                self.assertEqual(service.store.current_worker_token(), first_token)
            finally:
                process.return_code = 0
                with service._process_lock:
                    service._processes.pop(PROVIDER_A, None)
                service.close()
                raw.close()

    def test_worker_has_a_hard_source_budget_and_does_not_requeue_uncertain_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            rows = [
                {"stream_id": str(index), "category_id": "movies-a", "name": f"Movie {index}"}
                for index in range(1, 5)
            ]
            raw = create_raw_service(temporary, PROVIDER_A, movie_rows=rows)
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-token", "bearer")
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            try:
                service.ensure_projected()
                service.store.apply_classification(
                    [source_key(str(index)) for index in range(1, 5)],
                    "film",
                    method="test-fixture",
                    confidence=1,
                )
                service.store.prepare_enrichment(consent=True, diagnostic_limit=2)
                with patch.object(service, "enrich_source", return_value="unmatched") as enrich:
                    self.assertEqual(run_worker(service, max_jobs=2), "paused")
                self.assertEqual(enrich.call_count, 2)
                self.assertEqual(service.enrichment_status()["queue"]["pending"], 2)

                with service.store.connection(immediate=True) as connection:
                    connection.execute("UPDATE source_matches SET state='ambiguous'")
                    connection.execute("DELETE FROM enrichment_queue")
                service.store.prepare_enrichment(consent=True)
                with service.store.connection() as connection:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM enrichment_queue").fetchone()[0],
                        0,
                    )
            finally:
                raw.close()

    def test_worker_pause_resume_cancel_and_crash_recovery_state_are_provider_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A)
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-token", "bearer")
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings, tmdb_client_factory=lambda: FakeTMDBClient())
            try:
                service.ensure_projected()
                service.store.prepare_enrichment(consent=True)
                service.store.worker_command("pause")
                self.assertEqual(run_worker(service), "paused")
                service.store.worker_command("run")
                with patch.object(service, "enrich_source", return_value="unmatched"):
                    self.assertEqual(run_worker(service, max_jobs=1), "paused")
                service.store.worker_command("cancel")
                self.assertEqual(service.enrichment_status()["state"], "cancelled")
                service.store.prepare_enrichment(consent=True)
                service.store.worker_started(999999)
                with service.store.connection(immediate=True) as connection:
                    connection.execute("UPDATE worker_lease SET lease_expires_at=0")
                recovered = service.enrichment_status()
                self.assertEqual(recovered["state"], "awaiting-continuation")
                self.assertTrue(recovered["restart_confirmation_required"])
            finally:
                raw.close()

    def test_inactive_cancel_finishes_immediately_and_preserves_pending_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A)
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-token", "bearer")
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            try:
                service.ensure_projected()
                service.store.apply_classification(
                    [source_key("10")], "film", method="test-fixture", confidence=1
                )
                service.store.prepare_enrichment(consent=True)
                service.store.worker_finished("paused")
                cancelled = service.cancel_enrichment()
                self.assertEqual(cancelled["state"], "cancelled")
                self.assertEqual(cancelled["command"], "idle")
                self.assertEqual(cancelled["queue"]["cancelled"], 0)
                self.assertEqual(cancelled["queue"]["pending"], 1)

                service.store.prepare_enrichment(consent=True)
                with service.store.connection() as connection:
                    queue_state = connection.execute(
                        "SELECT status FROM enrichment_queue"
                    ).fetchone()[0]
                self.assertEqual(queue_state, "pending")

                service.store.worker_command("cancel")
                self.assertEqual(service.enrichment_status()["state"], "cancelled")
            finally:
                raw.close()


class IPTVMovieRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.manager = IPTVProviderManager(self.temporary.name, migrate_legacy=False)
        created = self.manager.create_provider(
            "Fixture Provider", "https://provider.example", "fixture-user", "fixture-password"
        )
        self.provider_id = created["provider_id"]
        self.raw = self.manager.service(self.provider_id)
        from tests.iptv_movie_fixtures import provider_catalog
        self.raw.store.replace_catalog(provider_catalog())
        app = Flask(__name__)
        register_iptv_routes(app, lambda: self.manager)
        self.client = app.test_client()

    def tearDown(self):
        self.manager.close()
        self.temporary.cleanup()

    def test_metadata_settings_api_is_redacted_and_validates_with_one_bounded_call(self):
        initial = self.client.get("/api/iptv/metadata/settings")
        saved = self.client.patch("/api/iptv/metadata/settings", json={
            "credential_type": "bearer", "credential": "fixture-route-secret"
        })
        with patch("services.iptv_routes.IPTVTMDBClient.validate", return_value=True) as validate:
            tested = self.client.post("/api/iptv/metadata/test")
        body = json.dumps([initial.get_json(), saved.get_json(), tested.get_json()])

        self.assertEqual(initial.get_json()["tmdb_configured"], False)
        self.assertEqual(saved.get_json()["tmdb_configured"], True)
        self.assertEqual(tested.get_json(), {"tmdb_configured": True, "valid": True})
        self.assertNotIn("fixture-route-secret", body)
        self.assertNotIn('"credential":', body)
        validate.assert_called_once_with()

    def test_movies_are_provider_scoped_lazy_and_raw_fallback_needs_no_tmdb(self):
        path = self.raw.root / "movies.sqlite"
        self.assertFalse(path.exists())
        self.assertEqual(self.client.get("/api/iptv/providers").status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/iptv/providers/{self.provider_id}/items?kind=live").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(f"/api/iptv/providers/{self.provider_id}/items?kind=series").status_code,
            200,
        )
        self.assertFalse(path.exists())

        response = self.client.get(
            f"/api/iptv/providers/{self.provider_id}/movies?playlist_id=movies-a&page=1&page_size=10"
        )
        payload = response.get_json()
        self.manager.movie_service(self.provider_id).start_projection(wait=True)
        payload = self.client.get(
            f"/api/iptv/providers/{self.provider_id}/movies?playlist_id=movies-a&page=1&page_size=10"
        ).get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["items"][0]["metadata_status"], "unprocessed")
        self.assertEqual(payload["items"][0]["playlist_name"], "Exact Provider Playlist")
        self.assertTrue(path.exists())
        self.assertEqual(
            self.client.get("/api/iptv/providers/not-a-provider/movies").status_code,
            404,
        )

    def test_startup_is_lazy_missing_tmdb_blocks_only_enrichment_and_provider_delete_is_confined(self):
        movie_path = self.raw.root / "movies.sqlite"
        self.assertEqual(self.manager._movie_services, {})
        self.assertFalse(movie_path.exists())
        self.assertEqual(
            self.client.post(
                f"/api/iptv/providers/{self.provider_id}/movies/enrichment/start"
            ).status_code,
            400,
        )
        fallback = self.client.get(
            f"/api/iptv/providers/{self.provider_id}/movies"
        ).get_json()
        self.manager.movie_service(self.provider_id).start_projection(wait=True)
        fallback = self.client.get(
            f"/api/iptv/providers/{self.provider_id}/movies"
        ).get_json()
        self.assertEqual(fallback["total"], 1)
        self.assertEqual(fallback["items"][0]["metadata_status"], "unprocessed")
        self.assertEqual(self.manager.movie_service(self.provider_id).enrichment_status()["state"], "idle")

        provider_root = self.raw.root
        outside = Path(self.temporary.name) / "outside-sentinel.txt"
        outside.write_text("preserve", encoding="utf-8")
        self.manager.remove_provider(self.provider_id, "Fixture Provider")
        self.assertFalse(provider_root.exists())
        self.assertEqual(outside.read_text(encoding="utf-8"), "preserve")

    def test_manual_match_favorite_and_custom_list_use_provider_local_owners(self):
        movie_service = self.manager.movie_service(self.provider_id)
        movie_service.tmdb_client_factory = lambda: FakeTMDBClient()
        movie_service.start_projection(wait=True)
        card = self.client.get(
            f"/api/iptv/providers/{self.provider_id}/movies"
        ).get_json()["items"][0]
        key = card["movie_key"]
        matched = self.client.post(
            f"/api/iptv/providers/{self.provider_id}/movies/{key}/match", json={"tmdb_id": 550}
        )
        matched_key = matched.get_json()["movie_key"]
        favorited = self.client.post(
            f"/api/iptv/providers/{self.provider_id}/movies/{matched_key}/favorite",
            json={"favorite": True},
        )
        custom = self.raw.create_list("Movie Picks")
        listed = self.client.post(
            f"/api/iptv/providers/{self.provider_id}/movies/{matched_key}/lists/{custom['list_id']}"
        )
        filtered = self.client.get(
            f"/api/iptv/providers/{self.provider_id}/movies?list_id={custom['list_id']}"
        ).get_json()

        self.assertEqual(matched.status_code, 200)
        self.assertTrue(favorited.get_json()["favorite"])
        self.assertTrue(listed.get_json()["included"])
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["source_count"], 1)
        self.assertEqual(self.raw.list_favorites(kind="movie")["total"], 1)


if __name__ == "__main__":
    unittest.main()
