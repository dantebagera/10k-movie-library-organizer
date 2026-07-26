import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class SqlMigrationParityTest(unittest.TestCase):
    """Fixture-backed contract tests for the JSON-to-SQL catalog migration."""

    def setUp(self):
        self.movies_tmp = tempfile.TemporaryDirectory()
        self.data_tmp = tempfile.TemporaryDirectory()
        self.movies_dir = Path(self.movies_tmp.name)
        self.data_dir = Path(self.data_tmp.name)
        self.store = app.AppMetadataStore(self.data_dir)
        self.original_state = {
            "movies_dirs": app._movies_dirs,
            "movies_dir": app._movies_dir,
            "user_data_dir": app._user_data_dir,
            "library_cache": dict(app._library_cache),
            "stats_cache": dict(app._stats_cache),
            "maintenance_audit_cache": dict(app._maintenance_audit_cache),
            "identity_audit_cache": dict(app._identity_verification_audit_cache),
            "plex_cache": dict(app._plex_cache),
            "plex_by_filename": dict(app._plex_matched_by_fname),
            "plex_token": app._plex_token,
        }
        app._movies_dirs = [str(self.movies_dir)]
        app._movies_dir = str(self.movies_dir)
        app._user_data_dir = str(self.data_dir)
        app._library_cache = {}
        app._stats_cache = {}
        app._maintenance_audit_cache = {"generation": None, "audit": None}
        app._identity_verification_audit_cache = {"revision": None, "audit": None}
        app._plex_cache = {}
        app._plex_matched_by_fname = {}
        app._plex_token = ""
        self.paths = self._seed_fixture_library()
        self.expected = json.loads(
            (Path(__file__).parent / "fixtures" / "catalog_performance_expected.json").read_text(encoding="utf-8")
        )

    def tearDown(self):
        app._movies_dirs = self.original_state["movies_dirs"]
        app._movies_dir = self.original_state["movies_dir"]
        app._user_data_dir = self.original_state["user_data_dir"]
        app._library_cache = self.original_state["library_cache"]
        app._stats_cache = self.original_state["stats_cache"]
        app._maintenance_audit_cache = self.original_state["maintenance_audit_cache"]
        app._identity_verification_audit_cache = self.original_state["identity_audit_cache"]
        app._plex_cache = self.original_state["plex_cache"]
        app._plex_matched_by_fname = self.original_state["plex_by_filename"]
        app._plex_token = self.original_state["plex_token"]
        self.movies_tmp.cleanup()
        self.data_tmp.cleanup()

    def _movie_path(self, filename):
        path = self.movies_dir / filename
        path.write_bytes(b"movie")
        return path

    def _accepted_movie(self, filename, metadata, *, resolution="1080p", rip_source="WEB-DL", size=100):
        path = self._movie_path(filename)
        self.store.apply_tmdb_match(str(path), metadata)
        self.store.update_file_record(str(path), {
            "filename": path.name,
            "library_root": str(self.movies_dir),
            "parsed_title": metadata["title"],
            "parsed_year": str(metadata["year"]),
            "resolution": resolution,
            "rip_source": rip_source,
            "size": size,
            "added_time": 1,
            "modified_time": 1,
            "ingest_status": "imported",
        })
        return path

    def _seed_fixture_library(self):
        shared = {
            "tmdb_id": "100",
            "imdb_id": "tt0000100",
            "title": "Correct Movie",
            "year": "2020",
            "poster_url": "https://poster.example/correct.jpg",
            "plot": "TMDB plot wins the canonical summary.",
            "genres": ["Drama", "Mystery"],
            "tmdb_rating": "8.4",
            "cast": [
                {"id": index, "name": f"Lead Actor {index}", "character": f"Role {index}"}
                for index in range(1, 7)
            ],
            "directors": [
                {"id": 20, "name": "Lead Director"},
                {"id": 21, "name": "Second Director"},
            ],
            "writers": [
                {"id": 30, "name": "Lead Writer", "job": "Screenplay"},
            ],
            "keywords": [
                {"id": 501, "name": "Time Travel"},
                "Mystery",
            ],
        }
        corrected = self._accepted_movie("Wrong.Provider.2020.1080p.mkv", shared)
        self.store.save_plex_metadata(str(corrected), {
            "plex_title": "Wrong Provider Movie",
            "plex_year": "2020",
            "tmdb_id": "999",
            "plex_summary": "Plex summary must remain available without replacing the TMDB plot.",
            "plex_genres": ["Incorrect"],
        })
        duplicate_best = self._accepted_movie(
            "Duplicate.Group.2021.4K.Remux.mkv",
            {"tmdb_id": "200", "title": "Duplicate Group", "year": "2021"},
            resolution="4K",
            rip_source="Remux",
            size=400,
        )
        duplicate_low = self._accepted_movie(
            "Duplicate.Group.2021.1080p.WEB-DL.mkv",
            {"tmdb_id": "200", "title": "Duplicate Group", "year": "2021"},
            size=100,
        )
        imported = self._accepted_movie(
            "Newly.Imported.2024.1080p.mkv",
            {"tmdb_id": "300", "title": "Newly Imported", "year": "2024"},
        )
        collection = self._accepted_movie(
            "Collection.Movie.2022.1080p.mkv",
            {
                "tmdb_id": "400",
                "title": "Collection Movie",
                "year": "2022",
                "poster_url": "https://poster.example/collection.jpg",
                "collection": {"id": "44", "name": "Parity Collection"},
            },
        )
        custom_poster = self._accepted_movie(
            "Custom.Poster.2023.1080p.mkv",
            {"tmdb_id": "500", "title": "Custom Poster", "year": "2023", "poster_url": "https://poster.example/original.jpg"},
        )
        self.store.save_poster_override(
            {"tmdb_id": "500", "title": "Custom Poster", "year": "2023"},
            "fixture",
            b"fixture-poster",
            ".jpg",
        )
        upgrade = self._accepted_movie(
            "Upgrade.Candidate.2019.720p.mkv",
            {"tmdb_id": "600", "title": "Upgrade Candidate", "year": "2019"},
            resolution="720p",
        )
        unmatched = self._movie_path("Unmatched.File.2025.1080p.mkv")
        self.store.update_file_record(str(unmatched), {
            "filename": unmatched.name,
            "library_root": str(self.movies_dir),
            "parsed_title": "Unmatched File",
            "parsed_year": "2025",
            "resolution": "1080p",
            "rip_source": "WEB-DL",
            "size": 100,
            "identity_status": "review",
            "metadata_status": "review",
            "metadata_accepted": False,
        })
        wrong_review = self._movie_path("Wrong.Provider.Review.2020.1080p.mkv")
        self.store.save_tmdb_metadata({
            "tmdb_id": "999",
            "title": "Wrong Provider Movie",
            "year": "2020",
            "plot": "Deliberately wrong provider candidate awaiting review.",
        })
        self.store.update_file_record(str(wrong_review), {
            "filename": wrong_review.name,
            "library_root": str(self.movies_dir),
            "parsed_title": "Correct Movie",
            "parsed_year": "2020",
            "resolution": "1080p",
            "rip_source": "WEB-DL",
            "size": 100,
            "tmdb_id": "999",
            "identity_status": "review",
            "metadata_status": "needs_review",
            "metadata_accepted": False,
        })
        self.store._write_json(self.store.metadata_overrides_file, {"overrides": [{
            "identity": {"tmdb_id": "400", "title": "Collection Movie", "year": "2022"},
            "identity_keys": ["tmdb:400"],
            "title": "Collection Movie (Director Cut)",
            "year": "2022",
            "locked": True,
        }]})
        self.store._write_json(self.data_dir / "user_lists.json", {"lists": [{
            "id": "parity-list",
            "name": "Parity List",
            "system_type": "watchlist",
            "movies": [{"tmdb_id": "100", "title": "Correct Movie", "year": "2020"}],
        }]})
        return {
            "corrected": corrected,
            "duplicate_best": duplicate_best,
            "duplicate_low": duplicate_low,
            "imported": imported,
            "collection": collection,
            "custom_poster": custom_poster,
            "upgrade": upgrade,
            "unmatched": unmatched,
            "wrong_review": wrong_review,
        }

    def test_performance_fixture_manifest_has_independent_expected_outputs(self):
        corrected = self._candidate_for_path(self.paths["corrected"])
        corrected_projection = corrected["relational_canonical"]
        expected = self.expected["corrected"]
        for field in ("tmdb_id", "imdb_id", "title", "year", "plot", "detail_provider"):
            self.assertEqual(corrected_projection.get(field), expected[field], field)
        self.assertEqual(
            [person["name"] for person in corrected_projection["cast"]],
            expected["cast_names"],
        )
        self.assertEqual(
            [person["name"] for person in corrected_projection["directors"]],
            expected["director_names"],
        )

        wrong_review = self._candidate_for_path(self.paths["wrong_review"])
        wrong_expected = self.expected["wrong_provider_review"]
        self.assertEqual(wrong_review["identity_status"], wrong_expected["identity_status"])
        self.assertEqual(wrong_review["metadata_status"], wrong_expected["metadata_status"])
        self.assertEqual(bool(wrong_review["metadata_accepted"]), wrong_expected["metadata_accepted"])
        self.assertEqual(wrong_review["tmdb_id"], wrong_expected["candidate_tmdb_id"])

    def _candidate_for_path(self, path):
        key = app._norm(str(path))
        for candidate in self.store.catalog.store.library_projection(include_details=True):
            if candidate["path_key"] == key:
                return candidate
        self.fail(f"Missing SQL candidate for {path}")

    def _json_derived_canonical(self, path):
        snapshot = self.store.snapshot()
        key = app._norm(str(path))
        file_record = snapshot["files"][key]
        tmdb = snapshot["tmdb_movies"].get(str(file_record.get("tmdb_id") or ""), {})
        plex = snapshot["plex_files"].get(key, {})
        manual = snapshot["manual_matches"].get(key, {})
        canonical = app._build_canonical_metadata(
            file_record,
            plex_data=plex,
            tmdb_data=tmdb,
            manual_match=manual,
            display_provider=file_record.get("display_provider", ""),
            file_record=file_record,
        )
        identity = app._poster_identity_for_movie(file_record, canonical, plex)
        canonical = app._apply_metadata_override(canonical, identity, store=self.store, snapshot=snapshot)
        return app._apply_poster_override(canonical, identity, store=self.store, snapshot=snapshot)

    def test_fixture_rows_domain_model_and_json_shadow_projection_agree(self):
        candidate = self._candidate_for_path(self.paths["corrected"])
        connection = self.store.catalog.store.connect()
        try:
            row = connection.execute(
                "SELECT tmdb_id, imdb_id, identity_status, metadata_accepted, raw_json FROM media_files WHERE path_key = ?",
                (candidate["path_key"],),
            ).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["tmdb_id"], "100")
        self.assertEqual(row["imdb_id"], "tt0000100")
        self.assertEqual(row["identity_status"], "accepted")
        self.assertEqual(row["metadata_accepted"], 1)

        sql_item = app._catalog_library_item(candidate, self.store, self.store.snapshot())
        json_item = self._json_derived_canonical(self.paths["corrected"])
        for field in ("title", "year", "tmdb_id", "imdb_id", "plot", "summary", "genres", "rating"):
            self.assertEqual(sql_item["canonical_metadata"].get(field), json_item.get(field), field)
        for field in ("cast", "directors"):
            normalize = lambda people: [(
                str(person.get("id", "") or ""),
                str(person.get("name", "") or "").strip(),
                str(person.get("character", "") or "").strip(),
                str(person.get("profile_url", "") or "").strip(),
            ) for person in (people or [])]
            self.assertEqual(
                normalize(sql_item["canonical_metadata"].get(field)),
                normalize(json_item.get(field)),
                field,
            )
        self.assertEqual(sql_item["canonical_metadata"]["plot"], "TMDB plot wins the canonical summary.")
        self.assertEqual(sql_item["canonical_metadata"]["detail_provider"], "tmdb_snapshot")
        self.assertEqual(sql_item["plex_summary"], "Plex summary must remain available without replacing the TMDB plot.")

        collection = app._catalog_library_item(self._candidate_for_path(self.paths["collection"]), self.store, self.store.snapshot())
        poster = app._catalog_library_item(self._candidate_for_path(self.paths["custom_poster"]), self.store, self.store.snapshot())
        self.assertEqual(collection["canonical_metadata"]["collection"]["name"], "Parity Collection")
        self.assertEqual(collection["canonical_metadata"]["title"], "Collection Movie (Director Cut)")
        self.assertTrue(poster["canonical_metadata"]["poster_override"])
        self.assertNotEqual(poster["canonical_metadata"]["poster_url"], "https://poster.example/original.jpg")

    def test_api_projections_include_canonical_card_metadata_without_provider_calls(self):
        client = app.app.test_client()
        with patch("app.urllib.request.urlopen", side_effect=AssertionError("SQL detail reads must not call a provider")):
            full = client.get("/api/library")
            cards = client.get("/api/library?view=cards")
            movie_list_cards = client.get("/api/library?view=movie-list")
            people = client.get("/api/library?view=people")
            keywords = client.get("/api/library?view=keywords&q=time")
            keywords_with_refresh_ignored = client.get(
                "/api/library?view=keywords&q=time&refresh_metadata=1&force_scan=1"
            )
            writer_cards = client.get(
                "/api/library?view=cards&role=writer&person_id=30&person_name=Lead+Writer"
            )
            keyword_cards = client.get("/api/library?view=cards&keyword_name=TIME+TRAVEL")
            writer_selection = client.post("/api/library/selection", json={
                "filters": {"role": "writer", "person_id": "30", "person_name": "Lead Writer"},
            })
            keyword_selection = client.post("/api/library/selection", json={
                "filters": {"keyword_id": "501"},
            })
            details = client.get("/api/library/details", query_string={"path": str(self.paths["corrected"])})
            ownership = client.post("/api/library/check", json={
                "include_items": True,
                "movies": [{"tmdb_id": "100", "title": "Correct Movie", "year": "2020"}],
            })

        self.assertEqual(full.status_code, 200)
        self.assertEqual(cards.status_code, 200)
        self.assertEqual(movie_list_cards.status_code, 200)
        self.assertEqual(people.status_code, 200)
        self.assertEqual(keywords.status_code, 200)
        self.assertEqual(keywords_with_refresh_ignored.status_code, 200)
        self.assertEqual(writer_cards.status_code, 200)
        self.assertEqual(keyword_cards.status_code, 200)
        self.assertEqual(writer_selection.status_code, 200)
        self.assertEqual(keyword_selection.status_code, 200)
        self.assertEqual(details.status_code, 200)
        self.assertEqual(ownership.status_code, 200)
        full_item = next(item for item in full.get_json()["items"] if item["tmdb_id"] == "100")
        card_item = next(item for item in cards.get_json()["items"] if item["path"] == str(self.paths["corrected"]))
        movie_list_card = next(item for item in movie_list_cards.get_json()["items"] if item["path"] == str(self.paths["corrected"]))
        people_item = next(item for item in people.get_json()["items"] if item["path"] == str(self.paths["corrected"]))
        owned_item = ownership.get_json()["results"][0]["library_item"]
        owned_card = ownership.get_json()["results"][0]["canonical_card"]
        self.assertTrue(ownership.get_json()["results"][0]["found"])
        for field in ("tmdb_id", "imdb_id", "title", "year", "plot", "summary", "detail_provider"):
            self.assertEqual(card_item["canonical_metadata"][field], full_item["canonical_metadata"][field], f"Library card {field}")
            self.assertEqual(movie_list_card["canonical_metadata"][field], full_item["canonical_metadata"][field], f"Movie List card {field}")
            self.assertEqual(owned_item["canonical_metadata"][field], full_item["canonical_metadata"][field], f"Discover ownership {field}")
            self.assertEqual(owned_card["canonical_metadata"][field], full_item["canonical_metadata"][field], f"Owned card {field}")
        for projected in (card_item, movie_list_card, owned_card):
            self.assertEqual(
                projected["canonical_metadata"]["projection_contract"],
                "canonical_movie_card",
            )
            self.assertIn("cast", projected["canonical_metadata"]["deferred_fields"])
        self.assertEqual(
            details.get_json()["item"]["canonical_metadata"]["projection_contract"],
            "canonical_movie_details",
        )
        self.assertEqual(card_item["canonical_metadata"]["plot"], "TMDB plot wins the canonical summary.")
        self.assertEqual(movie_list_card["canonical_metadata"]["plot"], "TMDB plot wins the canonical summary.")
        self.assertEqual(owned_item["canonical_metadata"]["plot"], "TMDB plot wins the canonical summary.")
        self.assertEqual(details.get_json()["item"]["canonical_metadata"]["plot"], "TMDB plot wins the canonical summary.")
        self.assertEqual(details.get_json()["item"]["plex_summary"], "Plex summary must remain available without replacing the TMDB plot.")
        for field in ("accepted", "title", "year"):
            self.assertEqual(
                people_item["canonical_metadata"][field],
                full_item["canonical_metadata"][field],
                f"People projection {field}",
            )
        self.assertEqual(people_item["canonical_metadata"]["cast"][0]["name"], "Lead Actor 1")
        self.assertEqual(people_item["canonical_metadata"]["writers"][0]["name"], "Lead Writer")
        self.assertEqual(keywords.get_json()["items"][0]["normalized_name"], "time travel")
        self.assertEqual(keywords.get_json()["page"], 1)
        self.assertEqual(keywords.get_json()["page_size"], 50)
        self.assertEqual(keywords.get_json()["total_pages"], 1)
        self.assertEqual(keywords.get_json()["total_results"], 1)
        self.assertEqual(keywords.get_json()["count"], 1)
        self.assertEqual(keywords.get_json()["source"], "catalog")
        self.assertEqual(
            keywords_with_refresh_ignored.get_json()["items"],
            keywords.get_json()["items"],
        )
        self.assertEqual(writer_cards.get_json()["total"], 1)
        self.assertEqual(keyword_cards.get_json()["total"], 1)
        self.assertEqual(writer_selection.get_json()["paths"], [str(self.paths["corrected"])])
        self.assertEqual(keyword_selection.get_json()["paths"], [str(self.paths["corrected"])])
        self.assertEqual(full_item["canonical_metadata"]["plot"], "TMDB plot wins the canonical summary.")

    def test_library_keyword_route_uses_page_contract_and_retires_limit(self):
        result = {
            "items": [{
                "keyword_key": "tmdb:501",
                "tmdb_id": "501",
                "name": "time travel",
                "normalized_name": "time travel",
                "movie_count": 1,
            }],
            "page": 3,
            "page_size": 25,
            "total_pages": 4,
            "total_results": 76,
            "catalog_generation": 9,
        }
        client = app.app.test_client()
        with patch("app._metadata_store", return_value=self.store), \
                patch.object(
                    self.store.catalog,
                    "library_keywords",
                    return_value=result,
                ) as library_keywords, \
                patch(
                    "app.urllib.request.urlopen",
                    side_effect=AssertionError("Library keyword search must not call TMDB"),
                ):
            response = client.get(
                "/api/library?view=keywords&q=time&page=3&page_size=25&limit=1"
            )

        self.assertEqual(response.status_code, 200)
        library_keywords.assert_called_once_with("time", page=3, page_size=25)
        self.assertEqual(response.get_json(), {
            **result,
            "count": 1,
            "source": "catalog",
        })

    def test_owned_details_route_never_uses_full_catalog_or_snapshot(self):
        client = app.app.test_client()
        with patch("app._metadata_store", return_value=self.store), \
                patch.object(
                    self.store.catalog.store,
                    "audit_library_candidates",
                    side_effect=AssertionError("owned details must not scan the Library"),
                ), \
                patch.object(
                    self.store,
                    "snapshot",
                    side_effect=AssertionError("owned details must not rebuild a document snapshot"),
                ), \
                patch("app.urllib.request.urlopen", side_effect=AssertionError("owned details must not call providers")):
            response = client.get(
                "/api/library/details",
                query_string={"path": str(self.paths["corrected"])},
            )

        self.assertEqual(response.status_code, 200)
        details = response.get_json()["item"]["canonical_metadata"]
        self.assertEqual(details["plot"], self.expected["corrected"]["plot"])
        self.assertEqual(
            [person["name"] for person in details["cast"]],
            self.expected["corrected"]["cast_names"],
        )
        self.assertEqual(
            [person["name"] for person in details["directors"]],
            self.expected["corrected"]["director_names"],
        )

    def test_production_library_read_surfaces_do_not_use_raw_audit_reader(self):
        client = app.app.test_client()
        with patch.object(
            self.store.catalog.store,
            "audit_library_candidates",
            side_effect=AssertionError("production reads must not decode raw audit documents"),
        ), patch("app.urllib.request.urlopen", side_effect=AssertionError("owned reads must remain offline")):
            cards = client.get("/api/library?view=cards")
            files = client.get("/api/library?view=files")
            people = client.get("/api/library?view=people")
            stats = client.get("/api/stats")
            collection = client.get("/api/library/collection/44")

        self.assertEqual(cards.status_code, 200)
        self.assertEqual(files.status_code, 200)
        self.assertEqual(people.status_code, 200)
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(collection.status_code, 200)
        self.assertTrue(any(item["canonical_metadata"]["plot"] for item in cards.get_json()["items"]))
        self.assertTrue(any(item["path"] == str(self.paths["unmatched"]) for item in files.get_json()["items"]))
        self.assertTrue(any(item["canonical_metadata"]["cast"] for item in people.get_json()["items"]))
        self.assertGreater(stats.get_json()["total_files"], 0)
        self.assertEqual(collection.get_json()["owned_count"], 1)

    def test_followed_and_curation_ownership_use_the_same_sql_identity_matcher(self):
        query = {"tmdb_id": "100", "title": "Correct Movie", "year": "2020"}
        result = app.app.test_client().post("/api/library/check", json={"movies": [query]}).get_json()["results"][0]
        owned = app._find_owned_movie(query)

        self.assertTrue(result["found"])
        self.assertIsNotNone(owned)
        self.assertEqual(owned["path"], result["path"])
        self.assertEqual(owned["resolution"], result["resolution"])

    def test_plex_source_sync_persists_changed_snapshot_once_without_generation_churn(self):
        path = str(self.paths["corrected"])
        path_key = app._norm(path)
        plex_record = {
            "rating_key": "plex-100",
            "plex_title": "Correct Movie",
            "plex_year": "2020",
            "plex_summary": "Fresh Plex source summary.",
            "plex_genres": ["Drama"],
            "plex_cast": [{"name": "Plex Actor"}],
            "plex_directors": [{"name": "Plex Director"}],
            "tmdb_id": "100",
            "imdb_id": "tt0000100",
            "plex_guid": "plex://movie-100",
        }
        original = (
            app._plex_url,
            app._plex_token,
            app._plex_cache_time,
            dict(app._plex_cache),
            dict(app._plex_unmatched),
            dict(app._plex_matched_by_fname),
            dict(app._plex_unmatched_by_fname),
            list(app._plex_section_ids),
        )
        app._plex_url = "http://plex.test"
        app._plex_token = "token"
        app._plex_cache_time = 0
        before = self.store.catalog.generation("media")
        try:
            with patch("app._fetch_plex_library", return_value=(
                {path_key: plex_record}, {}, {Path(path).name.lower(): plex_record}, {}, ["1"],
            )):
                app._auto_sync_plex(force=True)
                after_change = self.store.catalog.generation("media")
                app._auto_sync_plex(force=True)
                after_repeat = self.store.catalog.generation("media")
        finally:
            (
                app._plex_url,
                app._plex_token,
                app._plex_cache_time,
                app._plex_cache,
                app._plex_unmatched,
                app._plex_matched_by_fname,
                app._plex_unmatched_by_fname,
                app._plex_section_ids,
            ) = original

        plex_source = self.store.catalog.get_record(
            "app_metadata/plex_metadata.json", path_key, {}
        )
        self.assertEqual(after_change, before + 1)
        self.assertEqual(after_repeat, after_change)
        self.assertEqual(plex_source["plex_summary"], "Fresh Plex source summary.")

    def test_home_stats_and_maintenance_share_the_catalog_generation_and_refresh_after_mutation(self):
        client = app.app.test_client()
        before_generation = self.store.catalog.generation("media")
        before_audit = app._maintenance_audit_from_catalog()
        before_stats = client.get("/api/stats").get_json()
        before_library = client.get("/api/library?view=cards").get_json()

        self.store.update_file_record(str(self.paths["upgrade"]), {"resolution": "4K"})

        after_generation = self.store.catalog.generation("media")
        after_audit = app._maintenance_audit_from_catalog()
        after_stats = client.get("/api/stats").get_json()
        after_library = client.get("/api/library?view=cards").get_json()
        status = client.get("/api/library/status").get_json()
        self.assertEqual(after_generation, before_generation + 1)
        self.assertEqual(before_audit["generation"], before_generation)
        self.assertEqual(after_audit["generation"], after_generation)
        self.assertEqual(before_library["catalog_generation"], before_generation)
        self.assertEqual(after_library["catalog_generation"], after_generation)
        self.assertEqual(status["catalog_generation"], after_generation)
        self.assertEqual(before_audit["summary"]["upgrade_candidates"], 1)
        self.assertEqual(after_audit["summary"]["upgrade_candidates"], 0)
        self.assertEqual(before_stats["low_quality_count"], 1)
        self.assertEqual(after_stats["low_quality_count"], 0)

    def test_duplicate_upgrade_unmatched_and_rename_contracts_are_catalog_backed(self):
        audit = app._maintenance_audit_from_catalog()
        self.assertEqual(audit["summary"]["duplicate_groups"], 1)
        self.assertEqual(audit["summary"]["upgrade_candidates"], 1)
        self.assertEqual(audit["summary"]["unmatched_files"], 2)

        old_path = self.paths["imported"]
        new_path = old_path.with_name("Newly Imported (2024) [1080p].mkv")
        os.rename(old_path, new_path)
        app._migrate_library_path(str(old_path), str(new_path))

        candidates = self.store.catalog.store.audit_library_candidates()
        self.assertTrue(any(candidate["path"] == str(new_path) for candidate in candidates))
        self.assertFalse(any(candidate["path"] == str(old_path) for candidate in candidates))
        file_view = app.app.test_client().get("/api/library?view=files").get_json()["items"]
        self.assertTrue(any(item["path"] == str(new_path) for item in file_view))
        self.assertTrue(any(item["path"] == str(self.paths["unmatched"]) for item in file_view))

    def test_library_cards_expose_the_authoritative_maintenance_upgrade_decision(self):
        cards = app.app.test_client().get("/api/library?view=cards").get_json()["items"]
        by_path = {item["path"]: item for item in cards}

        self.assertTrue(by_path[str(self.paths["upgrade"])]["maintenance_upgrade_candidate"])
        self.assertFalse(by_path[str(self.paths["corrected"])]["maintenance_upgrade_candidate"])

    def test_owned_collection_resolves_from_sql_when_tmdb_and_collection_cache_are_unavailable(self):
        original_cache = app._tmdb_collection_cache
        app._tmdb_collection_cache = {}
        try:
            with patch("app.urllib.request.urlopen", side_effect=AssertionError("owned collection reads must remain SQL-only")), \
                    patch("app._fresh_library_cache_items", side_effect=AssertionError("catalog reads must not stat legacy library roots")):
                response = app.app.test_client().get("/api/library/collection/44")
        finally:
            app._tmdb_collection_cache = original_cache

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["source"], "library_sql")
        self.assertEqual(payload["owned_count"], 1)
        self.assertEqual(payload["parts"][0]["tmdb_id"], "400")

    def test_manual_identity_and_overrides_refresh_library_ownership_stats_and_maintenance(self):
        client = app.app.test_client()
        before_generation = self.store.catalog.generation("media")
        before_stats = client.get("/api/stats").get_json()
        before_audit = app._maintenance_audit_from_catalog()
        path = self.paths["unmatched"]

        self.store.apply_tmdb_match(str(path), {
            "tmdb_id": "700",
            "imdb_id": "tt0000700",
            "title": "Recovered Identity",
            "year": "2025",
            "plot": "Recovered without a provider call during read.",
            "poster_url": "https://poster.example/recovered.jpg",
        })
        self.store.save_metadata_override({"tmdb_id": "700", "title": "Recovered Identity", "year": "2025"}, "Recovered Identity (Edited)", "2025")
        poster_override = self.store.save_poster_override(
            {"tmdb_id": "700", "title": "Recovered Identity", "year": "2025"},
            "fixture",
            b"recovered-poster",
            ".jpg",
        )

        after_generation = self.store.catalog.generation("media")
        library = client.get("/api/library?view=cards").get_json()
        ownership = client.post("/api/library/check", json={
            "movies": [{"tmdb_id": "700", "title": "Recovered Identity", "year": "2025"}],
        }).get_json()
        after_stats = client.get("/api/stats").get_json()
        after_audit = app._maintenance_audit_from_catalog()
        status = client.get("/api/library/status").get_json()
        item = next(row for row in library["items"] if row["path"] == str(path))

        self.assertGreater(after_generation, before_generation)
        self.assertEqual(status["catalog_generation"], after_generation)
        self.assertEqual(item["canonical_metadata"]["title"], "Recovered Identity (Edited)")
        self.assertEqual(item["canonical_metadata"]["poster_url"], poster_override["poster_url"])
        self.assertTrue(ownership["results"][0]["found"])
        self.assertEqual(before_stats["unmatched_count"], 2)
        self.assertEqual(after_stats["unmatched_count"], 1)
        self.assertEqual(before_audit["summary"]["unmatched_files"], 2)
        self.assertEqual(after_audit["summary"]["unmatched_files"], 1)

    def test_rename_and_delete_refresh_catalog_backed_pages_and_ownership(self):
        client = app.app.test_client()
        old_path = self.paths["imported"]
        renamed_path = old_path.with_name("Newly Imported (2024) [1080p].mkv")
        before_rename_generation = self.store.catalog.generation("media")

        os.rename(old_path, renamed_path)
        app._migrate_library_path(str(old_path), str(renamed_path))

        after_rename_generation = self.store.catalog.generation("media")
        renamed_library = client.get("/api/library?view=files").get_json()
        self.assertGreater(after_rename_generation, before_rename_generation)
        self.assertTrue(any(item["path"] == str(renamed_path) for item in renamed_library["items"]))

        deleted_path = self.paths["custom_poster"]
        before_delete_stats = client.get("/api/stats").get_json()
        before_delete_generation = self.store.catalog.generation("media")
        deleted = app._delete_library_file(str(deleted_path), use_trash=False)

        after_delete_generation = self.store.catalog.generation("media")
        after_delete_library = client.get("/api/library?view=cards").get_json()
        after_delete_ownership = client.post("/api/library/check", json={
            "movies": [{"tmdb_id": "500", "title": "Custom Poster", "year": "2023"}],
        }).get_json()
        after_delete_stats = client.get("/api/stats").get_json()
        after_delete_audit = app._maintenance_audit_from_catalog()

        self.assertTrue(deleted["success"])
        self.assertGreater(after_delete_generation, before_delete_generation)
        self.assertFalse(any(item["path"] == str(deleted_path) for item in after_delete_library["items"]))
        self.assertFalse(after_delete_ownership["results"][0]["found"])
        self.assertEqual(after_delete_stats["total_files"], before_delete_stats["total_files"] - 1)
        self.assertEqual(after_delete_audit["generation"], after_delete_generation)

    def test_completed_import_invalidates_runtime_cache_before_reconciliation_persists_the_new_generation(self):
        manager = unittest.mock.Mock()
        app._library_cache = {"items": [{"path": str(self.paths["imported"])}]}
        generation = self.store.catalog.generation("media")
        completion = [{
            "hash": "fixture-import",
            "state": "imported",
            "library_scan_pending": True,
            "imported_paths": [str(self.paths["imported"])],
        }]

        with patch("app._start_library_reconcile", return_value={"status": "running"}) as start_reconcile:
            handled = app._handle_completed_qbittorrent_imports(manager, completion)

        self.assertTrue(handled)
        self.assertEqual(app._library_cache, {})
        self.assertEqual(self.store.catalog.generation("media"), generation)
        start_reconcile.assert_called_once_with(force=True)
        manager.jobs.upsert.assert_called_once_with("fixture-import", {
            "library_scan_pending": False,
            "identity_handoff": {
                "state": "deferred",
                "reason": "The download job has no stable identity",
                "paths": [],
            },
        })

    def test_cancelled_download_does_not_touch_catalog_reconciliation_or_identity_handoff(self):
        manager = unittest.mock.Mock()
        app._library_cache = {"sentinel": True}
        cancellation = [{
            "hash": "fixture-cancelled",
            "state": "cancelled",
            "identity_handoff": {"state": "not_required"},
            "imported_paths": [],
        }]

        with patch("app._metadata_store") as metadata_store, patch(
            "app._start_library_reconcile"
        ) as start_reconcile:
            handled = app._handle_completed_qbittorrent_imports(manager, cancellation)

        self.assertFalse(handled)
        self.assertEqual(app._library_cache, {"sentinel": True})
        metadata_store.assert_not_called()
        start_reconcile.assert_not_called()
        manager.jobs.upsert.assert_not_called()

    def test_failed_identity_handoff_remains_pending_for_restart_recovery(self):
        manager = unittest.mock.Mock()
        completion = [{
            "hash": "fixture-retry",
            "state": "imported",
            "library_scan_pending": True,
            "tmdb_id": "100",
            "title": "Correct Movie",
            "year": "2020",
            "imported_paths": [str(self.paths["corrected"])],
        }]

        with patch("app._apply_completed_download_identity", side_effect=RuntimeError("catalog locked")), patch(
            "app._start_library_reconcile"
        ) as start_reconcile:
            handled = app._handle_completed_qbittorrent_imports(manager, completion)

        self.assertTrue(handled)
        start_reconcile.assert_not_called()
        manager.jobs.upsert.assert_called_once_with("fixture-retry", {
            "library_scan_pending": True,
            "identity_handoff": {
                "state": "failed",
                "reason": "catalog locked",
                "paths": [],
            },
        })

    def test_imported_job_outside_library_is_deferred_once_not_replayed_forever(self):
        manager = unittest.mock.Mock()
        external = self.data_dir / "outside-library.mkv"
        external.write_bytes(b"movie")
        completion = [{
            "hash": "fixture-outside-library",
            "state": "imported",
            "library_scan_pending": False,
            "tmdb_id": "100",
            "imported_paths": [str(external)],
        }]

        with patch("app._start_library_reconcile") as start_reconcile:
            handled = app._handle_completed_qbittorrent_imports(manager, completion)

        self.assertTrue(handled)
        start_reconcile.assert_not_called()
        manager.jobs.upsert.assert_called_once_with("fixture-outside-library", {
            "library_scan_pending": False,
            "identity_handoff": {
                "state": "deferred",
                "reason": "Imported payload is outside the configured movie libraries",
                "paths": [str(external)],
            },
        })

    def test_source_review_blocks_owned_movies_before_search_and_submission(self):
        owned = {
            "tmdb_id": "100",
            "imdb_id": "tt0000100",
            "title": "Correct Movie",
            "year": "2020",
        }
        ready = {
            **owned,
            "selected": True,
            "status": "ready",
            "variant": {
                "title": "Correct Movie 2020 1080p",
                "resolution": "1080p",
                "magnet_url": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
            },
        }
        client = app.app.test_client()

        with patch("app._fetch_enabled_prowlarr_indexers", return_value=[]), patch(
            "app._ai_control_source_search",
            side_effect=AssertionError("owned movies must not perform a source lookup"),
        ):
            preview = client.post("/api/sources/review/preview", json={"movies": [owned]})
        with patch(
            "app._ai_control_submit_download",
            side_effect=AssertionError("owned movies must not submit a download"),
        ):
            submitted = client.post("/api/sources/review/submit", json={"rows": [ready]})

        self.assertEqual(preview.status_code, 200)
        preview_row = preview.get_json()["rows"][0]
        self.assertEqual(preview_row["status"], "owned")
        self.assertFalse(preview_row["selected"])
        self.assertEqual(preview_row["reason"], "Already in library")
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.get_json()["submitted_count"], 0)
        self.assertEqual(submitted.get_json()["skipped_count"], 1)

    def test_source_review_requires_a_stable_identity_before_search(self):
        client = app.app.test_client()
        with patch("app._fetch_enabled_prowlarr_indexers", return_value=[]), patch(
            "app._ai_control_source_search",
            side_effect=AssertionError("title-only rows must not perform a source lookup"),
        ):
            response = client.post("/api/sources/review/preview", json={
                "movies": [{"title": "Unidentified Movie", "year": "2026"}],
            })

        self.assertEqual(response.status_code, 200)
        row = response.get_json()["rows"][0]
        self.assertEqual(row["status"], "identity_required")
        self.assertFalse(row["selected"])
        self.assertEqual(row["reason"], "A TMDB or IMDb identity is required before download")

    def test_completed_download_hands_its_stable_identity_to_the_imported_library_file(self):
        downloaded = self._movie_path("Downloaded.Identity.2026.1080p.mkv")
        manager = unittest.mock.Mock()
        app._library_cache = {"items": [{"path": str(self.paths["imported"])}]}
        completion = [{
            "hash": "fixture-download",
            "state": "imported",
            "library_scan_pending": True,
            "imported_paths": [str(downloaded)],
            "tmdb_id": "800",
            "imdb_id": "tt0000800",
            "title": "Downloaded Identity",
            "year": "2026",
        }]

        with patch("app._fetch_tmdb_metadata_by_id", return_value={
            "tmdb_id": "800",
            "imdb_id": "tt0000800",
            "title": "Downloaded Identity",
            "year": "2026",
            "plot": "The submitted identity survives import without filename matching.",
        }), patch("app._start_library_reconcile", return_value={"status": "running"}) as start_reconcile:
            handled = app._handle_completed_qbittorrent_imports(manager, completion)

        candidate = self._candidate_for_path(downloaded)
        library_item = app._catalog_library_item(candidate, self.store, self.store.snapshot())
        ownership = app.app.test_client().post("/api/library/check", json={
            "movies": [{"tmdb_id": "800", "title": "Downloaded Identity", "year": "2026"}],
        }).get_json()["results"][0]
        job_patch = manager.jobs.upsert.call_args.args[1]

        self.assertTrue(handled)
        self.assertEqual(app._library_cache, {})
        self.assertEqual(library_item["canonical_metadata"]["tmdb_id"], "800")
        self.assertEqual(library_item["canonical_metadata"]["plot"], "The submitted identity survives import without filename matching.")
        self.assertTrue(ownership["found"])
        self.assertEqual(job_patch["identity_handoff"]["state"], "applied")
        self.assertEqual(job_patch["identity_handoff"]["paths"], [str(downloaded)])
        self.assertFalse(job_patch["library_scan_pending"])
        start_reconcile.assert_called_once_with(force=True)

    def test_imdb_download_identity_resolves_before_startup_reconciliation(self):
        downloaded = self._movie_path("IMDb.Identity.2026.1080p.mkv")
        manager = unittest.mock.Mock()
        before_generation = self.store.catalog.generation("media")
        completion = [{
            "hash": "fixture-imdb-download",
            "state": "imported",
            "library_scan_pending": True,
            "imported_paths": [str(downloaded)],
            "imdb_id": "tt0000900",
            "title": "IMDb Identity",
            "year": "2026",
        }]

        with patch("app._fetch_tmdb_metadata_by_imdb", return_value={
            "tmdb_id": "900",
            "imdb_id": "tt0000900",
            "title": "IMDb Identity",
            "year": "2026",
            "release_date": "2026-01-01",
            "plot": "An IMDb identity is resolved before the library scan.",
            "genres": ["Drama"],
            "tmdb_rating": "7.2",
        }), patch("app._start_library_reconcile", return_value={"status": "running"}):
            handled = app._handle_completed_qbittorrent_imports(manager, completion)

        generation = self.store.catalog.generation("media")
        client = app.app.test_client()
        library = client.get("/api/library?view=cards").get_json()
        stats = client.get("/api/stats").get_json()
        maintenance = app._maintenance_audit_from_catalog()
        status = client.get("/api/library/status").get_json()
        candidate = self._candidate_for_path(downloaded)
        item = app._catalog_library_item(candidate, self.store, self.store.snapshot())

        self.assertTrue(handled)
        self.assertGreater(generation, before_generation)
        self.assertEqual(item["canonical_metadata"]["tmdb_id"], "900")
        self.assertEqual(item["canonical_metadata"]["imdb_id"], "tt0000900")
        self.assertTrue(any(row["path"] == str(downloaded) for row in library["items"]))
        self.assertEqual(stats["catalog_generation"], generation)
        self.assertEqual(maintenance["generation"], generation)
        self.assertEqual(status["catalog_generation"], generation)
        self.assertEqual(manager.jobs.upsert.call_args.args[1]["identity_handoff"]["state"], "applied")

    def test_cold_start_reconciliation_uses_persisted_sql_and_keeps_pages_on_one_generation(self):
        before_generation = self.store.catalog.generation("media")
        previous_state = dict(app._library_reconcile_state)
        app._library_cache = {}
        app._stats_cache = {}
        app._maintenance_audit_cache = {"generation": None, "audit": None}
        try:
            with patch("app._active_metadata_provider", return_value="filename"), patch(
                "app.urllib.request.urlopen",
                side_effect=AssertionError("cold-start reads must use persisted SQL records"),
            ):
                app._run_library_reconcile_loop()

            client = app.app.test_client()
            library = client.get("/api/library?view=cards").get_json()
            stats = client.get("/api/stats").get_json()
            maintenance = app._maintenance_audit_from_catalog()
            status = client.get("/api/library/reconcile").get_json()
        finally:
            app._library_reconcile_state = previous_state

        after_generation = self.store.catalog.generation("media")
        self.assertGreater(after_generation, before_generation)
        self.assertEqual(status["status"], "completed")
        self.assertEqual(library["catalog_generation"], after_generation)
        self.assertEqual(stats["catalog_generation"], after_generation)
        self.assertEqual(maintenance["generation"], after_generation)
        self.assertTrue(any(
            item.get("canonical_metadata", {}).get("tmdb_id") == "100"
            for item in library["items"]
        ))


if __name__ == "__main__":
    unittest.main()
