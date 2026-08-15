import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.power_actions import PowerActionCoordinator, PowerActionError


class PowerActionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "power" / "action.json"
        self.jobs = {}
        self.dispatched = threading.Event()
        self.actions = []
        self.close_qbittorrent_options = []

        def execute(action, plan_id, claim, *, close_qbittorrent=False):
            claim(plan_id)
            self.actions.append(action)
            self.close_qbittorrent_options.append(close_qbittorrent)
            self.dispatched.set()

        self.coordinator = PowerActionCoordinator(
            self.path,
            lambda: self.jobs,
            execute,
            id_factory=lambda: "plan-1",
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_after_download_captures_current_jobs_and_waits_for_active_move(self):
        self.jobs["abc"] = {"hash": "abc", "title": "Movie", "state": "moving"}

        status = self.coordinator.request("device", after_download=True)

        self.assertEqual(status["plan"]["state"], "armed")
        self.assertEqual(status["plan"]["targets"][0]["hash"], "abc")
        self.assertFalse(self.coordinator.evaluate())
        self.assertFalse(self.dispatched.is_set())

    def test_imported_failed_match_is_a_recoverable_checkpoint_and_dispatches_once(self):
        self.jobs["abc"] = {
            "hash": "abc",
            "title": "Movie",
            "state": "imported",
            "library_scan_pending": True,
            "identity_handoff": {"state": "failed", "reason": "provider unavailable"},
        }
        self.coordinator.request("device", after_download=True)

        self.assertTrue(self.coordinator.evaluate())
        self.assertTrue(self.dispatched.wait(2))
        self.assertEqual(self.actions, ["device"])
        self.assertEqual(self.coordinator.snapshot()["plan"]["state"], "dispatch_claimed")
        self.assertFalse(self.coordinator.evaluate())
        self.assertEqual(self.actions, ["device"])

    def test_failure_after_dispatch_claim_is_recorded_without_automatic_retry(self):
        calls = []

        def reject_after_claim(action, plan_id, claim, *, close_qbittorrent=False):
            claim(plan_id)
            calls.append(action)
            raise RuntimeError("access denied")

        coordinator = PowerActionCoordinator(
            self.path,
            lambda: {},
            reject_after_claim,
            clock=lambda: 100,
            id_factory=lambda: "plan-2",
        )
        coordinator.request("device")
        deadline = time.monotonic() + 2
        while coordinator.snapshot()["plan"].get("state") != "dispatch_failed" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(coordinator.snapshot()["plan"].get("state"), "dispatch_failed")
        self.assertEqual(calls, ["device"])
        self.assertIn("Windows rejected", coordinator.snapshot()["plan"]["detail"])
        coordinator.cancel()
        self.assertEqual(coordinator.snapshot()["plan"]["state"], "cancelled")

    def test_move_failure_can_checkpoint_only_when_recovery_evidence_is_saved(self):
        self.jobs["abc"] = {"hash": "abc", "state": "move_failed", "last_error": ""}
        self.coordinator.request("cp", after_download=True)
        self.assertFalse(self.coordinator.evaluate())

        self.jobs["abc"]["last_error"] = "disk unavailable"
        self.assertTrue(self.coordinator.evaluate())
        self.assertTrue(self.dispatched.wait(2))

    def test_missing_target_journal_blocks_shutdown(self):
        self.jobs["abc"] = {"hash": "abc", "state": "downloading"}
        self.coordinator.request("cp", after_download=True)
        self.jobs.clear()

        self.assertFalse(self.coordinator.evaluate())
        self.assertIn("journal entry is missing", self.coordinator.snapshot()["plan"]["target_status"][0]["detail"])

    def test_restart_pauses_armed_plan_without_replaying_it(self):
        self.jobs["abc"] = {"hash": "abc", "state": "downloading"}
        self.coordinator.request("device", after_download=True)

        restarted = PowerActionCoordinator(self.path, lambda: self.jobs, lambda *_args: self.fail("must not dispatch"))

        self.assertEqual(restarted.snapshot()["plan"]["state"], "paused")
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["state"], "paused")

    def test_restart_never_repeats_a_claimed_power_command(self):
        self.coordinator.request("cp")
        self.assertTrue(self.dispatched.wait(2))

        restarted = PowerActionCoordinator(
            self.path,
            lambda: self.jobs,
            lambda *_args: self.fail("must not dispatch"),
        )

        self.assertEqual(restarted.snapshot()["plan"]["state"], "completed")

    def test_restart_keeps_an_uncertain_device_command_visible_without_replay(self):
        self.coordinator.request("device")
        self.assertTrue(self.dispatched.wait(2))

        restarted = PowerActionCoordinator(
            self.path,
            lambda: self.jobs,
            lambda *_args: self.fail("must not dispatch"),
        )

        self.assertEqual(restarted.snapshot()["plan"]["state"], "dispatch_unknown")
        restarted.cancel()
        self.assertEqual(restarted.snapshot()["plan"]["state"], "cancelled")

    def test_completed_dispatch_is_persisted_before_process_exit(self):
        self.coordinator.request("cp")
        self.assertTrue(self.dispatched.wait(2))

        completed = self.coordinator.complete_dispatch("plan-1")

        self.assertEqual(completed["state"], "completed")
        persisted = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["state"], "completed")

    def test_after_download_requires_an_active_cp_job(self):
        with self.assertRaisesRegex(PowerActionError, "no active CP downloads"):
            self.coordinator.request("device", after_download=True)

    def test_cp_turn_off_persists_optional_embedded_qbittorrent_choice(self):
        status = self.coordinator.request("cp", close_qbittorrent=True)
        self.assertTrue(self.dispatched.wait(2))
        self.assertTrue(status["plan"]["close_qbittorrent"])
        self.assertEqual(self.close_qbittorrent_options, [True])

    def test_restart_is_immediate_and_never_accepts_qbittorrent_shutdown(self):
        with self.assertRaisesRegex(PowerActionError, "cannot be scheduled"):
            self.coordinator.request("restart", after_download=True)
        with self.assertRaisesRegex(PowerActionError, "only when turning off CP"):
            self.coordinator.request("restart", close_qbittorrent=True)

        status = self.coordinator.request("restart")
        self.assertTrue(self.dispatched.wait(2))
        self.assertEqual(status["plan"]["action"], "restart")
        self.assertEqual(self.actions, ["restart"])


if __name__ == "__main__":
    unittest.main()
