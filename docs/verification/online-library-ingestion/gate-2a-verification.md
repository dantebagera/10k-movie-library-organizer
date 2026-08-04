# Gate 2A verification — passed

## Scope

Gate 2A corrected only the existing shared collection-cache owner in `src/hooks/useMovieCollectionCache.js`. When a catalog or curation invalidation aborts a pending collection request, the cache now restarts that same authoritative request. No Library-only request path or second cache was added.

## Isolated proof

Every run used `CP_TEST_MODE=1`, a new GUID-named `CP_TEST_ROOT` below the operating-system temporary directory, an isolated catalog, and isolated fixtures. The root-overlap assertion against configured live media roots passed before each run.

Exact formerly failing test:

```text
Library collection never shows a false zero and opens the full collection in Discover with one click
1 passed (2.5s)
```

Full desktop suite:

```text
48 passed (56.0s)
```

The successful full run used:

```text
C:\Users\dante\AppData\Local\Temp\cinema-paradiso-gate2a-full-a5b366a60cdd4b0089537cb029a6a71e
```

Its isolated server parent was PID 47376 and its actual port-5117 owner was PID 43452. The exact isolated process tree was stopped and the verified temporary root removed. Ports 5117 and 5119 were closed afterward. Live CP PID 8336 and qBittorrent PID 42792 were untouched.

## Diagnostic record

Two attempted full-suite wrappers did not produce product verdicts:

1. A 120-second shell timeout killed the orchestration wrapper before buffered output returned.
2. A 300-second wrapper redirected Flask output without draining it. The pipe filled, blocked the isolated server, and caused successive navigation timeouts.

The isolated process trees and exact temporary roots were verified and removed after each attempt. The final wrapper inherited server output instead of buffering it and completed normally. These failures were diagnosed; they were not counted as flaky product reruns.

## Outcome

Gate 2 and Gate 2A pass. The prior 47/48 Playwright blocker is resolved without weakening the test or changing backend ingestion behavior.
