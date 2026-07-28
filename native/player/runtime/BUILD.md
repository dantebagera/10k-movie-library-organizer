# Production native-player runtime

The accepted decoder/rendering dependency lock remains
`native/player-spike/runtime-lock.json`; its exact LGPL patch is
`native/player-spike/runtime/mpv-winbuild-cmake-lgpl.patch`. Those files record
the accepted Qt, mpv, FFmpeg, compiler, source revisions, build flags, and
`libmpv-2.dll` SHA-256. Do not replace any input with an unspecified latest
build.

The production runtime assembly is deliberately separate from the portable
application builder:

1. Build `native/player` with the pinned Qt 6.10.3 MSVC 2022 x64 toolchain and
   the accepted `libmpv-2.dll`.
2. Run `windeployqt` against `cp-player.exe`, including the QML directory.
3. Add the generated player assets and a `licenses` directory containing the
   exact files declared in `native/player/runtime-metadata.json`, plus
   `licenses/RELINKING.md` and the complete third-party notices/source offer.
4. Assemble the immutable version directory:

   ```powershell
   .\.venv\Scripts\python.exe tools\assemble_player_runtime.py `
     --staged-runtime <windeployqt-stage> `
     --output-root runtime\player
   ```

5. Build the portable release. `tools/build_portable_release.py` revalidates
   every declared SHA-256 hash and license path before copying only the
   manifest inventory.

Assembly rejects debug symbols, logs, app configuration, catalog data, history,
provider registries, caches, and any staged file not selected by the runtime
policy. Existing version directories are immutable; use a new bundle version
instead of overwriting one.
