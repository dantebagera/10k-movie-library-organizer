#include "MpvApi.h"

template<typename T>
bool MpvApi::resolve(T &target, const char *symbol)
{
    target = reinterpret_cast<T>(m_library.resolve(symbol));
    if (target) {
        return true;
    }
    m_error = QStringLiteral("Pinned libmpv is missing a required symbol: %1")
                  .arg(QString::fromLatin1(symbol));
    return false;
}

MpvApi::MpvApi(const QString &libraryPath)
    : m_library(libraryPath)
{
    m_library.setLoadHints(QLibrary::ResolveAllSymbolsHint);
    if (!m_library.load()) {
        m_error = QStringLiteral("Unable to load the pinned libmpv runtime");
        return;
    }

    const bool complete =
        resolve(create, "mpv_create")
        && resolve(initialize, "mpv_initialize")
        && resolve(terminateDestroy, "mpv_terminate_destroy")
        && resolve(setOptionString, "mpv_set_option_string")
        && resolve(command, "mpv_command")
        && resolve(commandAsync, "mpv_command_async")
        && resolve(observeProperty, "mpv_observe_property")
        && resolve(waitEvent, "mpv_wait_event")
        && resolve(setWakeupCallback, "mpv_set_wakeup_callback")
        && resolve(getPropertyString, "mpv_get_property_string")
        && resolve(freeValue, "mpv_free")
        && resolve(errorText, "mpv_error_string")
        && resolve(renderContextCreate, "mpv_render_context_create")
        && resolve(renderContextFree, "mpv_render_context_free")
        && resolve(renderContextRender, "mpv_render_context_render")
        && resolve(renderContextSetUpdateCallback, "mpv_render_context_set_update_callback");
    if (!complete) {
        m_library.unload();
    }
}

bool MpvApi::isLoaded() const
{
    return m_library.isLoaded() && m_error.isEmpty();
}

QString MpvApi::errorString() const
{
    return m_error;
}
