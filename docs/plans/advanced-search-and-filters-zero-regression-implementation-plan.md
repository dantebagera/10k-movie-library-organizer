# Advanced Search and Filters: Zero-Regression Implementation Plan

Status: saved for review and handoff only. Product implementation is not approved and has not started.

Proposed task name:

`Advanced Search and Filters - Zero Regression`

Planning baseline recorded on 2026-08-16:

- Repository: `C:\Users\dante\Desktop\cinema paradiso`
- Branch: `master`, one commit ahead of `origin/master`
- Checkpoint commit: `631080a98921e6b36041fe9db51869c1785616ec`
- Application version: `2.8.4`
- The worktree is intentionally not clean. It contains the already requested Discover Language/Country filter amendment in `app.py`, `DiscoverWorkspace.jsx`, `styles.css`, and related tests.
- That amendment had focused Python, build, Playwright, and served desktop UI evidence, but the running port-5000 backend had not been restarted; `/api/tmdb/filter-options` currently answers 404 from the old process.

The implementation task must recheck every baseline fact. This document does not authorize Git staging, a commit, a restart, a catalogue write, a release, or feature implementation.

## 1. Goal

Make search and filtering one coherent system in Library and Discover so a user can build an exact movie request from several criteria without losing the current quick-search experience.

The completed product must:

1. Keep Movies, People, and Keywords search working as they do now.
2. Add `Advanced` to the existing search-type selector.
3. Transform the search input into an unmistakable criterion builder in Advanced mode.
4. Allow several values of the same type with an explicit `AND` or `OR` rule.
5. Combine different criterion types with `AND`.
6. Use controlled identities for genres, people, keywords, countries, and languages so misspellings cannot silently corrupt the request.
7. Keep the current Library and Discover grids, cards, pagination, expansion, actions, selection, ownership badges, and source search unchanged.
8. Share one frontend query contract while respecting two different authoritative data owners: local SQL for Library and TMDB for Discover.
9. Migrate normal quick filters into the same underlying query model so no hidden second filter engine remains.
10. Preserve Library's `Latest additions` default and Discover's `Trending Week` default.

## 2. The uncomfortable technical truth

Library and Discover can share the builder and query language, but they cannot truthfully promise identical search completeness.

- Library owns its full dataset and can execute exact compound criteria in SQLite.
- TMDB's `/discover/movie` supports many compound filters, including comma-separated `AND` and pipe-separated `OR` values.
- TMDB's `/search/movie` searches titles but does not accept the full Discover filter set. The current Cinema Paradiso title path filters only the provider pages it has loaded.
- TMDB's generic `with_crew` parameter does not prove that a person was specifically the director, writer, or producer. Exact roles require the person's movie credits and job-aware filtering.

Therefore Advanced Discover must never label a bounded title refinement as a complete global result. Gate 1 must select and document one honest title strategy before implementation; no engineer may hide the limitation with unbounded fetching or per-card detail requests.

Official capability references:

- [TMDB Discover Movie](https://developer.themoviedb.org/reference/discover-movie)
- [TMDB Search Movie](https://developer.themoviedb.org/reference/search-movie)
- [TMDB Person Movie Credits](https://developer.themoviedb.org/reference/person-movie-credits)

## 3. Confirmed current owners

### 3.1 Shared desktop presentation

- `src/features/library/LibraryWorkspace.jsx` owns Library search mode, filters, paging state, result history, selection scope, and Library result loading.
- `src/features/discover/DiscoverWorkspace.jsx` owns Discover search mode, feed/filter state, relationship contexts, provider paging, history snapshots, stale-request cancellation, and ownership presentation.
- The two workspaces already share the global movie-card and pagination components. Those owners must not be forked.
- The existing desktop search-type selector currently exposes Movies, People, and Keywords. Advanced extends this selector; it does not introduce a separate window or left-side drawer.

### 3.2 Library execution

- `app.py::_library_query_filters` normalizes the current flat filter request.
- `GET /api/library?view=cards` delegates to `_paged_library_cards`.
- `services/catalog_store.py::library_page` and `_library_filter_sql` are the authoritative SQL result, total, paging, and filter owners.
- Existing Library person, keyword, collection, list, viewing-state, language, country, genre, source, resolution, date, rating, and title constraints already execute in SQL.
- Library people and keyword identity search must remain local to stored, owned catalogue data and make zero TMDB calls.

### 3.3 Discover execution

- `GET /api/tmdb/discover` owns provider-native feed/discover requests.
- `GET /api/tmdb/search` owns title search and currently applies additional criteria to the loaded provider page window.
- `GET /api/tmdb/person_movies` owns role-aware Actor, Director, and Writer filmographies.
- `GET /api/tmdb/people/search` and `/api/tmdb/keywords/search` own selectable remote identities.
- `/api/tmdb/filter-options` is the pending authoritative language/country option source in the current worktree.
- Existing request sequence guards and `AbortController` logic are authoritative for rejecting stale responses.
- Existing ownership attachment and user-list owners remain authoritative. Advanced Search must not create another ownership lookup implementation.

## 4. Product contract

### 4.1 Simple modes

- The selector remains `Movies | People | Keywords | Advanced`.
- Movies mode keeps the normal editable title search and the compact quick-filter toolbar.
- People and Keywords remain identity searches. Their selected identity may still resolve to movie results through the existing relationship flow.
- Quick filters remain optimized for one common value per type.
- Library opens in Movies mode, collapsed filters, `Latest additions` sort.
- Discover opens in Movies mode, `Trending Week`.

### 4.2 Entering Advanced

When Advanced is selected:

- The search input becomes a criterion canvas, not a text field.
- It has a gold accent, permanent `Advanced search builder` label, and a prominent gold `+ Add criterion` button.
- It shows a non-editable scope label: `Your entire library` in Library and `TMDB Catalog` in Discover.
- It has no blinking caret, search placeholder, or leading search icon that implies free typing.
- The quick-filter toolbar disappears because its active values have been compiled into criterion blocks.
- On the first entry after reset, the current Movies title and active quick filters are imported once. Re-entering Advanced restores the existing Advanced draft and must not duplicate imported blocks.

### 4.3 Builder layout

- Completed criteria render as compact blocks inside the existing search strip.
- The strip may wrap to multiple lines. Desktop height is capped at three visible lines; additional blocks collapse behind `+N more` with an explicit expand/collapse control.
- Every completed block has an accessible remove button (`x`).
- Same-type blocks show an `AND`/`OR` connector between them. The default is `OR`.
- Different types are always joined by `AND`; the UI states this once rather than repeating separators everywhere.
- The user adds values through `+ Add criterion`, not by typing syntax into the canvas.
- The current result grid and cards do not move into the builder and are not redesigned.

### 4.4 Adding a criterion

The interaction is:

`+ Add criterion` → choose type → choose/configure a valid value → choose role/operator if required → `Add`.

- Opening a picker or typing in autocomplete does not run the movie query.
- Selecting a completed value adds the block and schedules a result refresh.
- Removing a block, changing a connector, changing a role, or changing a numeric operator schedules a result refresh.
- Changes use a 250-400 ms debounce and cancel/ignore older requests.
- The existing Search button becomes `Run search` in Advanced mode and remains available for immediate execution or retry.
- Invalid or incomplete draft values never become blocks and never reach the API.

### 4.5 Leaving and restoring Advanced

- Each workspace owns an independent session draft. Library criteria never leak into Discover and vice versa.
- Switching from Advanced to Movies/People/Keywords restores that simple mode's state. Hidden Advanced criteria do not continue filtering results.
- Re-entering Advanced restores its last draft.
- `Reset advanced search` clears its draft and returns the page to its default: Latest additions for Library, Trending Week for Discover.
- Browser/workspace history snapshots restore mode, normalized query, page, results, totals, and label together.
- A criterion change resets to page 1, closes the expanded card, and applies the existing selection-scope rules.

## 5. Criterion and value contract

| Criterion | Pages | Value control | Same-type rule | Execution meaning |
|---|---|---|---|---|
| Title | Both | Text input inside its picker; one normalized block | One block only | Case-insensitive textual movie-title request |
| Genre | Both | Searchable controlled multi-picker | AND or OR | Stable TMDB genre ID in Discover; stored genre identity in Library |
| Person | Both | Debounced autocomplete, then required identity selection and role | AND or OR | Stable person identity plus Actor/Cast, Director, Writer, Producer, or Any credit |
| Keyword | Both | Debounced autocomplete, then required identity selection | AND or OR | Stable keyword identity; unmatched raw text is not accepted |
| Release year | Both | Exactly / At least / At most / Between with numeric year inputs | One block | Applies to primary release year/date |
| Rating | Both | Exactly / At least / At most / Between, validated 0-10 | One block | TMDB rating in Discover; stored canonical rating in Library |
| Minimum votes | Discover; Library only if stored vote counts are proven complete | One non-negative integer | One block | Always `vote_count >= value`; no comparator is displayed |
| Original language | Both | Searchable controlled picker | AND or OR only where provider/data can prove it | ISO language identity; not translated UI language |
| Production country | Both | Searchable controlled picker | AND or OR only where provider/data can prove it | Production/origin country; not release region |
| Runtime | Both | Short, Feature, Long, or Custom range | One block | Short `<60`, Feature `60-149`, Long `150+` minutes |
| Viewing status | Both | All, Watched, Unwatched, Watchlist | One block | Library is global SQL; Discover is local-state refinement with explicitly scoped totals |
| Movie list | Both | Controlled user-list picker | AND or OR after Gate 1 semantics proof | Membership in saved Cinema Paradiso lists |
| Resolution | Library only | Existing controlled options | OR | File resolution/upgrade status from authoritative media facts |
| Library source | Library only | Existing controlled options | OR | Stored rip/source fact |
| Availability | Discover only | All, Owned, Not owned | One block | Existing ownership map; never a TMDB catalogue claim |
| Sort | Both | Controlled sort picker | One block | Page-specific supported sort keys |

Notes:

- `Minimum votes` stays named Minimum votes precisely because its only meaning is “at least this many.” If comparators are later introduced, rename it to `Vote count`.
- Producer support is not assumed. Gate 1 must prove stored Library credit types and implement an exact TMDB job mapping before exposing it. If proof fails, the first release exposes only Actor, Director, Writer, and Any credit.
- `Any credit` means cast or crew, not a fuzzy name match.
- Multiple language or country values must not be exposed until the selected backend can preserve the advertised AND/OR meaning. A movie cannot normally have two original languages, so AND would intentionally return none; the UI should default these types to OR.
- Runtime presets are confirmed product defaults, with Custom available for precise ranges.

## 6. One normalized query model

The frontend must introduce one versioned, serializable model used by Advanced and compiled quick filters:

```json
{
  "version": 1,
  "scope": "library",
  "mode": "advanced",
  "groups": [
    {
      "type": "genre",
      "join": "or",
      "values": [
        { "id": "878", "label": "Science Fiction" },
        { "id": "53", "label": "Thriller" }
      ]
    },
    {
      "type": "person",
      "join": "and",
      "values": [
        { "id": "500", "label": "Tom Cruise", "role": "cast" },
        { "id": "31", "label": "Tom Hanks", "role": "cast" }
      ]
    },
    {
      "type": "year",
      "values": [{ "operator": "between", "from": 2000, "to": 2020 }]
    }
  ],
  "sort": { "key": "rating", "direction": "desc" }
}
```

Contract rules:

1. Different groups are implicitly `AND`.
2. Each repeatable type has exactly one group whose `join` is `and` or `or`.
3. Stable IDs and canonical codes are submitted; labels are presentation only.
4. The server validates the entire model and rejects unknown types, operators, roles, sort keys, IDs, excessive sizes, and impossible numeric ranges with HTTP 400.
5. Initial safety limits: 24 total values, 10 values in any repeatable group, 100 title characters, and a 200-result page-size ceiling. Gate 1 may lower these but may not remove bounds.
6. Query normalization produces a stable signature used for caching, stale-response rejection, history snapshots, selection scope, and tests.
7. The query model is state, not executable SQL or a provider URL. Each authoritative backend compiles it safely.

## 7. API and execution architecture

### 7.1 Transport

Use bounded POST search transports to avoid URL-length problems:

- `POST /api/library/search/advanced`
- `POST /api/tmdb/discover/advanced`

These routes are transport adapters only. They must delegate to the existing authoritative catalogue/TMDB services rather than contain parallel filtering logic.

During migration, simple quick filters compile into the normalized query but may continue using the old GET transport until parity tests pass. The compatibility adapter must then be removed in the same implementation series; it is not a permanent second engine.

### 7.2 Library planner

- Extend `CatalogStore.library_page` through a structured predicate compiler owned beside `_library_filter_sql`.
- Generate parameterized SQL only. Never interpolate values into SQL.
- Use correlated `EXISTS`, grouped relational joins, or set intersections to implement same-type AND/OR without duplicating rows.
- Count and page from the exact same predicate.
- Preserve deterministic tie-break sorting so paging never skips or repeats a movie.
- Extend `library_selection_paths` to consume the same normalized predicate. “Select all filtered” must select exactly the visible query universe.
- People and keywords resolve only through stored relational identities.
- Runtime and vote-count filters are exposed only after Gate 1 proves the canonical columns are populated and indexed sufficiently. Missing facts must have an explicit rule; they cannot be treated as zero by accident.
- Add only the indexes justified by query-plan and clone-database measurements. A schema migration requires a separate migration/parity proof inside the approved implementation scope.

### 7.3 Discover planner

Create one TMDB query-planning service in `app.py` or an existing TMDB service module, then make the existing Discover, title, and person routes delegate to it where appropriate.

Provider-native criteria map to TMDB Discover parameters:

- genres → `with_genres`
- keywords → `with_keywords`
- cast → `with_cast`
- generic people → `with_people`
- crew without a specific job claim → `with_crew`
- year/date → `primary_release_date.gte/lte`
- rating → `vote_average.gte/lte`
- minimum votes → `vote_count.gte`
- language → `with_original_language`
- country → `with_origin_country`
- runtime → `with_runtime.gte/lte`
- sort → `sort_by`

Comma/pipe serialization is permitted only for TMDB parameters whose official contract supports it. The planner owns that mapping; React components do not build provider URLs.

Role-aware people use the current person movie-credit behavior as the seed owner:

- Extract the credit normalization and job filtering from `/api/tmdb/person_movies` into a reusable service.
- Build stable movie-ID sets for each selected person/role.
- Apply same-type AND/OR as set intersection/union before paging.
- Do not issue movie-detail calls for every result.
- Do not claim Producer accuracy until its accepted job set is specified and tested.

Title strategy is a mandatory Gate 1 decision:

- Recommended first release: use `/search/movie` as the title owner, refine only the bounded provider page window, and label totals `TMDB title matches; filters applied to this page`. This preserves current behavior honestly.
- Deferred complete alternative: build an approved local TMDB index/cache with its own freshness, storage, and reconciliation contract. This is materially larger and is not authorized by this plan.
- Forbidden: silently crawling all TMDB search pages, fetching details N+1, or showing the provider's unfiltered total as an advanced filtered total.

### 7.4 Discover local-state criteria

Availability, viewing status, and Cinema Paradiso list membership are local refinements, not TMDB provider filters.

- They use existing ownership and `userLists` owners.
- They may refine only the currently loaded TMDB page unless Gate 1 approves a server-side identity-set strategy.
- The UI must label totals as page-scoped whenever a local criterion is active.
- They must never reduce a provider page while leaving an unqualified provider-global total on screen.

## 8. Quick-filter unification and removal of obsolete paths

The final architecture is hybrid in presentation but unified underneath:

- Simple mode: fast common controls, compiled into the normalized query model.
- Advanced mode: arbitrary supported combinations, using the same model.
- Library and Discover: shared criterion definitions and builder components, separate execution adapters.

Migration sequence:

1. Characterize every current quick-filter request and result fixture.
2. Add pure compilers from current simple state to the normalized query.
3. Prove old flat request and compiled request parity for every supported simple combination.
4. Make normal and Advanced execution use the same page-specific planner.
5. Remove the old ad hoc URL construction and duplicate local filtering that is no longer authoritative.
6. Keep a temporary adapter only while the parity gate is open; document its dependency and delete it before completion.

No implementation is complete while two code paths can interpret the same filter differently.

## 9. State, concurrency, and result behavior

1. Query changes reset page to 1 before execution.
2. The latest query signature and request sequence own the result. Older responses are ignored even if cancellation loses a race.
3. Picker autocomplete has its own abort/sequence guard and never overwrites movie results.
4. Empty Advanced query restores the page default rather than sending a meaningless provider request.
5. Search execution preserves the last successful cards while showing a restrained updating state, unless the scope changes enough that stale cards would be misleading.
6. Errors keep the completed blocks and expose Retry; they do not silently reset the request.
7. Back navigation restores the exact prior result snapshot only when its query signature matches.
8. Pagination reports totals from the actual execution owner and labels page-local totals honestly.
9. Expanded cards, card actions, watched/watchlist changes, source search, ownership refresh, and poster overrides continue through their existing owners.
10. Filtered bulk selection is recomputed through the authoritative query owner; changing criteria clears or reconciles selection according to the existing page contract.

## 10. Accessibility and desktop UI requirements

- Desktop only. Do not redesign or validate mobile/responsive layouts in this task.
- The builder is keyboard navigable: Tab reaches Add, blocks, connectors, and remove actions; Enter selects; Escape closes the active picker.
- Focus returns to `+ Add criterion` after a criterion is added or removed unless the user initiated another explicit target.
- Connectors expose complete accessible names, for example `Combine Genre values with OR`.
- Remove controls expose the value, for example `Remove genre Science Fiction`.
- Color is not the only signal that Advanced mode is active; label, structure, and focus behavior provide the distinction.
- The collapsed `+N more` summary remains screen-reader discoverable.
- No horizontal page overflow at the supported desktop verification width.

## 11. Implementation gates

### Gate 0 — Freeze and verify the baseline

Before feature work:

1. Record `git status`, HEAD, version, running process owner, and served bundle hash.
2. Preserve the existing uncommitted Discover Language/Country amendment exactly.
3. Finish or deliberately defer that amendment's activation with Dante's permission; do not build Advanced on an ambiguous old runtime.
4. Run the focused baseline suites and capture current screenshots at a fixed desktop viewport.
5. Record current API fixtures for Library and Discover defaults, quick filters, people, keywords, history, and paging.
6. Inspect a disposable SQLite backup for runtime/vote-count/producer data completeness and query plans.

Stop if the worktree changes unexpectedly, the runtime serves a different checkout, or baseline failures are unexplained.

### Gate 1 — Approve the semantic contract

Produce test fixtures and a short decision record for:

- same-type AND/OR and cross-type AND;
- Title Discover completeness wording;
- role definitions and whether Producer is released;
- missing runtime/rating/vote facts;
- list/viewing/availability page-scoped totals;
- exact limits and debounce timing;
- simple-to-Advanced import and mode restoration.

No UI or API implementation proceeds until Dante approves these product semantics.

### Gate 2 — Normalized model and shared criterion registry

- Add pure schema validation, normalization, stable signatures, labels, and simple-state compilers.
- Add one shared registry describing which criteria each page supports and how each value editor renders.
- Unit-test malformed, duplicate, reordered, conflicting, and maximum-size requests.
- No network or SQL is added in this gate.

### Gate 3 — Library SQL execution

- Extend the existing catalogue filter owner.
- Implement every approved shared and Library-only criterion.
- Make cards, totals, pages, and filtered selection use the same predicate.
- Prove zero TMDB calls.
- Measure broad and worst-case combinations on a temporary database clone.

### Gate 4 — Discover query planner

- Centralize provider parameter compilation.
- Add bounded Advanced transport and role-aware movie-ID set logic.
- Preserve provider pagination and request guards.
- Implement honest totals/labels for title and local-state refinements.
- Prove no N+1 detail fetching and no unbounded provider crawl.

### Gate 5 — Builder UI and workspace state

- Add Advanced to both existing selectors.
- Add shared builder canvas, criterion menu, value editors, blocks, connectors, overflow summary, reset, and Run search.
- Wire independent Library/Discover drafts, import/restore rules, history, page reset, and error/retry behavior.
- Keep current grids/cards/pagination untouched.

### Gate 6 — Migrate quick filters and delete duplication

- Compile current quick filters into the same normalized model.
- Prove request/result parity.
- Remove superseded filter URL assembly, client-side interpretations, and temporary adapters.
- Review ownership so a new developer can identify one query owner per page immediately.

### Gate 7 — Full regression and performance proof

Run the matrix in Section 12, production build, normally served bundle verification, and visible desktop rehearsal in both pages.

Required evidence includes:

- test commands and exact pass counts;
- representative API requests/responses;
- SQL query plans and timings for worst-case Library combinations;
- TMDB request-count evidence for Discover scenarios;
- screenshots for empty, one-line, wrapped, collapsed, picker, loading, empty-result, and error states;
- served asset/hash proof and zero unexpected browser console errors.

### Gate 8 — Commit/restart/release boundary

- Stop and present the evidence and complete diff to Dante.
- Obtain separate permission before staging/committing.
- Obtain permission before restarting the running Cinema Paradiso process.
- A push or release requires separate explicit authorization.

## 12. Zero-regression matrix

### 12.1 Defaults and simple modes

- Library opens Latest additions with collapsed quick filters.
- Discover opens Trending Week.
- Movies title search is unchanged with no advanced criteria.
- People and Keywords identities, paging, stale-response guards, selection, and relationship results remain reachable.
- Language and Country quick filters work in both applicable pages.
- Reset returns exact defaults.

### 12.2 Advanced combinations

- One genre.
- Genre A OR Genre B.
- Genre A AND Genre B.
- Two actors OR; two actors AND.
- Actor plus Director plus Writer across different criterion groups.
- Same person with two roles has defined, tested normalization.
- Two keyword identities OR; two keyword identities AND.
- Genre + person + year range + rating + minimum votes + language + country + runtime.
- Each numeric operator boundary, including equal bounds and invalid reversed ranges.
- Short at 59, Feature at 60 and 149, Long at 150.
- Watched, Unwatched, Watchlist, list membership, Owned, and Not owned with correctly scoped totals.
- Library Resolution and Source combinations.
- Sort stability across page boundaries.

### 12.3 Builder interaction

- First Advanced entry imports current simple criteria once.
- Re-entry does not duplicate blocks.
- Add, delete, connector change, role change, and Reset refresh correctly.
- Picker typing never refreshes movie results.
- Rapid edits show only the latest response.
- Three-line cap and `+N more` preserve access to every block.
- Mode changes restore independent simple and Advanced states.
- Library and Discover drafts do not leak into one another.
- Keyboard and accessible-name expectations pass.

### 12.4 Existing result surfaces

- Same card component, grid geometry, full-row page sizing, pagination above/below, expanded details, trailers, playback, source search, poster editing, list actions, and owned controls.
- Selection across Library pages and Discover pages remains identity-stable.
- Ownership cache invalidation after Library changes still updates Discover.
- Browser/workspace back restores criteria, page, results, total, expansion rule, and label.
- Empty, loading, provider error, invalid request, offline TMDB, and stale-response states do not crash or show mismatched results.

## 13. Test ownership and expected additions

Extend existing tests where they already own behavior:

- `tests/test_catalog_store.py`: SQL semantics, totals, paging, deterministic order, query bounds, zero duplicates.
- `tests/test_tmdb_details_transform.py`: Discover planner mappings, AND/OR serialization, roles, paging, limits, errors, and request counts.
- `tests/test_adult_metadata_settings.py`: title search safety and criteria compatibility.
- `tests/test_library_action_ux.py`: selectors, builder contract, compact desktop layout, defaults, and removal of duplicate filter owners.
- `tests/test_unified_movie_card_ui.py`: relationship/history/ownership/card preservation.
- `tests/test_discover_search_race_ui.py`: rapid advanced edits and stale response rejection.
- `tests/e2e/app-smoke.spec.js`: end-to-end Library and Discover rehearsals with mocked deterministic APIs.
- `tests/e2e/cross-page-selection.spec.js`: filtered selection and page transitions if this remains its authoritative coverage.

Add narrowly owned files if needed:

- `src/features/search/advancedSearchModel.js` with `tests/advancedSearchModel.test.mjs` for pure schema/compiler behavior.
- `src/features/search/AdvancedSearchBuilder.jsx` only after confirming no existing shared search component owns the responsibility.
- `tests/test_advanced_library_api.py` and `tests/test_advanced_discover_api.py` if extending existing API suites would obscure ownership.

Static source-string assertions alone are not sufficient for semantic search behavior.

## 14. Performance and safety budgets

- Library result requests remain page-bounded and return no more than the existing 200-card safety maximum.
- Identity autocomplete is debounced, abortable, and capped at 20 suggestions per page.
- Advanced request payloads obey the limits in Section 6.
- Library query count and latency are measured on the representative clone; any regression over the accepted baseline requires an index/query redesign, not a higher timeout.
- Discover records outbound TMDB request counts. A normal provider-native advanced page should require one bounded provider page window plus existing ownership batching, not calls proportional to card count.
- No raw SQL, provider parameter, arbitrary role, or arbitrary sort field is accepted from the client.
- Error messages do not expose keys, filesystem paths, SQL text, or provider credentials.

## 15. Rollback strategy

- Keep commits gate-scoped after implementation is separately approved.
- Roll back frontend builder/query-model wiring independently from backend planner changes.
- If a schema/index migration becomes necessary, use the existing migration owner, back up first, and prove forward and backward data integrity on a disposable copy.
- Do not preserve a disabled parallel Advanced engine as a permanent feature flag. If a gate fails, revert the incomplete gate and keep the single prior owner.
- The existing quick filters remain the user-visible fallback until Advanced and compiled-simple parity pass; after cutover, obsolete paths are removed.

## 16. Stop conditions

Stop and ask Dante before continuing if:

1. The Discover Title contract would require a local TMDB index or broad provider crawl.
2. Producer, runtime, or vote-count facts cannot meet the advertised semantics.
3. Exact same-type AND/OR requires a new catalogue schema not covered by the approved scope.
4. Local Discover criteria cannot produce honest totals without materially expanding the backend.
5. The runtime serves a different checkout or old bundle and restart permission is absent.
6. Existing uncommitted work overlaps the implementation in a way that cannot be preserved.
7. A mobile redesign, new drawer, card redesign, or unrelated search surface becomes necessary.
8. Tests reveal a current regression unrelated to Advanced Search.

## 17. Definition of complete

Advanced Search is complete only when:

- both pages expose the agreed builder and exact page-specific criteria;
- simple and Advanced presentation compile into one authoritative query model;
- Library executes entirely in the authoritative SQL catalogue;
- Discover uses one bounded TMDB planner with honest capability and total labels;
- misspelled people/keywords/controlled values cannot become active identities;
- AND/OR semantics match the visible connectors in API and UI tests;
- existing cards, grids, paging, history, selection, ownership, and actions pass regression;
- obsolete duplicate filter logic is removed;
- production build and normally served desktop UI are visibly verified;
- Dante has reviewed the evidence and separately approved any commit, restart, push, or release.

## 18. First implementation handoff

When implementation is approved, begin at Gate 0. Do not start by drawing the builder. First freeze current behavior, settle the five unresolved semantic items at Gate 1, and build executable contract fixtures. The UI is the final expression of that contract, not the place where search semantics should be invented.
