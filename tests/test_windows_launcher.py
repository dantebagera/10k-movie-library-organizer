from pathlib import Path
import json
import struct
import unittest


class WindowsLauncherTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.run_bat = self.root / "run.bat"
        self.script = self.run_bat.read_text(encoding="utf-8").lower()
        self.window_helper = (self.root / "tools" / "cp_window.ps1").read_text(encoding="utf-8").lower()

    def test_launcher_bootstraps_source_zip_before_starting_flask(self):
        self.assertIn("dist\\index.html", self.script)
        self.assertIn("npm.cmd install", self.script)
        self.assertIn("npm.cmd run build", self.script)
        self.assertIn("python -m venv .venv", self.script)
        self.assertIn("pip install -r requirements.txt", self.script)

    def test_launcher_opens_browser_after_frontend_build(self):
        build_position = self.script.index("npm.cmd run build")
        browser_position = self.script.index('cp_window.ps1" -action launch')

        self.assertLess(build_position, browser_position)
        self.assertIn("--app=$appurl", self.window_helper)
        self.assertIn('http://localhost:$port/', self.window_helper)
        self.assertIn("--start-maximized", self.window_helper)
        self.assertNotIn("--user-data-dir=", self.window_helper)

    def test_launcher_closes_only_its_owned_edge_window_and_does_not_pause_on_success(self):
        self.assertIn("enumwindows", self.window_helper)
        self.assertIn("window_handle", self.window_helper)
        self.assertIn("wm_close", self.window_helper)
        self.assertNotIn("stop-process", self.window_helper)
        self.assertIn("cp-window.stop", self.window_helper)
        self.assertIn('cp_window.ps1" -action close', self.script)
        success_tail = self.script.split('if not "%app_exit%"=="0"', 1)[1]
        self.assertTrue(success_tail.rstrip().endswith("exit /b 0"))
        self.assertEqual(success_tail.count("pause"), 1)

    def test_launcher_uses_the_installed_cp_edge_app_with_a_safe_fallback(self):
        manifest = json.loads((self.root / "static" / "manifest.webmanifest").read_text(encoding="utf-8"))
        index_html = (self.root / "index.html").read_text(encoding="utf-8")

        self.assertIn('<link rel="manifest" href="/static/manifest.webmanifest" />', index_html)
        self.assertEqual(manifest["id"], "/")
        self.assertEqual(manifest["name"], "Cinema Paradiso")
        self.assertEqual(manifest["display"], "standalone")
        self.assertIn("--app-id=$edgeappid", self.window_helper)
        self.assertIn("--app=$appurl", self.window_helper)
        self.assertIn("web applications\\manifest resources\\$appid", self.window_helper)
        self.assertIn("--profile-directory=", self.window_helper)
        self.assertIn("installed_web_app", self.window_helper)
        self.assertIn("url_app_fallback", self.window_helper)

        icons = {entry["sizes"]: entry for entry in manifest["icons"]}
        for size in (192, 512):
            entry = icons[f"{size}x{size}"]
            icon_path = self.root / entry["src"].lstrip("/")
            payload = icon_path.read_bytes()
            self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", payload[16:24]), (size, size))

    def test_restart_exit_replaces_the_old_command_window(self):
        restart_position = self.script.index('if "%app_exit%"=="75"')
        failure_position = self.script.index('if not "%app_exit%"=="0"')

        self.assertLess(restart_position, failure_position)
        self.assertIn('start "cinema paradiso" "%comspec%" /d /c call "%~f0" --restart', self.script)
        restart_branch = self.script[restart_position:failure_position]
        self.assertTrue(restart_branch.rstrip().endswith("exit /b 0\n)"))

    def test_launcher_reports_and_runs_flask_after_build(self):
        build_position = self.script.index("npm.cmd run build")
        flask_position = self.script.index('".venv\\scripts\\python.exe" app.py')

        self.assertLess(build_position, flask_position)
        self.assertIn("launching flask backend", self.script)
        self.assertIn("flask stopped with exit code", self.script)


class FlaskStartupTest(unittest.TestCase):
    def setUp(self):
        app_py = Path(__file__).resolve().parents[1] / "app.py"
        self.source = app_py.read_text(encoding="utf-8").lower()

    def test_flask_reloader_is_disabled_for_batch_launcher(self):
        self.assertIn("use_reloader=false", self.source)
        self.assertNotIn("use_reloader=true", self.source)


if __name__ == "__main__":
    unittest.main()
