import json
import tempfile
import unittest
from pathlib import Path

from services.catalog_store import CATALOG_SCHEMA_VERSION, CatalogStore
from services.canonical_catalog import (
    CANONICAL_CARD_CONTRACT,
    CANONICAL_CARD_FIELDS,
    CANONICAL_DEFERRED_DETAIL_FIELDS,
    CANONICAL_DETAILS_CONTRACT,
    canonical_card_projection,
)


def _file(path, tmdb_id, title, year):
    return {
        "path": path,
        "filename": Path(path).name,
        "identity_status": "accepted",
        "identity_title": title,
        "identity_year": year,
        "identity_source": "verified_tmdb",
        "display_provider": "tmdb",
        "metadata_status": "accepted",
        "metadata_accepted": True,
        "tmdb_id": tmdb_id,
        "resolution": "1080p",
    }


class CanonicalCatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CatalogStore(Path(self.tmp.name) / "catalog.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def _import(self, *, include_missing_tmdb=False):
        missing_path = "e:/movies/missing.mkv"
        duplicate_a = "e:/movies/complete-a.mkv"
        duplicate_b = "e:/movies/complete-b.mkv"
        documents = {
            "app_metadata/files.json": {"files": {
                missing_path: _file("E:/Movies/Missing.mkv", "404", "Missing", "2024"),
                duplicate_a: _file("E:/Movies/Complete A.mkv", "42", "Complete", "2024"),
                duplicate_b: _file("E:/Movies/Complete B.mkv", "42", "Complete", "2024"),
            }},
            "app_metadata/tmdb_metadata.json": {"movies": {
                "42": {
                    "tmdb_id": "42",
                    "imdb_id": "tt0000042",
                    "title": "Complete",
                    "year": "2024",
                    "plot": "Canonical TMDB plot.",
                    "poster_url": "https://image.example/complete.jpg",
                    "genres": ["Drama"],
                    "cast": [{
                        "id": "100",
                        "name": "Lead Actor",
                        "character": "Lead",
                        "profile_url": "https://image.example/actor.jpg",
                    }],
                    "directors": [{
                        "id": "200",
                        "name": "Director",
                        "profile_url": "https://image.example/director.jpg",
                    }],
                    "writers": [
                        {"id": "201", "name": "Screenwriter", "job": "Screenplay"},
                    ],
                    "certification": "PG-13",
                    "keywords": ["journey", "friendship"],
                    "collection": {"id": "9", "name": "Complete Collection"},
                    "updated_at": 10,
                },
                **({
                    "404": {
                        "tmdb_id": "404",
                        "title": "Missing",
                        "year": "2024",
                        "plot": "Backfilled TMDB plot.",
                        "poster_url": "https://image.example/missing.jpg",
                        "genres": ["Thriller"],
                        "cast": [{
                            "id": "300",
                            "name": "Recovered Actor",
                            "profile_url": "https://image.example/recovered.jpg",
                        }],
                        "directors": [],
                        "writers": [],
                        "certification": "",
                        "keywords": [],
                        "updated_at": 20,
                    }
                } if include_missing_tmdb else {}),
            }},
            "app_metadata/plex_metadata.json": {"files": {
                missing_path: {
                    "path": "E:/Movies/Missing.mkv",
                    "plex_title": "Missing",
                    "plex_year": "2024",
                    "plex_summary": "Plex fallback remains displayable.",
                    "plex_cast": [{"name": "Fallback Actor"}],
                    "plex_directors": [{"name": "Fallback Director"}],
                }
            }},
            "app_metadata/manual_matches.json": {"matches": {}},
            "app_metadata/poster_overrides.json": {"overrides": [{
                "id": "poster-42",
                "identity": {"tmdb_id": "42", "title": "Complete", "year": "2024"},
                "identity_keys": ["tmdb:42"],
                "poster_url": "/api/library/posters/image/custom.jpg",
                "source": "upload",
                "locked": True,
                "updated_at": 30,
            }]},
        }
        self.store.import_documents(documents, {})
        return missing_path, duplicate_a, duplicate_b

    def test_schema_v6_normalizes_movie_people_credits_genres_collections_and_overrides(self):
        _, duplicate_a, duplicate_b = self._import()
        connection = self.store.connect()
        try:
            schema_version = int(connection.execute(
                "SELECT value FROM catalog_meta WHERE key='schema_version'"
            ).fetchone()[0])
            projection_a = self.store.canonical.project_path(connection, duplicate_a)
            projection_b = self.store.canonical.project_path(connection, duplicate_b)
            movie_count = connection.execute("SELECT COUNT(*) FROM canonical_movies").fetchone()[0]
            file_count = connection.execute("SELECT COUNT(*) FROM canonical_movie_files").fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(schema_version, CATALOG_SCHEMA_VERSION)
        self.assertEqual(movie_count, 2)
        self.assertEqual(file_count, 3)
        self.assertEqual(projection_a, projection_b)
        self.assertEqual(projection_a["cast"][0]["id"], "100")
        self.assertEqual(projection_a["directors"][0]["profile_url"], "https://image.example/director.jpg")
        self.assertEqual(projection_a["genres"], ["Drama"])
        self.assertEqual(projection_a["collection"]["name"], "Complete Collection")
        self.assertEqual(projection_a["writers"][0]["name"], "Screenwriter")
        self.assertEqual(projection_a["certification"], "PG-13")
        self.assertEqual(projection_a["keywords"], ["journey", "friendship"])
        self.assertEqual(projection_a["poster_url"], "/api/library/posters/image/custom.jpg")
        self.assertTrue(projection_a["poster_override"])

    def test_tmdb_selected_movie_with_only_plex_fallback_is_incomplete(self):
        missing_path, _, _ = self._import()
        connection = self.store.connect()
        try:
            projection = self.store.canonical.project_path(connection, missing_path)
            report = self.store.canonical.strict_report(connection)
        finally:
            connection.close()

        self.assertEqual(projection["selected_provider"], "tmdb")
        self.assertFalse(projection["selected_provider_snapshot"])
        self.assertTrue(projection["fallback_active"])
        self.assertEqual(projection["detail_provider"], "plex_snapshot")
        self.assertEqual(projection["plot"], "Plex fallback remains displayable.")
        self.assertEqual(projection["enrichment_status"], "incomplete")
        self.assertFalse(report["passed"])
        self.assertEqual(len(report["violations"]), 1)

    def test_tmdb_backfill_replaces_fallback_and_completes_people_contract(self):
        missing_path, _, _ = self._import(include_missing_tmdb=True)
        connection = self.store.connect()
        try:
            projection = self.store.canonical.project_path(connection, missing_path)
            report = self.store.canonical.strict_report(connection)
        finally:
            connection.close()

        self.assertTrue(projection["selected_provider_snapshot"])
        self.assertFalse(projection["fallback_active"])
        self.assertEqual(projection["detail_provider"], "tmdb_snapshot")
        self.assertEqual(projection["plot"], "Backfilled TMDB plot.")
        self.assertEqual(projection["cast"][0]["id"], "300")
        self.assertEqual(projection["enrichment_status"], "complete")
        self.assertTrue(report["passed"])

    def test_named_card_and_details_contracts_make_deferred_fields_explicit(self):
        _, duplicate_a, _ = self._import()
        connection = self.store.connect()
        try:
            details = self.store.canonical.project_path(connection, duplicate_a)
        finally:
            connection.close()
        card = canonical_card_projection(details)

        self.assertEqual(card["projection_contract"], CANONICAL_CARD_CONTRACT)
        self.assertEqual(details["projection_contract"], CANONICAL_DETAILS_CONTRACT)
        self.assertEqual(card["deferred_fields"], list(CANONICAL_DEFERRED_DETAIL_FIELDS))
        self.assertEqual(details["deferred_fields"], [])
        self.assertTrue(set(CANONICAL_CARD_FIELDS).issubset(card))
        self.assertFalse(set(CANONICAL_DEFERRED_DETAIL_FIELDS).intersection(card))
        for field in CANONICAL_CARD_FIELDS:
            self.assertEqual(card[field], details[field], field)

    def test_detail_contract_backfill_query_only_returns_stale_selected_tmdb_snapshots(self):
        _, duplicate_a, _ = self._import()
        connection = self.store.connect()
        try:
            self.assertEqual(
                self.store.canonical.tmdb_detail_contract_backfill_ids(connection),
                ["404"],
            )
            connection.execute(
                "UPDATE provider_movie_snapshots SET source_json=? WHERE snapshot_key='tmdb:42'",
                (json.dumps({"tmdb_id": "42", "title": "Complete"}),),
            )
            self.assertEqual(
                self.store.canonical.tmdb_detail_contract_backfill_ids(connection),
                ["404", "42"],
            )
            connection.execute(
                "UPDATE provider_movie_snapshots SET source_json=? WHERE snapshot_key='tmdb:42'",
                (json.dumps({
                    "tmdb_id": "42",
                    "title": "Complete",
                    "writers": [],
                    "certification": "",
                    "keywords": [],
                }),),
            )
            self.assertEqual(
                self.store.canonical.tmdb_detail_contract_backfill_ids(connection),
                ["404"],
            )
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
