# Cinema Paradiso native player - Phase 5 findings

Date: 2026-07-28

## Scope delivered

Phase 5 completes the premium controls and hardening work in the existing
authoritative owners. The Qt Quick helper remains the interface and IPC
client, while libmpv remains responsible for decoding, seeking, rendering, and
track playback.

The native player now provides chapter markers and the existing chapter
browser, rolling file-specific seek thumbnails captured from libmpv, subtitle
styling, screenshots, A-B repeat, frame advance, playback statistics, aspect
ratio and crop controls, zoom, pan, rotation, always-on-top mode, advanced
audio output/downmix/passthrough preferences, and HDR/tone-mapping
preferences. Premium actions use the existing configurable shortcut contract
instead of a second input system.

Window size, position, screen, maximized state, and always-on-top state are
reported through the authenticated IPC channel and persisted by
`PlayerConfig`. The native bridge validates stored placement against current
screens and available geometry, including negative secondary-monitor
coordinates and missing-screen fallback.

The production assembly now uses the pinned Qt deployment tool, the pinned
libmpv runtime, a deterministic manifest, generated player-theme assets,
`qt.conf`, exact upstream licenses, third-party notices, relinking
instructions, and a source offer. The portable builder changed from broad
workspace copying to an explicit allowlist and includes no user data,
credentials, playback history, subtitle cache, logs, tests, screenshots, or
local absolute paths.

Existing installations still default to the operating-system player. Runtime
verification and damaged-runtime fallback remain available. IPTV and the
movie-card Stream action remain unchanged and do not use this player.

## Files changed

- Player preferences, validation, persistence, and IPC:
  `services/player_config.py`, `services/player_manager.py`,
  `services/player_protocol.py`, and `app.py`.
- Native premium controls and window behavior:
  `native/player/src/MpvApi.*`, `native/player/src/MpvItem.*`,
  `native/player/src/PlayerBridge.*`, and
  `native/player/qml/Main.qml`.
- Settings UI:
  `src/features/settings/SettingsWorkspace.jsx`.
- Runtime assembly, license inventory, and smoke tooling:
  `native/player/runtime-metadata.json`, `native/player/runtime/`,
  `native/player/tools/build_player.ps1`,
  `native/player/tools/smoke_player.py`, and
  `native/player/tools/smoke_manager.py`.
- Portable release construction:
  `tools/build_portable_release.py`.
- Regression coverage:
  `tests/test_native_player.py`, `tests/test_player_config.py`,
  `tests/test_player_manager.py`, `tests/test_player_protocol.py`,
  `tests/test_player_runtime_assembly.py`,
  `tests/test_player_settings_ui.py`, and
  `tests/test_release_packaging.py`.

## Automated verification

- Focused Phase 5 player/config/protocol/runtime/settings/package suite:
  **54 tests passed**.
- Broad Python suite under the isolated
  `CP_TEST_ROOT=C:\Users\dante\AppData\Local\Temp\cp-player-phase5-full-final`:
  **959 tests passed** in 80.393 seconds.
- Frontend Node suite: **70 tests passed**.
- `npm.cmd run build`: **passed**, 1,648 modules transformed.
- Isolated Chromium desktop E2E: **46/46 passed**. This includes the
  OS-player default, centralized local playback, unchanged movie-card Stream
  behavior, and unchanged IPTV provider behavior.
- Clean production Qt/libmpv native build and staged runtime assembly:
  **passed**.
- Runtime manifest verification: **1,328 required files and six license
  records passed hash and inventory validation**.
- `git diff --check`: **passed**.

## Real runtime and package evidence

The production `cp-player.exe` was exercised through the real Windows named
pipe with representative SDR H.264/AAC media, HDR HEVC 10-bit media,
multilingual audio and embedded subtitle tracks, an external subtitle, resume
state, restored track fingerprints and subtitle delay, and clean shutdown.
Progress, duration, track changes, resume choice, and close events were
observed over the authenticated protocol. The helper process arguments
contained only the executable; no media path, subtitle path, provider secret,
or download URL was exposed.

The screenshot command was moved to libmpv's asynchronous command API after a
real run exposed that a synchronous command could stall the QML thread.
Following that correction, playback progress continued and the rolling
seek-thumbnail cache produced valid JPEG frames from the current file.

A 7,205-second fixture was recognized as 7,205,000 ms and played, rendered,
reported progress, and closed cleanly. Manager integration was exercised for
both a clean close and a deliberately terminated helper. The crash path
recorded the final session event without launching a duplicate fallback
player.

The available desktop exposed one 1,536 x 864 logical display at 250% scaling.
The player rendered correctly there with controls and resume UI visible.
Negative monitor coordinates, stale screen names, and geometry clamping are
covered by native/backend tests.

Final staged runtime:

- Player SHA-256:
  `4793AAA2CC6D6D937BF6CE7D6D355BBD1268139278AADCDF1A7C2F4014D17D31`
- libmpv SHA-256:
  `0A76BD542BBA2D85ABEFCC7CD1005269085E1B5815B4E8BAEC62FF4EA4246675`

Final portable archive:

- `Cinema-Paradiso-2.8.1-Portable.zip`
- Size: **101,517,391 bytes**
- Entries: **1,560**
- SHA-256:
  `60D2766C8674805B1FA4697A74152B5FEC0DD7C46ACD423000E440AD3E448F22`
- Forbidden user-data/local-path matches: **0**
- Native runtime manifest: **1,328 files and six licenses verified**

No live catalog, playback-history migration, media file, subtitle provider
account, cache deletion, Windows media association, or remote repository was
modified during Phase 5.

## Unresolved release-certification limits

The implementation and available runtime checks are complete, but two
hardware/time matrix items from the plan could not truthfully be certified in
this session:

- The 7,205-second fixture was validated as long-duration media, but it was
  not left playing for two wall-clock hours.
- This machine exposed only one display at 250% scaling, so real secondary
  monitor placement and the requested 100%-200% display-scale matrix were not
  available. Automated validation covers those state transitions, but it is
  not a substitute for that hardware matrix.

Synthetic keyboard/mouse injection was also unreliable in the final desktop
session. Earlier phase runtime evidence verified the main controls, and the
Phase 5 actions are covered through their QML/libmpv contracts, but the final
run does not claim a fresh automated keystroke pass.

These are release-certification evidence gaps, not known code failures. The
remaining manual release gate is a two-hour wall-clock soak plus a real
multi-monitor 100%-200% DPI matrix on suitable hardware.
