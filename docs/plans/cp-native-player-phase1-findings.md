# Cinema Paradiso Native Player — Phase 1 Findings

Date: 2026-07-28

## Delivered behavior

- `PlayerConfig` is the authoritative validator/redaction owner for player
  preferences. It persists inside the existing application `config.json`; no
  second configuration file was introduced.
- Existing installations default to `os_default`. Selecting `built_in` is an
  explicit user preference.
- The dedicated API contract is live:
  - `GET /api/player/config`
  - `PUT /api/player/config`
  - `GET /api/player/status`
  - `POST /api/player/verify`
- OpenSubtitles and SubDL credentials are write-only. Public API payloads expose
  only configured/not-configured flags.
- Runtime status distinguishes `ready`, `missing`, `damaged`, and
  `incompatible`, always reports OS fallback availability, and exposes only
  safe version/license information.
- Runtime assembly is immutable and manifest-driven. It rejects unpinned
  libmpv, incomplete compliance material, missing Qt/QML/plugins/assets,
  modified hashes, debug files, configuration, history, cache, logs, and user
  data.
- The portable release builder copies only the verified native-player manifest
  inventory and fails when no pinned player runtime is available.
- The existing Settings workspace owns the desktop player card. It includes
  playback mode, resume/completion behavior, language ordering, track
  preferences, rendering/audio settings, subtitle storage/providers, keyboard
  shortcuts, reset, health status, versions, licenses, and Verify Player.
- The Settings copy explicitly states that IPTV and movie-card streaming retain
  their existing players.
- No local playback route was changed in Phase 1.

## Verification

- 139 isolated targeted Python tests passed, including player config/API,
  runtime integrity, immutable assembly, release packaging, Settings source,
  Phase 0 provenance, IPTV, Streaming, qBittorrent, and React routing.
- 70 Node tests passed.
- `npm.cmd run build` passed with 1,647 modules.
- The complete Chromium desktop E2E suite passed: 44/44.
- The new real-browser Settings test proved:
  - OS-default is the initial selection;
  - provider credentials are submitted but not rendered back;
  - saved credentials return only configured flags/placeholders;
  - Verify Player renders pinned CP Player, libmpv, Qt, architecture, fallback,
    and license state;
  - IPTV and movie-card streaming remain explicitly out of scope.
- 1920×1080 desktop screenshots were inspected from isolated mock data:
  - top SHA-256:
    `7F71A3BF988DB87E1CD2A6DED0C85F80AA042ED90D6CAB971D0B8080B5880331`
  - bottom SHA-256:
    `6408569EE10B5226CC9C34432594A204490A28BB325E26ED9D841B8C01CAA0DB`

## Remaining risk and next gate

- The production bundle intentionally cannot be assembled yet because Phase 2
  owns the production `cp-player.exe`. The assembly and portable builders now
  fail closed until that executable, the accepted libmpv DLL, Qt runtime,
  assets, full notices, license texts, source/relinking material, and matching
  hashes are all present.
- Phase 2 must implement the production QML/libmpv helper, versioned IPC,
  `PlayerManager`, and the one centralized local playback route before the
  obsolete OS-only local route can be removed.
- IPTV playback and the movie-card Stream action remain outside this migration.
