import {
  AlertTriangle, Bot, CheckCircle2, CirclePlus, Compass, Film, Loader2,
  MonitorPlay, Play, Radio, RefreshCcw, Search, Star, Wand2, X
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from '../../api/client.js';
import { CATALOG_GENERATION_CHANGED_EVENT, fetchOwnershipChecks } from '../../api/library.js';
import { fetchCanonicalMovieDetails, markMovieDetailsCacheStale, movieCollectionUrl, movieDetailsCacheKey } from '../../api/movieDetails.js';
import { addMoviePayloadsToList, announceCurationChanged, CURATION_GENERATION_CHANGED_EVENT, fetchCurationJson, fetchUserListsCached } from '../../api/curation.js';
import { previewSourceReview } from '../../api/sourceReview.js';
import ListEditorModal from '../../components/ListEditorModal.jsx';
import DiscoverResultGrid from '../../components/DiscoverResultGrid.jsx';
import Pagination from '../../components/Pagination.jsx';
import Rating from '../../components/Rating.jsx';
import PosterEditorModal from '../../components/PosterEditorModal.jsx';
import PersonSearchCard from '../../components/PersonSearchCard.jsx';
import { MovieLanguageToggle, useTransientMovieLanguage } from '../../components/MovieLanguageToggle.jsx';
import SelectionCheckbox from '../../components/SelectionCheckbox.jsx';
import SourceReviewDialog from '../../components/SourceReviewDialog.jsx';
import {
  DiscoverMovieCard, MovieExpandedCuration, MovieExpandedDetails, MovieExpandedFacts, PosterEditButton, PosterStateControls
} from '../../components/SharedMovieCards.jsx';
import TorrentActions from '../../components/TorrentActions.jsx';
import { UnifiedMovieCard } from '../../components/movie-card/MovieCard.jsx';
import { cx, formatCount, movieKey } from '../../utils/appUtils.js';
import {
  buildOwnershipMap, discoverMoviePayload, filterEnrichedIndexerResults,
  listsForDiscoverMovie, ownedMovieFor, sortTorrentVariants
} from '../../discoverUtils.js';
import { isLowQuality, movieIdentityKey, moviePayload, resolutionRank } from '../../utils/libraryUtils.js';
import { formatVoteCount } from '../../utils/moviePresentation.js';

const discoverLists = [
  { value: 'trending_week', label: 'Trending Week' },
  { value: 'catalog', label: 'TMDB Catalog' },
  { value: 'trending_today', label: 'Trending Today' },
  { value: 'now_playing', label: 'Now Playing' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'popular', label: 'Popular' },
  { value: 'top_rated', label: 'Top Rated' },
  { value: 'best_all_time', label: 'Best All Time' }
];

const discoverGenres = [
  { value: '', label: 'All genres' },
  { value: '28', label: 'Action' },
  { value: '12', label: 'Adventure' },
  { value: '16', label: 'Animation' },
  { value: '35', label: 'Comedy' },
  { value: '80', label: 'Crime' },
  { value: '99', label: 'Documentary' },
  { value: '18', label: 'Drama' },
  { value: '10751', label: 'Family' },
  { value: '14', label: 'Fantasy' },
  { value: '27', label: 'Horror' },
  { value: '9648', label: 'Mystery' },
  { value: '10749', label: 'Romance' },
  { value: '878', label: 'Sci-Fi' },
  { value: '53', label: 'Thriller' },
  { value: '10752', label: 'War' }
];

export default function DiscoverWorkspace({
  followed,
  notify,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onOpenTrailer,
  onManualTorrentSearch,
  onFollow,
  tmdbQuery,
  setTmdbQuery,
  browseQuery,
  setBrowseQuery,
  searchRequest,
  personRequest,
  activeTab,
  setActiveTab
}) {
  const [discoverList, setDiscoverList] = useState('trending_week');
  const [discoverGenre, setDiscoverGenre] = useState('');
  const [discoverMinVotes, setDiscoverMinVotes] = useState('0');
  const [discoverYearFrom, setDiscoverYearFrom] = useState('');
  const [discoverYearTo, setDiscoverYearTo] = useState('');
  const [discoverMinRating, setDiscoverMinRating] = useState('0');
  const [discoverSort, setDiscoverSort] = useState('auto');
  const [discoverOwnershipFilter, setDiscoverOwnershipFilter] = useState('all');
  const [discoverSearchKind, setDiscoverSearchKind] = useState('movies');
  const [discoverPeopleResults, setDiscoverPeopleResults] = useState([]);
  const [discoverPeopleLoading, setDiscoverPeopleLoading] = useState(false);
  const [discoverPeopleError, setDiscoverPeopleError] = useState('');
  const [discoverResults, setDiscoverResults] = useState([]);
  const [discoverPage, setDiscoverPage] = useState(1);
  const [discoverTotalPages, setDiscoverTotalPages] = useState(1);
  const [discoverTotalResults, setDiscoverTotalResults] = useState(0);
  const [discoverMode, setDiscoverMode] = useState('discover');
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverError, setDiscoverError] = useState('');
  const [browseRows, setBrowseRows] = useState([]);
  const [browseHiddenCount, setBrowseHiddenCount] = useState(0);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseError, setBrowseError] = useState('');
  const [browseHasLoaded, setBrowseHasLoaded] = useState(false);
  const [browseMode, setBrowseMode] = useState('idle');
  const [browseResolution, setBrowseResolution] = useState('all');
  const [browseIndexer, setBrowseIndexer] = useState('all');
  const [browseIndexerOptions, setBrowseIndexerOptions] = useState([]);
  const [browseIndexerLoading, setBrowseIndexerLoading] = useState(false);
  const [browseSort, setBrowseSort] = useState('seeders-desc');
  const [selectedVariants, setSelectedVariants] = useState({});
  const [pickPrompt, setPickPrompt] = useState('');
  const [pickResults, setPickResults] = useState([]);
  const [pickModel, setPickModel] = useState('');
  const [pickLoading, setPickLoading] = useState(false);
  const [pickError, setPickError] = useState('');
  const [ownership, setOwnership] = useState({});
  const [detailsCache, setDetailsCache] = useState({});
  const [collectionCache, setCollectionCache] = useState({});
  const [userLists, setUserLists] = useState([]);
  const [expandedMovieKey, setExpandedMovieKey] = useState('');
  const [listEditorTarget, setListEditorTarget] = useState(null);
  const [discoverContext, setDiscoverContext] = useState(null);
  const [discoverContextSourceResults, setDiscoverContextSourceResults] = useState([]);
  const [discoverHistory, setDiscoverHistory] = useState([]);
  const [pickContext, setPickContext] = useState(null);
  const [pickHistory, setPickHistory] = useState([]);
  const [posterEditor, setPosterEditor] = useState(null);
  const [selectedDiscoverKeys, setSelectedDiscoverKeys] = useState(() => new Set());
  const [sourceReview, setSourceReview] = useState(null);
  const [isNavigatingDiscoverContext, setIsNavigatingDiscoverContext] = useState(() => Boolean(personRequest?.requestId));
  const discoverRequestSeq = useRef(0);
  const handledPersonRequestRef = useRef(0);

  useEffect(() => {
    const clearDetailCaches = () => {
      setDetailsCache(markMovieDetailsCacheStale);
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

  function updateOwnedPoster(path, posterUrl) {
    setOwnership((state) => Object.fromEntries(
      Object.entries(state).map(([key, value]) => [
        key,
        value?.path === path ? { ...value, poster_url: posterUrl } : value
      ])
    ));
  }

  async function checkOwnership(movies) {
    const payload = (movies || []).filter((movie) => movie?.title);
    if (!payload.length) return;
    try {
      const ownershipResults = await fetchOwnershipChecks(payload);
      setOwnership((state) => ({ ...state, ...buildOwnershipMap(ownershipResults) }));
    } catch {
      // Ownership is best effort for online discovery.
    }
  }

  const loadUserLists = useCallback(async (options = {}) => {
    try {
      const data = await fetchUserListsCached({ force: Boolean(options?.force) });
      setUserLists(data.lists || []);
    } catch (error) {
      notify(`Lists unavailable: ${error.message}`, 'error');
    }
  }, [notify]);

  useEffect(() => {
    loadUserLists();
    window.addEventListener('cp-curation-changed', loadUserLists);
    return () => window.removeEventListener('cp-curation-changed', loadUserLists);
  }, [loadUserLists]);

  function discoverBaseLabel() {
    if (discoverMode === 'search' && tmdbQuery.trim()) return `Search: ${tmdbQuery.trim()}`;
    const listLabel = discoverLists.find((item) => item.value === discoverList)?.label || 'Discover Home';
    const genreLabel = discoverGenres.find((item) => item.value === discoverGenre)?.label || '';
    return genreLabel && discoverGenre ? `${listLabel} / ${genreLabel}` : listLabel;
  }

  function hasAdvancedDiscoverCriteria() {
    return Boolean(
      discoverGenre
      || discoverMinVotes !== '0'
      || discoverYearFrom.trim()
      || discoverYearTo.trim()
      || discoverMinRating !== '0'
      || discoverSort !== 'auto'
    );
  }

  function discoverResultContextLabel() {
    if (discoverContext) {
      return `${discoverContext.label}${hasAdvancedDiscoverCriteria() ? ' / refined' : ''}`;
    }
    if (discoverMode === 'search' && tmdbQuery.trim()) {
      return `Search: ${tmdbQuery.trim()}${hasAdvancedDiscoverCriteria() ? ' / refined' : ''}`;
    }
    return discoverLists.find((item) => item.value === discoverList)?.label || 'TMDB Catalog';
  }

  function isRefinedTitleSearch() {
    return discoverMode === 'search' && Boolean(tmdbQuery.trim()) && hasAdvancedDiscoverCriteria();
  }

  function appendDiscoverCriteria(params) {
    if (discoverGenre) params.set('genre', discoverGenre);
    if (discoverMinVotes !== '0') params.set('min_votes', discoverMinVotes);
    if (discoverYearFrom.trim()) params.set('year_from', discoverYearFrom.trim());
    if (discoverYearTo.trim()) params.set('year_to', discoverYearTo.trim());
    if (discoverMinRating !== '0') params.set('min_rating', discoverMinRating);
    if (discoverSort !== 'auto') params.set('sort', discoverSort);
    return params;
  }

  function discoverCriteriaKey() {
    return [discoverGenre, discoverMinVotes, discoverYearFrom, discoverYearTo, discoverMinRating, discoverSort].join('|');
  }

  function buildDiscoverUrl(query, page) {
    const params = new URLSearchParams({ page: String(page), page_size: '40' });
    if (query) {
      params.set('q', query);
      params.set('include_adult', 'false');
    } else {
      params.set('list', discoverList);
    }
    appendDiscoverCriteria(params);
    return `/api/tmdb/${query ? 'search' : 'discover'}?${params.toString()}`;
  }

  function setDiscoverCriterion(setter, value, defaultValue) {
    if (!discoverContext && (value !== defaultValue || hasAdvancedDiscoverCriteria())) {
      setDiscoverList('catalog');
    }
    setter(value);
  }

  function resetDiscoverCriteria() {
    setDiscoverGenre('');
    setDiscoverMinVotes('0');
    setDiscoverYearFrom('');
    setDiscoverYearTo('');
    setDiscoverMinRating('0');
    setDiscoverSort('auto');
    if (!discoverContext) setDiscoverList('trending_week');
  }

  function selectDiscoverList(value) {
    setTmdbQuery('');
    setDiscoverContext(null);
    setDiscoverContextSourceResults([]);
    setDiscoverList(value);
    if (value !== 'catalog') {
      setDiscoverGenre('');
      setDiscoverMinVotes('0');
      setDiscoverYearFrom('');
      setDiscoverYearTo('');
      setDiscoverMinRating('0');
      setDiscoverSort('auto');
    }
  }

  function currentDiscoverSnapshot() {
    return {
      label: discoverContext?.label || discoverBaseLabel(),
      context: discoverContext,
      results: discoverResults,
      contextSourceResults: discoverContextSourceResults,
      page: discoverPage,
      totalPages: discoverTotalPages,
      totalResults: discoverTotalResults,
      mode: discoverMode,
      query: tmdbQuery,
      searchKind: discoverSearchKind,
      peopleResults: discoverPeopleResults,
      peopleError: discoverPeopleError,
      list: discoverList,
      genre: discoverGenre,
      minVotes: discoverMinVotes,
      yearFrom: discoverYearFrom,
      yearTo: discoverYearTo,
      minRating: discoverMinRating,
      sort: discoverSort
    };
  }

  function currentPickSnapshot() {
    return {
      label: pickContext?.label || (pickResults.length ? 'AI Picks' : 'Pick My Movie'),
      context: pickContext,
      results: pickResults,
      model: pickModel
    };
  }

  function restoreDiscoverSnapshot(snapshot, nextHistory) {
    setDiscoverResults(snapshot.results || []);
    setDiscoverPage(snapshot.page || 1);
    setDiscoverTotalPages(snapshot.totalPages || 1);
    setDiscoverTotalResults(snapshot.totalResults || 0);
    setDiscoverMode(snapshot.mode || 'discover');
    setDiscoverContext(snapshot.context || null);
    setDiscoverContextSourceResults(snapshot.contextSourceResults || []);
    setTmdbQuery(snapshot.query || '');
    setDiscoverSearchKind(snapshot.searchKind || 'movies');
    setDiscoverPeopleResults(snapshot.peopleResults || []);
    setDiscoverPeopleError(snapshot.peopleError || '');
    setDiscoverList(snapshot.list || 'trending_week');
    setDiscoverGenre(snapshot.genre || '');
    setDiscoverMinVotes(snapshot.minVotes || '0');
    setDiscoverYearFrom(snapshot.yearFrom || '');
    setDiscoverYearTo(snapshot.yearTo || '');
    setDiscoverMinRating(snapshot.minRating || '0');
    setDiscoverSort(snapshot.sort || 'auto');
    setDiscoverError('');
    setDiscoverHistory(nextHistory || []);
    setExpandedMovieKey('');
    checkOwnership(snapshot.results || []);
  }

  function restorePickSnapshot(snapshot, nextHistory) {
    setPickResults(snapshot.results || []);
    setPickModel(snapshot.model || pickModel);
    setPickContext(snapshot.context || null);
    setPickError('');
    setPickHistory(nextHistory || []);
    setExpandedMovieKey('');
    checkOwnership(snapshot.results || []);
  }

  function resetDiscoverPath() {
    if (discoverHistory.length) {
      restoreDiscoverSnapshot(discoverHistory[0], []);
      return;
    }
    setDiscoverContext(null);
    setExpandedMovieKey('');
    loadDiscover({ append: false, search: discoverMode === 'search' ? tmdbQuery : '' });
  }

  function resetPickPath() {
    if (pickHistory.length) {
      restorePickSnapshot(pickHistory[0], []);
    }
  }

  async function fetchListMovies(list) {
    const movies = list?.movies || [];
    const enriched = [];
    for (let index = 0; index < movies.length; index += 6) {
      const batch = await Promise.all(movies.slice(index, index + 6).map(async (movie) => {
        if (movie?.genres?.length || movie?.plot) return movie;
        try {
          const query = `${movie.title || ''} ${movie.year || ''}`.trim();
          if (!query) return movie;
          const data = await fetchJson(`/api/tmdb/search?q=${encodeURIComponent(query)}&page=1&include_adult=false`);
          const match = (data.results || []).find((candidate) => (
            movie.tmdb_id && String(candidate.tmdb_id) === String(movie.tmdb_id)
          )) || (data.results || []).find((candidate) => (
            movie.year && String(candidate.year || '') === String(movie.year)
          )) || (data.results || [])[0];
          return match ? { ...match, path: movie.path || match.path || '' } : movie;
        } catch {
          return movie;
        }
      }));
      enriched.push(...batch);
    }
    return enriched;
  }

  async function loadDiscover({ append = false, search = '', page } = {}) {
    const query = String(search || '').trim();
    const nextPage = page || (append ? discoverPage + 1 : 1);
    const requestSeq = discoverRequestSeq.current + 1;
    discoverRequestSeq.current = requestSeq;
    setDiscoverLoading(true);
    setDiscoverError('');
    if (!append) {
      setDiscoverResults([]);
      setDiscoverContext(null);
      setDiscoverContextSourceResults([]);
      setDiscoverHistory([]);
      setExpandedMovieKey('');
    }
    try {
      const data = await fetchJson(buildDiscoverUrl(query, nextPage));
      if (requestSeq !== discoverRequestSeq.current) return;
      const nextResults = data.results || [];
      setDiscoverResults((state) => (append ? [...state, ...nextResults] : nextResults));
      setDiscoverPage(data.page || nextPage);
      setDiscoverTotalPages(data.total_pages || 1);
      setDiscoverTotalResults(data.total_results || nextResults.length);
      setDiscoverMode(query ? 'search' : 'discover');
      checkOwnership(nextResults);
    } catch (error) {
      if (requestSeq !== discoverRequestSeq.current) return;
      setDiscoverError(error.message);
      if (!append) setDiscoverResults([]);
    } finally {
      if (requestSeq === discoverRequestSeq.current) {
        setDiscoverLoading(false);
      }
    }
  }

  async function searchDiscoverPeople() {
    const query = tmdbQuery.trim();
    if (!query) return;
    setDiscoverPeopleLoading(true);
    setDiscoverPeopleError('');
    setDiscoverPeopleResults([]);
    setDiscoverContext(null);
    setDiscoverContextSourceResults([]);
    setDiscoverHistory([]);
    setExpandedMovieKey('');
    setDiscoverMode('people');
    try {
      const data = await fetchJson(`/api/tmdb/people/search?q=${encodeURIComponent(query)}&page=1&include_adult=false`);
      setDiscoverPeopleResults(data.results || []);
    } catch (error) {
      setDiscoverPeopleError(error.message);
    } finally {
      setDiscoverPeopleLoading(false);
    }
  }

  async function loadContextPage(target, context, { append = false } = {}) {
    if (!context?.baseUrl) return;
    const isPick = target === 'pick';
    const currentPage = isPick ? (context.page || 1) : discoverPage;
    const nextPage = append ? currentPage + 1 : 1;
    const [baseUrl, existingQuery = ''] = context.baseUrl.split('?');
    const params = new URLSearchParams(existingQuery);
    params.set('page', String(nextPage));
    if (!isPick) appendDiscoverCriteria(params);
    const url = `${baseUrl}?${params.toString()}`;
    if (isPick) {
      setPickLoading(true);
      setPickError('');
    } else {
      setDiscoverLoading(true);
      setDiscoverError('');
    }
    try {
      const data = await fetchJson(url);
      const nextResults = data.results || [];
      const nextContext = {
        ...context,
        page: data.page || nextPage,
        totalPages: data.total_pages || 1,
        criteriaKey: isPick ? context.criteriaKey || '' : discoverCriteriaKey()
      };
      if (isPick) {
        setPickResults((state) => (append ? [...state, ...nextResults] : nextResults));
        setPickContext(nextContext);
      } else {
        setDiscoverResults((state) => (append ? [...state, ...nextResults] : nextResults));
        setDiscoverPage(data.page || nextPage);
        setDiscoverTotalPages(data.total_pages || 1);
        setDiscoverTotalResults(data.total_results || nextResults.length);
        setDiscoverContext(nextContext);
        setDiscoverContextSourceResults([]);
        setDiscoverMode(context.type || 'related');
      }
      checkOwnership(nextResults);
    } catch (error) {
      if (isPick) setPickError(error.message);
      else setDiscoverError(error.message);
    } finally {
      if (isPick) setPickLoading(false);
      else setDiscoverLoading(false);
    }
  }

  function filterDiscoverContextResults(results) {
    if (!hasAdvancedDiscoverCriteria()) return [...(results || [])];
    const genreLabel = discoverGenres.find((item) => item.value === discoverGenre)?.label || '';
    const filtered = (results || []).filter((movie) => {
      const year = String(movie.release_date || movie.year || '').slice(0, 4);
      if (genreLabel && !(movie.genres || []).includes(genreLabel)) return false;
      if (discoverMinVotes !== '0' && Number(movie.tmdb_vote_count || 0) < Number(discoverMinVotes)) return false;
      if (discoverYearFrom.trim() && (!year || year < discoverYearFrom.trim())) return false;
      if (discoverYearTo.trim() && (!year || year > discoverYearTo.trim())) return false;
      if (discoverMinRating !== '0' && Number(movie.tmdb_rating || 0) < Number(discoverMinRating)) return false;
      return true;
    });
    if (discoverSort === 'popularity.desc') return [...filtered].sort((a, b) => Number(b.popularity || 0) - Number(a.popularity || 0));
    if (discoverSort === 'vote_average.desc') return [...filtered].sort((a, b) => Number(b.tmdb_rating || 0) - Number(a.tmdb_rating || 0));
    if (discoverSort === 'vote_count.desc') return [...filtered].sort((a, b) => Number(b.tmdb_vote_count || 0) - Number(a.tmdb_vote_count || 0));
    if (discoverSort === 'primary_release_date.desc') return [...filtered].sort((a, b) => String(b.release_date || '').localeCompare(String(a.release_date || '')));
    if (discoverSort === 'title.asc') return [...filtered].sort((a, b) => String(a.title || '').localeCompare(String(b.title || '')));
    return filtered;
  }

  function buildPersonMoviesContext(movie, role, person, labelPrefix = '') {
    const personId = person?.id || person?.tmdb_id;
    if (!personId) return;
    const labelRole = role === 'director' ? 'Director' : 'Actor';
    const prefix = labelPrefix || movie?.title || 'Movie';
    return {
      type: 'person',
      label: `${prefix} > ${labelRole}: ${person.name}`,
      baseUrl: `/api/tmdb/person_movies?person_id=${encodeURIComponent(personId)}&role=${encodeURIComponent(role)}`,
      emptyText: `No TMDB movies found for ${person.name}.`
    };
  }

  async function openSearchedPersonFilmography(person, role) {
    const context = buildPersonMoviesContext({}, role, person);
    if (!context) return;
    context.label = role === 'director' ? 'Directed films' : 'Acting credits';
    const selectionSnapshot = {
      ...currentDiscoverSnapshot(),
      label: person.name || 'TMDB person',
      mode: 'people',
      searchKind: 'people',
      peopleResults: discoverPeopleResults,
      peopleError: discoverPeopleError
    };
    setDiscoverSearchKind('movies');
    setTmdbQuery('');
    setDiscoverPeopleResults([]);
    setDiscoverPeopleError('');
    setDiscoverHistory((history) => [...history, selectionSnapshot]);
    setExpandedMovieKey('');
    setIsNavigatingDiscoverContext(true);
    try {
      await loadContextPage('explore', context, { append: false });
    } finally {
      setIsNavigatingDiscoverContext(false);
    }
  }

  useEffect(() => {
    if (!personRequest?.requestId || handledPersonRequestRef.current === personRequest.requestId) return;
    const context = buildPersonMoviesContext(
      personRequest.movie,
      personRequest.role,
      personRequest.person,
      personRequest.source || 'Library'
    );
    if (!context) {
      setIsNavigatingDiscoverContext(false);
      return;
    }
    handledPersonRequestRef.current = personRequest.requestId;
    setIsNavigatingDiscoverContext(true);
    setActiveTab('explore');
    setDiscoverHistory((history) => [...history, currentDiscoverSnapshot()]);
    setExpandedMovieKey('');
    loadContextPage('explore', context, { append: false }).finally(() => setIsNavigatingDiscoverContext(false));
  }, [personRequest]);

  async function browsePerson(target, movie, role, person) {
    const context = buildPersonMoviesContext(movie, role, person);
    if (!context) return;
    const isPick = target === 'pick';
    const snapshot = isPick ? currentPickSnapshot() : currentDiscoverSnapshot();
    if (isPick) setPickHistory((history) => [...history, snapshot]);
    else setDiscoverHistory((history) => [...history, snapshot]);
    setExpandedMovieKey('');
    await loadContextPage(target, context, { append: false });
  }

  async function browseCollection(target, movie, collection) {
    if (!collection?.id) return;
    const isPick = target === 'pick';
    if (isPick) {
      setPickLoading(true);
      setPickError('');
    } else {
      setDiscoverLoading(true);
      setDiscoverError('');
    }
    try {
      const collectionData = await fetchCurationJson(`/api/tmdb/collection?collection_id=${encodeURIComponent(collection.id)}`);
      setCollectionCache((state) => ({ ...state, [collection.id]: collectionData }));
      const results = collectionData.parts || [];
      const context = {
        type: 'collection',
        label: `${movie.title || 'Movie'} > ${collectionData.name || collection.name}`,
        emptyText: `No TMDB collection movies found for ${collectionData.name || collection.name}.`,
        criteriaKey: discoverCriteriaKey()
      };
      const snapshot = isPick ? currentPickSnapshot() : currentDiscoverSnapshot();
      if (isPick) {
        setPickHistory((history) => [...history, snapshot]);
        setPickResults(results);
        setPickContext(context);
      } else {
        const filteredResults = filterDiscoverContextResults(results);
        setDiscoverHistory((history) => [...history, snapshot]);
        setDiscoverResults(filteredResults);
        setDiscoverContextSourceResults(results);
        setDiscoverPage(1);
        setDiscoverTotalPages(1);
        setDiscoverTotalResults(filteredResults.length);
        setDiscoverMode('collection');
        setDiscoverContext(context);
      }
      setExpandedMovieKey('');
      checkOwnership(results);
    } catch (error) {
      if (isPick) setPickError(error.message);
      else setDiscoverError(error.message);
    } finally {
      if (isPick) setPickLoading(false);
      else setDiscoverLoading(false);
    }
  }

  async function browseList(target, movie, list) {
    const fullList = userLists.find((item) => item.id === list?.id) || list;
    if (!fullList?.id) return;
    const isPick = target === 'pick';
    if (isPick) {
      setPickLoading(true);
      setPickError('');
    } else {
      setDiscoverLoading(true);
      setDiscoverError('');
    }
    try {
      const results = await fetchListMovies(fullList);
      const context = {
        type: 'list',
        label: `${movie.title || 'Movie'} > List: ${fullList.name}`,
        emptyText: `No movies found in ${fullList.name}.`,
        criteriaKey: discoverCriteriaKey()
      };
      const snapshot = isPick ? currentPickSnapshot() : currentDiscoverSnapshot();
      if (isPick) {
        setPickHistory((history) => [...history, snapshot]);
        setPickResults(results);
        setPickContext(context);
      } else {
        const filteredResults = filterDiscoverContextResults(results);
        setDiscoverHistory((history) => [...history, snapshot]);
        setDiscoverResults(filteredResults);
        setDiscoverContextSourceResults(results);
        setDiscoverPage(1);
        setDiscoverTotalPages(1);
        setDiscoverTotalResults(filteredResults.length);
        setDiscoverMode('list');
        setDiscoverContext(context);
      }
      setExpandedMovieKey('');
      checkOwnership(results);
    } catch (error) {
      if (isPick) setPickError(error.message);
      else setDiscoverError(error.message);
    } finally {
      if (isPick) setPickLoading(false);
      else setDiscoverLoading(false);
    }
  }

  async function openTrailer(movie) {
    const owned = ownedMovieFor(movie, ownership);
    if (!movieDetailsCacheKey(movie, owned)) {
      onOpenTrailer(movie, '');
      return;
    }
    try {
      const details = await loadDiscoverDetails(movie, owned);
      onOpenTrailer(movie, details.trailer_url || '');
    } catch {
      onOpenTrailer(movie, '');
    }
  }

  async function loadDiscoverDetails(movie, owned = null) {
    const cacheKey = movieDetailsCacheKey(movie, owned);
    if (!cacheKey) return null;
    let details = detailsCache[cacheKey];
    if (!details || details.stale) {
      setDetailsCache((state) => ({ ...state, [cacheKey]: { loading: true, cast: [], directors: [], collection: {}, trailer_url: '' } }));
      try {
        details = await fetchCanonicalMovieDetails(movie, owned);
        setDetailsCache((state) => ({ ...state, [cacheKey]: details }));
      } catch (error) {
        details = { error: error.message, cast: [], directors: [], collection: {}, trailer_url: '' };
        setDetailsCache((state) => ({ ...state, [cacheKey]: details }));
      }
    }
    const collectionUrl = movieCollectionUrl(details);
    if (collectionUrl && !collectionCache[details.collection.id]) {
      fetchCurationJson(collectionUrl)
        .then((collectionData) => setCollectionCache((state) => ({ ...state, [details.collection.id]: collectionData })))
        .catch(() => {});
    }
    return details;
  }

  function toggleMovieDetails(movie, owned = null) {
    const key = movieKey(movie);
    const nextKey = expandedMovieKey === key ? '' : key;
    setExpandedMovieKey(nextKey);
    if (nextKey) loadDiscoverDetails(movie, owned);
  }

  async function createDiscoverList(name) {
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

  async function addDiscoverMovieToList(listId, movie) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}/movies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify('Movie added to list');
  }

  async function addDiscoverMoviesToList(listId, movies) {
    const payloads = (movies || []).map((movie) => moviePayload(movie));
    await addMoviePayloadsToList(listId, payloads);
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify(`${formatCount(payloads.length)} movie${payloads.length === 1 ? '' : 's'} added to list`);
    setSelectedDiscoverKeys(new Set());
  }

  async function removeDiscoverMovieFromList(listId, movie) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}/movies`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify('Movie removed from list');
  }

  async function toggleDiscoverSystemList(systemType, movie, owned) {
    const payload = discoverMoviePayload(movie, owned);
    const currentLists = listsForDiscoverMovie(movie, userLists, owned);
    const active = currentLists.some((list) => list.system_type === systemType || list.id === systemType);
    await fetchCurationJson(`/api/user/system-lists/${encodeURIComponent(systemType)}/toggle`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie: payload, active: !active })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify(`${movie.title} ${active ? 'removed from' : 'added to'} ${systemType === 'watched' ? 'Watched' : 'Watchlist'}`);
  }

  async function fetchIndexerMetadata(row) {
    try {
      const params = new URLSearchParams({ title: row.parsed_title || row.title || '' });
      if (row.parsed_year) params.set('year', row.parsed_year);
      const metadata = await fetchJson(`/api/metadata?${params.toString()}`);
      return { ...row, metadata };
    } catch {
      return { ...row, metadata: {} };
    }
  }

  const loadBrowseIndexers = useCallback(async () => {
    setBrowseIndexerLoading(true);
    try {
      const data = await fetchJson('/api/explore/indexers');
      setBrowseIndexerOptions(data.indexers || []);
    } catch (error) {
      setBrowseError((current) => current || `Indexer list unavailable: ${error.message}`);
    } finally {
      setBrowseIndexerLoading(false);
    }
  }, []);

  async function loadBrowse({ query = browseQuery } = {}) {
    const search = String(query || '').trim();
    setBrowseLoading(true);
    setBrowseError('');
    setBrowseHasLoaded(true);
    setBrowseMode(search ? 'search' : 'latest');
    setBrowseHiddenCount(0);
    setBrowseRows([]);
    setSelectedVariants({});
    setSelectedDiscoverKeys(new Set());
    try {
      const params = new URLSearchParams();
      if (search) {
        params.set('q', search);
      } else {
        params.set('latest', '1');
      }
      if (browseIndexer !== 'all') {
        params.set('indexer_id', browseIndexer);
      }
      const url = `/api/explore/browse?${params.toString()}`;
      const data = await fetchJson(url);
      if (data.indexers?.length) setBrowseIndexerOptions(data.indexers);
      const rows = data.results || [];
      const baseRows = filterEnrichedIndexerResults(rows);
      setBrowseRows(baseRows);
      setBrowseHiddenCount(baseRows.length);
      checkOwnership(baseRows);
      const enriched = [];
      for (let index = 0; index < rows.length; index += 8) {
        const batch = await Promise.all(rows.slice(index, index + 8).map(fetchIndexerMetadata));
        enriched.push(...batch);
        const filtered = filterEnrichedIndexerResults([...enriched, ...rows.slice(index + 8)]);
        setBrowseRows(filtered);
        setBrowseHiddenCount(filtered.filter((row) => !row.metadata || !row.metadata.tmdb_id).length);
      }
      const filtered = filterEnrichedIndexerResults(enriched);
      setBrowseRows(filtered);
      setBrowseHiddenCount(filtered.filter((row) => !row.metadata || !row.metadata.tmdb_id).length);
      checkOwnership(filtered);
    } catch (error) {
      setBrowseError(error.message);
    } finally {
      setBrowseLoading(false);
    }
  }

  async function askPickMyMovie(event) {
    event.preventDefault();
    const prompt = pickPrompt.trim();
    if (!prompt) {
      setPickError('Describe what you want to watch first.');
      return;
    }
    setPickLoading(true);
    setPickError('');
    setPickResults([]);
    setPickContext(null);
    setPickHistory([]);
    setExpandedMovieKey('');
    try {
      const data = await fetchJson('/api/ollama/recommend', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt })
      });
      const results = data.results || [];
      setPickResults(results);
      setPickModel(data.model || '');
      checkOwnership(results);
      notify(`${formatCount(results.length)} recommendations returned`, 'success');
    } catch (error) {
      setPickError(error.message);
    } finally {
      setPickLoading(false);
    }
  }

  useEffect(() => {
    if (isNavigatingDiscoverContext || discoverContext) return;
    loadDiscover({ append: false, search: tmdbQuery });
  }, [discoverList, discoverGenre, discoverMinVotes, discoverYearFrom, discoverYearTo, discoverMinRating, discoverSort, isNavigatingDiscoverContext]);

  useEffect(() => {
    if (!discoverContext) return;
    const criteriaKey = discoverCriteriaKey();
    if (discoverContext.criteriaKey === criteriaKey) return;
    if (discoverContext.type === 'person' && discoverContext.baseUrl) {
      loadContextPage('explore', discoverContext, { append: false });
      return;
    }
    if (discoverContextSourceResults.length) {
      const filteredResults = filterDiscoverContextResults(discoverContextSourceResults);
      setDiscoverResults(filteredResults);
      setDiscoverPage(1);
      setDiscoverTotalPages(1);
      setDiscoverTotalResults(filteredResults.length);
      setDiscoverContext((context) => context ? { ...context, criteriaKey } : context);
    }
  }, [discoverContext, discoverContextSourceResults, discoverGenre, discoverMinVotes, discoverYearFrom, discoverYearTo, discoverMinRating, discoverSort]);

  useEffect(() => {
    if (!searchRequest) return;
    if (activeTab === 'browse') {
      loadBrowse({ query: browseQuery });
    } else if (activeTab === 'explore') {
      if (discoverSearchKind === 'people') searchDiscoverPeople();
      else loadDiscover({ append: false, search: tmdbQuery, page: 1 });
    }
  }, [searchRequest]);

  useEffect(() => {
    if (activeTab === 'browse') {
      setBrowseError('');
      if (!browseIndexerOptions.length && !browseIndexerLoading) {
        loadBrowseIndexers();
      }
    }
  }, [activeTab, browseIndexerOptions.length, browseIndexerLoading, loadBrowseIndexers]);

  useEffect(() => {
    if (browseIndexer === 'all' || !browseIndexerOptions.length) return;
    if (!browseIndexerOptions.some((indexer) => String(indexer.id) === String(browseIndexer))) {
      setBrowseIndexer('all');
    }
  }, [browseIndexer, browseIndexerOptions]);

  const selectedBrowseIndexerName = useMemo(() => {
    if (browseIndexer === 'all') return 'All indexers';
    return browseIndexerOptions.find((indexer) => String(indexer.id) === String(browseIndexer))?.name || 'Selected indexer';
  }, [browseIndexer, browseIndexerOptions]);

  const filteredBrowseRows = useMemo(() => {
    const rows = browseRows.filter((movie) => {
      if (browseResolution !== 'all' && !movie.variants.some((variant) => (variant.resolution || 'Unknown') === browseResolution)) return false;
      if (browseIndexer !== 'all' && selectedBrowseIndexerName !== 'Selected indexer' && !movie.variants.some((variant) => variant.indexer === selectedBrowseIndexerName)) return false;
      return true;
    });
    const sorted = [...rows];
    sorted.sort((a, b) => {
      if (browseSort === 'title-asc') return String(a.title || '').localeCompare(String(b.title || ''));
      if (browseSort === 'year-desc') return String(b.year || '').localeCompare(String(a.year || ''));
      if (browseSort === 'quality-desc') return resolutionRank(b.best_resolution) - resolutionRank(a.best_resolution) || b.best_seeders - a.best_seeders;
      return b.best_seeders - a.best_seeders;
    });
    return sorted;
  }, [browseRows, browseResolution, browseIndexer, browseSort, selectedBrowseIndexerName]);

  const filteredDiscoverResults = useMemo(() => {
    if (discoverOwnershipFilter === 'all') return discoverResults;
    return discoverResults.filter((movie) => {
      const isOwned = Boolean(ownedMovieFor(movie, ownership));
      return discoverOwnershipFilter === 'owned' ? isOwned : !isOwned;
    });
  }, [discoverOwnershipFilter, discoverResults, ownership]);

  const activeDiscoverSelectionMovies = activeTab === 'pick'
    ? pickResults
    : activeTab === 'explore'
      ? filteredDiscoverResults
      : activeTab === 'browse' ? filteredBrowseRows : [];
  const selectedDiscoverMovies = useMemo(() => (
    activeDiscoverSelectionMovies
      .map((movie) => discoverMoviePayload(movie, ownedMovieFor(movie, ownership)))
      .filter((movie) => selectedDiscoverKeys.has(movieIdentityKey(movie)))
  ), [activeDiscoverSelectionMovies, ownership, selectedDiscoverKeys]);
  const allDiscoverResultsSelected = activeDiscoverSelectionMovies.length > 0 && activeDiscoverSelectionMovies.every((movie) => {
    const payload = discoverMoviePayload(movie, ownedMovieFor(movie, ownership));
    return selectedDiscoverKeys.has(movieIdentityKey(payload));
  });

  function toggleDiscoverSelection(movie, owned, checked) {
    const key = movieIdentityKey(discoverMoviePayload(movie, owned));
    setSelectedDiscoverKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function selectAllDiscoverResults() {
    setSelectedDiscoverKeys(new Set(activeDiscoverSelectionMovies.map((movie) => movieIdentityKey(discoverMoviePayload(movie, ownedMovieFor(movie, ownership))))));
  }

  function clearDiscoverSelection() {
    setSelectedDiscoverKeys(new Set());
  }

  async function openSelectedSourceReview() {
    if (!selectedDiscoverMovies.length) {
      notify?.('Select movies before finding sources.', 'neutral');
      return;
    }
    setSourceReview({ loading: true, rows: [], error: '', title: 'Find sources' });
    try {
      const data = await previewSourceReview(selectedDiscoverMovies.map((movie) => ({
        tmdb_id: movie.tmdb_id || '',
        imdb_id: movie.imdb_id || '',
        title: movie.title,
        year: movie.year,
        poster_url: movie.poster_url || '',
        path: movie.path || ''
      })));
      setSourceReview({
        loading: false,
        rows: data.rows || [],
        blocked: data.blocked || [],
        defaults: data.defaults || {},
        error: '',
        title: 'Find sources'
      });
    } catch (previewError) {
      setSourceReview((current) => ({ ...current, loading: false, error: previewError.message }));
    }
  }

  const tabs = [
    { id: 'explore', label: 'Explore Movies', icon: Compass },
    { id: 'browse', label: 'Browse Indexers', icon: Radio },
    { id: 'pick', label: 'Pick My Movie', icon: Bot }
  ];

  function backDiscoverPath() {
    if (!discoverHistory.length) return;
    const previous = discoverHistory[discoverHistory.length - 1];
    restoreDiscoverSnapshot(previous, discoverHistory.slice(0, -1));
  }

  function jumpDiscoverPath(index) {
    const snapshot = discoverHistory[index];
    if (!snapshot) return;
    restoreDiscoverSnapshot(snapshot, discoverHistory.slice(0, index));
  }

  function backPickPath() {
    if (!pickHistory.length) return;
    const previous = pickHistory[pickHistory.length - 1];
    restorePickSnapshot(previous, pickHistory.slice(0, -1));
  }

  function jumpPickPath(index) {
    const snapshot = pickHistory[index];
    if (!snapshot) return;
    restorePickSnapshot(snapshot, pickHistory.slice(0, index));
  }

  function runDiscoverSearch(event) {
    event.preventDefault();
    if (activeTab === 'browse') {
      loadBrowse({ query: browseQuery });
      return;
    }
    if (discoverSearchKind === 'people') {
      searchDiscoverPeople();
      return;
    }
    setDiscoverPeopleResults([]);
    setDiscoverPeopleError('');
    loadDiscover({ append: false, search: tmdbQuery, page: 1 });
  }

  return (
    <section className="discover-workspace">
      <header className="library-header discover-header">
        <div>
          <p className="screen-kicker">Online discovery</p>
          <h2>Discover</h2>
          <p>TMDB discovery, live indexer availability, and local Ollama recommendations with archive-aware actions.</p>
        </div>
        <div className="settings-summary">
          <strong>{formatCount(discoverResults.length + browseRows.length + pickResults.length)}</strong>
          <span>loaded titles</span>
        </div>
      </header>

      <div className="discover-tabs" role="tablist" aria-label="Discover tools">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              type="button"
              key={tab.id}
              className={cx(activeTab === tab.id && 'discover-tab-active')}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon size={16} /> {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab !== 'pick' && (
        <form className="discover-search-panel" onSubmit={runDiscoverSearch}>
          <label className="library-search discover-main-search">
            <Search size={17} />
            <input
              value={activeTab === 'browse' ? browseQuery : tmdbQuery}
              onChange={(event) => (activeTab === 'browse' ? setBrowseQuery : setTmdbQuery)(event.target.value)}
              placeholder={activeTab === 'browse' ? 'Search movie indexers...' : discoverSearchKind === 'people' ? 'Search TMDB people...' : 'Search TMDB movies...'}
              aria-label={activeTab === 'browse' ? 'Search movie indexers' : discoverSearchKind === 'people' ? 'Search TMDB people' : 'Search TMDB movies'}
            />
          </label>
          {activeTab === 'explore' && (
            <select
              value={discoverSearchKind}
              onChange={(event) => {
                setDiscoverSearchKind(event.target.value);
                setDiscoverPeopleResults([]);
                setDiscoverPeopleError('');
              }}
              aria-label="TMDB search type"
            >
              <option value="movies">Movies</option>
              <option value="people">People</option>
            </select>
          )}
          <button type="submit" className="btn btn-primary discover-search-submit" disabled={activeTab === 'browse' ? browseLoading : discoverLoading || discoverPeopleLoading}>
            {(activeTab === 'browse' ? browseLoading : discoverLoading || discoverPeopleLoading) ? <Loader2 size={15} className="spin" /> : <Search size={15} />} Search
          </button>
        </form>
      )}

      {activeTab === 'explore' && (
        <section className="discover-panel">
          <DiscoverPathBar
            history={discoverHistory}
            currentLabel={discoverContext?.label}
            resetLabel="Discover Home"
            onBack={backDiscoverPath}
            onReset={resetDiscoverPath}
            onCrumb={jumpDiscoverPath}
          />
          {discoverSearchKind !== 'people' && <div className="discover-toolbar">
            <select value={discoverList} onChange={(event) => selectDiscoverList(event.target.value)}>
              {discoverLists.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <select aria-label="Library ownership" value={discoverOwnershipFilter} onChange={(event) => setDiscoverOwnershipFilter(event.target.value)}>
              <option value="all">All movies</option>
              <option value="owned">Owned</option>
              <option value="unowned">Not owned</option>
            </select>
            <select value={discoverGenre} onChange={(event) => setDiscoverCriterion(setDiscoverGenre, event.target.value, '')}>
              {discoverGenres.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <select value={discoverMinVotes} onChange={(event) => setDiscoverCriterion(setDiscoverMinVotes, event.target.value, '0')}>
              <option value="0">Any votes</option>
              <option value="500">500+ votes</option>
              <option value="1000">1,000+ votes</option>
              <option value="5000">5,000+ votes</option>
              <option value="10000">10,000+ votes</option>
            </select>
            <input className="library-mini-input" value={discoverYearFrom} onChange={(event) => setDiscoverCriterion(setDiscoverYearFrom, event.target.value, '')} placeholder="Year from" inputMode="numeric" />
            <input className="library-mini-input" value={discoverYearTo} onChange={(event) => setDiscoverCriterion(setDiscoverYearTo, event.target.value, '')} placeholder="Year to" inputMode="numeric" />
            <select value={discoverMinRating} onChange={(event) => setDiscoverCriterion(setDiscoverMinRating, event.target.value, '0')}>
              <option value="0">Any rating</option>
              <option value="6">6+</option>
              <option value="7">7+</option>
              <option value="8">8+</option>
              <option value="8.5">8.5+</option>
            </select>
            <select value={discoverSort} onChange={(event) => setDiscoverCriterion(setDiscoverSort, event.target.value, 'auto')}>
              <option value="auto">Default order</option>
              <option value="popularity.desc">Popularity</option>
              <option value="vote_average.desc">Rating</option>
              <option value="vote_count.desc">Most voted</option>
              <option value="primary_release_date.desc">Release date</option>
              <option value="title.asc">Title A-Z</option>
            </select>
            <button type="button" className="btn btn-secondary" onClick={() => loadDiscover({ append: false, search: discoverMode === 'search' ? tmdbQuery : '' })} disabled={discoverLoading}>
              <RefreshCcw size={15} /> Refresh
            </button>
            {hasAdvancedDiscoverCriteria() && (
              <button type="button" className="btn btn-secondary" onClick={resetDiscoverCriteria} disabled={discoverLoading}>
                <X size={15} /> Reset filters
              </button>
            )}
            {discoverMode === 'search' && (
              <button type="button" className="btn btn-secondary" onClick={() => { setTmdbQuery(''); loadDiscover({ append: false, search: '', page: 1 }); }}>
                <X size={15} /> Clear search
              </button>
            )}
            <span className="discover-count">
              <span className="discover-filter-label">{discoverResultContextLabel()}</span>
              {discoverOwnershipFilter !== 'all'
                ? `${formatCount(filteredDiscoverResults.length)} of ${formatCount(discoverResults.length)} titles on this TMDB page`
                : isRefinedTitleSearch()
                ? `${formatCount(discoverResults.length)} matches on this TMDB search page`
                : `${formatCount(discoverTotalResults || discoverResults.length)} titles`}
            </span>
          </div>}
          {discoverSearchKind !== 'people' && filteredDiscoverResults.length > 0 && (
            <div className="bulk-selection-bar discover-bulk-selection">
              <SelectionCheckbox
                className="discover-selection-master"
                checked={allDiscoverResultsSelected}
                onChange={(checked) => { if (checked) selectAllDiscoverResults(); else clearDiscoverSelection(); }}
                label="Select all discover results"
              />
              <span>{selectedDiscoverMovies.length ? `${formatCount(selectedDiscoverMovies.length)} selected` : 'Select movies'}</span>
              <button type="button" className="mini-action" onClick={selectAllDiscoverResults}>Select all results</button>
              <button type="button" className="mini-action" onClick={clearDiscoverSelection} disabled={!selectedDiscoverMovies.length}>Clear</button>
              <button type="button" className="mini-action" onClick={() => setListEditorTarget({ bulkItems: selectedDiscoverMovies })} disabled={!selectedDiscoverMovies.length}>
                <CirclePlus size={13} /> Add to list
              </button>
              <button type="button" className="mini-action mini-action-source" onClick={openSelectedSourceReview} disabled={!selectedDiscoverMovies.length}>
                <Search size={13} /> Find sources
              </button>
            </div>
          )}

          {discoverSearchKind === 'people' ? (
            <PeopleSearchResults
              loading={discoverPeopleLoading}
              error={discoverPeopleError}
              people={discoverPeopleResults}
              onOpenFilmography={openSearchedPersonFilmography}
            />
          ) : <DiscoverResultGrid
            error={discoverError}
            loading={discoverLoading && !discoverResults.length}
            emptyText={discoverOwnershipFilter === 'owned'
              ? 'No owned movies match this TMDB result page.'
              : discoverOwnershipFilter === 'unowned'
                ? 'No movies missing from the library match this TMDB result page.'
                : discoverContext?.emptyText || 'No TMDB movies match this view.'}
            emptyHint={discoverContext?.type === 'collection'
              ? hasAdvancedDiscoverCriteria()
                ? 'No collection movies match the active Discover filters.'
                : 'TMDB returned no collection members for this collection.'
              : undefined}
          >
            {filteredDiscoverResults.map((movie, index) => {
              const owned = ownedMovieFor(movie, ownership);
              const details = detailsCache[movieDetailsCacheKey(movie, owned)] || null;
              const collection = details?.collection?.id ? collectionCache[details.collection.id] || details.collection : {};
              return (
                <DiscoverMovieCard
                  key={`${movie.tmdb_id || movie.title}-${movie.year}-${index}`}
                  movie={movie}
                  owned={owned}
                  followed={followed.some((item) => movieKey(item) === movieKey(movie))}
                  expanded={expandedMovieKey === movieKey(movie)}
                  details={details}
                  collection={collection}
                  itemLists={listsForDiscoverMovie(movie, userLists, owned)}
                  watched={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watched')}
                  watchlisted={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watchlist')}
                  onToggleWatched={owned ? () => toggleDiscoverSystemList('watched', movie, owned) : undefined}
                  onToggleWatchlist={() => toggleDiscoverSystemList('watchlist', movie, owned)}
                  selected={selectedDiscoverKeys.has(movieIdentityKey(discoverMoviePayload(movie, owned)))}
                  onSelect={(checked) => toggleDiscoverSelection(movie, owned, checked)}
                  onPlay={onPlay}
                  onStream={onStream}
                  streamingAvailable={streamingAvailable}
                  streamingLabel={streamingLabel}
                  onFindTorrent={onFindTorrent}
                  onFollow={onFollow}
                  onTrailer={openTrailer}
                  onToggleDetails={() => toggleMovieDetails(movie, owned)}
                  onPersonBrowse={(role, person) => browsePerson('explore', movie, role, person)}
                  onCollectionBrowse={(collectionItem) => browseCollection('explore', movie, collectionItem)}
                  onListBrowse={(list) => browseList('explore', movie, list)}
                  onEditLists={() => setListEditorTarget(discoverMoviePayload(movie, owned))}
                  onRemoveFromList={(listId) => removeDiscoverMovieFromList(listId, discoverMoviePayload(movie, owned))}
                  onEditPoster={owned ? () => setPosterEditor({ path: owned.path, title: movie.title }) : undefined}
                />
              );
            })}
          </DiscoverResultGrid>}

          {discoverSearchKind !== 'people' && discoverResults.length > 0 && !discoverContext?.baseUrl && (
            <Pagination
              page={discoverPage}
              totalPages={discoverTotalPages}
              total={discoverTotalResults || discoverResults.length}
              pageStart={(discoverPage - 1) * 40}
              pageEnd={(discoverPage - 1) * 40 + discoverResults.length}
              summary={isRefinedTitleSearch()
                ? `${formatCount(filteredDiscoverResults.length)} matching result${filteredDiscoverResults.length === 1 ? '' : 's'} on this TMDB search page`
                : ''}
              onPageChange={(nextPage) => loadDiscover({ append: false, search: discoverMode === 'search' ? tmdbQuery : '', page: nextPage })}
            />
          )}

          {discoverSearchKind !== 'people' && discoverResults.length > 0 && discoverContext?.baseUrl && discoverPage < discoverTotalPages && discoverPage < 10 && (
            <button type="button" className="load-more-button" onClick={() => loadContextPage('explore', discoverContext, { append: true })} disabled={discoverLoading}>
              {discoverLoading ? <Loader2 size={15} className="spin" /> : <CirclePlus size={15} />} Load more
            </button>
          )}
        </section>
      )}

      {activeTab === 'browse' && (
        <section className="discover-panel">
          <div className="discover-toolbar">
            <select value={browseResolution} onChange={(event) => setBrowseResolution(event.target.value)}>
              <option value="all">All qualities</option>
              <option value="4K">4K</option>
              <option value="1080p">1080p</option>
              <option value="720p">720p</option>
              <option value="480p">480p</option>
              <option value="Unknown">Unknown</option>
            </select>
            <select value={browseIndexer} onChange={(event) => setBrowseIndexer(event.target.value)}>
              <option value="all">All indexers</option>
              {browseIndexerOptions.map((indexer) => <option key={indexer.id} value={indexer.id}>{indexer.name}</option>)}
            </select>
            <select value={browseSort} onChange={(event) => setBrowseSort(event.target.value)}>
              <option value="seeders-desc">Seeders most</option>
              <option value="quality-desc">Quality best</option>
              <option value="year-desc">Year newest</option>
              <option value="title-asc">Title A-Z</option>
            </select>
            <button type="button" className="btn btn-secondary" onClick={() => loadBrowse({ query: browseMode === 'latest' ? '' : browseQuery })} disabled={browseLoading || (!browseQuery.trim() && browseMode !== 'latest' && !browseHasLoaded)}>
              {browseLoading ? <Loader2 size={15} className="spin" /> : <RefreshCcw size={15} />} Refresh
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => loadBrowse({ query: '' })} disabled={browseLoading}>
              {browseLoading && browseMode === 'latest' ? <Loader2 size={15} className="spin" /> : <Radio size={15} />} Load latest
            </button>
            <span className="discover-count">
              <span className="discover-filter-label">Indexer source</span>
              {browseMode === 'search' && browseQuery.trim() ? `Search: ${browseQuery.trim()} / ${selectedBrowseIndexerName} - ` : browseMode === 'latest' ? `Latest / ${selectedBrowseIndexerName} - ` : ''}
              {formatCount(filteredBrowseRows.length)} movies
              {browseHiddenCount > 0 ? `, ${formatCount(browseHiddenCount)} without TMDB details` : ''}
              {browseIndexerLoading ? ', loading sources' : ''}
            </span>
          </div>

          {filteredBrowseRows.length > 0 && (
            <div className="bulk-selection-bar discover-bulk-selection">
              <SelectionCheckbox
                className="discover-selection-master"
                checked={allDiscoverResultsSelected}
                onChange={(checked) => { if (checked) selectAllDiscoverResults(); else clearDiscoverSelection(); }}
                label="Select all browse indexer results"
              />
              <span>{selectedDiscoverMovies.length ? `${formatCount(selectedDiscoverMovies.length)} selected` : 'Select movies'}</span>
              <button type="button" className="mini-action" onClick={selectAllDiscoverResults}>Select all results</button>
              <button type="button" className="mini-action" onClick={clearDiscoverSelection} disabled={!selectedDiscoverMovies.length}>Clear</button>
              <button type="button" className="mini-action" onClick={() => setListEditorTarget({ bulkItems: selectedDiscoverMovies })} disabled={!selectedDiscoverMovies.length}>
                <CirclePlus size={13} /> Add to list
              </button>
              <button type="button" className="mini-action mini-action-source" onClick={openSelectedSourceReview} disabled={!selectedDiscoverMovies.length}>
                <Search size={13} /> Find sources
              </button>
            </div>
          )}

          {!browseHasLoaded && !browseLoading ? (
            <div className="empty-state discover-empty">
              <strong>Search indexers by movie title.</strong>
              <span>Choose an indexer source, use the top search for a targeted search, or click Load latest for a broad Prowlarr browse that may take longer.</span>
            </div>
          ) : (
            <DiscoverResultGrid
              error={browseError}
              loading={browseLoading && !browseRows.length}
              emptyText={browseMode === 'latest' ? `Latest feed for ${selectedBrowseIndexerName} timed out or returned no movies. Try a title search or switch source.` : `No ${selectedBrowseIndexerName} movies found for this search. Switch to All indexers to search every source.`}
              className="discover-indexer-grid"
            >
              {filteredBrowseRows.map((movie) => {
                const selectedIndex = selectedVariants[movie.parsed_title] || 0;
                const owned = ownedMovieFor(movie, ownership);
                const details = detailsCache[movieDetailsCacheKey(movie, owned)] || null;
                const collection = details?.collection?.id ? collectionCache[details.collection.id] || details.collection : {};
                return (
                  <IndexerMovieCard
                    key={`${movie.parsed_title}-${movie.parsed_year}`}
                    movie={movie}
                    selectedIndex={selectedIndex}
                    owned={owned}
                    expanded={expandedMovieKey === movieKey(movie)}
                    details={details}
                    collection={collection}
                    itemLists={listsForDiscoverMovie(movie, userLists, owned)}
                    watched={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watched')}
                    watchlisted={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watchlist')}
                    onToggleWatched={owned ? () => toggleDiscoverSystemList('watched', movie, owned) : undefined}
                    onToggleWatchlist={() => toggleDiscoverSystemList('watchlist', movie, owned)}
                    selected={selectedDiscoverKeys.has(movieIdentityKey(discoverMoviePayload(movie, owned)))}
                    onSelect={(checked) => toggleDiscoverSelection(movie, owned, checked)}
                    notify={notify}
                    onVariantSelect={(index) => setSelectedVariants((state) => ({ ...state, [movie.parsed_title]: index }))}
                    onPlay={onPlay}
                    onStream={onStream}
                    streamingAvailable={streamingAvailable}
                    streamingLabel={streamingLabel}
                    onFindTorrent={onFindTorrent}
                    onTrailer={openTrailer}
                    onToggleDetails={() => toggleMovieDetails(movie, owned)}
                    onEditLists={() => setListEditorTarget(discoverMoviePayload(movie, owned))}
                    onRemoveFromList={(listId) => removeDiscoverMovieFromList(listId, discoverMoviePayload(movie, owned))}
                    onEditPoster={owned ? () => setPosterEditor({ path: owned.path, title: movie.title }) : undefined}
                  />
                );
              })}
            </DiscoverResultGrid>
          )}
        </section>
      )}

      {activeTab === 'pick' && (
        <section className="discover-panel pick-panel-react">
          <form className="pick-prompt-panel" onSubmit={askPickMyMovie}>
            <div>
              <p className="screen-kicker">Local AI curator</p>
              <h3>Describe what you want to watch</h3>
              <p>Use a mood, memory, actor, era, half-remembered plot, or a specific kind of night.</p>
            </div>
            <textarea
              value={pickPrompt}
              onChange={(event) => setPickPrompt(event.target.value)}
              onKeyDown={(event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') askPickMyMovie(event);
              }}
              placeholder="Something funny but a little sad, maybe an indie movie with a warm ending..."
              rows={5}
            />
            <button type="submit" className="btn btn-primary btn-violet" disabled={pickLoading}>
              {pickLoading ? <Loader2 size={15} className="spin" /> : <Bot size={15} />} Ask AI
            </button>
            {pickModel && <p className="discover-inline-status"><CheckCircle2 size={15} /> Results from {pickModel}</p>}
            {pickError && <p className="discover-inline-status discover-inline-error"><AlertTriangle size={15} /> {pickError}</p>}
          </form>

          <DiscoverPathBar
            history={pickHistory}
            currentLabel={pickContext?.label}
            resetLabel="AI Picks"
            onBack={backPickPath}
            onReset={resetPickPath}
            onCrumb={jumpPickPath}
          />
          {pickResults.length > 0 && (
            <div className="bulk-selection-bar discover-bulk-selection">
              <SelectionCheckbox
                className="discover-selection-master"
                checked={allDiscoverResultsSelected}
                onChange={(checked) => { if (checked) selectAllDiscoverResults(); else clearDiscoverSelection(); }}
                label="Select all AI pick results"
              />
              <span>{selectedDiscoverMovies.length ? `${formatCount(selectedDiscoverMovies.length)} selected` : 'Select movies'}</span>
              <button type="button" className="mini-action" onClick={selectAllDiscoverResults}>Select all results</button>
              <button type="button" className="mini-action" onClick={clearDiscoverSelection} disabled={!selectedDiscoverMovies.length}>Clear</button>
              <button type="button" className="mini-action" onClick={() => setListEditorTarget({ bulkItems: selectedDiscoverMovies })} disabled={!selectedDiscoverMovies.length}>
                <CirclePlus size={13} /> Add to list
              </button>
              <button type="button" className="mini-action mini-action-source" onClick={openSelectedSourceReview} disabled={!selectedDiscoverMovies.length}>
                <Search size={13} /> Find sources
              </button>
            </div>
          )}

          <DiscoverResultGrid
            error={pickError && pickResults.length ? pickError : ''}
            loading={pickLoading && !pickResults.length}
            emptyText={pickContext?.emptyText || 'No recommendations yet. Ask Ollama for a mood or memory.'}
          >
            {pickResults.map((movie) => {
              const owned = ownedMovieFor(movie, ownership);
              const details = detailsCache[movieDetailsCacheKey(movie, owned)] || null;
              const collection = details?.collection?.id ? collectionCache[details.collection.id] || details.collection : {};
              return (
                <DiscoverMovieCard
                  key={`${movie.title}-${movie.year}`}
                  movie={movie}
                  reason={movie.reason}
                  owned={owned}
                  followed={followed.some((item) => movieKey(item) === movieKey(movie))}
                  expanded={expandedMovieKey === movieKey(movie)}
                  details={details}
                  collection={collection}
                  itemLists={listsForDiscoverMovie(movie, userLists, owned)}
                  watched={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watched')}
                  watchlisted={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watchlist')}
                  onToggleWatched={owned ? () => toggleDiscoverSystemList('watched', movie, owned) : undefined}
                  onToggleWatchlist={() => toggleDiscoverSystemList('watchlist', movie, owned)}
                  selected={selectedDiscoverKeys.has(movieIdentityKey(discoverMoviePayload(movie, owned)))}
                  onSelect={(checked) => toggleDiscoverSelection(movie, owned, checked)}
                  onPlay={onPlay}
                  onStream={onStream}
                  streamingAvailable={streamingAvailable}
                  streamingLabel={streamingLabel}
                  onFindTorrent={onFindTorrent}
                  onFollow={onFollow}
                  onTrailer={openTrailer}
                  onToggleDetails={() => toggleMovieDetails(movie, owned)}
                  onPersonBrowse={(role, person) => browsePerson('pick', movie, role, person)}
                  onCollectionBrowse={(collectionItem) => browseCollection('pick', movie, collectionItem)}
                  onListBrowse={(list) => browseList('pick', movie, list)}
                  onEditLists={() => setListEditorTarget(discoverMoviePayload(movie, owned))}
                  onRemoveFromList={(listId) => removeDiscoverMovieFromList(listId, discoverMoviePayload(movie, owned))}
                  onEditPoster={owned ? () => setPosterEditor({ path: owned.path, title: movie.title }) : undefined}
                />
              );
            })}
          </DiscoverResultGrid>
          {pickContext?.baseUrl && pickContext.page < pickContext.totalPages && (
            <button type="button" className="load-more-button" onClick={() => loadContextPage('pick', pickContext, { append: true })} disabled={pickLoading}>
              {pickLoading ? <Loader2 size={15} className="spin" /> : <CirclePlus size={15} />} Load more
            </button>
          )}
        </section>
      )}

      {listEditorTarget && (
        <ListEditorModal
          item={listEditorTarget.bulkItems ? null : listEditorTarget}
          bulkItems={listEditorTarget.bulkItems || []}
          items={[]}
          lists={userLists}
          onClose={() => setListEditorTarget(null)}
          onCreate={createDiscoverList}
          onAdd={addDiscoverMovieToList}
          onAddBulk={addDiscoverMoviesToList}
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
      {posterEditor && (
        <PosterEditorModal
          item={posterEditor}
          notify={notify}
          onClose={() => setPosterEditor(null)}
          onSaved={(posterUrl) => updateOwnedPoster(posterEditor.path, posterUrl)}
        />
      )}
    </section>
  );
}

function PeopleSearchResults({ people, loading, error, onOpenFilmography }) {
  if (loading) {
    return <div className="discover-grid person-search-grid"><div className="person-search-card skeleton-card" /></div>;
  }
  if (error) {
    return <div className="empty-state discover-empty"><strong>Could not search people.</strong><span>{error}</span></div>;
  }
  if (!people.length) {
    return <div className="empty-state discover-empty"><strong>Search TMDB people by name.</strong></div>;
  }
  return (
    <div className="discover-grid person-search-grid">
      {people.map((person) => (
        <PersonSearchCard
          key={person.tmdb_id}
          person={person}
          meta={person.known_for_department || 'TMDB person'}
          knownFor={person.known_for}
          roles={['actor', 'director']}
          onOpenFilmography={onOpenFilmography}
        />
      ))}
    </div>
  );
}



function DiscoverPathBar({ history = [], currentLabel, resetLabel, onBack, onReset, onCrumb }) {
  if (!history.length && !currentLabel) return null;
  return (
    <div className="discover-path-bar" aria-label="Discovery path">
      <button type="button" className="mini-action" onClick={onBack} disabled={!history.length}>
        Back
      </button>
      <div className="discover-crumbs">
        {history.map((item, index) => (
          <button type="button" key={`${item.label}-${index}`} onClick={() => onCrumb(index)}>
            {item.label}
          </button>
        ))}
        {currentLabel && <span>{currentLabel}</span>}
      </div>
      <button type="button" className="mini-action" onClick={onReset}>
        <RefreshCcw size={13} /> {resetLabel}
      </button>
    </div>
  );
}


function MovieFactChips({ movie, owned, lowQuality }) {
  return (
    <>
      <div className="chip-row">
        {(movie.genres || []).slice(0, 3).map((genre) => <span className="chip" key={genre}>{genre}</span>)}
        {movie.language && <span className="chip chip-muted">{movie.language}</span>}
        {(movie.country_flag || movie.country) && <span className="chip chip-muted">{movie.country_flag || movie.country}</span>}
      </div>
      <div className="ownership-row">
        {owned ? (
          <span className={cx('status-badge', lowQuality ? 'status-warning' : 'status-owned')}>
            <CheckCircle2 size={14} />
            Owned - {owned.resolution || 'Unknown'} - {owned.size_human || 'local file'}
          </span>
        ) : (
          <span className="status-badge status-missing">
            <Radio size={14} />
            Not in library
          </span>
        )}
      </div>
    </>
  );
}

function IndexerMovieCard({
  movie,
  selectedIndex,
  owned,
  expanded,
  details,
  collection,
  itemLists,
  notify,
  onVariantSelect,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onTrailer,
  onToggleDetails,
  onEditLists,
  onRemoveFromList,
  onEditPoster,
  watched,
  watchlisted,
  onToggleWatched,
  onToggleWatchlist,
  selected,
  onSelect
}) {
  const lowQuality = owned && isLowQuality(owned.resolution);
  const variants = sortTorrentVariants(movie.variants || []);
  const selectedVariant = variants[selectedIndex] || variants[0] || {};
  const baseDisplayMovie = owned?.poster_url ? { ...movie, poster_url: owned.poster_url } : movie;
  const languageView = useTransientMovieLanguage({ movie: baseDisplayMovie, details, expanded });
  const displayMovie = languageView.displayMovie;
  const displayDetails = languageView.displayDetails;
  const displayCollection = languageView.isArabic && displayDetails?.collection?.id
    ? { ...(collection || {}), ...displayDetails.collection }
    : collection;

  return (
    <UnifiedMovieCard
      className={cx('indexer-card', expanded && 'discover-card-expanded')}
      title={displayMovie.title}
      year={displayMovie.year}
      posterUrl={displayMovie.poster_url}
      rating={displayMovie.tmdb_rating}
      voteCount={formatVoteCount(displayMovie.tmdb_vote_count)}
      chips={(displayMovie.genres || []).slice(0, 2)}
      mutedChips={[
        selectedVariant.resolution || movie.best_resolution,
        selectedVariant.indexer,
        owned?.resolution,
        owned?.size_human
      ]}
      statusLabel={owned ? (lowQuality ? 'Upgrade candidate' : '') : `${formatCount(selectedVariant.seeders)} seeders`}
      statusTone={owned ? (lowQuality ? 'warning' : 'neutral') : 'neutral'}
      ownedBadge={Boolean(owned)}
      expanded={expanded}
      onToggle={onToggleDetails}
      showPlayOverlay={Boolean(owned)}
      onPlay={owned?.path ? () => onPlay(owned.path) : undefined}
      cornerControls={(
        <>
          <PosterStateControls
            title={displayMovie.title}
            watched={watched}
            watchlisted={watchlisted}
            onToggleWatched={owned ? onToggleWatched : undefined}
            onToggleWatchlist={onToggleWatchlist}
          />
          <PosterEditButton title={displayMovie.title} onEdit={owned ? onEditPoster : undefined} />
          <SelectionCheckbox
            className="discover-selection-checkbox"
            checked={Boolean(selected)}
            onChange={onSelect}
            label={`Select ${displayMovie.title}`}
          />
        </>
      )}
      expandedBody={expanded ? (
        <MovieExpandedCuration
          movie={displayMovie}
          details={displayDetails}
          collection={displayCollection}
          itemLists={itemLists}
          onEditLists={onEditLists}
          onRemoveFromList={onRemoveFromList}
        />
      ) : null}
      expandedFooter={expanded ? (
        <MovieExpandedDetails
          details={displayDetails}
        />
      ) : null}
    >
      {expanded && (
        <>
          <MovieLanguageToggle {...languageView.toggleProps} />
          <div className="variant-stack" aria-label={`Available releases for ${displayMovie.title}`}>
            {variants.map((variant, index) => (
              <button
                type="button"
                key={`${variant.title}-${index}`}
                className={cx('variant-option', index === selectedIndex && 'variant-option-active')}
                onClick={() => onVariantSelect(index)}
              >
                <strong>{variant.resolution || 'Unknown'}</strong>
                <span><span className="torrent-seeders">Seeders {formatCount(variant.seeders)}</span></span>
                <span>{variant.size_human || '?'}</span>
                <small>{variant.indexer || 'Unknown tracker'}</small>
              </button>
            ))}
          </div>
          <p className="movie-card-plot discover-plot-visible" dir={languageView.isArabic ? 'rtl' : undefined}>
            {displayMovie.summary || displayMovie.plot || 'No plot summary is available yet.'}
          </p>
          <div className="indexer-action-row indexer-action-row-expanded">
            <div className="indexer-selected-meta">
              <strong>{formatCount(selectedVariant.seeders)} seeders</strong>
              <span>{selectedVariant.indexer || 'Unknown tracker'}</span>
              <small>{selectedVariant.size_human || '?'}</small>
            </div>
            <TorrentActions
              variant={selectedVariant}
              movieTitle={movie.title || movie.parsed_title}
              movieYear={movie.year || movie.parsed_year}
              tmdbId={movie.tmdb_id || ''}
              imdbId={movie.imdb_id || ''}
              upgrade={Boolean(lowQuality)}
              notify={notify}
              primary
            />
            {owned ? (
              <button type="button" className="btn btn-primary btn-green" onClick={() => onPlay(owned.path)}>
                <Play size={15} /> Play
              </button>
            ) : streamingAvailable ? (
              <button type="button" className="btn btn-secondary btn-green-outline" onClick={() => onStream(movie)}>
                <MonitorPlay size={15} /> {streamingLabel}
              </button>
            ) : null}
            {lowQuality ? (
              <button type="button" className="btn btn-secondary" onClick={() => onFindTorrent(movie, true)}>
                <Wand2 size={15} /> Find upgrade
              </button>
            ) : (
              <button type="button" className="btn btn-secondary" onClick={() => onFindTorrent(movie)}>
                <Search size={15} /> Find sources
              </button>
            )}
            <button type="button" className="btn btn-secondary" onClick={() => onTrailer(movie)}>
              <Film size={15} /> Trailer
            </button>
          </div>
          <MovieExpandedFacts movie={displayMovie} details={displayDetails} />
        </>
      )}
    </UnifiedMovieCard>
  );
}
