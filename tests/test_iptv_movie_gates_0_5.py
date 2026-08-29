import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services.iptv_enrichment_worker import run_worker
from services.iptv_metadata_settings import IPTVMetadataSettings
from services.iptv_movie_service import IPTVMovieService
from services.iptv_movie_store import (
    MATCHER_VERSION,
    MOVIE_SCHEMA_VERSION,
    PARSER_VERSION,
    IPTVMovieStore,
    source_key,
)
from services.iptv_tmdb import (
    choose_automatic_match,
    normalize_tmdb_movie,
    parse_provider_title,
    provider_id_matches,
)
from tests.iptv_movie_fixtures import FakeTMDBClient, create_raw_service, tmdb_payload


PROVIDER_A = "a" * 32
PROVIDER_B = "b" * 32


def snapshot(tmdb_id, title, year, *, genre_id=18, person_id=10, keyword_id=20, collection_id=30, language="en", imdb_id=""):
    payload = tmdb_payload(tmdb_id, title, year)
    payload.update({
        "original_language": language,
        "imdb_id": imdb_id,
        "genres": [{"id": genre_id, "name": "Shared genre"}],
        "credits": {
            "crew": [{"id": person_id, "name": "Shared person", "job": "Director", "profile_path": "/person.jpg"}],
            "cast": [{"id": person_id + 1, "name": "Shared cast", "character": "Hero", "profile_path": "/cast.jpg"}],
        },
        "keywords": {"keywords": [{"id": keyword_id, "name": "shared keyword"}]},
        "belongs_to_collection": {"id": collection_id, "name": "Shared collection"},
    })
    return normalize_tmdb_movie(payload)


class SchemaV2MigrationTests(unittest.TestCase):
    def test_v1_decisions_snapshots_relationships_and_rollback_are_provider_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / PROVIDER_A
            store = IPTVMovieStore(root, PROVIDER_A)
            store.project_sources([
                {"item_id": "1", "name": "First (2024)"},
                {"item_id": "2", "name": "Second (2025)"},
            ], 1, memberships=[{"list_id": "favorites", "source_id": "1", "position": 0, "added_at": 1}])
            store.apply_match(f"source:{source_key('1')}", snapshot(101, "First", 2024), manual=True)
            store.apply_match(f"source:{source_key('2')}", snapshot(102, "Second", 2025))
            with store.connection(immediate=True) as connection:
                connection.execute("DELETE FROM movie_genres WHERE tmdb_id=101")
                connection.execute("DELETE FROM movie_credits WHERE tmdb_id=101")
                connection.execute("DELETE FROM movie_keywords WHERE tmdb_id=101")
                connection.execute("DELETE FROM movie_collections WHERE tmdb_id=101")
                connection.execute("DROP TABLE projection_jobs")
                connection.execute("DROP TABLE worker_lease")
                connection.execute("DROP TABLE tmdb_movie_localizations")
                connection.execute("UPDATE movie_meta SET value='1' WHERE key='schema_version'")
            pre = root / "movies.sqlite"
            migrated = IPTVMovieStore(root, PROVIDER_A)
            report = migrated.migration_report()
            self.assertEqual(report["schema_version"], MOVIE_SCHEMA_VERSION)
            self.assertTrue(Path(report["backup"]).is_file())
            with migrated.connection() as connection:
                accepted = connection.execute("SELECT source_key,tmdb_id,manual_lock FROM source_matches ORDER BY source_key").fetchall()
                self.assertEqual(len(accepted), 2)
                self.assertEqual(sum(row[2] for row in accepted), 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM movie_list_memberships").fetchone()[0], 1)
                for table in ("movie_genres", "movie_credits", "movie_keywords", "movie_collections"):
                    self.assertGreaterEqual(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE tmdb_id=101").fetchone()[0], 1)
                projection = connection.execute(
                    "SELECT state,source_generation,total,processed,checkpoint FROM projection_jobs WHERE job_id=1"
                ).fetchone()
                self.assertEqual(tuple(projection), ("complete", 1, 2, 2, 2))
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            migrated.rollback_migration()
            self.assertEqual(IPTVMovieStore.inspect_schema_version(pre), 1)

    def test_conflict_safe_shared_parents_retain_both_movies(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IPTVMovieStore(Path(temporary) / PROVIDER_A, PROVIDER_A)
            store.project_sources([{"item_id": "1", "name": "One"}, {"item_id": "2", "name": "Two"}], 1)
            store.apply_match(f"source:{source_key('1')}", snapshot(1, "One", 2024))
            store.apply_match(f"source:{source_key('2')}", snapshot(2, "Two", 2025))
            store.apply_match("tmdb:2", snapshot(2, "Two updated", 2025))
            with store.connection() as connection:
                for table in ("movie_genres", "movie_keywords", "movie_collections"):
                    self.assertEqual(connection.execute(f"SELECT COUNT(DISTINCT tmdb_id) FROM {table}").fetchone()[0], 2)
                self.assertEqual(connection.execute("SELECT COUNT(DISTINCT tmdb_id) FROM movie_credits WHERE person_id=10").fetchone()[0], 2)


class ProjectionAndWorkerTests(unittest.TestCase):
    def test_movies_get_is_pure_and_projection_is_nonblocking_progressive(self):
        rows = [{"stream_id": str(index), "category_id": "movies-a", "name": f"Movie {index}"} for index in range(200)]
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A, movie_rows=rows)
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, IPTVMetadataSettings(temporary))
            try:
                first = service.list_movies(page_size=10)
                self.assertEqual(first["items"], [])
                self.assertFalse(service.database_path.exists())
                original = IPTVMovieStore.project_source_batch

                def slow_batch(store, *args, **kwargs):
                    result = original(store, *args, **kwargs)
                    time.sleep(0.02)
                    return result

                service.PROJECTION_BATCH_SIZE = 20
                with patch.object(IPTVMovieStore, "project_source_batch", slow_batch):
                    started = time.perf_counter()
                    status = service.start_projection(wait=False)
                    self.assertLess(time.perf_counter() - started, 1.0)
                    self.assertEqual(status["state"], "running")
                    deadline = time.time() + 30
                    saw_partial = False
                    while time.time() < deadline:
                        status = service.projection_status()
                        if 0 < status["published"] < status["total"]:
                            saw_partial = True
                        if status["state"] == "complete":
                            break
                        time.sleep(0.01)
                self.assertTrue(saw_partial)
                self.assertEqual(status["state"], "complete")
                self.assertEqual(service.list_movies(page_size=10)["total"], 200)
            finally:
                if service._projection_thread is not None:
                    service._projection_thread.join(timeout=30)
                service.close()
                raw.close()

    def test_one_consent_continues_beyond_one_hundred_with_durable_checkpoint(self):
        rows = [{"stream_id": str(index), "category_id": "movies-a", "name": f"Movie {index}"} for index in range(105)]
        with tempfile.TemporaryDirectory() as temporary:
            raw = create_raw_service(temporary, PROVIDER_A, movie_rows=rows)
            settings = IPTVMetadataSettings(temporary)
            settings.save("fixture-token", "bearer")
            service = IPTVMovieService(raw.root, PROVIDER_A, raw, settings)
            try:
                service.start_projection(wait=True)
                token = service.store.prepare_enrichment(consent=True)
                with patch.object(service, "enrich_source", return_value="unmatched") as enrich:
                    self.assertEqual(run_worker(service, max_jobs=0, lease_token=token), "complete")
                status = service.enrichment_status()
                self.assertEqual(enrich.call_count, 105)
                self.assertEqual(status["queue"]["done"], 105)
                self.assertEqual(status["checkpoint"], 105)
                self.assertTrue(status["consent"])
            finally:
                raw.close()


class ParserLocalizationAndPresentationTests(unittest.TestCase):
    def test_authoritative_parser_handles_years_scripts_noise_and_installments(self):
        self.assertEqual(parse_provider_title("Balan - The Boy ( 2026 )", 2026)["primary_alias"], "balan the boy")
        self.assertEqual(parse_provider_title("Balan - The Boy 2026", 2026)["primary_alias"], "balan the boy")
        self.assertEqual(parse_provider_title("The Truthers 2026", 2026)["primary_alias"], "the truthers")
        self.assertEqual(parse_provider_title("1917 (2019)", 2019)["primary_alias"], "1917")
        self.assertEqual(parse_provider_title("2001: A Space Odyssey (1968)", 1968)["primary_alias"], "2001 a space odyssey")
        bilingual = parse_provider_title("Merry Little Batman \u0645\u064a\u0644\u0627\u062f \u0633\u0639\u064a\u062f \u0628\u0627\u062a\u0645\u0627\u0646 \u0627\u0644\u0635\u063a\u064a\u0631 (2023) (\u0645\u062f\u0628\u0644\u062c)", 2023)
        self.assertEqual(bilingual["latin_aliases"], ["merry little batman"])
        self.assertTrue(bilingual["arabic_aliases"])
        correct = tmdb_payload(1311031, "Demon Slayer: Kimetsu no Yaiba Infinity Castle", 2025)
        rival = tmdb_payload(129, "Demon Slayer: Kimetsu no Yaiba - The Movie: Mugen Train", 2020)
        title = "Demon Slayer: Kimetsu no Yaiba Infinity Castle (2025) 4K Eng Audio - \u062f\u0628\u0644\u062c\u0629 \u0625\u0646\u062c\u0644\u064a\u0632\u064a\u0629"
        valid, _score = provider_id_matches(title, 2025, correct)
        decision = choose_automatic_match(title, 2025, [rival, correct])
        self.assertTrue(valid)
        self.assertEqual(decision["accepted"]["id"], 1311031)
        self.assertLess(decision["candidates"][1]["match_score"], 78)

    def test_localization_external_links_and_people_are_provider_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IPTVMovieStore(Path(temporary) / PROVIDER_A, PROVIDER_A)
            store.project_sources([{"item_id": "1", "name": "Arabic Movie"}, {"item_id": "2", "name": "English Movie"}], 1)
            arabic = snapshot(1, "English transliteration", 2024, language="ar", imdb_id="tt1234567")
            arabic["original_title"] = "\u0641\u064a\u0644\u0645 \u0639\u0631\u0628\u064a \u0623\u0635\u0644\u064a"
            arabic["plot"] = "English fallback plot"
            english = snapshot(2, "English Movie", 2025, language="en", imdb_id="tt7654321")
            store.apply_classification(
                [source_key("1"), source_key("2")],
                "film",
                method="test-fixture",
                confidence=1,
            )
            store.apply_match(f"source:{source_key('1')}", arabic)
            store.apply_match(f"source:{source_key('2')}", english)
            fallback_card = {
                item["tmdb_id"]: item
                for item in store.list_movies({"view": "cp"}, page_size=10)["items"]
            }[1]
            self.assertEqual(fallback_card["name"], "\u0641\u064a\u0644\u0645 \u0639\u0631\u0628\u064a \u0623\u0635\u0644\u064a")
            self.assertEqual(fallback_card["plot"], "English fallback plot")
            fallback_detail = store.movie("tmdb:1")
            self.assertNotIn("arabic_display", fallback_detail)
            localized = {
                **arabic,
                "title": "",
                "plot": "",
                "directors": [{"id": 10, "name": "\u0645\u062e\u0631\u062c \u0639\u0631\u0628\u064a"}],
                "writers": [],
                "cast": [{"id": 11, "name": "\u0645\u0645\u062b\u0644 \u0639\u0631\u0628\u064a", "character": "\u0627\u0644\u0628\u0637\u0644"}],
            }
            store.save_localization(1, "ar-SA", localized)
            cards = {
                item["tmdb_id"]: item
                for item in store.list_movies({"view": "cp"}, page_size=10)["items"]
            }
            self.assertEqual(cards[1]["name"], "\u0641\u064a\u0644\u0645 \u0639\u0631\u0628\u064a \u0623\u0635\u0644\u064a")
            self.assertEqual(cards[1]["plot"], "English fallback plot")
            self.assertEqual(cards[1]["display_locale"], "ar-SA")
            self.assertIn("themoviedb.org/movie/1", cards[1]["external_url"])
            self.assertIn("imdb.com/title/tt7654321", cards[2]["external_url"])
            detail = store.movie("tmdb:1")
            self.assertEqual(detail["name"], "\u0641\u064a\u0644\u0645 \u0639\u0631\u0628\u064a \u0623\u0635\u0644\u064a")
            self.assertEqual(detail["plot"], "English fallback plot")
            self.assertEqual(detail["directors"][0]["name"], "\u0645\u062e\u0631\u062c \u0639\u0631\u0628\u064a")
            self.assertTrue(detail["directors"][0]["profile_url"].endswith("/person.jpg"))
            self.assertEqual(detail["cast"][0]["name"], "\u0645\u0645\u062b\u0644 \u0639\u0631\u0628\u064a")
            self.assertTrue(detail["cast"][0]["profile_url"].endswith("/cast.jpg"))
            self.assertEqual(detail["base_display"]["title"], "English transliteration")
            self.assertIn("ar-SA", detail["available_locales"])

            english_detail = store.movie("tmdb:2")
            native_overlay = store.merge_localization_display(english_detail, {
                "title": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c2a\u0c47\u0c30\u0c41",
                "original_title": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c05\u0c38\u0c32\u0c41 \u0c2a\u0c47\u0c30\u0c41",
                "plot": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c15\u0c25",
                "genres": [{"id": 18, "name": "\u0c21\u0c4d\u0c30\u0c3e\u0c2e\u0c3e"}],
                "collection": {"id": 30, "name": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c38\u0c47\u0c15\u0c30\u0c23"},
                "credits": {
                    "directors": [{"id": 10, "name": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c26\u0c30\u0c4d\u0c36\u0c15\u0c41\u0c21\u0c41"}],
                    "cast": [{"id": 11, "name": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c28\u0c1f\u0c41\u0c21\u0c41"}],
                },
            })
            self.assertEqual(native_overlay["title"], "English Movie")
            self.assertEqual(native_overlay["plot"], english_detail["base_display"]["plot"])
            self.assertEqual(native_overlay["directors"][0]["name"], "Shared person")
            self.assertEqual(native_overlay["cast"][0]["name"], "Shared cast")
            self.assertEqual(native_overlay["genres"][0]["name"], "Shared genre")
            self.assertEqual(native_overlay["collection"]["name"], "Shared collection")

            actual_arabic_overlay = store.merge_localization_display(english_detail, {
                "title": "\u0639\u0646\u0648\u0627\u0646 \u0639\u0631\u0628\u064a",
                "plot": "\u0642\u0635\u0629 \u0639\u0631\u0628\u064a\u0629",
                "credits": {"directors": [{"id": 10, "name": "\u0645\u062e\u0631\u062c \u0639\u0631\u0628\u064a"}]},
            })
            self.assertEqual(actual_arabic_overlay["title"], "\u0639\u0646\u0648\u0627\u0646 \u0639\u0631\u0628\u064a")
            self.assertEqual(actual_arabic_overlay["plot"], "\u0642\u0635\u0629 \u0639\u0631\u0628\u064a\u0629")
            self.assertEqual(actual_arabic_overlay["directors"][0]["name"], "\u0645\u062e\u0631\u062c \u0639\u0631\u0628\u064a")

    def test_stale_re_evaluation_preserves_manual_locks(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = IPTVMovieStore(Path(temporary) / PROVIDER_A, PROVIDER_A)
            store.project_sources([{"item_id": "1", "name": "Auto"}, {"item_id": "2", "name": "Manual"}], 1)
            store.set_match_state([source_key("1")], "unmatched", parser_version=1, matcher_version=1)
            store.set_match_state([source_key("2")], "unmatched", manual_lock=True, method="manual-unmatched", parser_version=1, matcher_version=1)
            self.assertEqual(store.mark_stale_automatic_results(), 1)
            self.assertEqual(store.re_evaluate_stale(), 1)
            with store.connection() as connection:
                rows = {row[0]: tuple(row[1:]) for row in connection.execute("SELECT source_key,state,manual_lock FROM source_matches")}
            self.assertEqual(rows[source_key("1")], ("unprocessed", 0))
            self.assertEqual(rows[source_key("2")], ("unmatched", 1))


if __name__ == "__main__":
    unittest.main()
