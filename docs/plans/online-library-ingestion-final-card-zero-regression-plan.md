# Online Library Ingestion and Final-Card Publication — Zero-Regression Plan

**Status:** Complete. Gates 0-8 pass; Gate 9 was measured unnecessary and introduced no schema/file-ID migration. Gate 10A and Gate 10B corrected the two mandatory-stop findings in the existing owners and pass full isolated qualification. Dante approved the final exact Rao Bahadur retry. After a stale deployed frontend bundle was caught and rolled back before copy, the qualified source was built into `dist`; the corrected live run passed startup stability, targeted external ingestion, final-card SQL publication, one post-commit event, no-flicker desktop preservation, and exact cleanup rollback. Production SQL/source/configuration/qBittorrent are restored or unchanged, and the accepted live catalog is preserved in the fresh backup.

**Prepared:** 2026-07-31

**Repository:** Cinema Paradiso (CP)

**Current catalog schema:** v10

## Authorization boundary

Dante approved creating and saving this plan. That approval does **not** authorize:

- application-code or configuration changes;
- database migration, catalog mutation, metadata backfill, or media-file mutation;
- starting, stopping, or restarting CP, qBittorrent, or another process;
- a live library scan or watcher trial against Dante's actual library;
- staging, committing, tagging, pushing, releasing, or opening a pull request.

Implementation begins only after Dante approves a named gate and its scope.

**Approval addendum (2026-08-01):** Gate 0 completed as a read-only baseline. Dante then approved Gate 1, Gate 2, and continuation through the remaining isolated implementation plan without intermediate approval pauses. Corrective Gate 2A resolved the initial frontend collection-cache/navigation failure. Gates 3-8 implemented and qualified the native observer, strict final-card publication, post-commit event transport, no-flicker desktop refresh, qBittorrent targeted handoff, and startup catch-up. Gate 9 remained intentionally unused. Dante subsequently approved the exact Rao Bahadur live fixture. Gate 10 stopped before media copy after queue saturation and unrelated startup artwork mutation; its catalog rollback is complete. Dante approved corrective Gate 10A and exact orphan cleanup. Gate 10A corrected those existing owners, passed its full isolated qualification, and moved the exact 36 orphan files into the recoverable Gate 10 backup quarantine. Dante approved the exact live retry. That retry stopped before browser/media work after a separate populated-catalog startup-transition mutation, and its rollback is exact. Dante then approved Gate 10B; it corrected the deployment transition and generation idempotence in the existing owners and passed the complete isolated qualification. Dante approved the final exact live retry. A stale deployed `dist` bundle was stopped and rolled back before media copy, then rebuilt from the qualified source. The corrected live run passed, and the approved cleanup restored production exactly. Evidence is indexed in [the verification README](../verification/online-library-ingestion/README.md).

At planning time, the worktree contained unrelated native-player work and `aqtinstall.log`. At the Gate 0 and Gate 1 baselines, the listed native-player files were tracked and clean; `aqtinstall.log` remained pre-existing and untracked. Gate 0 and Gate 1 owned only verification evidence. Gate 2 owns the explicitly listed parity-refactor code, tests, and evidence; `aqtinstall.log` remains preserved and unrelated.

Every implementation gate must re-run `git status --short`, preserve every pre-existing modified or untracked file, and stop if its intended edits overlap unreviewed user work.

---

## 1. What is happening now

### 1.1 The confirmed problem

CP does not continuously detect an externally added movie while CP is running.

Today:

1. A qBittorrent completion asks CP to run a forced library reconciliation.
2. Opening CP starts a reconciliation decision, but that decision may skip a recursive scan when the configured root directory signatures look unchanged.
3. An external file copied or moved into a nested library folder while CP stays open has no authoritative event path into ingestion.
4. The frontend checks reconciliation state at mount, then continues polling only when it already sees a reconciliation in progress.
5. The frontend's current `quiet` library reload still enters the loading state, and the grid is rendered only while that state is false. Using it for background updates would therefore create the flicker Dante explicitly rejected.

### 1.2 Where the behavior is owned

The current authoritative areas are:

| Responsibility | Current owner |
|---|---|
| Startup reconciliation trigger | `app.py`, application startup near line 11636 |
| Startup skip/scan decision | `app.py`, `_startup_reconcile_decision` near line 8336 |
| Recursive library reconciliation | `app.py`, `_reconcile_library_files` near line 8008 |
| File-copy stability check | `app.py`, `_file_copy_is_stable` near line 7794 |
| qBittorrent completion handoff | `app.py`, completion handler near lines 2401-2440 |
| qBittorrent state and recovery | `services/qbittorrent.py` and `services/download_monitor.py` |
| SQL library page query | `services/catalog_store.py`, `query_media_page` near line 1626 |
| Canonical card projection | `services/canonical_catalog.py` |
| Frontend reconciliation polling | `src/App.jsx`, near lines 439-469 |
| Frontend library loading | `src/features/library/LibraryWorkspace.jsx`, `loadLibrary` near line 325 |
| Frontend grid visibility | `src/features/library/LibraryWorkspace.jsx`, near line 1417 |
| Browser-local library event | `src/api/library.js`, near lines 87-98 |

Line numbers are navigation hints from the 2026-07-31 snapshot, not permanent contracts. Gate 0 must record exact symbols and current line numbers before implementation.

### 1.3 What this means for Dante

- A movie added externally while CP is online can remain absent until another action causes a scan.
- A known qBittorrent completion causes more filesystem work than necessary because it requests a full reconciliation.
- A naive frontend refresh can make the library disappear and reappear.
- Publishing a file before identity, metadata, and card projection are complete would expose an empty or visibly changing card.

These are separate defects. A filesystem watcher alone does not solve the final-card or frontend-flicker problems.

---

## 2. Required outcome

CP must reliably handle three ingestion cases through one authoritative pipeline:

| Case | Detection | Required action | User-visible result |
|---|---|---|---|
| External file added while CP is running | Continuous root monitoring, with reconciliation fallback | Reconcile only the affected path or directory, wait for stability, probe, identify, enrich, and publish | One finished card appears without a page refresh or flicker |
| CP-managed qBittorrent download completes | Existing qBittorrent completion handoff | Pass the known imported path into the same targeted pipeline | One finished card appears; no normal full-root walk |
| File added while CP is closed | Startup catch-up | Detect offline changes and run bounded directory/path reconciliation, escalating to a full scan only when evidence is insufficient | Finished cards appear as background ingestion completes |

Delivery order:

1. external additions while CP is online;
2. qBittorrent targeted handoff;
3. startup/offline catch-up hardening.

The stages share an architecture, but each must have a separate acceptance gate and rollback boundary.

---

## 3. Non-negotiable product contracts

### 3.1 Final-card-only contract

Movie View must never display a placeholder, half-populated, or progressively hydrating movie card.

A movie is publishable to Movie View only after the background pipeline has completed all required work:

1. the media path is stable and readable;
2. the file is an accepted video type;
3. media probing has completed or produced an explicitly accepted result;
4. movie identity has reached an accepted state;
5. required card metadata has been resolved;
6. the canonical card projection is valid;
7. poster handling has reached a defined ready state;
8. all catalog writes for the publication are committed atomically.

Only after commit may CP advance the media generation and notify connected browsers.

“Final” does not mean every optional expanded-detail field must be present. The exact required projection is frozen in Gate 1. Expanded cast, biography, filmography, recommendations, and similar detail-only data remain deferred unless the current canonical card contract requires them.

If identity or required metadata cannot be accepted, the file may remain visible through File View or Cleanup with an explicit status. It must not leak into Movie View as an unfinished card.

### 3.2 No-flicker frontend contract

When a movie becomes publishable:

- the existing grid remains mounted;
- no full-page or library spinner appears;
- no white/empty grid frame appears;
- no browser navigation or manual refresh occurs;
- filters, sort, page, search, scroll, selection, focus, and expanded-card state are preserved;
- currently visible poster images do not reload unnecessarily;
- the completed card is inserted only if it belongs on the current result page under the active query;
- if it belongs elsewhere because of filtering, sorting, or pagination, totals/facets update without forcing it onto the wrong page;
- burst events produce one bounded refresh, not one request per filesystem event.

The browser may perform a bounded background SQL page refetch. “No refresh” is a visual and interaction contract, not a ban on a network request.

### 3.3 Catalog ownership contract

- SQL remains the authoritative finalized catalog.
- The canonical catalog projection remains the authoritative card contract.
- qBittorrent operational jobs remain owned by the existing qBittorrent job/journal subsystem.
- File View remains the surface for physical file facts and incomplete or rejected ingestion records.
- Movie View remains limited to accepted canonical movies.
- Filesystem events are hints, never a second catalog or source of truth.
- Frontend memory is not authoritative and must not manufacture movie cards from event payloads.

### 3.4 Completeness contract

An update must not hide or silently drop an existing result. Sorting, filters, pagination, duplicate grouping, totals, and facets must remain consistent with the same committed SQL snapshot/generation.

### 3.5 Single-owner contract

The implementation must improve or extract the current reconciliation owner. It must not introduce:

- a second importer;
- a watcher-specific metadata pipeline;
- qBittorrent-only catalog business logic;
- route-specific publication rules;
- a second source of media identity;
- a browser-created card projection.

---

## 4. Recommended architecture

### 4.1 One ingestion coordinator, several trigger adapters

All triggers feed one coordinator:

```text
qBittorrent completion ─┐
filesystem observation ─┼─> ingestion coordinator ─> canonical catalog transaction
startup/manual scan ────┘              │                         │
                                      │                         └─> committed generation
                                      └─> stability / probe / identity / metadata
                                                                      │
                                                                      └─> catalog-ready event
```

The coordinator owns:

- path normalization and root containment;
- path/directory/full-scan work types;
- event coalescing and de-duplication;
- per-path serialization;
- bounded worker concurrency;
- copy/move stability;
- media probing;
- identity and metadata orchestration through existing owners;
- publication readiness;
- retry classification;
- catalog transaction ordering;
- one completion event after commit.

Trigger adapters only identify work. They must not perform catalog mutations.

### 4.2 Required reconciliation entry points

The authoritative reconciliation owner should expose three explicit operations:

- `reconcile_paths(paths, reason, correlation_id)`
- `reconcile_directories(directories, reason, correlation_id)`
- `reconcile_all(reason, correlation_id)`

The names and module location are design decisions for Gate 1. A likely extraction is `services/library_ingestion.py`, but the existing code must be inspected for a cleaner owner before that path is approved.

All three operations must share the same path inspection, identity, publication, and deletion logic. A targeted operation is not a simplified or lower-quality import path.

Escalation rules:

1. Known completed path: path reconciliation.
2. Create/move/rename hint with reliable containing directory: directory reconciliation.
3. Watcher overflow, lost journal, invalid checkpoint, or uncertain root state: full reconciliation for the affected root.
4. Global full reconciliation only when root-level evidence requires it or the user explicitly requests it.

### 4.3 Queue and concurrency

The queue must:

- normalize Windows paths case-insensitively;
- reject paths outside configured library roots;
- merge repeated events for the same path/directory;
- collapse parent/child work safely;
- serialize operations touching the same movie destination;
- place an upper bound on probing and metadata workers;
- apply backpressure instead of creating unbounded tasks;
- expose counts and current stage for diagnostics;
- persist or recover enough state that a CP restart cannot leave committed media invisible.

The design must define a single-writer boundary before background workers are enabled. If two CP backend processes can open the same catalog and both run watchers, implementation stops until process ownership is made explicit.

### 4.4 Filesystem observation

For local Windows roots, the recommended first candidate is a native event observer through the Python `watchdog` package, backed by Windows directory change notifications.

This dependency is not pre-approved. Gate 1 must compare:

- packaged-runtime support;
- installer size and license;
- recursive-root behavior;
- Windows network-share behavior;
- clean shutdown;
- buffer-overflow reporting;
- CPU and memory cost.

The observer callback must be deliberately small:

1. receive an event;
2. normalize the source and destination paths;
3. identify the containing configured root;
4. filter irrelevant extensions and internal CP paths;
5. enqueue a directory/path hint;
6. return.

It must not probe media, call metadata providers, write SQL, or block on copy stability inside the observer thread.

### 4.5 Event coalescing and stability

Windows moves and copies can emit several create, modify, rename, and close-like signals. CP must treat these as noisy hints.

Recommended stability algorithm:

1. debounce events for the same path/directory for a short bounded window;
2. sample existence, size, modification time, and readable-open state;
3. wait for two matching observations separated by the configured stability interval;
4. reject a disappeared path as superseded work;
5. run the existing media probe;
6. retry transient sharing/probe failures with a bounded backoff;
7. classify permanent failures visibly and stop retrying indefinitely.

The current 15-second stability behavior is the compatibility baseline. Changing that duration requires measured evidence, because lowering it may ingest a half-copied file and raising it worsens response time.

Folder-level events must consider sidecars such as subtitles without treating every sidecar as a new movie.

### 4.6 Overflow and unsupported-root recovery

Filesystem notifications are not durable. Buffers can overflow, network shares can behave differently, and event delivery can be lost across sleep or restart.

Therefore:

- an observer overflow marks the affected root dirty;
- a dirty root schedules a bounded recovery reconciliation;
- repeated observer errors switch that root to periodic reconciliation and report degraded monitoring;
- startup verifies watcher checkpoints before trusting them;
- manual scan remains available;
- periodic safety reconciliation is configurable and low priority;
- the UI must report degraded monitoring without showing false “up to date” status.

No root may be treated as empty merely because it is temporarily offline. A root connectivity failure must never mass-delete catalog rows.

### 4.7 qBittorrent integration

The first external-file stage does not change qBittorrent behavior.

When the qBittorrent stage is approved:

- retain `QBittorrentManager` ownership of runtime, submission, job state, cleanup, seeding, and recovery;
- retain existing journal and idempotency behavior;
- after CP finishes its current import/move step, pass the exact destination path to `reconcile_paths`;
- do not accept identity or metadata before the shared coordinator completes stability checking and a current probe; the current `probe=False` pre-acceptance shortcut must not survive the targeted handoff;
- remove the normal forced full reconciliation only after path-targeted parity is proven;
- preserve restart recovery for a qBittorrent process that outlives CP;
- make no seeding, hardlink, category, download-directory, or cleanup-policy changes in this project.

Incremental qBittorrent sync APIs, hardlink imports, and Radarr-like seeding policies are separate future work.

### 4.8 Startup catch-up

Startup remains the backstop for files added while CP was closed.

The current root-signature decision is not sufficient proof that nested content is unchanged. Gate 7 must select and prove one of:

- durable per-directory checkpoints;
- a lightweight stored inventory comparison;
- a file journal where supported plus conservative fallback;
- bounded root reconciliation at startup.

The chosen method must:

- catch nested changes;
- detect missed watcher events;
- avoid provider calls for unchanged accepted files;
- avoid re-probing unchanged files;
- avoid treating an offline root as deletion;
- preserve acceptable startup time;
- escalate to a full walk only when checkpoints cannot establish parity.

File IDs using Windows volume serial plus file identifier may later improve rename/move detection, but they imply a schema and migration decision. They are explicitly optional and not required for the initial online-addition fix.

---

## 5. Atomic final-card publication

### 5.1 Publication state

Gate 1 must define a single publish predicate using existing media-file, identity, metadata, enrichment, ingest, and asset fields where possible.

The predicate must answer:

> Can the canonical Movie View query return this movie in its final card form right now?

It must not infer readiness from elapsed time or the mere existence of a path.

The planned state flow is:

```text
observed
  -> waiting_for_stability
  -> probing
  -> resolving_identity
  -> enriching_required_card_data
  -> ready_to_publish
  -> committed
  -> browser_notified
```

Failure states must identify the failed stage and whether retry is safe. A failed item remains inspectable outside Movie View.

### 5.2 Poster readiness

Gate 1 must freeze one of these explicit policies:

1. a locally cached poster is required before Movie View publication; or
2. a provider poster URL is sufficient if the browser can preload/decode it before inserting the card; or
3. “no poster exists” is a valid final state rendered by the established intentional no-poster design.

A loading skeleton or poster slot that later changes is not acceptable.

Artwork generation and media generation must retain their separate meanings. A card publication must not force unrelated artwork invalidation.

### 5.3 Transaction and notification order

Required order:

1. complete all fallible external work that should not hold a SQL write lock;
2. open one catalog transaction;
3. write or update file facts, identity, metadata acceptance, canonical projection, and related rows;
4. validate invariants;
5. commit;
6. advance the appropriate catalog/media generation exactly once;
7. publish one compact readiness event for the committed generation.

The event must contain identifiers and generation information, not a second copy of the card:

```json
{
  "type": "catalog-ready",
  "generation": 123,
  "reason": "external-add",
  "movie_ids": ["tmdb:603"],
  "correlation_id": "..."
}
```

The frontend then refetches its current bounded query from SQL.

If browser notification fails, the committed catalog remains correct. Reconnection or generation comparison must recover the missed visual update without repeating ingestion.

---

## 6. Browser update transport

### 6.1 Recommended transport

Server-Sent Events (SSE) are the preferred first design:

- one server-to-browser connection;
- automatic browser reconnect;
- event IDs can support missed-event recovery;
- no bidirectional protocol is needed;
- Flask can stream a generator response.

This is a recommendation, not an implementation mandate. Gate 1 must prove:

- compatibility with CP's packaged Windows runtime;
- clean backend shutdown;
- behavior behind the current local server;
- reconnect after sleep/restart;
- bounded client and server queues;
- no leaked request/thread per event;
- no effect on normal API latency.

Gate 1 freezes SSE as the transport to qualify. If SSE cannot pass that proof, Gate 5 fails and returns for a new architecture decision; bounded polling must not be introduced silently as a fallback. WebSockets are not justified for this one-way use case unless another approved CP feature already establishes a shared transport.

### 6.2 One frontend subscriber

There must be one application-level catalog event subscriber. Feature workspaces consume one shared catalog-generation signal.

Do not create separate event connections for Library, Home, Cleanup, Movie Lists, or other surfaces.

### 6.3 Background refetch path

The current `loadLibrary({ quiet: true })` path is not acceptable because it still sets the loading state and can unmount the grid.

The frontend needs a distinct background-refresh state:

- keep current rows rendered;
- fetch the current query into a temporary result;
- cancel or discard stale responses by request/generation token;
- coalesce multiple events;
- allow only one current-query refresh in flight;
- preload/decode newly introduced poster assets;
- commit the new result in a non-blocking React transition;
- reconcile selection and expansion by stable movie identity, not array position;
- restore/retain scroll without a visible jump;
- leave foreground loading behavior unchanged for real navigation/query changes.

The final implementation should key cards by stable canonical movie identity where available. A path-only key can cause unnecessary remounts when a file is moved or re-associated.

---

## 7. Performance budgets

These are release gates, not aspirations.

### 7.1 Ordinary Library use

Compared with the Gate 0 baseline on the same machine and catalog:

- warm Library API p50 and p95 may regress by no more than the larger of 5% or 50 ms;
- cold Library API p50 and p95 may regress by no more than the larger of 5% or 50 ms;
- ordinary Library requests perform zero filesystem walks;
- ordinary Library requests perform zero per-file `isfile`, `stat`, or equivalent media-root filesystem checks;
- ordinary Library requests perform zero media probes;
- ordinary Library requests perform zero metadata-provider calls;
- SQL statement count for the same page/filter request must not increase without a measured and approved reason;
- card payload size must not materially grow for event transport.

### 7.2 Idle monitoring

With CP open and the library idle:

- average watcher/coordinator CPU target: below 0.5% after warm-up;
- additional steady-state memory target: below 20 MB;
- no recurring recursive full-root walk;
- no recurring metadata-provider calls;
- no unbounded queue, thread, handle, or SSE-client growth.

### 7.3 Ingestion response

For a supported local filesystem:

- watcher-event-to-queue target: below 250 ms p95;
- committed-event-to-visible-card target: below 1 second p95;
- stable-file-to-committed-final-card target: measured separately for warm-cache and provider-required cases;
- external last-write-to-final-card target: 15 seconds p95 when identity and required assets are locally available;
- provider latency is reported separately and may not be hidden by publishing an incomplete card;
- a normal external addition or qBittorrent completion performs zero global full-root walks;
- a burst containing one movie produces at most one catalog transaction, one media-generation advancement, and one browser refresh after coalescing.

### 7.4 Startup

- unchanged-library startup may regress by no more than the larger of 5% or 250 ms;
- catch-up work must run at bounded priority and must not block the initial usable UI longer than the approved baseline;
- unchanged files must not be re-probed or re-enriched.

If a budget fails, the gate fails even when functional tests pass.

---

## 8. Delivery gates

No gate may silently flow into the next. Each ends with a written evidence report and an explicit proceed/stop decision.

### Gate 0 — Read-only baseline and ownership proof

**Purpose:** Freeze current behavior before changing it.

Actions:

- record `git status --short`, branch, HEAD, Python/Node versions, catalog schema, and packaged-runtime version;
- inventory every current reconciliation trigger and call site;
- trace qBittorrent completion through import, journal, and forced reconciliation;
- trace startup reconciliation and its skip decision;
- trace Movie View SQL query, canonical projection, card key, loading states, and grid visibility;
- inventory existing tests by owner;
- record current API p50/p95, SQL statement count, payload sizes, startup time, process CPU/memory, and full-walk counts;
- record desktop screenshots/video for foreground load, filter, sort, pagination, expanded card, and current reconciliation behavior;
- construct isolated fixture roots for all later tests;
- prove no test points at a configured live media root or production catalog.

Required artifacts:

- `docs/verification/online-library-ingestion/gate-0-baseline.md`
- machine-readable performance JSON;
- route/call-graph inventory;
- fixture manifest;
- before screenshots/video.

Stop conditions:

- process ownership is unclear;
- baseline imports mutate live state;
- the isolated test catalog cannot be created and read consistently. Production-catalog backup or inspection is deferred to separately approved Gate 10;
- unrelated dirty work overlaps planned files;
- a current authoritative owner cannot be identified.

### Gate 1 — Architecture and contract freeze

**Purpose:** Approve exact ownership before code changes.

Decisions to freeze:

- authoritative coordinator module and public entry points;
- publish predicate and required card fields;
- poster-ready policy;
- event transport and reconnect contract;
- watcher dependency and packaged-runtime support;
- worker limits, debounce, stability, retry, and overflow policy;
- root capability matrix: local NTFS, removable drive, SMB/network share;
- single-writer/process boundary;
- diagnostics and user-visible degraded-state contract;
- exact schema impact, preferably none for the first delivery.

Required artifacts:

- ownership diagram;
- state machine;
- API/event schema;
- dependency/license review;
- rollback design;
- approved test map from each contract to at least one automated test.

No behavior change is allowed in this gate.

### Gate 2 — Reconciliation-owner parity refactor

**Purpose:** Establish targeted operations without changing observable behavior.

Implementation:

- extract or clarify the existing reconciliation owner;
- implement path, directory, and full-scan entry points over shared internals;
- preserve all existing identity, duplicate, subtitle, probe, metadata, cleanup, deletion, and failure behavior;
- add correlation IDs and instrumentation;
- retain current startup and qBittorrent callers until parity is proven.

Acceptance:

- full reconciliation output is identical before and after on the fixture matrix;
- targeted reconciliation produces the same rows/projections as a subsequent full reconciliation;
- no second importer or publication predicate exists;
- no live catalog mutation;
- performance budgets pass.

Rollback: revert only the refactor; no schema/data rollback should be required.

**Gate 2 outcome (2026-08-01): passed after Gate 2A.** Backend, ownership, isolation, performance, Node, packaging, and build proof pass. A pending collection request was initially aborted on route departure without recovery; Gate 2A corrected the existing shared cache owner and the full desktop suite passed 48/48. See [Gate 2 verification](../verification/online-library-ingestion/gate-2-verification.md) and [Gate 2A verification](../verification/online-library-ingestion/gate-2a-verification.md).

### Gate 3 — Online external-add detection

**Purpose:** Reliably enqueue externally added media while CP is running.

Implementation:

- add root observers through the approved dependency;
- add normalization, containment, filtering, coalescing, stability, retries, and bounded workers;
- add overflow/degraded-root recovery;
- keep frontend publication disabled during isolated backend proof.

Acceptance:

- externally copied, moved, renamed, and folder-added fixtures reach the same catalog result as explicit reconciliation;
- slow copies are never probed or published early;
- sidecar bursts do not duplicate movie work;
- queue remains bounded under an event storm;
- root disconnect does not delete media;
- idle and active performance budgets pass;
- clean startup/shutdown leaves no watcher thread or handle.

### Gate 4 — Atomic final-card publication and backend event

**Purpose:** Publish only committed, final Movie View records.

Implementation:

- enforce the approved publication predicate in the authoritative catalog path;
- make related catalog updates atomic;
- advance generation once after successful commit;
- add the approved event broker/endpoint;
- support reconnect/generation recovery;
- expose diagnostics without card duplication.

Acceptance:

- no event occurs before commit;
- rollback produces no event and no Movie View row;
- provider/probe/asset failure leaves an inspectable non-published record;
- retry publishes exactly once;
- multiple clients receive the same generation without multiplying ingestion work;
- a dropped client reconnect catches up;
- event pressure cannot block catalog commits.

### Gate 5 — No-flicker desktop frontend

**Purpose:** Show the finished card without disturbing the current screen.

Implementation:

- add one app-level event subscriber;
- implement a true background page refresh;
- retain the foreground navigation/loading path;
- use stale-response/generation protection;
- preload new poster assets before UI commit;
- preserve state by stable identity;
- coalesce burst refreshes.

Acceptance:

- the grid stays mounted for the entire background request;
- no placeholder or partial card is rendered in any frame;
- the new card appears only after the backend-ready event;
- no spinner, white frame, layout jump, scroll jump, or current-card remount;
- filter, sort, search, page, selection, focus, and expansion stay correct;
- failed background refresh leaves the old view intact and retries safely;
- an already idle-mounted Library receives a later committed event and performs exactly one quiet authoritative refetch;
- Desktop Chrome/Chromium Playwright video and screenshots prove the sequence.

Mobile/responsive redesign or testing is out of scope.

### Gate 6 — qBittorrent targeted handoff

**Purpose:** Replace the normal completion-time full reconciliation with a known-path handoff.

Implementation:

- preserve the existing qBittorrent importer and journal;
- hand the final imported destination to the shared coordinator;
- remove the forced full scan only after parity and recovery tests pass.

Acceptance:

- existing qBittorrent completion, pause/move, restart recovery, failure, and idempotency tests remain green;
- exactly one final card appears;
- no full-root walk occurs in the successful known-path case;
- no seeding, hardlink, cleanup, source-search, or download-setting behavior changes;
- a missed/invalid path escalates safely rather than silently losing the movie.

### Gate 7 — Startup/offline catch-up hardening

**Purpose:** Reliably find files added while CP was closed without punishing normal startup.

Implementation:

- replace or strengthen the nested-change decision according to Gate 1;
- recover incomplete ingestion work;
- restart observers only after root/catalog initialization;
- reconcile dirty roots conservatively.

Acceptance:

- a nested movie added while CP is closed is always found on next start;
- an unchanged library takes the fast path;
- an offline root does not cause deletion;
- a crash at every ingestion checkpoint recovers idempotently;
- startup budgets pass.

### Gate 8 — Full regression, failure, and performance qualification

**Purpose:** Prove the complete system, not only the new happy path.

Required:

- all backend unit/integration tests;
- all enumerated frontend Node tests;
- production frontend build;
- desktop Playwright regression suite;
- isolated packaged-runtime smoke test;
- event-storm, slow-copy, provider-failure, root-disconnect, process-restart, and browser-reconnect tests;
- SQL parity/integrity checks;
- performance comparison to Gate 0;
- test-order and repeat-run check for leaked state.

No live Dante-library test is allowed here.

### Gate 9 — Optional durable file identity

**Purpose:** Improve same-volume move/rename recognition only if measurement proves it is needed.

Possible design:

- Windows volume serial plus stable file identifier;
- schema v11 migration;
- tombstone/rename reconciliation;
- fallback for filesystems without stable IDs.

This is a separate migration project with rehearsal, backup, rollback, and parity proof. It must not block the initial external-add solution and may not be smuggled into an earlier gate.

### Gate 10 — Explicitly approved live acceptance

**Purpose:** Validate one representative real workflow after all isolated gates pass.

Prerequisites:

- Dante explicitly approves the exact library root and files;
- current backend/process ownership is confirmed;
- production catalog and relevant configuration are backed up;
- rollback and restore commands are rehearsed;
- expected rows and UI state are recorded.

Suggested bounded acceptance:

1. start from one known absent test movie outside the live root;
2. open Movie View and set a known filter/page;
3. move the file into one explicitly approved destination;
4. record watcher, coordinator, SQL generation, event, and browser timings;
5. prove only the final card appears and the screen does not flicker;
6. remove/restore the test item only under the approved cleanup procedure;
7. verify catalog parity and no unrelated file/catalog changes.

Stop immediately on any unexplained mutation, mass deletion signal, duplicate, placeholder frame, performance breach, or process-ownership ambiguity.

**2026-08-01 live result and required plan correction:** The approved Rao Bahadur run stopped before step 3. Recursive Watchdog directory-modification hints filled all 4,096 coordinator slots, while ordinary startup artwork backfill created 36 asset rows/files. Forty-seven processed directory jobs also rewrote the operational library inventory and falsely advanced the global/media/canonical-media generations by 47 even though movie tables did not change. The SQL catalog is restored byte-for-byte and the exact 36 unreferenced files are preserved. Before retrying this gate, correct the existing observer/coordinator owners to collapse or ignore directory metadata noise, eliminate unchanged inventory writes and media-generation bumps, and prevent startup artwork work from mutating the bounded acceptance pre-state. Add isolated regressions for a greater-than-capacity directory event storm and a mutation-free pre-acceptance startup, then rerun Gates 3, 7, and 8. No second observer/importer, schema migration, durable file ID, or parallel generation owner is authorized by this correction.

**2026-08-02 Gate 10A result:** The correction is complete in the existing owners. Directory `modified` noise is ignored; created/moved directory hints remain bounded; parent/child queue work collapses; operational inventory uses a SQL checkpoint without advancing catalog generations; and normal startup no longer launches implicit artwork backfill. The greater-than-capacity storm test, mutation-free startup test, full 1,059-test backend suite, 76 Node tests, 49 desktop Playwright tests, portable/package/player checks, performance budgets, and 30-minute observer soak pass. The exact 36 cache orphans are checksum-verified in a recoverable quarantine and zero remain active. Gate 10 may now be retried only after explicit approval; its original source, destination, backup, desktop workflow, and stop conditions remain unchanged.

**2026-08-02 first live retry result and required Gate 10B correction:** The approved retry stopped before the browser opened and before media copy. The populated production catalog predates operational key `library_directory_revisions_v1`; `LibraryStartupCatchup.run_once()` therefore treated the first upgraded start as an empty snapshot and invoked `reconcile_all_now()`. The global recovery reprocessed one unchanged manually accepted movie (`The Loved Ones`), changed only timestamps and identity revisions across existing rows, and nevertheless advanced global/media/canonical-media generations six times. Queue depth remained zero, no artwork asset changed, and no row count changed. CP was stopped immediately; the changed catalog is preserved; production SQL is restored byte-for-byte; source/destination and qBittorrent remain untouched. Before another live retry, add a populated pre-feature catalog transition fixture, preserve conservative offline change recovery, and make semantically unchanged enrichment persistence idempotent across the existing repository/metadata owners. Then rerun Gates 7, 8, and 10A. No schema migration, second scanner, alternative inventory, or duplicate catalog owner is authorized.

**2026-08-02 Gate 10B result:** The correction is complete in the existing startup catch-up, coordinator, AppMetadataStore, and CatalogRepository owners. First-checkpoint recovery remains conservative but disables enrichment of unchanged accepted cards; changed-directory recovery uses the same rule. Operational timestamp/revision persistence no longer advances global, media, or canonical-media generations, while material card changes still advance generation. Bounded directory recovery prunes deleted SQL/inventory paths only within the named root. The populated-upgrade fixture, final 1,062-test backend suite, 76 Node tests, 49 desktop Playwright tests, package/player checks, frozen performance budgets, forward/reverse critical repeats, and 30-minute native observer soak pass. No schema migration, durable file ID, second scanner, second inventory, or alternative writer was introduced. Production SQL/source remain byte-identical, the destination remains absent, CP remains stopped, and qBittorrent remains untouched. The exact Rao Bahadur live retry remains separately approval-gated.

**2026-08-02 final Gate 10 result:** Dante approved the exact retry. Its first preflight start was stopped before copy because the live server exposed a stale July 30 `dist` bundle with zero catalog-event subscribers. SQL was restored byte-for-byte, the old bundle was preserved, and the already-qualified source was built without source/dependency changes; the corrected server then exposed exactly one subscriber. First-checkpoint recovery created `library_directory_revisions_v1` with media generation 7,629 unchanged. The literal four-file Rao Bahadur copy entered the native observer and authoritative coordinator, completed probe, accepted TMDB identity/metadata, checksum-ready poster preparation, canonical projection, ready publication, and one post-commit event. Movie View added one final card while preserving the 1080p filter, newly-added sort, page, selection, expanded card, search focus, and visually anchored scroll position with no spinner, placeholder, blank grid, or reload. The accepted catalog is healthy and preserved. Approved cleanup re-hashed and removed only the copied destination and one new poster, restored production SQL to its original SHA-256 with zero Rao rows and no WAL/SHM, and left the source/configuration/qBittorrent unchanged. Gate 10 passes and the plan is complete. See [the final live verification](../verification/online-library-ingestion/gate-10-final-verification.md).

---

## 9. Automated test matrix

### 9.1 Unit tests — path and observer logic

- normalize drive-letter case and separators;
- resolve source/destination move events;
- reject traversal and paths outside roots;
- ignore unsupported extensions and CP internal paths;
- map subtitles/sidecars to the containing movie without creating a movie;
- coalesce create/modify/move bursts;
- collapse parent and child directory hints without losing files;
- enforce queue size and backpressure;
- handle deleted-before-stable paths;
- distinguish local, network, unavailable, and unsupported roots;
- convert observer overflow into a dirty-root reconciliation;
- stop all observers and workers cleanly.

### 9.2 Unit tests — stability and retry

- zero-byte then growing file;
- file whose size changes across observations;
- same size but changing modification time;
- stable readable file;
- stable but sharing-locked file;
- transient probe failure then success;
- permanent invalid-media failure;
- bounded retry exhaustion;
- CP shutdown during backoff;
- no busy loop while waiting.

### 9.3 Unit tests — publication state

- every required-state transition;
- forbidden transition rejection;
- accepted identity required for Movie View;
- required metadata missing;
- valid explicit no-poster result;
- poster pending;
- probe pending/failed;
- duplicate association;
- retry after provider failure;
- commit before generation advancement;
- generation before browser event;
- rollback produces no event;
- idempotent duplicate-ready event.

### 9.4 Backend integration tests

Use isolated roots and catalogs for:

- single file copied atomically;
- single file copied slowly in chunks;
- folder moved into the root;
- movie plus subtitle and artwork sidecars;
- two movies arriving together;
- rapid rename chain;
- movie moved within one root;
- movie moved between configured roots;
- same filename in different folders;
- existing exact file observed again;
- duplicate-content file;
- unsupported or corrupt video;
- provider unavailable;
- provider returns no acceptable match;
- poster download failure;
- root disconnect/reconnect;
- watcher overflow;
- CP restart during every ingestion stage;
- browser disconnected during publication;
- qBittorrent completion and restart recovery;
- startup discovery after CP was closed;
- manual full reconciliation after targeted ingestion.

For every successful scenario, a subsequent full reconciliation must produce zero semantic catalog changes.

### 9.5 SQL and catalog integrity tests

- foreign-key check;
- schema version and migration boundary;
- one canonical accepted identity per intended movie contract;
- File View contains the physical media facts;
- Movie View excludes incomplete/rejected records;
- duplicate and multi-file movie behavior remains unchanged;
- media generation increments exactly as designed;
- artwork generation remains independent;
- page count, result rows, totals, and facets come from a consistent committed state;
- rollback restores the prior generation and visibility;
- event payload IDs resolve to the same canonical SQL records.

### 9.6 Frontend unit tests

- one event subscriber;
- event burst coalescing;
- one background request in flight;
- stale response discarded after query change;
- stale generation discarded;
- background failure preserves existing rows;
- foreground loading behavior remains unchanged;
- filter/sort/page query retained;
- selection and expansion retained by stable identity;
- new result excluded when it does not match the active filter;
- totals/facets update correctly;
- poster preload success;
- poster preload failure follows the approved final-state policy;
- subscriber disconnect/reconnect;
- no listener leak after workspace mounts/unmounts.

### 9.7 Desktop Playwright tests

Instrument DOM presence, bounding boxes, network timing, and screenshots/video:

- start on Movie View with several existing cards;
- hold the background page request open and assert the grid remains mounted;
- assert the existing cards keep the same keys/nodes where their data did not change;
- assert no loading overlay or empty grid appears;
- release a ready event and response, then assert one final card appears;
- inspect every captured frame for placeholder title/poster/metadata;
- preserve scroll position within tolerance;
- preserve active filter, sort, search, and page;
- preserve selected and expanded card;
- test a new movie sorted onto the current page;
- test a new movie sorted onto another page;
- test a new movie excluded by the current filter;
- test event burst while a request is in flight;
- mount the Library while idle, publish later, and assert one post-commit notification produces exactly one quiet authoritative refetch;
- test background request failure and recovery;
- test browser reconnect after backend restart;
- verify Home, Cleanup, Movie Lists, Discover, AI Control, Continue Watching, and playback entry points show no ownership regression.

Only desktop viewport coverage is required unless a changed existing mobile-specific path makes mobile proof unavoidable.

### 9.8 Performance and soak tests

- API p50/p95 over repeated warm/cold samples;
- SQL statement count and query-plan comparison;
- filesystem-walk/probe/provider-call counters;
- watcher idle CPU/memory for at least 30 minutes;
- event storm with thousands of irrelevant and repeated events;
- batch arrival of representative movie folders;
- multiple SSE clients connect/reconnect;
- backend restart loop;
- sleep/wake where test infrastructure supports it;
- repeated suite runs in different orders;
- file-handle, thread, queue, and memory growth checks;
- packaged-app test, not only source/dev server.

---

## 10. Failure injection requirements

Tests must be able to pause or fail the pipeline at these boundaries:

1. after observer event;
2. after queue insertion;
3. during stability wait;
4. after probe;
5. after identity;
6. after required metadata;
7. before SQL transaction;
8. during SQL transaction;
9. after commit but before generation notification;
10. after generation but before browser delivery;
11. during browser background fetch;
12. after response but before React commit.

For each boundary, document:

- state before failure;
- state after restart/retry;
- whether work repeats;
- why duplicate publication cannot occur;
- whether the browser catches up;
- cleanup/rollback behavior.

---

## 11. Test isolation and commands

All tests must use:

- `CP_TEST_MODE=1`;
- a unique temporary `CP_TEST_ROOT`;
- an isolated catalog and asset directory;
- fixture media specifically created or copied for the test;
- explicit proof that no configured live library root is reachable for mutation.

PowerShell command forms should be recorded in each gate report. Expected suite categories include:

```powershell
$env:CP_TEST_MODE='1'
$env:CP_TEST_ROOT='<unique temporary test root>'
.\.venv\Scripts\python.exe -m unittest <enumerated backend test modules>
```

Frontend Node tests must be enumerated explicitly because wildcard behavior differs across Windows shells:

```powershell
node --test <test-1.test.mjs> <test-2.test.mjs> <test-3.test.mjs>
npm.cmd run build
```

Desktop browser proof uses CP's existing runner:

```powershell
.\tools\run_playwright_e2e.ps1 <approved arguments>
```

Exact modules and arguments are frozen in Gate 0 after the current test inventory is complete.

Importing the normal app module must not accidentally open or mutate the live catalog during a test. Any test that cannot prove isolation is invalid.

---

## 12. Regression surfaces that must remain unchanged

The final qualification must explicitly cover:

- manual library scan;
- startup reconciliation;
- qBittorrent job state, journal, recovery, and import;
- File View physical-file facts;
- Movie View accepted-card contract;
- duplicate handling;
- metadata correction and accepted provider identity;
- poster and local asset serving;
- filters, sorting, search, facets, totals, and pagination;
- owned-card rendering across shared surfaces;
- Home sections and Continue Watching;
- Cleanup;
- Movie Lists;
- Discover;
- AI Control ownership routing;
- expanded movie details;
- playback launch and resume actions;
- subtitles and sidecars;
- configured offline/removable/network roots;
- catalog recovery and backup behavior;
- application shutdown and restart.

Passing only the new Library happy-path test is not release evidence.

---

## 13. Observability and diagnostics

Every ingestion item or coalesced batch needs a correlation ID and structured stage timings:

- trigger type;
- normalized root/path;
- event count and coalescing duration;
- stability duration;
- probe duration/result;
- identity duration/result;
- required metadata/asset duration/result;
- transaction duration;
- committed generation;
- notification duration/client count;
- retry count and final classification;
- whether reconciliation escalated and why.

Sensitive paths must follow CP's existing logging/privacy policy. Logs must be bounded and rotated through existing ownership.

The Help/diagnostic surface should eventually expose:

- monitoring state per root;
- normal/degraded/offline status;
- queue depth;
- active stage;
- last successful event/reconciliation;
- last overflow/recovery;
- last committed generation.

This diagnostic UI is optional for initial code delivery unless the current UI already has an appropriate owner. Machine-readable diagnostics and logs are required.

---

## 14. Rollback strategy

Each gate must remain independently reversible.

- Gates 2-5 should avoid a schema change.
- The watcher is not enabled against live roots until isolated proof passes.
- The old full reconciliation remains available as recovery, not as the normal known-path action.
- Removing the qBittorrent forced full scan occurs only in Gate 6 after targeted parity.
- Failed browser events cannot corrupt the committed catalog.
- A browser can recover by comparing generations and issuing a normal bounded query.
- A failed watcher can be disabled per root while manual/startup reconciliation remains functional.
- Any schema work is deferred to Gate 9 and requires a separate backup/rehearsal/rollback plan.

Temporary internal rollout switches are permitted only during isolated development. If one survives a gate, its owner, purpose, dependency, removal condition, and test coverage must be documented. Do not leave competing permanent code paths “just in case.”

---

## 15. Global stop conditions

Stop the current gate and report to Dante if any of these occurs:

- intended edits overlap unrelated dirty work;
- tests access a live catalog or media root;
- a migration becomes necessary earlier than approved;
- two competing ingestion/publication owners emerge;
- a known-path ingestion performs a normal global full-root walk;
- an ordinary Library read touches the filesystem, probes media, or calls a provider;
- Movie View can observe an incomplete record;
- any captured frontend frame shows a placeholder, empty grid, or refresh flicker;
- filter, sort, pagination, selection, expansion, focus, or scroll changes unexpectedly;
- a root error is interpreted as mass deletion;
- qBittorrent journal, recovery, seeding, cleanup, or import semantics change outside Gate 6;
- performance exceeds a stated budget;
- queue, memory, threads, handles, connections, or retries are unbounded;
- packaged-runtime behavior differs materially from development behavior;
- process/single-writer ownership is unclear;
- rollback cannot be demonstrated.

“The test is flaky” is a failure requiring diagnosis, not permission to rerun until green.

---

## 16. Required evidence package

Before live acceptance, the project must contain or link:

- this approved plan;
- Gate 0 baseline and ownership inventory;
- Gate 1 architecture/contract decision record;
- Gate 1 API/event contract, publication state machine, dependency/license review, rollback design, and frozen contract-to-test map;
- fixture manifest;
- automated test inventory with contract-to-test mapping;
- per-gate implementation and rollback reports;
- machine-readable performance results and baseline comparison;
- SQL parity/integrity results;
- desktop screenshots and video before/during/after background publication;
- packaged-runtime smoke results;
- known limitations by filesystem/root type;
- final live-acceptance checklist requiring Dante's approval.

Evidence filenames should be stable and kept under:

`docs/verification/online-library-ingestion/`

---

## 17. Definition of complete

This project is complete only when all of the following are true:

1. An externally added movie is detected while CP remains open.
2. CP waits for the file to become stable.
3. The existing authoritative owners probe, identify, enrich, and project it.
4. Movie View cannot query it before the final-card predicate passes.
5. Related SQL writes commit atomically.
6. The browser is notified only after commit.
7. The current bounded Library query updates in the background.
8. The completed card appears with no placeholder, grid disappearance, refresh flicker, or interaction-state loss.
9. qBittorrent completion uses the same targeted pipeline without losing its existing journal/recovery behavior.
10. Startup catches files added while CP was closed.
11. Watcher loss, overflow, root disconnect, crash, and provider failure recover safely.
12. All regression, performance, integrity, packaged-runtime, and failure-injection gates pass.
13. No competing importer, catalog, projection, or frontend card source exists.
14. Any live acceptance was separately approved, backed up, bounded, and reversible.

Until every item is proven, the work is incomplete even if the basic demo appears to work.

---

## 18. First approved implementation slice

When Dante authorizes implementation, the first slice should be:

1. Gate 0 read-only baseline;
2. stop and review the evidence;
3. Gate 1 architecture/contract freeze;
4. stop and obtain approval for Gate 2.

Do not start by installing a watcher or editing the frontend. The current reconciliation and publication owners must be made explicit first, because a watcher connected to ambiguous ownership would only make the existing races happen faster.
