#include "WindowsWindowChrome.h"

#include <QCoreApplication>
#include <QQuickWindow>
#include <QWindow>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <algorithm>
#include <dwmapi.h>
#include <qt_windows.h>
#include <windowsx.h>

namespace {

constexpr int LogicalResizeBorder = 8;
constexpr int LogicalDragHeight = 54;
constexpr int LogicalControlExclusionWidth = 156;

int scaledPixels(HWND handle, int logicalPixels)
{
    const UINT dpi = GetDpiForWindow(handle);
    return std::max(1, MulDiv(logicalPixels, dpi ? static_cast<int>(dpi) : 96, 96));
}

void configureFramelessStyle(HWND handle)
{
    LONG_PTR style = GetWindowLongPtrW(handle, GWL_STYLE);
    style &= ~static_cast<LONG_PTR>(WS_CAPTION);
    style |= WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU;
    SetWindowLongPtrW(handle, GWL_STYLE, style);

    const BOOL darkMode = TRUE;
    DwmSetWindowAttribute(
        handle,
        DWMWA_USE_IMMERSIVE_DARK_MODE,
        &darkMode,
        sizeof(darkMode));

    constexpr COLORREF noBorder = 0xFFFFFFFE;
    DwmSetWindowAttribute(
        handle,
        DWMWA_BORDER_COLOR,
        &noBorder,
        sizeof(noBorder));

    SetWindowPos(
        handle,
        nullptr,
        0,
        0,
        0,
        0,
        SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
            | SWP_NOACTIVATE);
}

}
#endif

WindowsWindowChrome::WindowsWindowChrome(QObject *parent)
    : QObject(parent)
{
}

WindowsWindowChrome::~WindowsWindowChrome()
{
    if (m_filterInstalled && QCoreApplication::instance()) {
        QCoreApplication::instance()->removeNativeEventFilter(this);
    }
}

void WindowsWindowChrome::attach(QQuickWindow *window)
{
    m_window = window;
    if (!m_window) {
        return;
    }
    if (!m_filterInstalled && QCoreApplication::instance()) {
        QCoreApplication::instance()->installNativeEventFilter(this);
        m_filterInstalled = true;
    }
#ifdef Q_OS_WIN
    const HWND handle = reinterpret_cast<HWND>(m_window->winId());
    if (handle) {
        m_nativeHandle = reinterpret_cast<quintptr>(handle);
        configureFramelessStyle(handle);
    }
#endif
}

int WindowsWindowChrome::dragHeight() const
{
    return 54;
}

int WindowsWindowChrome::controlExclusionWidth() const
{
    return 156;
}

void WindowsWindowChrome::minimize()
{
    if (m_window) {
        m_window->showMinimized();
    }
}

void WindowsWindowChrome::toggleMaximized()
{
    if (!m_window) {
        return;
    }
    if (m_window->visibility() == QWindow::Maximized) {
        m_window->showNormal();
    } else {
        m_window->showMaximized();
    }
}

void WindowsWindowChrome::closeWindow()
{
    if (m_window) {
        m_window->close();
    }
}

bool WindowsWindowChrome::nativeEventFilter(
    const QByteArray &eventType,
    void *message,
    qintptr *result)
{
#ifdef Q_OS_WIN
    if (!m_window || (eventType != QByteArrayLiteral("windows_generic_MSG")
                      && eventType != QByteArrayLiteral("windows_dispatcher_MSG"))) {
        return false;
    }
    auto *nativeMessage = static_cast<MSG *>(message);
    const HWND handle = reinterpret_cast<HWND>(m_nativeHandle);
    if (!nativeMessage || nativeMessage->hwnd != handle) {
        return false;
    }
    if (nativeMessage->message == WM_NCDESTROY) {
        m_nativeHandle = 0;
        return false;
    }

    if (nativeMessage->message == WM_APPCOMMAND
        && GET_APPCOMMAND_LPARAM(nativeMessage->lParam)
               == APPCOMMAND_MEDIA_PLAY_PAUSE) {
        emit mediaPlayPauseRequested();
        *result = 1;
        return true;
    }

    if (nativeMessage->message == WM_NCCALCSIZE && nativeMessage->wParam) {
        *result = 0;
        return true;
    }

    if (nativeMessage->message == WM_GETMINMAXINFO) {
        auto *minimumMaximum = reinterpret_cast<MINMAXINFO *>(nativeMessage->lParam);
        const HMONITOR monitor = MonitorFromWindow(handle, MONITOR_DEFAULTTONEAREST);
        MONITORINFO information{sizeof(MONITORINFO)};
        if (minimumMaximum && GetMonitorInfoW(monitor, &information)) {
            minimumMaximum->ptMaxPosition.x =
                information.rcWork.left - information.rcMonitor.left;
            minimumMaximum->ptMaxPosition.y =
                information.rcWork.top - information.rcMonitor.top;
            minimumMaximum->ptMaxSize.x =
                information.rcWork.right - information.rcWork.left;
            minimumMaximum->ptMaxSize.y =
                information.rcWork.bottom - information.rcWork.top;
            *result = 0;
            return true;
        }
    }

    if (nativeMessage->message != WM_NCHITTEST) {
        return false;
    }

    if (m_window->visibility() == QWindow::FullScreen) {
        *result = HTCLIENT;
        return true;
    }

    RECT windowRectangle{};
    if (!GetWindowRect(handle, &windowRectangle)) {
        return false;
    }
    const POINT cursor{
        GET_X_LPARAM(nativeMessage->lParam),
        GET_Y_LPARAM(nativeMessage->lParam),
    };
    const int resizeBorder = scaledPixels(handle, LogicalResizeBorder);
    const bool maximized = IsZoomed(handle) != FALSE;
    const bool left = !maximized
        && cursor.x >= windowRectangle.left
        && cursor.x < windowRectangle.left + resizeBorder;
    const bool right = !maximized
        && cursor.x < windowRectangle.right
        && cursor.x >= windowRectangle.right - resizeBorder;
    const bool top = !maximized
        && cursor.y >= windowRectangle.top
        && cursor.y < windowRectangle.top + resizeBorder;
    const bool bottom = !maximized
        && cursor.y < windowRectangle.bottom
        && cursor.y >= windowRectangle.bottom - resizeBorder;

    if (top && left) { *result = HTTOPLEFT; return true; }
    if (top && right) { *result = HTTOPRIGHT; return true; }
    if (bottom && left) { *result = HTBOTTOMLEFT; return true; }
    if (bottom && right) { *result = HTBOTTOMRIGHT; return true; }
    if (left) { *result = HTLEFT; return true; }
    if (right) { *result = HTRIGHT; return true; }
    if (top) { *result = HTTOP; return true; }
    if (bottom) { *result = HTBOTTOM; return true; }

    const int dragHeight = scaledPixels(handle, LogicalDragHeight);
    const int controlsWidth = scaledPixels(handle, LogicalControlExclusionWidth);
    const bool overControls = cursor.x >= windowRectangle.right - controlsWidth
        && cursor.y < windowRectangle.top + dragHeight;
    if (!overControls && cursor.y < windowRectangle.top + dragHeight) {
        *result = HTCAPTION;
        return true;
    }
    *result = HTCLIENT;
    return true;
#else
    Q_UNUSED(eventType)
    Q_UNUSED(message)
    Q_UNUSED(result)
    return false;
#endif
}
