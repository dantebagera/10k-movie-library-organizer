# Search Completeness and Discover Pagination: Execution Evidence

Date: 2026-07-26

Status: Complete. Gate 5 passed after an explicitly approved ownership-query
remediation, and the separately approved normal-runtime verification passed.

Baseline:

- branch: `master`
- commit: `4f143dfbc7c7a635fe47bdf18f96faa42ef6a4dc`
- schema: 8
- SQLite runtime: 3.45.3
- live catalogue: not queried by Gate 1
- frozen clone:
  `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-search-gate0-a7620325732a429187b3b44d84a282b6\catalog-schema8-baseline.sqlite`
- clone SHA-256:
  `1FD08B7C2F62E36ACAB33CECCD1316967CD900E876F347A1A3B230D242312170`

The original plan began as an untracked planning input. It and this separate
evidence record were intentionally included only in the reviewed implementation
commit, rather than being silently bundled with unrelated work.

## 1. Scope decision

The approved complete scope includes:

- Library keyword identities;
- TMDB keyword identities;
- TMDB People identities;
- keyword movie relationships;
- Actor, Director, and Writer movie relationships;
- the normal 40-card TMDB Discover and Movies search page mapping where the
  same application-owned ten-page cap exists;
- relationship browsing reached from both the Explore and Pick tabs.

Collections and user lists remain finite local arrays and are not converted to
remote pagination.

This scope removes the application-owned cap without changing the source of
truth:

- Library remains relational SQLite only.
- TMDB remains the Discover result owner.
- The existing ownership-check route remains the only local ownership
  attachment owner.

## 2. Chosen Library SQL design

### 2.1 Rejected shapes

| Shape | Frozen-clone result | Decision |
| --- | --- | --- |
| Remove only the final `LIMIT` from the current full `effective` projection | The current broad `s` request exceeded 5,000 ms even with `LIMIT 50`; the unbounded planning probe exceeded 120 seconds. | Rejected. It does not bound database work. |
| Join keyword snapshots only when `provider_movie_snapshots.provider = canonical_movies.selected_provider` | Returned the current clone's ordinary rows, but deletes the existing selected-provider/fallback resolution rule when the selected snapshot is absent. Two-statement `s` median was 161.609 ms and p95 was 315.055 ms. | Rejected for correctness, not speed. |
| Persist a materialized keyword count or add another index | Could make reads cheaper but introduces a new schema object and synchronization owner. | Rejected by the approved architecture. |
| Rank the effective relational snapshot for each accepted file, then join only keyword relations | Exact current snapshot-selection order, no projection decoding, no schema change, two bounded SQL statements. | Chosen. |

### 2.2 Authoritative relational shape

The implementation will replace `_library_keywords_sql` with one shared
keyword-count CTE owner used by the count and page statements:

1. Read accepted `media_files`.
2. Join `canonical_movie_files` and `canonical_movies`.
3. Join the existing `provider_movie_snapshots` rows for that canonical movie.
4. Rank candidate snapshots per `path_key` in the same order as the current
   `COALESCE` subqueries:
   - selected provider and exact path;
   - selected provider on the canonical movie;
   - fallback provider and exact path;
   - fallback provider on the canonical movie.
5. Within the same rank, preserve current fallback provider priority, newest
   `updated_at`, then `snapshot_key`.
6. Keep rank 1 as the effective `(path_key, snapshot_key)` relation.
7. Range-scan `keywords.normalized_name` through
   `idx_keywords_normalized_name`.
8. Join `movie_keywords` through `idx_movie_keywords_keyword`.
9. Count distinct owned `path_key` values per keyword.

The count statement returns the number of matching owned keyword identities.
The page statement uses the same CTE and preserves this order:

1. exact normalized match first;
2. `movie_count DESC`;
3. `name COLLATE NOCASE`;
4. `keyword_key`.

The store performs at most two SQL statements per non-empty request. An empty
normalized query returns an empty page without executing the broad CTE.

### 2.3 Page normalization

- Default and desktop page size: 50.
- Safe API page-size range: 1 through 50.
- Page values below 1 become 1.
- A page above the last page becomes the last page, matching existing Library
  card pagination.
- Zero matches report page 1 of 1, total 0, and no items.
- Offset is calculated only after the accurate total is known.
- `count` is the current page length.
- `total_results` is the complete owned identity count.
- `total_pages = max(1, ceil(total_results / page_size))`.
- The response carries the current media catalogue generation.

No compatibility `limit` parameter remains after the repository caller and
tests move to `page` and `page_size`.

### 2.4 Correctness proof

The chosen query returned exactly the same ordered rows and `movie_count`
values as the current implementation for:

- `space`;
- ` SPACE  `, normalized to `space`;
- `war`;
- `love`;
- exact `based on novel or book`;
- no-match `zzzz-no-match`;
- `cliché`;
- the stored non-ASCII hyphen form in `close-quarters combat`.

On the broad `s` prefix:

- total rows: 924;
- pages at 50 rows: 19;
- union rows: 924;
- unique union rows: 924;
- repeat request order: identical;
- ordered-key SHA-256:
  `bef37e297bcb092005ca37e49f30122b58c0823bcf833096c8621ffa578181ce`.

An in-memory clone mutation inserted one synthetic `s` identity and
relationship, incremented media generation, then removed both:

- totals: 924, 925, 924;
- generations: 6048, 6049, 6050;
- an out-of-range page normalized to the new last page;
- no persistent clone or live-catalogue row was changed.

A forced SQLite progress-handler interruption produced `interrupted`;
`total_changes` did not increase and an `iterdump` digest remained unchanged.

### 2.5 Query plan

Both statements use:

- `idx_keywords_normalized_name` for the prefix range;
- `idx_movie_keywords_keyword` for keyword relationships;
- the canonical primary-key indexes for files and movies;
- `idx_provider_snapshots_movie` for snapshot candidates.

Temporary B-trees remain bounded to:

- effective snapshot ranking;
- keyword grouping;
- distinct owned-path counts;
- final page ordering.

The query does not read `provider_movie_snapshots.source_json`, decode a
canonical card projection, call TMDB, or introduce a persistent count source.

### 2.6 Frozen-clone performance

Each request below includes the accurate count statement and bounded page
statement. Cold samples use a fresh read-only SQLite connection. Warm samples
reuse one connection. OS file cache was not forcibly purged.

| Query/page | Rows | Total | Cold median | Cold p95 | Warm median | Warm p95 | Statements | JSON bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `space`, 1 | 30 | 30 | 125.011 ms | 128.394 ms | 123.487 ms | 125.316 ms | 2 | 5,330 |
| `war`, 1 | 31 | 31 | 126.431 ms | 128.882 ms | 123.683 ms | 127.212 ms | 2 | 5,368 |
| `s`, 1 | 50 | 924 | 143.664 ms | 144.834 ms | 142.275 ms | 146.996 ms | 2 | 8,671 |
| `s`, 10 | 50 | 924 | 143.318 ms | 159.128 ms | 141.827 ms | 145.458 ms | 2 | 8,725 |
| `s`, 19 | 24 | 924 | 142.326 ms | 144.349 ms | 139.448 ms | 141.540 ms | 2 | 4,315 |
| `s`, requested 999 | 24 | 924 | 140.711 ms | 142.266 ms | 138.517 ms | 141.274 ms | 2 | 4,315 |
| no match, 1 | 0 | 0 | 1.134 ms | 1.255 ms | 0.016 ms | 0.023 ms | 2 | 70 |
| empty normalized query | 0 | 0 | not applicable | not applicable | not applicable | not applicable | 0 | bounded empty contract |

The design clears every frozen Gate 0 Library threshold without changing a
threshold after measurement.

## 3. API contracts

### 3.1 Library keyword identities

Request:

```text
GET /api/library?view=keywords&q=<normalized-prefix>&page=<positive-int>&page_size=50
```

Response:

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

The existing route, repository, and store remain the only owners.

### 3.2 Native TMDB identity pages

Applies to keyword and People search.

```json
{
  "results": [],
  "page": 1,
  "page_size": 20,
  "total_pages": 1,
  "total_results": 0,
  "provider_total_pages": 1,
  "provider_page_limit": 500
}
```

Rules:

- Only the requested provider page is fetched.
- Valid request pages are 1 through TMDB's documented maximum of 500.
- Values below 1 normalize to 1.
- Values above 500 return HTTP 400 without a provider request; they are not
  silently changed to another page.
- `provider_total_pages` preserves the raw provider fact.
- `total_pages` is the reachable page count:
  `min(provider_total_pages, provider_page_limit)`.
- `total_results` remains the provider total even when the provider page limit
  makes only the first 500 pages reachable.
- Keyword identities remain deduplicated by non-empty TMDB ID within the
  returned page. A short page is not backfilled from later pages.
- People split-query fallback remains page-1-only and reports its finite
  fallback result as page 1 of 1.

### 3.3 TMDB movie pages

The normal Discover and Movies search result schema gains the same explicit
`page_size`, `provider_total_pages`, and `provider_page_limit` facts while
preserving all current movie fields, criteria fields, keyword context, and
totals.

For a native 20-result relationship page:

```text
Cinema Paradiso page p -> TMDB page p
```

For an existing 40-result normal Discover or Movies search page:

```text
Cinema Paradiso page p -> TMDB pages (2p - 1) and (2p)
```

Rules:

- Relationship page size remains 20.
- Normal Discover and Movies search page size remains 40.
- TMDB's maximum native page is 500.
- A 20-result route can expose at most 500 reachable pages.
- A 40-result route can expose at most 250 Cinema Paradiso pages.
- For 40-result pages, fetch the first mapped provider page, read its total,
  and fetch the second only when it is within both the provider total and page
  500.
- A final odd native provider page therefore makes one provider request and
  returns a partial 40-result page.
- Duplicate or missing provider rows are preserved in provider order. Cinema
  Paradiso does not pull later pages forward to fill a short page because that
  would change provider page boundaries and call counts.
- If either required provider request fails, the whole Cinema Paradiso page
  fails. Partial page success is not displayed.
- `total_results` remains the raw provider total. Current-page client criteria
  summaries and current-page ownership summaries remain explicitly local to
  the visible page.

### 3.4 Person movie-credit pages

The existing `/api/tmdb/person_movies` owner continues to:

1. fetch one complete TMDB credit document;
2. choose Actor, Director, or approved Writer credits;
3. deduplicate by TMDB movie ID;
4. apply existing filters;
5. apply existing sorting;
6. compute the filtered total;
7. return one 20-result page.

The application-owned ten-page clamp is removed. Page values below 1 normalize
to 1. Values above the computed final page normalize to the final page because
the complete finite result set is already local to that request.

### 3.5 Changed totals and out-of-range remote pages

Normal UI navigation cannot request beyond the last total it currently knows.
Provider totals can nevertheless shrink between requests.

The state owner will handle that race as follows:

1. accept the new provider total as authoritative;
2. if the requested page is now beyond the reachable last page, do not attach
   the empty/mismatched page to the last-page number;
3. issue one request for the new last page;
4. guard both responses with the existing request sequence and the new abort
   owner;
5. render only the result whose request identity is current.

No route prefetches page 1 merely to validate a requested page.

### 3.6 Provider errors

Zero-regression status behavior is retained:

- TMDB HTTP 401 remains Cinema Paradiso HTTP 401 with the invalid-key message.
- Other TMDB HTTP responses, including 429, remain Cinema Paradiso HTTP 502
  with the provider HTTP code in the error body.
- Timeout, malformed JSON, and unexpected payload errors remain visible errors
  and do not overwrite the previous current page.
- The UI does not silently retry 429.
- An intentional browser request abort is not shown as an error.

Official TMDB documentation currently defines pages as starting at 1 with a
maximum of 500, and documents 429 as its request-limit response:

- https://developer.themoviedb.org/docs/errors
- https://developer.themoviedb.org/reference/discover-movie
- https://developer.themoviedb.org/reference/search-keyword
- https://developer.themoviedb.org/reference/search-person

## 4. Desktop state contract

### 4.1 State ownership

`DiscoverWorkspace` remains the only Discover state owner.

Separate identity-page state is required so the normal movie pager cannot
remain visible under keyword or People identities:

- keyword identity results, page, total pages, total results;
- People identity results, page, total pages, total results;
- movie results, page, total pages, total results;
- relationship context and history.

`Pagination` remains the one presentation owner. It will accept an accessible
label prop. Library and each Discover surface pass an explicit label.

### 4.2 Transitions

| Event | Required transition |
| --- | --- |
| New Library keyword query | Increment request identity, reset keyword page to 1, clear expansion/old suggestions, request only page 1. |
| Library keyword Previous/Next | Preserve query, request the explicit adjacent page, replace identity cards. |
| New TMDB keyword or People query | Abort obsolete identity request, increment request identity, reset that identity page to 1, clear the other identity mode and relationship context. |
| Keyword or People identity Previous/Next | Preserve query and search kind, request one explicit page, replace identity cards. |
| Open keyword/person relationship | Push the complete identity-search snapshot, reset movie page to 1, clear expansion, request the relationship page. |
| Relationship Previous/Next | Preserve relationship, criteria, sort, path label, ownership mode, and selection set; replace movie cards; check ownership only for the new page. |
| Filter or sort change | Keep the relationship identity, reset movie page to 1, clear expansion, request page 1. |
| Ownership filter change | Do not fetch another TMDB page and do not reset the page. Re-filter only the loaded page and keep navigation enabled even when zero cards remain visible. |
| Enter expanded details | Keep page and filters. |
| Change page with expanded details open | Clear expansion before showing the replacement page. |
| Discover Back | Restore the saved query, search kind, identity/movie results, page, totals, criteria, relationship context, and path; clear expansion; refresh ownership only for restored movie results. |
| Navigate to Library and return | Preserve the mounted Discover state under the existing application navigation contract. |
| Older request completes | Ignore it by request sequence even if transport abort did not complete in time. |
| Request abort | Clear loading only for the request that still owns loading state; show no error. |
| Provider total shrinks | Redirect once to the new last page under a new request identity. |
| Selection across pages | Preserve the existing global identity-key set. The visible selected count remains based on the current page; returning to a prior page restores its checked cards. |

Explore and Pick relationship contexts both replace the Load more control with
the shared Previous / Page X of Y / Next control. Pick keeps its own existing
context/history owner; it does not borrow Explore state.

## 5. Frozen performance thresholds

These are the Gate 0 thresholds. Gate 1 does not loosen them.

| Area | Threshold |
| --- | --- |
| Library exact/ordinary prefix | cold <= 750 ms; warm median <= 450 ms; p95 <= 650 ms |
| Library broad first/late/count | cold <= 1,500 ms; warm median <= 750 ms; p95 <= 1,200 ms |
| Library identity SQL | at most 2 statements; no N+1 |
| Library identity response | at most 50 cards and 16 KiB |
| Selected Library keyword movie page | cold <= 800 ms; median <= 350 ms; p95 <= 450 ms; at most 16 statements |
| Keyword/movie provider transform | p95 <= 50 ms, excluding network |
| Person provider transform | p95 <= 100 ms, excluding network |
| Ownership attachment for 20 remote movies | cold <= 750 ms; median <= 400 ms; p95 <= 500 ms; at most 35 statements |
| Remote response sizes | identities <= 16 KiB; movie <= 64 KiB; person/ownership <= 128 KiB |
| Provider calls | 1 per native 20-result page; at most 2 per existing 40-result page; no speculative prefetch |
| Visible cards | Library identities <= 50; Library movies 40; TMDB identities <= 20; relationships <= 20; normal Discover <= 40 |
| Authority/race | Library makes zero TMDB calls; remote pages make zero persistence calls; stale responses win zero times |

## 6. Focused regression scaffolding

No executable test was changed in Gate 1. Copying the candidate SQL into a test
would create a second query owner, and committing skipped expected-behavior
tests would create a misleading green suite. Instead, the exact runnable test
additions are frozen here and will be added with the authoritative owner in the
corresponding implementation gate.

### Gate 2

`tests/test_catalog_store.py`

- `test_library_keyword_pages_reach_every_identity_beyond_one_hundred`
- `test_library_keyword_page_union_is_complete_unique_and_deterministic`
- `test_library_keyword_pages_preserve_exact_normalized_and_non_latin_order`
- `test_library_keyword_page_metadata_clamps_out_of_range`
- `test_library_keyword_page_updates_after_generation_change`
- `test_library_keyword_query_interruption_does_not_mutate_catalogue`
- `test_library_keyword_empty_query_executes_no_broad_search`
- `test_library_keyword_page_stays_within_statement_and_time_thresholds`

`tests/test_library_action_ux.py`

- `test_library_keyword_workspace_owns_page_and_total_state`
- `test_library_keyword_request_uses_page_contract_not_limit`

`tests/e2e/app-smoke.spec.js`

- Library keyword identity page replacement and page union;
- a stale page response cannot replace a newer page;
- selected keyword movies retain the existing 40-card Library pager.

### Gate 3

`tests/test_tmdb_details_transform.py`

- keyword identity page 11 and provider page 500;
- People identity page 11 and page-1 split fallback;
- keyword relationship page 11;
- normal 40-result provider page mapping beyond Cinema Paradiso page 10;
- final odd provider page makes one call;
- provider maximum, partial, empty, and changed-total responses;
- Actor, Director, and Writer pages beyond 10;
- role filtering, deduplication, sorting, and out-of-range normalization;
- 401, 429, timeout, and malformed payload behavior;
- zero persistence calls and bounded provider call counts.

### Gate 4

`tests/test_unified_movie_card_ui.py`

- one shared `Pagination` owner;
- explicit accessible labels;
- no relationship `Load more`;
- separate keyword, People, movie, and Pick page state;
- snapshot fields and stale-request guards.

`tests/test_library_action_ux.py`

- normal Library pagination remains unchanged;
- ownership-filter language remains current-page-specific.

`tests/e2e/app-smoke.spec.js`

- keyword and People identity Previous/Next;
- keyword, Actor, Director, and Writer page replacement;
- Explore and Pick relationship pagination;
- page beyond 10;
- first/last disabled states;
- filter reset, stale response, history restoration, and changed totals;
- owned/unowned empty current page still allows navigation;
- selection, expanded details, trailer, source, list, watch, follow, and
  ownership actions remain intact.

## 7. Exact implementation change list

### Gate 2

- `services/catalog_store.py`
- `services/catalog_repository.py`
- `app.py`
- `src/features/library/LibraryWorkspace.jsx`
- `tests/test_catalog_store.py`
- `tests/test_library_action_ux.py`
- `tests/e2e/app-smoke.spec.js`

### Gate 3

- `app.py`
- `tests/test_tmdb_details_transform.py`

### Gate 4

- `src/features/discover/DiscoverWorkspace.jsx`
- `src/components/Pagination.jsx`
- `tests/test_unified_movie_card_ui.py`
- `tests/test_library_action_ux.py`
- `tests/e2e/app-smoke.spec.js`

No schema, migration, backfill, CSS, new route, compatibility layer, persistent
cache, or second search owner is planned. An unexpected need for any of those
stops the relevant gate for separate approval.

## 8. Gate 1 verification

After writing this design record:

- focused Python: 136 tests passed in 40.821 seconds;
- focused Node: 29 tests passed, 0 failed, 0 skipped;
- production build: not rerun because Gate 1 changed Markdown only; the Gate 0
  production build remains green;
- Playwright: not rerun because Gate 1 changed no runtime or test code; the
  Gate 0 focused and complete desktop suites remain green;
- Git diff check: clean;
- worktree: only this evidence file and the original plan are untracked;
- repository-local test data, database clones, caches, and movie roots: none
  created.

## 9. Gate 1 decision

The chosen Library query meets the frozen correctness and performance
requirements without a schema change. The API, provider mapping, page sizes,
state transitions, error behavior, test additions, and exact implementation
files are now fixed for review.

Gate 2 did not begin until Dante approved it.

## 10. Gate 2 implementation

Gate 2 changed only the existing Library keyword identity owners and focused
coverage:

- `services/catalog_store.py`
- `services/catalog_repository.py`
- `app.py`
- `src/features/library/LibraryWorkspace.jsx`
- `tests/test_catalog_store.py`
- `tests/test_library_action_ux.py`
- `tests/test_sql_migration_parity.py`
- `tests/test_unified_movie_card_ui.py`
- `tests/e2e/app-smoke.spec.js`

The existing untracked plan was not edited or staged.

### 10.1 Store and route

- Replaced the old capped `limit` method with `page` and `page_size`.
- Enforced a maximum page size of 50 without limiting `total_results`.
- Added the ranked effective-snapshot query approved in Gate 1.
- Count and page reads share one read transaction, so metadata and rows come
  from the same SQLite snapshot.
- Embedded media generation in the count query, keeping the non-empty request
  at two relational statements including generation.
- Guaranteed connection closure even if an intentional SQLite interruption
  also interrupts rollback.
- Kept an empty normalized query to one generation lookup and zero broad
  keyword work.
- Returned `items`, `page`, `page_size`, `total_pages`, `total_results`,
  current-page `count`, `source`, and `catalog_generation`.
- Removed all in-repository Library keyword `limit` callers.

### 10.2 Desktop Library

- Added one authoritative keyword result object containing items and page
  metadata.
- Requests now send `page` and `page_size=50`.
- New queries reset to page 1.
- Previous and Next replace the visible identity cards.
- The existing request-sequence guard prevents an older query or page response
  from winning.
- The existing shared `Pagination` component renders the Library keyword
  controls; no second pager or CSS owner was added.
- Selecting a keyword still switches to the existing 40-card Library movie
  path and preserves exact TMDB ID/name fallback behavior.

## 11. Gate 2 focused correctness evidence

The new fixture crosses both retired ceilings with 125 matching identities.

- page lengths: 50, 50, 25;
- total: 125;
- total pages: 3;
- page union: 125;
- unique identities: 125;
- exact normalized identity remains first;
- repeat page response is identical;
- requested page 999 normalizes to page 3;
- requested page size 500 normalizes to 50.

Additional automated coverage proves:

- normalized, non-Latin, exact, no-match, and blank searches;
- deterministic ordering and counts;
- catalogue generation updates without a persistent count source;
- selected-provider fallback snapshot behavior;
- forced query interruption without catalogue mutation or a leaked handle;
- at most two relational keyword statements;
- zero `source_json` decoding;
- zero TMDB calls;
- route metadata and retirement of the `limit` argument;
- desktop page replacement, first/last controls, request parameters, stale
  response rejection, and selected-keyword movie behavior.

The frozen broad `s` union remains:

- total: 924;
- union: 924;
- unique: 924;
- ordered-key SHA-256:
  `bef37e297bcb092005ca37e49f30122b58c0823bcf833096c8621ffa578181ce`.

## 12. Gate 2 performance evidence

Measurements used only the isolated schema-8 `performance-working.sqlite`
copy. Each sample called the production `CatalogStore.library_keywords`
implementation.

| Query/page | Rows | Total | Median | p95 | JSON bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| `space`, 1 | 30 | 30 | 122.783 ms | 126.663 ms | 5,356 |
| `war`, 1 | 31 | 31 | 258.108 ms | 287.982 ms | 5,394 |
| `s`, 1 | 50 | 924 | 293.781 ms | 322.330 ms | 8,697 |
| `s`, 10 | 50 | 924 | 293.502 ms | 308.576 ms | 8,751 |
| `s`, 19 | 24 | 924 | 286.593 ms | 306.518 ms | 4,341 |
| `s`, requested 999 | 24 | 924 | 288.516 ms | 315.687 ms | 4,341 |
| no match | 0 | 0 | 4.480 ms | 6.470 ms | 96 |
| blank query | 0 | 0 | 5.514 ms | 9.281 ms | 96 |

All values remain inside the frozen Gate 0 thresholds. The performance copy
finished with `quick_check=ok` and schema version 8.

## 13. Gate 2 verification

- focused Python: 126 tests passed;
- focused Library Playwright: 3 tests passed;
- full Python: 760 tests passed in 140.169 seconds;
- full Node: 63 tests passed, 0 failed, 0 skipped;
- production Vite build: passed in 2.14 seconds;
- full desktop Playwright: 32 tests passed in 28.1 seconds at 1600 by 1000
  with one worker;
- Git diff check: clean;
- schema migration/backfill: none;
- live catalogue/provider calls: none;
- normal port-5000 process: untouched.

Two pre-existing non-failing Python `ResourceWarning` messages remained: one
temporary file and one `dist/index.html` handle.

Observed failures and resolutions:

- The sandboxed Vite build could not read the workspace configuration; the
  approved unsandboxed build passed.
- One initial generation-change assertion assumed a direct `CatalogStore`
  fixture already contained repository-owned media generation. The fixture was
  corrected to create that metadata row explicitly.
- A forced interruption could prevent cleanup rollback and skip connection
  close. Nested cleanup now guarantees close and the regression passes.
- One three-test Playwright run lost the Chromium page process after two
  passing tests. The failed test passed alone, the three-test group passed on
  rerun, and the complete 32-test desktop suite passed.

Seven isolated Gate 2 temporary roots, including the retained failed-browser
trace, were deleted after their paths were verified under the operating-system
temporary directory. They were disposable test artifacts and are not
recoverable. The frozen Gate 0 evidence root remains available.

## 14. Gate 2 stop

Library keyword identities are now complete through bounded pages, remain
SQL-only, and meet the frozen performance limits. Discover production behavior
has not changed.

Gate 3 must not begin until Dante approves it.

## 15. Gate 3 implementation

Gate 3 changed only the approved existing TMDB backend owner and focused
backend coverage:

- `app.py`
- `tests/test_tmdb_details_transform.py`

No frontend, schema, migration, backfill, catalogue, provider cache, or route
owner was added or changed.

### 15.1 Shared TMDB page contract

- Added one shared TMDB page contract for the existing movie Discover and
  Movies search routes.
- Preserved page sizes 20 and 40.
- A 20-result Cinema Paradiso page maps to one TMDB page.
- A 40-result Cinema Paradiso page maps to two consecutive TMDB pages.
- The second provider request is skipped on an odd partial last page.
- TMDB's provider page limit is 500, so the maximum reachable Cinema Paradiso
  page is 500 at page size 20 and 250 at page size 40.
- Requests beyond those limits return HTTP 400 before any provider request.
- Responses now distinguish raw provider totals from reachable totals with
  `provider_total_pages`, `provider_page_limit`, `page_size`, and
  `total_pages`.
- A provider total above 500 remains visible in `provider_total_pages`; only
  reachable page navigation is bounded by the provider's own limit.

### 15.2 Existing route owners

- `/api/tmdb/keywords/search` now reaches provider pages beyond 10 and retains
  its TMDB identity deduplication.
- `/api/tmdb/people/search` now reaches provider pages beyond 10 and retains
  its exact unspaced-name fallback on page 1.
- `/api/tmdb/discover` now reaches keyword and ordinary feed pages beyond 10,
  preserves `with_keywords`, criteria, result transformation, ordering, and
  keyword context.
- `/api/tmdb/search` now reaches movie-search pages beyond 10 and preserves the
  existing criteria filtering and sorting semantics.
- `/api/tmdb/person_movies` no longer truncates Actor, Director, or Writer
  filmographies at 200 results. It still fetches one credit document, filters,
  deduplicates, sorts, and only then slices a 20-result local page.
- A person-filmography request above its computed last page normalizes to the
  computed last page.
- HTTP 401 remains direct; other provider HTTP errors, including 429, remain
  Cinema Paradiso HTTP 502 responses. Malformed provider totals remain visible
  as HTTP 500 rather than being hidden.
- Remote result pages still make no persistence call.

## 16. Gate 3 focused correctness evidence

The focused backend tests prove:

- native page 11 and page 13 requests are sent unchanged to TMDB;
- a 40-result page 11 maps to provider pages 21 and 22;
- a 40-result last page 12 maps only to provider page 23 when provider totals
  are 23 pages;
- provider totals of 23 map to 12 Cinema Paradiso pages at page size 40;
- provider totals of 700 remain reported as 700 while reachable totals are
  500 at page size 20 and 250 at page size 40;
- native page 500 and combined page 250 remain valid;
- native page 501 and combined page 251 fail before a provider call;
- a native request within the provider limit but beyond the query's current
  total preserves the requested page and returns the provider's empty result;
- keyword identity, People identity, keyword movie authority, `with_keywords`,
  criteria, transformations, roles, and deduplication remain intact;
- a 221-film Actor result reaches page 11 and a one-result page 12;
- Writer job filtering and duplicate removal and Director filtering remain
  covered;
- 429, other provider errors, and malformed totals retain their prior visible
  error contracts;
- persistence owners are not called;
- each of the five improved routes has exactly one registered owner;
- existing adult-setting, criteria, feed, and unreleased-movie behavior remains
  covered.

Focused result:

- 38 Python tests passed in 0.197 seconds.

## 17. Gate 3 complete verification

- full Python: 768 tests passed in 105.593 seconds;
- full Node: 63 tests passed, 0 failed, 0 skipped;
- production Vite build: passed in 2.05 seconds;
- full desktop Playwright: 32 tests passed in 26.3 seconds at 1600 by 1000
  with one worker;
- Git diff check: clean;
- frozen schema-8 clone SHA-256 remained
  `1FD08B7C2F62E36ACAB33CECCD1316967CD900E876F347A1A3B230D242312170`;
- frozen clone `catalog_meta.schema_version`: 8;
- frozen clone `quick_check`: `ok`;
- live catalogue/provider calls: none;
- normal port-5000 listener: untouched at PID 37456.

The sandboxed Vite build again could not read the repository configuration;
the approved unsandboxed build passed. The same two pre-existing non-failing
Python `ResourceWarning` messages remained: one temporary file and one
`dist/index.html` handle.

Four isolated Gate 3 Python test roots were verified as direct children of the
operating-system temporary directory and deleted. They were disposable and are
not recoverable. The Playwright harness removed its own Gate 3 root. The frozen
Gate 0 evidence root remains available.

## 18. Gate 3 stop

The existing TMDB backend routes now expose every provider-reachable keyword,
People, movie-search, Discover, and relationship page without an
application-owned ten-page truncation. Requests remain bounded by page size and
TMDB's documented provider page limit, and relationship filmographies remain
bounded to one locally sliced page.

Gate 4 has not started and must not begin until Dante approves it.

## 19. Gate 4 implementation

Gate 4 changed only the existing Discover state owner, the shared Pagination
component, and focused regression coverage:

- `src/features/discover/DiscoverWorkspace.jsx`
  - keeps separate page, total-page, and total-result state for People and
    keyword identity searches;
  - makes every identity and relationship navigation request an explicit page;
  - replaces the current page instead of appending relationship results;
  - uses the shared Pagination component for People identities, keyword
    identities, keyword movies, Actor movies, Director movies, Writer movies,
    and Pick relationship movies;
  - removes both relationship `Load more` controls;
  - aborts superseded Discover and Pick requests and rejects responses from an
    older request sequence;
  - redirects once to the provider's new last page if a previously valid page
    becomes out of range;
  - preserves and restores identity pages, totals, relationship pages,
    criteria, ownership filters, checked selections, context labels, and
    navigation history;
  - keeps a relationship pager available when a local ownership filter makes
    the current provider page empty;
- `src/components/Pagination.jsx`
  - accepts a caller-supplied accessible label while preserving the Library
    label as the default;
- `tests/test_unified_movie_card_ui.py` and
  `tests/test_library_action_ux.py`
  - pin the single shared Pagination owner, replacement-page behavior,
    relationship `Load more` removal, abort handling, snapshot state, and
    changed-total redirect;
- `tests/e2e/app-smoke.spec.js`
  - extends the existing Discover keyword journey and adds focused stale,
    shrinking-total, relationship, page-beyond-ten, ownership-filter, and Pick
    pagination journeys.

No backend route, catalogue owner, schema, provider ownership route, card
owner, or CSS owner was added or replaced. Normal Discover continues to use
its existing paged owner. Library continues to use its existing SQL-only owner.

## 20. Gate 4 focused correctness evidence

The focused Python source-contract suite passed 82 tests in 0.032 seconds.

Four focused desktop Playwright regressions passed in two isolated runs:

- keyword identity Previous/Next navigation, first/last disabled states,
  `Page X of Y`, keyword movie replacement paging, and Back restoration;
- superseded relationship requests, filter reset to page 1, stale-response
  rejection, provider-total shrink, and last-page redirect;
- People identities plus Actor, Director, and Writer movie relationships,
  including replacement navigation beyond page 10, previous navigation,
  checked-selection restoration, role preservation, Back restoration, and an
  ownership-filtered empty page that remains navigable;
- Pick relationship Previous/Next replacement paging and Back restoration.

The first combined browser run exposed a test interaction issue: Playwright's
plain checkbox click targeted the input hidden below the existing styled
checkbox span. The focused test now checks that existing input directly. No
production checkbox or card behavior changed, and the corrected regression
passed both alone and in the complete suite.

The in-app browser rendered the production Discover build at 1600 by 1000 with
the correct page shell, heading, tabs, search controls, filters, and no
workspace crash. The isolated server had no TMDB key, so the page displayed its
existing explicit configuration error instead of making a provider request.

## 21. Gate 4 complete verification

- full Python: 771 tests passed in 115.991 seconds;
- full Node: 63 tests passed, 0 failed, 0 skipped;
- production Vite build: passed in 2.04 seconds;
- full desktop Playwright: 35 tests passed in 35.5 seconds at 1600 by 1000
  with one worker;
- Git diff check: clean;
- branch and commit remain `master` at
  `4f143dfbc7c7a635fe47bdf18f96faa42ef6a4dc`;
- frozen schema-8 clone SHA-256 remained
  `1FD08B7C2F62E36ACAB33CECCD1316967CD900E876F347A1A3B230D242312170`;
- frozen clone `catalog_meta.schema_version`: 8;
- frozen clone `quick_check`: `ok`;
- live catalogue/provider calls: none;
- normal port-5000 listener: untouched at PID 37456.

The sandboxed Vite build could not read the repository configuration; the
approved unsandboxed build passed. The same two pre-existing non-failing Python
`ResourceWarning` messages remained: one temporary file and one
`dist/index.html` handle.

The isolated full-Python root, isolated rendered-browser root, and one retained
failed Playwright diagnostic root were verified as direct children of the
operating-system temporary directory and deleted. They were disposable and are
not recoverable. Successful Playwright roots were removed by the harness. The
frozen Gate 0 evidence root remains available.

## 22. Gate 4 stop

Every provider-available Discover keyword and People identity page is now
reachable. Keyword, Actor, Director, Writer, and Pick relationship results use
standard Previous / Page X of Y / Next replacement pagination, including pages
beyond ten where the provider supplies them. Existing ownership attachment,
filters, selections, card actions, snapshots, and Back navigation remain
covered.

Gate 5 has not started and must not begin until Dante approves it.

## 23. Gate 5 precondition and focused acceptance

Dante approved Gate 5, but the plan's instruction to start from a Gate 4 green
commit could not be met: no gate commit had been authorized. The exact
reviewed green working tree was used instead. Branch and HEAD remained
`master` at `4f143dfbc7c7a635fe47bdf18f96faa42ef6a4dc`. Nothing was staged,
committed, amended, pushed, or restarted.

Focused isolated acceptance passed:

- 163 Python tests covering the catalogue store, SQL migration parity,
  catalogue parity, Library ownership, TMDB pagination and transforms,
  shared state, and UI source contracts;
- 10 desktop Playwright tests with one worker covering Library keyword
  identities and movies; Discover keyword and People identities; keyword,
  Actor, Director, Writer, and Pick relationships; stale responses; provider
  errors; page replacement; pages beyond ten; ownership; and Back navigation.

## 24. Gate 5 frozen-clone performance

The performance run used only disposable copies of the frozen Gate 0 schema-8
clone:

```text
C:\Users\dante\AppData\Local\Temp\cp-gate5-performance-8b0c092759264490b2d6ad36c6edee3d\performance-working.sqlite
C:\Users\dante\AppData\Local\Temp\cp-gate5-performance-8b0c092759264490b2d6ad36c6edee3d\user-data\.catalog-test.sqlite
```

The production `CatalogStore.library_keywords` owner passed every frozen
identity threshold:

| Query/page | Rows | Total | Cold | Median | p95 | Statements | JSON bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `space`, 1 | 30 | 30 | 116.632 ms | 117.589 ms | 119.213 ms | 2 | 5,356 |
| `war`, 1 | 31 | 31 | 264.235 ms | 119.937 ms | 261.058 ms | 2 | 5,394 |
| `s`, 1 | 50 | 924 | 287.876 ms | 294.030 ms | 307.187 ms | 2 | 8,697 |
| `s`, 10 | 50 | 924 | 283.328 ms | 287.817 ms | 297.599 ms | 2 | 8,751 |
| `s`, 19 | 24 | 924 | 136.014 ms | 142.389 ms | 284.923 ms | 2 | 4,341 |
| `s`, requested 999 | 24 | 924 | 136.570 ms | 136.316 ms | 140.044 ms | 2 | 4,341 |
| no match | 0 | 0 | 2.123 ms | 2.198 ms | 2.307 ms | 2 | 96 |
| blank query | 0 | 0 | 1.860 ms | 1.858 ms | 2.072 ms | 0 | 96 |

The broad `s` page union remained 924 rows and 924 unique identities with the
frozen ordered-key SHA-256
`bef37e297bcb092005ca37e49f30122b58c0823bcf833096c8621ffa578181ce`.

The selected `space` Library movie page passed:

- cold: 561.755 ms;
- median: 235.409 ms;
- p95: 251.576 ms;
- returned and total: 32;
- read statements: 16;
- deterministic repeat page: yes.

All isolated provider transformations passed:

| Route shape | Median | p95 | Results | Provider calls/request | JSON bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| keyword identities | 0.310 ms | 0.393 ms | 20 | 1 | 898 |
| People identities | 0.404 ms | 0.670 ms | 20 | 1 | 4,139 |
| keyword movies | 0.506 ms | 0.685 ms | 20 | 1 | 6,830 |
| 221-credit person filmography, page 11 | 3.821 ms | 7.764 ms | 20 | 1 | 13,428 |

The provider routes made zero persistence calls. The Library routes made zero
provider calls. Page sizes and serialized responses remained inside their
frozen limits.

## 25. Gate 5 performance stop

The isolated 20-movie ownership attachment missed two frozen limits:

- first cold request: 1,168.882 ms against `<= 750 ms`;
- statements: 37 against `<= 35`.

The rest of that request passed:

- warm median: 314.212 ms against `<= 400 ms`;
- warm p95: 332.584 ms against `<= 500 ms`;
- 20 queries and 20 authoritative matches;
- 55,176 response bytes against `<= 128 KiB`;
- zero provider calls;
- HTTP 200.

A diagnostic rerun reduced the cold time to 619.499 ms, showing that the first
cold timing is sensitive to one-time cache and SQLite page loading. It still
executed the same deterministic 37 reads. Their exact breakdown was:

- 11 source-document and relational snapshot reads;
- one bounded ownership-candidate query;
- 20 per-path identity-key reads;
- one media-generation read;
- two identity-audit reads;
- one maintenance-upgrade candidate read;
- one final media-generation read.

The 20 per-path identity reads are the existing
`CatalogStore._decode_media_rows(..., include_identity_keys=True)` N+1 path.
No Gate 2, 3, or 4 diff changes the ownership route, `_catalog_owned_entries`,
`_catalog_owned_movie`, or this decoder. This is therefore not a pagination
regression, but it still fails the numerical threshold frozen before
implementation. Silently excluding the two generation reads or loosening the
threshold after implementation would violate the plan.

Per the formal stop condition, Gate 5 stopped immediately. The complete Python,
Node, build, full Playwright, and schema-8 browser-runtime repetitions were not
run as Gate 5 evidence. Their Gate 4 results remain recorded above but are not
being relabeled as Gate 5 acceptance.

The frozen clone remained byte-identical at
`1FD08B7C2F62E36ACAB33CECCD1316967CD900E876F347A1A3B230D242312170`.
The normal port-5000 listener remained untouched at PID 37456. The focused and
performance roots were verified as direct children of the operating-system
temporary directory and deleted; they were disposable and are not
recoverable. The successful Playwright root was removed by its harness. The
frozen Gate 0 evidence root remains available.

Gate 5 is not complete. Meeting the frozen statement ceiling requires a newly
approved remediation in the existing catalogue ownership owner, most directly
replacing the per-path identity-key N+1 reads with one bounded batch read and
adding focused parity/performance coverage. No such implementation has begun.

## 26. Approved Gate 5 remediation

Dante explicitly approved the narrow ownership-query remediation after the
Gate 5 stop.

The implementation remediation changed only the existing catalogue owner and
its focused test:

- `services/catalog_store.py`
  - `_decode_media_rows(..., include_identity_keys=True)` now gathers the
    returned path keys and reads their identity keys in one bounded
    `json_each` batch query;
  - identity keys are grouped back onto their original candidates;
  - explicit `path_key, identity_key` ordering preserves the prior
    per-candidate key order;
- `tests/test_catalog_store.py`
  - a 20-candidate regression pins two total ownership-candidate reads,
    candidate order, exact identity-key order, decoded provider JSON, and the
    absence of an N+1 query path.

No route, schema, index, migration, backfill, provider boundary, ownership
matching rule, card contract, or persistent source of truth changed.

After the behavior was proven, the plan-required authoritative ownership map
and SQL parity matrix were updated to record the accepted pagination,
completeness, performance, and rollout boundaries. Those documentation changes
do not add another runtime owner.

The first two focused runs exposed only incorrect new fixture assumptions: the
synthetic paging rows have two identity aliases because they intentionally do
not store IMDb or path aliases. The regression was corrected to assert their
exact two-key order. The final focused ownership group passed 6 tests, and the
complete focused acceptance group passed 164 tests in 43.868 seconds.

## 27. Final Gate 5 performance acceptance

The repaired 20-movie ownership path passed on a fresh schema-8 clone:

- first cold request: 616.564 ms;
- seven cache-cold request median: 485.078 ms;
- warm median: 323.738 ms;
- warm p95: 359.211 ms;
- first cold statement count: 18;
- subsequent cache-cold statement count: 15;
- warm statement count: 4;
- authoritative matches: 20 of 20;
- serialized response: 55,176 bytes;
- provider calls: zero.

This is below the frozen limits of 750 ms cold, 400 ms warm median, 500 ms
warm p95, 35 statements, and 128 KiB.

The selected `space` Library movie path also passed a separately isolated,
properly primed larger sample:

- seven cold-run median: 288.216 ms;
- warm median: 246.370 ms;
- warm p95: 267.277 ms;
- warm maximum: 273.378 ms;
- statements: 16;
- returned and total: 32;
- deterministic repeat page: yes.

The first combined post-remediation probe produced two misleading failures:

- it measured the selected-page store's first unprimed call as part of the
  warm sample, inflating p95 to 690.885 ms;
- it measured ownership last after the complete sequential SQLite workload,
  producing a 753.488 ms cache-cold median.

The isolated larger samples above correct the first benchmark defect and
remove cross-probe load from the second. Both use production owners and
disposable copies of the same frozen clone. No threshold changed.

The complete post-remediation matrix otherwise passed:

| Query/page | Cold median | Warm median | Warm p95 |
| --- | ---: | ---: | ---: |
| `space`, 1 | 118.637 ms | 115.292 ms | 119.034 ms |
| `war`, 1 | 116.875 ms | 244.963 ms | 269.592 ms |
| `s`, 1 | 281.885 ms | 287.771 ms | 297.284 ms |
| `s`, 10 | 294.716 ms | 289.413 ms | 302.976 ms |
| `s`, 19 | 292.168 ms | 286.734 ms | 302.078 ms |
| `s`, requested 999 | 290.466 ms | 297.098 ms | 324.772 ms |
| no match | 5.168 ms | 4.333 ms | 5.187 ms |
| blank query | 5.076 ms | 3.519 ms | 3.732 ms |

Every non-empty identity request used two relational statements; the blank
query used none. The same row counts and serialized byte counts recorded in
section 24 remained bounded.

The broad `s` union again returned 924 rows and 924 unique identities with
ordered-key SHA-256
`bef37e297bcb092005ca37e49f30122b58c0823bcf833096c8621ffa578181ce`.
Query plans retained `idx_keywords_normalized_name`,
`idx_movie_keywords_keyword`, and `idx_provider_snapshots_movie`.

Final isolated provider transform p95 values were:

- keyword identities: 0.409 ms;
- People identities: 0.541 ms;
- keyword movies: 0.614 ms;
- 221-credit person filmography page: 6.515 ms.

Each returned at most 20 rows, made exactly one mocked provider request, made
zero persistence calls, and stayed within the frozen response-size limits.

## 28. Gate 5 complete verification

- focused Python: 164 tests passed in 43.868 seconds;
- full Python: 772 tests passed in 101.659 seconds;
- full Node: 63 tests passed, 0 failed, 0 skipped;
- production Vite build: passed in 2.06 seconds;
- full desktop Playwright: 35 tests passed in 34.4 seconds at 1600 by 1000
  with one worker;
- Git diff check: clean;
- branch and HEAD remain `master` at
  `4f143dfbc7c7a635fe47bdf18f96faa42ef6a4dc`;
- authoritative ownership and SQL parity documentation updated only after the
  behavior was proven;
- no files are staged or committed.

The same two pre-existing non-failing Python `ResourceWarning` messages
remained: one temporary file and one `dist/index.html` handle. The build used
the already approved unsandboxed command because the sandbox cannot read the
repository configuration.

### 28.1 Isolated schema-8 desktop runtime

The production build ran against a disposable schema-8 clone at:

```text
C:\Users\dante\AppData\Local\Temp\cp-gate5-browser-38cf2218f899413b95b97700a6eff488\user-data\.catalog-test.sqlite
```

The in-app browser rendered at 1600 by 1000 without a workspace crash:

- normal Library loaded 3,732 movies as page 1 of 94 with 40 visible cards;
- broad keyword `s` reported 924 identities across 19 pages;
- page 1 rendered 50 cards and `Showing 1-50 of 924`;
- page 2 replaced them with 50 cards and `Showing 51-100 of 924`;
- page 11 replaced them with 50 cards and
  `Showing 501-550 of 924`;
- page 19 rendered only its final 24 cards and
  `Showing 901-924 of 924`;
- Previous was disabled only on page 1 and Next only on page 19;
- selecting the page-19 `survivor memories` identity opened its one SQL-owned
  movie without a provider request.

Server logs showed one bounded `/api/library?view=keywords` request for each
explicit page. No page was prefetched and cards did not accumulate.

The disposable runtime clone finished with:

- schema version: 8;
- media generation: 6048, unchanged;
- `quick_check`: `ok`;
- foreign-key violations: zero.

The mounted application's existing followed-release check updated only the
disposable clone's `last_checked` values and advanced its curation generation
from 16752 to 16753. This was the established isolated curation behavior, not a
media-catalogue change. External provider access remained blocked by test mode.

The frozen source clone remained byte-identical at
`1FD08B7C2F62E36ACAB33CECCD1316967CD900E876F347A1A3B230D242312170`,
schema 8, media generation 6048, `quick_check=ok`, and zero foreign-key
violations.

## 29. Gate 5 cleanup and stop

Eleven Gate 5 focused, diagnostic, performance, full-suite, and browser roots
were verified as direct children of the operating-system temporary directory
and deleted. They were disposable and are not recoverable. Successful
Playwright roots were removed by the harness. The frozen Gate 0 evidence root
remains available.

The live catalogue, caches, configured movie roots, provider persistence, and
normal runtime were not used by tests or performance probes. The normal
port-5000 listener remains untouched at PID 37456.

Gate 5 is complete. The normal application has not been restarted, and no
live-catalogue rollout verification has begun. Per the plan, both require
Dante's separate approval.

## 30. Separately approved normal-runtime verification

Dante approved all remaining plan work after the Gate 5 stop. The reviewed
16-file implementation, regression, plan, and evidence patch was committed as:

```text
bed56a8d3a82665758571709a240af096728e6d2 Complete search and Discover pagination
```

The commit contains 3,466 insertions and 236 deletions. Every path was staged
explicitly; no directory-wide add, amend, push, or pull request was used.

The exact existing port-5000 process chain was resolved before restart:

- old parent PID: 46548;
- old listener PID: 37456;
- command: `.venv\Scripts\python.exe app.py`, spawning the Python 3.12
  listener.

The normal application was restarted from `bed56a8d3a82665758571709a240af096728e6d2`.
The final healthy process chain is:

- parent PID: 29644;
- listener PID: 46612;
- address: `127.0.0.1:5000`;
- application version rendered by the desktop UI: `v2.8.0`;
- API ready: 120.406 ms;
- reconcile status: `completed`.

The active log files are:

```text
C:\Users\dante\AppData\Local\Temp\cp-normal-runtime-20260726-041135.stdout.log
C:\Users\dante\AppData\Local\Temp\cp-normal-runtime-20260726-041135.stderr.log
```

They remain present because the running application owns them.

### 30.1 Live-state boundary

Only lightweight read-only state was captured; no live integrity audit,
backfill, rescan, repair, or performance benchmark was run.

Before restart:

- database:
  `C:\Users\dante\AppData\Local\Cinema Paradiso\Catalog\catalog-read-cb30c1d963c88463.sqlite`;
- schema version: 8;
- write authority: `sqlite`;
- media generation: 6076;
- curation generation: 16752;
- aggregate generation: 28951;
- media files: 3,737;
- provider snapshots: 7,447;
- people: 37,648;
- movie credits: 56,088;
- keywords: 7,937;
- movie-keyword relationships: 33,984;
- user lists: 11;
- collections: 583;
- followed releases: 11.

After restart and browser verification, schema version, write authority, media
generation, and every recorded row count were unchanged. Aggregate generation
advanced once to 28952 and curation generation advanced once to 16753,
coincident with the existing Home followed-release refresh. That request
completed with HTTP 200 and the 11 followed rows received the same new
`last_checked` value. No media generation changed.

### 30.2 Live desktop evidence

The in-app desktop browser exercised ordinary read, search, paging, and
navigation behavior:

- normal Library rendered 3,736 accepted movies as page 1 of 94, with 40
  cards and existing play controls;
- live Library keyword query `s` returned 925 identities across 19 pages;
- Library page 11 rendered 50 replacement cards and
  `Showing 501-550 of 925`;
- Library page 19 rendered its final 25 cards and
  `Showing 901-925 of 925`, with Next disabled;
- selecting the page-19 `survival thriller` identity opened its one SQL-owned
  movie;
- normal Trending Week Discover rendered 10,000 provider results as 250
  40-card application pages;
- normal Discover page 11 rendered 40 replacement cards and
  `Showing 401-440 of 10,000`;
- TMDB keyword query `space` returned 152 identities across eight bounded
  pages; page 8 rendered its final 12 identities;
- the selected `space` relationship returned 719 movies across 36
  20-card pages;
- moving that relationship from page 1 to page 2 replaced the first movie
  (`Supergirl` became `Alien³`), retained 20 cards, and exposed zero
  `Load more` buttons;
- Tom Hanks acting credits rendered 181 movies across ten bounded pages;
- Eric Roberts acting credits rendered 680 movies across 34 bounded pages;
- the Eric Roberts relationship reached page 11 with 20 replacement cards and
  `Showing 201-220 of 680`, with zero `Load more` buttons;
- Back restored the prior paged keyword identity state;
- Home, Movie Lists, Maintenance, and Downloads rendered normally;
- Movie Lists rendered its existing selected-list counts and playable owned
  cards;
- Maintenance rendered zero duplicate groups, 728 upgrade candidates, and one
  unmatched file;
- Downloads rendered the existing qBittorrent workspace;
- the SQL-owned Star Wars collection route returned HTTP 200 with nine parts,
  nine owned movies, media generation 6076, and curation generation 16753.

The server access log recorded:

- 20 bounded Library keyword identity requests, one per explicit page
  transition and no speculative page prefetch;
- 15 TMDB Discover requests;
- 15 TMDB keyword identity requests;
- two TMDB People identity requests;
- 12 TMDB person-movie requests;
- 30 existing authoritative `/api/library/check` ownership attachments;
- 257 HTTP 200 responses;
- two HTTP 304 responses;
- zero HTTP 500 responses and zero tracebacks.

One HTTP 404 was caused by the verification script issuing an empty collection
ID after assuming an obsolete SQL column name. The corrected read-only
`/api/library/collection/10` request returned HTTP 200. This was a probe error,
not an application failure, and made no write.

The existing followed-release refresh took 179,365.5 ms. It returned HTTP 200,
did not block the other threaded application routes, and is outside the
search/pagination change. It is recorded as an unrelated operational
observation, not concealed or attributed to this implementation.

The browser tab was closed after verification. The normal application remains
running on commit `bed56a8d3a82665758571709a240af096728e6d2`.

## 31. Plan completion

All formal gates, required regression evidence, documentation, commit
boundaries, and the separately approved normal-runtime verification are
complete. No schema migration, catalogue backfill, live rescan, repair, broad
live keyword benchmark, push, or pull request was performed.
