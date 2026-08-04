import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class LibraryIngestionPerformanceTest(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CP_TEST_MODE") != "1":
            raise RuntimeError("Gate 2 tests require CP_TEST_MODE=1")
        declared = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if declared != temporary and temporary not in declared.parents:
            raise RuntimeError("CP_TEST_ROOT must be inside system temporary storage")
        self.workspace = tempfile.TemporaryDirectory(dir=declared)
        self.root = Path(self.workspace.name)
        self.movies = self.root / "movies"
        self.data = self.root / "user-data"
        self.movies.mkdir()
        self.data.mkdir()
        self.original = (
            app._movies_dirs,
            app._movies_dir,
            app._user_data_dir,
            app._library_cache,
            app._maintenance_audit_cache,
            app._maintenance_upgrade_key_cache,
        )
        app._movies_dirs = [str(self.movies)]
        app._movies_dir = str(self.movies)
        app._user_data_dir = str(self.data)
        app._library_cache = {}
        app._maintenance_audit_cache = {'generation': None, 'audit': None}
        app._maintenance_upgrade_key_cache = {'generation': None, 'paths': set()}

    def tearDown(self):
        (
            app._movies_dirs,
            app._movies_dir,
            app._user_data_dir,
            app._library_cache,
            app._maintenance_audit_cache,
            app._maintenance_upgrade_key_cache,
        ) = self.original
        self.workspace.cleanup()

    def test_ordinary_movie_view_uses_sql_without_filesystem_or_provider_work(self):
        movie = self.movies / "SQL.Authority.2026.mkv"
        movie.write_bytes(b"fixture")
        store = app.AppMetadataStore(self.data)
        store.save_tmdb_metadata({
            "tmdb_id": "910001",
            "title": "SQL Authority",
            "year": "2026",
            "genres": ["Drama"],
            "plot": "Stored metadata.",
            "cast": [],
            "directors": [],
            "writers": [],
            "certification": "",
            "keywords": [],
        })
        store.update_file_record(str(movie), {
            "filename": movie.name,
            "library_root": str(self.movies),
            "size": movie.stat().st_size,
            "identity_status": "accepted",
            "identity_title": "SQL Authority",
            "identity_year": "2026",
            "metadata_status": "accepted",
            "metadata_accepted": True,
            "enrichment_status": "complete",
            "ingest_status": "stable",
            "display_provider": "tmdb",
            "tmdb_id": "910001",
        })

        with patch(
            "app.os.path.isfile",
            side_effect=AssertionError("ordinary Movie View restatted a media path"),
        ), patch(
            "app.os.walk",
            side_effect=AssertionError("ordinary Movie View walked a media root"),
        ), patch(
            "app.probe_media_file",
            side_effect=AssertionError("ordinary Movie View invoked a probe"),
        ), patch(
            "app.urllib.request.urlopen",
            side_effect=AssertionError("ordinary Movie View called a provider"),
        ):
            response = app.app.test_client().get(
                "/api/library?view=cards&page=1&page_size=40&sort=added"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total"], 1)


if __name__ == "__main__":
    unittest.main()

