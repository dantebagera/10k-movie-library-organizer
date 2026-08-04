# Gate 10B verification — populated-upgrade startup correction passed

## Outcome

Gate 10B passes. The existing startup catch-up, ingestion coordinator,
AppMetadataStore, and CatalogRepository owners now handle a populated catalog
that predates `library_directory_revisions_v1` without probing, enriching, or
advancing Movie View generation for unchanged accepted files.

No second scanner, inventory, metadata pipeline, catalog writer, schema
migration, or durable Windows file identifier was introduced. This gate did
not start live CP, open the live catalog through SQL, scan `E:\Movies`, touch
qBittorrent, or copy Rao Bahadur. The exact live Gate 10 retry remains a
separate approval boundary.

## Corrected owners

- `LibraryStartupCatchup` still performs its conservative first-checkpoint
  recovery when evidence is missing, but calls the authoritative coordinator
  with `enrich_accepted=False`. Changed-directory catch-up uses the same rule.
- `LibraryIngestionCoordinator` keeps accepted-card enrichment enabled for the
  existing manual/ordinary paths by default. Startup alone disables enrichment
  of unchanged accepted rows. Real file-fact changes, new files, unresolved
  identities, stability, probe, identity, metadata, poster, and publication
  rules remain owned by the same coordinator.
- `CatalogRepository.upsert_records()` now distinguishes card-affecting data
  from operational refresh fields. Updates limited to `updated_at`,
  `identity_revision`, `observed_at`, `probed_at`, or
  `release_years_checked_at` are persisted/exported but do not advance global,
  media, or canonical-media generations. Any material title, identity,
  provider, file-fact, readiness, or card change still advances generation.
- `AppMetadataStore.prune_missing_path_records()` accepts an optional bounded
  root scope. Directory catch-up now removes missing SQL/inventory paths only
  below the named changed directory, preserving records in every other root.

The first upgraded startup may still perform one recovery walk when no
directory-revision checkpoint exists. That is the plan's explicit
evidence-insufficient fallback. It no longer reprobes or re-enriches unchanged
accepted cards. Known external and qBittorrent paths remain exact-path work and
do not use this fallback.

## Gate 10B contract proof

Focused tests passed 53/53 in 10.499 seconds. The new proofs establish:

- a populated catalog with a valid authoritative inventory and no directory
  revision key runs first startup with zero probe, provider, reconcile-path,
  global-generation, media-generation, or canonical-generation change;
- first and changed-directory startup recovery explicitly disable accepted-card
  enrichment while preserving the existing default enrichment behavior;
- operational timestamps/revisions persist without a card generation;
- a material identity-title change still advances media generation exactly
  once;
- bounded directory reconciliation prunes a deleted file from SQL and the
  operational inventory while preserving a sentinel record in another root;
- current-checkpoint startup still skips reconciliation and unavailable roots
  remain conservative.

The broader catalog, canonical, ingestion, observer, final-publication,
startup, qBittorrent, and download-monitor set passed 189/189 in 20.676
seconds. Critical modules passed 51/51 in both forward and reverse order
(3.363/3.501 seconds), proving no order-dependent state leak.

## Complete isolated regression qualification

Every test used `CP_TEST_MODE=1`, a unique OS-temporary `CP_TEST_ROOT`, an
isolated catalog, and isolated media. Temporary roots were verified below the
OS temporary directory and removed after each run.

| Qualification | Result |
| --- | --- |
| Python backend | 1,062/1,062; 147.783 s test time, 148.379 s wrapper |
| Frontend Node | 76/76 across 14 files; 230.369 ms |
| Desktop Playwright | 49/49; 56.6 s test time, 65.824 s wrapper |
| Critical forward/reverse | 51/51 twice; 3.363/3.501 s |
| Packaged/native focused | 98/98; 0.336 s |
| Production frontend build | 1,652 modules, 35 files, 1,798,028 bytes; 3.155 s wrapper |
| Portable package | 285,013,740 bytes, 1,631 entries; 48.174 s |
| Native player smoke | qualified 0.1.20 runtime, 3 s synthetic media, 2,958 ms progress, exit 0 |

The Python run emitted only the same two pre-existing `ResourceWarning`
classes: a temporary buffered-file warning and the `dist/index.html` buffered
reader warning. No warning class was added. The portable package contains the
pinned Watchdog dependency, third-party notice, observer, and coordinator.

## Performance and 30-minute soak

All frozen budgets pass. Machine-readable results are in
`gate-10b-performance.json`.

- Movie View cold: p50 140.991 ms, p95 149.787 ms, maximum 150.505 ms,
  maximum 22 SQL statements.
- Movie View warm: p50 30.876 ms, p95 33.904 ms, maximum 33.954 ms,
  maximum 13 SQL statements.
- Payload: 81,820 bytes; 40 returned cards out of 55.
- Movie View performed zero walks, `isfile` checks, probes, or provider calls.
- Startup internal ready: p50 29.276 ms and p95 30.879 ms against the 279.551
  ms limit.
- External process-ready p50 was 588.119 ms and p95 was 994.872 ms. The p95 is
  slower than Gate 10A's 700.424 ms but has no frozen external-process budget;
  it was recorded without rerunning. Internal startup, the approved budget,
  shows no regression.
- Native observer soak: 1,800.000 seconds, zero idle coordinator calls,
  0.254340% one-core CPU, 0.007948% machine CPU, 352,256-byte warm RSS delta,
  maximum RSS 30,330,880 bytes, maximum private bytes 19,349,504, maximum five
  threads and 213 handles.
- All 40 active events arrived. Latency was p50 1.191 ms, p95 3.938 ms,
  maximum 12.775 ms. Shutdown was clean and the temporary root was removed.

Compared with Gate 10A, SQL counts, filesystem/provider/probe isolation,
payload, internal startup, CPU, RSS, event latency, build/package contents, and
shutdown remain within every frozen limit.

## Diagnosed test issue

The first focused run executed 52 tests: 51 passed and one test errored before
its assertion because it patched nonexistent symbol `app._tmdb_request_json`.
No product code failed. The test was corrected to patch the real provider
boundary, `app.urllib.request.urlopen`; the focused suite then passed 52/52.
After the bounded-delete proof was added, the final focused result was 53/53.
No flaky test was rerun until green.

## Production safety and rollback

Final read-only comparison confirms:

- production catalog SHA-256 remains
  `C8E0F52C65C9A61D8CEF45A522EA897876C73B889783999E3A17EBB90FA47961`;
- no production catalog WAL or SHM exists;
- Rao Bahadur source remains 2,989,813,923 bytes with SHA-256
  `3DFCF693F87A50822BCFF340D4308BB0039749C7EF6EF5A21176DC623BF90587`;
- the approved `E:\Movies\Rao Bahadur ...` destination remains absent;
- CP and all isolated test ports are stopped;
- qBittorrent remains PID 42792 on port 8686 and was not restarted;
- nothing is staged, committed, pushed, tagged, or released.

Gate 10B has no data or schema migration. Rollback is limited to its changes in
`services/library_ingestion.py`, `services/library_startup_catchup.py`,
`services/catalog_repository.py`, `app.py`, and their tests.

## Remaining boundary

Gate 10B resolved and qualified the second mandatory-stop cause. Dante then
approved the exact retry. First-checkpoint recovery finished with generation
7,629 unchanged, and the bounded Rao Bahadur live acceptance passed final-card
publication, one post-commit event, desktop state preservation, and exact
cleanup rollback. See [gate-10-final-verification.md](gate-10-final-verification.md).
