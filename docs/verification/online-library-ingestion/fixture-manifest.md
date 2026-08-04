# Gate 0 isolated fixture manifest

## Isolation contract

Every later automated test must:

1. set `CP_TEST_MODE=1`;
2. create a new GUID-named `CP_TEST_ROOT` below the Windows OS temporary directory;
3. place all test media below `<CP_TEST_ROOT>\movies`;
4. use `<CP_TEST_ROOT>\user-data\.catalog-test.sqlite`;
5. block external provider network access unless a local fake provider is explicitly injected;
6. assert that the resolved test root is a strict child of `tempfile.gettempdir()`;
7. assert that no configured production media root or production database path appears in the test's paths;
8. stop its own test processes and release its own port;
9. never share a mutable catalog between tests.

Code-enforced proof:

- Python tests refuse to start without `CP_TEST_MODE=1` and `CP_TEST_ROOT`: `app.py:119-143`;
- test roots outside OS temp are rejected: `app.py:140-143`;
- test-mode provider `urlopen` is blocked: `app.py:146-149`;
- media roots are replaced with `<CP_TEST_ROOT>\movies`: `app.py:301-307`;
- user data/cache/qBittorrent mode are isolated: `app.py:339-344`;
- temporary repositories resolve to `.catalog-test.sqlite`: `app.py:378-400`;
- `CatalogStore.connect()` rejects a test-mode database outside OS temp: `services/catalog_store.py:155-162`;
- `tools/run_playwright_e2e.ps1` creates a new GUID root, sets test mode/root, launches its own port 5117 server, then stops it.

## Gate 0 roots used

| Purpose | Root | Production access |
| --- | --- | --- |
| Full backend pass | `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-gate0-backend-6c5e6f03b308403bbff9501eb22a065b` | none |
| Node suite environment | `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-gate0-node-bf72047560c344d982db83a99d6a51e4` | none |
| Temporary Vite output | `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-gate0-build-cd46a8b3490343fcaaa99e4806ee114d` | none |
| Desktop/performance fixtures | `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-gate0-ui-4f6cc8d5d018497e9cdf84f37b16c745` | none |
| Three-file full-scan micro fixture | `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-gate0-scan-1ddf3d0c8c764af8b9ea1a292a178d02` | none |
| Playwright pass | `C:\Users\dante\AppData\Local\Temp\cinema-paradiso-playwright-9e4ecfdf83b74a1180ed4d4ac66ee644` | none; deleted by the successful runner |

The focused packaged-runtime suite generated a separate GUID test root inline. It did not launch an interactive player or use real media.

## Desktop fixture

The desktop root contained:

- 55 synthetic accepted movies named `Gate Zero Movie 01` through `Gate Zero Movie 55`;
- synthetic canonical metadata, genres, years, locale, quality, and summaries;
- no real posters, users, lists, playback history, or production paths;
- 1,500 additional empty synthetic `.mkv` files under `movies\loading-fixtures` for current loading/full-scan proof.

The accepted cards were sufficient to prove two-page server pagination at the current 40-card page size.

## Required per-gate fixture layouts

These are logical layouts to generate under a fresh root for each test, not shared durable test data:

| Gate/scenario | Required isolated layout |
| --- | --- |
| Gate 2 targeted parity | `movies\stable`, `movies\pending`, exact path queue, isolated SQL |
| Gate 3 external observer | `movies\incoming`, nested folders, rename pairs, burst files, deleted paths |
| Gate 3 overflow/fallback | dirty-root marker, bounded subtree, observer-disabled/network-root capability fake |
| Gate 4 publication | stable media fake, probe fake, identity/provider fake, poster asset temp directory, transaction-failure injection |
| Gate 5 frontend | 55+ accepted cards, expanded/selected card, page 2, search/filter/sort state, delayed background page response |
| Gate 6 qBittorrent | `qbt-staging`, `movies\destination`, isolated `qbittorrent\jobs.json`, simulated restart states |
| Gate 7 startup | persisted isolated inventory/signature/generation, offline additions/deletions/renames, unavailable root |
| Gate 8 performance | small deterministic set plus separately generated large/burst sets; fake clock and provider counters |
| Gate 9 optional file ID | migration rehearsal copy only; never a production catalog |
| Gate 10 live acceptance | intentionally absent; requires separate approval, production backup, rollback, and path confirmation |

No later test may reuse the Gate 0 roots as a mutable shared fixture.
