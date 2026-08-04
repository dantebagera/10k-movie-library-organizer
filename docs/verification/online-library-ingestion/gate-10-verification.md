# Gate 10 verification — aborted before media copy; SQL rollback complete

## Outcome

Gate 10 did not pass. The live acceptance was stopped at the plan's mandatory
stop boundary before any representative media or sidecar was copied into the
library.

Two independent startup mutations were observed:

1. the native observer filled the coordinator's entire 4,096-entry queue with
   `observer:modified` directory work under the configured `E:\Movies` root;
2. the existing one-second startup artwork backfill downloaded 36 artwork
   assets while CP was running.

The production SQL catalog was restored byte-for-byte from the pre-start
backup. Dante subsequently approved exact-file cleanup with corrective Gate
10A. The 36 newly created cache files were checksum-verified and moved out of
the active metadata root into the Gate 10 backup, preserving recovery.

## Approved representative item

- Source folder: `G:\0t\Rao Bahadur (2026) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.GG - YTS.BZ]`
- Video: `Rao.Bahadur.2026.1080p.WEBRip.x265.10bit.AAC5.1-[YTS.GG - YTS.BZ].mp4`
- Video size: `2,989,813,923` bytes
- Video SHA-256 before and after the aborted run:
  `3DFCF693F87A50822BCFF340D4308BB0039749C7EF6EF5A21176DC623BF90587`
- Approved destination:
  `E:\Movies\Rao Bahadur (2026) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.GG - YTS.BZ]`
- Destination absent before start and after rollback: yes
- Rao Bahadur catalog rows before start, at stop, and after restore: `0`

No movie, subtitle, image, or text sidecar was copied, moved, renamed, or
deleted.

## Ownership and bounded start

- Branch: `master`
- HEAD: `eaf6a749133fc3dec279f82f707719a3e5ed1bf0`
- Remote: `https://github.com/dantebagera/cinema-paradiso.git`
- CP listener during the bounded run: PID `48100`, port `5000`
- qBittorrent remained PID `42792`, port `8686`, and was not restarted or
  changed
- CP acquired the catalog writer lease before the check
- CP was stopped immediately after the stop condition; port `5000` is no
  longer listening

The repository owner SID differs from the transient runner SID. Read-only Git
proof therefore used a per-command `safe.directory` override; global or local
Git configuration was not changed.

## Stop evidence

The first ingestion status checks, before any representative file copy, showed:

- observer implementation `watchdog-native`, alive, supported local root;
- coordinator queue depth `4096` of `4096`;
- a dirty root marker;
- active work type `directory` with reason `observer:modified`.

This is both an unexplained-mutation stop and a bounded-queue stop. Continuing
would have hidden the representative workflow behind unrelated recursive
directory scans and invalidated the timing and no-global-walk acceptance.

## Catalog mutation and rollback

Pre-start backup directory:

`C:\Users\dante\AppData\Local\Temp\cp-gate10-live-backup-66696580e47b44a3bfb7afc767374686`

The backup contains the catalog, configuration, app metadata, curation JSON,
logs, and a preserved copy of the aborted catalog plus its WAL/SHM files.

| Fact | Pre-start backup | Aborted catalog | Restored catalog |
|---|---:|---:|---:|
| `media_files` | 3,795 | 3,795 | 3,795 |
| `canonical_movies` | 3,780 | 3,780 | 3,780 |
| `canonical_movie_files` | 3,780 | 3,780 | 3,780 |
| `provider_movie_snapshots` | 7,508 | 7,508 | 7,508 |
| `media_assets` | 23,181 | 23,217 | 23,181 |
| global generation | 30,626 | 30,673 | 30,626 |
| media generation | 7,629 | 7,676 | 7,629 |
| canonical media generation | 7,629 | 7,676 | 7,629 |
| asset generation | 23,658 | 23,718 | 23,658 |
| `PRAGMA quick_check` | `ok` | `ok` | `ok` |
| foreign-key errors | 0 | 0 | 0 |

The pre-start and restored catalog SHA-256 values are identical:

`C8E0F52C65C9A61D8CEF45A522EA897876C73B889783999E3A17EBB90FA47961`

The transient zero-length WAL and 32 KiB SHM created by the final read-only
SQLite verification were removed only after CP was confirmed stopped and the
main database hash was revalidated. The production catalog currently has no
WAL/SHM sidecars.

The aborted catalog is preserved for diagnosis with SHA-256:

`281357D29ED26A4DD9B1FC26A3ADE5A2D132AFFEDC76EE61795EDC6977517AC4`

Configuration matched the backup exactly. All copied `app_metadata` documents
and curation JSON documents had zero content changes. Current SQL has no Rao
Bahadur row and no reference to any of the 36 newly created cache checksums.

## Confirmed owners and causes

### Observer queue flood

`services/library_observer.py` owns native event adaptation. Its
`_RootEventHandler.on_any_event()` accepts directory `modified` events, and
`LibraryObserverAdapter._emit()` submits every extant directory directly to
`reconcile_directories()`.

`services/library_ingestion.py` owns the queue and recursive work. It coalesces
only identical keys, does not collapse parent/child directory hints, and
`reconcile_directories_now()` performs `os.walk()` for every accepted directory.
The 4,096 unique pending directories therefore exhausted the bounded queue.

### False media-generation churn

Every directory reconciliation calls `save_library_inventory()` even if the
inventory is unchanged. `AppMetadataStore._write_json()` calls
`CatalogRepository.replace_document()`, which always bumps a generation.
`CatalogRepository._document_domain()` classifies every `app_metadata/*`
document—including operational `library_inventory.json`—as media. The 47
processed directory jobs therefore caused exactly 47 false global/media/
canonical-media generation increments without changing any movie row.

### Startup artwork mutation

`app.py` starts `_run_startup_artwork_backfill()` on a one-second timer for every
normal launch. That owner queues all missing owned movie/person artwork and
runs four download workers. During this bounded run it created 36 ready SQL
asset rows and 36 novel files: 5 posters and 31 portraits, totaling 703,870
bytes. Their creation times fall inside the CP run. None of their checksums
existed in the pre-start catalog.

The SQL restore intentionally did not guess at filesystem cleanup. After Dante
approved the exact manifest, all 36 files were hash-verified and moved to:

`C:\Users\dante\AppData\Local\Temp\cp-gate10-live-backup-66696580e47b44a3bfb7afc767374686\orphan-assets-quarantine`

The quarantine contains 36 files and 703,870 bytes with zero checksum
mismatches. Zero manifest files remain in the active metadata asset root. The
cleanup is recoverable and no unrelated asset directory was removed.

## Required correction before another live attempt — completed in Gate 10A

This is a correction to the implementation plan, not permission to layer on a
second watcher, importer, inventory owner, generation source, or asset worker.

1. Correct the existing observer adapter so directory metadata noise is ignored
   or reduced to the smallest relevant movie/sidecar path, and collapse parent
   and child directory hints before queue admission.
2. Correct the existing coordinator so targeted directory work never performs
   an unchanged inventory document write and never turns operational inventory
   bookkeeping into a Movie View media generation.
3. Separate the existing startup artwork backfill from live-ingestion
   acceptance. It must not mutate the catalog or asset filesystem before the
   bounded pre-state is recorded. Asset-generation changes must not masquerade
   as media-card publication.
4. Add an isolated event-storm regression reproducing more than 4,096 unique
   directory modifications and prove bounded collapse, no root walk, no false
   media generation, and clean shutdown.
5. Add an isolated clean-start regression proving no background asset/catalog
   mutation before the representative ingestion workflow.
6. Re-run Gates 3, 7, and 8 after the correction. Only then request approval to
   remove the exact 36 orphan files and retry Gate 10.

No schema migration, durable Windows file ID, duplicate pipeline, or second
catalog source was required. Gate 10A implemented these corrections in the
existing authoritative owners and passed the full isolated regression,
performance, package, native-player, and 30-minute observer-soak qualification.
The exact cleanup also completed: the 36 files are checksum-verified in the
recoverable backup quarantine and zero remain in the active asset root.

## Baseline comparison and unresolved risk

Gate 10A supersedes Gate 8 as the last passing isolated regression baseline:
1,059 backend, 76 Node, 49 desktop Playwright, 98 packaged/native tests, the
portable build, native-player smoke, performance checks, and the 30-minute soak
all pass. Gate 10 still did not reach browser/UI timing, final-card publication,
or live cleanup acceptance, so those live checks remain unproven.

The observer storm, false media-generation churn, startup asset mutation, and
active-root orphan-file risks are corrected and regression-tested. The only
remaining acceptance risk is whether the corrected pipeline behaves the same
way against the exact approved live root and desktop workflow. That requires a
separately approved Gate 10 retry under the original stop conditions.
