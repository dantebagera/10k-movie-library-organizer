# New Task Prompt: Implement Provider-Local IPTV Movies TMDB Enrichment

Use the following prompt in a new Codex task whose workspace is:

`C:\Users\dante\Desktop\cinema paradiso`

After sending this prompt, Dante will send the separate IPTV TMDB credential in that new task. Do not include the credential in this prompt.

---

Your name is lam3y. My name is Dante.

Implement the approved provider-local IPTV Movies TMDB enrichment architecture end to end under the zero-tolerance non-IPTV regression contract below.

Read this entire plan first and treat it as authoritative:

`C:\Users\dante\Desktop\cinema paradiso\docs\plans\iptv-movies-tmdb-enrichment-zero-regression-plan.md`

This prompt explicitly approves:

- implementation inside the plan's IPTV-owned allowed-file boundary;
- new provider-local `movies.sqlite` databases;
- isolated IPTV TMDB settings and client code;
- automated tests using fake providers and fake TMDB responses;
- production frontend build;
- disposable desktop browser verification;
- storing and validating the IPTV-only TMDB credential after I provide it in this task;
- a bounded, reversible IPTV-only pilot after every protected regression gate passes.

This prompt does **not** approve:

- editing any protected non-IPTV file or owner;
- modifying, migrating, backfilling, reprojecting, repairing, or writing CP's main SQL catalog;
- modifying CP's existing TMDB key, cache, client, routes, or metadata behavior;
- restarting my existing live CP process;
- automatically running a complete live provider enrichment;
- committing, staging, pushing, releasing, publishing, resetting, checking out, or changing Git configuration.

Stop only for a genuine protected-boundary conflict, non-IPTV regression, secret-exposure risk, unexpected live-data mismatch, destructive action outside provider-local IPTV state, or a product choice not settled by the plan.

## Absolute Priority

IPTV Movies may have incomplete matches, provider failures, TMDB failures, or IPTV-only defects during development. Stable non-IPTV Cinema Paradiso has zero regression tolerance.

If implementation requires changing a protected CP owner, stop and report the evidence. Do not refactor stable CP code to make IPTV cleaner. Do not weaken existing tests. Do not silently expand scope.

## Final Product Contract

- Movies only. Do not change or enrich Series, episodes, or Live TV.
- Every provider remains a separate movie library.
- There is no All Providers view.
- Lionz and EgySat metadata, matches, sources, lists, history, and databases never mix.
- One card groups several sources only when those sources belong to the selected provider and share an accepted TMDB identity.
- Provider playlists/categories remain visible, unchanged, in a dedicated `Provider playlist` dropdown.
- `My list` is a separate dropdown.
- Filters never create lists.
- Lists are created only by explicit user action and remain provider-local.
- Unmatched movies remain visible and playable with provider data.
- Every unmatched card offers `Match metadata`.
- Manual matches are locked, correctable, and removable.
- Raw provider playback identity is retained after matching.
- The main CP SQL catalog is never written.
- The existing CP TMDB credential is never read as a fallback or modified.

## IPTV TMDB Credential Handling

I will provide the new IPTV-only TMDB credential in this conversation after this prompt.

When I provide it:

1. Do not repeat, quote, summarize, partially reveal, or display it.
2. Do not include it in commentary or the final response.
3. Do not place it in tracked files, documentation, tests, fixtures, screenshots, Git diffs, logs, memory, URLs printed to output, or process command-line arguments.
4. Do not alter CP's existing `tmdb_key`.
5. Store it only through the new IPTV metadata-settings owner under ignored `data/iptv/` state.
6. Public APIs may return only `tmdb_configured: true|false`.
7. Password-style fields load blank and never return a key hint.
8. Redact exact credential values plus common `api_key` and `Authorization` forms from errors.
9. Validate with one bounded IPTV-owned request and report only success/failure.
10. Never fall back to CP's TMDB credential if the IPTV credential is missing, invalid, or rate-limited.

Avoid interpolating the credential into shell command lines. Use a local secret-input path that suppresses request bodies and output. Delete any temporary secret-bearing input immediately after successful atomic storage, and verify that no tracked or evidence file contains it.

## Protected File Denylist

Do not edit:

```text
app.py
config.json
services/catalog_store.py
services/catalog_repository.py
services/canonical_catalog.py
services/curation_store.py
services/library_*.py
services/media_*.py
services/frontend_routes.py
src/App.jsx
src/styles.css
src/components/SharedMovieCards.jsx
src/components/movie-card/MovieCard.jsx
src/features/library/**
src/features/discover/**
src/features/home/**
src/features/movie-lists/**
src/features/settings/SettingsWorkspace.jsx
native/**
```

This includes formatting-only changes. If any protected file appears necessary, stop before editing it.

Expected allowed implementation area:

```text
services/iptv_provider_manager.py
services/iptv_service.py
services/iptv_store.py                 only with a demonstrated IPTV-owned need
services/iptv_routes.py
services/iptv_xtream.py                only with a demonstrated movie-detail need
services/iptv_movie_store.py            new
services/iptv_movie_service.py          new
services/iptv_tmdb.py                   new
services/iptv_metadata_settings.py      new
services/iptv_enrichment_worker.py      new
src/api/iptv.js
src/features/iptv/**
tests/test_iptv_*.py
tests/iptv_*.test.mjs
tests/seed_iptv_e2e.py
tests/e2e/app-smoke.spec.js             IPTV-contained additions only
docs/plans/iptv-movies-tmdb-enrichment-*.md
```

At every stage, run `git status --short`, `git diff --name-only`, and `git diff --check`. Stop if the diff escapes the allowed boundary. Preserve all unrelated user changes.

## Required Data Ownership

Keep the existing raw provider layout and add one database per provider:

```text
data/iptv/
  metadata-settings.json
  providers.json
  providers/<provider-id>/
    provider.json
    iptv.sqlite
    movies.sqlite
    images/
    movie-images/
    playback/
```

- `iptv.sqlite` remains raw provider availability/playback/list/history ownership.
- `movies.sqlite` owns only that provider's movie sources, match states, TMDB snapshots, filter relationships, movie-level list membership, and enrichment state.
- Never create a global enriched IPTV movie database.
- Never place rows from two providers in the same `movies.sqlite`.
- The same TMDB ID may exist independently in several provider databases.
- Artwork is lazy and outside SQL.
- Provider deletion remains path-confined.

## Required Movie Behavior

Identity order:

1. Preserve every raw provider movie source.
2. Fetch provider `get_vod_info` and prefer a provider-supplied TMDB ID.
3. Validate that ID against TMDB facts.
4. If no usable ID exists, search by cleaned title/year with strict deterministic scoring.
5. Auto-accept only high-confidence results without a credible rival.
6. Keep uncertain entries ambiguous or unmatched.
7. Never improve match percentage by loosening correctness.

Required states:

```text
unprocessed
provider-id-pending
search-pending
matched-auto
matched-manual
ambiguous
unmatched
error-retryable
error-terminal
```

Matched display:

- full provider-local cached TMDB title, plot, poster/backdrop URLs, genres, rating/votes, release date, runtime, language, country, certification, directors, writers, cast, collection, and keywords when supplied;
- no live TMDB request when expanding a card;
- one card per accepted TMDB ID inside the provider;
- all same-provider member sources visible through a source chooser.

Unmatched display:

- provider title, poster, year, rating, playlist, plot, cast text, director text, genre text, duration, extension, and source facts when available;
- Play, Favorite, Add to list, and Match metadata;
- honest status badge;
- no disappearance and no silent CP metadata fallback.

## Provider Playlists, Filters, and Lists

The Movies toolbar must keep three concerns separate:

```text
[Provider playlist: All provider playlists]
[My list: All movies]
[Search and CP-style filters]
```

- Provider playlist names/IDs remain exact provider data.
- Filters are server-side, SQL-paged, and scoped to the selected provider.
- Initial filters: search, provider playlist, My list, genre, language, country, year range, minimum rating, metadata status, provider-claimed quality, watched state where supported, and deterministic sort.
- TMDB-dependent filters exclude unmatched cards because those facts are unknown.
- Metadata status exposes unmatched, ambiguous, and failed rows.
- Every valid result must be reachable through bounded pages; do not render or fetch the entire provider catalog at once.
- Existing provider-local list definitions remain authoritative.
- Movie-level membership is one movie per list, independent of source count.
- Matching or merging sources preserves and deduplicates list membership.
- Existing movie Favorites and history must be preserved through copied-provider rehearsal before live use.
- Live TV and Series list/history behavior must not change.

## Worker Isolation

Do not perform a 60,000-title enrichment inside Flask or an uncontrolled thread.

- Use an IPTV-owned subprocess or equivalently isolated process.
- Never start it on import, startup, provider selection, ordinary sync, or opening IPTV.
- Start only by explicit IPTV action.
- Keep the credential out of arguments.
- Bound requests, memory, transaction size, retries, and backoff.
- Persist provider-local progress.
- Support pause, resume, cancel, crash recovery, and restart.
- A worker failure must leave raw IPTV Movies usable and must not affect Flask or non-IPTV CP.
- Do not download the complete poster library during enrichment.

## Main CP Read Boundary

Core IPTV Movies must work without reading CP's main catalog.

If you implement an `Owned locally` overlay:

- put the adapter in a new IPTV-owned file;
- open the existing catalog with `mode=ro` and `PRAGMA query_only=ON`;
- run batched TMDB-ID `SELECT` only;
- never instantiate `CatalogRepository` or initialize a catalog;
- never reconcile, hydrate, export, migrate, update generations, or recover errors;
- return no ownership overlay if the read cannot be proven non-writing;
- prove the main logical catalog baseline is unchanged before and after.

Omit the badge rather than weaken this boundary.

## Mandatory Implementation Order

1. Read the authoritative plan completely.
2. Inspect current Git state and all relevant IPTV diffs.
3. Capture protected tracked-file hashes.
4. Capture a read-only logical baseline of the main CP catalog and `config.json` hash without displaying secrets.
5. Capture provider-local raw database/list/history facts.
6. Build disposable fake-provider and fake-TMDB fixtures.
7. Implement isolated IPTV metadata settings and provider-local movie-store schema.
8. Implement raw movie-source projection with no TMDB dependency.
9. Implement isolated IPTV TMDB client and strict match engine.
10. Implement source grouping, manual correction, and provider-local relational details.
11. Implement isolated worker and provider-scoped APIs.
12. Implement IPTV Movies UI, filters, provider playlist dropdown, My list dropdown, unmatched fallback, matching UI, and source chooser.
13. Rehearse existing provider movie Favorite/history continuity on copied roots.
14. Run the complete protected regression gates.
15. Receive/store/validate the IPTV credential if not already supplied.
16. Run only the bounded, reversible IPTV pilot allowed by the plan.
17. Stop and report before restarting the existing CP process or starting a full live provider enrichment.

## Mandatory Tests and Proof

At minimum, add tests for:

- lazy movie-store creation;
- no movie-store access from Live TV or Series;
- provider path confinement;
- independent same-TMDB-ID rows in two providers;
- no cross-provider source grouping;
- raw fallback without TMDB;
- provider-detail TMDB-ID validation;
- strict automatic matching and credible-rival rejection;
- manual lock/correction/reset;
- unmatched Play/Favorite/Add to list;
- one card with several same-provider sources;
- provider playlist filtering;
- My list filtering;
- matched/unmatched filter semantics;
- deterministic paging and sorting;
- list-membership preservation on match/merge/source loss;
- existing movie Favorites/history rehearsal;
- unchanged Live TV/Series state;
- redacted settings and errors;
- missing, invalid, 401, 429, timeout, and 5xx TMDB behavior;
- worker start/pause/resume/cancel/crash/recovery;
- import/startup creates no movie database and starts no worker;
- main CP read adapter cannot write, if included;
- main CP logical catalog and config hash unchanged.

Run:

```text
focused IPTV Python tests
focused IPTV Node tests
complete Python unittest discovery with CP_TEST_MODE=1 and a unique verified OS-temp CP_TEST_ROOT
all frontend Node tests
npm.cmd run build
npm.cmd run test:e2e
```

Use disposable data roots, fake providers, fake TMDB responses, a private server/port, and the normally served production bundle. Never run broad tests against live CP catalog data, movie roots, qBittorrent state, or provider credentials.

Explicitly verify unchanged non-IPTV behavior for:

- Home;
- Library File View and Movie View;
- Discover;
- Movie Lists;
- AI Control and Ask AI;
- Downloads;
- Maintenance/Cleanup/metadata correction;
- local/native playback and Continue Watching;
- non-IPTV Settings;
- shared cards and global layout.

Any non-IPTV failure blocks completion even when every IPTV test passes.

## Live Safety Gates

- Do not modify existing `iptv.sqlite` until copied-provider list/history rehearsal passes.
- Back up only provider-local IPTV state before a bounded live pilot.
- Never write or migrate main CP SQL.
- Never start a full provider scan automatically.
- Do not restart the existing CP process without asking Dante at the single live-activation gate.
- Do not commit, stage, push, tag, release, or publish.

## Required Completion Report

Lead with any unresolved protected-boundary or correctness issue.

Report:

- exact changed files and their IPTV ownership;
- proof that no protected file changed;
- main CP SQL schema/integrity/logical digest/generations/counts before and after;
- `config.json` hash before and after;
- confirmation that CP's existing TMDB credential was untouched;
- IPTV credential configuration and validation as boolean status only;
- provider-local database isolation evidence;
- same-TMDB-ID cross-provider isolation evidence;
- existing movie Favorites/history rehearsal results;
- focused and complete test results;
- production build and disposable served-browser results;
- protected non-IPTV workflow results;
- bounded pilot match accuracy and failure behavior;
- remaining IPTV-only risks;
- whether live restart/full enrichment still awaits approval.

Do not claim completion if any protected CP behavior changed, the main catalog changed, a secret appeared, providers mixed, unmatched movies disappeared, or a complete scan started without explicit authorization.

---
