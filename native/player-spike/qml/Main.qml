import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts
import CinemaParadiso.PlayerSpike

ApplicationWindow {
    id: window
    width: 1280
    height: 720
    minimumWidth: 800
    minimumHeight: 450
    visible: true
    color: "#050505"
    title: "Cinema Paradiso · Native Player Spike"

    property bool controlsVisible: true

    component CpButton: Button {
        id: buttonControl
        implicitHeight: 34
        leftPadding: 14
        rightPadding: 14

        contentItem: Text {
            text: buttonControl.text
            color: buttonControl.enabled ? "#17130d" : "#756f65"
            font.pixelSize: 13
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: 4
            color: buttonControl.down ? "#b98a37"
                                      : buttonControl.hovered ? "#f0ca7e" : "#d7ad58"
            border.color: "#f3d69c"
            border.width: 1
        }
    }

    FileDialog {
        id: mediaDialog
        title: "Open a local media file"
        fileMode: FileDialog.OpenFile
        onAccepted: player.openLocalFile(selectedFile)
    }

    FileDialog {
        id: subtitleDialog
        title: "Add an external subtitle"
        fileMode: FileDialog.OpenFile
        nameFilters: ["Subtitle files (*.srt *.ass *.ssa *.sub *.vtt)", "All files (*)"]
        onAccepted: player.addExternalSubtitle(selectedFile)
    }

    MpvItem {
        id: player
        objectName: "mpvItem"
        anchors.fill: parent
        z: 0
        focus: true

        Keys.onPressed: event => {
            if (event.key === Qt.Key_Space) {
                player.togglePause()
                event.accepted = true
            } else if (event.key === Qt.Key_Left) {
                player.seekRelative(-10)
                event.accepted = true
            } else if (event.key === Qt.Key_Right) {
                player.seekRelative(10)
                event.accepted = true
            } else if (event.key === Qt.Key_F) {
                if (window.visibility === Window.FullScreen)
                    window.showNormal()
                else
                    window.showFullScreen()
                event.accepted = true
            } else if (event.key === Qt.Key_A) {
                player.cycleAudio()
                event.accepted = true
            } else if (event.key === Qt.Key_S) {
                player.cycleSubtitle()
                event.accepted = true
            }
        }

        TapHandler {
            acceptedButtons: Qt.LeftButton
            onTapped: window.controlsVisible = !window.controlsVisible
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: !player.available
        color: "#050505"
        z: 20

        Column {
            anchors.centerIn: parent
            spacing: 14

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "Cinema Paradiso"
                color: "#d7ad58"
                font.pixelSize: 30
                font.weight: Font.DemiBold
            }

            Text {
                width: Math.min(window.width - 120, 760)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: player.status
                color: "#e8e3d9"
                font.pixelSize: 16
            }
        }
    }

    Rectangle {
        id: controls
        visible: window.controlsVisible
        height: 148
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        color: "#e6000000"
        z: 10

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 10

            Slider {
                id: timeline
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, player.duration)
                value: player.position
                onMoved: player.seekAbsolute(value)
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                CpButton {
                    text: "Open"
                    onClicked: mediaDialog.open()
                }

                CpButton {
                    text: player.paused ? "Play" : "Pause"
                    onClicked: player.togglePause()
                }

                CpButton {
                    text: "Audio (" + player.audioTracks.length + ")"
                    onClicked: player.cycleAudio()
                }

                CpButton {
                    text: "Subs (" + player.subtitleTracks.length + ")"
                    onClicked: player.cycleSubtitle()
                }

                CpButton {
                    text: "External subtitle"
                    onClicked: subtitleDialog.open()
                }

                Item {
                    Layout.fillWidth: true
                }

                Text {
                    text: Math.floor(player.position) + " / " + Math.floor(player.duration) + " s"
                    color: "#e8e3d9"
                }

                Text {
                    text: "Volume"
                    color: "#aaa59d"
                }

                Slider {
                    Layout.preferredWidth: 140
                    from: 0
                    to: 100
                    value: player.volume
                    onMoved: player.setVolume(value)
                }

                CpButton {
                    text: window.visibility === Window.FullScreen ? "Window" : "Fullscreen"
                    onClicked: {
                        if (window.visibility === Window.FullScreen)
                            window.showNormal()
                        else
                            window.showFullScreen()
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    Layout.fillWidth: true
                    text: player.status
                    color: "#d7ad58"
                    elide: Text.ElideRight
                }

                Text {
                    text: "Space play/pause · ←/→ seek · A audio · S subtitles · F fullscreen"
                    color: "#77736c"
                    font.pixelSize: 12
                }
            }
        }
    }
}
