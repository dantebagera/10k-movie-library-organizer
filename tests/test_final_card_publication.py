import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from services.catalog_repository import CatalogRepository
from services.canonical_catalog import canonical_card_projection
from services.media_file_facts import FILE_FACTS_VERSION, QUALITY_CLASSIFIER_VERSION

import app


def _candidate(**overrides):
    raw = {
        "path": "C:/fixture/Movie.mkv", "ingest_status": "stable",
        "probe_status": "ok", "probe_size": 100, "size": 100,
        "probe_modified_time": 20, "modified_time": 20, "probe_error": "",
        "metadata_accepted": True, "identity_status": "accepted",
        "file_facts_version": FILE_FACTS_VERSION,
        "classifier_version": QUALITY_CLASSIFIER_VERSION,
    }
    card = canonical_card_projection({
        "accepted": True, "movie_key": "tmdb:1", "title": "Movie", "year": "2026",
        "selected_provider": "tmdb", "selected_provider_snapshot": True,
        "enrichment_status": "complete", "fallback_active": False,
        "people_status": "empty", "poster_url": "", "local_poster_url": "",
    })
    raw.update(overrides.pop("raw", {})); card.update(overrides.pop("card", {}))
    return {"raw_json": raw, "relational_canonical": card, **overrides}


class FinalCardPublicationTests(unittest.TestCase):
    def _repository(self, candidate):
        repository = object.__new__(CatalogRepository)
        repository._lock = threading.RLock()
        repository._cache = {}
        repository.store = Mock()
        transaction = MagicMock()
        connection = Mock()

        def execute(statement, parameters=()):
            if "SELECT status, checksum, local_path FROM media_assets" in statement:
                checksum = str(parameters[0])
                cursor = Mock()
                cursor.fetchone.return_value = ("ready", checksum, str(Path(__file__).resolve()))
                return cursor
            return Mock()

        connection.execute.side_effect = execute
        transaction.__enter__.return_value = connection
        repository.store.transaction.return_value = transaction
        repository.store._candidates_for_path_keys.return_value = [candidate]
        repository.schedule_export = Mock()
        return repository

    def test_complete_no_poster_terminal_card_is_publishable(self):
        result = self._repository(_candidate()).final_card_publication(["C:/fixture/Movie.mkv"])
        self.assertEqual(result, [{"path": "C:/fixture/Movie.mkv", "movie_key": "tmdb:1"}])

    def test_probe_metadata_and_poster_failures_cannot_publish(self):
        cases = [
            _candidate(raw={"probe_status": "pending"}),
            _candidate(raw={"metadata_accepted": False}),
            _candidate(raw={"identity_status": "conflict"}),
            _candidate(card={"selected_provider_snapshot": False}),
            _candidate(card={"enrichment_status": "incomplete"}),
            _candidate(card={"people_status": "missing"}),
            _candidate(card={"title": ""}),
            _candidate(card={"poster_url": "https://image.invalid/poster.jpg"}),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertEqual(self._repository(candidate).final_card_publication(["x"]), [])

    def test_verified_local_poster_is_publishable(self):
        local_url = "/api/assets/" + "a" * 64
        candidate = _candidate(card={"poster_url": local_url, "local_poster_url": local_url})
        self.assertEqual(len(self._repository(candidate).final_card_publication(["x"])), 1)

    def test_remote_poster_is_cached_and_checksum_verified_before_publication(self):
        repository = Mock()
        repository.library_candidates_for_paths.return_value = [{
            "relational_canonical": {
                "movie_key": "tmdb:1",
                "selected_provider": "tmdb",
                "poster_url": "https://image.invalid/poster.jpg",
                "remote_poster_url": "https://image.invalid/poster.jpg",
                "local_poster_url": "",
            }
        }]
        service = Mock()
        service.queue_movie.return_value = "asset-key"
        with tempfile.TemporaryDirectory() as root:
            poster = Path(root) / "poster.jpg"
            poster.write_bytes(b"verified fixture")
            service.download.return_value = {
                "status": "ready",
                "checksum": "a" * 64,
                "local_path": str(poster),
            }
            with (
                patch.object(app, "_catalog_repository", return_value=repository),
                patch.object(app, "_media_asset_service", return_value=service),
            ):
                app._prepare_final_card_assets(["C:/fixture/Movie.mkv"])

        service.queue_movie.assert_called_once_with(
            "tmdb:1",
            "poster",
            "tmdb",
            "https://image.invalid/poster.jpg",
            retention_class="owned",
            selected=True,
        )
        service.download.assert_called_once_with("asset-key")

    def _transaction_repository(self, root):
        path = "C:/fixture/Atomic Movie.mkv"
        file_record = {
            "path": path,
            "filename": "Atomic Movie.mkv",
            "library_root": "C:/fixture",
            "size": 100,
            "modified_time": 20,
            "identity_status": "accepted",
            "identity_title": "Atomic Movie",
            "identity_year": "2026",
            "identity_source": "verified_tmdb",
            "tmdb_id": "1",
            "display_provider": "tmdb",
            "metadata_status": "accepted",
            "metadata_accepted": True,
            "movie_view_publication": "pending",
        }
        documents = {
            "app_metadata/files.json": {"files": {path: file_record}},
            "app_metadata/tmdb_metadata.json": {"movies": {"1": {
                "tmdb_id": "1", "title": "Atomic Movie", "year": "2026",
                "poster_url": "", "enrichment_status": "complete",
            }}},
            "app_metadata/plex_metadata.json": {"files": {}},
            "app_metadata/manual_matches.json": {"matches": {}},
            "user_lists.json": {"lists": []},
            "user_collections.json": {"overrides": {}},
            "followed_releases.json": {"movies": []},
        }
        repository = CatalogRepository(
            Path(root) / "user-data",
            database_path=Path(root) / "catalog.sqlite",
            auto_export=False,
        )
        repository.store.import_documents(documents, {})
        connection = repository.store.connect()
        try:
            path_key = connection.execute(
                "SELECT path_key FROM media_files LIMIT 1"
            ).fetchone()[0]
        finally:
            connection.close()
        candidate = _candidate(
            path_key=path_key,
            raw={"path": path, "movie_view_publication": "pending"},
            card={"title": "Atomic Movie"},
        )
        repository.schedule_export = Mock()
        return repository, path, candidate

    def test_pending_row_is_hidden_until_atomic_publication_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            repository, path, candidate = self._transaction_repository(root)
            self.assertEqual(repository.library_page()["total"], 0)
            before = repository.generation("media")
            ready_candidate = _candidate(
                path_key=candidate["path_key"],
                raw={"path": path, "movie_view_publication": "ready"},
                card={"title": "Atomic Movie"},
            )
            with patch.object(
                repository.store,
                "_candidates_for_path_keys",
                side_effect=([candidate], [ready_candidate], [ready_candidate]),
            ):
                self.assertEqual(len(repository.final_card_publication([path])), 1)
                after = repository.generation("media")
                self.assertEqual(repository.library_page()["total"], 1)
                self.assertEqual(after, before + 1)
                self.assertEqual(len(repository.final_card_publication([path])), 1)
                self.assertEqual(repository.generation("media"), after)
            repository.close()

    def test_publication_transaction_rollback_keeps_row_hidden_and_generation_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            repository, path, candidate = self._transaction_repository(root)
            before = repository.generation("media")
            with (
                patch.object(repository.store, "_candidates_for_path_keys", return_value=[candidate]),
                patch.object(repository, "_bump_generation", side_effect=RuntimeError("injected")),
                self.assertRaisesRegex(RuntimeError, "injected"),
            ):
                repository.final_card_publication([path])
            self.assertEqual(repository.library_page()["total"], 0)
            self.assertEqual(repository.generation("media"), before)
            repository.close()


if __name__ == "__main__":
    unittest.main()
