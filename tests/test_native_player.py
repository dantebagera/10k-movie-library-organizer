import struct
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAYER_ROOT = PROJECT_ROOT / "native" / "player"


class NativePlayerSourceTests(unittest.TestCase):
    def test_windows_helper_embeds_the_cp_application_icon(self):
        cmake = (PLAYER_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        resource = (PLAYER_ROOT / "resources" / "cp-player.rc").read_text(
            encoding="utf-8"
        )
        resource_header = (
            PLAYER_ROOT / "resources" / "resource.h"
        ).read_text(encoding="utf-8")
        main = (PLAYER_ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        icon = (PLAYER_ROOT / "resources" / "cp-player.ico").read_bytes()

        self.assertIn("resources/cp-player.rc", cmake)
        self.assertIn('"${CMAKE_CURRENT_SOURCE_DIR}/resources"', cmake)
        self.assertIn('IDI_CP_PLAYER_ICON ICON "cp-player.ico"', resource)
        self.assertIn("#define IDI_CP_PLAYER_ICON 101", resource_header)
        self.assertIn('QT_RESOURCE_ALIAS "cp-player.png"', cmake)
        self.assertIn('PREFIX "/branding"', cmake)
        self.assertIn(
            'QIcon(QStringLiteral(":/branding/cp-player.png"))',
            main,
        )

        reserved, resource_type, image_count = struct.unpack_from("<HHH", icon)
        self.assertEqual((reserved, resource_type), (0, 1))
        self.assertGreater(image_count, 0)

        sizes = set()
        for index in range(image_count):
            (
                width,
                height,
                _color_count,
                entry_reserved,
                planes,
                bits_per_pixel,
                image_size,
                image_offset,
            ) = struct.unpack_from("<BBBBHHII", icon, 6 + (index * 16))
            width = width or 256
            height = height or 256
            self.assertEqual(entry_reserved, 0)
            self.assertEqual(planes, 1)
            self.assertEqual(bits_per_pixel, 32)
            self.assertLessEqual(image_offset + image_size, len(icon))
            sizes.add((width, height))

        expected_sizes = {16, 20, 24, 32, 40, 48, 64, 128, 256}
        self.assertTrue({(size, size) for size in expected_sizes}.issubset(sizes))

    def test_production_helper_is_qt_quick_plus_libmpv(self):
        cmake = (PLAYER_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        main = (PLAYER_ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        mpv_item = (PLAYER_ROOT / "src" / "MpvItem.cpp").read_text(encoding="utf-8")

        self.assertIn("qt_add_executable(cp-player WIN32", cmake)
        self.assertIn("Qt6::Quick", cmake)
        self.assertIn("Qt6::Network", cmake)
        self.assertIn("renderContextRender(m_context", mpv_item)
        self.assertNotIn("MPV_RENDER_PARAM_ADVANCED_CONTROL", mpv_item)
        self.assertNotIn("MPV_RENDER_PARAM_FLIP_Y", mpv_item)
        self.assertIn('QByteArrayLiteral("hwdec")', mpv_item)
        self.assertNotIn("QMediaPlayer", cmake + mpv_item)
        self.assertIn("target_link_libraries(cp-player PRIVATE dwmapi)", cmake)
        for attribute in (
            "DWMWA_USE_IMMERSIVE_DARK_MODE",
            "DWMWA_CAPTION_COLOR",
            "DWMWA_TEXT_COLOR",
            "DWMWA_BORDER_COLOR",
        ):
            self.assertIn(attribute, main)

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
        self.assertIn("root.requestActivate()", qml)
        self.assertIn("mpv.forceActiveFocus()", qml)
        self.assertIn("nativeCaptionColor: PlayerTheme.archiveBlack", qml)
        self.assertIn("nativeCaptionTextColor: PlayerTheme.projectorGoldBright", qml)
        self.assertIn("nativeCaptionBorderColor: PlayerTheme.projectorGold", qml)
        self.assertIn("visible: root.visibility !== Window.FullScreen", qml)
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

    def test_subtitle_icon_owns_track_search_and_selected_download_save_actions(self):
        qml = (PLAYER_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        bridge = (PLAYER_ROOT / "src" / "PlayerBridge.cpp").read_text(encoding="utf-8")
        bridge_header = (PLAYER_ROOT / "src" / "PlayerBridge.h").read_text(
            encoding="utf-8"
        )
        mpv_item = (PLAYER_ROOT / "src" / "MpvItem.cpp").read_text(encoding="utf-8")

        self.assertIn("function showSubtitleSearch()", qml)
        self.assertIn('onActivated: root.showSubtitleSearch()', qml)
        self.assertIn('text: "Search online subtitles"', qml)
        self.assertIn('"Save selected subtitle beside movie"', qml)
        self.assertIn("playerBridge.requestSaveSelectedSubtitle()", qml)
        self.assertIn("selectedSubtitleCanSave", bridge_header)
        self.assertIn('QStringLiteral("subtitle.save")', bridge)
        self.assertIn('QStringLiteral("subtitle.saved")', bridge)
        self.assertIn('QByteArrayLiteral("external-filename")', mpv_item)
        self.assertIn("selectedSubtitleExternalPath", mpv_item)

    def test_player_control_strip_uses_scalable_gold_icons_without_button_tiles(self):
        qml = (PLAYER_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        cmake = (PLAYER_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        icons_root = PLAYER_ROOT / "resources" / "icons"
        icon_names = {
            "audio-tracks.svg",
            "enter-fullscreen.svg",
            "exit-fullscreen.svg",
            "forward-10.svg",
            "pause.svg",
            "play.svg",
            "rewind-10.svg",
            "speed.svg",
            "subtitles.svg",
            "volume-high.svg",
            "volume-muted.svg",
        }

        self.assertIn("component CpIconButton: AbstractButton", qml)
        self.assertIn('iconControl.selected ? "#16d4af37" : "transparent"', qml)
        self.assertIn("border.width: 0", qml)
        self.assertIn("ToolTip.text: iconControl.label", qml)
        self.assertIn('PREFIX "/icons"', cmake)
        self.assertNotIn("RoundButton {", qml)
        self.assertIn('label: mpv.paused ? "Play" : "Pause"', qml)
        self.assertIn("acceptedButtons: Qt.LeftButton", qml)
        self.assertIn("TapHandler {", qml)
        self.assertIn("const hitsTopControls", qml)
        self.assertIn("const hitsBottomControls", qml)
        self.assertIn(
            "root.visibility === Window.FullScreen && !root.controlsVisible",
            qml,
        )
        self.assertIn("? Qt.BlankCursor : Qt.ArrowCursor", qml)

        for old_control in (
            'text: "AUDIO"',
            'text: "SUBS"',
            '? "WINDOW" : "FULL"',
            'ToolButton { text: "+10"',
        ):
            self.assertNotIn(old_control, qml)

        self.assertEqual(
            {path.name for path in icons_root.glob("*.svg")},
            icon_names,
        )
        for icon_name in icon_names:
            self.assertIn(f"resources/icons/{icon_name}", cmake)
            self.assertIn(f"qrc:/icons/{icon_name}", qml)
            svg = (icons_root / icon_name).read_text(encoding="utf-8")
            root = ElementTree.fromstring(svg)
            self.assertEqual(root.attrib.get("viewBox"), "0 0 32 32")
            self.assertIn("#F7D57A", svg)
            self.assertIn("#D4AF37", svg)
            self.assertIn("#8C6418", svg)

    def test_now_playing_overlay_uses_the_authoritative_poster_without_cropping(self):
        qml = (PLAYER_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")

        self.assertIn("id: nowPlayingPosterFrame", qml)
        self.assertIn("height: 156", qml)
        self.assertIn("width: 104", qml)
        self.assertIn("height: nowPlayingSummary.height", qml)
        self.assertIn("source: playerBridge.posterReference", qml)
        self.assertIn("fillMode: Image.PreserveAspectFit", qml)
        self.assertNotIn("Image.PreserveAspectCrop", qml)
        poster_block = qml.split("id: nowPlayingPosterFrame", 1)[1].split(
            "Column {", 1
        )[0]
        self.assertNotIn("border.width", poster_block)
        self.assertNotIn("border.color", poster_block)
        self.assertNotIn("anchors.margins", poster_block)
        self.assertIn("posterImage.status !== Image.Error", qml)
        self.assertIn("posterImage.status !== Image.Null", qml)
        self.assertIn(
            "? nowPlayingPosterFrame.width + nowPlayingSummary.spacing",
            qml,
        )
        smoke = (PLAYER_ROOT / "tools" / "smoke_player.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('parser.add_argument("--poster-reference", type=Path)', smoke)
        self.assertIn("poster_reference = poster_path.as_uri()", smoke)

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

    def test_timeline_has_direct_pointer_seeking_and_on_demand_preview(self):
        qml = (PLAYER_ROOT / "qml" / "Main.qml").read_text(encoding="utf-8")
        mpv_item = (PLAYER_ROOT / "src" / "MpvItem.cpp").read_text(encoding="utf-8")
        smoke = (PLAYER_ROOT / "tools" / "smoke_player.py").read_text(encoding="utf-8")

        self.assertNotIn("value: pressed ? value : mpv.position", qml)
        self.assertIn("Layout.preferredHeight: 28", qml)
        self.assertIn("id: timelinePointer", qml)
        self.assertIn("property bool previewActive: false", qml)
        self.assertIn("function seekFromPointer(localX)", qml)
        self.assertIn("onPressed: mouse => {", qml)
        self.assertIn("timeline.previewActive = true", qml)
        self.assertIn("onPositionChanged: mouse =>", qml)
        self.assertIn("mpv.seekAbsolute(value)", qml)
        self.assertIn("timeline.scrubbing", qml)
        self.assertIn("property bool seeking: timeline.scrubbing", qml)
        self.assertIn("seekThumbnailIntervalSeconds = 5", mpv_item)
        self.assertIn('QByteArrayLiteral("vo"), QByteArrayLiteral("null")', mpv_item)
        self.assertIn("m_thumbnailMpv", mpv_item)
        self.assertIn("MPV_EVENT_PLAYBACK_RESTART", mpv_item)
        self.assertIn("maximumSeekThumbnailFiles = 120", mpv_item)
        self.assertNotIn("captureCurrentSeekThumbnail", mpv_item)
        self.assertNotIn("m_lastThumbnailBucket", mpv_item)
        self.assertIn("--exercise-timeline", smoke)
        self.assertIn('"timeline_exercised": bool(args.exercise_timeline)', smoke)


if __name__ == "__main__":
    unittest.main()
