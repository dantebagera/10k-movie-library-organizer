"""Authoritative local-media probing and quality classification.

Measured stream facts, filename claims, and the derived compatibility class are
deliberately separate.  This module never writes SQL and never contacts a
metadata provider.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


FILE_FACTS_VERSION = 2
QUALITY_CLASSIFIER_VERSION = 2

QUALITY_RANK = {"4K": 4, "1080p": 3, "720p": 2, "480p": 1, "Unknown": 0}

# Active-picture encodes commonly crop black bars.  The area floors prevent a
# low-resolution file from being promoted merely because one edge is long.
UHD_LONG_EDGE = 3200
UHD_SHORT_EDGE = 1350
UHD_MIN_PIXELS = 5_000_000
FULL_HD_LONG_EDGE = 1700
FULL_HD_UNUSUAL_MIN_EDGE = 800
FULL_HD_MIN_PIXELS = 1_050_000
HD_LONG_EDGE = 1200
HD_SHORT_EDGE = 500
HD_ALT_SHORT_EDGE = 700
SD_LONG_EDGE = 700
SD_SHORT_EDGE = 400

PROBE_COMPLETE_STATUSES = {
    "ok",
    "no_video",
    "unsupported",
    "corrupt",
    "inaccessible",
    "mediainfo_unavailable",
    "missing",
    "file_changed",
}


def _integer(value: Any) -> int:
    try:
        if value is None or value == "":
            return 0
        return int(float(str(value).replace(" ", "")))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def filename_quality_claim(filename: str) -> str:
    """Return the explicit release-name claim without treating it as measured.

    A numeric ``1080p`` token wins over decorative words such as ``UHD`` or
    ``4K Remastered``.  This avoids the legacy precedence bug where a
    ``UHD ... 1080p`` filename was presented as a measured 4K file.
    """

    name = Path(str(filename or "")).name.lower()
    numeric = (
        ("4K", r"(?<!\d)2160p?(?!\d)"),
        ("1080p", r"(?<!\d)1080p?(?!\d)"),
        ("720p", r"(?<!\d)720p?(?!\d)"),
        ("480p", r"(?<!\d)480p?(?!\d)"),
    )
    for label, pattern in numeric:
        if re.search(pattern, name, re.IGNORECASE):
            return label
    if re.search(r"(^|[^a-z0-9])(4k|uhd)([^a-z0-9]|$)", name, re.IGNORECASE):
        return "4K"
    return "Unknown"


@dataclass(frozen=True)
class QualityDecision:
    quality_class: str
    source: str
    conflict: bool
    nonstandard: bool


def classify_dimensions(width: Any, height: Any, claim: str = "Unknown") -> QualityDecision:
    """Classify coded dimensions using explicit active-picture guardrails."""

    width = max(0, _integer(width))
    height = max(0, _integer(height))
    claim = _text(claim) or "Unknown"
    if not width or not height:
        fallback = claim if claim in QUALITY_RANK and claim != "Unknown" else "Unknown"
        return QualityDecision(fallback, "filename_fallback" if fallback != "Unknown" else "unavailable", False, True)

    long_edge = max(width, height)
    short_edge = min(width, height)
    pixels = width * height
    portrait = height > width

    if long_edge >= UHD_LONG_EDGE and short_edge >= UHD_SHORT_EDGE and pixels >= UHD_MIN_PIXELS:
        quality = "4K"
    elif (
        (long_edge >= FULL_HD_LONG_EDGE and pixels >= FULL_HD_MIN_PIXELS)
        or (
            short_edge >= FULL_HD_UNUSUAL_MIN_EDGE
            and pixels >= FULL_HD_MIN_PIXELS
        )
    ):
        quality = "1080p"
    elif (
        (long_edge >= HD_LONG_EDGE and short_edge >= HD_SHORT_EDGE)
        or (long_edge >= 900 and short_edge >= HD_ALT_SHORT_EDGE)
    ):
        quality = "720p"
    elif long_edge >= SD_LONG_EDGE and short_edge >= SD_SHORT_EDGE:
        quality = "480p"
    else:
        quality = f"{short_edge}p" if short_edge else "Unknown"

    conflict = (
        claim in QUALITY_RANK
        and claim != "Unknown"
        and quality in QUALITY_RANK
        and claim != quality
    )
    standard_dimensions = {
        "4K": {(3840, 2160), (2160, 3840)},
        "1080p": {(1920, 1080), (1080, 1920)},
        "720p": {(1280, 720), (720, 1280)},
        "480p": {(854, 480), (720, 480), (480, 854), (480, 720)},
    }
    nonstandard = (width, height) not in standard_dimensions.get(quality, set())
    source = "measured_conflict" if conflict else "measured_portrait" if portrait else "measured"
    return QualityDecision(quality, source, conflict, nonstandard)


@dataclass(frozen=True)
class MediaFileFacts:
    video_width: int = 0
    video_height: int = 0
    video_codec: str = ""
    video_profile: str = ""
    video_bit_depth: int = 0
    video_bitrate: int = 0
    video_frame_rate: float = 0.0
    duration_ms: int = 0
    display_aspect_ratio: float = 0.0
    rotation_degrees: float = 0.0
    audio_codec: str = ""
    audio_channels: float = 0.0
    audio_bitrate: int = 0
    filename_quality_claim: str = "Unknown"
    quality_class: str = "Unknown"
    quality_source: str = "unavailable"
    quality_conflict: bool = False
    quality_nonstandard: bool = True
    file_facts_version: int = FILE_FACTS_VERSION
    classifier_version: int = QUALITY_CLASSIFIER_VERSION
    probe_status: str = "unprobed"
    probed_at: float = 0.0
    probe_error: str = ""
    probe_size: int = 0
    probe_modified_time: float = 0.0

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["quality_conflict"] = bool(record["quality_conflict"])
        record["quality_nonstandard"] = bool(record["quality_nonstandard"])
        record["resolution"] = self.quality_class
        record["quality_display"] = quality_display(record)
        return record


def quality_display(facts: dict[str, Any]) -> str:
    quality = _text(facts.get("quality_class") or facts.get("resolution")) or "Unknown"
    claim = _text(facts.get("filename_quality_claim")) or "Unknown"
    width = _integer(facts.get("video_width"))
    height = _integer(facts.get("video_height"))
    status = _text(facts.get("probe_status"))
    source = _text(facts.get("quality_source"))
    if width and height:
        if bool(facts.get("quality_conflict")):
            return f"Measured {width} x {height} - filename claims {claim}"
        if bool(facts.get("quality_nonstandard")):
            class_label = quality[:-1] if quality.endswith("p") else quality
            return f"{class_label}-class - {width} x {height}"
        return quality
    if source == "filename_fallback" or (status and status != "ok" and claim != "Unknown"):
        return f"Filename claim {claim} (unmeasured)"
    return quality


def _track_value(track: Any, name: str, default: Any = None) -> Any:
    if isinstance(track, dict):
        return track.get(name, default)
    return getattr(track, name, default)


def _is_yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1"}


def _primary_video(tracks: Iterable[Any]) -> Any | None:
    videos = [
        (index, track)
        for index, track in enumerate(tracks)
        if _text(_track_value(track, "track_type")).lower() == "video"
    ]
    if not videos:
        return None
    return max(
        videos,
        key=lambda pair: (
            _is_yes(_track_value(pair[1], "default")),
            _integer(_track_value(pair[1], "width")) * _integer(_track_value(pair[1], "height")),
            _integer(_track_value(pair[1], "duration")),
            _integer(_track_value(pair[1], "bit_rate")),
            -pair[0],
        ),
    )[1]


def _primary_audio(tracks: Iterable[Any]) -> Any | None:
    audios = [
        (index, track)
        for index, track in enumerate(tracks)
        if _text(_track_value(track, "track_type")).lower() == "audio"
    ]
    if not audios:
        return None
    return max(
        audios,
        key=lambda pair: (
            _is_yes(_track_value(pair[1], "default")),
            _float(_track_value(pair[1], "channel_s")),
            _integer(_track_value(pair[1], "bit_rate")),
            _integer(_track_value(pair[1], "duration")),
            -pair[0],
        ),
    )[1]


def _probe_failure(
    filename: str,
    status: str,
    error: str,
    stat_result: os.stat_result | None,
    now: float,
) -> MediaFileFacts:
    claim = filename_quality_claim(filename)
    decision = classify_dimensions(0, 0, claim)
    return MediaFileFacts(
        filename_quality_claim=claim,
        quality_class=decision.quality_class,
        quality_source=decision.source,
        quality_conflict=decision.conflict,
        quality_nonstandard=decision.nonstandard,
        probe_status=status,
        probed_at=now,
        probe_error=error,
        probe_size=int(stat_result.st_size) if stat_result else 0,
        probe_modified_time=float(stat_result.st_mtime) if stat_result else 0.0,
    )


def probe_media_file(
    path: str | os.PathLike[str],
    *,
    parser: Callable[[str], Any] | None = None,
    clock: Callable[[], float] = time.time,
    stat: Callable[[str], os.stat_result] = os.stat,
) -> MediaFileFacts:
    """Probe one stable file once and return a complete immutable fact set."""

    path = os.fspath(path)
    filename = os.path.basename(path)
    now = float(clock())
    try:
        before = stat(path)
    except FileNotFoundError:
        return _probe_failure(filename, "missing", "missing", None, now)
    except PermissionError:
        return _probe_failure(filename, "inaccessible", "access_denied", None, now)
    except OSError:
        return _probe_failure(filename, "inaccessible", "stat_failed", None, now)

    if parser is None:
        try:
            from pymediainfo import MediaInfo
        except (ImportError, OSError):
            return _probe_failure(filename, "mediainfo_unavailable", "mediainfo_unavailable", before, now)
        parser = MediaInfo.parse

    try:
        parsed = parser(path)
        tracks = list(_track_value(parsed, "tracks", []) or [])
    except PermissionError:
        return _probe_failure(filename, "inaccessible", "access_denied", before, now)
    except (FileNotFoundError, OSError):
        return _probe_failure(filename, "inaccessible", "read_failed", before, now)
    except Exception:
        return _probe_failure(filename, "corrupt", "parse_failed", before, now)

    try:
        after = stat(path)
    except OSError:
        return _probe_failure(filename, "file_changed", "post_probe_stat_failed", before, now)
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        return _probe_failure(filename, "file_changed", "file_changed", after, now)

    video = _primary_video(tracks)
    if video is None:
        return _probe_failure(filename, "no_video", "no_video_stream", after, now)
    audio = _primary_audio(tracks)
    width = _integer(_track_value(video, "width"))
    height = _integer(_track_value(video, "height"))
    if not width or not height:
        return _probe_failure(filename, "unsupported", "missing_dimensions", after, now)

    claim = filename_quality_claim(filename)
    decision = classify_dimensions(width, height, claim)
    duration = _integer(_track_value(video, "duration"))
    if not duration:
        general = next(
            (
                track for track in tracks
                if _text(_track_value(track, "track_type")).lower() == "general"
            ),
            None,
        )
        duration = _integer(_track_value(general, "duration")) if general is not None else 0
    return MediaFileFacts(
        video_width=width,
        video_height=height,
        video_codec=_text(_track_value(video, "format")),
        video_profile=_text(_track_value(video, "format_profile")),
        video_bit_depth=_integer(_track_value(video, "bit_depth")),
        video_bitrate=_integer(_track_value(video, "bit_rate")),
        video_frame_rate=_float(_track_value(video, "frame_rate")),
        duration_ms=duration,
        display_aspect_ratio=_float(_track_value(video, "display_aspect_ratio")),
        rotation_degrees=_float(_track_value(video, "rotation")),
        audio_codec=_text(_track_value(audio, "format")) if audio is not None else "",
        audio_channels=_float(_track_value(audio, "channel_s")) if audio is not None else 0.0,
        audio_bitrate=_integer(_track_value(audio, "bit_rate")) if audio is not None else 0,
        filename_quality_claim=claim,
        quality_class=decision.quality_class,
        quality_source=decision.source,
        quality_conflict=decision.conflict,
        quality_nonstandard=decision.nonstandard,
        probe_status="ok",
        probed_at=now,
        probe_error="",
        probe_size=int(after.st_size),
        probe_modified_time=float(after.st_mtime),
    )
