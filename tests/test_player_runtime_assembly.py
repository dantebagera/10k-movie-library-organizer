import json
import tempfile
import unittest
from pathlib import Path

from services.player_runtime import validate_player_manifest
from tools.assemble_player_runtime import (
    BUILD_METADATA_SCHEMA,
    assemble_player_runtime,
)


class PlayerRuntimeAssemblyTests(unittest.TestCase):
    def _metadata(self, root, staged):
        files = {
            "cp-player.exe": b"player",
            "libmpv-2.dll": b"mpv",
            "Qt6Core.dll": b"qt",
            "plugins/platforms/qwindows.dll": b"plugin",
            "qml/QtQuick/qtquick2plugin.dll": b"qml",
            "assets/player-theme.json": b"{}",
            "licenses/Qt.txt": b"license",
            "licenses/RELINKING.md": b"Relinking instructions",
            "licenses/THIRD-PARTY-NOTICES.md": b"Third-party notices",
        }
        for relative, content in files.items():
            path = staged / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        metadata = {
            "schema": BUILD_METADATA_SCHEMA,
            "bundle_version": "assembled-test-1",
            "player_version": "0.1.0",
            "ipc_protocol_version": 1,
            "mpv_version": "test",
            "mpv_commit": "abc123",
            "mpv_dll": "libmpv-2.dll",
            "qt_version": "6.10.3",
            "architecture": "x86_64",
            "build_flags": ["-Dgpl=false"],
            "compatible_cp_versions": ["9.9.9"],
            "sources": [{
                "name": "test",
                "url": "https://example.test/source",
                "revision": "abc123",
            }],
            "licenses": [{
                "component": "test",
                "spdx": "LGPL-3.0-only",
                "path": "licenses/Qt.txt",
            }],
            "pinned_sha256": {},
        }
        metadata_path = Path(root) / "metadata.json"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return metadata_path

    def test_assembly_creates_immutable_verified_bundle_and_selector(self):
        with tempfile.TemporaryDirectory() as root:
            staged = Path(root) / "staged"
            staged.mkdir()
            metadata = self._metadata(root, staged)
            (staged / "config.json").write_text("secret", encoding="utf-8")
            (staged / "cp-player.pdb").write_bytes(b"debug")
            output = Path(root) / "runtime" / "player"

            bundle = assemble_player_runtime(staged, output, metadata)

            self.assertFalse((bundle / "config.json").exists())
            self.assertFalse((bundle / "cp-player.pdb").exists())
            manifest = validate_player_manifest(
                bundle,
                app_version="9.9.9",
                verify_hashes=True,
            )
            self.assertEqual(manifest["bundle_version"], "assembled-test-1")
            selector = json.loads((output / "current.json").read_text(encoding="utf-8"))
            self.assertEqual(selector["bundle_version"], "assembled-test-1")

    def test_assembly_rejects_a_mismatched_pinned_hash(self):
        with tempfile.TemporaryDirectory() as root:
            staged = Path(root) / "staged"
            staged.mkdir()
            metadata_path = self._metadata(root, staged)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["pinned_sha256"] = {"libmpv-2.dll": "0" * 64}
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            output = Path(root) / "runtime" / "player"
            with self.assertRaisesRegex(ValueError, "Pinned runtime hash"):
                assemble_player_runtime(
                    staged,
                    output,
                    metadata_path,
                )
            self.assertFalse((output / "versions" / "assembled-test-1").exists())
            self.assertEqual(
                list((output / "versions").glob(".assembling-*")),
                [],
            )

    def test_production_metadata_license_inventory_is_complete(self):
        project = Path(__file__).resolve().parents[1]
        metadata = json.loads(
            (project / "native" / "player" / "runtime-metadata.json")
            .read_text(encoding="utf-8")
        )
        license_root = project / "native" / "player" / "runtime"
        paths = {entry["path"] for entry in metadata["licenses"]}

        for required in (
            "licenses/Qt-LGPL-3.0.txt",
            "licenses/mpv-LGPL-2.1.txt",
            "licenses/FFmpeg-LGPL-3.0.txt",
            "licenses/RELINKING.md",
            "licenses/THIRD-PARTY-NOTICES.md",
            "licenses/SOURCE-OFFER.md",
        ):
            self.assertIn(required, paths)
            self.assertTrue((license_root / required).is_file())


if __name__ == "__main__":
    unittest.main()
