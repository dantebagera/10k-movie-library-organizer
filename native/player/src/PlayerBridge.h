#pragma once

#include <QJsonObject>
#include <QHash>
#include <QLocalSocket>
#include <QObject>
#include <QPointer>
#include <QSet>
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
    Q_PROPERTY(QVariantMap windowState READ windowState NOTIFY preferencesChanged)
    Q_PROPERTY(bool resumeDecisionPending READ resumeDecisionPending NOTIFY resumeChanged)
    Q_PROPERTY(qint64 resumePositionMs READ resumePositionMs NOTIFY resumeChanged)
    Q_PROPERTY(QVariantList subtitleResults READ subtitleResults NOTIFY subtitleSearchChanged)
    Q_PROPERTY(QString subtitleSearchStatus READ subtitleSearchStatus NOTIFY subtitleSearchChanged)
    Q_PROPERTY(QString subtitleSearchError READ subtitleSearchError NOTIFY subtitleSearchChanged)
    Q_PROPERTY(bool selectedSubtitleCanSave READ selectedSubtitleCanSave NOTIFY subtitleSaveChanged)
    Q_PROPERTY(QString subtitleSaveStatus READ subtitleSaveStatus NOTIFY subtitleSaveChanged)
    Q_PROPERTY(QString subtitleSaveError READ subtitleSaveError NOTIFY subtitleSaveChanged)

public:
    explicit PlayerBridge(QObject *parent = nullptr);

    QString title() const;
    QString year() const;
    QString posterReference() const;
    QString connectionStatus() const;
    bool connected() const;
    QVariantMap shortcuts() const;
    QVariantMap windowState() const;
    bool resumeDecisionPending() const;
    qint64 resumePositionMs() const;
    QVariantList subtitleResults() const;
    QString subtitleSearchStatus() const;
    QString subtitleSearchError() const;
    bool selectedSubtitleCanSave() const;
    QString subtitleSaveStatus() const;
    QString subtitleSaveError() const;

    bool configurationValid() const;
    QString configurationError() const;
    void attachPlayer(MpvItem *player);
    void connectToBackend();

    Q_INVOKABLE void requestClose();
    Q_INVOKABLE void requestSubtitleSearch();
    Q_INVOKABLE void requestSubtitleDownload(const QString &resultId);
    Q_INVOKABLE void requestSaveSelectedSubtitle();
    Q_INVOKABLE void chooseResume();
    Q_INVOKABLE void chooseRestart();
    Q_INVOKABLE void reportWindowState(int x, int y, int width, int height,
                                       const QString &screen, bool maximized,
                                       bool alwaysOnTop);

signals:
    void mediaChanged();
    void connectionStatusChanged();
    void preferencesChanged();
    void resumeChanged();
    void subtitleSearchChanged();
    void subtitleSaveChanged();
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

    static QString normalizedLocalPath(const QString &path);
    QString selectedSubtitleResultId() const;
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
    QVariantList m_subtitleResults;
    QString m_subtitleSearchStatus = QStringLiteral("idle");
    QString m_subtitleSearchError;
    QHash<QString, QString> m_subtitleResultIdsByPath;
    QString m_lastSelectedSubtitleResultId;
    QString m_subtitleSaveStatus = QStringLiteral("idle");
    QString m_subtitleSaveError;
    double m_subtitleDelaySeconds = 0.0;
    QString m_connectionStatus = QStringLiteral("Preparing secure player session");
    QVariantMap m_shortcuts;
    QVariantMap m_windowState;
    bool m_loadAccepted = false;
    bool m_closingSent = false;
    bool m_closedSent = false;
};
