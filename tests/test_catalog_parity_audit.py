import tempfile
import unittest
from pathlib import Path

import app
from tools.catalog_parity_audit import audit_catalog


class CatalogParityAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_user_data_dir = app._user_data_dir
        self.original_repositories = dict(app._catalog_repository_cache)
        app._user_data_dir = self.tmp.name
        app._catalog_repository_cache.clear()
        self.store = app.AppMetadataStore(Path(self.tmp.name))

    def tearDown(self):
        app._catalog_repository_cache.clear()
        app._catalog_repository_cache.update(self.original_repositories)
        app._user_data_dir = self.original_user_data_dir
        self.tmp.cleanup()

    def test_audit_accepts_sql_canonical_card_metadata_and_deferred_people(self):
        path = "E:/Movies/Parity Movie.2024.1080p.mkv"
        self.store.apply_tmdb_match(path, {
            "tmdb_id": "42",
            "imdb_id": "tt0000042",
            "title": "Parity Movie",
            "year": "2024",
            "plot": "Stored detail.",
            "cast": [{"name": "Actor"}],
            "writers": [{"id": "9", "name": "Writer", "job": "Screenplay"}],
            "keywords": ["parity", "offline"],
            "certification": "",
        })
        self.store.update_file_record(path, {"filename": "Parity Movie.2024.1080p.mkv", "resolution": "1080p"})
        self.store.save_plex_metadata(path, {"plex_title": "Parity Movie", "plex_year": "2024", "plex_summary": "Plex detail."})

        report = audit_catalog(self.tmp.name)

        self.assertTrue(report["passed"])
        self.assertEqual(report["checked_records"], 1)
        self.assertEqual(report["accepted_records"], 1)
        self.assertEqual(report["provider_calls"], 0)

    def test_audit_rejects_plex_fallback_as_completion_for_tmdb_selected_identity(self):
        path = "E:/Movies/Plex Fallback.2024.1080p.mkv"
        self.store.update_file_record(path, {
            "filename": "Plex Fallback.2024.1080p.mkv",
            "identity_status": "accepted",
            "identity_title": "Plex Fallback",
            "identity_year": "2024",
            "identity_source": "verified_tmdb",
            "display_provider": "tmdb",
            "metadata_status": "accepted",
            "metadata_accepted": True,
            "tmdb_id": "99",
        })
        self.store.save_plex_metadata(path, {
            "plex_title": "Plex Fallback",
            "plex_year": "2024",
            "plex_summary": "Persisted fallback detail.",
        })

        report = audit_catalog(self.tmp.name)

        self.assertFalse(report["passed"])
        self.assertEqual(report["active_detail_providers"], {"plex_snapshot": 1})
        self.assertEqual(len(report["violations"]["deferred_details"]), 1)
        self.assertEqual(len(report["relational"]["violations"]), 1)

    def test_audit_rejects_tmdb_display_rows_without_a_sql_snapshot(self):
        path = "E:/Movies/Missing Snapshot.2024.mkv"
        self.store.update_file_record(path, {
            "filename": "Missing Snapshot.2024.mkv",
            "identity_status": "accepted",
            "identity_title": "Missing Snapshot",
            "identity_year": "2024",
            "identity_source": "manual_tmdb",
            "display_provider": "tmdb",
            "metadata_status": "accepted",
            "metadata_accepted": True,
            "tmdb_id": "404",
        })

        report = audit_catalog(self.tmp.name)

        self.assertFalse(report["passed"])
        self.assertEqual(len(report["violations"]["deferred_details"]), 1)

    def test_audit_compares_relational_projection_to_legacy_json_contract(self):
        path = "E:/Movies/Shadow Movie.2024.mkv"
        self.store.apply_tmdb_match(path, {
            "tmdb_id": "77",
            "imdb_id": "tt0000077",
            "title": "Shadow Movie",
            "year": "2024",
            "plot": "Stored detail.",
            "cast": [{"id": "7", "name": "Actor"}],
            "directors": [{"id": "8", "name": "Director"}],
        })
        self.store.update_file_record(path, {"filename": "Shadow Movie.2024.mkv"})
        connection = self.store.catalog.store.connect()
        try:
            connection.execute(
                "UPDATE canonical_movies SET title = 'Relational projection changed' WHERE tmdb_id = '77'"
            )
            connection.commit()
        finally:
            connection.close()

        report = audit_catalog(self.tmp.name)

        self.assertFalse(report["passed"])
        self.assertEqual(len(report["violations"]["relational_shadow"]), 1)

    def test_audit_rejects_writer_or_keyword_relational_drift(self):
        path = "E:/Movies/Search Relations.2024.mkv"
        self.store.apply_tmdb_match(path, {
            "tmdb_id": "88",
            "title": "Search Relations",
            "year": "2024",
            "writers": [{"id": "18", "name": "Expected Writer", "job": "Story"}],
            "keywords": ["expected keyword"],
            "certification": "",
        })
        self.store.update_file_record(path, {"filename": "Search Relations.2024.mkv"})
        connection = self.store.catalog.store.connect()
        try:
            connection.execute(
                "DELETE FROM movie_credits WHERE snapshot_key='tmdb:88' AND credit_type='writer'"
            )
            connection.commit()
        finally:
            connection.close()

        report = audit_catalog(self.tmp.name)

        self.assertFalse(report["passed"])
        self.assertEqual(len(report["violations"]["relational_shadow"]), 1)


if __name__ == "__main__":
    unittest.main()
