from pathlib import Path
import unittest


class PowerUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.app = (root / "src" / "App.jsx").read_text(encoding="utf-8")
        cls.styles = (root / "src" / "styles.css").read_text(encoding="utf-8")

    def test_sidebar_exposes_windows_style_power_choices_above_version(self):
        self.assertIn('aria-label="Power options"', self.app)
        self.assertIn('After current downloads finish', self.app)
        self.assertIn('<span>RESET</span>', self.app)
        self.assertIn('<span>RESTART</span>', self.app)
        self.assertIn('<span>TURN OFF</span>', self.app)
        self.assertIn('<span>SHUT DOWN DEVICE</span>', self.app)
        self.assertIn('Close qBittorrent too', self.app)
        self.assertIn("onPowerAction('restart', false, false)", self.app)
        self.assertIn("onPowerAction('cp', afterDownload, closeQbittorrent)", self.app)
        self.assertIn("onPowerAction('device', afterDownload, false)", self.app)
        self.assertIn("resetUrl.searchParams.set('_cp_reset'", self.app)
        self.assertLess(self.app.index('className={cx(\'sidebar-power-zone\''), self.app.index('className="sidebar-footer"'))
        self.assertIn('grid-template-columns: minmax(0, 1fr) auto;', self.styles)
        self.assertIn('.sidebar-power-menu', self.styles)

    def test_armed_action_is_visible_resumable_and_cancellable(self):
        self.assertIn("['armed', 'draining', 'paused', 'failed', 'dispatch_claimed', 'dispatch_failed', 'dispatch_unknown']", self.app)
        self.assertIn('Resume scheduled action', self.app)
        self.assertIn('Cancel scheduled action', self.app)

    def test_power_drain_blocks_another_download_completion_cycle(self):
        backend = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        self.assertIn(
            "_power_action_coordinator_instance.submissions_blocked()",
            backend,
        )


if __name__ == '__main__':
    unittest.main()
