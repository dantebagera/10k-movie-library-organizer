import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from services.media_file_facts import (
    FILE_FACTS_VERSION,
    classify_dimensions,
    filename_quality_claim,
    probe_media_file,
    quality_display,
)


def track(track_type, **values):
    return SimpleNamespace(track_type=track_type, **values)


class MediaFileFactsTest(unittest.TestCase):
    def test_frozen_dimension_corpus(self):
        cases = (
            (3840, 2160, "Unknown", "4K"),
            (3840, 1608, "2160p", "4K"),
            (3200, 1600, "2160p", "4K"),
            (1920, 1080, "1080p", "1080p"),
            (1920, 800, "1080p", "1080p"),
            (1920, 696, "1080p", "1080p"),
            (1920, 640, "1080p", "1080p"),
            (1920, 500, "1080p", "720p"),
            (1872, 784, "1080p", "1080p"),
            (1856, 800, "1080p", "1080p"),
            (1800, 960, "1080p", "1080p"),
            (1744, 816, "1080p", "1080p"),
            (1480, 800, "1080p", "1080p"),
            (1434, 984, "1080p", "1080p"),
            (1136, 960, "1080p", "1080p"),
            (1280, 720, "720p", "720p"),
            (1280, 536, "720p", "720p"),
            (954, 576, "1080p", "480p"),
            (912, 592, "1080p", "480p"),
            (854, 480, "480p", "480p"),
            (640, 360, "Unknown", "360p"),
            (1080, 1920, "1080p", "1080p"),
            (1080, 1080, "Unknown", "1080p"),
            (720, 1280, "720p", "720p"),
            (0, 0, "1080p", "1080p"),
            (0, 0, "Unknown", "Unknown"),
        )
        for width, height, claim, expected in cases:
            with self.subTest(width=width, height=height, claim=claim):
                self.assertEqual(classify_dimensions(width, height, claim).quality_class, expected)

    def test_filename_claim_prefers_numeric_release_token_over_decorative_uhd(self):
        self.assertEqual(filename_quality_claim("Movie.UHD.BLURAY.1080p.x264.mkv"), "1080p")
        self.assertEqual(filename_quality_claim("Movie.4K.Remastered.720p.x264.mkv"), "720p")
        self.assertEqual(filename_quality_claim("Movie.2160p.UHD.mkv"), "4K")
        self.assertEqual(filename_quality_claim("Movie.4K.Remastered.mkv"), "4K")

    def test_low_measurement_is_not_promoted_by_1080_filename(self):
        decision = classify_dimensions(954, 576, "1080p")
        self.assertEqual(decision.quality_class, "480p")
        self.assertTrue(decision.conflict)
        self.assertEqual(decision.source, "measured_conflict")
        self.assertEqual(
            quality_display({
                "quality_class": decision.quality_class,
                "quality_conflict": decision.conflict,
                "video_width": 954,
                "video_height": 576,
                "filename_quality_claim": "1080p",
                "probe_status": "ok",
            }),
            "Measured 954 x 576 - filename claims 1080p",
        )

    def test_cropped_1080_display_keeps_exact_dimensions(self):
        decision = classify_dimensions(1800, 960, "1080p")
        self.assertTrue(decision.nonstandard)
        self.assertEqual(
            quality_display({
                "quality_class": decision.quality_class,
                "quality_nonstandard": decision.nonstandard,
                "video_width": 1800,
                "video_height": 960,
                "filename_quality_claim": "1080p",
                "probe_status": "ok",
            }),
            "1080-class - 1800 x 960",
        )

    def test_probe_selects_primary_video_and_audio_deterministically(self):
        parsed = SimpleNamespace(tracks=[
            track("General", duration="5780917"),
            track("Video", width="640", height="360", format="MJPEG", duration="1"),
            track(
                "Video", width="1800", height="960", format="HEVC",
                format_profile="Main 10@L4@Main", bit_depth="10", bit_rate="2000527",
                frame_rate="24.000", duration="5780917", display_aspect_ratio="1.875",
                rotation="0.000", default="Yes",
            ),
            track("Audio", format="AAC", channel_s="2", bit_rate="132300", duration="5495616", default="Yes"),
            track("Audio", format="AAC", channel_s="6", bit_rate="384000", duration="5495616", default="No"),
        ])
        with tempfile.TemporaryDirectory() as root:
            movie = Path(root) / "The.Monkey.2025.1080p.x265.10bit.mkv"
            movie.write_bytes(b"fixture")
            result = probe_media_file(movie, parser=lambda _path: parsed, clock=lambda: 123.0)

        self.assertEqual(result.probe_status, "ok")
        self.assertEqual(result.video_width, 1800)
        self.assertEqual(result.video_height, 960)
        self.assertEqual(result.video_codec, "HEVC")
        self.assertEqual(result.video_bit_depth, 10)
        self.assertEqual(result.audio_channels, 2)
        self.assertEqual(result.quality_class, "1080p")
        self.assertEqual(result.file_facts_version, FILE_FACTS_VERSION)

    def test_probe_handles_missing_multiple_and_no_streams_safely(self):
        missing = probe_media_file("Z:/definitely/missing.1080p.mkv", parser=Mock())
        self.assertEqual(missing.probe_status, "missing")
        self.assertEqual(missing.quality_source, "filename_fallback")
        self.assertEqual(missing.quality_class, "1080p")
        self.assertNotIn("Z:", missing.probe_error)

        with tempfile.TemporaryDirectory() as root:
            movie = Path(root) / "audio-only.m4a"
            movie.write_bytes(b"fixture")
            parsed = SimpleNamespace(tracks=[track("Audio", format="AAC", channel_s="2")])
            result = probe_media_file(movie, parser=lambda _path: parsed)
        self.assertEqual(result.probe_status, "no_video")
        self.assertEqual(result.probe_error, "no_video_stream")

    def test_probe_failures_are_bounded_and_never_expose_the_path(self):
        with tempfile.TemporaryDirectory() as root:
            movie = Path(root) / "private-name.1080p.mkv"
            movie.write_bytes(b"fixture")
            inaccessible = probe_media_file(
                movie,
                parser=lambda _path: (_ for _ in ()).throw(PermissionError(str(movie))),
            )
            corrupt = probe_media_file(
                movie,
                parser=lambda _path: (_ for _ in ()).throw(RuntimeError(str(movie))),
            )
            missing_dimensions = probe_media_file(
                movie,
                parser=lambda _path: SimpleNamespace(tracks=[
                    track("Video", width="0", height="0", format="AVC"),
                ]),
            )
            with patch.dict(sys.modules, {"pymediainfo": None}):
                unavailable = probe_media_file(movie)

        self.assertEqual((inaccessible.probe_status, inaccessible.probe_error), ("inaccessible", "access_denied"))
        self.assertEqual((corrupt.probe_status, corrupt.probe_error), ("corrupt", "parse_failed"))
        self.assertEqual((missing_dimensions.probe_status, missing_dimensions.probe_error), ("unsupported", "missing_dimensions"))
        self.assertEqual(
            (unavailable.probe_status, unavailable.probe_error),
            ("mediainfo_unavailable", "mediainfo_unavailable"),
        )
        for result in (inaccessible, corrupt, missing_dimensions, unavailable):
            self.assertNotIn(str(movie), result.probe_error)

    def test_probe_rejects_a_changed_file(self):
        with tempfile.TemporaryDirectory() as root:
            movie = Path(root) / "changing.1080p.mkv"
            movie.write_bytes(b"before")
            real_stat = os.stat
            calls = 0

            def changing_stat(path):
                nonlocal calls
                calls += 1
                result = real_stat(path)
                if calls == 1:
                    return result
                values = list(result)
                values[8] = result.st_mtime + 1
                return os.stat_result(values)

            parsed = SimpleNamespace(tracks=[
                track("Video", width="1920", height="1080", format="AVC"),
            ])
            result = probe_media_file(movie, parser=lambda _path: parsed, stat=changing_stat)

        self.assertEqual(result.probe_status, "file_changed")
        self.assertEqual(result.video_width, 0)
        self.assertEqual(result.quality_source, "filename_fallback")

    def test_probe_normalizes_rotation_and_anamorphic_metadata_without_inflation(self):
        parsed = SimpleNamespace(tracks=[
            track(
                "Video", width="720", height="576", format="AVC",
                display_aspect_ratio="1.778", rotation="90.000",
            ),
        ])
        with tempfile.TemporaryDirectory() as root:
            movie = Path(root) / "anamorphic.mkv"
            movie.write_bytes(b"fixture")
            result = probe_media_file(movie, parser=lambda _path: parsed)
        self.assertEqual((result.video_width, result.video_height), (720, 576))
        self.assertEqual(result.display_aspect_ratio, 1.778)
        self.assertEqual(result.rotation_degrees, 90.0)
        self.assertEqual(result.quality_class, "480p")


if __name__ == "__main__":
    unittest.main()
