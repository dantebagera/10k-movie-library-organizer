import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAYER_ROOT = PROJECT_ROOT / "native" / "player"


class NativePlayerSourceTests(unittest.TestCase):
    def test_production_helper_is_qt_quick_plus_libmpv(self):
        cmake = (PLAYER_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        mpv_item = (PLAYER_ROOT / "src" / "MpvItem.cpp").read_text(encoding="utf-8")

        self.assertIn("qt_add_executable(cp-player WIN32", cmake)
        self.assertIn("Qt6::Quick", cmake)
        self.assertIn("Qt6::Network", cmake)
        self.assertIn("renderContextRender(m_context", mpv_item)
        self.assertNotIn("MPV_RENDER_PARAM_ADVANCED_CONTROL", mpv_item)
        self.assertIn('QByteArrayLiteral("hwdec")', mpv_item)
        self.assertNotIn("QMediaPlayer", cmake + mpv_item)

    def test_helper_accepts_media_only_from_authenticated_ipc(self):
        main = (PLAYER_ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        bridge = (PLAYER_ROOT / "src" / "PlayerBridge.cpp").read_text(encoding="utf-8")

        self.assertNotIn("argv[1]", main)
        self.assertIn('requiredEnvironment("CP_PLAYER_PIPE")', bridge)
        self.assertIn('qgetenv("CP_PLAYER_SESSION_TOKEN")', bridge)
        self.assertIn('qunsetenv("CP_PLAYER_SESSION_TOKEN")', bridge)
        self.assertIn('QStringLiteral("hello")', bridge)
        self.assertIn('QStringLiteral("load")', bridge)
        self.assertIn("openTrustedLocalPath", bridge)
        self.assertIn("MaximumMessageBytes = 256 * 1024", (PLAYER_ROOT / "src" / "PlayerBridge.h").read_text(encoding="utf-8"))

    def test_qml_uses_the_generated_theme_and_owns_the_keyboard_contract(self):
        qml = (PLAYER_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        generated_theme = (PLAYER_ROOT / "qml" / "PlayerTheme.qml").read_text(encoding="utf-8")

        self.assertIn("PlayerTheme.controlsHideMs", qml)
        self.assertIn("fillMode: Image.PreserveAspectFit", qml)
        for shortcut in (
            'shortcuts.play_pause || "Space"',
            'shortcuts.seek_backward || "Left"',
            'shortcuts.seek_forward_long || "Shift+Right"',
            'shortcuts.mute || "M"',
            'shortcuts.fullscreen || "F"',
            'shortcuts.audio_tracks || "A"',
            'shortcuts.subtitle_tracks || "S"',
            'shortcuts.subtitle_search || "D"',
            'shortcuts.audio_delay_down || "Ctrl+Z"',
            'shortcuts.audio_delay_up || "Ctrl+X"',
            'shortcuts.chapters || "C"',
            'shortcuts.statistics || "I"',
            'shortcuts.screenshot || "P"',
            'shortcuts.crop || "Shift+V"',
            'shortcuts.always_on_top || "T"',
        ):
            self.assertIn(shortcut, qml)
        self.assertIn("Generated from design/player-theme.json", generated_theme)

    def test_resume_prompt_keeps_the_choice_inside_the_native_cp_interface(self):
        qml = (PLAYER_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        bridge = (PLAYER_ROOT / "src" / "PlayerBridge.cpp").read_text(encoding="utf-8")

        self.assertIn('text: "Continue watching?"', qml)
        self.assertIn("playerBridge.chooseResume()", qml)
        self.assertIn("playerBridge.chooseRestart()", qml)
        self.assertIn('QStringLiteral("resume.choice")', bridge)
        self.assertIn("m_player->setPaused(true)", bridge)
        self.assertIn('QStringLiteral("playback.settings")', bridge)
        self.assertIn("m_player->setSubtitleDelay", bridge)

    def test_subtitle_provider_credentials_do_not_enter_the_helper(self):
        native_source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in PLAYER_ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() in {".cpp", ".h", ".qml"}
        ).lower()
        for forbidden in ("opensubtitles", "subdl", "api_key", "password"):
            self.assertNotIn(forbidden, native_source)

    def test_premium_controls_stay_in_the_libmpv_owner(self):
        qml = (PLAYER_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        mpv_item = (PLAYER_ROOT / "src" / "MpvItem.cpp").read_text(encoding="utf-8")
        bridge = (PLAYER_ROOT / "src" / "PlayerBridge.cpp").read_text(encoding="utf-8")
        smoke = (PLAYER_ROOT / "tools" / "smoke_player.py").read_text(encoding="utf-8")

        for command in (
            "screenshot-to-file",
            "ab-loop-a",
            "frame-step",
            "video-aspect-override",
            "video-crop",
            "video-pan-x",
            "video-rotate",
            "tone-mapping",
            "audio-channels",
        ):
            self.assertIn(command, mpv_item)
        self.assertIn("seekThumbnail(hoverPosition)", qml)
        self.assertIn("model: mpv.chapters", qml)
        self.assertIn("reportWindowState", qml)
        self.assertIn('QStringLiteral("window.state")', bridge)
        self.assertIn("--require-min-position-ms", smoke)
        self.assertIn('"max_position_ms": max_position_ms', smoke)


if __name__ == "__main__":
    unittest.main()
