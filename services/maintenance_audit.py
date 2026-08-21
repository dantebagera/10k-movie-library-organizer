"""Catalog-backed maintenance projections for the local movie archive."""

import json
import os
import re
import time

from services.identity_verification import verify_catalog_identity
from services.media_file_facts import (
    FILE_FACTS_VERSION,
    QUALITY_CLASSIFIER_VERSION,
    quality_display,
)
from services.movie_identity import group_identity_records


RESOLUTION_RANK = {"4K": 4, "1080p": 3, "720p": 2, "480p": 1, "Unknown": 0}
RIP_RANK = {
    "BD Remux": 9, "Remux": 8, "Blu-ray": 7, "BDRip": 6,
    "WEB-DL": 5, "WEBRip": 4, "HDRip": 3, "HDTV": 2,
    "DVDRip": 1, "DVDScr": 0, "CAMRip": -1, "HDCAM": -2, "Unknown": -3,
}
_BULK_PLEX_GROUP_LIMIT = 4
_DURATION_TOLERANCE_RATIO = 0.005
_ASPECT_RATIO_TOLERANCE = 0.03
_FRAME_COUNT_TOLERANCE_RATIO = 0.005
_STRONG_PIXEL_ADVANTAGE = 1.5
_DECISIVE_PIXEL_ADVANTAGE = 4.0
_TIED_PIXEL_RATIO = 1.05
_LOSSLESS_AUDIO_CODECS = {
    "alac",
    "flac",
    "mlp fba",
    "pcm",
    "truehd",
    "wave",
}


def format_size(size):
    size = int(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _text(value):
    return str(value or "").strip()


def _identity_state(candidate, record):
    state = _text(candidate.get("identity_status") or record.get("identity_status") or candidate.get("metadata_status") or record.get("metadata_status")).lower()
    return {"needs_review": "review", "candidate": "review"}.get(state, state or "unmatched")


def _metadata_hint(item):
    if item["metadata_status"] == "conflict":
        return "Accepted identity has contradictory public IDs. Review the exact movie before changing it."
    if item["metadata_status"] == "unverified":
        if item.get("enrichment_needed"):
            return "Filename and Plex agree on another title. Check TMDB aliases before deciding whether the accepted identity is wrong."
        return "Filename and Plex still disagree with the accepted identity after alias verification."
    if item["metadata_status"] == "review":
        return "A possible identity exists but still needs human approval."
    if item["fixable_path"]:
        return "The file is nested too deeply for a conventional movie-library layout."
    if not item["suggested_title"]:
        return "The filename cannot provide a usable movie identity."
    return "No accepted movie identity is stored for this file."


def _item_from_candidate(candidate):
    record = dict(candidate.get("raw_json") or {})
    plex = dict(candidate.get("plex_json") or {})
    manual = dict(candidate.get("manual_json") or {})
    tmdb = dict(candidate.get("tmdb_json") or {})
    path = _text(candidate.get("path") or record.get("path"))
    filename = _text(record.get("filename")) or os.path.basename(path)
    title = _text(
        candidate.get("identity_title")
        or record.get("identity_title")
        or record.get("accepted_title")
        or manual.get("title")
        or plex.get("plex_title")
        or tmdb.get("title")
        or record.get("parsed_title")
    )
    year = _text(
        candidate.get("identity_year")
        or record.get("identity_year")
        or record.get("accepted_year")
        or manual.get("year")
        or plex.get("plex_year")
        or tmdb.get("year")
        or record.get("parsed_year")
    )
    library_root = _text(candidate.get("library_root") or record.get("library_root"))
    try:
        depth = len(os.path.relpath(path, library_root).split(os.sep)) - 1 if library_root else 0
    except ValueError:
        depth = 0
    verification = verify_catalog_identity(candidate)
    identity_state = _identity_state(candidate, record)
    identity_conflict = verification["classification"] == "hard_conflict"
    metadata_accepted = bool(candidate.get("metadata_accepted") or record.get("metadata_accepted") or identity_state == "accepted")
    metadata_status = (
        "conflict"
        if identity_conflict
        else "unverified"
        if metadata_accepted and verification["classification"] == "unverified"
        else "accepted"
        if metadata_accepted
        else identity_state
    )
    observations = verification.get("observations") or {}
    observed = observations.get("parsed") or observations.get("plex") or {}
    audio_tracks_json = candidate.get("audio_tracks_json") or record.get("audio_tracks_json") or "[]"
    try:
        audio_tracks = json.loads(audio_tracks_json) if isinstance(audio_tracks_json, str) else list(audio_tracks_json)
    except (TypeError, ValueError):
        audio_tracks = []
    if not isinstance(audio_tracks, list):
        audio_tracks = []
    item = {
        "path": path,
        "filename": filename,
        "library_root": library_root,
        "title": title,
        "year": year,
        "suggested_title": _text(observed.get("title")) or title,
        "suggested_year": _text(observed.get("year")) or year,
        "accepted_title": title,
        "accepted_year": year,
        "parsed_title": _text(record.get("parsed_title")),
        "parsed_year": _text(record.get("parsed_year")),
        "resolution": _text(candidate.get("resolution") or record.get("resolution")) or "Unknown",
        "rip_source": _text(candidate.get("rip_source") or record.get("rip_source")) or "Unknown",
        "size": int(candidate.get("size") or record.get("size") or 0),
        "video_width": int(candidate.get("video_width") or record.get("video_width") or 0),
        "video_height": int(candidate.get("video_height") or record.get("video_height") or 0),
        "video_codec": _text(candidate.get("video_codec") or record.get("video_codec")),
        "video_profile": _text(candidate.get("video_profile") or record.get("video_profile")),
        "video_bit_depth": int(candidate.get("video_bit_depth") or record.get("video_bit_depth") or 0),
        "video_bitrate": int(candidate.get("video_bitrate") or record.get("video_bitrate") or 0),
        "video_frame_rate": float(candidate.get("video_frame_rate") or record.get("video_frame_rate") or 0),
        "duration_ms": int(candidate.get("duration_ms") or record.get("duration_ms") or 0),
        "audio_codec": _text(candidate.get("audio_codec") or record.get("audio_codec")),
        "audio_channels": float(candidate.get("audio_channels") or record.get("audio_channels") or 0),
        "audio_bitrate": int(candidate.get("audio_bitrate") or record.get("audio_bitrate") or 0),
        "audio_tracks": [track for track in audio_tracks if isinstance(track, dict)],
        "filename_quality_claim": _text(candidate.get("filename_quality_claim") or record.get("filename_quality_claim")),
        "quality_class": _text(candidate.get("quality_class") or record.get("quality_class") or candidate.get("resolution") or record.get("resolution")) or "Unknown",
        "quality_source": _text(candidate.get("quality_source") or record.get("quality_source")),
        "quality_conflict": bool(candidate.get("quality_conflict") or record.get("quality_conflict")),
        "quality_nonstandard": bool(candidate.get("quality_nonstandard") or record.get("quality_nonstandard")),
        "file_facts_version": int(candidate.get("file_facts_version") or record.get("file_facts_version") or 0),
        "classifier_version": int(candidate.get("classifier_version") or record.get("classifier_version") or 0),
        "probe_status": _text(candidate.get("probe_status") or record.get("probe_status")) or "unprobed",
        "probe_error": _text(candidate.get("probe_error") or record.get("probe_error")),
        "tmdb_id": _text(candidate.get("tmdb_id") or record.get("tmdb_id") or manual.get("tmdb_id") or plex.get("tmdb_id")),
        "imdb_id": _text(candidate.get("imdb_id") or record.get("imdb_id") or manual.get("imdb_id") or plex.get("imdb_id")),
        "plex_guid": _text(candidate.get("plex_guid") or record.get("plex_guid") or manual.get("plex_guid") or plex.get("plex_guid")),
        "plex_title": _text(plex.get("plex_title")),
        "plex_year": _text(plex.get("plex_year")),
        "plex_matched": bool(plex),
        "rating_key": _text(candidate.get("plex_rating_key") or record.get("plex_rating_key") or plex.get("rating_key")),
        "metadata_status": metadata_status,
        "metadata_accepted": metadata_accepted,
        "identity_status": identity_state,
        "identity_conflict": identity_conflict,
        "identity_verified": verification["classification"] == "verified",
        "verification_status": verification["classification"],
        "verification_reasons": verification.get("reasons", []),
        "metadata_drift": bool(verification.get("metadata_drift")),
        "drift_reasons": verification.get("drift_reasons", []),
        "observations": observations,
        "enrichment_needed": bool(verification.get("enrichment_needed")),
        "depth": depth,
        "fixable_path": depth > 1,
    }
    item["size_human"] = format_size(item["size"])
    item["file_size"] = item["size_human"]
    item["resolution_rank"] = RESOLUTION_RANK.get(item["resolution"], 0)
    item["rip_rank"] = RIP_RANK.get(item["rip_source"], -3)
    item["quality_display"] = quality_display(item)
    item["metadata_hint"] = _metadata_hint(item)
    return item


def _split_bulk_plex_groups(groups):
    split = []
    for group in groups:
        if len(group) <= _BULK_PLEX_GROUP_LIMIT or not any(item.get("plex_title") for item in group):
            split.append(group)
            continue
        buckets = {}
        for item in group:
            title = _text(item.get("parsed_title"))
            year = _text(item.get("parsed_year"))
            if title:
                buckets.setdefault((title.lower(), year), []).append(item)
        split.extend(buckets.values())
    return split


def _content_fact_blockers(item):
    filename = item.get("filename") or "copy"
    blockers = []
    if item.get("probe_status") != "ok":
        blockers.append(f"{filename}: the media probe did not complete successfully")
    if int(item.get("file_facts_version") or 0) < FILE_FACTS_VERSION:
        blockers.append(f"{filename}: measured file facts are outdated")
    if int(item.get("classifier_version") or 0) < QUALITY_CLASSIFIER_VERSION:
        blockers.append(f"{filename}: the resolution classification is outdated")
    missing = []
    if int(item.get("video_width") or 0) <= 0 or int(item.get("video_height") or 0) <= 0:
        missing.append("video dimensions")
    if int(item.get("duration_ms") or 0) <= 0:
        missing.append("runtime")
    if not _text(item.get("video_codec")):
        missing.append("video codec")
    if not _text(item.get("audio_codec")):
        missing.append("primary-audio codec")
    if float(item.get("audio_channels") or 0) <= 0:
        missing.append("primary-audio channels")
    if missing:
        blockers.append(f"{filename}: missing {', '.join(missing)}")
    return blockers


def _optional_fact_warnings(*items):
    warnings = []
    for item in items:
        missing = []
        if item.get("quality_conflict"):
            warnings.append(
                f"{item.get('filename') or 'copy'}: the filename claims "
                f"{item.get('filename_quality_claim') or 'another resolution'}, but measured "
                f"{item.get('video_width') or 0} x {item.get('video_height') or 0} is authoritative"
            )
        if int(item.get("video_bitrate") or 0) <= 0:
            missing.append("video bitrate")
        if int(item.get("audio_bitrate") or 0) <= 0:
            missing.append("primary-audio bitrate")
        if missing:
            warnings.append(
                f"{item.get('filename') or 'copy'}: {', '.join(missing)} unavailable; "
                "CP did not treat unavailable bitrate as evidence of lower quality"
            )
    if len(items) == 2:
        left, right = items
        if _text(left.get("video_codec")).lower() != _text(right.get("video_codec")).lower():
            warnings.append(
                f"Video codecs differ: {left.get('video_codec') or 'Unknown'} versus "
                f"{right.get('video_codec') or 'Unknown'}"
            )
        if _text(left.get("audio_codec")).lower() != _text(right.get("audio_codec")).lower():
            warnings.append(
                f"Primary-audio codecs differ: {left.get('audio_codec') or 'Unknown'} versus "
                f"{right.get('audio_codec') or 'Unknown'}"
            )
    return warnings


def _facts_complete(item):
    """Return whether the facts needed for content and feature safety are present.

    Bitrates are supporting evidence, not a prerequisite. Some containers do not
    expose them reliably; a missing bitrate or bit-depth tag must not erase otherwise
    decisive identity, runtime, framing, resolution, codec, and channel evidence.
    """
    return not _content_fact_blockers(item)


def _duration_equivalent(left, right):
    return _duration_evidence(left, right)["equivalent"]


def _aspect_ratio(item):
    width = int(item.get("video_width") or 0)
    height = int(item.get("video_height") or 0)
    return width / height if width and height else 0


def _relative_delta(left, right):
    largest = max(abs(float(left or 0)), abs(float(right or 0)))
    return abs(float(left or 0) - float(right or 0)) / largest if largest else 0.0


def _display_fps(value):
    value = float(value or 0)
    if not value:
        return "unknown"
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _is_cinema_pal_pair(left_fps, right_fps):
    left_fps = float(left_fps or 0)
    right_fps = float(right_fps or 0)
    cinema = lambda value: 23.9 <= value <= 24.1
    pal = lambda value: 24.9 <= value <= 25.1
    return (cinema(left_fps) and pal(right_fps)) or (pal(left_fps) and cinema(right_fps))


def _duration_evidence(
    keeper,
    candidate,
    *,
    tolerance_ratio=_DURATION_TOLERANCE_RATIO,
    tolerance_max_ms=None,
):
    keeper_duration = int(keeper.get("duration_ms") or 0)
    candidate_duration = int(candidate.get("duration_ms") or 0)
    delta_ratio = _relative_delta(keeper_duration, candidate_duration)
    tolerance = max(2_000, int(max(keeper_duration, candidate_duration) * tolerance_ratio))
    if tolerance_max_ms is not None:
        tolerance = min(tolerance, int(tolerance_max_ms))
    if abs(keeper_duration - candidate_duration) <= tolerance:
        reason = (
            "identical runtime"
            if keeper_duration == candidate_duration
            else f"runtime matches within {delta_ratio * 100:.2f}%"
        )
        return {
            "equivalent": True,
            "kind": "same_runtime",
            "reason": reason,
            "duration_delta_percent": round(delta_ratio * 100, 3),
            "frame_count_delta_percent": None,
            "uses_frame_rate": False,
        }

    keeper_fps = float(keeper.get("video_frame_rate") or 0)
    candidate_fps = float(candidate.get("video_frame_rate") or 0)
    if _is_cinema_pal_pair(keeper_fps, candidate_fps):
        keeper_frames = (keeper_duration / 1000) * keeper_fps
        candidate_frames = (candidate_duration / 1000) * candidate_fps
        frame_delta_ratio = _relative_delta(keeper_frames, candidate_frames)
        if frame_delta_ratio <= _FRAME_COUNT_TOLERANCE_RATIO:
            return {
                "equivalent": True,
                "kind": "frame_rate_timing_normalization",
                "reason": (
                    f"{_display_fps(keeper_fps)} and {_display_fps(candidate_fps)} fps timing normalization; "
                    f"estimated frame count matches within {frame_delta_ratio * 100:.2f}%"
                ),
                "duration_delta_percent": round(delta_ratio * 100, 3),
                "frame_count_delta_percent": round(frame_delta_ratio * 100, 3),
                "uses_frame_rate": True,
            }

    if keeper_duration > candidate_duration:
        return {
            "equivalent": True,
            "kind": "keeper_longer",
            "reason": (
                f"keeper is {(keeper_duration - candidate_duration) / 1000:.1f}s longer; "
                "deleting the shorter copy does not discard runtime"
            ),
            "duration_delta_percent": round(delta_ratio * 100, 3),
            "frame_count_delta_percent": None,
            "uses_frame_rate": False,
        }

    return {
        "equivalent": False,
        "kind": "candidate_longer",
        "reason": (
            f"deletion candidate is {(candidate_duration - keeper_duration) / 1000:.1f}s longer "
            f"than the proposed keeper; deletion could lose runtime, and no matching "
            "frame-rate timing normalization was found"
        ),
        "duration_delta_percent": round(delta_ratio * 100, 3),
        "frame_count_delta_percent": None,
        "uses_frame_rate": False,
    }


def _aspect_evidence(left, right, *, tolerance=_ASPECT_RATIO_TOLERANCE):
    delta_ratio = _relative_delta(_aspect_ratio(left), _aspect_ratio(right))
    equivalent = delta_ratio <= tolerance
    if not delta_ratio:
        reason = "identical framing"
    elif equivalent:
        reason = f"framing differs by {delta_ratio * 100:.2f}% (minor crop)"
    else:
        reason = (
            f"framing differs by {delta_ratio * 100:.2f}%; automatic selection allows up to "
            f"{tolerance * 100:.2f}%"
        )
    return {
        "equivalent": equivalent,
        "reason": reason,
        "aspect_delta_percent": round(delta_ratio * 100, 3),
        "uses_aspect_ratio": bool(delta_ratio),
    }


def _edition_tokens(filename):
    normalized = re.sub(r"[^a-z0-9]+", " ", _text(filename).lower()).strip()
    markers = set()
    patterns = (
        ("Extended", r"\bextended\b"),
        ("Director's Cut", r"\b(?:dc|director(?:s| s)? cut)\b"),
        ("Theatrical", r"\btheatrical\b"),
        ("Unrated", r"\bunrated\b"),
        ("Alternate", r"\balternate\b"),
        ("Subbed", r"\bsubbed\b"),
        ("Dubbed", r"\bdubbed\b"),
        ("Multi audio", r"\bmulti audio\b"),
        ("Commentary", r"\bcommentary\b"),
    )
    for label, pattern in patterns:
        if re.search(pattern, normalized):
            markers.add(label)
    return markers


def _edition_warning(left, right):
    left_markers = _edition_tokens(left.get("filename"))
    right_markers = _edition_tokens(right.get("filename"))
    if left_markers == right_markers:
        return ""
    details = []
    left_only = sorted(left_markers - right_markers)
    right_only = sorted(right_markers - left_markers)
    if left_only:
        details.append(f"{left.get('filename')}: {', '.join(left_only)}")
    if right_only:
        details.append(f"{right.get('filename')}: {', '.join(right_only)}")
    return (
        "Filename edition markers differ (" + "; ".join(details) + "). "
        "Runtime and framing still determine content equivalence, but review the cut label before deletion"
    )


def _content_equivalence(
    keeper,
    candidate,
    *,
    duration_tolerance_ratio=_DURATION_TOLERANCE_RATIO,
    duration_tolerance_max_ms=None,
    aspect_tolerance=_ASPECT_RATIO_TOLERANCE,
):
    blockers = _content_fact_blockers(keeper) + _content_fact_blockers(candidate)
    warnings = _optional_fact_warnings(keeper, candidate)
    edition_warning = _edition_warning(keeper, candidate)
    if edition_warning:
        warnings.append(edition_warning)

    duration = None
    if int(keeper.get("duration_ms") or 0) > 0 and int(candidate.get("duration_ms") or 0) > 0:
        duration = _duration_evidence(
            keeper,
            candidate,
            tolerance_ratio=duration_tolerance_ratio,
            tolerance_max_ms=duration_tolerance_max_ms,
        )
        if not duration["equivalent"]:
            blockers.append(duration["reason"])

    aspect = None
    if _pixel_count(keeper) and _pixel_count(candidate):
        aspect = _aspect_evidence(keeper, candidate, tolerance=aspect_tolerance)
        if not aspect["equivalent"]:
            blockers.append(aspect["reason"])

    passed = []
    if duration and duration["equivalent"]:
        passed.append(duration["reason"])
    if aspect and aspect["equivalent"]:
        passed.append(aspect["reason"])

    if blockers:
        kind = (
            "runtime_mismatch"
            if duration and not duration["equivalent"]
            else "framing_mismatch"
            if aspect and not aspect["equivalent"]
            else "incomplete"
        )
    else:
        kind = duration["kind"] if duration else "equivalent"
    return {
        "equivalent": not blockers,
        "kind": kind,
        "reason": "; ".join(passed if not blockers else blockers),
        "blockers": blockers,
        "warnings": warnings,
        "passed": passed,
        "duration_delta_percent": duration["duration_delta_percent"] if duration else None,
        "frame_count_delta_percent": duration["frame_count_delta_percent"] if duration else None,
        "aspect_delta_percent": aspect["aspect_delta_percent"] if aspect else None,
        "uses_frame_rate": bool(duration and duration["uses_frame_rate"]),
        "uses_aspect_ratio": bool(aspect and aspect["uses_aspect_ratio"]),
    }


def _pixel_count(item):
    return int(item.get("video_width") or 0) * int(item.get("video_height") or 0)


def _resolution_rank(item):
    return RESOLUTION_RANK.get(
        _text(item.get("quality_class") or item.get("resolution")) or "Unknown",
        0,
    )


def _primary_audio_comparison(left, right):
    left_lossless = _is_lossless_audio(left.get("audio_codec"))
    right_lossless = _is_lossless_audio(right.get("audio_codec"))
    if left_lossless != right_lossless:
        return {"winner": "left" if left_lossless else "right", "reason": "lossless primary audio"}
    left_channels = float(left.get("audio_channels") or 0)
    right_channels = float(right.get("audio_channels") or 0)
    if left_channels != right_channels:
        return {
            "winner": "left" if left_channels > right_channels else "right",
            "reason": f"{max(left_channels, right_channels):g} versus {min(left_channels, right_channels):g} primary-audio channels",
        }
    left_codec = _text(left.get("audio_codec")).lower()
    right_codec = _text(right.get("audio_codec")).lower()
    left_bitrate = int(left.get("audio_bitrate") or 0)
    right_bitrate = int(right.get("audio_bitrate") or 0)
    if left_codec == right_codec and left_bitrate and right_bitrate:
        ratio = max(left_bitrate, right_bitrate) / min(left_bitrate, right_bitrate)
        if ratio >= 1.2:
            return {
                "winner": "left" if left_bitrate > right_bitrate else "right",
                "reason": f"{ratio:.2f}x primary-audio bitrate",
            }
    if left_codec != right_codec:
        return {"winner": None, "reason": "different lossy primary-audio codecs"}
    return {"winner": None, "reason": "equivalent primary audio"}


def _visual_comparison(left, right):
    left_pixels = _pixel_count(left)
    right_pixels = _pixel_count(right)
    if not left_pixels or not right_pixels:
        return {"kind": "unknown", "winner": None, "pixel_ratio": 0.0}

    def strongly_dominates(winner, loser):
        winner_width = int(winner.get("video_width") or 0)
        winner_height = int(winner.get("video_height") or 0)
        loser_width = int(loser.get("video_width") or 0)
        loser_height = int(loser.get("video_height") or 0)
        return bool(
            winner_width >= loser_width
            and winner_height >= loser_height
            and _pixel_count(winner) / max(1, _pixel_count(loser)) >= _STRONG_PIXEL_ADVANTAGE
            and _resolution_rank(winner) > _resolution_rank(loser)
        )

    if strongly_dominates(left, right):
        return {
            "kind": "strong_advantage",
            "winner": "left",
            "pixel_ratio": left_pixels / right_pixels,
        }
    if strongly_dominates(right, left):
        return {
            "kind": "strong_advantage",
            "winner": "right",
            "pixel_ratio": right_pixels / left_pixels,
        }

    pixel_ratio = max(left_pixels, right_pixels) / min(left_pixels, right_pixels)
    if pixel_ratio <= _TIED_PIXEL_RATIO:
        same_video = (
            _text(left.get("video_codec")).lower() == _text(right.get("video_codec")).lower()
            and int(left.get("video_bit_depth") or 0) == int(right.get("video_bit_depth") or 0)
            and int(left.get("rip_rank", -3)) == int(right.get("rip_rank", -3))
        )
        audio = _primary_audio_comparison(left, right)
        if same_video and audio["winner"]:
            return {
                "kind": "audio_advantage",
                "winner": audio["winner"],
                "pixel_ratio": pixel_ratio,
                "audio_reason": audio["reason"],
            }
        return {
            "kind": "encoding_tradeoff",
            "winner": None,
            "pixel_ratio": pixel_ratio,
            "audio_reason": audio["reason"],
        }
    return {
        "kind": "uncertain_advantage",
        "winner": "left" if left_pixels > right_pixels else "right",
        "pixel_ratio": pixel_ratio,
    }


def _has_decisive_visual_advantage(visual):
    return bool(
        visual.get("kind") == "strong_advantage"
        and float(visual.get("pixel_ratio") or 0) >= _DECISIVE_PIXEL_ADVANTAGE
    )


def _is_lossless_audio(codec):
    normalized = _text(codec).lower()
    return normalized in _LOSSLESS_AUDIO_CODECS or "lossless" in normalized


def _feature_regressions(winner, loser, *, allow_audio_tradeoff=False):
    regressions = []
    warnings = []
    regression_kind = "quality_tradeoff"
    audio = _primary_audio_comparison(winner, loser)
    if audio["winner"] == "right":
        message = f"the deletion candidate has better primary audio ({audio['reason']})"
        if allow_audio_tradeoff:
            warnings.append(
                f"Audio trade-off: {message}; the 4x-or-greater pixel advantage keeps the video recommendation"
            )
        else:
            regressions.append(message)
    elif audio["winner"] is None and audio["reason"] == "different lossy primary-audio codecs":
        message = "primary-audio quality cannot be ordered across the two lossy codecs"
        if allow_audio_tradeoff:
            warnings.append(f"Audio trade-off: {message}; the 4x-or-greater pixel advantage keeps the video recommendation")
        else:
            regressions.append(message)
    return regressions, regression_kind, warnings


def _feature_passes(winner, loser):
    passed = []
    audio = _primary_audio_comparison(winner, loser)
    if audio["winner"] == "left":
        passed.append(f"Keeper has better primary audio ({audio['reason']})")
    elif audio["winner"] is None and audio["reason"] == "equivalent primary audio":
        passed.append("Keeper preserves equivalent primary audio")
    return passed


def _audio_languages(item):
    return {
        _text(track.get("language")).lower()
        for track in item.get("audio_tracks", [])
        if _text(track.get("language"))
    }


_AUDIO_LANGUAGE_LABELS = {
    "eng": "English",
    "fra": "French",
    "deu": "German",
    "spa": "Spanish",
    "ita": "Italian",
    "jpn": "Japanese",
    "kor": "Korean",
    "zho": "Chinese",
    "por": "Portuguese",
    "rus": "Russian",
    "ara": "Arabic",
    "hin": "Hindi",
}


def _audio_language_losses(keeper, candidate):
    losses = _audio_languages(candidate) - _audio_languages(keeper)
    return sorted(_AUDIO_LANGUAGE_LABELS.get(language, language) for language in losses)


def _size_evidence(left, right):
    left_size = int(left.get("size") or 0)
    right_size = int(right.get("size") or 0)
    largest = max(left_size, right_size)
    delta = abs(left_size - right_size)
    if not largest or not delta:
        return {
            "smaller": None,
            "bytes": delta,
            "percent": 0.0,
            "reason": "file sizes are equal",
        }
    smaller = "left" if left_size < right_size else "right"
    return {
        "smaller": smaller,
        "bytes": delta,
        "percent": delta / largest * 100,
        "reason": f"the smaller encode saves {format_size(delta)} ({delta / largest * 100:.1f}%)",
    }


def _pair_comparison(left, right):
    visual = _visual_comparison(left, right)
    decisive = _has_decisive_visual_advantage(visual)
    keeper = left if visual.get("winner") == "left" else right
    candidate = right if keeper is left else left
    content = _content_equivalence(
        keeper,
        candidate,
        aspect_tolerance=_ASPECT_RATIO_TOLERANCE,
    )
    storage = _size_evidence(left, right)
    regressions = []
    feature_warnings = []
    feature_passed = []
    regression_kind = "unique_features"
    audio_language_losses = []
    if visual["winner"] == "left":
        regressions, regression_kind, feature_warnings = _feature_regressions(
            left,
            right,
            allow_audio_tradeoff=decisive,
        )
        feature_passed = _feature_passes(left, right)
        audio_language_losses = _audio_language_losses(left, right)
    elif visual["winner"] == "right":
        regressions, regression_kind, feature_warnings = _feature_regressions(
            right,
            left,
            allow_audio_tradeoff=decisive,
        )
        feature_passed = _feature_passes(right, left)
        audio_language_losses = _audio_language_losses(right, left)
    if audio_language_losses:
        feature_warnings.append(
            "Deletion loses audio language track(s): " + ", ".join(audio_language_losses)
        )
    return {
        "content": content,
        "visual": visual,
        "storage": storage,
        "feature_regressions": regressions,
        "feature_warnings": feature_warnings,
        "feature_passed": feature_passed,
        "regression_kind": regression_kind,
        "audio_language_losses": audio_language_losses,
    }


def _comparison_fields(peer, pair):
    return {
        "comparison_peer": peer.get("filename"),
        "pixel_ratio": round(float(pair["visual"].get("pixel_ratio") or 0), 3),
        "duration_delta_percent": pair["content"].get("duration_delta_percent"),
        "frame_count_delta_percent": pair["content"].get("frame_count_delta_percent"),
        "aspect_delta_percent": pair["content"].get("aspect_delta_percent"),
        "comparison_uses_frame_rate": bool(pair["content"].get("uses_frame_rate")),
        "comparison_uses_aspect_ratio": bool(pair["content"].get("uses_aspect_ratio")),
        "storage_delta_bytes": int(pair["storage"].get("bytes") or 0),
        "storage_delta_percent": round(float(pair["storage"].get("percent") or 0), 2),
        "audio_language_losses": list(pair.get("audio_language_losses") or []),
        "audio_language_loss_keeper": peer.get("filename") if pair.get("audio_language_losses") else "",
    }


def _unique_messages(messages):
    return list(dict.fromkeys(_text(message) for message in messages if _text(message)))


def _shared_identity_evidence(files):
    evidence = []
    for field, label in (("tmdb_id", "TMDB"), ("imdb_id", "IMDb")):
        identities = [_text(file.get(field)) for file in files]
        if identities and all(identities) and len(set(identity.lower() for identity in identities)) == 1:
            evidence.append(f"All copies share {label} identity {identities[0]}")
    return evidence


def _decision_fields(*, blockers=(), warnings=(), passed=()):
    return {
        "decision_blockers": _unique_messages(blockers),
        "decision_warnings": _unique_messages(warnings),
        "decision_passed": _unique_messages(passed),
    }


def _visual_uncertainty_reason(winner, loser, visual):
    ratio = float(visual.get("pixel_ratio") or 0)
    if ratio < _STRONG_PIXEL_ADVANTAGE:
        return (
            f"Pixel advantage is {ratio:.2f}x; automatic recommendation requires at least "
            f"{_STRONG_PIXEL_ADVANTAGE:.2f}x"
        )
    if _resolution_rank(winner) <= _resolution_rank(loser):
        return "The higher-pixel copy does not have a higher recognized resolution class"
    return "The higher-pixel copy is not at least as wide and as tall as the other copy"


def _quality_advantage_reason(winner, loser, pair, *, candidate_view=False):
    visual = pair["visual"]
    if visual.get("kind") == "audio_advantage":
        prefix = f"{winner['filename']} has" if candidate_view else "This copy has"
        return f"{prefix} better primary audio ({visual.get('audio_reason')}) with equivalent video quality"
    ratio = float(visual.get("pixel_ratio") or 0)
    if candidate_view:
        return f"{winner['filename']} has {ratio:.2f}x as many pixels and a higher resolution class"
    return f"This copy has {ratio:.2f}x the pixels of {loser['filename']}"


def _quality_reason_sentence(winner, loser, pair, *, removal):
    visual = pair["visual"]
    if visual.get("kind") == "audio_advantage":
        if removal:
            return (
                f"equivalent video quality; {winner['filename']} has better primary audio "
                f"({visual.get('audio_reason')})"
            )
        return (
            f"equivalent video quality and better primary audio "
            f"({visual.get('audio_reason')}) than {loser['filename']}"
        )
    ratio = float(visual.get("pixel_ratio") or 0)
    return (
        f"{ratio:.2f}× fewer pixels than {winner['filename']}"
        if removal
        else f"{ratio:.2f}× the pixels of {loser['filename']}"
    )


def _tradeoff_reason(left, right, pair):
    dimensions = (
        f"{int(left.get('video_width') or 0)} x {int(left.get('video_height') or 0)}"
        if (
            int(left.get("video_width") or 0) == int(right.get("video_width") or 0)
            and int(left.get("video_height") or 0) == int(right.get("video_height") or 0)
        )
        else "near-identical measured dimensions"
    )
    left_encode = f"{_text(left.get('video_codec'))} {int(left.get('video_bit_depth') or 0)}-bit"
    right_encode = f"{_text(right.get('video_codec'))} {int(right.get('video_bit_depth') or 0)}-bit"
    return (
        f"Encoding trade-off — {dimensions}; {left_encode} versus {right_encode}; "
        f"{pair['storage']['reason']}; cross-codec quality cannot be proven."
    )


def _duplicate_identity_safe(files):
    if not files or not all(file["metadata_accepted"] for file in files):
        return False
    if any(file["verification_status"] in {"unverified", "hard_conflict"} for file in files):
        return False
    for field in ("tmdb_id", "imdb_id"):
        identities = [_text(file.get(field)).lower() for file in files]
        if all(identities) and len(set(identities)) == 1:
            return True
    return False


def _duplicate_groups(items):
    groups = []
    grouped_items = _split_bulk_plex_groups(group_identity_records(items))
    for files in grouped_items:
        if len(files) < 2:
            continue
        ranked = sorted(files, key=lambda item: (
            _facts_complete(item),
            _pixel_count(item),
            int(item.get("video_height") or 0),
            int(item.get("video_width") or 0),
            item["resolution_rank"],
            item["rip_rank"],
            item["filename"].lower(),
        ), reverse=True)
        identity_safe = _duplicate_identity_safe(ranked)
        identity_passed = _shared_identity_evidence(ranked) if identity_safe else []
        pair_results = {}
        for left_index, left in enumerate(ranked):
            for right_index in range(left_index + 1, len(ranked)):
                pair_results[(left_index, right_index)] = _pair_comparison(left, ranked[right_index])

        def oriented_pair(index, other_index):
            left_index, right_index = sorted((index, other_index))
            pair = pair_results[(left_index, right_index)]
            current_side = "left" if index == left_index else "right"
            other_side = "right" if current_side == "left" else "left"
            return pair, current_side, other_side

        def pair_decision(pair, *, blockers=(), warnings=(), passed=(), include_language_loss=True):
            content = pair.get("content") or {}
            feature_warnings = list(pair.get("feature_warnings", []))
            if not include_language_loss:
                feature_warnings = [
                    warning for warning in feature_warnings
                    if not warning.startswith("Deletion loses audio language track(s):")
                ]
            return _decision_fields(
                blockers=[*content.get("blockers", []), *blockers],
                warnings=[
                    *content.get("warnings", []),
                    *feature_warnings,
                    *warnings,
                ],
                passed=[
                    *identity_passed,
                    *content.get("passed", []),
                    *pair.get("feature_passed", []),
                    *passed,
                ],
            )

        output_files = []
        for index, file in enumerate(ranked):
            row = dict(file)
            safe_dominators = []
            uncertain_dominators = []
            safe_dominated = []
            uncertain_dominated = []
            tradeoffs = []
            for other_index, other in enumerate(ranked):
                if other_index == index:
                    continue
                pair, current_side, other_side = oriented_pair(index, other_index)
                winner = pair["visual"].get("winner")
                content_safe = bool(pair["content"].get("equivalent"))
                feature_safe = not pair["feature_regressions"]
                if pair["visual"].get("kind") == "encoding_tradeoff":
                    tradeoffs.append((other, pair))
                elif winner == other_side:
                    target = safe_dominators if content_safe and feature_safe else uncertain_dominators
                    target.append((other, pair))
                elif winner == current_side:
                    target = safe_dominated if content_safe and feature_safe else uncertain_dominated
                    target.append((other, pair))

            if not identity_safe:
                row.update({
                    "role": "candidate",
                    "recommendation": "review",
                    "verdict": "identity_review",
                    "verdict_label": "Identity review required",
                    "verdict_tone": "warning",
                    "reason": "Duplicate files share an identity, but that identity must be confirmed before removal.",
                    **_decision_fields(
                        blockers=[
                            "The accepted movie identity is not confirmed by one shared TMDB or IMDb ID",
                        ],
                        passed=["CP grouped these files as possible copies of the same movie"],
                    ),
                })
            elif safe_dominators:
                peer, pair = max(safe_dominators, key=lambda entry: entry[1]["visual"]["pixel_ratio"])
                ratio = float(pair["visual"]["pixel_ratio"])
                row.update({
                    "role": "candidate",
                    "recommendation": "recommended",
                    "verdict": "recommended_removal",
                    "verdict_label": "Recommended removal",
                    "verdict_tone": "danger",
                    "reason": (
                        f"Recommended removal — {_quality_reason_sentence(peer, file, pair, removal=True)}; "
                        f"{pair['content']['reason'].rstrip('.')}."
                    ),
                    **_comparison_fields(peer, pair),
                    **pair_decision(
                        pair,
                        passed=[
                            _quality_advantage_reason(peer, file, pair, candidate_view=True),
                        ],
                    ),
                })
            elif uncertain_dominators:
                peer, pair = max(uncertain_dominators, key=lambda entry: entry[1]["visual"]["pixel_ratio"])
                ratio = float(pair["visual"]["pixel_ratio"])
                if pair["feature_regressions"]:
                    verdict = pair.get("regression_kind") or "unique_features"
                    label = (
                        "Quality trade-off"
                        if verdict == "quality_tradeoff"
                        else "Unique features detected"
                    )
                    explanation = "; ".join(pair["feature_regressions"])
                else:
                    verdict = "lower_quality_verify_cut"
                    label = "Lower quality · verify cut"
                    explanation = pair["content"]["reason"]
                decision_blockers = list(pair["feature_regressions"])
                if not decision_blockers and not pair["content"].get("blockers"):
                    decision_blockers.append(_visual_uncertainty_reason(peer, file, pair["visual"]))
                row.update({
                    "role": "candidate",
                    "recommendation": "review",
                    "verdict": verdict,
                    "verdict_label": label,
                    "verdict_tone": "warning",
                    "reason": (
                        f"{label} — {ratio:.2f}× fewer pixels than {peer['filename']}; "
                        f"{explanation.rstrip('.')}."
                    ),
                    **_comparison_fields(peer, pair),
                    **pair_decision(
                        pair,
                        blockers=decision_blockers,
                        passed=[f"{peer['filename']} has {ratio:.2f}x as many pixels"],
                    ),
                })
            elif safe_dominated:
                peer, pair = max(safe_dominated, key=lambda entry: entry[1]["visual"]["pixel_ratio"])
                ratio = float(pair["visual"]["pixel_ratio"])
                row.update({
                    "role": "keep",
                    "recommendation": "keep",
                    "verdict": "recommended_keep",
                    "verdict_label": "Recommended keep",
                    "verdict_tone": "success",
                    "reason": (
                        f"Recommended keep — {_quality_reason_sentence(file, peer, pair, removal=False)}; "
                        f"{pair['content']['reason'].rstrip('.')}."
                    ),
                    **_comparison_fields(peer, pair),
                    **pair_decision(
                        pair,
                        passed=[
                            _quality_advantage_reason(file, peer, pair),
                            "CP recommends keeping this stronger copy",
                        ],
                        include_language_loss=False,
                    ),
                    "audio_language_losses": [],
                    "audio_language_loss_keeper": "",
                })
            elif uncertain_dominated:
                peer, pair = max(uncertain_dominated, key=lambda entry: entry[1]["visual"]["pixel_ratio"])
                ratio = float(pair["visual"]["pixel_ratio"])
                explanation = (
                    "; ".join(pair["feature_regressions"])
                    if pair["feature_regressions"]
                    else pair["content"]["reason"]
                )
                decision_blockers = list(pair["feature_regressions"])
                if not decision_blockers and not pair["content"].get("blockers"):
                    decision_blockers.append(_visual_uncertainty_reason(file, peer, pair["visual"]))
                row.update({
                    "role": "keep",
                    "recommendation": "review",
                    "verdict": "quality_winner_verify_cut",
                    "verdict_label": "Quality winner · verify cut",
                    "verdict_tone": "warning",
                    "reason": (
                        f"Quality winner — {ratio:.2f}× the pixels of {peer['filename']}; "
                        f"{explanation.rstrip('.')}."
                    ),
                    **_comparison_fields(peer, pair),
                    **pair_decision(
                        pair,
                        blockers=decision_blockers,
                        passed=[f"This copy has {ratio:.2f}x the pixels of {peer['filename']}"],
                        include_language_loss=False,
                    ),
                    "audio_language_losses": [],
                    "audio_language_loss_keeper": "",
                })
            elif tradeoffs:
                peer, pair = max(
                    tradeoffs,
                    key=lambda entry: int(entry[1]["storage"].get("bytes") or 0),
                )
                row.update({
                    "role": "tradeoff",
                    "recommendation": "review",
                    "verdict": "encoding_tradeoff",
                    "verdict_label": "Encoding trade-off",
                    "verdict_tone": "neutral",
                    "reason": _tradeoff_reason(file, peer, pair),
                    **_comparison_fields(peer, pair),
                    **pair_decision(
                        pair,
                        blockers=[
                            "Neither copy has a decisive resolution advantage; cross-codec encoding quality cannot be proven",
                        ],
                    ),
                })
            else:
                row.update({
                    "role": "candidate",
                    "recommendation": "review",
                    "verdict": "manual_comparison",
                    "verdict_label": "Manual comparison",
                    "verdict_tone": "warning",
                    "reason": "No copy has a strong, safely equivalent technical advantage.",
                    **_decision_fields(
                        blockers=[
                            "No copy reaches the decisive technical advantage required for automatic selection",
                        ],
                        passed=identity_passed,
                    ),
                })
            output_files.append(row)

        verdict_order = {
            "recommended_keep": 0,
            "quality_winner_verify_cut": 1,
            "encoding_tradeoff": 2,
            "quality_tradeoff": 3,
            "unique_features": 4,
            "identity_review": 5,
            "manual_comparison": 6,
            "lower_quality_verify_cut": 7,
            "recommended_removal": 8,
        }
        output_files.sort(key=lambda row: (
            verdict_order.get(row.get("verdict"), 9),
            -_pixel_count(row),
            row["filename"].lower(),
        ))
        representative = max(ranked, key=lambda item: (
            bool(item.get("title")),
            _pixel_count(item),
            item["filename"].lower(),
        ))
        title = representative["title"] or representative["plex_title"] or representative["parsed_title"] or representative["filename"]
        year = representative["year"] or representative["plex_year"] or representative["parsed_year"]
        reclaimable = sum(
            int(file.get("size") or 0)
            for file in output_files
            if file.get("recommendation") == "recommended"
        )
        possible_reclaimable = max(
            0,
            sum(int(file.get("size") or 0) for file in output_files)
            - max(int(file.get("size") or 0) for file in output_files),
        )
        groups.append({
            "key": "|".join(sorted(file["path"] for file in ranked)),
            "title": f"{title}{f' ({year})' if year else ''}",
            "files": output_files,
            "identity_safe": identity_safe,
            "needs_identity_review": not identity_safe,
            "reclaimable_bytes": reclaimable,
            "reclaimable_human": format_size(reclaimable),
            "possible_reclaimable_bytes": possible_reclaimable,
            "possible_reclaimable_human": format_size(possible_reclaimable),
            "recommended_count": sum(
                file["recommendation"] == "recommended"
                for file in output_files
            ),
            "comparison_scope": "Measured video, runtime, framing, and audio; subtitles excluded",
        })
    return sorted(groups, key=lambda group: group["title"].lower())


def build_maintenance_audit(candidates, generation=0):
    """Build a maintenance view from the persisted catalog without walking disks."""
    items = [_item_from_candidate(candidate) for candidate in candidates if _text(candidate.get("path") or (candidate.get("raw_json") or {}).get("path"))]
    duplicates = _duplicate_groups(items)
    grouped_by_path = {
        item["path"]: group
        for group in duplicates
        for item in group["files"]
    }
    upgrades = [
        item for item in items
        if item["metadata_accepted"] and item["identity_verified"]
        and item["resolution_rank"] < RESOLUTION_RANK["1080p"]
        and not any(
            other["resolution_rank"] >= RESOLUTION_RANK["1080p"]
            for other in (grouped_by_path.get(item["path"], {}).get("files") or [])
        )
    ]
    unmatched = [
        item for item in items
        if not item["metadata_accepted"] and item["metadata_status"] != "pending"
    ]
    verification = [
        item for item in items
        if item["metadata_accepted"] and item["verification_status"] in {"unverified", "hard_conflict"}
    ]
    audit_pending = sum(
        1 for item in items
        if item["metadata_accepted"] and item["verification_status"] == "audit_pending"
    )
    pending = sum(1 for item in items if not item["metadata_accepted"] and item["metadata_status"] == "pending")
    extra_copies = sum(max(0, len(group["files"]) - 1) for group in duplicates)
    reclaimable = sum(group["reclaimable_bytes"] for group in duplicates)
    recommended = sum(group["recommended_count"] for group in duplicates)
    return {
        "source": "catalog",
        "generation": int(generation or 0),
        "generated_at": time.time(),
        "summary": {
            "duplicate_groups": len(duplicates),
            "extra_copies": extra_copies,
            "reclaimable_bytes": reclaimable,
            "reclaimable_human": format_size(reclaimable),
            "recommended_removals": recommended,
            "upgrade_candidates": len(upgrades),
            "identity_issues": len(unmatched) + len(verification),
            "unmatched_files": len(unmatched),
            "verification_gaps": len(verification),
            "automated_identity_checks": audit_pending,
            "hard_conflicts": sum(item["identity_conflict"] for item in verification),
            "metadata_drift": sum(item["metadata_drift"] for item in items),
            "metadata_pending": pending,
        },
        "storage": {"groups": duplicates},
        "upgrades": {"items": sorted(upgrades, key=lambda item: (item["title"].lower(), item["path"].lower()))},
        "identity": {
            "items": sorted(unmatched, key=lambda item: item["filename"].lower()),
            "verification": sorted(
                verification,
                key=lambda item: (item["metadata_status"] != "conflict", item["filename"].lower()),
            ),
        },
    }
