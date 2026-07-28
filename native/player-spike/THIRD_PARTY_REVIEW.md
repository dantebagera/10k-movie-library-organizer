# Phase 0 third-party review

This directory is an isolated rendering and packaging proof. Its runtime
architecture and LGPL libmpv candidate are accepted for implementation, but
this spike package is not itself a production distribution.

## Qt 6.10.3

The spike uses official Qt 6.10.3 MSVC 2022 x64 binary packages installed with
`aqtinstall` archive verification. The selected Qt modules are dynamically
linked.

Production distribution must:

- enumerate every deployed Qt module and its applicable license;
- include complete notices and license texts;
- provide required corresponding source or a valid written offer;
- preserve the user's ability to replace or relink LGPL libraries;
- verify that no GPL-only Qt module enters the deployment.

References:

- https://doc.qt.io/qt-6/licensing.html
- https://www.qt.io/development/open-source-lgpl-obligations

## LGPL-compatible libmpv candidate

The original shinchiro `20260610` binary was rejected because its recipe used
mpv's GPL-default configuration. It was used only to prove the render path.

The accepted candidate is rebuilt from the pinned `20260610` recipe revision
with the committed patch in `runtime/mpv-winbuild-cmake-lgpl.patch`. The patch:

- sets mpv to `-Dgpl=false`;
- sets FFmpeg to `--disable-gpl --enable-version3`;
- removes GPL or unused AviSynth, davs2, DVD, Rubber Band, x264, x265, and
  Xvid dependencies;
- disables embedded Lua/JavaScript and mpv's standalone OSC;
- pins moving Vulkan Loader and SPIRV-Cross inputs needed by the recipe.

FFmpeg's own `-L` runtime probe reports LGPL version 3 or later. Its decoder
probe confirms native H.264, HEVC, AAC, AC-3, DTS, TrueHD, SRT, ASS, and PGS.
The Qt desktop matrix passed with the exact DLL hash in `runtime-lock.json`.

Production packaging must still collect and ship the complete notices, license
texts, source/relinking material, build patch, and dependency inventory. It
must verify the locked DLL hash before release creation.

References:

- https://github.com/mpv-player/mpv
- https://github.com/shinchiro/mpv-winbuild-cmake
- https://ffmpeg.org/legal.html
