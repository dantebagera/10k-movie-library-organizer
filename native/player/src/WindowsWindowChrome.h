#pragma once

#include <QAbstractNativeEventFilter>
#include <QObject>
#include <QPointer>

class QQuickWindow;

class WindowsWindowChrome final : public QObject,
                                  public QAbstractNativeEventFilter
{
    Q_OBJECT
    Q_PROPERTY(int dragHeight READ dragHeight CONSTANT)
    Q_PROPERTY(int controlExclusionWidth READ controlExclusionWidth CONSTANT)

public:
    explicit WindowsWindowChrome(QObject *parent = nullptr);
    ~WindowsWindowChrome() override;

    void attach(QQuickWindow *window);
    int dragHeight() const;
    int controlExclusionWidth() const;

    Q_INVOKABLE void minimize();
    Q_INVOKABLE void toggleMaximized();
    Q_INVOKABLE void closeWindow();

    bool nativeEventFilter(const QByteArray &eventType, void *message,
                           qintptr *result) override;

signals:
    void mediaPlayPauseRequested();

private:
    QPointer<QQuickWindow> m_window;
    quintptr m_nativeHandle = 0;
    bool m_filterInstalled = false;
};
