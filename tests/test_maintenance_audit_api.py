import unittest
from unittest.mock import patch

import app


class MaintenanceAuditApiTest(unittest.TestCase):
    def test_delete_preview_and_execution_require_audio_language_loss_acknowledgement(self):
        path = r"E:\Movies\Alien.1979.720p.multi.mkv"
        maintenance = {
            "storage": {"groups": [{
                "files": [{
                    "path": path,
                    "filename": "Alien.1979.720p.multi.mkv",
                    "recommendation": "review",
                    "comparison_peer": "Alien.1979.1080p.mkv",
                    "audio_language_losses": ["French"],
                }],
            }]},
        }
        plan = {"actions": [], "file_count": 1}
        deleted = {"deleted_paths": [path], "folder_count": 0, "catalog_generation": 9}

        with patch.object(app, "_maintenance_audit_from_catalog", return_value=maintenance), \
                patch.object(app, "_plan_library_file_deletions", return_value=dict(plan)), \
                patch.object(app, "_delete_library_files", return_value=deleted) as delete_many:
            client = app.app.test_client()
            preview = client.post("/api/delete", json={"paths": [path], "preview": True})
            blocked = client.post("/api/delete", json={"paths": [path]})
            confirmed = client.post("/api/delete", json={
                "paths": [path],
                "confirmed_audio_language_losses": [{"path": path, "languages": ["French"]}],
            })

        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.get_json()["audio_language_losses"][0]["languages"], ["French"])
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.get_json()["confirmation_required"], "audio_language_loss")
        self.assertEqual(confirmed.status_code, 200)
        delete_many.assert_called_once()

    def test_workspace_contract_exposes_only_unmatched_and_authoritative_review_rows(self):
        maintenance = {
            "source": "catalog",
            "summary": {
                "unmatched_files": 1,
                "identity_issues": 33,
                "verification_gaps": 32,
                "automated_identity_checks": 177,
                "hard_conflicts": 0,
                "metadata_drift": 184,
            },
            "storage": {"groups": []},
            "upgrades": {"items": []},
            "identity": {
                "items": [{"path": "E:/Movies/Unmatched.mkv"}],
                "verification": [{"path": f"E:/Movies/Diagnostic-{index}.mkv"} for index in range(32)],
            },
        }
        identity_review = {
            "id": "audit-1",
            "status": "completed",
            "shadow_mode": True,
            "mutates_metadata": False,
            "outcome_counts": {"actionable": 1},
            "proposals": [{"id": "proposal-1", "classification": "actionable"}],
        }

        with patch.object(app, "_maintenance_audit_from_catalog", return_value=maintenance), \
                patch.object(app, "_get_identity_audit_coordinator") as coordinator:
            coordinator.return_value.status.return_value = identity_review
            response = app.app.test_client().get("/api/maintenance/audit")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["summary"]["actionable_identities"], 1)
        self.assertEqual(payload["summary"]["identity_issues"], 2)
        self.assertNotIn("verification_gaps", payload["summary"])
        self.assertNotIn("automated_identity_checks", payload["summary"])
        self.assertEqual(payload["identity"], {"items": maintenance["identity"]["items"]})
        self.assertEqual(payload["identity_review"]["proposals"], identity_review["proposals"])
        self.assertTrue(payload["identity_review"]["shadow_mode"])
        self.assertFalse(payload["identity_review"]["mutates_metadata"])

    def test_section_contract_returns_only_requested_paginated_projection(self):
        maintenance = {
            "source": "catalog",
            "generation": 12,
            "generated_at": 123.0,
            "summary": {"duplicate_groups": 2, "unmatched_files": 0},
            "storage": {
                "groups": [
                    {"title": "Alpha (2001)", "files": [{"filename": "Alpha.mkv", "path": "E:/Alpha.mkv"}]},
                    {"title": "Beta (2002)", "files": [{"filename": "Beta.mkv", "path": "E:/Beta.mkv"}]},
                ]
            },
            "upgrades": {"items": []},
            "identity": {"items": [], "verification": []},
        }
        with patch.object(app, "_maintenance_audit_from_catalog", return_value=maintenance), \
                patch.object(app, "_get_identity_audit_coordinator") as coordinator:
            coordinator.return_value.status.return_value = {"status": "idle", "proposals": []}
            response = app.app.test_client().get(
                "/api/maintenance/audit?section=storage&q=beta&page=1&page_size=1"
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["generation"], 12)
        self.assertEqual([group["title"] for group in payload["storage"]["groups"]], ["Beta (2002)"])
        self.assertEqual(payload["storage"]["pagination"]["total"], 1)
        self.assertNotIn("upgrades", payload)
        self.assertNotIn("identity", payload)
        self.assertNotIn("identity_review", payload)

    def test_invalid_section_is_rejected(self):
        with patch.object(app, "_maintenance_audit_from_catalog", return_value={"summary": {}}), \
                patch.object(app, "_get_identity_audit_coordinator") as coordinator:
            coordinator.return_value.status.return_value = {"status": "idle", "proposals": []}
            response = app.app.test_client().get("/api/maintenance/audit?section=legacy")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
