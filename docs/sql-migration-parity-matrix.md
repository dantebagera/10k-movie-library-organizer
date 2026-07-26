# SQL Migration Parity Matrix

This is the release checklist for the JSON-to-SQL catalog cutover. SQL is the active catalog authority. JSON is retained only as a rollback export and read-only shadow-comparison input; it is not a second live authority.

## Rules for Every Row

- The SQL row must contain the required state.
- The canonical movie model must expose it.
- Compact projections may intentionally defer detail fields, but expanded details must read them from SQL without a provider request.
- A catalog mutation must advance `catalog_generation` and invalidate server and browser projections that depend on it.
- A list, collection, or followed-release mutation must advance `curation_generation` and invalidate every browser projection that depends on curation state.
- The user must see the same movie identity across relevant pages.

## Workflow Evidence

| Workflow | Before SQL source | Current SQL source and involved state | User-visible invariant and completion proof |
| --- | --- | --- | --- |
| Home statistics versus Maintenance audit | JSON-derived library snapshot and audit state | `media_files` and catalog generation; server library, stats, and maintenance caches | Counts refresh together after a mutation. Proven by `test_home_stats_and_maintenance_share_the_catalog_generation_and_refresh_after_mutation`. |
| Library cards versus Discover owned cards versus Movie List cards | Library JSON, Discover ownership lookup, user-list JSON | `media_files`, canonical model, `/api/library`, `/api/library/check`, `/api/library/details`; browser ownership and source-aware detail caches | The same accepted TMDB/IMDb/title/year identity and plot are shown everywhere. Expanded owned cards on Library, Discover, Movie Lists, Home, and AI Control fetch deferred people, collection, and trailer data from SQL. Only unowned cards may call TMDB. Proven by `test_api_projections_include_canonical_card_metadata_without_provider_calls`, the five-surface Playwright parity test, and the ownership-cache browser test. |
| Summary metadata versus expanded details | TMDB and Plex JSON snapshots | `tmdb_json`, `plex_json`, canonical model, card/list/people projections | TMDB is the default enrichment source when its persisted snapshot exists; Plex remains an intentional fallback source. Compact cards preserve canonical plot and identity while people may be deferred; expanded details resolve those deferred fields from SQL. Proven by catalog audit, SQL fixture tests with provider calls blocked, and the shared `fetchCanonicalMovieDetails` contract. |
| Posters, plots, cast, genres, ratings, collections, and manual overrides | TMDB/Plex JSON plus override JSON | SQL snapshots and durable override records, projected through canonical metadata | The same accepted movie preserves metadata and custom poster without mutating provider snapshots. Proven by SQL fixture, metadata override, poster override, and collection tests. |
| Identity matching, correction, conflict review, and audit | Match JSON and provider-specific records | Accepted identity columns, manual matches, audit state, decision fingerprints | Manual corrections stay locked; conflicts remain reviewable; exact identities can be verified read-only. Proven by identity audit, repair, verification, and Plex manual-match suites. |
| Duplicate groups and upgrade candidates | JSON-derived audit grouping | SQL library candidates and maintenance audit projection | Duplicate and quality groups use the same accepted identity and change after file facts mutate. Proven by SQL fixture and duplicate identity tests. |
| Source search, ownership checks, download submission, cancellation, completed import, and library reconciliation | Source result state, JSON job records, filename follow-up | Stable TMDB/IMDb/Plex identity in job metadata, SQL ownership lookup, job journal, reconcile state | Owned movies do not download; title-only sources are rejected; a user-removed unfinished torrent becomes a normal terminal cancellation without moving files or touching SQL; a completed import hands its original identity to the exact imported file before reconciliation. Recoverable completed payloads always take precedence over cancellation. Proven by SQL fixture plus qBittorrent API/service tests. |
| File View, deletion, rename, and metadata persistence | File JSON plus filesystem scan state | SQL path records and canonical item projections; catalog generation and library cache | Rename/delete changes File View, Library, ownership, stats, and maintenance without a full rescan. Proven by catalog file mutation and SQL fixture tests. |
| Startup reconciliation and background job updates | Metadata checkpoints and qBittorrent job JSON | SQL persisted facts, reconciliation state, qBittorrent journal, catalog generation | Cold start reads SQL without provider calls; pending identity handoffs replay once; completed handoffs do not replay. Proven by SQL fixture and qBittorrent service tests. |
| Navigation and page-local state | Mounted React workspace state and browser scroll | One mounted instance per visited workspace; active workspace visibility and per-workspace scroll positions | Moving between Library, Discover, Movie Lists, Maintenance, AI Control, IPTV, Downloads, and Settings preserves filters, queries, tabs, unsaved form edits, iframe state, and scroll for the session. Proven by the all-stateful-workspaces Playwright navigation test. |
| Lists, collections, followed releases, and curation caches | User-list JSON and browser-local followed-release state | SQL curation tables, `curation_generation`, list cache, collection caches, and browser invalidation events | Every successful curation read exposes its generation; mutations advance it; a newly observed generation clears dependent caches without requiring a catalog rescan. Proven by curation route/API tests and the browser curation-cache test. |

## Fixture Library

`tests/test_sql_migration_parity.py` seeds and exercises:

- a duplicate group and low-quality upgrade candidate;
- a manually corrected identity with a wrong Plex provider match;
- an owned Discover result;
- TMDB plot with a distinct Plex summary;
- a newly imported download and an unmatched file;
- a collection movie and custom poster;
- stable TMDB and IMDb download identity handoff.

## Current Acceptance Evidence

On 2026-07-20, the schema-v6 active-catalog audit passed at catalog generation 298:

- 3,708 SQL records checked and 3,707 accepted canonical movies;
- 7,199 provider snapshots, 31,206 people, and 43,833 ordered credits exposed relationally;
- 3,702 selected TMDB detail providers and 5 selected Plex fallback providers;
- 6 explicitly partial records, with no false provider completion;
- 0 provider calls;
- 0 SQL-row, canonical-model, deferred-detail, projection, or relational-shadow violations;
- SQLite integrity `ok` and 0 foreign-key violations.

The literal legacy JSON comparison was refreshed from the current SQL rollback export and independently passed:

- file records: 3,708 JSON / 3,708 expected / 3,708 SQL;
- TMDB snapshots: 4,749 / 4,749 / 4,749;
- Plex snapshots: 3,572 / 3,572 / 3,572;
- manual matches: 486 / 486 / 486;
- no legacy-only, SQL-only, canonical, document, or provider-call violations.

The immutable cutover archive `data/catalog-migration-backups/cp-catalog-migration-20260716T132416Z.zip` remains pinned by `docs/sql-migration-cutover.json` for historical evidence. The accepted current-state rollback package is `C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260720T001304Z.zip`; it contains 1,150 files and was checksum-verified and rebuilt into a passing shadow catalog.

Desktop browser parity is proven by the Playwright test `Library, Discover-owned, and Movie List cards render one canonical movie contract`. Its compact fixture intentionally omits people, supplies them only through SQL deferred details, forces TMDB details to fail, and verifies Library, owned Discover, owned Movie List, Home, and AI Control render the persisted plot and people without a provider request. The browser ownership-cache test also proves a catalog-generation change invalidates cached ownership results.

The earlier cutover verification passed: 54 JavaScript tests, 19 desktop Playwright workflow tests, the production frontend build, and all 676 Python tests. Normal operational monitoring remains separate from this cutover evidence.

## Catalog-read and local-artwork acceptance addendum

The staged performance/artwork implementation completed on 2026-07-21 without changing the workflow invariants above:

| Acceptance area | Final evidence | Result |
| --- | --- | --- |
| Home and Maintenance statistics | Both projections report 0 duplicate groups, 0 extra files, 0 reclaimable bytes, and 732 upgrade candidates from the same normalized SQL facts. | Passed |
| Library, Discover-owned, and List cards | One canonical card contract is used on all three surfaces; owned expansion uses the canonical details contract. | Passed |
| Plots, posters, cast, directors, genres, ratings, collections, and overrides | Relational audit checked 3,708 files, 3,707 accepted movies, 31,206 people, and 43,833 ordered credits with 0 violations and 0 provider calls. Local artwork relationships are included without changing metadata precedence. | Passed |
| Identity matching, correction, conflicts, and audit | Existing correction/conflict suites plus the live relational and literal rollback shadows passed; manual/custom state remains authoritative. | Passed |
| Duplicates and upgrade candidates | Normalized maintenance projection and Home statistics agree; file fingerprints remain in the authoritative projection. | Passed |
| Source search, ownership, downloads, import, and reconciliation | Existing source/qBittorrent suites passed; owned reads remain provider-free and identity handoffs remain idempotent. | Passed |
| File View, rename, deletion, and persistence | File View uses SQL `file_inventory`; mutation/generation and persistence suites passed without a raw-document fallback. | Passed |
| Startup and background jobs | Fresh SQL readiness was 258.838 ms; first bounded Library response was 476.793 ms; no provider call or ordinary root scan occurred. Artwork scheduling is bounded and resumable. | Passed |
| Navigation and page-state preservation | Desktop Playwright asserts Library paging/filter/selection state after navigation in addition to the existing all-workspace preservation coverage. | Passed |
| Rollback and single authority | JSON remains export/shadow only. Backup v3 restored schema 7, all SQL/user state, and 19,169 unique registered asset files with 0 missing or unexpected checksums. | Passed |

The schema-7 acceptance measurements are recorded in `docs/sql-investigation/catalog-read-performance-final-2026-07-20.json`, `docs/sql-investigation/catalog-artwork-backfill-2026-07-20.json`, and `docs/sql-investigation/catalog-artwork-acceptance-2026-07-20.json`. The stage-by-stage gate record is `docs/sql-investigation/catalog-read-performance-stage-report.md`.

## Writer and keyword search acceptance addendum

The schema-8 writer and keyword implementation was exercised on 2026-07-25 against a SQLite-backup clone of the Gate 0 rehearsal catalogue. Dante then separately approved the controlled live rollout, which completed against the production catalogue with a fresh verified backup and two-start verification.

| Acceptance area | Final evidence | Result |
| --- | --- | --- |
| Existing cast and directors | All 48,469 pre-existing cast/director rows retained their order and logical digest `8acfc9c7b196758c7d314b9a0ce8a7e9688052c0703724fac5cc78bb98a2412b`. | Passed |
| Provider evidence | All 7,440 `source_json` rows retained digest `091101b63f118e112bc09bd239ef46f9fba1ccfcb4069ebd7487a855798e6180`. | Passed |
| Other SQL state | All 25 non-migration tables retained aggregate logical digest `cb330d2102680864d089088702dd6674b6f4da79d1bde5f6cecd2d396095979c`; mismatch list was empty. | Passed |
| Writer projection | 7,527 ordered writer credits were projected into the existing people/movie-credit owner; 3,173 people were inserted and 4,354 reused, with 0 rejected or deduplicated credits. | Passed |
| Keyword projection | 7,925 normalized keywords and 33,909 ordered relationships were projected, with 0 rejected or deduplicated entries. | Passed |
| Library authority | Writer and keyword queries used indexed relational plans; the restored-clone audit checked 3,730 files and 3,729 accepted movies with 0 provider calls or violations. | Passed |
| Discover authority | People/writer discovery stays on TMDB person credits; keyword discovery resolves a TMDB keyword ID and passes it through `with_keywords`; ownership remains on `/api/library/check`. | Passed |
| Expanded owned details | The desktop clone rendered stored writers and keywords through `/api/library/details` with a 200 response and no provider call. | Passed |
| Assets and overrides | SQL-generated rollback documents now include metadata and poster overrides. A relocated browser clone served all 21 observed `/api/assets` requests with 200 responses, with no 409 or 500 response. | Passed |
| SQLite and restart | Schema version 8, integrity `ok`, 0 foreign-key violations, no partial migration objects, and a second open performed no migration rewrite. | Passed |
| Live rollout | Fresh archive `cp-catalog-migration-20260725T172051Z.zip` was checksum verified and rehearsal restored. Production migrated atomically to schema 8 with preserved cast/director and provider-JSON digests, zero migration provider calls, zero parity violations, integrity `ok`, 0 foreign-key violations, and successful first- and second-start desktop/API verification. | Passed |

The final ownership map is `docs/plans/writer-keyword-search-authoritative-paths.md`. The complete command, path, count, digest, parity, runtime, and test record is `docs/plans/writer-keyword-search-stage-e-evidence-2026-07-25.md`.

## Search completeness and Discover pagination acceptance addendum

The search-completeness work was accepted on 2026-07-26 against disposable
schema-8 catalogue clones. It changed neither schema nor catalogue data and
did not require a migration or backfill. The normal runtime and live catalogue
were not used for tests or performance probes.

| Acceptance area | Final evidence | Result |
| --- | --- | --- |
| Git and catalogue authority | Work remained based on clean `master` commit `4f143dfbc7c7a635fe47bdf18f96faa42ef6a4dc`. `services/catalog_store.py` remains the SQLite owner; Library stayed SQL-only; Discover stayed TMDB-owned. | Passed |
| Library keyword completeness | Broad query `s` returned 924 identities across 19 bounded 50-row pages. The page union contained 924 unique identities with ordered-key digest `bef37e297bcb092005ca37e49f30122b58c0823bcf833096c8621ffa578181ce`; each non-empty identity request used two relational reads and zero provider calls. | Passed |
| Library paging and performance | Keyword identity pages expose accurate totals and replace results; selecting an identity uses the existing 40-card Library movie pager. Broad identity pages stayed below the frozen 350 ms cold, warm-median, and warm-p95 limits; the isolated selected-movie page stayed below its 600/500/650 ms limits. | Passed |
| Discover completeness and routing | Keyword and People identities use bounded provider pages; keyword and person relationships use bounded 20-movie pages; normal Discover/Movies uses 40-card pages formed from two TMDB pages and preserves TMDB's 500-page boundary as 250 reachable application pages. No ten-page application cap remains. | Passed |
| Desktop pagination and state | The shared pagination presentation renders Previous / Page X of Y / Next. Explore, Pick a Movie, keyword relationships, and person relationships replace pages without card accumulation. Request cancellation, stale-response rejection, history, filters, selection, detail, and navigation regression coverage passed. | Passed |
| Ownership attachment | `/api/library/check` remained the only local attachment route. A 20-movie request returned 20 authoritative matches with zero provider calls in 18 first-cold reads and 4 warm reads after batching identity keys; cold was 616.564 ms and warm p95 was 359.211 ms. | Passed |
| Complete verification | 772 Python tests, 63 Node tests, the production Vite build, and 35 desktop Playwright tests passed. A 1600 by 1000 isolated schema-8 browser run reached Library keyword page 19 of 19 without prefetching or accumulating cards; SQLite finished with `quick_check=ok`, zero foreign-key violations, and unchanged media generation 6048. | Passed |
| Rollout boundary | No schema migration, catalogue backfill, live-catalogue probe, normal-runtime restart, commit, stage, or push was performed as part of Gate 5 acceptance. | Passed |

The final ownership map is
`docs/plans/writer-keyword-search-authoritative-paths.md`. The gate-by-gate
commands, thresholds, timings, hashes, browser observations, cleanup, and Git
scope are recorded in
`docs/plans/search-completeness-discover-pagination-execution-evidence-2026-07-26.md`.

After Gate 5, Dante separately approved normal-runtime verification. Commit
`bed56a8d3a82665758571709a240af096728e6d2` was started on port 5000 and
passed live desktop Library, Discover, relationship, ownership, Home,
Maintenance, list, collection, playback-control, and Downloads availability
checks. Schema remained version 8, media generation remained 6076, and all
recorded catalogue row counts remained unchanged. The existing Home
followed-release refresh advanced curation generation once and is documented
separately from the search/pagination acceptance.
