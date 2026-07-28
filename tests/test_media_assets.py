import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app as cp_app
from services.catalog_repository import CatalogRepository
from services.media_assets import MediaAssetError, MediaAssetService
from tests.catalog_schema_fixtures import downgrade_catalog_to_v6_asset_fixture


class _Response:
    def __init__(self, payload, content_type="image/png", error=None):
        self.payload = payload
        self.headers = {"Content-Type": content_type}
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit=-1):
        if self.error:
            raise self.error
        return self.payload


def _png(color=(120, 30, 200), size=(24, 36)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def _documents():
    return {
        "app_metadata/files.json": {"files": {
            "e:/movies/asset.mkv": {
                "path": "E:/Movies/Asset.mkv", "filename": "Asset.mkv",
                "identity_status": "accepted", "identity_title": "Asset Movie",
                "identity_year": "2024", "identity_source": "verified_tmdb",
                "display_provider": "tmdb", "metadata_status": "accepted",
                "metadata_accepted": True, "tmdb_id": "42", "resolution": "1080p",
            }
        }},
        "app_metadata/tmdb_metadata.json": {"movies": {"42": {
            "tmdb_id": "42", "title": "Asset Movie", "year": "2024",
            "poster_url": "https://image.example/poster.png", "plot": "Offline plot.",
            "genres": ["Drama"],
            "cast": [
                {"id": "100", "name": "Shared Person", "profile_url": "https://image.example/person.png", "biography": "Do not persist me."},
                {"id": "101", "name": "Second Person", "profile_url": "https://image.example/person.png"},
            ],
            "directors": [], "updated_at": 10,
        }}},
        "app_metadata/plex_metadata.json": {"files": {}},
        "app_metadata/manual_matches.json": {"matches": {}},
        "app_metadata/poster_overrides.json": {"overrides": []},
        "user_lists.json": {"lists": [{
            "id": "saved", "name": "Saved", "movies": [{
                "tmdb_id": "99", "title": "Saved Movie", "year": "2022",
                "poster_url": "https://image.example/saved-list.png",
            }],
        }]},
        "user_collections.json": {"overrides": {}},
        "followed_releases.json": {"movies": []},
    }


class MediaAssetServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.repository = CatalogRepository(root / "user", database_path=root / "catalog.sqlite", export_delay=0)
        self.repository.store.import_documents(_documents(), {})
        self.payload = _png()
        self.service = MediaAssetService(
            self.repository, root / "Metadata",
            open_url=lambda *_args, **_kwargs: _Response(self.payload),
            soft_limit_bytes=1,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _movie_key(self):
        connection = self.repository.store.connect()
        try:
            return connection.execute("SELECT movie_key FROM canonical_movies").fetchone()[0]
        finally:
            connection.close()

    def _person_keys(self):
        connection = self.repository.store.connect()
        try:
            return [row[0] for row in connection.execute("SELECT person_key FROM people ORDER BY person_key")]
        finally:
            connection.close()

    def test_known_schema_6_asset_migration_chains_to_9_without_changing_canonical_rows(self):
        connection = self.repository.store.connect()
        try:
            before = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM canonical_movies),"
                "(SELECT COUNT(*) FROM canonical_movie_files),"
                "(SELECT COUNT(*) FROM provider_movie_snapshots)"
            ).fetchone())
            generation = self.repository.generation("media")
        finally:
            connection.close()

        downgrade_catalog_to_v6_asset_fixture(self.repository.store)
        self.repository.store.initialize()
        connection = self.repository.store.connect()
        try:
            after = tuple(connection.execute(
                "SELECT (SELECT COUNT(*) FROM canonical_movies),"
                "(SELECT COUNT(*) FROM canonical_movie_files),"
                "(SELECT COUNT(*) FROM provider_movie_snapshots)"
            ).fetchone())
            schema = int(connection.execute("SELECT value FROM catalog_meta WHERE key='schema_version'").fetchone()[0])
        finally:
            connection.close()

        self.assertEqual(schema, 10)
        self.assertEqual(after, before)
        self.assertEqual(self.repository.generation("media"), generation)

    def test_checksum_deduplicates_physical_portraits_and_local_projection_is_offline(self):
        people = self._person_keys()
        first = self.service.queue_person(people[0], "tmdb", "https://image.example/a.png")
        second = self.service.queue_person(people[1], "tmdb", "https://image.example/b.png")
        self.service.download(first)
        self.service.download(second)
        movie = self.service.queue_movie(self._movie_key(), "poster", "tmdb", "https://image.example/poster.png")
        self.service.download(movie)
        connection = self.repository.store.connect()
        try:
            projection = self.repository.store.canonical.project_path(connection, "e:/movies/asset.mkv")
        finally:
            connection.close()

        self.assertEqual(len(list(self.service.assets_root.rglob("*.png"))), 1)
        self.assertTrue(projection["poster_url"].startswith("/api/assets/"))
        self.assertTrue(all(person["profile_url"].startswith("/api/assets/") for person in projection["cast"]))
        self.assertEqual(projection["plot"], "Offline plot.")
        self.assertNotIn("biography", projection["cast"][0])

    def test_asset_generation_changes_without_catalog_generation(self):
        catalog_before = self.repository.generation("media")
        asset_before = self.repository.generation("asset")
        key = self.service.queue_movie(
            self._movie_key(), "poster", "tmdb", "https://image.example/generation.png"
        )
        self.service.download(key)

        self.assertEqual(self.repository.generation("media"), catalog_before)
        self.assertGreater(self.repository.generation("asset"), asset_before)

    def test_deleting_one_movie_preserves_unrelated_local_artwork_relationships(self):
        self.repository.upsert_record("app_metadata/tmdb_metadata.json", "43", {
            "tmdb_id": "43", "title": "Preserved Movie", "year": "2025",
            "poster_url": "https://image.example/preserved-poster.png",
            "cast": [{
                "id": "102", "name": "Preserved Person",
                "profile_url": "https://image.example/preserved-person.png",
            }],
            "directors": [],
        })
        self.repository.upsert_record("app_metadata/files.json", "e:/movies/preserved.mkv", {
            "path": "E:/Movies/Preserved.mkv", "filename": "Preserved.mkv",
            "identity_status": "accepted", "identity_title": "Preserved Movie",
            "identity_year": "2025", "identity_source": "verified_tmdb",
            "display_provider": "tmdb", "metadata_status": "accepted",
            "metadata_accepted": True, "tmdb_id": "43", "resolution": "1080p",
        })
        connection = self.repository.store.connect()
        try:
            preserved_movie_key = connection.execute(
                "SELECT movie_key FROM canonical_movies WHERE tmdb_id='43'"
            ).fetchone()[0]
            preserved_person_key = connection.execute(
                "SELECT person_key FROM people WHERE tmdb_id='102'"
            ).fetchone()[0]
        finally:
            connection.close()
        self.service.queue_movie(
            preserved_movie_key,
            "poster",
            "tmdb",
            "https://image.example/preserved-poster.png",
        )
        self.service.queue_person(
            preserved_person_key,
            "tmdb",
            "https://image.example/preserved-person.png",
        )

        self.repository.remove_path_records(["e:/movies/asset.mkv"])

        connection = self.repository.store.connect()
        try:
            deleted_movie = connection.execute(
                "SELECT COUNT(*) FROM canonical_movies WHERE tmdb_id='42'"
            ).fetchone()[0]
            preserved_movie_assets = connection.execute(
                "SELECT COUNT(*) FROM movie_assets WHERE movie_key=? AND selected=1",
                (preserved_movie_key,),
            ).fetchone()[0]
            preserved_person_assets = connection.execute(
                "SELECT COUNT(*) FROM person_assets WHERE person_key=? AND selected=1",
                (preserved_person_key,),
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(deleted_movie, 0)
        self.assertEqual(preserved_movie_assets, 1)
        self.assertEqual(preserved_person_assets, 1)

    def test_deleting_duplicate_copy_preserves_shared_movie_artwork_relationships(self):
        movie_key = self._movie_key()
        person_keys = self._person_keys()
        self.service.queue_movie(
            movie_key,
            "poster",
            "tmdb",
            "https://image.example/poster.png",
        )
        for person_key in person_keys:
            self.service.queue_person(
                person_key,
                "tmdb",
                "https://image.example/person.png",
            )
        self.repository.upsert_record("app_metadata/files.json", "e:/movies/asset-720p.mkv", {
            "path": "E:/Movies/Asset-720p.mkv", "filename": "Asset-720p.mkv",
            "identity_status": "accepted", "identity_title": "Asset Movie",
            "identity_year": "2024", "identity_source": "verified_tmdb",
            "display_provider": "tmdb", "metadata_status": "accepted",
            "metadata_accepted": True, "tmdb_id": "42", "resolution": "720p",
        })

        self.repository.remove_path_records(["e:/movies/asset-720p.mkv"])

        connection = self.repository.store.connect()
        try:
            remaining_files = connection.execute(
                "SELECT COUNT(*) FROM canonical_movie_files WHERE movie_key=?",
                (movie_key,),
            ).fetchone()[0]
            poster_links = connection.execute(
                "SELECT COUNT(*) FROM movie_assets WHERE movie_key=? AND selected=1",
                (movie_key,),
            ).fetchone()[0]
            portrait_links = connection.execute(
                "SELECT COUNT(*) FROM person_assets WHERE selected=1"
            ).fetchone()[0]
        finally:
            connection.close()

        self.assertEqual(remaining_files, 1)
        self.assertEqual(poster_links, 1)
        self.assertEqual(portrait_links, len(person_keys))

    def test_invalid_mime_partial_image_and_interrupted_download_are_retryable(self):
        key = self.service.queue_movie(
            self._movie_key(), "poster", "tmdb", "https://image.example/retry.png"
        )
        self.service.open_url = lambda *_args, **_kwargs: _Response(b"<html>nope</html>", "text/html")
        with self.assertRaises(MediaAssetError):
            self.service.download(key)
        self.service.open_url = lambda *_args, **_kwargs: _Response(self.payload[:20], "image/png")
        with self.assertRaises(MediaAssetError):
            self.service.download(key)
        self.service.open_url = lambda *_args, **_kwargs: _Response(b"", "image/png", OSError("connection lost"))
        with self.assertRaises(MediaAssetError):
            self.service.download(key)
        self.assertFalse(list(self.service.temporary_root.glob("*.part")))
        self.service.open_url = lambda *_args, **_kwargs: _Response(self.payload, "image/png")
        ready = self.service.download(key)
        self.assertEqual(ready["status"], "ready")

    def test_custom_poster_precedence_and_retention_survive_cleanup(self):
        custom = Path(self.temp.name) / "custom.png"
        custom.write_bytes(_png((1, 2, 3)))
        custom_asset = self.service.ingest_custom_file(self._movie_key(), custom)
        generation_after_custom = self.repository.generation("asset")
        repeated = self.service.ingest_custom_file(self._movie_key(), custom)
        self.assertEqual(repeated["asset_key"], custom_asset["asset_key"])
        self.assertEqual(self.repository.generation("asset"), generation_after_custom)
        provider = self.service.queue_movie(
            self._movie_key(), "poster", "tmdb", "https://image.example/provider.png"
        )
        self.service.download(provider)
        connection = self.repository.store.connect()
        try:
            projection = self.repository.store.canonical.project_path(connection, "e:/movies/asset.mkv")
        finally:
            connection.close()
        cleaned = self.service.cleanup_temporary(grace_seconds=0)

        self.assertEqual(projection["poster_url"], f"/api/assets/{custom_asset['checksum']}")
        self.assertEqual(cleaned["removed"], 0)
        self.assertTrue(Path(custom_asset["local_path"]).is_file())
        self.assertTrue(self.service.reset_custom_poster(self._movie_key()))
        self.assertTrue(Path(custom_asset["local_path"]).is_file())
        self.assertEqual(self.service.lookup(asset_key=custom_asset["asset_key"])["status"], "ready")

    def test_owned_backfill_queues_saved_list_artwork_and_retry_uses_backoff(self):
        self.service.queue_owned_artwork()
        connection = self.repository.store.connect()
        try:
            saved = connection.execute("""
                SELECT a.asset_key FROM curated_asset_refs cr
                JOIN media_assets a ON a.asset_key=cr.asset_key
                WHERE cr.curated_identity_key='tmdb:99' AND a.retention_class='saved'
            """).fetchone()
        finally:
            connection.close()
        self.assertIsNotNone(saved)

        calls = []
        self.service.open_url = lambda *_args, **_kwargs: calls.append(1) or _Response(b"bad", "image/png")
        with self.assertRaises(MediaAssetError):
            self.service.download(saved[0])
        self.service.run_backfill(limit=10, workers=1)
        connection = self.repository.store.connect()
        try:
            attempts = connection.execute(
                "SELECT attempt_count FROM media_assets WHERE asset_key=?", (saved[0],)
            ).fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(attempts, 1)

    def test_asset_route_is_checksum_bounded_and_immutable(self):
        key = self.service.queue_movie(
            self._movie_key(), "poster", "tmdb", "https://image.example/route.png"
        )
        ready = self.service.download(key)
        client = cp_app.app.test_client()
        with patch("app._media_asset_service", return_value=self.service):
            response = client.get(f"/api/assets/{ready['checksum']}")
            invalid = client.get("/api/assets/not-a-checksum")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")
        self.assertIn(ready["checksum"], response.headers["ETag"])
        self.assertEqual(invalid.status_code, 400)
        response.close()

    def test_saved_and_owned_assets_cannot_be_evicted_as_temporary_discover_data(self):
        owned_key = self.service.queue_movie(
            self._movie_key(), "poster", "tmdb", "https://image.example/owned.png"
        )
        self.service.download(owned_key)
        saved_key = self.service.queue_curated("tmdb:99", "https://image.example/saved.png")
        self.service.download(saved_key)
        with self.repository.store.transaction() as connection:
            temporary_key = self.service._ensure_asset(
                connection, "discover_poster", "tmdb", "https://image.example/temporary.png", "temporary"
            )
        self.service.download(temporary_key)
        with self.repository.store.transaction() as connection:
            connection.execute("UPDATE media_assets SET updated_at=0 WHERE asset_key=?", (temporary_key,))
        cleaned = self.service.cleanup_temporary(grace_seconds=0)

        self.assertEqual(cleaned["removed"], 1)
        self.assertIsNone(self.service.lookup(asset_key=temporary_key))
        self.assertEqual(self.service.lookup(asset_key=owned_key)["status"], "ready")
        self.assertEqual(self.service.lookup(asset_key=saved_key)["status"], "ready")


if __name__ == "__main__":
    unittest.main()
