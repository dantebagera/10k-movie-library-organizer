# Writer and Keyword Search — Stage A Evidence

Date: 2026-07-25
Starting commit: `923f0b5a8df0d551fca8ec59c97bb3be1bdb9a68`

## Scope

Stage A implements only:

- the explicit catalogue version 7 to version 8 migration;
- writer projection into the existing `people` and `movie_credits` owners;
- relational `keywords` and `movie_keywords` projections;
- relational writer/keyword detail reads;
- migration, parity, JSON-shadow, integrity, rollback, and performance coverage.

Library search, Discover search, and desktop search UI were not changed.

## Isolation and data boundaries

- Every Python test used `CP_TEST_MODE=1` and a unique operating-system temporary `CP_TEST_ROOT`.
- Playwright used `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-playwright-5067a348aca944909b73d8565fba71d9`.
- Provider access was blocked in migration and parity tests.
- The restored Gate 0 database was opened read-only only to confirm the physical version 7 `movie_credits` schema.
- No migration was applied to the restored rehearsal catalogue or the live catalogue.
- No TMDB request, backfill, filesystem scan, or live application restart occurred.

## Migration contract evidence

The isolated migration fixture reported:

- source version: 7;
- target version: 8;
- existing credits: 2;
- existing-credit digest before and after: `799c3f903e2fc117581e992038c40660fa35cd1a910915abe6851ec1c285651d`;
- writer entries processed: 9;
- writer credits inserted: 6;
- writer duplicates: 1;
- writer rejects: 2;
- keyword entries processed: 6;
- keyword relationships inserted: 4;
- keyword duplicates: 1;
- keyword rejects: 1;
- integrity check: `ok`;
- foreign-key violations: 0.

All seven required failure points were injected independently:

1. before table creation;
2. during existing-credit copy;
3. during writer backfill;
4. during keyword backfill;
5. before index creation;
6. before schema-version update;
7. during final validation.

Every injected failure restored schema version 7, the original credit and people digests, zero temporary version 8 objects, integrity `ok`, and zero foreign-key violations. A separate post-migration initialization failure also rolled the whole transaction back and emitted no migration report.

## Automated verification

| Verification | Result |
| --- | --- |
| Focused migration/catalogue/parity Python suite | 53 passed |
| Full Python suite | 739 passed in 83.091 s |
| Frontend Node suite | 63 passed |
| Production Vite build | 1,642 modules; passed in 1.96 s |
| Desktop Playwright suite | 25 passed in 18.7 s |

The full Python suite emitted two existing non-fatal `ResourceWarning` messages for an unclosed temporary file and `dist/index.html`. No test failed.

The repository has no generic `npm test` script. The authoritative frontend command was `node --test tests/*.test.mjs`. The first sandboxed Vite attempt could not read the workspace configuration; the identical build passed outside that filesystem restriction.

## Performance evidence

The 400-movie isolated fixture used the Gate 0 measurement method: 10 warmups and 100 measured iterations.

| Workflow | Median | p95 | Frozen ceiling | Result |
| --- | ---: | ---: | ---: | --- |
| Library first page | 6.988 ms | 7.281 ms | 8.1 ms | Pass |
| Existing Movies search | 9.301 ms | 9.921 ms | 10.6 ms | Pass |
| Owned expanded detail | 2.373 ms | 2.578 ms | 4.7 ms | Pass |

Existing query-count tests remain green: Library paging is bounded to at most 11 SQL statements and owned details to at most 12.

## Stage boundary

Stage A is green and separately reviewable. Stage B Library writer/keyword search must not begin until Dante explicitly approves it.
