# Gate 10 retry verification — mandatory stop before browser or media copy

## Outcome

The first Gate 10 retry after corrective Gate 10A was stopped before the
browser was opened and before any Rao Bahadur file was copied. A new mandatory
stop condition appeared during normal startup: the authoritative media
generation changed from 7,629 to 7,635 before the representative workflow
began.

CP PID 45036 was stopped immediately. The changed catalog was preserved for
diagnosis, and the fresh pre-start catalog backup was restored byte-for-byte.
qBittorrent remained PID 42792 on port 8686 and was not restarted or changed.

## Fresh baseline and backup

- Branch: `master`
- HEAD: `eaf6a749133fc3dec279f82f707719a3e5ed1bf0`
- Remote: `https://github.com/dantebagera/cinema-paradiso.git`
- Repository owner/current user: `DANTE-PCX\dante`
- Fresh backup:
  `C:\Users\dante\AppData\Local\Temp\cp-gate10-retry-backup-6f5d5c4f9c594875b39c3c0e4eb74c90`
- Backup files: 60
- Backup bytes: 249,992,608
- Backup catalog SHA-256:
  `C8E0F52C65C9A61D8CEF45A522EA897876C73B889783999E3A17EBB90FA47961`

Before startup, port 5000 was free, qBittorrent alone listened on port 8686,
the approved destination was absent, and the source video remained
2,989,813,923 bytes with SHA-256
`3DFCF693F87A50822BCFF340D4308BB0039749C7EF6EF5A21176DC623BF90587`.

## Stop evidence

The normal `.venv` backend acquired the catalog writer lease and listened as
PID 45036. Its first ingestion status showed:

- observer implementation `watchdog-native`, started and alive;
- supported, online local `E:\Movies` root;
- coordinator queue depth 0 of 4,096;
- no active work, no pending work, and no dirty root;
- media generation 7,635 instead of the 7,629 pre-start baseline.

There was no observer storm, artwork startup worker, traceback, or queue error.
The generation change itself satisfied the plan's unexplained-mutation stop
condition.

## Exact diagnosis

`LibraryStartupCatchup` owns offline startup catch-up. Its operational
checkpoint is catalog metadata key `library_directory_revisions_v1`. The live
schema-v10 catalog predates this key. When that key is missing,
`LibraryStartupCatchup.run_once()` intentionally calls the authoritative
`reconcile_all_now()` global recovery path.

The isolated Gate 7 test `test_first_snapshot_uses_authoritative_full_recovery`
explicitly requires that behavior for a new checkpoint. It did not include the
real deployment-transition case: an existing populated catalog with a valid
library inventory but no directory-revision checkpoint.

The global recovery found no count changes in any movie/catalog table, but it
reprocessed this existing manually accepted file:

`E:\Movies\The Loved Ones (2009) [BluRay] [1080p] [YTS.AM]\The.Loved.Ones.2009.1080p.BluRay.x264-[YTS.AM].mp4`

The file size and modification time exactly match the existing inventory. The
only semantic database differences were operational timestamps and an identity
revision:

- `media_files.identity_revision`: 120 to 122;
- `media_files.probed_at`, `observed_at`, and `updated_at`: refreshed;
- `identity_decisions.revision`: 120 to 122, with the same timestamp-only file
  changes;
- `provider_movie_snapshots.updated_at`: refreshed;
- `tmdb_movies.updated_at`: refreshed;
- `canonical_movies.identity_revision`: 120 to 122 and `updated_at` refreshed.

All provider and file JSON fields other than those timestamps/revision values
were identical. Nevertheless, six separate writes advanced global, media, and
canonical-media generations from 7,629 to 7,635. The row counts for
`media_files`, `canonical_movies`, `identity_decisions`,
`provider_movie_snapshots`, and `tmdb_movies` did not change.

This is not the directory-event storm fixed in Gate 10A. It is a missing
deployment-transition contract plus non-idempotent enrichment writes during a
first-checkpoint global recovery.

## Rollback proof

The stopped changed catalog was preserved as
`stopped-current-catalog.sqlite` with SHA-256
`020FA4C613C2981677034DAA2EB65DAEC30F98BA7D930C1952D8C6BDD14798B0`.
Its `PRAGMA quick_check` was `ok` and it had zero foreign-key errors.

The production catalog was then restored to SHA-256
`C8E0F52C65C9A61D8CEF45A522EA897876C73B889783999E3A17EBB90FA47961`.
It has no WAL or SHM sidecar. Configuration, all 55 backed-up app-metadata
files, and all three curation documents match the fresh backup. Zero active
metadata assets were created or modified during the attempt.

Final state:

- CP is stopped and port 5000 is free;
- qBittorrent remains PID 42792 on port 8686;
- Rao Bahadur source hash and size are unchanged;
- the approved destination remains absent;
- no browser/UI action occurred;
- nothing was staged, committed, pushed, or released.

## Required Gate 10B correction

The saved plan must add a deployment-transition gate before another live
retry. The correction must remain in the existing startup catch-up,
coordinator, metadata, and repository owners.

Required proof:

1. Add an isolated populated-catalog fixture with a valid authoritative library
   inventory but no `library_directory_revisions_v1` key.
2. Prove the first upgraded startup does not publish, reprobe, re-enrich, or
   advance a media generation for unchanged accepted files.
3. Preserve conservative offline add/delete/rename recovery. Missing the new
   checkpoint must not be solved by blindly declaring the live root current.
4. Make provider/enrichment persistence idempotent: timestamp-only or
   revision-only rewrites of semantically unchanged accepted data must not
   create six Movie View generations.
5. Prove current-checkpoint startup still skips work, a genuinely changed file
   is reconciled once, and no known path normally causes a global walk.
6. Re-run the Gate 7, Gate 8, and Gate 10A qualification before requesting the
   exact live retry again.

No schema migration, durable Windows file ID, second startup scanner, second
inventory, or alternative catalog owner is justified by this result.

## Gate 10B completion

Gate 10B completed this correction in the existing startup catch-up,
coordinator, metadata, and repository owners. Its isolated populated-upgrade
fixture proves zero probe, provider, path reconciliation, or Movie View
generation change for unchanged accepted files while preserving conservative
first-checkpoint recovery. Operational timestamp/revision persistence is now
generation-idempotent, material changes still advance generation, and bounded
directory deletion preserves records outside the changed root.

The full 1,062-test backend suite, 76 Node tests, 49 desktop Playwright tests,
package/player checks, frozen performance budgets, and 30-minute native
observer soak pass. See [gate-10b-verification.md](gate-10b-verification.md)
and [gate-10b-performance.json](gate-10b-performance.json). Only the exact
live Gate 10 retry remains, and it still requires separate approval.

Dante subsequently approved that exact retry. It passed after a pre-copy stale
`dist` deployment was stopped, rolled back, and rebuilt from the qualified
source. The live external addition produced one final SQL card, one post-commit
event, preserved desktop state, and an exact cleanup rollback. See
[gate-10-final-verification.md](gate-10-final-verification.md).
