import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from services.player_config import PlayerConfig
from services.subtitle_service import (
    SubtitleProviderError,
    SubtitleService,
    SubtitleServiceError,
    opensubtitles_hash,
    redact_sensitive_text,
)


def subtitle_row(provider, release, *, language="en", hash_match=False, rating=0, downloads=0):
    return {
        "provider": provider,
        "provider_ref": {"id": release},
        "provider_identity": f"{provider}-{release}",
        "language": language,
        "release_name": release,
        "release_names": [release],
        "file_name": f"{release}.srt",
        "frame_rate": 23.976,
        "rating": rating,
        "download_count": downloads,
        "hearing_impaired": False,
        "forced": False,
        "hash_match": hash_match,
        "imdb_id": "tt0133093",
        "tmdb_id": "603",
        "title": "The Matrix",
        "year": "1999",
    }


class FastProvider:
    name = "opensubtitles"
    rows = []
    download_payload = b"1\r\n00:00:01,000 --> 00:00:02,000\r\nHello\r\n"
    download_name = "matrix.srt"

    def __init__(self, credentials, opener):
        self.credentials = credentials

    def search(self, identity, languages):
        return [dict(row) for row in self.rows]

    def download(self, provider_ref):
        return self.download_payload, self.download_name


class SecondProvider(FastProvider):
    name = "subdl"
    rows = []


class FailingProvider(FastProvider):
    def search(self, identity, languages):
        raise SubtitleProviderError("network_unavailable")


class RateLimitedProvider(FastProvider):
    def search(self, identity, languages):
        raise SubtitleProviderError("rate_limited", retry_after=120)


class SlowProvider(FastProvider):
    def search(self, identity, languages):
        time.sleep(0.15)
        return [subtitle_row(self.name, "late")]


class SubtitleServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.media = root / "The.Matrix.1999.1080p.BluRay.mkv"
        self.media.write_bytes(b"\0" * 140000)
        self.cache = root / "cache"
        self.config = PlayerConfig({
            "preferred_subtitle_languages": ["en", "fr"],
            "providers": {
                "opensubtitles": {"enabled": True, "api_key": "open-secret"},
                "subdl": {"enabled": True, "api_key": "subdl-secret"},
            },
        })
        self.media_payload = {
            "path_key": str(self.media).lower(),
            "path": str(self.media),
            "filename": self.media.name,
            "file_size": self.media.stat().st_size,
            "frame_rate": 23.976,
            "title": "The Matrix",
            "year": "1999",
            "imdb_id": "tt0133093",
            "tmdb_id": "603",
        }
        FastProvider.rows = []
        SecondProvider.rows = []
        FastProvider.download_payload = (
            b"1\r\n00:00:01,000 --> 00:00:02,000\r\nHello\r\n"
        )
        FastProvider.download_name = "matrix.srt"

    def tearDown(self):
        self.temp.cleanup()

    def service(self, providers=None):
        return SubtitleService(
            self.config,
            lambda: self.cache,
            provider_classes=providers or {
                "opensubtitles": FastProvider,
                "subdl": SecondProvider,
            },
        )

    def test_supported_file_hash_is_deterministic_and_search_identity_is_complete(self):
        self.assertEqual(len(opensubtitles_hash(self.media)), 16)
        self.assertEqual(opensubtitles_hash(self.media), opensubtitles_hash(self.media))
        FastProvider.rows = [subtitle_row("opensubtitles", "The.Matrix.1999.1080p.BluRay")]
        payload = self.service({"opensubtitles": FastProvider}).search("session", self.media_payload)
        self.assertEqual(len(payload["results"]), 1)

    def test_concurrent_partial_failure_keeps_successful_provider_results(self):
        FastProvider.rows = [subtitle_row("opensubtitles", "The.Matrix.1999.1080p.BluRay")]
        payload = self.service({
            "opensubtitles": FastProvider,
            "subdl": FailingProvider,
        }).search("session", self.media_payload)
        self.assertEqual([row["provider"] for row in payload["results"]], ["opensubtitles"])
        self.assertEqual(payload["diagnostics"]["subdl"]["last_error"], "network_unavailable")

    def test_slow_provider_does_not_block_fast_provider(self):
        FastProvider.rows = [subtitle_row("opensubtitles", "The.Matrix.1999.1080p.BluRay")]
        service = self.service({
            "opensubtitles": FastProvider,
            "subdl": SlowProvider,
        })
        with patch("services.subtitle_service.SEARCH_TIMEOUT_SECONDS", 0.02):
            started = time.perf_counter()
            payload = service.search("session", self.media_payload)
            elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.12)
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["diagnostics"]["subdl"]["last_error"], "timeout")

    def test_ranking_is_deterministic_and_deduplicates_cross_provider_release(self):
        FastProvider.rows = [
            subtitle_row("opensubtitles", "Other.Release", hash_match=True),
            subtitle_row("opensubtitles", "The.Matrix.1999.1080p.BluRay", rating=9),
        ]
        SecondProvider.rows = [
            subtitle_row("subdl", "The.Matrix.1999.1080p.BluRay", downloads=10000),
        ]
        results = self.service().search("session", self.media_payload)["results"]
        self.assertEqual(results[0]["release_name"], "Other.Release")
        matching_release = [
            row for row in results
            if row["release_name"] == "The.Matrix.1999.1080p.BluRay"
        ]
        self.assertEqual(len(matching_release), 1)
        self.assertEqual(results[0]["match_reason"], "Exact file hash")

    def test_language_filter_and_preference_are_applied(self):
        FastProvider.rows = [
            subtitle_row("opensubtitles", "French.Release", language="fr"),
            subtitle_row("opensubtitles", "English.Release", language="en"),
        ]
        results = self.service({"opensubtitles": FastProvider}).search(
            "session",
            self.media_payload,
        )["results"]
        self.assertEqual(results[0]["language"], "en")

    def test_download_normalizes_text_and_writes_attributed_cache_without_media_path(self):
        FastProvider.rows = [subtitle_row("opensubtitles", "The.Matrix.1999.1080p.BluRay")]
        service = self.service({"opensubtitles": FastProvider})
        result = service.search("session", self.media_payload)["results"][0]
        loaded = service.download("session", result["result_id"], self.media_payload)
        destination = Path(loaded["path"])
        self.assertEqual(destination.read_bytes(), b"1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        metadata = json.loads(
            destination.with_suffix(destination.suffix + ".json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["provider"], "opensubtitles")
        self.assertNotIn(str(self.media), json.dumps(metadata))
        self.assertNotIn("secret", json.dumps(metadata))

    def test_safe_zip_download_selects_supported_subtitle(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("readme.exe", b"no")
            output.writestr("The.Matrix.1999.1080p.BluRay.srt", "hello")
        FastProvider.download_payload = archive.getvalue()
        FastProvider.download_name = "subtitles.zip"
        FastProvider.rows = [subtitle_row("opensubtitles", "The.Matrix.1999.1080p.BluRay")]
        service = self.service({"opensubtitles": FastProvider})
        result = service.search("session", self.media_payload)["results"][0]
        loaded = service.download("session", result["result_id"], self.media_payload)
        self.assertEqual(Path(loaded["path"]).read_text(encoding="utf-8"), "hello")

    def test_beside_movie_storage_requires_the_explicit_config_mode(self):
        self.config.update({"subtitle_storage": "beside_movie"})
        FastProvider.rows = [subtitle_row("opensubtitles", "release")]
        service = self.service({"opensubtitles": FastProvider})
        result = service.search("session", self.media_payload)["results"][0]
        loaded = service.download("session", result["result_id"], self.media_payload)
        self.assertEqual(Path(loaded["path"]).parent, self.media.parent)
        self.assertTrue(Path(loaded["path"]).name.startswith("The.Matrix.1999"))

    def test_archive_traversal_is_rejected_without_writing_outside_cache(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("../escape.srt", "bad")
        FastProvider.download_payload = archive.getvalue()
        FastProvider.download_name = "subtitles.zip"
        FastProvider.rows = [subtitle_row("opensubtitles", "The.Matrix.1999.1080p.BluRay")]
        service = self.service({"opensubtitles": FastProvider})
        result = service.search("session", self.media_payload)["results"][0]
        with self.assertRaisesRegex(SubtitleServiceError, "unsafe"):
            service.download("session", result["result_id"], self.media_payload)
        self.assertFalse((self.cache.parent / "escape.srt").exists())

    def test_unapproved_extension_and_binary_text_are_rejected(self):
        FastProvider.rows = [subtitle_row("opensubtitles", "release")]
        service = self.service({"opensubtitles": FastProvider})
        result = service.search("session", self.media_payload)["results"][0]
        FastProvider.download_name = "payload.exe"
        with self.assertRaisesRegex(SubtitleServiceError, "format"):
            service.download("session", result["result_id"], self.media_payload)
        FastProvider.download_name = "payload.srt"
        FastProvider.download_payload = b"\x00\x01\x02"
        with self.assertRaisesRegex(SubtitleServiceError, "invalid"):
            service.download("session", result["result_id"], self.media_payload)

    def test_expanded_subtitle_size_limit_rejects_archive_bomb(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            output.writestr("oversized.srt", b"a" * (5 * 1024 * 1024 + 1))
        FastProvider.download_payload = archive.getvalue()
        FastProvider.download_name = "subtitles.zip"
        FastProvider.rows = [subtitle_row("opensubtitles", "release")]
        service = self.service({"opensubtitles": FastProvider})
        result = service.search("session", self.media_payload)["results"][0]
        with self.assertRaisesRegex(SubtitleServiceError, "too large"):
            service.download("session", result["result_id"], self.media_payload)

    def test_rate_limit_is_diagnostic_and_skips_provider_until_cooldown(self):
        service = self.service({"opensubtitles": RateLimitedProvider})
        first = service.search("session", self.media_payload)
        self.assertEqual(first["diagnostics"]["opensubtitles"]["state"], "rate_limited")
        second = service.search("session-2", self.media_payload)
        self.assertEqual(second["results"], [])
        self.assertGreater(
            second["diagnostics"]["opensubtitles"]["rate_limited_until"],
            int(time.time()),
        )

    def test_result_ids_are_session_scoped_and_expire(self):
        FastProvider.rows = [subtitle_row("opensubtitles", "release")]
        now = [1000]
        service = SubtitleService(
            self.config,
            lambda: self.cache,
            clock=lambda: now[0],
            provider_classes={"opensubtitles": FastProvider},
        )
        result = service.search("session", self.media_payload)["results"][0]
        with self.assertRaisesRegex(SubtitleServiceError, "expired"):
            service.download("other", result["result_id"], self.media_payload)
        now[0] += 1000
        with self.assertRaisesRegex(SubtitleServiceError, "expired"):
            service.download("session", result["result_id"], self.media_payload)

    def test_redaction_removes_credentials_and_sensitive_urls(self):
        value = redact_sensitive_text(
            "https://example.invalid?q=1&api_key=abc password=hunter2 "
            "Authorization=Bearer-token Bearer ey.secret"
        )
        self.assertNotIn("abc", value)
        self.assertNotIn("hunter2", value)
        self.assertNotIn("ey.secret", value)


if __name__ == "__main__":
    unittest.main()
