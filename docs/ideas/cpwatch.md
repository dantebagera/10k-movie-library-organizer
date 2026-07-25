# CP Watch: Where To Watch And Web Services

- **Status:** Approved
- **Last reviewed:** 2026-07-21
- **Owner:** Cinema Paradiso
- **Implementation plan:** [CP Watch implementation plan](../plans/cp-watch-implementation-plan.md)

## Problem

Cinema Paradiso is becoming the main media interface for a Windows 10/11 mini PC connected to a television. It already knows the identity and metadata of local, discovered, and listed movies, but it does not answer the next practical question: where can this movie be watched in the user's country right now?

Users must separately search subscription services, rental stores, and cinema listings. Even after finding the right provider, they must leave CP, open a browser or Windows application, find the provider again, sign in, and repeat the movie search.

CP needs a movie-first path from its existing cards to current regional availability and then into the user's real, logged-in provider website. It should do this without building a provider-specific client for every company, storing subscription credentials, scraping provider catalogues, or turning volatile availability into permanent library metadata.

## Intended Experience

- Every shared expanded movie card with an accepted TMDB ID can show a **Where to Watch** action.
- Nothing is fetched merely because a card is rendered or expanded. Availability is requested only when the user clicks the action.
- A polished CP-native popup shows the movie, selected country, provider logos, subscription/free/ad-supported/rent/buy groupings, and Egyptian theatrical information where available.
- The popup clearly distinguishes included subscription access from rental and purchase offers.
- The popup can hand a provider result to CP Watch, which opens the configured, logged-in provider website and searches for the movie when a supported search route exists.
- When provider search navigation is unavailable, CP opens the provider homepage or TMDB's regional watch-options page as an honest fallback.
- Provider sessions persist across CP restarts, so users do not normally sign in again.
- Passwords are entered only into the provider's real website. With explicit user consent, WebView2 may offer its native password saving and autofill; CP never receives or stores the credential itself.
- The user can return to CP without navigating through the Windows desktop or a conventional browser interface.

The current preferred public name is **Watch**, with **Where to Watch** as the movie-card action and **Your Services** as a possible standalone page heading. **Tubes** remains a possible product name or internal codename. The final name has not been chosen.

## Proposed Direction

This combined direction is approved in principle. The availability popup, configurable services workspace, and WebView2 launcher are complementary parts of one system rather than competing features. Product implementation remains gated by the desktop mockups and the provider compatibility experiment defined in the implementation plan.

### Movie-first entry point

The primary entry point should be the authoritative shared expanded-card component so Library, Discover, Movie Lists, Home, and AI-produced movie results behave consistently. The action should appear for owned and unowned movies because availability depends on the movie's accepted TMDB identity, not CP ownership.

The action should be hidden or disabled with a clear explanation when no TMDB ID is available. It must remain separate from CP's existing configured **Stream** action: Stream attempts playback through a configured movie URL, while Where to Watch reports regional availability and routes the user toward a legal provider.

### On-demand availability with no SQL dependency

Use the existing TMDB movie ID to request two kinds of regional information:

- TMDB Watch Providers, powered by JustWatch, for subscription, free, ad-supported, rental, and purchase availability.
- TMDB regional release dates and Now Playing classification for Egyptian theatrical information.

The availability feature should not read from or write to the SQL catalogue beyond receiving the movie's existing TMDB ID from the card. Availability is external, regional, and volatile, so it must not become part of canonical movie metadata or owned-library state.

The request flow should be:

1. The user clicks Where to Watch.
2. React sends `tmdb_id` and the selected ISO country code to one CP backend endpoint.
3. The backend queries the required TMDB endpoints and normalizes their results.
4. The popup renders the normalized response.
5. The response is cached in memory by `tmdb_id + region` for approximately 12 to 24 hours.

Losing this cache when CP restarts is harmless. A small frontend session cache can prevent reopening the same popup from making another request during the same CP session. The selected watch country belongs in normal application configuration, not SQL.

TMDB's Watch Providers response includes provider IDs, names, categories, display priority, and logo paths. It does not provide a guaranteed provider-specific direct-play URL. The response includes one regional TMDB watch page, and JustWatch attribution is mandatory wherever the availability data appears.

### Where to Watch popup

The popup should be designed and visually approved before implementation. The current direction is a desktop-only modal approximately 850 to 950 pixels wide with a maximum height around 80 percent of the display.

The popup should include:

- Movie poster, title, year, and selected country in the header.
- A refresh action and a clear close action.
- A prominent cinema strip using careful wording such as **TMDB lists this as currently in Egyptian cinemas**.
- Large provider tiles for services included with a subscription.
- Separate sections for free and ad-supported availability when present.
- Compact rent/buy rows that combine the same provider into one entry with multiple offer badges.
- Uniform logo containers so provider artwork with different proportions still looks intentional.
- Loading skeletons, an inline error state, and an honest **No availability information found** state.
- A visible last-checked time and **Availability data by JustWatch** attribution.
- A **View watch options** action linking to TMDB's regional page as the universal fallback.

Provider tiles are informational until CP has a real destination for that provider. They must not imply direct playback when CP only knows the provider name.

### One generic provider model

Use one authoritative collection of web-service entries instead of provider-specific Netflix, Disney+, Apple TV, Shahid, or YouTube implementations. Common presets may contain:

- Stable CP provider identifier
- Display name
- HTTPS homepage
- Optional search URL template containing a `{query}` placeholder
- One or more matching TMDB provider IDs
- Optional icon or visual treatment
- Enabled state
- Display order

Provider-to-TMDB mappings and supported search templates should live in centrally maintained presets, not in card components or scattered conditionals. Custom services may supply a name and homepage without claiming search support.

Closely named services must not be merged carelessly. For example, a provider sold as an Amazon Channel may represent a different subscription entitlement from the provider's direct service.

### One authoritative launcher

All service cards and Where to Watch results should call one launcher responsibility, conceptually:

```text
openWebService({
  providerId,
  action: "search",
  query: "Inception 2010"
})
```

The launcher should choose the best available destination in this order:

1. A genuine title-specific provider URL, if a future licensed source supplies one.
2. The provider's supported search URL with the encoded title and year.
3. The provider's configured search page or homepage.
4. TMDB's regional watch-options page.

If a provider does not expose its search query in the URL, CP can open the provider's search page and make the movie title easy to copy. CP should not inject scripts into remote provider pages, inspect their private DOM, scrape logged-in content, or automate their search boxes. Those approaches would be fragile, unsafe, and likely to break whenever a provider changes its website.

While CP still runs in a normal browser, the launcher can open the selected destination as a separate top-level browser page. When CP gains its Windows desktop shell, the launcher can delegate to that host without replacing the popup, shared-card action, provider presets, or saved configuration.

### Combined user journey

The intended end-to-end path is:

```text
CP movie card
  -> Where to Watch
  -> Available on Shahid VIP in Egypt
  -> Search in Shahid
  -> Logged-in Shahid website inside CP
  -> User confirms the provider result and starts playback
```

Provider search is not the same as a verified direct title link. The user may still need to select the correct result, and stale availability data may occasionally lead to an empty provider search.

### Standalone services workspace

A standalone Watch/Your Services workspace is a core part of the feature. Users must be able to browse Netflix, Shahid, YouTube, or any other configured provider without starting from a CP movie. It must reuse the same provider collection and launcher used by the popup rather than introducing a second service model.

Settings must allow any number of provider entries. The workspace presents the enabled entries in the user's chosen order, supports common presets and fully custom HTTPS services, and provides clear edit and empty-state paths. Selecting a provider opens its homepage through the same launcher used for a movie search. The two equally supported entry paths are therefore:

1. **Movie-first:** expanded movie card -> Where to Watch -> provider availability -> search/open provider.
2. **Platform-first:** Watch workspace -> selected configured provider -> explore the provider website.

### Planned Windows desktop behavior

CP will try a thin Windows x64 host using Microsoft Edge WebView2. WebView2 is the Edge browser engine embedded inside CP; it does not require a visible Edge window. Provider compatibility is not assumed and must still be proved by the isolated experiment:

1. The host starts the existing local Flask backend.
2. It displays CP's existing React interface without opening a conventional browser window.
3. Watch opens a selected provider as a top-level browser surface, not as an iframe inside the React page.
4. A small CP-owned toolbar supplies Back to CP, Back, Forward, Reload, Home, Fullscreen, and Open in Edge actions.
5. An app-specific persistent WebView2 profile retains cookies, permissions, and provider session state.

If a provider rejects WebView2 login or protected playback, the same central launcher should offer a full Microsoft Edge app-style window as the compatibility fallback. That fallback is less visually integrated but uses a browser the providers officially support.

Use the Evergreen WebView2 Runtime so the browser engine receives Microsoft security and compatibility updates. The Windows installer must detect the runtime and install it when missing. Windows 11 is the preferred target; Windows 10 support is conditional on Microsoft continuing WebView2 servicing and on the target hardware passing the same provider tests. A fixed WebView2 runtime is not the default because it would add substantial package size and make CP responsible for browser-runtime updates.

While a provider is open, it owns the top-level WebView2 content surface rather than appearing inside a remote iframe. CP's normal sidebar should be hidden and replaced by a narrow native toolbar containing Back to Watch, Back, Forward, Reload, Home, the real hostname, Fullscreen, and Open in Edge. The hostname and secure-connection state must remain visible enough to protect users from misleading login pages.

### Browser profile, passwords, and security boundary

Persistent provider sessions and saved passwords are related but separate choices:

- **Remember sign-ins** retains provider cookies and site data and should default to on for the intended living-room experience.
- **Offer to save and autofill passwords** uses WebView2's native password manager and should default to off. Enabling it must be an explicit user choice and should preserve WebView2's own Save/Update Password prompt.
- CP must never render its own provider password field, store a password in `config.json` or SQL, read autofilled credentials, inspect authentication tokens, or advertise access to passwords saved by Edge or Apple Keychain.
- General form and payment autofill should remain off. Payment information is outside CP's responsibility.
- Settings must provide separate controls to clear provider sessions/site data, delete passwords saved in the CP Watch profile, and reset all Watch browser data.
- WebView2 user data must live in a protected per-Windows-user location under LocalAppData, not beside the portable executable, on a network share, or inside normal CP exports and backups.
- Remote provider origins must never receive CP native host objects, Flask administration APIs, filesystem access, or injected scripts. A minimal native launch bridge may be exposed only to CP's own trusted local origin.
- External custom services must use HTTPS. CP must show the real hostname and warn before unexpected navigation outside the configured domain, while still permitting explicit authentication redirects.
- Production builds should disable WebView2 developer tools on provider surfaces and define safe behavior for downloads, pop-ups, permissions, and new-window requests.

Separate Windows user accounts remain the strongest way to separate household credentials and sessions. Separate CP household browser profiles or a Windows Hello/CP Watch lock can be evaluated later, but the first implementation must not imply that a shared Windows session provides private credentials for each household member.

### Compatibility experiment before desktop implementation

Before committing CP to the WebView2 direction, build an isolated proof of concept outside the CP product code and test the intended providers on representative Windows 10/11 mini-PC hardware. The experiment must test real playback rather than stopping after a homepage loads.

The test matrix should cover:

- Login, logout, two-factor authentication, and account/profile selection
- Protected video playback and DRM errors
- Fullscreen entry and exit
- Subtitles and alternate audio
- Available video resolution, including 1080p and 4K where applicable
- Hardware acceleration, HDCP, HDMI audio, and television display behavior
- Provider-created pop-ups and redirects
- Persistent login after restarting the host
- Sleep, wake, network interruption, and playback recovery
- Keyboard and mouse navigation
- Search URL behavior for each maintained provider preset
- A reliable return path to CP

Initial providers: Netflix, Apple TV, Disney+, Shahid, and YouTube.

## Constraints And Risks

- Major providers prevent their complete websites from being displayed in third-party iframes through `X-Frame-Options` or Content Security Policy. A normal React iframe is therefore not a viable generic implementation.
- Paid services use DRM, browser/device recognition, HDCP, and hardware-dependent decoding. A site loading successfully does not prove that protected video will play.
- Providers officially support specific full browsers and can change browser requirements or embedded-browser behavior without coordinating with CP.
- WebView2 uses the Edge engine but is not automatically equivalent to the full Edge browser from a provider-support perspective.
- TMDB/JustWatch availability can be delayed, incomplete, or missing for a country. Missing data must not be presented as proof that a movie is unavailable.
- TMDB's Now Playing classification is based on regional theatrical-release windows, not live Egyptian cinema schedules or individual showtimes.
- JustWatch attribution is required when displaying TMDB Watch Providers data.
- TMDB does not return full provider-specific deep links from its Watch Providers endpoint.
- Provider search URLs are provider-controlled and can change. Presets need validation and a safe homepage fallback.
- A provider search may return the wrong edition, remake, or similarly titled movie. CP must not claim that a search result is a verified title match.
- Login pages may use two-factor authentication, CAPTCHA, external identity providers, or new windows that the desktop host must handle safely.
- Arbitrary URLs create a phishing risk. The service surface must display the real hostname, reject unsafe URL schemes, preserve normal browser security, and avoid injecting CP scripts or privileged bridges into remote pages.
- CP must not proxy, alter, scrape, or attempt to bypass provider pages, DRM, geographic restrictions, advertising, or subscription requirements.
- Provider browser data must live in a persistent, writable user-data location and have an explicit reset/sign-out path.
- Remembered sessions are a practical shared-device security risk even when no password is stored. Anyone using the same unlocked Windows account may be able to open a signed-in provider.
- A WebView2 password store is safer than CP inventing its own credential vault, but it still depends on the security of the Windows account and the WebView2 profile.
- A desktop browser surface adds memory and GPU use that must be measured on the eventual mini-PC hardware.
- TMDB's developer API is free for attributed non-commercial use; commercial distribution requires a separate licensing review.

## Non-Goals

- Building custom Netflix, Disney+, Apple TV, Shahid, or YouTube clients.
- Combining provider catalogues with CP's local/TMDB movie catalogue.
- Persisting watch availability, cinema state, or provider offers in SQL.
- Background-scanning the whole CP library for current availability.
- Searching every provider catalogue by scraping or automating its logged-in website.
- Tracking provider watch history or availability by scraping websites.
- Building a CP password manager or storing subscription usernames, passwords, payment details, or authentication tokens in CP configuration or SQL.
- Claiming exact Egyptian cinema locations or showtimes from TMDB release-window data.
- Bypassing DRM, advertisements, geographic restrictions, provider policies, or subscription checks.
- Replacing CP IPTV or merging subscription services with IPTV channels.
- Designing or testing a mobile interface.
- Treating Windows startup behavior and final EXE packaging as approved merely because this idea anticipates them.

## Open Questions

- Should the public workspace name be Watch, Tubes, or another name?
- What exact popup composition, dimensions, logo treatment, and empty states should be approved through a desktop mockup?
- Should the default watch region be Egypt, and should the popup allow a temporary region switch without changing Settings?
- Should the first availability version use only TMDB, accepting one regional watch link, or should direct provider links become a requirement that triggers comparison with a service such as Watchmode?
- Which TMDB provider IDs map safely to each maintained CP service preset?
- Which initial providers expose stable, legal search URLs that preserve the query after authentication?
- What should the launcher do when provider availability exists but no maintained service preset matches it?
- Should the first version use one shared CP Watch browser profile, or must household browser profiles or a Windows Hello/CP Watch lock be delivered before password saving can be enabled?
- What should happen when a provider navigates outside its configured domain for authentication, support, or payment?
- Does WebView2 pass real login and DRM playback tests for every initial provider on the target hardware?

## Dependencies

- A reviewed desktop visual mockup for the Where to Watch popup.
- A defined Windows desktop-shell direction for the final CP application.
- Representative Windows 10/11 mini-PC hardware connected to a television over HDMI.
- Current Microsoft Edge/WebView2 runtime and GPU drivers on the target device.
- Legitimate test accounts for the initial providers.
- Validation of provider search URL templates and TMDB provider-ID mappings.
- An isolated WebView2 compatibility experiment with recorded provider-by-provider results.
- Acceptance of the staged [CP Watch implementation plan](../plans/cp-watch-implementation-plan.md), including security boundaries, cache behavior, fallback behavior, packaging, and automated regression coverage.

## Revisit Conditions

The idea is approved in principle. Production implementation remains gated by Stage 0 of the implementation plan: accept the desktop mockups, verify the TMDB response and attribution contract, validate the initial provider mappings/search routes, and record which services support real login and protected playback in WebView2 versus requiring the Edge fallback. A failed provider test changes that provider's launch policy; it does not justify fragile DOM automation or DRM workarounds.

## References

- [`run.bat`](../../run.bat) - current browser-based CP launcher.
- [`package.json`](../../package.json) - current React/Vite dependency boundary; no desktop host exists yet.
- [`src/api/movieDetails.js`](../../src/api/movieDetails.js) - existing lazy details path keyed by owned path or TMDB ID.
- [`src/components/SharedMovieCards.jsx`](../../src/components/SharedMovieCards.jsx) - authoritative shared expanded-card surface proposed to own the action.
- [`src/features/downloads/DownloadsWorkspace.jsx`](../../src/features/downloads/DownloadsWorkspace.jsx) - existing same-origin qBittorrent iframe, which is not a model for third-party subscription sites.
- [TMDB: Movie Watch Providers](https://developer.themoviedb.org/reference/movie-watch-providers)
- [TMDB: Movie Now Playing](https://developer.themoviedb.org/reference/movie-now-playing-list)
- [TMDB: Movie Release Dates](https://developer.themoviedb.org/reference/movie-release-dates)
- [TMDB: Region Support](https://developer.themoviedb.org/docs/region-support)
- [TMDB: API FAQ and attribution](https://developer.themoviedb.org/docs/faq)
- [Microsoft: Manage WebView2 user data folders](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/user-data-folder)
- [Microsoft: Support multiple WebView2 profiles](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/multi-profile-support)
- [Microsoft: WebView2 distribution](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
- [Microsoft: WebView2 password autosave](https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2settings.ispasswordautosaveenabled)
- [Microsoft: Clear WebView2 browsing data](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/browsing-data)
- [Microsoft: Use Progressive Web Apps in Edge](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/ux)
- [Netflix supported browsers and system requirements](https://help.netflix.com/en/node/30081)
- [Disney+ browser requirements](https://help.disneyplus.com/en-GB/article/disneyplus-computer-browser-requirements)
- [Watchmode streaming availability API](https://api.watchmode.com/)
