# Search Completeness and Discover Pagination: Zero-Regression Plan

Status: approved for planning and handoff only. Implementation has not started.

Proposed task name:

`Search Completeness and Discover Pagination - Zero Regression`

Current planning baseline:

- Repository: `C:\Users\dante\Desktop\cinema paradiso`
- Branch: `master`
- Observed clean commit: `4f143dfbc7c7a635fe47bdf18f96faa42ef6a4dc`
- Application version: 2.8.0
- Live catalogue: schema version 8 after the accepted writer/keyword rollout
- This work is a code, API, query, and desktop-UI change. It does not require a catalogue migration or backfill.

The implementation task must recheck every baseline fact. This document does not authorize implementation, Git staging, a commit, a process restart, a live-catalogue write, or work beyond the currently approved gate.

## 1. Goal

Remove Cinema Paradiso's arbitrary total-result truncation while keeping every request and rendered page safely bounded.

The completed behavior must provide:

1. Every Library keyword identity matching the existing search semantics is reachable.
2. Every TMDB keyword identity that the provider makes available is reachable.
3. Every TMDB movie page for a selected keyword is reachable within the provider's supported pagination contract.
4. Discover person, writer, and keyword movie results use standard Previous / Page X of Y / Next pagination instead of accumulated Load more behavior.
5. Library keyword searches remain SQL-only and make zero provider calls.
6. Discover remains TMDB-owned and attaches local ownership through the existing authoritative ownership path.
7. Existing Movies, Actor, Director, Writer, lists, collections, cards, details, filters, selection, navigation, and ownership behavior do not regress.

The product principle is:

> Unlimited reach through bounded pages, never an unlimited one-shot response.

## 2. Explicit separation of concerns

The implementation must keep these three concerns separate.

### 2.1 Search completeness

Search completeness determines whether every valid match can eventually be reached.

- A Cinema Paradiso total-result ceiling is not allowed.
- Provider-imposed limits remain provider facts and must be reported honestly.
- No valid result may disappear merely because it is beyond the first 50, 100, or 10 pages.

### 2.2 Display pagination

Display pagination determines how many results are rendered simultaneously.

- A page size is not a total-result limit.
- Changing pages replaces the visible result cards; it does not append indefinitely.
- The interface remains responsive regardless of total result count.

### 2.3 Query and provider performance

Performance determines how a page is produced.

- Removing `LIMIT` without redesigning the query is forbidden.
- Fetching every TMDB page in advance is forbidden.
- Accurate totals must come from the authoritative local query or provider response, not from loading all result objects into the browser.

## 3. Confirmed current behavior and defects

These facts were observed during planning and must be verified again at Gate 0.

### 3.1 Library keyword identities

- `src/features/library/LibraryWorkspace.jsx` requests `view=keywords` with `limit=50`.
- `services/catalog_store.py` defaults to 50 and clamps the maximum to 100.
- Keyword identity matching is normalized, case-insensitive prefix matching.
- The current SQL groups and counts matching owned relationships before its final `LIMIT`.
- Consequently, the result cap limits the response and rendered cards but does not adequately limit broad-prefix database work.

The live catalogue observed during planning contained:

- 7,925 keyword identities;
- 33,909 movie-keyword relationships;
- 506 keyword identities beginning with `a`;
- 924 keyword identities beginning with `s`.

Preliminary read-only measurements, not acceptance thresholds:

- an unbounded all-keyword query did not finish within 120 seconds;
- `a` and `s` did not finish within 10 seconds even with the current 50-row result limit;
- `war`, 31 identities, was approximately 505 ms;
- `love`, 16 identities, was approximately 344 ms;
- `space`, 30 identities, was approximately 485 ms.

These measurements prove that deleting the limit is not an acceptable implementation. Gate 0 must repeat performance analysis on a temporary SQLite backup clone, not against the live database.

### 3.2 Library keyword movies

- Selecting a keyword already uses the normal Library card query.
- Results are paged at 40 movies per page.
- The API reports total results and total pages.
- This path already provides bounded display without intentional total truncation.

This behavior must remain unchanged except for any strictly necessary shared pagination regression fix.

### 3.3 Discover keyword identities

- The frontend always requests `/api/tmdb/keywords/search?...&page=1`.
- The backend accepts a page but clamps it to 10.
- The backend returns `page`, `total_pages`, and `total_results`.
- The UI does not expose another keyword-identity page.

This is truncation, not complete pagination.

### 3.4 Discover relationship movie results

- Normal Discover movie feeds already use the shared `Pagination` component.
- Person, writer, and keyword relationship contexts use `loadContextPage`.
- The current relationship path loads 20 movies, appends subsequent pages, and displays Load more.
- The frontend already stores `discoverPage`, `discoverTotalPages`, and `discoverTotalResults`.
- The current Discover backend clamps requests and returned totals to 10 Cinema Paradiso pages.
- The selected keyword path uses the existing `/api/tmdb/discover` route with `with_keywords`; no separate keyword-movie owner is required.
- The person route retrieves TMDB movie credits, filters by Actor, Director, or Writer, computes a local result total, and then slices 20 results per page.

The required change is page navigation and cap retirement, not a second remote search implementation.

### 3.5 Collections and lists

- Collection and user-list relationship views currently load finite complete arrays and do not use the remote Load more path.
- They are not part of the approved Load more replacement unless Gate 0 proves that the same pagination defect applies.
- Do not redesign collection or list browsing merely for visual uniformity.

## 4. Non-negotiable architecture and safety rules

1. `services/catalog_store.py` remains the SQLite catalogue owner.
2. `services/catalog_repository.py` remains the catalogue repository boundary.
3. `services/canonical_catalog.py` remains the relational canonical owner.
4. The existing `/api/library?view=keywords` route remains the Library keyword-identity path.
5. The existing `/api/tmdb/keywords/search` route remains the TMDB keyword-identity path.
6. The existing `/api/tmdb/discover` route remains the TMDB movie-discovery path, including keyword discovery through `with_keywords`.
7. The existing `/api/tmdb/person_movies` route remains the Actor, Director, and Writer movie-credit path.
8. The existing ownership-check path remains the only local-ownership attachment owner for remote Discover results.
9. The existing shared `Pagination` component must be improved or reused. Do not create a Discover-only duplicate.
10. Library keyword search and owned Library details remain SQL-only with zero TMDB calls.
11. Discover remote results remain TMDB-owned and must not be copied into a second persistent local search store.
12. Do not parse `provider_movie_snapshots.source_json` in Library search.
13. Do not create a new schema version, index, table, trigger, materialized count, cache authority, compatibility route, or feature flag without stopping for a separate architecture approval.
14. Do not preserve obsolete `limit` or Load more behavior "just in case." Update all in-repository callers and remove the retired path after coverage proves it is unused.
15. Do not change Movies search semantics.
16. Do not change current normalized prefix semantics for Library keyword identity search unless Dante separately approves that product change.
17. Desktop only. Do not introduce unrelated mobile or responsive work.
18. Do not run performance experiments, broad tests, parity tools, repair tools, migrations, or backfills against the live catalogue.
19. Do not stage or commit unrelated work.
20. Any unexplained correctness, ordering, count, ownership, navigation, provider-call, performance, or visual difference stops the gate.

## 5. Product and API contract to approve

No implementation begins until Dante approves this contract after Gate 0 evidence.

### 5.1 Library keyword identity contract

Proposed request:

```text
GET /api/library?view=keywords&q=<normalized-prefix>&page=<positive-int>&page_size=50
```

Proposed response:

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total_pages": 1,
  "total_results": 0,
  "count": 0,
  "source": "catalog",
  "catalog_generation": 0
}
```

Rules:

- `page_size=50` is the initial display size, not a total-result ceiling.
- The backend may enforce a safe maximum page size, but must never clamp `total_results`.
- `count` means items on the current page.
- `total_results` means all owned keyword identities matching the current prefix.
- `total_pages` is derived from the authoritative total.
- Invalid pages are normalized consistently with existing Library pagination.
- Empty query returns no identities and does not enumerate all 7,925 keywords.
- Ordering remains deterministic across pages.
- Exact normalized match remains first.
- No identity may repeat or disappear between stable pages.
- Selecting an identity continues to use exact TMDB keyword ID when present and exact normalized name otherwise.
- The old unpaged `limit` contract is removed after all in-repository callers and tests move to the page contract.

### 5.2 Discover keyword identity contract

Proposed request:

```text
GET /api/tmdb/keywords/search?q=<query>&page=<positive-int>
```

Rules:

- Preserve TMDB keyword identity and provider ordering.
- Return TMDB's `page`, `total_pages`, and `total_results` without a Cinema Paradiso 10-page truncation.
- Validate against the provider's supported page range rather than an arbitrary application ceiling.
- Request only the selected page.
- Do not prefetch later pages.
- Do not persist remote keyword result pages.
- Provider errors remain visible and retryable.
- A newer query or page request must not be overwritten by an older response.

### 5.3 Discover movie-page contract

Applies to:

- keyword-filtered movies;
- Actor movies;
- Director movies;
- Writer movies.

Rules:

- Replace Load more with Previous / Page X of Y / Next.
- Preserve the current provider-native 20-result relationship page size unless Gate 0 measurements justify a separately approved change.
- A page change replaces visible results instead of appending.
- Changing filters or relationship identity resets to page 1.
- Changing page preserves the relationship path, filters, sorting, and ownership mode.
- Back navigation restores the prior page, visible results, total, relationship context, and filter state.
- Expanded-card state is cleared or restored according to the existing navigation contract; do not leave an expansion attached to a movie no longer on the page.
- Selection state follows the existing Discover bulk-selection contract and must be explicitly tested across pages.
- Ownership is checked only for the loaded page.
- TMDB total results describe the remote result set.
- With an ownership filter active, the UI reports owned/unowned results on the current TMDB page. It must not claim a global owned count that has not been computed.
- A page with zero locally owned results is still a valid TMDB page and must allow navigation onward.

### 5.4 Provider boundaries

- TMDB keyword search is natively paged.
- TMDB Discover is natively paged and supports `with_keywords`.
- Provider-supported maximum pages and HTTP 429 behavior are external constraints, not Cinema Paradiso result caps.
- The implementation must respect provider responses and cannot promise results that TMDB does not expose.
- Do not fetch every provider page merely to compute local ownership totals.

## 6. Gate 0: freeze the new stable baseline

Gate 0 is read-only except for temporary isolated test artifacts. No production file edit begins before approval.

### 6.1 Git and worktree inventory

Record:

```powershell
git -c safe.directory='C:/Users/dante/Desktop/cinema paradiso' status --short --branch
git -c safe.directory='C:/Users/dante/Desktop/cinema paradiso' rev-parse HEAD
git -c safe.directory='C:/Users/dante/Desktop/cinema paradiso' log -10 --date=iso --format='%h %ad %s'
```

- Inspect every modified and untracked file.
- Confirm whether `4f143dfbc7c7a635fe47bdf18f96faa42ef6a4dc` is still the accepted baseline.
- Classify any later changes by feature and approval status.
- Do not discard, overwrite, stage, or commit unrelated work.

### 6.2 Confirm isolated data paths

- Create a consistent SQLite backup clone in the operating-system temporary directory.
- Use temporary user data, movie roots, cache, asset, and database paths for tests.
- Block provider access in owned Library tests.
- Never aim a broad prefix benchmark at the live catalogue again.
- Never run migration, backfill, repair, parity mutation, or broad test tooling against `%LOCALAPPDATA%\Cinema Paradiso`.
- This task must not change schema version 8 or live catalogue contents.

### 6.3 Record the current contracts

Capture exact source and route behavior for:

- Library keyword identity request and response;
- Library keyword selected-movie pagination;
- Discover keyword identity page 1;
- Discover keyword movie Load more;
- Discover Actor, Director, and Writer Load more;
- normal Discover Pagination;
- Discover path history and back restoration;
- ownership filters and per-page counts;
- bulk selection across the currently loaded result set;
- provider error and stale-response behavior.

### 6.4 Baseline automated verification

Run targeted tests first, then:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node --test tests/*.test.mjs
npm.cmd run build
npm.cmd run test:e2e
```

Record exact discovered test counts. If Node wildcard behavior is unreliable in PowerShell, enumerate repository-local `.test.mjs` files safely and record the executed list.

### 6.5 Baseline browser evidence

Using isolated data and the desktop browser, record:

- normal Discover page navigation;
- keyword identity search showing only the first provider page;
- keyword movie Load more appending results;
- Actor, Director, and Writer Load more appending results;
- Library keyword identity search;
- Library keyword movie pages;
- page/filter/navigation state after moving between Library and Discover;
- ownership badges and owned expanded details;
- lists, collections, card actions, and bulk-selection behavior relevant to the touched grid.

### 6.6 Baseline performance evidence

On the isolated schema-8 clone, measure cold, warm median, and p95 for:

- exact Library keyword identity;
- ordinary multi-character prefix;
- one-character broad prefix;
- first page and a late page;
- total-count query;
- keyword-selected Library movie first and last page;
- Discover keyword identity request;
- Discover keyword movie page;
- Actor, Director, and Writer page;
- ownership attachment per remote page.

Record:

- SQL statements;
- query plans;
- returned rows;
- serialized response bytes;
- provider calls;
- browser rendered-card count;
- overlapping request behavior.

Gate 0 must propose numerical acceptance thresholds before implementation. Do not invent thresholds after seeing the new implementation.

### 6.7 Gate 0 stop

Report:

- worktree classification;
- baseline Git commit;
- isolated paths;
- test results;
- current route contracts;
- current result caps;
- query plans and performance;
- browser behavior;
- proposed numerical thresholds;
- exact files expected in Gate 1.

Wait for Dante's approval. Do not begin implementation.

## 7. Gate 1: approve the detailed query and API design

Gate 1 is design and focused test scaffolding only unless Dante approves implementation.

### 7.1 Library query-design proof

Compare candidate SQL designs on the isolated clone.

Requirements:

- preserve normalized prefix semantics;
- preserve exact-match-first behavior;
- preserve deterministic ordering;
- preserve correct owned `movie_count`;
- provide accurate `total_results`;
- provide stable `LIMIT/OFFSET` or equivalent page boundaries;
- use the existing relational keyword/movie owners;
- avoid full canonical projection decoding;
- avoid N+1 count queries;
- avoid a materialized count source unless separately approved;
- require no new schema object unless separately approved.

Test:

- empty, exact, common, broad, non-Latin, and no-match prefixes;
- first, middle, last, and out-of-range pages;
- insertion/deletion generation changes;
- equal names, case/whitespace normalization, and deterministic ties;
- identity deduplication;
- repeated page requests;
- query interruption/failure without state mutation.

If no query design meets the approved threshold without a new index or schema object, stop and present the measured alternatives. Do not silently add an index or schema migration.

### 7.2 Discover page-mapping proof

Document:

- provider page to Cinema Paradiso page mapping;
- behavior for 20-result relationship pages;
- behavior of the existing 40-result normal Discover pages that combine two TMDB pages;
- provider maximum-page handling;
- last partial page;
- out-of-range page;
- changed provider totals between requests;
- duplicates or missing provider rows;
- HTTP 401, 429, timeout, malformed response, and empty page behavior.

### 7.3 State contract proof

Specify the state transition for:

- new query;
- next page;
- previous page;
- filter change;
- ownership filter change;
- relationship change;
- entering expanded details;
- leaving and returning through Discover history;
- navigating to Library and back;
- stale request completing after a newer page;
- selected movies spanning pages.

### 7.4 Gate 1 stop

Present the chosen SQL shape, API schemas, page sizes, provider mapping, state transitions, test additions, performance thresholds, and exact change list.

Wait for Dante's approval before editing production code.

## 8. Gate 2: Library completeness and performance

Gate 2 changes only the existing Library keyword identity owner, its route contract, its frontend caller, and focused coverage.

Implementation responsibilities:

- replace the unpaged `limit` request with `page` and `page_size`;
- return accurate page metadata;
- implement the approved SQL design;
- retain SQL-only ownership;
- retain normalized prefix semantics;
- retain keyword identity rules;
- retain selected-keyword movie pagination;
- retire the obsolete `limit` caller/contract;
- keep Movies, People, Actor, Director, and Writer behavior unchanged.

Focused tests must prove:

- more than 100 matching keyword identities are reachable;
- the union of pages equals the authoritative complete result set;
- no duplicates or omissions across pages;
- exact-match-first and deterministic ordering;
- accurate `movie_count`, total, and page metadata;
- first/middle/last/out-of-range page behavior;
- broad-prefix performance within the pre-approved threshold;
- empty search performs no full enumeration;
- zero provider calls;
- selection by TMDB ID and normalized-name fallback;
- selected-keyword Library movie pages remain complete;
- stale browser responses cannot replace a newer query or page.

End Gate 2 green, record evidence, and stop for approval.

## 9. Gate 3: Discover backend completeness

Gate 3 changes only the existing TMDB keyword, movie discovery, and person-movie page contracts plus focused backend coverage.

Implementation responsibilities:

- remove the arbitrary 10-page cap from keyword identity search;
- remove the arbitrary 10-page cap from keyword movie discovery;
- remove the arbitrary 10-page cap from Actor, Director, and Writer local pagination;
- validate pages against provider or computed totals;
- preserve existing provider transformations and ordering;
- preserve `with_keywords`;
- preserve all current Discover criteria;
- preserve one provider request per requested remote page where the current page-size contract permits;
- preserve zero persistence of remote result pages.

Focused tests must prove:

- a page beyond 10 is reachable;
- first/middle/last/out-of-range pages;
- 20-result and existing 40-result page mapping;
- partial last page;
- accurate totals without Cinema Paradiso truncation;
- Actor, Director, Writer role filtering and deduplication;
- keyword identity and keyword movie authority;
- provider error and 429 propagation;
- no persistence call;
- no duplicate route or search implementation;
- existing movie feeds remain unchanged.

End Gate 3 green, record evidence, and stop for approval.

## 10. Gate 4: Discover desktop pagination

Gate 4 changes only the existing Discover state owner and shared pagination presentation plus focused frontend/Playwright coverage.

Implementation responsibilities:

- let `loadContextPage` accept an explicit requested page;
- replace results rather than append;
- render the shared Pagination component for person, writer, and keyword movie contexts;
- paginate TMDB keyword identities;
- remove the retired relationship Load more control;
- preserve relationship path labels and history;
- preserve page/total state in snapshots;
- preserve filters, sorting, ownership mode, selections, and card actions;
- retain stale-response sequencing and add browser request abortion where it safely reduces obsolete work;
- do not create a second pagination component;
- do not redesign unrelated controls.

Desktop tests must prove:

- keyword identities: Previous, Next, page status, first/last disablement;
- keyword movies: Previous, Next, page replacement, totals;
- Actor, Director, and Writer pages;
- page beyond 10;
- back navigation restores the prior page and results;
- changing query/filter/relationship resets to page 1;
- a stale page response cannot overwrite the active page;
- ownership badges remain correct;
- owned/unowned filters report current-page counts honestly;
- an ownership-filtered empty page still allows navigation;
- expanded card, trailer, source, list, watch, follow, selection, and ownership actions retain their contracts;
- normal Discover Pagination and Library Pagination remain unchanged;
- desktop-only rendering at the accepted viewport.

End Gate 4 green, record evidence, and stop for approval.

## 11. Gate 5: complete regression and acceptance

Start from the Gate 4 green commit.

Run:

1. Focused Library keyword pagination tests.
2. Focused Discover keyword/person pagination tests.
3. Catalogue/parity/provider-boundary tests.
4. Full Python suite.
5. Full Node suite.
6. Production build.
7. Full desktop Playwright suite using one worker where required for deterministic state.
8. Isolated desktop runtime verification against a schema-8 clone.
9. Performance suite against the same Gate 0 clone and thresholds.

Acceptance matrix:

| Area | Required evidence |
| --- | --- |
| Git scope | Only approved files and tests changed; unrelated work untouched. |
| Schema/data | Schema remains version 8; no migration, backfill, live-catalogue write, or new source of truth. |
| Library completeness | Every matching keyword identity is reachable across stable pages; selected owned movies remain complete. |
| Library authority | Zero provider calls; relational SQL only. |
| Discover completeness | Keyword identities and keyword/person movie pages remain reachable beyond the old caps, subject only to provider constraints. |
| Discover authority | TMDB remains remote owner; existing local ownership route remains the only attachment path. |
| Display | Shared Previous / Page X of Y / Next replaces relationship Load more without accumulated cards. |
| Counts | Remote totals, local totals, and current-page ownership wording are accurate and not conflated. |
| Existing behavior | Movies, Actor, Director, Writer, Library pages, normal Discover pages, cards, filters, selection, lists, collections, actions, details, and navigation remain at baseline. |
| Races/errors | Stale responses, request abortion, provider errors, empty pages, and changed totals are deterministic. |
| Performance | All approved cold, median, p95, statement-count, response-size, and rendered-card thresholds pass. |
| Automated tests | Targeted and complete Python, Node, build, and desktop Playwright suites pass. |
| Runtime | Isolated browser evidence proves first, middle, last, beyond-10, back-navigation, ownership, and error scenarios. |

Any unexplained difference fails Gate 5.

## 12. Review, documentation, and commit boundaries

- Each implementation gate must be separately reviewable.
- Show Dante the exact files and diff summary before every commit.
- Never stage by directory or use broad `git add`.
- Do not amend, squash, push, or open a pull request without explicit approval.
- Record commit hashes for each accepted gate.
- Update the authoritative search/pagination documentation and parity matrix only after behavior is proven.
- Remove obsolete Load more and unpaged `limit` code once no approved caller depends on it.
- If a compatibility path is unexpectedly required, stop and document its owner, dependency, retirement criteria, and tests before adding it.

## 13. Runtime and live-data boundary

This plan does not authorize a live-catalogue migration because none is required.

After Gate 5 passes:

- stop and ask Dante before restarting the normal application;
- do not write, repair, rescan, backfill, or audit the live catalogue as part of rollout;
- if Dante approves a normal runtime verification, use only ordinary read/search/navigation behavior;
- record the live backend commit and app version;
- verify Library keyword pages without provider calls;
- verify Discover pages with expected TMDB calls;
- verify normal Library, Discover, Home, Maintenance, lists, collections, playback, and downloads remain available;
- stop on any unexpected catalogue generation, data mutation, error, or performance difference.

## 14. Required execution record

Maintain one concise evidence document containing:

- commands;
- Git status and commits;
- exact changed files;
- isolated user-data/cache/database/movie-root paths;
- confirmation that live catalogue data was not used by tests or performance probes;
- route contracts before and after;
- page sizes, totals, and provider mappings;
- SQL query plans and statement counts;
- baseline and final cold/median/p95 timings;
- response sizes and rendered-card counts;
- provider-call counts;
- result-set digests or deterministic page unions;
- automated test totals;
- build result;
- Playwright scenarios;
- browser evidence;
- deviations, failures, and resolutions;
- final compatibility retirement status.

No gate may be marked complete from memory, a green status alone, or a small fixture that does not cross the old result limits.

## 15. Formal stop conditions

Stop immediately and report to Dante if:

- the worktree is not cleanly understood;
- the current baseline is not green;
- a test or benchmark resolves to live catalogue data;
- Library search calls TMDB;
- a page union loses or duplicates identities;
- ordering changes without approval;
- accurate Library totals require a new persistent source of truth;
- optimization appears to require a new index or schema version;
- Discover requires a new remote search route;
- the provider total cannot be mapped correctly;
- ownership wording would claim an uncomputed global count;
- a page request triggers bulk provider prefetch;
- an old response can replace a newer query/page;
- existing Movies, Actor, Director, Writer, filters, cards, actions, history, lists, or collections regress;
- performance misses the pre-approved threshold;
- any requested action expands beyond this plan.

At every formal gate, wait for Dante's explicit approval. Never continue automatically to the following gate.
