# Cinema Paradiso native player — Phase 2 findings

Date: 2026-07-28

## Scope delivered

Phase 2 now has one local-library playback route and one backend authority.
React posts the selected catalog `path_key` to `POST /api/player/play`.
`PlayerManager` resolves the record through the SQL catalog, confines the
result to configured library roots, verifies the immutable runtime, and then
either opens the OS-default player or launches `cp-player.exe`. The obsolete
`/api/open-file` route is removed.

IPTV playback and the movie-card Stream action remain outside this route and
retain their existing players.

The production helper is a Qt 6.10.3 Qt Quick application using the accepted
LGPL `libmpv-2.dll`. It receives its random pipe name, session ID, protocol,
and one-use authentication material through a private child environment. Its
process command line contains only `cp-player.exe`. The authenticated backend
`load` message is the only way to supply a media path.

The version-1 newline-delimited JSON protocol now covers authenticated
handshake, load acceptance, playback state, bounded progress, descriptive
track models, subtitle-search requests, errors, and orderly close. The Windows
pipe rejects remote clients, protocol input is size and shape bounded, and
late or duplicate event sequences are ignored.

The CP-owned QML interface provides:

- play/pause and short/long seek;
- draggable timeline with current and total time;
- volume, mute, speed, audio delay, and subtitle delay;
- fullscreen/windowed behavior;
- descriptive audio, embedded-subtitle, and external-subtitle panels;
- chapters when present;
- the configured keyboard contract from `PlayerConfig`;
- a `D` subtitle-search overlay without provider secrets;
- 2.5-second control hiding while playing;
- CP black/gold visual tokens generated from the same theme source as React;
- work-area-aware desktop sizing and correct high-DPI rendering.

## Files changed

- Backend ownership and security:
  `app.py`, `services/player_routes.py`, `services/player_runtime.py`,
  `services/player_catalog.py`, `services/player_manager.py`,
  `services/player_protocol.py`, and `services/player_windows_pipe.py`.
- Frontend route and shared theme:
  `src/App.jsx`, `src/main.jsx`, `src/styles.css`,
  `src/styles/playerTheme.css`, `design/player-theme.json`, and
  `tools/generate_player_theme.py`.
- Native helper:
  `native/player/CMakeLists.txt`, `native/player/src/*`,
  `native/player/qml/*`, and `native/player/tools/*`.
- Regression coverage:
  `tests/test_native_player.py`, `tests/test_player_catalog.py`,
  `tests/test_player_manager.py`, `tests/test_player_play_api.py`,
  `tests/test_player_protocol.py`, `tests/test_player_route_ownership.py`,
  `tests/test_player_theme.py`, `tests/test_player_settings_ui.py`, and
  `tests/e2e/app-smoke.spec.js`.

## Automated verification

- Broad Python suite under a unique isolated `CP_TEST_ROOT`:
  **909 tests passed** in 84.805 seconds.
- Frontend Node suite: **70 tests passed**.
- `npm.cmd run build`: **passed**, 1,648 modules transformed.
- Isolated Chromium desktop E2E: **45/45 passed**, including the new proof
  that Library Play uses `/api/player/play` while Stream is not invoked.
- Production native build with MSVC 2022 x64, Qt 6.10.3, and the pinned LGPL
  libmpv: **passed**.
- Theme generation drift check: **passed**.

## Real runtime evidence

The deployed production helper was exercised over the real Windows named-pipe
transport with generated representative fixtures:

- SDR H.264 + AAC + AC-3 + embedded SRT/ASS + external SRT/ASS;
- HEVC Main 10 HDR + DTS + TrueHD;
- H.264 + PGS subtitles.

All completed hello/load/ready/state/tracks/progress/closing/closed and exited
with code 0. The interactive run also proved:

- pause and resume through the actual `Space` shortcut;
- accurate `Right` seek from about 1.5 seconds to about 10 seconds;
- real switch from English AAC to French AC-3;
- real switch to the Spanish embedded ASS subtitle;
- embedded and external subtitle discovery;
- fullscreen and Escape;
- `D` emitting `subtitle.search`;
- no media path in process arguments;
- no OS fallback during a healthy real `PlayerManager` session.

Runtime helper SHA-256:
`E7CD8F39FB48E6B63EC99C4076C28A389F988E88139AB1D4DB1E5840E3442189`.

Inspected desktop evidence under
`%LOCALAPPDATA%\Temp\cp-player-phase2\evidence`:

- `player-phase2-final-tracks-5.png` —
  `F3D1E9205B685A824FAFE983C304C79532E02CA212D4136FB6E84C702B6A3665`
- `player-phase2-final-tracks-5-audio-tracks.png` —
  `0FE02F0F9306A438DB8487EBB0A4A7BCA6969969B281F94B352265158B692285`
- `player-phase2-final-tracks-5-subtitle-tracks.png` —
  `069F20FACB1CE11E367565D21BCFF32E4B68A4E61331526B3F595D1D9816816C`
- `player-phase2-final-tracks-5-subtitle-search.png` —
  `8BA9E2D5EE6B14F39A8E424CE206B6BB7454BF7E817166D5FA62BF4C11D0E4B4`

The evidence process was explicitly per-monitor-DPI-aware. This avoided
Windows virtualizing screenshot coordinates at the desktop's 250% scale.

## Unresolved risks and next phase

Playback-history resume is intentionally still zero until Phase 3 supplies the
saved position. Subtitle-provider results/downloads remain Phase 4. Premium
statistics, screenshots, thumbnails, HDR controls, advanced audio, and
multi-monitor persistence remain Phase 5.

The real helper is staged with `windeployqt`, but the distributable immutable
bundle is intentionally not assembled yet. Phase 5 must add the complete
license/source/relinking material and pass the final package manifest gate;
the current temporary runtime is evidence, not a release artifact.

Phase 3 is next. Its additive playback-history schema will be rehearsed only
inside an isolated test root. No live catalog migration or backfill is
authorized or required.
