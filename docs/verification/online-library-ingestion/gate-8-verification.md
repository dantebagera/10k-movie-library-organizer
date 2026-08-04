# Gate 8 verification — passed

## Final regression results

- Backend: 1,053/1,053 in 150.489 seconds.
- Frontend Node: 76/76 across 14 explicitly named files in 221.7946 ms.
- Production build: 1,652 modules, 35 files, 1,798,028 bytes.
- Desktop Playwright: 49/49 in 1.0 minute, fresh isolated production build.
- Packaged/native focused suite: 98/98.
- Critical ingestion modules in forward and reverse order: 35/35 twice.
- Portable assembly: 285,012,364-byte ZIP, 1,631 files, watchdog pin/notice and new services present; temp package removed.
- Native player: three-second synthetic fixture reached progress at 958/3000 ms in built-in mode with zero OS fallback; fixture removed.

## Diagnosed failure, not hidden as flake

The first final discovery ran 1,049 tests and failed 9. All failures used tiny text bytes as movie fixtures; the new mandatory probe correctly classified them as corrupt before the identity behavior those tests intended to exercise. The fixtures were corrected to inject an explicit successful probe. During diagnosis, a real bug was found: poster-preparation failure still called the publication callback with an empty list. The coordinator now bypasses publication entirely, retries boundedly, then records a File View failure. Focused proof passed before the one clean final discovery.

The two Gate 0 resource warnings remain (a temporary catalog file and a buffered `dist/index.html` reader). No new warning class appeared.

## Performance and isolation

See `gate-8-performance.json`. Every API, SQL, payload, walk, probe/provider, startup, observer CPU/RSS, event-latency, and shutdown budget passes. Movie View performs zero filesystem walks, `isfile` calls, probes, and provider calls. Warm latency increased relative to Gate 0 but remains well inside the explicit +50 ms budget; SQL counts did not increase and payload is smaller.

Every new/runtime measurement set `CP_TEST_MODE=1`, used a GUID-named `CP_TEST_ROOT` below the OS temp directory, and created only isolated catalog/media/assets. Successful roots were removed. No production catalog or live media root was opened or scanned.

## Failure and recovery coverage

Observer event/queue insertion, stability wait, probe/identity/metadata/poster rejection, pre-transaction invisibility, transaction rollback, post-commit event ordering, slow-client pressure/reconnect, held browser fetch, and React state preservation are covered across observer, coordinator, final-publication, broker, Node, and Playwright tests. qBittorrent journal recovery and startup checkpoint recovery remain in their established suites.
