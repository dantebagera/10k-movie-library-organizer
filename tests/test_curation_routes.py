import unittest

from services.curation_routes import project_owned_list_identities


class CurationRouteProjectionTest(unittest.TestCase):
    def test_legacy_membership_is_projected_from_owned_catalog_without_mutating_storage(self):
        lists = [{
            "id": "watched",
            "system_type": "watched",
            "movies": [{
                "title": "Michael",
                "year": "2026",
                "path": "E:/Movies/Michael.2026.mkv",
                "watched_at": 123,
            }],
        }]
        owned = [{
            "movie_key": "tmdb:936075",
            "tmdb_id": "936075",
            "imdb_id": "tt11378946",
            "plex_guid": "plex://movie/michael",
            "title": "Michael",
            "year": "2026",
            "path": "E:/Movies/Michael.2026.mkv",
        }]

        projected = project_owned_list_identities(lists, owned)

        self.assertNotIn("movie_key", lists[0]["movies"][0])
        self.assertEqual(projected[0]["movies"][0]["movie_key"], "tmdb:936075")
        self.assertEqual(projected[0]["movies"][0]["imdb_id"], "tt11378946")
        self.assertEqual(projected[0]["movies"][0]["watched_at"], 123)


if __name__ == "__main__":
    unittest.main()
