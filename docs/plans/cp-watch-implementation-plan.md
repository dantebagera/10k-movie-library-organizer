# CP Watch Implementation Plan

- **Status:** Approved for planning; application implementation has not started.
- **Last reviewed:** 2026-07-21
- **Source idea:** [CP Watch: Where to Watch and Web Services](../ideas/cpwatch.md)

## Purpose

Deliver one desktop-first CP Watch system with two equal entry paths:

1. A movie-first **Where to Watch** popup on every shared expanded movie card with an accepted TMDB ID.
2. A platform-first **Watch/Your Services** workspace for exploring any number of user-configured web services.

Both paths must use one provider collection, one launch-resolution service, and one secure Windows browser host. The feature must improve CP's living-room experience without turning CP into a provider-specific client, credential store, catalogue scraper, or DRM workaround.

## Decisions Already Made

- The public name is provisionally **Watch**. **Where to Watch** is the movie-card action; **Your Services** may be the workspace heading. Final naming remains a product decision.
- The standalone services workspace is required, not optional.
- Settings supports an arbitrary number of enabled or disabled services, ordered by the user.
- Common services may use maintained presets; custom services can use any valid HTTPS homepage.
- Availability is fetched only after the user clicks Where to Watch.
- TMDB Watch Providers, regional release dates, and Now Playing data are the first availability sources.
- Availability and service configuration do not belong in the movie SQL catalogue. Services remain in normal CP application configuration; availability uses an in-memory time-limited cache.
- JustWatch attribution is visible whenever TMDB Watch Providers data is displayed.
- TMDB theatrical data is described as a regional release-window indication, never as actual Egyptian cinema branches or showtimes.
- Provider results do not imply a verified deep link. CP searches the service when a supported search route exists and otherwise opens an honest fallback.
- WebView2 is the desktop direction to try. Each initial provider must pass real login and playback testing; failed providers use an Edge app-style fallback.
- Provider pages are top-level WebView2 content, never iframes inside the React page.
- CP does not build a password manager. WebView2 native password saving is opt-in and off by default; CP never receives the credential.
- The first release is desktop-only. Mobile and responsive redesign are outside scope.

## Non-Negotiable Product Contract

### Availability

- No availability request occurs during card rendering, card expansion, page loading, or background catalogue scanning.
- The only required movie input is an accepted `tmdb_id`; the selected ISO 3166-1 region comes from normal app configuration or an explicit popup override.
- Missing or stale third-party data is reported as unknown, not as proof of unavailability.
- Provider categories remain distinct: subscription, free, ads, rent, and buy.
- No availability response writes to SQL or changes ownership, canonical metadata, stream URLs, or download state.

### Services

- The provider collection has one authoritative representation. Settings, Watch, the popup, and the native host do not maintain competing provider lists.
- Presets supply convenience mappings and search routes; users can edit or remove their configured entries.
- A custom service without a supported search route remains useful as a homepage entry and must not pretend to support title search.
- Closely named entitlements such as direct services and add-on channels remain separate when their TMDB provider IDs differ.

### Browser and credentials

- External services must use HTTPS. Unsafe schemes are rejected.
- The true hostname and navigation state remain visible on provider surfaces.
- CP never injects scripts into provider pages, scrapes logged-in content, reads credentials or authentication tokens, or exposes privileged native objects to remote origins.
- Remembering sign-ins and saving passwords are separate settings.
- Browser data is stored per Windows user under LocalAppData and is excluded from ordinary CP exports, backups, and portable application folders.
- Users can separately clear site sessions, delete passwords saved in the CP Watch profile, or reset the entire profile.
- Anyone using the same unlocked Windows account may be able to use remembered provider sessions. The UI and Help text must say this plainly.

## Existing Owners And Planned Ownership

The implementation must extend the existing owners rather than create route-specific copies.

| Responsibility | Current owner or boundary | Planned authoritative owner |
| --- | --- | --- |
| Application settings persistence | `app.py` and `config.json` | Existing config owner with one validated `watch` configuration object |
| Shared expanded movie details | `src/components/SharedMovieCards.jsx` | Existing shared expanded-card owner adds one action hook |
| Application navigation and workspace mounting | `src/App.jsx` | Existing app shell adds the `/watch` workspace and coordinates the global modal |
| Settings UI | `src/features/settings/SettingsWorkspace.jsx` | Existing Settings workspace owns Watch service and security settings |
| TMDB-backed Watch normalization and cache | No owner yet | New backend `WatchService` domain owner; thin HTTP routes call it |
| Frontend Watch API contract | No owner yet | One `src/api/watch.js` client module |
| Availability presentation | No owner yet | One reusable `WhereToWatchModal` mounted outside individual card lists |
| Configured-service browsing | No owner yet | One `WatchWorkspace` using the same frontend provider collection contract |
| Destination selection | No owner yet | One launch resolver shared by Watch and the popup |
| Desktop browser and process lifecycle | No desktop host exists | One Windows x64 host using WebView2 and a narrowly scoped CP-origin bridge |
| Portable release build | `tools/build_portable_release.py` | Keep current browser release intact until the packaging stage defines its replacement or extension |

Exact filenames may change during implementation, but responsibility may not be duplicated to avoid changing an existing owner.

## Target Flow

```text
Shared movie card --------> Where to Watch modal -----> launch resolver
                                  |                          |
                                  v                          v
                           Watch backend API          Windows host bridge
                                  |                          |
                         TMDB + memory cache          WebView2 or Edge fallback

Settings ----> one Watch config ----> Watch workspace ------^
```

Remote provider pages are outside the trusted CP origin. The bridge exists only between the local CP UI and the Windows host.

## Planned Contracts

### Watch configuration

One `watch` object in normal application configuration should contain:

```json
{
  "region": "EG",
  "remember_sign_ins": true,
  "offer_password_saving": false,
  "services": [
    {
      "id": "stable-user-entry-id",
      "preset_id": "netflix",
      "name": "Netflix",
      "homepage_url": "https://www.netflix.com/",
      "search_url_template": "https://www.netflix.com/search?q={query}",
      "tmdb_provider_ids": [8],
      "icon": "preset:netflix",
      "enabled": true,
      "order": 10
    }
  ]
}
```

The exact provider IDs and search templates above are illustrative until Stage 0 validates them. Validation must enforce stable unique entry IDs, HTTPS external URLs, one optional `{query}` placeholder, normalized ordering, known icon references, and an arbitrary service count. Passwords, cookies, tokens, and WebView2 profile paths are never accepted in this contract.

### Availability response

The backend response should normalize third-party data so React does not understand TMDB response quirks:

```json
{
  "tmdb_id": 27205,
  "region": "EG",
  "providers": {
    "subscription": [],
    "free": [],
    "ads": [],
    "rent": [],
    "buy": []
  },
  "theatrical": {
    "listed_now": false,
    "basis": "tmdb_regional_release_window"
  },
  "watch_page_url": null,
  "attribution": "Availability data by JustWatch",
  "checked_at": "ISO-8601 timestamp",
  "cached": false
}
```

Each provider includes its TMDB ID, display name, logo URL, display priority, matched configured-service ID when known, and supported launch actions. The API must distinguish an empty valid result from a TMDB error.

### Launch request

Every UI entry uses one conceptual request:

```json
{
  "provider_id": "stable-user-entry-id",
  "action": "search",
  "query": "Inception 2010",
  "fallback_url": "https://www.themoviedb.org/movie/27205/watch"
}
```

The resolver chooses, in order: a genuine licensed title link if later available, a validated search URL, a configured search page or homepage, then the TMDB regional watch page. It returns the destination, its reason, and whether the provider compatibility policy requires WebView2 or Edge. React must not reconstruct this logic in individual components.

## Implementation Stages

### Stage 0 - Desktop mockups and isolated WebView2 compatibility spike

This is the gate before production coding.

1. Produce desktop mockups for:
   - The Where to Watch modal, including loading, data, empty, and error states.
   - The Watch workspace with configured services and its empty state.
   - The Settings service manager and browser-security controls.
   - The provider browser surface with the narrow native toolbar.
2. Build an isolated WebView2 proof of concept that does not become a second CP implementation.
3. Test Netflix, Apple TV, Disney+, Shahid, and YouTube on representative mini-PC hardware connected to a television.
4. Record per provider:
   - Homepage, login, logout, two-factor authentication, CAPTCHA, and profile selection.
   - Search URL behavior before and after authentication.
   - Protected playback, DRM errors, available resolution, hardware acceleration, HDMI/HDCP, and audio.
   - Fullscreen, subtitles, alternate audio, pop-ups, authentication redirects, and return to CP.
   - Persistent session and optional password prompt after restart.
   - Sleep/wake, network interruption, and recovery.
5. Assign a launch policy to each tested provider: embedded WebView2, Edge fallback, or unsupported with a clear explanation.

**Exit gate:** Dante accepts the four desktop surfaces, the initial provider mappings are evidence-backed, and the provider matrix proves real playback or records the fallback. A homepage merely loading does not pass.

### Stage 1 - Backend configuration and availability domain

1. Extend the existing application config owner with the validated `watch` object and safe defaults.
2. Add one Watch domain service that owns:
   - Provider preset lookup and configured-entry normalization.
   - `tmdb_id + region` in-memory caching with a documented 12-to-24-hour time limit.
   - TMDB Watch Providers normalization.
   - Regional release-date and Now Playing normalization.
   - Provider-to-configured-service matching.
3. Add thin routes for reading/updating Watch settings and requesting one movie's availability.
4. Preserve existing config fields when Watch settings are updated; write configuration atomically.
5. Include the required attribution and source timestamps in the normalized response.

**Automated coverage:** valid and invalid service entries, unlimited-list behavior, duplicate IDs, URL and template validation, old-config defaults, atomic update preservation, cache hit/expiry/refresh, TMDB error versus empty result, region separation, provider-category normalization, theatrical wording basis, and a guard proving the operation makes no SQL writes.

### Stage 2 - Settings and standalone Watch workspace

1. Add the desktop Watch navigation item and direct `/watch` route through the existing app shell and frontend-route owner.
2. Add a Watch section to the existing Settings workspace:
   - Region selection.
   - Add from preset or add custom service.
   - Edit, enable/disable, reorder, and remove any number of entries.
   - Preview the resolved icon, homepage, search support, and TMDB matching.
   - Remember-sign-ins and password-saving choices, with the latter disabled until the native host exists.
3. Build the Watch workspace from the same saved service contract:
   - Ordered enabled-service tiles.
   - Search/filter when the configured list becomes large.
   - Open provider homepage.
   - Clear empty state linking to Settings.
   - Visible fallback and error feedback.
4. While CP still runs in a normal browser, route launches through a temporary top-level browser-window adapter behind the same launcher interface. Remove that adapter when the Windows host replaces it; do not let it become a second destination resolver.

**Automated coverage:** settings CRUD and ordering, preset/custom behavior, invalid URLs, empty state, workspace ordering/filtering, route reload, launcher request formation, and unchanged behavior in existing workspaces.

### Stage 3 - Shared-card Where to Watch experience

1. Add one shared action to the authoritative expanded-card component. Do not patch Library, Discover, Home, Movie Lists, or AI result cards separately.
2. Mount one modal outside repeated card lists so it owns request state, focus management, and dismissal consistently.
3. Fetch availability only after the click and cache the response for the frontend session.
4. Implement the accepted desktop visual states and provider groupings.
5. Match provider results to configured services. Only show a search/open action when the launcher has a truthful destination.
6. Keep **View watch options** as the universal TMDB fallback and show JustWatch attribution.
7. Use cautious theatrical wording and never invent showtimes or cinema branches.

**Automated coverage:** no eager fetch, shared behavior across card consumers, absent-TMDB state, modal focus/escape/close behavior, loading/error/empty/data states, category grouping, rent/buy de-duplication, unmatched providers, search versus homepage fallback, attribution, and frontend session caching.

### Stage 4 - Windows x64 host and WebView2 integration

1. Choose WPF or WinUI based on the Stage 0 spike and document why. Do not maintain both.
2. Build one Windows host that:
   - Starts the packaged CP backend without a visible console.
   - Waits for a health check before showing the UI.
   - Displays the existing local React application in the primary WebView2 surface.
   - Enforces single-instance behavior and shuts child processes down cleanly.
   - Supports full-screen startup and a deliberate escape/exit path.
3. Add a minimal native bridge available only to CP's trusted local origin. Its initial responsibility is accepting a validated launch request, not exposing general filesystem or shell access.
4. Open providers in a top-level provider WebView2 surface with the accepted native toolbar; hide CP's normal sidebar until return.
5. Store the WebView2 user-data folder under protected per-user LocalAppData.
6. Use Evergreen WebView2 and add runtime detection. Missing-runtime installation belongs to the installer stage, not ad hoc application downloads.
7. Enforce the provider launch policy recorded in Stage 0 and preserve Open in Edge as a user-visible fallback.

**Automated coverage:** trusted-origin bridge allow-list, rejected remote bridge calls, launch validation, process readiness/failure/cleanup, single-instance behavior, toolbar state, navigation return, profile-path selection, and provider-policy routing. DRM playback remains a recorded manual acceptance test because automation cannot prove commercial-provider compatibility reliably.

### Stage 5 - Browser security and data controls

1. Implement browser-profile settings with these defaults:
   - Remember sign-ins: on.
   - Offer password saving/autofill: off.
   - General form autofill: off.
   - Payment autofill: off.
2. When password saving is enabled, use only WebView2's native Save/Update Password behavior.
3. Add separate confirmed actions for:
   - Clear provider sessions and site data.
   - Delete passwords saved in the CP Watch profile.
   - Reset all CP Watch browser data.
4. Display the true hostname and HTTPS state. Define allow/warn behavior for authentication redirects and navigation outside the configured domain.
5. Handle new windows, downloads, permissions, certificate errors, external protocols, and production developer-tools policy explicitly.
6. Add Help text explaining the shared-Windows-account risk and that CP cannot retrieve passwords saved in normal Edge or Apple Keychain.

**Security review gate:** verify that provider pages cannot call native CP operations, browsing data is outside backup/export paths, destructive clear actions target only the resolved CP Watch profile, and no logs or diagnostics contain URLs with sensitive query data, cookies, tokens, or credentials.

### Stage 6 - Search routing and provider maintenance

1. Finalize the central launch resolver and validated preset catalogue using Stage 0 evidence.
2. Version maintained provider presets so changed search URLs or TMDB mappings can be updated without overwriting user customizations.
3. Define behavior for provider availability with no configured match: show information, offer the TMDB page, and link to adding/configuring the service where useful.
4. Make the title-and-year query easy to copy when only a search page or homepage can be opened.
5. Document a small provider verification checklist for future preset changes.

**Automated coverage:** URL encoding, missing query, invalid template, preset upgrade preservation, direct-service versus channel mapping, unmatched provider behavior, destination-priority order, and provider-specific Edge fallback.

### Stage 7 - Packaging, appliance startup, and final acceptance

1. Define the Windows distribution model without silently changing the current portable browser release.
2. Package the chosen Windows host, built frontend, backend runtime, existing required helpers, and configuration defaults into one supported x64 distribution.
3. Add an installer or bootstrap step that detects and installs the Evergreen WebView2 Runtime when missing.
4. Keep mutable user configuration, database, metadata, logs, and browser profile data outside the installed program directory with documented migration and uninstall behavior.
5. Add optional start-with-Windows behavior only after normal launch, update, failure recovery, and clean exit are proven. Startup registration must remain user-controlled and reversible.
6. Run full acceptance on clean Windows 11 and the supported Windows 10 baseline, using the actual mini PC, HDMI television, keyboard, and mouse.
7. Review TMDB/JustWatch attribution and commercial API licensing before public or commercial distribution.

**Exit gate:** one installer or supported package launches CP full-screen without a conventional browser, existing CP workspaces still operate, Watch passes the agreed provider policy, browser data controls work, startup can be enabled and disabled safely, and rollback does not lose the user's catalogue or settings.

## Acceptance Matrix

| Area | Required proof |
| --- | --- |
| Existing CP behavior | Current backend, frontend, and end-to-end regression suites pass; Library, Discover, Home, Movie Lists, AI, downloads, streaming, and IPTV retain their existing contracts. |
| Lazy availability | Network trace and automated test prove no Watch request occurs until a user clicks Where to Watch. |
| No SQL coupling | Backend test proves availability and configured-service changes create no movie-catalogue SQL writes. |
| Regional accuracy | EG responses preserve provider categories, cautious theatrical wording, timestamps, empty/error distinction, and JustWatch attribution. |
| Unlimited configuration | Add, edit, reorder, disable, delete, restart, and reload a large mixed preset/custom service list without data loss. |
| Shared-card parity | One change appears consistently wherever the authoritative expanded card is used. |
| Launcher truthfulness | Every button states whether it searches, opens a homepage, opens TMDB, or uses Edge; none claims direct playback without a real direct link. |
| Provider compatibility | Per-provider matrix records login and actual protected playback on target hardware, plus WebView2/Edge policy. |
| Credentials | CP never receives a provider password; password saving is off until enabled; session, password, and full-profile clearing are independently verified. |
| Security boundary | Remote pages cannot invoke the CP bridge or local administrative APIs; unsafe schemes and unexpected navigation are handled visibly. |
| Packaging | Clean-machine install, first launch, upgrade, restart, optional Windows startup, uninstall, and reinstall preserve or remove the documented data only. |

## Principal Risks And Responses

- **A provider blocks WebView2 or DRM playback.** Use the recorded Edge fallback; do not spoof browsers or bypass DRM.
- **A search route changes.** Maintain it in the central versioned preset and fall back to the homepage/TMDB page.
- **TMDB availability is incomplete.** Show source, region, checked time, and an unknown/empty state instead of claiming unavailability.
- **A shared living-room PC exposes a signed-in account.** Explain the risk, provide fast session clearing, and recommend separate Windows accounts where privacy matters.
- **The desktop host becomes a second application architecture.** Keep React and Flask as the product UI/domain owners; the host owns only process lifecycle, trusted native capabilities, and browser surfaces.
- **Packaging work destabilizes the current browser release.** Keep the existing release path usable until the native package passes clean-machine acceptance and rollback testing.
- **Provider browser data grows or becomes corrupt.** Provide bounded diagnostics and a targeted profile reset that cannot touch unrelated CP data.

## Rollback Strategy

- Stages 1 through 3 must remain usable through the existing browser launcher, with provider destinations opening as normal top-level browser pages.
- The native host is introduced as a new distribution path until it passes acceptance; it does not replace the working browser path immediately.
- Provider launch policy can move an individual service from WebView2 to Edge without changing Settings, the Watch workspace, or the popup.
- A failed Watch availability request never blocks cards or other CP workflows.
- Browser-profile resets never delete CP configuration, SQL data, metadata, downloads, or media.

## Definition Of Done

CP Watch is done only when:

- Users can configure and explore any number of services from one Watch workspace.
- Every supported shared expanded movie card can lazily show an accurate, polished regional availability popup.
- Both paths call one truthful launcher and reach the best supported provider destination.
- The Windows x64 host runs CP full-screen and returns reliably between CP and provider surfaces.
- Each initial provider has an evidence-backed WebView2, Edge-fallback, or unsupported policy based on real playback.
- Sessions and optional WebView2 password saving behave exactly as the user selected, with clear targeted reset controls and no CP-managed credential store.
- No remote provider page receives privileged CP access.
- Existing CP behavior remains covered and intact.
- Packaging, clean-machine installation, optional Windows startup, update/rollback behavior, attribution, and licensing review are complete.
