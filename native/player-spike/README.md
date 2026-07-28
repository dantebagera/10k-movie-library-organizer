# Cinema Paradiso native-player Phase 0 spike

This is the plan-required isolated Qt Quick/libmpv rendering proof. It has no
backend routes, settings, history, catalog access, IPTV behavior, Stream-button
behavior, or production packaging integration.

The spike keeps one owner for each responsibility:

- QML owns the visible desktop shell and controls.
- `MpvItem` owns playback state and libmpv commands.
- libmpv owns decode, seek, track playback, and rendering.
- `main.cpp` owns the temporary automation harness.

Automation launches with `--scenario <json-file> --report <json-file>`. The
scenario contains media paths, so media paths never appear in process
arguments. Reports contain media IDs and playback facts, not media paths.

The runtime lock now records the audited LGPL-compatible libmpv build that
passed the complete Phase 0 fixture matrix. Read `THIRD_PARTY_REVIEW.md` and
`runtime/BUILD.md` before reproducing or packaging it.

## Local build

Use `tools/build_spike.ps1`. It expects the official Qt 6.10.3 MSVC install and
the pinned LGPL libmpv output to exist outside the repository.

Generated build, fixture, report, screenshot, and package artifacts belong
under an isolated temporary directory. They must not be committed.

The Phase 0 package remains a technical artifact until production packaging
adds the complete Qt/libmpv/FFmpeg dependency inventory, corresponding source
or offer, license texts, and relinking material.
