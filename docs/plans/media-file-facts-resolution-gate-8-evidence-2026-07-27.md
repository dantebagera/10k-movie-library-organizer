# Media File Facts and Resolution: Gate 8 Evidence

Date: 2026-07-27

Status: implementation and isolated rehearsal complete. Live rollout is
separately gated and has not been approved or run.

## Result

The version 9 implementation passed schema migration, rollback, protected-data,
bounded backfill, API, desktop browser, build, and complete regression checks
against disposable catalogues.

The two controlled `The Monkey (2025)` files now produce:

| File | Stored measured facts | Display | Duplicate result |
| --- | --- | --- | --- |
| x264 | 1800 x 960, AVC High@L4.1, 8-bit, 2,250,404 bps, AAC 2.0 at 132,300 bps | `1080-class - 1800 x 960` | Review |
| x265 | 1800 x 960, HEVC Main 10@L4@Main, 10-bit, 2,000,527 bps, AAC 2.0 at 132,300 bps | `1080-class - 1800 x 960` | Reference copy; no automatic removal |

Both rows have duration 5,780,917 ms, measured aspect ratio 1.875, and probe
status `ok`. Maintenance recommends zero removals because the codec and bit-depth
tradeoff is not objective dominance.

## Safety boundary and frozen source

No live schema migration, live backfill, live rescan, live media mutation,
provider refresh, cache deletion, Git stage, commit, push, reset, checkout, or
configuration change was performed.

The approved rehearsal source was frozen after an independently changing live
catalogue was re-baselined:

- source schema: 8;
- source media generation: 6,873;
- source curation generation: 16,792;
- source file rows: 3,782;
- integrity: `ok`;
- foreign-key violations: 0.

Verified archive:

`C:\Users\dante\AppData\Local\Temp\cp-media-facts-rehearsal-backup\cp-catalog-migration-20260727T182320Z.zip`

- ZIP bytes: 820,752,164;
- archived files: 26,889;
- uncompressed bytes: 1,142,048,388;
- file records: 3,782;
- TMDB records: 4,880;
- Plex records: 3,814;
- manual matches: 481;
- lists/list items: 11 / 273;
- collection overrides: 1;
- followed releases: 11;
- qBittorrent jobs: 249;
- metadata assets: 23,037 files / 471,535,083 bytes.

The physical `res_cache.json` remained present and unchanged at 1,554,563
bytes. Runtime source search finds no read or write of it; remaining references
are documentation, release exclusions, and tests.

At the final read-only live check, the independently running catalogue had
advanced to 3,783 rows and media generation 6,880. It remained schema 8 with
integrity `ok` and zero foreign-key violations. Therefore the eventual live
rollout must use a fresh baseline and a fresh backup; the rehearsal archive
must not be reused as the production rollback point.

## Authoritative implementation

- `services/catalog_store.py` remains the schema and SQL query owner.
- `services/catalog_repository.py` remains the write/export boundary.
- `services/media_file_facts.py` is the single MediaInfo adapter,
  normalization, classification, and safe-error owner.
- `services/media_file_backfill.py` is the bounded resume/retry coordinator.
- Existing reconciliation owns new, changed, and renamed local-file probing.
- `services/maintenance_audit.py` remains the duplicate and upgrade policy
  owner.
- Shared cards and `src/utils/libraryUtils.js` own cross-surface quality
  presentation.

The complete ownership map is
`docs/plans/media-file-facts-authoritative-paths.md`.

## Exact schema diff

Schema 9 adds 25 columns to the existing `media_files` owner:

`video_width`, `video_height`, `video_codec`, `video_profile`,
`video_bit_depth`, `video_bitrate`, `video_frame_rate`, `duration_ms`,
`display_aspect_ratio`, `rotation_degrees`, `audio_codec`, `audio_channels`,
`audio_bitrate`, `filename_quality_claim`, `quality_class`, `quality_source`,
`quality_conflict`, `quality_nonstandard`, `file_facts_version`,
`classifier_version`, `probe_status`, `probed_at`, `probe_error`, `probe_size`,
and `probe_modified_time`.

It also:

- changes `idx_media_files_quality` from `(resolution, rip_source)` to
  `(quality_class, resolution, rip_source)`;
- adds `idx_media_files_facts_stale` on
  `(probe_status, file_facts_version, classifier_version, path_key)`;
- preserves `resolution` as an atomically updated compatibility projection;
- initializes all migrated rows as unprobed/version 0 without probing files.

No table, identity field, provider field, curation field, download field, or
asset relationship is duplicated into a second authority.

## Migration and protected-data proof

Disposable source:

`C:\Users\dante\AppData\Local\Temp\cp-media-facts-rehearsal-restored\catalog\catalog.sqlite`

Migrated clone:

`C:\Users\dante\AppData\Local\Temp\cp-media-facts-rehearsal-work\catalog-v9.sqlite`

Results:

- migration time on the current machine: 1,378.454 ms;
- database size before/after: 163,565,568 bytes;
- schema version: 8 to 9;
- rows marked unprobed: 3,782;
- old `media_files` projection digest before/after:
  `49cecf5a5c65e60f2cf20367ed00da7213f8bd4e79d2f9b1b469a2f2fa00a27f`;
- all 30 pre-existing table projections compared;
- protected mismatch list: empty;
- media and curation generations unchanged by migration;
- integrity: `ok`;
- foreign-key violations: 0;
- provider calls and filesystem probes during migration: 0;
- second initialization: no rewrite and no probe.

Automated failure injection covers schema creation, index creation,
schema-version update, validation, and post-migration initialization. Each
failure leaves the source schema, logical digest, integrity, and foreign keys
unchanged.

## Controlled backfill proof

Controlled clone:

`C:\Users\dante\AppData\Local\Temp\cp-media-facts-rehearsal-work\catalog-v9-monkey-controlled.sqlite`

Only the two explicit `The Monkey (2025)` paths were eligible. Every other row
was marked rehearsal-excluded in new schema-9 fields only.

| Pass | Selected / changed | Failures | Generation | Duration |
| --- | ---: | ---: | --- | ---: |
| First bounded batch | 1 / 1 | 0 | 6,873 to 6,874 | 397.239 ms |
| Resume | 1 / 1 | 0 | 6,874 to 6,875 | 172.347 ms |
| Idempotent pass | 0 / 0 | 0 | 6,875 to 6,875 | 72.489 ms |

Measured MediaInfo calls took 40.413 ms and 94.062 ms. The idempotent pass used
a probe callback that raises if called; it completed without invoking it.

Before/after SHA-256, size, and modification time were identical for both media
files:

- x264:
  `017e4891b1a4e275f2e5abbc41267041d544a5735153ff508d9f578678b8d3da`;
- x265:
  `484791a8716429f79ff144518a79f4831d32d0cbf93652c3ba9068bcb5247b62`.

The controlled database finished at schema 9, generation 6,875, integrity
`ok`, and zero foreign-key violations.

## Rollback proof

The verified archive rebuilt this schema-9 rollback shadow:

`C:\Users\dante\AppData\Local\Temp\cp-media-facts-rehearsal-work\rollback-shadow.sqlite`

The shadow passed with 3,782 file records, 4,880 TMDB records, 3,814 Plex
records, 481 manual matches, 11 lists, 273 list items, one collection override,
and 11 followed releases.

A separate full restore reproduced all 26,889 files and 1,142,048,388 bytes.
The restored schema-8 catalog was byte-for-byte identical to the frozen source:

`ce9c7feb49523e711fbf38c940cd0661da06eaacb00ab8b47387ec99d514238a`

It reopened as schema 8 with 3,782 rows, integrity `ok`, and zero foreign-key
violations.

## API and desktop acceptance

The browser clone relocated every displayed media path under:

`C:\Users\dante\AppData\Local\Temp\cp-media-facts-browser-20260727`

It could not access a broad real movie root. Read-only API checks proved:

- Library projects both rows as `1080-class - 1800 x 960`;
- Home/stats sees the two controlled copies as one title and one duplicate
  group;
- Maintenance exposes exact dimensions, codec, profile, bit depth, bitrate,
  duration, and audio facts;
- Maintenance reports `recommended_removals: 0`;
- facts backfill status is idle with zero remaining rows.

In-app desktop browser inspection proved:

- Movie View renders the exact non-standard quality chip on both cards;
- File View renders the exact quality on both rows;
- expanded x265 details render `1800 x 960 · HEVC · 10-bit`, AAC stereo, and
  probe status `Measured`;
- the existing desktop layout remains intact;
- browser console errors: 0.

The isolated server was stopped after inspection.

## Complete verification

| Check | Result |
| --- | --- |
| Python | final run: 840 passed in 93.586 s |
| Node | 69 passed |
| Production Vite build | 1,646 modules; passed in 2.18 s |
| Desktop Playwright | clean full rerun: 42 passed in 57.3 s |
| Final media-facts Playwright subset | 3 passed in 5.6 s |
| SQLite migration/rollback | passed |
| In-app browser visual QA | passed; 0 console errors |

One earlier full Playwright run had Chromium crash before an existing
People-search test interacted with the page. That exact test passed alone in a
fresh process, and the required full 42-test rerun then passed cleanly.

A final SQL fallback audit added one backend-only regression: an unchanged file
retains its last valid measured fields if a later temporary probe fails, while
the failed status blocks duplicate automation and remains retryable. The final
840-test Python run and the media-facts card/Maintenance Playwright subset passed.
Two additional full Playwright attempts after that backend-only change hit the
existing async Library collection test's 15-second loading timeout; the exact
case passed in 2.4 seconds in a fresh isolated run. No assertion returned an
incorrect collection value, and this route-mocked browser case does not execute
the changed file-facts write path.

## Expected live load

The clone migration took 1.38 seconds and performed no media I/O. Startup does
not wait for the full backfill.

The default backfill uses eight-row batches and two concurrent probes, capped
at four by code. The two real probes took 40-94 ms each. A simple extrapolation
is roughly three minutes for 3,783 rows on the current machine; operationally,
allow 3-10 minutes for disk seeks, missing/locked files, and SQLite batches.
The backfill opens at most two media files concurrently and reads container
metadata; it does not hash or decode whole movies. Progress and bounded failures
are exposed through Maintenance.

This is an estimate, not a promise. A fresh Gate 9 baseline must re-check row
count, quiescence, and available disk space.

## Gate 9 operator commands — not executed

These commands are the proposed controlled live procedure after separate
approval. They must run only after Cinema Paradiso and download imports are
quiescent.

```powershell
$projectRoot = 'C:\Users\dante\Desktop\cinema paradiso'
$backupRoot = 'C:\Users\dante\AppData\Local\Cinema Paradiso\Backups'
$liveDb = 'C:\Users\dante\AppData\Local\Cinema Paradiso\Catalog\catalog-read-cb30c1d963c88463.sqlite'

Set-Location -LiteralPath $projectRoot
python tools\catalog_migration_backup.py backup --project-root $projectRoot --output-dir $backupRoot
```

Copy the exact archive path printed by that command:

```powershell
$archive = 'C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-YYYYMMDDTHHMMSSZ.zip'
$restoreCheck = 'C:\Users\dante\AppData\Local\Temp\cp-media-facts-live-restore-check-YYYYMMDDTHHMMSSZ'

python tools\catalog_migration_backup.py verify $archive
python tools\catalog_migration_backup.py restore $archive $restoreCheck
python tools\build_shadow_catalog.py $archive --database "$restoreCheck\rollback-shadow.sqlite"
```

After confirming port 5000 has no listener, start the normal backend once. Its
existing schema owner performs the transaction and its existing startup
coordinator begins the bounded resumable backfill:

```powershell
$env:CP_PORT = '5000'
& "$projectRoot\.venv\Scripts\python.exe" "$projectRoot\app.py"
```

Monitor from another PowerShell window:

```powershell
Invoke-RestMethod 'http://127.0.0.1:5000/api/library/status' | ConvertTo-Json -Depth 8
Invoke-RestMethod 'http://127.0.0.1:5000/api/maintenance/audit' | ConvertTo-Json -Depth 8
```

Abort is safe before or during backfill: stop the backend. Completed batches
remain committed and restart resumes stale rows. Do not roll back merely
because the backfill is incomplete.

If schema, integrity, foreign keys, protected counts/digests, or behavior shows
an unexplained mismatch, keep the backend stopped. Restore only the catalogue
because this migration changes no provider JSON, media, metadata assets, or
curation files:

```powershell
$failedRoot = 'C:\Users\dante\AppData\Local\Temp\cp-media-facts-failed-v9-YYYYMMDDTHHMMSSZ'
New-Item -ItemType Directory -Path $failedRoot

Move-Item -LiteralPath $liveDb -Destination "$failedRoot\failed-v9.sqlite"
if (Test-Path -LiteralPath "$liveDb-wal") {
    Move-Item -LiteralPath "$liveDb-wal" -Destination "$failedRoot\failed-v9.sqlite-wal"
}
if (Test-Path -LiteralPath "$liveDb-shm") {
    Move-Item -LiteralPath "$liveDb-shm" -Destination "$failedRoot\failed-v9.sqlite-shm"
}
Copy-Item -LiteralPath "$restoreCheck\catalog\catalog.sqlite" -Destination $liveDb
```

Then reopen the restored database read-only, require schema 8, integrity `ok`,
zero foreign-key violations, and the fresh baseline counts before restarting
Cinema Paradiso.

## Remaining risks and stop boundary

- The live catalogue is changing; Gate 9 requires a new quiescent baseline and
  backup.
- Real-world probe duration and failure count across all rows are not knowable
  from two controlled files.
- Missing, inaccessible, changing, corrupt, and unsupported files remain
  explicit retry/review states; they do not block other rows.
- Failed or incomplete facts prevent automatic duplicate-removal
  recommendations.
- The historical `res_cache.json` remains on disk. It is unused, but deletion
  still requires separate explicit permission after live acceptance.
- No live action in the proposed command section is approved by this evidence.

Gate 8 stops here and waits for Dante's separate live-rollout decision.

## Gate 9 controlled live rollout addendum

Dante explicitly approved the live rollout. It completed on 2026-07-27.

### Quiescence, baseline, backup, and restore

- The port-5000 backend and its import monitor were stopped before the baseline,
  migration, and backfill. The embedded qBittorrent process remained running;
  its active download remained in the configured incomplete directory.
- The fresh stopped baseline contained 3,783 `media_files` rows at schema 8,
  media generation 6,880, curation generation 16,792, integrity `ok`, and zero
  foreign-key violations.
- The 30 protected table projections had aggregate digest
  `a00d99069ded11d6ecaf33129f21df0064228063056f6c7896e703692d6b56b3`.
- The fresh backup is
  `C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260727T204639Z.zip`.
  It is 820,751,040 bytes and contains 26,889 files.
- Archive verification passed. Its semantic inventory contained 3,783 file
  records, 4,880 TMDB records, 3,814 Plex records, 481 manual matches, 11
  lists, 273 list items, one collection override, 11 followed records, 249
  qBittorrent records, and 23,037 asset files.
- An independent rollback shadow built from that archive passed at schema 9
  with integrity `ok`, zero foreign-key violations, and no count mismatch.
- Restoring the exact archive reproduced the schema-8 catalogue with all 30
  logical table projections and the aggregate protected digest unchanged.
  SQLite page layout differed, as expected from the online-backup API; logical
  content did not.

### Live migration and protected-state proof

- The authoritative schema owner migrated the live catalogue from 8 to 9 in
  1,332.644 ms with network and media probes blocked.
- All 3,783 old `media_files` projections retained digest
  `8c15dd86f4edb691a2f13ed8d3a792b203d2158be989c3ee6ac834d0312003de`.
- All 30 protected table projections retained the baseline aggregate digest.
- Media and curation generations remained 6,880 and 16,792 immediately after
  migration. Integrity was `ok` and foreign-key violations remained zero.
- A second schema initialization performed no migration, no probe, no provider
  call, no generation advance, and no database rewrite.

### Live backfill and idempotence

- The bounded worker selected and probed all 3,783 rows in eight-row batches
  with concurrency two. It changed all 3,783 rows in 710.232 seconds.
- One explicit retry of the two failed rows took 0.467 seconds. Total measured
  backfill and retry time was 710.699 seconds (11.845 minutes).
- Final states are 3,781 `ok` and two `no_video`; no rows are pending and no
  row was rejected by catalogue ownership checks.
- Both failures are stable MediaInfo results containing only a General track:
  `Dr..Jekyll.And.Mr..Hyde.1931.1080p.BluRay.x264.AAC-[YTS.MX].mp4` and
  `Mobile.Suit.Gundam.0083.The.Afterglow.Of.Zeon.1992.1080p.BluRay.x264.AAC-[YTS.MX].mp4`.
  They remain explicit unmeasured states and cannot authorize automatic
  duplicate removal.
- Media generation advanced from 6,880 to 7,354; curation generation remained
  16,792. A final pass selected, probed, and changed zero rows and did not
  advance generation.
- After backfill, all 29 pre-existing `media_files` columns and all other
  protected table projections were unchanged. Only the approved `resolution`,
  `raw_json`, schema metadata, generation metadata, and new facts columns
  changed.

### Live behavior and restored service

- Both `The Monkey (2025)` files store 1800 x 960, duration 5,780,917 ms, AAC
  stereo, and measured `1080p`. The x264 copy is AVC 8-bit at 2,250,404 bps;
  the x265 copy is HEVC Main 10 at 2,000,527 bps.
- Library Movie View, File View, file details, and Maintenance all render
  `1080-class - 1800 x 960`. Maintenance exposes the codec/bit-depth
  difference and reports zero recommended removals for this pair.
- `/api/library`, `/api/maintenance/audit`, `/api/stats`,
  `/api/library/status`, and `/api/qbittorrent/status` returned successfully.
  The normal port-5000 backend completed a second start with schema 9, media
  generation 7,354, zero pending probes, integrity `ok`, and zero foreign-key
  violations.
- Desktop in-app browser verification found no console warnings or errors.
  Playback, rename, and delete controls remained present, but no live
  playback, rename, delete, or new-file ingest action was triggered.
- The embedded qBittorrent service remains running and its import monitor is
  healthy with zero consecutive errors.
- No media file was written, renamed, or deleted. Historical
  `res_cache.json` was not read, written, or removed. Git was not staged,
  committed, reset, or pushed.

Gate 9 is complete. Retain the verified backup until Dante accepts the live
result.

## Post-rollout duplicate-comparison refinement — 2026-07-28

After reviewing the live manual-comparison cases, Dante approved separating
content equivalence, technical quality, and storage efficiency in the existing
Maintenance owner. This refinement required no schema change, catalogue
backfill, provider call, or media mutation.

- Duplicate comparisons are pairwise; tied dimensions no longer produce an
  arbitrary filename-selected `Recommended keep`.
- Runtime and frame rate are content-equivalence evidence only. Frame rate
  never contributes to technical-quality rank.
- Relative framing differences up to two percent are disclosed as minor crops.
- A higher measured resolution class with at least 1.5 times the pixels can
  dominate only when identity/content are safe and source, bit depth, and
  primary audio do not regress.
- Size is storage-efficiency evidence, not cross-codec quality evidence.
- Recommended reclaimable space now counts recommended removals only.
- Live results became five recommended removals: the existing three plus
  `Lolita (1997)` 720p and `Vamps (2012)` DVDRip. Both `The Monkey (2025)`
  files remain unselected `Encoding trade-off` rows.
- Final verification passed 846 Python tests, 69 Node tests, the production
  Vite build, 43 isolated desktop Playwright tests, live API checks, and live
  in-app browser inspection with zero console warnings or errors.
