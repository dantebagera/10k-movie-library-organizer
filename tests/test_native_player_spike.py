import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPIKE_ROOT = PROJECT_ROOT / "native" / "player-spike"


class NativePlayerSpikeTest(unittest.TestCase):
    def test_phase0_spike_is_isolated_from_production_player_routes(self):
        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (SPIKE_ROOT / "src").glob("*")
            if path.suffix in {".cpp", ".h"}
        )

        self.assertNotIn("/api/player/play", sources)
        self.assertNotIn("/api/open-file", sources)
        self.assertNotIn("iptv", sources.lower())
        self.assertNotIn("streaming", sources.lower())

    def test_phase0_automation_keeps_media_paths_out_of_process_arguments(self):
        main_source = (SPIKE_ROOT / "src" / "main.cpp").read_text(encoding="utf-8")

        self.assertIn('"scenario"', main_source)
        self.assertIn('"report"', main_source)
        self.assertNotIn('"media-file"', main_source)
        self.assertNotIn('"media-path"', main_source)
        self.assertIn("mediaPath", main_source)

    def test_phase0_runtime_lock_accepts_only_audited_lgpl_candidate(self):
        lock = json.loads(
            (SPIKE_ROOT / "runtime-lock.json").read_text(encoding="utf-8")
        )

        self.assertEqual(
            lock["libmpv"]["dll_sha256"],
            "0A76BD542BBA2D85ABEFCC7CD1005269085E1B5815B4E8BAEC62FF4EA4246675",
        )
        self.assertEqual(lock["qt"]["version"], "6.10.3")
        self.assertEqual(
            lock["libmpv"]["production_disposition"],
            "accepted_phase0_candidate",
        )
        self.assertIn("-Dgpl=false", lock["libmpv"]["configuration"]["mpv"])
        self.assertIn("--disable-gpl", lock["libmpv"]["configuration"]["ffmpeg"])

    def test_phase0_lgpl_recipe_removes_gpl_and_unused_dependencies(self):
        patch = (
            SPIKE_ROOT / "runtime" / "mpv-winbuild-cmake-lgpl.patch"
        ).read_text(encoding="utf-8")
        added_lines = "\n".join(
            line[1:]
            for line in patch.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )

        self.assertIn("-Dgpl=false", added_lines)
        self.assertIn("--disable-gpl", added_lines)
        for forbidden in (
            "--enable-gpl",
            "--enable-libx264",
            "--enable-libx265",
            "--enable-libxvid",
            "--enable-avisynth",
            "--enable-libdavs2",
        ):
            self.assertNotIn(forbidden, added_lines)

    def test_phase0_package_script_guards_user_data_and_temp_scope(self):
        package_script = (SPIKE_ROOT / "tools" / "package_spike.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("cp-player-phase0", package_script)
        self.assertIn("canonical_catalog.db", package_script)
        self.assertIn("res_cache.json", package_script)
        self.assertIn("DO_NOT_DISTRIBUTE.txt", package_script)
        self.assertIn("production compliance bundle", package_script)


if __name__ == "__main__":
    unittest.main()
