import unittest
from unittest.mock import Mock, patch

import app


class PowerExecutionTests(unittest.TestCase):
    def test_cp_shutdown_persists_completion_and_closes_player_without_qbittorrent_by_default(self):
        ingestion = Mock()
        ingestion.checkpoint_for_shutdown.return_value = True
        manager = Mock()
        power = Mock()
        monitor = Mock()
        player = Mock()
        iptv = Mock()
        timeline = []
        power.complete_dispatch.side_effect = lambda plan_id: timeline.append(("completed", plan_id))

        with patch.object(app, "_TEST_MODE", False), patch.object(
            app, "_library_ingestion_coordinator", return_value=ingestion
        ), patch.object(app, "_qbittorrent_manager", manager), patch.object(
            app, "_power_action_coordinator_instance", power
        ), patch.object(app, "_player_manager", player), patch.object(
            app, "_iptv_provider_manager", iptv
        ), patch.object(app, "_qbittorrent_import_monitor", monitor), patch.object(
            app, "_shutdown_library_background_services"
        ), patch.object(app.time, "sleep"), patch.object(
            app.os, "_exit", side_effect=SystemExit(0)
        ):
            with self.assertRaises(SystemExit):
                app._execute_power_action(
                    "cp",
                    "plan-cp",
                    lambda plan_id: timeline.append(("claimed", plan_id)),
                )

        self.assertEqual(timeline, [("claimed", "plan-cp"), ("completed", "plan-cp")])
        manager.shutdown.assert_not_called()
        player.close_active.assert_called_once_with()
        iptv.close.assert_called_once_with()
        monitor.shutdown.assert_called_once_with()

    def test_cp_shutdown_closes_only_embedded_qbittorrent_when_selected(self):
        ingestion = Mock()
        ingestion.checkpoint_for_shutdown.return_value = True
        manager = Mock()
        power = Mock()

        with patch.object(app, "_TEST_MODE", False), patch.object(
            app, "_qbt_mode", "embedded"
        ), patch.object(app, "_library_ingestion_coordinator", return_value=ingestion), patch.object(
            app, "_qbittorrent_manager", manager
        ), patch.object(app, "_power_action_coordinator_instance", power), patch.object(
            app, "_close_cp_owned_playback"
        ), patch.object(app, "_qbittorrent_import_monitor"), patch.object(
            app, "_shutdown_library_background_services"
        ), patch.object(app.time, "sleep"), patch.object(
            app.os, "_exit", side_effect=SystemExit(0)
        ):
            with self.assertRaises(SystemExit):
                app._execute_power_action(
                    "cp",
                    "plan-cp-qbt",
                    lambda _plan_id: None,
                    close_qbittorrent=True,
                )

        manager.shutdown.assert_called_once_with()

    def test_system_qbittorrent_shutdown_is_rejected_before_checkpoint(self):
        ingestion = Mock()
        with patch.object(app, "_TEST_MODE", False), patch.object(
            app, "_qbt_mode", "system"
        ), patch.object(app, "_library_ingestion_coordinator", return_value=ingestion):
            with self.assertRaisesRegex(RuntimeError, "system-managed"):
                app._execute_power_action(
                    "cp",
                    "plan-system-qbt",
                    lambda _plan_id: None,
                    close_qbittorrent=True,
                )
        ingestion.checkpoint_for_shutdown.assert_not_called()

    def test_device_shutdown_closes_player_but_never_explicitly_stops_qbittorrent(self):
        coordinator = Mock()
        coordinator.checkpoint_for_shutdown.return_value = True
        manager = Mock()
        power = Mock()
        player = Mock()
        iptv = Mock()
        timeline = []

        def claim(plan_id):
            timeline.append(("claimed", plan_id))

        with patch.object(app, "_TEST_MODE", False), patch.object(
            app, "_library_ingestion_coordinator", return_value=coordinator
        ), patch.object(app, "_qbittorrent_manager", manager), patch.object(
            app, "_power_action_coordinator_instance", power
        ), patch.object(app, "_player_manager", player), patch.object(
            app, "_iptv_provider_manager", iptv
        ), patch.object(
            app.shutil, "which", return_value=r"C:\Windows\System32\shutdown.exe"
        ), patch.object(app.subprocess, "run") as run:
            app._execute_power_action("device", "plan-1", claim)

        coordinator.checkpoint_for_shutdown.assert_called_once_with(timeout_seconds=60)
        self.assertEqual(timeline, [("claimed", "plan-1")])
        manager.shutdown.assert_not_called()
        player.close_active.assert_called_once_with()
        iptv.close.assert_called_once_with()
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["shutdown.exe", "/s", "/t", "0"])
        self.assertNotIn("/f", command)
        power.complete_dispatch.assert_called_once_with("plan-1")

    def test_restart_closes_cp_runtime_leaves_qbittorrent_running_and_exits_75(self):
        coordinator = Mock()
        coordinator.checkpoint_for_shutdown.return_value = True
        manager = Mock()
        power = Mock()

        with patch.object(app, "_TEST_MODE", False), patch.object(
            app, "_library_ingestion_coordinator", return_value=coordinator
        ), patch.object(app, "_qbittorrent_manager", manager), patch.object(
            app, "_power_action_coordinator_instance", power
        ), patch.object(app, "_close_cp_owned_playback") as close_playback, patch.object(
            app, "_qbittorrent_import_monitor"
        ), patch.object(app, "_shutdown_library_background_services"), patch.object(
            app.time, "sleep"
        ), patch.object(app.os, "_exit", side_effect=SystemExit(75)) as exit_process:
            with self.assertRaisesRegex(SystemExit, "75"):
                app._execute_power_action("restart", "plan-restart", lambda _plan_id: None)

        close_playback.assert_called_once_with()
        manager.shutdown.assert_not_called()
        power.complete_dispatch.assert_called_once_with("plan-restart")
        exit_process.assert_called_once_with(app.CP_RESTART_EXIT_CODE)

    def test_rejected_windows_command_resumes_ingestion_without_retrying_it(self):
        coordinator = Mock()
        coordinator.checkpoint_for_shutdown.return_value = True
        power = Mock()

        with patch.object(app, "_TEST_MODE", False), patch.object(
            app, "_library_ingestion_coordinator", return_value=coordinator
        ), patch.object(app, "_qbittorrent_manager", None), patch.object(
            app, "_power_action_coordinator_instance", power
        ), patch.object(app, "_close_cp_owned_playback"), patch.object(
            app.shutil, "which", return_value=r"C:\Windows\System32\shutdown.exe"
        ), patch.object(app.subprocess, "run", side_effect=OSError("access denied")):
            with self.assertRaisesRegex(OSError, "access denied"):
                app._execute_power_action("device", "plan-2", lambda _plan_id: None)

        coordinator.resume_after_shutdown_failure.assert_called_once_with()
        power.complete_dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
