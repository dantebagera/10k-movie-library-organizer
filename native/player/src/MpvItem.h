#pragma once

#include "MpvApi.h"

#include <QElapsedTimer>
#include <QQuickFramebufferObject>
#include <QVariantList>
#include <QtQml/qqmlregistration.h>

#include <memory>

class MpvItem : public QQuickFramebufferObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool available READ available NOTIFY availableChanged)
    Q_PROPERTY(bool paused READ paused NOTIFY pausedChanged)
    Q_PROPERTY(bool muted READ muted NOTIFY mutedChanged)
    Q_PROPERTY(double position READ position NOTIFY positionChanged)
    Q_PROPERTY(double duration READ duration NOTIFY durationChanged)
    Q_PROPERTY(double volume READ volume NOTIFY volumeChanged)
    Q_PROPERTY(double speed READ speed NOTIFY speedChanged)
    Q_PROPERTY(double subtitleDelay READ subtitleDelay NOTIFY subtitleDelayChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(QVariantList audioTracks READ audioTracks NOTIFY audioTracksChanged)
    Q_PROPERTY(QVariantList subtitleTracks READ subtitleTracks NOTIFY subtitleTracksChanged)
    Q_PROPERTY(QVariantList chapters READ chapters NOTIFY chaptersChanged)

public:
    explicit MpvItem(QQuickItem *parent = nullptr);
    ~MpvItem() override;

    Renderer *createRenderer() const override;

    bool available() const;
    bool paused() const;
    bool muted() const;
    double position() const;
    double duration() const;
    double volume() const;
    double speed() const;
    double subtitleDelay() const;
    QString status() const;
    QVariantList audioTracks() const;
    QVariantList subtitleTracks() const;
    QVariantList chapters() const;

    bool openTrustedLocalPath(const QString &path, const QVariantMap &preferences);
    Q_INVOKABLE void togglePause();
    Q_INVOKABLE void setPaused(bool paused);
    Q_INVOKABLE void seekAbsolute(double seconds);
    Q_INVOKABLE void seekRelative(double seconds);
    Q_INVOKABLE void setVolume(double value);
    Q_INVOKABLE void toggleMute();
    Q_INVOKABLE void setSpeed(double value);
    Q_INVOKABLE void selectAudioTrack(int id);
    Q_INVOKABLE void selectSubtitleTrack(int id);
    Q_INVOKABLE void disableSubtitles();
    Q_INVOKABLE bool loadExternalSubtitle(const QString &path);
    Q_INVOKABLE void adjustSubtitleDelay(double seconds);
    Q_INVOKABLE void setSubtitleDelay(double seconds);
    Q_INVOKABLE void adjustAudioDelay(double seconds);
    Q_INVOKABLE void shutdownPlayback();

signals:
    void availableChanged();
    void pausedChanged();
    void mutedChanged();
    void positionChanged();
    void durationChanged();
    void volumeChanged();
    void speedChanged();
    void subtitleDelayChanged();
    void statusChanged();
    void audioTracksChanged();
    void subtitleTracksChanged();
    void tracksChanged();
    void chaptersChanged();
    void fileLoaded();
    void playbackEnded();
    void firstFrameRendered(qint64 elapsedMilliseconds);
    void playbackError(const QString &code, const QString &message);

private slots:
    void processEvents();
    void requestRender();
    void noteFirstFrame();

private:
    friend class MpvRenderer;

    static void wakeup(void *context);
    bool sendCommand(const QList<QByteArray> &arguments);
    void initializeMpv();
    void setStatus(const QString &status);
    void updateTrackModels();
    void updateChapters();
    QString propertyString(const QByteArray &name) const;
    QVariantMap trackModel(int index) const;
    static QString trackFingerprint(const QVariantMap &track);
    void applyPreferences(const QVariantMap &preferences);

    std::unique_ptr<MpvApi> m_api;
    mpv_handle *m_mpv = nullptr;
    bool m_available = false;
    bool m_paused = false;
    bool m_muted = false;
    bool m_firstFrameNoted = false;
    double m_position = 0.0;
    double m_duration = 0.0;
    double m_volume = 100.0;
    double m_speed = 1.0;
    double m_subtitleDelay = 0.0;
    QString m_status = QStringLiteral("Initializing Cinema Paradiso Player");
    QVariantList m_audioTracks;
    QVariantList m_subtitleTracks;
    QVariantList m_chapters;
    QElapsedTimer m_loadTimer;
    quint64 m_loadGeneration = 0;
    quint64 m_fileLoadedGeneration = 0;
};
