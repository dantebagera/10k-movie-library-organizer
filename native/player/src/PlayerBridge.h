#pragma once

#include <QJsonObject>
#include <QLocalSocket>
#include <QObject>
#include <QPointer>
#include <QTimer>
#include <QVariantList>

class MpvItem;

class PlayerBridge final : public QObject
{
    Q_OBJECT
    Q_PROPERTY(QString title READ title NOTIFY mediaChanged)
    Q_PROPERTY(QString year READ year NOTIFY mediaChanged)
    Q_PROPERTY(QString posterReference READ posterReference NOTIFY mediaChanged)
    Q_PROPERTY(QString connectionStatus READ connectionStatus NOTIFY connectionStatusChanged)
    Q_PROPERTY(bool connected READ connected NOTIFY connectionStatusChanged)
    Q_PROPERTY(QVariantMap shortcuts READ shortcuts NOTIFY preferencesChanged)
    Q_PROPERTY(bool resumeDecisionPending READ resumeDecisionPending NOTIFY resumeChanged)
    Q_PROPERTY(qint64 resumePositionMs READ resumePositionMs NOTIFY resumeChanged)

public:
    explicit PlayerBridge(QObject *parent = nullptr);

    QString title() const;
    QString year() const;
    QString posterReference() const;
    QString connectionStatus() const;
    bool connected() const;
    QVariantMap shortcuts() const;
    bool resumeDecisionPending() const;
    qint64 resumePositionMs() const;

    bool configurationValid() const;
    QString configurationError() const;
    void attachPlayer(MpvItem *player);
    void connectToBackend();

    Q_INVOKABLE void requestClose();
    Q_INVOKABLE void requestSubtitleSearch();
    Q_INVOKABLE void chooseResume();
    Q_INVOKABLE void chooseRestart();

signals:
    void mediaChanged();
    void connectionStatusChanged();
    void preferencesChanged();
    void resumeChanged();
    void closeWindowRequested();

private slots:
    void handleConnected();
    void handleReadyRead();
    void handleSocketError(QLocalSocket::LocalSocketError error);
    void handleDisconnected();
    void handleFileLoaded();
    void handlePlaybackEnded();
    void handlePlaybackError(const QString &code, const QString &message);
    void handlePausedChanged();
    void handleTracksChanged();
    void sendProgress();
    void sendPlaybackSettings();

private:
    static constexpr int ProtocolVersion = 1;
    static constexpr qsizetype MaximumMessageBytes = 256 * 1024;

    bool validateEnvelope(const QJsonObject &message, const QString &expectedType) const;
    bool handleLoad(const QJsonObject &message);
    void handleMessage(const QJsonObject &message);
    void sendMessage(const QString &type, const QJsonObject &payload = {});
    void sendPlaybackState(const QString &state);
    void sendTracks();
    void setConnectionStatus(const QString &status);
    void failAndClose(const QString &code, const QString &message);

    QString m_pipeName;
    QString m_sessionId;
    QByteArray m_token;
    QString m_configurationError;
    QLocalSocket m_socket;
    QByteArray m_buffer;
    QPointer<MpvItem> m_player;
    QTimer m_progressTimer;
    quint64 m_sendSequence = 1;
    quint64 m_lastReceivedSequence = 0;
    double m_resumeSeconds = 0.0;
    bool m_resumeDecisionPending = false;
    QString m_title;
    QString m_year;
    QString m_posterReference;
    QString m_audioTrackFingerprint;
    QString m_subtitleTrackFingerprint;
    double m_subtitleDelaySeconds = 0.0;
    QString m_connectionStatus = QStringLiteral("Preparing secure player session");
    QVariantMap m_shortcuts;
    bool m_loadAccepted = false;
    bool m_closingSent = false;
    bool m_closedSent = false;
};
