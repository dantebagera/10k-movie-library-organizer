import unittest
from unittest.mock import Mock, patch

import app


class TmdbDetailsTransformTest(unittest.TestCase):
    def test_extracts_director_cast_and_collection(self):
        payload = {
            "runtime": 117,
            "tagline": "In space no one can hear you scream.",
            "release_date": "1979-05-25",
            "belongs_to_collection": {
                "id": 8091,
                "name": "Alien Collection",
                "poster_path": "/alien-poster.jpg",
                "backdrop_path": "/alien-backdrop.jpg",
            },
            "credits": {
                "crew": [
                    {"id": 1, "name": "Editor Person", "job": "Editor", "profile_path": "/editor.jpg"},
                    {"id": 2, "name": "Ridley Scott", "job": "Director", "profile_path": "/ridley.jpg"},
                    {"id": 3, "name": "Dan O'Bannon", "job": "Writer", "profile_path": "/writer.jpg"},
                    {"id": 3, "name": "Dan O'Bannon", "job": "Screenplay", "profile_path": "/writer.jpg"},
                    {"id": 4, "name": "Ronald Shusett", "job": "Story"},
                ],
                "cast": [
                    {"id": idx, "name": f"Actor {idx}", "character": f"Role {idx}", "profile_path": f"/actor-{idx}.jpg"}
                    for idx in range(1, 9)
                ],
            },
            "videos": {
                "results": [
                    {"site": "YouTube", "type": "Trailer", "key": "official-key", "official": True},
                ]
            },
            "release_dates": {
                "results": [{
                    "iso_3166_1": "US",
                    "release_dates": [
                        {"certification": "R", "type": 4, "release_date": "1979-05-22T00:00:00.000Z"},
                        {"certification": "R", "type": 3, "release_date": "1979-05-25T00:00:00.000Z"},
                    ],
                }]
            },
            "keywords": {
                "keywords": [
                    {"id": 1, "name": "space"},
                    {"id": 2, "name": "alien"},
                    {"id": 3, "name": "space"},
                ]
            },
        }

        result = app._normalize_tmdb_details_payload(payload)

        self.assertEqual(result["director"]["name"], "Ridley Scott")
        self.assertEqual(result["director"]["profile_url"], "https://image.tmdb.org/t/p/w185/ridley.jpg")
        self.assertEqual(len(result["cast"]), 8)
        self.assertEqual(result["cast"][0]["character"], "Role 1")
        self.assertEqual(result["collection"]["name"], "Alien Collection")
        self.assertEqual(result["collection"]["poster_url"], "https://image.tmdb.org/t/p/w185/alien-poster.jpg")
        self.assertEqual(result["trailer_url"], "https://www.youtube.com/watch?v=official-key")
        self.assertEqual(result["release_date"], "1979-05-25")
        self.assertEqual([writer["name"] for writer in result["writers"]], ["Dan O'Bannon", "Ronald Shusett"])
        self.assertEqual(result["certification"], "R")
        self.assertEqual(result["keywords"], ["space", "alien"])

    def test_details_keep_primary_and_regional_release_year_evidence(self):
        payload = {
            "release_date": "2010-06-03",
            "release_dates": {
                "results": [
                    {"iso_3166_1": "ES", "release_dates": [{"release_date": "2009-10-06T00:00:00.000Z"}]},
                    {"iso_3166_1": "US", "release_dates": [{"release_date": "2010-06-04T00:00:00.000Z"}]},
                    {"iso_3166_1": "JP", "release_dates": [{"release_date": "2011-01-08T00:00:00.000Z"}]},
                ]
            },
            "credits": {"crew": [], "cast": []},
            "videos": {"results": []},
        }

        result = app._normalize_tmdb_details_payload(payload)

        self.assertEqual(result["release_years"], ["2010", "2009", "2011"])
        self.assertGreater(result["release_years_checked_at"], 0)

    def test_partial_tmdb_save_does_not_erase_release_year_evidence(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            store = app.AppMetadataStore(Path(tmp))
            store.save_tmdb_metadata({
                "tmdb_id": "37707",
                "title": "Splice",
                "release_years": ["2010", "2009", "2011"],
                "release_years_checked_at": 123,
            })
            saved = store.save_tmdb_metadata({
                "tmdb_id": "37707",
                "title": "Splice",
                "release_years": ["2010"],
                "release_years_checked_at": 0,
            })

        self.assertEqual(saved["release_years"], ["2010", "2009", "2011"])
        self.assertEqual(saved["release_years_checked_at"], 123)

    def test_collection_parts_keep_movie_card_metadata(self):
        app._tmdb_genres = {28: "Action", 878: "Sci-Fi"}
        payload = {
            "id": 123,
            "name": "Future Collection",
            "poster_path": "/collection.jpg",
            "backdrop_path": "/collection-bg.jpg",
            "parts": [
                {
                    "id": 10,
                    "title": "Future One",
                    "release_date": "2020-05-01",
                    "poster_path": "/future-one.jpg",
                    "genre_ids": [28, 878],
                    "vote_average": 7.25,
                    "vote_count": 3200,
                    "overview": "A future starts here.",
                    "original_language": "en",
                }
            ],
        }

        result = app._normalize_tmdb_collection_payload(payload)

        self.assertEqual(result["parts"][0]["tmdb_id"], "10")
        self.assertEqual(result["parts"][0]["genres"], ["Action", "Sci-Fi"])
        self.assertEqual(result["parts"][0]["tmdb_rating"], "7.2")
        self.assertEqual(result["parts"][0]["tmdb_vote_count"], 3200)
        self.assertEqual(result["parts"][0]["plot"], "A future starts here.")
        self.assertEqual(result["parts"][0]["language"], "English")

    def test_person_movies_endpoint_filters_directed_movies(self):
        original_key = app._tmdb_key
        original_genres = app._tmdb_genres
        app._tmdb_key = "tmdb-key"
        app._tmdb_genres = {80: "Crime"}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "crew": [
                        {
                            "id": 1,
                            "title": "Directed Movie",
                            "release_date": "2001-01-01",
                            "poster_path": "/directed.jpg",
                            "genre_ids": [80],
                            "vote_average": 8.44,
                            "overview": "A directed movie.",
                            "original_language": "en",
                            "job": "Director",
                        },
                        {
                            "id": 2,
                            "title": "Produced Movie",
                            "release_date": "2002-01-01",
                            "job": "Producer",
                        },
                    ],
                    "cast": []
                }).encode()

        requested_urls = []

        def fake_urlopen(request, timeout=0):
            requested_urls.append(request.full_url)
            return FakeResponse()

        try:
            with patch("app._ensure_tmdb_genres"), patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                response = app.app.test_client().get("/api/tmdb/person_movies?person_id=55&role=director&page=1")
        finally:
            app._tmdb_key = original_key
            app._tmdb_genres = original_genres

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("/person/55/movie_credits", requested_urls[0])
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["title"], "Directed Movie")
        self.assertEqual(data["results"][0]["genres"], ["Crime"])

    def test_person_movies_endpoint_filters_allowed_writer_jobs_and_deduplicates_movies(self):
        original_key = app._tmdb_key
        original_genres = app._tmdb_genres
        app._tmdb_key = "tmdb-key"
        app._tmdb_genres = {18: "Drama"}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "cast": [],
                    "crew": [
                        {"id": 1, "title": "Written Movie", "release_date": "2001-01-01", "genre_ids": [18], "job": "Writer", "popularity": 8},
                        {"id": 1, "title": "Written Movie", "release_date": "2001-01-01", "genre_ids": [18], "job": "Screenplay", "popularity": 8},
                        {"id": 2, "title": "Story Movie", "release_date": "2002-01-01", "genre_ids": [18], "job": "Story", "popularity": 7},
                        {"id": 3, "title": "Novel Movie", "release_date": "2003-01-01", "genre_ids": [18], "job": "Novel", "popularity": 6},
                        {"id": 4, "title": "Produced Movie", "release_date": "2004-01-01", "genre_ids": [18], "job": "Producer", "popularity": 10},
                        {"id": 5, "title": "Directed Movie", "release_date": "2005-01-01", "genre_ids": [18], "job": "Director", "popularity": 9},
                    ],
                }).encode()

        try:
            with patch("app._ensure_tmdb_genres"), \
                    patch("app._metadata_store", side_effect=AssertionError("remote writer results must not persist")), \
                    patch("app.urllib.request.urlopen", return_value=FakeResponse()) as provider_call:
                response = app.app.test_client().get(
                    "/api/tmdb/person_movies?person_id=55&role=writer&page=1"
                )
        finally:
            app._tmdb_key = original_key
            app._tmdb_genres = original_genres

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["role"], "writer")
        provider_call.assert_called_once()
        self.assertEqual(
            [movie["title"] for movie in data["results"]],
            ["Written Movie", "Story Movie", "Novel Movie"],
        )
        self.assertEqual(data["total_results"], 3)

    def test_keyword_search_returns_deduplicated_tmdb_identities_without_persistence(self):
        original_key = app._tmdb_key
        app._tmdb_key = "tmdb-key"

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "page": 1,
                    "total_pages": 2,
                    "total_results": 3,
                    "results": [
                        {"id": 501, "name": "time travel"},
                        {"id": 501, "name": "Time Travel"},
                        {"name": "missing identity"},
                    ],
                }).encode()

        requested_urls = []

        def fake_urlopen(request, timeout=0):
            requested_urls.append(request.full_url)
            return FakeResponse()

        try:
            with patch("app._metadata_store", side_effect=AssertionError("remote keyword search must not persist")), \
                    patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                response = app.app.test_client().get(
                    "/api/tmdb/keywords/search?q=time+travel&page=1&include_adult=false"
                )
        finally:
            app._tmdb_key = original_key

        self.assertEqual(response.status_code, 200)
        self.assertIn("/search/keyword?", requested_urls[0])
        self.assertIn("query=time+travel", requested_urls[0])
        self.assertEqual(response.get_json()["results"], [{
            "tmdb_id": "501",
            "name": "time travel",
        }])

    def test_keyword_search_preserves_validation_and_provider_error_contracts(self):
        original_key = app._tmdb_key
        client = app.app.test_client()
        try:
            app._tmdb_key = ""
            missing_key = client.get("/api/tmdb/keywords/search?q=space")

            app._tmdb_key = "tmdb-key"
            missing_query = client.get("/api/tmdb/keywords/search")
            with patch(
                "app.urllib.request.urlopen",
                side_effect=app.urllib.error.HTTPError(
                    "https://api.themoviedb.org/3/search/keyword",
                    503,
                    "Unavailable",
                    None,
                    None,
                ),
            ):
                provider_error = client.get("/api/tmdb/keywords/search?q=space")
        finally:
            app._tmdb_key = original_key

        self.assertEqual(missing_key.status_code, 400)
        self.assertEqual(missing_query.status_code, 400)
        self.assertEqual(provider_error.status_code, 502)
        self.assertEqual(provider_error.get_json()["error"], "TMDB returned HTTP 503")

    def test_discover_filters_by_keyword_identity_and_keeps_results_remote(self):
        original_key = app._tmdb_key
        original_genres = app._tmdb_genres
        app._tmdb_key = "tmdb-key"
        app._tmdb_genres = {878: "Sci-Fi"}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "page": 2,
                    "total_pages": 3,
                    "total_results": 1,
                    "results": [{
                        "id": 10,
                        "title": "Temporal Feature",
                        "release_date": "2024-01-02",
                        "poster_path": "/temporal.jpg",
                        "genre_ids": [878],
                        "vote_average": 8.1,
                        "vote_count": 1200,
                        "overview": "Time folds.",
                        "original_language": "en",
                    }],
                }).encode()

        requested_urls = []

        def fake_urlopen(request, timeout=0):
            requested_urls.append(request.full_url)
            return FakeResponse()

        try:
            with patch("app._ensure_tmdb_genres"), \
                    patch("app._metadata_store", side_effect=AssertionError("remote keyword results must not persist")), \
                    patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                response = app.app.test_client().get(
                    "/api/tmdb/discover"
                    "?list=catalog&keyword_id=501&keyword_name=time+travel&page=2"
                    "&genre=878&year_from=2020&min_rating=7&min_votes=1000&sort=vote_average.desc"
                )
        finally:
            app._tmdb_key = original_key
            app._tmdb_genres = original_genres

        self.assertEqual(response.status_code, 200)
        requested = requested_urls[0]
        self.assertIn("/discover/movie?", requested)
        self.assertIn("with_keywords=501", requested)
        self.assertIn("page=2", requested)
        self.assertNotIn("/search/movie", requested)
        self.assertIn("with_genres=878", requested)
        self.assertIn("primary_release_date.gte=2020-01-01", requested)
        self.assertEqual(response.get_json()["keyword"], {
            "tmdb_id": "501",
            "name": "time travel",
        })
        self.assertEqual(response.get_json()["page"], 2)
        self.assertEqual(response.get_json()["total_pages"], 3)
        self.assertEqual(response.get_json()["results"][0]["title"], "Temporal Feature")
        self.assertEqual(response.get_json()["results"][0]["genres"], ["Sci-Fi"])

    def test_person_movies_filters_and_sorts_the_full_filmography_before_paging(self):
        original_key = app._tmdb_key
        original_genres = app._tmdb_genres
        app._tmdb_key = "tmdb-key"
        app._tmdb_genres = {16: "Animation", 18: "Drama"}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "cast": [
                        {"id": 1, "title": "Zed Animation", "release_date": "2005-01-01", "genre_ids": [16], "vote_average": 7.5, "vote_count": 100, "popularity": 1},
                        {"id": 2, "title": "Alpha Animation", "release_date": "2010-01-01", "genre_ids": [16], "vote_average": 8.0, "vote_count": 200, "popularity": 5},
                        {"id": 3, "title": "Drama", "release_date": "2010-01-01", "genre_ids": [18], "vote_average": 9.0, "vote_count": 500, "popularity": 8},
                        {"id": 4, "title": "Old Animation", "release_date": "1990-01-01", "genre_ids": [16], "vote_average": 9.0, "vote_count": 500, "popularity": 8},
                    ],
                    "crew": []
                }).encode()

        try:
            with patch("app._ensure_tmdb_genres"), patch("app.urllib.request.urlopen", return_value=FakeResponse()):
                response = app.app.test_client().get(
                    "/api/tmdb/person_movies?person_id=55&role=actor&genre=16&year_from=2000&min_rating=7&min_votes=100&sort=title.asc"
                )
        finally:
            app._tmdb_key = original_key
            app._tmdb_genres = original_genres

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual([movie["title"] for movie in data["results"]], ["Alpha Animation", "Zed Animation"])
        self.assertEqual(data["total_results"], 2)

    def test_person_endpoint_returns_biography_profile_payload(self):
        original_key = app._tmdb_key
        app._tmdb_key = "tmdb-key"

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "id": 287,
                    "name": "Brad Pitt",
                    "profile_path": "/brad.jpg",
                    "biography": "Brief biography.",
                    "birthday": "1963-12-18",
                    "deathday": None,
                    "place_of_birth": "Shawnee, Oklahoma, USA",
                    "known_for_department": "Acting",
                    "homepage": "https://example.test",
                }).encode()

        requested_urls = []

        def fake_urlopen(request, timeout=0):
            requested_urls.append(request.full_url)
            return FakeResponse()

        try:
            with patch("app.urllib.request.urlopen", side_effect=fake_urlopen):
                response = app.app.test_client().get("/api/tmdb/person?person_id=287")
        finally:
            app._tmdb_key = original_key

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("/person/287?", requested_urls[0])
        self.assertEqual(payload["id"], "287")
        self.assertEqual(payload["name"], "Brad Pitt")
        self.assertEqual(payload["profile_url"], "https://image.tmdb.org/t/p/w342/brad.jpg")
        self.assertEqual(payload["biography"], "Brief biography.")
        self.assertEqual(payload["birthday"], "1963-12-18")
        self.assertEqual(payload["deathday"], "")
        self.assertEqual(payload["place_of_birth"], "Shawnee, Oklahoma, USA")
        self.assertEqual(payload["known_for_department"], "Acting")

    def test_fetch_tmdb_metadata_refetches_cached_movie_without_release_date(self):
        original_key = app._tmdb_key
        app._tmdb_key = "tmdb-key"

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "id": 1368337,
                    "title": "The Odyssey",
                    "release_date": "2026-07-15",
                    "credits": {"crew": [], "cast": []},
                    "videos": {"results": []},
                }).encode()

        try:
            with self.subTest("metadata store cache"):
                import tempfile
                from pathlib import Path

                with tempfile.TemporaryDirectory() as tmp:
                    store = app.AppMetadataStore(Path(tmp))
                    store.save_tmdb_metadata({"tmdb_id": "1368337", "title": "The Odyssey"})
                    with patch("app.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
                        result = app._fetch_tmdb_metadata_by_id("1368337", store=store)
                    self.assertTrue(urlopen.called)
                    self.assertEqual(result["release_date"], "2026-07-15")
        finally:
            app._tmdb_key = original_key

    def test_card_projection_is_read_only_for_incomplete_cached_metadata(self):
        cached = {"tmdb_id": "1368337", "title": "The Odyssey", "release_date": "2026-07-15"}
        expected = {
            **cached,
            "genres": ["Adventure"],
            "tmdb_rating": "8.0",
            "plot": "An epic voyage.",
        }

        class Store:
            def get_tmdb_metadata(self, tmdb_id):
                self.requested_id = tmdb_id
                return cached

        store = Store()
        with patch("app._fetch_tmdb_metadata_by_id", return_value=expected) as fetch:
            result = app._tmdb_card_projection_by_id("1368337", store=store)

        self.assertEqual(store.requested_id, "1368337")
        self.assertEqual(result, {})
        fetch.assert_not_called()

    def test_card_projections_endpoint_batches_unique_valid_tmdb_ids(self):
        projection = {
            "tmdb_id": "1368337",
            "title": "The Odyssey",
            "genres": ["Adventure"],
            "tmdb_rating": "8.0",
        }
        store = Mock()
        store.catalog.generation.return_value = 73

        def card_projection(movie, projection_store):
            self.assertIs(projection_store, store)
            return {**projection, "tmdb_id": movie["tmdb_id"]}

        with patch("app._metadata_store", return_value=store), \
             patch("app._movie_card_projection", side_effect=card_projection) as resolve:
            response = app.app.test_client().post("/api/tmdb/card-projections", json={
                "movies": [
                    {"key": "tmdb:1368337", "tmdb_id": "1368337"},
                    {"key": "tmdb:1368337", "tmdb_id": 1368337},
                    {"key": "tmdb:42", "tmdb_id": "42"},
                    {"key": "bad", "tmdb_id": "not-a-tmdb-id"},
                    {"key": "empty"},
                ],
            })

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["requested"], 2)
        self.assertEqual(payload["resolved"], 2)
        self.assertEqual(payload["catalog_generation"], 73)
        self.assertEqual(set(payload["items"]), {"tmdb:1368337", "tmdb:42"})
        self.assertEqual(resolve.call_count, 2)

    def test_plex_card_projection_uses_cached_provider_metadata_without_title_guessing(self):
        poster_url = "http://localhost:32400/library/metadata/1044/thumb/1777947200?token=value"
        store = Mock()
        store.get_plex_metadata_by_poster_url.return_value = {
            "plex_title": "Film Postcards: Serbia",
            "plex_year": "2012",
            "plex_poster": poster_url,
            "plex_genres": ["Short"],
            "plex_country": "Spain",
            "plex_directors": [{"name": "Irene M. Borrego"}],
        }

        projection = app._plex_card_projection_by_poster_url(poster_url, store=store)

        self.assertEqual(projection["title"], "Film Postcards: Serbia")
        self.assertEqual(projection["genres"], ["Short"])
        self.assertEqual(projection["director"]["name"], "Irene M. Borrego")

    def test_tmdb_details_endpoint_refetches_cached_payload_without_movie_projection(self):
        original_key = app._tmdb_key
        original_cache = app._tmdb_library_cache
        app._tmdb_key = "tmdb-key"
        app._tmdb_library_cache = {
            "1368337": {
                "fetched_at": 1,
                "data": {
                    "tmdb_id": "1368337",
                    "title": "The Odyssey",
                    "plot": "Old cached plot.",
                    "genres": ["Adventure"],
                    "runtime": 100,
                    "release_date": "2026-07-15",
                    "cast": [],
                    "directors": [],
                },
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "id": 1368337,
                    "title": "The Odyssey",
                    "overview": "Odysseus begins his long voyage home.",
                    "release_date": "2026-07-15",
                    "runtime": 100,
                    "genres": [{"id": 12, "name": "Adventure"}],
                    "vote_average": 8.1,
                    "imdb_id": "tt31564624",
                    "credits": {
                        "crew": [{"id": 1, "name": "Christopher Nolan", "job": "Writer"}],
                        "cast": [],
                    },
                    "videos": {"results": []},
                    "release_dates": {
                        "results": [{
                            "iso_3166_1": "US",
                            "release_dates": [{"certification": "PG-13", "type": 3}],
                        }]
                    },
                    "keywords": {"keywords": [{"id": 1, "name": "odyssey"}]},
                }).encode()

        try:
            with patch("app.urllib.request.urlopen", return_value=FakeResponse()) as urlopen, \
                 patch("app._save_tmdb_library_cache"):
                response = app.app.test_client().get("/api/tmdb/details?tmdb_id=1368337")
        finally:
            app._tmdb_key = original_key
            app._tmdb_library_cache = original_cache

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(urlopen.called)
        self.assertFalse(payload["cached"])
        self.assertEqual(payload["title"], "The Odyssey")
        self.assertEqual(payload["plot"], "Odysseus begins his long voyage home.")
        self.assertEqual(payload["genres"], ["Adventure"])
        self.assertEqual(payload["release_date"], "2026-07-15")
        self.assertEqual(payload["certification"], "PG-13")
        self.assertEqual(payload["writers"][0]["name"], "Christopher Nolan")
        self.assertEqual(payload["keywords"], ["odyssey"])
        self.assertIn("release_dates", urlopen.call_args.args[0].full_url)
        self.assertIn("keywords", urlopen.call_args.args[0].full_url)

    def test_arabic_tmdb_details_are_transient_and_do_not_touch_persistent_cache(self):
        original_key = app._tmdb_key
        original_cache = app._tmdb_library_cache
        app._tmdb_key = "tmdb-key"
        app._tmdb_library_cache = {
            "550": {"fetched_at": 1, "data": {"tmdb_id": "550", "runtime": 139, "release_date": "1999-10-15"}}
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return app._json.dumps({
                    "id": 550,
                    "title": "نادي القتال",
                    "overview": "حبكة عربية",
                    "poster_path": "/arabic-poster.jpg",
                    "release_date": "1999-10-15",
                    "runtime": 139,
                    "genres": [{"id": 18, "name": "دراما"}],
                    "credits": {
                        "crew": [{"id": 7467, "name": "ديفيد فينشر", "job": "Director"}],
                        "cast": [{"id": 287, "name": "براد بيت", "character": "Tyler Durden"}],
                    },
                    "videos": {"results": []},
                }, ensure_ascii=False).encode("utf-8")

        try:
            with patch("app.urllib.request.urlopen", return_value=FakeResponse()) as urlopen, \
                 patch("app._save_tmdb_library_cache") as save_cache:
                response = app.app.test_client().get("/api/tmdb/details?tmdb_id=550&language=ar-SA")
        finally:
            retained_cache = app._tmdb_library_cache
            app._tmdb_key = original_key
            app._tmdb_library_cache = original_cache

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["title"], "نادي القتال")
        self.assertEqual(payload["plot"], "حبكة عربية")
        self.assertEqual(payload["genres"], ["دراما"])
        self.assertEqual(payload["directors"][0]["name"], "ديفيد فينشر")
        self.assertTrue(payload["transient"])
        self.assertEqual(payload["display_language"], "ar-SA")
        self.assertIn("language=ar-SA", urlopen.call_args.args[0].full_url)
        self.assertEqual(retained_cache["550"]["data"]["runtime"], 139)
        save_cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()
