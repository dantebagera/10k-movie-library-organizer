import sys
from pathlib import Path

from services.iptv_movie_store import source_key
from services.iptv_provider_manager import IPTVProviderManager
from services.iptv_tmdb import normalize_tmdb_movie


def catalog(label):
    movies = [{
        "stream_id": "7",
        "category_id": "shared",
        "name": f"{label} Movie",
        "container_extension": "mp4",
        "year": "2024",
    }]
    if label == "First":
        movies.extend([
            {
                "stream_id": "8",
                "category_id": "shared",
                "name": "First Movie 4K",
                "container_extension": "mkv",
                "year": "2024",
            },
            {
                "stream_id": "9",
                "category_id": "shared",
                "name": "First Unmatched Movie",
                "container_extension": "mp4",
                "year": "2023",
            },
            {
                "stream_id": "10",
                "category_id": "shared",
                "name": "\u0641\u064a\u0644\u0645 \u0627\u062e\u062a\u0628\u0627\u0631\u064a \u0639\u0631\u0628\u064a (1990)",
                "container_extension": "mp4",
                "year": "1990",
            },
            {
                "stream_id": "11",
                "category_id": "shared",
                "name": "English Indian Fixture (2020)",
                "container_extension": "mp4",
                "year": "2020",
            },
        ])
    return {
        "live": {
            "categories": [{"category_id": "shared", "category_name": f"{label} Live"}],
            "items": [{"stream_id": "7", "category_id": "shared", "name": f"{label} Channel"}],
        },
        "movie": {
            "categories": [{"category_id": "shared", "category_name": f"{label} Movies"}],
            "items": movies,
        },
        "series": {
            "categories": [{"category_id": "shared", "category_name": f"{label} Series"}],
            "items": [{"series_id": "7", "category_id": "shared", "name": f"{label} Series"}],
        },
    }


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Expected the isolated CP_TEST_ROOT")
    test_root = Path(sys.argv[1]).resolve()
    manager = IPTVProviderManager(test_root / "user-data", migrate_legacy=False)
    try:
        first = manager.create_provider(
            "Provider One",
            "https://provider-one.invalid",
            "fixture-one",
            "fixture-password-one",
            False,
        )
        second = manager.create_provider(
            "Provider Two",
            "https://provider-two.invalid",
            "fixture-two",
            "fixture-password-two",
            True,
        )
        first_service = manager.service(first["provider_id"])
        second_service = manager.service(second["provider_id"])
        first_service.store.replace_catalog(catalog("First"))
        second_service.store.replace_catalog(catalog("Second"))
        first_service.set_favorite("movie", "7", True)
        first_list = first_service.create_list("First fixture list")
        first_service.set_list_item(first_list["list_id"], "movie", "7", True)
        first_service.store.update_history("movie", "7", 12, 100, False)
        first_movies = manager.movie_service(first["provider_id"])
        first_movies.ensure_projected()
        snapshot = normalize_tmdb_movie({
            "id": 550,
            "title": "First Enriched Movie",
            "original_title": "First Enriched Movie",
            "overview": "A disposable provider-local enriched movie used by Playwright.",
            "poster_path": "",
            "backdrop_path": "",
            "vote_average": 8.1,
            "vote_count": 100,
            "release_date": "2024-01-01",
            "runtime": 101,
            "original_language": "en",
            "imdb_id": "tt0137523",
            "spoken_languages": [{"iso_639_1": "en", "english_name": "English"}],
            "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
            "genres": [{"id": 18, "name": "Drama"}],
            "credits": {
                "crew": [
                    {"id": 101, "name": "Fixture Director", "job": "Director", "department": "Directing"},
                    {"id": 102, "name": "Fixture Writer", "job": "Screenplay", "department": "Writing"},
                ],
                "cast": [{"id": 103, "name": "Fixture Actor", "character": "The Tester", "order": 0}],
            },
            "keywords": {"keywords": []},
            "release_dates": {"results": []},
        })
        first_movies.store.apply_match(f"source:{source_key('7')}", snapshot)
        first_movies.store.apply_match(f"source:{source_key('8')}", snapshot)
        first_movies.store.save_localization(550, "ar-SA", {
            **snapshot,
            "title": "\u0641\u064a\u0644\u0645 \u0627\u062e\u062a\u0628\u0627\u0631\u064a",
            "plot": "\u0648\u0635\u0641 \u0639\u0631\u0628\u064a \u0645\u062d\u0644\u064a \u0644\u0644\u0627\u062e\u062a\u0628\u0627\u0631.",
        })
        arabic_snapshot = normalize_tmdb_movie({
            "id": 551,
            "title": "Arabic Fixture Transliteration",
            "original_title": "\u0641\u064a\u0644\u0645 \u0627\u062e\u062a\u0628\u0627\u0631\u064a \u0639\u0631\u0628\u064a",
            "overview": "English fallback plot for the Arabic fixture.",
            "poster_path": "",
            "backdrop_path": "",
            "vote_average": 7.4,
            "vote_count": 25,
            "release_date": "1990-01-01",
            "runtime": 90,
            "original_language": "ar",
            "spoken_languages": [{"iso_639_1": "ar", "english_name": "Arabic"}],
            "production_countries": [{"iso_3166_1": "EG", "name": "Egypt"}],
            "genres": [{"id": 35, "name": "Comedy"}],
            "credits": {
                "crew": [{"id": 201, "name": "Fixture Arabic Director", "job": "Director", "profile_path": "https://images.example/director.jpg"}],
                "cast": [{"id": 202, "name": "Fixture Arabic Actor", "character": "Lead", "order": 0, "profile_path": "https://images.example/actor.jpg"}],
            },
            "keywords": {"keywords": []},
            "release_dates": {"results": []},
        })
        first_movies.store.apply_match(f"source:{source_key('10')}", arabic_snapshot)
        # Leave this accepted Arabic match without a stored ar-SA row. The
        # browser test supplies the transient localization response so it can
        # prove the first expanded render requests and applies Arabic people.
        indian_snapshot = normalize_tmdb_movie({
            "id": 552,
            "title": "English Indian Fixture",
            "original_title": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c05\u0c38\u0c32\u0c41 \u0c2a\u0c47\u0c30\u0c41",
            "overview": "English plot for the Indian fixture.",
            "poster_path": "",
            "backdrop_path": "",
            "vote_average": 7.0,
            "vote_count": 10,
            "release_date": "2020-01-01",
            "runtime": 100,
            "original_language": "te",
            "spoken_languages": [{"iso_639_1": "te", "english_name": "Telugu"}],
            "production_countries": [{"iso_3166_1": "IN", "name": "India"}],
            "genres": [{"id": 18, "name": "Drama"}],
            "credits": {
                "crew": [{"id": 301, "name": "English Indian Director", "job": "Director", "profile_path": "https://images.example/indian-director.jpg"}],
                "cast": [{"id": 302, "name": "English Indian Actor", "character": "Lead", "order": 0, "profile_path": "https://images.example/indian-actor.jpg"}],
            },
            "keywords": {"keywords": []},
            "release_dates": {"results": []},
        })
        first_movies.store.apply_match(f"source:{source_key('11')}", indian_snapshot)
        first_movies.store.save_localization(552, "ar-SA", {
            **indian_snapshot,
            "title": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c2a\u0c47\u0c30\u0c41",
            "plot": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c15\u0c25",
            "directors": [{"id": 301, "name": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c26\u0c30\u0c4d\u0c36\u0c15\u0c41\u0c21\u0c41"}],
            "writers": [],
            "cast": [{"id": 302, "name": "\u0c24\u0c46\u0c32\u0c41\u0c17\u0c41 \u0c28\u0c1f\u0c41\u0c21\u0c41"}],
        })
        # The fixture writes the raw catalog directly, bypassing the production
        # post-sync coordinator. Prepare the second disposable provider
        # explicitly so GET requests remain pure reads during browser tests.
        manager.movie_service(second["provider_id"]).ensure_projected()
        second_list = second_service.create_list("Second fixture list")
        second_service.set_list_item(second_list["list_id"], "series", "7", True)
        manager.set_selection(first["provider_id"])
    finally:
        manager.close()


if __name__ == "__main__":
    main()
