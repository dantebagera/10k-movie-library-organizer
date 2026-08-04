# Find Sources Progressive Filters: Zero-Reset Plan

- **Status:** Approved for planning and handoff only. Implementation has not started under this plan.
- **Last reviewed:** 2026-08-04
- **Repository:** `C:\Users\dante\Desktop\cinema paradiso`
- **Observed branch:** `master`
- **Target:** Cinema Paradiso desktop Find Sources popup opened from movie cards.
- **Primary frontend owner:** `TorrentModal` and `findTorrent()` in `src/App.jsx`.
- **Backend owner:** the existing progressive source-search job in `app.py`.

This plan is the implementation contract. It does not authorize implementation, Git staging, a commit, a process restart, a backend narrowing change, or work beyond the currently approved gate. The implementation task must recheck the worktree, active process, served bundle, and current behavior before changing code.

## 1. Goal

Allow the user to filter and sort progressively arriving Prowlarr results without interrupting the complete search or losing any selected control state.

The completed behavior must provide:

1. Selecting an indexer such as YTS immediately shows only currently available YTS results.
2. Prowlarr continues searching every configured indexer in the background.
3. Newly arriving non-YTS results remain hidden while YTS is selected.
4. Newly arriving YTS results appear automatically.
5. Title, resolution, indexer, and sorting selections survive every polling update, completion update, and same-search error update.
6. Those controls reset only when the user starts a genuinely new source search.
7. Filtering and sorting remain presentation-only and never alter, cancel, restart, or narrow the backend job.
8. The normally served production bundle demonstrates the behavior through the real movie-card path before completion is declared.

The product principle is:

> One complete backend search, one stable frontend search session, and presentation-only filters that never reset during that session.

## 2. Confirmed planning baseline

These facts were observed during planning and must be verified again at Gate 0.

### 2.1 Dirty-worktree protection

The checkout is already heavily dirty with unrelated work. In the Find Sources area specifically:

- `src/App.jsx` is modified.
- `tests/e2e/source-search-filter.spec.js` exists as an untracked file.
- The current `src/App.jsx` contains an attempted split between live-result synchronization and search-identity initialization.
- The attempted fix and test belong to the existing worktree and must be preserved, audited, and improved in place where correct.

Do not reset, overwrite, discard, stage, or commit unrelated changes. Before editing, capture a path-scoped diff for every planned file.

### 2.2 Original failure

The committed pre-fix `TorrentModal` used one effect keyed to the complete `state` object. Each polling response replaced that object, causing the effect to reset:

- the manual query;
- resolved movie identity;
- title filter;
- resolution filter;
- indexer filter;
- sorting mode.

That made a filter work briefly and then revert as the next indexer result arrived.

### 2.3 Current attempted correction

The working tree currently separates:

- live `variants`, loading, error, and progress synchronization; and
- filter/identity initialization based on movie fields.

This is directionally correct but uses movie fields as an indirect proxy for a new search. The final implementation should use one explicit search-session identity instead.

### 2.4 Real application evidence

Planning-time live verification used the normal application on `127.0.0.1:5000`:

- Find Sources was opened from an expanded Discover movie card.
- Four results arrived while seventeen indexers were still pending.
- Title `Spider`, resolution `1080p`, indexer `1337x`, and `Seeders most` were selected during the running job.
- More indexers and results arrived.
- All four controls survived until completion.
- Only 1337x rows remained visible.

The active server ran `python.exe app.py`. The JavaScript asset returned by port 5000 matched the on-disk normal `dist` asset by SHA-256.

This evidence proves that the attempted correction can work in the live bundle. It does not replace the stronger session contract and regression matrix required by this plan.

### 2.5 Existing focused test

`tests/e2e/source-search-filter.spec.js` currently covers:

- YTS selected during a running search;
- later non-YTS results remaining hidden;
- a later YTS result appearing automatically;
- selection surviving until completion.

The focused test passed against an isolated production build. It currently proves the indexer selection but does not fully prove title, resolution, sorting, genuine-new-search reset, or same-search error behavior.

### 2.6 Backend behavior

`app.py:_run_source_search_job` already:

- fetches every enabled Prowlarr indexer;
- starts indexer work concurrently;
- records pending, searching, completed, failed, and timed-out indexers;
- merges and deduplicates variants as indexers finish;
- completes only after the configured indexer work finishes or fails.

No backend or Prowlarr narrowing change is required for filter persistence.

## 3. Non-negotiable product contract

### 3.1 Search-session contract

- Every source-search invocation receives one explicit `searchSessionId`.
- The ID is created once when the search begins.
- The same ID is carried through the initial state, every progressive poll, completion, and error.
- A new card search creates a new ID even if it searches the same movie again.
- Submitting a new manual query inside the popup counts as a new source-search session.
- Polling data changes never create a new session.
- A selected movie identity being enriched or an error being reported never creates a new session.

`searchSessionId`, not the complete state object and not a collection of movie fields, is the authoritative reset boundary.

### 3.2 Filter contract

The popup owns four presentation controls:

| Control | Default | During polling | On a new search session |
| --- | --- | --- | --- |
| Title filter | empty | preserved | reset |
| Resolution | all | preserved | reset |
| Indexer | all | preserved | reset |
| Sorting | size largest | preserved | reset |

The filters apply only to the accumulated `variants` already returned to the frontend.

They must not be included in:

- `POST /api/explore/search/jobs`;
- `GET /api/explore/search/jobs/<search_id>`;
- a cancellation request;
- a replacement source job;
- a narrowed Prowlarr query.

### 3.3 Progressive-result contract

- Every poll replaces or synchronizes the authoritative accumulated variant snapshot.
- The visible result list is always recalculated from the newest variants plus the preserved controls.
- A nonmatching arrival changes the total received count but does not appear.
- A matching arrival appears automatically without changing the user's controls.
- Sorting is reapplied to the complete visible subset after every arrival.
- A selected indexer remains selected even when a particular snapshot has zero results for it.

### 3.4 Indexer-option contract

The indexer dropdown must be built from the union of:

- indexer names represented by returned variants;
- pending indexers;
- searching indexers;
- completed indexers;
- timed-out indexers;
- failed indexer names;
- the currently selected indexer, defensively retained.

This permits selecting YTS before YTS finishes and prevents the selected option from disappearing during polling.

The dropdown remains presentation-only. Selecting a pending indexer does not prioritize, cancel, or restart any backend indexer work.

### 3.5 Popup-state contract

The popup should preserve its existing desktop structure. This is not a general redesign.

It should contain:

1. Movie title and year.
2. A visible count in the form `N shown · M received`.
3. Existing manual search input and Search action.
4. Title, resolution, indexer, and sorting controls.
5. Search progress that explicitly says the complete indexer search is continuing.
6. Only the matching result rows.

Required running states:

- **Matching results exist:** show them plus `Still searching all configured indexers`.
- **Selected indexer has no results yet:** show `No <indexer> results yet. The complete search is still running.`
- **Nonmatching results arrive:** update `M received`; do not flash, remount, or show them.
- **Matching results arrive:** update `N shown` and insert them in the selected sort order.

Required terminal states:

- **Completed with matches:** keep the filters and show the matching rows.
- **Completed without matches:** show `No <selected filter> sources found.` without implying Prowlarr returned nothing globally.
- **Selected indexer timed out or failed:** preserve all controls and show the indexer-specific status.
- **Whole job error:** preserve all controls and the last visible matching results while reporting the error.

### 3.6 Count semantics

- `received` means the number of accumulated frontend variants from all indexers.
- `shown` means the number remaining after title, resolution, and indexer filtering.
- Neither count changes backend work.
- The count must not imply that hidden results were discarded.

## 4. Authoritative ownership

| Responsibility | Authoritative owner |
| --- | --- |
| Starting card-based source search | Existing `findTorrent()` in `src/App.jsx` |
| Preventing stale search updates | Existing `sourceSearchTokenRef` mechanism |
| Explicit frontend search-session identity | Existing source-search state, extended with `searchSessionId` |
| Progressive job execution and all-indexer fan-out | Existing `_run_source_search_job` in `app.py` |
| Progressive job snapshot | Existing `/api/explore/search/jobs/<search_id>` response |
| Filter and sorting control state | Existing `TorrentModal` |
| Visible filtered/sorted variants | Existing `TorrentModal` memoized projection |
| Find Sources popup markup | Existing `TorrentModal` |
| Regression scenario | Existing `tests/e2e/source-search-filter.spec.js` |

Do not create:

- a second Find Sources modal;
- route-specific copies of filter logic;
- backend filter state;
- a second source-search job manager;
- a new persistent filter store;
- a compatibility feature flag;
- a Prowlarr query path dedicated to a selected presentation filter.

## 5. Target frontend design

### 5.1 Parent search state

When `findTorrent()` starts:

1. Increment the existing source-search token.
2. Use that token, or an equally stable generated value, as `searchSessionId`.
3. Publish the initial modal state once with movie identity, the session ID, loading state, and empty variants.
4. Start the existing unrestricted backend job.

Every later update must preserve the stable fields and patch only live fields:

- `loading`;
- `error`;
- `variants`;
- `sourceSearch`.

Use a functional state update or an equally explicit single update helper so error paths cannot accidentally omit `tmdb_id`, `imdb_id`, `upgrade`, or `searchSessionId`.

Reject updates whose session ID no longer matches the active session.

### 5.2 Modal synchronization

`TorrentModal` should have two clearly separated responsibilities:

1. Synchronize live backend snapshot fields when those fields change.
2. Reset user-controlled presentation state only when `searchSessionId` changes.

The reset effect must not depend on:

- `state` as an object;
- `variants`;
- `loading`;
- `error`;
- `sourceSearch`;
- pending/searching/completed indexer arrays.

### 5.3 Manual search

Gate 0 must confirm every caller and purpose of the existing parent `searchTorrents()` and modal `runManualSearch()` paths before editing either.

The implementation must leave one understandable reset rule:

- submitting a manual query starts a new session and resets the four presentation controls once;
- responses belonging to that manual query do not reset them again.

If two implementations perform the same manual source search, consolidate into the existing authoritative owner rather than preserving duplicate request logic.

Do not broaden this task into a general source-search refactor unless Gate 0 proves consolidation is necessary to satisfy the contract. A material scope expansion requires Dante's approval.

### 5.4 Indexer options and selected-value stability

Create one memoized indexer-option projection inside `TorrentModal` from the job status arrays and variants.

Rules:

- normalize empty names out;
- deduplicate without changing displayed names;
- keep deterministic ordering;
- keep the current selection present;
- do not reset the selected value when the option list grows;
- do not send the selection to the backend.

### 5.5 Result projection

Keep one memoized projection in this order:

1. Start from all accumulated variants.
2. Apply normalized title substring filtering.
3. Apply exact resolution filtering.
4. Apply exact indexer filtering.
5. Sort a copy of the filtered array.

Do not mutate the backend snapshot array.

## 6. Behavior acceptance matrix

| Event | Backend search | Selected controls | Visible rows |
| --- | --- | --- | --- |
| Open Find Sources for movie A | Starts all indexers | Defaults | Available results |
| Select YTS while running | Continues unchanged | YTS retained | Only available YTS |
| Non-YTS result arrives | Continues unchanged | All retained | Non-YTS hidden |
| YTS result arrives | Continues unchanged | All retained | New YTS appears in sort order |
| Resolution option list grows | Continues unchanged | All retained | Existing resolution filter still applies |
| Indexer option list grows | Continues unchanged | All retained | Existing indexer filter still applies |
| Search completes | Stops naturally | All retained | Final matching subset |
| One indexer times out | Other work continues | All retained | Last matching subset plus status |
| Same job reports an error | No replacement job | All retained | Last matching subset plus error |
| Start movie B search | Starts a new all-indexer job | Reset once | Movie B results |
| Start movie A again after closing | Starts a new all-indexer job | Reset once | New movie A session results |
| Submit a new manual query | Starts the existing manual-search path | Reset once | Manual-query results |

## 7. Gated implementation plan

### Gate 0 - Reproduce, inventory, and protect the current state

Read-only until evidence is recorded.

1. Recheck cwd, branch, remote, application version, and dirty worktree.
2. Capture path-scoped diffs for `src/App.jsx`, the focused E2E test, and any proposed style file.
3. Confirm the real movie-card to Find Sources route.
4. Confirm every `setTorrentModal` update path, including success, poll, completion, error, close, manual search, and any non-card caller.
5. Confirm the active process serving port 5000.
6. Confirm the exact JavaScript asset returned by the normally served application and compare it with normal `dist`.
7. Attempt the progressive-filter scenario in the real application.
8. If the current attempted fix prevents reproduction, record that fact; do not roll it back merely to recreate the defect.
9. Confirm the backend request payload contains movie identity only and no presentation filters.
10. Confirm which indexer-status arrays are returned by the job response.

Gate 0 deliverable:

- current-state evidence;
- exact authoritative call graph;
- path-scoped diff inventory;
- confirmation or correction of this plan's assumptions.

Stop and ask for approval before Gate 1 if Gate 0 reveals a different owner, a backend contract change, or material overlap with unrelated user work.

### Gate 1 - Establish the explicit search-session boundary

1. Add `searchSessionId` to the existing modal search state.
2. Carry it through every card-search update and error path.
3. Preserve stable movie identity fields through functional live-state patches.
4. Make the modal's presentation reset depend only on the new session boundary.
5. Route manual search through the same clear session rule without adding a second filter owner.
6. Remove obsolete reset dependencies and any now-redundant code after coverage proves they are unused.

Gate 1 acceptance:

- polling cannot reset any presentation control;
- a new search resets all four controls exactly once;
- same-session completion and errors retain them;
- no backend code or request shape changed.

### Gate 2 - Complete pending-indexer and status UX

1. Build the indexer option union from variants and job status.
2. Keep the selected value stable while the union changes.
3. Introduce `shown · received` count semantics.
4. Distinguish running-with-zero-filtered-results from globally empty completion.
5. Reuse existing popup styles where possible.
6. If new CSS is required, keep it narrowly scoped to the existing popup.

Gate 2 acceptance:

- YTS can be selected while YTS is pending when the backend has exposed its name;
- zero matching results during a running job are described honestly;
- hidden results never flash into view;
- no unrelated modal or mobile work changes.

### Gate 3 - Expand automated zero-regression coverage

Extend `tests/e2e/source-search-filter.spec.js` rather than creating a competing scenario owner.

Required assertions:

1. Select a nondefault title filter, resolution, indexer, and sorting mode while the job is running.
2. Confirm all four exact values before the next poll.
3. Deliver a later nonmatching-indexer result and confirm it stays hidden.
4. Deliver a later wrong-resolution result from the selected indexer and confirm it stays hidden.
5. Deliver a later matching result and confirm it appears automatically.
6. Confirm the final visible order matches the selected sort.
7. Confirm all four controls survive job completion.
8. Confirm a same-session error update preserves all four controls and last matching rows.
9. Start a genuinely new movie search and confirm all four reset once.
10. Confirm a pending indexer can remain selected before it has results.
11. Assert that the backend start payload does not contain title-filter, resolution-filter, indexer-filter, or sorting fields.

Targeted backend regression must continue to prove:

- all enabled indexers are submitted independently;
- variants merge progressively;
- one indexer filter never narrows job execution.

Gate 3 acceptance:

- focused Playwright scenario passes;
- relevant source-search Python tests pass in an isolated `CP_TEST_ROOT`;
- no test uses the live catalogue, live download state, or live provider credentials.

### Gate 4 - Production build and normally served acceptance

1. Run the focused automated checks.
2. Run `npm.cmd run build` for the normal `dist` only after the implementation scope is approved.
3. Confirm the build completes without unrelated generated changes.
4. Confirm port 5000 serves the newly built asset.
5. Compare the served asset hash with the normal `dist` asset.
6. Reload the normally served application.
7. Open Find Sources from a real movie card.
8. Select all four controls while the search is still running.
9. Observe at least one later nonmatching arrival or indexer-option expansion.
10. Confirm the controls remain selected, hidden rows remain hidden, and matching rows update automatically when the provider produces them.
11. Confirm the complete search reaches its natural terminal state.
12. Record the visible result, active asset, process, and test evidence.

Gate 4 acceptance:

- the user-facing bundle is proven current;
- the real card path visibly preserves the selected controls;
- the backend still searches every configured indexer;
- no completion claim relies only on a mock, isolated server, or source inspection.

If the provider does not naturally produce a late matching result during the live window, report that limitation honestly. Use the deterministic E2E test for that timing edge, but still require the live application to prove filter persistence across real progressive updates.

## 8. Verification commands

The implementation task must first verify the commands against the current checkout.

### Focused Playwright

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\run_playwright_e2e.ps1 source-search-filter.spec.js
```

### Targeted Python source-search coverage

Use `.venv\Scripts\python.exe -m unittest` with `CP_TEST_MODE=1` and a unique, verified `CP_TEST_ROOT` under the operating-system temporary directory. Expected modules include the current source-search and Library action owners, such as:

```text
tests.test_yts_option2
tests.test_library_action_ux
```

Do not use an unisolated test root. Do not claim a broad suite passed if zero tests were discovered.

### Production build

```powershell
npm.cmd run build
```

### Live bundle proof

Record:

- listener and owning process for port 5000;
- script asset referenced by the served `index.html`;
- local asset SHA-256;
- served asset SHA-256;
- source and build timestamps only as secondary evidence.

Hash equality and a browser reload are required. Timestamps alone are not sufficient.

## 9. Expected file scope

Expected authoritative changes:

- `src/App.jsx`
- `tests/e2e/source-search-filter.spec.js`

Possible narrow change only if Gate 2 requires it:

- `src/styles.css`

Backend production changes are not expected. Backend test changes are allowed only if a missing no-narrowing assertion is required:

- existing source-search test module, preferably `tests/test_yts_option2.py`

Generated normal build output may change when Gate 4 runs. Do not hand-edit generated assets.

## 10. Risks and mitigations

### Risk: session ID is omitted from one update path

Effect: completion or error could still reset controls.

Mitigation: patch live fields functionally, preserve stable fields, enumerate every update path, and test the error transition.

### Risk: indexer options are derived only from current variants

Effect: the user cannot select a pending YTS indexer, or a selected option may disappear.

Mitigation: derive one union from job status, variants, and current selection.

### Risk: presentation filters leak into backend requests

Effect: the complete search becomes narrowed or restarted.

Mitigation: assert the exact job-start payload and inspect live requests.

### Risk: a generic empty state lies about hidden results

Effect: `No sources found` could appear while sources exist but do not match the selected filter.

Mitigation: distinguish running, filtered-empty, completed-empty, timed-out, and failed states.

### Risk: isolated tests pass while the user sees a stale bundle

Effect: the implementation is falsely declared complete.

Mitigation: rebuild normal `dist`, hash the served asset, reload the live app, and verify through the movie-card path.

### Risk: dirty-worktree overlap is overwritten

Effect: unrelated user work or the existing attempted fix is lost.

Mitigation: path-scoped diffs before every edit, minimal patches, no reset/checkout, and no broad formatting rewrite.

## 11. Explicit non-goals

- Do not redesign the Find Sources popup.
- Do not add mobile or responsive work.
- Do not change source ranking or deduplication.
- Do not change Prowlarr configuration or indexer priority.
- Do not cancel indexers based on a selected filter.
- Do not add server-side filter persistence.
- Do not change download, qBittorrent, upgrade, identity-resolution, or source-page actions unless Gate 0 proves a direct regression caused by this work.
- Do not introduce a new database, schema version, cache, service, route, feature flag, compatibility layer, or persistent preference.
- Do not stage, commit, push, restart the live process, or publish a release without separate explicit approval.

## 12. Stop conditions

Stop the current gate, summarize the evidence, and ask Dante before proceeding if:

1. The authoritative owner is not `findTorrent()` plus `TorrentModal`.
2. The required fix would narrow or modify backend Prowlarr execution.
3. A new route, database change, persistent store, or feature flag becomes necessary.
4. Existing dirty changes conflict materially with the approved patch.
5. Manual search consolidation materially expands the task.
6. Any selected control still resets during a same-session update.
7. A hidden nonmatching result flashes into view.
8. The normal served asset does not match the built asset.
9. Live behavior contradicts the deterministic regression test.
10. An unrelated user-visible behavior, test, or source-search action changes.

## 13. Completion definition

This plan is complete only when all of the following are true:

- one explicit search-session identity owns the reset boundary;
- all four presentation controls survive every same-session update;
- a genuinely new search resets them exactly once;
- indexer options remain stable and include pending/searching indexers exposed by the job;
- newly arriving nonmatching results stay hidden;
- newly arriving matching results appear automatically in the selected order;
- the backend continues searching every configured indexer;
- the focused E2E and targeted backend tests pass;
- the normal production build passes;
- port 5000 serves that exact build;
- the real movie-card path visibly demonstrates the behavior;
- no unrelated work was overwritten, staged, committed, or published.

Until the live, normally served acceptance is recorded, report the work as partial rather than complete.
