# Gate 0 regression and toolchain baseline

## Suite inventory

- 104 Python `tests\test_*.py` modules;
- 13 Node `.test.mjs` files;
- one Playwright spec containing 48 desktop tests;
- Playwright viewport: 1600x1000, Chromium, one worker;
- Playwright configuration captures trace/screenshots on failure and does not currently record video.

Relevant existing Python owners include catalog schema/store/repository/canonical tests, Library reconciliation/ownership/action tests, media-file-facts tests, qBittorrent service/API/monitor tests, frontend crash guards, React routes, and native-player/runtime/packaging tests.

## Python backend discovery

Environment:

```powershell
$env:CP_TEST_MODE='1'
$env:CP_TEST_ROOT='<unique OS-temp GUID root>'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -q
```

Result:

```text
Ran 1002 tests in 138.685s
OK
```

Recorded warnings:

- unclosed temporary file reported from `services/catalog_store.py:94`;
- unclosed `dist/index.html` buffered reader in a unittest route path.

An initial diagnostic invocation set `CP_TEST_QBT_MODE=system` and produced one deterministic failure: `test_react_routes` expected the embedded `/qbittorrent/` route to return 200, while system mode correctly returned 409. This was diagnosed as a test-environment mismatch, not treated as flaky, and not repeatedly rerun. The baseline discovery was then run once with the repository's default embedded test mode and passed.

## Node unit suite

Command used the 13 explicit `.test.mjs` files under a unique temp environment.

Result:

```text
75 tests passed
duration 262.4085 ms
```

Files:

```text
appUtils.test.mjs
browser_curation_cache.test.mjs
browser_ownership_cache.test.mjs
cardGrid.test.mjs
cardLabPrototype.test.mjs
cleanupUtils.test.mjs
deletionPlan.test.mjs
discoverUtils.test.mjs
homeMovies.test.mjs
iptv_sync_policy.test.mjs
libraryUtils.test.mjs
movieDetails.test.mjs
ollamaModels.test.mjs
```

## Desktop Playwright

Command:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\tools\run_playwright_e2e.ps1
```

Isolated root:

```text
C:\Users\dante\AppData\Local\Temp\cinema-paradiso-playwright-9e4ecfdf83b74a1180ed4d4ac66ee644
```

Result:

```text
48 passed (47.5s)
```

Coverage includes route smoke, sidebar state, Downloads/qBittorrent UI, player settings/runtime verification, Library Movie/File views, Library people/keyword/server paging, poster locality, shared card contracts, metadata correction, curation refresh state, and cross-workspace state preservation.

The current suite does not cover the proposed idle-to-background-ingestion event, grid non-unmount requirement, exact scroll/focus preservation during background page refresh, observer behavior, final publication predicate, or qBittorrent zero-walk handoff.

The first attempt to invoke the `.ps1` directly was blocked by the machine's PowerShell execution policy. A nested `powershell.exe` workaround exposed a duplicate `Path`/`PATH` environment issue in `Start-Process`. Running the existing script in the current PowerShell process with process-scoped execution-policy bypass passed. No repository script was edited.

## Packaged/native-player focused suite

Modules:

```text
test_release_packaging
test_player_theme
test_player_settings_ui
test_player_runtime_assembly
test_player_runtime
test_player_route_ownership
test_player_protocol
test_player_play_api
test_player_manager
test_player_config_api
test_player_config
test_player_catalog
test_native_player_spike
test_native_player
```

Result:

```text
Ran 97 tests in 0.321s
OK
```

The current selector points to `0.1.20-qt6.10.3-mpv20260610-lgpl`.

Interactive `smoke_player.py`/`smoke_manager.py` with real media was not run. Gate 0 prohibited touching real media and did not authorize launching a GUI player. Representative real-media smoke remains a Gate 8 qualification item.

## Frontend production build

The normal `dist` directory was not overwritten. Vite output was redirected to:

```text
C:\Users\dante\AppData\Local\Temp\cinema-paradiso-gate0-build-cd46a8b3490343fcaaa99e4806ee114d\dist
```

Result:

```text
Vite 6.4.3
1,651 modules transformed
built in 2.56s
35 files
1,795,902 bytes
```

## Baseline conclusion

The existing suites are green, but they do not encode the new ingestion, publication, process, transport, or no-flicker contracts. Passing them is necessary for every later gate and insufficient by itself.
