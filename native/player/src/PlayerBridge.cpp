#include "PlayerBridge.h"

#include "MpvItem.h"

#include <QCoreApplication>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QSet>
#include <QTimer>

#include <cmath>
#include <limits>

namespace {

QString requiredEnvironment(const char *name)
{
    return qEnvironmentVariable(name).trimmed();
}

QJsonObject trackToJson(const QVariant &value)
{
    const QVariantMap track = value.toMap();
    QJsonObject result;
    const QStringList strings{
        QStringLiteral("fingerprint"),
        QStringLiteral("type"),
        QStringLiteral("language"),
        QStringLiteral("title"),
        QStringLiteral("codec"),
        QStringLiteral("channels"),
    };
    for (const QString &key : strings) {
        result.insert(key, track.value(key).toString());
    }
    const QStringList flags{
        QStringLiteral("selected"),
        QStringLiteral("default"),
        QStringLiteral("forced"),
        QStringLiteral("hearing_impaired"),
    };
    for (const QString &key : flags) {
        result.insert(key, track.value(key).toBool());
    }
    return result;
}

} // namespace

PlayerBridge::PlayerBridge(QObject *parent)
    : QObject(parent)
    , m_pipeName(requiredEnvironment("CP_PLAYER_PIPE"))
    , m_sessionId(requiredEnvironment("CP_PLAYER_SESSION_ID"))
    , m_token(qgetenv("CP_PLAYER_SESSION_TOKEN"))
{
    const QString protocol = requiredEnvironment("CP_PLAYER_PROTOCOL");
    qunsetenv("CP_PLAYER_SESSION_TOKEN");

    if (m_pipeName.isEmpty() || m_pipeName.size() > 128) {
        m_configurationError = QStringLiteral("The private player endpoint is invalid");
    } else if (m_sessionId.isEmpty() || m_sessionId.size() > 128) {
        m_configurationError = QStringLiteral("The player session is invalid");
    } else if (m_token.isEmpty() || m_token.size() > 256) {
        m_configurationError = QStringLiteral("The player authentication material is invalid");
    } else if (protocol != QString::number(ProtocolVersion)) {
        m_configurationError = QStringLiteral("The player protocol version is incompatible");
    }

    m_progressTimer.setInterval(1000);
    connect(&m_progressTimer, &QTimer::timeout, this, &PlayerBridge::sendProgress);
    connect(&m_socket, &QLocalSocket::connected, this, &PlayerBridge::handleConnected);
    connect(&m_socket, &QLocalSocket::readyRead, this, &PlayerBridge::handleReadyRead);
    connect(&m_socket, &QLocalSocket::errorOccurred, this, &PlayerBridge::handleSocketError);
    connect(&m_socket, &QLocalSocket::disconnected, this, &PlayerBridge::handleDisconnected);
}

QString PlayerBridge::title() const { return m_title; }
QString PlayerBridge::year() const { return m_year; }
QString PlayerBridge::posterReference() const { return m_posterReference; }
QString PlayerBridge::connectionStatus() const { return m_connectionStatus; }
bool PlayerBridge::connected() const
{
    return m_socket.state() == QLocalSocket::ConnectedState;
}
QVariantMap PlayerBridge::shortcuts() const { return m_shortcuts; }
bool PlayerBridge::resumeDecisionPending() const { return m_resumeDecisionPending; }
qint64 PlayerBridge::resumePositionMs() const { return qRound64(m_resumeSeconds * 1000.0); }
bool PlayerBridge::configurationValid() const { return m_configurationError.isEmpty(); }
QString PlayerBridge::configurationError() const { return m_configurationError; }

void PlayerBridge::attachPlayer(MpvItem *player)
{
    if (!player || m_player == player) {
        return;
    }
    m_player = player;
    connect(player, &MpvItem::fileLoaded, this, &PlayerBridge::handleFileLoaded);
    connect(player, &MpvItem::playbackEnded, this, &PlayerBridge::handlePlaybackEnded);
    connect(player, &MpvItem::playbackError, this, &PlayerBridge::handlePlaybackError);
    connect(player, &MpvItem::pausedChanged, this, &PlayerBridge::handlePausedChanged);
    connect(player, &MpvItem::tracksChanged, this, &PlayerBridge::handleTracksChanged);
    connect(player, &MpvItem::subtitleDelayChanged,
            this, &PlayerBridge::sendPlaybackSettings);
}

void PlayerBridge::connectToBackend()
{
    if (!configurationValid() || !m_player || !m_player->available()) {
        const QString message = !configurationValid()
                                    ? m_configurationError
                                    : QStringLiteral("The native playback runtime is unavailable");
        setConnectionStatus(message);
        QTimer::singleShot(0, this, [this, message]() {
            emit closeWindowRequested();
            Q_UNUSED(message);
        });
        return;
    }
    setConnectionStatus(QStringLiteral("Connecting to Cinema Paradiso"));
    m_socket.connectToServer(m_pipeName, QIODevice::ReadWrite);
}

void PlayerBridge::requestClose()
{
    if (!m_closingSent) {
        m_closingSent = true;
        sendMessage(QStringLiteral("closing"));
    }
    if (!m_closedSent) {
        m_closedSent = true;
        sendMessage(QStringLiteral("closed"));
    }
    m_socket.flush();
    m_socket.waitForBytesWritten(250);
    emit closeWindowRequested();
}

void PlayerBridge::requestSubtitleSearch()
{
    if (m_loadAccepted) {
        sendMessage(QStringLiteral("subtitle.search"));
    }
}

void PlayerBridge::chooseResume()
{
    if (!m_resumeDecisionPending || !m_player) {
        return;
    }
    m_player->seekAbsolute(m_resumeSeconds);
    m_resumeDecisionPending = false;
    emit resumeChanged();
    QJsonObject payload;
    payload.insert(QStringLiteral("choice"), QStringLiteral("resume"));
    sendMessage(QStringLiteral("resume.choice"), payload);
    m_player->setPaused(false);
}

void PlayerBridge::chooseRestart()
{
    if (!m_resumeDecisionPending || !m_player) {
        return;
    }
    m_player->seekAbsolute(0.0);
    m_resumeDecisionPending = false;
    emit resumeChanged();
    QJsonObject payload;
    payload.insert(QStringLiteral("choice"), QStringLiteral("restart"));
    sendMessage(QStringLiteral("resume.choice"), payload);
    m_player->setPaused(false);
}

void PlayerBridge::handleConnected()
{
    setConnectionStatus(QStringLiteral("Authenticating player session"));
    QJsonObject payload;
    payload.insert(QStringLiteral("token"), QString::fromUtf8(m_token));
    sendMessage(QStringLiteral("hello"), payload);
    m_token.fill('\0');
    m_token.clear();
}

void PlayerBridge::handleReadyRead()
{
    m_buffer.append(m_socket.readAll());
    if (m_buffer.size() > MaximumMessageBytes && !m_buffer.contains('\n')) {
        failAndClose(QStringLiteral("message_too_large"),
                     QStringLiteral("The backend sent an oversized player message"));
        return;
    }

    while (true) {
        const qsizetype newline = m_buffer.indexOf('\n');
        if (newline < 0) {
            break;
        }
        const QByteArray line = m_buffer.left(newline);
        m_buffer.remove(0, newline + 1);
        if (line.isEmpty()) {
            continue;
        }
        if (line.size() > MaximumMessageBytes) {
            failAndClose(QStringLiteral("message_too_large"),
                         QStringLiteral("The backend sent an oversized player message"));
            return;
        }
        QJsonParseError parseError;
        const QJsonDocument document = QJsonDocument::fromJson(line, &parseError);
        if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
            failAndClose(QStringLiteral("malformed_message"),
                         QStringLiteral("The backend sent an invalid player message"));
            return;
        }
        handleMessage(document.object());
    }
}

void PlayerBridge::handleSocketError(QLocalSocket::LocalSocketError)
{
    setConnectionStatus(QStringLiteral("Cinema Paradiso connection was lost"));
    if (!m_loadAccepted) {
        emit closeWindowRequested();
    }
}

void PlayerBridge::handleDisconnected()
{
    emit connectionStatusChanged();
    if (!m_closedSent) {
        emit closeWindowRequested();
    }
}

void PlayerBridge::handleFileLoaded()
{
    if (m_player) {
        for (const QVariant &value : m_player->audioTracks()) {
            const QVariantMap track = value.toMap();
            if (!m_audioTrackFingerprint.isEmpty()
                && track.value(QStringLiteral("fingerprint")).toString()
                    == m_audioTrackFingerprint) {
                m_player->selectAudioTrack(track.value(QStringLiteral("id")).toInt());
                break;
            }
        }
        if (m_subtitleTrackFingerprint == QStringLiteral("disabled")) {
            m_player->disableSubtitles();
        } else {
            for (const QVariant &value : m_player->subtitleTracks()) {
                const QVariantMap track = value.toMap();
                if (!m_subtitleTrackFingerprint.isEmpty()
                    && track.value(QStringLiteral("fingerprint")).toString()
                        == m_subtitleTrackFingerprint) {
                    m_player->selectSubtitleTrack(track.value(QStringLiteral("id")).toInt());
                    break;
                }
            }
        }
        m_player->setSubtitleDelay(m_subtitleDelaySeconds);
    }
    sendPlaybackState(m_player && m_player->paused()
                          ? QStringLiteral("paused")
                          : QStringLiteral("playing"));
    sendTracks();
    sendPlaybackSettings();
    sendProgress();
    m_progressTimer.start();
}

void PlayerBridge::handlePlaybackEnded()
{
    sendProgress();
    sendPlaybackState(QStringLiteral("ended"));
}

void PlayerBridge::handlePlaybackError(const QString &code, const QString &message)
{
    QJsonObject payload;
    payload.insert(QStringLiteral("code"), code.left(128));
    payload.insert(QStringLiteral("message"), message.left(1024));
    sendMessage(QStringLiteral("error"), payload);
    sendPlaybackState(QStringLiteral("error"));
}

void PlayerBridge::handlePausedChanged()
{
    if (!m_loadAccepted || !m_player) {
        return;
    }
    sendPlaybackState(m_player->paused() ? QStringLiteral("paused")
                                         : QStringLiteral("playing"));
    sendProgress();
}

void PlayerBridge::handleTracksChanged()
{
    if (m_loadAccepted) {
        sendTracks();
    }
}

void PlayerBridge::sendProgress()
{
    if (!m_loadAccepted || !m_player) {
        return;
    }
    const double position = std::max(0.0, m_player->position());
    const double duration = std::max(0.0, m_player->duration());
    QJsonObject payload;
    payload.insert(QStringLiteral("position_ms"), qRound64(position * 1000.0));
    payload.insert(QStringLiteral("duration_ms"), qRound64(duration * 1000.0));
    payload.insert(QStringLiteral("paused"), m_player->paused());
    sendMessage(QStringLiteral("progress"), payload);
}

bool PlayerBridge::validateEnvelope(const QJsonObject &message,
                                    const QString &expectedType) const
{
    if (message.value(QStringLiteral("type")).toString() != expectedType
        || message.value(QStringLiteral("protocol")).toInt(-1) != ProtocolVersion
        || message.value(QStringLiteral("session_id")).toString() != m_sessionId) {
        return false;
    }
    const QJsonValue sequenceValue = message.value(QStringLiteral("sequence"));
    if (!sequenceValue.isDouble()) {
        return false;
    }
    const double sequence = sequenceValue.toDouble();
    return std::isfinite(sequence) && sequence > static_cast<double>(m_lastReceivedSequence)
           && sequence <= static_cast<double>(std::numeric_limits<quint64>::max());
}

bool PlayerBridge::handleLoad(const QJsonObject &message)
{
    if (!validateEnvelope(message, QStringLiteral("load")) || m_loadAccepted || !m_player) {
        return false;
    }
    const QJsonObject media = message.value(QStringLiteral("media")).toObject();
    const QString pathKey = media.value(QStringLiteral("path_key")).toString();
    const QString path = media.value(QStringLiteral("path")).toString();
    const QString title = media.value(QStringLiteral("title")).toString().trimmed();
    const QString year = media.value(QStringLiteral("year")).toString().trimmed();
    const QString poster = media.value(QStringLiteral("poster_reference")).toString().trimmed();
    const QFileInfo file(path);
    const double startMs = message.value(QStringLiteral("start_position_ms")).toDouble(-1.0);
    const QJsonObject playbackState =
        message.value(QStringLiteral("playback_state")).toObject();
    const QString audioFingerprint =
        playbackState.value(QStringLiteral("audio_track_fingerprint")).toString();
    const QString subtitleFingerprint =
        playbackState.value(QStringLiteral("subtitle_track_fingerprint")).toString();
    const double subtitleDelayMs =
        playbackState.value(QStringLiteral("subtitle_delay_ms")).toDouble(0.0);
    if (pathKey.isEmpty() || pathKey.size() > 4096 || title.isEmpty() || title.size() > 512
        || year.size() > 16 || poster.size() > 4096 || path.size() > 32768
        || !file.isAbsolute() || !file.exists() || !file.isFile()
        || !std::isfinite(startMs) || startMs < 0.0
        || audioFingerprint.size() > 512 || subtitleFingerprint.size() > 512
        || !std::isfinite(subtitleDelayMs)
        || subtitleDelayMs < -3600000.0 || subtitleDelayMs > 3600000.0
        || !message.value(QStringLiteral("preferences")).isObject()) {
        return false;
    }

    m_lastReceivedSequence =
        static_cast<quint64>(message.value(QStringLiteral("sequence")).toDouble());
    m_title = title;
    m_year = year;
    m_posterReference = poster;
    m_resumeSeconds = startMs / 1000.0;
    m_audioTrackFingerprint = audioFingerprint;
    m_subtitleTrackFingerprint = subtitleFingerprint;
    m_subtitleDelaySeconds = subtitleDelayMs / 1000.0;
    m_resumeDecisionPending = m_resumeSeconds > 0.0;
    emit mediaChanged();
    emit resumeChanged();

    const QVariantMap preferences =
        message.value(QStringLiteral("preferences")).toObject().toVariantMap();
    const QVariantMap requestedShortcuts =
        preferences.value(QStringLiteral("keyboard_shortcuts")).toMap();
    static const QSet<QString> allowedShortcutActions{
        QStringLiteral("play_pause"),
        QStringLiteral("seek_backward"),
        QStringLiteral("seek_forward"),
        QStringLiteral("seek_backward_long"),
        QStringLiteral("seek_forward_long"),
        QStringLiteral("volume_up"),
        QStringLiteral("volume_down"),
        QStringLiteral("mute"),
        QStringLiteral("fullscreen"),
        QStringLiteral("audio_tracks"),
        QStringLiteral("subtitle_tracks"),
        QStringLiteral("subtitle_search"),
        QStringLiteral("speed_down"),
        QStringLiteral("speed_up"),
        QStringLiteral("subtitle_delay_down"),
        QStringLiteral("subtitle_delay_up"),
        QStringLiteral("audio_delay_down"),
        QStringLiteral("audio_delay_up"),
        QStringLiteral("chapters"),
        QStringLiteral("statistics"),
        QStringLiteral("screenshot"),
    };
    QVariantMap validatedShortcuts;
    for (auto iterator = requestedShortcuts.cbegin();
         iterator != requestedShortcuts.cend();
         ++iterator) {
        const QString sequence = iterator.value().toString().trimmed();
        if (allowedShortcutActions.contains(iterator.key())
            && !sequence.isEmpty() && sequence.size() <= 64) {
            validatedShortcuts.insert(iterator.key(), sequence);
        }
    }
    m_shortcuts = validatedShortcuts;
    emit preferencesChanged();
    if (m_resumeDecisionPending) {
        m_player->setPaused(true);
    }
    if (!m_player->openTrustedLocalPath(file.absoluteFilePath(), preferences)) {
        return false;
    }
    m_loadAccepted = true;
    setConnectionStatus(QStringLiteral("Loading"));
    QJsonObject ready;
    ready.insert(QStringLiteral("accepted"), true);
    sendMessage(QStringLiteral("ready"), ready);
    sendPlaybackState(QStringLiteral("loading"));
    return true;
}

void PlayerBridge::handleMessage(const QJsonObject &message)
{
    const QString type = message.value(QStringLiteral("type")).toString();
    if (type == QStringLiteral("load")) {
        if (!handleLoad(message)) {
            failAndClose(QStringLiteral("invalid_load"),
                         QStringLiteral("The backend playback request was rejected"));
        }
        return;
    }
    if (type == QStringLiteral("close")
        && validateEnvelope(message, QStringLiteral("close"))) {
        m_lastReceivedSequence =
            static_cast<quint64>(message.value(QStringLiteral("sequence")).toDouble());
        requestClose();
        return;
    }
    failAndClose(QStringLiteral("unsupported_message"),
                 QStringLiteral("The backend sent an unsupported player command"));
}

void PlayerBridge::sendMessage(const QString &type, const QJsonObject &payload)
{
    if (m_socket.state() != QLocalSocket::ConnectedState) {
        return;
    }
    QJsonObject message = payload;
    message.insert(QStringLiteral("type"), type);
    message.insert(QStringLiteral("protocol"), ProtocolVersion);
    message.insert(QStringLiteral("session_id"), m_sessionId);
    message.insert(QStringLiteral("sequence"), static_cast<qint64>(m_sendSequence++));
    const QByteArray encoded = QJsonDocument(message).toJson(QJsonDocument::Compact) + '\n';
    if (encoded.size() <= MaximumMessageBytes) {
        m_socket.write(encoded);
        m_socket.flush();
    }
}

void PlayerBridge::sendPlaybackState(const QString &state)
{
    QJsonObject payload;
    payload.insert(QStringLiteral("state"), state);
    sendMessage(QStringLiteral("playback.state"), payload);
}

void PlayerBridge::sendTracks()
{
    if (!m_player) {
        return;
    }
    QJsonArray tracks;
    for (const QVariant &track : m_player->audioTracks()) {
        tracks.append(trackToJson(track));
    }
    for (const QVariant &track : m_player->subtitleTracks()) {
        tracks.append(trackToJson(track));
    }
    QJsonObject payload;
    payload.insert(QStringLiteral("tracks"), tracks);
    sendMessage(QStringLiteral("tracks.changed"), payload);
}

void PlayerBridge::sendPlaybackSettings()
{
    if (!m_loadAccepted || !m_player) {
        return;
    }
    QJsonObject payload;
    payload.insert(
        QStringLiteral("subtitle_delay_ms"),
        qRound64(m_player->subtitleDelay() * 1000.0)
    );
    sendMessage(QStringLiteral("playback.settings"), payload);
}

void PlayerBridge::setConnectionStatus(const QString &status)
{
    if (m_connectionStatus == status) {
        return;
    }
    m_connectionStatus = status;
    emit connectionStatusChanged();
}

void PlayerBridge::failAndClose(const QString &code, const QString &message)
{
    QJsonObject payload;
    payload.insert(QStringLiteral("code"), code.left(128));
    payload.insert(QStringLiteral("message"), message.left(1024));
    sendMessage(QStringLiteral("error"), payload);
    setConnectionStatus(message);
    m_socket.flush();
    m_socket.waitForBytesWritten(100);
    m_socket.disconnectFromServer();
    emit closeWindowRequested();
}
