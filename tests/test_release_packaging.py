import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.player_runtime_fixture import create_player_runtime_bundle


class PortableReleasePackagingTests(unittest.TestCase):
    @staticmethod
    def current_app_version():
        package_path = Path(__file__).resolve().parents[1] / "package.json"
        return json.loads(package_path.read_text(encoding="utf-8"))["version"]

    def test_release_plan_excludes_qbittorrent_debug_symbols(self):
        from tools.build_portable_release import should_include_qbt_file

        self.assertFalse(should_include_qbt_file("qbittorrent.pdb"))
        self.assertTrue(should_include_qbt_file("qbittorrent.exe"))

    def test_release_carries_pinned_watcher_and_apache_notice(self):
        from tools.build_portable_release import PORTABLE_ROOT_FILES

        project = Path(__file__).resolve().parents[1]
        requirements = (project / "requirements.txt").read_text(encoding="utf-8")
        notices = (project / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")

        self.assertIn("watchdog==6.0.0", requirements)
        self.assertIn("THIRD-PARTY-NOTICES.md", PORTABLE_ROOT_FILES)
        self.assertIn("Watchdog 6.0.0", notices)
        self.assertIn("Apache License 2.0", notices)

    def test_release_runtime_manifest_names_bundled_qbt_version(self):
        from tools.build_portable_release import build_qbt_manifest

        manifest = build_qbt_manifest("5.2.2")

        self.assertEqual(manifest["name"], "qBittorrent")
        self.assertEqual(manifest["version"], "5.2.2")
        self.assertEqual(manifest["source"], "official qBittorrent Windows x64 release")
        self.assertEqual(manifest["bundled_for"], f"Cinema Paradiso {self.current_app_version()}")

    def test_copy_qbt_runtime_excludes_profile_user_data_and_requires_exe(self):
        from tools.build_portable_release import copy_qbt_runtime

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "qbt-source"
            destination = Path(root) / "release" / "runtime" / "qbittorrent"
            source.mkdir()
            (source / "qbittorrent.exe").write_bytes(b"exe")
            (source / "qbittorrent.pdb").write_bytes(b"debug")
            (source / "profile").mkdir()
            (source / "profile" / "qBittorrent.ini").write_text("user", encoding="utf-8")
            (source / "BT_backup").mkdir()
            (source / "BT_backup" / "queue").write_text("user", encoding="utf-8")

            manifest = copy_qbt_runtime(source, destination, version="5.2.2")

            self.assertTrue((destination / "qbittorrent.exe").exists())
            self.assertFalse((destination / "qbittorrent.pdb").exists())
            self.assertFalse((destination / "profile").exists())
            self.assertFalse((destination / "BT_backup").exists())
            self.assertEqual(manifest["version"], "5.2.2")

    def test_release_zip_excludes_runtime_user_data(self):
        from tools.build_portable_release import build_release_zip

        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            qbt = Path(root) / "qbt"
            player = create_player_runtime_bundle(
                Path(root) / "player",
                app_version="9.9.9",
            )
            out = Path(root) / "out"
            project.mkdir()
            qbt.mkdir()
            (project / "package.json").write_text('{"version":"9.9.9"}', encoding="utf-8")
            (project / "README.md").write_text("Cinema Paradiso", encoding="utf-8")
            (project / "config.json").write_text(
                '{"opensubtitles_api_key":"secret","media":"C:\\\\Users\\\\dante\\\\Movies\\\\private.mkv"}',
                encoding="utf-8",
            )
            (project / "res_cache.json").write_text("cache", encoding="utf-8")
            (project / "cp-server.stdout.log").write_text("local log", encoding="utf-8")
            (project / "cp-server.stderr.log").write_text("local error log", encoding="utf-8")
            (project / "tools").mkdir()
            (project / "tools" / "build_portable_release.py").write_text("# tool", encoding="utf-8")
            (project / "tools" / "_debug_trace.log").write_text("local trace", encoding="utf-8")
            (project / "data").mkdir()
            (project / "data" / "state.json").write_text("user", encoding="utf-8")
            (project / "data" / "playback-history.db").write_bytes(b"history")
            (project / "cache").mkdir()
            (project / "cache" / "downloaded-subtitles.srt").write_text("subtitle", encoding="utf-8")
            (project / "screenshots").mkdir()
            (project / "screenshots" / "private.png").write_bytes(b"private-image")
            (project / ".agents").mkdir()
            (project / ".agents" / "private.txt").write_text("private-agent-data", encoding="utf-8")
            (project / "runtime").mkdir()
            (project / "runtime" / "old.exe").write_bytes(b"old")
            (qbt / "qbittorrent.exe").write_bytes(b"exe")

            zip_path = build_release_zip(
                project,
                qbt_source=qbt,
                player_source=player,
                output_dir=out,
            )

            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())
                archive_payload = b"\n".join(archive.read(name) for name in names)

        self.assertEqual(zip_path.name, "Cinema-Paradiso-9.9.9-Portable.zip")
        self.assertTrue(any(name.endswith("README.md") for name in names))
        self.assertFalse(any(name.endswith("config.json") for name in names))
        self.assertFalse(any(name.endswith("res_cache.json") for name in names))
        self.assertFalse(any(name.endswith(".log") for name in names))
        self.assertTrue(any(name.endswith("tools/build_portable_release.py") for name in names))
        self.assertFalse(any("/data/" in name for name in names))
        self.assertFalse(any(name.endswith("runtime/old.exe") for name in names))
        self.assertNotIn(b"opensubtitles_api_key", archive_payload)
        self.assertNotIn(b"playback-history", archive_payload)
        self.assertNotIn(b"downloaded-subtitles", archive_payload)
        self.assertNotIn(b"C:\\Users\\dante", archive_payload)
        self.assertNotIn(b"private-image", archive_payload)
        self.assertNotIn(b"private-agent-data", archive_payload)
        self.assertTrue(any(name.endswith("runtime/player/current.json") for name in names))
        self.assertTrue(any(name.endswith("runtime/player/versions/player-test-1/cp-player.exe") for name in names))

    def test_copy_ffmpeg_runtime_builds_expected_layout_and_manifest(self):
        from tools.build_portable_release import copy_ffmpeg_runtime

        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "ffmpeg-source" / "bin"
            destination = Path(root) / "release" / "runtime" / "ffmpeg"
            source.mkdir(parents=True)
            (source / "ffmpeg.exe").write_bytes(b"ffmpeg")
            (source / "ffprobe.exe").write_bytes(b"ffprobe")

            manifest = copy_ffmpeg_runtime(source.parent, destination, version="8.1.1")

            self.assertTrue((destination / "bin" / "ffmpeg.exe").is_file())
            self.assertTrue((destination / "bin" / "ffprobe.exe").is_file())
            self.assertEqual(manifest["license"], "GPLv3")
        self.assertEqual(manifest["bundled_for"], f"Cinema Paradiso {self.current_app_version()}")

    def test_copy_player_runtime_requires_hashes_licenses_and_only_copies_inventory(self):
        from tools.build_portable_release import copy_player_runtime

        with tempfile.TemporaryDirectory() as root:
            source = create_player_runtime_bundle(
                Path(root) / "source",
                app_version="9.9.9",
            )
            (source / "config.json").write_text("secret", encoding="utf-8")
            destination = Path(root) / "release" / "runtime" / "player"

            manifest = copy_player_runtime(
                source,
                destination,
            )

            version_root = destination / "versions" / manifest["bundle_version"]
            self.assertTrue((version_root / "cp-player.exe").is_file())
            self.assertTrue((version_root / "licenses" / "Qt-LGPL-3.0.txt").is_file())
            self.assertFalse((version_root / "config.json").exists())
            selector = json.loads((destination / "current.json").read_text(encoding="utf-8"))
            self.assertEqual(selector["bundle_version"], manifest["bundle_version"])

    def test_release_fails_without_pinned_player_runtime(self):
        from tools.build_portable_release import build_release_zip

        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "project"
            qbt = Path(root) / "qbt"
            project.mkdir()
            qbt.mkdir()
            (project / "package.json").write_text('{"version":"9.9.9"}', encoding="utf-8")
            (qbt / "qbittorrent.exe").write_bytes(b"exe")

            with self.assertRaises(FileNotFoundError):
                build_release_zip(project, qbt_source=qbt, output_dir=Path(root) / "out")


if __name__ == "__main__":
    unittest.main()
