import {
  AlertTriangle, CirclePlus, Clapperboard, Copy, Database, Folder, Info, Library,
  Link as LinkIcon, Loader2, Play, RefreshCcw, Search, Trash2, Wand2, X
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from '../../api/client.js';
import { announceLibraryChanged, CATALOG_GENERATION_CHANGED_EVENT, observeCatalogGeneration } from '../../api/library.js';
import { fetchCanonicalMovieDetails, markMovieDetailsCacheStale, movieCollectionUrl } from '../../api/movieDetails.js';
import { addMoviePayloadsToList, announceCurationChanged, CURATION_GENERATION_CHANGED_EVENT, fetchCurationJson, fetchUserListsCached } from '../../api/curation.js';
import { previewSourceReview } from '../../api/sourceReview.js';
import ExportCopyDialog from '../../components/ExportCopyDialog.jsx';
import ListEditorModal from '../../components/ListEditorModal.jsx';
import MetadataCorrectionModal from '../../components/MetadataCorrectionModal.jsx';
import PosterEditorModal from '../../components/PosterEditorModal.jsx';
import PersonSearchCard from '../../components/PersonSearchCard.jsx';
import KeywordSearchCard from '../../components/KeywordSearchCard.jsx';
import SelectionCheckbox from '../../components/SelectionCheckbox.jsx';
import SourceReviewDialog from '../../components/SourceReviewDialog.jsx';
import { LibraryMovieCard } from '../../components/SharedMovieCards.jsx';
import Pagination from '../../components/Pagination.jsx';
import { ConfirmDialog, LibraryRenameModal, LibraryStat } from '../../components/LibraryControls.jsx';
import { cx, formatCount, getUniqueOptions } from '../../utils/appUtils.js';
import {
  applyPosterOverrideToLibraryItems, buildLibraryPeopleIndex, buildLibraryViewModel,
  getLocaleTag, getMovieIdentity, getTmdbCacheKey, isLowQuality, listLibraryCoverage,
  listsForItem, movieHasSystemState, movieIdentityKey, moviePayload, rootLabel
} from '../../utils/libraryUtils.js';

const LIBRARY_KEYWORD_PAGE_SIZE = 50;

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

function libraryFilterQuery(filters, page, pageSize, forceScan = false) {
  const params = new URLSearchParams({
    view: 'cards',
    page: String(page),
    page_size: String(pageSize),
    q: filters.query,
    quality: filters.quality,
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

export default function LibraryWorkspace({ onPlay, onFindTorrent, onOpenTrailer, notify, query, setQuery, onReviewUnmatched, onOpenDiscoverPerson, filterRequest, onFilterRequestConsumed }) {
  const pageSize = 40;
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
  const [qualityFilter, setQualityFilter] = useState('all');
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
  const [tmdbCache, setTmdbCache] = useState({});
  const [collectionCache, setCollectionCache] = useState({});
  const [userLists, setUserLists] = useState([]);
  const [librarySearchKind, setLibrarySearchKind] = useState('movies');
  const [roleFilter, setRoleFilter] = useState(null);
  const [keywordFilter, setKeywordFilter] = useState(null);
  const [collectionFilter, setCollectionFilter] = useState(null);
  const [listFilter, setListFilter] = useState(null);
  const [metadataStatus, setMetadataStatus] = useState('');
  const [collectionEditor, setCollectionEditor] = useState(null);
  const [listEditor, setListEditor] = useState(null);
  const [listsManagerOpen, setListsManagerOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [posterEditor, setPosterEditor] = useState(null);
  const [metadataCorrection, setMetadataCorrection] = useState(null);
  const [sourceReview, setSourceReview] = useState(null);
  const [showAdultMovies, setShowAdultMovies] = useState(true);
  const [selectedLibraryKeys, setSelectedLibraryKeys] = useState(() => new Set());
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
  const libraryKeywordRequestSeq = useRef(0);
  const peopleLoadPromiseRef = useRef(null);

  useEffect(() => {
    const clearDetailCaches = () => {
      setTmdbCache(markMovieDetailsCacheStale);
      setCollectionCache({});
    };
    window.addEventListener(CATALOG_GENERATION_CHANGED_EVENT, clearDetailCaches);
    return () => window.removeEventListener(CATALOG_GENERATION_CHANGED_EVENT, clearDetailCaches);
  }, []);

  useEffect(() => {
    const clearCurationCaches = () => {
      setCollectionCache({});
    };
    window.addEventListener(CURATION_GENERATION_CHANGED_EVENT, clearCurationCaches);
    return () => window.removeEventListener(CURATION_GENERATION_CHANGED_EVENT, clearCurationCaches);
  }, []);

  useEffect(() => {
    if (!filterRequest?.id) return;
    resetAllLibraryFilters();
    setMode('movie');
    setQualityFilter(filterRequest.quality || 'all');
    onFilterRequestConsumed?.(filterRequest.id);
  }, [filterRequest, onFilterRequestConsumed]);

  const serverFilters = useMemo(() => ({
    query,
    quality: qualityFilter,
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
    collection_id: collectionFilter?.id || '',
    collection_paths: collectionFilter?.owned_paths || [],
    list_id: listFilter?.id || ''
  }), [query, qualityFilter, resolutionFilter, sourceFilter, genreFilter, languageFilter, countryFilter, yearFrom, yearTo, minRating, sortMode, viewingStateFilter, roleFilter, keywordFilter, collectionFilter, listFilter]);

  const loadLibrary = useCallback(async (forceScan = false, options = {}) => {
    const requestSeq = libraryRequestSeq.current + 1;
    libraryRequestSeq.current = requestSeq;
    const quiet = Boolean(options.quiet);
    setLoading(true);
    setError('');
    setStatus(forceScan ? 'Rescanning library folders...' : 'Loading library...');
    try {
      const requestedPage = forceScan ? 1 : currentPage;
      const data = await fetchJson(libraryFilterQuery(serverFilters, requestedPage, pageSize, forceScan));
      if (requestSeq !== libraryRequestSeq.current) return;
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
        setStatus('');
        if (!quiet && !options.silentSuccess) notify(`${formatCount(data.count)} library files loaded`, 'success');
      }
    } catch (loadError) {
      if (requestSeq !== libraryRequestSeq.current) return;
      setError(loadError.message);
      notify(`Library unavailable: ${loadError.message}`, 'error');
    } finally {
      if (requestSeq === libraryRequestSeq.current) setLoading(false);
    }
  }, [currentPage, notify, serverFilters]);

  useEffect(() => {
    if (mode === 'movie' && librarySearchKind === 'movies') loadLibrary(false, { quiet: true, silentSuccess: true });
  }, [librarySearchKind, loadLibrary, mode]);

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
      loadLibrary(false, { quiet: true });
    }
    window.addEventListener('cp-library-changed', handleLibraryChanged);
    return () => window.removeEventListener('cp-library-changed', handleLibraryChanged);
  }, [loadLibrary]);

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
    visibleItems,
    stats
  } = useMemo(() => {
    if (mode === 'movie') {
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
    return buildLibraryViewModel({
    items: activeItems,
    pageSize,
    currentPage,
    query,
    qualityFilter,
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
    collectionFilter,
    listFilter,
    lists: userLists,
    viewingStateFilter,
    tmdbCache,
    showAdultMovies
    });
  }, [activeItems, items, libraryResult, query, qualityFilter, identityFilter, sortMode, genreFilter, resolutionFilter, sourceFilter, languageFilter, countryFilter, yearFrom, yearTo, minRating, sizeFilter, mode, roleFilter, collectionFilter, listFilter, userLists, viewingStateFilter, tmdbCache, showAdultMovies, currentPage]);

  const selectedPageItems = useMemo(() => (
    items.filter((item) => selectedLibraryKeys.has(librarySelectionKey(item)))
  ), [items, selectedLibraryKeys]);
  const listMissingCoverage = useMemo(() => (
    listFilter ? listLibraryCoverage(listCoverageItems, listFilter) : null
  ), [listCoverageItems, listFilter]);
  const libraryPeopleResults = useMemo(() => (
    buildLibraryPeopleIndex(peopleItems, query)
  ), [peopleItems, query]);
  const allFilteredLibrarySelected = libraryResult.total > 0 && selectedLibraryKeys.size === libraryResult.total;

  function toggleLibrarySelection(item, checked) {
    const key = librarySelectionKey(item);
    setSelectedLibraryKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  async function selectAllFilteredLibrary() {
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

  function clearLibrarySelection() {
    setSelectedLibraryKeys(new Set());
  }

  async function resolveSelectedLibraryItems() {
    if (!selectedLibraryKeys.size) return [];
    const data = await fetchJson('/api/library/selection/items', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: [...selectedLibraryKeys] })
    });
    return data.items || [];
  }

  async function openSelectedSourceReview() {
    if (!selectedLibraryKeys.size) {
      notify('Select movies before finding sources.', 'neutral');
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
    if (!selectedLibraryKeys.size) return;
    const byPath = new Map(selectedPageItems.map((item) => [item.path, item]));
    setDeleteTarget({
      items: [...selectedLibraryKeys].map((path) => byPath.get(path) || ({ path, filename: path.split(/[\\/]/).pop() || path }))
    });
  }

  async function openSelectedListEditor() {
    if (!selectedLibraryKeys.size) return;
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
    if (mode !== 'movie' && selectedLibraryKeys.size) {
      setSelectedLibraryKeys(new Set());
    }
  }, [mode, selectedLibraryKeys.size]);

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
    setQualityFilter('all');
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
    setCollectionFilter(null);
    setListFilter(null);
    setMetadataStatus('');
    setSelectedLibraryKeys(new Set());
    resetLibraryPage();
  }

  function goToLibraryPage(page) {
    const nextPage = Math.min(Math.max(1, page), totalPages);
    setCurrentPage(nextPage);
    setExpandedPath('');
  }

  async function loadLibraryDetails(item) {
    const cacheKey = getTmdbCacheKey(item);
    let details = tmdbCache[cacheKey];
    if (details && !details.loading && !details.error && !details.stale) return details;
    setTmdbCache((cache) => ({ ...cache, [cacheKey]: { loading: true, cast: [], trailer_url: '' } }));
    try {
      details = await fetchCanonicalMovieDetails(item, item);
      setTmdbCache((cache) => ({ ...cache, [cacheKey]: details }));
      const collectionUrl = movieCollectionUrl(details);
      if (collectionUrl && !collectionCache[details.collection.id]) {
        fetchCurationJson(collectionUrl)
          .then((collectionData) => setCollectionCache((cache) => ({ ...cache, [details.collection.id]: collectionData })))
          .catch(() => {});
      }
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
    setRoleFilter({
      role,
      id: person.id || '',
      name: person.name || '',
      localOnly: Boolean(options.localOnly)
    });
    setKeywordFilter(null);
    setQuery('');
    setCollectionFilter(null);
    resetLibraryPage();
    setMetadataStatus('');
  }

  function applyLibraryPersonFilter(person, role) {
    setLibrarySearchKind('movies');
    applyRoleFilter(role, person, { localOnly: true });
  }

  function applyLibraryKeywordFilter(keyword) {
    if (!keyword?.name) return;
    setLibrarySearchKind('movies');
    setKeywordFilter(keyword);
    setRoleFilter(null);
    setCollectionFilter(null);
    setListFilter(null);
    setQuery('');
    setMetadataStatus('');
    resetLibraryPage();
  }

  async function applyCollectionFilter(collection) {
    if (!collection?.id) return;
    setRoleFilter(null);
    setKeywordFilter(null);
    setListFilter(null);
    setQuery('');
    resetLibraryPage();
    setMetadataStatus(`Loading ${collection.name} collection...`);
    setCollectionFilter({ ...collection, parts: [] });
    try {
      const data = await fetchCurationJson(`/api/library/collection/${encodeURIComponent(collection.id)}`);
      setCollectionCache((cache) => ({ ...cache, [data.id || collection.id]: data }));
      setCollectionFilter({
        id: data.id || collection.id,
        name: data.name || collection.name,
        parts: data.parts || [],
        owned_paths: data.owned_paths || [],
        owned_count: Number(data.owned_count || 0),
        unresolved_count: Number(data.unresolved_count || 0),
        unresolved_parts: data.unresolved_parts || [],
        conflicts: data.conflicts || [],
        source: data.source,
        is_edited: data.is_edited
      });
      setMetadataStatus('');
    } catch (collectionError) {
      setMetadataStatus(`Collection unavailable: ${collectionError.message}`);
    }
  }

  function clearMetadataFilters() {
    setRoleFilter(null);
    setKeywordFilter(null);
    setCollectionFilter(null);
    setListFilter(null);
    setMetadataStatus('');
    resetLibraryPage();
  }

  function applyListFilter(list) {
    setRoleFilter(null);
    setKeywordFilter(null);
    setCollectionFilter(null);
    setListFilter(list);
    setQuery('');
    resetLibraryPage();
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
    setCollectionCache((cache) => ({ ...cache, [collection.id]: data }));
    setCollectionFilter((filter) => (filter?.id === collection.id ? { ...data } : filter));
    setCollectionEditor(null);
    notify(`Collection saved as user edited`);
  }

  async function resetCollection(collection) {
    await fetchCurationJson(`/api/user/collection/${encodeURIComponent(collection.id)}/reset`, { method: 'POST' });
    const data = await fetchCurationJson(`/api/library/collection/${encodeURIComponent(collection.id)}?refresh=1`);
    setCollectionCache((cache) => ({ ...cache, [collection.id]: data }));
    setCollectionFilter((filter) => (filter?.id === collection.id ? { ...data } : filter));
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
  }

  async function renameList(listId, name) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify('List renamed');
  }

  async function deleteList(listId) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}`, { method: 'DELETE' });
    if (listFilter?.id === listId) setListFilter(null);
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify('List deleted');
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
    const active = movieHasSystemState(item, userLists, systemType);
    await fetchCurationJson(`/api/user/system-lists/${encodeURIComponent(systemType)}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie: moviePayload(item), active: !active })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
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
    const failures = [];
    for (const target of targets) {
      try {
        await fetchJson('/api/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: target.path, trash: true })
        });
        deletedPaths.push(target.path);
      } catch (deleteError) {
        failures.push(`${target.filename || target.path}: ${deleteError.message}`);
      }
    }
    const deleted = new Set(deletedPaths);
    setItems((current) => current.filter((item) => !deleted.has(item.path)));
    setFileItems((current) => current.filter((item) => !deleted.has(item.path)));
    setSelectedLibraryKeys(new Set());
    setDeleteTarget(null);
    if (deletedPaths.length) {
      notify(`${formatCount(deletedPaths.length)} file${deletedPaths.length === 1 ? '' : 's'} moved to Recycle Bin`);
      announceLibraryChanged({ source: 'library-delete', deleted_paths: deletedPaths });
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
              <button type="button" className={cx(mode === 'movie' && 'segment-active')} onClick={() => { setMode('movie'); resetLibraryPage(); }}>
                <Clapperboard size={18} /> Movie View
              </button>
              <button type="button" className={cx(mode === 'file' && 'segment-active')} onClick={() => { setMode('file'); resetLibraryPage(); }}>
                <Folder size={18} /> File View
              </button>
            </div>
          </div>
          <div className="library-action-row">
            <button type="button" className="btn btn-secondary" onClick={() => loadLibrary(true)} disabled={activeLoading}>
              {activeLoading ? <Loader2 size={15} className="spin" /> : <Database size={15} />} Rescan Files
            </button>
            {stats.unmatched > 0 && (
              <button type="button" className="btn btn-primary btn-violet" onClick={onReviewUnmatched}>
                <LinkIcon size={15} /> Review Unmatched
              </button>
            )}
            <button type="button" className="btn btn-secondary" onClick={() => setListEditor({ item: null })}>
              <CirclePlus size={15} /> New list
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setListsManagerOpen(true)}>
              <Library size={15} /> My Lists
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

      {librarySearchKind === 'movies' && <div className={cx('library-toolbar library-filter-toolbar', !filtersOpen && 'library-filter-toolbar-collapsed')}>
        {!filtersOpen ? (
          <>
            <span>Filters collapsed: quality, resolution, source, genre, viewing state, language, country, year, rating, sort</span>
            <button type="button" className="btn btn-secondary" onClick={() => setFiltersOpen(true)}>
              Open Filters
            </button>
          </>
        ) : (
          <>
            <select aria-label="Library quality filter" value={qualityFilter} onChange={(event) => { setQualityFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All qualities</option>
              <option value="upgrade">Upgrade candidates</option>
              <option value="good">1080p and above</option>
              <option value="4k">4K only</option>
            </select>
            <select value={resolutionFilter} onChange={(event) => { setResolutionFilter(event.target.value); resetLibraryPage(); }}>
              <option value="all">All resolutions</option>
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
            <button type="button" className="btn btn-secondary library-reset-filters" onClick={resetAllLibraryFilters}>
              <RefreshCcw size={15} /> Reset filters
            </button>
            <button type="button" className="btn btn-secondary library-hide-filters" onClick={() => setFiltersOpen(false)}>
              <X size={15} /> Hide Filters
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

      {(roleFilter || keywordFilter || collectionFilter || listFilter || metadataStatus) && (
        <div className="metadata-filter-bar">
          {metadataStatus && (
            <span className="metadata-filter-status">
              <Loader2 size={14} className={metadataStatus.startsWith('Loading') ? 'spin' : ''} />
              {metadataStatus}
            </span>
          )}
          {roleFilter && (
            <button type="button" className="metadata-filter-chip" onClick={clearMetadataFilters}>
              {roleFilter.role === 'writer' ? 'Writer' : roleFilter.role === 'director' ? 'Director' : 'Actor'}: {roleFilter.name}
              <X size={14} />
            </button>
          )}
          {keywordFilter && (
            <button type="button" className="metadata-filter-chip" onClick={clearMetadataFilters}>
              Keyword: {keywordFilter.name}
              <X size={14} />
            </button>
          )}
          {collectionFilter && (
            <button type="button" className="metadata-filter-chip" onClick={clearMetadataFilters}>
              Collection: {collectionFilter.name}
              {Number.isFinite(collectionFilter.owned_count) && ` · ${formatCount(collectionFilter.owned_count)} owned`}
              {collectionFilter.unresolved_count > 0 && ` · ${formatCount(collectionFilter.unresolved_count)} need identity review`}
              <X size={14} />
            </button>
          )}
          {listFilter && (
            <button type="button" className="metadata-filter-chip" onClick={clearMetadataFilters}>
              List: {listFilter.name}
              <X size={14} />
            </button>
          )}
          {listMissingCoverage?.missingCount > 0 && (
            <span className="list-missing-warning">
              <AlertTriangle size={14} />
              {formatCount(listMissingCoverage.matched)} of {formatCount(listMissingCoverage.total)} list movies found in Library.
              {' '}Missing: {listMissingCoverage.missingMovies.slice(0, 5).map((movie) => movie.title || 'Untitled').join(', ')}
              {listMissingCoverage.missingCount > 5 && `, +${formatCount(listMissingCoverage.missingCount - 5)} more`}
            </span>
          )}
        </div>
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
          {mode === 'movie' && libraryResult.total > 0 && (
            <div className="bulk-selection-bar library-bulk-selection">
              <SelectionCheckbox
                className="library-selection-master"
                checked={allFilteredLibrarySelected}
                onChange={(checked) => { if (checked) selectAllFilteredLibrary(); else clearLibrarySelection(); }}
                label="Select all filtered library movies"
              />
              <span>{selectedLibraryKeys.size ? `${formatCount(selectedLibraryKeys.size)} selected` : 'Select movies'}</span>
              <button type="button" className="mini-action" onClick={selectAllFilteredLibrary}>
                Select all filtered
              </button>
              <button type="button" className="mini-action" onClick={clearLibrarySelection} disabled={!selectedLibraryKeys.size}>
                Clear
              </button>
              <button type="button" className="mini-action" onClick={openSelectedListEditor} disabled={!selectedLibraryKeys.size}>
                <CirclePlus size={13} /> Add to list
              </button>
              <button type="button" className="mini-action mini-action-source" onClick={openSelectedSourceReview} disabled={!selectedLibraryKeys.size}>
                <Search size={13} /> Find sources
              </button>
              <button type="button" className="mini-action mini-action-danger" onClick={requestBulkDelete} disabled={!selectedLibraryKeys.size}>
                <Trash2 size={13} /> Delete selected
              </button>
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
          {visibleItems.length ? (
            <div className={cx('library-results', mode === 'movie' ? 'library-movie-results' : 'library-file-results')}>
              {visibleItems.map((item) => (
                mode === 'movie' ? (
                  <LibraryMovieCard
                    key={item.path}
                    item={item}
                    expanded={expandedPath === item.path}
                    details={tmdbCache[getTmdbCacheKey(item)]}
                    collection={(() => {
                      const details = tmdbCache[getTmdbCacheKey(item)];
                      return details?.collection?.id ? collectionCache[details.collection.id] || details.collection : {};
                    })()}
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
                    onCollectionFilter={applyCollectionFilter}
                    onEditCollection={(collection) => setCollectionEditor({ collection, item })}
                    onResetCollection={resetCollection}
                    onListFilter={applyListFilter}
                    onEditLists={() => setListEditor({ item })}
                    onRemoveFromList={(listId) => removeMovieFromList(listId, item)}
                    onEditPoster={() => setPosterEditor({ item, path: item.path, title: getMovieIdentity(item).title })}
                    onCorrectMetadata={() => setMetadataCorrection(item)}
                    watched={movieHasSystemState(item, userLists, 'watched')}
                    watchlisted={movieHasSystemState(item, userLists, 'watchlist')}
                    onToggleWatched={() => toggleSystemList('watched', item)}
                    onToggleWatchlist={() => toggleSystemList('watchlist', item)}
                    showOwnedBadge={false}
                    selected={selectedLibraryKeys.has(librarySelectionKey(item))}
                    onSelect={(checked) => toggleLibrarySelection(item, checked)}
                  />
                ) : (
                  <LibraryFileRow
                    key={item.path}
                    item={item}
                    expanded={expandedPath === item.path}
                    onToggle={() => setExpandedPath((path) => (path === item.path ? '' : item.path))}
                    onPlay={onPlay}
                    onFindTorrent={onFindTorrent}
                    onRename={() => setRenameTarget(item)}
                    onDelete={() => setDeleteTarget(item)}
                  />
                )
              ))}
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
      {listsManagerOpen && (
        <MyListsManagerModal
          lists={userLists}
          items={items}
          onClose={() => setListsManagerOpen(false)}
          onCreate={createList}
          onRename={renameList}
          onDelete={deleteList}
          onAdd={addMovieToList}
          onRemove={removeMovieFromList}
          onFilter={applyListFilter}
          notify={notify}
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
          resetLabel="Reset to provider metadata"
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


function MyListsManagerModal({ lists, items, onClose, onCreate, onRename, onDelete, onAdd, onRemove, onFilter, notify }) {
  const [selectedId, setSelectedId] = useState(lists[0]?.id || '');
  const [newName, setNewName] = useState('');
  const [renameValue, setRenameValue] = useState('');
  const [search, setSearch] = useState('');
  const [tmdbCandidates, setTmdbCandidates] = useState([]);
  const [tmdbLoading, setTmdbLoading] = useState(false);
  const [selectedMovieKeys, setSelectedMovieKeys] = useState(() => new Set());
  const [copyMovies, setCopyMovies] = useState(null);
  const selectedList = lists.find((list) => list.id === selectedId) || lists[0] || null;
  const listMovieKeys = useMemo(() => new Set((selectedList?.movies || []).map((movie) => movieIdentityKey(movie))), [selectedList]);
  const selectedMovies = useMemo(() => (
    (selectedList?.movies || []).filter((movie) => selectedMovieKeys.has(movieIdentityKey(movie)))
  ), [selectedList, selectedMovieKeys]);
  const allListMoviesSelected = Boolean((selectedList?.movies || []).length) && (selectedList?.movies || []).every((movie) => selectedMovieKeys.has(movieIdentityKey(movie)));
  const candidates = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q || !selectedList) return [];
    return items
      .filter((item) => {
        const payload = moviePayload(item);
        if (listMovieKeys.has(movieIdentityKey(payload))) return false;
        return `${payload.title} ${payload.year} ${item.filename || ''}`.toLowerCase().includes(q);
      })
      .slice(0, 12);
  }, [items, listMovieKeys, search, selectedList]);

  useEffect(() => {
    if (!selectedList && lists[0]) setSelectedId(lists[0].id);
    if (selectedList) setRenameValue(selectedList.name || '');
  }, [lists, selectedList]);

  useEffect(() => {
    setSelectedMovieKeys(new Set());
  }, [selectedId]);

  async function submitCreate(event) {
    event.preventDefault();
    const created = await onCreate(newName);
    setNewName('');
    setSelectedId(created.id);
  }

  async function submitRename(event) {
    event.preventDefault();
    if (!selectedList || !renameValue.trim()) return;
    await onRename(selectedList.id, renameValue.trim());
  }

  async function deleteSelected() {
    if (!selectedList) return;
    await onDelete(selectedList.id);
    const remaining = lists.filter((list) => list.id !== selectedList.id);
    setSelectedId(remaining[0]?.id || '');
  }

  function toggleListMovie(movie, checked) {
    const key = movieIdentityKey(movie);
    setSelectedMovieKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function selectAllListMovies() {
    setSelectedMovieKeys(new Set((selectedList?.movies || []).map((movie) => movieIdentityKey(movie))));
  }

  function clearListSelection() {
    setSelectedMovieKeys(new Set());
  }

  async function removeSelectedMovies() {
    if (!selectedList || !selectedMovies.length) return;
    for (const movie of selectedMovies) {
      await onRemove(selectedList.id, movie);
    }
    setSelectedMovieKeys(new Set());
  }

  async function searchTmdbWatchlist() {
    if (selectedList?.system_type !== 'watchlist' || !search.trim()) return;
    setTmdbLoading(true);
    try {
      const data = await fetchJson(`/api/tmdb/search?q=${encodeURIComponent(search.trim())}&page=1&include_adult=false`);
      setTmdbCandidates((data.results || []).slice(0, 12));
    } finally {
      setTmdbLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="torrent-dialog curation-dialog" role="dialog" aria-modal="true" aria-label="My lists" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">Library lists</p>
            <h2>My Lists</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close my lists">
            <X size={18} />
          </button>
        </div>
        <div className="lists-manager-grid">
          <aside className="lists-manager-sidebar">
            <form onSubmit={submitCreate} className="list-create-inline">
              <input value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="New list name..." />
              <button type="submit" className="mini-action" disabled={!newName.trim()}><CirclePlus size={13} /> Create</button>
            </form>
            {lists.length ? lists.map((list) => (
              <button type="button" key={list.id} className={cx('list-manager-item', selectedList?.id === list.id && 'list-manager-item-active')} onClick={() => setSelectedId(list.id)}>
                <span>{list.name}</span>
                <small>{formatCount((list.movies || []).length)} movies</small>
              </button>
            )) : <small>No lists yet.</small>}
          </aside>
          <div className="lists-manager-detail">
            {selectedList ? (
              <>
                <form className="list-rename-row" onSubmit={submitRename}>
                  <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} disabled={Boolean(selectedList?.system_type)} />
                  {selectedList?.system_type ? <span className="chip chip-muted">System list</span> : <button type="submit" className="mini-action">Rename</button>}
                  <button type="button" className="mini-action" onClick={() => onFilter(selectedList)}>Filter</button>
                  {!selectedList?.system_type && (
                    <button type="button" className="mini-action mini-action-danger" onClick={deleteSelected}>
                      <Trash2 size={13} /> Delete
                    </button>
                  )}
                </form>
                <label className="library-search curation-search">
                  <Search size={17} />
                  <input value={search} onChange={(event) => { setSearch(event.target.value); setTmdbCandidates([]); }} placeholder={selectedList.system_type === 'watchlist' ? 'Search local movies or TMDB...' : 'Search local movies to add...'} />
                </label>
                {selectedList.system_type === 'watchlist' && search.trim() && (
                  <button type="button" className="mini-action" onClick={searchTmdbWatchlist} disabled={tmdbLoading}>
                    {tmdbLoading ? <Loader2 size={13} className="spin" /> : <Search size={13} />} Search TMDB to add to Watchlist
                  </button>
                )}
                {candidates.length > 0 && (
                  <div className="curation-candidates">
                    {candidates.map((item) => {
                      const payload = moviePayload(item);
                      return (
                        <button type="button" key={item.path} onClick={() => { onAdd(selectedList.id, item); setSearch(''); }}>
                          <CirclePlus size={15} />
                          {payload.title}{payload.year ? ` (${payload.year})` : ''}
                        </button>
                      );
                    })}
                  </div>
                )}
                {tmdbCandidates.length > 0 && selectedList.system_type === 'watchlist' && (
                  <div className="curation-candidates">
                    {tmdbCandidates.map((movie) => {
                      const owned = items.some((item) => movieIdentityKey(moviePayload(item)) === movieIdentityKey(movie));
                      return (
                        <button type="button" key={movie.tmdb_id || movieIdentityKey(movie)} onClick={() => { onAdd(selectedList.id, movie); setSearch(''); setTmdbCandidates([]); }}>
                          <CirclePlus size={15} />
                          {movie.title}{movie.year ? ` (${movie.year})` : ''} · {owned ? 'Owned' : 'Not owned'}
                        </button>
                      );
                    })}
                  </div>
                )}
                {(selectedList.movies || []).length > 0 && (
                  <div className="bulk-selection-bar list-bulk-selection">
                    <SelectionCheckbox
                      className="list-select-all"
                      checked={allListMoviesSelected}
                      onChange={(checked) => { if (checked) selectAllListMovies(); else clearListSelection(); }}
                      label={`Select all movies in ${selectedList.name}`}
                    />
                    <span>{selectedMovies.length ? `${formatCount(selectedMovies.length)} selected` : 'Select list movies'}</span>
                    <button type="button" className="mini-action" onClick={selectAllListMovies}>Select all</button>
                    <button type="button" className="mini-action" onClick={clearListSelection} disabled={!selectedMovies.length}>Clear</button>
                    <button type="button" className="mini-action mini-action-danger" onClick={removeSelectedMovies} disabled={!selectedMovies.length}>
                      <Trash2 size={13} /> Remove selected
                    </button>
                    <button type="button" className="mini-action" onClick={() => setCopyMovies(selectedMovies)} disabled={!selectedMovies.length}>
                      <Copy size={13} /> Copy selected to...
                    </button>
                  </div>
                )}
                <div className="curation-list">
                  {(selectedList.movies || []).map((movie) => (
                    <div className="curation-row" key={movieIdentityKey(movie)}>
                      <SelectionCheckbox
                        className="list-row-checkbox"
                        checked={selectedMovieKeys.has(movieIdentityKey(movie))}
                        onChange={(checked) => toggleListMovie(movie, checked)}
                        label={`Select ${movie.title}`}
                      />
                      <span>{movie.title}{movie.year ? ` (${movie.year})` : ''}</span>
                      <button type="button" className="mini-action mini-action-danger" onClick={() => onRemove(selectedList.id, movie)}>
                        <Trash2 size={13} /> Remove
                      </button>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-state">
                <strong>No list selected.</strong>
                <span>Create a list to start curating movies.</span>
              </div>
            )}
          </div>
        </div>
        {copyMovies && (
          <ExportCopyDialog
            movies={copyMovies}
            onClose={() => setCopyMovies(null)}
            notify={notify}
          />
        )}
      </section>
    </div>
  );
}


function LibraryFileRow({ item, expanded, onToggle, onPlay, onFindTorrent, onRename, onDelete }) {
  const identity = getMovieIdentity(item);
  const canonical = item.canonical_metadata || {};
  const lowQuality = isLowQuality(item.resolution);
  const movieForSearch = { title: identity.title, year: identity.year, imdb_id: item.imdb_id || '', tmdb_id: item.tmdb_id || '' };
  return (
    <article className={cx('library-file-row', expanded && 'library-file-row-expanded')}>
      <div className="file-row-main">
        <div className="file-row-title">
          <strong>{item.filename}</strong>
          <span>{identity.title}{identity.year ? ` (${identity.year})` : ''}</span>
        </div>
        <div className="file-row-path" title={item.path}>{item.path}</div>
        <div className="file-row-meta">
          <span className={cx('chip', lowQuality && 'chip-warning')}>{item.resolution || 'Unknown'}</span>
          <span className="chip chip-muted">{item.rip_source || 'Unknown source'}</span>
          <span className="chip chip-muted">{item.size_human || '?'}</span>
          {item.library_root && <span className="chip chip-muted">{rootLabel(item.library_root)}</span>}
          <span className={cx('chip', item.metadata_accepted ? 'status-owned' : 'status-missing')}>{item.metadata_accepted ? 'Catalog matched' : 'Needs identity'}</span>
          {(canonical.genres?.length ? canonical.genres : item.plex_genres || []).slice(0, 2).map((genre) => <span className="chip chip-muted" key={genre}>{genre}</span>)}
          {getLocaleTag(item) && <span className="chip chip-muted">{getLocaleTag(item)}</span>}
        </div>
      </div>
      <div className="file-row-actions">
        <button type="button" className="btn btn-primary btn-green" onClick={() => onPlay(item.path)}>
          <Play size={15} /> Play
        </button>
        <button type="button" className={cx('btn', lowQuality ? 'btn-upgrade' : 'btn-secondary')} onClick={() => onFindTorrent(movieForSearch, lowQuality)}>
          <Wand2 size={15} /> {lowQuality ? 'Find upgrade' : 'Find sources'}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onRename}>
          <Clapperboard size={15} /> Rename
        </button>
        <button type="button" className="btn btn-danger" onClick={onDelete}>
          <Trash2 size={15} /> Delete
        </button>
        <button type="button" className="btn btn-secondary" onClick={onToggle}>
          <Info size={15} /> {expanded ? 'Less' : 'Details'}
        </button>
      </div>
      {expanded && (
        <div className="file-expanded-panel">
          <div><span>Full path</span><strong>{item.path}</strong></div>
          <div><span>Catalog title</span><strong>{canonical.title || identity.title || 'Needs identity'}</strong></div>
          <div><span>Catalog year</span><strong>{canonical.year || identity.year || 'Unknown'}</strong></div>
          <div><span>Metadata source</span><strong>{item.metadata_source || canonical.source || 'None'}</strong></div>
          <div><span>TMDB / IMDb</span><strong>{canonical.tmdb_id || item.tmdb_id || '—'} / {canonical.imdb_id || item.imdb_id || '—'}</strong></div>
          <div><span>Plex evidence</span><strong>{item.plex_matched ? `${item.plex_title || 'Matched'}${item.plex_year ? ` (${item.plex_year})` : ''}` : 'Not available'}</strong></div>
          <div><span>Locale</span><strong>{getLocaleTag(item) || 'Unknown'}</strong></div>
          <div><span>Size</span><strong>{item.size_human || '?'} ({formatCount(item.size)} bytes)</strong></div>
          <div><span>Genres</span><strong>{(canonical.genres?.length ? canonical.genres : item.plex_genres || []).join(', ') || 'None'}</strong></div>
        </div>
      )}
    </article>
  );
}
