# Writer and Keyword Search Stage E Evidence

Date: 2026-07-25

Pre-Stage-E commit: `7f295d63f1cf8cc67d13f455ef31b7cfe513f900`

Gate 0 safeguard commit: `923f0b5`

This record covers the pre-live schema-8 shadow migration and Stage E retirement/documentation work. The live Cinema Paradiso catalogue was not migrated, backfilled, audited, or used as a writable test target.

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

## Approval boundary

Stage E completion does not approve the controlled live rollout. The live catalogue remains at schema version 7. A fresh final backup, live migration, post-migration audits, and second-start verification require Dante's explicit next approval.
