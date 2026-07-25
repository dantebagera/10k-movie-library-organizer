# Writer and Keyword Search - Stage D Evidence

Date: 2026-07-25
Starting commit: `8178c03a8e18f5887513dcf02f1991693fef1974`

## Scope

Stage D implements only the shared desktop search UI:

- expose Writer as a third role action on the shared person card;
- expose Keywords as a third Library and Discover search mode;
- render Library and Discover keyword identities through one shared keyword card;
- connect Library keyword selection to the existing SQL card query;
- connect Discover keyword selection to the existing TMDB discovery context;
- preserve existing Movies, actor, director, ownership, paging, filter, and navigation behavior.

No schema, migration, backfill, backend route, canonical projection, or provider-evidence code changed.

## Authority and behavior

- `PersonSearchCard.jsx` remains the shared person-result owner. Actor, Director, and Writer actions use the existing filmography callbacks with explicit role values.
- `KeywordSearchCard.jsx` is the shared keyword-result presentation. It does not fetch data or own search logic.
- Library keyword suggestions call only `/api/library?view=keywords`, then select the stable stored keyword identity.
- Library owned-movie results continue through `/api/library?view=cards` with `keyword_id` or normalized-name fallback. The existing SQL card, paging, filter, selection, and detail paths remain authoritative.
- Discover keyword suggestions call `/api/tmdb/keywords/search`, then pass the TMDB keyword ID through the existing `/api/tmdb/discover` relationship context.
- Discover ownership still attaches through the existing `/api/library/check` path and the shared Discover movie cards.
- Existing Movies mode parameters were not changed.
- Existing actor and director controls remain present and retain their existing callbacks.
- Desktop-only styles were added. No mobile or responsive redesign was introduced.

## UI contracts and state safety

Automated desktop evidence proves:

- a stored Library writer exposes `Written films` and sends `role=writer` with the correct person identity;
- a Discover person exposes Actor, Director, and Writer actions and sends `role=writer`;
- Library keyword suggestions show owned-movie counts and selected TMDB keyword identity;
- selecting a Library keyword returns to Movies mode, displays the existing movie cards, and shows a removable keyword filter chip;
- Discover keyword selection preserves the TMDB ID, renders existing Discover cards, and attaches an owned badge through the existing ownership check;
- Discover Back restores Keywords mode and the previous keyword entity result;
- Library and Discover show separate, authority-specific empty and error states;
- both keyword modes reject older in-flight responses after a newer query wins;
- request invalidation clears loading state;
- long keyword labels wrap inside the desktop keyword card;
- three person-role actions wrap inside the existing desktop person card instead of overflowing.

## Isolation and live-data boundary

All Python application tests used `CP_TEST_MODE=1` and temporary `CP_TEST_ROOT` values.

Recorded isolated paths:

- initial failing UI contract: `C:\Users\dante\AppData\Local\Temp\cp-stage-d-red`
- focused green UI contract: `C:\Users\dante\AppData\Local\Temp\cp-stage-d-focused-green`
- targeted catalogue/search suite: `C:\Users\dante\AppData\Local\Temp\cp-stage-d-targeted-20260725`
- full Python suite: `C:\Users\dante\AppData\Local\Temp\cp-stage-d-full-python-20260725`
- focused desktop UI: `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-playwright-e236e66259d64ab7811e77671f064a2e`
- final desktop suite: `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-playwright-bc0cc38721504699b1124a6f1a31d2fd`

The live catalogue was opened only through a SQLite read-only URI with `PRAGMA query_only=ON`:

- path: `C:\Users\dante\AppData\Local\Cinema Paradiso\Catalog\catalog-read-cb30c1d963c88463.sqlite`
- schema version: 7
- `keywords`/`movie_keywords` tables present: none
- database modification time before and after the check: unchanged

No live migration, schema initialization, backfill, audit, repair, scan, provider refresh, or application restart occurred.

## Performance and bounded work

Stage D changed frontend presentation and request coordination only; the Stage B indexed SQL queries and Stage C remote routes were not modified.

- Library keyword typing uses a 150 ms debounce.
- Each settled Library keyword query issues one bounded SQL suggestion request with `limit=50`.
- Selecting a Library keyword issues one existing paged card request.
- Discover keyword search issues one TMDB keyword request; selecting a result issues one existing Discover request.
- Stale responses are ignored rather than triggering another request.
- No per-keyword or per-movie request loop was introduced.

Production bundle measurements compared with Stage C:

| Asset | Stage C | Stage D | Difference |
| --- | ---: | ---: | ---: |
| Main CSS gzip | 26.30 kB | 26.41 kB | +0.11 kB |
| Library workspace gzip | 11.11 kB | 11.74 kB | +0.63 kB |
| Discover workspace gzip | 11.45 kB | 11.70 kB | +0.25 kB |
| Shared keyword-card gzip | none | 0.75 kB | +0.75 kB |
| Icon bundle gzip | 5.55 kB | 5.80 kB | +0.25 kB |

The final production build completed in 2.05 seconds.

## Automated verification

| Verification | Result |
| --- | --- |
| Focused source contract | 3 passed |
| Focused Writer/Keyword desktop workflows | 7 passed |
| Targeted catalogue/search Python suite | 77 passed |
| Full Python suite | 749 passed in 84.880 s |
| Frontend Node suite | 63 passed |
| Production Vite build | 1,643 modules; passed in 2.05 s |
| Full desktop Playwright suite | 31 passed in 24.8 s |

The full Python suite emitted the same two known non-fatal `ResourceWarning` messages recorded in Stages A through C: one temporary file and `dist/index.html`.

## Resolved verification interruptions

- The new source contract initially failed because the shared keyword card and visible controls did not exist. This was the expected pre-implementation failure.
- The first Discover keyword ownership assertion matched both the ownership filter option and the movie badge. The test was narrowed to the existing `.unified-owned-badge`; application ownership behavior was already correct.
- Library keyword request invalidation was strengthened so a previous response cannot appear during the debounce window.
- The existing person-action row was allowed to wrap so three explicit roles remain usable without redesigning the card.

## Commands

- `.venv\Scripts\python.exe -m unittest` focused UI contracts
- `.venv\Scripts\python.exe -m unittest` targeted catalogue/search modules
- `.venv\Scripts\python.exe -m unittest discover -s tests`
- `node --test tests/*.test.mjs`
- `npm.cmd run build`
- `tools\run_playwright_e2e.ps1` with focused grep selections
- `tools\run_playwright_e2e.ps1`
- read-only SQLite URI schema check with `PRAGMA query_only=ON`

## Stage boundary

Stage D is green and separately reviewable. Stage E compatibility retirement, documentation, and final evidence must not begin until Dante explicitly approves it.
