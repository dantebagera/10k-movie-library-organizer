#include "MpvItem.h"
#include "PlayerBridge.h"

#include <QGuiApplication>
#include <QColor>
#include <QIcon>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickWindow>
#include <QSGRendererInterface>
#include <QTimer>

#ifdef Q_OS_WIN
#include <dwmapi.h>
#include <qt_windows.h>

namespace {

COLORREF windowsColor(const QColor &color)
{
    return RGB(color.red(), color.green(), color.blue());
}

void applyWindowsCaptionTheme(QQuickWindow *window)
{
    if (!window) {
        return;
    }
    const HWND handle = reinterpret_cast<HWND>(window->winId());
    if (!handle) {
        return;
    }

    const BOOL darkCaption = TRUE;
    DwmSetWindowAttribute(
        handle,
        DWMWA_USE_IMMERSIVE_DARK_MODE,
        &darkCaption,
        sizeof(darkCaption));

    const COLORREF caption = windowsColor(
        window->property("nativeCaptionColor").value<QColor>());
    const COLORREF text = windowsColor(
        window->property("nativeCaptionTextColor").value<QColor>());
    const COLORREF border = windowsColor(
        window->property("nativeCaptionBorderColor").value<QColor>());
    DwmSetWindowAttribute(handle, DWMWA_CAPTION_COLOR, &caption, sizeof(caption));
    DwmSetWindowAttribute(handle, DWMWA_TEXT_COLOR, &text, sizeof(text));
    DwmSetWindowAttribute(handle, DWMWA_BORDER_COLOR, &border, sizeof(border));
}

}
#endif

int main(int argc, char *argv[])
{
    QQuickWindow::setGraphicsApi(QSGRendererInterface::OpenGL);
    QGuiApplication application(argc, argv);
    application.setApplicationName(QStringLiteral("Cinema Paradiso Player"));
    application.setOrganizationName(QStringLiteral("Cinema Paradiso"));
    application.setWindowIcon(
        QIcon(QStringLiteral(":/branding/cp-player.png")));
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

#ifdef Q_OS_WIN
    applyWindowsCaptionTheme(qobject_cast<QQuickWindow *>(root));
#endif

    bridge.attachPlayer(player);
    QObject::connect(&bridge, &PlayerBridge::closeWindowRequested,
                     &application, &QCoreApplication::quit);
    QTimer::singleShot(0, &bridge, &PlayerBridge::connectToBackend);
    return application.exec();
}
