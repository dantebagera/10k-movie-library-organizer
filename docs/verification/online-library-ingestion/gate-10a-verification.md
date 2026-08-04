# Gate 10A verification - corrective qualification passed

## Outcome

Gate 10A passes. The existing observer, ingestion coordinator, operational
inventory writer, and startup background-service owner were corrected; no
parallel importer, reconciler, publication rule, catalog source, metadata
pipeline, or frontend card source was introduced.

This gate did not restart Cinema Paradiso, did not touch qBittorrent, and did
not retry the live Rao Bahadur acceptance. Gate 10 remains incomplete until a
separately approved retry proves the live watcher-to-final-card workflow and
desktop no-flicker behavior.

## Corrected authoritative owners

- `services/library_observer.py` now ignores directory `modified` metadata
  noise. Directory `created` and `moved` events still produce bounded directory
  hints.
- `services/library_ingestion.py` collapses pending parent/child directory
  hints in either arrival order and consults the authoritative SQL operational
  inventory checkpoint rather than assuming the legacy JSON file exists.
- `services/catalog_repository.py` treats
  `app_metadata/library_inventory.json` as an operational document. Its
  dedicated replacement path does not advance global, media, canonical-media,
  or asset generations.
- `app.py` writes the inventory through that operational owner, skips unchanged
  writes only after a real SQL or legacy checkpoint exists, and no longer
  starts artwork backfill automatically. Artwork backfill remains available
  only through its existing explicit API/tool owner.
- `app.py` has one `_start_background_services()` startup owner. Normal startup
  starts ingestion/event services without starting a hidden asset mutation.

No schema migration or durable Windows file identifier was added.

## Corrective contract proof

The focused corrective contract suite passed 5/5 in 0.356 seconds, including:

- 5,000 directory `modified` events produce zero coordinator submissions;
- a directory `created` event produces one bounded hint;
- parent/child queue hints collapse in either order;
- the first empty inventory creates a real SQL checkpoint;
- unchanged inventory bookkeeping advances no catalog generation;
- normal background startup creates no timer, asset service, asset file, or
  catalog-generation mutation.

The final SQL-owner focused run passed 49/49. The final relevant ingestion,
catalog, observer, startup, and qBittorrent run passed 187/187.

## Complete regression qualification

All tests used `CP_TEST_MODE=1`, a unique OS-temporary `CP_TEST_ROOT`, an
isolated catalog, and isolated fixture media. Test roots were checked before
execution and removed afterward. No test opened the production catalog,
scanned a live media root, or started/stopped CP or qBittorrent.

| Qualification | Final result |
| --- | --- |
| Python backend | 1,059/1,059; 148.324 s test time, 148.908 s wrapper |
| Frontend Node | 76/76 across 14 files; 213.174 ms |
| Desktop Playwright | 49/49; 66.949 s |
| Critical modules, forward/reverse | 41/41 twice; 1.320/1.319 s |
| Packaged/native focused | 98/98; 0.333 s |
| Production frontend build | 1,652 modules, 35 files, 1,798,028 bytes; 3.008 s |
| Portable package | 285,013,081 bytes, 1,631 entries |
| Native player smoke | qualified runtime, synthetic 3 s media, exit 0, position 2,958 ms |

The portable package contains the pinned Watchdog dependency, its notice, the
observer, and the coordinator. The temporary package and build roots were
removed. The player runtime remained
`0.1.20-qt6.10.3-mpv20260610-lgpl`.

The Python run emitted the same two pre-existing `ResourceWarning` classes
already diagnosed in the baseline: a temporary buffered-file warning and a
distribution index-reader warning. No new warning class appeared.

## Performance and soak comparison

Machine-readable results are in
`gate-10a-performance.json`. Every Gate 0/Gate 8 budget passed.

- Movie View cold: p50 139.118 ms, p95 150.907 ms, maximum 152.359 ms,
  maximum 22 SQL statements.
- Movie View warm: p50 30.040 ms, p95 34.768 ms, maximum 41.743 ms,
  maximum 13 SQL statements.
- Payload: 82,300 bytes for 40 returned cards out of 55.
- Movie View performed zero filesystem walks, `isfile` checks, probes, or
  provider calls.
- Startup internal ready: p50 29.077 ms, p95 31.017 ms against the 279.551 ms
  limit. External process ready: p50 586.912 ms, p95 700.424 ms.
- The full native-observer soak ran 1,800.001 seconds. Idle coordinator calls
  were zero; one-core CPU was 0.246528%, machine CPU 0.007704%, RSS delta
  348,160 bytes, maximum RSS 30,306,304 bytes, maximum private bytes
  19,320,832, maximum 5 threads and 214 handles.
- All 40 active events arrived. Event-to-queue latency was p50 1.038 ms,
  p95 3.883 ms, maximum 10.458 ms. Shutdown was clean.

Compared with Gate 8, latency, SQL, payload, filesystem, startup, CPU, memory,
event delivery, package, and shutdown results remain inside the frozen
budgets. There is no measured regression.

## Diagnosed execution issues

Failures were diagnosed rather than rerun blindly:

1. The first targeted command accidentally used system Python, which lacks the
   already-pinned Watchdog package. Its 23 available tests passed and three
   modules failed at import. The documented repository `.venv` was then used;
   no dependency was installed or changed.
2. The first 187-test run found two real failures: an empty inventory compared
   equal to the fallback `{}`, so no first checkpoint was written. The owner
   was corrected to skip only when an actual SQL/legacy checkpoint exists.
3. `npm test` is not a repository script and ran no tests. The documented
   enumerated `node --test` command then ran all 76 tests.
4. Final review found the coordinator still tested only for the legacy JSON
   checkpoint. It was changed to consult `AppMetadataStore.has_library_inventory()`;
   the focused 49-test run and the full 1,059-test run cover the final code.

## Production safety and exact cleanup

The failed Gate 10 catalog rollback remains byte-for-byte exact:

- production catalog SHA-256:
  `C8E0F52C65C9A61D8CEF45A522EA897876C73B889783999E3A17EBB90FA47961`;
- no production catalog WAL or SHM sidecar exists;
- source video remains 2,989,813,923 bytes with SHA-256
  `3DFCF693F87A50822BCFF340D4308BB0039749C7EF6EF5A21176DC623BF90587`;
- approved destination remains absent;
- CP PID 48100 is absent and port 5000 is not listening;
- qBittorrent remains PID 42792 on port 8686 and was not restarted.

After Dante approved exact cleanup, the 36 checksum-verified orphan artwork
files (703,870 bytes) were moved from the active metadata root into the
recoverable Gate 10 backup quarantine:

`C:\Users\dante\AppData\Local\Temp\cp-gate10-live-backup-66696580e47b44a3bfb7afc767374686\orphan-assets-quarantine`

All 36 filenames match their SHA-256 contents, and none of the manifest files
remain in the active asset root. No unrelated cache file was moved.

## Rollback and remaining gate

Gate 10A has no data/schema migration. Code rollback is limited to the
corrective changes in `app.py`, `services/catalog_repository.py`,
`services/library_ingestion.py`, `services/library_observer.py`, and their new
tests. The quarantined artwork is recoverable from the backup if a later audit
requires it.

The Gate 10A problems are resolved in isolation, but the originally required
live proof is still absent. The first live retry subsequently exposed a
separate deployment-transition gap: a populated production catalog without the
new directory-revision checkpoint performs first-start global recovery and can
advance media generation for timestamp/revision-only enrichment rewrites. See
`gate-10-retry-verification.md`. Gate 10B must correct and qualify that existing
owner before Gate 10 retries the exact Rao Bahadur source and destination.
