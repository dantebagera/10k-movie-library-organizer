import {
  AlertTriangle, ChevronDown, ChevronUp, CirclePlus, Clapperboard, Filter, Folder,
  Loader2, Play, RefreshCcw, RefreshCw, Search, Trash2, Wand2, X
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from '../../api/client.js';
import { announceLibraryChanged, CATALOG_GENERATION_CHANGED_EVENT, observeCatalogGeneration } from '../../api/library.js';
import { CATALOG_READY_EVENT } from '../../api/catalogEvents.js';
import { fetchCanonicalMovieDetails, markMovieDetailsCacheStale } from '../../api/movieDetails.js';
import { addMoviePayloadsToList, announceCurationChanged, CURATION_GENERATION_CHANGED_EVENT, fetchCurationJson, fetchUserListsCached } from '../../api/curation.js';
import { previewSourceReview } from '../../api/sourceReview.js';
import ListEditorModal from '../../components/ListEditorModal.jsx';
import MetadataCorrectionModal from '../../components/MetadataCorrectionModal.jsx';
import PosterEditorModal from '../../components/PosterEditorModal.jsx';
import PersonSearchCard from '../../components/PersonSearchCard.jsx';
import KeywordSearchCard from '../../components/KeywordSearchCard.jsx';
import SelectionCheckbox from '../../components/SelectionCheckbox.jsx';
import SourceReviewDialog from '../../components/SourceReviewDialog.jsx';

async function preloadFinalPosters(items) {
  const urls = [...new Set((items || []).map((item) => item?.poster_url || item?.canonical_metadata?.poster_url || '')
    .filter((url) => String(url).startsWith('/api/assets/')))];
  await Promise.all(urls.map((url) => new Promise((resolve, reject) => {
    const image = new Image();
    const timeout = window.setTimeout(() => reject(new Error(`Poster preload timed out: ${url}`)), 5000);
    image.onload = () => { window.clearTimeout(timeout); resolve(); };
    image.onerror = () => { window.clearTimeout(timeout); reject(new Error(`Poster preload failed: ${url}`)); };
    image.src = url;
  })));
}
import WorkspacePathBar from '../../components/WorkspacePathBar.jsx';
import { LibraryMovieCard } from '../../components/SharedMovieCards.jsx';
import Pagination from '../../components/Pagination.jsx';
import { ConfirmDialog, LibraryRenameModal, LibraryStat } from '../../components/LibraryControls.jsx';
import useCardGridMetrics from '../../hooks/useCardGridMetrics.js';
import useMovieCollectionCache from '../../hooks/useMovieCollectionCache.js';
import { cx, formatCount, getUniqueOptions, movieKey } from '../../utils/appUtils.js';
import {
  applyPosterOverrideToLibraryItems, applySystemListState, buildLibraryPeopleIndex, buildLibraryViewModel,
  getLocaleTag, getMovieIdentity, getQualityFactsLabel, getQualityLabel, getTmdbCacheKey, isLowQuality, listLibraryCoverage,
  listsForItem, movieHasSystemState, movieIdentityKey, moviePayload, rootLabel
} from '../../utils/libraryUtils.js';

const LIBRARY_KEYWORD_PAGE_SIZE = 50;

function sameLibraryPath(left, right) {
  return String(left || '').replaceAll('\\', '/').toLowerCase()
    === String(right || '').replaceAll('\\', '/').toLowerCase();
}

function LibraryPeopleSearchResults({ people, query, onOpenFilmography }) {
  if (!query.trim()) {
    return <div className="empty-state library-empty"><strong>Search people in your library.</strong><span>Only accepted movies and their stored actor, director, or writer metadata are used.</span></div>;
  }
  if (!people.length) {
    return <div className="empty-state library-empty"><strong>No owned people match that search.</strong><span>Try a different spelling or search movie titles instead.</span></div>;
  }
  return (
    <div className="discover-grid person-search-grid library-person-search-grid">
      {people.map((person) => (
        <PersonSearchCard
          key={person.id ? `id:${person.id}` : `name:${person.name}`}
          person={person}
          meta={`${formatCount(person.movieCount)} owned movie${person.movieCount === 1 ? '' : 's'}${person.localIdentity ? ' · Stored metadata' : ''}`}
          knownFor={person.knownFor}
          roles={person.roles}
          onOpenFilmography={onOpenFilmography}
        />
      ))}
    </div>
  );
}

function LibraryKeywordSearchResults({ result, query, loading, error, onOpenKeyword, onPageChange }) {
  const keywords = result.items || [];
  if (loading) {
    return <div className="discover-grid keyword-search-grid"><div className="keyword-search-card skeleton-card" /></div>;
  }
  if (error) {
    return <div className="empty-state library-empty"><strong>Could not search stored keywords.</strong><span>{error}</span></div>;
  }
  if (!query.trim()) {
    return <div className="empty-state library-empty"><strong>Search keywords in your library.</strong><span>Only normalized keywords already attached to owned SQL movies are used.</span></div>;
  }
  if (!keywords.length) {
    return <div className="empty-state library-empty"><strong>No owned keywords match that search.</strong><span>Try a shorter spelling or search movie titles instead.</span></div>;
  }
  return (
    <>
      <Pagination
        total={result.total_results}
        page={result.page}
        totalPages={result.total_pages}
        pageStart={(result.page - 1) * result.page_size}
        pageEnd={(result.page - 1) * result.page_size + keywords.length}
        onPageChange={onPageChange}
      />
      <div className="discover-grid keyword-search-grid library-keyword-search-grid">
        {keywords.map((keyword) => (
          <KeywordSearchCard
            key={keyword.keyword_key || keyword.tmdb_id || keyword.normalized_name}
            keyword={keyword}
            scope="library"
            meta={`${formatCount(keyword.movie_count)} owned movie${Number(keyword.movie_count) === 1 ? '' : 's'}`}
            onOpen={onOpenKeyword}
          />
        ))}
      </div>
    </>
  );
}

function librarySelectionKey(item) {
  return item.path || movieIdentityKey(moviePayload(item));
}

function LibraryBulkSelectionBar({
  kind,
  selectedCount,
  allFilteredSelected,
  onToggleAll,
  onSelectAll,
  onClear,
  onAddToList,
  onFindSources,
  onDelete
}) {
  const noun = kind === 'file' ? 'files' : 'movies';
  return (
    <div className="bulk-selection-bar library-bulk-selection">
      <SelectionCheckbox
        className="library-selection-master"
        checked={allFilteredSelected}
        onChange={onToggleAll}
        label={`Select all filtered library ${noun}`}
      />
      <span>{selectedCount ? `${formatCount(selectedCount)} selected` : `Select ${noun}`}</span>
      <button type="button" className="mini-action" onClick={onSelectAll}>
        Select all filtered
      </button>
      <button type="button" className="mini-action" onClick={onClear} disabled={!selectedCount}>
        Clear
      </button>
      <button type="button" className="mini-action" onClick={onAddToList} disabled={!selectedCount}>
        <CirclePlus size={13} /> Add to list
      </button>
      <button type="button" className="mini-action mini-action-source" onClick={onFindSources} disabled={!selectedCount}>
        <Search size={13} /> Find sources
      </button>
      <button type="button" className="mini-action mini-action-danger" onClick={onDelete} disabled={!selectedCount}>
        <Trash2 size={13} /> Delete selected
      </button>
    </div>
  );
}

function libraryFilterQuery(filters, page, pageSize, forceScan = false) {
  const params = new URLSearchParams({
    view: 'cards',
    page: String(page),
    page_size: String(pageSize),
    q: filters.query,
    resolution: filters.resolution,
    source: filters.source,
    genre: filters.genre,
    language: filters.language,
    country: filters.country,
    year_from: filters.year_from,
    year_to: filters.year_to,
    min_rating: filters.min_rating,
    sort: filters.sort,
    viewing_state: filters.viewing_state,
    role: filters.role,
    person_id: filters.person_id,
    person_name: filters.person_name,
    keyword_id: filters.keyword_id,
    keyword_name: filters.keyword_name,
    keyword_query: filters.keyword_query,
    collection_id: filters.collection_id,
    collection_paths: JSON.stringify(filters.collection_paths || []),
    list_id: filters.list_id
  });
  if (forceScan) params.set('force_scan', '1');
  return `/api/library?${params.toString()}`;
}

export default function LibraryWorkspace({
  onPlay,
  onFindTorrent,
  onOpenTrailer,
  notify,
  query,
  setQuery,
  followed = [],
  onOpenDiscoverPerson,
  onOpenDiscoverCollection = () => {},
  filterRequest,
  onFilterRequestConsumed,
  fileDetailsRequest,
  onFileDetailsRequestConsumed,
  onInitialReady
}) {
  const {
    gridRef: libraryMovieGridRef,
    measured: libraryGridMeasured,
    pageSize
  } = useCardGridMetrics({ target: 40, max: 200, bias: 'lower' });
  const [items, setItems] = useState([]);
  const [fileItems, setFileItems] = useState([]);
  const [fileItemsLoaded, setFileItemsLoaded] = useState(false);
  const [fileLoading, setFileLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [mode, setMode] = useState(() => (
    typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('view') === 'file' ? 'file' : 'movie'
  ));
  const [identityFilter, setIdentityFilter] = useState('all');
  const [sortMode, setSortMode] = useState('added');
  const [genreFilter, setGenreFilter] = useState('all');
  const [resolutionFilter, setResolutionFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');
  const [languageFilter, setLanguageFilter] = useState('all');
  const [countryFilter, setCountryFilter] = useState('all');
  const [yearFrom, setYearFrom] = useState('');
  const [yearTo, setYearTo] = useState('');
  const [minRating, setMinRating] = useState('all');
  const [sizeFilter, setSizeFilter] = useState('all');
  const [viewingStateFilter, setViewingStateFilter] = useState('all');
  const [currentPage, setCurrentPage] = useState(1);
  const [expandedPath, setExpandedPath] = useState('');
  const [focusedFilePath, setFocusedFilePath] = useState('');
  const [focusedMovieItem, setFocusedMovieItem] = useState(null);
  const [libraryHistory, setLibraryHistory] = useState([]);
  const [libraryCurrentLabel, setLibraryCurrentLabel] = useState('');
  const [tmdbCache, setTmdbCache] = useState({});
  const {
    clear: clearCollectionCache,
    getView: getCollectionView,
    load: loadMovieCollection,
    storeLoaded: storeLoadedCollection
  } = useMovieCollectionCache();
  const [userLists, setUserLists] = useState([]);
  const [librarySearchKind, setLibrarySearchKind] = useState('movies');
  const [roleFilter, setRoleFilter] = useState(null);
  const [keywordFilter, setKeywordFilter] = useState(null);
  const [listFilter, setListFilter] = useState(null);
  const [collectionEditor, setCollectionEditor] = useState(null);
  const [listEditor, setListEditor] = useState(null);
  const [renameTarget, setRenameTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [posterEditor, setPosterEditor] = useState(null);
  const [metadataCorrection, setMetadataCorrection] = useState(null);
  const [sourceReview, setSourceReview] = useState(null);
  const [showAdultMovies, setShowAdultMovies] = useState(true);
  const [selectedLibraryKeys, setSelectedLibraryKeys] = useState(() => new Set());
  const [selectedFilePaths, setSelectedFilePaths] = useState(() => new Set());
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [peopleLoaded, setPeopleLoaded] = useState(false);
  const [peopleItems, setPeopleItems] = useState([]);
  const [libraryKeywordResult, setLibraryKeywordResult] = useState({
    items: [],
    page: 1,
    page_size: LIBRARY_KEYWORD_PAGE_SIZE,
    total_pages: 1,
    total_results: 0
  });
  const [libraryKeywordLoading, setLibraryKeywordLoading] = useState(false);
  const [libraryKeywordError, setLibraryKeywordError] = useState('');
  const [listCoverageItems, setListCoverageItems] = useState([]);
  const [libraryResult, setLibraryResult] = useState({
    total: 0, page: 1, total_pages: 1, page_start: 0, page_end: 0,
    facets: { genres: [], sources: [], languages: [], countries: [] },
    stats: { total: 0, low: 0, matched: 0, pending: 0, unmatched: 0 }
  });
  const libraryRequestSeq = useRef(0);
  const backgroundRequestSeq = useRef(0);
  const backgroundRefreshRef = useRef({ running: false, pending: false });
  const initialLibraryLoadRef = useRef({ complete: false, pending: false, generation: 0, unconditional: false });
  const initialReadyNotifiedRef = useRef(false);
  const libraryLoadSignatureRef = useRef(null);
  const libraryKeywordRequestSeq = useRef(0);
  const peopleLoadPromiseRef = useRef(null);
  const movieViewStateRef = useRef(null);

  useEffect(() => {
    const clearDetailCaches = () => {
      setTmdbCache(markMovieDetailsCacheStale);
      clearCollectionCache();
    };
    window.addEventListener(CATALOG_GENERATION_CHANGED_EVENT, clearDetailCaches);
    return () => window.removeEventListener(CATALOG_GENERATION_CHANGED_EVENT, clearDetailCaches);
  }, [clearCollectionCache]);

  useEffect(() => {
    const clearCurationCaches = () => {
      clearCollectionCache();
    };
    window.addEventListener(CURATION_GENERATION_CHANGED_EVENT, clearCurationCaches);
    return () => window.removeEventListener(CURATION_GENERATION_CHANGED_EVENT, clearCurationCaches);
  }, [clearCollectionCache]);

  useEffect(() => {
    if (!filterRequest?.id) return;
    resetAllLibraryFilters();
    setMode('movie');
    setResolutionFilter(filterRequest.resolution || 'all');
    onFilterRequestConsumed?.(filterRequest.id);
  }, [filterRequest, onFilterRequestConsumed]);

  useEffect(() => {
    if (!fileDetailsRequest?.id || !fileDetailsRequest.path) return;
    openFileInventory(fileDetailsRequest.path);
    onFileDetailsRequestConsumed?.(fileDetailsRequest.id);
  }, [fileDetailsRequest, onFileDetailsRequestConsumed]);

  const serverFilters = useMemo(() => ({
    query,
    resolution: resolutionFilter,
    source: sourceFilter,
    genre: genreFilter,
    language: languageFilter,
    country: countryFilter,
    year_from: yearFrom,
    year_to: yearTo,
    min_rating: minRating,
    sort: sortMode,
    viewing_state: viewingStateFilter,
    role: roleFilter?.role || '',
    person_id: roleFilter?.id || '',
    person_name: roleFilter?.name || '',
    keyword_id: keywordFilter?.tmdb_id || '',
    keyword_name: keywordFilter?.tmdb_id ? '' : keywordFilter?.name || '',
    keyword_query: '',
    collection_id: '',
    collection_paths: [],
    list_id: listFilter?.id || ''
  }), [query, resolutionFilter, sourceFilter, genreFilter, languageFilter, countryFilter, yearFrom, yearTo, minRating, sortMode, viewingStateFilter, roleFilter, keywordFilter, listFilter]);

  const loadLibrary = useCallback(async (forceScan = false, options = {}) => {
    const background = Boolean(options.background);
    const requestSeq = background
      ? backgroundRequestSeq.current + 1
      : libraryRequestSeq.current + 1;
    if (background) backgroundRequestSeq.current = requestSeq;
    else libraryRequestSeq.current = requestSeq;
    const quiet = Boolean(options.quiet);
    if (!background) {
      setLoading(true);
      setError('');
      setStatus(forceScan ? 'Rescanning library folders...' : 'Loading library...');
    }
    try {
      const requestedPage = forceScan ? 1 : currentPage;
      const data = await fetchJson(libraryFilterQuery(serverFilters, requestedPage, pageSize, forceScan));
      if (requestSeq !== (background ? backgroundRequestSeq.current : libraryRequestSeq.current)) return;
      if (background) await preloadFinalPosters(data.items || []);
      if (requestSeq !== (background ? backgroundRequestSeq.current : libraryRequestSeq.current)) return;
      observeCatalogGeneration(data.catalog_generation);
      setItems(data.items || []);
      setLibraryResult({
        total: Number(data.total || 0),
        page: Number(data.page || 1),
        total_pages: Number(data.total_pages || 1),
        page_start: Number(data.page_start || 0),
        page_end: Number(data.page_end || 0),
        facets: data.facets || { genres: [], sources: [], languages: [], countries: [] },
        stats: data.stats || { total: 0, low: 0, matched: 0, pending: 0, unmatched: 0 }
      });
      setFileItemsLoaded(false);
      if (forceScan) setCurrentPage(1);
      if (forceScan) {
        const discovered = Number(data.new_files || 0);
        const identified = Number(data.metadata_matched || 0);
        const pending = Number(data.metadata_pending || 0);
        const summary = [
          discovered ? `${formatCount(discovered)} new file${discovered === 1 ? '' : 's'}` : '',
          identified ? `${formatCount(identified)} identified` : '',
          pending ? `${formatCount(pending)} still copying` : ''
        ].filter(Boolean).join(' · ');
        setStatus(summary || 'Rescan complete — no changes found');
        notify(summary || 'Library rescan complete — no changes found', discovered || identified ? 'success' : 'neutral');
        announceLibraryChanged({ source: 'manual-rescan', library: data });
      } else {
        if (!background) setStatus('');
        if (!quiet && !options.silentSuccess) notify(`${formatCount(data.count)} library files loaded`, 'success');
      }
      return data;
    } catch (loadError) {
      if (requestSeq !== (background ? backgroundRequestSeq.current : libraryRequestSeq.current)) return;
      if (background) setStatus(`Background library update deferred: ${loadError.message}`);
      else {
        setError(loadError.message);
        notify(`Library unavailable: ${loadError.message}`, 'error');
      }
      return null;
    } finally {
      if (!background && requestSeq === libraryRequestSeq.current) setLoading(false);
    }
  }, [currentPage, notify, pageSize, serverFilters]);

  const refreshLibraryInBackground = useCallback(async () => {
    if (backgroundRefreshRef.current.running) {
      backgroundRefreshRef.current.pending = true;
      return;
    }
    backgroundRefreshRef.current.running = true;
    let latest = null;
    try {
      do {
        backgroundRefreshRef.current.pending = false;
        latest = await loadLibrary(false, { background: true, quiet: true, silentSuccess: true });
      } while (backgroundRefreshRef.current.pending);
    } finally {
      backgroundRefreshRef.current.running = false;
    }
    return latest;
  }, [loadLibrary]);

  const requestLibraryBackgroundRefresh = useCallback((detail = {}) => {
    if (initialLibraryLoadRef.current.complete) return refreshLibraryInBackground();
    const generation = Number(detail?.generation || detail?.catalog_generation || detail?.reconcile?.catalog_generation || 0);
    initialLibraryLoadRef.current.pending = true;
    if (Number.isFinite(generation) && generation > 0) {
      initialLibraryLoadRef.current.generation = Math.max(initialLibraryLoadRef.current.generation, generation);
    } else {
      initialLibraryLoadRef.current.unconditional = true;
    }
    return Promise.resolve(null);
  }, [refreshLibraryInBackground]);

  const libraryQuerySignature = useMemo(() => JSON.stringify({
    page: currentPage,
    filters: serverFilters
  }), [currentPage, serverFilters]);

  useEffect(() => {
    if (mode !== 'movie' || librarySearchKind !== 'movies' || !libraryGridMeasured) return undefined;
    let cancelled = false;
    const previous = libraryLoadSignatureRef.current;
    const pageSizeOnlyChange = Boolean(
      initialLibraryLoadRef.current.complete
      && previous
      && previous.query === libraryQuerySignature
      && previous.pageSize !== pageSize
    );
    libraryLoadSignatureRef.current = { query: libraryQuerySignature, pageSize };

    async function refresh() {
      if (pageSizeOnlyChange) {
        await refreshLibraryInBackground();
        return;
      }
      const data = await loadLibrary(false, { quiet: true, silentSuccess: true });
      if (cancelled || !data || initialLibraryLoadRef.current.complete) return;
      const pending = { ...initialLibraryLoadRef.current };
      initialLibraryLoadRef.current.complete = true;
      initialLibraryLoadRef.current.pending = false;
      initialLibraryLoadRef.current.generation = 0;
      initialLibraryLoadRef.current.unconditional = false;
      const loadedGeneration = Number(data.catalog_generation || 0);
      if (pending.pending && (pending.unconditional || pending.generation > loadedGeneration)) {
        await refreshLibraryInBackground();
      }
    }

    refresh();
    return () => { cancelled = true; };
  }, [libraryGridMeasured, libraryQuerySignature, librarySearchKind, loadLibrary, mode, pageSize, refreshLibraryInBackground]);

  useEffect(() => {
    if (
      initialReadyNotifiedRef.current
      || !initialLibraryLoadRef.current.complete
      || loading
    ) return;
    initialReadyNotifiedRef.current = true;
    onInitialReady?.();
  }, [items, loading, onInitialReady]);

  useEffect(() => {
    const refresh = (event) => requestLibraryBackgroundRefresh(event.detail);
    window.addEventListener(CATALOG_READY_EVENT, refresh);
    return () => window.removeEventListener(CATALOG_READY_EVENT, refresh);
  }, [requestLibraryBackgroundRefresh]);

  useEffect(() => {
    if (mode !== 'file' || fileItemsLoaded) return;
    let cancelled = false;
    setFileLoading(true);
    setError('');
    setStatus('Loading file inventory...');
    fetchJson('/api/library?view=files')
      .then((data) => {
        if (cancelled) return;
        observeCatalogGeneration(data.catalog_generation);
        setFileItems(data.items || []);
        setFileItemsLoaded(true);
        setStatus('');
      })
      .catch((loadError) => {
        if (!cancelled) setError(loadError.message);
      })
      .finally(() => {
        if (!cancelled) setFileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fileItemsLoaded, mode]);

  const loadPeopleProjection = useCallback(async () => {
    if (peopleLoaded) return;
    if (peopleLoadPromiseRef.current) return peopleLoadPromiseRef.current;
    const request = fetchJson('/api/library?view=people')
      .then((data) => {
        observeCatalogGeneration(data.catalog_generation);
        setPeopleItems(data.items || []);
        setPeopleLoaded(true);
      })
      .catch((error) => {
        peopleLoadPromiseRef.current = null;
        throw error;
      });
    peopleLoadPromiseRef.current = request;
    return request;
  }, [peopleLoaded]);

  useEffect(() => {
    if (mode !== 'movie' || librarySearchKind !== 'people' || peopleLoaded) return;
    loadPeopleProjection().catch((peopleError) => notify(`People index unavailable: ${peopleError.message}`, 'error'));
  }, [librarySearchKind, loadPeopleProjection, mode, notify, peopleLoaded]);

  const loadKeywordProjection = useCallback(async (keywordQuery, requestedPage = 1) => {
    const normalizedQuery = String(keywordQuery || '').trim();
    const nextPage = Math.max(Number(requestedPage) || 1, 1);
    const requestSeq = libraryKeywordRequestSeq.current + 1;
    libraryKeywordRequestSeq.current = requestSeq;
    if (!normalizedQuery) {
      setLibraryKeywordResult({
        items: [],
        page: 1,
        page_size: LIBRARY_KEYWORD_PAGE_SIZE,
        total_pages: 1,
        total_results: 0
      });
      setLibraryKeywordError('');
      setLibraryKeywordLoading(false);
      return;
    }
    setLibraryKeywordLoading(true);
    setLibraryKeywordError('');
    setLibraryKeywordResult((state) => ({ ...state, items: [] }));
    try {
      const data = await fetchJson(
        `/api/library?view=keywords&q=${encodeURIComponent(normalizedQuery)}&page=${nextPage}&page_size=${LIBRARY_KEYWORD_PAGE_SIZE}`
      );
      if (requestSeq !== libraryKeywordRequestSeq.current) return;
      observeCatalogGeneration(data.catalog_generation);
      setLibraryKeywordResult({
        items: data.items || [],
        page: Number(data.page || nextPage),
        page_size: Number(data.page_size || LIBRARY_KEYWORD_PAGE_SIZE),
        total_pages: Number(data.total_pages || 1),
        total_results: Number(data.total_results || 0)
      });
    } catch (keywordError) {
      if (requestSeq !== libraryKeywordRequestSeq.current) return;
      setLibraryKeywordError(keywordError.message);
    } finally {
      if (requestSeq === libraryKeywordRequestSeq.current) setLibraryKeywordLoading(false);
    }
  }, []);

  useEffect(() => {
    libraryKeywordRequestSeq.current += 1;
    if (mode !== 'movie' || librarySearchKind !== 'keywords') {
      setLibraryKeywordLoading(false);
      return undefined;
    }
    setLibraryKeywordResult({
      items: [],
      page: 1,
      page_size: LIBRARY_KEYWORD_PAGE_SIZE,
      total_pages: 1,
      total_results: 0
    });
    setLibraryKeywordError('');
    setLibraryKeywordLoading(Boolean(query.trim()));
    if (!query.trim()) return undefined;
    const timer = window.setTimeout(() => loadKeywordProjection(query, 1), 150);
    return () => window.clearTimeout(timer);
  }, [librarySearchKind, loadKeywordProjection, mode, query]);

  useEffect(() => {
    function handleLibraryChanged(event) {
      if (event.detail?.source === 'manual-rescan') {
        return;
      }
      requestLibraryBackgroundRefresh(event.detail);
    }
    window.addEventListener('cp-library-changed', handleLibraryChanged);
    return () => window.removeEventListener('cp-library-changed', handleLibraryChanged);
  }, [requestLibraryBackgroundRefresh]);

  useEffect(() => {
    let cancelled = false;
    async function loadLibraryPreferences() {
      try {
        const data = await fetchJson('/api/config');
        if (!cancelled) setShowAdultMovies(data.show_adult_movies !== false);
      } catch {
        if (!cancelled) setShowAdultMovies(true);
      }
    }
    loadLibraryPreferences();
    return () => { cancelled = true; };
  }, []);

  const loadUserLists = useCallback(async (options = {}) => {
    try {
      const data = await fetchUserListsCached({ force: Boolean(options?.force) });
      setUserLists(data.lists || []);
    } catch (listsError) {
      notify(`Lists unavailable: ${listsError.message}`, 'error');
    }
  }, [notify]);

  useEffect(() => {
    loadUserLists();
    window.addEventListener('cp-curation-changed', loadUserLists);
    return () => window.removeEventListener('cp-curation-changed', loadUserLists);
  }, [loadUserLists]);

  useEffect(() => {
    setCurrentPage(1);
    setExpandedPath('');
  }, [query]);

  useEffect(() => {
    if (!loading) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const data = await fetchJson('/api/library/status');
        if (data.status) setStatus(data.status);
      } catch {
        // Status is non-critical; the main library request carries the error.
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [loading]);

  const activeItems = mode === 'file' ? fileItems : items;
  const activeLoading = loading || (mode === 'file' && fileLoading);
  const optionSets = useMemo(() => ({
    genres: mode === 'movie' ? libraryResult.facets.genres || [] : getUniqueOptions(activeItems, (item) => item.canonical_metadata?.genres?.length ? item.canonical_metadata.genres : item.plex_genres || []),
    sources: mode === 'movie' ? libraryResult.facets.sources || [] : getUniqueOptions(activeItems, (item) => item.rip_source),
    languages: mode === 'movie' ? libraryResult.facets.languages || [] : getUniqueOptions(activeItems, (item) => item.canonical_metadata?.language || item.plex_language),
    countries: mode === 'movie' ? libraryResult.facets.countries || [] : getUniqueOptions(activeItems, (item) => item.canonical_metadata?.country_flag || item.canonical_metadata?.country || item.plex_country_flag || item.plex_country)
  }), [activeItems, libraryResult.facets, mode]);

  const {
    filteredItems,
    totalPages,
    safePage,
    pageStart,
    pageEnd,
    visibleItems
  } = useMemo(() => {
    if (mode === 'movie') {
      if (focusedMovieItem) {
        return {
          filteredItems: [focusedMovieItem],
          totalPages: 1,
          safePage: 1,
          pageStart: 0,
          pageEnd: 1,
          visibleItems: [focusedMovieItem],
          stats: libraryResult.stats
        };
      }
      return {
        filteredItems: items,
        totalPages: libraryResult.total_pages,
        safePage: libraryResult.page,
        pageStart: libraryResult.page_start,
        pageEnd: libraryResult.page_end,
        visibleItems: items,
        stats: libraryResult.stats
      };
    }
    if (focusedFilePath) {
      const focusedItem = activeItems.find((item) => sameLibraryPath(item.path, focusedFilePath));
      const visible = focusedItem ? [focusedItem] : [];
      return {
        filteredItems: visible,
        totalPages: 1,
        safePage: 1,
        pageStart: 0,
        pageEnd: visible.length,
        visibleItems: visible,
        stats: libraryResult.stats
      };
    }
    return buildLibraryViewModel({
    items: activeItems,
    pageSize,
    currentPage,
    query,
    identityFilter,
    sortMode,
    genreFilter,
    resolutionFilter,
    sourceFilter,
    languageFilter,
    countryFilter,
    yearFrom,
    yearTo,
    minRating,
    sizeFilter,
    mode,
    roleFilter,
    listFilter,
    lists: userLists,
    viewingStateFilter,
    tmdbCache,
    showAdultMovies
    });
  }, [activeItems, focusedFilePath, focusedMovieItem, items, libraryResult, query, identityFilter, sortMode, genreFilter, resolutionFilter, sourceFilter, languageFilter, countryFilter, yearFrom, yearTo, minRating, sizeFilter, mode, roleFilter, listFilter, userLists, viewingStateFilter, tmdbCache, showAdultMovies, currentPage]);

  const activeSelectedPaths = mode === 'movie' ? selectedLibraryKeys : selectedFilePaths;
  const selectedPageItems = useMemo(() => {
    const activeItemsForSelection = mode === 'movie' ? items : fileItems;
    return activeItemsForSelection.filter((item) => activeSelectedPaths.has(librarySelectionKey(item)));
  }, [activeSelectedPaths, fileItems, items, mode]);
  const listMissingCoverage = useMemo(() => (
    listFilter ? listLibraryCoverage(listCoverageItems, listFilter) : null
  ), [listCoverageItems, listFilter]);
  const libraryPeopleResults = useMemo(() => (
    buildLibraryPeopleIndex(peopleItems, query)
  ), [peopleItems, query]);
  const allFilteredLibrarySelected = libraryResult.total > 0 && selectedLibraryKeys.size === libraryResult.total;
  const allFilteredFilesSelected = filteredItems.length > 0
    && filteredItems.every((item) => selectedFilePaths.has(item.path));

  function toggleLibrarySelection(item, checked) {
    const key = librarySelectionKey(item);
    setSelectedLibraryKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function toggleFileSelection(item, checked) {
    setSelectedFilePaths((current) => {
      const next = new Set(current);
      if (checked) next.add(item.path);
      else next.delete(item.path);
      return next;
    });
  }

  async function selectAllFiltered() {
    if (mode === 'file') {
      setSelectedFilePaths(new Set(filteredItems.map((item) => item.path)));
      return;
    }
    try {
      const data = await fetchJson('/api/library/selection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filters: serverFilters })
      });
      setSelectedLibraryKeys(new Set(data.paths || []));
    } catch (selectionError) {
      notify(`Library selection failed: ${selectionError.message}`, 'error');
    }
  }

  function clearActiveSelection() {
    if (mode === 'file') setSelectedFilePaths(new Set());
    else setSelectedLibraryKeys(new Set());
  }

  async function resolveSelectedLibraryItems(paths = activeSelectedPaths) {
    if (!paths.size) return [];
    const data = await fetchJson('/api/library/selection/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: [...paths] })
    });
    return data.items || [];
  }

  async function openSelectedSourceReview() {
    if (!activeSelectedPaths.size) {
      notify(`Select ${mode === 'file' ? 'files' : 'movies'} before finding sources.`, 'neutral');
      return;
    }
    setSourceReview({ loading: true, rows: [], error: '', title: 'Find sources' });
    try {
      const selectedLibraryItems = await resolveSelectedLibraryItems();
      const data = await previewSourceReview(selectedLibraryItems.map((item) => {
        const movie = moviePayload(item);
        return {
          tmdb_id: movie.tmdb_id || '',
          imdb_id: movie.imdb_id || '',
          title: movie.title,
          year: movie.year,
          poster_url: movie.poster_url || '',
          path: item.path || '',
        };
      }));
      setSourceReview({
        loading: false,
        rows: data.rows || [],
        blocked: data.blocked || [],
        defaults: data.defaults || {},
        error: '',
        title: 'Find sources',
      });
    } catch (previewError) {
      setSourceReview((current) => ({ ...current, loading: false, error: previewError.message }));
    }
  }

  function requestBulkDelete() {
    if (!activeSelectedPaths.size) return;
    const byPath = new Map(selectedPageItems.map((item) => [item.path, item]));
    setDeleteTarget({
      items: [...activeSelectedPaths].map((path) => byPath.get(path) || ({ path, filename: path.split(/[\\/]/).pop() || path }))
    });
  }

  async function openSelectedListEditor() {
    if (!activeSelectedPaths.size) return;
    try {
      setListEditor({ items: await resolveSelectedLibraryItems() });
    } catch (selectionError) {
      notify(`Selected movies unavailable: ${selectionError.message}`, 'error');
    }
  }

  useEffect(() => {
    if (!listFilter?.id) {
      setListCoverageItems([]);
      return undefined;
    }
    let cancelled = false;
    fetchJson('/api/library/selection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filters: { list_id: listFilter.id, sort: 'title' } })
    })
      .then((selection) => fetchJson('/api/library/selection/items', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: selection.paths || [] })
      }))
      .then((data) => { if (!cancelled) setListCoverageItems(data.items || []); })
      .catch((coverageError) => { if (!cancelled) notify(`List coverage unavailable: ${coverageError.message}`, 'error'); });
    return () => { cancelled = true; };
  }, [listFilter?.id, notify]);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
      setExpandedPath('');
    }
  }, [currentPage, totalPages]);

  useEffect(() => {
    if (mode !== 'movie') setLibrarySearchKind('movies');
  }, [mode]);

  function resetLibraryPage() {
    setCurrentPage(1);
    setExpandedPath('');
  }

  function resetAllLibraryFilters() {
    setLibrarySearchKind('movies');
    setQuery('');
    setIdentityFilter('all');
    setSortMode('added');
    setGenreFilter('all');
    setResolutionFilter('all');
    setSourceFilter('all');
    setLanguageFilter('all');
    setCountryFilter('all');
    setYearFrom('');
    setYearTo('');
    setMinRating('all');
    setSizeFilter('all');
    setViewingStateFilter('all');
    setRoleFilter(null);
    setKeywordFilter(null);
    setListFilter(null);
    setFocusedMovieItem(null);
    setFocusedFilePath('');
    setLibraryHistory([]);
    setLibraryCurrentLabel('');
    setSelectedLibraryKeys(new Set());
    setSelectedFilePaths(new Set());
    resetLibraryPage();
  }

  function captureLibraryMovieView() {
    return {
      query,
      identityFilter,
      sortMode,
      genreFilter,
      resolutionFilter,
      sourceFilter,
      languageFilter,
      countryFilter,
      yearFrom,
      yearTo,
      minRating,
      sizeFilter,
      viewingStateFilter,
      librarySearchKind,
      roleFilter,
      keywordFilter,
      listFilter,
      currentPage,
      expandedPath,
      focusedMovieItem
    };
  }

  function restoreLibraryMovieView(snapshot = {}) {
    setQuery(snapshot.query || '');
    setIdentityFilter(snapshot.identityFilter || 'all');
    setSortMode(snapshot.sortMode || 'added');
    setGenreFilter(snapshot.genreFilter || 'all');
    setResolutionFilter(snapshot.resolutionFilter || 'all');
    setSourceFilter(snapshot.sourceFilter || 'all');
    setLanguageFilter(snapshot.languageFilter || 'all');
    setCountryFilter(snapshot.countryFilter || 'all');
    setYearFrom(snapshot.yearFrom || '');
    setYearTo(snapshot.yearTo || '');
    setMinRating(snapshot.minRating || 'all');
    setSizeFilter(snapshot.sizeFilter || 'all');
    setViewingStateFilter(snapshot.viewingStateFilter || 'all');
    setLibrarySearchKind(snapshot.librarySearchKind || 'movies');
    setRoleFilter(snapshot.roleFilter || null);
    setKeywordFilter(snapshot.keywordFilter || null);
    setListFilter(snapshot.listFilter || null);
    setCurrentPage(snapshot.currentPage || 1);
    setExpandedPath(snapshot.expandedPath || '');
    setFocusedMovieItem(snapshot.focusedMovieItem || null);
    setFocusedFilePath('');
    setMode('movie');
  }

  function rememberMovieViewState() {
    if (mode !== 'movie') return;
    movieViewStateRef.current = {
      snapshot: captureLibraryMovieView(),
      history: libraryHistory,
      currentLabel: libraryCurrentLabel
    };
  }

  function openFileInventory(path = '') {
    rememberMovieViewState();
    setMode('file');
    setFocusedMovieItem(null);
    setFocusedFilePath(path);
    setCurrentPage(1);
    setExpandedPath(path || '');
  }

  function openRememberedMovieView() {
    const remembered = movieViewStateRef.current;
    if (remembered?.snapshot) {
      restoreLibraryMovieView(remembered.snapshot);
      setLibraryHistory(remembered.history || []);
      setLibraryCurrentLabel(remembered.currentLabel || '');
      return;
    }
    setMode('movie');
    setFocusedFilePath('');
    resetLibraryPage();
  }

  function pushLibraryContext(label, applyContext) {
    const previous = {
      ...captureLibraryMovieView(),
      label: libraryCurrentLabel || 'Library Home'
    };
    setLibraryHistory((history) => [...history, previous]);
    setLibraryCurrentLabel(label);
    setFocusedMovieItem(null);
    applyContext();
  }

  function goBackLibraryPath() {
    const previous = libraryHistory.at(-1);
    if (!previous) return;
    setLibraryHistory((history) => history.slice(0, -1));
    setLibraryCurrentLabel(previous.label === 'Library Home' ? '' : previous.label);
    restoreLibraryMovieView(previous);
  }

  function openLibraryCrumb(index) {
    const target = libraryHistory[index];
    if (!target) return;
    setLibraryHistory((history) => history.slice(0, index));
    setLibraryCurrentLabel(target.label === 'Library Home' ? '' : target.label);
    restoreLibraryMovieView(target);
  }

  function openMovieForFile(item) {
    if (!item?.metadata_accepted && !item?.canonical_metadata?.accepted) return;
    const remembered = movieViewStateRef.current;
    if (remembered?.snapshot) {
      setLibraryHistory([
        ...(remembered.history || []),
        {
          ...remembered.snapshot,
          label: remembered.currentLabel || 'Library Home'
        }
      ]);
    } else {
      setLibraryHistory([]);
    }
    const identity = getMovieIdentity(item);
    setLibraryCurrentLabel(identity.year ? `${identity.title} (${identity.year})` : identity.title);
    setMode('movie');
    setLibrarySearchKind('movies');
    setFocusedFilePath('');
    setFocusedMovieItem(item);
    setCurrentPage(1);
    setExpandedPath(item.path);
    loadLibraryDetails(item);
  }

  function goToLibraryPage(page) {
    const nextPage = Math.min(Math.max(1, page), totalPages);
    setCurrentPage(nextPage);
    setExpandedPath('');
  }

  async function loadLibraryDetails(item) {
    const cacheKey = getTmdbCacheKey(item);
    let details = tmdbCache[cacheKey];
    if (details && !details.loading && !details.error && !details.stale) {
      loadMovieCollection(details);
      return details;
    }
    setTmdbCache((cache) => ({ ...cache, [cacheKey]: { loading: true, cast: [], trailer_url: '' } }));
    try {
      details = await fetchCanonicalMovieDetails(item, item);
      setTmdbCache((cache) => ({ ...cache, [cacheKey]: details }));
      loadMovieCollection(details);
    } catch (detailsError) {
      details = { cast: [], trailer_url: '', error: detailsError.message };
      setTmdbCache((cache) => ({ ...cache, [cacheKey]: details }));
    }
    return details;
  }

  async function openLibraryTrailer(item) {
    const identity = getMovieIdentity(item);
    const details = await loadLibraryDetails(item);
    onOpenTrailer({ title: identity.title, year: identity.year }, details?.trailer_url || '');
  }

  async function applyRoleFilter(role, person, options = {}) {
    try {
      await loadPeopleProjection();
    } catch (peopleError) {
      notify(`People index unavailable: ${peopleError.message}`, 'error');
      return;
    }
    const roleLabel = role === 'writer' ? 'Writer' : role === 'director' ? 'Director' : 'Actor';
    pushLibraryContext(`${roleLabel}: ${person.name}`, () => {
      setRoleFilter({
        role,
        id: person.id || '',
        name: person.name || '',
        localOnly: Boolean(options.localOnly)
      });
      setKeywordFilter(null);
      setListFilter(null);
      setQuery('');
      resetLibraryPage();
    });
  }

  function applyLibraryPersonFilter(person, role) {
    setLibrarySearchKind('movies');
    applyRoleFilter(role, person, { localOnly: true });
  }

  function applyLibraryKeywordFilter(keyword) {
    if (!keyword?.name) return;
    pushLibraryContext(`Keyword: ${keyword.name}`, () => {
      setLibrarySearchKind('movies');
      setKeywordFilter(keyword);
      setRoleFilter(null);
      setListFilter(null);
      setQuery('');
      resetLibraryPage();
    });
  }

  function applyListFilter(list) {
    pushLibraryContext(`List: ${list.name}`, () => {
      setRoleFilter(null);
      setKeywordFilter(null);
      setListFilter(list);
      setQuery('');
      resetLibraryPage();
    });
  }

  async function saveCollectionOverride(collection, parts) {
    await fetchCurationJson('/api/user/collection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        collection_id: collection.id,
        original: collection,
        parts
      })
    });
    const data = await fetchCurationJson(`/api/library/collection/${encodeURIComponent(collection.id)}`);
    storeLoadedCollection({
      detail_source: 'library_sql',
      collection: { id: collection.id }
    }, data);
    setCollectionEditor(null);
    notify(`Collection saved as user edited`);
  }

  async function resetCollection(collection) {
    await fetchCurationJson(`/api/user/collection/${encodeURIComponent(collection.id)}/reset`, { method: 'POST' });
    const data = await fetchCurationJson(`/api/library/collection/${encodeURIComponent(collection.id)}?refresh=1`);
    storeLoadedCollection({
      detail_source: 'library_sql',
      collection: { id: collection.id }
    }, data);
    notify('Collection reset to TMDB');
  }

  async function createList(name) {
    const created = await fetchCurationJson('/api/user/lists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify(`List created: ${created.name}`);
    return created;
  }

  async function addMovieToList(listId, item) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}/movies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie: moviePayload(item) })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify('Movie added to list');
  }

  async function addMoviesToList(listId, movies) {
    const payloads = (movies || []).map((movie) => moviePayload(movie));
    await addMoviePayloadsToList(listId, payloads);
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify(`${formatCount((movies || []).length)} movie${(movies || []).length === 1 ? '' : 's'} added to list`);
    setSelectedLibraryKeys(new Set());
    setSelectedFilePaths(new Set());
  }

  async function removeMovieFromList(listId, item) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}/movies`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie: moviePayload(item) })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify('Movie removed from list');
  }

  async function toggleSystemList(systemType, item) {
    const payload = moviePayload(item);
    const active = movieHasSystemState(item, userLists, systemType);
    const nextActive = !active;
    setUserLists((current) => applySystemListState(current, systemType, payload, nextActive));
    try {
      await fetchCurationJson(`/api/user/system-lists/${encodeURIComponent(systemType)}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movie: payload, active: nextActive })
      });
    } catch (error) {
      setUserLists((current) => applySystemListState(current, systemType, payload, active));
      notify(error.message, 'error');
      return;
    }
    notify(`${getMovieIdentity(item).title} ${active ? 'removed from' : 'added to'} ${systemType === 'watched' ? 'Watched' : 'Watchlist'}`);
  }

  async function submitRename(event) {
    event.preventDefault();
    if (!renameTarget) return;
    const form = new FormData(event.currentTarget);
    const title = String(form.get('title') || '').trim();
    const year = String(form.get('year') || '').trim();
    if (!title) {
      notify('Title is required', 'error');
      return;
    }
    try {
      const data = await fetchJson('/api/rename-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: renameTarget.path, title, year })
      });
      setItems((current) => current.map((item) => (
        item.path === renameTarget.path
          ? { ...item, path: data.new_path, filename: data.new_filename, title: `${title}${year ? ` (${year})` : ''}` }
          : item
      )));
      setFileItems((current) => current.map((item) => (
        item.path === renameTarget.path
          ? { ...item, path: data.new_path, filename: data.new_filename, title: `${title}${year ? ` (${year})` : ''}` }
          : item
      )));
      setRenameTarget(null);
      notify(`Renamed to ${data.new_filename}`);
    } catch (renameError) {
      notify(`Rename failed: ${renameError.message}`, 'error');
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const targets = deleteTarget.items || [deleteTarget];
    const deletedPaths = [];
    let catalogGeneration = null;
    const failures = [];
    for (const target of targets) {
      try {
        const result = await fetchJson('/api/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: target.path, trash: true })
        });
        catalogGeneration = result.catalog_generation ?? catalogGeneration;
        deletedPaths.push(target.path);
      } catch (deleteError) {
        failures.push(`${target.filename || target.path}: ${deleteError.message}`);
      }
    }
    const deleted = new Set(deletedPaths);
    setItems((current) => current.filter((item) => !deleted.has(item.path)));
    setFileItems((current) => current.filter((item) => !deleted.has(item.path)));
    setSelectedLibraryKeys(new Set());
    setSelectedFilePaths(new Set());
    setDeleteTarget(null);
    if (deletedPaths.length) {
      notify(`${formatCount(deletedPaths.length)} file${deletedPaths.length === 1 ? '' : 's'} moved to Recycle Bin`);
      announceLibraryChanged({
        source: 'library-delete',
        deleted_paths: deletedPaths,
        catalog_generation: catalogGeneration
      });
    }
    if (failures.length) notify(`Delete failed for ${formatCount(failures.length)} file${failures.length === 1 ? '' : 's'}: ${failures[0]}`, 'error');
  }

  function applyPosterToSharedMovie(item, posterUrl, override) {
    setItems((current) => applyPosterOverrideToLibraryItems(current, item, posterUrl, override));
  }

  return (
    <section className="library-workspace">
      <div className="library-header">
        <div>
          <p className="screen-kicker">Local archive</p>
          <h2>{mode === 'movie' ? 'Movie View' : 'File View'}</h2>
          <p>{mode === 'movie' ? 'Choose what to watch using movie metadata, quality, rating, genre, country, and language.' : 'Manage local files with canonical identity, provider evidence, quality, rename, delete, and source search actions.'}</p>
        </div>
        <div className="library-header-actions">
          <div className="library-view-row">
            <div className="segmented-control library-view-switch" aria-label="Library mode">
              <button type="button" className={cx(mode === 'movie' && 'segment-active')} onClick={openRememberedMovieView}>
                <Clapperboard size={18} /> Movie View
              </button>
              <button type="button" className={cx(mode === 'file' && 'segment-active')} onClick={() => openFileInventory()}>
                <Folder size={18} /> File View
              </button>
            </div>
            <button
              type="button"
              className="btn btn-secondary library-rescan-button"
              onClick={() => loadLibrary(true)}
              disabled={activeLoading}
              aria-label="Rescan library files"
              title="Rescan library files"
            >
              {activeLoading ? <Loader2 size={19} className="spin" /> : <RefreshCw size={19} />}
            </button>
          </div>
        </div>
      </div>

      <form
        className="library-search-panel"
        data-people-search={mode === 'movie' || undefined}
        onSubmit={(event) => {
          event.preventDefault();
          if (mode === 'movie' && librarySearchKind === 'keywords') {
            loadKeywordProjection(query, 1);
          } else {
            resetLibraryPage();
          }
        }}
      >
        <label className="library-search library-main-search">
          <Search size={17} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={mode !== 'movie'
              ? 'Search your offline library...'
              : librarySearchKind === 'people'
                ? 'Search people in your library...'
                : librarySearchKind === 'keywords'
                  ? 'Search keywords in your library...'
                  : 'Search your offline library...'}
            aria-label={mode !== 'movie'
              ? 'Search your offline library'
              : librarySearchKind === 'people'
                ? 'Search people in your library'
                : librarySearchKind === 'keywords'
                  ? 'Search keywords in your library'
                  : 'Search your offline library'}
          />
        </label>
        {mode === 'movie' && (
          <select
            value={librarySearchKind}
            onChange={(event) => {
              const nextSearchKind = event.target.value;
              if (nextSearchKind !== 'movies') {
                libraryRequestSeq.current += 1;
                setLoading(false);
              }
              setError('');
              setLibrarySearchKind(nextSearchKind);
              resetLibraryPage();
            }}
            aria-label="Library search type"
          >
            <option value="movies">Movies</option>
            <option value="people">People</option>
            <option value="keywords">Keywords</option>
          </select>
        )}
        <button type="submit" className="btn btn-primary library-search-submit">
          <Search size={15} /> Search
        </button>
      </form>

      {librarySearchKind === 'movies' && <div className={cx('library-toolbar library-filter-toolbar', `library-filter-toolbar-${mode}`, !filtersOpen && 'library-filter-toolbar-collapsed')}>
        {!filtersOpen ? (
          <>
            <span>Filters collapsed: resolution, source, genre, viewing state, language, country, year, rating, sort</span>
            <button
              type="button"
              className="btn btn-secondary library-filter-icon-button"
              onClick={() => setFiltersOpen(true)}
              aria-label="Open filters"
              title="Open filters"
            >
              <Filter size={17} />
            </button>
          </>
        ) : (
          <>
            <select aria-label="Library resolution filter" value={resolutionFilter} onChange={(event) => { setResolutionFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All resolutions</option>
              <option value="upgrade">Upgrade candidates</option>
              <option value="4k">4K</option>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
              <option value="below-720p">Below 720p</option>
            </select>
            <select value={sourceFilter} onChange={(event) => { setSourceFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All sources</option>
              {optionSets.sources.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            {mode === 'movie' ? (
              <>
            <select value={genreFilter} onChange={(event) => { setGenreFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All genres</option>
              {optionSets.genres.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <select value={viewingStateFilter} onChange={(event) => { setViewingStateFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All viewing states</option>
              <option value="watched">Watched</option>
              <option value="unwatched">Unwatched</option>
              <option value="watchlist">Watchlist</option>
            </select>
            <select value={languageFilter} onChange={(event) => { setLanguageFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All languages</option>
              {optionSets.languages.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <select value={countryFilter} onChange={(event) => { setCountryFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All countries</option>
              {optionSets.countries.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <input className="library-mini-input" value={yearFrom} onChange={(event) => { setYearFrom(event.target.value); resetLibraryPage(); }} placeholder="Year from" inputMode="numeric" />
            <input className="library-mini-input" value={yearTo} onChange={(event) => { setYearTo(event.target.value); resetLibraryPage(); }} placeholder="Year to" inputMode="numeric" />
            <select value={minRating} onChange={(event) => { setMinRating(event.target.value); resetLibraryPage(); }}>
              <option value="all">Any rating</option>
              <option value="6">6+</option>
              <option value="7">7+</option>
              <option value="8">8+</option>
            </select>
            <select value={sortMode} onChange={(event) => { setSortMode(event.target.value); resetLibraryPage(); }}>
              <option value="added">Sort by newly added</option>
              <option value="title">Sort by title</option>
              <option value="rating">Sort by rating</option>
              <option value="year-desc">Year newest</option>
              <option value="year-asc">Year oldest</option>
              <option value="quality">Sort by quality</option>
            </select>
              </>
            ) : (
              <>
            <select value={identityFilter} onChange={(event) => { setIdentityFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All identity states</option>
              <option value="matched">Catalog matched</option>
              <option value="unmatched">Needs identity</option>
            </select>
            <select value={genreFilter} onChange={(event) => { setGenreFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All genres</option>
              {optionSets.genres.map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
            <select value={sizeFilter} onChange={(event) => { setSizeFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All sizes</option>
              <option value="small">Small files</option>
              <option value="large">Large files</option>
            </select>
            <select value={sortMode} onChange={(event) => { setSortMode(event.target.value); resetLibraryPage(); }}>
              <option value="added">Sort by newly added</option>
              <option value="filename">Sort by filename</option>
              <option value="title">Sort by movie title</option>
              <option value="quality">Sort by resolution</option>
              <option value="size">Sort by file size</option>
              <option value="identity">Sort by identity status</option>
              <option value="source">Sort by source</option>
            </select>
              </>
            )}
            <button
              type="button"
              className="btn btn-secondary library-filter-icon-button library-hide-filters"
              onClick={() => setFiltersOpen(false)}
              aria-label="Hide filters"
              title="Hide filters"
            >
              <ChevronUp size={18} />
            </button>
            <button
              type="button"
              className="btn btn-secondary library-filter-icon-button library-reset-filters"
              onClick={resetAllLibraryFilters}
              aria-label="Reset filters"
              title="Reset filters"
            >
              <RefreshCcw size={17} />
            </button>
          </>
        )}
      </div>}

      {(activeLoading || status || error) && (
        <div className={cx('library-status', error && 'library-status-error')}>
          {activeLoading && <Loader2 size={16} className="spin" />}
          <span>{error || status || 'Loading library...'}</span>
        </div>
      )}

      {mode === 'movie' && (
        <WorkspacePathBar
          ariaLabel="Library path"
          history={libraryHistory}
          currentLabel={libraryCurrentLabel}
          resetLabel="Library Home"
          onBack={goBackLibraryPath}
          onReset={resetAllLibraryFilters}
          onCrumb={openLibraryCrumb}
        />
      )}

      {listMissingCoverage?.missingCount > 0 && (
        <div className="metadata-filter-bar">
          <span className="list-missing-warning">
            <AlertTriangle size={14} />
            {formatCount(listMissingCoverage.matched)} of {formatCount(listMissingCoverage.total)} list movies found in Library.
            {' '}Missing: {listMissingCoverage.missingMovies.slice(0, 5).map((movie) => movie.title || 'Untitled').join(', ')}
            {listMissingCoverage.missingCount > 5 && `, +${formatCount(listMissingCoverage.missingCount - 5)} more`}
          </span>
        </div>
      )}

      {mode === 'movie' && librarySearchKind === 'movies' && !libraryGridMeasured && (
        <div
          ref={libraryMovieGridRef}
          className="library-results library-movie-results library-grid-metrics-probe"
          aria-hidden="true"
        />
      )}

      {!activeLoading && !error && (
        librarySearchKind === 'people' && mode === 'movie' ? (
          <LibraryPeopleSearchResults
            people={libraryPeopleResults}
            query={query}
            onOpenFilmography={applyLibraryPersonFilter}
          />
        ) : librarySearchKind === 'keywords' && mode === 'movie' ? (
          <LibraryKeywordSearchResults
            result={libraryKeywordResult}
            query={query}
            loading={libraryKeywordLoading}
            error={libraryKeywordError}
            onOpenKeyword={applyLibraryKeywordFilter}
            onPageChange={(nextPage) => loadKeywordProjection(query, nextPage)}
          />
        ) : (
        <>
          {(mode === 'movie' ? libraryResult.total > 0 : filteredItems.length > 0) && (
            <LibraryBulkSelectionBar
              kind={mode}
              selectedCount={activeSelectedPaths.size}
              allFilteredSelected={mode === 'movie' ? allFilteredLibrarySelected : allFilteredFilesSelected}
              onToggleAll={(checked) => { if (checked) selectAllFiltered(); else clearActiveSelection(); }}
              onSelectAll={selectAllFiltered}
              onClear={clearActiveSelection}
              onAddToList={openSelectedListEditor}
              onFindSources={openSelectedSourceReview}
              onDelete={requestBulkDelete}
            />
          )}
        <Pagination
            total={focusedMovieItem ? visibleItems.length : mode === 'movie' ? libraryResult.total : filteredItems.length}
            page={safePage}
            totalPages={totalPages}
            pageStart={pageStart}
            pageEnd={pageEnd}
            onPageChange={goToLibraryPage}
          />
          {visibleItems.length ? (
            <div
              ref={mode === 'movie' ? libraryMovieGridRef : undefined}
              className={cx('library-results', mode === 'movie' ? 'library-movie-results' : 'library-file-results')}
            >
              {visibleItems.map((item) => {
                if (mode === 'movie') {
                  const details = tmdbCache[getTmdbCacheKey(item)];
                  const collectionView = getCollectionView(details);
                  const identity = getMovieIdentity(item);
                  return (
                    <LibraryMovieCard
                      key={item.path}
                      item={item}
                      followed={followed.some((followedMovie) => movieKey(followedMovie) === movieKey(identity))}
                      expanded={expandedPath === item.path}
                      details={details}
                      collection={collectionView.data}
                      collectionStatus={collectionView.status}
                      collectionError={collectionView.error}
                      itemLists={listsForItem(item, userLists)}
                      onToggle={() => {
                        const next = expandedPath === item.path ? '' : item.path;
                        setExpandedPath(next);
                        if (next) loadLibraryDetails(item);
                      }}
                      onPlay={onPlay}
                      onFindTorrent={onFindTorrent}
                      onTrailer={() => openLibraryTrailer(item)}
                      onPersonFilter={applyRoleFilter}
                      onPersonDiscover={onOpenDiscoverPerson}
                      onCollectionBrowse={(collection) => onOpenDiscoverCollection(identity, collection)}
                      onCollectionRetry={() => loadMovieCollection(details, { force: true })}
                      onEditCollection={(collection) => setCollectionEditor({ collection, item })}
                      onResetCollection={resetCollection}
                      onListFilter={applyListFilter}
                      onEditLists={() => setListEditor({ item })}
                      onRemoveFromList={(listId) => removeMovieFromList(listId, item)}
                      onEditPoster={() => setPosterEditor({ item, path: item.path, title: identity.title })}
                      onCorrectMetadata={() => setMetadataCorrection(item)}
                      onOpenFileDetails={(owned) => openFileInventory(owned.path)}
                      watched={movieHasSystemState(item, userLists, 'watched')}
                      watchlisted={movieHasSystemState(item, userLists, 'watchlist')}
                      onToggleWatched={() => toggleSystemList('watched', item)}
                      onToggleWatchlist={() => toggleSystemList('watchlist', item)}
                      showOwnedBadge={false}
                      selected={selectedLibraryKeys.has(librarySelectionKey(item))}
                      onSelect={(checked) => toggleLibrarySelection(item, checked)}
                    />
                  );
                }
                return (
                  <LibraryFileRow
                    key={item.path}
                    item={item}
                    expanded={expandedPath === item.path}
                    onToggle={() => setExpandedPath((path) => (path === item.path ? '' : item.path))}
                    onPlay={onPlay}
                    onFindTorrent={onFindTorrent}
                    onRename={() => setRenameTarget(item)}
                    onDelete={() => setDeleteTarget(item)}
                    onOpenMovieView={() => openMovieForFile(item)}
                    selected={selectedFilePaths.has(item.path)}
                    onSelect={(checked) => toggleFileSelection(item, checked)}
                  />
                );
              })}
            </div>
          ) : (
            <div className="empty-state library-empty">
              <strong>No {mode === 'movie' ? 'movies' : 'files'} match these filters.</strong>
              <span>Clear search or change the active filters.</span>
            </div>
          )}
          <Pagination
            total={mode === 'movie' ? libraryResult.total : filteredItems.length}
            page={safePage}
            totalPages={totalPages}
            pageStart={pageStart}
            pageEnd={pageEnd}
            onPageChange={goToLibraryPage}
          />
        </>
        )
      )}

      {renameTarget && (
        <LibraryRenameModal
          item={renameTarget}
          onClose={() => setRenameTarget(null)}
          onSubmit={submitRename}
        />
      )}
      {deleteTarget && (
        <ConfirmDialog
          title={deleteTarget.items ? `Move ${deleteTarget.items.length} selected files to Recycle Bin?` : 'Move file to Recycle Bin?'}
          body={(deleteTarget.items || [deleteTarget]).map((item) => item.path).join('\n')}
          confirmLabel="Move to Recycle Bin"
          danger
          onCancel={() => setDeleteTarget(null)}
          onConfirm={confirmDelete}
        />
      )}
      {sourceReview && (
        <SourceReviewDialog
          state={sourceReview}
          setState={setSourceReview}
          onClose={() => setSourceReview(null)}
          notify={notify}
        />
      )}
      {collectionEditor && (
        <CollectionEditorModal
          collection={collectionEditor.collection}
          items={items}
          onClose={() => setCollectionEditor(null)}
          onSave={saveCollectionOverride}
        />
      )}
      {listEditor && (
        <ListEditorModal
          item={listEditor.item}
          bulkItems={listEditor.items || []}
          items={items}
          lists={userLists}
          onClose={() => setListEditor(null)}
          onCreate={createList}
          onAdd={addMovieToList}
          onAddBulk={addMoviesToList}
        />
      )}
      {posterEditor && (
        <PosterEditorModal
          item={posterEditor}
          notify={notify}
          onClose={() => setPosterEditor(null)}
          onSaved={(posterUrl, override) => applyPosterToSharedMovie(posterEditor.item, posterUrl, override)}
        />
      )}
      {metadataCorrection && (
        <MetadataCorrectionModal
          item={metadataCorrection}
          notify={notify}
          resetLabel="Reset display title/year"
          onClose={() => setMetadataCorrection(null)}
          onSaved={() => loadLibrary(false)}
        />
      )}
    </section>
  );
}




function CollectionEditorModal({ collection, items, onClose, onSave }) {
  const [parts, setParts] = useState(collection.parts || []);
  const [search, setSearch] = useState('');
  const partKeys = useMemo(() => new Set(parts.map((movie) => movieIdentityKey(movie))), [parts]);
  const candidates = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items
      .filter((item) => {
        const payload = moviePayload(item);
        if (partKeys.has(movieIdentityKey(payload))) return false;
        if (!q) return false;
        return `${payload.title} ${payload.year}`.toLowerCase().includes(q);
      })
      .slice(0, 12);
  }, [items, partKeys, search]);

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="torrent-dialog curation-dialog" role="dialog" aria-modal="true" aria-label="Edit collection" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">Edit collection</p>
            <h2>{collection.name}</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close collection editor">
            <X size={18} />
          </button>
        </div>
        <p className="dialog-body-path">Saving changes marks this collection as made by User. Reset restores the TMDB version.</p>
        <label className="library-search curation-search">
          <Search size={17} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search local movies to add..." />
        </label>
        {candidates.length > 0 && (
          <div className="curation-candidates">
            {candidates.map((item) => {
              const payload = moviePayload(item);
              return (
                <button type="button" key={item.path} onClick={() => { setParts((current) => [...current, payload]); setSearch(''); }}>
                  <CirclePlus size={15} />
                  {payload.title}{payload.year ? ` (${payload.year})` : ''}
                </button>
              );
            })}
          </div>
        )}
        <div className="curation-list">
          {parts.map((movie) => (
            <div className="curation-row" key={movieIdentityKey(movie)}>
              <span>{movie.title}{movie.year ? ` (${movie.year})` : ''}</span>
              <button type="button" className="mini-action mini-action-danger" onClick={() => setParts((current) => current.filter((item) => movieIdentityKey(item) !== movieIdentityKey(movie)))}>
                <Trash2 size={13} /> Remove
              </button>
            </div>
          ))}
        </div>
        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={() => onSave(collection, parts)}>Save collection</button>
        </div>
      </section>
    </div>
  );
}


function formatMediaDecimal(value, maximumFractionDigits = 3) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return '';
  return number.toFixed(maximumFractionDigits).replace(/0+$/, '').replace(/\.$/, '');
}

function formatMediaBitrate(value) {
  const bitsPerSecond = Number(value || 0);
  if (!Number.isFinite(bitsPerSecond) || bitsPerSecond <= 0) return 'Unavailable';
  if (bitsPerSecond >= 1000000) {
    return `${formatMediaDecimal(bitsPerSecond / 1000000, 2)} Mbps`;
  }
  return `${Math.round(bitsPerSecond / 1000)} kbps`;
}

function formatMediaDuration(value) {
  const totalSeconds = Math.round(Number(value || 0) / 1000);
  if (!totalSeconds) return 'Unavailable';
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours ? `${hours}h` : '', `${minutes}m`, `${seconds}s`].filter(Boolean).join(' ');
}

function formatMediaRotation(value) {
  const degrees = Number(value || 0);
  if (!Number.isFinite(degrees) || degrees === 0) return 'None';
  const magnitude = Math.abs(degrees).toFixed(3).replace(/0+$/, '').replace(/\.$/, '');
  return `${degrees < 0 ? '-' : ''}${magnitude}°`;
}

function formatProbeStatus(item) {
  const labels = {
    ok: 'Measured',
    unprobed: 'Not measured yet',
    missing: 'File unavailable',
    unstable: 'File changed during inspection',
    error: 'Measurement failed'
  };
  const status = String(item.probe_status || 'unprobed');
  const measuredAt = Number(item.probed_at || 0);
  const timestamp = measuredAt > 0 ? new Date(measuredAt * 1000).toLocaleString() : '';
  return `${labels[status] || status}${timestamp ? ` · ${timestamp}` : ''}`;
}

function describeFileQualityEvidence(item) {
  const claim = item.filename_quality_claim && item.filename_quality_claim !== 'Unknown'
    ? item.filename_quality_claim
    : '';
  const measuredClass = item.quality_class || item.resolution || 'Unknown';
  const dimensions = item.video_width && item.video_height
    ? `${item.video_width} × ${item.video_height}`
    : '';

  if (item.quality_conflict) {
    return `Conflict: filename claims ${claim || 'no quality'}; measured ${dimensions || 'dimensions'} classify as ${measuredClass}.`;
  }
  if (item.quality_source === 'filename_fallback') {
    return `${claim ? `Filename claims ${claim}` : 'No measured dimensions'}; stream measurement is unavailable, so this classification is provisional.`;
  }
  if (dimensions && item.quality_nonstandard) {
    return `${dimensions} is a non-standard frame size classified in the ${measuredClass} quality class.`;
  }
  if (dimensions && claim) {
    return `Filename claim ${claim} agrees with the measured ${dimensions} frame.`;
  }
  if (dimensions) {
    return `${measuredClass} is based on the measured ${dimensions} frame.`;
  }
  return 'Quality evidence is unavailable until this file is measured.';
}

function LibraryFileRow({
  item,
  expanded,
  onToggle,
  onPlay,
  onFindTorrent,
  onRename,
  onDelete,
  onOpenMovieView,
  selected,
  onSelect
}) {
  const identity = getMovieIdentity(item);
  const canonical = item.canonical_metadata || {};
  const lowQuality = isLowQuality(item.resolution);
  const movieForSearch = { title: identity.title, year: identity.year, imdb_id: item.imdb_id || '', tmdb_id: item.tmdb_id || '' };
  const videoFormat = [
    item.video_codec,
    item.video_profile,
    item.video_bit_depth ? `${item.video_bit_depth}-bit` : ''
  ].filter(Boolean).join(' · ') || 'Unavailable';
  const audioFormat = [
    item.audio_codec,
    item.audio_channels ? `${formatMediaDecimal(item.audio_channels)} channels` : '',
    item.audio_bitrate ? formatMediaBitrate(item.audio_bitrate) : ''
  ].filter(Boolean).join(' · ') || 'Unavailable';
  function handleKeyDown(event) {
    if (event.target !== event.currentTarget) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onToggle();
    }
  }
  return (
    <article
      className={cx('library-file-row', expanded && 'library-file-row-expanded', selected && 'library-file-row-selected')}
      onClick={onToggle}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      aria-expanded={expanded}
    >
      <div className="file-row-main">
        <SelectionCheckbox
          className="file-selection-checkbox"
          checked={selected}
          onChange={onSelect}
          label={`Select ${item.filename}`}
        />
        <div className="file-row-copy">
          <div className="file-row-title">
            <strong>{item.filename}</strong>
            <span>{identity.title}{identity.year ? ` (${identity.year})` : ''}</span>
          </div>
          <div className="file-row-path" title={item.path}>{item.path}</div>
          <div className="file-row-meta">
            <span className={cx('chip', lowQuality && 'chip-warning')}>{getQualityFactsLabel(item)}</span>
            <span className="chip chip-muted">{item.rip_source || 'Unknown source'}</span>
            <span className="chip chip-muted">{item.size_human || '?'}</span>
            {item.library_root && <span className="chip chip-muted">{rootLabel(item.library_root)}</span>}
            <span className={cx('chip', item.metadata_accepted ? 'status-owned' : 'status-missing')}>{item.metadata_accepted ? 'Catalog matched' : 'Needs identity'}</span>
            {(canonical.genres?.length ? canonical.genres : item.plex_genres || []).slice(0, 2).map((genre) => <span className="chip chip-muted" key={genre}>{genre}</span>)}
            {getLocaleTag(item) && <span className="chip chip-muted">{getLocaleTag(item)}</span>}
          </div>
        </div>
      </div>
      <div className="file-row-actions" onClick={(event) => event.stopPropagation()}>
        <button type="button" className="btn btn-primary btn-green" onClick={() => onPlay(item.path)}>
          <Play size={15} /> Play
        </button>
        <button type="button" className={cx('btn', lowQuality ? 'btn-upgrade' : 'btn-secondary')} onClick={() => onFindTorrent(movieForSearch, lowQuality)}>
          <Wand2 size={15} /> {lowQuality ? 'Find upgrade' : 'Find sources'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onRename}>
          <Clapperboard size={15} /> Rename
        </button>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={onOpenMovieView}
          disabled={!item.metadata_accepted && !canonical.accepted}
          title={!item.metadata_accepted && !canonical.accepted ? 'This file has no accepted Movie View identity yet.' : 'Open this movie in Movie View'}
        >
          <Clapperboard size={15} /> Movie View
        </button>
        <button type="button" className="btn btn-danger" onClick={onDelete}>
          <Trash2 size={15} /> Delete
        </button>
        <button
          type="button"
          className="btn btn-secondary file-row-expand"
          onClick={onToggle}
          aria-label={expanded ? `Collapse file details for ${item.filename}` : `Expand file details for ${item.filename}`}
          aria-expanded={expanded}
          title={expanded ? 'Collapse file details' : 'Expand file details'}
        >
          <ChevronDown size={17} />
        </button>
      </div>
      {expanded && (
        <div className="file-expanded-panel" onClick={(event) => event.stopPropagation()}>
          <div><span>Full path</span><strong>{item.path}</strong></div>
          <div><span>Catalog title</span><strong>{canonical.title || identity.title || 'Needs identity'}</strong></div>
          <div><span>Catalog year</span><strong>{canonical.year || identity.year || 'Unknown'}</strong></div>
          <div><span>Metadata source</span><strong>{item.metadata_source || canonical.source || 'None'}</strong></div>
          <div><span>TMDB / IMDb</span><strong>{canonical.tmdb_id || item.tmdb_id || '—'} / {canonical.imdb_id || item.imdb_id || '—'}</strong></div>
          <div><span>Plex evidence</span><strong>{item.plex_matched ? `${item.plex_title || 'Matched'}${item.plex_year ? ` (${item.plex_year})` : ''}` : 'Not available'}</strong></div>
          <div><span>Locale</span><strong>{getLocaleTag(item) || 'Unknown'}</strong></div>
          <div><span>Size</span><strong>{item.size_human || '?'} ({formatCount(item.size)} bytes)</strong></div>
          <div><span>Genres</span><strong>{(canonical.genres?.length ? canonical.genres : item.plex_genres || []).join(', ') || 'None'}</strong></div>
          <div className="file-expanded-section-title">
            <span>Physical file facts</span>
            <strong>Measured from the primary video and audio streams</strong>
          </div>
          <div><span>Measured dimensions</span><strong>{item.video_width && item.video_height ? `${item.video_width} × ${item.video_height}` : 'Unavailable'}</strong></div>
          <div><span>Quality classification</span><strong>{item.quality_class || getQualityLabel(item)}</strong></div>
          <div><span>Video format</span><strong>{videoFormat}</strong></div>
          <div><span>Video bitrate</span><strong>{formatMediaBitrate(item.video_bitrate)}</strong></div>
          <div><span>Duration</span><strong>{formatMediaDuration(item.duration_ms)}</strong></div>
          <div className="file-expanded-secondary-fact"><span>Frame rate</span><strong>{formatMediaDecimal(item.video_frame_rate) ? `${formatMediaDecimal(item.video_frame_rate)} fps` : 'Unavailable'}</strong></div>
          <div className="file-expanded-secondary-fact"><span>Display aspect ratio</span><strong>{formatMediaDecimal(item.display_aspect_ratio) ? `${formatMediaDecimal(item.display_aspect_ratio)}:1` : 'Unavailable'}</strong></div>
          <div className="file-expanded-secondary-fact"><span>Rotation</span><strong>{formatMediaRotation(item.rotation_degrees)}</strong></div>
          <div><span>Primary audio</span><strong>{audioFormat}</strong></div>
          <div><span>Probe status</span><strong>{formatProbeStatus(item)}</strong></div>
          <div className={cx('file-expanded-quality-evidence', item.quality_conflict && 'file-expanded-quality-conflict')}>
            <span>Quality evidence</span>
            <strong>{describeFileQualityEvidence(item)}</strong>
          </div>
          {item.probe_error && (
            <div className="file-expanded-probe-error">
              <span>Probe error</span>
              <strong>{item.probe_error}</strong>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
