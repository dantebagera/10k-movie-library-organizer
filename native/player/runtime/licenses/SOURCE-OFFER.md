# Corresponding source information

The exact upstream source locations and revisions for Qt, mpv, FFmpeg, and the
Windows build scripts are recorded in `cinema-paradiso-player.json`.

Cinema Paradiso Player source is distributed with the portable application
under `native/player/`. The runtime is reproducible from the recorded source
revisions and build flags. No unspecified latest dependency is fetched by the
release builder.

For the LGPL-covered libraries, recipients may obtain the corresponding source
directly from the recorded upstream repositories and rebuild compatible DLLs
using the instructions in `RELINKING.md`.
