#include "MpvItem.h"
#include "PlayerBridge.h"

#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QSGRendererInterface>
#include <QTimer>

int main(int argc, char *argv[])
{
    QQuickWindow::setGraphicsApi(QSGRendererInterface::OpenGL);
    QGuiApplication application(argc, argv);
    application.setApplicationName(QStringLiteral("Cinema Paradiso Player"));
    application.setOrganizationName(QStringLiteral("Cinema Paradiso"));
    application.setQuitOnLastWindowClosed(true);

    PlayerBridge bridge;
    if (!bridge.configurationValid()) {
        return 2;
    }

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("playerBridge"), &bridge);
    engine.loadFromModule(QStringLiteral("CinemaParadiso.Player"), QStringLiteral("Main"));
    if (engine.rootObjects().isEmpty()) {
        return 3;
    }

    QObject *root = engine.rootObjects().constFirst();
    auto *player = root->findChild<MpvItem *>(QStringLiteral("mpvItem"));
    if (!player || !player->available()) {
        return 4;
    }

    bridge.attachPlayer(player);
    QObject::connect(&bridge, &PlayerBridge::closeWindowRequested,
                     &application, &QCoreApplication::quit);
    QTimer::singleShot(0, &bridge, &PlayerBridge::connectToBackend);
    return application.exec();
}
