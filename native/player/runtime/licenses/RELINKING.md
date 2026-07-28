# Relinking the Cinema Paradiso Player

The bundled `cp-player.exe` dynamically links to Qt and `libmpv`. The runtime
keeps those libraries as separate DLL files so a recipient can replace them
with a compatible, modified build.

To relink or replace the libraries:

1. Build Cinema Paradiso Player from the corresponding application source with
   CMake, MSVC 2022 x64, and the Qt and mpv revisions recorded in
   `cinema-paradiso-player.json`.
2. Keep the Qt and mpv libraries dynamically linked.
3. Replace the applicable DLLs and plugin/QML module directories in the
   versioned runtime.
4. Regenerate the runtime manifest and SHA-256 inventory with
   `tools/assemble_player_runtime.py`.

Modified libraries must remain ABI-compatible with the helper. The upstream
source locations, revisions, and build flags required to reproduce the shipped
runtime are recorded in the same manifest.
