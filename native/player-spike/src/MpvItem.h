#pragma once

#include "MpvApi.h"

#include <QElapsedTimer>
#include <QQuickFramebufferObject>
#include <QStringList>
#include <QUrl>
#include <QtQml/qqmlregistration.h>

#include <memory>

class MpvItem : public QQuickFramebufferObject
{
    Q_OBJECT
    QML_ELEMENT

    Q_PROPERTY(bool available READ available NOTIFY availableChanged)
    Q_PROPERTY(bool paused READ paused NOTIFY pausedChanged)
    Q_PROPERTY(double position READ position NOTIFY positionChanged)
    Q_PROPERTY(double duration READ duration NOTIFY durationChanged)
    Q_PROPERTY(double volume READ volume NOTIFY volumeChanged)
    Q_PROPERTY(QString status READ status NOTIFY statusChanged)
    Q_PROPERTY(QStringList audioTracks READ audioTracks NOTIFY tracksChanged)
    Q_PROPERTY(QStringList subtitleTracks READ subtitleTracks NOTIFY tracksChanged)

public:
    explicit MpvItem(QQuickItem *parent = nullptr);
    ~MpvItem() override;

    Renderer *createRenderer() const override;

    bool available() const;
    bool paused() const;
    double position() const;
    double duration() const;
    double volume() const;
    QString status() const;
    QStringList audioTracks() const;
    QStringList subtitleTracks() const;

    Q_INVOKABLE bool openLocalFile(const QUrl &url);
    Q_INVOKABLE bool addExternalSubtitle(const QUrl &url);
    Q_INVOKABLE void togglePause();
    Q_INVOKABLE void seekAbsolute(double seconds);
    Q_INVOKABLE void seekRelative(double seconds);
    Q_INVOKABLE void setVolume(double value);
    Q_INVOKABLE void cycleAudio();
    Q_INVOKABLE void cycleSubtitle();
    Q_INVOKABLE void shutdownPlayback();

signals:
    void availableChanged();
    void pausedChanged();
    void positionChanged();
    void durationChanged();
    void volumeChanged();
    void statusChanged();
    void tracksChanged();
    void fileLoaded();
    void firstFrameRendered(qint64 elapsedMilliseconds);
    void playbackError(const QString &message);

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
    void updateTrackLists();
    QString propertyString(const QByteArray &name) const;
    QString trackLabel(int index) const;

    std::unique_ptr<MpvApi> m_api;
    mpv_handle *m_mpv = nullptr;
    bool m_available = false;
    bool m_paused = false;
    bool m_firstFrameNoted = false;
    double m_position = 0.0;
    double m_duration = 0.0;
    double m_volume = 100.0;
    QString m_status = QStringLiteral("Initializing native rendering");
    QStringList m_audioTracks;
    QStringList m_subtitleTracks;
    QElapsedTimer m_loadTimer;
    quint64 m_loadGeneration = 0;
    quint64 m_fileLoadedGeneration = 0;
};
