# Media File Facts and Resolution: Zero-Regression Plan

Status: Gate 9 controlled live rollout completed on 2026-07-27 after Dante's
explicit approval. The verified pre-migration backup is retained.

Proposed task name:

`Media File Facts and Resolution - Zero Regression`

Repository:

`C:\Users\dante\Desktop\cinema paradiso`

This plan changes the SQLite catalogue, local-file probing, quality display,
Library filtering, upgrade detection, and duplicate recommendations. It must be
treated as a catalogue migration, not as a local threshold patch.

The implementation task may change code, create isolated fixtures, run tests,
build the frontend, and rehearse migration/backfill against disposable catalogue
copies. It may not migrate or backfill the live catalogue until Dante separately
approves the completed rehearsal evidence.

## 1. Confirmed defect and why it is systemic

The two current copies of `The Monkey (2025)` both contain a measured
`1800 x 960` video stream:

| File | Video | Bit depth | Video bitrate | Audio | Size |
| --- | --- | ---: | ---: | --- | ---: |
| x264 copy | AVC | 8-bit | 2.25 Mbps | AAC stereo, 132 kbps | 1.60 GB |
| x265 copy | HEVC | 10-bit | 2.00 Mbps | AAC stereo, 132 kbps | 1.43 GB |

Both have the same duration, frame rate, measured dimensions, display aspect
ratio, and audio configuration.

Cinema Paradiso currently classifies dimensions using these hard thresholds:

- `4K` when width is at least 3800 or height is at least 2000;
- `1080p` when width is at least 1900 or height is at least 1000;
- `720p` when width is at least 1200 or height is at least 700.

`1800 x 960` misses both 1080 thresholds and is therefore stored as `720p`.
MediaInfo measured the files correctly; the derived label is wrong.

The current live catalogue inspection also found:

- 9 filenames claiming `1080p` whose stored value is `720p`;
- all 9 measured files occupy the same gap between the current 720 and 1080
  thresholds;
- 2 filenames claiming `1080p` whose measured dimensions are only about
  `954 x 576` and `912 x 592`, proving that filenames cannot become the
  authority;
- several filenames containing `4K Remastered` or `UHD ... 1080p` whose actual
  streams are 720/1080 class, proving that simple token precedence also fails.

The wrong result currently propagates through:

1. the MediaInfo probe;
2. the hard-coded dimension classifier;
3. `res_cache.json`;
4. `media_files.resolution`;
5. Library filters and quality counts;
6. upgrade candidates;
7. Maintenance duplicate sorting and recommendations.

There is a second defect: duplicate ranking compares only resolution label,
release-source label, and file size. It does not know measured dimensions,
codec, bit depth, bitrate, duration, or audio configuration. For otherwise
equal files it treats the larger file as the best baseline, even when the
smaller file uses a more efficient codec. Size alone is not proof of quality.

## 2. Required outcome

The completed system must:

1. Persist measured local-file facts in SQLite as the only runtime authority.
2. Preserve the exact measured width and height instead of collapsing all
   evidence into one resolution string.
3. Keep filename quality tokens as separate claims, never as measured facts.
4. Derive a user-facing quality class through one documented and tested policy.
5. Display exact dimensions wherever an unusual derived class could hide useful
   information.
6. Make Library filters, statistics, upgrade candidates, cards, and Maintenance
   consume the same authoritative facts.
7. Remove `res_cache.json` from runtime authority.
8. Re-probe old records automatically through a versioned, resumable,
   non-blocking backfill.
9. Prevent automatic duplicate-removal recommendations when the comparison lacks
   sufficient measured facts or when neither file is objectively dominated.
10. Preserve all identity, metadata, artwork, curation, download, IPTV, and
    filesystem behavior not explicitly changed by this plan.

## 3. Non-negotiable architecture

### 3.1 Existing owners remain authoritative

- `services/catalog_store.py` remains the only SQLite schema and query owner.
- `services/catalog_repository.py` remains the catalogue repository and export
  boundary.
- `services/canonical_catalog.py` remains the canonical movie relationship
  owner.
- The existing library-reconciliation owner remains responsible for detecting
  new, changed, missing, and stable local files.
- `services/maintenance_audit.py` remains the duplicate and upgrade policy
  owner.
- Shared frontend cards remain shared; do not add page-specific quality logic.

Do not create:

- another SQLite database;
- another resolution cache;
- a second background scanner;
- route-specific quality calculations;
- a JSON file that competes with SQL;
- provider calls during local-file probing or migration;
- a compatibility route or feature flag preserving the old classifier.

### 3.2 SQL is the single file-facts authority

The authoritative record remains the physical file record owned by
`media_files`. Schema version 9 should add normalized facts to that owner rather
than creating a second competing file record.

The final column names may follow existing repository conventions, but the
schema must represent at least:

- measured video width;
- measured video height;
- video codec;
- video profile;
- video bit depth;
- video bitrate;
- frame rate;
- duration;
- primary audio codec;
- primary audio channels;
- primary audio bitrate;
- filename-declared quality;
- derived quality class;
- quality derivation source/status;
- file-facts version;
- probe status;
- probe timestamp;
- a bounded, redacted probe error code or category.

The existing `resolution` projection may remain as the derived compatibility
field only if it is stored and updated atomically with those facts in the same
row. It must never be writable through a separate path.

Do not duplicate identity or provider metadata into the new fields.

### 3.3 One probing owner

Create or extract one file-facts probe service that:

1. accepts one stable local file;
2. reads MediaInfo once;
3. selects the intended primary video and audio streams deterministically;
4. normalizes raw values;
5. applies the one approved quality-classification policy;
6. returns one complete immutable facts object;
7. performs no SQL write itself.

The repository/reconciliation owner writes that object transactionally.

The probe must distinguish:

- successful measured facts;
- no video stream;
- MediaInfo unavailable;
- inaccessible file;
- malformed/corrupt media;
- file changed while being probed;
- unsupported media/container.

Do not swallow all exceptions into `Unknown`. Store a safe error category while
keeping paths and sensitive operating-system details out of browser responses.

## 4. Quality model and product contract

### 4.1 Separate evidence from interpretation

Every local file has three different concepts:

1. **Measured dimensions**: exact stream width and height from MediaInfo.
2. **Filename claim**: tokens such as `2160p`, `1080p`, or `720p`.
3. **Derived quality class**: CP's compatibility bucket used by filters and
   coarse comparisons.

These values must not overwrite each other.

### 4.2 Classification policy

The implementation must freeze a dimension corpus and expected outcome before
changing production logic. The corpus must include at least:

- `3840 x 2160`;
- cropped 4K examples;
- `1920 x 1080`;
- `1920 x 800`;
- `1872 x 784`;
- `1856 x 800`;
- `1800 x 960`;
- `1744 x 816`;
- `1480 x 800`;
- `1434 x 984`;
- `1136 x 960`;
- `1280 x 720`;
- `1280 x 536`;
- `954 x 576`;
- `912 x 592`;
- standard 480 and sub-480 examples;
- portrait, square, rotated, anamorphic, and missing-dimension examples.

The policy must:

- classify `1800 x 960` and the confirmed active-picture 1080 release examples
  as 1080-class;
- not promote `954 x 576` or `912 x 592` to 1080 merely because the filename
  claims it;
- handle cinematic crop and unusual aspect ratio explicitly;
- use measured facts as the hard safety boundary;
- use a filename claim only as supporting evidence inside documented guardrails;
- expose an evidence conflict instead of silently lying when the claim and
  measurement disagree materially;
- keep exact dimensions available to the UI and duplicate policy.

The task must not replace the current thresholds with another unexplained list
of magic numbers. Named constants, rationale, and regression fixtures are
required.

### 4.3 Display contract

Normal standard files may continue to show a compact class such as `1080p`.

For non-standard dimensions or evidence conflicts, cards and Maintenance must
be able to show the exact measured dimensions, for example:

`1080-class - 1800 x 960`

or:

`Measured 954 x 576 - filename claims 1080p`

The exact wording may follow existing chip styles. Do not redesign unrelated
card content.

### 4.4 Failure and fallback contract

If a local file cannot be probed:

- retain its last successfully measured facts when the same file identity is
  still valid;
- otherwise expose the filename-derived value as an explicitly marked fallback;
- never present a filename fallback as measured;
- do not issue an automatic duplicate-removal recommendation involving that
  unresolved file;
- allow a later retry without changing movie identity.

## 5. Duplicate recommendation contract

Duplicate detection and duplicate identity safety remain separate from quality
comparison.

Identity must be proven by the existing accepted TMDB/IMDb/canonical rules
before any removal recommendation is possible.

Quality comparison must use measured facts and follow these rules:

1. Exact width and height are compared before the coarse quality label.
2. Duration must be within an approved tolerance before files can be treated as
   equivalent editions.
3. A file with missing or failed probe facts forces manual review.
4. AVC versus HEVC is a compatibility and efficiency difference, not automatic
   proof that one encode looks better.
5. 8-bit versus 10-bit is useful evidence, not automatic deletion authority.
6. Bitrate and file size are supporting evidence, not standalone proof.
7. Audio codec/channels must not be silently discarded from the comparison.
8. Different cuts, durations, aspect ratios, audio configurations, or subtitle
   evidence force review unless a separately tested policy proves dominance.
9. Automatic recommendation is allowed only when one candidate is objectively
   dominated under the complete approved policy.
10. The selected “keep” baseline must state why it won. “Larger file” alone is
    not an acceptable reason.

For the two current `The Monkey` files, both should become 1080-class with exact
`1800 x 960` dimensions. Their codec/bit-depth/bitrate difference should remain
visible, and CP should require review unless further measured evidence proves
one is safely dominated.

The play buttons already requested for manual comparison remain useful, but
manual playback is not a substitute for correct stored facts.

## 6. Schema migration contract

### 6.1 Version 8 to version 9

Implement one explicit `8 -> 9` migration in `CatalogStore`.

The schema migration must:

- run inside the existing `BEGIN IMMEDIATE` transaction;
- validate the exact approved version 8 source schema;
- reject partial version 9 objects/columns;
- add or rebuild the file-facts schema deterministically;
- preserve every existing row and every unrelated column;
- initialize new probe fields as legacy/unprobed, not as fabricated measured
  values;
- preserve the existing resolution string temporarily until that row is
  successfully re-probed;
- update `schema_version` only after all schema work and validation succeeds;
- run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`;
- produce a structured migration report;
- perform zero filesystem probing and zero provider/network calls.

The migration transaction must be fast and data-shape-only. File probing belongs
to the later resumable backfill, never to application startup migration.

### 6.2 Migration preservation proof

Before and after migration, compare logical row counts and SHA-256 digests for:

- every pre-existing `media_files` column;
- canonical movies and file relationships;
- provider snapshots;
- people, credits, genres, collections, writers, and keywords;
- manual matches and overrides;
- curation tables;
- qBittorrent documents/state;
- asset registry and relationships;
- catalogue metadata other than explicitly approved schema/migration keys.

Any unexplained difference fails the migration.

### 6.3 Failure injection and rollback

Tests must inject failure:

- before schema changes;
- during column/table creation;
- during row copy if a rebuild is used;
- before index creation;
- before schema-version update;
- during final validation;
- immediately after migration but before initialization completes.

Every failure must leave:

- schema version 8;
- the original schema;
- the original logical digests;
- no partial version 9 objects;
- integrity `ok`;
- zero foreign-key violations.

### 6.4 Upgrade-chain and restart behavior

Prove:

- fresh catalogues create the exact version 9 schema;
- valid version 8 catalogues migrate once;
- supported version 6/7 catalogues follow the existing ordered chain through
  version 8 and then version 9;
- invalid or partial schemas are rejected;
- a second startup performs no migration rewrite;
- opening a completed version 9 catalogue performs no probe or backfill inside
  schema initialization.

## 7. Cache retirement

`res_cache.json` must stop being read or written by the runtime.

The new cache key is the authoritative SQL row itself:

- path key;
- observed file size;
- observed modification time;
- file-facts version;
- classifier version if separate from the probe version.

When all match and the prior probe succeeded, no re-probe is required. If any
changes, the row becomes pending and is probed through the same owner.

Do not copy legacy `res_cache.json` results into measured columns. Its contents
may be used only as Gate 0 comparison evidence. The obsolete runtime code should
be removed after tests prove SQL ownership.

The physical legacy cache file is a user artifact. Do not delete it during code
implementation or rehearsal. After successful live acceptance, report that it
is unused and obtain explicit permission before deleting it.

## 8. Versioned backfill contract

### 8.1 General behavior

The version 9 schema marks old rows as unprobed. A bounded background coordinator
then:

1. selects stale rows through SQL;
2. verifies that each path still belongs to a configured movie root;
3. checks stability using size and modification time;
4. probes with bounded concurrency;
5. rechecks size and modification time after probing;
6. discards the result if the file changed during the probe;
7. writes a complete row update transactionally;
8. advances `catalog_generation` once per committed batch;
9. invalidates Library, statistics, ownership, upgrade, and Maintenance
   projections through existing generation mechanisms;
10. records progress and bounded failure summaries.

### 8.2 Resumability and idempotence

The backfill must survive:

- normal restart;
- forced interruption between batches;
- one corrupt file;
- a missing file;
- a locked/inaccessible file;
- a file changing during probing;
- MediaInfo being temporarily unavailable.

Completed rows with unchanged path/size/mtime/version must not be probed again.
A second complete pass must produce:

- zero changed file-facts rows;
- zero unnecessary generation increment;
- identical logical digests;
- zero provider calls.

### 8.3 Runtime behavior

- Startup must remain usable without waiting for full backfill.
- Library reads must remain bounded and SQL-only.
- The backfill must not monopolize SQLite or media disks.
- Batch size and concurrency must be explicit and measured.
- Progress belongs in the existing Maintenance/operational surface.
- The current duplicate group and filename/measurement conflicts may be
  prioritized, but there must still be one general backfill implementation.
- Do not implement a one-off repair specifically for `The Monkey`.

### 8.4 Generation behavior

File-facts changes affect Library and Maintenance behavior, so they must use the
existing `catalog_generation`.

Do not create a second browser-visible generation unless measurements prove the
existing generation cannot safely support bounded batches and Dante approves a
separate architecture change.

## 9. Read and write path conversion

All existing resolution consumers must be inventoried and moved together.

At minimum:

- library reconciliation and new-file ingest;
- file rename and mutation paths;
- `media_files` upsert/import/export;
- Library cards and File View;
- Library quality and resolution filters;
- quality sorting;
- Home statistics;
- Maintenance audit;
- duplicate ranking and reasons;
- upgrade-candidate queries;
- Discover/List/Home/AI owned-file chips;
- API contracts and frontend utilities;
- rollback export and shadow comparison;
- tests and fixtures.

Filename-only torrent/source results remain a different domain because no local
file exists yet. They may continue to expose a release-name claim, but the API
and UI must not present it as measured local-file quality.

Release-source parsing (`WEB-DL`, `Blu-ray`, `Remux`, and similar) also remains a
filename claim unless a later separately approved probe model replaces it.

## 10. Gate plan

### Gate 0 - Freeze baseline without writes

Record:

- Git status, current commit, and all dirty-file ownership;
- application/schema version;
- catalogue path and size;
- `catalog_generation` and `curation_generation`;
- every table count;
- aggregate logical digests;
- SQLite integrity and foreign-key status;
- rollback export verification;
- current Library/Home/Maintenance counts;
- duplicate and upgrade counts;
- current `The Monkey` API rows and measured stream facts;
- all filename-claim versus stored-resolution mismatch counts;
- current startup and Library response timings;
- current `res_cache.json` version/count without modifying it.

No live catalogue write, repair, rescan, provider refresh, or process restart is
allowed in Gate 0.

**Exit gate:** a redacted baseline artifact exists and every source path is
identified.

### Gate 1 - Freeze file-facts and recommendation contracts

Create the dimension corpus, probe-result model, UI wording, fallback behavior,
and duplicate dominance matrix as executable tests.

**Exit gate:** `The Monkey` and every boundary case has an explicit expected
result before production logic changes.

### Gate 2 - Implement and prove schema version 9

Implement the fresh schema, `8 -> 9` migration, validation, report, failure
checkpoints, upgrade chain, export, and restore behavior against disposable
catalogues only.

**Exit gate:** all migration, rollback, digest, integrity, and second-start tests
pass with provider and filesystem access blocked.

### Gate 3 - Implement the authoritative probe owner

Extract one MediaInfo adapter, normalized facts object, classifier, and error
contract. Remove competing resolution derivations from local-file paths.

**Exit gate:** unit and integration fixtures pass; no SQL or UI path independently
reimplements classification.

### Gate 4 - Implement resumable backfill and new-file ingest

Add bounded stale-row selection, stable-file probing, atomic batch updates,
progress, retry behavior, cancellation, generation invalidation, and
idempotence.

**Exit gate:** interruption, changed-file, corrupt-file, retry, resume, and
second-pass tests pass on disposable roots.

### Gate 5 - Convert projections and recommendation policy

Move Library, statistics, upgrade, cards, Maintenance, duplicates, and exports
to the authoritative facts. Retire runtime `res_cache.json` use.

**Exit gate:** all page/API parity fixtures consume one SQL file-facts contract;
uncertain comparisons cannot become automatic removal recommendations.

### Gate 6 - Complete isolated verification

Run:

- focused classifier/probe tests;
- schema migration and rollback tests;
- catalogue repository/export/restore tests;
- reconciliation and backfill tests;
- Library filter/statistics/upgrade tests;
- Maintenance and duplicate-policy tests;
- frontend Node tests;
- the complete Python suite with `CP_TEST_MODE=1` and a unique temporary
  `CP_TEST_ROOT`;
- `npm.cmd run build`;
- desktop Playwright against a disposable server and disposable data/movie
  roots.

Do not run broad tests against the live catalogue, movie root, qBittorrent
profile, provider data, or artwork registry.

**Exit gate:** all suites pass, no test touched live state, and Git diff contains
only approved files plus pre-existing user changes.

### Gate 7 - Rehearse on a verified live-catalogue clone

Using the existing backup tooling:

1. create or use a verified online backup without stopping the live application;
2. restore it to a disposable location;
3. prove exact pre-migration parity;
4. migrate the clone to version 9;
5. run the complete file-facts backfill against an isolated movie corpus or a
   deliberately read-only controlled mapping;
6. prove restart/resume and second-pass idempotence;
7. compare all protected table digests;
8. verify Library/Home/Maintenance/upgrade/duplicate behavior;
9. run browser acceptance against the migrated clone;
10. rehearse restoration of the pre-migration backup.

The clone must never point broad mutation or test code at the real movie roots.
If real media files are used read-only for probe verification, path access must
be explicit, bounded, and separated from all mutation actions.

**Exit gate:** a complete evidence report exists with zero unexplained
differences.

### Gate 8 - Stop for Dante's live-rollout approval

The implementation task must stop here and report:

- exact schema diff;
- migration and rollback evidence;
- protected-table digests;
- backfill counts, failures, duration, and idempotence;
- before/after mismatch matrix;
- test/build/browser results;
- expected live duration and disk load;
- exact live backup, rollout, abort, and restore commands;
- remaining risks.

No wording in the task prompt pre-approves a live schema migration or live
backfill.

### Gate 9 - Controlled live rollout after separate approval

Only after Dante explicitly approves:

1. stop file mutations/download imports or prove they are quiescent;
2. capture a fresh baseline;
3. create and verify a fresh timestamped backup;
4. rehearse restoring that exact backup;
5. migrate the live catalogue transactionally;
6. verify schema, integrity, foreign keys, counts, and protected digests before
   starting backfill;
7. start the bounded background backfill;
8. monitor progress and failures;
9. verify `The Monkey`, Library, Home, Maintenance, upgrades, duplicates,
   playback, rename, deletion, and new-file ingest;
10. complete a second start and idempotence check;
11. retain the backup until Dante accepts the result.

An unexplained mismatch stops the rollout. Do not attempt an improvised repair
on the live catalogue.

**Completed 2026-07-27:** Dante separately approved the rollout. All eleven
steps passed against the 3,783-row live catalogue. The normal backend was
restored on port 5000, the qBittorrent import monitor is healthy, and the exact
backup remains at
`C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260727T204639Z.zip`.
Detailed results are in the Gate 9 addendum of the evidence report.

## 11. Required automated coverage

### Classifier and probe

- all frozen dimension-corpus cases;
- filename agreement and disagreement;
- multiple video/audio tracks;
- rotated and anamorphic metadata;
- missing dimensions;
- no video track;
- unavailable MediaInfo;
- corrupt/inaccessible file;
- stable and changing size/mtime;
- safe error redaction.

### Schema and migration

- exact fresh version 9 columns and indexes;
- valid version 8 migration;
- supported older upgrade chain;
- source-schema rejection;
- partial-schema rejection;
- failure at every checkpoint;
- preserved counts and digests;
- integrity and foreign keys;
- no network/filesystem probe during migration;
- no rewrite on second startup.

### Backfill

- bounded batches and concurrency;
- resume after interruption;
- retry after transient failure;
- permanent failure isolation;
- missing/moved/changed file;
- atomic row update;
- one generation advance per changed batch;
- no generation advance on an idempotent pass;
- no provider call;
- no live-root access in tests.

### Behavior parity

- Library resolution filters and quality sorting;
- Home/Library/Maintenance count agreement;
- upgrade candidates;
- cards on Library, Discover-owned, Lists, Home, and AI Control;
- File View;
- rename and deletion;
- new-file ingest;
- rollback JSON export and shadow reconstruction;
- cache invalidation by catalog generation.

### Duplicate safety

- same dimensions/source/codec;
- same dimensions with AVC versus HEVC;
- 8-bit versus 10-bit;
- different duration/cut;
- different audio channels/codecs;
- missing probe facts;
- filename/measurement conflict;
- lower measured resolution;
- identity conflict;
- editable user selection;
- bulk recommended selection contains only genuinely recommended candidates.

## 12. Performance and operational budgets

Gate 0 must measure the current machine before freezing exact limits. At minimum:

- schema migration must remain a short transactional metadata/data-shape
  operation and must not probe files;
- normal startup must not wait for whole-library backfill;
- Library must remain usable during backfill;
- one failed media file must not stop a batch;
- SQLite lock waits must remain bounded;
- disk probing concurrency must default conservatively;
- backfill progress writes must be batched;
- ordinary Library reads must not open media files;
- unchanged files must not be re-probed.

Record migration time, per-file probe distribution, batch transaction time,
total backfill time, failures, retries, SQLite size change, and generation
changes in the rehearsal evidence.

## 13. Explicit stop conditions

Stop and report instead of continuing if:

- the current schema is not the expected valid version 8 shape;
- integrity or foreign-key checks fail;
- the worktree contains overlapping changes whose ownership cannot be
  determined;
- a test or tool reaches the live catalogue in test mode;
- migration changes an unrelated table digest;
- rollback reconstruction differs;
- provider/network access occurs during migration or local-file probing;
- a probe needs to modify a movie file;
- the backfill cannot resume idempotently;
- recommendation policy would automatically delete an uncertain comparison;
- live baseline differs from rehearsal assumptions;
- credentials or sensitive paths would be exposed;
- any live migration/backfill is requested without Dante's separate approval.

## 14. Scope boundaries

Included:

- local movie-file probe facts;
- schema version 9;
- cache retirement;
- background backfill;
- quality display/filter/statistics;
- upgrade detection;
- duplicate ranking and recommendation safety;
- regression coverage and rehearsal evidence.

Excluded unless separately approved:

- changing TMDB/Plex identity authority;
- changing release-source parsing beyond separating claims from measurements;
- provider metadata refresh;
- transcoding or modifying media;
- automatic quality scoring by AI;
- perceptual video-quality analysis;
- subtitle-content analysis;
- mobile/responsive redesign;
- unrelated card redesign;
- deleting live files;
- live schema migration or backfill before Gate 8 approval;
- commit, push, reset, checkout, or Git configuration changes.

## 15. Required implementation artifacts

The implementation task must leave:

- this plan, updated only if approved decisions change;
- one authoritative-path ownership note;
- schema version 9 tests and fixtures;
- classifier/probe fixtures;
- migration and rollback evidence;
- backfill/rehearsal evidence;
- updated SQL parity matrix after acceptance;
- exact commands and paths used;
- a final report distinguishing isolated rehearsal from live rollout.

## 16. Completion definition

Code implementation is complete only when:

- schema version 9 is transactionally proven on isolated catalogues;
- the old cache is no longer a runtime authority;
- raw measured facts are persisted and projected consistently;
- old rows are automatically and idempotently backfilled;
- `The Monkey` is correctly classified in the rehearsal;
- uncertain duplicates cannot be recommended automatically;
- all focused and complete isolated suites pass;
- production build and disposable desktop Playwright pass;
- rollback is rehearsed successfully;
- no live catalogue or movie file was changed.

Live rollout is a separate completion gate and requires Dante's explicit
approval after reviewing the rehearsal evidence.
