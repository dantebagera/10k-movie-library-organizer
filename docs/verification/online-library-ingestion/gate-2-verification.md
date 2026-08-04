# Gate 2 verification — passed after Gate 2A

## Outcome

Gate 2 initially stopped on one isolated desktop Playwright collection-cache/navigation failure. Gate 2A corrected the existing shared cache owner, the exact failed test passed, and the complete desktop suite then passed 48/48. Gate 2 now passes the gated zero-regression process. See [Gate 2A verification](gate-2a-verification.md).

No live catalog or real media root was opened by a test. CP and qBittorrent were not restarted. No dependency, configuration, media file, catalog schema, Git index, commit, tag, remote, or release was changed.

## Repository and preservation proof

- branch: `master`;
- HEAD: `eaf6a749133fc3dec279f82f707719a3e5ed1bf0`;
- remote: `https://github.com/dantebagera/cinema-paradiso.git` (`dantebagera/cinema-paradiso`), repository permission `ADMIN` at the Gate 2 baseline;
- schema: v10;
- staged files: none;
- pre-existing `aqtinstall.log`: preserved untracked;
- pre-existing plan and verification work: preserved;
- no commit, stage, push, tag, release, branch switch, reset, deletion, or move.

## Authoritative ownership after the refactor

`services/library_ingestion.py::LibraryIngestionCoordinator` is the single reconciliation owner. It owns shared internals plus exact-path, bounded-directory, and full-scan entry points. `app.py` retains only documented compatibility seams for existing startup, manual, and qBittorrent callers; those seams delegate and contain no competing reconciliation algorithm.

`services/catalog_repository.py` remains the SQL repository owner and now exposes the transaction boundary. `services/catalog_writer_lease.py` provides one operating-system-backed writer lease for the exact catalog path. `app.py` acquires that lease before constructing or activating the repository.

Ownership that deliberately did not move in Gate 2:

- SQL remains the authoritative finalized Movie View catalog;
- File View/reconciliation remain responsible for physical-file facts;
- current qBittorrent manager, completion/import journal, recovery, cleanup, and full-reconcile caller remain unchanged;
- current publication predicate and frontend card source remain unchanged;
- no watcher, SSE transport, new importer, second reconciliation pipeline, second catalog source, metadata pipeline, or frontend card source was added.

## Implemented Gate 2 scope

- Extracted the current reconciliation behavior into the authoritative coordinator.
- Added shared exact-path, bounded-directory, and full-scan operations.
- Added correlation IDs, a bounded 4096-item queue, 500 ms coalescing, one serialized dispatcher, redacted pressure diagnostics, and joined shutdown.
- Reused the existing stability rule through one pure helper.
- Added an OS-released catalog writer lease and repository-owned atomic transaction context.
- Added read-only `/api/library/ingestion/status`; it does not initialize a repository and does not expose configured paths.
- Removed per-card `isfile` checks from the SQL Movie View read path. Reconciliation/File View remain the owners of physical existence.
- Kept startup, manual, and qBittorrent callers on their current observable behavior pending later approved gates.

The private compatibility seams in `app.py` are temporary, documented, and have an explicit removal condition: later approved trigger gates must migrate callers and parity tests must prove there is no remaining dependency. They are delegators, not a second implementation.

## Acceptance results

| Contract | Result | Evidence |
|---|---:|---|
| Full reconciliation behavior parity | Pass | Existing reconciliation suites plus final 1025-test backend discovery |
| Targeted result equals subsequent full result | Pass | Exact-path/directory parity and idempotence tests |
| Known path causes no global walk | Pass | Test and benchmark: zero global walks |
| One reconciliation owner | Pass | Source ownership tests and delegating compatibility seams |
| Single catalog writer | Pass | same-process, other-process, crash-release, and acquisition-order tests |
| Atomic transaction | Pass | commit and rollback test |
| Queue bounded and serialized | Pass | capacity, coalescing, pressure, dispatcher, and shutdown tests |
| No live catalog/media mutation | Pass | pre-run isolation assertions and unique OS-temp fixtures |
| Schema/dependency/config parity | Pass | schema v10; no watcher dependency; dependency files unchanged |
| Performance budgets | Pass | [gate-2-performance.json](gate-2-performance.json) |
| Backend/Node/build/packaging regression | Pass | [gate-2-regression.md](gate-2-regression.md) |
| Desktop Playwright regression | Pass after Gate 2A | 48 passed in 56.0s |

## Baseline comparison

- Backend: 1002/1002 at Gate 0; 1025/1025 at Gate 2.
- Node: 75/75 at both gates.
- Vite: identical 1,651 modules, 35 files, and 1,795,902 bytes.
- Playwright: 48/48 at Gate 0; 47/48 initially at Gate 2; 48/48 after Gate 2A.
- Cold Movie View: 223.900 ms to 153.918 ms; SQL remains 22 statements.
- Warm Movie View p95: 17.842 ms to 16.595 ms; SQL remains 13 statements.
- Cold Movie View physical checks: 1,555 `isfile` calls to zero.
- Three-file full scan: 162.771 ms to 79.278 ms.
- Catalog open with writer lease: 6.616 ms, 2.474 ms above the Gate 0 isolated DB-open sample and well below the 250 ms budget.

The Gate 2 payload is smaller, but its fixture text is not byte-identical to Gate 0. It is valid as a no-growth measurement, not as byte-for-byte projection parity.

## Plan discrepancy and required correction

The saved plan says Gate 2 was unapproved and that implementation had not started. Dante approved Gate 2 on 2026-08-01; the plan status is corrected accordingly.

The plan also assumes the existing regression baseline remains a reliable green acceptance floor. The new trace proves a pre-existing frontend defect: route departure aborts a pending collection request, while restored expanded-card state does not trigger a replacement request. That defect is outside Gate 2's backend parity-refactor scope, but the zero-regression rule correctly prevents calling the gate green.

The recommended narrow Gate 2A correction was implemented in the existing collection-cache owner and passed its exact and full-suite proof. No Library-only cache or request path was introduced.

## Rollback and unresolved risks

Rollback requires reverting only the Gate 2 code and tests; there is no schema or data rollback. Nothing is staged or committed, so the change set remains locally reviewable.

Unresolved risks:

- The frontend collection-cache defect is resolved by Gate 2A.
- The PowerShell Playwright launcher has a machine/environment `Path`/`PATH` collision; the equivalent direct launcher worked, but the repository script itself remains unchanged.
- The two Gate 0 resource warnings remain.
- Compatibility seams cannot be removed until later approved trigger migrations prove no caller depends on them.

## Stop boundary

Gate 2's stop boundary is satisfied. Later work remains subject to its own gate contracts.
