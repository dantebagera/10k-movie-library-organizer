import json
import unittest

from services.subtitle_service import (
    OpenSubtitlesProvider,
    SubtitleProviderError,
    SubDLProvider,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.offset = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


class RecordingOpener:
    def __init__(self):
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        url = request.full_url
        if "api.opensubtitles.com/api/v1/subtitles" in url:
            return FakeResponse(json.dumps({
                "data": [{
                    "id": "open-1",
                    "attributes": {
                        "language": "en",
                        "release": "Movie.2024.1080p",
                        "fps": 23.976,
                        "ratings": 8,
                        "download_count": 400,
                        "hearing_impaired": True,
                        "moviehash_match": True,
                        "feature_details": {
                            "imdb_id": 123,
                            "tmdb_id": 456,
                            "title": "Movie",
                            "year": 2024,
                        },
                        "files": [{"file_id": 99, "file_name": "movie.srt"}],
                    },
                }],
            }).encode())
        if url.endswith("/api/v1/login"):
            return FakeResponse(json.dumps({
                "token": "account-token",
                "base_url": "api.opensubtitles.com",
            }).encode())
        if url.endswith("/api/v1/download"):
            return FakeResponse(json.dumps({
                "link": "https://dl.opensubtitles.com/en/download/file/99",
                "file_name": "movie.srt",
            }).encode())
        if "dl.opensubtitles.com/" in url:
            return FakeResponse(b"subtitle")
        if "api.subdl.com/api/v1/subtitles" in url:
            return FakeResponse(json.dumps({
                "status": True,
                "results": [{
                    "imdb_id": "tt123",
                    "tmdb_id": 456,
                    "name": "Movie",
                    "year": 2024,
                }],
                "subtitles": [{
                    "release_name": "Movie.2024.1080p",
                    "name": "movie.zip",
                    "url": "/subtitle/one-two.zip",
                    "language": "EN",
                    "fps": "23.976",
                    "hi": False,
                }],
            }).encode())
        if "dl.subdl.com/" in url:
            return FakeResponse(b"PK fixture")
        raise AssertionError(f"Unexpected URL: {url}")


IDENTITY = {
    "title": "Movie",
    "year": "2024",
    "filename": "Movie.2024.1080p.mkv",
    "file_size": 1000,
    "file_hash": "0123456789abcdef",
    "frame_rate": 23.976,
    "imdb_id": "tt123",
    "tmdb_id": "456",
}


class SubtitleProviderAdapterTests(unittest.TestCase):
    def test_opensubtitles_normalizes_search_and_keeps_download_link_internal(self):
        opener = RecordingOpener()
        provider = OpenSubtitlesProvider({"api_key": "secret"}, opener)

        results = provider.search(IDENTITY, ["en"])
        payload, name = provider.download(results[0]["provider_ref"])

        self.assertTrue(results[0]["hash_match"])
        self.assertEqual(results[0]["provider"], "opensubtitles")
        self.assertEqual(results[0]["provider_ref"], {"file_id": "99"})
        self.assertEqual(payload, b"subtitle")
        self.assertEqual(name, "movie.srt")
        search_request = opener.requests[0][0]
        self.assertEqual(search_request.get_header("Api-key"), "secret")
        download_request = opener.requests[1][0]
        self.assertIsNone(download_request.get_header("Authorization"))
        self.assertFalse(any(
            request.full_url.endswith("/api/v1/login")
            for request, _timeout in opener.requests
        ))

    def test_opensubtitles_account_mode_logs_in_and_uses_bearer_token(self):
        opener = RecordingOpener()
        provider = OpenSubtitlesProvider({
            "authentication_mode": "account",
            "api_key": "secret",
            "username": "account-user",
            "password": "account-password",
        }, opener)

        payload, name = provider.download({"file_id": "99"})

        self.assertEqual(payload, b"subtitle")
        self.assertEqual(name, "movie.srt")
        self.assertTrue(opener.requests[0][0].full_url.endswith("/api/v1/login"))
        download_request = opener.requests[1][0]
        self.assertEqual(
            download_request.get_header("Authorization"),
            "Bearer account-token",
        )

    def test_opensubtitles_account_mode_never_falls_back_without_credentials(self):
        provider = OpenSubtitlesProvider({
            "authentication_mode": "account",
            "api_key": "secret",
        }, RecordingOpener())

        with self.assertRaises(SubtitleProviderError) as raised:
            provider.download({"file_id": "99"})

        self.assertEqual(raised.exception.code, "not_configured")

    def test_subdl_normalizes_search_and_uses_header_for_download_key(self):
        opener = RecordingOpener()
        provider = SubDLProvider({"api_key": "secret"}, opener)

        results = provider.search(IDENTITY, ["en", "fr"])
        payload, name = provider.download(results[0]["provider_ref"])

        self.assertEqual(results[0]["provider"], "subdl")
        self.assertEqual(results[0]["language"], "en")
        self.assertEqual(results[0]["provider_ref"], {"path": "/subtitle/one-two.zip"})
        self.assertEqual(payload, b"PK fixture")
        self.assertEqual(name, "one-two.zip")
        download_request = opener.requests[-1][0]
        self.assertEqual(download_request.get_header("X-api-key"), "secret")
        self.assertNotIn("secret", download_request.full_url)


if __name__ == "__main__":
    unittest.main()
