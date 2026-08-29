import json
import tempfile
import unittest
from pathlib import Path

from services.player_runtime import (
    PLAYER_SELECTOR_SCHEMA,
    PlayerRuntime,
    PlayerRuntimeError,
    validate_player_manifest,
)
from tests.player_runtime_fixture import create_player_runtime_bundle


class PlayerRuntimeTests(unittest.TestCase):
    def test_missing_runtime_keeps_os_fallback_available(self):
        with tempfile.TemporaryDirectory() as root:
            status = PlayerRuntime(root).status()

        self.assertEqual(status["state"], "missing")
        self.assertFalse(status["ready"])
        self.assertTrue(status["os_fallback_available"])

    def test_complete_pinned_runtime_verifies_hashes(self):
        with tempfile.TemporaryDirectory() as root:
            runtime_root = Path(root)
            bundle = create_player_runtime_bundle(
                runtime_root / "versions",
                app_version="9.9.9",
            )
            (runtime_root / "current.json").write_text(
                json.dumps({
                    "schema": PLAYER_SELECTOR_SCHEMA,
                    "bundle_version": bundle.name,
                }),
                encoding="utf-8",
            )

            status = PlayerRuntime(runtime_root).status(verify_hashes=True)

        self.assertEqual(status["state"], "ready")
        self.assertEqual(status["player_version"], "0.1.0")
        self.assertEqual(status["mpv_version"], "0.40.0")
        self.assertEqual(status["qt_version"], "6.10.3")
        self.assertTrue(status["notices"])

    def test_modified_runtime_is_damaged_only_during_full_verify(self):
        with tempfile.TemporaryDirectory() as root:
            runtime_root = Path(root)
            bundle = create_player_runtime_bundle(runtime_root / "versions")
            (runtime_root / "current.json").write_text(
                json.dumps({
                    "schema": PLAYER_SELECTOR_SCHEMA,
                    "bundle_version": bundle.name,
                }),
                encoding="utf-8",
            )
            (bundle / "cp-player.exe").write_bytes(b"tampered")

            quick = PlayerRuntime(runtime_root).status(verify_hashes=False)
            verified = PlayerRuntime(runtime_root).status(verify_hashes=True)

        self.assertEqual(quick["state"], "ready")
        self.assertEqual(verified["state"], "damaged")
        self.assertIn("damaged", verified["detail"].lower())

    def test_runtime_does_not_depend_on_the_cp_app_version(self):
        with tempfile.TemporaryDirectory() as root:
            runtime_root = Path(root)
            bundle = create_player_runtime_bundle(runtime_root / "versions")
            (runtime_root / "current.json").write_text(
                json.dumps({
                    "schema": PLAYER_SELECTOR_SCHEMA,
                    "bundle_version": bundle.name,
                }),
                encoding="utf-8",
            )

            status = PlayerRuntime(runtime_root).status()

        self.assertEqual(status["state"], "ready")
        self.assertTrue(status["ready"])

    def test_manifest_rejects_unsafe_and_incomplete_file_inventory(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = create_player_runtime_bundle(root)
            manifest_path = bundle / "cinema-paradiso-player.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["required_files"].append("../config.json")
            manifest["sha256"]["../config.json"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaises(PlayerRuntimeError):
                validate_player_manifest(bundle)


if __name__ == "__main__":
    unittest.main()
