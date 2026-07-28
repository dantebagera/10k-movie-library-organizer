# Cinema Paradiso native player — Phase 3 findings

Date: 2026-07-28

## Scope delivered

Phase 3 adds one authoritative, file-specific playback-history service on top
of the existing canonical catalog. Schema version 10 adds only the
`playback_history` table and its indexes. The isolated migration preserves the
media projection byte-for-byte, validates integrity, and rolls back injected
failures. No live catalog migration or backfill was run.

`PlaybackHistoryStore` owns position, duration, completion time, track
fingerprints, subtitle delay, and optimistic session revision. `PlayerManager`
starts the history session only after the authenticated helper handshake and
forwards the existing native event stream to that service. Progress is saved
at a bounded cadence and on pause, seek, track/settings changes, orderly close,
helper error, and unexpected helper exit. Older sessions cannot overwrite a
newer revision.

Completion uses the existing user-curation Watched list as its sole watched
authority. History does not create a second watched state. Automatic
completion retries if curation was temporarily unavailable, while a manual
Watched choice keeps the item out of Continue Watching.

The Home screen now shows the approved compact portrait Continue Watching rail
after the hero. It uses the shared poster renderer with `object-fit: contain`,
keeps exact-file progress while presenting the current canonical movie
identity, collapses duplicate copies to the most recent one, and exposes
Resume, Start over, and Remove progress. Empty history renders no rail.

The native helper restores audio and subtitle tracks by descriptive
fingerprint, restores subtitle delay, and pauses before seeking when saved
progress exists. Its CP-owned resume prompt offers Resume and Start over
without exposing the media path.

IPTV playback and the movie-card Stream action remain unchanged and outside
this implementation.

## Files changed

- Schema and catalog mutation ownership:
  `services/catalog_store.py`, `services/catalog_repository.py`,
  `tests/catalog_schema_fixtures.py`, and the schema regression tests.
- History and playback integration:
  `services/playback_history.py`, `services/player_manager.py`,
  `services/player_protocol.py`, `services/player_routes.py`,
  `services/player_catalog.py`, and `app.py`.
- Native resume and restoration:
  `native/player/src/MpvItem.*`, `native/player/src/PlayerBridge.*`,
  `native/player/qml/Main.qml`, and `native/player/tools/smoke_player.py`.
- Continue Watching:
  `src/App.jsx`, `src/features/home/HomeWorkspace.jsx`,
  `src/components/movie-card/MovieCard.jsx`,
  `src/components/movie-card/movieCard.css`, and `src/styles.css`.
- Regression coverage:
  `tests/test_catalog_schema_v10.py`, `tests/test_playback_history.py`,
  `tests/test_playback_history_mutations.py`, and updates to the existing
  player, schema, ownership, UI-source, and desktop E2E suites.

## Automated verification

- Focused schema/history/player suite under an isolated `CP_TEST_ROOT`:
  **60 tests passed**.
- Broad Python suite under a unique isolated `CP_TEST_ROOT`:
  **935 tests passed** in 87.529 seconds.
- Frontend Node suite: **70 tests passed**.
- `npm.cmd run build`: **passed**, 1,648 modules transformed.
- Isolated Chromium desktop E2E: **46/46 passed**, including Continue
  Watching layout/actions, centralized local playback, unchanged Stream
  behavior, unchanged IPTV provider isolation, and OS-player default.
- Production native build with MSVC 2022 x64, Qt 6.10.3, and the pinned LGPL
  libmpv: **passed**.
- `git diff --check`: **passed**.

## Real runtime evidence

The staged production helper was exercised with representative real media over
the Windows named-pipe transport. A resume run emitted authenticated
hello/ready/state/progress/tracks/settings/resume-choice/closing/closed events,
sought to the saved position, continued playback, and exited with code 0. A
second run restored the French audio fingerprint, Spanish embedded ASS
subtitle fingerprint, and a -250 ms subtitle delay.

Runtime helper SHA-256:
`1222E6C4E5AD1B9D7A163C126EE452E7FD41F861B83C260924CBE551A08BBC9C`.

Inspected desktop evidence under
`%LOCALAPPDATA%\Temp\cp-player-phase2\evidence`:

- `player-phase3-final-resume-prompt.png` —
  `9232872F3C721182F68F8C92A7CF13F6D630E46D63C10C7A677ECB5A13827B2F`
- `continue-watching-phase3.png` —
  `E69A4716479C6E9CD4725AD4B3967E51EE8B5D2430AA77018A8E27E236060D80`

The resume prompt was captured at the desktop's 250% DPI scale. The Home
evidence is 1920x1000 and shows the complete compact poster tiles without
stretching or cropping.

## Unresolved risks and next phase

The initial subtitle-search overlay still has no provider results or downloads;
that belongs to Phase 4. The temporary helper staging directory is evidence,
not a distributable package; pinned runtime manifests, hashes, licenses,
relinking/source materials, and user-data exclusion remain Phase 5.

Phase 4 is next. Subtitle credentials will remain backend-only and redacted.
Provider calls, archive handling, caching, ranking, and helper loading will be
tested entirely with isolated fixtures and fake providers before any optional
real provider smoke.
