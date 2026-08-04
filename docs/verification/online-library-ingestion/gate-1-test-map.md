# Gate 1 Contract-to-Test Map

This map is the acceptance contract for later gates. Every test uses 'CP_TEST_MODE=1', a unique temporary 'CP_TEST_ROOT', an isolated catalog, and isolated fixture media. The test harness must first prove that resolved catalog and media paths are inside that temporary root. A missing, skipped, flaky, live-data-touching, or budget-exceeding test is a gate failure.

| ID | Frozen contract | Planned automated proof | Earliest gate |
|---|---|---|---:|
| OWN-01 | One ingestion coordinator owns startup, manual, external, observer, and qBittorrent hints. | 'tests/test_library_ingestion_ownership.py': route and trigger delegation; source-owner audit. | 2 |
| OWN-02 | CatalogRepository is the only SQL write owner; CatalogStore owns one final-card predicate; CanonicalCatalog owns projection. | 'tests/test_library_ingestion_ownership.py': import/call graph and forbidden-direct-write audit. | 2 |
| OWN-03 | File View owns physical and incomplete-file facts; Movie View receives accepted final cards only. | 'tests/test_library_catalog_publication.py': intermediate fact visibility and final predicate truth table. | 4 |
| OWN-04 | qBittorrent manager, import job, journal, recovery, cleanup, and restart ownership do not move. | Existing qBittorrent suites plus 'tests/test_qbittorrent_targeted_ingestion.py'. | 6 |
| OWN-05 | Browser SQL page remains the card source; SSE carries no cards. | 'tests/test_catalog_events.py' and 'tests/e2e/library-ingestion.spec.js'. | 5 |
| PROC-01 | A catalog-specific Windows writer lease exists before repository, port, or workers. | 'tests/test_catalog_writer_lease.py': first owner, second-process fail-closed, crash release, different-catalog independence. | 2 |
| PROC-02 | Shutdown stops intake, drains bounded work, joins workers, releases lease, and leaves no child process. | 'tests/test_library_ingestion_ownership.py' plus packaged-runtime process inventory. | 2 |
| PATH-01 | Known file hints reconcile the containing item only; known directory hints stay bounded. | 'tests/test_library_ingestion_paths.py': sentinel roots and exact walk/stat counters. | 2 |
| PATH-02 | A known external or qBittorrent path does not normally cause a global walk. | 'tests/test_library_ingestion_paths.py' and 'tests/test_qbittorrent_targeted_ingestion.py'. | 2/6 |
| PATH-03 | Full scan is explicit startup/manual/recovery behavior only. | 'tests/test_library_ingestion_paths.py': reason matrix and forbidden escalation assertions. | 2 |
| QUEUE-01 | Capacity is 4096, per-path work is serialized, duplicates coalesce within 500 ms. | 'tests/test_library_ingestion_queue.py': flood, duplicate, ordering, and queue-bound proof. | 2 |
| QUEUE-02 | Pressure marks only the affected root dirty and never silently publishes or globally scans. | 'tests/test_library_ingestion_queue.py': overflow and root-isolation proof. | 2 |
| STAB-01 | Publication waits for 15 seconds of unchanged size and mtime. | 'tests/test_library_ingestion_stability.py' using a fake monotonic clock and growing-file fixture. | 2 |
| STAB-02 | Share violations retry at 1, 2, 4, 8, and 15 seconds and never create a placeholder. | 'tests/test_library_ingestion_stability.py': deterministic injected open failures. | 2 |
| STAB-03 | A continuously changing copy stops after 24 hours as failed/deferred, without Movie View publication. | Same module with fake clock; no wall-clock wait. | 2 |
| PROBE-01 | Successful current ffprobe facts are mandatory before identity and metadata acceptance. | 'tests/test_library_catalog_publication.py': ordered-call trace and stale-fact rejection. | 4 |
| PROBE-02 | Probe retry does not use 'probe=False' or accept filename identity early. | Source audit plus injected probe failures in publication tests. | 4 |
| ID-01 | Identity is accepted, stable, and bound to the current file observation. | Publication predicate truth table with mismatch and stale-version cases. | 4 |
| META-01 | Selected provider snapshot, details, people, and enrichment completion are required; fallback data is rejected. | Publication predicate truth table and provider-call fixtures. | 4 |
| META-02 | Optional semantic values may be empty only when a complete provider snapshot says unavailable. | Canonical projection fixtures with absent and incomplete provider fields. | 4 |
| POSTER-01 | Poster-bearing titles need a local checksum-verified asset; provider URL alone is not ready. | Publication transaction test with corrupt, missing, and valid assets. | 4 |
| POSTER-02 | Explicit terminal no-poster is allowed only from a complete provider result and renders intentional no-poster UI. | Backend predicate and desktop Playwright assertions. | 4/5 |
| TX-01 | 'publish_final_card' performs canonical rows, acceptance, and one generation bump atomically. | 'tests/test_library_catalog_publication.py': failure injection at every write boundary and SQL snapshot parity. | 4 |
| TX-02 | Intermediate File View facts bump only 'file_generation', never Movie View generation. | Same module with generation assertions. | 4 |
| TX-03 | Idempotency fingerprint prevents duplicate publication and generation churn. | Repeat and restart cases in publication tests. | 4 |
| EVENT-01 | 'catalog-ready' is emitted only after commit and contains no paths or cards. | 'tests/test_catalog_events.py': commit-order spy and payload schema. | 4/5 |
| EVENT-02 | Commit succeeds safely if notification fails; later sync repairs the client. | Broker failure injection plus browser reconnect test. | 5 |
| SSE-01 | Ring size 256, client queue 32, replay, overflow coalescing, heartbeat, and clean shutdown match the contract. | 'tests/test_catalog_events.py' with deterministic broker and stream fixtures. | 5 |
| SSE-02 | One mounted Library creates one EventSource and closes it on unmount. | 'tests/libraryBackgroundRefresh.test.mjs' and Playwright connection counter. | 5 |
| OBS-01 | Local and removable roots use recursive native observation; emitted paths are hints only. | 'tests/test_library_observer.py' with isolated directories and adapter spy. | 3 |
| OBS-02 | SMB/CIFS is explicitly degraded by default; no recursive polling violates idle budgets. | Observer root-classification tests and performance counters. | 3 |
| ROOT-01 | Offline or error roots are never pruned; reattach schedules bounded catch-up. | 'tests/test_library_startup_catchup.py' with mocked drive states. | 7 |
| UI-01 | Background refresh never unmounts the grid or displays a loading spinner/placeholder/flicker. | 'tests/libraryBackgroundRefresh.test.mjs' DOM identity assertions and Playwright video/trace. | 5 |
| UI-02 | Filters, sort, page, search, scroll, focus, selection, and expanded-card state survive refresh. | 'tests/e2e/library-ingestion.spec.js', one assertion group per state. | 5 |
| UI-03 | An idle-mounted Library receives a later post-commit event and performs exactly one quiet refetch. | Playwright API counters and a fixture publication after idle. | 5 |
| UI-04 | Unique cards key by 'movie_key'; collisions fall back to 'movie_key + path_key' without hiding results. | Node component test plus duplicate-title Playwright fixture. | 5 |
| UI-05 | Failed fetch or poster preload retains the current grid and reports non-blocking status. | Node and Playwright failure injection. | 5 |
| QBT-01 | Completion goes through stability, probe, identity, metadata, poster, projection, transaction, then notification. | 'tests/test_qbittorrent_targeted_ingestion.py': ordered trace and failure at each stage. | 6 |
| QBT-02 | Completion and restart recovery remain idempotent and journal-safe. | Existing journal/recovery suites extended with generation and fingerprint assertions. | 6 |
| START-01 | Startup catch-up uses the coordinator and preserves offline roots. | 'tests/test_library_startup_catchup.py'. | 7 |
| PERF-01 | Known-path ingestion meets the plan latency and zero-global-walk budgets. | 'tests/test_library_ingestion_performance.py' with walk, stat, probe, provider, SQL, CPU, and memory counters. | 8 |
| PERF-02 | Idle watcher meets filesystem, CPU, memory, handle, and thread budgets on every supported root class. | Same module and packaged-runtime monitoring. | 3/8 |
| PERF-03 | Library API latency, SQL statements, and payload do not regress from Gate 0. | Existing isolated benchmark harness compared with 'performance-baseline.json'. | Every gate |
| PKG-01 | Watchdog resolves in packaged Python 3.12, creates no console/child, and portable install is licensed and reproducible. | Packaged-runtime dependency smoke and release inventory. | 3/8 |
| PKG-02 | One SSE stream does not starve packaged API traffic or prevent clean shutdown. | Packaged-runtime concurrency and shutdown test. | 5/8 |
| REG-01 | Existing backend, frontend, Playwright, build, and packaged-runtime suites remain green without reruns for flakiness. | Exact Gate 0 suite inventory in 'regression-baseline.md'. | Every gate |
| ROLL-01 | Each gate's authoritative implementation can be removed without data loss or a parallel fallback. | Gate-specific isolated rollback rehearsal from 'rollback-design.md'. | Every gate |
| SAFE-01 | Test paths resolve inside unique 'CP_TEST_ROOT' before any scan or write. | Shared autouse guard deliberately rejects live catalog/root examples. | Before any test |
| SAFE-02 | Tests cannot restart CP, qBittorrent, or another process. | Process baseline comparison and forbidden launcher mock/assertion. | Before any test |

## Required existing suite comparison

Every implementation gate reruns the Gate 0-approved relevant subset and, at the gate named by the plan, the complete backend, frontend, Playwright, Vite build, and packaged-runtime suites. Results are compared with:

- 'gate-0-baseline.md'
- 'performance-baseline.json'
- 'regression-baseline.md'
- 'contract-to-test-matrix.md'

No contract may be marked covered solely because a neighboring test passed. If instrumentation cannot distinguish a global walk, stat call, provider call, probe, SQL statement, DOM remount, or process change, the proof is incomplete.

