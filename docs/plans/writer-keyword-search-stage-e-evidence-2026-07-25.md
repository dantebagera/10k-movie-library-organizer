# Writer and Keyword Search Stage E Evidence

Date: 2026-07-25

Pre-Stage-E commit: `7f295d63f1cf8cc67d13f455ef31b7cfe513f900`

Gate 0 safeguard commit: `923f0b5`

This record covers the pre-live schema-8 shadow migration, Stage E retirement/documentation work, and the separately approved controlled live rollout. The rehearsal evidence below was completed without using the live catalogue as a writable test target. The final sections record the later live migration and two-start verification.

## Isolated inputs and paths

- Gate 0 backup: `C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260725T122413Z.zip`
- Backup SHA-256: `c100279512266ed647df0913a04ba59257448fc266a041984924b22e3b13fc0d`
- Backup size: 607,337,058 bytes
- Rehearsal restore: `C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\rehearsals\gate0-3a68dda-20260725T122413Z`
- Rehearsal manifest: format version 3, app version 2.8.0, 22,839 files, 836,800,143 bytes
- Source schema-7 database: `...\gate0-3a68dda-20260725T122413Z\catalog\catalog.sqlite`
- Migrated shadow: `C:\Users\dante\AppData\Local\Temp\cp-stage-e-shadow-retry-7f295d6\catalog-shadow-v8.sqlite`
- Runtime/parity clone: `C:\Users\dante\AppData\Local\Temp\cp-stage-e-shadow-runtime-7f295d6`
- Asset-complete browser clone: `C:\Users\dante\AppData\Local\Temp\cp-stage-e-shadow-browser-assets-7f295d6`

All application and test runs used `CP_TEST_MODE=1` with `CP_TEST_ROOT` inside the operating-system temporary directory. Test mode blocked external provider access. The browser evidence server used the asset-complete clone on `127.0.0.1:5124` and was stopped after verification.

## Backup and baseline facts

The Gate 0 archive was checksum verified and restored into an empty rehearsal directory. Its manifest recorded:

- 3,730 file records;
- 4,779 TMDB records;
- 3,791 Plex records;
- 484 manual matches;
- 10 lists containing 262 movie entries;
- 1 collection override;
- 11 followed releases;
- 190 qBittorrent jobs;
- 21,295 metadata asset files totalling 446,332,695 bytes.

The source database was opened read-only and cloned with SQLite's backup API. Its modification time did not change.

## Migration preservation evidence

The explicit atomic version 7 to version 8 migration produced:

| Measure | Before | After |
| --- | ---: | ---: |
| `media_files` | 3,730 | 3,730 |
| `canonical_movies` | 3,729 | 3,729 |
| `provider_movie_snapshots` | 7,440 | 7,440 |
| `people` | 34,434 | 37,607 |
| all `movie_credits` | 48,469 | 55,996 |
| writer credits | 0 | 7,527 |
| keywords | 0 | 7,925 |
| movie-keyword relationships | 0 | 33,909 |

Preservation checks:

- Existing cast/director logical digest before and after: 48,469 rows, `8acfc9c7b196758c7d314b9a0ce8a7e9688052c0703724fac5cc78bb98a2412b`.
- Migration's internal existing-credit digest before and after: `b34ce4a804c9f741e9d8f8d49fc1aadd6ef345592bb304b6730c1a4dc59c0a54`.
- Provider source JSON before and after: 7,440 rows, `091101b63f118e112bc09bd239ef46f9fba1ccfcb4069ebd7487a855798e6180`.
- Twenty-five other tables retained aggregate digest `cb330d2102680864d089088702dd6674b6f4da79d1bde5f6cecd2d396095979c`; mismatch list was empty.
- Writer projection: 7,527 processed and inserted, 0 rejected, 0 deduplicated, 3,173 people inserted, 4,354 reused, 51 empty arrays, 3,716 missing arrays.
- Keyword projection: 33,909 entries and relationships, 0 rejected, 0 deduplicated, 3,869 empty arrays, 3,716 missing arrays.
- Invalid JSON: 0. Malformed writer/keyword arrays: 0.
- `PRAGMA integrity_check`: `ok`.
- `PRAGMA foreign_key_check`: 0 rows.
- Reopening schema version 8 returned no migration report and left the database identical.

## Defects found and closed before acceptance

The first full rehearsal migration stopped safely because the deployed schema-7 `movie_credits` column order differed from the fresh schema-7 fixture order. The transaction rolled back completely to version 7 and left no temporary objects. The validator now explicitly accepts only the two known complete version-7 layouts, and a regression test proves their named-column logical digest is identical.

The full parity tools then exposed three comparison defects rather than catalogue loss:

- a missing remote portrait could render as the literal string `"None"`;
- local `/api/assets/...` URLs were compared directly with remote poster/profile provenance;
- unmatched rows were compared against an accepted-only relational projection.

Those tools now normalize local assets through their stored remote provenance and use the existing non-relational canonical projection for unmatched rows. Focused regression coverage was added.

Finally, SQL contained 16 poster overrides that the stale rollback JSON did not contain. Backup generation already preserved them in SQL; the authoritative rollback-document list now also exports `metadata_overrides.json` and `poster_overrides.json`. The runtime clone exported and verified all 16 documents with no mismatch.

## Parity and provider-boundary evidence

`tools/catalog_parity_audit.py` on the runtime clone:

- checked 3,730 files and 3,729 accepted movies;
- selected 3,724 TMDB and 5 Plex detail providers;
- checked 55,996 credits, including 7,527 writer credits;
- checked 7,925 keywords and 33,909 movie-keyword relationships;
- recorded 0 provider calls;
- recorded 0 SQL, canonical, deferred-detail, projection, relational, writer, keyword, integrity, or foreign-key violations.

`tools/catalog_json_shadow_compare.py` on the same clone:

- files 3,730 / 3,730 / 3,730;
- manual matches 484 / 484 / 484;
- Plex records 3,791 / 3,791 / 3,791;
- TMDB records 4,779 / 4,779 / 4,779;
- 0 provider calls;
- 0 legacy-only, SQL-only, canonical, document, or post-cutover exception violations.

## Runtime, query, and browser evidence

The schema-8 route probe recorded:

- schema version 8, integrity `ok`, 0 foreign-key violations, and no provider calls;
- ten owned detail samples: median 6.099 ms, maximum and p95 8.113 ms, exactly 12 SQL statements per request;
- Library first page: cold 546.375 ms / 21 statements, warm 153.743 ms / 13 statements;
- writer search `A L Katz`: 1 result, 13 statements, approximately 253 ms;
- keyword entity search `10th century`: 1 result, 2 statements, approximately 62 ms;
- keyword movie cards: 1 result, 13 statements, approximately 119 ms;
- writer plan used `sqlite_autoindex_movie_credits_1`;
- keyword plans used `idx_keywords_normalized_name` and `idx_movie_keywords_keyword`;
- no N+1 provider, person, or keyword lookup was observed.

The first browser clone intentionally lacked relocated asset files and correctly received 409 from the managed-asset boundary. No application code was weakened. A separate disposable presentation clone copied the rehearsal's 21,295 assets and 16 custom posters, then rebased only that clone's 21,299 ready `media_assets.local_path` rows. It had zero missing files, integrity `ok`, and zero foreign-key violations.

Rendered desktop verification on the asset-complete clone proved:

- Library showed 3,729 accepted titles across 94 pages;
- People search returned `A L Katz`, labelled the relationship `Written films`, and opened `Children of the Corn II: The Final Sacrifice (1992)` under a writer filter;
- Keywords search returned `10th century` and opened `The Last Kingdom: Seven Kings Must Die (2023)` under a keyword filter;
- expanded SQL details rendered plot, IMDb identity, certification, keywords, writers Martha Hillier and Bernard Cornwell, runtime, director, and cast;
- `/api/library/details` returned 200;
- all 21 observed `/api/assets` requests returned 200;
- no 409 or 500 response occurred.

## Compatibility and retirement decision

No temporary search route, duplicate writer-credit store, feature flag, or compatibility wrapper remains. The version 7 to version 8 migration remains because it is the required controlled-rollout path; its retirement criterion is documented in `writer-keyword-search-authoritative-paths.md`. Rollback JSON remains export/shadow evidence only.

## Automated verification

Focused migration and parity tests passed:

- 70 tests in 47.388 seconds during migration validation;
- 34 final focused schema/backup/parity tests in 5.900 seconds.

The final complete Python, Node, production-build, and desktop Playwright results are recorded below after the last verification run:

- Targeted catalogue/parity Python: 151 passed in 38.430 seconds.
- Full Python: 753 passed in 58.510 seconds.
- Node: 63 passed in 190.391 milliseconds.
- Production build: passed with Vite 6.4.3, 1,643 modules transformed, in 2.10 seconds.
- Desktop Playwright: 31 passed in 23.3 seconds using one worker.

The first build attempt was denied by the restricted filesystem sandbox before Vite could load its configuration. The identical build command passed after the required read access was granted; this was an execution-environment denial, not an application or build defect.

The final read-only production-catalogue boundary check reported schema version 7, integrity `ok`, and zero foreign-key violations. No version 8 write was made to it.

## Controlled live rollout

Dante separately approved the controlled live rollout after Stage E commit `682d53663ee66c154ece8ad93308f93deffe1412`. Only the Cinema Paradiso backend was stopped. The running qBittorrent and MPC-HC processes were not touched.

### Final backup and rehearsal restore

- Final backup: `C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260725T172051Z.zip`
- SHA-256: `B9805B270D0EB9985ACB147575ACFCB53F420D5DF73B11C92D5DD3486CE59AD5`
- Manifest: app version 2.8.0, 22,840 files, 836,819,315 bytes
- Semantic contents: 3,730 file records; 4,781 TMDB records; 3,791 Plex records; 484 manual matches; 10 lists with 262 movie entries; 1 collection override; 11 followed releases; 192 qBittorrent jobs; 21,295 asset files totalling 446,332,695 bytes
- Empty rehearsal restore: `C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\rehearsals\live-rollout-final-682d536-20260725T172051Z`
- The restored archive reproduced all manifest file, byte, and semantic counts exactly.

The first backup invocation was blocked before archive creation because the restricted execution environment could not open the database. The identical approved command then completed outside that restriction. No partial archive or catalogue write was produced by the blocked attempt.

### Exact pre-migration live state

The live database was `C:\Users\dante\AppData\Local\Cinema Paradiso\Catalog\catalog-read-cb30c1d963c88463.sqlite`.

- Schema version: 7
- Media generation: 6,020
- `media_files`: 3,730
- `canonical_movies`: 3,729
- `provider_movie_snapshots`: 7,440
- `people`: 34,434
- `movie_credits`: 48,469
- `media_assets`: 21,299
- Existing cast/director logical digest: 48,469 rows, `77bade83dee90071f2e4af0766adc6a9b8cf3c068212abb2ff6bad38b49b021d`
- Provider `source_json` logical digest: 7,440 rows, `de54142846b6a17650e5a5ca848ddb52fe96d2f16d34bab5d524a4c8173213e4`
- Twenty-five preserved tables aggregate digest: `56c0f25e2906fd209b619f3602a07d955ec98f5ea87423fceca08edd613a1c14`
- Integrity: `ok`; foreign-key violations: 0

The verified archive source and live database matched every recorded precondition before migration.

### Live version 7 to version 8 migration

`CatalogStore.initialize()` performed the explicit atomic migration with outbound provider access patched to fail. The migration itself made zero TMDB calls.

| Measure | Before | After |
| --- | ---: | ---: |
| `media_files` | 3,730 | 3,730 |
| `canonical_movies` | 3,729 | 3,729 |
| `provider_movie_snapshots` | 7,440 | 7,440 |
| `people` | 34,434 | 37,607 |
| all `movie_credits` | 48,469 | 55,996 |
| writer credits | 0 | 7,527 |
| keywords | 0 | 7,925 |
| movie-keyword relationships | 0 | 33,909 |

The live migration report recorded 7,527 writer entries processed and inserted, 0 rejected, 0 deduplicated, 3,173 people inserted, and 4,354 existing people reused. It recorded 33,909 keyword entries and relationships, 0 rejected, and 0 deduplicated. Invalid JSON and malformed writer/keyword arrays were both 0. The internal existing-credit digest remained `b34ce4a804c9f741e9d8f8d49fc1aadd6ef345592bb304b6730c1a4dc59c0a54`.

Immediately after migration:

- schema version was 8 and media generation remained 6,020;
- the 48,469 cast/director logical rows still had digest `77bade83dee90071f2e4af0766adc6a9b8cf3c068212abb2ff6bad38b49b021d`;
- the 7,440 provider source JSON rows still had digest `de54142846b6a17650e5a5ca848ddb52fe96d2f16d34bab5d524a4c8173213e4`;
- all 25 preserved tables retained aggregate digest `56c0f25e2906fd209b619f3602a07d955ec98f5ea87423fceca08edd613a1c14`;
- no partial migration object existed;
- integrity was `ok` and foreign-key violations were 0.

### Live parity and rollback-document evidence

The live `catalog_parity_audit.py` run checked 3,730 files, 3,729 accepted movies, 37,607 people, 55,996 credits including 7,527 writers, 7,925 keywords, and 33,909 relationships. It selected 3,724 TMDB and 5 Plex stored-detail providers, made zero provider calls, and reported no SQL, canonical, relational, writer, keyword, integrity, or foreign-key violation.

The first literal JSON comparison correctly stopped because the filesystem rollback JSON predated the final SQL state. The existing authoritative `tools/catalog_writer.py export` path exported and verified all 16 rollback documents. The comparison was then rerun against the explicit final archive and passed:

- 3,730 file records;
- 4,781 TMDB records;
- 3,791 Plex records;
- 484 manual matches;
- zero provider calls;
- zero count, canonical, document, post-snapshot, deletion, or post-cutover violations.

The same parity audit and explicit-archive JSON-shadow comparison passed again after the second application start. The final JSON-shadow result checked 3,730 records at media generation 6,020 with no differences or violations.

Two diagnostic invocations accidentally pointed at `%LOCALAPPDATA%\Cinema Paradiso` and its empty `data` child rather than the configured `C:\Users\dante\Desktop\cinema paradiso\data` directory. Their zero-record results were rejected rather than accepted as evidence. The two 400 KB `.catalog-test.sqlite` files and the empty directory created by those probes were removed after timestamp and path verification. The active catalogue was never targeted by that cleanup.

### First and second application starts

The first live start reproduced the expected desktop behavior:

- Home: 3,730 files, 0 duplicate groups, 1 unmatched file, and 728 low-quality files;
- Library: 3,729 accepted movies across 94 pages;
- People writer search: `A L Katz` -> `Written films` -> `Children of the Corn II: The Final Sacrifice`;
- existing actor search: `Alexander Dreymon` retained `Acting credits`;
- existing director search: `Edward Bazalgette` retained `Directed films`;
- keyword search: `10th century` -> `The Last Kingdom: Seven Kings Must Die`;
- owned expanded details rendered the stored plot, IMDb identity, certification, 12 keywords, writers Martha Hillier and Bernard Cornwell, 111-minute runtime, director, and cast;
- Discover People returned four written films for A L Katz and attached local ownership through the existing ownership route;
- Discover Keywords resolved TMDB keyword 235499, returned 19 remote movies, and attached local ownership through the same authoritative route.

Home and Maintenance agreed at generation 6,020: 3,730 files, 3,730 unique titles, 0 duplicate groups, 0 extra copies, 1 unmatched file, 728 upgrade candidates, and 0 reclaimable bytes. Followed releases remained 11; lists remained 10 with 262 entries.

Observed warm live timings were approximately 153.3 ms for the Library first page, 252.2 ms for writer cards, 61.1 ms for keyword entities, 121.0 ms for keyword cards, and 5.7 ms for owned expanded details. All returned 200.

The exact first backend process was stopped and the port was proved closed before the second start. Its log contained 19 asset requests, all 200 or 304, with no 409 or 500 response.

On the second start:

- reopening the schema-8 catalogue returned no migration report;
- the repeated live parity and JSON-shadow audits passed with zero provider calls;
- the desktop repeated Library writer search, Library keyword search, owned result, and expanded SQL details successfully;
- all eight machine-readable route checks returned 200;
- the route matrix returned one A L Katz writer result, one `10th century` keyword result, the expected owned titles, 12 stored keywords, the two expected writers, runtime 111, certification R, and TMDB identity 948713;
- Home and Maintenance again agreed at generation 6,020, with 3,730 files, 3,730 unique titles, 0 duplicate groups, 0 extra copies, 1 unmatched file, 728 upgrade candidates, and 0 reclaimable bytes;
- followed releases remained 11.

The existing startup artwork owner registered and materialized 1,610 writer portraits on the second start. Every added asset is a ready, owned TMDB portrait; every file exists; every added person-asset relationship is selected; no asset or relationship was removed; and zero pre-existing essential asset rows changed. This is expected derived artwork enrichment through the existing `media_assets` and `person_assets` owner, not migration state or a second writer-credit store.

The final live database contains 22,909 media assets and 19,077 person-asset relationships. Integrity remains `ok`; foreign-key violations remain 0. The 21 other common non-migration tables match the pre-migration restore exactly. Expected differences are limited to schema metadata, people/writer credits, derived portrait assets, and the followed-release check timestamps. Only `followed_releases.json` changed among stored source documents, matching the explicitly exercised followed-release check.

The second-start log recorded 77 HTTP requests, zero 4xx/5xx responses, and zero traceback, migration, integrity, or foreign-key error patterns. The final backend remains running on port 5000 under listener PID 48692.

### Controlled-rollout command record

The principal commands were run from `C:\Users\dante\Desktop\cinema paradiso` with `.venv\Scripts\python.exe`. PowerShell process commands resolved the exact port-5000 owner before either stop and never targeted qBittorrent or MPC-HC.

```text
git -c "safe.directory=C:/Users/dante/Desktop/cinema paradiso" status --short
git -c "safe.directory=C:/Users/dante/Desktop/cinema paradiso" rev-parse HEAD
.venv\Scripts\python.exe tools\catalog_migration_backup.py backup --project-root . --output-dir "C:\Users\dante\AppData\Local\Cinema Paradiso\Backups"
.venv\Scripts\python.exe tools\catalog_migration_backup.py verify "C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260725T172051Z.zip"
.venv\Scripts\python.exe tools\catalog_migration_backup.py restore "C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260725T172051Z.zip" "C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\rehearsals\live-rollout-final-682d536-20260725T172051Z"
.venv\Scripts\python.exe -  # read-only precondition counts/digests/integrity assertions
.venv\Scripts\python.exe -  # CatalogStore.initialize migration with provider access blocked and complete postcondition assertions
.venv\Scripts\python.exe tools\catalog_parity_audit.py --project-root . --max-errors 100
.venv\Scripts\python.exe tools\catalog_writer.py export --project-root .
.venv\Scripts\python.exe tools\catalog_writer.py verify --project-root .
.venv\Scripts\python.exe tools\catalog_json_shadow_compare.py --user-data-dir "C:\Users\dante\Desktop\cinema paradiso\data" --cutover-archive "C:\Users\dante\AppData\Local\Cinema Paradiso\Backups\cp-catalog-migration-20260725T172051Z.zip" --max-errors 100
.venv\Scripts\python.exe app.py
.venv\Scripts\python.exe -  # localhost route, performance, second-open no-op, logical digest, asset-preservation, integrity, and foreign-key assertions
```

The long inline Python assertions were deliberately not installed as a parallel migration or safety tool. They opened the approved database/archive read-only except for the one explicit `CatalogStore.initialize()` migration call and exercised the existing repository, backup, parity, JSON-shadow, and route owners.

## Final approval boundary

The separately approved controlled live rollout is complete. The production catalogue is now schema version 8 and has passed migration, immediate parity, first-start behavior, second-start idempotence, desktop rendering, data-preservation, integrity, provider-boundary, and performance checks. There is no automatic next gate: any further catalogue or search change requires a new explicit scope and approval.
