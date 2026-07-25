# Writer and Keyword Search — Stage B Evidence

Date: 2026-07-25
Starting commit: `2c7cbf0201e35e266d9999aa4bc3df756be97a4a`

## Scope

Stage B implements only Library search:

- extend the existing owned People projection and role filter to stored writers;
- add normalized, relational keyword suggestions and owned-movie filtering;
- preserve the existing Movies query, actor/director behavior, paging, sorting, filters, and selection;
- extend the existing catalogue read-performance probe with writer and keyword measurements.

Discover search and the shared Writer/Keyword controls were not implemented. They remain Stage C and Stage D work.

## Authority and behavior

- `services/catalog_store.py` remains the only SQLite Library-query owner.
- `services/canonical_catalog.py` remains the keyword-normalization owner.
- Writer filtering reuses `people` and `movie_credits`; no second credit system was added.
- Keyword filtering uses `keywords` and `movie_keywords`.
- TMDB keyword ID is used when present. Normalized name is the fallback identity.
- Keyword suggestions and free query filtering use normalized, case-insensitive prefix matching. Selecting a keyword can use exact TMDB ID or exact normalized name.
- Existing Movies `q` behavior still searches title, year, filename, path, plot, and genre only. Writer and keyword text were not added to Movies mode.
- Search queries never parse `provider_movie_snapshots.source_json`.
- `view=keywords` ignores refresh/rescan flags and remains an offline SQL read.

## Isolation and live-data boundary

Every Python verification used `CP_TEST_MODE=1` and an operating-system temporary `CP_TEST_ROOT`.

Important retained paths:

- focused: `C:\Users\dante\AppData\Local\Temp\cp-stage-b-final-focused-29275ac60a544f03ac3b5fca04de0a7b`
- targeted: `C:\Users\dante\AppData\Local\Temp\cp-stage-b-targeted-76232979405d48dd8867e9d1007804ae`
- final full Python: `C:\Users\dante\AppData\Local\Temp\cp-stage-b-final-python-55974bde08d34714bd2301d117228803`
- performance: `C:\Users\dante\AppData\Local\Temp\cp-stage-b-performance-12e235de0e854702bfd5242bbbd8840e`
- final Playwright: `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-playwright-27636c8e6b004e18b01b97c91841362a`
- deterministic evidence catalogue: `C:\Users\dante\AppData\Local\Temp\cp-stage-b-evidence-3b626ce03b7a4c148b76f11eff8e9a87\search-evidence.sqlite`

The live catalogue was opened with SQLite `mode=ro` and `PRAGMA query_only=ON` only:

- path: `C:\Users\dante\AppData\Local\Cinema Paradiso\Catalog\catalog-read-cb30c1d963c88463.sqlite`
- schema version: 7
- `keywords` tables present: 0

No live migration, backfill, repair, scan, provider refresh, or application restart occurred.

## Deterministic SQL evidence

The retained 85-movie isolated version 8 fixture reported:

| Item | Result |
| --- | ---: |
| `media_files` | 85 |
| `canonical_movies` | 85 |
| `provider_movie_snapshots` | 85 |
| `people` | 239 |
| `movie_credits` | 255 |
| `keywords` | 86 |
| `movie_keywords` | 170 |
| Integrity | `ok` |
| Foreign-key violations | 0 |

Logical SHA-256 evidence:

- provider `source_json`: `32808b005e867705cd39d3d79fc811d475dc9a60412aacea93427fd7780a8605`
- existing Movies behavior: `3bfcf9b8d2dc44424d6842bf57aecd93875cbb4f865f7da4aeb464de0c306d55`
- existing actor/director behavior: `0afbad23af5c59f18b7fad92fc27ed583ac2742f8bd25c711e329bb95c93acaa`
- new writer/keyword results: `4c547fc888f5a202385da66099a6a8f7147ae9061e642a57063f46283c50e235`

Result counts were 17 movies for the shared actor, one for Director 3, one for Writer 3, and 85 for the shared keyword.

Focused coverage also proves:

- writer ID matching does not merge two people with the same display name;
- a person can retain Actor, Director, and Writer roles;
- case and whitespace normalization is deterministic;
- non-Latin keyword prefixes work;
- keyword suggestions are deduplicated and bounded to at most 100 rows;
- paging and selection use the same writer/keyword filters;
- writer and keyword results remain identical after all snapshot `source_json` values are replaced with `{}` in an isolated fixture;
- actor/director results and Movies search stay unchanged.

## Query plans, provider boundary, and performance

SQLite query plans report:

- writer search: `sqlite_autoindex_movie_credits_1`;
- keyword name lookup: `idx_keywords_normalized_name`;
- keyword relationship lookup: `idx_movie_keywords_keyword`.

The extended route probe reported zero provider calls. On its isolated route fixture:

| Workflow | Status | SQL statements | Returned |
| --- | ---: | ---: | ---: |
| Writer cards | 200 | 13 | 1 |
| Keyword entities | 200 | 2 | 1 |
| Keyword cards | 200 | 13 | 1 |

The 400-movie performance fixture used 10 warmups and 100 measured iterations:

| Workflow | Median | p95 | Frozen ceiling | Result |
| --- | ---: | ---: | ---: | --- |
| Library first page | 7.401 ms | 7.710 ms | 8.1 ms | Pass |
| Existing Movies search | 8.252 ms | 8.699 ms | 10.6 ms | Pass |
| Writer search | 5.363 ms | 5.887 ms | New workflow | Pass |
| Keyword movie search | 15.316 ms | 20.985 ms | New workflow | Pass |
| Keyword entity lookup | 7.961 ms | 10.374 ms | New workflow | Pass |

The unchanged owned-detail path was remeasured separately after a noisy mixed-workload sample: 2.363 ms median and 2.621 ms p95, below the frozen 4.7 ms ceiling. A second 300-sample run was 2.334 ms median and 2.509 ms p95.

## Automated verification

| Verification | Result |
| --- | --- |
| Focused final Python/Node slice | 20 Python and 21 Node tests passed |
| Targeted catalogue/parity/performance Python suite | 152 passed |
| Full Python suite | 743 passed in 91.851 s |
| Frontend Node suite | 63 passed |
| Production Vite build | 1,642 modules; passed in 1.97 s |
| Desktop Playwright suite | 25 passed in 22.1 s |

The full Python suite emitted the same two known non-fatal `ResourceWarning` messages recorded at Stage A: one temporary file and `dist/index.html`.

## Resolved verification interruptions

- The initial focused tests failed as intended before implementation because writer projection and keyword query methods did not exist.
- The first production build attempt was blocked by the restricted filesystem. The identical command passed outside that restriction.
- The first Playwright launch was blocked by PowerShell execution policy.
- The second Playwright launch found duplicate `Path`/`PATH` entries in the Codex process environment before any test ran. Normalizing that process environment allowed the unchanged isolated launcher to run; all 25 tests passed.
- One mixed benchmark produced a noisy owned-detail result above its ceiling. Two isolated 300-sample reruns passed, and no Stage B code changes that detail path.

## Commands

The gate used:

- focused and targeted `python -m unittest` selections;
- `.venv\Scripts\python.exe -m unittest discover -s tests`;
- `node --test tests\*.test.mjs`;
- `npm.cmd run build`;
- `tools\run_playwright_e2e.ps1` with an isolated temporary root;
- isolated SQL fixture scripts for logical digests, query plans, provider-call blocking, and performance;
- a read-only SQLite URI for the final live-catalogue version check.

## Stage boundary

Stage B is green and separately reviewable. Stage C Discover writer/keyword search must not begin until Dante explicitly approves it.
