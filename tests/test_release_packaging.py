import json
import tempfile
import unittest
import zipfile
from pathlib import Path


class PortableReleasePackagingTests(unittest.TestCase):
    @staticmethod
    def current_app_version():
        package_path = Path(__file__).resolve().parents[1] / "package.json"
        return json.loads(package_path.read_text(encoding="utf-8"))["version"]

    def test_release_plan_excludes_qbittorrent_debug_symbols(self):
        from tools.build_portable_release import should_include_qbt_file

        self.assertFalse(should_include_qbt_file("qbittorrent.pdb"))
        self.assertTrue(should_include_qbt_file("qbittorrent.exe"))

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
            out = Path(root) / "out"
            project.mkdir()
            qbt.mkdir()
            (project / "package.json").write_text('{"version":"9.9.9"}', encoding="utf-8")
            (project / "README.md").write_text("Cinema Paradiso", encoding="utf-8")
            (project / "config.json").write_text("secret", encoding="utf-8")
            (project / "res_cache.json").write_text("cache", encoding="utf-8")
            (project / "cp-server.stdout.log").write_text("local log", encoding="utf-8")
            (project / "cp-server.stderr.log").write_text("local error log", encoding="utf-8")
            (project / "data").mkdir()
            (project / "data" / "state.json").write_text("user", encoding="utf-8")
            (project / "runtime").mkdir()
            (project / "runtime" / "old.exe").write_bytes(b"old")
            (qbt / "qbittorrent.exe").write_bytes(b"exe")

            zip_path = build_release_zip(project, qbt_source=qbt, output_dir=out)

            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())

        self.assertEqual(zip_path.name, "Cinema-Paradiso-9.9.9-Portable.zip")
        self.assertTrue(any(name.endswith("README.md") for name in names))
        self.assertFalse(any(name.endswith("config.json") for name in names))
        self.assertFalse(any(name.endswith("res_cache.json") for name in names))
        self.assertFalse(any(name.endswith(".log") for name in names))
        self.assertFalse(any("/data/" in name for name in names))
        self.assertFalse(any(name.endswith("runtime/old.exe") for name in names))

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


if __name__ == "__main__":
    unittest.main()
