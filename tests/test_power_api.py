import unittest
from unittest.mock import Mock, patch

import app


class PowerApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        self.coordinator = Mock()
        self.coordinator.snapshot.return_value = {"active_downloads": 1, "plan": {}}
        self.coordinator.request.return_value = {"active_downloads": 1, "plan": {"state": "armed"}}
        self.coordinator.cancel.return_value = {"active_downloads": 1, "plan": {"state": "cancelled"}}
        self.coordinator.resume.return_value = {"active_downloads": 1, "plan": {"state": "armed"}}
        self.patch = patch.object(app, "_power_action_coordinator", return_value=self.coordinator)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_status_and_after_download_action(self):
        status = self.client.get("/api/power/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.get_json()["torrent_client"]["can_close"])
        response = self.client.post("/api/power/actions", json={"action": "device", "after_download": True})
        self.assertEqual(response.status_code, 200)
        self.coordinator.request.assert_called_once_with(
            "device",
            after_download=True,
            close_qbittorrent=False,
        )

    def test_turn_off_forwards_the_embedded_qbittorrent_choice(self):
        response = self.client.post("/api/power/actions", json={
            "action": "cp",
            "close_qbittorrent": True,
        })
        self.assertEqual(response.status_code, 200)
        self.coordinator.request.assert_called_once_with(
            "cp",
            after_download=False,
            close_qbittorrent=True,
        )

    def test_system_qbittorrent_can_never_be_closed_by_a_power_action(self):
        with patch.object(app, "_qbt_mode", "system"):
            response = self.client.post("/api/power/actions", json={
                "action": "cp",
                "close_qbittorrent": True,
            })
        self.assertEqual(response.status_code, 409)
        self.coordinator.request.assert_not_called()

    def test_cancel_and_resume_routes(self):
        self.assertEqual(self.client.post("/api/power/cancel").get_json()["plan"]["state"], "cancelled")
        self.assertEqual(self.client.post("/api/power/resume").get_json()["plan"]["state"], "armed")


if __name__ == "__main__":
    unittest.main()
