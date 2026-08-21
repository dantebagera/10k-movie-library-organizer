# Advanced Search Continuity and Regression Repair: Zero-Regression Plan

Status: saved for Dante's review. This document authorizes no product-code edit, Git staging or commit, process restart, push, release, or live-catalogue mutation.

Planning date: 2026-08-17

Repository: `C:\Users\dante\Desktop\cinema paradiso`

Observed planning baseline:

- HEAD: `631080a98921e6b36041fe9db51869c1785616ec`
- The worktree is intentionally dirty and contains the Advanced Search implementation plus the earlier Discover Language/Country work.
- The dirty work must be preserved exactly. Do not reset, overwrite, discard, or stage it as a side effect of this repair.
- The original plan remains the architecture foundation: `docs/plans/advanced-search-and-filters-zero-regression-implementation-plan.md`.
- This repair plan supersedes the original plan and `advanced-search-gate-1-decision-record.md` only where this document explicitly changes the UI rehearsal, result-density contract, mode-transition behavior, relationship execution, reset behavior, and tests.
- Repository instructions were supplied directly by Dante for this task. No physical `AGENTS.md` exists in this checkout or its parent path; the supplied instructions remain authoritative.

## 1. Goal

Repair the current Advanced Search implementation so it behaves like a continuous part of Cinema Paradiso rather than a separate page, while fixing every confirmed functional, paging, state, performance, API, and test regression.

The completed result must:

1. Restore the agreed compact in-search-bar rehearsal.
2. Keep the page, cards, filters, search selector, Search button, pagination, selection, expansion, history, and actions visually and behaviorally continuous.
3. Produce dense logical result pages at the measured desktop grid capacity (39 cards in the reported live viewport) whenever at least that many reachable matches exist.
4. Restore complete Actor, Director, and Writer filmography behavior in normal People search, Advanced Person criteria, expanded-card navigation, and Library-to-Discover navigation.
5. Compile normal Movies filters and Advanced criteria into one authoritative query model per workspace.
6. Keep Library SQL-only through `CatalogStore.library_page` and the existing selection owner.
7. Keep Discover TMDB-owned through one bounded planner, with honest limitations and no per-card detail crawl.
8. Remove tests that encode the current bugs and replace them with behavioral regression coverage.
9. Remain desktop-only. Do not redesign mobile or unrelated surfaces.

## 2. Confirmed failures that this plan must repair

These are current measured or source-proven failures, not speculative enhancements.

| Failure | Current owner/location | User impact |
| --- | --- | --- |
| People filmography is routed through Advanced Discover whenever a relationship context contains `query` | `DiscoverWorkspace.loadContextPage` | Normal People, Advanced Person, and Library-to-Discover filmographies show incomplete or empty credits. Tom Hanks returned 182 backend credits but only one UI card in the live reproduction. |
| Person filtering occurs after a generic provider page is sliced | `advanced_tmdb_discover` | Role matches are scattered across many sparse pages instead of being resolved as one credit set before pagination. |
| Title, summary, person, and local criteria may filter an already sliced provider window | `advanced_tmdb_discover` and workspace local filtering | Pages can contain only a few cards even though enough later matches exist to fill the desktop grid. |
| Selecting Advanced while a relationship context is open leaves that old context active | Discover workspace mode/context effects | The Advanced builder appears but criteria do nothing until Search manually clears the context. |
| Hidden quick-filter state still filters Advanced collection/list contexts | `filterDiscoverContextResults` and `hasAdvancedDiscoverCriteria` | Visible Advanced blocks and actual results can disagree. |
| Ownership and other local refinements trigger a new TMDB request | Discover load-effect dependencies | A local filter disables Search, reloads cards, and makes the page appear to collapse or refresh. |
| Switching Advanced to Movies reloads or clears cards even when the effective query did not change | Library and Discover mode effects | The same result universe visibly refreshes merely because its editor changed. |
| Advanced Reset does not reset the import lifecycle | builder reset plus `advancedImportedRef` | After Reset, later Movies criteria are never imported on the next first Advanced entry. |
| Advanced errors and Retry are inside the `+` popover | `AdvancedSearchBuilder` | A failed request can leave stale cards with no visible error or recovery action. |
| Library expanded-card person/list actions can update hidden simple state while Advanced remains authoritative | `applyRoleFilter`, `applyListFilter`, `activeLibraryQuery` | Clicking an action may appear to do nothing or navigate using the wrong query. |
| Library Advanced person autocomplete downloads the whole People projection | `searchLibraryAdvancedIdentities` | A single lookup transferred about 8.2 MB and 3,835 items and took about 7.7 seconds in the live measurement. |
| Identity lookup failures are swallowed as an empty list | `IdentityPicker` | Network or API failure looks like “no matches” and has no Retry. |
| Malformed Library page values escape as HTTP 500 HTML | `POST /api/library/search/advanced` | Invalid client input produces an uncontrolled server failure instead of JSON HTTP 400. |
| Shared request contract says 200 while TMDB silently clamps to 100 | Advanced validation versus `_tmdb_requested_page_size` | Client and server disagree about accepted page size. |
| Current source-string and mocked E2E tests encode the wrong relationship route | `test_unified_movie_card_ui.py` and broad `/api/tmdb/discover**` mocks | Green tests conceal the real People regression. |
| The current warning, labels, and button styling differ from the approved rehearsal | builder, registry, workspace buttons, CSS | Advanced looks like a foreign panel and the page loses visual continuity. |

## 3. Authoritative product contract

### 3.1 Search-strip continuity

- Advanced remains inside the existing search form. It is not a separate panel, drawer, card, or page section.
- The surrounding search form keeps its normal width, location, height rhythm, selector location, and Search-button location.
- Selecting Advanced synchronously hides the normal quick-filter toolbar, whether the toolbar was expanded or collapsed. This is a React state transition only; it must not blank cards or issue a request solely because the toolbar disappeared.
- Leaving Advanced synchronously restores the prior Movies toolbar open/collapsed state without blanking cards.
- The gold Advanced affordance is a simple circular `+` inside the former text-input area.
- When no completed criterion exists, red text immediately after `+` says that the field is no longer a normal text search. The final short wording is rehearsed visually, but it must not become a large heading or second panel.
- As soon as the first criterion is completed, the red warning disappears. Criteria begin immediately after `+` and flow left-to-right in the same strip.
- Criterion clusters remain compact. They may wrap only within the existing bounded search-strip expansion contract; overflow uses the existing explicit `+N more` control.
- Different criterion groups are joined by visible `AND` text.
- Repeated values show a visible `AND` or `OR` control between values. Clicking the word toggles to the other allowed connector. The visible word and submitted query must always agree.
- The picker/popover is temporary editing UI. Closing it never removes completed criteria, cards, errors, or Retry.

### 3.2 Existing controls

- The selector remains in the same location and size and remains `Movies | People | Keywords | Advanced`.
- The button remains the existing `Search` button in the same location and size. Its label stays `Search` in Advanced mode.
- Advanced may change only the button fill/accent to the existing Cinema Paradiso blue/violet palette used by the Experimental badge. Use the existing palette variables; do not introduce a one-off gradient or new color system.
- Loading may replace the icon with the established spinner, but must not change button geometry or label.
- Advanced registry display labels are `Language` and `Country`. Their semantics remain original language and production/origin country internally and in accessible help where needed.
- `Reset advanced search` is explicit and accessible from the Advanced strip/picker without requiring an error state.

### 3.3 Draft, execution, and reset

- Each workspace owns an independent Advanced draft and last executed Advanced query.
- First Advanced entry after a true Advanced reset imports the current Movies title and quick criteria exactly once.
- Ordinary exit and re-entry restores the existing Advanced draft without re-import or duplication.
- Reset clears draft, executed query, Advanced history/result snapshots, and the import marker together, then restores Library Latest additions or Discover Trending Week.
- The next Advanced entry after Reset imports the then-current Movies criteria once.
- Editing a draft does not make hidden quick-filter state authoritative.
- Search executes the current normalized draft immediately. The existing 300 ms debounce may execute completed edits automatically, but both paths call the same execution owner.
- Error and Retry remain visible beside the strip whenever the last requested query failed, regardless of picker state. Existing cards and blocks remain visible.

### 3.4 Mode transitions without card refresh

Define an effective result identity as:

`workspace + source owner + normalized query signature + relationship identity + logical page size + logical page`

- Changing only the editor mode must not change effective result identity.
- If Advanced and Movies compile to the same effective result identity, switching between them reuses the current cards, totals, page, ownership, selection, and expansion state with zero network request.
- If the effective query genuinely changes, keep the last successful cards and fixed grid geometry visible while the replacement loads. Do not clear the grid, collapse the page, or show a blank intermediate state.
- Selection and expansion are cleared or reconciled only when the effective result identity changes under their existing contracts, not merely when the selector changes.
- A relationship context must never silently remain authoritative behind a different visible mode. Mode transition must either restore the selected mode's saved snapshot or execute that mode's explicit query.

## 4. Dense logical page contract

### 4.1 Required behavior

- Page size comes from the existing desktop grid measurement owner, not a new constant. The reported viewport currently resolves to 39 cards.
- Filtering and sorting happen before logical UI pagination.
- If at least one full logical page of reachable matches exists, the page contains the measured capacity. A non-terminal page with two or three cards while matches are scattered on later provider pages is a regression.
- Only the genuinely terminal page may be partial.
- Changing viewport-derived page size recomputes the logical window through the existing grid owner without creating a second result engine.
- Ordering is deterministic. Moving Next then Previous must return the same movie identities in the same order for a stable provider snapshot.

The forbidden order is:

`fetch provider page -> slice UI page -> apply criteria -> render sparse page`

The required order is:

`normalize query -> resolve authoritative candidate stream/set -> apply all executable criteria -> deterministic sort -> slice dense logical page -> attach ownership/local presentation -> render`

### 4.2 Execution by criterion class

1. **Library criteria:** SQL applies the complete predicate, count, sort, and page in `CatalogStore.library_page`. No client post-filter may thin an SQL page.
2. **TMDB provider-native criteria:** compile into the provider request before TMDB pagination. Existing logical-page composition may fetch the minimum adjacent 20-row provider pages needed for the measured UI capacity.
3. **Role-specific People criteria:** `/api/tmdb/person_movies` credit normalization is the seed owner. Build each selected person/role movie-ID set first; apply same-type union/intersection and cross-type intersection before logical paging. Do not intersect a generic already-sliced Discover page.
4. **Title plus summary criteria:** use a bounded sequential title-page scanner because TMDB Search cannot accept all Discover filters. It collects matching summaries until the dense logical page is full, the provider is exhausted, or an approved scan budget is reached. Totals remain explicitly bounded/unknown until exhaustion.
5. **Availability, viewing status, and Cinema Paradiso list criteria:** use existing local identity owners. They may refine the TMDB candidate stream, but the dense-window owner—not a React render filter—must collect enough matching summaries for the requested logical page.
6. **Collections and finite user-list arrays:** filter/sort the complete finite array first, then slice locally. Do not pass them through the remote Advanced route.

### 4.3 One bounded dense-window owner

Extend the existing TMDB logical-page service rather than adding route-specific loops.

The owner is keyed by normalized query signature and records only a short-lived execution ledger:

- provider pages already examined;
- ordered matching movie summaries/IDs;
- provider cursor/next page;
- whether the provider is exhausted;
- request-generation identity and expiry.

Rules:

- It is a bounded cache, not a persistent source of truth.
- It is shared by normal and Advanced Discover execution when their normalized query is equivalent.
- It fetches sequential provider pages only as required to satisfy the requested logical window.
- It never fetches movie details once per card.
- It deduplicates by stable TMDB movie ID before slicing.
- It aborts/ignores stale work through the existing request sequence and abort owners.
- A scan budget is frozen from Gate 1 measurements before implementation. It cannot be increased after a failing test merely to force green results.
- Hitting the scan budget before producing a full non-terminal page is not reported as a normal complete page. Preserve prior cards and show a retryable, honest bounded-result state.
- If measurements prove that the requested 39-card behavior for a supported local/title combination requires an unsafe broad TMDB crawl, stop at Gate 1 and present the measured product alternatives to Dante. Do not silently restore sparse pages or perform an unbounded crawl.

### 4.4 Pagination metadata

Do not fabricate a provider-global filtered total.

For exact result owners (Library SQL, finite credit set, exhausted finite collection/list), return exact `total_results` and `total_pages`.

For a still-scanning bounded TMDB stream, return:

```json
{
  "page": 1,
  "page_size": 39,
  "results": [],
  "total_scope": "bounded",
  "total_results": null,
  "total_pages": null,
  "has_previous": false,
  "has_next": true,
  "provider_exhausted": false,
  "total_label": "39 matches collected from TMDB"
}
```

- Enhance the existing shared Pagination owner to support an unknown-total state; do not create an Advanced-only paginator.
- Unknown-total presentation shows `Page N`, Previous, and Next without inventing `of Y`.
- Once exhaustion is proven, the same owner may expose the exact final total and terminal partial page.
- Normal provider-native queries that already have reliable TMDB totals keep `Page X of Y`.

### 4.5 Page-size contract

- Use one shared validated maximum of 100 results per logical page, matching the existing desktop grid hook and current TMDB logical-page owner.
- Update the shared schema/decision record from 200 to 100. Do not silently clamp a value that the validator accepted.
- Invalid type, non-numeric value, zero, negative value, or value above 100 returns JSON HTTP 400 from both Advanced transports.

## 5. Authoritative ownership after repair

### 5.1 Shared query model

- `src/features/search/advancedSearchModel.js` remains the single normalization/signature compiler for frontend simple and Advanced state.
- `src/features/search/advancedSearchRegistry.js` remains the single display/capability registry.
- Add no workspace-specific duplicate criterion semantics.
- Query signature must exclude presentation labels that do not change execution and include every value that does.

### 5.2 Library

- `services/catalog_store.py::CatalogStore.library_page` remains the only card predicate/count/sort/page owner.
- `library_selection_paths` consumes the exact same normalized predicate.
- Expanded-card person, keyword, and list actions must deliberately transition to the correct query mode and owner before changing criteria.
- Library person autocomplete must query a bounded local identity route or the existing loaded People cache. It must never download the complete card projection per keystroke and must make zero TMDB calls.

### 5.3 Discover

- `services/tmdb_advanced_search.py` owns provider planning and criterion classification.
- Existing `app.py` TMDB page-window helpers own bounded provider composition and are extended into the dense-window execution owner.
- `/api/tmdb/person_movies` credit normalization is extracted/reused; it is not bypassed by the Advanced route.
- `DiscoverWorkspace` owns presentation state, history, mode snapshots, request sequencing, and ownership rendering. It does not interpret movie-filter semantics after a page is returned.
- Remove `context.query && !isPick` as a route selector. Context type/source explicitly selects its authoritative endpoint/planner.
- Remove hidden quick-state filtering from Advanced collection/list/relationship execution after the normalized-query owner covers it.
- Ownership-map updates remain local and optimistic where already supported. Changing an ownership selector itself must not issue a TMDB request unless the dense-window contract genuinely needs more candidate rows to fill the current page.

### 5.4 Workspace state machine

Replace independent effect-driven mode side effects with one explicit transition owner per workspace:

- `enterMode(nextMode)` selects/restores the saved editor and result snapshot;
- `executeQuery(normalizedQuery, reason)` owns request identity and loading/error state;
- `enterRelationship(context)` selects the relationship owner and snapshot;
- `resetAdvanced()` clears all Advanced state including import lifecycle;
- `restoreSnapshot(snapshot)` restores mode, query, relationship, results, page, totals, and label atomically.

Effects may observe these states, but two effects must not compete to execute the same semantic transition.

## 6. API repairs

### 6.1 Library Advanced

- Catch JSON shape, integer conversion, bounds, and query validation errors and return a consistent JSON HTTP 400 envelope.
- Never expose Flask's HTML 500 response for client validation failures.
- Preserve SQL-only execution and existing card response shape.

### 6.2 Discover Advanced

- Delegate provider-native, title-stream, and people-seed strategies through one planner/executor.
- Return exact versus bounded total metadata honestly.
- Preserve adult-content settings through the same owner used by normal search.
- Do not expose raw provider errors, keys, URLs, or stack traces.

### 6.3 Identity endpoints

- Library person/keyword suggestion responses are capped at 20 and return only controlled identity fields needed by the picker.
- Discover People/Keyword suggestions retain their current bounded endpoints, abort behavior, and paging.
- Picker responses distinguish `loading`, `no matches`, and `request failed`; failure includes Retry.

## 7. Implementation gates

### Gate 0 — Freeze the failing baseline

Read-only except disposable test artifacts.

1. Record HEAD, complete dirty status, diff summary, version, live process owner, served bundle hashes, and normal API owner.
2. Preserve every current uncommitted file.
3. Capture deterministic failing fixtures for Tom Hanks Actor credits, another Director, another Writer, one Advanced person+genre query, one title+filter query, and one local-ownership query.
4. Record current visible card counts and network calls for Movies -> Advanced -> Movies, quick-filter hide/show, Reset/re-import, error with picker closed, and relationship-to-Advanced transition.
5. Measure the current Library Advanced person suggestion payload/time.
6. Capture malformed request responses and the 200-versus-100 page-size mismatch.
7. Run the focused tests but classify false positives; green is not acceptance.

Stop if HEAD/worktree/runtime owner differs unexpectedly or a failing fixture cannot be reproduced/explained.

### Gate 1 — Freeze dense-window semantics and budgets

This gate is design, fixtures, and measurement before production-code repair.

1. Approve this document's UI contract and its supersession of the earlier large-panel rehearsal.
2. Measure how many provider pages representative title, person, owned, unowned, watched, watchlist, and list queries require to fill the live 39-card viewport.
3. Freeze provider request, elapsed-time, cache-size, and expiry budgets before implementation.
4. Approve unknown-total pagination wording for bounded streams.
5. Confirm the single maximum logical page size of 100.
6. Produce exact expected ordered movie-ID fixtures for every strategy.

Mandatory stop: if safe bounds cannot normally produce dense pages for an advertised criterion, present the measured choices to Dante. Do not guess or conceal the limitation.

### Gate 2 — Replace false-positive tests first

Before repairing production behavior:

- Delete/replace the assertion that requires `context.query && !isPick`.
- Make People E2E mocks distinguish `/api/tmdb/person_movies` from `/api/tmdb/discover/advanced` and fail when the wrong route is called.
- Add backend fixtures where matches occur beyond the first provider page so post-slice filtering necessarily fails.
- Add a 39-card logical-page fixture assembled across several 20-row provider pages.
- Add network-count assertions for mode-only transitions and local-only filter changes.
- Add reset/re-import, closed-picker error, hidden-state disagreement, expanded-card person/list action, and malformed-page tests.

The new tests must fail for the current implementation for the expected reasons before repair begins.

### Gate 3 — Backend correctness and dense pagination

1. Reuse/extract the `/api/tmdb/person_movies` credit-set owner.
2. Implement pre-pagination person set union/intersection and cross-criterion intersection.
3. Extend the existing TMDB logical-page owner with the bounded dense-window ledger.
4. Move all post-window filtering that affects membership ahead of logical slicing.
5. Implement exact/bounded metadata and unknown-total pagination contract.
6. Align validation at maximum page size 100 and return controlled JSON 400 errors.
7. Preserve provider-native one-window behavior for ordinary queries and prove no N+1 details.

Gate acceptance requires ordered identity fixtures, dense pages, stable back/forward paging, bounded provider calls, and exact route-owner assertions.

### Gate 4 — Workspace state and relationship repair

1. Introduce the explicit mode/query/relationship transition owner in Library and Discover.
2. Restore normal People, Advanced Person, expanded-card, and Library-to-Discover filmographies through their correct owner.
3. Remove mode-switch requests when effective result identity is unchanged.
4. Preserve current cards and geometry during genuine replacement requests.
5. Make local filter changes immediate; request more TMDB candidates only through the dense-window owner when required to fill the page.
6. Remove hidden simple-filter interpretation from Advanced contexts.
7. Repair Reset/import lifecycle and atomic history restoration.
8. Make expanded-card person, keyword, list, and collection actions choose an explicit query owner.

### Gate 5 — Compact rehearsal UI

1. Keep the Advanced canvas in the existing search field footprint.
2. Use the small circular gold `+` and transient red warning.
3. Make criteria start immediately after `+`; hide the warning after the first block.
4. Keep clickable AND/OR words exactly as rehearsed.
5. Keep selector and Search button geometry/label; use only the existing blue/violet palette token for Advanced emphasis.
6. Rename visible registry labels to Language and Country.
7. Keep quick filters disappearing/restoring synchronously without result-grid movement.
8. Keep error/Retry outside the temporary picker and retain keyboard/focus accessibility.

Desktop visual rehearsal is required at the existing supported viewport. No mobile work.

### Gate 6 — Identity performance and duplicate-owner removal

1. Replace full Library People projection downloads with bounded local identity lookup/cache reuse.
2. Add explicit picker error/no-match states.
3. Remove obsolete local filtering, URL selection, mode effects, and compatibility logic made redundant by Gates 3-4.
4. Verify one query owner per workspace and one relationship owner per context.
5. Measure cold/warm identity lookup, serialized bytes, SQL/provider calls, and dense-window behavior against Gate 1 budgets.

### Gate 7 — Full zero-regression proof

Run proportionate focused suites first, then:

- complete Python suite under unique `CP_TEST_ROOT` and `CP_TEST_MODE=1`;
- all repository Node tests;
- production `npm.cmd run build`;
- full desktop Playwright with exact route mocks and one worker where shared state requires it;
- isolated normally served `dist` verification;
- visible desktop rehearsal against the normally served application after separate restart approval if the live process requires replacement.

Evidence must include exact pass counts, request logs, response metadata, provider-call counts, payload bytes, screenshots, served asset hashes, and browser console errors.

### Gate 8 — Mutation boundary

Stop and present:

- complete diff;
- files changed by owner;
- removed obsolete paths;
- automated evidence;
- performance evidence;
- normally served desktop evidence;
- remaining honest limitations.

Separate authorization is still required before staging/commit, restarting the normal process, pushing, releasing, or mutating the live catalogue. A broad “finish implementation” approval does not silently authorize those external mutations unless Dante explicitly says it does.

## 8. Regression matrix

### 8.1 Filmography and relationships

- People search -> Tom Hanks -> Actor shows the complete reachable credit total and full logical pages.
- Actor, Director, and Writer each call their correct relationship owner.
- Advanced one-person and multi-person OR/AND work before pagination.
- Person + genre/year/rating filters produce dense logical pages where enough matches exist.
- Library expanded-card local person filtering stays in Library SQL.
- Library `Open filmography` deliberately enters Discover and uses `/api/tmdb/person_movies` semantics.
- Keyword relationships remain correctly paged and are not accidentally routed through person/advanced execution.
- Collection and list navigation preserve their finite-array owner.

### 8.2 Dense pages

- Provider page boundary: 39 UI cards assembled from at least two 20-card TMDB pages.
- Sparse-match fixture: matching rows distributed across at least five provider pages still form one dense logical page within the approved budget.
- Only terminal page is partial.
- No duplicate IDs or missing IDs across logical pages.
- Next -> Previous restores exact identities and order.
- Title+summary and local refinements show bounded/unknown totals until exhaustion, never fake global totals.
- Budget exhaustion is visible and retryable; it is never mislabeled as a complete sparse page.

### 8.3 Mode continuity

- Movies -> Advanced with equivalent query makes zero result request and preserves cards.
- Advanced -> Movies with equivalent query makes zero result request and preserves cards.
- Different query keeps old cards until new success and never collapses grid geometry.
- Expanded/collapsed quick toolbar disappears and restores without network activity.
- Switching from an open relationship to Advanced restores/executes the correct Advanced snapshot; no hidden relationship remains.
- Back restores mode, query, relationship, results, page, totals, label, and selection contract atomically.

### 8.4 Builder and design

- Empty Advanced strip shows `+` plus red warning.
- First completed criterion removes warning and occupies the next inline position.
- AND/OR click changes visible connector, signature, request, and results together.
- Button remains `Search`, same geometry, blue/violet token.
- Selector remains same geometry/location.
- Language and Country are the visible labels.
- Picker open/close does not move results or own persistent errors.
- Error with picker closed is visible with Retry and preserved blocks/cards.
- Reset then modified Movies filters then Advanced imports once.

### 8.5 Library and API

- Normal and Advanced equivalent Library query return identical totals, ordered IDs, pages, and selection paths.
- Library title, genre, person, keyword, year, rating, runtime, status, list, resolution, source, language, and country remain SQL-only.
- Library Advanced person suggestions return at most 20 controlled identities with bounded payload and zero TMDB calls.
- Invalid JSON, unknown fields, bad page/page_size type, out-of-range values, unsupported criteria, and reversed numeric ranges return JSON HTTP 400.
- Page size 100 succeeds; 101 fails consistently in frontend and both APIs.

### 8.6 Existing surfaces

- Cards, desktop grid, upper/lower pagination, expansion, trailers, playback, source search, poster editing, watched/watchlist, user lists, ownership, and bulk selection remain under existing owners.
- Library default remains Latest additions.
- Discover default remains Trending Week.
- Normal Movies, People, and Keywords search remain reachable and complete under their existing contracts.
- Language/Country work already in the dirty tree remains intact.
- Offline TMDB, 401, 429, timeout, abort, stale response, malformed provider data, and empty results do not crash or mismatch cards and query.

## 9. Test ownership

- `tests/test_advanced_search_model.py` and `tests/advancedSearchModel.test.mjs`: normalization, labels, signatures, 100-row bound, mode-equivalence identity, reset/import helpers.
- `tests/test_advanced_library_api.py`: SQL parity, HTTP 400 envelope, suggestion bounds, zero provider calls.
- `tests/test_advanced_discover_api.py`: planner strategies, dense windows, people seed sets, bounded totals, scan budget, errors, provider-call counts.
- `tests/test_tmdb_details_transform.py`: reusable person-credit owner and logical-page helper behavior.
- `tests/test_catalog_store.py`: exact SQL page/count/selection parity and deterministic order.
- `tests/test_library_action_ux.py`: mode transitions, local relationship/list actions, labels, button/search-strip contract.
- `tests/test_unified_movie_card_ui.py`: remove wrong route assertion; assert explicit relationship owner and card/history preservation.
- `tests/test_discover_search_race_ui.py`: stale dense-window request rejection and mode-switch request counts.
- `tests/e2e/app-smoke.spec.js`: visible compact rehearsal, 39-card dense page, People discography, reset/re-import, errors, and no-refresh transitions.
- `tests/e2e/cross-page-selection.spec.js`: logical-page identity and selection behavior where the existing owner applies.

Static source-string checks may supplement structure but cannot be the only proof of execution semantics.

## 10. Performance and safety budgets

Numerical TMDB dense-window budgets are frozen at Gate 1 from measured fixtures. Additional non-negotiable limits:

- No unbounded provider crawl.
- No movie-detail request proportional to rendered cards.
- No full Library card/People projection for autocomplete.
- Identity response: at most 20 suggestions and only required identity fields.
- Logical UI page: no more than 100 cards.
- Provider-page cache: bounded entry count, bounded TTL, query-signature isolation, no persistent authority.
- Aborted/stale work cannot update cards, totals, history, loading, or errors.
- Server validation errors never expose SQL, filesystem paths, API keys, provider URLs with credentials, or tracebacks.
- Tests and benchmarks use unique disposable roots; no live catalogue mutation, migration, backfill, rescan, or repair.

## 11. Stop conditions

Stop and ask Dante if:

1. Dense 39-card pages for an advertised title/local criterion require an unsafe or effectively unbounded TMDB crawl.
2. The correct role-specific People implementation requires a new persistent TMDB index or catalogue schema.
3. A supported result owner cannot provide deterministic ordering across dense pages.
4. Unknown-total pagination would require replacing rather than safely extending the shared Pagination component.
5. Existing card, selection, history, ownership, or relationship behavior cannot be preserved inside the stated owners.
6. The dirty worktree changes unexpectedly or overlaps cannot be preserved.
7. The runtime serves another checkout or bundle and restart authority is absent.
8. Mobile, unrelated page redesign, schema migration, live catalogue work, new persistence authority, commit, push, restart, or release becomes necessary.
9. Gate 1 budgets fail and the only apparent fix is raising them after implementation.

## 12. Definition of complete

The repair is complete only when:

- Advanced visually remains the same search strip and follows the approved `+`, warning, inline criteria, connector, Search button, selector, and palette contract;
- normal and Advanced modes compile into one query model and equivalent mode switches make zero result requests;
- non-terminal result pages are dense at the measured grid capacity when enough reachable matches exist;
- People filmographies are complete and use the correct relationship owner before pagination;
- hidden quick state cannot influence Advanced results;
- local controls do not cause unnecessary TMDB refreshes;
- Reset/re-import, error/Retry, relationship transitions, expanded-card actions, history, selection, and pagination pass behavioral coverage;
- Library remains exact SQL-only and its autocomplete is bounded;
- Discover remains one bounded TMDB planner with honest exact/bounded totals;
- malformed requests return controlled JSON 400 responses;
- the shared page-size contract is consistently 100;
- false-positive tests are removed and the current implementation fails the new regressions before the repair makes them pass;
- obsolete duplicate logic is removed;
- focused/full tests, production build, normally served assets, and visible desktop rehearsal pass;
- Dante separately approves any commit, normal-process restart, push, release, or live mutation.

## 13. Implementation handoff

After Dante approves implementation, begin at Gate 0 and proceed gate by gate. Do not begin with CSS. First freeze the failing fixtures and replace the tests that currently bless the wrong relationship route. Then repair result ownership and pagination, then workspace state transitions, and only then apply the compact visual rehearsal. The visual continuity depends on correct state ownership; CSS alone cannot fix the card refresh, sparse pages, or broken filmographies.
