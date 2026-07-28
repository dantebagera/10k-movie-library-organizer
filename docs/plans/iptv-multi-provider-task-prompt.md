# New Task Prompt: Implement Multiple Xtream Providers

Use the following prompt in a new Codex task whose workspace is:

`C:\Users\dante\Desktop\cinema paradiso`

---

Your name is lam3y. My name is Dante.

Implement the approved Cinema Paradiso multi-provider IPTV architecture end to end. This prompt explicitly approves implementation of the scope below, including code changes, automated tests, production build, disposable browser verification, and the final protected migration of the existing Lionz provider. Do not stop for repeated implementation permission. Stop only for a genuine product decision, an unexpected live-data mismatch, credential exposure risk, destructive operation outside the approved IPTV migration, or an irresolvable conflict with my existing worktree changes.

Read this plan first and treat it as the authoritative contract:

`C:\Users\dante\Desktop\cinema paradiso\docs\plans\iptv-multi-provider-zero-regression-plan.md`

## Required Outcome

Cinema Paradiso must support any number of independent Xtream providers.

- Settings must provide a desktop provider rail and one provider editor for add, edit, rename, Save & Test, sync, and removal.
- IPTV must have one explicit active-provider selector in its header.
- Every backend and frontend catalog, category, detail, EPG, image, Favorite, custom-list, history, sync, and playback operation must carry a provider ID.
- Provider data must never merge. There is no All Providers mode.
- Synchronizing or deleting one provider must not alter any other provider.
- Identical Xtream category and media IDs across providers must remain isolated.
- Switching provider must stop previous playback, clear provider-specific view state, preserve the current media tab where sensible, and load only the selected provider.
- The 24-hour stale-catalog policy must operate independently for the selected provider.

## Required Architecture

Use one `IPTVProviderManager` and one refactored `IPTVService` instance per provider. Reuse the existing service/store/player owners rather than cloning them.

Use isolated provider roots:

```text
data/iptv/
  providers.json
  migration-backups/<timestamp>/
  providers/<provider-id>/
    provider.json
    iptv.sqlite
    images/
    playback/
```

`providers.json` contains stable provider IDs, display names, ordering, and last-selected preference only. Secrets remain in each backend-only provider credential file. Provider IDs must be stable UUID-like opaque values and must not be derived from mutable credentials.

Do not implement a process-global active provider. Remembered selection is a UI/default preference only; every data request still resolves an explicit provider ID.

Replace the singular internal IPTV routes with provider registry routes and provider-scoped routes. Migrate all CP callers and tests in the same implementation, then remove the obsolete singular route behavior rather than maintaining two implementations.

## Protected Existing Work

The worktree is dirty. Inspect `git status` and diffs first.

Known pre-existing changes include:

- `src/App.jsx`
- `src/styles.css`
- `tests/e2e/app-smoke.spec.js`
- `tests/test_workspace_layout_ui.py`
- ongoing IPTV synchronization/category work in:
  - `src/features/iptv/IPTVWorkspace.jsx`
  - `src/features/iptv/iptvSyncPolicy.js`
  - `tests/iptv_sync_policy.test.mjs`
  - `tests/test_iptv_ui.py`

Do not revert, overwrite, or reformat unrelated user changes. Incorporate the current IPTV auto-sync and provider-category-generation behavior into the provider-specific design.

Do not commit, push, reset, checkout, or change Git configuration unless I separately request it.

## Protected Lionz Migration

The existing live Lionz credentials are currently stored in:

`C:\Users\dante\Desktop\cinema paradiso\data\iptv\provider.json`

Never print, echo, log, expose in browser output, include in documentation, add to a test fixture, or commit its username/password values.

Before changing live IPTV data:

1. Record a redacted baseline of credential flags, server, username hint, catalog generation/counts, category counts, Favorites, custom lists, list entries, history, database size, and image-cache size.
2. Confirm automated tests use a disposable IPTV root and fake provider credentials.
3. Prove legacy migration success, rollback, and idempotence with fixtures.
4. Confirm no active playback session exists.
5. Create and validate a timestamped migration backup.

Migrate the current Lionz credential file, SQLite catalog, Favorites, custom list, history, details, and images into the first provider root named `Lionz`. Do not migrate playback directories.

After all code, tests, build, and disposable UI verification are green:

1. Compare the migrated Lionz data with the recorded pre-migration baseline before starting a fresh sync.
2. Read the existing/migrated credential values locally and re-save them through the new provider update API.
3. Preserve the existing invalid-TLS choice.
4. Never display the password during this operation.
5. Verify the save response exposes only redacted flags and username hint.
6. Run the new provider Test action/API and require successful Xtream authentication.
7. Confirm the saved credential file exists under the Lionz provider directory.
8. Confirm Settings lists Lionz and IPTV selects it.
9. Confirm Lionz Favorites and the existing custom list still work.
10. Keep the migration backup until I accept the result.

Do not ask me to paste credentials that already exist locally. Do not invent credentials.

## Required Implementation Order

1. Baseline and isolated fixtures.
2. Provider-root `IPTVService` refactor.
3. `IPTVProviderManager` with atomic redacted CRUD.
4. Idempotent legacy Lionz migration with rollback.
5. Provider-scoped backend routes and app-data-root lifecycle.
6. Provider-required frontend API.
7. Settings provider manager.
8. IPTV header selector and provider state isolation.
9. Focused and complete isolated tests.
10. Production build.
11. Disposable desktop Playwright verification.
12. Protected live Lionz migration and credential re-save.
13. Live redacted acceptance checks.

## Required Regression Coverage

At minimum, prove:

- same category/item IDs in two providers do not collide;
- one provider sync cannot change another provider;
- details, images, EPG, history, Favorites, custom lists, and playback remain isolated;
- blank password preserves the saved password;
- API and error redaction;
- duplicate-account rejection and same-server/different-user acceptance;
- provider removal path confinement and isolation;
- migration preserves the legacy catalog and user state;
- interrupted migration rolls back;
- second startup is idempotent;
- late frontend responses from a previous provider cannot update the selected provider;
- provider switching closes playback and resets provider state;
- new/deleted provider categories refresh after sync;
- stale auto-sync is per provider and never duplicates a running sync;
- existing non-IPTV CP behavior remains green.

Run:

- focused provider manager/service/store/route tests;
- focused IPTV UI and synchronization-policy tests;
- complete Python tests against a disposable `CP_TEST_ROOT`;
- frontend Node tests;
- `npm.cmd run build`;
- desktop Playwright against a disposable server/data root.

Do not run broad tests against the live CP catalog, movie roots, qBittorrent profile, or Lionz credentials.

## UI Contract

Desktop only.

IPTV header:

```text
IPTV                                      [ Lionz v ] [sync]
Provider television                       Updated 2h ago

Home   Live TV   Movies   Series   Favorites   My Lists
```

Settings:

```text
IPTV Providers                                      [add]

[provider rail]       [single selected-provider editor]
Lionz                 Display name
Provider Two          Server URL
                      Username
                      Password
                      TLS option
                      Save & Test / Sync / Remove
```

Do not add provider badges to media cards, nested settings cards, an All Providers mode, or unrelated responsive/mobile work.

## Completion Report

Lead with any unresolved correctness or data-safety issue.

Report:

- files and owners changed;
- migration behavior;
- exact test/build/browser evidence;
- Lionz pre/post redacted catalog and user-state comparison;
- confirmation that Lionz credentials were re-saved without exposure;
- connection-test result;
- second-provider isolation result;
- remaining risks.

Do not claim completion until Lionz is present and saved in the new provider manager, the credential response is redacted, the connection test succeeds, and the protected existing Lionz data is verified.

---
