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
        if (!item) {
            return;
        }
        QMetaObject::invokeMethod(item, &MpvItem::requestRender, Qt::QueuedConnection);
    }

    void ensureRenderContext()
    {
        if (m_context || !m_api || !m_mpv) {
            return;
        }

        const char *apiType = MPV_RENDER_API_TYPE_OPENGL;
        mpv_opengl_init_params openGlParameters{
            &resolveOpenGlProcedure,
            nullptr,
        };
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
                    emit item->playbackError(message);
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

bool MpvItem::available() const
{
    return m_available;
}

bool MpvItem::paused() const
{
    return m_paused;
}

double MpvItem::position() const
{
    return m_position;
}

double MpvItem::duration() const
{
    return m_duration;
}

double MpvItem::volume() const
{
    return m_volume;
}

QString MpvItem::status() const
{
    return m_status;
}

QStringList MpvItem::audioTracks() const
{
    return m_audioTracks;
}

QStringList MpvItem::subtitleTracks() const
{
    return m_subtitleTracks;
}

bool MpvItem::openLocalFile(const QUrl &url)
{
    if (!m_available || !url.isLocalFile()) {
        setStatus(QStringLiteral("Only an existing local media file can be opened"));
        return false;
    }

    const QString localPath = QFileInfo(url.toLocalFile()).absoluteFilePath();
    if (!QFileInfo::exists(localPath)) {
        setStatus(QStringLiteral("The selected local media file does not exist"));
        return false;
    }

    m_firstFrameNoted = false;
    ++m_loadGeneration;
    m_loadTimer.restart();
    setStatus(QStringLiteral("Loading local media"));
    return sendCommand({
        QByteArrayLiteral("loadfile"),
        QFile::encodeName(localPath),
        QByteArrayLiteral("replace"),
    });
}

bool MpvItem::addExternalSubtitle(const QUrl &url)
{
    if (!m_available || !url.isLocalFile()) {
        return false;
    }

    const QString localPath = QFileInfo(url.toLocalFile()).absoluteFilePath();
    if (!QFileInfo::exists(localPath)) {
        return false;
    }

    return sendCommand({
        QByteArrayLiteral("sub-add"),
        QFile::encodeName(localPath),
        QByteArrayLiteral("select"),
    });
}

void MpvItem::togglePause()
{
    sendCommand({QByteArrayLiteral("cycle"), QByteArrayLiteral("pause")});
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

void MpvItem::cycleAudio()
{
    sendCommand({QByteArrayLiteral("cycle"), QByteArrayLiteral("audio")});
    QTimer::singleShot(100, this, &MpvItem::updateTrackLists);
}

void MpvItem::cycleSubtitle()
{
    sendCommand({QByteArrayLiteral("cycle"), QByteArrayLiteral("sub")});
    QTimer::singleShot(100, this, &MpvItem::updateTrackLists);
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
            updateTrackLists();
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
            } else if (name == QByteArrayLiteral("duration") && property->format == MPV_FORMAT_DOUBLE) {
                m_duration = *static_cast<double *>(property->data);
                emit durationChanged();
            } else if (name == QByteArrayLiteral("volume") && property->format == MPV_FORMAT_DOUBLE) {
                m_volume = *static_cast<double *>(property->data);
                emit volumeChanged();
            } else if (name == QByteArrayLiteral("pause") && property->format == MPV_FORMAT_FLAG) {
                m_paused = *static_cast<int *>(property->data) != 0;
                emit pausedChanged();
            }
            continue;
        }

        if (event->event_id == MPV_EVENT_END_FILE) {
            auto *end = static_cast<mpv_event_end_file *>(event->data);
            if (end && end->error < 0) {
                const QString message = QStringLiteral("Playback failed: %1")
                                            .arg(QString::fromUtf8(m_api->errorText(end->error)));
                setStatus(message);
                emit playbackError(message);
            } else {
                setStatus(QStringLiteral("Playback ended"));
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
    if (!item) {
        return;
    }
    QMetaObject::invokeMethod(item, &MpvItem::processEvents, Qt::QueuedConnection);
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
    emit playbackError(message);
    return false;
}

void MpvItem::initializeMpv()
{
    const QString runtimePath = QCoreApplication::applicationDirPath()
                                + QStringLiteral("/libmpv-2.dll");
    m_api = std::make_unique<MpvApi>(runtimePath);
    if (!m_api->isLoaded()) {
        setStatus(m_api->errorString());
        emit playbackError(m_status);
        return;
    }

    m_mpv = m_api->create();
    if (!m_mpv) {
        setStatus(QStringLiteral("libmpv could not create a playback client"));
        emit playbackError(m_status);
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
    };
    for (const auto &[name, value] : options) {
        const int result = m_api->setOptionString(m_mpv, name.constData(), value.constData());
        if (result < 0) {
            setStatus(QStringLiteral("libmpv rejected required option: %1")
                          .arg(QString::fromLatin1(name)));
            emit playbackError(m_status);
            return;
        }
    }

    const int initialized = m_api->initialize(m_mpv);
    if (initialized < 0) {
        setStatus(QStringLiteral("libmpv initialization failed: %1")
                      .arg(QString::fromUtf8(m_api->errorText(initialized))));
        emit playbackError(m_status);
        return;
    }

    m_api->observeProperty(m_mpv, 1, "time-pos", MPV_FORMAT_DOUBLE);
    m_api->observeProperty(m_mpv, 2, "duration", MPV_FORMAT_DOUBLE);
    m_api->observeProperty(m_mpv, 3, "pause", MPV_FORMAT_FLAG);
    m_api->observeProperty(m_mpv, 4, "volume", MPV_FORMAT_DOUBLE);
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

void MpvItem::updateTrackLists()
{
    QStringList audioTracks;
    QStringList subtitleTracks;
    bool countOk = false;
    const int count = propertyString(QByteArrayLiteral("track-list/count")).toInt(&countOk);
    if (countOk) {
        for (int index = 0; index < count; ++index) {
            const QByteArray base = QByteArrayLiteral("track-list/")
                                    + QByteArray::number(index)
                                    + QByteArrayLiteral("/");
            const QString type = propertyString(base + QByteArrayLiteral("type"));
            if (type == QStringLiteral("audio")) {
                audioTracks.append(trackLabel(index));
            } else if (type == QStringLiteral("sub")) {
                subtitleTracks.append(trackLabel(index));
            }
        }
    }

    if (audioTracks == m_audioTracks && subtitleTracks == m_subtitleTracks) {
        return;
    }
    m_audioTracks = audioTracks;
    m_subtitleTracks = subtitleTracks;
    emit tracksChanged();
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

QString MpvItem::trackLabel(int index) const
{
    const QByteArray base = QByteArrayLiteral("track-list/")
                            + QByteArray::number(index)
                            + QByteArrayLiteral("/");
    const QString id = propertyString(base + QByteArrayLiteral("id"));
    QString language = propertyString(base + QByteArrayLiteral("lang"));
    QString codec = propertyString(base + QByteArrayLiteral("codec"));
    const bool selected = propertyString(base + QByteArrayLiteral("selected"))
                              == QStringLiteral("yes");

    if (language.isEmpty()) {
        language = QStringLiteral("und");
    }
    if (codec.isEmpty()) {
        codec = QStringLiteral("unknown");
    }

    QString label = QStringLiteral("%1 | %2 | %3").arg(id, language, codec);
    if (selected) {
        label += QStringLiteral(" | selected");
    }
    return label;
}
