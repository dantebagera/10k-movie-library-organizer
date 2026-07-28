# Cinema Paradiso native player — Phase 4 findings

Date: 2026-07-28

## Scope delivered

Phase 4 adds one backend `SubtitleService` as the authority for OpenSubtitles
and SubDL. Provider secrets remain in `PlayerConfig`; neither the native
helper, its environment, process arguments, public configuration/status, safe
result model, cache attribution, nor diagnostics contain credentials.

The service builds searches from the verified movie identity, release
filename, file size, OpenSubtitles file hash, stored frame rate, and preferred
languages. Enabled providers run concurrently under bounded timeouts. A slow,
failed, or rate-limited provider cannot block another provider's results.
Diagnostics expose only stable redacted states, counts, latency, and cooldown.

Both adapters normalize into one internal result contract. Ranking follows the
approved order: exact hash, release match, provider movie identity,
title/year, frame rate, language/preferences, then provider rating/download
signals. Cross-provider duplicates are removed with deterministic tie
breaking. The helper receives only opaque session-scoped result IDs and safe
display fields; download URLs stay in backend memory and expire.

Downloads are bounded and staged by the backend. The validator rejects
traversal, absolute/symlink archive entries, excessive entry counts, oversized
responses/expanded files, unsupported extensions, invalid text, and unsafe
download hosts. SRT, ASS, SSA, and VTT text is normalized to UTF-8. Cache
attribution preserves provider/release/hash without credentials, URLs, or a
media path. The default is the controlled subtitle cache; beside-movie storage
is used only when the existing explicit setting selects it.

The `D` overlay now displays ranked results, match reason, provider, language,
frame rate, and SDH/forced markers. Mouse/tap and Enter select the first
result. The backend validates and caches the download, sends its local path
only over the authenticated pipe, and libmpv loads and selects it immediately.

IPTV and the movie-card Stream action remain unchanged.

## Files changed

- Backend subtitle authority:
  `services/subtitle_service.py`, `services/player_catalog.py`,
  `services/player_manager.py`, `services/player_protocol.py`,
  `services/player_routes.py`, and `app.py`.
- Native result/download/load flow:
  `native/player/src/MpvItem.*`, `native/player/src/PlayerBridge.*`,
  `native/player/qml/Main.qml`, and `native/player/tools/smoke_player.py`.
- Regression coverage:
  `tests/test_subtitle_service.py`, `tests/test_subtitle_providers.py`,
  `tests/test_player_protocol.py`, `tests/test_player_manager.py`,
  `tests/test_player_config_api.py`, and the existing native-player suite.

## Automated verification

- Focused subtitle/provider/protocol/player suite under an isolated
  `CP_TEST_ROOT`: **58 tests passed**.
- Broad Python suite under a unique isolated `CP_TEST_ROOT`:
  **953 tests passed** in 81.336 seconds.
- Frontend Node suite: **70 tests passed**.
- `npm.cmd run build`: **passed**, 1,648 modules transformed.
- Isolated Chromium desktop E2E: **46/46 passed**, including provider-secret
  redaction, OS-player default, centralized local playback, unchanged Stream,
  and unchanged IPTV provider behavior.
- Production Qt/libmpv native build: **passed**.
- `git diff --check`: **passed**.

## Real runtime evidence

The staged production helper completed the provider-facing native loop with
representative local media over the real Windows named pipe:

- `D` emitted `subtitle.search`;
- a safe ranked result rendered at 250% desktop DPI;
- Enter emitted the opaque `subtitle.download` request;
- the authenticated backend supplied a validated external SRT cache path;
- libmpv loaded and selected the external track;
- the helper emitted `subtitle.loaded` and an updated external-track model;
- the process closed cleanly with exit code 0.

The process argument list contained only `cp-player.exe`; no media path,
provider URL, credential, or subtitle path appeared there.

Runtime helper SHA-256:
`E8D3C1145F2F1AE842C65133256F6C37DCCC1400BC988CA14CCB2ADB4325BEF0`.

Inspected evidence:
`%LOCALAPPDATA%\Temp\cp-player-phase2\evidence\player-phase4-final-evidence-subtitle-search.png`
— SHA-256
`D0D824E839FC4261859912D04B8E7BFEB96A48E3EE3B6948FE308B9F52654931`.

The adapters were verified against isolated official-response fixtures rather
than consuming Dante's provider quota or sending a real release filename
without an explicit in-player search action.

## Unresolved risks and next phase

OpenSubtitles and SubDL can change quota policy or response fields; adapter
failures are isolated and surfaced as redacted diagnostics. A real account
smoke remains an optional explicit user action because it consumes provider
quota and transmits search identity. It is not required for safe installation
or OS-player fallback.

Phase 5 is next: premium controls, accessibility/configurable shortcuts,
window-state/multi-monitor hardening, crash/long-play validation, and the
deterministic licensed portable runtime package.
