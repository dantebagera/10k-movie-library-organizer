# New Task Prompt: Media File Facts and Resolution

Use the following prompt in a new Codex task whose workspace is:

`C:\Users\dante\Desktop\cinema paradiso`

---

Your name is lam3y. My name is Dante.

Implement and rehearse the approved Cinema Paradiso media-file-facts and
resolution architecture. This prompt authorizes code changes, isolated schema
migration work, automated tests, a production frontend build, disposable
desktop browser verification, and migration/backfill rehearsal against verified
disposable catalogue copies.

This prompt does **not** authorize migration or backfill of the live catalogue,
modification of real movie files, deletion of the legacy cache file, deletion of
duplicates, Git staging, a commit, a push, a reset, a checkout, or Git
configuration changes. Stop after the complete rehearsal report and wait for my
separate approval before any live rollout.

Read this plan completely before acting and treat it as the authoritative
contract:

`C:\Users\dante\Desktop\cinema paradiso\docs\plans\media-file-facts-resolution-zero-regression-plan.md`

Also read the current catalogue authority and parity documents:

`C:\Users\dante\Desktop\cinema paradiso\docs\plans\writer-keyword-search-authoritative-paths.md`

`C:\Users\dante\Desktop\cinema paradiso\docs\sql-migration-parity-matrix.md`

## Required outcome

Replace Cinema Paradiso's lossy resolution-only model with one authoritative,
versioned SQL file-facts model.

- Persist measured width, height, video codec/profile/bit depth/bitrate/frame
  rate, duration, primary audio facts, filename quality claim, derived quality
  class, probe status, and facts version.
- Keep measured facts, filename claims, and derived quality class separate.
- Correctly handle cropped and unusual-aspect 1080 releases including the
  confirmed `1800 x 960` `The Monkey` files.
- Do not promote genuinely low-resolution files merely because their names say
  `1080p`.
- Remove `res_cache.json` from runtime authority.
- Add a resumable, bounded, idempotent background backfill for old SQL rows.
- Make Library, Home, cards, filters, statistics, upgrades, Maintenance, and
  duplicate policy consume the same SQL facts.
- Prevent automatic duplicate-removal recommendations when facts are missing,
  conflicting, or do not prove that one file is objectively dominated.

## Required ownership

- `services/catalog_store.py` remains the only SQLite schema/query owner.
- `services/catalog_repository.py` remains the repository/export boundary.
- `services/canonical_catalog.py` remains canonical relationship authority.
- Existing reconciliation remains the file-change/new-file owner.
- `services/maintenance_audit.py` remains duplicate/upgrade policy owner.
- Shared cards remain shared.

Do not add another database, JSON authority, resolution cache, scanner,
route-specific classifier, compatibility route, or feature flag.

The version 8 to version 9 schema migration must be transactional,
filesystem-free, provider-free, failure-injected, integrity-checked,
foreign-key-checked, digest-verified, and idempotent. It marks old rows as
unprobed; it must not inspect thousands of files inside startup migration.

The backfill runs afterward in bounded background batches, verifies file
stability before and after probing, writes complete facts atomically, advances
the existing catalog generation only for changed batches, resumes after
interruption, and performs no work on an unchanged second pass.

## Required execution order

1. Inspect Git status and overlapping diffs. Preserve all existing user work.
2. Perform Gate 0 read-only baseline capture. Do not restart or mutate the live
   runtime/catalogue.
3. Freeze the executable dimension corpus, fallback behavior, and duplicate
   dominance matrix.
4. Implement and prove fresh schema version 9 and the version 8 to 9 migration
   on temporary catalogues.
5. Implement the one authoritative MediaInfo probe/facts/classifier owner.
6. Implement resumable backfill and new/changed-file ingestion.
7. Convert every SQL/API/UI consumer together.
8. Retire runtime reads/writes of `res_cache.json` without deleting the physical
   file.
9. Run focused tests.
10. Run the complete Python suite with `CP_TEST_MODE=1` and a unique temporary
    `CP_TEST_ROOT`.
11. Run frontend Node tests and `npm.cmd run build`.
12. Run desktop Playwright against a disposable server, catalogue, user-data
    root, and movie root.
13. Create/verify/restore a catalogue backup into an isolated rehearsal root.
14. Rehearse migration, backfill, restart/resume, second-pass idempotence,
    browser behavior, and rollback.
15. Write the evidence report and stop for my approval.

## Protected live state

The worktree is dirty. Inspect it before editing. Do not revert, overwrite,
reformat, or stage unrelated changes.

Do not run broad tests, migrations, backfills, repair tools, performance tools,
or mutation routes against:

- the live SQLite catalogue;
- `E:\Movies`;
- the live user-data root;
- the live qBittorrent profile;
- IPTV/provider data;
- the live artwork registry;
- the normal port-5000 runtime.

Read-only Gate 0 observations must remain bounded and must not trigger a rescan,
provider refresh, catalogue activation, or application import that mutates
state.

Tests must use disposable operating-system temporary roots. Migration tests
must block provider/network access and file probing. Browser tests must use a
disposable desktop fixture, not mobile/responsive work.

## Required regression evidence

At minimum, prove:

- exact fresh version 9 schema;
- valid version 8 migration and supported older upgrade chain;
- rejection of partial/invalid schemas;
- rollback at every injected migration checkpoint;
- preservation of every unrelated table count and logical digest;
- integrity `ok` and zero foreign-key violations;
- zero provider calls and zero file probes during schema migration;
- exact dimension/classification corpus including `1800 x 960`;
- filename/measurement conflict handling;
- multiple/missing/corrupt streams and safe probe failures;
- changed-file race rejection;
- bounded backfill, resume, retry, cancellation, and idempotence;
- no generation change on an unchanged second pass;
- Library/Home/Maintenance/upgrade parity;
- shared-card quality parity;
- rename, deletion, and new-file ingestion behavior;
- duplicate safety for codec, bit-depth, bitrate, duration, audio, identity, and
  missing-fact differences;
- rollback export and shadow reconstruction;
- no live-state access by tests.

## The Monkey acceptance case

In the isolated rehearsal, both copies must be measured as `1800 x 960` and
classified as 1080-class. The x264 8-bit and HEVC/x265 10-bit facts must remain
visible. The smaller HEVC file must not be automatically declared worse merely
because it is smaller, and neither file may become an automatic deletion
recommendation unless the approved dominance policy proves that conclusion.

Plex matched/unmatched status must not alter measured resolution or encode
quality.

## Mandatory stop conditions

Stop and report immediately if:

- the live/source schema is not the expected valid version 8 shape;
- integrity or foreign-key checks fail;
- an unrelated digest changes;
- rollback reconstruction differs;
- a test reaches live state;
- migration or probing makes a provider call;
- probing would modify a media file;
- the backfill is not resumable and idempotent;
- an uncertain duplicate can be automatically recommended;
- an overlapping dirty change cannot be preserved;
- completion would require live migration/backfill.

## Completion report

Lead with any unresolved correctness or data-safety issue.

Report:

- files and authoritative owners changed;
- exact schema and migration behavior;
- cache retirement behavior;
- classifier and duplicate-policy contract;
- backfill batching, duration, failures, resume, and idempotence;
- protected-table count/digest comparisons;
- integrity, foreign-key, export, restore, and rollback results;
- exact focused/full Python, Node, build, and Playwright evidence;
- `The Monkey` rehearsal result;
- expected live rollout time/load;
- exact proposed live backup, migration, abort, and restore procedure;
- remaining risks.

Do not claim live completion. Stop after isolated rehearsal and wait for my
explicit approval.

---
