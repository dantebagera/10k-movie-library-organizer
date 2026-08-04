# Post-plan startup performance correction

**Date:** 2026-08-02

**Scope:** Desktop initial paint and cold Library startup sequencing after the completed online-ingestion plan. No backend, SQL, schema, catalog, media, qBittorrent, dependency, process, or Git-state change was authorized or made.

## Confirmed before-state

- The running backend served the qualified source build, so the reported delay was not a stale-package problem.
- A read-only live browser diagnosis measured approximately 3.25 seconds for the initial Library navigation and observed the sidebar with an empty main region before cards appeared.
- Six read-only live `view=cards&page_size=40&sort=added` requests measured 443.2-488.1 ms and 112,342 bytes.
- The existing grid correction was active: after publication the 40 Library cards remained mounted. The remaining problem was startup sequencing and an unstyled pre-React interval.
- `App.jsx` launched followed-release loading/checking and streaming configuration at application mount. The followed-release owner may backfill TMDB dates, query release providers per followed movie, and persist the curation result even when the active route is Library.

## Owner-level correction

- `index.html` now contains the critical bootstrap paint styles. The loading mark and label no longer depend on the React entry bundle before becoming visible.
- `App.jsx` retains ownership of followed-release and streaming startup work.
- A direct cold Library start holds that nonessential work until `LibraryWorkspace` reports that its first authoritative SQL result has committed and React has painted it.
- After that first paint, the same existing followed-release and streaming owners run normally. Release notifications were not removed or restricted to a subset of routes.
- The existing reconciliation poll, catalog event subscriber, SQL Library query, canonical card source, and no-flicker background refresh were not replaced.

## Isolation proof

- The desktop runner created a unique GUID root below the Windows OS temporary directory.
- It set `CP_TEST_MODE=1`, `CP_TEST_ROOT=<unique temp child>`, and `CP_TEST_DIST_DIR=<that root>\dist` before importing or starting CP.
- `app.py` rejects test roots outside OS temp, and `services/frontend_routes.py` rejects a test distribution outside `CP_TEST_ROOT`.
- Fixture media, catalog, assets, logs, and port 5117 were isolated. No live media root or production catalog was reachable from the tests.
- One initial Node invocation was rejected as evidence after PowerShell failed to create its declared temp root. The command was corrected to create and verify the exact directory before the single valid run below.

## Regression results

| Check | Result |
|---|---|
| Production Vite build | PASS - 1,653 modules; entry `index-DvoPZw2l.js` |
| `git diff --check` on changed frontend/evidence owners | PASS - no patch errors |
| Enumerated Node suite | PASS - 76/76 using verified unique `CP_TEST_ROOT` |
| Focused bootstrap and cold-Library tests | PASS - 2/2 |
| Full desktop Playwright suite | PASS - 51/51 in 57.2 seconds |
| Cold Library request contract | PASS - one `page_size=39` SQL card request; no Home request |
| Startup ordering contract | PASS - no followed-release or streaming request before the first Library grid commit; all three existing requests run afterward |
| Bootstrap paint contract | PASS - full-viewport gold loading surface visible while the frontend entry bundle is deliberately held |
| No-flicker publication contract | PASS - existing grid node, selection, expansion, focus, and cards preserved; no Library spinner during background commit |

The final isolated route smoke rendered `/library` in 494 ms. The focused cold-Library ordering test completed in 840 ms. These are isolated regression timings, not a substitute for a separately approved live-library acceptance measurement.

## Deployment/process proof

- The running CP listener remained PID 49436 with command `python.exe app.py`; it was not restarted.
- qBittorrent processes were observed only; no qBittorrent process or setting was changed.
- A read-only request to `/` confirmed the running backend now serves entry `index-DvoPZw2l.js` and the inline bootstrap animation.
- An already-open browser tab keeps its loaded JavaScript. A fresh navigation or reopening CP is required to load the rebuilt bundle.

## Remaining risk

- The production Library API still measured roughly 0.44-0.49 seconds before this frontend correction. This change removes unrelated provider/curation work from its critical startup path but does not alter SQL.
- No new live-library acceptance was run because that remains separately approval-gated. Dante's next fresh desktop launch is therefore the first production-perception check for this correction.
- If the remaining delay is still unacceptable after that fresh launch, the next step is read-only profiling of the production-sized SQL card projection. A schema redesign is not currently justified.

## Git boundary

Nothing was staged, committed, pushed, tagged, released, reset, moved, or deleted. All pre-existing dirty and untracked work remains preserved.
