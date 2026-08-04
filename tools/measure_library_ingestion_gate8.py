"""Isolated Gate 8 native-observer soak and event-latency measurement."""

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.library_observer import LibraryObserverAdapter


class _RecordingCoordinator:
    def __init__(self, created_at):
        self.dependencies = SimpleNamespace(video_extensions=frozenset({".mkv", ".mp4"}))
        self.created_at = created_at
        self.latencies_ms = []
        self.seen_paths = set()
        self.calls = 0
        self._condition = threading.Condition()

    def _record(self, paths):
        now = time.perf_counter()
        with self._condition:
            for path in paths:
                created = self.created_at.get(os.path.normcase(os.path.normpath(str(path))))
                normalized = os.path.normcase(os.path.normpath(str(path)))
                if created is not None and normalized not in self.seen_paths:
                    self.seen_paths.add(normalized)
                    self.latencies_ms.append((now - created) * 1000)
            self.calls += 1
            self._condition.notify_all()

    def reconcile_paths(self, paths, reason, correlation_id=None):
        paths = tuple(paths)
        self._record(paths)
        return {"accepted": len(paths), "rejected": 0}

    def reconcile_directories(self, paths, reason, correlation_id=None):
        paths = tuple(paths)
        self._record(paths)
        return {"accepted": len(paths), "rejected": 0}

    def wait_for_latencies(self, count, timeout):
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self.latencies_ms) < count and time.monotonic() < deadline:
                self._condition.wait(timeout=min(0.25, max(0, deadline - time.monotonic())))
            return len(self.latencies_ms) >= count


def _percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _sample(process):
    memory = process.memory_info()
    return {
        "rss_bytes": int(memory.rss),
        "private_bytes": int(getattr(memory, "private", 0)),
        "threads": int(process.num_threads()),
        "handles": int(process.num_handles()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--soak-seconds", type=int, default=1800)
    parser.add_argument("--active-files", type=int, default=40)
    arguments = parser.parse_args()

    if os.environ.get("CP_TEST_MODE") != "1":
        raise RuntimeError("CP_TEST_MODE=1 is required")
    declared = Path(os.environ["CP_TEST_ROOT"]).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if declared == temporary or temporary not in declared.parents:
        raise RuntimeError("CP_TEST_ROOT must be a unique child of the OS temporary directory")
    root = declared / f"watcher-soak-{uuid.uuid4().hex}"
    root.mkdir(parents=True)

    process = psutil.Process()
    logical_processors = psutil.cpu_count(logical=True) or 1
    baseline = _sample(process)
    created_at = {}
    coordinator = _RecordingCoordinator(created_at)
    adapter = LibraryObserverAdapter([root], coordinator)
    started = adapter.start()
    if not started["alive"]:
        raise RuntimeError(f"Native observer did not start: {started}")
    time.sleep(5)
    warm = _sample(process)
    cpu_start = process.cpu_times()
    wall_start = time.perf_counter()
    samples = []
    next_sample = wall_start
    while time.perf_counter() - wall_start < arguments.soak_seconds:
        now = time.perf_counter()
        if now >= next_sample:
            samples.append(_sample(process))
            next_sample = now + 5
        time.sleep(min(1, max(0.05, arguments.soak_seconds - (now - wall_start))))
    wall_end = time.perf_counter()
    cpu_end = process.cpu_times()
    idle_calls = coordinator.calls

    for index in range(arguments.active_files):
        path = root / f"Observed.{index:03d}.2026.mkv"
        key = os.path.normcase(os.path.normpath(str(path)))
        created_at[key] = time.perf_counter()
        path.write_bytes(b"isolated watcher fixture")
        time.sleep(0.025)
    received_all = coordinator.wait_for_latencies(arguments.active_files, timeout=10)
    active = _sample(process)
    shutdown_clean = adapter.shutdown(timeout_seconds=10)
    time.sleep(0.1)
    stopped = _sample(process)

    cpu_seconds = (cpu_end.user + cpu_end.system) - (cpu_start.user + cpu_start.system)
    elapsed = wall_end - wall_start
    one_core_percent = 100 * cpu_seconds / elapsed if elapsed else 0
    machine_percent = one_core_percent / logical_processors
    latencies = coordinator.latencies_ms[: arguments.active_files]
    result = {
        "isolation": {
            "cp_test_mode": True,
            "test_root": str(declared),
            "test_root_is_os_temp_child": True,
            "media_root": str(root),
        },
        "idle": {
            "requested_seconds": arguments.soak_seconds,
            "elapsed_seconds": round(elapsed, 3),
            "cpu_seconds": round(cpu_seconds, 6),
            "one_core_cpu_percent": round(one_core_percent, 6),
            "machine_cpu_percent": round(machine_percent, 6),
            "logical_processors": logical_processors,
            "baseline": baseline,
            "warm": warm,
            "observer_rss_delta_bytes": warm["rss_bytes"] - baseline["rss_bytes"],
            "max_rss_bytes": max(sample["rss_bytes"] for sample in samples),
            "max_private_bytes": max(sample["private_bytes"] for sample in samples),
            "max_threads": max(sample["threads"] for sample in samples),
            "max_handles": max(sample["handles"] for sample in samples),
            "coordinator_calls": idle_calls,
        },
        "active": {
            "files": arguments.active_files,
            "received_all": received_all,
            "latency_samples": len(latencies),
            "event_to_queue_p50_ms": round(statistics.median(latencies), 3) if latencies else 0,
            "event_to_queue_p95_ms": round(_percentile(latencies, 0.95), 3),
            "event_to_queue_max_ms": round(max(latencies), 3) if latencies else 0,
            "sample": active,
        },
        "shutdown": {
            "clean": shutdown_clean,
            "alive": adapter.status()["alive"],
            "sample": stopped,
        },
    }
    result["budgets"] = {
        "duration_at_least_30_minutes": elapsed >= 1800 if arguments.soak_seconds >= 1800 else None,
        "machine_cpu_below_0_5_percent": machine_percent < 0.5,
        "rss_delta_below_20_mb": warm["rss_bytes"] - baseline["rss_bytes"] < 20 * 1024 * 1024,
        "event_p95_below_250_ms": received_all and _percentile(latencies, 0.95) < 250,
        "clean_shutdown": shutdown_clean and not adapter.status()["alive"],
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
