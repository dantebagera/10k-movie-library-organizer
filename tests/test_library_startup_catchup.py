import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from services.library_startup_catchup import LibraryStartupCatchup


class LibraryStartupCatchupTests(unittest.TestCase):
    def setUp(self):
        declared = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(declared.is_relative_to(temporary))
        self.workspace = tempfile.TemporaryDirectory(dir=declared)
        self.root = Path(self.workspace.name)
        self.repository = Mock()
        self.repository.catalog_meta.return_value = ""
        self.coordinator = Mock()
        self.coordinator.reconcile_all_now.return_value = {"checked": 0}
        self.coordinator.reconcile_directories_now.return_value = {"checked": 1}

    def tearDown(self):
        self.workspace.cleanup()

    def _catchup(self):
        return LibraryStartupCatchup(lambda: [str(self.root)], self.coordinator, self.repository)

    def test_first_snapshot_uses_non_enriching_authoritative_full_recovery(self):
        self._catchup().run_once()
        self.coordinator.reconcile_all_now.assert_called_once_with(
            enrich_accepted=False
        )

    def test_nested_offline_addition_reconciles_only_changed_directories(self):
        first = self._catchup(); first.run_once()
        saved = self.repository.set_operational_meta.call_args.args[1]
        nested = self.root / "Genre" / "Movie"
        nested.mkdir(parents=True)
        (nested / "Movie.2026.mkv").write_bytes(b"fixture")
        self.repository.catalog_meta.return_value = saved
        second = self._catchup(); result = second.run_once()
        self.assertGreater(result["changed_directories"], 0)
        submitted = self.coordinator.reconcile_directories_now.call_args.args[0]
        self.assertIn(os.path.normcase(os.path.normpath(str(nested))), submitted)
        self.assertFalse(
            self.coordinator.reconcile_directories_now.call_args.kwargs["enrich_accepted"]
        )

    def test_unchanged_snapshot_takes_no_reconciliation_path(self):
        catchup = self._catchup(); catchup.run_once()
        saved = self.repository.set_operational_meta.call_args.args[1]
        self.repository.catalog_meta.return_value = saved
        self.coordinator.reset_mock()
        result = self._catchup().run_once()
        self.assertTrue(result["result"]["skipped"])
        self.coordinator.reconcile_all_now.assert_not_called()
        self.coordinator.reconcile_directories_now.assert_not_called()

    def test_offline_root_preserves_previous_revision_and_never_prunes(self):
        normalized = os.path.normcase(os.path.normpath(str(self.root)))
        self.repository.catalog_meta.return_value = json.dumps({normalized: 1})
        self.workspace.cleanup()
        result = self._catchup().run_once()
        self.assertEqual(result["offline_roots"], 1)
        self.coordinator.reconcile_all_now.assert_not_called()
        self.coordinator.reconcile_directories_now.assert_not_called()
