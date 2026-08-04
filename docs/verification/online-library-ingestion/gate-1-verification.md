# Gate 1 Verification and Stop Report

Date: 2026-08-01 (Africa/Cairo)

Scope: architecture and contract freeze only. No Gate 2 implementation was started.

## Result

Gate 1 passes as a documentation gate. It freezes one authoritative ingestion and publication design, records every later proof obligation, corrects contradicted plan assumptions, and leaves application code, configuration, dependencies, schema, catalog, media, runtime processes, and Git state untouched.

## Repository and preservation proof

At Gate 1 entry and exit:

- branch: 'master';
- HEAD: 'eaf6a749133fc3dec279f82f707719a3e5ed1bf0';
- remote: 'dantebagera/cinema-paradiso';
- repository viewer permission: 'ADMIN';
- pre-existing untracked file preserved: 'aqtinstall.log';
- gate-owned changes: the tracked plan amendment and documentation under this verification directory;
- no file was staged, committed, moved, deleted, reset, pushed, tagged, or released.

The current listeners at exit were CP Python PID 8336 on 127.0.0.1:5000 and its qBittorrent child PID 42792 on 127.0.0.1:8686. Both started at approximately 11:18 on 2026-08-01, before Gate 1 work. Gate 1 did not start, stop, or restart them. Gate 0's earlier PIDs have naturally changed, while the one-CP/one-qBittorrent topology and ports remain consistent. Isolated Gate 0 ports 5117 and 5119 were not listening.

## Frozen architecture

- One extracted 'LibraryIngestionCoordinator' replaces the embedded 'app.py' reconciliation owner after Gate 2 parity; it is not a wrapper or parallel pipeline.
- 'CatalogRepository' remains the sole SQL writer, 'CatalogStore' owns one final-card predicate and Movie View query, and 'CanonicalCatalog' remains the card projection owner.
- File View keeps physical and incomplete-file facts. Movie View reads only transactionally accepted final cards.
- A Windows exclusive catalog writer lease fails closed before the repository, HTTP listener, or workers can create a second writer.
- Known paths stay targeted. Capacity pressure may dirty only the affected root and cannot promote ordinary work to a global walk.
- Stability precedes probe; a current successful probe precedes identity, required metadata, poster readiness, canonical projection, and one atomic publication commit.
- 'media_generation' advances only for finalized Movie View publication. Intermediate facts use an existing metadata-table key, 'file_generation', without schema DDL.
- The broker sends identifiers and generation after commit only. The browser quietly refetches SQL while retaining the mounted desktop grid and interaction state.
- qBittorrent's manager, job journal, import/move, cleanup, recovery, and restart ownership remain unchanged.

## Dependency and transport decision

'watchdog==6.0.0' is approved for installation only if Gate 3 is separately approved. It was not installed or added to requirements in Gate 1; the repository virtual environment still reports no 'watchdog' module.

Fixed local and present removable roots may use recursive native observation. SMB/CIFS stays explicitly degraded by default because the dependency directs CIFS users to polling, while recursive polling conflicts with the plan's idle no-walk budget.

SSE is the Gate 5 transport to qualify. It adds no dependency. If post-commit ordering, bounded replay/pressure, packaged-runtime concurrency, or shutdown cannot be proven, Gate 5 fails and returns for a new decision; it does not silently introduce polling.

## Plan corrections recorded

The saved plan now records:

1. the real Gate 0/Gate 1 approval boundary and current dirty-work evidence;
2. the current qBittorrent identity-before-probe and 'probe=False' shortcut as behavior that must not survive the targeted handoff;
3. zero per-file filesystem checks as part of ordinary Library request budgets, following Gate 0's 1,555-call cold-path finding;
4. the required idle-mounted Library event test;
5. the correct Gate 0 isolated-catalog stop condition, with production backup/inspection deferred to Gate 10;
6. Gate 5 failure rather than a silently substituted polling architecture.

No stated latency, CPU, memory, filesystem, provider, probe, SQL, payload, startup, transaction, or UI budget was weakened.

## Evidence inventory

- [gate-1-architecture-contract.md](gate-1-architecture-contract.md)
- [ownership-diagram.md](ownership-diagram.md)
- [publication-state-machine.md](publication-state-machine.md)
- [api-event-contract.md](api-event-contract.md)
- [dependency-license-review.md](dependency-license-review.md)
- [rollback-design.md](rollback-design.md)
- [gate-1-test-map.md](gate-1-test-map.md)

The index in [README.md](README.md) links Gate 0 and Gate 1 evidence.

## Gate 0 comparison

Gate 1 changes no executable behavior, so the Gate 0 functional and performance measurements remain the comparison baseline and were not rerun merely to retest unchanged code. The saved contracts add missing proof for:

- cross-process single-writer enforcement;
- strict final-card readiness;
- targeted known-path work;
- native observer capability and degraded network roots;
- post-commit event replay and pressure;
- true no-flicker background refetch;
- per-gate rollback.

The existing Gate 0 results remain 1,002 Python tests, 75 Node tests, 48 Playwright tests, successful Vite build, and the recorded packaged-runtime smoke. Gate 1 adds no test or application code, so no new behavioral suite was expected. A later implementation gate must rerun its approved relevant suites once and diagnose any flake instead of rerunning to green.

## Unresolved risks and stop boundary

- The exact 15-second stability window and 15-second external-add p95 budget may be physically tight. Neither was weakened; the implementation gate fails if both cannot be met.
- Network shares do not have continuous default monitoring under this design. The UI must state degraded coverage, and startup/manual recovery remains required.
- The current runtime still has no enforceable cross-process catalog lease; Gate 2 must add and prove it before any observer.
- Final-card predicate fields and the atomic repository operation do not yet exist as one implementation.
- SSE worker concurrency and packaged shutdown remain test obligations, not assumed facts.
- Duplicate physical copies use a path-based UI collision key until optional Gate 9 durable file IDs; rename remounts remain a documented limitation.

Gate 2 is not authorized. No implementation, dependency installation, schema work, catalog mutation, process restart, or live-library acceptance may begin without Dante's explicit approval.

