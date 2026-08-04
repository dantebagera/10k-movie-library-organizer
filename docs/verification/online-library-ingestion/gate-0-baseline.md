# Gate 0 baseline and ownership proof

Date: 2026-07-31 (Africa/Cairo)

Scope: Gate 0 only. This package records the current repository, owners, runtime, tests, performance, and desktop behavior. It contains no application, configuration, dependency, catalog, media, process, or Git-state implementation change.

## Gate result

Gate 0 is complete for isolated/code/runtime evidence and is stopped at the approval boundary.

The uncomfortable result is that the current application does not satisfy the proposed final-card or no-flicker contracts:

1. Movie View publication is gated only by accepted identity, not by stable file facts, successful probing, complete required metadata, poster readiness, canonical projection readiness, or one atomic final commit.
2. qBittorrent applies accepted TMDB identity with `probe=False` before starting a forced global reconciliation.
3. both manual and quiet/background Library refreshes set the foreground loading flag, and the grid is rendered only when that flag is false. An isolated 1,500-file rescan produced zero mounted `article` cards and the visible placeholder `Rescanning library folders...`.
4. qBittorrent completion still invokes `_start_library_reconcile(force=True)`, which performs a recursive walk.
5. there is no external-file observer while CP is already online.
6. current locks establish only in-process ownership. There is no OS-level process lease, mutex, or lock file proving a single catalog writer across multiple CP processes.

No Gate 1 work is authorized or included.

## Repository freeze

| Field | Baseline |
| --- | --- |
| Working directory | `C:\Users\dante\Desktop\cinema paradiso` |
| Branch | `master` |
| HEAD | `eaf6a749133fc3dec279f82f707719a3e5ed1bf0` |
| HEAD subject | `Checkpoint native player updates and library ingestion plan` |
| Remote | `origin https://github.com/dantebagera/cinema-paradiso.git` (fetch/push) |
| Repository owner | `dantebagera/cinema-paradiso` |
| Connected GitHub permission | `ADMIN` |
| Initial `git status --short` | `?? aqtinstall.log` |
| Python | 3.12.8 |
| Node | v24.15.0 |
| npm | 11.12.1 |
| Git | 2.43.0.windows.1 |
| Application version | 2.8.2 |
| Catalog schema | v10 (`CATALOG_SCHEMA_VERSION = 10`) |
| Packaged player selector | `0.1.20-qt6.10.3-mpv20260610-lgpl` |

The repository does not contain an `AGENTS.md` file at this HEAD. The AGENTS instructions supplied with the task were treated as authoritative and followed.

The plan's planning-time dirty-worktree note is stale. The four listed native-player files are now tracked in HEAD; only the pre-existing untracked `aqtinstall.log` remained before Gate 0 evidence was added. It was not touched.

## What currently owns each responsibility

| Responsibility | Current authoritative owner | Evidence |
| --- | --- | --- |
| SQL write authority | `CatalogRepository` | `services/catalog_repository.py:42-55` |
| SQL schema and Movie View page query | `CatalogStore` | `services/catalog_store.py:26`, `:1313-1421`, `:1626-1702` |
| Canonical card projection | `CanonicalCatalog` | `services/canonical_catalog.py:84`, `:218`, `:1079-1313` |
| Filesystem inventory, stability, probe, and reconciliation | `app.py` reconciliation functions | `app.py:7794-8169`, `:8262-8453` |
| File View physical/incomplete-file facts | `/api/library` full projection plus `LibraryFileRow` | `app.py:5087-5112`; `src/features/library/LibraryWorkspace.jsx:1985+` |
| qBittorrent runtime, journal, move/import, recovery, cleanup | `QBittorrentManager`, `QBittorrentJobStore`, `DownloadImportMonitor` | `services/qbittorrent.py:289-417`, `:919-1060`; `services/download_monitor.py:5-63` |
| Browser Library state and grid | `LibraryWorkspace` | `src/features/library/LibraryWorkspace.jsx:219-1536` |
| Browser reconcile polling | root `App` effect | `src/App.jsx:439-469` |
| Browser-local catalog/reconcile notifications | `src/api/library.js` | `src/api/library.js:13-27`, `:87-99` |

SQL remains the only finalized catalog in the current architecture. qBittorrent jobs remain an explicitly external operational document (`services/catalog_repository.py:23`), not a competing catalog.

## Trigger and behavior baseline

The complete trigger inventory and call graph are in [route-call-graph.md](route-call-graph.md).

Key conclusions:

- startup calls `_start_library_reconcile()` only in non-test mode (`app.py:11634-11646`);
- `POST /api/library/reconcile` forces the same global owner (`app.py:4682-4686`);
- `GET /api/library?force_scan=1` runs `_reconcile_library_files(force_unresolved=True)` synchronously (`app.py:5050-5086`);
- the qBittorrent monitor polls every five seconds and preserves its existing manager/journal ownership (`services/download_monitor.py:8-63`);
- qBittorrent completion applies exact-path identity, then starts a forced global reconcile (`app.py:2389-2448`);
- there is no online external-file trigger, watcher dependency, SSE route, or `EventSource` subscriber;
- the stability window is 15 seconds. A file is stable when its mtime is at least 15 seconds old, or the same size/mtime observation persists for 15 seconds (`app.py:7794-7806`);
- every pending pass repeats `_reconcile_library_files()` after 15 seconds, so pending stability currently repeats a full walk (`app.py:8289-8312`);
- the startup root signature stats configured root directories only; it does not fingerprint nested files (`app.py:8315-8333`);
- the startup decision may write operational signature/generation metadata while bootstrapping an existing inventory (`app.py:8357-8360`).

## Final-card publication baseline

The current Movie View SQL predicate is:

```sql
WHERE mf.identity_status = 'accepted' OR mf.metadata_accepted = 1
```

It appears in the effective Movie View query at `services/catalog_store.py:1396`. It does not enforce any of the plan's other readiness requirements.

`AppMetadataStore.accept_tmdb_identity()` writes TMDB metadata, manual-match state, and the accepted file record through separate repository calls (`app.py:1297-1349`). Each `CatalogRepository.upsert_records()` call is internally transactional and synchronizes canonical projections before generation bump/commit (`services/catalog_repository.py:472-493`), but the complete acceptance sequence is not one transaction.

The qBittorrent handoff calls `accept_tmdb_identity(... facts=_metadata_file_facts(path, probe=False))` (`app.py:2389-2397`) before the forced reconciliation. Therefore an accepted card can become query-visible before stability checking and probing. Poster readiness is not part of the SQL predicate.

This is a confirmed contract violation, not an assumption.

## Browser baseline

Current reconciliation polling:

- checks `/api/library/reconcile` once when the root app mounts;
- polls every two seconds only if that response already says `running`;
- dispatches browser-local `CustomEvent` notifications after a completed run is observed;
- has no server-pushed event transport.

A reconcile that begins after the one idle check is not guaranteed to start polling.

`LibraryWorkspace.loadLibrary()` always calls `setLoading(true)`, including `quiet` refreshes (`src/features/library/LibraryWorkspace.jsx:325-372`). The grid is behind `!activeLoading && !error` (`:1417+`). Cards are keyed by physical `item.path` (`:1468`), as are File View rows (`:1508`).

Isolated desktop proof at 1600x1000:

| State | Evidence |
| --- | --- |
| Initial Movie View, page 1 of 2 | [before/library-movie-view-initial.png](before/library-movie-view-initial.png) |
| Genre `Drama` plus title sort | [before/library-filter-sort.png](before/library-filter-sort.png) |
| One selected card plus a different expanded card | [before/library-selection-expanded.png](before/library-selection-expanded.png) |
| Internal workspace scroll retained at 819.6 px with expanded card focused | [before/library-scrolled.png](before/library-scrolled.png) |
| Page 2 of 2, showing items 41-55 | [before/library-pagination-page-2.png](before/library-pagination-page-2.png) |
| Foreground rescan: zero cards mounted and placeholder visible | [before/library-foreground-loading.png](before/library-foreground-loading.png) |

All screenshots were captured against an isolated catalog with 55 accepted synthetic cards and synthetic files under an OS-temporary `CP_TEST_ROOT`. The loading proof added 1,500 isolated pending fixture files. No production card, path, poster, or metadata appears in the captures.

## Performance baseline summary

Full machine-readable results are in [performance-baseline.json](performance-baseline.json).

### Ordinary Movie View API, isolated 1,555-file/55-card catalog

| Metric | Cold | Warm |
| --- | ---: | ---: |
| Latency | 223.900 ms | p50 16.732 ms; p95 17.842 ms |
| SQL statements | 22 | 13 per request |
| JSON payload | 82,924 bytes | 82,924 bytes |
| Gzip-equivalent payload | 3,498 bytes | 3,498 bytes |
| Recursive walks | 0 | 0 total across 30 requests |
| `isfile` calls | 1,555 | 0 total across 30 requests |
| Probe calls | 0 | 0 |
| Provider calls | 0 | 0 |

The cold request's 1,555 `isfile` calls come from the generation-scoped maintenance audit. Ordinary warm card paging is SQL-only, but the cold generation path is not filesystem-free.

An isolated HTTP loop of 50 requests measured p50 53.625 ms and p95 62.569 ms, with 0.8438 CPU-seconds consumed and working set rising from 101,998,592 to 104,873,984 bytes.

### Full scan micro-baseline

Three stable isolated `.mkv` fixtures:

- elapsed: 162.771 ms;
- one recursive walk yielding three files;
- three probe calls;
- zero provider calls under the filename provider;
- all three finished `stable`/`unmatched` with `probe_status=no_video`.

The 1,500-file foreground rescan remained visibly in progress beyond 42 seconds on a subsequent isolated pass. That pass was used only to capture current loading behavior and was stopped with its isolated server; it was not treated as a passing performance test.

### Startup and process baseline

Existing CP `/api/startup/status` was read without restart or mutation:

- API ready: 776.339 ms;
- database open: 345.808 ms;
- first Library query: 1,007.356 ms;
- reconciliation decision: 734.982 ms;
- decision: `skip`, reason `current_inventory`.

An isolated pre-seeded test process reported API ready 29.551 ms, database open 4.142 ms, and first Library query 82.414 ms. Test mode intentionally skips production background startup work, so these values are not interchangeable.

Five-second idle process sample:

| Process | PID | CPU-seconds delta | Machine CPU | Working set | Private bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing CP listener | 38300 | 0.0156 | 0.010% | 269,901,824 | 250,437,632 |
| Existing qBittorrent | 6340 | 0.0000 | 0.000% | 56,291,328 | 28,569,600 |

## Runtime and single-writer ownership

At capture time:

```text
run.bat/cmd PID 33512
  venv Python shim PID 19028
    CP Python listener PID 38300 on 127.0.0.1:5000
      qBittorrent PID 6340 on 127.0.0.1:8686
```

Only one existing CP listener was present. That is observed runtime state, not an enforced invariant.

`CatalogRepository`, reconciliation, qBittorrent jobs, and qBittorrent completion all use `threading.Lock`/`RLock`. No cross-process mutex, lock file, or single-writer lease exists. Gate 1 must freeze this boundary before any observer worker is designed.

The running qBittorrent executable is `data\qbittorrent\versions\5.2.3\qbittorrent.exe`, while `BUNDLED_QBT_VERSION` is `5.2.2` in `services/qbittorrent.py:25`. Watcher/ingestion work must not silently normalize or change that separate runtime discrepancy.

## Regression baseline

See [regression-baseline.md](regression-baseline.md) for commands and diagnostics.

| Suite | Result |
| --- | --- |
| Python backend discovery | 1002 passed in 138.685 s |
| Node unit tests | 75 passed across 13 files |
| Desktop Playwright | 48 passed in 47.5 s |
| Packaged/native-player focused suite | 97 passed in 0.321 s |
| Vite production build to temp output | passed, 1,651 modules, 2.56 s |

Existing backend warnings remain: an unclosed temporary file reported from `services/catalog_store.py:94` and an unclosed `dist/index.html` reader in a unittest path. They did not fail the suite but are recorded baseline debt.

## Required plan corrections before Gate 1

1. **Refresh the repository snapshot.** The plan's dirty native-player list no longer matches HEAD; only `aqtinstall.log` was pre-existing and untracked.
2. **Make the process boundary an approval blocker, not a footnote.** Current ownership is single-process by observation only. Gate 1 must approve either an enforceable CP writer lease or a deployment guarantee with a testable failure mode.
3. **State explicitly that qBittorrent identity cannot be accepted before coordinator stability/probe.** The current exact-path handoff already writes accepted identity with `probe=False`; Gate 6 must route its known imported paths through the same readiness transaction without moving importer/journal ownership.
4. **Define one atomic acceptance transaction owner.** Current repository transactions are per document/call. Gate 1 must identify the one method that commits file facts, identity, required metadata, poster readiness, canonical projection, publication state, and generation together.
5. **Clarify Gate 0's “current catalog can be backed up/read” stop condition.** The task also forbids touching production data. Gate 0 proved the code path and isolated catalog integrity only. Production backup/read and rollback proof must remain Gate 10 work requiring separate live approval.
6. **Freeze the qBittorrent version discrepancy as out of scope.** Code defaults to 5.2.2 while the running managed binary is 5.2.3. Do not combine runtime normalization with ingestion work.
7. **Add the cold maintenance audit to the ordinary-use budget.** A generation-cold Movie View request performs one `isfile` call per catalog candidate even though it performs no recursive walk. Gate 1 should decide whether zero ordinary filesystem I/O includes this path; the plan currently measures walks but not this hidden O(n) stat workload.
8. **Require an idle-to-running notification test.** Current polling stops after an idle result. The future transport test must begin with an already-mounted idle Library, then start ingestion, and prove one post-commit background update.

These corrections refine the contract; they do not authorize implementation.

## Stop-condition accounting

| Gate 0 stop condition | Result |
| --- | --- |
| Process ownership is unclear | Current runtime owner is identified; cross-process enforcement is absent and must be frozen in Gate 1. |
| Baseline imports mutate live state | Passed. All imports/tests used OS-temporary roots and isolated catalogs. |
| Current catalog cannot be backed up/read consistently | Production catalog deliberately not touched. Isolated schema/read/write/integrity paths passed; plan wording needs correction as above. |
| Unrelated dirty work overlaps planned files | No overlap. `aqtinstall.log` was preserved. Evidence files are the only new workspace paths. |
| An authoritative owner cannot be identified | Passed. Owners are listed above and in the route graph. |

## Safety accounting

- Existing CP and qBittorrent were never restarted, stopped, or signaled.
- Isolated test servers used ports 5119 and 5117 and were stopped after evidence capture.
- No configured live media root or production catalog was opened by a test.
- No dependency was installed.
- No watcher, schema migration, durable Windows file ID, or application code was added.
- No Git staging, commit, tag, push, release, or pull request occurred.

Gate 1 requires Dante's explicit approval.
