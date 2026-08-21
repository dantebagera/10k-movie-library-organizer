# Changelog

## v2.8.5 - August 2026

Cinema Paradiso v2.8.5 adds one shared advanced-search language across the local Library and TMDB Discover, expands IPTV movie review and classification, and tightens native playback and catalogue behavior.

### Added

- A shared, validated advanced-search query model and desktop criterion builder for Library and Discover.
- SQL-owned compound Library search, identity lookup, stable query signatures, paging, and complete-result selection.
- TMDB-owned compound Discover planning with bounded provider paging and explicit handling for criteria TMDB cannot prove globally.
- Provider-local IPTV movie classification, metadata-review, rebuild, fusion, manual-match, and list workflows with preview-before-apply routes.
- Optional localhost Ollama assistance for IPTV classification with bounded payload validation and provider-local settings.
- Complete normalized audio-track inventories in authoritative media-file facts.
- Native-player subtitle action icons and Windows media play/pause command handling.
- Zero-regression design records for advanced-search ownership, continuity, and release handoff.

### Changed

- Library and Discover simple filters compile into the same query contract used by Advanced mode instead of maintaining a second filter language.
- IPTV movie storage, enrichment, filtering, pagination, and review state remain provider-local while exposing richer desktop controls.
- Native-player source metadata and compatibility now identify player `0.1.25` for Cinema Paradiso 2.8.5.
- Desktop search, pagination, Maintenance, and IPTV layouts were refined without introducing a separate mobile redesign.

### Fixed

- Completed movies opened for rewatch now create a fresh resumable playback session while preserving the independent Watched state.
- Continue Watching can present an unfinished rewatch even when the movie remains Watched.
- Maintenance audio decisions use every audio track and exclude subtitle streams from the audio inventory.
- Stale Discover requests and navigation history no longer replace a newer advanced-search result.
- Native Windows media play/pause requests respect the resume-decision gate and reveal player controls.

## v2.8.4 - August 2026

Cinema Paradiso v2.8.4 expands Home trailers, makes list and card actions update immediately, and keeps bulk selections and page navigation consistent across the desktop workspaces.

### Added

- Balanced Home trailer channels for Rotten Tomatoes Trailers and Movie Trailers Source, with source filters and cursor-based loading.
- Optional YouTube Data API configuration, validation, and clearing in Settings for longer trailer feeds and fallback trailer search.
- In-player matching actions for Home trailers, including session-only manual TMDB matching, follow controls, and direct Discover navigation.
- Regression coverage for cross-page selection and synchronized top-and-bottom pagination across Library, Discover, Movie Lists, and Maintenance.
- Planning notes for a possible Trakt related-movies integration without adding a second recommendation authority.

### Changed

- Curation routes attach authoritative SQL ownership identity before mutating user and system lists.
- Watched and Watchlist controls update optimistically across Home, Library, Discover, Movie Lists, and AI Control, with rollback when persistence fails.
- Discover movie, people, keyword, relationship, and AI Pick grids expose the same page controls above and below results.
- Movie Lists expose synchronized page controls above and below long lists.
- Shared movie-card and Home layouts use the updated desktop spacing, action, and complete-row behavior.

### Fixed

- Selections now accumulate across result pages and bulk actions receive the complete selected set instead of only the visible page.
- Maintenance no longer clears selected duplicate or identity paths when another page loads.
- Home trailer feeds ignore unavailable videos, preserve exhausted-source cursors, and avoid duplicate reposts while balancing channels.
- Trailer fallback and manual movie matches remain session-only and do not create hidden persistent mappings.
- System-list mutations preserve canonical owned paths and identities instead of degrading owned movies into remote-only entries.

## v2.8.3 - August 2026

Cinema Paradiso v2.8.3 makes externally added movies appear as complete Library cards while the app is running, refines the desktop navigation, and advances the native player with first-party Windows window controls.

### Added

- Background Library observation, startup catch-up, stable-file checks, and canonical final-card publication for movies added outside Cinema Paradiso.
- Catalog generation events so active Library surfaces can refresh from the authoritative SQL catalog without polling or replacing the grid with a loading screen.
- A catalog writer lease that serializes ingestion and reconciliation work around the existing catalog authority.
- First-party native-player title-bar controls and Windows window-chrome integration.
- Distinct icons for Watched, Watchlist, and Following system lists.

### Changed

- Library ingestion now completes probe, identity, metadata, artwork, and catalog publication before exposing a new Movie View card.
- The desktop sidebar uses a clearer collapsed and expanded navigation hierarchy while preserving the existing workspace routes.
- The native-player bundle advances to `0.1.24-qt6.10.3-mpv20260610-lgpl` with broader smoke coverage for windowed and fullscreen interactions.
- Startup defers non-critical release and streaming work until the initial Library result is ready.

### Fixed

- Background Library refreshes preserve the current grid, filters, sort, page, selection, and scroll position instead of flickering through foreground loading state.
- Repeated file-system notifications and concurrent catalog writers converge on one final card instead of publishing duplicate or partial entries.
- Native-player custom chrome retains correct minimize, maximize, restore, close, drag, resize, and fullscreen behavior on Windows.
- Movie Lists communicate the role of built-in system lists without adding route-specific list logic.

## v2.8.2 - July 2026

Cinema Paradiso v2.8.2 adds first-party native playback, a Continue Watching screening room, and a more cinematic Home while tightening shared card and large-grid behavior.

### Added

- Bundled Qt Quick and libmpv native player with play/pause, seek, volume, speed, audio-track, subtitle-track, and fullscreen controls.
- Continue Watching history backed by the existing SQL catalog authority and exposed as a compact Home rail.
- Integrated subtitle search, download, save-next-to-movie, language preference, delay, and per-title restoration.
- Home trailer rail sourced from the configured YouTube playlist.
- Native-player settings, runtime status, keyboard shortcuts, and provider configuration.

### Changed

- Home now presents the cinematic hero, library health, release watchlist, Continue Watching, trailers, trending movies, and upcoming releases in one desktop hierarchy.
- Movie grids calculate complete rows from their available width while keeping every bounded result reachable through pagination.
- Owned movie cards use compact quality and source labels; detailed physical media facts remain in Library File View.
- AI Control batches owned-title checks and retrieves bounded TMDB pages concurrently without changing its Ollama skill contract.
- The sidebar version and portable archive now derive from the authoritative v2.8.2 package metadata.

### Fixed

- Native playback remains responsive during long sessions and closes cleanly without leaking player processes.
- Playback launch, progress reporting, resume state, audio/subtitle restoration, and safe OS fallback are validated across the app-to-player protocol.
- Discover, Library, Movie Lists, AI Control, and IPTV card owners follow the same shared expanded-card and grid contracts.
- Home movie selection and trailer loading ignore stale results and preserve deterministic ordering.

## v2.8.1 - July 2026

Cinema Paradiso v2.8.1 expands catalog search, completes bounded Discover pagination, and tightens shared movie-card and AI Control behavior.

### Added

- Catalog schema v8 writer and keyword projections with staged backup, parity, shadow, and rollback evidence.
- Writer and keyword search across Library and Discover through their authoritative SQL and TMDB paths.
- Bounded pagination that keeps valid Library and Discover search results reachable without unbounded reads.
- Transient Arabic display for shared expanded movie cards without changing persisted catalog metadata.
- Bulk source upgrades for owned movies and explicit Ollama model recommendations in Settings.

### Changed

- Shared expanded movie cards use one redesigned layout with consistent proportions and workspace margins.
- AI Control actions are card-first and complete their approved library mutations through the existing authoritative services.
- Source review requires exact quality matching before an upgrade is accepted.
- The sidebar version is rebuilt from the package version and now identifies v2.8.1.

### Fixed

- Home inspectors retain followed-movie plots.
- Discover relationship browsing no longer applies stale responses after navigation changes.
- Catalog migration audits and JSON shadow checks fail safely when their prerequisites are not satisfied.
- Search pagination preserves current filters and avoids stale or incomplete result sets.
- Portable release packaging derives its version from the authoritative package metadata instead of a separate hardcoded value.

## v2.8.0 - July 2026

Cinema Paradiso v2.8.0 begins with the SQL catalog migration and adds a separated, provider-agnostic IPTV workspace.

### Added

- SQL migration parity matrix and catalog audit tooling.
- Historical JSON shadow comparison for cutover verification.
- Browser ownership-cache regression coverage across shared movie-card workflows.
- Restart-safe recovery for completed downloads that still need catalog import.
- User-triggered updates for the isolated portable qBittorrent runtime through the official GitHub release.
- Xtream IPTV Settings card with redacted saved credentials, connection testing, and full catalog sync.
- Separate IPTV Home, Live TV, Movies, Series, Favorites, and My Lists views with provider category order preserved.
- Provider-scoped IPTV custom lists with mixed media, manual ordering, rename/delete controls, and retained snapshots for unavailable provider items.
- Dedicated `iptv.sqlite` storage for provider categories, media, favorites, custom lists, detail caches, and watch history.
- Lazy provider movie/series details, Unicode and Arabic search, episode browsing, and short EPG support.
- Tokenized loopback playback relay with FFmpeg HLS remuxing so credential-bearing stream URLs never reach React or FFmpeg process arguments.
- Portable-release support for an independently bundled FFmpeg runtime and third-party manifest.
- Checksum-addressed local storage for selected owned posters and people portraits, with resumable bounded backfill and custom-poster protection.

### Changed

- SQL is the active catalog authority, with legacy JSON retained for rollback and shadow comparison.
- Library expanded cards load persisted canonical SQL details.
- Download submissions preserve TMDB and IMDb identity through completion and reconciliation.
- The sidebar version is rebuilt from the package version and now identifies v2.8.0.
- IPTV remains separate from Cinema Paradiso ownership, local catalog identity, Movie Lists, and torrent workflows; its Favorites and custom lists stay provider-scoped inside the IPTV workspace.
- Library paging, filters, sorting, facets, filtered selection, card projections, and owned details now use bounded SQL reads.
- Artwork invalidation uses a separate asset generation so artwork maintenance does not invalidate the catalog.

### Fixed

- Stale ownership state after catalog generation changes.
- Cross-workspace movie identity consistency.
- Interrupted completed-download import recovery.
- User-cancelled unfinished torrents now close as normal terminal jobs instead of remaining false migration-review records.
- Windows SQLite handles are closed after every IPTV transaction so catalog files can be replaced and test data can be cleaned reliably.
- Per-provider invalid-certificate handling is explicit and disabled by default instead of weakening TLS globally.
- IPTV playback directories remain owned by their active FFmpeg session instead of being deleted when another service instance starts.
- Live IPTV remuxing is paced in real time and keeps a bounded rolling HLS window instead of rapidly accumulating provider segments.
- Slow FFmpeg shutdowns defer directory removal until the muxer exits, preventing missing-segment races and orphaned playback data.
- Live IPTV relaying emits provider data promptly, retains a larger rolling safety window, and recovers bounded browser network or media failures before giving up.
- Live IPTV remuxing can consume provider recovery bursts faster than real time and splits irregular provider GOPs into shorter browser segments, allowing playback to rebuild its buffer after delivery stalls.

## v2.7.0 - July 2026

Cinema Paradiso v2.7.0 adds an experimental AI Control workspace for review-first natural-language library actions while preserving the v2.6 source-search, qBittorrent, movie-card, trailer, streaming, identity-review, and metadata-repair foundations.

### Added

- AI Control sidebar workspace for plain-language find, create-list, download-planning, and delete-planning requests.
- AI Control preview and execute APIs with a capability schema for supported actions and safety requirements.
- Trusted-indexer controls for AI Control download planning, with YTS/YIFY used as the default trusted source when no explicit source is configured.
- Card and table result views for AI Control find results, including pagination, total counts, list actions, and Discover-style card metadata.
- Blocked-row reporting so skipped or unsafe rows remain visible with the reason they were blocked.
- Staged preview-loading messages for long-running AI Control planning.

### Changed

- AI Control plans are review-first: commands produce a preview plan before execution, and execution requires the reviewed plan ID.
- Download planning skips movies already owned locally and uses trusted Prowlarr sources for source searches.
- Find and list planning can use TMDB genre, year-range, top-rated, and person-grounded discovery paths.
- AI Control result rows preserve TMDB and Plex metadata needed by the shared movie-card/list workflow.
- The sidebar version is rebuilt from the package version and now identifies v2.7.0.

### Fixed

- Vague prompts now return clarification requests instead of running an unintended action.
- Malformed AI filters return safe no-match previews instead of server errors.
- Delete execution is rejected if a file changed after the preview plan was created.
- Large delete plans require an explicit confirmation phrase before execution.

### Notes

- AI Control is experimental and does not run actions automatically.
- qBittorrent remains the bundled tested runtime path; install/update controls stay disabled in this release.
- v2.6.7 remains the previous public rollback point before the AI Control release.

## v2.6.7 - July 2026

Cinema Paradiso v2.6.7 tightens source-search reliability, YTS handling, and local release packaging while preserving the v2.6.6 movie-card, trailer, streaming, and unreleased-movie improvements.

### Added

- YTS RSS latest-feed supplement for Browse Indexers when the selected trusted YTS/Prowlarr source has no fresh latest rows.
- IMDb-first source queries for Explore search and followed-release checks.
- TMDB original-title and alternative-title fallbacks for source searches.
- Refreshed Cinema Paradiso icon assets for packaging and Windows presentation.

### Changed

- Source searches now use a progressive per-indexer job path so slow or timed-out indexers do not hide fast valid results.
- Prowlarr result links are normalized so redirect-style download URLs can still expose usable magnet links when an info hash is available.
- Source-search query budgets are bounded per alias and per job to keep slow providers from blocking the UI.
- The sidebar version is rebuilt from the package version and now identifies v2.6.7.

### Fixed

- Rejected polluted IMDb search results before falling back to title/year queries.
- Accepted known alias titles while still rejecting wrong-year torrent results.
- Preserved valid YTS results even when seeders are zero.
- Prevented stale local builds from carrying the previous sidebar version into the release artifact.

### Notes

- qBittorrent remains the bundled tested runtime path; install/update controls stay disabled in this release.
- v2.6.6 remains the previous public rollback point before the source-search/YTS reliability release.

## v2.6.6 - July 2026

Cinema Paradiso v2.6.6 polishes the movie-card experience, trailer playback, streaming configuration, and unreleased-movie handling while keeping the local-first v2.6 architecture.

### Added

- Unified movie-card component shared across Library, Discover, Ask AI, collection/person views, and expanded details.
- In-app trailer modal with embedded YouTube playback and fullscreen support.
- Streaming configuration API and Settings controls for enable/disable, action label, and URL template.
- Unreleased-movie release-date labels for Discover/Home cards and selected movie details.

### Changed

- Movie posters use uncropped contain framing with stronger card sizing, cleaner expanded layouts, and top-right expanded ratings.
- Discover and Home hide stream/source actions for unreleased unowned movies while still allowing indexer browsing where appropriate.
- TMDB detail and collection transforms preserve runtime, release date, director, cast, collection metadata, trailer URL, and card-ready fields more consistently.

### Fixed

- Fresh Discover searches now clear stale cards before fetching and ignore older in-flight responses.
- Duplicate TMDB rows in Discover use stable position-aware keys.
- Cached TMDB details without release dates are refetched so unreleased gates and detail panels have current release data.

### Notes

- qBittorrent remains the bundled tested runtime path; install/update controls stay disabled in this release.
- v2.6.5 remains the previous public rollback point before the card/trailer/streaming polish release.

## v2.6.5 - June 2026

Cinema Paradiso v2.6.5 improves large-library metadata matching, followed-release availability, and bulk list workflows while keeping the local-first v2.6 architecture.

### Added

- Trusted Prowlarr indexer selection for followed-release availability, with YTS/YIFY used as the default trusted source when no explicit choice was saved.
- Bulk selection and add-to-list workflows in Library and Discover.
- List popup select-all and local-file copy export with a folder browser.
- Library reset-filters control.

### Changed

- Followed releases only become Available from trusted Prowlarr indexers and approved sources: WEBRip, Blu-ray, BDRip, or BRRip.
- Trusted release indexers are managed from a Prowlarr Settings popup instead of expanding the Settings card.
- Automatic metadata matching accepts clearly dominant exact TMDB title/year matches while keeping strong provider conflicts in review.
- Manual unmatched matches persist as accepted metadata across restarts.

### Fixed

- Rejected WEB-DL, Remux, BDRemux, HDCAM, and TELESYNC-style followed-release matches.
- Improved adult-title handling through separate metadata-search and Movie View visibility settings.
- Kept Movie View fast after restart by avoiding unnecessary full metadata fetches during normal library loading.

## v2.6.4 - June 2026

Cinema Paradiso v2.6.4 adds the Help workspace and prepares the app for a portable release that includes a tested bundled qBittorrent runtime.

### Added

- Help sidebar page with setup guidance for Plex, Prowlarr, TMDB, Ollama, and qBittorrent.
- Official dependency links and Settings shortcuts for each Help section.
- Portable release packaging helper for building a ZIP artifact with the tested bundled qBittorrent runtime.

### Changed

- Settings remains the only dynamic Ready/Missing and connection-test area; Help is documentation only.
- qBittorrent install/update controls are disabled for v2.6.4 because the portable release includes the tested runtime.
- Embedded qBittorrent status now describes the bundled runtime and keeps the system default client option.

### Fixed

- CP-managed qBittorrent now runs hidden in the background instead of opening a standalone desktop window.
- The portable release helper excludes qBittorrent debug symbols, profiles, incomplete downloads, and user data.

## v2.6.3 - June 2026

Cinema Paradiso v2.6.3 strengthens metadata identity, repair, and curation workflows while preserving the local-first behavior of the v2.6 stable line.

### Added

- Identity Review queue for uncertain matches, provider conflicts, and metadata discrepancies, with pause, resume, rescan, selection, and explicit apply controls.
- Home metadata-health counts for unmatched, pending, and identity-review items, with direct Cleanup navigation.
- Library reconciliation for stable files that are missing metadata records, including files predating the current metadata checkpoint.
- Local title/year correction for owned movies without changing Plex metadata or renaming files.
- Durable poster overrides using TMDB artwork, Plex artwork, or local uploads, with reset support.
- Protected Watched and Watchlist system lists, poster controls, and Library viewing-state filters.
- Richer manual Plex matching with local-only apply behavior and explicit retry after a Plex scan.

### Changed

- Unified Library, Discover, collections, lists, duplicates, posters, and ownership checks around accepted Cinema Paradiso identities.
- Improved automatic TMDB decisions using exact titles, official alternative titles, provider evidence, and controlled release-year tolerance.
- Preserved accepted movie identity when provider enrichment is missing, unavailable, or incomplete.
- Grouped duplicate copies by shared strong identity while refusing to merge conflicting provider IDs.
- Smart Match now keeps matching, review, apply, and rename as separate explicit operations.

### Fixed

- Prevented conflicting strong IDs or weak title-only evidence from silently replacing an accepted movie.
- Rejected stale Smart Match proposals after the underlying identity revision changes.
- Hardened metadata JSON writes and restart recovery, including repair backups for corrupt state.
- Prevented Plex tokens and sensitive provider details from appearing in returned errors.
- Kept poster and metadata overrides through provider refreshes and shared them only across conflict-safe duplicate identities.
- Prevented previously unrecorded library files from remaining invisible to metadata repair workflows.

### Notes

- Plex matching remains local and read-only: applying a match does not modify the Plex server.
- Watched applies only to owned movies; Watchlist can also contain online discovery results.
- Runtime data, local posters, configuration, caches, generated builds, and dependencies are not committed.
- `v2.6.0` remains the stable rollback point before the identity and metadata changes in this release.

## v2.6.0 - June 2026

Cinema Paradiso v2.6 is the current stable baseline for the React/Vite movie archive console. It folds the recent UI, metadata, Discover, Library, Cleanup, Settings, and release-watchlist work into one recoverable GitHub release.

### Added

- App metadata storage for file facts, TMDB metadata, Plex metadata, manual matches, and conflicts under user data.
- TMDB-based local metadata matching so users without Plex can still build a rich offline movie library.
- Cleanup > Unmatched Metadata workflow with TMDB search/apply, optional Plex matching, rename, fix-path, and refresh actions.
- Discover vote-count preservation and minimum vote filtering for stronger rating confidence.
- Browse Indexers source selector that loads enabled Prowlarr indexers before search/load and can query one selected indexer.
- Progressive Browse Indexers enrichment: raw Prowlarr rows appear first, then TMDB details are added when available.
- Tests for metadata architecture, library ownership matching, Discover utilities, adult metadata settings, library action UX, and Prowlarr indexer scoping.

### Changed

- Movie View now focuses on files with accepted Plex or TMDB metadata; File View remains the complete local-file management surface.
- Plex is optional for rich local metadata instead of being the only practical metadata source.
- Discover/Home ownership matching prefers stable IDs such as TMDB/IMDb before title/year fallback.
- Browse Indexers search and latest feeds can be scoped to `All indexers` or one selected Prowlarr source.
- Project docs now describe v2.6 as the stable release baseline before future code optimization work.

### Fixed

- Removed the old Flask template UI from the public app so a missing React build can no longer show the pre-React interface.
- Updated Windows `run.bat` to bootstrap `.venv`, install Python dependencies, install frontend dependencies when needed, build React when `dist/` is missing, then start Flask.
- Flask now returns a clear setup error if the React build is missing instead of silently falling back to legacy HTML.
- Reduced false "not in library" Discover results caused by title differences between Plex and TMDB.
- Prevented Browse Indexers from timing out just by opening the tab; broad latest loading is now explicit.
- Preserved indexer rows without TMDB metadata instead of hiding them.
- Improved v2.6 metadata read-path performance by avoiding writes and TMDB fetches during normal library reads.
- Kept local resolution probing so cropped 1080p files are not mislabeled as 720p.

### Notes

- `config.json`, `data/`, `cache/`, `res_cache.json`, `node_modules/`, `dist/`, and `winapp/` are not part of the committed release.
- Windows users can use `run.bat` to install dependencies and build the React frontend from a source ZIP or fresh clone.
- Manual setup users should run `npm install` and `npm run build` after checkout because built frontend assets are generated locally.
- `v2.6.0` is intended as the stable rollback point before larger code optimization/refactor work.

## v2.5.0 - June 2026

Cinema Paradiso v2.5 is the major release that moves the app from the old file-organizer interface into a React/Vite movie archive console.

### Added

- React/Vite frontend served by the existing Flask backend.
- Cinema Paradiso black/gold UI system with styleguide assets and updated screenshots.
- Home command center with library health, archive-aware discovery, selected movie details, and release watchlist.
- Persistent release watchlist stored in user data, with Prowlarr checks for WEB/Blu-ray availability and CAM/TS/HDCAM filtering.
- Library Movie View for watching decisions and File View for file management.
- Library pagination with 40 items per page.
- Local library search ranking that prioritizes title matches over plot-only matches.
- Simplified resolution buckets: 4K, 1080p, 720p, and Below 720p.
- User lists and edited TMDB collection overrides stored separately from disposable metadata cache.
- Settings workspace for library paths, app data, Plex, Prowlarr, TMDB, and Ollama.
- Cleanup workspace for duplicates, smart clean, low quality, and unmatched Plex workflows.
- Discover workspace for Explore Movies, Browse Indexers, and Pick My Movie.
- Expanded movie cards with director, cast, collection/list context, trailers, and source actions.

### Changed

- App branding changed from My Library Organizer / 10k Movie Library Organizer to Cinema Paradiso.
- Release watchlist now opens a full list view and supports unfollow/delete actions.
- Discover and Library cards now expose Play, Stream, Find Sources, and Find Upgrade based on local ownership and quality.
- Library default sort is newly added instead of title.
- Video stream resolution probing is used to avoid mislabeling cropped 1080p files as 720p.

### Notes

- `config.json`, `data/`, `cache/`, and `res_cache.json` are local runtime/user files and are not committed.
- The Windows app experiment under `winapp/` remains out of scope for this release.
