import tempfile
import unittest
from pathlib import Path

import app
from services.identity_decision import metadata_discrepancy_proposal


class MetadataOverrideTest(unittest.TestCase):
    def setUp(self):
        self.original_dirs = app._movies_dirs
        self.original_dir = app._movies_dir
        self.original_user_data_dir = app._user_data_dir
        self.original_library_cache = dict(app._library_cache)

    def tearDown(self):
        app._movies_dirs = self.original_dirs
        app._movies_dir = self.original_dir
        app._user_data_dir = self.original_user_data_dir
        app._library_cache = self.original_library_cache

    def configure(self, movies_tmp, data_tmp):
        app._movies_dirs = [movies_tmp]
        app._movies_dir = movies_tmp
        app._user_data_dir = data_tmp
        app._library_cache = {"items": ["stale"]}

    def test_override_is_shared_by_duplicate_identity_but_not_conflicting_id(self):
        with tempfile.TemporaryDirectory() as data_tmp:
            store = app.AppMetadataStore(Path(data_tmp))
            saved = store.save_metadata_override(
                {"tmdb_id": "348", "imdb_id": "tt0078748", "title": "Alien", "year": "1979"},
                title="Alien: The Corrected Title",
                year="1979",
            )

            duplicate = store.get_metadata_override(
                {"tmdb_id": "348", "title": "Alien", "year": "1979"}
            )
            conflict = store.get_metadata_override(
                {"tmdb_id": "999", "title": "Alien", "year": "1979"}
            )

        self.assertEqual(duplicate["id"], saved["id"])
        self.assertEqual(duplicate["title"], "Alien: The Corrected Title")
        self.assertEqual(conflict, {})

    def test_override_precedes_provider_values_and_can_be_reset(self):
        with tempfile.TemporaryDirectory() as data_tmp:
            store = app.AppMetadataStore(Path(data_tmp))
            identity = {"tmdb_id": "560981", "title": "The Amusement Park", "year": "2021"}
            store.save_metadata_override(identity, title="The Amusement Park", year="1975")
            canonical = {
                "accepted": True,
                "tmdb_id": "560981",
                "title": "The Amusement Park",
                "year": "2021",
            }

            displayed = app._apply_metadata_override(canonical, identity, store=store)
            removed = store.reset_metadata_override(identity)
            reset_value = store.get_metadata_override(identity)

        self.assertEqual(displayed["title"], "The Amusement Park")
        self.assertEqual(displayed["year"], "1975")
        self.assertEqual(displayed["provider_title"], "The Amusement Park")
        self.assertEqual(displayed["provider_year"], "2021")
        self.assertTrue(displayed["metadata_override"])
        self.assertTrue(removed)
        self.assertEqual(reset_value, {})

    def test_override_api_saves_identity_level_title_year_and_resets(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as data_tmp:
            first = Path(movies_tmp) / "The.Amusement.Park.1975.mkv"
            second = Path(movies_tmp) / "The.Amusement.Park.1975.copy.mkv"
            first.write_bytes(b"one")
            second.write_bytes(b"two")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            for movie in (first, second):
                store.update_file_record(str(movie), {
                    "display_provider": "tmdb",
                    "metadata_status": "accepted",
                    "metadata_accepted": True,
                    "tmdb_id": "560981",
                    "imdb_id": "tt0061781",
                })
            store.save_tmdb_metadata({
                "tmdb_id": "560981",
                "imdb_id": "tt0061781",
                "title": "The Amusement Park",
                "year": "2021",
            })
            client = app.app.test_client()

            saved = client.post("/api/metadata/override", json={
                "path": str(first),
                "title": "The Amusement Park",
                "year": "1975",
            })
            duplicate = client.get(
                "/api/metadata/override",
                query_string={"path": str(second)},
            )
            reset = client.delete(
                "/api/metadata/override",
                json={"path": str(first)},
            )

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["effective"]["year"], "1975")
        self.assertEqual(duplicate.get_json()["override"]["year"], "1975")
        self.assertEqual(duplicate.get_json()["display_provider"], "tmdb")
        self.assertEqual(set(duplicate.get_json()["providers"]), {"tmdb", "plex", "filename"})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.get_json()["override"], {})
        self.assertEqual(app._library_cache, {})

    def test_override_api_validates_year_and_authorized_path(self):
        with tempfile.TemporaryDirectory() as movies_tmp, tempfile.TemporaryDirectory() as outside_tmp, tempfile.TemporaryDirectory() as data_tmp:
            movie = Path(movies_tmp) / "Alien.1979.mkv"
            outside = Path(outside_tmp) / "Alien.1979.mkv"
            movie.write_bytes(b"movie")
            outside.write_bytes(b"outside")
            self.configure(movies_tmp, data_tmp)
            store = app.AppMetadataStore(Path(data_tmp))
            store.update_file_record(str(movie), {
                "display_provider": "tmdb",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "tmdb_id": "348",
            })
            store.save_tmdb_metadata({"tmdb_id": "348", "title": "Alien", "year": "1979"})
            client = app.app.test_client()

            bad_year = client.post("/api/metadata/override", json={
                "path": str(movie),
                "title": "Alien",
                "year": "79",
            })
            forbidden = client.get(
                "/api/metadata/override",
                query_string={"path": str(outside)},
            )

        self.assertEqual(bad_year.status_code, 400)
        self.assertEqual(forbidden.status_code, 403)


class MetadataDiscrepancyTest(unittest.TestCase):
    def test_three_year_difference_creates_manual_discrepancy(self):
        proposal = metadata_discrepancy_proposal(
            current={
                "tmdb_id": "560981",
                "title": "The Amusement Park",
                "year": "2021",
            },
            filename_identity={"title": "The Amusement Park", "year": "1975"},
            has_override=False,
        )

        self.assertEqual(proposal["proposal_type"], "metadata_discrepancy")
        self.assertEqual(proposal["candidate"]["year"], "1975")
        self.assertFalse(proposal["preselected"])

    def test_one_or_two_year_difference_and_existing_override_are_ignored(self):
        current = {"tmdb_id": "1", "title": "Audition", "year": "2000"}
        for year in ("1999", "1998"):
            self.assertEqual(
                metadata_discrepancy_proposal(
                    current=current,
                    filename_identity={"title": "Audition", "year": year},
                    has_override=False,
                ),
                {},
            )
        self.assertEqual(
            metadata_discrepancy_proposal(
                current=current,
                filename_identity={"title": "Audition", "year": "1990"},
                has_override=True,
            ),
            {},
        )

    def test_different_title_is_not_a_year_discrepancy(self):
        self.assertEqual(
            metadata_discrepancy_proposal(
                current={"tmdb_id": "1", "title": "Wrong Movie", "year": "2021"},
                filename_identity={"title": "The Amusement Park", "year": "1975"},
                has_override=False,
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
