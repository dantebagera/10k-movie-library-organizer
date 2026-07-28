#pragma once

#include <QLibrary>
#include <QString>

#include <mpv/client.h>
#include <mpv/render_gl.h>

class MpvApi final
{
public:
    explicit MpvApi(const QString &libraryPath);

    bool isLoaded() const;
    QString errorString() const;

    decltype(&mpv_create) create = nullptr;
    decltype(&mpv_initialize) initialize = nullptr;
    decltype(&mpv_terminate_destroy) terminateDestroy = nullptr;
    decltype(&mpv_set_option_string) setOptionString = nullptr;
    decltype(&mpv_command) command = nullptr;
    decltype(&mpv_observe_property) observeProperty = nullptr;
    decltype(&mpv_wait_event) waitEvent = nullptr;
    decltype(&mpv_set_wakeup_callback) setWakeupCallback = nullptr;
    decltype(&mpv_get_property_string) getPropertyString = nullptr;
    decltype(&mpv_free) freeValue = nullptr;
    decltype(&mpv_error_string) errorText = nullptr;
    decltype(&mpv_render_context_create) renderContextCreate = nullptr;
    decltype(&mpv_render_context_free) renderContextFree = nullptr;
    decltype(&mpv_render_context_render) renderContextRender = nullptr;
    decltype(&mpv_render_context_set_update_callback) renderContextSetUpdateCallback = nullptr;

private:
    template<typename T>
    bool resolve(T &target, const char *symbol);

    QLibrary m_library;
    QString m_error;
};
