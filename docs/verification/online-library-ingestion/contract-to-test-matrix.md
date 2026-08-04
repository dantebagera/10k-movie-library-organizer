# Gate 1-10 contract-to-test matrix

Status meanings:

- **Existing**: a current test provides partial or full regression coverage.
- **Required**: must be added in the named gate before that gate can pass.
- **Approval-only**: evidence/decision, not an implementation test.

| Gate | Contract | Existing coverage | Required proof before gate passes |
| --- | --- | --- | --- |
| 1 | One authoritative ingestion coordinator and named entry points | Static owner trace in Gate 0 | Approval-only ownership diagram; import-boundary test plan proving no second importer/reconciler/publication owner |
| 1 | Explicit final publication predicate and required card fields | Catalog/canonical tests cover current projections | Approval-only predicate specification mapped field-by-field to Gate 4 tests |
| 1 | Poster-ready policy | Poster override/editor tests | Approval-only definition of local/default/remote poster readiness and failure behavior |
| 1 | One post-commit browser event transport with reconnect semantics | None | Approval-only API/event schema, reconnect/replay rule, generation ordering |
| 1 | Watcher dependency and packaged-runtime support | Release/runtime assembly tests; no watcher dependency today | Dependency/license review plus proposed packaging test targets; no install in Gate 1 |
| 1 | Single writer/process boundary | In-process locks only | Approval-only enforceable boundary plus future second-process rejection test |
| 2 | Existing startup/manual/qBittorrent callers preserve observable behavior through one owner | `test_library_reconcile`, `test_download_monitor`, qBittorrent service/API tests | Targeted coordinator unit tests for every caller; parity snapshots for statuses, journal callbacks, and catalog generation |
| 2 | Targeted path/subtree operations perform no accidental global walk | No direct contract test | Patch/count `os.walk`; exact path must be zero walks, bounded subtree at most one bounded walk |
| 2 | No second catalog or metadata pipeline | Catalog repository/authority tests | Static import/owner test plus integration proof all finalized writes use `CatalogRepository` |
| 3 | External add while CP is online enters the authoritative queue | None | Isolated observer integration: create file after idle mount, observe queued exact path |
| 3 | Rename/burst coalescing and path normalization | Existing path helpers only | Unit matrix for case, separators, Unicode, long paths, repeated modify/create/rename bursts |
| 3 | Stability requires unchanged observations; incomplete files stay File View only | `test_media_file_facts`, `test_library_reconcile` partial | Fake-clock tests for size/mtime changes, 15-second window, retry/backoff, timeout/degraded state |
| 3 | Observer overflow/unavailable/unsupported roots use bounded recovery | None | Failure injection for overflow, removable disconnect, SMB/network capability fallback; count bounded walks |
| 3 | Idle watcher meets CPU/memory budgets | None | 30-minute isolated idle soak with CPU, RSS/private bytes, handles, threads, queue depth |
| 4 | No Movie View row before stability, probe, identity, metadata, poster, canonical projection | Current predicate fails this | Integration test after every pipeline step asserting SQL page count remains zero until ready |
| 4 | Final acceptance is one SQL transaction and one generation bump | Repository transactions are per current call | SQLite trace/failure-injection tests at every write boundary; rollback leaves no published row/asset reference |
| 4 | Browser notification occurs only after commit | None | Commit-hook ordering test: subscriber reading on event sees the complete card and new generation |
| 4 | Probe/provider/poster failures never leak placeholder cards | Partial media/provider tests | Parameterized failure tests with SQL page absence and File View diagnostic presence |
| 4 | Canonical projection remains the sole card source | Canonical/catalog tests | Projection equality test across Library, Discover-owned, and Movie Lists after one publication |
| 5 | Background update never unmounts grid or shows loading placeholder/spinner | Current behavior fails; no existing test | Desktop Playwright delays page response, asserts same grid DOM node remains connected and no loading UI appears |
| 5 | Preserve filters, sort, page, search, scroll, focus, selection, expanded card | Existing server paging/state and curation-expanded tests are partial | One Playwright scenario snapshots all states before a post-commit event and verifies exact equality afterward |
| 5 | Stable card identity across path change/publication update | Current key is `item.path` | Frontend unit + Playwright proof using approved stable key; no remount of unaffected cards |
| 5 | Exactly one frontend subscriber and one bounded page refetch | None | Request counter asserts one page request per committed generation; no reload/navigation |
| 6 | qBittorrent importer, journal, cleanup, recovery ownership is unchanged | qBittorrent service/API/monitor tests | Full existing qBittorrent suite stays green |
| 6 | Known imported paths enter targeted coordinator; normal completion performs zero global walks | Current callback forces global scan | Integration test with `os.walk` trap and exact `imported_paths` assertion |
| 6 | Identity is not accepted before stability/probe/readiness | Current callback uses `probe=False` | Stepwise qBittorrent completion test asserting Movie View absence until coordinator commit |
| 6 | Restart recovery/idempotency/collision/cleanup failure remain correct | Existing service tests cover many states | Restart at `moving`, `payload_imported`, `cleanup_failed`, missing-qBT, duplicate target; assert one final card and journal preservation |
| 7 | Startup skips current inventory within budget | Existing startup decision/reconcile tests partial; live read-only status captured | Isolated current-inventory startup benchmark below budget with zero global walk |
| 7 | Offline add/delete/rename catch-up is complete and conservative | Current inventory tests partial | Restart fixtures for each change, unavailable root, and dirty-root recovery; assert no unsafe prune |
| 7 | Root signature/capability behavior is deterministic | Current signature only stats roots | Tests for nested changes, root unavailable/reappears, network/removable capability matrix |
| 8 | All existing backend, Node, Playwright, packaging/runtime suites remain green | Gate 0 baseline recorded | Re-run once against final branch; any flake is diagnosed, not rerun blindly |
| 8 | Performance budgets for ordinary use, idle, ingestion, startup | Gate 0 metrics exist | Automated p50/p95, SQL, payload, walk, probe/provider, CPU/RSS, queue, event latency, and startup assertions |
| 8 | Failure injection and soak do not lose/duplicate cards or jobs | Partial catalog/qBittorrent tests | Kill/restart, transaction abort, provider timeout, poster failure, observer overflow, root disconnect, burst/soak |
| 8 | Packaged runtime includes approved observer dependency and still plays representative media | Runtime assembly/unit baseline exists | Packaged dependency/import check plus isolated representative real-media player smoke |
| 9 | Optional durable Windows file IDs only with separate schema approval | No implementation; schema v10 baseline | Migration rehearsal on copied isolated catalog, backup/rollback, unsupported-volume fallback, ID reuse/rename tests |
| 10 | Live acceptance only after separate approval | Intentionally none | Confirm exact live paths/processes, create verified backup, run bounded acceptance, compare all Gate 0 metrics/state, prove rollback, then stop |
| 10A | Directory metadata storms never fill the coordinator | Gate 3 observer/queue coverage | 5,000 unique directory-modified events produce zero submissions; created/moved directories retain one bounded hint; parent/child work collapses |
| 10A | Operational inventory bookkeeping is not a Movie View publication | Catalog generation tests | First SQL checkpoint exists; unchanged and changed operational inventory writes advance no global/media/canonical/asset generation |
| 10A | Normal startup performs no hidden artwork/catalog mutation | Explicit artwork API/tool remains | Startup-owner regression proves no timer, asset worker, asset file, or generation mutation |
| 10B | First upgraded startup is safe for a populated catalog lacking the new directory-revision checkpoint | Pass: populated pre-feature catalog plus authoritative inventory fixture | Unchanged accepted files cause zero probe/provider/path reconciliation/generation; first and changed-directory catch-up disable accepted-card enrichment; bounded deletion preserves other roots |
| 10B | Semantically unchanged enrichment persistence is idempotent | Pass: repository operational-field tests plus populated-upgrade integration | Timestamp/revision-only file/provider persistence advances no Movie View generation; material identity-title change advances exactly once |

## Global assertions to carry into every later gate

Every new test must additionally assert:

- `CP_TEST_MODE=1`;
- unique OS-temporary `CP_TEST_ROOT`;
- database path below that root;
- all media/staging/poster paths below that root;
- no production media root appears in resolved paths;
- no provider network call escapes an injected fake;
- no existing CP or qBittorrent process is started, stopped, or signaled;
- no live acceptance is included without separate approval.

## Final execution status

| Gate | Status | Final evidence |
| --- | --- | --- |
| 1 | Pass with later correction | Architecture files plus the atomic-visibility correction in `gate-4-verification.md` |
| 2/2A | Pass | Coordinator ownership, isolated performance, and 48/48 desktop restoration |
| 3 | Pass | Observer/stability/queue tests and 30-minute native soak |
| 4 | Pass | Strict predicate, SQL invisibility, rollback, idempotence, poster and ordering tests |
| 5 | Pass | Node subscriber test, 49/49 Playwright, screenshots, and video |
| 6 | Pass | Exact-path qBittorrent handoff, zero-walk trap, and full qBittorrent regression coverage |
| 7 | Pass | Startup checkpoint tests and 10-sample startup benchmark |
| 8 | Pass | 1,053 backend, 76 Node, 49 Playwright, 98 packaged/native, portable build, player smoke, order repeats, and performance JSON |
| 9 | Not triggered | Measurements did not justify schema v11 or durable Windows file IDs |
| 10 | Aborted and rolled back | Stopped before copy; SQL restored byte-for-byte; browser/card acceptance not reached |
| 10A | Pass | 1,059 backend, 76 Node, 49 Playwright, corrective storm/startup/generation tests, package/player proof, and 30-minute soak |
| 10 retry 1 | Aborted and rolled back | Stopped before browser/copy when first-checkpoint global recovery advanced media generation six times; SQL restored byte-for-byte |
| 10B | Pass | 1,062 backend, 76 Node, 49 Playwright, populated-upgrade and scoped-delete proofs, package/player proof, performance budgets, and 30-minute soak |
| Gate 10 retry 2 | Pass | Exact Rao Bahadur external copy produced one final canonical SQL card, one post-commit event, preserved desktop state, and exact cleanup rollback; see `gate-10-final-verification.md` |
