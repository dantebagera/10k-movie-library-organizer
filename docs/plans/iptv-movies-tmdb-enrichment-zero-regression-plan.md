# IPTV Movies TMDB Enrichment: Zero-Tolerance Non-IPTV Regression Plan

- **Status:** Consolidated action plan. Plan edits are approved; implementation, live migration, provider repair, enrichment, restart, Git, and release actions remain separately approval-gated.
- **Saved:** 2026-08-13
- **Workspace:** `C:\Users\dante\Desktop\cinema paradiso`
- **Scope:** Desktop IPTV Movies only. Live TV and Series/TV Shows remain unchanged.
- **Primary safety rule:** IPTV defects are tolerable during development; any regression, mutation, or behavioral drift in stable non-IPTV Cinema Paradiso is not.

## 1. Objective

For each configured Xtream provider, build a separate CP-style IPTV movie library that:

1. Preserves the provider as the availability and playback authority.
2. Stores enriched movie identity and TMDB metadata in a new database inside that provider's root.
3. Displays one card per accepted TMDB movie, with multiple playable sources from that provider attached to the card.
4. Never combines Lionz, EgySat, or any future provider's catalog, metadata, matches, lists, history, or sources.
5. Keeps the provider's original movie playlists/categories visible in a dedicated dropdown.
6. Adds CP-style filtering without automatically creating playlists or lists.
7. Lets the user create provider-local lists explicitly.
8. Keeps unmatched movies visible and playable with provider metadata plus an explicit `Match metadata` action.
9. Uses a separate IPTV-only TMDB credential with no fallback to CP's existing TMDB credential.
10. Does not write to, migrate, backfill, reproject, or otherwise mutate CP's main catalog, main metadata cache, non-IPTV APIs, or non-IPTV frontend state.

## 2. User Decisions That Are Final

These decisions are not open for reinterpretation during implementation:

- Movies only. Do not enrich Series, episodes, or Live TV.
- Providers remain strictly isolated.
- There is no `All Providers` movie view.
- One card may contain several sources only when those sources belong to the currently selected provider.
- Provider playlists remain available exactly as provider-origin navigation in their own dropdown.
- Provider playlists are not converted into CP lists.
- Filters are temporary query state. They do not create lists.
- Lists are created only by an explicit user action.
- Unmatched movies do not disappear and do not become empty placeholders.
- Manual TMDB correction is provider-local and must be lockable and reversible.
- IPTV may read narrowly scoped CP ownership facts if required, but it may never write to CP's frontend state, backend domains, or SQL.
- Stable non-IPTV CP behavior has zero regression tolerance.
- The IPTV TMDB credential is separate from the existing CP TMDB credential.
- The IPTV TMDB credential is already stored through IPTV-only ignored state. Never request, display, infer, copy, log, or expose it.
- Provider catalog synchronization, provider-local Movies projection, and optional TMDB enrichment are three separate stages with separate state and progress.
- Provider-local projection may start automatically after a committed provider sync because it performs no TMDB request and is required to make raw Movies browseable. It must never block a Movies request or present a false empty finished state.
- First-time TMDB enrichment requires one clear consent action for the selected provider. A successful credential test alone does not start enrichment.
- After consent, enrichment continues through the provider-local backlog without another click every 100 sources. The 100-source limit remains diagnostic/pilot-only.
- The initial restart policy is visible confirmation: after a normal CP restart, durable progress is preserved and the user is offered `Continue metadata improvement`; enrichment does not silently auto-resume.
- The initial conservative global scheduler permits one active IPTV TMDB worker. Another provider may wait visibly for capacity, but its data, queue, identities, and progress remain independent.
- Existing schema-version-1 accepted matches, manual locks, TMDB snapshots, lists, favorites, history, and completed work are migration input and must not be discarded or blanket-rematched.
- Arabic-original accepted movies default to TMDB's `ar-SA` display metadata with a transient English switch. Localization is presentation-only and never affects match acceptance.
- Arabic-original matched cards link primarily to TMDB. Other cards use IMDb when a valid IMDb ID exists and TMDB as the guaranteed fallback.
- Add a provider-scoped IPTV `Metadata` tab. It is an observability, control, and review surface, not the engine's ignition key and not a CP Maintenance integration.

## 3. Original Baseline and Confirmed Trial Findings

Gate 0 must re-measure these facts because live provider data can change.

### 3.1 Repository state at original planning time and current baseline rule

- Branch: `master`.
- Worktree at the original planning snapshot: clean.
- Remote: `origin` points to the Cinema Paradiso repository.
- No application, configuration, SQL, runtime, Git, or credential mutation was performed while preparing this plan.

The current worktree is intentionally dirty with unrelated Dante-owned changes. Every implementation stage must capture a fresh read-only baseline of protected tracked-file hashes, current dirty paths, configuration hashes, and main-catalog facts. Success means the approved IPTV work adds no protected-file or main-CP delta relative to that captured baseline. Never reset, overwrite, stage, or conceal unrelated changes merely to recreate the historical clean state.

### 3.2 Existing provider isolation

The implemented provider manager already gives every provider an isolated root:

```text
data/iptv/
  providers.json
  providers/<provider-id>/
    provider.json
    iptv.sqlite
    images/
    playback/
```

Existing authoritative owners:

| Responsibility | Current owner |
| --- | --- |
| Provider IDs, registry, path confinement, credential CRUD, service lifecycle | `services/iptv_provider_manager.py` |
| One provider's raw catalog, playback, lists, history, details and images | `services/iptv_service.py` and `services/iptv_store.py` |
| Xtream protocol | `services/iptv_xtream.py` |
| Provider-scoped HTTP routes | `services/iptv_routes.py` |
| IPTV frontend API | `src/api/iptv.js` |
| IPTV workspace | `src/features/iptv/IPTVWorkspace.jsx` |
| IPTV list UI | `src/features/iptv/IPTVListsWorkspace.jsx` |
| IPTV visual scope | `src/features/iptv/iptv.css` |

The manager is lazily created by the already-registered IPTV route owner. The new implementation must not require a new `app.py` registration path.

### 3.3 Measured provider movie inventory

Read-only inspection at planning time found:

| Provider | Raw movie sources | TMDB IDs in catalog rows | Missing year | Cached full movie details | Provider movie playlists |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lionz | 40,755 at original planning; 40,771 at latest diagnosis | 0 in original raw catalog rows | 13,457 at original planning | 0 at original planning | 86 at original planning |
| EgySat | 20,912 | 0 | 11,508 | 6 | 126 |

Additional measured facts:

- Lionz contained 938 exact duplicate normalized title/year groups covering 1,906 rows.
- The two providers shared at least 2,453 exact normalized title/year identities, but those identities must remain separate by provider.
- All six cached EgySat movie detail payloads contained a provider-supplied TMDB ID.
- The six cached details also exposed fields such as plot, cast, director, genre, duration, backdrop, rating, and trailer reference.
- Current movie list memberships must be preserved: Lionz has one movie Favorite; EgySat has eleven movie Favorites.
- Current movie history must be preserved: Lionz has nine movie-history rows; EgySat has seven.

These measurements prove that SQLite volume is not the main risk. Identity accuracy, provider request volume, TMDB request volume, list/history continuity, and isolation are the main risks.

### 3.4 Raw catalog behavior and implemented trial baseline

- Provider sync gets `get_vod_streams` and replaces the raw `items` table.
- Provider detail gets `get_vod_info` only when a movie is opened.
- `IPTVStore.replace_catalog()` deletes the raw `items` rows and cached `details` before saving the refreshed provider catalog.
- Therefore durable TMDB matches and enriched metadata cannot be owned by the replaceable raw tables.
- Current provider playlist names are saved and rendered exactly as supplied.
- Current IPTV movie cards use the unchanged shared visual shell but provider-specific expanded content.
- At original planning time, IPTV modules made no TMDB request. The implemented trial now has an isolated IPTV TMDB client, provider-local movie store, explicit worker, matching, manual correction, raw fallback, filters, grouping, and paging. Those trial results and their defects are the migration baseline described in Section 23.

## 4. Absolute Non-IPTV Protection Boundary

### 4.1 Protected files and owners

The implementation task must not edit any of the following without stopping and obtaining a new explicit approval from Dante:

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

This denylist includes formatting-only and supposedly harmless refactors. Do not edit protected files to share helpers, improve naming, move code, add props, add styles, register routes, or reduce duplication.

### 4.2 Allowed implementation area

Expected allowed files:

```text
services/iptv_provider_manager.py
services/iptv_service.py
services/iptv_store.py                 only if existing raw IPTV integration requires it
services/iptv_routes.py
services/iptv_xtream.py                only for a demonstrated Xtream movie-detail need
services/iptv_movie_store.py            new
services/iptv_movie_service.py          new
services/iptv_tmdb.py                   new
services/iptv_metadata_settings.py      new
services/iptv_enrichment_worker.py      new
src/api/iptv.js
src/features/iptv/IPTVWorkspace.jsx
src/features/iptv/IPTVListsWorkspace.jsx
src/features/iptv/iptv.css
src/features/iptv/iptvMovieFilters.js   new if useful
tests/test_iptv_*.py
tests/iptv_*.test.mjs
tests/seed_iptv_e2e.py
tests/e2e/app-smoke.spec.js             only IPTV-contained additions; preserve all existing tests
docs/plans/iptv-movies-tmdb-enrichment-*.md
```

If another file becomes necessary, stop and explain exactly why. Do not silently widen scope.

### 4.3 Intentional duplication boundary

The existing CP TMDB implementation is coupled to CP's main metadata and catalog owners. This IPTV implementation must not refactor or route existing CP TMDB behavior through new shared code.

Create an IPTV-owned TMDB client and normalization path. Any duplicated protocol-level normalization must be documented as an intentional isolation boundary. Stable CP code is not to be refactored merely to reduce duplication.

### 4.4 Diff allowlist gate

At the end of every implementation stage:

1. Before the stage, record `git status --short`, protected tracked-file hashes, and the exact pre-existing dirty-file set.
2. After the stage, run `git status --short` and `git diff --name-only` again.
3. Compare the post-stage state with the recorded baseline, not with an imaginary clean worktree.
4. Require every new delta to be inside the explicitly approved IPTV area.
5. Stop immediately if the stage adds or alters a protected-file delta.
6. Never use reset, checkout, formatting, staging, or destructive cleanup to hide a boundary violation or erase Dante's unrelated work.

## 5. Target Data Layout

Each provider receives a separate enriched movie database:

```text
data/iptv/
  metadata-settings.json               IPTV-only TMDB credential; backend-only
  providers.json
  providers/<provider-id>/
    provider.json
    iptv.sqlite                         raw provider catalog/playback/state
    movies.sqlite                       enriched movie identity and metadata
    images/
    movie-images/                       optional lazy IPTV-only cache
    playback/
```

Rules:

- `movies.sqlite` never exists outside its provider root.
- No table may contain rows from another provider.
- Do not add a global enriched IPTV movie database.
- The same TMDB ID may exist independently in several providers.
- Provider deletion may remove only that provider root and its `movies.sqlite`.
- Raw provider `iptv.sqlite` remains the availability and playback authority.
- `movies.sqlite` contains both durable user decisions and rebuildable derived data. Manual matches, manual-unmatched locks, consent, review decisions, and continuity facts are not disposable.
- Projection rows, normalized relationships, facets, and queue calculations may be rebuilt only while preserving the durable rows and after a provider-local backup.
- Do not store artwork bytes in SQL.
- Do not write, copy into, own, rename, delete, or mutate CP's main metadata or artwork directories. An optional accepted-identity overlay may read validated existing CP artwork through the strict boundary in Section 12.

## 6. IPTV-Only TMDB Credential Contract

### 6.1 Ownership

- One IPTV-only TMDB credential is sufficient for the IPTV subsystem.
- It is not provider data and therefore may be stored once at `data/iptv/metadata-settings.json`.
- Using one IPTV credential must not cause provider metadata to share a database or match state.
- There is no fallback to CP's existing `tmdb_key` or TMDB cache.

### 6.2 Storage and exposure

- Store the credential through a new IPTV-owned settings service using atomic replacement.
- The credential file is under the already ignored user-data tree.
- Public responses expose only `tmdb_configured: true|false` and optionally a non-secret credential type.
- Password-style frontend fields load blank. Blank save means preserve the stored value.
- Never return a hint derived from the TMDB key.
- Never place the credential in a URL that is logged by CP.
- Never place the credential on a subprocess command line.
- Never print, echo, log, test, screenshot, document, commit, or add the credential to memory.
- Redact both the exact credential and common `api_key`/`Authorization` forms from IPTV errors.
- The implementation report states only whether configuration and validation succeeded.

### 6.3 Failure behavior

- Missing or invalid IPTV TMDB credentials do not break raw provider browsing or playback.
- Enrichment and manual TMDB search show an IPTV-local configuration error.
- A TMDB HTTP 401 pauses only IPTV enrichment.
- A TMDB HTTP 429 applies bounded IPTV-local backoff and never changes CP TMDB behavior.
- IPTV enrichment never retries by using CP's key.

## 7. Provider-Local Movie Model

### 7.1 Identity hierarchy

Within one provider:

1. Every raw movie row has one immutable source identity based on its provider item ID.
2. An unmatched source initially renders as its own provider movie card.
3. An accepted TMDB ID becomes the grouping identity for that provider.
4. All accepted sources with the same TMDB ID render as one movie card.
5. Sources from another provider never participate in that grouping.
6. Sources are not grouped only because titles look similar.
7. Manual decisions are locked until the user explicitly corrects or resets them.

### 7.2 Required match states

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

Every state must retain the provider source. Derived state may be rebuilt, but manual locks and accepted user decisions must survive migration and repair.

### 7.3 Match evidence order

1. Fetch provider movie detail and inspect its TMDB ID.
2. Validate any provider-supplied TMDB ID against TMDB title/year evidence.
3. If no usable ID exists, normalize the provider title and year.
4. Search TMDB using strict deterministic scoring.
5. Auto-accept only a high-confidence result with no credible rival.
6. Leave uncertain results ambiguous or unmatched.
7. Do not loosen thresholds to improve the match percentage.

False matches are more harmful than unmatched cards.

### 7.4 Manual match behavior

The IPTV-specific matching UI must:

- prefill provider title and year;
- search using the IPTV TMDB credential;
- show candidate title, year, poster, plot, and stable TMDB ID;
- apply the selected match only to the current provider;
- persist a manual lock;
- support `Correct match` and `Remove match`;
- preserve raw provider fields and sources after matching;
- never call CP's existing metadata-correction APIs.

### 7.5 Unmatched fallback card

An unmatched card displays all provider-supplied facts available from the raw row or provider detail:

- title;
- poster;
- year;
- provider rating;
- provider playlist/category;
- plot;
- cast text;
- director text;
- genre text;
- duration;
- container extension;
- source labels;
- Play, Favorite, Add to list, and Match metadata actions.

It also displays an honest `Unmatched` status. Missing fields remain absent or use a clear provider-data fallback. Do not silently query CP metadata.

## 8. Proposed `movies.sqlite` Responsibilities

The exact schema may be refined inside isolated tests, but ownership must remain equivalent to the following:

| Table/domain | Responsibility |
| --- | --- |
| `movie_meta` | Schema version, source catalog generation, enrichment generation, worker state |
| `movie_sources` | Raw provider movie IDs, playlist IDs/names, availability, provider snapshots, source attributes |
| `source_matches` | Match state, TMDB ID, method, evidence, confidence, manual lock, parser/matcher versions, terminal time, errors |
| `tmdb_movies` | Provider-local normalized TMDB movie snapshot and raw response needed for rebuild/audit |
| `tmdb_movie_localizations` | Provider-local display snapshots keyed by TMDB ID and locale; required `ar-SA` snapshot for Arabic-original default presentation |
| `people` and `movie_credits` | Provider-local TMDB cast, director, writer and person identity |
| `genres` and `movie_genres` | Filterable provider-local genre relationships |
| `keywords` and `movie_keywords` | Filterable provider-local keyword relationships |
| `collections` and `movie_collections` | Provider-local collection relationships |
| `movie_list_memberships` | Movie-level membership keyed to the existing provider-local list definition |
| `projection_jobs` | Provider-local projection lease, source generation, total, processed, phase, heartbeat, failure, retry, and committed checkpoint |
| `enrichment_queue` | Resumable source evaluations, priority, work key, attempts, timestamps, backoff, cancellation and error state |
| `worker_lease` or equivalent durable meta | Provider-local worker token, PID, heartbeat, command, consent, restart state, and crash reconciliation |

Requirements:

- Foreign keys enabled.
- Explicit schema version.
- Transactional schema initialization and migrations.
- WAL only if isolated tests prove lifecycle safety on Windows.
- Indexed filtering and deterministic pagination.
- A source has at most one accepted identity because `source_matches` is keyed by source. Several same-provider sources may intentionally accept the same TMDB ID; TMDB ID must not be globally unique.
- Source rows are never deleted merely because a sync temporarily omits them; mark unavailable with a generation and apply a grace policy.
- Manual locks survive catalog sync and metadata refresh.
- Schema version 2 migrates schema-version-1 state in place after a provider-local backup. It preserves all accepted IDs, manual locks, stored raw TMDB snapshots, lists, favorites, history, and completed evaluations.
- Relationship repair reconstructs missing genre, people, keyword, collection, language, and country links from stored raw TMDB snapshots where possible without a TMDB call.
- Shared parent tables use conflict-safe `INSERT ... ON CONFLICT DO UPDATE` semantics. Do not use destructive `INSERT OR REPLACE` on foreign-key parents.
- Matcher and parser versions are explicit. A version change may mark eligible automatic unmatched/ambiguous outcomes stale, but it never unlocks or overwrites manual decisions.
- The progress denominator is eligible available provider sources. The evaluated numerator counts terminal source decisions under the current matcher version and never unique grouped cards.
- No TV/Series kind is accepted by this database or API.

## 9. Provider Playlists, Filters, and Lists

### 9.1 Provider playlists

- Preserve exact provider playlist/category IDs and names.
- Render them in a dedicated `Provider playlist` dropdown.
- Default is `All provider playlists` inside the selected provider.
- Selecting a playlist filters cards to movies having at least one available source in that playlist.
- A source may retain raw playlist-derived signals such as provider-claimed 4K, HDCAM, dubbing, subtitle, language, or platform grouping.
- Provider claims are labelled as claims until actual stream inspection proves them.

### 9.2 CP-style filters

Implement the filter semantics inside IPTV-owned frontend and SQL code. Do not modify or import Library state owners.

Initial filters:

- text search;
- provider playlist;
- My list;
- genre;
- language;
- country;
- year from/to;
- minimum rating;
- metadata status;
- provider-claimed source quality;
- dubbed/subtitle indicators when provider evidence exists;
- watched/unwatched when provider-local history supports it;
- deterministic sort by recently added, title, rating, year newest, and year oldest.

Advanced identity filters may include person, keyword, and collection only after the basic paged query is proven.

Rules:

- Filters never create lists.
- Every valid result is reachable through bounded server-side pages.
- Do not load the complete provider catalog into React.
- TMDB-dependent filters exclude unmatched rows because those facts are unknown.
- `Metadata status` must allow users to find unmatched, ambiguous, and failed rows explicitly.
- A source filter matches a card if at least one available source satisfies it.
- When a source filter is active, qualifying sources are shown or prioritized honestly.

### 9.3 User-created lists

- Existing provider-local list definitions remain authoritative in `iptv.sqlite`.
- New movie-group membership is owned in the same provider's `movies.sqlite` and references the existing provider-local `list_id` logically.
- Do not create a second competing list-definition owner.
- A movie is added to a list once, regardless of source count.
- Unmatched movies may be added to lists.
- When an unmatched source becomes matched, list membership migrates transactionally to the accepted provider-local movie identity.
- When several sources collapse into one TMDB movie, duplicate memberships deduplicate without losing the earliest position or added timestamp.
- If a selected source disappears but another source remains, the list entry remains available.
- If all sources disappear, the list entry remains understandable and is marked unavailable.
- Existing raw movie Favorites and history are rehearsed and migrated/projected without changing Live TV or Series list/history behavior.

## 10. Multiple Sources and Playback

- A matched movie card groups only sources from the selected provider.
- Each source retains its raw Xtream item ID and playback extension.
- One available source plays directly.
- Several sources open an IPTV-local source chooser.
- Visible source labels may include provider playlist, provider quality claim, dubbing/subtitle claim, and availability.
- Container/file extensions remain internal playback facts. Do not render `MKV`, `MP4`, or other file-type badges on IPTV movie cards; IPTV is not presenting locally owned library files and the extension adds no useful movie meaning.
- Playback still goes through the existing provider-scoped playback routes and service.
- Do not modify the FFmpeg relay, Hls.js player, native player, or non-IPTV playback.
- Starting a grouped movie updates source-level history through existing IPTV ownership.
- Movie-level watch state is projected from the most recent or completed member source without rewriting non-movie history.

## 11. Enrichment Process Isolation

Bulk enrichment must not execute as an uncontrolled Flask background thread.

### 11.0 Projection is not enrichment

- Provider-local Movies projection is a bounded local database transformation from that provider's `iptv.sqlite` into its `movies.sqlite`.
- Projection performs no provider-detail or TMDB request.
- After provider sync commits, a provider-local projection coordinator may start automatically. Ordinary Movies and facet `GET` routes must remain pure reads and must not synchronously initialize or rebuild the store.
- Permit one projection lease per provider. A late Lionz response cannot publish into an EgySat view, and vice versa.
- On first-ever projection, publish committed raw batches with an honest `Preparing provider movies` state so cards begin appearing without a false empty completion.
- On later generations, retain the last committed browseable generation until the replacement is safe; do not clear the existing catalog at projection start.
- Store projection total, processed count, generation, phase, heartbeat, error, retry state, and last committed checkpoint provider-locally.

### 11.1 Worker contract

- Use an IPTV-owned subprocess or equivalently isolated worker process.
- First start requires one explicit `Improve this provider's Movies` consent action after successful IPTV credential validation.
- Credential save/test, CP import, CP startup, provider selection, provider sync, and opening IPTV or Metadata never constitute consent and never start TMDB work.
- Once consented and started, continue across bounded internal work units until complete, paused, cancelled, authorization fails, or service backoff requires waiting. Do not stop every 100 sources.
- After a normal CP restart, preserve the checkpoint and initially require a visible `Continue metadata improvement` confirmation. Do not silently auto-resume in the first production version.
- Read the IPTV TMDB credential from the backend-only settings file; never pass it on the command line.
- Allow at most one worker per provider and initially one active IPTV TMDB worker globally. A second provider remains independently queued with a visible waiting-for-capacity state.
- Persist progress to that provider's `movies.sqlite`.
- Use a durable provider-local lease/token and heartbeat. Do not rely only on an in-memory process dictionary or PID.
- Support pause/cancel/resume without corrupting committed rows.
- Bound provider requests, TMDB requests, memory, and database transaction size.
- Use finite timeouts and bounded exponential backoff.
- Browsing may raise the priority of already queued visible sources, but a foreground page must never perform a TMDB request directly. Apply priority aging so the backlog cannot starve.
- Retain one source evaluation per source while deduplicating provider-local network work by validated provider TMDB ID and normalized query work key. Shared work may advance several sources only after each source independently passes identity/year validation.
- Provider detail retrieval for enrichment must bypass the raw `iptv.sqlite` detail cache. Store normalized provider evidence in that provider's `movies.sqlite`; do not mutate raw catalog/detail state merely to enrich metadata.
- A worker crash changes only IPTV-local status.
- CP remains usable if the worker executable, database, provider, or TMDB is unavailable.

### 11.2 Publication contract

- Commit bounded source/relationship transactions and coalesced publication checkpoints. A full 20K/40K run is never one transaction.
- Never expose a partially written movie relationship.
- Separate high-frequency worker progress/heartbeat from card metadata generation. Do not force a full visible-page refresh for every individual source.
- Increment an IPTV movie generation only after a committed publication checkpoint, and expose affected identities when practical.
- Frontend refreshes bounded pages from `movies.sqlite` after generation changes.
- Do not publish cards through CP catalog events.
- Do not alter CP `catalog_generation`, `media_generation`, `asset_generation`, or curation generations.

## 12. Main CP Read Boundary

IPTV Movies remains independently usable from provider-local data, but an accepted TMDB identity may now receive a read-only CP canonical overlay. The overlay may expose ownership, intentional canonical metadata, and already-downloaded poster or person artwork. It is an optimization and presentation layer, never match evidence and never the only IPTV fallback.

The overlay must use a new IPTV-owned read adapter with all of the following properties:

- resolve the IPTV match first, then query CP only by the accepted TMDB ID;
- never prefer or accept a candidate because CP owns it;
- no `CatalogRepository` instance;
- no `CatalogStore.initialize()`;
- no catalog schema creation or migration;
- SQLite URI `mode=ro`;
- `PRAGMA query_only=ON`;
- batched `SELECT` for only the accepted TMDB IDs and person IDs present on the bounded page;
- no reconcile, details hydration, cache write, export, generation update, or error recovery;
- do not copy canonical movie, people, credit, or artwork records into either provider's `movies.sqlite`;
- do not copy CP artwork files into either provider root;
- reuse a local artwork file only through an IPTV-owned, path-validated, strictly read-only resolver;
- do not use the existing `/api/assets/<checksum>` path for this overlay unless it is independently proven to use a read-only connection; its current lookup path opens the normal writer-capable catalog connection;
- a missing, incompatible, or unreadable catalog returns no canonical overlay and cannot fail IPTV browsing;
- missing canonical fields or artwork fall back to provider-local TMDB data, then raw provider metadata;
- logical and physical main-catalog facts are identical before and after the query and asset read.

The display precedence is:

1. provider-local manual identity decisions, playback sources, lists, favorites, and history;
2. eligible CP canonical metadata and local artwork for the already accepted TMDB identity;
3. provider-local IPTV TMDB snapshot data;
4. raw Lionz or EgySat metadata for unmatched or incomplete items.

People are joined across the read boundary only by TMDB person ID, never by display name. If any platform behavior makes a truly non-writing canonical or artwork read impossible, omit the overlay and continue with provider-local data. Do not weaken the boundary.

The overlay is a later, independently gated phase. Core schema migration, relationship repair, projection, enrichment, localization, raw browsing, and Metadata progress must work without it. Before overlay implementation, Dante must approve the exact field precedence. The safest initial overlay is ownership plus validated existing local poster/person artwork; intentional CP canonical field overrides remain explicit rather than silently replacing provider-local TMDB fields.

### 12.1 IPTV localization and external-link contract

- Matching remains locale-neutral. Never accept or reject an identity merely because the UI requests Arabic or English display metadata.
- The accepted base TMDB snapshot records `original_language`, `original_title`, alternative titles, and optional `imdb_id`.
- If `original_language == 'ar'`, fetch TMDB `ar-SA` through the IPTV-owned client after identity acceptance and store that provider-local display snapshot. Arabic is the default expanded-card presentation and the switch reads `English`.
- For other original languages, English/base metadata remains default. An explicit `العربية` switch may request a transient `ar-SA` overlay through the IPTV credential; it must not call CP's `/api/tmdb/details` route or CP credential.
- Localization falls back field by field. Missing Arabic fields never blank a usable original or English title, plot, genre, poster, collection, or credit.
- The display switch resets when the expanded card collapses or changes unless a later separately approved preference contract is introduced.
- Use `dir="auto"` for localized titles, plot, people, roles, and labels. Take TMDB's localized payload as supplied; do not invent translations or merge people by display name.
- Arabic-original movies use a TMDB movie-page link as the primary external reference. Other movies use IMDb when a valid `tt...` ID exists and TMDB otherwise. The external target depends on stable original language, not the currently selected display language.

## 13. API Direction

All movie routes remain provider-scoped:

```text
GET    /api/iptv/metadata/settings
PATCH  /api/iptv/metadata/settings
POST   /api/iptv/metadata/test

GET    /api/iptv/providers/<provider_id>/movies
GET    /api/iptv/providers/<provider_id>/movies/facets
GET    /api/iptv/providers/<provider_id>/movies/projection/status
POST   /api/iptv/providers/<provider_id>/movies/projection/retry
GET    /api/iptv/providers/<provider_id>/movies/metadata/status
POST   /api/iptv/providers/<provider_id>/movies/enrichment/start
POST   /api/iptv/providers/<provider_id>/movies/enrichment/pause
POST   /api/iptv/providers/<provider_id>/movies/enrichment/resume
POST   /api/iptv/providers/<provider_id>/movies/enrichment/cancel
POST   /api/iptv/providers/<provider_id>/movies/enrichment/retry-failures
POST   /api/iptv/providers/<provider_id>/movies/enrichment/re-evaluate-stale
GET    /api/iptv/providers/<provider_id>/movies/metadata/review
GET    /api/iptv/providers/<provider_id>/movies/<movie_key>
GET    /api/iptv/providers/<provider_id>/movies/<movie_key>/sources
GET    /api/iptv/providers/<provider_id>/movies/<movie_key>/localization/<locale>
GET    /api/iptv/providers/<provider_id>/movies/<movie_key>/match/search
POST   /api/iptv/providers/<provider_id>/movies/<movie_key>/match/ai-preview
POST   /api/iptv/providers/<provider_id>/movies/<movie_key>/match
DELETE /api/iptv/providers/<provider_id>/movies/<movie_key>/match
POST   /api/iptv/providers/<provider_id>/movies/<movie_key>/lists/<list_id>
DELETE /api/iptv/providers/<provider_id>/movies/<movie_key>/lists/<list_id>
```

Exact paths may be simplified if one authoritative REST shape is clearer. Non-negotiable properties:

- every provider movie operation carries `provider_id`;
- movie keys are opaque and path-validated;
- responses never contain secrets or raw credential-bearing URLs;
- paging metadata is explicit;
- dashboard and review queries are SQL-paged and never return the complete provider catalog;
- projection status and enrichment status are separate response contracts with separate denominators;
- localization and AI routes use only IPTV-owned services, configuration, SQL, and credential ownership;
- errors are IPTV-local and redacted;
- no existing non-IPTV route changes.

## 14. Desktop UI Contract

Movies retains the existing provider selection at the IPTV workspace level.

```text
IPTV                                             [ Lionz v ] [sync]

Home  Live TV  Movies  Metadata  Series  Favorites  My Lists

Movies
[Provider playlist: All provider playlists v]
[My list: All movies v]
[Search] [Genre] [Language] [Country] [Year] [Rating]
[Quality] [Metadata status] [Sort]
```

Rules:

- Desktop only.
- Do not redesign Live TV, Series, Home, global navigation, or Settings.
- Put IPTV TMDB configuration and enrichment controls inside the IPTV workspace, not shared Settings.
- `Metadata` is provider-scoped and appears immediately after `Movies`. Switching provider switches the complete dashboard state.
- The Metadata page centers one durable progress bar labelled in provider sources, with distinct projection, enrichment, review, failure, and waiting/backoff states.
- Visiting Metadata is never required for already-consented background progress.
- Use the unchanged shared movie-card shell only through its existing props.
- Put all new details, people presentation, language switching, external-link selection, matching, source chooser, filters, dashboard, review, and key configuration in IPTV-owned components.
- Scope every new CSS selector beneath `.iptv-workspace` or a stricter IPTV class.
- No global CSS variables or shared selector edits.
- Provider playlist and My list are separate controls.
- Raw provider playlist names remain visible and unchanged.
- Unmatched cards remain visually complete enough to browse and play.
- Matched cards show full TMDB details without a live TMDB call on card expansion.
- Render metadata state once per card. A matched movie shows one green `Matched` badge in the same status area when collapsed and expanded; expanding the card must not add a second status badge.
- Do not expose container/file-type chips in collapsed or expanded IPTV movie cards. Retain the extension only where the playback owner requires it internally.
- IPTV may mirror CP expanded-card behavior but must not call CP person, details, Maintenance, Smart Match, or TMDB routes. Biographies are omitted initially unless a later approved IPTV-owned contract supplies them.

## 15. Consolidated Action Sequence and Approval Gates

The original settings, provider-local store, strict matcher, raw cards, manual correction, grouping, filters, lists, and 100-source pilot are implemented and validated evidence. They are the migration baseline, not permission to run more live work. The next implementation must proceed in this order.

### Gate 0 - Fresh read-only baseline and exact scope

1. Inspect branch, remote, current dirty worktree, overlapping user changes, and the exact running configuration owner.
2. Record the current dirty-file set and hashes of every protected tracked file before editing.
3. Locate the main CP catalog without importing `app.py` or instantiating a writer owner.
4. Record a read-only logical and physical catalog baseline: schema, tables/indexes, integrity, generations, row counts, deterministic digests, file hashes, timestamps, and sidecars.
5. Record `config.json` and protected configuration hashes without displaying contents.
6. Record read-only provider facts for Lionz and EgySat separately: raw/source generation, schema version, source/match/queue/list/history counts, integrity, file hashes, and worker/projection state.
7. Confirm no enrichment or projection process is active.
8. Define the exact IPTV-owned file manifest for the approved implementation stage.

**Exit gate:** the current state is reproducibly captured, no read-only inspection has lazily mutated provider state, and unrelated dirty work is protected by a before/after delta contract.

### Gate 1 - Schema version 2 migration and relationship repair rehearsal

1. Design an in-place migration that separates durable user decisions from rebuildable derived state.
2. Preserve every schema-version-1 accepted TMDB ID, manual lock, manual-unmatched lock, stored raw TMDB snapshot, list/favorite/history continuity fact, and completed evaluation.
3. Add parser/matcher versions, terminal evaluation facts, projection job state, durable worker lease/heartbeat, consent/restart policy, queue priority/work keys, localization storage, and optional IMDb ID.
4. Replace destructive shared-parent writes with conflict-safe updates.
5. Rebuild missing relationships from stored raw TMDB snapshots without network calls where possible.
6. Rehearse separately on disposable copies of Lionz and EgySat. Never use one provider's backup, snapshot, IDs, or repair report for the other.
7. Verify before/after accepted IDs and manual locks exactly; verify repeated saving of shared genres, people, keywords, and collections retains every relationship.
8. Prove rollback restores only the affected provider copy.

**Exit gate:** migration and repair preserve all valuable trial work, repair relationship loss, make no live request, and have exact provider-local rollback evidence. Live databases remain untouched pending separate approval.

### Gate 2 - Honest non-blocking provider projection

1. Move projection out of ordinary Movies/facet `GET` requests into the provider-local coordinator.
2. Trigger local projection after a committed provider sync without triggering TMDB work.
3. Add durable total/processed/phase/checkpoint/heartbeat/failure/retry state and one projection lease per provider.
4. Publish first-ever raw batches progressively with an honest preparing state; retain the previous committed generation during later reprojection.
5. Preserve bounded SQL/browser paging and never decode or send the complete provider catalog to the browser.
6. Add stale-response protection for provider switching, refresh, failure/retry, and late generations.
7. Prove slow 20K/40K projections do not block Flask, show a false empty completion, or affect Live TV/Series.

**Exit gate:** raw Movies become progressively browseable without TMDB and the first-open defect is eliminated rather than hidden by a prepared live database.

### Gate 3 - Durable continuous enrichment and provider-scoped control APIs

1. Replace the user-facing 100-source stop with continuous bounded processing after one explicit provider consent.
2. Retain `Run next 100` only behind a diagnostic/pilot surface.
3. Add durable worker lease/token/heartbeat and crash reconciliation independent of in-memory process tracking.
4. Initially enforce one active IPTV TMDB worker globally; show another provider as waiting for capacity without merging state.
5. Fetch provider detail through a non-caching enrichment path so metadata work does not alter raw `iptv.sqlite` detail state.
6. Keep source evaluation independent while deduplicating provider-local network work by validated TMDB ID or normalized query work key.
7. Add fair visible/new-source priority with aging, bounded rate/backoff, responsive pause/resume/cancel, failure retry, and current-rule stale re-evaluation.
8. Separate progress heartbeat from coalesced card-generation publication.
9. Implement the initial restart policy: preserve checkpoint and offer visible continuation, with no silent auto-resume.
10. Inject authentication, rate limit, timeout, server error, process crash, stale PID, lease loss, provider deletion, and CP restart scenarios.

**Exit gate:** a disposable run crosses 100 sources without another action, remains bounded/resumable, preserves raw browsing, and cannot start or modify another provider.

### Gate 4 - Authoritative parser, matching evidence, and localization

1. Use one parser for provider-ID validation, automatic search, manual search, re-evaluation, and AI-proposed queries.
2. Implement the bounded multilingual ladder and distinctive installment-token penalties without lowering strict acceptance thresholds.
3. Version parser/matcher outcomes and select only eligible automatic stale results for bounded re-evaluation; preserve manual locks.
4. Store provider-ID evidence separately from fallback-search evidence and show credible-rival reasoning.
5. Preserve existing accepted trial matches unless a separately reviewed correction proves one wrong.
6. Add provider-local Arabic-original `ar-SA` display snapshots after acceptance and the transient English/Arabic switch contract in Section 12.1.
7. Persist optional IMDb ID and implement the stable original-language external-link rule.
8. Verify localization never changes accepted identity, grouping, lists, sources, or playback.

**Exit gate:** all named fixtures and multilingual/number-bearing regressions pass; localization improves presentation without becoming match evidence.

### Gate 5 - Provider-local Metadata dashboard and rich IPTV details

1. Add `Metadata` after `Movies` inside the existing desktop IPTV navigation only.
2. Make the durable source progress bar primary and show sync, projection, and enrichment as separate stages and denominators.
3. Add paged Overview, Needs review, Unmatched, Failed, and Manual matches subviews.
4. Add Start/Continue all, Pause, Resume, Cancel future work, Retry failures, and Re-evaluate stale automatic results.
5. Preserve all completed work and raw playback when cancelling future claims.
6. Replace the inferior IPTV people text with an IPTV-owned expanded detail presentation containing directors, writers, cast, roles, characters, TMDB person IDs, and portrait references.
7. Do not modify or call protected CP expanded-person, biography, Maintenance, or Smart Match owners.
8. Preserve page, scroll, filters, expanded card, source choice, provider selection, lists, and playback when metadata publishes.
9. Consolidate metadata status into one card badge and remove container/file-type chips without changing playback source data.

**Exit gate:** Lionz and EgySat expose completely separate dashboards and the production bundle shows CP-quality IPTV details without a protected-owner change.

### Gate 6 - Optional IPTV Match by AI review tool

This gate is optional and may be deferred without blocking deterministic enrichment.

1. Use IPTV-owned AI configuration, service, routes, and state. Do not read or call CP Maintenance/Smart Match configuration or routes.
2. AI proposes only structured title, year, and aliases for explicit selected review rows or a small selected batch.
3. The IPTV TMDB client performs every search and deterministic validation; AI cannot invent or apply a trusted ID.
4. Require preview and explicit user application for AI-assisted results in the initial version.
5. Timeout, invalid JSON, unavailable AI, and hallucinated queries leave identity and playback unchanged.

**Exit gate:** deterministic matching remains complete without AI, and every AI path is optional, preview-first, IPTV-owned, and provider-scoped.

### Gate 7 - Optional CP canonical read-only overlay

This gate follows the core provider-local system and requires separate approval of exact overlay fields.

1. Implement one IPTV-owned failure-safe read adapter using accepted TMDB/person IDs only.
2. Prove `mode=ro`, `query_only=ON`, bounded batch reads, path containment, and physical/logical zero-write behavior against an active catalog and sidecars.
3. Initially prefer ownership and eligible existing local poster/person artwork; do not silently override provider-local TMDB fields without the approved field contract.
4. Do not copy CP rows or artwork, invoke normal catalog/asset owners, update caches/generations, or use ownership as match evidence.
5. Treat every missing database/schema/asset/lock/read failure as an empty overlay.

**Exit gate:** before/after CP schema, rows, generations, digests, files, timestamps, sidecars, caches, and asset relationships are identical; otherwise omit the overlay.

### Gate 8 - Zero-tolerance regression and production-bundle proof

1. Compare all protected files and configuration against the captured dirty baseline and require no new protected delta.
2. Confirm main CP catalog schema, integrity, generations, digests, rows, overrides, lists, history, assets, timestamps, and sidecars are unchanged.
3. Run focused IPTV tests and migration/repair rehearsals on disposable provider copies.
4. Run complete isolated Python tests with `CP_TEST_MODE=1` and a unique verified OS-temp `CP_TEST_ROOT`.
5. Run all frontend Node tests and the production build.
6. Run disposable desktop Playwright against the built bundle and private test data.
7. Verify Home, Library, Discover, Movie Lists, AI Control, Downloads, Maintenance, Settings, Help, shared cards, people, artwork, and playback.
8. Verify provider sync, Movies, Metadata, Live TV, Series, Favorites, My Lists, provider switching, slow projection, continuous enrichment, pause/resume/cancel, failure/retry, and restart offer.
9. Verify the normally served production asset hashes and visible behavior, not source-only UI.

**Exit gate:** any non-IPTV regression, provider crossover, credential exposure, false progress, or unapproved file delta blocks live activation.

### Gate 9 - Separately approved live provider migration and activation

1. Obtain explicit approval naming the provider and action before touching its live `movies.sqlite`.
2. Back up only that provider's affected IPTV-owned files and verify the backup before migration.
3. Migrate/repair one provider at a time; prove accepted IDs/manual locks/list/history continuity and integrity immediately afterward.
4. Do not start enrichment merely because migration, credential test, projection, page opening, provider switching, or CP launch succeeded.
5. Obtain explicit consent for `Improve this provider's Movies` before the first continuous run for that provider.
6. Present pilot/runtime evidence before enabling the second provider or changing restart/concurrency policy.
7. No restart, full run, commit, stage, push, release, or publication occurs without its own explicit approval.

## 16. Regression Matrix

### 16.1 Protected non-IPTV CP workflows

- Home rows, navigation, actions, and trailers.
- Library File View and Movie View.
- Library paging, filters, search, people, keywords, collections, lists, viewing state, and details.
- Discover search, browse, ownership attachment, related navigation, details, and download actions.
- Movie Lists CRUD, imported lists, shared cards, and ownership display.
- AI Control and Ask AI separation.
- Downloads/qBittorrent workflows.
- Maintenance, Cleanup, metadata correction, unmatched, and provider selection.
- Local/native playback, Continue Watching, subtitles, and artwork.
- Settings sections unrelated to IPTV.
- Help and application data paths.

All must remain behaviorally identical.

### 16.2 Existing IPTV workflows outside Movies

- Provider add/edit/test/sync/remove.
- Provider selection and stale-response handling.
- Live TV categories, EPG, Favorites, lists, playback, and recovery.
- Series categories, details, seasons, episodes, Favorites, lists, and playback.
- IPTV Home and recent items.
- Provider isolation for identical IDs.
- App-data-root lifecycle.

### 16.3 IPTV Movies workflows

- Raw fallback with no IPTV TMDB key.
- Matched, unmatched, ambiguous, retryable, and terminal states.
- Provider playlist dropdown.
- My list dropdown.
- Filter combinations and deterministic paging.
- One accepted movie with one source.
- One accepted movie with several sources in the same provider.
- Same TMDB ID in different providers remains separate.
- Manual match, correction, reset, and lock.
- Unmatched card Play/Favorite/Add to list.
- Source chooser and source removal.
- Existing movie Favorite/history continuity.
- Worker start/pause/resume/cancel/crash/restart.
- Missing, invalid, rate-limited, and redacted IPTV TMDB credential behavior.
- Schema-version-1 to version-2 preservation and rollback.
- Shared relationship repair from stored snapshots without TMDB calls.
- Slow first projection, progressive raw publication, refresh, failure/retry, and provider switching.
- Continuous processing beyond 100 sources, fair priority, global-capacity waiting, durable checkpoints, and visible restart continuation.
- Metadata dashboard counters, review pages, controls, and provider isolation.
- Arabic-original default display, transient English switch, fallback behavior, and TMDB/IMDb external-link rule.

## 17. Performance and Resource Budgets

- No movie-store creation or enrichment work during CP import/startup.
- Automatic post-sync projection is local, provider-scoped, non-blocking, and TMDB-free; it is the only automatic preparation stage.
- No complete provider catalog decoding on one frontend request.
- All movie pages and facets are SQL-paged/indexed.
- Card expansion is database-backed and does not wait for TMDB.
- No per-card main-catalog query.
- No per-card live provider detail query after enrichment.
- Worker transaction batches are bounded and observable.
- Provider and TMDB concurrency defaults are conservative and configurable only inside IPTV ownership.
- CP foreground requests retain priority by process isolation; if measurable non-IPTV latency increases, stop and reduce or redesign the worker before continuing.
- Artwork is lazy; do not download tens of thousands of posters during identity-only enrichment.

## 18. Backup, Recovery, and Removal

- `iptv.sqlite` remains unchanged by projection and enrichment. Existing explicit list/favorite/history/playback owners may continue their established raw-state writes.
- Provider-detail evidence used by enrichment bypasses raw detail caching and is stored in `movies.sqlite`.
- `movies.sqlite` is not wholly disposable once it contains manual identity decisions or consent. Repair rebuilds derived tables while preserving durable state.
- Whole-file deletion/recreation is permitted only for a never-used/disposable provider copy or after an explicit export/restore design proves every durable decision is preserved.
- Schema migration backs up only the affected provider's `movies.sqlite` first.
- Failed migration restores that provider-local backup.
- Provider deletion closes only that provider's worker/playback and removes only its confined root.
- Removing the IPTV TMDB credential pauses enrichment but does not delete enriched metadata.
- Main CP catalog backup/restore code is not invoked by IPTV.

## 19. Stop Conditions

Stop implementation and report evidence if any of the following occurs:

- A protected source file appears necessary.
- A non-IPTV source file changes unexpectedly.
- A main CP SQL schema, row, generation, digest, sidecar, cache, or config value changes because of IPTV work.
- The IPTV TMDB credential appears in output, a shell/process command line, a diff, a test fixture, a printed URL, a log, a screenshot, documentation, or memory.
- An IPTV route can resolve media without an explicit provider ID.
- A provider's `movies.sqlite` can read or write another provider's data.
- A source from one provider appears on another provider's card.
- Live TV or Series behavior changes.
- TMDB enrichment starts without the selected provider's explicit consent, silently auto-resumes under the initial restart policy, or blocks Flask.
- Ordinary Movies/facet `GET` requests synchronously initialize or rebuild the provider projection.
- The worker can consume CP's TMDB credential.
- Unmatched movies disappear from ordinary browsing.
- A manual match can be overwritten automatically.
- Existing IPTV movie Favorites/history cannot be preserved in rehearsal.
- Any protected non-IPTV automated or rendered workflow fails.
- The worktree contains overlapping user changes that cannot be preserved safely.

## 20. Explicit Non-Goals

- No TV Show or episode enrichment.
- No All Providers catalog.
- No cross-provider source grouping or deduplication.
- No automatic generation of playlists or lists.
- No replacement of provider playlists.
- No main CP list integration.
- No main CP metadata ingestion from IPTV.
- No CP catalog migration, backfill, reprojection, or repair.
- No modification of existing CP TMDB behavior.
- No shared Settings redesign.
- No global/shared card redesign.
- No mobile/responsive work.
- No FFmpeg, Hls.js, native-player, subtitle, or download changes.
- No commit, push, release, publication, or existing live-process restart without separate authorization.

## 21. Definition of Done

Implementation is complete only when all of the following are true:

1. Every provider has its own independently versioned `movies.sqlite`.
2. Providers never share movie rows, matches, sources, metadata, list membership, or worker state.
3. Movies only are enriched.
4. One accepted provider-local movie card can expose several same-provider sources.
5. Provider playlists remain available in a separate dropdown.
6. CP-style filters query bounded provider-local SQL pages and do not create lists.
7. User-created provider-local lists work for matched and unmatched movies.
8. Unmatched cards display provider data and support manual matching.
9. Manual matches are locked, correctable, and removable.
10. The IPTV TMDB credential is stored separately, redacted, and never falls back to CP's key.
11. Raw IPTV movie browsing/playback works without TMDB.
12. Worker failure cannot crash or block CP.
13. Schema-version-1 accepted identities, manual locks, and completed work migrate without deletion or blanket rematching.
14. Shared genres, people, keywords, and collections survive repeated saves and repair.
15. Slow first projection is visible, retryable, provider-local, and never looks like an empty finished catalog.
16. One explicit provider consent starts continuous bounded enrichment beyond 100 sources; credential test, sync, navigation, and startup do not.
17. Restart preserves progress and initially offers visible continuation rather than silently resuming.
18. The provider-local Metadata dashboard exposes honest source progress, review queues, controls, and distinct sync/projection/enrichment state.
19. Arabic-original movies default to IPTV-owned TMDB Arabic display metadata with a transient English switch and TMDB external link.
20. Collapsed and expanded IPTV movie cards show one metadata-status badge, matched state is green, and container/file-type chips are absent while playback retains its internal extension.
21. No new protected-file delta exists relative to the captured dirty baseline.
22. Main CP SQL, config, metadata caches, APIs, sidecars, and non-IPTV frontend behavior are unchanged.
23. Complete isolated Python, Node, build, Playwright, served-bundle, migration, and workflow-parity gates pass.
24. No secret appears in tracked files or evidence.
25. Live migration, repair, enrichment, restart, Git, and release actions remain separately approved and provider-specific.

## 22. Completion Evidence Template

- Baseline commit/branch/worktree:
- Protected-file hash comparison:
- Diff allowlist result:
- Main CP SQL schema/integrity/logical digest before and after:
- Main CP generations and protected row counts before and after:
- `config.json` hash before and after:
- IPTV credential redaction result:
- Provider-local database isolation result:
- Same-TMDB-ID cross-provider isolation result:
- Existing provider movie Favorites/history rehearsal:
- Live TV and Series parity result:
- Match precision pilot:
- Ambiguous/unmatched behavior:
- Worker failure/cancel/resume evidence:
- Schema-version-1 preservation and schema-version-2 migration report:
- Relationship repair before/after report:
- Projection progress/failure/retry/provider-switch evidence:
- Continuous run beyond 100 and restart-offer evidence:
- Metadata dashboard counter reconciliation:
- Arabic-original default/English switch/external-link evidence:
- Focused IPTV Python tests:
- Complete isolated Python suite:
- Frontend Node suite:
- Production build:
- Disposable Playwright:
- Normally served bundle verification:
- Protected non-IPTV workflow matrix:
- Changed files and ownership:
- Remaining IPTV-only risks:
- Live restart/full-enrichment approval status:

## 23. Living Post-Trial Findings and Global Resolution Plan

Status: observations consolidated into the authoritative action sequence in Section 15. Saving or editing this section does not authorize implementation, database repair, enrichment, provider sync, CP restart, commit, push, release, or publication.

### 23.1 Confirmed findings

1. **First-open projection can look broken.** The first Movies request can synchronously prepare tens of thousands of provider-local sources. The UI currently has no separate honest projection state, progress, failure, or retry surface. Cards appearing after a later refresh does not prove the defect is fixed.
2. **A Matched badge currently proves identity acceptance, not complete metadata projection.** `Ashes ( 2026 )` and `Prisoners of Paradise ( 2025 )` have accepted provider TMDB IDs and stored TMDB responses containing genres, yet their normalized genre relationships disappeared.
3. **The relationship loss is systemic, not a title-specific matching failure.** `_save_tmdb_movie()` uses `INSERT OR REPLACE` for shared parent rows such as genres, people, keywords, and collections. In SQLite, replacement deletes and recreates the parent row, which can cascade-delete relationships belonging to previously saved movies.
4. **People data exists but IPTV does not present it through the generic CP expanded-card behavior.** IPTV stores person IDs, names, roles, characters, profile URLs, and credits in the selected provider's `movies.sqlite`, but the expanded IPTV card renders an inferior comma-separated view instead of portrait credit cards.
5. **Manual and automatic sources can correctly group under one movie.** The Lionz `Minions & Monsters` card groups three same-provider sources under TMDB ID `1315772`; one source is manually locked and two were automatically accepted from the provider ID.
6. **Canonical reuse has measured value.** A strict read-only inspection found that CP owns `Minions & Monsters`, has a local poster, and already has local portraits for 18 of the 41 people related to the IPTV movie. Those existing files can improve IPTV presentation without another image download.
7. **The existing CP asset route is not sufficient proof of the new boundary.** Its lookup opens the ordinary writer-capable catalog connection. IPTV requires a separately proven read-only file-resolution path before canonical artwork reuse can be accepted as zero-write.
8. **Automatic and manual title normalization currently diverge.** Lionz source `Balan - The Boy ( 2026 )` is stored as unmatched even though the manual search returns the single correct result. The automatic evidence records `query_title: "balan the boy 2026"`, `query_year: 2026`, and no candidates, while the manual path cleans the current card title to `balan the boy` with year `2026`. The automatic path prefers a provider-detail title; the shared cleaner removes a parenthesized year but not the same bare trailing year. This is a normalization-path defect, not evidence that the global confidence threshold should be lowered.
9. **Multilingual titles require structured aliases, not one flattened query.** Lionz source `Merry Little Batman ميلاد سعيد باتمان الصغير (2023) (مدبلج)` contains the canonical English title, an Arabic translated title, release year, and the Arabic label for dubbed. Lionz also supplied the correct TMDB ID `870358`. Its stored unmatched decision predates the newer Arabic/dub-suffix validator; the current pure validator accepts the correct title/year at score `95`. However, the fallback evidence shows a single flattened search for `merry little batman ميلاد سعيد باتمان الصغير مدبلج`, which returned no candidates. Without a usable provider ID, the present fallback would still fail this valid case.
10. **Stored unmatched decisions can become stale after safe matcher improvements.** Updating parser or validator code does not automatically re-evaluate completed queue rows. A card can therefore remain visibly unmatched even when the current rule would accept it. Re-evaluation must be explicit, versioned, provider-local, bounded, and must never overwrite manual locks.
11. **The same provider may contain cleaner sibling sources that have not yet contributed evidence.** Lionz currently also contains `Merry Little Batman ( 2023 )` and `Merry Little Batman (2023) مدبلج فرنسي`; both remain unprocessed. Provider-local sibling titles can provide useful aliases after independent identity validation, but source count or title similarity alone must not create a match.
12. **`The Truthers ( 2026 )` independently reproduces the bare-trailing-year defect.** The raw Lionz catalog title cleanly parses to title `the truthers` and year `2026`, but stored automatic evidence shows the provider-detail form was normalized to query title `the truthers 2026` while also sending year `2026`; fallback search returned no candidates. Lionz supplied TMDB ID `1659155`, but no TMDB snapshot remains in the provider database to independently verify that ID's external identity. Against a candidate titled `The Truthers` from 2026, the current pure validator scores the raw catalog form `100` and the bare-year detail form only `81.207`, below provider-ID acceptance. This confirms the same normalization-path defect as `Balan - The Boy`, not a separate threshold problem.
13. **Raw manual-search results are currently presented as if every row were a credible candidate.** For `Demon Slayer: Kimetsu no Yaiba Infinity Castle (2025) 4K Eng Audio - دبلجة إنجليزي`, Lionz supplied the correct TMDB ID `1311031`. Old automatic evidence scored the correct Infinity Castle result `78.158` and Mugen Train `22.667`; the low Mugen score did not cause ambiguity. Noise in the source title lowered the correct result into the ambiguous band. The current newer provider-ID suffix validator accepts Infinity Castle at `95`, so the visible ambiguous state is stale. Separately, manual search returns up to 20 TMDB rows in provider order, calculates a score, but the UI neither displays that score nor separates validated, plausible, and irrelevant results. Mugen Train appears because TMDB returned a franchise-related raw result, not because CP considered it a credible rival.
14. **`Run next 100` is a pilot safety control, not acceptable production onboarding.** A normal CP user who adds an IPTV provider should not need to understand enrichment batches or repeatedly press a developer-oriented button. Raw provider movies must become browseable as soon as their bounded local projection is available, then improve continuously and quietly in the background. The current first-open projection opacity and manually repeated 100-source workflow do not satisfy that product contract.
15. **The current enrichment detail path mutates raw provider state.** `enrich_source()` calls the ordinary provider `detail()` owner, which caches newly fetched provider detail into `iptv.sqlite`. That contradicts the intended projection/enrichment read boundary and must be replaced with a non-caching enrichment retrieval path.
16. **Schema version 1 cannot express the production dashboard contract.** It has no parser/matcher version per source, terminal evaluation version, durable projection progress, consent/restart policy, work deduplication key, or robust worker lease/heartbeat. Its accepted identities and manual decisions remain valuable and must migrate forward.
17. **Current worker ownership is process-memory dependent.** An in-memory process dictionary and PID are insufficient for restart, stale-process, or multi-process reconciliation. The current global limit of one also means providers are isolated but may wait for shared resource capacity; the UI must state that honestly.
18. **The historical clean-worktree gate is no longer usable literally.** The current checkout contains unrelated Dante-owned protected changes. Zero regression must be proved as no additional protected delta relative to a freshly captured dirty baseline, never by resetting the repository.
19. **`movies.sqlite` is not fully disposable after user decisions exist.** Manual matches, manual-unmatched locks, review decisions, consent, and grouped continuity facts cannot be reconstructed solely from raw provider data and the IPTV TMDB credential. Repair must distinguish durable and derived tables.
20. **Arabic-original movies need original-language-aware presentation.** The observed Arabic/Egyptian movie `Alwad syd alnasab` is correctly matched but displays an English transliterated title and English plot. For an accepted movie whose TMDB `original_language` is Arabic, the provider-local `ar-SA` snapshot should be the default presentation with a transient English switch; this must not affect identity acceptance.
21. **The card currently duplicates metadata status and promotes an irrelevant file fact.** A matched IPTV movie shows a grey `Matched` chip while collapsed and adds a second green `Matched` badge when expanded. It also renders `MKV` on nearly every card even though IPTV container extension is only a playback implementation fact, not useful library metadata.

### 23.2 Accepted decisions

1. The observation phase is complete for this action plan. Resolve systemic ownership and architecture problems through the consolidated gates rather than isolated hotfixes.
2. Repair systemic ownership and relationship problems at their authoritative IPTV owner.
3. Matching and ownership lookup are separate phases. Ownership never increases match confidence and never changes the accepted TMDB candidate.
4. After a TMDB ID is accepted, IPTV may batch-read CP canonical data for the bounded visible page through the strict boundary in Section 12.
5. Reuse eligible canonical metadata and existing local poster or portrait files without copying canonical rows or artwork into Lionz or EgySat storage.
6. Lionz and EgySat retain fully separate sources, match decisions, metadata snapshots, lists, favorites, history, worker state, and databases.
7. Provider-local TMDB and raw provider data remain sufficient fallbacks when CP has no owned match, lacks a field or asset, or cannot be read safely.
8. No CP canonical SQL row, schema, generation, cache, asset relationship, or protected owner may be changed by IPTV work.
9. Add a provider-scoped IPTV `Metadata` tab as the progress, control, and identity-review center for IPTV Movies. CP Library Maintenance is a product-design reference only; the IPTV tab must not call, import, mutate, or depend on CP Maintenance backend state, routes, catalog owners, Smart Match state, or TMDB credential.
10. Preserve every valuable schema-version-1 accepted match, manual lock, stored TMDB snapshot, list/favorite/history fact, and completed evaluation through the schema-version-2 migration. Do not delete the first 200 processed results or blanket-rematch them.
11. Automatically prepare provider-local raw Movies after sync without TMDB, but require one clear provider consent before continuous TMDB enrichment.
12. After consent, continue in bounded units beyond 100 sources. `Run next 100` is diagnostic only.
13. Initially preserve restart checkpoints and require a visible continue action rather than silent auto-resume.
14. Arabic-original matched movies default to provider-local TMDB `ar-SA` presentation, expose a transient English switch, and link primarily to TMDB. Localization never changes matching.
15. IPTV movie cards show metadata state once. `Matched` is one green badge in collapsed and expanded states, and container/file extensions are not rendered on the card.

### 23.3 Proposed workstreams after explicit implementation approval

These workstreams preserve the detailed reasoning gathered during trials. Section 15 is the authoritative execution order and resolves any older wording conflict in this section.

#### A. Restore provider-local relationship integrity

- Replace destructive shared-parent replacement with conflict-safe updates at the existing IPTV movie-store owner.
- Rebuild missing genre, people, keyword, and collection relationships from already stored raw TMDB snapshots where possible, without new TMDB calls.
- Repair one provider at a time in bounded transactions with before/after integrity evidence and a provider-local backup.
- Prove repeated enrichment of different movies cannot delete earlier relationships.

#### B. Establish one IPTV movie-detail presentation contract

- Return complete provider-local directors, top cast, roles, characters, person IDs, and portrait references from the authoritative IPTV detail projection.
- Remove the inferior route-specific people rendering after a safe replacement is selected.
- Match the desktop CP expanded-card behavior without invoking CP's TMDB credential.
- Do not persist biographies by default. Biography retrieval, filmography behavior, and credential ownership remain an explicit open decision.

#### C. Add the canonical read-only overlay

- Implement one IPTV-owned, failure-safe adapter that opens the active canonical database with `mode=ro` and `query_only=ON`.
- Query accepted movie and person TMDB IDs in bounded batches; prohibit per-card `N+1` catalog reads.
- Overlay only eligible canonical fields and local asset references, with explicit provenance and deterministic fallback rules.
- Serve an eligible existing artwork file through an IPTV-owned read-only resolver that validates checksum and managed-root containment.
- Treat missing databases, schema differences, locked files, missing assets, and read errors as an empty overlay rather than an IPTV failure.

#### D. Make first-open provider projection honest

- Expose provider-local projection state separately from TMDB enrichment state.
- Never show an empty, finished-looking Movies grid while projection is active.
- Provide a clear Preparing provider movies state with progress or honest indeterminate activity, failure details, and retry.
- Permit only one projection per provider and prevent a late response from a previously selected provider from publishing into the current view.
- Preserve bounded SQL and browser paging; never load the complete 20K or 40K catalog into the browser.
- Perform no TMDB requests during raw projection.

#### E. Continue matcher trials before changing global rules

- For each reported matched or unmatched example, record the raw provider title, parsed title/year, provider-supplied TMDB ID if present, stored TMDB candidate, evidence used, and rejection reason.
- Classify each failure as provider-data error, parser failure, candidate-search failure, validator failure, relationship-projection failure, or UI projection failure.
- Change shared parsing or matching rules only after several examples demonstrate one safe general pattern.
- Use one authoritative title/year parser for provider-ID validation, automatic title/year search, and manual search so the same source produces the same query tuple in every path.
- Treat the raw catalog title and provider-detail title as auditable aliases rather than allowing a differently formatted detail title to silently degrade a cleaner catalog title.
- Strip a bare terminal release year only under safe evidence, such as equality with the explicit or already extracted provider year and the presence of a non-year title. Preserve numbers that are part of the actual title.
- Record provider-ID validation evidence separately from fallback-search evidence so a future unmatched diagnosis can show exactly which phase rejected the identity and why.
- Preserve strict automatic thresholds, manual locks, unmatched visibility, and provider metadata playback fallback.

#### F. Add a bounded multilingual search protocol

- Parse each provider title into structured evidence: release year, Latin-script title segments, Arabic-script title segments, quality tags, language/audio/subtitle labels, edition text, and other provider noise.
- Preserve the raw title for display and audit. Never treat the destructive cleaned string as the only source of truth.
- Validate a provider-supplied TMDB ID against every credible parsed title alias and the year before performing fallback search.
- When fallback search is required, use a bounded ordered ladder and stop early only on strong validated evidence:
  1. primary Latin title alias with year;
  2. primary Arabic title alias with year;
  3. other credible parsed aliases with year;
  4. repeat the credible aliases without a year only when year-filtered searches return no usable candidate;
  5. enrich only a small top set with TMDB details and alternative titles, merge by TMDB ID, then score every candidate against every parsed alias and the year.
- Never search quality, codec, resolution, dubbed, subtitled, translated, language, or playlist-label tokens as part of the movie title.
- Cap query variants, candidates, and detail calls; deduplicate TMDB IDs across every search attempt; record which alias and search phase produced each candidate.
- A single returned result is evidence, not proof. Automatic acceptance still requires the strict identity/year validator and absence of a credible rival.
- Weight distinctive sequel or installment tokens such as `Infinity Castle` and `Mugen Train` more strongly than shared franchise prefixes such as `Demon Slayer: Kimetsu no Yaiba`. Missing or conflicting installment tokens are strong negative evidence.
- Treat a conflicting known release year as strong negative evidence. A franchise-relative result from 2020 must not rival an exact-title 2025 candidate merely because both share franchise words.
- A confidently accepted sibling source from the same provider may supply a candidate ID for validation, but never authorize acceptance without validating the target source's aliases and year.
- Return explicit result classes to the manual UI: validated recommendation, plausible review result, and low-relevance provider result. Show the evidence score, matching alias, year agreement, and rejection warnings.
- Keep low-relevance TMDB rows available only behind an explicit `Show other TMDB results` affordance for deliberate manual correction; do not give them equal visual weight or imply that they caused ambiguity.

#### G. Consider IPTV Match by AI as an explicit review tool

- CP's existing Match by AI does not let AI choose or apply an identity directly. Ollama proposes a canonical title, year, and up to three aliases; deterministic provider search and ranking produce candidates; the user reviews and explicitly applies selected proposals.
- Do not call or import CP's existing route directly for IPTV. It is coupled to library filesystem records, CP Smart Match state, the CP TMDB credential, and protected `app.py` owners.
- If approved, implement the same safety contract inside IPTV-owned files: AI may propose structured title/year/alias queries only; IPTV's isolated TMDB client performs candidate lookup and deterministic validation using only the IPTV credential.
- Never accept a TMDB ID invented by the model. The ID must come from the IPTV TMDB client's search or provider-ID validation and pass the normal matcher.
- Default AI use to an explicit `Match by AI` action on selected unmatched cards or a small review batch. Do not send the full 20K or 40K provider catalog to AI and do not make AI a required background enrichment dependency.
- Show the raw provider title, AI-proposed queries, TMDB candidates, evidence score, runner-up gap, and fallback warnings before any apply action.
- If AI is unavailable, times out, returns invalid JSON, or proposes unusable queries, retain deterministic search/manual matching and leave the movie visible and playable.
- If AI is implemented, use IPTV-owned AI configuration and state. Do not read, call, import, or depend on CP Maintenance/Smart Match configuration, routes, persistence, or TMDB credential.

#### H. Replace pilot batching with production progressive onboarding

- Keep `Run next 100` only as a development, diagnostic, or explicitly selected pilot action. It must not be the default production journey for a newly added provider.
- Separate three provider-local stages in state and UI:
  1. provider catalog synchronization;
  2. local Movies projection and grouping, with no TMDB calls;
  3. optional TMDB identity and metadata enrichment.
- Publish bounded raw provider movie pages as soon as projection makes them queryable. Never wait for the complete TMDB enrichment run before showing the Movies catalog, and never show a false empty finished state.
- Raw cards are not fake placeholders. They retain truthful provider title, year, artwork, source, playlist, playback, lists, favorites, and history. Display a quiet `Preparing metadata`, `Unprocessed`, or equivalent state until identity work completes.
- After the IPTV metadata credential is configured and the user opts into enrichment, run the provider-local queue continuously in the isolated worker until it completes, pauses, is cancelled, loses authorization, or reaches a recoverable service backoff. Do not require another click every 100 sources.
- Retain bounded internal units even during a full run: small network work units, one-movie relationship transactions, bounded commits/generation updates, durable checkpoints, and responsive pause/cancel. Removing the user-facing 100 stop must not create one 40K transaction.
- Prioritize the current visible bounded page and newly added provider sources, then continue through the durable backlog fairly so older rows cannot starve. Deduplicate work by accepted provider TMDB ID and normalized title/year query before making network requests.
- Quietly replace a raw card with the accepted enriched projection after a committed generation change. Preserve scroll position, filters, paging, expanded-card state, selected provider, source choice, list state, and playback; do not clear or flicker the grid.
- If no safe match is found, the movie remains permanently visible and playable with provider metadata and an honest unmatched/ambiguous badge. Background completion does not mean forcing every source into a TMDB identity.
- Show ordinary product language rather than implementation controls: `Preparing provider movies`, `Improving movie metadata`, processed/remaining counts, current backoff or failure, Pause, Resume, and Cancel. Advanced pilot controls may live behind an explicit diagnostic surface.
- Full enrichment is provider-by-provider. Adding or enriching Lionz never starts, publishes, merges with, or modifies EgySat, and vice versa. Under the initial one-worker global scheduler, one provider may wait visibly for capacity while the other runs; waiting is resource scheduling, not shared provider state.
- Restart recovery preserves durable provider-local checkpoints and initially waits for a visible user continuation action. It never silently falls back to CP's TMDB credential.

#### I. Add the provider-local Metadata dashboard

- Add `Metadata` immediately after `Movies` in the desktop IPTV navigation: `Home | Live TV | Movies | Metadata | Series | Favorites | My Lists`.
- The selected provider remains the complete scope. Lionz and EgySat have separate dashboards, progress counters, queues, review decisions, failures, checkpoints, and controls.
- Visiting the Metadata tab is never required for normal background progress. It is an observability, control, and review center rather than the enrichment engine's ignition key.
- Make one durable enrichment progress bar the visual center of the page. It must remain visible above secondary statistics and review queues.
- The primary label must be explicit, for example `200 of 40,788 provider sources evaluated (0.49%)`. Never label provider sources as unique movies.
- Show unique outcomes separately: grouped movie cards, distinct TMDB movies, matched sources, matched unique movies, manual matches, ambiguous, unmatched, failed, retrying, stale-rule results, and remaining sources.
- Define `evaluated` as a terminal decision under the current matcher-rule version: matched automatically, matched manually, ambiguous, unmatched, or terminally failed. Pending, running, retryable-error, stale-rule, and unprocessed rows do not count as complete.
- A grouped or deduplicated work item may advance several source rows after each source is independently validated. Progress may jump by more than one, but the committed numerator must never exceed the eligible available-source denominator.
- Render the progress bar as outcome segments where legible: accepted, needs review, unmatched, failed, and remaining. Segment colors and text must not imply that `evaluated` means `matched`.
- Show the active provider, worker state, current phase, processed and remaining counts, recent processing rate, last committed checkpoint, and current retry/backoff reason next to the bar.
- Do not invent an exact ETA. Show an ETA range only after a stable measured sample; otherwise display `Estimating after more progress` or omit it.
- Provider sync, local projection, and TMDB enrichment have separate progress/state surfaces. Never reuse one percentage across stages with different denominators.
- Persist progress in provider-local SQL rather than browser state. Reloading the page, switching tabs, closing the workspace, or restarting according to the approved policy must recover the same committed progress.
- If a provider sync adds new sources, the denominator may increase and the percentage may decrease. Explain this honestly as new provider items discovered rather than hiding or freezing the denominator.
- Controls include Start/Continue all, Pause, Resume, Cancel future work, Retry failures, and Re-evaluate stale automatic results. `Cancel` preserves raw sources, completed matches, metadata, lists, favorites, history, and committed progress.
- Provide bounded subviews: `Overview`, `Needs review`, `Unmatched`, `Failed`, and `Manual matches`.
- Review rows show raw provider title, parsed aliases/year, provider-supplied TMDB ID, proposed identity, matching evidence, conflicts, same-provider sibling sources, and available actions.
- Smart Match runs only on explicitly selected unmatched or ambiguous provider-local movies, produces a preview, and requires deterministic IPTV TMDB verification before an apply action. It never uses CP Maintenance routes, CP Smart Match persistence, filesystem paths, or CP's TMDB credential.
- Keep advanced diagnostic controls such as `Run next 100` outside the ordinary dashboard journey.

### 23.4 Remaining decision gates that do not block the core migration

1. Before optional CP overlay implementation, which exact canonical fields may override provider-local TMDB fields? Until approved, limit the proposed overlay to ownership and eligible existing local artwork.
2. Biographies are omitted from the first IPTV rich-people implementation. A later IPTV-owned live or cached biography contract requires separate approval.
3. People without existing CP portraits use TMDB remote profile references initially. A provider-local portrait-download cache is a later optional decision and must not block identity enrichment.
4. The multilingual ladder is implemented for new automatic evaluations, but already completed automatic unmatched/ambiguous rows are re-evaluated only through an explicit provider-local stale-results action after disposable validation.
5. IPTV Match by AI is optional and deferred from the core path. If reopened, decide whether it remains card-by-card or also supports a small selected batch; the first version still requires preview and explicit apply.
6. Increasing global TMDB worker concurrency or changing the visible-confirmation restart policy requires measured production evidence and separate approval.

### 23.5 Required regression coverage for the combined resolution

- Two movies sharing a genre, person, keyword, or collection retain both relationships after repeated saves and rebuilds.
- Existing affected raw snapshots can reconstruct relationships without a TMDB request.
- Manual match, correction, removal, and grouping behavior remains provider-local and deterministic.
- Ownership does not influence candidate acceptance or confidence.
- `Balan - The Boy ( 2026 )` from the raw catalog and `Balan - The Boy 2026` from provider details produce the same normalized title `balan the boy` and year `2026` in provider-ID validation, automatic search, and manual search.
- `The Truthers ( 2026 )` from the raw catalog and `The Truthers 2026` from provider details likewise produce title `the truthers` and year `2026` through every match path.
- `Demon Slayer: Kimetsu no Yaiba Infinity Castle (2025) 4K Eng Audio - دبلجة إنجليزي` validates TMDB `1311031` after removing source/audio labels, while `Demon Slayer: Kimetsu no Yaiba - The Movie: Mugen Train (2020)` is rejected as a credible rival because its distinctive installment tokens and year conflict.
- Manual search presents Infinity Castle as the validated recommendation and places Mugen Train under clearly labelled low-relevance results rather than displaying both with equal `Use this match` prominence.
- Year-bearing titles remain intact: `1917 (2019)`, `2001: A Space Odyssey (1968)`, and `Blade Runner 2049 (2017)` remove only the release-year decoration and preserve the year that belongs to the title.
- One correct result may be accepted automatically only when it still passes the strict identity and year rules; candidate count alone never authorizes a match.
- `Merry Little Batman ميلاد سعيد باتمان الصغير (2023) (مدبلج)` produces separate English and Arabic title aliases, year `2023`, and a dubbed tag excluded from every TMDB query.
- The stored provider ID `870358` validates against a credible parsed alias under the current rule, while an incorrect ID with a superficially related Batman title is rejected.
- English-only, Arabic-only, bilingual, reversed-script-order, dubbed, translated, and subtitled fixtures converge on the same candidate without lowering thresholds.
- An accepted Arabic-original movie stores `original_language=ar`, defaults to its IPTV-owned TMDB `ar-SA` display snapshot, switches transiently to English, falls back field-by-field when Arabic data is missing, and links to TMDB regardless of current display language.
- A non-Arabic accepted movie keeps English/base display, exposes the explicit Arabic switch, links to IMDb only when a valid IMDb ID exists, and otherwise links to TMDB.
- Collapsed and expanded matched-card fixtures contain exactly one visible green `Matched` badge and never duplicate the state label during expansion.
- IPTV movie cards never render `MKV`, `MP4`, or another container/file-type badge, while playback retains the source extension internally.
- Matcher-rule version changes identify eligible stale automatic unmatched/ambiguous rows for bounded re-evaluation while preserving manual locks and provider isolation.
- AI output cannot apply a match, supply a trusted TMDB ID, use CP's TMDB credential, or bypass the deterministic identity/year validator.
- Invalid, unavailable, slow, or hallucinated AI output falls back without changing the source's accepted identity or playability.
- A newly added 20K or 40K provider presents bounded raw movie pages before enrichment completes, then upgrades visible cards quietly as accepted metadata commits.
- A full background run crosses more than 100 sources without another user action while retaining bounded commits, checkpoints, pause/cancel responsiveness, and provider isolation.
- Foreground browsing, playback, manual matching, Live TV, and Series remain responsive during continuous enrichment; the current visible movie page receives priority without starving the remaining backlog.
- Closing and reopening the Movies workspace preserves progress and never returns to a false empty grid; the approved restart policy resumes or clearly offers continuation from the durable checkpoint.
- Metadata navigation and every dashboard query/control remain scoped to the selected provider and cannot publish or mutate another provider's progress or identities.
- The durable progress numerator counts only current-rule terminal source decisions, never exceeds the eligible denominator, and survives reload, tab switching, pause/resume, cancellation, provider switching, and the approved restart behavior.
- Matched, manual, ambiguous, unmatched, failed, retrying, stale, unprocessed, source-total, and unique-movie counters reconcile to their documented SQL definitions; `evaluated` never masquerades as `matched`.
- Adding new provider sources can increase the denominator and lower the displayed percentage without losing committed work; the UI explains the change.
- Cancelling from Metadata stops future claims while preserving all completed matches, provider metadata, raw playability, lists, favorites, history, and checkpoints.
- IPTV Smart Match preview and apply operate entirely through IPTV-owned routes, provider-local movie keys, IPTV SQL, and the IPTV TMDB credential; protected CP Maintenance behavior and data remain unchanged.
- Canonical overlay queries are bounded, read-only, and leave CP schema, data, generations, WAL/sidecars, caches, and asset relationships unchanged.
- Missing or unreadable CP canonical data produces a normal provider-local IPTV card.
- Local artwork is served without a CP catalog write; missing files fall back safely.
- Expanded IPTV cards display director and top-cast portrait cards using IPTV-owned data and credential boundaries.
- Slow 20K and 40K first projection, refresh, failure/retry, cancellation boundaries, and provider switching cannot show a false empty completion or stale provider results.
- Lionz and EgySat metadata, sources, lists, history, databases, and worker state never mix.
- Live TV, Series, Library, Discover, Movie Lists, people, artwork, playback, and all protected non-IPTV workflows retain parity.

### 23.6 Approval gates after consolidation

1. This document now records the completed design discussion and consolidated action sequence.
2. Before implementation, present the exact IPTV-owned file manifest and the disposable schema-migration/relationship-repair rehearsal procedure.
3. Wait for explicit implementation approval covering a named set of gates; plan approval alone is not implementation approval.
4. Separately obtain approval before touching either live provider database, starting projection/enrichment, restarting CP, or performing any Git/release/publication action.
