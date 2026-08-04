# Gate 1 architecture and contract decision record

Date: 2026-08-01 (Africa/Cairo)

Status: frozen for Gate 2 approval. Gate 1 changes documentation only. No application behavior, dependency, schema, catalog, media, process, or Git state was changed.

## Outcome

Gate 1 approves one extraction of the current reconciliation owner into `services/library_ingestion.py`. It does not approve a wrapper around the current `app.py` implementation and does not approve a second pipeline.

The frozen system has these boundaries:

- `LibraryIngestionCoordinator` owns work normalization, queueing, coalescing, stability, probing orchestration, identity/metadata orchestration, poster readiness, retries, and final publication ordering.
- `CatalogRepository` remains the only SQL write authority and gains one transaction-aware final publication operation.
- `CatalogStore` owns the one reusable final-card eligibility query and the Movie View query.
- `CanonicalCatalog` remains the only canonical card/details projection.
- the existing media-asset service owns poster download, validation, checksums, and local asset paths.
- `QBittorrentManager`, its job store, and `DownloadImportMonitor` keep all runtime, job, move/import, cleanup, collision, and restart-recovery ownership.
- File View continues to expose physical, pending, rejected, and failed ingestion facts.
- Movie View reads only SQL rows that pass the frozen final-card predicate.
- filesystem and qBittorrent adapters provide hints/paths only; they perform no probe, provider, asset, or SQL work.
- the browser receives identifiers and generation only, then refetches its current bounded SQL query.

The detailed owner graph is in [ownership-diagram.md](ownership-diagram.md).

## Authoritative coordinator interface

Module: `services/library_ingestion.py`

Class: `LibraryIngestionCoordinator`

Public operations:

```python
reconcile_paths(paths, reason, correlation_id=None)
reconcile_directories(directories, reason, correlation_id=None)
reconcile_all(reason, correlation_id=None)
status()
shutdown(timeout_seconds=10)
```

All reconciliation triggers must call these operations. The extraction must move or replace `_file_copy_is_stable`, `_reconcile_library_path`, `_reconcile_library_files`, and `_run_library_reconcile_loop`; those functions must not remain as a competing implementation in `app.py` after Gate 2 parity is proven.

The three operations use the same inspection, stability, probe, identity, metadata, poster, canonical, deletion, and publication owners. A targeted operation is not a reduced-quality path.

Submission results are acknowledgements, not cards:

```json
{
  "correlation_id": "uuid",
  "accepted": 1,
  "coalesced": 0,
  "rejected": 0,
  "queue_depth": 1
}
```

## Process and single-writer boundary

One CP backend process must hold one exclusive, crash-released Windows file handle for the resolved catalog path before `CatalogRepository` is initialized and before reconciliation, observer, qBittorrent monitor, or artwork workers start.

Frozen owner: `services/catalog_writer_lease.py`, class `CatalogWriterLease`.

Windows implementation contract:

- lease file location is the existing per-catalog LocalAppData catalog directory;
- lease filename includes a BLAKE2 hash of the resolved catalog path;
- open through `CreateFileW` with no sharing for the full backend lifetime;
- a second writer fails before binding the HTTP port and reports the owning catalog path without exposing secrets;
- normal process termination and crashes release the OS handle; the zero-byte file may remain and is not treated as a stale lock;
- test mode uses its unique temporary catalog path, so tests never contend with the live lease.

There is no read-only secondary backend mode in this delivery. Failing closed is safer than allowing an unproven second writer.

## Queue, workers, and backpressure

| Setting | Frozen value |
| --- | --- |
| Work types | exact path, bounded directory, affected root/full recovery |
| Queue capacity | 4,096 normalized work keys |
| Dispatcher/catalog writers | one |
| Probe workers | two |
| Provider/artwork workers | two total |
| Per-path mutation concurrency | one |
| Event-to-queue target | below 250 ms p95 |
| Coalescing window | 500 ms, without delaying queue acknowledgement |
| Stability window | current 15 seconds |
| SSE event buffer | 256 committed generation events |
| Per-client SSE queue | 32 entries, coalesced to newest generation on pressure |

Repeated path hints merge by normalized case-insensitive Windows path. Parent directory work subsumes child hints only when it is bounded to the same configured root. A known path may never be promoted to a global walk merely because the queue is busy.

If the queue reaches capacity, the adapter marks only the affected root dirty and schedules one root-recovery marker. It must not silently discard work or create unbounded tasks.

## Stability and retry policy

The compatibility window remains exactly 15 seconds. Gate 1 does not lower it and does not weaken the plan's 15-second p95 target. If later measurement proves those two constraints cannot coexist, that gate fails and returns to Dante for a decision.

Stability uses existence, size, modification time, and readable-open state. A change resets the stability deadline. Continuous copying is bounded by a 24-hour first-observed deadline; after that the item becomes visibly failed and a later filesystem/manual event may submit new work.

Transient sharing/probe errors receive at most five retries with 1, 2, 4, 8, and 15 second delays. Provider and poster failures receive at most three retries with 2, 10, and 30 second delays. Permanent identity conflicts, unsupported media, and exhausted retries stop automatically and remain visible in File View.

## Root capability matrix

| Root | Default monitoring | Recovery | Deletion safety |
| --- | --- | --- | --- |
| Fixed local NTFS | recursive native watchdog observer | affected-root reconciliation only on overflow/loss | prune only after root is confirmed online and inventory completes |
| Removable NTFS/exFAT | native observer when root is present | mark offline on removal; bounded catch-up after reattach | never prune while absent/offline |
| UNC or mapped SMB/CIFS | degraded by default; no trusted native guarantee | manual/startup reconciliation; configurable polling remains off by default | never treat observer silence or disconnect as empty root |
| Unsupported/erroring observer | degraded | manual/startup plus explicitly triggered affected-root recovery | no mass deletion |

`GetDriveTypeW` plus UNC detection selects the capability class. Watchdog's polling observer is not enabled automatically for SMB/CIFS because it performs recursive snapshots and would violate the idle no-full-walk budget. The UI must say monitoring is degraded instead of claiming the root is current.

## Publication and generations

The complete predicate and transaction are frozen in [publication-state-machine.md](publication-state-machine.md).

Generation semantics:

- public `catalog_generation` continues to mean finalized Movie View/media generation;
- intermediate physical/File View observations use a new `file_generation` key in existing `catalog_meta` and do not advance `media_generation`;
- one successful final-card transaction advances `media_generation` exactly once;
- curation and asset generations retain their current meanings;
- generic unrelated repository writes keep their existing behavior until their owning tests prove any required call-site classification.

Adding `file_generation` to the existing key/value `catalog_meta` table requires no DDL and no schema-version change.

## Event and frontend contract

Transport: one application-level Server-Sent Events connection at `GET /api/catalog/events`.

The backend event broker is a distinct transport owner in `services/catalog_events.py`; it cannot project cards or write SQL. The root frontend subscriber is `src/api/catalogEvents.js`; workspaces consume its shared generation signal and must not create their own `EventSource`.

The exact wire and reconnect schema is in [api-event-contract.md](api-event-contract.md).

Library background refresh must:

- retain the existing grid DOM node and rows;
- issue one bounded request for the current query;
- keep filters, sorting, pagination, search, internal scroll, focus, selection, and expansion unchanged;
- discard stale request/generation responses;
- preload/decode only newly introduced local poster assets;
- commit through a non-blocking React transition;
- never set the foreground `loading` state.

Stable UI identity is `canonical_metadata.movie_key` when unique in the result. Duplicate physical copies use `movie_key + path_key` as a collision-safe fallback. The duplicate fallback may remount after a physical rename until optional durable file identity is separately approved in Gate 9; it may not hide either result.

## Poster-ready policy

Policy 1 is selected: a poster that exists must be cached and checksum-verified locally before publication. A remote provider URL alone is not ready.

A valid explicit no-poster final state is allowed only when the selected provider snapshot is complete and contains no usable poster URL. It renders through the established intentional no-poster design, not a skeleton or temporary slot.

Poster work completes before the SQL transaction:

1. download to a temporary asset path;
2. validate type/decode and checksum;
3. atomically place the immutable asset;
4. open the SQL transaction and reference it;
5. garbage-collect an orphan asset later if SQL rolls back.

## Diagnostics and degraded-state contract

Machine-readable diagnostics are mandatory through `GET /api/library/ingestion/status` and structured logs. Required fields are defined in the API contract.

Desktop UI behavior:

- no new mobile work;
- use the existing Library toolbar/status owner;
- show no indicator while healthy and idle;
- show a compact non-blocking `Catching up` state while bounded recovery is running;
- show a persistent warning for degraded/offline roots, with the affected root and manual Rescan action;
- never replace, cover, or unmount the Movie View grid for background status;
- per-file failures remain in File View/Review Unmatched, not Movie View placeholders.

## Dependency and schema decisions

- observer dependency: `watchdog==6.0.0`, approved for installation only in Gate 3;
- transport dependencies: none; Flask streaming plus browser `EventSource`;
- schema: remains v10 through Gates 2-8;
- durable Windows file identifiers and schema v11 remain Gate 9 only;
- the running qBittorrent 5.2.3 versus code-default 5.2.2 discrepancy is explicitly out of scope.

See [dependency-license-review.md](dependency-license-review.md).

## Approved implementation order

1. Gate 2 extracts the current reconciliation owner, establishes the writer lease and transaction-capable boundaries, and proves behavior parity. No observer or SSE is enabled.
2. Gate 3 installs/pins watchdog and adds external observation through the shared coordinator.
3. Gate 4 changes publication behavior atomically and emits post-commit events.
4. Gate 5 adds the single SSE subscriber and no-flicker background refresh.
5. Gate 6 changes only qBittorrent's final handoff from forced global reconciliation to exact paths after parity.

Each gate remains separately approval-gated.

## Gate 0 comparison and Gate 1 stop conditions

| Area | Gate 0 | Gate 1 frozen contract |
| --- | --- | --- |
| Reconciliation owner | embedded in `app.py` | extracted replacement in `services/library_ingestion.py` |
| Process ownership | one observed process; no enforcement | fail-fast exclusive catalog writer lease |
| External detection | absent | watchdog native observer for supported local roots in Gate 3 |
| Publication | accepted identity only | one strict reusable final-card predicate and atomic commit |
| Poster | not a publication requirement | local verified asset or explicit terminal no-poster |
| Browser update | mount-time conditional polling | one reconnecting SSE subscriber, post-commit only |
| Background refresh | unmounts grid | retains DOM and all interaction state |
| Known qBittorrent path | forced global walk | exact-path coordinator handoff in Gate 6 |
| Schema | v10 | v10 through Gate 8 |

No Gate 1 stop condition was triggered. Ownership is explicit, rollback is documented, the proposed dependency is not installed, no schema migration is needed, and no competing implementation was created.

Gate 2 is not authorized by this document.
