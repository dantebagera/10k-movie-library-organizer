# Cinema Paradiso Player third-party notices

The native player uses the following dynamically linked components:

- Qt 6.10.3, licensed under LGPL-3.0-only for this distribution.
- mpv commit `48e6c35c0e056d9e4ff04b98e012416697736d8a`, built with
  `-Dgpl=false -Dlibmpv=true -Dlua=disabled -Djavascript=disabled` and
  distributed under LGPL-2.1-or-later.
- FFmpeg commit `c6309b5c63add7ad0ec221fafefc32bdcd6f8b91`, built with
  `--disable-gpl --enable-version3` and distributed under
  LGPL-3.0-or-later as part of the pinned mpv runtime.

The complete license texts are included beside this notice. Exact upstream
locations, revisions, required files, and hashes are recorded in
`cinema-paradiso-player.json`.

Cinema Paradiso does not prevent reverse engineering of these library
interfaces for debugging modifications to the LGPL-covered components.
