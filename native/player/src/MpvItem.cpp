#include "MpvItem.h"

#include <QCoreApplication>
#include <QFile>
#include <QFileInfo>
#include <QMetaObject>
#include <QOpenGLContext>
#include <QOpenGLFramebufferObject>
#include <QQuickOpenGLUtils>
#include <QTimer>

#include <algorithm>
#include <vector>

namespace {

void *resolveOpenGlProcedure(void *, const char *name)
{
    QOpenGLContext *context = QOpenGLContext::currentContext();
    if (!context) {
        return nullptr;
    }
    const QFunctionPointer procedure = context->getProcAddress(QByteArray(name));
    return reinterpret_cast<void *>(procedure);
}

bool propertyYes(const QString &value)
{
    return value == QStringLiteral("yes") || value == QStringLiteral("true");
}

QString normalizedLanguage(QString value)
{
    value = value.trimmed().toLower();
    return value.isEmpty() ? QStringLiteral("und") : value;
}

} // namespace

class MpvRenderer final : public QQuickFramebufferObject::Renderer
{
public:
    explicit MpvRenderer(MpvItem *item)
        : m_item(item)
    {
    }

    ~MpvRenderer() override
    {
        if (m_context && m_api) {
            m_api->renderContextSetUpdateCallback(m_context, nullptr, nullptr);
            m_api->renderContextFree(m_context);
        }
    }

    QOpenGLFramebufferObject *createFramebufferObject(const QSize &size) override
    {
        QOpenGLFramebufferObjectFormat format;
        format.setAttachment(QOpenGLFramebufferObject::CombinedDepthStencil);
        return new QOpenGLFramebufferObject(size, format);
    }

    void synchronize(QQuickFramebufferObject *item) override
    {
        m_item = static_cast<MpvItem *>(item);
        m_api = m_item->m_api.get();
        m_mpv = m_item->m_mpv;
        if (m_loadGeneration != m_item->m_fileLoadedGeneration) {
            m_loadGeneration = m_item->m_fileLoadedGeneration;
            m_firstFrameSent = false;
        }
        ensureRenderContext();
    }

    void render() override
    {
        if (!m_context || !m_api) {
            return;
        }
        QOpenGLFramebufferObject *target = framebufferObject();
        if (!target) {
            return;
        }

        mpv_opengl_fbo framebuffer{
            static_cast<int>(target->handle()),
            target->width(),
            target->height(),
            0,
        };
        int flipY = 1;
        mpv_render_param parameters[] = {
            {MPV_RENDER_PARAM_OPENGL_FBO, &framebuffer},
            {MPV_RENDER_PARAM_FLIP_Y, &flipY},
            {MPV_RENDER_PARAM_INVALID, nullptr},
        };
        m_api->renderContextRender(m_context, parameters);
        QQuickOpenGLUtils::resetOpenGLState();

        if (!m_firstFrameSent && m_loadGeneration > 0) {
            m_firstFrameSent = true;
            QMetaObject::invokeMethod(m_item, &MpvItem::noteFirstFrame, Qt::QueuedConnection);
        }
    }

private:
    static void update(void *context)
    {
        auto *item = static_cast<MpvItem *>(context);
        if (item) {
            QMetaObject::invokeMethod(item, &MpvItem::requestRender, Qt::QueuedConnection);
        }
    }

    void ensureRenderContext()
    {
        if (m_context || !m_api || !m_mpv) {
            return;
        }
        const char *apiType = MPV_RENDER_API_TYPE_OPENGL;
        mpv_opengl_init_params openGlParameters{&resolveOpenGlProcedure, nullptr};
        int advancedControl = 1;
        mpv_render_param parameters[] = {
            {MPV_RENDER_PARAM_API_TYPE, const_cast<char *>(apiType)},
            {MPV_RENDER_PARAM_OPENGL_INIT_PARAMS, &openGlParameters},
            {MPV_RENDER_PARAM_ADVANCED_CONTROL, &advancedControl},
            {MPV_RENDER_PARAM_INVALID, nullptr},
        };
        const int result = m_api->renderContextCreate(&m_context, m_mpv, parameters);
        if (result < 0) {
            const QString message = QStringLiteral("libmpv render context failed: %1")
                                        .arg(QString::fromUtf8(m_api->errorText(result)));
            QMetaObject::invokeMethod(
                m_item,
                [item = m_item, message]() {
                    item->setStatus(message);
                    emit item->playbackError(QStringLiteral("render_context"), message);
                },
                Qt::QueuedConnection);
            return;
        }
        m_api->renderContextSetUpdateCallback(m_context, &MpvRenderer::update, m_item);
    }

    MpvItem *m_item = nullptr;
    MpvApi *m_api = nullptr;
    mpv_handle *m_mpv = nullptr;
    mpv_render_context *m_context = nullptr;
    quint64 m_loadGeneration = 0;
    bool m_firstFrameSent = false;
};

MpvItem::MpvItem(QQuickItem *parent)
    : QQuickFramebufferObject(parent)
{
    setMirrorVertically(false);
    initializeMpv();
}

MpvItem::~MpvItem()
{
    shutdownPlayback();
}

QQuickFramebufferObject::Renderer *MpvItem::createRenderer() const
{
    return new MpvRenderer(const_cast<MpvItem *>(this));
}

bool MpvItem::available() const { return m_available; }
bool MpvItem::paused() const { return m_paused; }
bool MpvItem::muted() const { return m_muted; }
double MpvItem::position() const { return m_position; }
double MpvItem::duration() const { return m_duration; }
double MpvItem::volume() const { return m_volume; }
double MpvItem::speed() const { return m_speed; }
double MpvItem::subtitleDelay() const { return m_subtitleDelay; }
QString MpvItem::status() const { return m_status; }
QVariantList MpvItem::audioTracks() const { return m_audioTracks; }
QVariantList MpvItem::subtitleTracks() const { return m_subtitleTracks; }
QVariantList MpvItem::chapters() const { return m_chapters; }

bool MpvItem::openTrustedLocalPath(const QString &path, const QVariantMap &preferences)
{
    if (!m_available) {
        emit playbackError(QStringLiteral("runtime_unavailable"), m_status);
        return false;
    }
    const QFileInfo media(path);
    if (!media.isAbsolute() || !media.exists() || !media.isFile()) {
        const QString message = QStringLiteral("The authenticated library file is unavailable");
        setStatus(message);
        emit playbackError(QStringLiteral("media_unavailable"), message);
        return false;
    }

    applyPreferences(preferences);
    m_firstFrameNoted = false;
    ++m_loadGeneration;
    m_loadTimer.restart();
    setStatus(QStringLiteral("Loading"));
    return sendCommand({
        QByteArrayLiteral("loadfile"),
        QFile::encodeName(media.absoluteFilePath()),
        QByteArrayLiteral("replace"),
    });
}

void MpvItem::togglePause()
{
    sendCommand({QByteArrayLiteral("cycle"), QByteArrayLiteral("pause")});
}

void MpvItem::setPaused(bool paused)
{
    sendCommand({
        QByteArrayLiteral("set"),
        QByteArrayLiteral("pause"),
        paused ? QByteArrayLiteral("yes") : QByteArrayLiteral("no"),
    });
}

void MpvItem::seekAbsolute(double seconds)
{
    sendCommand({
        QByteArrayLiteral("seek"),
        QByteArray::number(std::max(0.0, seconds), 'f', 3),
        QByteArrayLiteral("absolute+exact"),
    });
}

void MpvItem::seekRelative(double seconds)
{
    sendCommand({
        QByteArrayLiteral("seek"),
        QByteArray::number(seconds, 'f', 3),
        QByteArrayLiteral("relative+exact"),
    });
}

void MpvItem::setVolume(double value)
{
    sendCommand({
        QByteArrayLiteral("set"),
        QByteArrayLiteral("volume"),
        QByteArray::number(std::clamp(value, 0.0, 100.0), 'f', 1),
    });
}

void MpvItem::toggleMute()
{
    sendCommand({QByteArrayLiteral("cycle"), QByteArrayLiteral("mute")});
}

void MpvItem::setSpeed(double value)
{
    sendCommand({
        QByteArrayLiteral("set"),
        QByteArrayLiteral("speed"),
        QByteArray::number(std::clamp(value, 0.25, 4.0), 'f', 2),
    });
}

void MpvItem::selectAudioTrack(int id)
{
    sendCommand({
        QByteArrayLiteral("set"),
        QByteArrayLiteral("aid"),
        QByteArray::number(id),
    });
    QTimer::singleShot(250, this, &MpvItem::updateTrackModels);
    QTimer::singleShot(750, this, &MpvItem::updateTrackModels);
}

void MpvItem::selectSubtitleTrack(int id)
{
    sendCommand({
        QByteArrayLiteral("set"),
        QByteArrayLiteral("sid"),
        QByteArray::number(id),
    });
    QTimer::singleShot(250, this, &MpvItem::updateTrackModels);
    QTimer::singleShot(750, this, &MpvItem::updateTrackModels);
}

void MpvItem::disableSubtitles()
{
    sendCommand({QByteArrayLiteral("set"), QByteArrayLiteral("sid"), QByteArrayLiteral("no")});
    QTimer::singleShot(250, this, &MpvItem::updateTrackModels);
    QTimer::singleShot(750, this, &MpvItem::updateTrackModels);
}

void MpvItem::adjustSubtitleDelay(double seconds)
{
    sendCommand({
        QByteArrayLiteral("add"),
        QByteArrayLiteral("sub-delay"),
        QByteArray::number(seconds, 'f', 3),
    });
}

void MpvItem::setSubtitleDelay(double seconds)
{
    sendCommand({
        QByteArrayLiteral("set"),
        QByteArrayLiteral("sub-delay"),
        QByteArray::number(std::clamp(seconds, -3600.0, 3600.0), 'f', 3),
    });
}

void MpvItem::adjustAudioDelay(double seconds)
{
    sendCommand({
        QByteArrayLiteral("add"),
        QByteArrayLiteral("audio-delay"),
        QByteArray::number(seconds, 'f', 3),
    });
}

void MpvItem::shutdownPlayback()
{
    if (!m_mpv || !m_api) {
        return;
    }
    m_api->setWakeupCallback(m_mpv, nullptr, nullptr);
    m_api->terminateDestroy(m_mpv);
    m_mpv = nullptr;
    m_available = false;
    emit availableChanged();
}

void MpvItem::processEvents()
{
    if (!m_mpv || !m_api) {
        return;
    }
    while (true) {
        mpv_event *event = m_api->waitEvent(m_mpv, 0.0);
        if (!event || event->event_id == MPV_EVENT_NONE) {
            break;
        }
        if (event->event_id == MPV_EVENT_FILE_LOADED) {
            m_fileLoadedGeneration = m_loadGeneration;
            setStatus(QStringLiteral("Playing"));
            updateTrackModels();
            updateChapters();
            update();
            emit fileLoaded();
            continue;
        }
        if (event->event_id == MPV_EVENT_PROPERTY_CHANGE) {
            auto *property = static_cast<mpv_event_property *>(event->data);
            if (!property || !property->data) {
                continue;
            }
            const QByteArray name(property->name);
            if (name == QByteArrayLiteral("time-pos") && property->format == MPV_FORMAT_DOUBLE) {
                m_position = *static_cast<double *>(property->data);
                emit positionChanged();
            } else if (name == QByteArrayLiteral("duration")
                       && property->format == MPV_FORMAT_DOUBLE) {
                m_duration = *static_cast<double *>(property->data);
                emit durationChanged();
            } else if (name == QByteArrayLiteral("volume")
                       && property->format == MPV_FORMAT_DOUBLE) {
                m_volume = *static_cast<double *>(property->data);
                emit volumeChanged();
            } else if (name == QByteArrayLiteral("pause")
                       && property->format == MPV_FORMAT_FLAG) {
                m_paused = *static_cast<int *>(property->data) != 0;
                emit pausedChanged();
            } else if (name == QByteArrayLiteral("mute")
                       && property->format == MPV_FORMAT_FLAG) {
                m_muted = *static_cast<int *>(property->data) != 0;
                emit mutedChanged();
            } else if (name == QByteArrayLiteral("speed")
                       && property->format == MPV_FORMAT_DOUBLE) {
                m_speed = *static_cast<double *>(property->data);
                emit speedChanged();
            } else if (name == QByteArrayLiteral("sub-delay")
                       && property->format == MPV_FORMAT_DOUBLE) {
                m_subtitleDelay = *static_cast<double *>(property->data);
                emit subtitleDelayChanged();
            }
            continue;
        }
        if (event->event_id == MPV_EVENT_END_FILE) {
            auto *end = static_cast<mpv_event_end_file *>(event->data);
            if (end && end->error < 0) {
                const QString message = QStringLiteral("Playback failed: %1")
                                            .arg(QString::fromUtf8(m_api->errorText(end->error)));
                setStatus(message);
                emit playbackError(QStringLiteral("playback_failed"), message);
            } else {
                setStatus(QStringLiteral("Playback ended"));
                emit playbackEnded();
            }
        }
    }
}

void MpvItem::requestRender()
{
    update();
}

void MpvItem::noteFirstFrame()
{
    if (m_firstFrameNoted || !m_loadTimer.isValid()) {
        return;
    }
    m_firstFrameNoted = true;
    emit firstFrameRendered(m_loadTimer.elapsed());
}

void MpvItem::wakeup(void *context)
{
    auto *item = static_cast<MpvItem *>(context);
    if (item) {
        QMetaObject::invokeMethod(item, &MpvItem::processEvents, Qt::QueuedConnection);
    }
}

bool MpvItem::sendCommand(const QList<QByteArray> &arguments)
{
    if (!m_mpv || !m_api || arguments.isEmpty()) {
        return false;
    }
    std::vector<const char *> command;
    command.reserve(static_cast<std::size_t>(arguments.size()) + 1);
    for (const QByteArray &argument : arguments) {
        command.push_back(argument.constData());
    }
    command.push_back(nullptr);
    const int result = m_api->command(m_mpv, command.data());
    if (result >= 0) {
        return true;
    }
    const QString message = QStringLiteral("libmpv command failed: %1")
                                .arg(QString::fromUtf8(m_api->errorText(result)));
    setStatus(message);
    emit playbackError(QStringLiteral("mpv_command"), message);
    return false;
}

void MpvItem::initializeMpv()
{
    const QString runtimePath = QCoreApplication::applicationDirPath()
                                + QStringLiteral("/libmpv-2.dll");
    m_api = std::make_unique<MpvApi>(runtimePath);
    if (!m_api->isLoaded()) {
        setStatus(m_api->errorString());
        emit playbackError(QStringLiteral("runtime_unavailable"), m_status);
        return;
    }
    m_mpv = m_api->create();
    if (!m_mpv) {
        setStatus(QStringLiteral("libmpv could not create a playback client"));
        emit playbackError(QStringLiteral("mpv_create"), m_status);
        return;
    }
    const QList<QPair<QByteArray, QByteArray>> options = {
        {QByteArrayLiteral("config"), QByteArrayLiteral("no")},
        {QByteArrayLiteral("terminal"), QByteArrayLiteral("no")},
        {QByteArrayLiteral("input-default-bindings"), QByteArrayLiteral("no")},
        {QByteArrayLiteral("vo"), QByteArrayLiteral("libmpv")},
        {QByteArrayLiteral("hwdec"), QByteArrayLiteral("auto-safe")},
        {QByteArrayLiteral("keep-open"), QByteArrayLiteral("yes")},
        {QByteArrayLiteral("audio-display"), QByteArrayLiteral("no")},
        {QByteArrayLiteral("sub-auto"), QByteArrayLiteral("all")},
    };
    for (const auto &[name, value] : options) {
        const int result = m_api->setOptionString(m_mpv, name.constData(), value.constData());
        if (result < 0) {
            setStatus(QStringLiteral("libmpv rejected required option: %1")
                          .arg(QString::fromLatin1(name)));
            emit playbackError(QStringLiteral("mpv_option"), m_status);
            return;
        }
    }
    const int initialized = m_api->initialize(m_mpv);
    if (initialized < 0) {
        setStatus(QStringLiteral("libmpv initialization failed: %1")
                      .arg(QString::fromUtf8(m_api->errorText(initialized))));
        emit playbackError(QStringLiteral("mpv_initialize"), m_status);
        return;
    }
    m_api->observeProperty(m_mpv, 1, "time-pos", MPV_FORMAT_DOUBLE);
    m_api->observeProperty(m_mpv, 2, "duration", MPV_FORMAT_DOUBLE);
    m_api->observeProperty(m_mpv, 3, "pause", MPV_FORMAT_FLAG);
    m_api->observeProperty(m_mpv, 4, "volume", MPV_FORMAT_DOUBLE);
    m_api->observeProperty(m_mpv, 5, "mute", MPV_FORMAT_FLAG);
    m_api->observeProperty(m_mpv, 6, "speed", MPV_FORMAT_DOUBLE);
    m_api->observeProperty(m_mpv, 7, "sub-delay", MPV_FORMAT_DOUBLE);
    m_api->setWakeupCallback(m_mpv, &MpvItem::wakeup, this);
    m_available = true;
    setStatus(QStringLiteral("Native renderer ready"));
    emit availableChanged();
}

void MpvItem::setStatus(const QString &status)
{
    if (m_status == status) {
        return;
    }
    m_status = status;
    emit statusChanged();
}

QString MpvItem::propertyString(const QByteArray &name) const
{
    if (!m_mpv || !m_api) {
        return {};
    }
    char *value = m_api->getPropertyString(m_mpv, name.constData());
    if (!value) {
        return {};
    }
    const QString result = QString::fromUtf8(value);
    m_api->freeValue(value);
    return result;
}

QVariantMap MpvItem::trackModel(int index) const
{
    const QByteArray base = QByteArrayLiteral("track-list/")
                            + QByteArray::number(index)
                            + QByteArrayLiteral("/");
    QVariantMap track;
    track.insert(QStringLiteral("id"),
                 propertyString(base + QByteArrayLiteral("id")).toInt());
    track.insert(QStringLiteral("type"),
                 propertyString(base + QByteArrayLiteral("type")));
    track.insert(QStringLiteral("language"),
                 normalizedLanguage(propertyString(base + QByteArrayLiteral("lang"))));
    track.insert(QStringLiteral("title"),
                 propertyString(base + QByteArrayLiteral("title")).trimmed());
    track.insert(QStringLiteral("codec"),
                 propertyString(base + QByteArrayLiteral("codec")).trimmed());
    track.insert(QStringLiteral("channels"),
                 propertyString(base + QByteArrayLiteral("audio-channels")).trimmed());
    track.insert(QStringLiteral("selected"),
                 propertyYes(propertyString(base + QByteArrayLiteral("selected"))));
    track.insert(QStringLiteral("default"),
                 propertyYes(propertyString(base + QByteArrayLiteral("default"))));
    track.insert(QStringLiteral("forced"),
                 propertyYes(propertyString(base + QByteArrayLiteral("forced"))));
    track.insert(QStringLiteral("hearing_impaired"),
                 propertyYes(propertyString(base + QByteArrayLiteral("hearing-impaired"))));
    track.insert(QStringLiteral("fingerprint"), trackFingerprint(track));
    return track;
}

QString MpvItem::trackFingerprint(const QVariantMap &track)
{
    return QStringLiteral("%1|%2|%3|%4|%5")
        .arg(track.value(QStringLiteral("type")).toString(),
             track.value(QStringLiteral("language")).toString(),
             track.value(QStringLiteral("codec")).toString(),
             track.value(QStringLiteral("channels")).toString(),
             track.value(QStringLiteral("title")).toString());
}

void MpvItem::updateTrackModels()
{
    QVariantList audio;
    QVariantList subtitles;
    bool countOk = false;
    const int count = propertyString(QByteArrayLiteral("track-list/count")).toInt(&countOk);
    if (countOk) {
        for (int index = 0; index < std::min(count, 128); ++index) {
            const QVariantMap track = trackModel(index);
            if (track.value(QStringLiteral("type")).toString() == QStringLiteral("audio")) {
                audio.append(track);
            } else if (track.value(QStringLiteral("type")).toString()
                       == QStringLiteral("sub")) {
                subtitles.append(track);
            }
        }
    }
    const bool audioChanged = audio != m_audioTracks;
    const bool subtitlesChanged = subtitles != m_subtitleTracks;
    if (!audioChanged && !subtitlesChanged) {
        return;
    }
    if (audioChanged) {
        m_audioTracks = audio;
        emit audioTracksChanged();
    }
    if (subtitlesChanged) {
        m_subtitleTracks = subtitles;
        emit subtitleTracksChanged();
    }
    emit tracksChanged();
}

void MpvItem::updateChapters()
{
    QVariantList chapters;
    bool countOk = false;
    const int count = propertyString(QByteArrayLiteral("chapter-list/count")).toInt(&countOk);
    if (countOk) {
        for (int index = 0; index < std::min(count, 256); ++index) {
            const QByteArray base = QByteArrayLiteral("chapter-list/")
                                    + QByteArray::number(index)
                                    + QByteArrayLiteral("/");
            QVariantMap chapter;
            chapter.insert(QStringLiteral("title"),
                           propertyString(base + QByteArrayLiteral("title")).trimmed());
            chapter.insert(QStringLiteral("time"),
                           propertyString(base + QByteArrayLiteral("time")).toDouble());
            chapters.append(chapter);
        }
    }
    if (chapters == m_chapters) {
        return;
    }
    m_chapters = chapters;
    emit chaptersChanged();
}

void MpvItem::applyPreferences(const QVariantMap &preferences)
{
    const QStringList audioLanguages =
        preferences.value(QStringLiteral("preferred_audio_languages")).toStringList();
    const QStringList subtitleLanguages =
        preferences.value(QStringLiteral("preferred_subtitle_languages")).toStringList();
    if (!audioLanguages.isEmpty()) {
        sendCommand({
            QByteArrayLiteral("set"),
            QByteArrayLiteral("alang"),
            audioLanguages.join(u',').toUtf8(),
        });
    }
    if (!subtitleLanguages.isEmpty()) {
        sendCommand({
            QByteArrayLiteral("set"),
            QByteArrayLiteral("slang"),
            subtitleLanguages.join(u',').toUtf8(),
        });
    }
    const QString hardware =
        preferences.value(QStringLiteral("hardware_decoding")).toString().trimmed();
    if (!hardware.isEmpty()) {
        const QByteArray value = hardware == QStringLiteral("off")
                                     ? QByteArrayLiteral("no")
                                     : QByteArrayLiteral("auto-safe");
        sendCommand({QByteArrayLiteral("set"), QByteArrayLiteral("hwdec"), value});
    }
}
