import os
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from services.library_observer import LibraryObserverAdapter, classify_library_root


class RecordingCoordinator:
    def __init__(self):
        self.dependencies = SimpleNamespace(video_extensions=frozenset({".mkv", ".mp4"}))
        self.calls = []
        self.called = threading.Event()

    def reconcile_paths(self, paths, reason, correlation_id=None):
        self.calls.append(("paths", tuple(paths), reason))
        self.called.set()
        return {"accepted": len(tuple(paths)), "rejected": 0}

    def reconcile_directories(self, paths, reason, correlation_id=None):
        self.calls.append(("directories", tuple(paths), reason))
        self.called.set()
        return {"accepted": len(tuple(paths)), "rejected": 0}


class FakeObserver:
    def __init__(self):
        self.schedules = []
        self.started = False

    def schedule(self, handler, root, recursive):
        self.schedules.append((handler, root, recursive))

    def start(self):
        self.started = True

    def is_alive(self):
        return self.started

    def stop(self):
        self.started = False

    def join(self, timeout=None):
        return None


class LibraryObserverTests(unittest.TestCase):
    def setUp(self):
        configured = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temp_base = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(configured.is_relative_to(temp_base))
        self.root = configured / f"observer-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True)
        self.assertTrue(self.root.is_relative_to(configured))
        self.coordinator = RecordingCoordinator()

    def test_network_roots_are_degraded_without_polling(self):
        state = classify_library_root(r"\\server\movies", is_directory=lambda _path: True)
        self.assertEqual(state["kind"], "network")
        self.assertFalse(state["supported"])
        self.assertTrue(state["degraded"])

    def test_native_observer_is_recursive_and_stops_cleanly(self):
        fake = FakeObserver()
        adapter = LibraryObserverAdapter([self.root], self.coordinator, observer_factory=lambda: fake)
        status = adapter.start()
        self.assertEqual(len(fake.schedules), 1)
        self.assertTrue(fake.schedules[0][2])
        self.assertTrue(status["alive"])
        self.assertTrue(adapter.shutdown())
        self.assertFalse(fake.started)

    def test_video_move_emits_exact_source_and_destination_hints(self):
        adapter = LibraryObserverAdapter([self.root], self.coordinator, observer_factory=FakeObserver)
        adapter.start()
        source = self.root / "Old.mkv"
        destination = self.root / "New.mkv"
        source.write_bytes(b"old")
        destination.write_bytes(b"new")
        adapter.handle_event(str(self.root), str(source), destination=str(destination), event_type="moved")
        self.assertEqual([call[0] for call in self.coordinator.calls], ["paths", "paths"])
        self.assertEqual(self.coordinator.calls[0][1], (str(source),))
        self.assertEqual(self.coordinator.calls[1][1], (str(destination),))

    def test_sidecar_burst_maps_to_bounded_containing_directory(self):
        adapter = LibraryObserverAdapter([self.root], self.coordinator, observer_factory=FakeObserver)
        adapter.start()
        sidecar = self.root / "Movie.en.srt"
        sidecar.write_text("subtitle", encoding="utf-8")
        adapter.handle_event(str(self.root), str(sidecar), event_type="created")
        self.assertEqual(self.coordinator.calls, [("directories", (str(self.root),), "observer:created")])

    def test_directory_modified_storm_is_ignored_before_queue_admission(self):
        adapter = LibraryObserverAdapter([self.root], self.coordinator, observer_factory=FakeObserver)
        adapter.start()
        for index in range(5000):
            adapter.handle_event(
                str(self.root),
                str(self.root / f"Existing-{index}"),
                is_directory=True,
                event_type="modified",
            )
        self.assertEqual(self.coordinator.calls, [])

    def test_new_directory_emits_one_bounded_directory_hint(self):
        adapter = LibraryObserverAdapter([self.root], self.coordinator, observer_factory=FakeObserver)
        adapter.start()
        directory = self.root / "New Movie (2026)"
        directory.mkdir()
        adapter.handle_event(
            str(self.root),
            str(directory),
            is_directory=True,
            event_type="created",
        )
        self.assertEqual(
            self.coordinator.calls,
            [("directories", (str(directory),), "observer:created")],
        )

    def test_offline_root_drops_delete_hint_instead_of_pruning(self):
        adapter = LibraryObserverAdapter([self.root], self.coordinator, observer_factory=FakeObserver)
        adapter.start()
        missing_root = str(self.root)
        self.root.rmdir()
        adapter.handle_event(missing_root, os.path.join(missing_root, "Movie.mkv"), event_type="deleted")
        self.assertEqual(self.coordinator.calls, [])
        self.assertEqual(adapter.status()["roots"][0]["reason"], "offline")

    def test_overflow_schedules_only_the_affected_root(self):
        adapter = LibraryObserverAdapter([self.root], self.coordinator, observer_factory=FakeObserver)
        adapter.start()
        result = adapter.mark_overflow(str(self.root))
        self.assertEqual(result["accepted"], 1)
        self.assertEqual(self.coordinator.calls, [("directories", (str(self.root),), "observer:overflow")])

    def test_real_watchdog_observer_receives_temp_file_and_stops(self):
        adapter = LibraryObserverAdapter([self.root], self.coordinator)
        adapter.start()
        movie = self.root / "Observed.mkv"
        movie.write_bytes(b"fixture")
        self.assertTrue(self.coordinator.called.wait(5), "native observer did not emit a path hint")
        self.assertTrue(adapter.shutdown())
        time.sleep(0.05)
        self.assertFalse(adapter.status()["alive"])


if __name__ == "__main__":
    unittest.main()
