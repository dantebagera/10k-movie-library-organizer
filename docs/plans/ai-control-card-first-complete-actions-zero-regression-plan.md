# AI Control Card-First Complete Actions - Zero Regression Plan

## Objective

Make every AI Control command produce one complete, paged, editable card result set that follows the existing Discover card and bulk-selection rules.

The untouched default selection represents the exact interpreted command. If the user changes the selection, Confirm action applies the same interpreted action and parameters only to the selected cards.

Remove Cinema Paradiso total-result and qBittorrent submission ceilings. Keep provider requests, source searches, browser rendering, and submission work bounded internally without making later results unreachable.

## Accepted baseline

- Repository: `C:\Users\dante\Desktop\cinema paradiso`
- Baseline commit: `e5f93b5 Allow bulk source upgrades for owned movies`
- Baseline worktree: clean
- Catalogue schema: unchanged; this work requires no migration or backfill
- Live catalogue, movie roots, qBittorrent profile, caches, and settings must not be used by automated verification

## Authoritative ownership

- `services/ai_control.py`
  - Interprets the prompt.
  - Resolves the command candidate set.
  - Stores reviewed plans.
  - Validates an untouched all-result selection or a user-customized subset.
  - Orchestrates the confirmed action.
- `src/components/SharedMovieCards.jsx`
  - Remains the shared card presentation and behavior owner.
- `/api/library/check`
  - Remains the authoritative ownership attachment used by online cards.
- `/api/sources/review/preview`
  - Remains the shared source lookup, quality-variant, and upgrade-row owner.
- `_ai_control_submit_download` and the existing qBittorrent manager
  - Remain the submission, job journal, identity handoff, duplicate/conflict, and queue boundary.
- qBittorrent
  - Remains the owner of active-download limits, queue order, and download concurrency.

No parallel card component, ownership route, source selector, qBittorrent queue, catalogue owner, or compatibility layer may be added.

## Product contract

### Result presentation

- Every valid `find`, `create_list`, `download`, and `delete` plan displays as shared movie cards.
- Cards are paged; the complete result set is reachable without rendering the whole universe at once.
- Every command-matching result starts selected.
- Selection persists across pages.
- Select all results restores the exact interpreted command scope.
- Clear and per-card checkboxes produce a customized subset.
- The toolbar follows Discover:
  - master checkbox
  - selected count
  - Select all results
  - Clear
  - Add to list
  - Find sources
  - Confirm action
- Owned cards use the authoritative ownership route and show the same Owned, resolution, size, and upgrade-candidate presentation as Discover.

### Confirmation

- Confirm with the untouched selection executes the complete stored command.
- Confirm after selection changes executes the same action and parameters only for the selected stored-plan items.
- The server accepts only selection keys that belong to the stored plan.
- Empty or foreign selections fail closed.
- A plan remains one-shot and expires through the existing `PlanStore`.

### Find

- Find results are card-first and all selected.
- Confirmation produces a read-only completion receipt for the selected scope.

### Create list

- Confirmation creates the interpreted list using exactly the selected cards.

### Download

- Preview resolves candidates only; it does not silently source-search a capped prefix.
- Remove `max_download_searches` rather than increasing it.
- Remove the obsolete `max_matched_movies` setting and persisted configuration surface.
- Direct Confirm source-searches every selected movie and submits every ready result.
- Source searches use bounded worker concurrency, but no total movie cap.
- Submission to qBittorrent has no Cinema Paradiso total cap.
- Individual unavailable or failed movies are reported; they are never silently omitted.
- Selecting an owned movie sets `upgrade: true`; the existing library file remains intact.
- Find sources is optional detailed review:
  - it uses the shared source-review owner;
  - it does not submit;
  - reviewed source/quality choices are applied only when Confirm action is clicked.
- AI Control trusted-indexer policy remains separate from the normal trusted-release policy, but both use the same source-row implementation.

### Delete

- Delete targets are cards with exact local path and size retained in the plan/card data.
- Confirmation rechecks root containment, file existence, and observed size.
- Large customized selections require a confirmation phrase calculated from the selected count, not the original count.
- Recycle Bin behavior is preserved.

### Provider completeness and paging

- TMDB requests remain provider-paged.
- AI Control follows provider `total_pages`; it must not introduce a smaller Cinema Paradiso total cap.
- Duplicate provider identities are removed without changing provider order.
- UI page size remains a display concern, never a result ceiling.

## Implementation sequence

1. Remove obsolete AI Control total-cap configuration from the service, Flask configuration payload/save path, Settings, Help, and tests.
2. Add stable server-issued selection keys to every stored plan item.
3. Store find plans and add read-only find execution.
4. Change download preview to return all command candidates without source search.
5. Validate selected plan subsets inside `PlanStore.claim`.
6. Calculate delete confirmation requirements from the selected subset.
7. Factor one shared source-review row builder and use it from bulk review and confirmed AI downloads.
8. Add bounded concurrent source preparation with no total cap and per-movie result reporting.
9. Make Source Review support a review-only callback for AI Control.
10. Replace the AI Control table/toggle path with shared cards for all actions.
11. Hoist all-result selection across card pages and initialize every plan item as selected.
12. Add the Discover-style toolbar and send selection/review state to Confirm action.
13. Add focused service, API, UI, shared-source, and desktop regressions.
14. Run targeted and complete isolated Python, Node, build, and desktop Playwright suites.
15. Restart the normal app only after green verification; perform read-only runtime/render checks.

## Regression requirements

- Full result sets remain reachable and selected across card pages.
- Untouched confirmation executes all stored items.
- Customized confirmation executes only selected stored items.
- Unknown selection keys are rejected.
- Find confirmation is supported and read-only.
- Create-list confirmation uses the subset.
- Delete subset confirmation and stale-file checks remain safe.
- Download preview makes zero source calls.
- Confirmed download performs more than the old cap and submits every ready movie.
- Source failures do not block unrelated ready submissions.
- Reviewed quality choices survive until Confirm action.
- Owned confirmed downloads carry `upgrade: true`.
- Existing Library, Discover, Movie Lists, shared cards, source review, lists, deletion, qBittorrent, pagination, state, and navigation behavior remains green.

## Expected files

- `docs/plans/ai-control-card-first-complete-actions-zero-regression-plan.md`
- `services/ai_control.py`
- `app.py`
- `src/api/sourceReview.js`
- `src/components/SourceReviewDialog.jsx`
- `src/features/ai-control/AIControlWorkspace.jsx`
- `src/features/settings/SettingsWorkspace.jsx`
- `src/features/help/HelpWorkspace.jsx`
- `src/styles.css` only if the shared card toolbar needs narrowly scoped AI Control styling
- `tests/test_ai_control_service.py`
- `tests/test_ai_control_api.py`
- `tests/test_ai_control_ui.py`
- `tests/test_help_page_manual.py`
- `tests/e2e/app-smoke.spec.js`

Any additional file requires a demonstrated owner or regression need.

## Completion evidence

- Focused Python: 122 tests passed.
- Complete Python: 783 tests passed against a disposable `CP_TEST_ROOT`.
- Node: 63 tests passed.
- Production build: 1,643 modules transformed successfully.
- Desktop Playwright: 37 tests passed against a disposable server and data root.
- The desktop regression proves 21 results start selected, 20 render on page 1, page-2 selection changes persist, the authoritative Owned badge renders, and Confirm sends the exact remaining server keys.
- The normal app was restarted only after the isolated suites were green; `/api/library/status` returned HTTP 200.
- No schema migration, catalogue backfill, live catalogue benchmark, movie-root write, or qBittorrent submission was performed.
