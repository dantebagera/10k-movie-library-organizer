# Online Library ingestion verification

Post-plan correction evidence:

- [post-plan-startup-performance-correction.md](post-plan-startup-performance-correction.md) - initial paint, post-grid startup sequencing, isolated regression proof, and remaining live-perception risk

Gate 0 evidence:

- [gate-0-baseline.md](gate-0-baseline.md) — findings, ownership, discrepancies, and approval boundary
- [performance-baseline.json](performance-baseline.json) — machine-readable latency, SQL, payload, filesystem, probe/provider, startup, CPU, and memory data
- [route-call-graph.md](route-call-graph.md) — all startup/manual/external/qBittorrent triggers and authoritative owners
- [fixture-manifest.md](fixture-manifest.md) — isolation proof and later-gate fixture layouts
- [regression-baseline.md](regression-baseline.md) — backend, Node, Playwright, packaged-runtime, and build results
- [contract-to-test-matrix.md](contract-to-test-matrix.md) — every later gate mapped to automated proof
- [before](before) — visually verified 1600x1000 desktop screenshots

Gate 1 evidence:

- [gate-1-verification.md](gate-1-verification.md) — result, baseline comparison, plan corrections, unresolved risks, and Gate 2 stop boundary
- [gate-1-architecture-contract.md](gate-1-architecture-contract.md) — authoritative owners, coordinator boundary, queue, root, generation, UI-key, and diagnostics decisions
- [ownership-diagram.md](ownership-diagram.md) — single-writer and trigger-to-publication ownership
- [publication-state-machine.md](publication-state-machine.md) — exact final-card predicate, transaction, and post-commit notification order
- [api-event-contract.md](api-event-contract.md) — reconciliation, diagnostics, SSE, replay, pressure, and browser-subscriber contracts
- [dependency-license-review.md](dependency-license-review.md) — pinned watcher review and packaged-runtime qualification requirements
- [rollback-design.md](rollback-design.md) — per-gate rollback boundaries and stop conditions
- [gate-1-test-map.md](gate-1-test-map.md) — frozen contracts mapped to later automated proof

Gate 2 evidence:

- [gate-2-verification.md](gate-2-verification.md) — blocked outcome, ownership proof, baseline comparison, plan correction, rollback, and stop boundary
- [gate-2-regression.md](gate-2-regression.md) — backend, Node, packaged-runtime, build, Playwright, isolation, and failure diagnosis
- [gate-2-performance.json](gate-2-performance.json) — machine-readable Movie View, reconciliation, startup, and Gate 0 comparison measurements

Gate 2A evidence:

- [gate-2a-verification.md](gate-2a-verification.md) — shared cache correction, exact regression proof, full 48-test desktop result, and isolated-process cleanup

Later-gate evidence:

- [gate-3-verification.md](gate-3-verification.md) — native watcher, dependency/package proof, degraded roots, and 30-minute soak
- [gate-4-verification.md](gate-4-verification.md) — strict final-card predicate, atomic visibility, rollback, poster readiness, and plan correction
- [gate-5-verification.md](gate-5-verification.md) — one subscriber, true quiet refetch, desktop screenshots, and video
- [gate-6-verification.md](gate-6-verification.md) — qBittorrent exact-path handoff and journal preservation
- [gate-7-verification.md](gate-7-verification.md) — startup checkpoint catch-up and startup budget
- [gate-8-verification.md](gate-8-verification.md) — complete regression/failure/package/runtime qualification
- [gate-8-performance.json](gate-8-performance.json) — final machine-readable performance and baseline comparison
- [gate-9-verification.md](gate-9-verification.md) — optional schema/file-ID gate intentionally not triggered
- [gate-10-verification.md](gate-10-verification.md) — aborted live acceptance, exact rollback proof, root causes, and required correction
- [gate-10-aborted-live-evidence.json](gate-10-aborted-live-evidence.json) — machine-readable stop state, catalog comparison, and residual asset manifest
- [gate-10a-verification.md](gate-10a-verification.md) — corrective owner changes, complete regression qualification, cleanup, and live-retry boundary
- [gate-10a-performance.json](gate-10a-performance.json) — machine-readable corrective contracts, performance, soak, package, and production-safety proof
- [gate-10-retry-verification.md](gate-10-retry-verification.md) — first live retry stop, startup-transition diagnosis, exact rollback, and required Gate 10B correction
- [gate-10-retry-stop-evidence.json](gate-10-retry-stop-evidence.json) — machine-readable startup-generation stop and rollback proof
- [gate-10b-verification.md](gate-10b-verification.md) — populated-upgrade correction, complete isolated qualification, and exact live-retry boundary
- [gate-10b-performance.json](gate-10b-performance.json) — machine-readable regression, performance, soak, package, and production-safety proof
- [gate-10-final-verification.md](gate-10-final-verification.md) — successful bounded live acceptance, deployment preflight correction, final card, desktop preservation, and exact rollback
- [gate-10-final-evidence.json](gate-10-final-evidence.json) — machine-readable live timeline, SQL/card facts, screenshots, process ownership, and cleanup parity
- [after](after) — verified desktop during/after screenshots and Playwright video

All required gates pass. Gate 9 was measured unnecessary and introduced no migration. Gate 10's original run and first retry stopped before media work, leading to the isolated Gate 10A and Gate 10B corrections. The final approved Rao Bahadur retry then passed: startup remained generation-stable, the watched external copy produced one probe-complete, metadata-complete, poster-ready canonical SQL card, one post-commit browser event, and a no-spinner/no-placeholder desktop refresh that preserved interaction state. A stale deployed `dist` bundle was detected and rolled back before copy, then rebuilt from the already-qualified source; the corrected live bundle had exactly one event subscriber. The accepted catalog is preserved, and production SQL/source/configuration/qBittorrent were restored or retained exactly after approved cleanup. No schema migration, second pipeline, or durable Windows file ID was introduced.
