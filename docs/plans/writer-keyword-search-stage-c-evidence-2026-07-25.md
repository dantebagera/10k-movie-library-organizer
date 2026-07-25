# Writer and Keyword Search - Stage C Evidence

Date: 2026-07-25
Starting commit: `dd086e5590f5052876c905a4a7392abc655a22b6`

## Scope

Stage C implements only Discover search infrastructure:

- extend the existing TMDB person-credit route to resolve writer filmographies;
- add TMDB keyword identity resolution;
- pass the selected TMDB keyword ID through the existing `/api/tmdb/discover` route;
- preserve the existing movie/person request sequencing, relationship paging, filters, ownership attachment, and remote-result boundary;
- add focused backend, source-contract, and desktop browser regression coverage.

The shared Writer controls, Keywords search-mode option, keyword result cards, and other visible desktop controls remain Stage D work.

## Authority and behavior

- Discover remote movie results remain TMDB-owned.
- `/api/tmdb/person_movies` remains the single person-to-movie relationship route. Writer results use the canonical accepted jobs `Writer`, `Screenplay`, `Story`, and `Novel`.
- `/api/tmdb/keywords/search` returns deduplicated TMDB keyword identities and does not persist remote results.
- `/api/tmdb/discover` remains the single movie-discovery route. A keyword relationship adds `with_keywords=<TMDB keyword ID>` to that route rather than introducing a parallel keyword-movie implementation.
- The existing Discover `checkOwnership` path remains the only local ownership attachment step for remote movies.
- Existing Movies search behavior was not changed.
- Existing actor and director filtering was not changed.
- Remote writer and keyword tests fail if the application attempts to call the metadata store.
- No schema, migration, backfill, Library-query, or canonical projection code changed in Stage C.

## Request, paging, and error contracts

Focused coverage proves:

- writer credits exclude producer/director jobs and deduplicate a movie credited under more than one accepted writing job;
- keyword identity, not movie-title text, drives keyword discovery;
- keyword discovery preserves the existing Discover genre, year, rating, vote, sort, and page parameters;
- keyword search rejects missing configuration and missing queries;
- TMDB HTTP failures retain the existing API error shape;
- person, keyword, movie-feed, and relationship requests share sequence-based stale-response protection;
- invalidating a request clears its loading state;
- restoring Discover history invalidates older in-flight requests;
- ownership checks occur only after the current relationship response wins the sequence guard.

The desktop Playwright test starts a deliberately delayed People request, submits a newer request, then releases the old response. Only the newer person remains visible and the Search button returns to its enabled state.

## Isolation and live-data boundary

All Python application tests used `CP_TEST_MODE=1` and a temporary `CP_TEST_ROOT`.

Recorded isolated paths:

- focused architecture: `C:\Users\dante\AppData\Local\Temp\cp-stage-c-focused-architecture`
- focused contracts: `C:\Users\dante\AppData\Local\Temp\cp-stage-c-focused-contracts-2`
- provider boundary: `C:\Users\dante\AppData\Local\Temp\cp-stage-c-provider-boundary`
- full Python: `C:\Users\dante\AppData\Local\Temp\cp-stage-c-full-python-20260725`
- performance: `C:\Users\dante\AppData\Local\Temp\cp-stage-c-performance-20260725`
- final Playwright: `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-playwright-91470d9f00e441b5bee7026a5635b530`

The live catalogue was opened only through a SQLite read-only URI with `PRAGMA query_only=ON`:

- path: `C:\Users\dante\AppData\Local\Cinema Paradiso\Catalog\catalog-read-cb30c1d963c88463.sqlite`
- schema version: 7
- `keywords`/`movie_keywords` tables present: none
- database modification time before and after the check: unchanged

No live migration, schema initialization, backfill, audit, repair, scan, provider refresh, or application restart occurred.

## Provider calls and performance

The isolated mocked-provider benchmark used 10 warmups and 200 measured requests per workflow:

| Workflow | Median | p95 | Provider calls |
| --- | ---: | ---: | ---: |
| Writer credits, 80 crew rows / 40 unique movies | 0.545 ms | 0.605 ms | 210 for 210 requests |
| Keyword identity resolution, 20 identities | 0.176 ms | 0.193 ms | 210 for 210 requests |
| Keyword discovery, 20 movies | 0.276 ms | 0.317 ms | 210 for 210 requests |

Each workflow made exactly one mocked TMDB request per application request. No per-result provider calls or persistence calls occurred. These measurements cover application-side transformation overhead; real TMDB network time is provider-dependent.

## Automated verification

| Verification | Result |
| --- | --- |
| Focused Discover Python/source suite | 44 passed |
| Full Python suite | 748 passed in 87.836 s |
| Frontend Node suite | 63 passed |
| Production Vite build | 1,642 modules; passed in 2.04 s |
| Focused desktop stale-response race | 1 passed |
| Full desktop Playwright suite | 26 passed in 22.3 s |

The full Python suite emitted the same two known non-fatal `ResourceWarning` messages recorded in Stages A and B: one temporary file and `dist/index.html`.

## Resolved verification interruptions

- The initial focused tests failed before implementation because writer relationships fell back to actor behavior, keyword routes did not exist, and the frontend identity paths were absent.
- An initial keyword-movie route duplicated the existing Discover responsibility. It was removed before acceptance; keyword IDs now extend `/api/tmdb/discover`.
- The restricted build attempt could not read the Vite workspace configuration. The identical approved build outside that restriction passed.
- A nested PowerShell Playwright launch encountered the previously observed duplicate `Path`/`PATH` environment issue before running tests. Invoking the existing isolated script in the current process with process-scoped execution-policy bypass avoided the environment duplication.
- The first browser race probe used the old production bundle and correctly demonstrated the old stale-response behavior. After the required production build, the unchanged race test passed in isolation and in the full suite.

## Commands

- `.venv\Scripts\python.exe -m unittest tests.test_tmdb_details_transform tests.test_unified_movie_card_ui tests.test_discover_search_race_ui`
- `.venv\Scripts\python.exe -m unittest discover -s tests`
- `node --test tests/*.test.mjs`
- `npm.cmd run build`
- `tools\run_playwright_e2e.ps1 -g "Discover People search ignores a stale response"`
- `tools\run_playwright_e2e.ps1`
- isolated mocked-provider timing probe
- read-only SQLite URI schema check with `PRAGMA query_only=ON`

## Stage boundary

Stage C is green and separately reviewable. Stage D shared desktop Writer/Keyword controls must not begin until Dante explicitly approves it.
