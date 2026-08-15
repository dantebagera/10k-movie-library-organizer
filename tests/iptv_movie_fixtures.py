import io
import json
from pathlib import Path

from services.iptv_service import IPTVService


def provider_catalog(prefix="Fixture", movie_rows=None):
    movies = movie_rows or [
        {
            "stream_id": "10",
            "category_id": "movies-a",
            "name": f"{prefix} Movie (2024) 1080p",
            "year": "2024",
            "stream_icon": "https://images.example/poster.jpg",
            "container_extension": "mkv",
            "rating": "7.5",
            "plot": "Provider plot",
            "cast": "Provider Cast",
            "director": "Provider Director",
            "genre": "Provider Genre",
            "duration": "01:40:00",
            "added": "100",
        }
    ]
    return {
        "live": {
            "categories": [{"category_id": "live-a", "category_name": "Fixture Live"}],
            "items": [{"stream_id": "10", "category_id": "live-a", "name": "Fixture Channel"}],
        },
        "movie": {
            "categories": [
                {"category_id": "movies-a", "category_name": "Exact Provider Playlist"},
                {"category_id": "movies-b", "category_name": "Second Provider Playlist"},
            ],
            "items": movies,
        },
        "series": {
            "categories": [{"category_id": "series-a", "category_name": "Fixture Series"}],
            "items": [{"series_id": "10", "category_id": "series-a", "name": "Fixture Series"}],
        },
    }


def create_raw_service(root, provider_id, prefix="Fixture", movie_rows=None):
    provider_root = Path(root) / "iptv" / "providers" / provider_id
    service = IPTVService(provider_root, provider_id)
    service.save_config("https://provider.example", "fixture-user", "fixture-password", False)
    service.store.replace_catalog(provider_catalog(prefix, movie_rows))
    return service


def tmdb_payload(tmdb_id=550, title="Fixture Movie", year=2024):
    return {
        "id": int(tmdb_id),
        "title": title,
        "original_title": title,
        "overview": f"TMDB plot for {title}",
        "poster_path": "/poster.jpg",
        "backdrop_path": "/backdrop.jpg",
        "vote_average": 8.2,
        "vote_count": 1200,
        "release_date": f"{int(year):04d}-02-03",
        "runtime": 101,
        "original_language": "en",
        "spoken_languages": [{"iso_639_1": "en", "english_name": "English"}],
        "production_countries": [{"iso_3166_1": "US", "name": "United States"}],
        "genres": [{"id": 18, "name": "Drama"}],
        "belongs_to_collection": {"id": 77, "name": "Fixture Collection"},
        "credits": {
            "crew": [
                {"id": 1, "name": "Director One", "job": "Director"},
                {"id": 2, "name": "Writer One", "job": "Screenplay"},
            ],
            "cast": [{"id": 3, "name": "Actor One", "character": "Lead", "order": 0}],
        },
        "keywords": {"keywords": [{"id": 9, "name": "fixture"}]},
        "release_dates": {
            "results": [{"iso_3166_1": "US", "release_dates": [{"certification": "PG-13"}]}]
        },
    }


class FakeTMDBClient:
    def __init__(self, movies=None, search_results=None):
        self.movies = movies or {550: tmdb_payload()}
        self.search_results = search_results

    def validate(self):
        return True

    def movie(self, tmdb_id, language=""):
        return self.movies[int(tmdb_id)]

    def normalized_movie(self, tmdb_id, language=""):
        from services.iptv_tmdb import normalize_tmdb_movie

        return normalize_tmdb_movie(self.movie(tmdb_id, language=language))

    def search_movies(self, title, year=0, page=1):
        if self.search_results is not None:
            return list(self.search_results)
        return [self.movies[550]]


class FakeHTTPResponse:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}

    def read(self, _limit=-1):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def close(self):
        return None
