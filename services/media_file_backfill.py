"""Bounded coordinator for versioned SQL media-file-facts backfill."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, Callable

from services.media_file_facts import (
    FILE_FACTS_VERSION,
    QUALITY_CLASSIFIER_VERSION,
    MediaFileFacts,
    classify_dimensions,
    filename_quality_claim,
    probe_media_file,
)


DEFAULT_BATCH_SIZE = 8
DEFAULT_RECLASSIFY_BATCH_SIZE = 100
DEFAULT_CONCURRENCY = 2
MAX_CONCURRENCY = 4
MAX_FAILURE_SUMMARY = 25


def _inside_root(path: str, roots: list[str]) -> bool:
    normalized_path = os.path.normcase(os.path.abspath(path))
    for root in roots:
        normalized_root = os.path.normcase(os.path.abspath(root))
        try:
            if os.path.commonpath([normalized_path, normalized_root]) == normalized_root:
                return True
        except ValueError:
            continue
    return False


def _failure(row: dict[str, Any], status: str, error: str, *, stat_result=None) -> MediaFileFacts:
    claim = filename_quality_claim(row.get("filename") or row.get("path") or "")
    decision = classify_dimensions(0, 0, claim)
    return MediaFileFacts(
        filename_quality_claim=claim,
        quality_class=decision.quality_class,
        quality_source=decision.source,
        quality_conflict=decision.conflict,
        quality_nonstandard=decision.nonstandard,
        probe_status=status,
        probed_at=time.time(),
        probe_error=error,
        probe_size=int(stat_result.st_size) if stat_result is not None else 0,
        probe_modified_time=float(stat_result.st_mtime) if stat_result is not None else 0.0,
    )


def _probe_row(
    row: dict[str, Any],
    roots: list[str],
    probe: Callable[[str], MediaFileFacts],
) -> tuple[dict[str, Any], MediaFileFacts, float, bool]:
    started = time.perf_counter()
    if _can_reclassify_from_stored(row):
        stored = MediaFileFacts(**{
            field.name: row.get(field.name, field.default)
            for field in fields(MediaFileFacts)
        })
        decision = classify_dimensions(
            stored.video_width,
            stored.video_height,
            stored.filename_quality_claim,
        )
        return row, replace(
            stored,
            quality_class=decision.quality_class,
            quality_source=decision.source,
            quality_conflict=decision.conflict,
            quality_nonstandard=decision.nonstandard,
            classifier_version=QUALITY_CLASSIFIER_VERSION,
        ), 0.0, True

    path = str(row.get("path") or "")
    if not path or not _inside_root(path, roots):
        return row, _failure(row, "inaccessible", "outside_library_root"), 0.0, False
    try:
        before = os.stat(path)
    except FileNotFoundError:
        return row, _failure(row, "missing", "missing"), 0.0, False
    except PermissionError:
        return row, _failure(row, "inaccessible", "access_denied"), 0.0, False
    except OSError:
        return row, _failure(row, "inaccessible", "stat_failed"), 0.0, False
    expected_size = int(row.get("size") or 0)
    expected_modified = float(row.get("modified_time") or 0)
    if (
        before.st_size != expected_size
        or abs(float(before.st_mtime) - expected_modified) > 0.001
    ):
        return row, _failure(
            row,
            "file_changed",
            "catalog_fingerprint_changed",
            stat_result=before,
        ), 0.0, False
    facts = probe(path)
    elapsed_ms = (time.perf_counter() - started) * 1000
    if (
        facts.file_facts_version != FILE_FACTS_VERSION
        or facts.classifier_version != QUALITY_CLASSIFIER_VERSION
    ):
        facts = replace(
            facts,
            file_facts_version=FILE_FACTS_VERSION,
            classifier_version=QUALITY_CLASSIFIER_VERSION,
        )
    return row, facts, elapsed_ms, False


def _can_reclassify_from_stored(row: dict[str, Any]) -> bool:
    return (
        int(row.get("file_facts_version") or 0) == FILE_FACTS_VERSION
        and int(row.get("classifier_version") or 0) < QUALITY_CLASSIFIER_VERSION
        and row.get("probe_status") == "ok"
        and int(row.get("video_width") or 0) > 0
        and int(row.get("video_height") or 0) > 0
        and int(row.get("probe_size") or 0) == int(row.get("size") or 0)
        and abs(
            float(row.get("probe_modified_time") or 0)
            - float(row.get("modified_time") or 0)
        ) <= 0.001
    )


def run_file_facts_backfill(
    repository,
    roots,
    *,
    probe: Callable[[str], MediaFileFacts] = probe_media_file,
    batch_size: int = DEFAULT_BATCH_SIZE,
    concurrency: int = DEFAULT_CONCURRENCY,
    retry_failed: bool = False,
    max_batches: int | None = None,
    cancel_event: threading.Event | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Refresh stale SQL file facts and advance one generation per committed batch."""

    batch_size = min(max(int(batch_size or DEFAULT_BATCH_SIZE), 1), 100)
    concurrency = min(max(int(concurrency or DEFAULT_CONCURRENCY), 1), MAX_CONCURRENCY)
    roots = [str(Path(root).resolve()) for root in roots or [] if str(root or "").strip()]
    cancel_event = cancel_event or threading.Event()
    started = time.perf_counter()
    report = {
        "status": "running",
        "facts_version": FILE_FACTS_VERSION,
        "classifier_version": QUALITY_CLASSIFIER_VERSION,
        "batch_size": batch_size,
        "concurrency": concurrency,
        "batches": 0,
        "selected": 0,
        "probed": 0,
        "reclassified": 0,
        "changed": 0,
        "rejected": 0,
        "failures": 0,
        "failure_summary": [],
        "probe_ms": [],
        "generation_start": repository.generation("media"),
        "generation_end": repository.generation("media"),
        "remaining": repository.file_facts_backfill_remaining(
            retry_failed=retry_failed,
        ),
    }
    attempted = set()
    while not cancel_event.is_set():
        if max_batches is not None and report["batches"] >= int(max_batches):
            report["status"] = "paused"
            break
        available = repository.file_facts_backfill_candidates(
            DEFAULT_RECLASSIFY_BATCH_SIZE,
            retry_failed=retry_failed,
        )
        available = [
            row for row in available
            if row.get("path_key") not in attempted
        ]
        reclassifiable = [
            row for row in available
            if _can_reclassify_from_stored(row)
        ]
        candidates = (
            reclassifiable[:DEFAULT_RECLASSIFY_BATCH_SIZE]
            if reclassifiable
            else available[:batch_size]
        )
        if not candidates:
            report["status"] = "completed"
            break
        report["selected"] += len(candidates)
        results = []
        with ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix="cp-file-facts",
        ) as executor:
            futures = {
                executor.submit(_probe_row, row, roots, probe): row
                for row in candidates
            }
            for future in as_completed(futures):
                if cancel_event.is_set():
                    for pending in futures:
                        pending.cancel()
                row, facts, elapsed_ms, reclassified = future.result()
                attempted.add(row.get("path_key"))
                if reclassified:
                    report["reclassified"] += 1
                else:
                    report["probed"] += 1
                if elapsed_ms:
                    report["probe_ms"].append(round(elapsed_ms, 3))
                if facts.probe_status != "ok":
                    report["failures"] += 1
                    if len(report["failure_summary"]) < MAX_FAILURE_SUMMARY:
                        report["failure_summary"].append({
                            "path_key": row.get("path_key"),
                            "status": facts.probe_status,
                            "error": facts.probe_error,
                        })
                results.append({
                    "path_key": row.get("path_key"),
                    "expected_size": int(row.get("size") or 0),
                    "expected_modified_time": float(row.get("modified_time") or 0),
                    "facts": facts.as_record(),
                })
        if not results:
            report["status"] = "cancelled"
            break
        batch_report = repository.apply_file_facts_batch(results)
        report["batches"] += 1
        report["changed"] += int(batch_report.get("changed") or 0)
        report["rejected"] += int(batch_report.get("rejected") or 0)
        report["generation_end"] = repository.generation("media")
        report["remaining"] = repository.file_facts_backfill_remaining(
            retry_failed=False,
        )
        if progress:
            progress(dict(report))
        if cancel_event.is_set():
            report["status"] = "cancelled"
            break

    report["generation_end"] = repository.generation("media")
    report["remaining"] = repository.file_facts_backfill_remaining(
        retry_failed=False,
    )
    report["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    probe_ms = list(report.pop("probe_ms"))
    report["probe_timing_ms"] = {
        "count": len(probe_ms),
        "min": min(probe_ms) if probe_ms else 0,
        "max": max(probe_ms) if probe_ms else 0,
        "average": round(sum(probe_ms) / len(probe_ms), 3) if probe_ms else 0,
    }
    return report
