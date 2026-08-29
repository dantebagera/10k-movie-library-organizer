cmake_minimum_required(VERSION 3.24)

project(cp_player VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 6.10 REQUIRED COMPONENTS
    Core
    Gui
    Network
    OpenGL
    Qml
    Quick
    QuickControls2
)

if(NOT DEFINED MPV_ROOT)
    message(FATAL_ERROR "MPV_ROOT must point to the pinned libmpv development bundle")
endif()

set(MPV_INCLUDE_DIR "${MPV_ROOT}/include")
set(MPV_RUNTIME_DLL "${MPV_ROOT}/libmpv-2.dll")

if(NOT EXISTS "${MPV_INCLUDE_DIR}/mpv/client.h")
    message(FATAL_ERROR "Missing libmpv headers under MPV_ROOT: ${MPV_INCLUDE_DIR}")
endif()
if(NOT EXISTS "${MPV_RUNTIME_DLL}")
    message(FATAL_ERROR "Missing pinned libmpv runtime: ${MPV_RUNTIME_DLL}")
endif()

qt_standard_project_setup(REQUIRES 6.10)

qt_add_executable(cp-player WIN32
    resources/cp-player.rc
    src/main.cpp
    src/MpvApi.cpp
    src/MpvApi.h
    src/MpvItem.cpp
    src/MpvItem.h
    src/PlayerBridge.cpp
    src/PlayerBridge.h
    src/WindowsWindowChrome.cpp
    src/WindowsWindowChrome.h
)

set_source_files_properties(qml/PlayerTheme.qml PROPERTIES
    QT_QML_SINGLETON_TYPE TRUE
)

qt_add_qml_module(cp-player
    URI CinemaParadiso.Player
    VERSION 1.0
    QML_FILES
        qml/Main.qml
        qml/PlayerTheme.qml
)

set(CP_PLAYER_ICON_PNG
    "${CMAKE_CURRENT_SOURCE_DIR}/resources/cp-player-icon.png"
)
set_source_files_properties("${CP_PLAYER_ICON_PNG}" PROPERTIES
    QT_RESOURCE_ALIAS "cp-player.png"
)
qt_add_resources(cp-player "cp_player_branding"
    PREFIX "/branding"
    FILES "${CP_PLAYER_ICON_PNG}"
)

set(CP_PLAYER_CONTROL_ICONS
    resources/icons/audio-tracks.svg
    resources/icons/enter-fullscreen.svg
    resources/icons/exit-fullscreen.svg
    resources/icons/forward-10.svg
    resources/icons/pause.svg
    resources/icons/play.svg
    resources/icons/rewind-10.svg
    resources/icons/search.svg
    resources/icons/speed.svg
    resources/icons/subtitles.svg
    resources/icons/download.svg
    resources/icons/volume-high.svg
    resources/icons/volume-muted.svg
    resources/icons/window-close.svg
    resources/icons/window-maximize.svg
    resources/icons/window-minimize.svg
    resources/icons/window-restore.svg
)
foreach(CP_PLAYER_CONTROL_ICON IN LISTS CP_PLAYER_CONTROL_ICONS)
    get_filename_component(CP_PLAYER_CONTROL_ICON_NAME
        "${CP_PLAYER_CONTROL_ICON}" NAME
    )
    set_source_files_properties("${CP_PLAYER_CONTROL_ICON}" PROPERTIES
        QT_RESOURCE_ALIAS "${CP_PLAYER_CONTROL_ICON_NAME}"
    )
endforeach()
qt_add_resources(cp-player "cp_player_control_icons"
    PREFIX "/icons"
    FILES ${CP_PLAYER_CONTROL_ICONS}
)

target_include_directories(cp-player PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/resources"
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${MPV_INCLUDE_DIR}"
)

target_link_libraries(cp-player PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::Network
    Qt6::OpenGL
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
)

if(WIN32)
    target_link_libraries(cp-player PRIVATE dwmapi)
endif()

target_compile_definitions(cp-player PRIVATE
    QT_NO_CAST_FROM_ASCII
    QT_NO_CAST_TO_ASCII
)

add_custom_command(TARGET cp-player POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${MPV_RUNTIME_DLL}"
        "$<TARGET_FILE_DIR:cp-player>/libmpv-2.dll"
    VERBATIM
)
