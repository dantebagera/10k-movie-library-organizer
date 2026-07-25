import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from services.catalog_store import CATALOG_SCHEMA_VERSION, CatalogError, CatalogStore
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
                "cast": [{"id": "shared-actor" if index % 5 == 0 else f"actor-{index}",
                          "name": "Shared Actor" if index % 5 == 0 else f"Actor {index}"}],
                "directors": [{"id": f"director-{index}", "name": f"Director {index}"}],
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

    def test_audit_library_candidates_return_provider_snapshots_without_filesystem_scan(self):
        with tempfile.TemporaryDirectory() as root:
            store = CatalogStore(Path(root) / "catalog.sqlite")
            store.import_documents(self._documents(), {})

            rows = store.audit_library_candidates()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], "E:/Movies/Alien.mkv")
        self.assertEqual(rows[0]["tmdb_json"]["title"], "Alien")
        self.assertEqual(rows[0]["plex_json"]["plex_title"], "Alien")

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
