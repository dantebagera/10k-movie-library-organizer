# Writer and Keyword Search: Zero-Regression Implementation Plan

Status: approved for planning only; implementation has not started.

Scope:

- Add writers to People search in Library and Discover.
- Add Keywords as a third search mode in Library and Discover.
- Normalize only the writer and keyword data required for reliable search.
- Preserve `provider_movie_snapshots.source_json` as provider evidence and a rebuild source.
- Preserve every existing Cinema Paradiso workflow and page-specific card behavior.

This plan treats the SQL change as behavior-breaking until the evidence below proves otherwise.

## 1. Non-negotiable safety rules

1. Do not run broad tests, migrations, backfills, audits, or repair commands against the live `%LOCALAPPDATA%\Cinema Paradiso` catalogue.
2. Do not modify the schema until the current working application is represented by a verified Git checkpoint.
3. Do not combine schema migration, Library search, Discover search, and UI work into one implementation step or commit.
4. Do not remove or rewrite `provider_movie_snapshots.source_json`.
5. Do not introduce a second canonical catalogue, competing people store, route-specific SQL shortcut, or alternate search authority.
6. Library remains SQL-owned and must not contact TMDB while searching or expanding owned movies.
7. Discover remains TMDB-owned for remote results and uses local SQL only to attach ownership and locally persisted details.
8. Any unexplained count, field, ordering, integrity, performance, or user-visible difference blocks the next stage.
9. Any migration failure must roll back the whole migration. Partial success is failure.
10. A passing startup or a passing unit test is not sufficient acceptance evidence.

## 2. Confirmed current architecture and risk

- `services/catalog_store.py` owns the SQLite catalogue and currently declares catalogue schema version 7.
- `services/canonical_catalog.py` owns relational canonical movies, provider snapshots, people, movie credits, genres, and collections.
- `movie_credits.credit_type` currently has a SQLite check constraint allowing only `cast` and `director`.
- Adding `writer` therefore requires an explicit table-rebuild migration; changing Python constants alone is insufficient.
- Writers, certification, and keywords are currently projected from `provider_movie_snapshots.source_json`.
- Existing keyword snapshots currently preserve names, while writer objects preserve person information supplied by the TMDB-details transform.
- Library's current Movies mode searches more than titles: it includes title, year, filename, path, plot, and genres. That behavior must not be narrowed accidentally.
- Existing backup, restore rehearsal, catalogue audit, JSON-shadow comparison, fixture parity, and browser parity tools must be extended rather than replaced.

The worktree observed immediately before this plan was created was `master`, six commits ahead of `origin/master`, with many modified and untracked files spanning approved UI work, catalogue work, maintenance work, Settings/Ollama work, and tests. The exact state must be inspected again at execution time. Nothing may be committed blindly as one bundle.

## 3. Product contract

Both Library and Discover will expose three explicit modes:

| Mode | Library authority and behavior | Discover authority and behavior |
| --- | --- | --- |
| Movies | Preserve the current owned-catalogue movie-text behavior unless Dante separately approves a narrower title-only contract. | Search TMDB movies using the existing movie-search path. |
| People | Search actors, directors, and writers attached to owned movies. | Search TMDB people and resolve their movie credits by relevant role. |
| Keywords | Search normalized keywords attached to owned movies. | Resolve a TMDB keyword and discover movies using its TMDB keyword identity. |

People behavior:

- A person is deduplicated by stable TMDB person identity where available, not only by display name.
- One person may retain multiple roles: Actor, Director, and Writer.
- Writer eligibility initially follows the already accepted display contract: `Writer`, `Screenplay`, `Story`, and `Novel`.
- Existing actor and director results, order, portraits, role filters, and person-to-movie navigation must remain unchanged.
- A person result must expose the roles that caused the result to match.

Keyword behavior:

- Keywords are searchable entities, not an unstructured substring scan of `source_json`.
- TMDB keyword ID is authoritative where available.
- A normalized name key supports existing snapshots that currently contain only keyword names.
- Keyword matching is case-insensitive and deduplicated without destroying the provider's display name.
- Discover keyword resolution and movie discovery stay remote; the application does not persist the entire remote result set.

## 4. Gate 0: freeze and prove the current stable baseline

No feature implementation begins until this gate passes.

### 4.1 Inventory the worktree

- Record `git status --short --branch`.
- Record recent commits with dates.
- Inspect every modified and untracked file.
- Classify changes by feature and approval status.
- Do not discard, overwrite, stage, or commit any file without confirming its scope.
- Separate unrelated changes into logical checkpoints where possible.

### 4.2 Establish isolated test data

- Use temporary directories for `app._user_data_dir`, movie roots, repository caches, and database paths.
- Confirm that no test command resolves to the real Cinema Paradiso user-data directory.
- Add or strengthen a guard that makes broad tests fail before opening a database under the live user-data root.
- Provider calls must be mocked or blocked for owned-catalogue parity tests.

### 4.3 Run the baseline verification bundle

Run targeted tests first, then the complete suite:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_canonical_catalog tests.test_catalog_store tests.test_catalog_parity_audit tests.test_catalog_json_shadow_compare tests.test_sql_migration_parity
.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
node --test tests/*.test.mjs
npm.cmd run build
npm.cmd run test:e2e
```

If PowerShell wildcard behavior prevents the Node command from discovering tests reliably, enumerate the `.test.mjs` files with a safe repository-local command and record the exact executed list.

### 4.4 Capture baseline behavior

Record machine-readable and browser evidence for:

- Library card and expanded-detail contracts.
- Discover owned and unowned cards.
- Movie Lists cards.
- Home followed-movie inspector plots.
- AI Control requested cards.
- Existing actor/director People search in Library and Discover.
- Plots, posters, cast, directors, genres, collections, certification, writers, keywords, IMDb links, Arabic toggle, and page-specific ownership badges.
- Home statistics and Maintenance audit agreement before and after a catalogue mutation.
- Library paging, filtering, selection, query, expansion, and navigation-state preservation.
- Owned detail reads making zero provider calls.

### 4.5 Secure recovery artifacts

After the baseline is green and Dante approves the exact commit scope:

- Create the clean pre-search Git checkpoint.
- Create a catalogue backup with `tools/catalog_migration_backup.py backup`.
- Verify it with `tools/catalog_migration_backup.py verify`.
- Restore it into a new empty rehearsal directory with `tools/catalog_migration_backup.py restore`.
- Build/open a shadow catalogue from the restored data.
- Run SQL integrity, foreign-key, canonical parity, and JSON-shadow audits against the restored copy.
- Record archive path, manifest checksum, Git commit, schema version, semantic counts, catalogue generation, and test totals.

Gate 0 fails if the worktree cannot be cleanly understood, any baseline test fails, any backup hash fails, or the rehearsal restore does not reproduce the baseline.

## 5. Gate 1: approve the schema and migration contract

The schema design must be reviewed before code is written.

### 5.1 Catalogue version

- Introduce one explicit version 7 to version 8 migration.
- Do not disguise a destructive migration inside general initialization.
- Fresh database creation and version 7 upgrade must converge on the same schema.
- The migration must be idempotent: reopening version 8 performs no rewrite.
- An unknown, newer, or partially migrated schema must fail closed with a clear error.

### 5.2 Writer credits

The authoritative existing `movie_credits` owner will be improved; no second writer-credit store will be created.

Proposed target:

- Continue using `people` for person identity.
- Extend `movie_credits.credit_type` to allow `writer`.
- Preserve `position`, credited name, character, profile URL, and all existing cast/director rows exactly.
- Add a `job` field if it is required to preserve Writer versus Screenplay versus Story versus Novel without reparsing JSON.

Safe SQLite rebuild sequence inside one transaction:

1. Validate that the source schema is exactly version 7.
2. Create the version 8 replacement table under a temporary name.
3. Copy all existing cast and director rows without transformation.
4. Compare row count and a deterministic logical digest across every copied column.
5. Backfill writers from valid stored provider snapshots.
6. Validate writer identities, positions, allowed jobs, and foreign keys.
7. Drop/swap tables only after all validation passes.
8. Recreate indexes.
9. Update the schema version last.
10. Run final integrity and foreign-key checks before commit.

An exception at any step must roll back every step.

### 5.3 Keywords

Use relational keyword ownership:

- `keywords`: stable local key, TMDB keyword ID when available, display name, normalized name.
- `movie_keywords`: provider snapshot/movie relationship, keyword key, and deterministic position.
- Enforce uniqueness so repeat ingestion and repeat migration do not duplicate relationships.
- Add indexes required by Library keyword lookup.

Keep the original keyword payload in `source_json`. The relational rows are the searchable projection.

### 5.4 Backfill rules

- Backfill only from already stored snapshots during migration.
- Do not call TMDB during schema migration.
- Invalid JSON, missing arrays, and empty arrays are valid known states and must not abort unrelated movie migration.
- Malformed individual writer/keyword entries must be counted and reported, not silently converted into different data.
- A migration report must distinguish processed, inserted, deduplicated, skipped-empty, and rejected-malformed records.
- Any rejected record that would change current visible behavior blocks live rollout until reviewed.

## 6. Gate 2: migration test matrix

These tests must exist and pass before a shadow copy of the real catalogue is migrated.

### 6.1 Schema lifecycle

- Fresh database creates the complete version 8 schema.
- Realistic version 7 fixture upgrades to version 8.
- Opening version 8 again is a no-op.
- Unknown schema versions fail closed.
- Interrupted/partial marker states fail closed.

### 6.2 Atomicity and rollback

Inject failures:

- Before table creation.
- During existing-credit copy.
- During writer backfill.
- During keyword backfill.
- Before index creation.
- Before schema-version update.
- During final validation.

After each injected failure, prove:

- Schema version remains 7.
- The original `movie_credits` table and all rows remain intact.
- No temporary tables or partial keyword relationships remain.
- Integrity and foreign-key checks still pass.

### 6.3 Existing-data preservation

Before and after migration compare:

- Counts and logical digests for every pre-existing authoritative table.
- Every movie identity and file relationship.
- Every provider snapshot and its `source_json`.
- Every cast/director row and ordering value.
- Genres and movie relationships.
- Collections and movie relationships.
- Overrides, identity decisions, user lists, assets, and mutation generations.
- Canonical projection for every owned path.

Only the documented schema-version change, new schema objects, optional `job` default, and expected writer/keyword rows may differ.

### 6.4 Writer cases

- No writers.
- One writer.
- Multiple ordered writers.
- Duplicate crew entries for one person and job.
- One person with multiple writing jobs.
- One person who is also cast or director.
- Same name with different TMDB IDs.
- Missing TMDB ID with a stable fallback identity.
- Missing profile image.
- Malformed person object.
- Allowed and disallowed crew jobs.

### 6.5 Keyword cases

- No keywords.
- One and multiple keywords.
- Duplicate names with case/whitespace differences.
- Same name with a stable TMDB ID.
- Existing name-only snapshot upgraded later with a TMDB ID.
- Non-Latin keyword names.
- Malformed entries.
- Repeat ingestion and repeat migration.

### 6.6 Application contracts

- Existing Movies search is unchanged.
- Existing actor/director People search is unchanged.
- Writer People search returns correct owned movies and role labels.
- Keyword Library search returns only owned SQL matches.
- Library search and owned details make zero provider calls.
- Discover writer relationships return the correct TMDB movies.
- Discover keyword resolution uses keyword identity rather than movie-title search.
- Ownership attachment and page-specific badges remain unchanged.
- Empty results, provider errors, races, pagination, filters, and navigation state behave correctly.

## 7. Gate 3: full shadow migration

Use SQLite's consistent backup mechanism to clone the current catalogue. Never copy a potentially active SQLite file with an ordinary filesystem copy.

On the clone:

1. Record schema, counts, deterministic table digests, projections, generations, and performance baselines.
2. Apply the version 8 migration.
3. Run `PRAGMA integrity_check` and `PRAGMA foreign_key_check`.
4. Compare all preservation invariants.
5. Run `tools/catalog_parity_audit.py` with writer and keyword coverage added.
6. Run `tools/catalog_json_shadow_compare.py` with writer and keyword coverage added.
7. Verify owned projections with provider access blocked.
8. Run the entire automated verification bundle against the migrated clone.
9. Start the application against the clone and perform desktop browser verification.
10. Stop and restart it, then repeat persistence and integrity checks.

Record the complete shadow report as a reviewable artifact. Any unexplained difference fails Gate 3.

## 8. Gate 4: staged implementation

Each stage must start green, add focused tests, end green, and be separately reviewable.

### Stage A: migration and relational projections

- Implement the approved version 8 migration.
- Implement writer and keyword ingestion/backfill in the existing canonical owner.
- Extend canonical reports and parity tools.
- Do not change UI or search routes.

### Stage B: Library search

- Extend the existing Library People projection/query to writers.
- Add the relational keyword query.
- Preserve Movies behavior, paging, sorting, filters, selection, and performance.
- Do not parse `source_json` in the search query.

### Stage C: Discover search

- Extend the existing TMDB person-credit relationship path for writers.
- Add TMDB keyword resolution and keyword-filtered movie discovery.
- Preserve current movie/person request cancellation and stale-response protection.

### Stage D: shared desktop UI

- Add the Keywords mode to Library and Discover.
- Expose Actor, Director, and Writer roles clearly.
- Add keyword suggestions/results without redesigning unrelated controls.
- Reuse the existing shared card and ownership behavior.
- Desktop only; do not introduce unrelated responsive/mobile work.

### Stage E: retirement and documentation

- Remove any obsolete temporary migration or compatibility path once nothing depends on it.
- Document the final authoritative paths.
- Update the parity matrix and acceptance evidence.

## 9. Performance acceptance

Capture baseline and post-change measurements on the same machine and catalogue clone.

- Existing Movies search must not regress materially.
- Existing Library first-page and detail-read performance must remain within the accepted baseline envelope.
- Writer and keyword queries must use indexed relational lookups.
- Search must remain paged and bounded.
- No N+1 provider, database, person, or keyword lookup pattern is acceptable.
- No ordinary startup-wide provider refresh or full movie-library filesystem scan may be introduced.

Set numerical thresholds from Gate 0 measurements before implementation; do not invent thresholds after seeing slower results.

## 10. Final acceptance matrix

All must pass:

| Area | Required evidence |
| --- | --- |
| Git baseline | Approved pre-search checkpoint with recorded commit and clean understood scope. |
| Backup | Checksum-verified archive plus successful empty-directory rehearsal restore. |
| SQLite | Integrity `ok`, zero foreign-key violations, expected schema version, no partial migration objects. |
| Existing data | Pre/post counts, logical digests, ordering, canonical projections, and source JSON preserved. |
| Existing behavior | Library, Discover, Lists, Home, Maintenance, AI Control, cards, details, ownership, plots, people, collections, assets, and page state remain at baseline. |
| New behavior | Writer People search and Keyword search work in Library and Discover with correct authority boundaries. |
| Provider boundary | Owned Library/search/detail workflows make zero provider calls. |
| Regression tests | Targeted Python/Node tests, full Python suite, frontend Node suite, production build, and Playwright suite pass. |
| Runtime | Migrated clone passes desktop browser verification and a second-start persistence check. |
| Performance | Pre-agreed thresholds pass with query evidence and no N+1 behavior. |
| Rollback | The final pre-live backup restores and reproduces the accepted baseline. |

## 11. Controlled live rollout

This is the first stage allowed to touch the live catalogue.

1. Confirm every prior gate is signed off.
2. Stop Cinema Paradiso and prevent background writers.
3. Create and verify a fresh final backup.
4. Record exact Git commit, app version, schema version, catalogue path, semantic counts, and archive checksum.
5. Apply the exact migration already proven against the shadow clone.
6. Immediately run integrity, foreign-key, relational, and canonical parity checks.
7. Start CP and verify the highest-risk workflows.
8. Stop and start CP a second time; verify persistence, counts, searches, details, Home/Maintenance agreement, and provider boundaries again.
9. Preserve the rollback archive until Dante explicitly accepts the release.

Immediate rollback triggers:

- Startup failure.
- Integrity or foreign-key failure.
- Any lost or changed existing authoritative row outside the approved migration contract.
- Missing plots, posters, people, collections, ownership, lists, or overrides.
- Actor/director search regression.
- Home and Maintenance disagreement.
- Provider requests during owned SQL workflows.
- Unexplained performance regression.
- Migration cannot be rerun as a no-op.

Rollback must use the previously rehearsal-restored archive. Do not attempt ad hoc live repair before restoring the stable state and diagnosing the failed clone offline.

## 12. Required execution record

The implementation task must maintain a concise gate record containing:

- Commands executed.
- Test counts and results.
- Paths of temporary/rehearsal data.
- Confirmation that live user data was not used during testing.
- Baseline and final Git commits.
- Backup paths and checksums.
- Schema versions and migration report.
- Pre/post semantic counts and logical digests.
- Integrity and foreign-key results.
- Parity and provider-call results.
- Performance measurements.
- Browser scenarios verified.
- Any deviation, failure, rollback, and its resolution.

No gate may be marked complete from memory or assumption.
