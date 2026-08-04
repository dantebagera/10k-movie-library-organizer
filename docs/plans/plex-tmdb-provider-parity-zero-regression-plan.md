# Plex/TMDB Metadata Provider Parity: Zero-Regression Plan

- **Status:** Saved for discussion and handoff only. Implementation is not authorized and has not started under this plan.
- **Last reviewed:** 2026-08-04
- **Repository:** `C:\Users\dante\Desktop\cinema paradiso`
- **Observed branch:** `master`
- **Product surface:** Cinema Paradiso desktop Library, Movie View, File View, Settings, Correct metadata, and Unmatched review.
- **Primary backend owners:** metadata authority/provider selection in `app.py`, provider ingestion in `app.py`, `AppMetadataStore`, `services/catalog_repository.py`, and `services/canonical_catalog.py`.
- **Primary frontend owners:** Settings metadata authority UI, `src/components/MetadataCorrectionModal.jsx`, Unmatched/Maintenance workflows, and the shared card contract in `src/components/SharedMovieCards.jsx`.

This document is the planning contract. It does not authorize application-code changes, catalog writes, schema migration, a live Plex mutation, process restarts, Git staging, commits, or publication. Every implementation gate must preserve the existing dirty worktree. Any live catalog backfill requires a separate explicit approval after isolated rehearsal and rollback proof.

## 1. Goal

Give Cinema Paradiso users the same product experience whether their automatic metadata provider is TMDB or Plex.

"Same experience" means:

1. The same Movie View card structure and controls.
2. A poster, title, year, plot, genres, rating, language/country when supplied, director, and available top cast.
3. The same expanded-card people layout and person interactions where provider identifiers permit them.
4. The same Correct metadata workflow.
5. The same Unmatched recovery workflow.
6. The same manual-lock and provider-ownership guarantees.
7. No requirement for a TMDB API key when Plex is the selected provider.
8. No requirement for Plex when TMDB is the selected provider.

Provider parity does **not** mean that Plex and TMDB must return identical values or identical optional fields. Cinema Paradiso must normalize both providers into one card contract while honestly displaying only the data supplied by the accepted provider.

The product principle is:

> One automatic primary provider, one accepted provider owner per movie, one normalized card contract, and both configured providers always available for deliberate manual recovery.

## 2. Confirmed planning baseline

These facts were measured during planning and must be verified again at Gate 0.

### 2.1 Historical provider behavior

- Cinema Paradiso previously used Plex as its active metadata provider.
- The live metadata authority record currently says `previous_provider: plex` and `active_provider: tmdb`.
- The completed Plex-to-TMDB migration recorded 3,445 matched files, 171 review files, and zero failed files.
- The pre-SQL v2.7 path converted a stored `plex_thumb` into an authenticated poster URL before building the card and passed Plex directors/cast through the in-memory provider payload.
- The current SQL path persists provider snapshots before that historical poster conversion, and the relational projector expects `plex_poster` rather than the stored `plex_thumb`.

This is therefore a parity-restoration task, not a new Plex feature bolted onto TMDB behavior.

### 2.2 Current live Plex projection failure

Planning-time SQL evidence showed:

- 5 files currently select Plex as their accepted display provider.
- 5/5 have a Plex provider snapshot.
- 0/5 project a poster.
- 2/5 project any cast, and those two project only three cast members.
- The remaining Plex-selected files have empty or missing people projections.

At the same time, the raw Plex cache contained:

- 3,808 Plex file rows.
- 3,806 rows with a Plex thumbnail.
- 3,783 rows with cast.
- 3,793 rows with directors.

The dominant failure is therefore ingestion/projection parity, not absence of metadata from Plex.

### 2.3 The Abandon acceptance fixture

The file:

`E:\Movies\The Abandon (2022) [1080p] [WEBRip] [5.1] [YTS.MX]\The.Abandon.2022.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4`

is the primary real-world acceptance fixture.

Its current CP state is internally inconsistent:

- Selected provider: Plex.
- Plex rating key: `9956`.
- Correct Plex title/year: `The Abandon` (2022).
- Stale TMDB/IMDb identity retained from another movie: TMDB `1006763`, IMDb `tt22742070`.
- Current projected poster: empty.
- Current projected director/cast: empty.

The detailed Plex endpoint `/library/metadata/9956` supplies:

- Title/year: `The Abandon` (2022).
- Poster thumbnail path.
- Plot and genres.
- Director: Jason Satterlund.
- Five cast members: Jonathan Rosenthal, Tamara Perry, Regis Terencio, Dan Kyle, and Priscilla Avila.
- Correct external cross-references: IMDb `tt10273738`, TMDB `933088`, TVDB `357692`.

The completed Plex-owned card must therefore show one director plus five actors without making a TMDB API call.

### 2.4 Existing provider infrastructure to preserve

Cinema Paradiso already has:

- TMDB/Plex/filename provider availability state.
- A locally persisted active metadata provider.
- Per-file accepted-provider state.
- Manual provider locks.
- Provider movie snapshots.
- Relational people and movie credits.
- Shared Movie View card projection.
- Correct metadata searches for TMDB and Plex.
- Unmatched searches for TMDB and Plex.
- A Plex library refresh action.
- Migration and catalog backup tooling.

The implementation must repair these authoritative owners. It must not add a second provider-selection system, a route-specific card patch, or a separate Plex-only UI.

### 2.5 Dirty-worktree protection

The checkout is already heavily dirty with unrelated ingestion, startup, frontend, testing, and release work. `app.py` is modified, although the currently diagnosed Plex match block was not changed in the inspected diff.

Before implementation:

1. Recheck `git status --short --branch` using a command-scoped safe-directory override.
2. Capture path-scoped diffs for every planned file.
3. Preserve all unrelated modifications and untracked files.
4. Do not reset, discard, stage, commit, or reformat unrelated work.
5. Stop if the target owner has materially changed since this plan was saved.

## 3. Non-negotiable product contract

### 3.1 Provider availability and primary selection

| Available providers | Required automatic primary behavior |
| --- | --- |
| TMDB only | Select TMDB automatically. |
| Connected/authenticated Plex only | Select Plex automatically. |
| Both TMDB and Plex | Require an explicit user choice if no primary has been saved. |
| Neither | Use File View and unresolved/filename state; do not fabricate rich Movie View cards. |

"Plex installed" is not sufficient by itself. CP must have a working Plex URL and authorization token. Onboarding may detect the local server, but it must not pretend it is usable until authentication succeeds.

When both providers become available and a valid primary is already saved, CP must preserve that choice. Connecting the secondary provider must not interrupt the user or silently change the primary.

### 3.2 Primary-provider responsibility

The primary provider:

- automatically searches for newly discovered movies;
- owns automatic metadata hydration for those movies;
- saves the accepted provider snapshot;
- retries its own transient failures;
- does not silently hand an unmatched file to the secondary provider.

If the primary is unavailable or cannot identify a file, the file remains pending/unmatched with an honest status. The user may then deliberately choose either configured provider through Unmatched or Correct metadata.

Changing the primary affects future and unresolved movies only. It must not rewrite existing accepted movies. Existing-library provider conversion remains a separate explicit migration operation.

### 3.3 Per-movie ownership

Every accepted Movie View item has one selected metadata owner: TMDB or Plex.

- The selected provider supplies all displayed provider metadata.
- External IDs supplied by that provider may be stored as cross-references and ownership keys.
- External IDs must not cause fields from the nonselected provider to leak into the displayed card.
- A manual match creates a manual lock.
- Automatic scanning must not replace a manually locked identity.
- Switching a movie from one provider to another must replace incompatible identity fields atomically.
- Stale TMDB/IMDb/Plex identifiers from the previous accepted identity must not survive unless the newly accepted provider independently supplies the same identifier.

### 3.4 Common card contract

Both provider snapshots normalize into the same card contract:

| Field | TMDB owner | Plex owner | Required behavior |
| --- | --- | --- | --- |
| Title/year | TMDB details | Plex item details | Required for accepted Movie View publication. |
| Poster | TMDB poster | Plex thumb/art | Required unless the provider genuinely has no art. |
| Plot | TMDB overview | Plex summary | Display when supplied. |
| Genres | TMDB genres | Plex genres | Display when supplied. |
| Rating | TMDB vote average/count | Plex rating/audience rating | Provider-labelled semantics; do not mislabel Plex ratings as TMDB votes. |
| Language/country | TMDB fields | Plex fields | Display when supplied. |
| Director | TMDB credits | Plex Director entries | Same people-card layout. |
| Cast | TMDB credits | Plex Role entries | Same people-card layout, bounded by the shared UI limit. |
| Person portrait | TMDB profile | Plex person art | Use a safe CP asset/proxy reference. |
| External IDs | TMDB details | Plex Guid entries | Cross-reference only; they do not change the selected provider. |
| Optional fields | TMDB-specific | Plex-specific | Missing optional fields remain absent; do not silently query the other provider. |

Provider-specific data differences are acceptable. Empty fields caused by CP dropping available provider data are not acceptable.

### 3.5 Correct metadata contract

Correct metadata remains provider-independent:

- Show TMDB search when TMDB is configured.
- Show Plex search when Plex is connected and indexed.
- Show both when both are available, regardless of the automatic primary.
- Applying a result selects that provider for the movie and creates a manual lock.
- Applying a result must produce a complete provider snapshot before publication.
- A sparse match candidate must never overwrite a richer same-identity snapshot.
- Display-only title/year edits remain explicitly separate from provider identity correction.

Open design question for implementation Gate 0:

> When a chosen Plex match GUID differs from the identity currently applied by the Plex server, can CP retrieve a complete detail record for that candidate without mutating Plex?

The implementation must prove the answer from the Plex API. It must not silently mutate the user's Plex server. If full candidate details require applying the match in Plex, that external mutation needs an explicit user-facing action and a separate approval/confirmation contract.

### 3.6 Unmatched contract

Unmatched recovery remains provider-independent:

- Search either configured provider.
- Searching the secondary provider does not change the global primary.
- Accepting a result changes only that file/movie.
- Files stay visible in File View throughout the workflow.
- Movie View publication occurs only after the accepted provider snapshot satisfies the final-card readiness contract.
- No automatic acceptance based solely on a loose title result or provider rank.

### 3.7 No-flicker publication contract

For newly discovered files and corrected identities, final Movie View publication remains:

1. Stable/readable file.
2. Physical file probe.
3. Accepted provider identity.
4. Complete selected-provider detail fetch.
5. Poster and required card metadata readiness.
6. Canonical provider projection.
7. One atomic SQL commit.
8. Catalog generation/event notification.
9. Quiet authoritative frontend refetch and asset preload.

Do not publish a partially hydrated Plex card and replace it later with a different layout.

## 4. Authoritative implementation direction

### 4.1 Provider selection owner

Keep one backend resolver for automatic provider selection.

The resolver should return one of:

- `tmdb`;
- `plex`;
- `filename`/no-rich-provider;
- `selection_required` when both providers are ready and no valid primary is saved.

The frontend onboarding/settings UI presents the required choice and persists it through the existing metadata authority owner. Do not encode an independent frontend default.

### 4.2 Plex summary versus detail ingestion

Use Plex's section listing only for bounded discovery and path/rating-key indexing.

For accepted card hydration, fetch the detailed item by rating key:

`/library/metadata/<rating_key>`

Normalize the detailed record into one Plex snapshot containing:

- provider identity and external IDs;
- title/year;
- summary, genres and rating;
- poster/art references;
- language/country;
- directors;
- cast;
- provider timestamps/revision evidence.

Do not treat the abbreviated `/library/sections/<id>/all` people list as proof that the detailed Plex record contains only those people.

### 4.3 Plex artwork safety

- Persist stable Plex artwork references, not URLs containing the Plex token.
- Convert relative Plex paths into a tokenless CP endpoint such as `/api/plex/image?path=...` at projection time.
- Define a restricted and tested strategy for Plex-hosted absolute artwork/person URLs.
- Do not create an open proxy.
- Do not expose the Plex token in browser payloads, SQL, logs, test artifacts, or generated documentation.
- Preserve the existing local-artwork override and asset-retention rules.

### 4.4 Snapshot completeness and replacement

A provider snapshot write must be transactional and completeness-aware.

- A full detailed snapshot may replace an older snapshot for the same provider identity.
- A sparse search candidate may not erase poster, credits, genres, IDs, or other fields from a richer same-identity snapshot.
- A genuinely different provider identity must not inherit fields from the previous identity.
- Detail and people states must reflect the normalized stored fields rather than merely the existence of a provider row.
- The canonical projector reads one selected snapshot and its relational credits/assets.

### 4.5 SQL/schema strategy

No schema change is expected at planning time. Existing tables already represent:

- canonical movies and files;
- provider snapshots;
- people and credits;
- genres and collections;
- artwork assets;
- overrides;
- identity decisions.

Prefer correcting current import, normalization, and projection owners. If implementation discovers that schema 10 cannot represent the required Plex detail contract without duplication or ambiguous ownership, stop and produce a separate migration proposal before editing the schema.

## 5. Gates

### Gate 0 - Fresh read-only audit and decision closure

No writes.

Required evidence:

1. Current branch, remote, dirty worktree and target diffs.
2. Current backend process and served frontend bundle.
3. Provider configuration and saved authority state without exposing credentials.
4. Current counts for TMDB-selected, Plex-selected, unresolved and manually locked files.
5. Raw Plex summary/detail comparison for a bounded fixture set.
6. Exact provider availability/selection UI behavior on a clean isolated profile.
7. Whether a different Plex match candidate can be fully hydrated without mutating Plex.
8. Exact SQL tables and foreign-key relationships touched by reprojection.
9. Final list of files proposed for implementation.

Stop and discuss any contradiction before Gate 1.

### Gate 1 - Provider-choice contract in isolated tests

No live catalog writes.

Implement and verify:

- zero/one/two-provider selection matrix;
- explicit `selection_required` behavior;
- local primary persistence;
- no silent primary switch when a secondary provider is added;
- changing primary affects only future/unresolved work;
- provider-unavailable status without silent fallback;
- Settings/onboarding desktop UI only.

### Gate 2 - Complete Plex detail normalization and card projection

No live catalog writes.

Implement against isolated `CP_TEST_MODE=1` and a unique verified `CP_TEST_ROOT`:

- summary discovery by section/path/rating key;
- bounded detailed item fetch;
- complete Plex snapshot normalization;
- safe poster/person artwork projection;
- relational people/credit synchronization;
- rating semantics;
- completeness state;
- shared Movie View card parity.

Do not redesign mobile or unrelated Library UI.

### Gate 3 - Correct metadata and Unmatched parity

No live catalog writes.

Verify:

- both configured providers remain searchable regardless of primary;
- accepting TMDB produces a complete locked TMDB snapshot;
- accepting Plex produces a complete locked Plex snapshot;
- a sparse Plex search candidate cannot erase rich metadata;
- switching providers clears incompatible identity fields;
- display-only edits remain separate;
- no external Plex mutation occurs unless the explicitly approved design includes one.

### Gate 4 - Isolated catalog rehearsal

Use a copied catalog and copied user-data root only.

Rehearse:

1. Reprojecting existing Plex file rows through the corrected owner.
2. Hydrating Plex-selected fixtures from detailed Plex responses or recorded fixtures.
3. Preserving TMDB-selected movies byte-for-byte at the provider/card contract level.
4. Preserving manual locks, lists, playback history, overrides and file relationships.
5. Moving stale identity keys only when the accepted provider proves the replacement IDs.
6. Rollback from the rehearsal backup.

Produce a before/after parity report and stop for approval.

### Gate 5 - Live mutation approval gate

Do not enter this gate without Dante's explicit approval after reviewing Gate 4 evidence.

Before live writes:

- stop or coordinate the catalog writer safely;
- capture the exact database, WAL and SHM state as required by the existing backup owner;
- create a verified recoverable backup;
- record catalog generation and row counts;
- verify rollback on the rehearsal copy;
- enumerate the exact live records in scope.

### Gate 6 - Bounded live Plex reprojection

Only after Gate 5 approval.

- Apply the smallest authoritative write set.
- Do not bulk-delete/recreate unrelated provider data.
- Preserve TMDB snapshots that may be valid for other movies.
- Reproject accepted Plex movies transactionally.
- Increment catalog/asset generations only when their owned data changes.
- Emit one bounded catalog event/refetch signal.
- Immediately run integrity and parity checks.

### Gate 7 - Real runtime and rendered UI verification

Verification must include the normally served production bundle, not only isolated tests.

- Restart/reload only with explicit scope and process ownership confirmed.
- Verify the live served asset hash.
- Verify desktop Movie View with TMDB primary and Plex primary fixtures.
- Verify Correct metadata searches both providers.
- Verify Unmatched searches both providers.
- Verify no grid flicker during final-card publication.
- Verify browser/API timing separately from loading UX.
- Confirm no credentials appear in requests, HTML, logs or asset URLs.

## 6. Regression matrix

### 6.1 Provider availability

- Neither provider configured.
- TMDB only.
- Plex only.
- Both, no saved primary.
- Both, saved TMDB primary.
- Both, saved Plex primary.
- Primary temporarily unavailable.
- Secondary temporarily unavailable.

### 6.2 New-file ingestion

- TMDB-primary successful match.
- Plex-primary successful match.
- Primary returns no match.
- Primary provider times out.
- Secondary has a match but primary does not; no silent fallback.
- External file added while CP is running.
- File copied slowly and observed before stability.
- Duplicate and conflicting path/identity cases.

### 6.3 Provider correction

- TMDB to TMDB replacement.
- Plex to Plex same-identity refresh.
- Plex sparse candidate against rich same-identity snapshot.
- TMDB to Plex replacement.
- Plex to TMDB replacement.
- Incorrect stale external IDs.
- Manual lock survives startup/reconcile.
- Display-only override survives provider refresh appropriately.

### 6.4 Cards and details

- Poster from each provider.
- Missing-provider-art state.
- Director and 1/3/5/8 cast cases.
- Person portrait present/missing.
- Plot, genres, language and country.
- Correct provider-specific rating label.
- Expanded card and collapsed card.
- Poster override and reset.
- File View remains physical-file authoritative.

### 6.5 SQL safety

- `PRAGMA integrity_check` passes.
- `PRAGMA foreign_key_check` returns no rows.
- Canonical movie/file counts reconcile.
- Provider snapshot counts reconcile.
- People/credit orphan checks pass.
- Manual locks and identity decisions reconcile.
- Playback history movie/path relationships remain valid.
- Lists and ownership matching remain valid.
- No unintended TMDB-selected movie changes.
- Backup restoration reproduces the pre-write catalog.

## 7. The Abandon final acceptance

### Plex-owned acceptance

For rating key `9956`, without a TMDB API call:

- Selected provider remains `plex`.
- Title/year are `The Abandon` / `2022`.
- IMDb cross-reference is `tt10273738`.
- TMDB cross-reference is `933088` only because Plex supplied it.
- Poster renders through a safe CP/Plex asset URL.
- Plot and genres render.
- Jason Satterlund renders as director.
- Five actors render in Plex order.
- Expanded card shows six people total.
- Old TMDB `1006763` and IMDb `tt22742070` are no longer attached to this accepted identity.
- No token appears in the browser-visible URL or payload.

### Manual TMDB-switch acceptance

If the user deliberately chooses TMDB `933088` through Correct metadata:

- Selected provider changes only for this movie to `tmdb`.
- A complete TMDB snapshot becomes authoritative.
- A manual lock is stored.
- The global primary provider does not change.
- The Plex snapshot may remain available for future deliberate correction but does not contribute displayed fields.

## 8. Completion criteria

This plan is complete only when all of the following are true:

1. Provider choice follows the zero/one/two-provider contract.
2. The primary provider alone owns automatic new-movie matching.
3. Correct metadata and Unmatched continue to expose both configured providers.
4. Plex-only users receive complete Plex-owned cards without TMDB calls.
5. TMDB-only users retain existing behavior.
6. Both-provider users retain explicit control and no silent cross-provider fallback.
7. Existing manually locked movies remain stable.
8. Plex poster/director/cast data survives SQL ingestion and projection.
9. The Abandon passes the Plex-owned fixture contract.
10. The isolated backfill rehearsal, rollback rehearsal, SQL integrity checks, automated tests, production build, live API checks and rendered desktop checks all pass.
11. Dante explicitly approves any live catalog mutation after reviewing rehearsal evidence.

## 9. Explicit non-goals

- No mobile/responsive redesign.
- No general Library redesign.
- No custom metadata provider.
- No silent merging of TMDB and Plex fields.
- No automatic rewrite of existing accepted movies when the primary changes.
- No forced Plex-server metadata mutation without a separate explicit design and approval.
- No token-bearing Plex URLs persisted or exposed.
- No schema change unless Gate 0 proves it is unavoidable and a separate migration is approved.
- No staging, commit, push, release or publication under this planning-only task.

## 10. Discussion items deliberately left open

These decisions should be discussed before implementation:

1. Exact first-run wording and whether TMDB should be visually marked "recommended" while still requiring an explicit choice when both providers are ready.
2. Whether Plex detail hydration should be eager for accepted movies or queued with bounded concurrency before final publication.
3. How CP should obtain complete details for a Plex match candidate whose GUID differs from the Plex server's currently applied identity.
4. Whether fixing a match in the Plex server itself should ever be offered, and what confirmation is required.
5. The safe proxy/local-asset policy for absolute Plex-hosted person portraits.
6. Whether a Plex rating should display its source label explicitly in the shared card.
7. Whether existing Plex-selected records should be hydrated online during live backfill or only reprojected from already stored raw snapshots first.
