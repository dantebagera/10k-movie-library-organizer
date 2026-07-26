from pathlib import Path
import re
import unittest
from tests.frontend_source import read_frontend_source


APP_JSX = Path(__file__).resolve().parents[1] / "src" / "App.jsx"
APP_PY = Path(__file__).resolve().parents[1] / "app.py"
LIBRARY_UTILS = Path(__file__).resolve().parents[1] / "src" / "utils" / "libraryUtils.js"
CLEANUP_UTILS = Path(__file__).resolve().parents[1] / "src" / "utils" / "cleanupUtils.js"
CLEANUP_WORKSPACE = Path(__file__).resolve().parents[1] / "src" / "features" / "cleanup" / "CleanupWorkspace.jsx"
CLIENT_API = Path(__file__).resolve().parents[1] / "src" / "api" / "client.js"
CURATION_API = Path(__file__).resolve().parents[1] / "src" / "api" / "curation.js"
SHARED_CARDS = Path(__file__).resolve().parents[1] / "src" / "components" / "SharedMovieCards.jsx"
MOVIE_LISTS = Path(__file__).resolve().parents[1] / "src" / "features" / "movie-lists" / "MovieListsWorkspace.jsx"
DISCOVER = Path(__file__).resolve().parents[1] / "src" / "features" / "discover" / "DiscoverWorkspace.jsx"
AI_CONTROL = Path(__file__).resolve().parents[1] / "src" / "features" / "ai-control" / "AIControlWorkspace.jsx"
LIST_EDITOR = Path(__file__).resolve().parents[1] / "src" / "components" / "ListEditorModal.jsx"
EXPORT_DIALOG = Path(__file__).resolve().parents[1] / "src" / "components" / "ExportCopyDialog.jsx"
METADATA_CORRECTION = Path(__file__).resolve().parents[1] / "src" / "components" / "MetadataCorrectionModal.jsx"
SOURCE_REVIEW_API = Path(__file__).resolve().parents[1] / "src" / "api" / "sourceReview.js"
SOURCE_REVIEW_DIALOG = Path(__file__).resolve().parents[1] / "src" / "components" / "SourceReviewDialog.jsx"
STYLES = Path(__file__).resolve().parents[1] / "src" / "styles.css"


class LibraryActionUxTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = read_frontend_source()
        cls.library_utils_source = LIBRARY_UTILS.read_text(encoding="utf-8")
        cls.cleanup_utils_source = CLEANUP_UTILS.read_text(encoding="utf-8")
        cls.cleanup_workspace_source = CLEANUP_WORKSPACE.read_text(encoding="utf-8")
        cls.client_api_source = CLIENT_API.read_text(encoding="utf-8")
        cls.curation_api_source = CURATION_API.read_text(encoding="utf-8")
        cls.shared_cards_source = SHARED_CARDS.read_text(encoding="utf-8")
        cls.movie_lists_source = MOVIE_LISTS.read_text(encoding="utf-8")
        cls.movie_lists_workspace_source = cls.movie_lists_source[
            cls.movie_lists_source.index("function MovieListsWorkspace"):
            cls.movie_lists_source.index("function TmdbListAddDialog")
        ]
        cls.discover_source = DISCOVER.read_text(encoding="utf-8")
        cls.list_editor_source = LIST_EDITOR.read_text(encoding="utf-8")
        cls.export_dialog_source = EXPORT_DIALOG.read_text(encoding="utf-8")
        cls.metadata_correction_source = METADATA_CORRECTION.read_text(encoding="utf-8")
        cls.source_review_api_source = SOURCE_REVIEW_API.read_text(encoding="utf-8")
        cls.source_review_dialog_source = SOURCE_REVIEW_DIALOG.read_text(encoding="utf-8")

    def test_library_daily_actions_are_file_scan_and_unmatched_review(self):
        self.assertIn("Rescan Files", self.source)
        self.assertIn("Review Unmatched", self.source)
        self.assertIn("params.set('force_scan', '1')", self.source)
        self.assertIn("/api/library/reconcile", self.source)
        self.assertIn("cp-library-reconciled", self.source)
        self.assertNotIn("Fetch Metadata", self.source)
        self.assertNotIn("need metadata", self.source)

    def test_library_action_row_does_not_expose_plex_sync(self):
        match = re.search(
            r'<div className="library-action-row">(.*?)<button type="button" className="btn btn-secondary" onClick=\{\(\) => setListEditor',
            self.source,
            flags=re.S,
        )
        self.assertIsNotNone(match, "Library action row should be present")
        self.assertNotIn("Sync Plex", match.group(1))
        self.assertNotIn("force_plex", match.group(1))
        self.assertNotIn("Fetch Metadata", match.group(1))

    def test_unmatched_shortcut_targets_maintenance_identity_tab(self):
        self.assertIn("reviewUnmatchedMetadata", self.source)
        self.assertIn("setCleanupInitialTab('identity')", self.source)
        self.assertIn("initialTab = 'storage'", self.source)

    def test_settings_uses_clear_plex_cache_language(self):
        self.assertIn('label="Refresh Plex Cache"', self.source)
        self.assertIn('label="Force Plex Scan"', self.source)
        self.assertIn("Plex cache refreshed.", self.source)

    def test_match_modal_submit_buttons_have_aligned_action_class(self):
        styles = (APP_JSX.parents[0] / "styles.css").read_text(encoding="utf-8")

        self.assertIn("cleanup-match-submit", self.source)
        self.assertIn(".cleanup-match-submit", styles)
        self.assertIn("grid-column: 1 / -1", styles)
        self.assertIn(".cleanup-match-form .dialog-field", styles)
        self.assertIn("min-width: 0", styles)

    def test_settings_exposes_separate_adult_metadata_and_library_controls(self):
        self.assertIn("showAdultMovies: true", self.source)
        self.assertIn("includeAdult: false", self.source)
        self.assertIn("Show adult movies in Movie View", self.source)
        self.assertIn("Include adult titles in metadata search", self.source)
        self.assertIn("show_adult_movies", self.source)
        self.assertIn("include_adult", self.source)

    def test_movie_view_hides_adult_titles_without_affecting_file_view(self):
        self.assertIn("showAdultMovies", self.source)
        self.assertIn("mode === 'movie' && !showAdultMovies && canonical.adult", self.library_utils_source)
        self.assertNotIn("mode === 'file' && !showAdultMovies && canonical.adult", self.library_utils_source)

    def test_library_people_search_uses_only_owned_stored_people_data(self):
        self.assertIn("const [librarySearchKind, setLibrarySearchKind] = useState('movies')", self.source)
        self.assertIn("<option value=\"people\">People</option>", self.source)
        self.assertIn("buildLibraryPeopleIndex(peopleItems, query)", self.source)
        self.assertIn("applyRoleFilter(role, person, { localOnly: true })", self.source)
        self.assertIn("function buildLibraryPeopleIndex", self.library_utils_source)
        self.assertIn("if (!item?.canonical_metadata?.accepted) continue;", self.library_utils_source)
        self.assertIn("filter.localOnly ? getStoredRolePeople", self.library_utils_source)

    def test_library_view_model_safe_page_is_bound_for_pagination(self):
        self.assertIn("totalPages: libraryResult.total_pages", self.source)
        self.assertIn("visibleItems: items", self.source)
        self.assertIn("return buildLibraryViewModel({", self.source)
        self.assertIn("page={safePage}", self.source)
        self.assertIn("total={mode === 'movie' ? libraryResult.total : filteredItems.length}", self.source)

    def test_shared_pagination_keeps_library_default_and_accepts_discover_labels(self):
        pagination_source = (APP_JSX.parent / "components" / "Pagination.jsx").read_text(encoding="utf-8")

        self.assertIn("ariaLabel = 'Library pagination'", pagination_source)
        self.assertIn('aria-label={ariaLabel}', pagination_source)
        self.assertIn('ariaLabel="TMDB movie pagination"', self.discover_source)
        self.assertEqual(self.discover_source.count("import Pagination from '../../components/Pagination.jsx';"), 1)

    def test_library_keyword_search_uses_the_authoritative_page_contract(self):
        self.assertIn("const LIBRARY_KEYWORD_PAGE_SIZE = 50;", self.source)
        self.assertIn("const [libraryKeywordResult, setLibraryKeywordResult] = useState({", self.source)
        self.assertIn("page_size: LIBRARY_KEYWORD_PAGE_SIZE", self.source)
        self.assertIn("total_pages: 1", self.source)
        self.assertIn("total_results: 0", self.source)
        self.assertIn("&page=${nextPage}&page_size=${LIBRARY_KEYWORD_PAGE_SIZE}", self.source)
        self.assertNotIn("&limit=50", self.source)
        self.assertIn("result={libraryKeywordResult}", self.source)
        self.assertIn("onPageChange={(nextPage) => loadKeywordProjection(query, nextPage)}", self.source)

    def test_discover_search_forces_adult_titles_off(self):
        self.assertIn("include_adult=false", self.source)
        self.assertIn("metadata_context: 'unmatched'", self.source)

    def test_unmatched_tmdb_search_sends_title_and_year_separately(self):
        self.assertIn("tmdbParams.set('q', query || matchModal.item.filename)", self.source)
        self.assertIn("tmdbParams.set('year', matchModal.year.trim())", self.source)
        self.assertNotIn("`${matchModal.title || ''} ${matchModal.year || ''}`", self.source)

    def test_plex_search_resolves_missing_keys_and_offers_scan_retry(self):
        self.assertIn("path: matchModal.item.path", self.source)
        self.assertIn("plex_item_not_indexed", self.source)
        self.assertIn("Request Plex scan", self.source)
        self.assertIn("Retry Plex lookup", self.source)
        self.assertNotIn("No Plex rating key for this file", self.source)

    def test_pending_metadata_is_separate_from_unmatched_count(self):
        self.assertIn("label=\"Metadata pending\"", self.source)
        self.assertIn("summary.metadata_pending", self.source)
        self.assertIn('item["metadata_status"] != "pending"', (Path(__file__).resolve().parents[1] / "services" / "maintenance_audit.py").read_text(encoding="utf-8"))
        self.assertNotIn('<option value="pending">Pending metadata</option>', self.source)
        self.assertIn("if (item.metadata_status === 'pending') return 'Pending metadata';", self.cleanup_utils_source)

    def test_home_health_uses_backend_cleanup_counts(self):
        self.assertIn("value: stats?.duplicate_groups", self.source)
        self.assertIn("value: stats?.unmatched_count", self.source)
        self.assertIn("value: stats?.identity_review_count", self.source)
        self.assertNotIn("label: 'Plex matched'", self.source)
        self.assertNotIn("value: stats?.dup_groups", self.source)

    def test_home_health_refreshes_when_library_changes(self):
        self.assertIn("function announceLibraryChanged", self.source)
        self.assertIn("window.addEventListener('cp-library-changed', refreshHealthStats)", self.source)
        self.assertIn("window.removeEventListener('cp-library-changed', refreshHealthStats)", self.source)
        self.assertIn("announceLibraryChanged({ source: 'manual-rescan'", self.source)

    def test_maintenance_delete_refreshes_maintenance_and_home_counts(self):
        self.assertIn(
            "announceLibraryChanged({ source: 'maintenance-delete', deleted_paths: deletedPaths })",
            self.cleanup_workspace_source,
        )
        self.assertIn(
            "window.addEventListener('cp-library-changed', refreshForLibraryChange)",
            self.cleanup_workspace_source,
        )
        self.assertIn(
            "window.addEventListener('cp-library-changed', refreshHealthStats)",
            self.source,
        )

    def test_reconcile_poll_announces_backend_download_imports(self):
        self.assertIn("function reconcileSignature(state)", self.source)
        self.assertIn("fetchJson('/api/library/reconcile')", self.source)
        self.assertIn("announceLibraryReconciled(state)", self.source)
        self.assertIn("if (status === 'running')", self.source)
        self.assertNotIn("fetchJson('/api/library/reconcile', { method: 'POST' })", self.source)

    def test_visited_workspaces_remain_mounted_and_preserve_page_state(self):
        self.assertIn("const [mountedSections, setMountedSections]", self.source)
        self.assertIn("setMountedSections((sections)", self.source)
        self.assertIn("sectionScrollPositionsRef", self.source)
        self.assertIn("workspace.scrollTop = sectionScrollPositionsRef.current[activeSection] || 0", self.source)
        for section in ('home', 'library', 'movie-lists', 'discover', 'downloads', 'ai-control', 'iptv', 'help', 'cleanup', 'settings'):
            self.assertIn(f"mountedSections.has('{section}')", self.source)
            self.assertIn(f"hidden={{activeSection !== '{section}'}}", self.source)

    def test_settings_hydration_preserves_fields_edited_while_requests_are_in_flight(self):
        self.assertIn("const editedFieldsRef = useRef(new Set())", self.source)
        self.assertIn("editedFieldsRef.current.add(`${section}.${field}`)", self.source)
        self.assertIn("merged[section] = { ...merged[section], [field]: current[section][field] }", self.source)

    def test_library_refreshes_quietly_for_background_changes(self):
        self.assertIn("function LibraryWorkspace({", self.source)
        self.assertIn("window.addEventListener('cp-library-changed', handleLibraryChanged)", self.source)
        self.assertIn("loadLibrary(false, { quiet: true })", self.source)
        self.assertIn("const requestedPage = forceScan ? 1 : currentPage", self.source)
        self.assertNotIn("if (!quiet) setCurrentPage(1)", self.source)
        self.assertNotIn("Library changed. Refresh view", self.source)

    def test_movie_view_exposes_local_metadata_correction(self):
        self.assertIn("Correct metadata", self.shared_cards_source)
        self.assertIn("MetadataCorrectionModal", self.source)
        self.assertIn("Reset to provider metadata", self.metadata_correction_source)

    def test_library_and_discover_expose_bulk_add_to_list_selection(self):
        self.assertIn("library-selection-checkbox", self.shared_cards_source)
        self.assertIn("Select all filtered", self.source)
        self.assertIn("discover-selection-checkbox", self.shared_cards_source)
        self.assertIn("addMoviesToList", self.source)
        self.assertIn("/movies/bulk", self.curation_api_source)

    def test_discover_bulk_add_to_list_uses_discover_scoped_handler(self):
        discover_source = self.source[
            self.source.index("function DiscoverWorkspace"):
            self.source.index("function PeopleSearchResults")
        ]
        self.assertIn("async function addDiscoverMoviesToList", discover_source)
        self.assertIn("onAddBulk={addDiscoverMoviesToList}", discover_source)

    def test_browse_indexers_expose_selection_and_bulk_add_to_list(self):
        discover_source = self.source[
            self.source.index("function DiscoverWorkspace"):
            self.source.index("function PeopleSearchResults")
        ]
        browse_source = self.source[
            self.source.index("{activeTab === 'browse'"):
            self.source.index("{activeTab === 'pick'")
        ]
        indexer_card_source = self.source[
            self.source.index("function IndexerMovieCard"):
            self.source.index("function Rating")
        ]

        self.assertIn("activeTab === 'browse' ? filteredBrowseRows", discover_source)
        self.assertIn("Select all browse indexer results", browse_source)
        self.assertIn("setListEditorTarget({ bulkItems: selectedDiscoverMovies })", browse_source)
        self.assertIn("selected={selectedDiscoverKeys.has(movieIdentityKey(discoverMoviePayload(movie, owned)))}", browse_source)
        self.assertIn("onSelect={(checked) => toggleDiscoverSelection(movie, owned, checked)}", browse_source)
        self.assertIn("selected,", indexer_card_source)
        self.assertIn("onSelect", indexer_card_source)
        self.assertIn('className="discover-selection-checkbox"', indexer_card_source)

    def test_library_list_filter_warns_when_list_movies_are_missing(self):
        self.assertIn("listLibraryCoverage", self.source)
        self.assertIn("listMissingCoverage", self.source)
        self.assertIn("list-missing-warning", self.source)
        self.assertIn("list movies found in Library", self.source)
        self.assertIn("Missing:", self.source)

    def test_lists_popup_exposes_select_all_and_copy_export(self):
        self.assertIn("list-select-all", self.source)
        self.assertIn("Copy selected to", self.source)
        self.assertIn("/api/library/export-jobs", self.export_dialog_source)
        self.assertIn("ExportCopyDialog", self.source)

    def test_bulk_add_to_list_falls_back_when_backend_route_is_missing(self):
        self.assertIn("bulkError.status !== 404", self.curation_api_source)
        self.assertIn("addMoviePayloadsIndividually", self.curation_api_source)
        self.assertIn("selectedPayloads.length", self.list_editor_source)
        self.assertIn("list-editor-error", self.list_editor_source)

    def test_fetch_json_preserves_status_for_non_json_errors(self):
        self.assertIn("response.text()", self.client_api_source)
        self.assertIn("Request failed: ${response.status}", self.client_api_source)
        self.assertIn("Failed to parse response JSON", self.client_api_source)

    def test_user_lists_loads_are_cached_without_stale_mutation_reads(self):
        self.assertIn("const USER_LISTS_CACHE_TTL = 1000", self.curation_api_source)
        self.assertIn("let userListsCache = { data: null, time: 0, promise: null }", self.curation_api_source)
        self.assertIn("let userListsCacheVersion = 0", self.curation_api_source)
        self.assertIn("async function fetchUserListsCached", self.curation_api_source)
        self.assertEqual(self.curation_api_source.count("fetchCurationJson('/api/user/lists')"), 1)
        self.assertIn("fetchUserListsCached({ force: Boolean(options?.force) })", self.source)
        self.assertIn("fetchUserListsCached({ force: forceLists })", self.movie_lists_source)
        self.assertIn("await loadUserLists({ force: true })", self.source)
        self.assertIn("await loadMovieLists({ forceLists: true })", self.movie_lists_source)

    def test_ownership_checks_are_cached_and_cleared_on_library_changes(self):
        self.assertIn("import { ownershipKeys }", self.source)
        self.assertIn("const OWNERSHIP_CHECK_CACHE_TTL = 30000", self.source)
        self.assertIn("let ownershipCheckCache = new Map()", self.source)
        self.assertIn("async function fetchOwnershipChecks", self.source)
        self.assertEqual(self.source.count("fetchJson('/api/library/check'"), 2)
        self.assertIn("clearOwnershipCheckCache();", self.source)
        self.assertIn("const ownershipResults = await fetchOwnershipChecks", self.source)
        self.assertIn("setOwnership((state) => ({ ...state, ...buildOwnershipMap(ownershipResults) }))", self.source)

    def test_copy_dialog_has_folder_browser_and_library_has_reset_filters(self):
        self.assertIn("FolderBrowserDialog", self.export_dialog_source)
        self.assertIn("/api/system/folders", self.export_dialog_source)
        self.assertIn("Browse...", self.export_dialog_source)
        self.assertIn("Reset filters", self.source)
        self.assertIn("resetAllLibraryFilters", self.source)

    def test_library_chrome_is_condensed_without_removing_second_header(self):
        library_source = self.source[
            self.source.index("function LibraryWorkspace"):
            self.source.index("function Pagination")
        ]
        self.assertIn("activeSection !== 'home' && activeSection !== 'library'", self.source)
        self.assertIn('className="library-header"', library_source)
        self.assertNotIn('className="library-stat-strip"', library_source)
        self.assertIn('className="library-search-panel"', library_source)
        self.assertIn("filtersOpen", library_source)
        self.assertIn("Open Filters", library_source)
        self.assertNotIn('className="library-results-meta"', library_source)

    def test_cleanup_help_and_settings_do_not_render_shared_topbar(self):
        topbar_condition = self.source[:self.source.index("function TopBar")]
        self.assertIn("activeSection !== 'cleanup'", topbar_condition)
        self.assertIn("activeSection !== 'help'", topbar_condition)
        self.assertIn("activeSection !== 'settings'", topbar_condition)

    def test_maintenance_uses_paginated_catalog_sections_instead_of_per_tab_scans(self):
        cleanup_source = self.source[
            self.source.index("function CleanupWorkspace"):
            self.source.index("function DuplicatesCleanupTab")
        ]
        self.assertIn("fetchJson(`/api/maintenance/audit?${params.toString()}`)", cleanup_source)
        self.assertIn("section,", cleanup_source)
        self.assertIn("page_size: String(MAINTENANCE_PAGE_SIZE)", cleanup_source)
        self.assertIn("Catalog-backed maintenance", cleanup_source)
        self.assertIn("const maintenanceTabs", self.source)
        self.assertIn("Select recommended", self.source)
        self.assertIn("MAINTENANCE_PAGE_SIZE = 50", self.source)
        self.assertIn("items={visibleUnmatched}", cleanup_source)
        self.assertIn("if (state.identity_review) setIdentityAudit(state.identity_review)", cleanup_source)
        self.assertIn("items={identityAudit?.proposals || []}", cleanup_source)
        self.assertNotIn("LowQualityCleanupTab", self.source)
        self.assertNotIn("id: 'upgrades'", self.source)
        self.assertIn("onOpenLibraryUpgrades", cleanup_source)
        self.assertNotIn("visibleVerification", cleanup_source)
        self.assertNotIn("IdentityVerificationList", cleanup_source)
        self.assertNotIn("/api/metadata/identity-verification/enrich", cleanup_source)
        self.assertNotIn("identity.verification", cleanup_source)
        self.assertIn("cp-library-changed", cleanup_source)
        self.assertNotIn("/api/duplicates", cleanup_source)
        self.assertNotIn("/api/smart-scan", cleanup_source)
        self.assertNotIn("/api/low-quality", cleanup_source)
        self.assertNotIn("/api/fix-unmatched", cleanup_source)

    def test_maintenance_tabs_fill_the_desktop_bar_for_the_current_tab_count(self):
        styles = STYLES.read_text(encoding="utf-8")
        cleanup_tabs = re.search(r"\.cleanup-tabs \{(?P<body>.*?)\n\}", styles, re.DOTALL)
        cleanup_buttons = re.search(r"\.cleanup-tabs button \{(?P<body>.*?)\n\}", styles, re.DOTALL)

        self.assertIsNotNone(cleanup_tabs)
        self.assertIsNotNone(cleanup_buttons)
        self.assertIn("display: flex;", cleanup_tabs.group("body"))
        self.assertIn("flex: 1 1 0;", cleanup_buttons.group("body"))

    def test_maintenance_route_replaces_legacy_cleanup_routes(self):
        app_source = APP_PY.read_text(encoding="utf-8")
        self.assertIn("@app.route('/api/maintenance/audit')", app_source)
        self.assertIn("@app.route('/api/metadata/identity-verification')", app_source)
        self.assertIn("@app.route('/api/metadata/identity-verification/enrich', methods=['POST'])", app_source)
        self.assertNotIn("@app.route('/api/duplicates')", app_source)
        self.assertNotIn("@app.route('/api/smart-scan')", app_source)
        self.assertNotIn("@app.route('/api/low-quality')", app_source)
        self.assertNotIn("@app.route('/api/fix-unmatched')", app_source)

    def test_catalog_verification_diagnostics_do_not_create_a_second_review_queue(self):
        cleanup_source = self.source[
            self.source.index("function CleanupWorkspace"):
            self.source.index("function DuplicatesCleanupTab")
        ]
        self.assertIn('label="Actionable identities"', cleanup_source)
        self.assertNotIn('label="Verification gaps"', cleanup_source)
        self.assertNotIn("accepted identities need verification", self.source)

    def test_downloads_keeps_topbar_without_search_or_file_badge(self):
        topbar_source = self.source[
            self.source.index("function TopBar"):
            self.source.index("function DownloadsWorkspace")
        ]
        self.assertIn("const isDownloads = activeSection === 'downloads';", topbar_source)
        self.assertIn("!isDownloads && (", topbar_source)
        self.assertIn("downloads-title-credit", topbar_source)
        self.assertIn("hidden={activeSection !== 'downloads'}", self.source[:self.source.index("function TopBar")])

    def test_discover_moves_search_below_tabs_without_shared_topbar(self):
        discover_source = self.source[
            self.source.index("function DiscoverWorkspace"):
            self.source.index("function DiscoverResultGrid")
        ]
        self.assertIn("activeSection !== 'discover'", self.source[:self.source.index("function TopBar")])
        self.assertIn('className="discover-search-panel"', discover_source)
        self.assertIn("activeTab !== 'pick'", discover_source)
        self.assertIn("activeTab === 'browse' ? browseQuery : tmdbQuery", discover_source)
        self.assertIn("activeTab === 'browse' ? setBrowseQuery", discover_source)
        self.assertIn("loadBrowse({ query: browseQuery })", discover_source)
        self.assertIn("loadDiscover({ append: false, search: tmdbQuery, page: 1 })", discover_source)
        self.assertIn("Search", discover_source)

    def test_discover_uses_one_criteria_builder_for_search_and_catalog_results(self):
        discover_source = self.source[
            self.source.index("function DiscoverWorkspace"):
            self.source.index("function DiscoverResultGrid")
        ]
        self.assertIn("function buildDiscoverUrl(query, page)", discover_source)
        self.assertIn("params.set('genre', discoverGenre)", discover_source)
        self.assertIn("params.set('year_from', discoverYearFrom.trim())", discover_source)
        self.assertIn("params.set('min_rating', discoverMinRating)", discover_source)
        self.assertIn("return `/api/tmdb/${query ? 'search' : 'discover'}?${params.toString()}`", discover_source)
        self.assertIn("fetchJson(buildDiscoverUrl(query, nextPage), { signal: controller.signal })", discover_source)
        self.assertIn("{ value: 'catalog', label: 'TMDB Catalog' }", self.source)
        self.assertIn("Search: ${tmdbQuery.trim()}${hasAdvancedDiscoverCriteria() ? ' / refined' : ''}", discover_source)

    def test_settings_prowlarr_exposes_trusted_release_indexers(self):
        self.assertIn("trusted_release_indexers", self.source)
        self.assertIn("TrustedIndexerDialog", self.source)
        self.assertIn("trusted-indexer-summary", self.source)
        self.assertIn('label="Trusted indexers"', self.source)
        self.assertIn("const saved = await onSave();", self.source)
        self.assertIn("if (saved) onClose();", self.source)
        self.assertIn("Trusted release watchlist indexers", self.source)
        self.assertIn("No trusted indexers selected", self.source)

    def test_movie_lists_are_a_top_level_mixed_owned_missing_workspace(self):
        self.assertIn("id: 'movie-lists'", self.source)
        self.assertIn("label: 'Movie Lists'", self.source)
        self.assertIn("MovieListsWorkspace", self.source)
        movie_lists_source = self.movie_lists_workspace_source
        self.assertNotIn("fetchJson('/api/library?view=movie-list')", movie_lists_source)
        self.assertIn("body: JSON.stringify({ movies, include_items: true })", movie_lists_source)
        self.assertIn("window.addEventListener('cp-library-changed', refreshOwnership)", movie_lists_source)
        self.assertIn("buildMovieListViewModel", self.library_utils_source)
        self.assertIn("Find sources", movie_lists_source)
        self.assertNotIn("Find missing", movie_lists_source)
        self.assertNotIn("Find upgrades", movie_lists_source)
        self.assertIn("openSelectedSourceReview", movie_lists_source)
        self.assertIn("SourceReviewDialog", movie_lists_source)
        self.assertIn("/api/sources/review/preview", self.source_review_api_source)
        self.assertIn("/api/sources/review/submit", self.source_review_api_source)
        self.assertIn("source-review-dialog", self.source_review_dialog_source)

    def test_movie_lists_reuses_global_movie_cards_and_normal_per_card_source_search(self):
        movie_lists_source = self.movie_lists_workspace_source
        self.assertIn("<LibraryMovieCard", movie_lists_source)
        self.assertIn("<DiscoverMovieCard", movie_lists_source)
        self.assertNotIn("function MovieListCard", self.source)
        self.assertNotIn("movie-list-card", movie_lists_source)
        self.assertIn("onFindTorrent={onFindTorrent}", movie_lists_source)
        self.assertNotIn("onFindSources", movie_lists_source)
        self.assertIn("openSelectedSourceReview", movie_lists_source)

    def test_missing_movie_list_cards_use_the_shared_tmdb_card_projection(self):
        movie_lists_source = self.movie_lists_workspace_source
        self.assertIn("/api/tmdb/card-projections", movie_lists_source)
        self.assertIn("body: JSON.stringify({ movies })", movie_lists_source)
        self.assertIn("movieIdentityKey(movie)", movie_lists_source)
        self.assertIn("const cardMovie = projection", movie_lists_source)
        self.assertIn("const cardDetails = projection", movie_lists_source)
        self.assertIn("movie={cardMovie}", movie_lists_source)

    def test_movie_list_card_projection_requests_survive_ownership_rerenders(self):
        movie_lists_source = self.movie_lists_workspace_source
        self.assertIn("cardProjectionInFlightKeys", movie_lists_source)
        self.assertIn("cardProjectionMounted", movie_lists_source)
        self.assertNotIn("let cancelled = false;\n    fetchJson('/api/tmdb/card-projections'", movie_lists_source)
        self.assertIn(".finally(() => {", movie_lists_source)

    def test_library_loads_ignore_older_responses(self):
        library_workspace = (Path(__file__).resolve().parents[1] / "src" / "features" / "library" / "LibraryWorkspace.jsx").read_text(encoding="utf-8")
        self.assertRegex(
            library_workspace,
            re.compile(
                r"const requestSeq = libraryRequestSeq\.current \+ 1;.*"
                r"libraryRequestSeq\.current = requestSeq;.*"
                r"if \(requestSeq !== libraryRequestSeq\.current\) return;",
                re.S,
            ),
        )

    def test_ai_control_ownership_checks_ignore_a_previous_page_or_plan(self):
        ai_control = AI_CONTROL.read_text(encoding="utf-8")
        self.assertIn("ownershipScopeKey", ai_control)
        self.assertRegex(
            ai_control,
            re.compile(
                r"const requestSeq = ownershipRequestSeq\.current \+ 1;.*"
                r"ownershipRequestSeq\.current = requestSeq;.*"
                r"if \(requestSeq !== ownershipRequestSeq\.current\) return;",
                re.S,
            ),
        )

    def test_movie_lists_has_full_list_management_without_duplicate_select_all_button(self):
        movie_lists_source = self.movie_lists_workspace_source
        self.assertIn("New list", movie_lists_source)
        self.assertIn("Rename list", movie_lists_source)
        self.assertIn("Delete list", movie_lists_source)
        self.assertIn("Copy selected to", movie_lists_source)
        self.assertIn("Remove selected", movie_lists_source)
        self.assertIn("Add movie", movie_lists_source)
        self.assertIn("TmdbListAddDialog", self.movie_lists_source)
        self.assertIn("/api/tmdb/search", self.movie_lists_source)
        self.assertIn("ExportCopyDialog", movie_lists_source)
        self.assertNotIn(">Select all</button>", movie_lists_source)

    def test_discover_uses_the_shared_selected_source_review_in_every_movie_tab(self):
        self.assertIn("async function openSelectedSourceReview", self.discover_source)
        self.assertIn("previewSourceReview(selectedDiscoverMovies.map", self.discover_source)
        self.assertEqual(self.discover_source.count("onClick={openSelectedSourceReview}"), 3)
        self.assertEqual(self.discover_source.count("<SourceReviewDialog"), 1)

    def test_discover_explore_ownership_filter_uses_the_existing_ownership_map(self):
        styles = (APP_JSX.parents[0] / "styles.css").read_text(encoding="utf-8")
        self.assertIn("const [discoverOwnershipFilter, setDiscoverOwnershipFilter] = useState('all')", self.discover_source)
        self.assertIn("const filteredDiscoverResults = useMemo", self.discover_source)
        self.assertIn("ownedMovieFor(movie, ownership)", self.discover_source)
        self.assertIn("? filteredDiscoverResults", self.discover_source)
        self.assertIn('aria-label="Library ownership"', self.discover_source)
        self.assertIn('<option value="all">All movies</option>', self.discover_source)
        self.assertIn('<option value="owned">Owned</option>', self.discover_source)
        self.assertIn('<option value="unowned">Not owned</option>', self.discover_source)
        self.assertEqual(self.discover_source.count("mini-action mini-action-source"), 3)
        self.assertIn("mini-action mini-action-source", self.movie_lists_source)
        self.assertIn(".mini-action-source", styles)

    def test_library_global_card_keeps_owned_badge(self):
        library_card_source = self.shared_cards_source[
            self.shared_cards_source.index("function LibraryMovieCard"):
        ]
        self.assertIn("ownedBadge", library_card_source)

    def test_settings_prowlarr_exposes_movie_list_download_defaults(self):
        self.assertIn("download_default_quality", self.source)
        self.assertIn("download_indexer_mode", self.source)
        self.assertIn("Automation defaults", self.source)
        self.assertIn("Default download quality", self.source)
        self.assertIn("Use release trusted indexers", self.source)

    def test_source_search_loading_warns_that_prowlarr_indexers_can_take_time(self):
        self.assertIn("Connecting to Prowlarr indexers", self.source)
        self.assertIn("This may take some time", self.source)
        self.assertIn("/api/explore/search/jobs", self.source)
        self.assertIn("Still searching", self.source)


if __name__ == "__main__":
    unittest.main()
