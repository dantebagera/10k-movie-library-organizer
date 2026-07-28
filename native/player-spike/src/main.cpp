#include "MpvItem.h"

#include <QCommandLineOption>
#include <QCommandLineParser>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QQmlApplicationEngine>
#include <QQuickWindow>
#include <QQuickStyle>
#include <QSaveFile>
#include <QScreen>
#include <QTimer>

#include <algorithm>
#include <cmath>
#include <memory>

namespace {

QJsonObject readJsonObject(const QString &path, QString *error)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        *error = QStringLiteral("Unable to read scenario file");
        return {};
    }

    QJsonParseError parseError;
    const QJsonDocument document = QJsonDocument::fromJson(file.readAll(), &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject()) {
        *error = QStringLiteral("Scenario is not a valid JSON object");
        return {};
    }
    return document.object();
}

bool writeJsonObject(const QString &path, const QJsonObject &object)
{
    if (path.isEmpty()) {
        return true;
    }
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly)) {
        return false;
    }
    file.write(QJsonDocument(object).toJson(QJsonDocument::Indented));
    return file.commit();
}

QJsonArray stringsToJson(const QStringList &values)
{
    QJsonArray result;
    for (const QString &value : values) {
        result.append(value);
    }
    return result;
}

} // namespace

int main(int argc, char *argv[])
{
    QQuickWindow::setGraphicsApi(QSGRendererInterface::OpenGL);

    QGuiApplication application(argc, argv);
    QElapsedTimer processTimer;
    processTimer.start();
    QQuickStyle::setStyle(QStringLiteral("Fusion"));
    QCoreApplication::setApplicationName(QStringLiteral("Cinema Paradiso Player Spike"));
    QCoreApplication::setApplicationVersion(QStringLiteral("0.1.0"));

    QCommandLineParser parser;
    parser.setApplicationDescription(
        QStringLiteral("Throwaway Qt Quick/libmpv rendering proof for Cinema Paradiso"));
    parser.addHelpOption();
    parser.addVersionOption();
    const QCommandLineOption scenarioOption(
        QStringList{QStringLiteral("scenario")},
        QStringLiteral("Read automation instructions from a JSON file; media paths never enter process arguments."),
        QStringLiteral("json-file"));
    const QCommandLineOption reportOption(
        QStringList{QStringLiteral("report")},
        QStringLiteral("Write redacted runtime evidence to a JSON file."),
        QStringLiteral("json-file"));
    parser.addOption(scenarioOption);
    parser.addOption(reportOption);
    parser.process(application);

    const QString scenarioPath = parser.value(scenarioOption);
    const QString reportPath = parser.value(reportOption);
    QString scenarioError;
    QJsonObject scenario;
    if (!scenarioPath.isEmpty()) {
        scenario = readJsonObject(QFileInfo(scenarioPath).absoluteFilePath(), &scenarioError);
        if (!scenarioError.isEmpty()) {
            qCritical("%s", qUtf8Printable(scenarioError));
            return 2;
        }
    }

    QQmlApplicationEngine engine;
    engine.loadFromModule(QStringLiteral("CinemaParadiso.PlayerSpike"), QStringLiteral("Main"));
    if (engine.rootObjects().isEmpty()) {
        return 3;
    }

    auto *window = qobject_cast<QQuickWindow *>(engine.rootObjects().constFirst());
    auto *player = window ? window->findChild<MpvItem *>(QStringLiteral("mpvItem")) : nullptr;
    if (!window || !player) {
        qCritical("The spike QML shell did not expose its authoritative MpvItem");
        return 4;
    }

    QObject::connect(window, &QQuickWindow::sceneGraphInvalidated,
                     player, &MpvItem::shutdownPlayback, Qt::QueuedConnection);

    auto report = std::make_shared<QJsonObject>();
    report->insert(QStringLiteral("schema"), QStringLiteral("cp-player-phase0-report-v1"));
    report->insert(QStringLiteral("qt_version"), QString::fromLatin1(qVersion()));
    report->insert(QStringLiteral("render_api"), QStringLiteral("OpenGL/libmpv-render"));
    report->insert(QStringLiteral("libmpv_available"), player->available());
    report->insert(QStringLiteral("media_id"),
                   scenario.value(QStringLiteral("mediaId")).toString(QStringLiteral("manual")));
    report->insert(QStringLiteral("file_loaded"), false);
    report->insert(QStringLiteral("first_frame_rendered"), false);
    report->insert(QStringLiteral("seek_requested"), false);
    report->insert(QStringLiteral("seek_observed"), false);
    report->insert(QStringLiteral("fullscreen_entered"), false);
    report->insert(QStringLiteral("fullscreen_exited"), false);
    report->insert(QStringLiteral("resize_applied"), false);
    report->insert(QStringLiteral("screenshot_saved"), false);
    report->insert(QStringLiteral("errors"), QJsonArray{});

    QObject::connect(player, &MpvItem::playbackError, &application,
                     [report](const QString &message) {
                         QJsonArray errors = report->value(QStringLiteral("errors")).toArray();
                         errors.append(message);
                         report->insert(QStringLiteral("errors"), errors);
                     });

    QObject::connect(player, &MpvItem::tracksChanged, &application,
                     [player, report]() {
                         report->insert(QStringLiteral("audio_tracks"),
                                        stringsToJson(player->audioTracks()));
                         report->insert(QStringLiteral("subtitle_tracks"),
                                        stringsToJson(player->subtitleTracks()));
                     });

    QObject::connect(player, &MpvItem::durationChanged, &application,
                     [player, report]() {
                         report->insert(QStringLiteral("duration_seconds"), player->duration());
                     });

    QObject::connect(player, &MpvItem::firstFrameRendered, &application,
                     [report](qint64 milliseconds) {
                         report->insert(QStringLiteral("first_frame_rendered"), true);
                         report->insert(QStringLiteral("first_frame_ms"), milliseconds);
                     });

    const double seekSeconds = scenario.value(QStringLiteral("seekSeconds")).toDouble(-1.0);
    QObject::connect(player, &MpvItem::positionChanged, &application,
                     [player, report, seekSeconds]() {
                         report->insert(QStringLiteral("last_position_seconds"), player->position());
                         if (seekSeconds >= 0.0
                             && std::abs(player->position() - seekSeconds) <= 1.5) {
                             report->insert(QStringLiteral("seek_observed"), true);
                         }
                     });

    QObject::connect(player, &MpvItem::fileLoaded, &application,
                     [window, player, report, scenario, seekSeconds, processTimer]() mutable {
                         report->insert(QStringLiteral("file_loaded"), true);
                         report->insert(QStringLiteral("process_to_file_loaded_ms"),
                                        processTimer.elapsed());
                         report->insert(QStringLiteral("duration_seconds"), player->duration());
                         report->insert(QStringLiteral("audio_tracks"),
                                        stringsToJson(player->audioTracks()));
                         report->insert(QStringLiteral("subtitle_tracks"),
                                        stringsToJson(player->subtitleTracks()));

                         const QString subtitlePath =
                             scenario.value(QStringLiteral("externalSubtitlePath")).toString();
                         if (!subtitlePath.isEmpty() && QFileInfo::exists(subtitlePath)) {
                             QTimer::singleShot(100, player, [player, subtitlePath, report]() {
                                 report->insert(
                                     QStringLiteral("external_subtitle_added"),
                                     player->addExternalSubtitle(QUrl::fromLocalFile(subtitlePath)));
                             });
                         }

                         if (seekSeconds >= 0.0) {
                             QTimer::singleShot(300, player, [player, seekSeconds, report]() {
                                 report->insert(QStringLiteral("seek_requested"), true);
                                 player->seekAbsolute(seekSeconds);
                             });
                         }

                         if (scenario.value(QStringLiteral("cycleAudio")).toBool()) {
                             QTimer::singleShot(550, player, [player, report]() {
                                 player->cycleAudio();
                                 report->insert(QStringLiteral("audio_cycle_sent"), true);
                             });
                         }
                         if (scenario.value(QStringLiteral("cycleSubtitle")).toBool()) {
                             QTimer::singleShot(800, player, [player, report]() {
                                 player->cycleSubtitle();
                                 report->insert(QStringLiteral("subtitle_cycle_sent"), true);
                             });
                         }

                         const int width = scenario.value(QStringLiteral("targetWidth")).toInt();
                         const int height = scenario.value(QStringLiteral("targetHeight")).toInt();
                         if (width >= 640 && height >= 360) {
                             window->resize(width, height);
                             report->insert(QStringLiteral("resize_applied"), true);
                             report->insert(QStringLiteral("window_width"), width);
                             report->insert(QStringLiteral("window_height"), height);
                         }

                         if (scenario.value(QStringLiteral("toggleFullscreen")).toBool()) {
                             QTimer::singleShot(1050, window, [window, report]() {
                                 window->showFullScreen();
                                 report->insert(QStringLiteral("fullscreen_entered"),
                                                window->visibility() == QWindow::FullScreen);
                             });
                             QTimer::singleShot(1550, window, [window, report]() {
                                 window->showNormal();
                                 report->insert(QStringLiteral("fullscreen_exited"),
                                                window->visibility() != QWindow::FullScreen);
                             });
                         }

                         const QString screenshotPath =
                             scenario.value(QStringLiteral("screenshotPath")).toString();
                         if (!screenshotPath.isEmpty()) {
                             QTimer::singleShot(1900, window, [window, screenshotPath, report]() {
                                 report->insert(QStringLiteral("screenshot_saved"),
                                                window->grabWindow().save(screenshotPath));
                             });
                         }
                     });

    window->show();
    QTimer::singleShot(0, &application, [window, report]() {
        report->insert(QStringLiteral("device_pixel_ratio"), window->devicePixelRatio());
        if (window->screen()) {
            report->insert(QStringLiteral("logical_dpi"), window->screen()->logicalDotsPerInch());
        }
    });

    if (!scenario.isEmpty()) {
        application.setQuitOnLastWindowClosed(false);
        const QString mediaPath = scenario.value(QStringLiteral("mediaPath")).toString();
        if (mediaPath.isEmpty() || !QFileInfo::exists(mediaPath)) {
            qCritical("Scenario media is missing or does not exist");
            return 5;
        }
        if (player->available()) {
            QTimer::singleShot(0, player, [player, mediaPath]() {
                player->openLocalFile(QUrl::fromLocalFile(mediaPath));
            });
        } else {
            report->insert(QStringLiteral("runtime_fallback_visible"), true);
        }

        const int requestedRuntime = scenario.value(QStringLiteral("runtimeMs")).toInt(5000);
        const int runtime = std::clamp(requestedRuntime, 3000, 30000);
        QTimer::singleShot(runtime, window, [window]() {
            window->releaseResources();
            window->close();
            QTimer::singleShot(500, QCoreApplication::instance(), &QCoreApplication::quit);
        });
    }

    QObject::connect(&application, &QCoreApplication::aboutToQuit, &application,
                     [window, player, report, reportPath, processTimer]() {
                         report->insert(QStringLiteral("process_runtime_ms"),
                                        processTimer.elapsed());
                         report->insert(
                             QStringLiteral("final_status"),
                             player->available()
                                 ? player->status()
                                 : QStringLiteral("Native runtime unavailable"));
                         report->insert(QStringLiteral("final_position_seconds"),
                                        player->position());
                         report->insert(QStringLiteral("device_pixel_ratio"),
                                        window->devicePixelRatio());
                         if (!writeJsonObject(reportPath, *report)) {
                             qWarning("Unable to write the requested redacted report");
                         }
                     });

    return application.exec();
}
