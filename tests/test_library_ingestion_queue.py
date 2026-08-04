import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from services.library_ingestion import (
    LibraryIngestionCoordinator,
    LibraryIngestionDependencies,
)


def _dependencies(root):
    state = {}
    return LibraryIngestionDependencies(
        store=Mock(),
        roots=lambda: [str(root)],
        iter_video_files=lambda: (),
        metadata_file_facts=Mock(),
        stability_check=Mock(return_value=True),
        reconcile_path=Mock(return_value="matched"),
        active_metadata_provider=Mock(return_value="filename"),
        migrate_metadata_path=Mock(),
        resolve_authoritative_identity=Mock(return_value={}),
        record_has_unresolved_identity=Mock(return_value=False),
        record_needs_metadata_enrichment=Mock(return_value=False),
        accepted_identity_evidence_changed=Mock(return_value=False),
        identity_evidence_fingerprint=Mock(return_value=""),
        record_needs_identity_decision_refresh=Mock(return_value=False),
        plex_data=Mock(return_value={}),
        plex_rescan=Mock(),
        auto_sync_plex=Mock(),
        inventory_bootstrap_cutoff=Mock(return_value=0),
        clear_library_cache=Mock(),
        run_detail_backfill=Mock(return_value={}),
        run_file_facts_backfill=Mock(return_value={}),
        read_state=lambda: dict(state),
        write_state=lambda value: state.update(value),
        mark_complete=Mock(),
        identity_decision_version=5,
        video_extensions=frozenset({".mkv"}),
    )


class LibraryIngestionQueueTest(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CP_TEST_MODE") != "1":
            raise RuntimeError("Gate 2 tests require CP_TEST_MODE=1")
        declared = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if declared != temporary and temporary not in declared.parents:
            raise RuntimeError("CP_TEST_ROOT must be temporary")
        self.workspace = tempfile.TemporaryDirectory(dir=declared)
        self.root = Path(self.workspace.name)

    def tearDown(self):
        self.workspace.cleanup()

    def test_duplicate_path_hints_coalesce_before_dispatch(self):
        coordinator = LibraryIngestionCoordinator(_dependencies(self.root))
        coordinator.COALESCE_SECONDS = 0.05
        processed = threading.Event()
        calls = []

        def execute(paths, **_kwargs):
            calls.append(tuple(paths))
            processed.set()
            return {"checked": 1}

        coordinator.reconcile_paths_now = execute
        path = self.root / "Movie.2026.mkv"
        first = coordinator.reconcile_paths([path], reason="external")
        second = coordinator.reconcile_paths([path], reason="external")
        self.assertEqual(first["accepted"], 1)
        self.assertEqual(second["coalesced"], 1)
        self.assertTrue(processed.wait(2))
        self.assertEqual(calls, [(str(path),)])
        self.assertTrue(coordinator.shutdown())

    def test_capacity_rejects_only_excess_and_marks_affected_root_dirty(self):
        coordinator = LibraryIngestionCoordinator(_dependencies(self.root))
        coordinator.QUEUE_CAPACITY = 2
        coordinator.COALESCE_SECONDS = 0.2
        coordinator.reconcile_paths_now = lambda paths, **_kwargs: {"checked": len(paths)}
        paths = [self.root / f"Movie-{index}.mkv" for index in range(3)]
        result = coordinator.reconcile_paths(paths, reason="external")
        self.assertEqual(result["accepted"], 2)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(len(coordinator.status()["dirty_root_ids"]), 1)
        self.assertTrue(coordinator.shutdown())

    def test_parent_directory_hint_collapses_pending_children(self):
        coordinator = LibraryIngestionCoordinator(_dependencies(self.root))
        coordinator._ensure_dispatcher_locked = lambda: None
        parent = self.root / "Collection"
        children = [parent / f"Movie-{index}" for index in range(3)]
        for directory in [parent, *children]:
            directory.mkdir(parents=True, exist_ok=True)

        child_result = coordinator.reconcile_directories(children, reason="observer:created")
        parent_result = coordinator.reconcile_directories([parent], reason="observer:moved")

        self.assertEqual(child_result["accepted"], 3)
        self.assertEqual(parent_result["accepted"], 1)
        self.assertEqual(parent_result["coalesced"], 3)
        self.assertEqual(coordinator.status()["queue_depth"], 1)
        coordinator._accepting = False

    def test_pending_parent_absorbs_child_hint_without_new_work(self):
        coordinator = LibraryIngestionCoordinator(_dependencies(self.root))
        coordinator._ensure_dispatcher_locked = lambda: None
        parent = self.root / "Collection"
        child = parent / "Movie"
        child.mkdir(parents=True)

        first = coordinator.reconcile_directories([parent], reason="observer:created")
        second = coordinator.reconcile_directories([child], reason="observer:created")

        self.assertEqual(first["accepted"], 1)
        self.assertEqual(second["accepted"], 0)
        self.assertEqual(second["coalesced"], 1)
        self.assertEqual(coordinator.status()["queue_depth"], 1)
        coordinator._accepting = False

    def test_pending_path_retries_with_bounded_backoff_until_ready(self):
        coordinator = LibraryIngestionCoordinator(_dependencies(self.root))
        coordinator.COALESCE_SECONDS = 0
        coordinator.RETRY_DELAYS = (0.01,)
        ready = threading.Event()
        calls = []

        def execute(paths, **_kwargs):
            calls.append(tuple(paths))
            if len(calls) == 1:
                return {"checked": 1, "pending": 1}
            ready.set()
            return {"checked": 1, "pending": 0}

        coordinator.reconcile_paths_now = execute
        path = self.root / "Slow.Copy.2026.mkv"
        coordinator.reconcile_paths([path], reason="observer:modified")
        self.assertTrue(ready.wait(2))
        self.assertEqual(calls, [(str(path),), (str(path),)])
        self.assertTrue(coordinator.shutdown())

    def test_one_dispatcher_serializes_path_mutation_and_shutdown_joins_it(self):
        coordinator = LibraryIngestionCoordinator(_dependencies(self.root))
        coordinator.COALESCE_SECONDS = 0
        active = 0
        maximum = 0
        lock = threading.Lock()

        def execute(paths, **_kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return {"checked": len(paths)}

        coordinator.reconcile_paths_now = execute
        coordinator.reconcile_paths(
            [self.root / f"Movie-{index}.mkv" for index in range(4)],
            reason="external",
        )
        self.assertTrue(coordinator.shutdown(timeout_seconds=2))
        self.assertEqual(maximum, 1)
        self.assertEqual(coordinator.status()["queue_depth"], 0)

    def test_final_commit_completes_before_catalog_event_is_published(self):
        timeline = []
        path = self.root / "Final.Movie.2026.mkv"
        dependencies = replace(
            _dependencies(self.root),
            prepare_final_card_assets=lambda paths: timeline.append(("assets", tuple(paths))),
            final_card_publication=lambda paths: (
                timeline.append(("commit", tuple(paths)))
                or [{"path": str(path), "movie_key": "tmdb:2026"}]
            ),
            publish_catalog_event=lambda **kwargs: timeline.append(("event", kwargs)) or True,
        )
        coordinator = LibraryIngestionCoordinator(dependencies)
        coordinator.COALESCE_SECONDS = 0
        coordinator.reconcile_paths_now = lambda paths, **_kwargs: {
            "checked": 1,
            "pending": 0,
            "_matched_paths": list(paths),
        }

        coordinator.reconcile_paths([path], reason="observer:created")
        deadline = time.monotonic() + 2
        while len(timeline) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual([entry[0] for entry in timeline], ["assets", "commit", "event"])
        self.assertEqual(timeline[2][1]["movie_keys"], ["tmdb:2026"])
        self.assertTrue(coordinator.shutdown())

    def test_poster_failure_retries_boundedly_and_never_commits_or_notifies(self):
        prepare = Mock(side_effect=RuntimeError("poster unavailable"))
        publish = Mock()
        final = Mock()
        dependencies = replace(
            _dependencies(self.root),
            prepare_final_card_assets=prepare,
            final_card_publication=final,
            publish_catalog_event=publish,
        )
        coordinator = LibraryIngestionCoordinator(dependencies)
        coordinator.COALESCE_SECONDS = 0
        coordinator.ASSET_RETRY_DELAYS = (0.01,)
        path = self.root / "Poster.Failure.2026.mkv"
        coordinator.reconcile_paths_now = lambda paths, **_kwargs: {
            "checked": 1,
            "pending": 0,
            "_matched_paths": list(paths),
        }

        coordinator.reconcile_paths([path], reason="observer:created")
        update = dependencies.store.return_value.update_file_record
        deadline = time.monotonic() + 2
        while not update.called and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(prepare.call_count, 2)
        final.assert_not_called()
        publish.assert_not_called()
        update.assert_called_once_with(str(path), {
            "ingest_status": "failed",
            "poster_error": "RuntimeError: poster unavailable",
        })
        self.assertTrue(coordinator.shutdown())


if __name__ == "__main__":
    unittest.main()
