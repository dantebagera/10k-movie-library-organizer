import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from services.catalog_store import (
    CATALOG_SCHEMA_VERSION,
    CatalogError,
    CatalogStore,
    _keyword_prefix_bounds,
)
from services.media_file_facts import MediaFileFacts
from tools.build_shadow_catalog import _load_documents
from tools.catalog_migration_backup import BackupError


class CatalogStoreTest(unittest.TestCase):
    def test_test_mode_refuses_catalogue_database_outside_temporary_directory(self):
        unsafe_path = Path.cwd() / "data" / "catalog" / "must-not-open.sqlite"
        with patch.dict(os.environ, {"CP_TEST_MODE": "1"}):
            with self.assertRaisesRegex(CatalogError, "operating-system temporary directory"):
                CatalogStore(unsafe_path).connect()
        self.assertFalse(unsafe_path.exists())

    def _documents(self):
        return {
            "app_metadata/files.json": {
                "files": {
                    "e:/movies/alien.mkv": {
                        "path": "E:/Movies/Alien.mkv",
                        "filename": "Alien.mkv",
                        "library_root": "E:/Movies",
                        "size": 100,
                        "resolution": "1080p",
                        "rip_source": "Blu-ray",
                        "identity_status": "accepted",
                        "identity_title": "Alien",
                        "identity_year": "1979",
                        "identity_source": "manual_tmdb",
                        "identity_revision": 3,
                        "tmdb_id": "348",
                        "imdb_id": "tt0078748",
                        "display_provider": "tmdb",
                        "metadata_status": "accepted",
                        "metadata_accepted": True,
                        "manual_lock": True,
                    }
                }
            },
            "app_metadata/tmdb_metadata.json": {
                "movies": {"348": {"tmdb_id": "348", "imdb_id": "tt0078748", "title": "Alien", "year": "1979"}}
            },
            "app_metadata/plex_metadata.json": {
                "files": {"e:/movies/alien.mkv": {"path": "E:/Movies/Alien.mkv", "plex_title": "Alien", "plex_year": "1979"}}
            },
            "app_metadata/manual_matches.json": {
                "matches": {"e:/movies/alien.mkv": {"path": "E:/Movies/Alien.mkv", "provider": "tmdb", "tmdb_id": "348", "accepted": True}}
            },
            "user_lists.json": {
                "lists": [{"id": "watched", "name": "Watched", "system_type": "watched", "movies": [{"tmdb_id": "348", "title": "Alien", "year": "1979"}]}]
            },
            "user_collections.json": {"overrides": {"10": {"name": "Alien Collection"}}},
            "followed_releases.json": {"movies": [{"tmdb_id": "679", "title": "Aliens", "year": "1986"}]},
        }

    def _expected(self):
        return {
            "file_records": 1,
            "tmdb_movies": 1,
            "plex_files": 1,
            "manual_matches": 1,
            "user_lists": 1,
            "list_movies": 1,
            "collection_overrides": 1,
            "followed_releases": 1,
        }

    def _paging_documents(self, count=85):
        files = {}
        movies = {}
        for index in range(count):
            tmdb_id = str(1000 + index)
            path = f"E:/Movies/{index:03d} - Movie's Test.mkv"
            path_key = path.lower()
            files[path_key] = {
                "path": path,
                "filename": Path(path).name,
                "library_root": "E:/Movies",
                "size": (index + 1) * 1000,
                "added_time": 10000 - index,
                "modified_time": 9000 - index,
                "resolution": "2160p" if index % 4 == 0 else "1080p" if index % 3 else "720p",
                "rip_source": "Blu-ray" if index % 2 else "WEB",
                "identity_status": "accepted",
                "identity_title": f"Movie {index:03d}",
                "identity_year": str(1980 + index % 40),
                "identity_source": "verified_tmdb",
                "display_provider": "tmdb",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "tmdb_id": tmdb_id,
            }
            movies[tmdb_id] = {
                "tmdb_id": tmdb_id,
                "imdb_id": f"tt{1000 + index:07d}",
                "title": f"Movie {index:03d}",
                "year": str(1980 + index % 40),
                "plot": f"Golden punctuation plot for movie {index:03d}.",
                "poster_url": f"https://image.example/{tmdb_id}.jpg",
                "genres": ["Drama" if index % 2 else "Action"],
                "language": "English" if index % 2 else "French",
                "country": "France" if index % 2 == 0 else "United States",
                "country_flag": "FR" if index % 2 == 0 else "US",
                "tmdb_rating": str(5 + index % 5),
                "tmdb_vote_count": 100 + index,
                "runtime": [59, 60, 149, 150][index % 4],
                "cast": [{"id": "shared-actor" if index % 5 == 0 else f"actor-{index}",
                          "name": "Shared Actor" if index % 5 == 0 else f"Actor {index}"}],
                "directors": [{"id": f"director-{index}", "name": f"Director {index}"}],
                "writers": [{
                    "id": f"writer-{index}", "name": f"Writer {index}", "job": "Screenplay",
                }],
                "keywords": [f"Keyword {index}", "shared keyword"],
                "certification": "",
                "collection": {"id": "collection-1", "name": "Golden Collection"} if index < 7 else {},
                "updated_at": index + 1,
            }
        list_movies = [
            {"tmdb_id": str(1000 + index), "title": f"Movie {index:03d}", "year": str(1980 + index % 40)}
            for index in range(0, count, 7)
        ]
        return {
            "app_metadata/files.json": {"files": files},
            "app_metadata/tmdb_metadata.json": {"movies": movies},
            "app_metadata/plex_metadata.json": {"files": {}},
            "app_metadata/manual_matches.json": {"matches": {}},
            "app_metadata/poster_overrides.json": {"overrides": [{
                "id": "custom-poster-1000", "identity_keys": ["tmdb:1000"],
                "identity": {"tmdb_id": "1000", "title": "Movie 000", "year": "1980"},
                "poster_url": "/api/library/posters/image/custom-1000.jpg",
                "source": "upload", "locked": True, "updated_at": 999,
            }]},
            "user_lists.json": {"lists": [{
                "id": "golden-list", "name": "Golden List", "movies": list_movies,
            }]},
            "user_collections.json": {"overrides": {}},
            "followed_releases.json": {"movies": []},
        }

    def test_import_preserves_identity_provider_and_user_state(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {"semantic_counts": self._expected()})
            report = store.parity_report(self._expected())
            connection = store.connect()
            try:
                media = dict(connection.execute("SELECT * FROM media_files").fetchone())
                list_item = dict(connection.execute("SELECT * FROM list_items").fetchone())
            finally:
                connection.close()

        self.assertTrue(report["passed"])
        self.assertEqual(report["schema_version"], CATALOG_SCHEMA_VERSION)
        self.assertEqual(media["tmdb_id"], "348")
        self.assertEqual(media["identity_revision"], 3)
        self.assertEqual(media["manual_lock"], 1)
        self.assertEqual(list_item["identity_key"], "tmdb:348")

    def test_parity_detects_missing_imported_rows(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})
            connection = store.connect()
            try:
                connection.execute("DELETE FROM tmdb_movies")
                connection.commit()
            finally:
                connection.close()

            report = store.parity_report(self._expected())

        self.assertFalse(report["passed"])
        self.assertEqual(report["mismatches"]["tmdb_movies"], {"expected": 1, "actual": 0})

    def test_schema_uses_identity_and_quality_indexes(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.initialize()
            connection = store.connect()
            try:
                indexes = {
                    row["name"]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
                }
            finally:
                connection.close()

        self.assertIn("idx_media_files_tmdb_id", indexes)
        self.assertIn("idx_media_files_title_year", indexes)
        self.assertIn("idx_media_files_quality", indexes)
        self.assertIn("idx_media_identity_key", indexes)

    def test_library_and_file_projections_expose_the_same_measured_facts(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})
            facts = MediaFileFacts(
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
                probe_size=100,
                probe_modified_time=0,
            ).as_record()
            with store.transaction() as connection:
                report = store.apply_file_facts_batch(connection, [{
                    "path_key": "e:/movies/alien.mkv",
                    "expected_size": 100,
                    "expected_modified_time": 0,
                    "facts": facts,
                }])
            library = store.library_projection()[0]
            inventory = store.file_inventory()[0]
            measured_1080 = store.library_page({"resolution": "1080p"})
            measured_720 = store.library_page({"resolution": "720p"})
            upgrade = store.library_page({
                "resolution": "upgrade",
                "upgrade_path_keys": ["e:/movies/alien.mkv"],
            })

        self.assertEqual(report, {"changed": 1, "rejected": 0})
        for projection in (library, inventory):
            self.assertEqual((projection["video_width"], projection["video_height"]), (1800, 960))
            self.assertEqual(projection["video_codec"], "HEVC")
            self.assertEqual(projection["video_bit_depth"], 10)
            self.assertEqual(projection["quality_class"], "1080p")
            self.assertEqual(projection["resolution"], "1080p")
            self.assertEqual(projection["probe_status"], "ok")
        self.assertEqual(measured_1080["total"], 1)
        self.assertEqual(measured_720["total"], 0)
        self.assertEqual(upgrade["total"], 1)

    def test_ownership_candidates_support_all_existing_identity_aliases(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})

            by_tmdb = store.ownership_candidates(["tmdb:348"])
            by_imdb = store.ownership_candidates(["imdb:tt0078748"])
            by_title = store.ownership_candidates(["title:alien|1979"])

        self.assertEqual([row["path"] for row in by_tmdb], ["E:/Movies/Alien.mkv"])
        self.assertEqual([row["path"] for row in by_imdb], ["E:/Movies/Alien.mkv"])
        self.assertEqual([row["path"] for row in by_title], ["E:/Movies/Alien.mkv"])
        self.assertEqual(by_tmdb[0]["tmdb_json"]["title"], "Alien")

    def test_ownership_candidates_batch_identity_keys_without_n_plus_one(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(20), {})
            statements = []
            original_connect = store.connect

            def traced_connect():
                connection = original_connect()
                connection.set_trace_callback(statements.append)
                return connection

            store.connect = traced_connect
            candidates = store.ownership_candidates([
                f"tmdb:{1000 + index}"
                for index in range(20)
            ])

        reads = [
            statement for statement in statements
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))
        ]
        self.assertEqual(len(reads), 2)
        self.assertEqual(len(candidates), 20)
        self.assertEqual(
            [row["tmdb_id"] for row in candidates],
            [str(1000 + index) for index in range(20)],
        )
        self.assertEqual(
            [row["identity_keys"] for row in candidates],
            [
                [
                    f"title:movie {index:03d}|{1980 + index % 40}",
                    f"tmdb:{1000 + index}",
                ]
                for index in range(20)
            ],
        )
        self.assertEqual(candidates[0]["tmdb_json"]["title"], "Movie 000")

    def test_owned_identity_candidates_are_canonical_and_constant_query(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(20), {})
            statements = []
            original_connect = store.connect

            def traced_connect():
                connection = original_connect()
                connection.set_trace_callback(statements.append)
                return connection

            store.connect = traced_connect
            candidates = store.owned_identity_candidates(
                [f"tmdb:{1000 + index}" for index in range(20)],
                ["e:/movies/005 - movie's test.mkv"],
            )

        reads = [
            statement for statement in statements
            if statement.lstrip().upper().startswith(("SELECT", "WITH"))
        ]
        self.assertEqual(len(reads), 2)
        self.assertEqual(len(candidates), 20)
        self.assertEqual(candidates[0]["movie_key"], "tmdb:1000")
        self.assertEqual(candidates[0]["title"], "Movie 000")
        self.assertEqual(candidates[0]["imdb_id"], "")
        self.assertNotIn("tmdb_json", candidates[0])
        self.assertEqual(candidates[0]["identity_keys"], [
            "title:movie 000|1980",
            "tmdb:1000",
        ])

    def test_audit_library_candidates_return_provider_snapshots_without_filesystem_scan(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})

            rows = store.audit_library_candidates()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "E:/Movies/Alien.mkv")
        self.assertEqual(rows[0]["tmdb_json"]["title"], "Alien")
        self.assertEqual(rows[0]["plex_json"]["plex_title"], "Alien")

    def test_maintenance_candidates_use_normalized_columns_not_legacy_raw_json(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})
            with store.transaction() as connection:
                connection.execute(
                    "UPDATE media_files SET raw_json='{broken json' "
                    "WHERE path_key='e:/movies/alien.mkv'"
                )
            candidate = store.maintenance_candidates()[0]

        self.assertEqual(candidate["path"], "E:/Movies/Alien.mkv")
        self.assertEqual(candidate["identity_title"], "Alien")
        self.assertEqual(candidate["plex_json"]["plex_title"], "Alien")
        self.assertEqual(candidate["manual_json"]["provider"], "tmdb")
        self.assertEqual(candidate["tmdb_json"]["title"], "Alien")
        self.assertIsInstance(candidate["raw_json"], dict)

    def test_owned_movie_candidate_query_count_is_bounded_by_one_movie(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})

            statements = []
            original_connect = store.connect

            def traced_connect():
                connection = original_connect()
                connection.set_trace_callback(lambda statement: statements.append(statement))
                return connection

            store.connect = traced_connect
            first = store.owned_movie_candidate(path_key="e:/movies/alien.mkv")
            first_count = len(statements)

            store.connect = original_connect
            with store.transaction() as connection:
                for index in range(3700):
                    key = f"e:/movies/unmatched-{index}.mkv"
                    store._upsert_media_file(connection, key, {
                        "path": key,
                        "filename": f"unmatched-{index}.mkv",
                        "identity_status": "review",
                        "metadata_status": "needs_review",
                    })

            statements.clear()
            store.connect = traced_connect
            second = store.owned_movie_candidate(path_key="e:/movies/alien.mkv")
            second_count = len(statements)

        self.assertEqual(first["path"], "E:/Movies/Alien.mkv")
        self.assertEqual(second["relational_canonical"]["title"], "Alien")
        self.assertEqual(first_count, second_count)
        self.assertLessEqual(second_count, 12)

    def test_library_sql_paging_has_no_duplicate_or_skipped_rows(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(), {})
            expected = store.library_selection_paths({"sort": "title"})
            actual = []
            for page in range(1, 6):
                result = store.library_page({"sort": "title"}, page=page, page_size=20)
                actual.extend(row["path"] for row in result["candidates"])

        self.assertEqual(len(expected), 85)
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

    def test_advanced_library_query_uses_one_predicate_for_cards_and_selection(self):
        documents = self._paging_documents(20)
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(documents, {})
            query = {
                "version": 1,
                "scope": "library",
                "mode": "advanced",
                "groups": [
                    {"type": "genre", "join": "or", "values": [
                        {"id": "Action", "label": "Action"},
                        {"id": "Drama", "label": "Drama"},
                    ]},
                    {"type": "year", "values": [{"operator": "between", "from": 1985, "to": 1995}]},
                    {"type": "rating", "values": [{"operator": "at_least", "value": 6}]},
                ],
                "sort": {"key": "year-desc", "direction": "desc"},
            }
            page = store.library_page(query=query, page=1, page_size=5)
            selection = store.library_selection_paths(query=query)

        self.assertEqual(page["total"], len(selection))
        self.assertEqual([row["path"] for row in page["candidates"]], selection[:5])
        self.assertEqual(len(selection), len(set(selection)))

    def test_advanced_library_repeatable_and_or_people_keywords_and_lists(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(12), {})

            def query(group):
                return {
                    "version": 1, "scope": "library", "mode": "advanced",
                    "groups": [group], "sort": {"key": "title", "direction": "asc"},
                }

            genre_or = store.library_selection_paths(query=query({
                "type": "genre", "join": "or", "values": [
                    {"id": "Action", "label": "Action"}, {"id": "Drama", "label": "Drama"},
                ],
            }))
            genre_and = store.library_selection_paths(query=query({
                "type": "genre", "join": "and", "values": [
                    {"id": "Action", "label": "Action"}, {"id": "Drama", "label": "Drama"},
                ],
            }))
            person_and = store.library_selection_paths(query=query({
                "type": "person", "join": "and", "values": [
                    {"id": "shared-actor", "label": "Shared Actor", "role": "actor"},
                    {"id": "writer-5", "label": "Writer 5", "role": "writer"},
                ],
            }))
            keyword_and = store.library_selection_paths(query=query({
                "type": "keyword", "join": "and", "values": [
                    {"id": "shared keyword", "label": "shared keyword"},
                    {"id": "keyword 3", "label": "Keyword 3"},
                ],
            }))
            listed = store.library_selection_paths(query=query({
                "type": "movie_list", "join": "or", "values": [
                    {"id": "golden-list", "label": "Golden List"},
                ],
            }))

        self.assertEqual(len(genre_or), 12)
        self.assertEqual(genre_and, [])
        self.assertEqual([Path(path).name for path in person_and], ["005 - Movie's Test.mkv"])
        self.assertEqual([Path(path).name for path in keyword_and], ["003 - Movie's Test.mkv"])
        self.assertEqual(len(listed), 2)

    def test_advanced_library_runtime_boundaries_exclude_unknown_facts(self):
        documents = self._paging_documents(4)
        documents["app_metadata/tmdb_metadata.json"]["movies"]["1000"]["runtime"] = None
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(documents, {})

            def paths(preset):
                query = {
                    "version": 1, "scope": "library", "mode": "advanced",
                    "groups": [{"type": "runtime", "values": [{"preset": preset}]}],
                    "sort": {"key": "title", "direction": "asc"},
                }
                return [Path(path).name for path in store.library_selection_paths(query=query)]

            short = paths("short")
            feature = paths("feature")
            long = paths("long")

        self.assertEqual(short, [])
        self.assertEqual(feature, ["001 - Movie's Test.mkv", "002 - Movie's Test.mkv"])
        self.assertEqual(long, ["003 - Movie's Test.mkv"])

    def test_movie_view_hides_new_pending_publications_but_preserves_legacy_rows(self):
        documents = self._paging_documents(2)
        file_records = list(documents["app_metadata/files.json"]["files"].values())
        file_records[1]["movie_view_publication"] = "pending"
        pending_tmdb_id = file_records[1]["tmdb_id"]
        documents["app_metadata/tmdb_metadata.json"]["movies"][pending_tmdb_id]["keywords"] = [
            {"id": "pending-only", "name": "PendingOnly"}
        ]
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(documents, {})
            page = store.library_page({"sort": "title"}, page=1, page_size=20)
            selection = store.library_selection_paths({"sort": "title"})
            keywords = store.library_keywords("PendingOnly", page=1, page_size=20)

        self.assertEqual(page["total"], 1)
        self.assertEqual([row["path"] for row in page["candidates"]], [file_records[0]["path"]])
        self.assertEqual(selection, [file_records[0]["path"]])
        self.assertEqual(keywords["total_results"], 0)

    def test_library_sql_combined_filters_people_lists_and_custom_poster(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(), {})
            combined = store.library_selection_paths({
                "query": "punctuation", "genre": "Action", "language": "French",
                "country": "FR", "year_from": "1990", "year_to": "2010",
                "min_rating": "7", "resolution": "4k", "source": "WEB", "sort": "year-desc",
            })
            people = store.library_selection_paths({
                "role": "cast", "person_id": "shared-actor", "person_name": "Shared Actor", "sort": "added",
            })
            listed = store.library_selection_paths({"list_id": "golden-list", "sort": "added"})
            first = store.library_page({"query": "Movie 000", "sort": "title"}, page=1, page_size=10)

        self.assertTrue(combined)
        self.assertTrue(all(int(Path(path).name[:3]) % 4 == 0 for path in combined))
        self.assertEqual(len(people), 17)
        self.assertEqual(len(listed), 13)
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["candidates"][0]["relational_canonical"]["poster_url"],
                         "/api/library/posters/image/custom-1000.jpg")

    def test_existing_movies_query_searches_title_year_filename_path_plot_and_genre(self):
        documents = self._paging_documents(1)
        file_record = next(iter(documents["app_metadata/files.json"]["files"].values()))
        file_record["path"] = "E:/PathBeacon/Feature/Feature.FilenameBeacon.mkv"
        file_record["filename"] = "Feature.FilenameBeacon.mkv"
        file_record["identity_title"] = "TitleBeacon"
        movie = documents["app_metadata/tmdb_metadata.json"]["movies"]["1000"]
        movie.update({
            "title": "TitleBeacon",
            "year": "1980",
            "plot": "A PlotBeacon remains searchable.",
            "genres": ["GenreBeacon"],
        })

        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(documents, {})
            results = {
                query: store.library_page({"query": query, "sort": "title"}, page=1, page_size=10)["total"]
                for query in ("TitleBeacon", "1980", "FilenameBeacon", "PathBeacon", "PlotBeacon", "GenreBeacon")
            }

        self.assertEqual(results, {
            "TitleBeacon": 1,
            "1980": 1,
            "FilenameBeacon": 1,
            "PathBeacon": 1,
            "PlotBeacon": 1,
            "GenreBeacon": 1,
        })

    def test_library_writer_and_keyword_filters_use_relational_search_without_changing_movies_query(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(12), {})

            actor_paths = store.library_selection_paths({
                "role": "actor", "person_id": "shared-actor", "sort": "title",
            })
            director_paths = store.library_selection_paths({
                "role": "director", "person_name": "DIRECTOR 3", "sort": "title",
            })
            writer_paths = store.library_selection_paths({
                "role": "writer", "person_id": "writer-3", "sort": "title",
            })
            writer_name_paths = store.library_selection_paths({
                "role": "writer", "person_name": "WRITER 3", "sort": "title",
            })
            keyword_paths = store.library_selection_paths({
                "keyword_query": "  SHARED   KEYWORD  ", "sort": "title",
            })
            exact_keyword_paths = store.library_selection_paths({
                "keyword_name": "  KEYWORD 3  ", "sort": "title",
            })
            movies_writer_query = store.library_page(
                {"query": "Writer 3", "sort": "title"}, page=1, page_size=20,
            )
            movies_keyword_query = store.library_page(
                {"query": "shared keyword", "sort": "title"}, page=1, page_size=20,
            )

            with store.transaction() as connection:
                connection.execute("UPDATE provider_movie_snapshots SET source_json='{}'")

            writer_after_json_removal = store.library_selection_paths({
                "role": "writer", "person_id": "writer-3", "sort": "title",
            })
            keyword_after_json_removal = store.library_selection_paths({
                "keyword_name": "keyword 3", "sort": "title",
            })

        self.assertEqual(len(actor_paths), 3)
        self.assertEqual([Path(path).name for path in director_paths], ["003 - Movie's Test.mkv"])
        self.assertEqual(writer_paths, director_paths)
        self.assertEqual(writer_name_paths, writer_paths)
        self.assertEqual(len(keyword_paths), 12)
        self.assertEqual(exact_keyword_paths, writer_paths)
        self.assertEqual(movies_writer_query["total"], 0)
        self.assertEqual(movies_keyword_query["total"], 0)
        self.assertEqual(writer_after_json_removal, writer_paths)
        self.assertEqual(keyword_after_json_removal, exact_keyword_paths)

    def test_library_keyword_entities_are_normalized_deduplicated_owned_and_bounded(self):
        documents = self._paging_documents(12)
        documents["app_metadata/tmdb_metadata.json"]["movies"]["1003"]["keywords"] = [
            {"id": "501", "name": "Shared Keyword"},
            {"name": "KEYWORD 3"},
        ]
        documents["app_metadata/tmdb_metadata.json"]["movies"]["1004"]["keywords"].append(
            "رحلة عبر الزمن"
        )
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(documents, {})

            shared_result = store.library_keywords("  SHARED   KEYWORD  ", page=1, page_size=5)
            numbered_result = store.library_keywords("keyword 1", page=1, page_size=2)
            non_latin_result = store.library_keywords("رحلة")
            empty_result = store.library_keywords("does not exist", page=1, page_size=5)
            blank_result = store.library_keywords("   ")

        shared = shared_result["items"]
        self.assertEqual(shared, [{
            "keyword_key": shared[0]["keyword_key"],
            "tmdb_id": "501",
            "name": "shared keyword",
            "normalized_name": "shared keyword",
            "movie_count": 12,
        }])
        self.assertEqual(
            [(row["normalized_name"], row["movie_count"]) for row in numbered_result["items"]],
            [("keyword 1", 1), ("keyword 10", 1)],
        )
        self.assertEqual(
            [(row["normalized_name"], row["movie_count"]) for row in non_latin_result["items"]],
            [("رحلة عبر الزمن", 1)],
        )
        self.assertEqual(empty_result["items"], [])
        self.assertEqual(blank_result["items"], [])
        self.assertEqual(shared_result["page"], 1)
        self.assertEqual(shared_result["page_size"], 5)
        self.assertEqual(shared_result["total_pages"], 1)
        self.assertEqual(shared_result["total_results"], 1)
        self.assertIsInstance(shared_result["catalog_generation"], int)

    def test_library_keyword_pages_are_complete_unique_and_deterministic(self):
        documents = self._paging_documents(125)
        documents["app_metadata/tmdb_metadata.json"]["movies"]["1000"]["keywords"] = [
            "keyword",
            "shared keyword",
        ]
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(documents, {})

            first = store.library_keywords("  KEYWORD  ", page=1, page_size=50)
            middle = store.library_keywords("keyword", page=2, page_size=50)
            last = store.library_keywords("keyword", page=3, page_size=50)
            repeated_middle = store.library_keywords("keyword", page=2, page_size=50)
            out_of_range = store.library_keywords("keyword", page=999, page_size=500)

        items = [*first["items"], *middle["items"], *last["items"]]
        keys = [item["keyword_key"] for item in items]
        self.assertEqual(first["items"][0]["normalized_name"], "keyword")
        self.assertEqual([len(first["items"]), len(middle["items"]), len(last["items"])], [50, 50, 25])
        self.assertEqual(first["total_results"], 125)
        self.assertEqual(first["total_pages"], 3)
        self.assertEqual(len(keys), 125)
        self.assertEqual(len(set(keys)), 125)
        self.assertEqual(repeated_middle, middle)
        self.assertEqual(out_of_range["page"], 3)
        self.assertEqual(out_of_range["page_size"], 50)
        self.assertEqual(out_of_range["items"], last["items"])

    def test_library_keyword_pages_follow_generation_changes_without_persisted_counts(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(12), {})
            with store.transaction() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO catalog_meta(key, value) "
                    "VALUES('media_generation', '0')"
                )
            before = store.library_keywords("gate")

            with store.transaction() as connection:
                snapshot_key = connection.execute(
                    "SELECT snapshot_key FROM movie_keywords ORDER BY snapshot_key LIMIT 1"
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO keywords(keyword_key, tmdb_id, name, normalized_name) "
                    "VALUES('tmdb:gate-keyword', 'gate-keyword', 'gate keyword', 'gate keyword')"
                )
                connection.execute(
                    "INSERT INTO movie_keywords(snapshot_key, position, keyword_key) "
                    "VALUES(?, 99999, 'tmdb:gate-keyword')",
                    (snapshot_key,),
                )
                connection.execute(
                    "UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 "
                    "WHERE key='media_generation'"
                )

            inserted = store.library_keywords("gate")
            with store.transaction() as connection:
                connection.execute(
                    "DELETE FROM movie_keywords WHERE keyword_key='tmdb:gate-keyword'"
                )
                connection.execute(
                    "DELETE FROM keywords WHERE keyword_key='tmdb:gate-keyword'"
                )
                connection.execute(
                    "UPDATE catalog_meta SET value=CAST(value AS INTEGER)+1 "
                    "WHERE key='media_generation'"
                )
            deleted = store.library_keywords("gate")

        self.assertEqual(before["total_results"], 0)
        self.assertEqual(inserted["total_results"], 1)
        self.assertEqual(inserted["items"][0]["movie_count"], 1)
        self.assertEqual(deleted["total_results"], 0)
        self.assertEqual(
            [before["catalog_generation"] + 1, before["catalog_generation"] + 2],
            [inserted["catalog_generation"], deleted["catalog_generation"]],
        )

    def test_library_keyword_query_interruption_does_not_mutate_catalogue(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(125), {})
            connection = store.connect()
            before = tuple(connection.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM keywords), "
                "(SELECT COUNT(*) FROM movie_keywords), "
                "(SELECT value FROM catalog_meta WHERE key='media_generation')"
            ).fetchone())
            callbacks = 0

            def interrupt():
                nonlocal callbacks
                callbacks += 1
                return int(callbacks > 20)

            connection.set_progress_handler(interrupt, 1)
            with patch.object(store, "connect", return_value=connection):
                with self.assertRaisesRegex(sqlite3.OperationalError, "interrupted"):
                    store.library_keywords("keyword", page=2, page_size=50)

            verification = store.connect()
            try:
                after = tuple(verification.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM keywords), "
                    "(SELECT COUNT(*) FROM movie_keywords), "
                    "(SELECT value FROM catalog_meta WHERE key='media_generation')"
                ).fetchone())
            finally:
                verification.close()

        self.assertEqual(after, before)

    def test_library_keyword_query_preserves_snapshot_fallback_selection(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(1), {})
            with store.transaction() as connection:
                movie_key = connection.execute(
                    "SELECT movie_key FROM canonical_movies LIMIT 1"
                ).fetchone()[0]
                connection.execute(
                    "UPDATE canonical_movies SET selected_provider='plex' WHERE movie_key=?",
                    (movie_key,),
                )
                connection.execute(
                    "DELETE FROM provider_movie_snapshots "
                    "WHERE movie_key=? AND provider='plex'",
                    (movie_key,),
                )
            result = store.library_keywords("keyword 0")

        self.assertEqual(result["total_results"], 1)
        self.assertEqual(result["items"][0]["normalized_name"], "keyword 0")
        self.assertEqual(result["items"][0]["movie_count"], 1)

    def test_library_keyword_page_uses_two_relational_queries_and_blank_search_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(12), {})
            statements = []
            connection = store.connect()
            connection.set_trace_callback(statements.append)
            with patch.object(store, "connect", return_value=connection):
                result = store.library_keywords("keyword", page=1, page_size=50)

            blank_statements = []
            blank_connection = store.connect()
            blank_connection.set_trace_callback(blank_statements.append)
            with patch.object(store, "connect", return_value=blank_connection):
                blank = store.library_keywords("   ", page=1, page_size=50)

        relational_queries = [
            statement for statement in statements
            if "keyword_counts AS" in statement
        ]
        self.assertEqual(len(relational_queries), 2)
        self.assertNotIn("source_json", "\n".join(relational_queries))
        self.assertEqual(result["total_results"], 12)
        self.assertEqual(len(blank_statements), 1)
        self.assertNotIn("keyword_counts AS", blank_statements[0])
        self.assertEqual(blank["total_results"], 0)

    def test_library_keyword_queries_use_relational_indexes(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(12), {})

            normalized, upper_bound = _keyword_prefix_bounds("keyword")
            keyword_where, keyword_parameters = store._library_filter_sql({
                "keyword_query": "keyword",
            })
            where, parameters = store._library_filter_sql({
                "role": "writer", "person_id": "writer-3",
            })
            connection = store.connect()
            try:
                plans = [
                    str(row["detail"])
                    for row in connection.execute(
                        f"EXPLAIN QUERY PLAN {store._library_keywords_page_sql()}",
                        (normalized, upper_bound, normalized, 50, 0),
                    ).fetchall()
                ]
                plans.extend(
                    str(row["detail"])
                    for row in connection.execute(
                        f"EXPLAIN QUERY PLAN {store._library_effective_cte()} "
                        f"SELECT e.path_key FROM effective AS e{keyword_where}",
                        keyword_parameters,
                    ).fetchall()
                )
                writer_plan = [
                    str(row["detail"])
                    for row in connection.execute(
                        f"EXPLAIN QUERY PLAN {store._library_effective_cte()} "
                        f"SELECT e.path_key FROM effective AS e{where}",
                        parameters,
                    ).fetchall()
                ]
            finally:
                connection.close()

        joined = "\n".join(plans)
        self.assertIn("idx_keywords_normalized_name", joined)
        self.assertIn("idx_movie_keywords_keyword", joined)
        self.assertIn("sqlite_autoindex_movie_credits_1", "\n".join(writer_plan))

    def test_library_writer_identity_does_not_merge_same_name_people(self):
        documents = self._paging_documents(2)
        documents["app_metadata/tmdb_metadata.json"]["movies"]["1000"]["writers"] = [{
            "id": "writer-a", "name": "Shared Writer", "job": "Screenplay",
        }]
        documents["app_metadata/tmdb_metadata.json"]["movies"]["1001"]["writers"] = [{
            "id": "writer-b", "name": "Shared Writer", "job": "Story",
        }]
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(documents, {})

            first = store.library_selection_paths({
                "role": "writer", "person_id": "writer-a", "person_name": "Shared Writer",
            })
            second = store.library_selection_paths({
                "role": "writer", "person_id": "writer-b", "person_name": "Shared Writer",
            })

        self.assertEqual([Path(path).name for path in first], ["000 - Movie's Test.mkv"])
        self.assertEqual([Path(path).name for path in second], ["001 - Movie's Test.mkv"])

    def test_library_page_query_count_is_bounded_by_page_size(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(400), {})
            store.library_page({"sort": "added"}, page=1, page_size=20)
            statements = []
            original_connect = store.connect

            def traced_connect():
                connection = original_connect()
                connection.set_trace_callback(statements.append)
                return connection

            store.connect = traced_connect
            first = store.library_page({"sort": "added"}, page=1, page_size=20)
            first_count = len(statements)
            statements.clear()
            second = store.library_page({"sort": "added"}, page=20, page_size=20)
            second_count = len(statements)

        self.assertEqual(len(first["candidates"]), 20)
        self.assertEqual(len(second["candidates"]), 20)
        self.assertEqual(first_count, second_count)
        self.assertLessEqual(first_count, 11)

    def test_card_and_detail_projections_do_not_read_legacy_raw_json(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._paging_documents(12), {})
            before_page = store.library_page({"sort": "title"}, page=1, page_size=12)
            before_details = store.owned_movie_candidate(path_key="e:/movies/000 - movie's test.mkv")
            with store.transaction() as connection:
                for table in ("media_files", "tmdb_movies", "plex_files", "manual_matches"):
                    connection.execute(f"UPDATE {table} SET raw_json='{{}}'")
                connection.execute("UPDATE provider_movie_snapshots SET source_json='{}'")
                connection.execute("UPDATE identity_decisions SET raw_json='{}'")
            after_page = store.library_page({"sort": "title"}, page=1, page_size=12)
            after_details = store.owned_movie_candidate(path_key="e:/movies/000 - movie's test.mkv")

        before_cards = [row["relational_canonical"] for row in before_page["candidates"]]
        after_cards = [row["relational_canonical"] for row in after_page["candidates"]]
        self.assertEqual(after_cards, before_cards)
        self.assertEqual(after_details["relational_canonical"], before_details["relational_canonical"])
        self.assertEqual(after_details["relational_canonical"]["writers"], [{
            "id": "writer-0", "name": "Writer 0", "profile_url": "", "job": "Screenplay",
        }])
        self.assertEqual(
            after_details["relational_canonical"]["keywords"],
            ["Keyword 0", "shared keyword"],
        )

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})
            store.import_documents(self._documents(), {})

            report = store.parity_report(self._expected())

        self.assertTrue(report["passed"])

    def test_loader_ignores_historical_json_not_owned_by_catalog(self):
        with tempfile.TemporaryDirectory() as root:
            archive_path = Path(root) / "backup.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("user-data/app_metadata/files.json", json.dumps({"files": {}}))
                archive.writestr("user-data/app_metadata/backups/old/smart_match.json", "{broken")
            manifest = {
                "files": [
                    {"archive_path": "user-data/app_metadata/files.json"},
                    {"archive_path": "user-data/app_metadata/backups/old/smart_match.json"},
                ]
            }

            documents = _load_documents(archive_path, manifest)

        self.assertEqual(documents, {"app_metadata/files.json": {"files": {}}})

    def test_loader_rejects_corrupted_authoritative_document(self):
        with tempfile.TemporaryDirectory() as root:
            archive_path = Path(root) / "backup.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("user-data/app_metadata/files.json", "{broken")
            manifest = {"files": [{"archive_path": "user-data/app_metadata/files.json"}]}

            with self.assertRaises(BackupError):
                _load_documents(archive_path, manifest)


if __name__ == "__main__":
    unittest.main()
