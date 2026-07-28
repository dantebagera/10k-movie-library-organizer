import os
import tempfile
import unittest
from pathlib import Path

from services.player_catalog import PlayerMediaError, resolve_library_media


class FakeStore:
    def __init__(self, records):
        self.records = records

    def owned_movie_candidate(self, *, path_key="", movie_key=""):
        return self.records.get(path_key)


class FakeRepository:
    def __init__(self, records):
        self.store = FakeStore(records)


class PlayerCatalogTests(unittest.TestCase):
    def test_resolves_only_authoritative_catalog_file_under_library_root(self):
        with tempfile.TemporaryDirectory() as root:
            library = Path(root) / "Movies"
            library.mkdir()
            media = library / "Movie.mkv"
            media.write_bytes(b"fixture")
            path_key = os.path.normcase(os.path.normpath(str(media)))
            repository = FakeRepository({
                path_key: {
                    "path_key": path_key,
                    "path": str(media),
                    "identity_title": "Movie",
                    "identity_year": "2024",
                    "relational_canonical": {
                        "movie_key": "tmdb:42",
                        "title": "Canonical Movie",
                        "year": "2024",
                        "poster_url": "https://image.tmdb.org/poster.jpg?token=remove",
                    },
                },
            })

            resolved = resolve_library_media(repository, path_key, [library])

        self.assertEqual(resolved["path"], str(media))
        self.assertEqual(resolved["movie_key"], "tmdb:42")
        self.assertEqual(resolved["title"], "Canonical Movie")
        self.assertEqual(
            resolved["poster_reference"],
            "https://image.tmdb.org/poster.jpg",
        )

    def test_rejects_arbitrary_paths_remote_urls_and_stale_files(self):
        with tempfile.TemporaryDirectory() as root:
            library = Path(root) / "Movies"
            outside = Path(root) / "Outside"
            library.mkdir()
            outside.mkdir()
            media = outside / "Movie.mkv"
            media.write_bytes(b"fixture")
            path_key = os.path.normcase(os.path.normpath(str(media)))
            repository = FakeRepository({
                path_key: {
                    "path_key": path_key,
                    "path": str(media),
                    "relational_canonical": {},
                },
            })

            with self.assertRaisesRegex(PlayerMediaError, "outside"):
                resolve_library_media(repository, path_key, [library])
            with self.assertRaisesRegex(PlayerMediaError, "invalid"):
                resolve_library_media(repository, "https://example.test/movie.mkv", [library])
            with self.assertRaisesRegex(PlayerMediaError, "not in"):
                resolve_library_media(repository, str(library / "Unknown.mkv"), [library])
            missing = library / "Missing.mkv"
            missing_key = os.path.normcase(os.path.normpath(str(missing)))
            repository.store.records[missing_key] = {
                "path_key": missing_key,
                "path": str(missing),
                "relational_canonical": {},
            }
            with self.assertRaisesRegex(PlayerMediaError, "missing"):
                resolve_library_media(repository, missing_key, [library])

    def test_rejects_catalog_key_mismatch(self):
        with tempfile.TemporaryDirectory() as root:
            media = Path(root) / "Movie.mkv"
            media.write_bytes(b"fixture")
            path_key = os.path.normcase(os.path.normpath(str(media)))
            repository = FakeRepository({
                path_key: {
                    "path_key": path_key + ".other",
                    "path": str(media),
                },
            })

            with self.assertRaisesRegex(PlayerMediaError, "does not match"):
                resolve_library_media(repository, path_key, [root])


if __name__ == "__main__":
    unittest.main()
