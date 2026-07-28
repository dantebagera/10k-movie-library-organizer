from pathlib import Path
import unittest
from tests.frontend_source import read_frontend_source


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = read_frontend_source()
SHARED_CARDS_SOURCE = (ROOT / "src" / "components" / "SharedMovieCards.jsx").read_text(encoding="utf-8")
PRESENTATION_SOURCE = (ROOT / "src" / "utils" / "moviePresentation.js").read_text(encoding="utf-8")
MOVIE_LISTS_SOURCE = (ROOT / "src" / "features" / "movie-lists" / "MovieListsWorkspace.jsx").read_text(encoding="utf-8")
AI_CONTROL_SOURCE = (ROOT / "src" / "features" / "ai-control" / "AIControlWorkspace.jsx").read_text(encoding="utf-8")
DISCOVER_SOURCE = (ROOT / "src" / "features" / "discover" / "DiscoverWorkspace.jsx").read_text(encoding="utf-8")
COLLECTION_CACHE_SOURCE = (ROOT / "src" / "hooks" / "useMovieCollectionCache.js").read_text(encoding="utf-8")
APP = APP_SOURCE
MAIN = (ROOT / "src" / "main.jsx").read_text(encoding="utf-8")
COMPONENT = ROOT / "src" / "components" / "movie-card" / "MovieCard.jsx"
STYLES = ROOT / "src" / "components" / "movie-card" / "movieCard.css"
APP_STYLES = ROOT / "src" / "styles.css"


class UnifiedMovieCardUiTest(unittest.TestCase):
    def test_shared_movie_card_component_exists_and_is_imported(self):
        self.assertTrue(COMPONENT.exists())
        self.assertTrue(STYLES.exists())
        component_source = COMPONENT.read_text(encoding="utf-8")
        self.assertIn("export function UnifiedMovieCard", component_source)
        self.assertIn("export function UnifiedMoviePoster", component_source)
        self.assertIn("import './components/movie-card/movieCard.css';", MAIN)
        self.assertIn("UnifiedMovieCard", APP)

    def test_standard_card_contract_is_minimal_and_ownership_gated(self):
        component_source = COMPONENT.read_text(encoding="utf-8")
        self.assertIn("showPlayOverlay", component_source)
        self.assertIn("ownedBadge", component_source)
        self.assertIn("cornerControls", component_source)
        self.assertIn("movie-card-play-overlay", component_source)
        self.assertIn("unified-rating-row", component_source)
        self.assertIn("unified-title-long", component_source)
        self.assertNotIn("Find sources", component_source)
        self.assertNotIn("Correct metadata", component_source)

    def test_standard_poster_uses_uncropped_contain_framing(self):
        styles_source = STYLES.read_text(encoding="utf-8")
        self.assertIn(".unified-movie-poster img", styles_source)
        self.assertIn("object-fit: contain", styles_source)
        self.assertIn("grid-template-columns: var(--movie-card-poster-width) minmax(0, 1fr)", styles_source)
        self.assertIn("width: var(--movie-card-poster-width)", styles_source)
        self.assertIn("min-height: var(--movie-card-poster-height)", styles_source)
        self.assertIn(".movie-card-play-overlay:hover", styles_source)
        self.assertIn("var(--projector-gold)", styles_source)
        self.assertNotIn("overflow-wrap: anywhere", styles_source)

    def test_discover_unowned_cards_keep_owned_only_controls_gated(self):
        self.assertIn("showPlayOverlay={Boolean(owned)}", APP)
        self.assertIn("ownedBadge={Boolean(owned)}", APP)
        self.assertIn("onEditPoster={owned ? onEditPoster : undefined}", APP)
        self.assertIn("onToggleWatched={owned ? onToggleWatched : undefined}", APP)

    def test_unreleased_gate_applies_to_discover_and_home_but_not_indexer(self):
        self.assertIn("function isUnreleasedMovie(movie)", APP)
        self.assertIn("function formatReleaseDateLabel(value)", APP)
        self.assertIn("const unreleased = !owned && isUnreleasedMovie(displayMovie);", APP)
        self.assertIn("statusLabel={owned ? (lowQuality ? 'Upgrade candidate' : '') : (unreleased ? 'Unreleased' : (followed ? 'Following' : 'Not in library'))}", APP)
        self.assertIn("{!unreleased && streamingAvailable && (", APP)
        self.assertIn("{!unreleased && (", APP)

        discover_card = SHARED_CARDS_SOURCE[
            SHARED_CARDS_SOURCE.index("function DiscoverMovieCard({"):
            SHARED_CARDS_SOURCE.index("function MovieExpandedDetails", SHARED_CARDS_SOURCE.index("function DiscoverMovieCard({"))
        ]
        self.assertIn("const unreleased = !owned && isUnreleasedMovie(displayMovie);", discover_card)
        self.assertIn("!unreleased", discover_card)

        smart_card = APP[APP.index("function SmartMovieCard(props)"):APP.index("function MovieInspector", APP.index("function SmartMovieCard(props)"))]
        self.assertIn("const unreleased = !owned && isUnreleasedMovie(displayMovie);", smart_card)

        inspector = APP[APP.index("function MovieInspector({"):APP.index("function PosterEditButton", APP.index("function MovieInspector({"))]
        self.assertIn("const unreleased = !owned && isUnreleasedMovie(displayMovie);", inspector)
        self.assertIn("const releaseDateLabel = unreleased ? formatReleaseDateLabel(displayMovie.release_date) : '';", inspector)
        self.assertIn("{releaseDateLabel && <span>Releases {releaseDateLabel}</span>}", inspector)
        self.assertIn("{!unreleased && streamingAvailable && (", inspector)
        self.assertIn("const selectedMovieWithDetails = selectedMovie ? {", APP)
        self.assertIn("release_date: selectedMovie.release_date || selectedDetails?.release_date || ''", APP)
        self.assertIn("plot: selectedDetails?.plot || selectedDetails?.summary || selectedMovie.plot || ''", APP)
        self.assertIn("selectedMovie={selectedMovieWithDetails}", APP)

        indexer_card = APP[APP.index("function IndexerMovieCard({"):APP.index("function Rating", APP.index("function IndexerMovieCard({"))]
        self.assertNotIn("isUnreleasedMovie", indexer_card)
        self.assertIn("onFindTorrent(movie)", indexer_card)

    def test_expanded_details_show_release_date_only_for_unreleased_movies(self):
        expanded_facts = SHARED_CARDS_SOURCE[
            SHARED_CARDS_SOURCE.index("function MovieExpandedFacts({"):
            SHARED_CARDS_SOURCE.index("function MovieExpandedDetails({")
        ]
        self.assertIn("const releaseDate = movie?.release_date || details?.release_date || '';", expanded_facts)
        self.assertIn("const releaseDateLabel = isUnreleasedMovie({ release_date: releaseDate }) ? formatReleaseDateLabel(releaseDate) : '';", expanded_facts)
        self.assertIn("!details?.tagline && !details?.runtime && !releaseDateLabel", expanded_facts)
        self.assertIn("{releaseDateLabel && <div><span>Release date</span><strong>Releases {releaseDateLabel}</strong></div>}", expanded_facts)

    def test_library_cards_hide_redundant_owned_badge_without_changing_shared_badge(self):
        library_component_start = SHARED_CARDS_SOURCE.index("export function LibraryMovieCard({")
        library_component = SHARED_CARDS_SOURCE[library_component_start:]
        self.assertIn("showOwnedBadge = true", library_component)
        self.assertIn("ownedBadge={showOwnedBadge}", library_component)
        self.assertIn("showOwnedBadge={false}", APP)
        self.assertEqual(APP.count("showOwnedBadge={false}"), 1)
        self.assertNotIn("showOwnedBadge={false}", MOVIE_LISTS_SOURCE)
        self.assertNotIn("statusLabel={lowQuality ? 'Upgrade candidate' : 'Owned'}", library_component)

    def test_card_grids_keep_multiple_cards_without_too_narrow_cards(self):
        styles_source = STYLES.read_text(encoding="utf-8")
        self.assertIn("--movie-card-min-width: 460px", styles_source)
        self.assertIn("repeat(auto-fill, minmax(min(100%, var(--movie-card-min-width)), 1fr))", styles_source)

    def test_expanded_cards_move_rating_to_top_right(self):
        component_source = COMPONENT.read_text(encoding="utf-8")
        styles_source = STYLES.read_text(encoding="utf-8")
        self.assertIn("unified-expanded-rating", component_source)
        self.assertIn("{rating && expanded ? (", component_source)
        self.assertIn("{rating && !expanded ? (", component_source)
        self.assertIn(".unified-expanded-rating", styles_source)
        self.assertIn(".unified-movie-card-expanded", styles_source)
        self.assertIn("grid-column: 1 / -1", styles_source)

    def test_expanded_cards_share_tmdb_certification_writers_keywords_and_imdb_link(self):
        component_source = COMPONENT.read_text(encoding="utf-8")
        styles_source = STYLES.read_text(encoding="utf-8")

        self.assertIn("headerActions", component_source)
        self.assertIn('className="unified-header-actions" onClick={stopCardToggle}', component_source)
        self.assertIn("function MovieImdbLink", APP)
        self.assertIn("function MovieKeywordRow", APP)
        self.assertGreaterEqual(APP.count("<MovieImdbLink"), 2)
        self.assertGreaterEqual(APP.count("<MovieKeywordRow"), 2)
        self.assertIn("displayDetails?.certification || displayMovie.certification", APP)
        self.assertIn("tone: 'certification'", APP)
        self.assertIn(".unified-chip.unified-chip-certification", STYLES.read_text(encoding="utf-8"))
        self.assertIn("details?.writers || movie?.writers", APP)
        self.assertIn("https://www.imdb.com/title/", APP)
        self.assertIn(".movie-imdb-link", styles_source)
        self.assertIn(".movie-keyword-row", styles_source)
        self.assertIn(".movie-expanded-writers", styles_source)
        self.assertNotIn("movie-expanded-facts-wrap", APP)
        self.assertIn('className="movie-expanded-primary-facts"', APP)
        self.assertIn('className="movie-expanded-runtime"', APP)
        self.assertIn("grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr) minmax(90px, 0.35fr)", APP_STYLES.read_text(encoding="utf-8"))
        self.assertIn("margin-right: 14px", APP_STYLES.read_text(encoding="utf-8"))

    def test_expanded_language_toggle_uses_far_right_metadata_action_slot(self):
        component_source = COMPONENT.read_text(encoding="utf-8")
        card_styles = STYLES.read_text(encoding="utf-8")
        app_styles = APP_STYLES.read_text(encoding="utf-8")
        self.assertIn("metadataActions", component_source)
        self.assertIn("unified-chip-row-actions", component_source)
        self.assertEqual(SHARED_CARDS_SOURCE.count("metadataActions={expanded ? ("), 2)
        self.assertEqual(SHARED_CARDS_SOURCE.count("<MovieLanguageToggle {...languageView.toggleProps} />"), 2)
        self.assertIn("margin-left: auto", card_styles)
        self.assertIn("min-height: 36px", app_styles)
        self.assertIn("padding: 0 14px", app_styles)

    def test_expanded_details_are_shared_and_include_runtime(self):
        self.assertIn("function MovieExpandedDetails", APP)
        self.assertIn("function MovieExpandedFacts", APP)
        self.assertNotIn("function DiscoverExpandedDetails", APP)
        self.assertGreaterEqual(APP.count("<MovieExpandedDetails"), 3)
        self.assertGreaterEqual(APP.count("<MovieExpandedFacts"), 3)
        self.assertIn("details?.runtime", APP)
        self.assertIn("<span>Runtime</span>", APP)

    def test_expanded_card_uses_two_rows_with_approved_desktop_scale(self):
        component_source = COMPONENT.read_text(encoding="utf-8")
        card_styles = STYLES.read_text(encoding="utf-8")
        app_styles = APP_STYLES.read_text(encoding="utf-8")

        self.assertIn("expandedFooter", component_source)
        self.assertIn('className="unified-movie-expanded-row"', component_source)
        self.assertIn("--expanded-movie-card-min-height: 796px", card_styles)
        self.assertIn("--expanded-movie-card-poster-width: 309px", card_styles)
        self.assertIn("--expanded-movie-card-poster-height: 464px", card_styles)
        self.assertIn("grid-template-columns: var(--expanded-movie-card-poster-width) minmax(0, 1fr)", card_styles)
        self.assertIn(".movie-expanded-curation", app_styles)
        self.assertIn(".movie-expanded-people-grid", app_styles)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(140px, 1fr))", app_styles)
        self.assertIn('className="movie-expanded-credits-panel"', SHARED_CARDS_SOURCE)
        self.assertIn("<MovieExpandedCuration", SHARED_CARDS_SOURCE)
        self.assertIn("Director &amp; top cast", SHARED_CARDS_SOURCE)

    def test_expanded_people_cards_include_biography_popup(self):
        expanded_details = APP[APP.index("function MovieExpandedDetails({"):APP.index("function formatVoteCount", APP.index("function MovieExpandedDetails({"))]
        self.assertIn("BookOpen", APP)
        self.assertIn("import { createPortal } from 'react-dom';", APP)
        self.assertIn("function PersonCreditCard", expanded_details)
        self.assertIn("className=\"person-bio-button\"", expanded_details)
        self.assertIn("className=\"person-discover-button\"", expanded_details)
        self.assertIn("Show all movies for", expanded_details)
        self.assertIn("<Film size={14} />", expanded_details)
        self.assertIn("event.stopPropagation()", expanded_details)
        self.assertIn("fetchJson(`/api/tmdb/person?person_id=${encodeURIComponent(person.id)}`)", expanded_details)
        self.assertIn("function PersonBioModal", expanded_details)
        self.assertIn("const biography = String(data.biography || '').trim();", expanded_details)
        self.assertNotIn("personBioExcerpt(data.biography)", expanded_details)
        self.assertIn("createPortal(modal, document.body)", expanded_details)

        styles_source = APP_STYLES.read_text(encoding="utf-8")
        self.assertIn(".person-bio-button", styles_source)
        self.assertIn(".person-discover-button", styles_source)
        self.assertIn("bottom: 6px", styles_source)
        self.assertIn(".person-bio-dialog", styles_source)
        self.assertIn(".person-bio-backdrop", styles_source)

        bio_dialog_styles = styles_source[
            styles_source.index(".person-bio-dialog {"):
            styles_source.index(".person-bio-header")
        ]
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", bio_dialog_styles)
        self.assertIn("overflow: hidden", bio_dialog_styles)

        bio_copy_styles = styles_source[
            styles_source.index(".person-bio-copy {"):
            styles_source.index(".person-bio-copy p")
        ]
        self.assertIn("max-height: calc(86vh - 118px)", bio_copy_styles)
        self.assertIn("overflow: auto", bio_copy_styles)

    def test_shared_relationship_cards_can_jump_to_discover(self):
        discover_source = APP[
            APP.index("function DiscoverWorkspace({"):
            APP.index("function DiscoverMovieCard", APP.index("function DiscoverWorkspace({"))
        ]
        library_source = APP[
            APP.index("function LibraryWorkspace"):
            APP.index("function LibraryFileRow", APP.index("function LibraryWorkspace"))
        ]
        library_card_source = SHARED_CARDS_SOURCE[
            SHARED_CARDS_SOURCE.index("function LibraryMovieCard"):
        ]
        movie_lists_source = MOVIE_LISTS_SOURCE

        self.assertIn("const [discoverRelationshipRequest, setDiscoverRelationshipRequest] = useState(null);", APP)
        self.assertIn("function openPersonInDiscover(movie, role, person)", APP)
        self.assertIn("function openCollectionInDiscover(movie, collection)", APP)
        self.assertIn("onOpenDiscoverPerson={openPersonInDiscover}", APP)
        self.assertIn("onOpenDiscoverCollection={openCollectionInDiscover}", APP)
        self.assertIn("relationshipRequest={discoverRelationshipRequest}", APP)
        self.assertIn("relationshipRequest,", discover_source)
        self.assertIn("handledRelationshipRequestRef", discover_source)
        self.assertIn("function buildPersonMoviesContext(movie, role, person, labelPrefix = '')", discover_source)
        self.assertIn("setActiveTab('explore')", discover_source)
        self.assertIn("loadContextPage('explore', context, { page: 1 })", discover_source)
        self.assertIn("onPersonDiscover={onOpenDiscoverPerson}", library_source)
        self.assertIn("onPersonDiscover ? (role, person) => onPersonDiscover({ title: identity.title, year: identity.year }, role, person) : undefined", library_card_source)
        self.assertIn("onDiscover={onPersonDiscover}", APP)
        self.assertIn("onOpenDiscoverPerson", movie_lists_source)
        self.assertIn("onOpenDiscoverCollection", movie_lists_source)
        self.assertIn("onPersonBrowse={(role, person) => onOpenDiscoverPerson", movie_lists_source)
        self.assertIn("onCollectionBrowse={(collection) => onOpenDiscoverCollection", movie_lists_source)
        self.assertIn("onPersonBrowse={(role, person) => onOpenDiscoverPerson", AI_CONTROL_SOURCE)
        self.assertIn("onCollectionBrowse={(collection) => onOpenDiscoverCollection", AI_CONTROL_SOURCE)
        indexer_card_source = DISCOVER_SOURCE[DISCOVER_SOURCE.index("function IndexerMovieCard({"):]
        self.assertIn("onCollectionBrowse={onCollectionBrowse}", indexer_card_source)
        self.assertIn("onPersonBrowse={onPersonBrowse}", indexer_card_source)

    def test_collection_loading_is_source_aware_and_never_infers_false_zero(self):
        self.assertIn("movieCollectionCacheKey", COLLECTION_CACHE_SOURCE)
        self.assertIn("status: 'loading'", COLLECTION_CACHE_SOURCE)
        self.assertIn("status: 'error'", COLLECTION_CACHE_SOURCE)
        self.assertIn("options.force", COLLECTION_CACHE_SOURCE)
        self.assertIn("'Loading collection...'", SHARED_CARDS_SOURCE)
        self.assertIn("'Collection details unavailable'", SHARED_CARDS_SOURCE)
        self.assertIn("'Collection members unavailable'", SHARED_CARDS_SOURCE)
        self.assertNotIn("(activeCollection.parts || []).length", SHARED_CARDS_SOURCE)
        self.assertNotIn("discover-collection-static", SHARED_CARDS_SOURCE)

    def test_discover_relationship_contexts_preserve_filters_and_block_initial_feed_race(self):
        discover_source = APP[
            APP.index("function DiscoverWorkspace({"):
            APP.index("function DiscoverMovieCard", APP.index("function DiscoverWorkspace({"))
        ]

        self.assertIn("const [isNavigatingDiscoverContext, setIsNavigatingDiscoverContext]", discover_source)
        self.assertIn("if (isNavigatingDiscoverContext || discoverContext) return;", discover_source)
        self.assertIn("function appendDiscoverCriteria(params)", discover_source)
        self.assertIn("if (!isPick) appendDiscoverCriteria(params);", discover_source)
        self.assertIn("function filterDiscoverContextResults(results)", discover_source)
        self.assertIn("if (['person', 'keyword'].includes(discoverContext.type) && discoverContext.baseUrl)", discover_source)
        self.assertIn("loadContextPage('explore', discoverContext, { page: 1 });", discover_source)
        self.assertIn("setDiscoverContextSourceResults(results);", discover_source)

    def test_collection_browse_uses_the_tmdb_payload_and_keeps_default_criteria_non_destructive(self):
        discover_source = (ROOT / "src" / "features" / "discover" / "DiscoverWorkspace.jsx").read_text(encoding="utf-8")
        result_grid_source = (ROOT / "src" / "components" / "DiscoverResultGrid.jsx").read_text(encoding="utf-8")

        self.assertIn("if (!hasAdvancedDiscoverCriteria()) return [...(results || [])];", discover_source)
        self.assertIn("`/api/tmdb/collection?collection_id=${encodeURIComponent(collection.id)}`,", discover_source)
        self.assertIn("{ signal: controller.signal }", discover_source)
        self.assertIn("emptyHint={discoverContext?.type === 'collection'", discover_source)
        self.assertIn("emptyHint || 'Check Settings if this depends on TMDB, Prowlarr, or Ollama.'", result_grid_source)

    def test_discover_people_search_keeps_person_selection_separate_from_movie_cards(self):
        discover_source = APP[
            APP.index("function DiscoverWorkspace({"):
            APP.index("function DiscoverMovieCard", APP.index("function DiscoverWorkspace({"))
        ]

        self.assertIn("const [discoverSearchKind, setDiscoverSearchKind] = useState('movies');", discover_source)
        self.assertIn("/api/tmdb/people/search", discover_source)
        self.assertIn('aria-label="TMDB search type"', discover_source)
        self.assertIn('<option value="people">People</option>', discover_source)
        self.assertIn("function openSearchedPersonFilmography(person, role)", discover_source)
        self.assertIn("const personId = person?.id || person?.tmdb_id;", discover_source)
        self.assertIn("const selectionSnapshot = {", discover_source)
        self.assertIn("label: person.name || 'TMDB person'", discover_source)
        self.assertIn("peopleResults: discoverPeopleResults", discover_source)
        self.assertIn("setDiscoverHistory((history) => [...history, selectionSnapshot]);", discover_source)
        self.assertIn("setDiscoverSearchKind(snapshot.searchKind || 'movies');", discover_source)
        self.assertIn("setDiscoverPeopleResults(snapshot.peopleResults || []);", discover_source)
        self.assertIn("<PeopleSearchResults", discover_source)
        self.assertIn("function PeopleSearchResults", APP)
        self.assertIn("Acting credits", APP)

    def test_discover_writer_and_keyword_relationship_paths_keep_identity_and_stale_guards(self):
        discover_source = (ROOT / "src" / "features" / "discover" / "DiscoverWorkspace.jsx").read_text(encoding="utf-8")

        self.assertIn("role === 'writer' ? 'Writer'", discover_source)
        self.assertIn("role === 'writer' ? 'Written films'", discover_source)
        self.assertIn("/api/tmdb/keywords/search", discover_source)
        self.assertIn("/api/tmdb/discover?list=catalog&keyword_id=", discover_source)
        self.assertIn("function searchDiscoverKeywords({ page = 1, reset = false } = {})", discover_source)
        self.assertIn("function openSearchedKeywordMovies(keyword)", discover_source)
        self.assertIn("const requestSeq = discoverRequestSeq.current + 1;", discover_source)
        self.assertIn("if (requestSeq !== discoverRequestSeq.current) return;", discover_source)
        self.assertIn("role: ['actor', 'director', 'writer'].includes(role) ? role : 'actor'", APP)
        self.assertIn("Directed films", APP)

    def test_discover_uses_shared_replacement_pagination_for_identities_and_relationships(self):
        discover_source = (ROOT / "src" / "features" / "discover" / "DiscoverWorkspace.jsx").read_text(encoding="utf-8")
        pagination_source = (ROOT / "src" / "components" / "Pagination.jsx").read_text(encoding="utf-8")

        self.assertIn("const [discoverPeoplePage, setDiscoverPeoplePage] = useState(1);", discover_source)
        self.assertIn("const [discoverKeywordPage, setDiscoverKeywordPage] = useState(1);", discover_source)
        self.assertIn("async function loadContextPage(target, context, { page = 1 } = {})", discover_source)
        self.assertIn("setDiscoverResults(nextResults);", discover_source)
        self.assertIn("setPickResults(nextResults);", discover_source)
        context_loader = discover_source[
            discover_source.index("async function loadContextPage"):
            discover_source.index("function filterDiscoverContextResults")
        ]
        self.assertNotIn("append ? [...state, ...nextResults]", context_loader)
        self.assertNotIn("Load more", discover_source)
        self.assertIn('ariaLabel="TMDB People search pagination"', discover_source)
        self.assertIn('ariaLabel="TMDB keyword search pagination"', discover_source)
        self.assertIn('ariaLabel="TMDB relationship pagination"', discover_source)
        self.assertIn('ariaLabel="AI Pick relationship pagination"', discover_source)
        self.assertIn("ariaLabel = 'Library pagination'", pagination_source)
        self.assertIn('aria-label={ariaLabel}', pagination_source)

    def test_discover_pagination_snapshots_totals_and_aborts_stale_requests(self):
        discover_source = (ROOT / "src" / "features" / "discover" / "DiscoverWorkspace.jsx").read_text(encoding="utf-8")

        self.assertIn("peoplePage: discoverPeoplePage", discover_source)
        self.assertIn("keywordPage: discoverKeywordPage", discover_source)
        self.assertIn("ownershipFilter: discoverOwnershipFilter", discover_source)
        self.assertIn("setDiscoverPeoplePage(snapshot.peoplePage || 1);", discover_source)
        self.assertIn("setDiscoverKeywordPage(snapshot.keywordPage || 1);", discover_source)
        self.assertIn("setDiscoverOwnershipFilter(snapshot.ownershipFilter || 'all');", discover_source)
        self.assertIn("const discoverAbortRef = useRef(null);", discover_source)
        self.assertIn("const pickAbortRef = useRef(null);", discover_source)
        self.assertIn("signal: controller.signal", discover_source)
        self.assertIn("if (isAbortedRequest(error)) return;", discover_source)
        self.assertIn("requestedPage > totalPages && responsePage !== totalPages", discover_source)

    def test_shared_desktop_search_ui_exposes_writer_and_keyword_actions(self):
        library_source = (ROOT / "src" / "features" / "library" / "LibraryWorkspace.jsx").read_text(encoding="utf-8")
        discover_source = (ROOT / "src" / "features" / "discover" / "DiscoverWorkspace.jsx").read_text(encoding="utf-8")
        person_card_source = (ROOT / "src" / "components" / "PersonSearchCard.jsx").read_text(encoding="utf-8")
        keyword_card_source = (ROOT / "src" / "components" / "KeywordSearchCard.jsx").read_text(encoding="utf-8")

        self.assertIn("const canBrowseWriting = roles.includes('writer');", person_card_source)
        self.assertIn("Written films", person_card_source)
        self.assertIn('<option value="keywords">Keywords</option>', library_source)
        self.assertIn("/api/library?view=keywords", library_source)
        self.assertIn("<Pagination", library_source)
        self.assertIn("total={result.total_results}", library_source)
        self.assertIn("totalPages={result.total_pages}", library_source)
        self.assertIn("keyword_id: keywordFilter?.tmdb_id || ''", library_source)
        self.assertIn("<KeywordSearchCard", library_source)
        self.assertIn('<option value="keywords">Keywords</option>', discover_source)
        self.assertIn("Search TMDB keywords...", discover_source)
        self.assertIn("<KeywordSearchResults", discover_source)
        self.assertIn("onOpenKeyword={openSearchedKeywordMovies}", discover_source)
        self.assertIn("View owned movies", keyword_card_source)
        self.assertIn("Discover movies", keyword_card_source)

    def test_library_expanded_card_removes_duplicate_metadata_strip(self):
        library_card_start = APP.index("function LibraryMovieCard")
        library_card_source = APP[library_card_start:]
        self.assertNotIn('className="movie-expanded-meta"', library_card_source)
        self.assertNotIn("<span>Country</span>", library_card_source)
        self.assertNotIn("<span>Language</span>", library_card_source)
        self.assertNotIn("<span>Resolution</span>", library_card_source)
        self.assertNotIn("<span>Source</span>", library_card_source)

    def test_expanded_people_photos_use_approved_large_scale(self):
        styles_source = STYLES.read_text(encoding="utf-8") + APP_STYLES.read_text(encoding="utf-8")
        self.assertIn("--expanded-cast-avatar-width: 106px", styles_source)
        self.assertIn("--expanded-cast-avatar-height: 132px", styles_source)
        self.assertIn("minmax(140px, 1fr)", styles_source)

    def test_expanded_people_photos_use_rectangular_portrait_framing(self):
        styles_source = APP_STYLES.read_text(encoding="utf-8")
        self.assertIn("--expanded-cast-avatar-width: 106px", styles_source)
        self.assertIn("--expanded-cast-avatar-height: 132px", styles_source)
        self.assertIn("border-radius: 10px", styles_source)

        expanded_avatar_styles = styles_source[
            styles_source.index(".movie-expanded-people-grid .person-card .person-avatar"):
            styles_source.index(".movie-expanded-people-grid .director-person .person-avatar")
        ]
        self.assertIn("width: var(--expanded-cast-avatar-width)", expanded_avatar_styles)
        self.assertIn("height: var(--expanded-cast-avatar-height)", expanded_avatar_styles)
        self.assertIn("border-radius: 10px", expanded_avatar_styles)

        expanded_director_avatar_styles = styles_source[
            styles_source.index(".movie-expanded-people-grid .director-person .person-avatar"):
            styles_source.index(".movie-expanded-people-grid .person-card strong")
        ]
        self.assertIn("border-color: #d4af3790", expanded_director_avatar_styles)

    def test_expanded_people_photos_fill_stable_portrait_frames(self):
        styles_source = APP_STYLES.read_text(encoding="utf-8")
        avatar_styles = styles_source[
            styles_source.index(".person-avatar {"):
            styles_source.index(".person-avatar img")
        ]
        self.assertIn("position: relative", avatar_styles)
        self.assertIn("overflow: hidden", avatar_styles)

        avatar_image_styles = styles_source[
            styles_source.index(".person-avatar img"):
            styles_source.index(".person-grid")
        ]
        self.assertIn("position: absolute", avatar_image_styles)
        self.assertIn("inset: 0", avatar_image_styles)
        self.assertIn("width: 100%", avatar_image_styles)
        self.assertIn("height: 100%", avatar_image_styles)
        self.assertIn("min-width: 100%", avatar_image_styles)
        self.assertIn("min-height: 100%", avatar_image_styles)
        self.assertIn("object-fit: cover", avatar_image_styles)

        expanded_card_styles = styles_source[
            styles_source.index(".movie-expanded-people-grid .person-card {"):
            styles_source.index(".movie-expanded-people-grid .director-person")
        ]
        self.assertIn("grid-template-rows: var(--expanded-cast-avatar-height) auto auto", expanded_card_styles)
        self.assertIn("align-content: start", expanded_card_styles)
        self.assertIn("justify-items: start", expanded_card_styles)
        self.assertIn("padding: 10px", expanded_card_styles)

    def test_indexer_expanded_card_uses_shared_content_width_and_action_row(self):
        styles_source = APP_STYLES.read_text(encoding="utf-8")
        card_styles = STYLES.read_text(encoding="utf-8")
        self.assertIn(".indexer-card:has(.movie-expanded-details)", styles_source)
        indexer_expanded_styles = styles_source[
            styles_source.index(".indexer-card:has(.movie-expanded-details)"):
            styles_source.index(".indexer-poster-wrap", styles_source.index(".indexer-card:has(.movie-expanded-details)"))
        ]
        self.assertNotIn("grid-template-columns", indexer_expanded_styles)
        self.assertNotIn("190px", indexer_expanded_styles)
        self.assertIn("grid-template-columns: var(--expanded-movie-card-poster-width) minmax(0, 1fr)", card_styles)

        self.assertIn("indexer-action-row indexer-action-row-expanded", APP)
        self.assertNotIn("indexer-action-rail indexer-action-rail-expanded", APP)
        self.assertIn(".indexer-action-row-expanded", styles_source)
        action_row_styles = styles_source[
            styles_source.index(".indexer-action-row-expanded"):
            styles_source.index(".indexer-selected-meta", styles_source.index(".indexer-action-row-expanded"))
        ]
        self.assertIn("display: flex", action_row_styles)
        self.assertIn("flex-wrap: wrap", action_row_styles)


if __name__ == "__main__":
    unittest.main()
