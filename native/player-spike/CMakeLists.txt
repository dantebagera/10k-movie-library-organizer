cmake_minimum_required(VERSION 3.24)

project(cp_player_spike VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 6.10 REQUIRED COMPONENTS Core Gui OpenGL Qml Quick QuickControls2)

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

qt_add_executable(cp-player-spike
    src/main.cpp
    src/MpvApi.cpp
    src/MpvApi.h
    src/MpvItem.cpp
    src/MpvItem.h
)

qt_add_qml_module(cp-player-spike
    URI CinemaParadiso.PlayerSpike
    VERSION 1.0
    QML_FILES
        qml/Main.qml
)

target_include_directories(cp-player-spike PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src"
    "${MPV_INCLUDE_DIR}"
)

target_link_libraries(cp-player-spike PRIVATE
    Qt6::Core
    Qt6::Gui
    Qt6::OpenGL
    Qt6::Qml
    Qt6::Quick
    Qt6::QuickControls2
)

target_compile_definitions(cp-player-spike PRIVATE
    QT_NO_CAST_FROM_ASCII
    QT_NO_CAST_TO_ASCII
)

add_custom_command(TARGET cp-player-spike POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${MPV_RUNTIME_DLL}"
        "$<TARGET_FILE_DIR:cp-player-spike>/libmpv-2.dll"
    VERBATIM
)
