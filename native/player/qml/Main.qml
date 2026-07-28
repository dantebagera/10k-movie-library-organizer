import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import CinemaParadiso.Player

ApplicationWindow {
    id: root
    width: Math.min(1280, Screen.desktopAvailableWidth * 0.92)
    height: Math.min(720, Screen.desktopAvailableHeight * 0.90)
    minimumWidth: Math.min(860, Screen.desktopAvailableWidth * 0.82)
    minimumHeight: Math.min(520, Screen.desktopAvailableHeight * 0.72)
    x: Math.max(0, (Screen.desktopAvailableWidth - width) / 2)
    y: Math.max(0, (Screen.desktopAvailableHeight - height) / 2)
    visible: true
    color: PlayerTheme.archiveBlack
    title: playerBridge.title.length > 0
           ? playerBridge.title + " — Cinema Paradiso"
           : "Cinema Paradiso Player"

    property bool controlsVisible: true
    property bool audioPanelOpen: false
    property bool subtitlePanelOpen: false
    property bool chapterPanelOpen: false
    property bool subtitleSearchOpen: false
    property bool statisticsOpen: false
    property var playbackStatistics: ({})
    property string toastText: ""
    property bool seeking: timeline.pressed

    component CpButton: Button {
        id: control
        leftPadding: 14
        rightPadding: 14
        topPadding: 9
        bottomPadding: 9
        contentItem: Text {
            text: control.text
            color: control.highlighted ? PlayerTheme.projectorGoldBright : PlayerTheme.textSoft
            font.pixelSize: 13
            font.weight: control.highlighted ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignLeft
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: PlayerTheme.radiusMedium
            color: control.down ? PlayerTheme.surfaceRaised
                                : control.hovered ? "#ff26282d" : PlayerTheme.panelBlack
            border.color: control.highlighted ? PlayerTheme.projectorGold
                                              : PlayerTheme.borderStrong
        }
    }

    function showControls() {
        controlsVisible = true
        hideControls.restart()
    }

    function closeOverlays() {
        if (audioPanelOpen || subtitlePanelOpen || chapterPanelOpen || subtitleSearchOpen
                || statisticsOpen) {
            audioPanelOpen = false
            subtitlePanelOpen = false
            chapterPanelOpen = false
            subtitleSearchOpen = false
            statisticsOpen = false
            showControls()
            return true
        }
        return false
    }

    function toggleFullscreen() {
        visibility = visibility === Window.FullScreen ? Window.Windowed : Window.FullScreen
        showControls()
    }

    function setAlwaysOnTop(enabled) {
        const current = Boolean(root.flags & Qt.WindowStaysOnTopHint)
        if (current === enabled)
            return
        if (enabled)
            root.flags = root.flags | Qt.WindowStaysOnTopHint
        else
            root.flags = root.flags & ~Qt.WindowStaysOnTopHint
    }

    function restoreWindowState() {
        const state = playerBridge.windowState
        if (!state || !state.width || !state.positioned)
            return
        root.width = state.width
        root.height = state.height
        root.x = state.x
        root.y = state.y
        root.setAlwaysOnTop(Boolean(state.always_on_top))
        if (state.maximized)
            root.visibility = Window.Maximized
    }

    function formatTime(seconds) {
        if (!isFinite(seconds) || seconds < 0)
            return "0:00"
        const total = Math.floor(seconds)
        const hours = Math.floor(total / 3600)
        const minutes = Math.floor((total % 3600) / 60)
        const secs = total % 60
        return hours > 0
                ? hours + ":" + String(minutes).padStart(2, "0") + ":" + String(secs).padStart(2, "0")
                : minutes + ":" + String(secs).padStart(2, "0")
    }

    function trackLabel(track) {
        const language = track.language && track.language !== "und" ? track.language.toUpperCase() : "Unknown"
        const detail = [track.title, track.codec ? track.codec.toUpperCase() : "",
                        track.channels].filter(Boolean).join(" — ")
        const flags = [track.default ? "Default" : "", track.forced ? "Forced" : "",
                       track.hearing_impaired ? "SDH" : ""].filter(Boolean).join(" · ")
        return language + (detail ? " — " + detail : "") + (flags ? " · " + flags : "")
    }

    onClosing: function(close) {
        playerBridge.reportWindowState(
            root.x, root.y, root.width, root.height, Screen.name,
            root.visibility === Window.Maximized,
            Boolean(root.flags & Qt.WindowStaysOnTopHint)
        )
        playerBridge.requestClose()
    }

    Connections {
        target: playerBridge
        function onPreferencesChanged() { root.restoreWindowState() }
    }

    Timer {
        id: hideControls
        interval: PlayerTheme.controlsHideMs
        running: true
        repeat: false
        onTriggered: {
            if (!mpv.paused && !root.seeking && !audioPanelOpen && !subtitlePanelOpen
                    && !chapterPanelOpen && !subtitleSearchOpen
                    && !statisticsOpen
                    && !playerBridge.resumeDecisionPending)
                controlsVisible = false
        }
    }

    Timer {
        id: toastTimer
        interval: 1800
        onTriggered: toastText = ""
    }
    Timer {
        interval: 1000
        running: statisticsOpen
        repeat: true
        triggeredOnStart: true
        onTriggered: playbackStatistics = mpv.playbackStatistics()
    }

    Shortcut { enabled: !playerBridge.resumeDecisionPending; sequence: playerBridge.shortcuts.play_pause || "Space"; onActivated: { mpv.togglePause(); root.showControls() } }
    Shortcut { enabled: !playerBridge.resumeDecisionPending; sequence: playerBridge.shortcuts.seek_backward || "Left"; onActivated: { mpv.seekRelative(-10); root.showControls() } }
    Shortcut { enabled: !playerBridge.resumeDecisionPending; sequence: playerBridge.shortcuts.seek_forward || "Right"; onActivated: { mpv.seekRelative(10); root.showControls() } }
    Shortcut { enabled: !playerBridge.resumeDecisionPending; sequence: playerBridge.shortcuts.seek_backward_long || "Shift+Left"; onActivated: { mpv.seekRelative(-60); root.showControls() } }
    Shortcut { enabled: !playerBridge.resumeDecisionPending; sequence: playerBridge.shortcuts.seek_forward_long || "Shift+Right"; onActivated: { mpv.seekRelative(60); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.volume_up || "Up"; onActivated: { mpv.setVolume(mpv.volume + 5); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.volume_down || "Down"; onActivated: { mpv.setVolume(mpv.volume - 5); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.mute || "M"; onActivated: { mpv.toggleMute(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.fullscreen || "F"; onActivated: root.toggleFullscreen() }
    Shortcut { enabled: !playerBridge.resumeDecisionPending && !subtitleSearchOpen; sequence: "Enter"; onActivated: root.toggleFullscreen() }
    Shortcut { enabled: playerBridge.resumeDecisionPending; sequence: "Return"; onActivated: playerBridge.chooseResume() }
    Shortcut {
        enabled: subtitleSearchOpen && playerBridge.subtitleResults.length > 0
        sequence: "Return"
        onActivated: playerBridge.requestSubtitleDownload(
            playerBridge.subtitleResults[0].result_id
        )
    }
    Shortcut { enabled: playerBridge.resumeDecisionPending; sequence: "R"; onActivated: playerBridge.chooseRestart() }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (!root.closeOverlays() && root.visibility === Window.FullScreen)
                root.visibility = Window.Windowed
        }
    }
    Shortcut {
        sequence: playerBridge.shortcuts.audio_tracks || "A"
        onActivated: {
            audioPanelOpen = !audioPanelOpen
            subtitlePanelOpen = false
            chapterPanelOpen = false
            subtitleSearchOpen = false
            root.showControls()
        }
    }
    Shortcut {
        sequence: playerBridge.shortcuts.subtitle_tracks || "S"
        onActivated: {
            subtitlePanelOpen = !subtitlePanelOpen
            audioPanelOpen = false
            chapterPanelOpen = false
            subtitleSearchOpen = false
            root.showControls()
        }
    }
    Shortcut {
        sequence: playerBridge.shortcuts.subtitle_search || "D"
        onActivated: {
            subtitleSearchOpen = true
            audioPanelOpen = false
            subtitlePanelOpen = false
            chapterPanelOpen = false
            playerBridge.requestSubtitleSearch()
            root.showControls()
        }
    }
    Shortcut {
        sequence: playerBridge.shortcuts.chapters || "C"
        onActivated: {
            chapterPanelOpen = !chapterPanelOpen
            audioPanelOpen = false
            subtitlePanelOpen = false
            subtitleSearchOpen = false
            root.showControls()
        }
    }
    Shortcut { sequence: playerBridge.shortcuts.speed_down || "["; onActivated: { mpv.setSpeed(mpv.speed - 0.05); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.speed_up || "]"; onActivated: { mpv.setSpeed(mpv.speed + 0.05); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.subtitle_delay_down || "Z"; onActivated: { mpv.adjustSubtitleDelay(-0.1); toastText = "Subtitles −0.1 s"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.subtitle_delay_up || "X"; onActivated: { mpv.adjustSubtitleDelay(0.1); toastText = "Subtitles +0.1 s"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.audio_delay_down || "Ctrl+Z"; onActivated: { mpv.adjustAudioDelay(-0.1); toastText = "Audio −0.1 s"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.audio_delay_up || "Ctrl+X"; onActivated: { mpv.adjustAudioDelay(0.1); toastText = "Audio +0.1 s"; toastTimer.restart(); root.showControls() } }
    Shortcut {
        sequence: playerBridge.shortcuts.statistics || "I"
        onActivated: {
            statisticsOpen = !statisticsOpen
            audioPanelOpen = false
            subtitlePanelOpen = false
            chapterPanelOpen = false
            subtitleSearchOpen = false
            playbackStatistics = mpv.playbackStatistics()
            root.showControls()
        }
    }
    Shortcut {
        sequence: playerBridge.shortcuts.screenshot || "P"
        onActivated: {
            toastText = mpv.captureScreenshot()
            toastTimer.restart()
            root.showControls()
        }
    }
    Shortcut { sequence: playerBridge.shortcuts.ab_repeat || "Ctrl+B"; onActivated: { toastText = mpv.cycleABRepeat(); toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.frame_advance || "."; onActivated: { mpv.frameAdvance(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.aspect_ratio || "V"; onActivated: { mpv.cycleAspectRatio(); toastText = "Aspect ratio changed"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.crop || "Shift+V"; onActivated: { mpv.cycleCrop(); toastText = "Video crop changed"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.rotate || "Alt+R"; onActivated: { mpv.rotateVideo(); toastText = "Video rotated"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.zoom_in || "Ctrl++"; onActivated: { mpv.adjustZoom(0.1); toastText = "Zoom in"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.zoom_out || "Ctrl+-"; onActivated: { mpv.adjustZoom(-0.1); toastText = "Zoom out"; toastTimer.restart(); root.showControls() } }
    Shortcut { sequence: playerBridge.shortcuts.pan_left || "Alt+Left"; onActivated: mpv.adjustPan(-0.05, 0) }
    Shortcut { sequence: playerBridge.shortcuts.pan_right || "Alt+Right"; onActivated: mpv.adjustPan(0.05, 0) }
    Shortcut { sequence: playerBridge.shortcuts.pan_up || "Alt+Up"; onActivated: mpv.adjustPan(0, -0.05) }
    Shortcut { sequence: playerBridge.shortcuts.pan_down || "Alt+Down"; onActivated: mpv.adjustPan(0, 0.05) }
    Shortcut {
        sequence: playerBridge.shortcuts.always_on_top || "T"
        onActivated: {
            root.setAlwaysOnTop(!(root.flags & Qt.WindowStaysOnTopHint))
            toastText = (root.flags & Qt.WindowStaysOnTopHint)
                        ? "Always on top" : "Normal window"
            toastTimer.restart()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: PlayerTheme.archiveBlack
    }

    Image {
        anchors.fill: parent
        anchors.margins: 48
        source: playerBridge.posterReference
        fillMode: Image.PreserveAspectFit
        opacity: mpv.status === "Loading" ? 0.18 : 0
        asynchronous: true
        cache: false
    }

    MpvItem {
        id: mpv
        objectName: "mpvItem"
        anchors.fill: parent
        focus: true
        onPausedChanged: root.showControls()
        onPlaybackEnded: root.showControls()
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        hoverEnabled: true
        onPositionChanged: root.showControls()
    }

    Rectangle {
        id: topBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 116
        opacity: root.controlsVisible ? 1 : 0
        visible: opacity > 0
        color: "transparent"

        gradient: Gradient {
            GradientStop { position: 0; color: "#d9000000" }
            GradientStop { position: 1; color: "#00000000" }
        }
        Behavior on opacity { NumberAnimation { duration: 160 } }

        Column {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.margins: 28
            spacing: 4

            Text {
                text: playerBridge.title || "Cinema Paradiso"
                color: PlayerTheme.textStrong
                font.pixelSize: 22
                font.weight: Font.DemiBold
                elide: Text.ElideRight
                width: Math.min(720, root.width - 180)
            }
            Text {
                text: [playerBridge.year, mpv.paused ? "Paused" : mpv.status]
                      .filter(Boolean).join("  ·  ")
                color: PlayerTheme.textMuted
                font.pixelSize: 13
            }
        }

        ToolButton {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 22
            text: "✕"
            font.pixelSize: 20
            onClicked: playerBridge.requestClose()
            contentItem: Text {
                text: parent.text
                color: PlayerTheme.textSoft
                font: parent.font
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                radius: PlayerTheme.radiusMedium
                color: parent.hovered ? "#663a3d45" : "#33000000"
            }
        }
    }

    RoundButton {
        anchors.centerIn: parent
        width: 76
        height: 76
        visible: root.controlsVisible
        text: mpv.paused ? "▶" : "Ⅱ"
        font.pixelSize: 30
        onClicked: {
            mpv.togglePause()
            root.showControls()
        }
        contentItem: Text {
            text: parent.text
            color: PlayerTheme.textStrong
            font: parent.font
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
            radius: width / 2
            color: parent.hovered ? "#e6d4af37" : "#b3121316"
            border.color: parent.hovered ? PlayerTheme.projectorGoldBright : PlayerTheme.borderStrong
        }
    }

    Rectangle {
        id: bottomBar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 170
        opacity: root.controlsVisible ? 1 : 0
        visible: opacity > 0
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0; color: "#00000000" }
            GradientStop { position: 1; color: "#ed000000" }
        }
        Behavior on opacity { NumberAnimation { duration: 160 } }

        ColumnLayout {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            anchors.bottomMargin: 20
            spacing: 8

            Slider {
                id: timeline
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, mpv.duration)
                value: pressed ? value : mpv.position
                property real hoverPosition: 0
                property string hoverThumbnail: ""
                function updateHoverPreview() {
                    const localX = Math.max(0, Math.min(width, timelineHover.point.position.x))
                    hoverPosition = to * localX / Math.max(1, width)
                    hoverThumbnail = mpv.seekThumbnail(hoverPosition)
                }
                onMoved: mpv.seekAbsolute(value)
                onPressedChanged: root.showControls()
                HoverHandler { id: timelineHover }
                Timer {
                    interval: 90
                    running: timelineHover.hovered
                    repeat: true
                    triggeredOnStart: true
                    onTriggered: timeline.updateHoverPreview()
                }
                Connections {
                    target: mpv
                    function onSeekThumbnailsChanged() {
                        if (timelineHover.hovered)
                            timeline.updateHoverPreview()
                    }
                }
                Rectangle {
                    z: 8
                    visible: timelineHover.hovered
                    width: 220
                    height: timeline.hoverThumbnail.length > 0 ? 154 : 42
                    x: Math.max(0, Math.min(timeline.width - width,
                        timelineHover.point.position.x - width / 2))
                    y: -height - 8
                    radius: PlayerTheme.radiusMedium
                    color: PlayerTheme.panelBlack
                    border.color: PlayerTheme.borderStrong
                    Image {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 6
                        height: 118
                        visible: timeline.hoverThumbnail.length > 0
                        source: timeline.hoverThumbnail
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 7
                        text: root.formatTime(timeline.hoverPosition)
                        color: PlayerTheme.textSoft
                        font.pixelSize: 12
                    }
                }
                background: Rectangle {
                    x: parent.leftPadding
                    y: parent.topPadding + parent.availableHeight / 2 - height / 2
                    width: parent.availableWidth
                    height: 4
                    radius: 2
                    color: PlayerTheme.borderStrong
                    Rectangle {
                        width: parent.width * timeline.visualPosition
                        height: parent.height
                        radius: 2
                        color: PlayerTheme.projectorGold
                    }
                    Repeater {
                        model: mpv.chapters
                        delegate: Rectangle {
                            required property var modelData
                            x: Math.max(0, Math.min(parent.width - 2,
                                parent.width * Number(modelData.time || 0)
                                / Math.max(1, mpv.duration)))
                            width: 2
                            height: 10
                            anchors.verticalCenter: parent.verticalCenter
                            color: PlayerTheme.textSoft
                            opacity: 0.8
                        }
                    }
                }
                handle: Rectangle {
                    x: timeline.leftPadding + timeline.visualPosition
                       * (timeline.availableWidth - width)
                    y: timeline.topPadding + timeline.availableHeight / 2 - height / 2
                    width: timeline.pressed || timeline.hovered ? 16 : 12
                    height: width
                    radius: width / 2
                    color: PlayerTheme.projectorGoldBright
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                ToolButton {
                    text: mpv.paused ? "▶" : "Ⅱ"
                    onClicked: mpv.togglePause()
                }
                ToolButton { text: "−10"; onClicked: mpv.seekRelative(-10) }
                ToolButton { text: "+10"; onClicked: mpv.seekRelative(10) }
                ToolButton {
                    text: mpv.muted ? "🔇" : "♪"
                    onClicked: mpv.toggleMute()
                }
                Slider {
                    Layout.preferredWidth: 112
                    from: 0
                    to: 100
                    value: mpv.volume
                    onMoved: mpv.setVolume(value)
                }
                Text {
                    text: root.formatTime(mpv.position) + " / " + root.formatTime(mpv.duration)
                    color: PlayerTheme.textSoft
                    font.pixelSize: 13
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: mpv.speed.toFixed(2) + "×"
                    color: PlayerTheme.textMuted
                    font.pixelSize: 12
                }
                ToolButton {
                    text: "AUDIO"
                    onClicked: {
                        audioPanelOpen = !audioPanelOpen
                        subtitlePanelOpen = false
                        chapterPanelOpen = false
                        subtitleSearchOpen = false
                        root.showControls()
                    }
                }
                ToolButton {
                    text: "SUBS"
                    onClicked: {
                        subtitlePanelOpen = !subtitlePanelOpen
                        audioPanelOpen = false
                        chapterPanelOpen = false
                        subtitleSearchOpen = false
                        root.showControls()
                    }
                }
                ToolButton {
                    text: root.visibility === Window.FullScreen ? "WINDOW" : "FULL"
                    onClicked: root.toggleFullscreen()
                }
            }
        }
    }

    Rectangle {
        id: trackPanel
        width: Math.min(430, root.width - 56)
        height: Math.min(390, root.height - 210)
        anchors.right: parent.right
        anchors.bottom: bottomBar.top
        anchors.rightMargin: 28
        anchors.bottomMargin: -44
        visible: audioPanelOpen || subtitlePanelOpen || chapterPanelOpen
        color: PlayerTheme.panelBlack
        radius: PlayerTheme.radiusLarge
        border.color: PlayerTheme.borderStrong

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 10

            Text {
                text: audioPanelOpen ? "Audio tracks"
                                     : subtitlePanelOpen ? "Subtitle tracks" : "Chapters"
                color: PlayerTheme.textStrong
                font.pixelSize: 18
                font.weight: Font.DemiBold
            }
            Rectangle { Layout.fillWidth: true; height: 1; color: PlayerTheme.border }
            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ScrollView {
                    anchors.fill: parent
                    visible: audioPanelOpen
                    clip: true
                    Column {
                        width: parent.width
                        spacing: 4
                        Repeater {
                            model: mpv.audioTracks
                            delegate: CpButton {
                                required property var modelData
                                width: parent.width
                                text: root.trackLabel(modelData)
                                highlighted: !!modelData.selected
                                onClicked: {
                                    mpv.selectAudioTrack(modelData.id)
                                    root.closeOverlays()
                                }
                            }
                        }
                        Text {
                            width: parent.width
                            visible: mpv.audioTracks.length === 0
                            text: "No audio tracks are available."
                            color: PlayerTheme.textMuted
                            wrapMode: Text.WordWrap
                            padding: 12
                        }
                    }
                }

                ScrollView {
                    anchors.fill: parent
                    visible: subtitlePanelOpen
                    clip: true
                    Column {
                        width: parent.width
                        spacing: 4
                        CpButton {
                            width: parent.width
                            text: "Off"
                            onClicked: {
                                mpv.disableSubtitles()
                                subtitlePanelOpen = false
                            }
                        }
                        Repeater {
                            model: mpv.subtitleTracks
                            delegate: CpButton {
                                required property var modelData
                                width: parent.width
                                text: root.trackLabel(modelData)
                                highlighted: !!modelData.selected
                                onClicked: {
                                    mpv.selectSubtitleTrack(modelData.id)
                                    root.closeOverlays()
                                }
                            }
                        }
                        Text {
                            width: parent.width
                            visible: mpv.subtitleTracks.length === 0
                            text: "No subtitle tracks are available."
                            color: PlayerTheme.textMuted
                            wrapMode: Text.WordWrap
                            padding: 12
                        }
                    }
                }

                ScrollView {
                    anchors.fill: parent
                    visible: chapterPanelOpen
                    clip: true
                    Column {
                        width: parent.width
                        spacing: 4
                        Repeater {
                            model: mpv.chapters
                            delegate: CpButton {
                                required property var modelData
                                width: parent.width
                                text: (modelData.title || "Chapter") + "  ·  "
                                      + root.formatTime(modelData.time)
                                onClicked: {
                                    mpv.seekAbsolute(modelData.time)
                                    root.closeOverlays()
                                }
                            }
                        }
                        Text {
                            width: parent.width
                            visible: mpv.chapters.length === 0
                            text: "No chapters are available."
                            color: PlayerTheme.textMuted
                            wrapMode: Text.WordWrap
                            padding: 12
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        z: 20
        width: Math.min(560, root.width - 56)
        height: 260
        anchors.centerIn: parent
        visible: playerBridge.resumeDecisionPending
        color: PlayerTheme.panelBlack
        radius: PlayerTheme.radiusExtraLarge
        border.color: PlayerTheme.projectorGold

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 28
            spacing: 14
            Text {
                text: "Continue watching?"
                color: PlayerTheme.textStrong
                font.pixelSize: 24
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: "Cinema Paradiso saved your place at "
                      + root.formatTime(playerBridge.resumePositionMs / 1000) + "."
                color: PlayerTheme.textSoft
                font.pixelSize: 15
                wrapMode: Text.WordWrap
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignRight
                spacing: 10
                CpButton {
                    text: "Start over"
                    onClicked: playerBridge.chooseRestart()
                }
                CpButton {
                    text: "Resume from " + root.formatTime(playerBridge.resumePositionMs / 1000)
                    highlighted: true
                    onClicked: playerBridge.chooseResume()
                }
            }
        }
    }

    Rectangle {
        width: Math.min(760, root.width - 56)
        height: Math.min(570, root.height - 72)
        anchors.centerIn: parent
        visible: subtitleSearchOpen
        color: PlayerTheme.panelBlack
        radius: PlayerTheme.radiusExtraLarge
        border.color: PlayerTheme.projectorGold

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 24
            spacing: 12
            Text {
                text: "Find subtitles"
                color: PlayerTheme.textStrong
                font.pixelSize: 22
                font.weight: Font.DemiBold
            }
            Text {
                Layout.fillWidth: true
                text: playerBridge.subtitleSearchStatus === "searching"
                      ? "Searching your configured providers…"
                      : playerBridge.subtitleSearchStatus === "downloading"
                        ? "Downloading and validating the selected subtitle…"
                        : playerBridge.subtitleSearchStatus === "loaded"
                          ? "Subtitle loaded. You can close this panel."
                          : playerBridge.subtitleResults.length === 0
                            ? "No matching subtitles were returned by the configured providers."
                            : playerBridge.subtitleResults.length + " ranked results"
                color: PlayerTheme.textSoft
                wrapMode: Text.WordWrap
                lineHeight: 1.2
            }
            Text {
                Layout.fillWidth: true
                visible: playerBridge.subtitleSearchError.length > 0
                text: playerBridge.subtitleSearchError
                color: PlayerTheme.dangerRed
                wrapMode: Text.WordWrap
            }
            ListView {
                id: subtitleResultList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: playerBridge.subtitleResults
                ScrollBar.vertical: ScrollBar { }
                delegate: Rectangle {
                    required property var modelData
                    width: subtitleResultList.width
                    height: 92
                    radius: PlayerTheme.radiusMedium
                    color: resultHover.hovered
                           ? PlayerTheme.surfaceRaised : PlayerTheme.archiveBlack
                    border.color: PlayerTheme.borderStrong

                    HoverHandler { id: resultHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        onTapped: playerBridge.requestSubtitleDownload(modelData.result_id)
                    }
                    Column {
                        anchors.left: parent.left
                        anchors.right: providerLabel.left
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 14
                        anchors.rightMargin: 12
                        spacing: 5
                        Text {
                            width: parent.width
                            text: modelData.release_name
                            color: PlayerTheme.textStrong
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            width: parent.width
                            text: [
                                String(modelData.language || "und").toUpperCase(),
                                modelData.frame_rate > 0 ? Number(modelData.frame_rate).toFixed(3) + " fps" : "",
                                modelData.hearing_impaired ? "SDH" : "",
                                modelData.forced ? "Forced" : ""
                            ].filter(Boolean).join("  ·  ")
                            color: PlayerTheme.textSoft
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                        Text {
                            width: parent.width
                            text: modelData.match_reason
                            color: PlayerTheme.projectorGoldBright
                            font.pixelSize: 12
                            elide: Text.ElideRight
                        }
                    }
                    Text {
                        id: providerLabel
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.rightMargin: 14
                        width: 118
                        text: modelData.provider
                        color: PlayerTheme.textMuted
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignRight
                    }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                Text {
                    Layout.fillWidth: true
                    text: "Credentials stay in the Cinema Paradiso backend."
                    color: PlayerTheme.textMuted
                    font.pixelSize: 11
                }
                CpButton {
                    text: "Search again"
                    onClicked: playerBridge.requestSubtitleSearch()
                }
                CpButton { text: "Close"; onClicked: root.closeOverlays() }
            }
        }
    }

    Rectangle {
        width: 350
        height: 250
        anchors.right: parent.right
        anchors.top: topBar.bottom
        anchors.rightMargin: 28
        visible: statisticsOpen
        color: PlayerTheme.panelBlack
        radius: PlayerTheme.radiusLarge
        border.color: PlayerTheme.projectorGold

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 8
            Text {
                text: "Playback statistics"
                color: PlayerTheme.textStrong
                font.pixelSize: 18
                font.weight: Font.DemiBold
            }
            Repeater {
                model: [
                    ["Video", playbackStatistics.video_codec || "Unknown"],
                    ["Resolution", playbackStatistics.resolution || "Unknown"],
                    ["Frame rate", playbackStatistics.frame_rate || "Unknown"],
                    ["Hardware decoder", playbackStatistics.hardware_decoder || "Software"],
                    ["Audio", playbackStatistics.audio_codec || "Unknown"],
                    ["Display", playbackStatistics.display_fps
                                ? playbackStatistics.display_fps + " Hz" : "Unknown"]
                ]
                delegate: RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    Text { text: modelData[0]; color: PlayerTheme.textMuted; Layout.preferredWidth: 125 }
                    Text { text: modelData[1]; color: PlayerTheme.textSoft; Layout.fillWidth: true; elide: Text.ElideRight }
                }
            }
            Item { Layout.fillHeight: true }
            Text {
                text: "I closes statistics"
                color: PlayerTheme.textFaint
                font.pixelSize: 11
            }
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: bottomBar.top
        anchors.bottomMargin: 8
        visible: toastText.length > 0
        color: PlayerTheme.surfaceRaised
        radius: PlayerTheme.radiusMedium
        border.color: PlayerTheme.borderStrong
        width: toast.implicitWidth + 28
        height: 38
        Text {
            id: toast
            anchors.centerIn: parent
            text: toastText
            color: PlayerTheme.textSoft
            font.pixelSize: 13
        }
    }
}
