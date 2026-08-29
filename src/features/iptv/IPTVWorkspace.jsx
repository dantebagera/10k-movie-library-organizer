import {
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  CircleAlert,
  Clapperboard,
  Clock3,
  Database,
  ExternalLink,
  Film,
  Heart,
  Home,
  KeyRound,
  Layers3,
  ListPlus,
  ListVideo,
  Loader2,
  Languages,
  Pause,
  Play,
  Radio,
  RefreshCcw,
  Search,
  ServerCog,
  Square,
  Star,
  Tv,
  WandSparkles,
  X
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { iptvApi, iptvImage } from '../../api/iptv.js';
import { MovieExpandedFacts, MovieKeywordRow } from '../../components/SharedMovieCards.jsx';
import { UnifiedMovieCard } from '../../components/movie-card/MovieCard.jsx';
import useCardGridMetrics from '../../hooks/useCardGridMetrics.js';
import { formatCount, movieKey } from '../../utils/appUtils.js';
import { formatVoteCount } from '../../utils/moviePresentation.js';
import IPTVPlayer from './IPTVPlayer.jsx';
import IPTVListsWorkspace, { IPTVListPickerModal } from './IPTVListsWorkspace.jsx';
import {
  createIPTVMovieFilters,
  iptvMovieIdentity,
  iptvMovieQuery,
  iptvMovieQuerySignature,
  normalizeIPTVMovieSearchQuery,
  IPTV_MOVIE_CATEGORIES,
  IPTV_MOVIE_SORTS,
  IPTV_MOVIE_VIEWS
} from './iptvMovieFilters.js';
import { shouldAutoSyncIPTVCatalog } from './iptvSyncPolicy.js';
import './iptv.css';

const TABS = [
  { id: 'home', label: 'Home', icon: Home },
  { id: 'live', label: 'Live TV', icon: Radio },
  { id: 'movie', label: 'Movies', icon: Film },
  { id: 'metadata', label: 'Metadata', icon: Database },
  { id: 'series', label: 'Series', icon: Tv },
  { id: 'favorites', label: 'Favorites', icon: Heart },
  { id: 'lists', label: 'My Lists', icon: ListVideo }
];

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 30 };
const EMPTY_MOVIE_FACETS = { playlists: [], lists: [], categories: [], genres: [], languages: [], countries: [], qualities: [] };
const MOVIE_STATUS_SUMMARY_FIELDS = [
  'matches', 'evaluated', 'remaining', 'grouped_movies', 'distinct_tmdb_movies',
  'stale', 'needs_review', 'automatic_remaining', 'classification_review', 'categories',
  'summary_revision', 'summary_updated_at'
];

function mergeIPTVMovieStatus(current, incoming) {
  if (!incoming || typeof incoming !== 'object') return current;
  if (!current) return incoming;
  const previousRevision = Number(current.summary_revision || 0);
  const incomingRevision = Number(incoming.summary_revision || 0);
  if (incomingRevision >= previousRevision) return incoming;
  const merged = { ...current, ...incoming };
  MOVIE_STATUS_SUMMARY_FIELDS.forEach((field) => {
    if (current[field] !== undefined) merged[field] = current[field];
  });
  return merged;
}

function mediaTitle(item) {
  const name = String(item?.name || item?.title || 'Untitled');
  const year = String(item?.year || '').slice(0, 4);
  return year ? name.replace(new RegExp(`\\s*\\(\\s*${year}\\s*\\)\\s*$`), '').trim() || name : name;
}

function movieChipLabel(value) {
  if (typeof value === 'string' || typeof value === 'number') return String(value).trim();
  if (!value || typeof value !== 'object') return '';
  return movieChipLabel(value.name ?? value.label ?? '');
}

function movieGenreLabels(movie) {
  const values = Array.isArray(movie?.genres)
    ? movie.genres
    : String(movie?.genre || '').split(',');
  return values.map(movieChipLabel).filter(Boolean).slice(0, 3);
}

function movieWithDisplay(movie, display) {
  if (!display) return movie;
  return {
    ...movie,
    ...display,
    name: display.title || movie.name,
    image_url: display.poster_url || movie.image_url,
    backdrop_url: display.backdrop_url || movie.backdrop_url,
    directors: display.directors || movie.directors,
    writers: display.writers || movie.writers,
    cast: display.cast || movie.cast,
    genres: display.genres || movie.genres,
    collection: display.collection || movie.collection
  };
}

function relativeSyncTime(timestamp) {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(timestamp || 0)));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function IPTVWorkspace({ notify, followed = [] }) {
  const [providers, setProviders] = useState([]);
  const [activeProviderId, setActiveProviderId] = useState('');
  const [activeTab, setActiveTab] = useState('home');
  const [favoriteKind, setFavoriteKind] = useState('all');
  const [status, setStatus] = useState(null);
  const [categories, setCategories] = useState({ live: [], movie: [], series: [] });
  const [categoryId, setCategoryId] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [catalog, setCatalog] = useState(EMPTY_PAGE);
  const [recent, setRecent] = useState([]);
  const [loading, setLoading] = useState(true);
  const [movieLoading, setMovieLoading] = useState(false);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [selectedSeason, setSelectedSeason] = useState(1);
  const [selectedLive, setSelectedLive] = useState(null);
  const [epg, setEpg] = useState([]);
  const [playback, setPlayback] = useState(null);
  const [playbackLoading, setPlaybackLoading] = useState(false);
  const [lists, setLists] = useState([]);
  const [selectedListId, setSelectedListId] = useState('');
  const [listCatalog, setListCatalog] = useState(EMPTY_PAGE);
  const [listLoading, setListLoading] = useState(false);
  const [listQuery, setListQuery] = useState('');
  const [listKind, setListKind] = useState('all');
  const [listPage, setListPage] = useState(1);
  const [newListName, setNewListName] = useState('');
  const [renameListName, setRenameListName] = useState('');
  const [listRefresh, setListRefresh] = useState(0);
  const [listPickerItem, setListPickerItem] = useState(null);
  const [listPickerLists, setListPickerLists] = useState([]);
  const [listPickerBusy, setListPickerBusy] = useState(false);
  const [listPickerName, setListPickerName] = useState('');
  const [movieFilters, setMovieFilters] = useState(createIPTVMovieFilters);
  const [movieFacets, setMovieFacets] = useState(EMPTY_MOVIE_FACETS);
  const [movieStatus, setMovieStatus] = useState(null);
  const [enrichmentControl, setEnrichmentControl] = useState(null);
  const [movieRefresh, setMovieRefresh] = useState(0);
  const [metadataSettings, setMetadataSettings] = useState({ tmdb_configured: false, credential_type: 'bearer' });
  const [metadataCredential, setMetadataCredential] = useState('');
  const [metadataCredentialType, setMetadataCredentialType] = useState('bearer');
  const [metadataEditing, setMetadataEditing] = useState(true);
  const [metadataBusy, setMetadataBusy] = useState(false);
  const [metadataView, setMetadataView] = useState('overview');
  const [metadataReview, setMetadataReview] = useState({ items: [], total: 0, page: 1, page_size: 50 });
  const [metadataPage, setMetadataPage] = useState(1);
  const [metadataFilters, setMetadataFilters] = useState({ q: '', category: '', playlist_id: '' });
  const [metadataReviewLoading, setMetadataReviewLoading] = useState(false);
  const [metadataSelection, setMetadataSelection] = useState(() => new Set());
  const [metadataAllFiltered, setMetadataAllFiltered] = useState(false);
  const [proposalJob, setProposalJob] = useState(null);
  const [lastProposalJob, setLastProposalJob] = useState(null);
  const [proposalBusy, setProposalBusy] = useState(false);
  const [classificationPreview, setClassificationPreview] = useState(null);
  const [rebuildJob, setRebuildJob] = useState(null);
  const [lastRebuildJob, setLastRebuildJob] = useState(null);
  const [fusionPreview, setFusionPreview] = useState(null);
  const [ollamaEnabled, setOllamaEnabled] = useState(false);
  const [ollamaUrl, setOllamaUrl] = useState('http://127.0.0.1:11434');
  const [ollamaModel, setOllamaModel] = useState('');
  const [movieLocale, setMovieLocale] = useState('default');
  const [sourceChooser, setSourceChooser] = useState(null);
  const [matchDialog, setMatchDialog] = useState(null);
  const [matchQuery, setMatchQuery] = useState('');
  const [matchYear, setMatchYear] = useState('');
  const [matchResults, setMatchResults] = useState([]);
  const [matchBusy, setMatchBusy] = useState(false);
  const playbackRef = useRef(null);
  const activeProviderRef = useRef('');
  const detailRequestRef = useRef(0);
  const movieRequestRef = useRef({ sequence: 0, signature: '', controller: null });
  const enrichmentControlRef = useRef({ sequence: 0, providerId: '' });
  const categoryIdRef = useRef('');
  const autoSyncRequestedRef = useRef(new Set());
  const metadataLoadedRef = useRef(false);
  const ollamaLoadedRef = useRef(false);

  const browseKind = activeTab === 'favorites' ? favoriteKind : activeTab;
  const isBrowseTab = ['live', 'movie', 'series', 'favorites'].includes(activeTab);
  const adaptiveCardGrid = ['movie', 'series'].includes(browseKind)
    && !(activeTab === 'favorites' && favoriteKind === 'all');
  const {
    gridRef: iptvCardGridRef,
    pageSize: adaptiveCardPageSize
  } = useCardGridMetrics({
    target: activeTab === 'favorites' ? 60 : 30,
    max: 100,
    bias: 'lower'
  });
  const browsePageSize = browseKind === 'live'
    ? 80
    : (adaptiveCardGrid ? adaptiveCardPageSize : (activeTab === 'favorites' ? 60 : 30));
  const activeCardGridRef = adaptiveCardGrid ? iptvCardGridRef : undefined;
  categoryIdRef.current = categoryId;
  activeProviderRef.current = activeProviderId;
  const activeProvider = providers.find((provider) => provider.provider_id === activeProviderId) || null;

  const refreshStatus = useCallback(async () => {
    if (!activeProviderId) return null;
    const data = await iptvApi.status(activeProviderId);
    if (activeProviderRef.current !== activeProviderId) return data;
    setStatus(data);
    setProviders((state) => state.map((provider) => provider.provider_id === activeProviderId ? { ...provider, ...data } : provider));
    return data;
  }, [activeProviderId]);

  useEffect(() => {
    let cancelled = false;
    iptvApi.providers()
      .then((data) => {
        if (cancelled) return;
        const nextProviders = data.providers || [];
        const selected = nextProviders.some((provider) => provider.provider_id === data.last_selected_provider_id)
          ? data.last_selected_provider_id
          : (nextProviders[0]?.provider_id || '');
        setProviders(nextProviders);
        setActiveProviderId(selected);
      })
      .catch((requestError) => !cancelled && setError(requestError.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!activeProviderId) {
      setStatus(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    refreshStatus()
      .then(async (data) => {
        if (cancelled || !data?.configured) return;
        if (shouldAutoSyncIPTVCatalog(data) && !autoSyncRequestedRef.current.has(activeProviderId)) {
          autoSyncRequestedRef.current.add(activeProviderId);
          try {
            const result = await iptvApi.sync(activeProviderId);
            if (!cancelled && result.status) setStatus(result.status);
          } catch (requestError) {
            if (!cancelled) setError(requestError.message);
          }
        }
        if (!cancelled) {
          const result = await iptvApi.recent(activeProviderId);
          if (!cancelled) setRecent(result.items || []);
        }
      })
      .catch((requestError) => !cancelled && setError(requestError.message))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [activeProviderId, refreshStatus]);

  useEffect(() => {
    if (status?.sync?.state !== 'running') return undefined;
    const timer = window.setInterval(() => {
      refreshStatus().catch(() => {});
    }, 1500);
    return () => window.clearInterval(timer);
  }, [status?.sync?.state, refreshStatus]);

  useEffect(() => {
    if (!status?.configured || !['live', 'series'].includes(activeTab)) return undefined;
    let cancelled = false;
    iptvApi.categories(activeProviderId, activeTab)
      .then((result) => {
        if (cancelled) return;
        const nextCategories = result.items || [];
        setCategories((state) => ({ ...state, [activeTab]: nextCategories }));
        const selectedCategory = categoryIdRef.current;
        if (selectedCategory && !nextCategories.some((category) => category.category_id === selectedCategory)) {
          setCategoryId('');
          setPage(1);
        }
      })
      .catch((requestError) => !cancelled && setError(requestError.message));
    return () => { cancelled = true; };
  }, [activeProviderId, activeTab, status?.configured, status?.generation]);

  useEffect(() => {
    if (!status?.configured || !['movie', 'metadata'].includes(activeTab)) return undefined;
    let cancelled = false;
    const reviewView = metadataView === 'overview' ? 'needs-review' : metadataView;
    const loadingReview = activeTab === 'metadata' && metadataView !== 'overview';
    if (loadingReview) {
      setMetadataReviewLoading(true);
      setMetadataReview({ items: [], total: 0, page: metadataPage, page_size: 50 });
    }
    Promise.all([
      iptvApi.movieFacets(activeProviderId, { view: activeTab === 'movie' ? movieFilters.view : 'provider' }),
      iptvApi.movieStatus(activeProviderId),
      iptvApi.metadataSettings(),
      activeTab === 'metadata' && metadataView !== 'overview'
        ? iptvApi.movieMetadataReview(activeProviderId, { view: reviewView, ...metadataFilters, page: metadataPage, page_size: 50 })
        : Promise.resolve({ items: [], total: 0, page: 1, page_size: 50 })
    ]).then(([facets, worker, metadata, review]) => {
      if (cancelled || activeProviderRef.current !== activeProviderId) return;
      setMovieFacets({ ...EMPTY_MOVIE_FACETS, ...facets });
      setMovieStatus((current) => mergeIPTVMovieStatus(current, worker));
      setMetadataReview(review);
      setMetadataSettings(metadata);
      if (!metadataLoadedRef.current) {
        setMetadataCredential('');
        setMetadataCredentialType(metadata.credential_type || 'bearer');
        setMetadataEditing(!metadata.tmdb_configured);
        metadataLoadedRef.current = true;
      } else if (!metadata.tmdb_configured) {
        setMetadataEditing(true);
      }
      if (!ollamaLoadedRef.current) {
        setOllamaEnabled(Boolean(metadata.ollama_enabled));
        setOllamaUrl(metadata.ollama_url || 'http://127.0.0.1:11434');
        setOllamaModel(metadata.ollama_model || '');
        ollamaLoadedRef.current = true;
      }
    }).catch((requestError) => !cancelled && setError(requestError.message))
      .finally(() => !cancelled && loadingReview && setMetadataReviewLoading(false));
    return () => { cancelled = true; };
  }, [activeProviderId, activeTab, status?.configured, status?.generation, movieRefresh, movieFilters.view, metadataView, metadataPage, metadataFilters]);

  useEffect(() => {
    if (!status?.configured || activeTab !== 'metadata' || !movieStatus?.latest_jobs) return undefined;
    let cancelled = false;
    const requestedProviderId = activeProviderId;
    const matchJobId = movieStatus.latest_jobs.match?.job_id || '';
    const rebuildJobId = movieStatus.latest_jobs.rebuild?.job_id || '';
    Promise.all([
      matchJobId ? iptvApi.movieMatchJob(requestedProviderId, matchJobId) : Promise.resolve(null),
      rebuildJobId ? iptvApi.movieRebuildJob(requestedProviderId, rebuildJobId) : Promise.resolve(null)
    ]).then(([matchJob, durableRebuildJob]) => {
      if (cancelled || activeProviderRef.current !== requestedProviderId) return;
      setLastProposalJob(matchJob);
      setLastRebuildJob(durableRebuildJob);
    }).catch((requestError) => {
      if (!cancelled && activeProviderRef.current === requestedProviderId) setError(requestError.message);
    });
    return () => { cancelled = true; };
  }, [
    activeProviderId,
    activeTab,
    status?.configured,
    movieStatus?.latest_jobs?.match?.job_id,
    movieStatus?.latest_jobs?.rebuild?.job_id
  ]);

  useEffect(() => {
    if (!movieStatus || (!enrichmentControl && !['starting', 'running', 'pausing', 'cancelling', 'waiting-capacity'].includes(movieStatus.state) && movieStatus?.projection?.state !== 'running')) return undefined;
    const requestedProviderId = activeProviderId;
    const previousWorkerState = movieStatus.state;
    const previousProjectionState = movieStatus?.projection?.state;
    const intervalMs = enrichmentControl || ['pausing', 'cancelling'].includes(previousWorkerState) ? 250 : 1000;
    const timer = window.setInterval(() => {
      iptvApi.movieStatus(requestedProviderId, { control_only: 1 }).then((next) => {
        if (activeProviderRef.current !== requestedProviderId) return;
        setMovieStatus((current) => mergeIPTVMovieStatus(current, next));
        const activeStates = ['starting', 'running', 'pausing', 'cancelling', 'waiting-capacity'];
        const workerSettled = activeStates.includes(previousWorkerState) && !activeStates.includes(next.state);
        const projectionSettled = previousProjectionState === 'running' && next?.projection?.state !== 'running';
        if (workerSettled || projectionSettled) {
          window.clearInterval(timer);
          setMovieRefresh((value) => value + 1);
          iptvApi.movieStatus(requestedProviderId).then((summary) => {
            if (activeProviderRef.current === requestedProviderId) {
              setMovieStatus((current) => mergeIPTVMovieStatus(current, summary));
            }
          }).catch(() => {});
        }
      }).catch(() => {});
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [activeProviderId, enrichmentControl, movieStatus?.state, movieStatus?.projection?.state]);

  useEffect(() => {
    if (!status?.configured || activeTab !== 'movie') return undefined;
    const normalizedQuery = normalizeIPTVMovieSearchQuery(movieFilters.q);
    const signature = iptvMovieQuerySignature(
      activeProviderId,
      { ...movieFilters, q: normalizedQuery },
      page,
      browsePageSize,
      Number(status?.generation || 0)
    );
    const sequence = movieRequestRef.current.sequence + 1;
    movieRequestRef.current.controller?.abort();
    const controller = new AbortController();
    movieRequestRef.current = { sequence, signature, controller };
    setMovieLoading(true);
    setError('');
    setCatalog({ ...EMPTY_PAGE, page, page_size: browsePageSize, loading: true, query: normalizedQuery, view: movieFilters.view });
    const timer = window.setTimeout(async () => {
      try {
        const result = await iptvApi.movies(
          activeProviderId,
          iptvMovieQuery({ ...movieFilters, q: normalizedQuery }, page, browsePageSize),
          { signal: controller.signal }
        );
        const current = movieRequestRef.current;
        if (controller.signal.aborted || current.sequence !== sequence || current.signature !== signature || activeProviderRef.current !== activeProviderId) return;
        setCatalog({ ...result, loading: false, query: normalizedQuery, view: movieFilters.view });
      } catch (requestError) {
        if (controller.signal.aborted || requestError?.name === 'AbortError') return;
        const current = movieRequestRef.current;
        if (current.sequence !== sequence || current.signature !== signature || activeProviderRef.current !== activeProviderId) return;
        setCatalog({ ...EMPTY_PAGE, page, page_size: browsePageSize, loading: false, query: normalizedQuery, view: movieFilters.view, failed: true });
        setError(requestError.message);
      } finally {
        const current = movieRequestRef.current;
        if (current.sequence === sequence && current.signature === signature && activeProviderRef.current === activeProviderId) setMovieLoading(false);
      }
    }, normalizedQuery ? 220 : 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      setMovieLoading(false);
    };
  }, [activeProviderId, activeTab, browsePageSize, page, status?.configured, status?.generation, movieFilters, movieRefresh]);

  useEffect(() => {
    if (!status?.configured || !isBrowseTab || activeTab === 'movie') return undefined;
    let cancelled = false;
    setLoading(true);
    setError('');
    const timer = window.setTimeout(async () => {
      try {
        if (activeTab === 'favorites') {
          const result = await iptvApi.favorites(activeProviderId, {
            kind: favoriteKind === 'all' ? '' : favoriteKind,
            q: query.trim(),
            page,
            page_size: browsePageSize
          });
          if (!cancelled) setCatalog(result);
          return;
        }
        const result = await iptvApi.items(activeProviderId, {
          kind: browseKind,
          category_id: categoryId,
          q: query.trim(),
          page,
          page_size: browsePageSize,
          favorites: activeTab === 'favorites'
        });
        if (!cancelled) setCatalog(result);
      } catch (requestError) {
        if (!cancelled) setError(requestError.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, query ? 220 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [activeProviderId, activeTab, browseKind, browsePageSize, categoryId, query, page, status?.configured, status?.generation]);

  useEffect(() => {
    setPage(1);
  }, [browsePageSize]);

  useEffect(() => {
    if (!status?.configured || activeTab !== 'lists') return undefined;
    let cancelled = false;
    iptvApi.lists(activeProviderId)
      .then((result) => {
        if (cancelled) return;
        const nextLists = result.items || [];
        setLists(nextLists);
        setSelectedListId((current) => nextLists.some((list) => list.list_id === current) ? current : (nextLists[0]?.list_id || ''));
      })
      .catch((requestError) => !cancelled && setError(requestError.message));
    return () => { cancelled = true; };
  }, [activeProviderId, activeTab, status?.configured, status?.generation, listRefresh]);

  useEffect(() => {
    const selected = lists.find((list) => list.list_id === selectedListId);
    setRenameListName(selected?.name || '');
  }, [lists, selectedListId]);

  useEffect(() => {
    if (!status?.configured || activeTab !== 'lists' || !selectedListId) {
      if (!selectedListId) setListCatalog(EMPTY_PAGE);
      return undefined;
    }
    let cancelled = false;
    setListLoading(true);
    const timer = window.setTimeout(() => {
      iptvApi.listItems(activeProviderId, selectedListId, {
        kind: listKind === 'all' ? '' : listKind,
        q: listQuery.trim(),
        page: listPage,
        page_size: 60
      })
        .then((result) => !cancelled && setListCatalog(result))
        .catch((requestError) => !cancelled && setError(requestError.message))
        .finally(() => !cancelled && setListLoading(false));
    }, listQuery ? 220 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [activeProviderId, activeTab, status?.configured, selectedListId, listKind, listQuery, listPage, listRefresh]);

  useEffect(() => () => {
    if (playbackRef.current?.token) iptvApi.stopPlayback(playbackRef.current.provider_id, playbackRef.current.token).catch(() => {});
  }, []);

  function selectTab(tab) {
    setActiveTab(tab);
    setCategoryId('');
    setQuery('');
    setPage(1);
    setSelectedId('');
    setDetail(null);
  }

  function resetProviderState() {
    movieRequestRef.current.controller?.abort();
    movieRequestRef.current = { sequence: movieRequestRef.current.sequence + 1, signature: '', controller: null };
    setStatus(null);
    setCategories({ live: [], movie: [], series: [] });
    setCategoryId('');
    setQuery('');
    setPage(1);
    setCatalog(EMPTY_PAGE);
    setMovieLoading(false);
    setRecent([]);
    setSelectedId('');
    setDetail(null);
    setDetailLoading(false);
    setSelectedSeason(1);
    setSelectedLive(null);
    setEpg([]);
    setPlayback(null);
    playbackRef.current = null;
    setLists([]);
    setSelectedListId('');
    setListCatalog(EMPTY_PAGE);
    setListQuery('');
    setListKind('all');
    setListPage(1);
    setListPickerItem(null);
    setListPickerLists([]);
    setMovieFilters(createIPTVMovieFilters());
    setMovieFacets(EMPTY_MOVIE_FACETS);
    setMovieStatus(null);
    enrichmentControlRef.current = { sequence: enrichmentControlRef.current.sequence + 1, providerId: '' };
    setEnrichmentControl(null);
    setMetadataFilters({ q: '', category: '', playlist_id: '' });
    setMetadataReviewLoading(false);
    setMetadataSelection(new Set());
    setMetadataAllFiltered(false);
    setProposalJob(null);
    setLastProposalJob(null);
    setClassificationPreview(null);
    setRebuildJob(null);
    setLastRebuildJob(null);
    setMetadataCredential('');
    setSourceChooser(null);
    setMatchDialog(null);
    setMatchResults([]);
    setError('');
  }

  async function switchProvider(providerId) {
    if (!providerId || providerId === activeProviderId) return;
    const previousPlayback = playbackRef.current;
    resetProviderState();
    if (previousPlayback?.token) {
      await iptvApi.stopPlayback(previousPlayback.provider_id || activeProviderId, previousPlayback.token).catch(() => {});
    }
    setActiveProviderId(providerId);
    iptvApi.selectProvider(providerId).catch((requestError) => setError(requestError.message));
  }

  async function syncCatalog() {
    setError('');
    try {
      await iptvApi.sync(activeProviderId);
      await refreshStatus();
      notify?.('IPTV catalog sync started');
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function toggleFavorite(item) {
    const next = !item.favorite;
    try {
      if (item.movie_key) await iptvApi.movieFavorite(activeProviderId, item.movie_key, next);
      else await iptvApi.favorite(activeProviderId, item.kind, item.item_id, next);
      setCatalog((state) => {
        const matches = (row) => item.movie_key ? row.movie_key === item.movie_key : row.kind === item.kind && row.item_id === item.item_id;
        if (activeTab === 'favorites' && !next) {
          return { ...state, items: state.items.filter((row) => !matches(row)), total: Math.max(0, Number(state.total || 0) - 1) };
        }
        return { ...state, items: state.items.map((row) => matches(row) ? { ...row, favorite: next } : row) };
      });
      setDetail((state) => state && (item.movie_key ? state.movie_key === item.movie_key : state.kind === item.kind && state.item_id === item.item_id) ? { ...state, favorite: next } : state);
      setSelectedLive((state) => state && state.kind === item.kind && state.item_id === item.item_id ? { ...state, favorite: next } : state);
      setRecent((state) => state.map((row) => row.kind === item.kind && row.item_id === item.item_id ? { ...row, favorite: next } : row));
      notify?.(next ? 'Added to IPTV favorites' : 'Removed from IPTV favorites');
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function createIPTVList() {
    const name = newListName.trim();
    if (!name) return;
    try {
      const created = await iptvApi.createList(activeProviderId, name);
      setNewListName('');
      setSelectedListId(created.list_id);
      setListRefresh((value) => value + 1);
      notify?.(`IPTV list created: ${created.name}`);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function renameIPTVList() {
    const name = renameListName.trim();
    if (!selectedListId || !name) return;
    try {
      const renamed = await iptvApi.renameList(activeProviderId, selectedListId, name);
      setRenameListName(renamed.name);
      setListRefresh((value) => value + 1);
      notify?.(`IPTV list renamed: ${renamed.name}`);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function deleteIPTVList() {
    const selected = lists.find((list) => list.list_id === selectedListId);
    if (!selected || !window.confirm(`Delete IPTV list "${selected.name}"? Saved media will not be removed from the provider.`)) return;
    try {
      await iptvApi.deleteList(activeProviderId, selectedListId);
      setSelectedListId('');
      setListRefresh((value) => value + 1);
      notify?.('IPTV list deleted');
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function removeIPTVListItem(item) {
    try {
      await iptvApi.setListItem(activeProviderId, selectedListId, item.kind, item.item_id, false);
      setListRefresh((value) => value + 1);
      notify?.('Removed from IPTV list');
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function moveIPTVListItem(item, direction) {
    try {
      await iptvApi.moveListItem(activeProviderId, selectedListId, item.kind, item.item_id, direction);
      setListRefresh((value) => value + 1);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function openListPicker(item) {
    setListPickerItem(item);
    setListPickerLists([]);
    setListPickerName('');
    setListPickerBusy(true);
    try {
      const result = await iptvApi.lists(activeProviderId, { kind: item.kind, item_id: item.item_id });
      if (item.movie_key) {
        const movie = item.sources ? item : await iptvApi.movieDetail(activeProviderId, item.movie_key);
        const included = new Set(movie.list_ids || []);
        setListPickerLists((result.items || []).map((list) => ({ ...list, included: included.has(list.list_id) })));
      } else {
        setListPickerLists(result.items || []);
      }
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setListPickerBusy(false);
    }
  }

  async function togglePickerList(list) {
    if (!listPickerItem) return;
    setListPickerBusy(true);
    try {
      const included = !list.included;
      if (listPickerItem.movie_key) await iptvApi.setMovieList(activeProviderId, listPickerItem.movie_key, list.list_id, included);
      else await iptvApi.setListItem(activeProviderId, list.list_id, listPickerItem.kind, listPickerItem.item_id, included);
      setListPickerLists((state) => state.map((row) => row.list_id === list.list_id ? { ...row, included, item_count: Math.max(0, row.item_count + (included ? 1 : -1)) } : row));
      setListRefresh((value) => value + 1);
      notify?.(included ? `Added to ${list.name}` : `Removed from ${list.name}`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setListPickerBusy(false);
    }
  }

  async function createPickerList() {
    const name = listPickerName.trim();
    if (!name || !listPickerItem) return;
    setListPickerBusy(true);
    try {
      const created = await iptvApi.createList(activeProviderId, name);
      if (listPickerItem.movie_key) await iptvApi.setMovieList(activeProviderId, listPickerItem.movie_key, created.list_id, true);
      else await iptvApi.setListItem(activeProviderId, created.list_id, listPickerItem.kind, listPickerItem.item_id, true);
      setListPickerLists((state) => [...state, { ...created, included: true, item_count: 1 }]);
      setListPickerName('');
      setListRefresh((value) => value + 1);
      notify?.(`Created ${created.name} and added media`);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setListPickerBusy(false);
    }
  }

  async function loadDetail(item) {
    const requestedProviderId = activeProviderId;
    const requestedId = item.movie_key || item.item_id;
    const requestId = ++detailRequestRef.current;
    setSelectedId(requestedId);
    setMovieLocale('default');
    setDetailLoading(true);
    setError('');
    try {
      const result = item.movie_key
        ? await iptvApi.movieDetail(requestedProviderId, item.movie_key)
        : await iptvApi.detail(requestedProviderId, item.kind, item.item_id);
      if (activeProviderRef.current !== requestedProviderId || detailRequestRef.current !== requestId) return;
      let displayedResult = result;
      if (item.movie_key && result.matched && result.original_language === 'ar') {
        try {
          const localized = result.arabic_display
            || await iptvApi.movieLocalization(requestedProviderId, result.movie_key, 'ar-SA');
          if (activeProviderRef.current !== requestedProviderId || detailRequestRef.current !== requestId) return;
          displayedResult = movieWithDisplay({ ...result, arabic_display: localized }, localized);
        } catch (localizationError) {
          if (activeProviderRef.current === requestedProviderId && detailRequestRef.current === requestId) {
            setError(localizationError.message);
          }
        }
      }
      if (activeProviderRef.current !== requestedProviderId || detailRequestRef.current !== requestId) return;
      setDetail(displayedResult);
      const seasonNumbers = [...new Set((result.episodes || []).map((episode) => episode.season))].sort((a, b) => a - b);
      setSelectedSeason(seasonNumbers[0] || 1);
    } catch (requestError) {
      if (activeProviderRef.current === requestedProviderId) setError(requestError.message);
    } finally {
      if (activeProviderRef.current === requestedProviderId) setDetailLoading(false);
    }
  }

  async function openDetail(item) {
    const itemId = item.movie_key || item.item_id;
    if (selectedId === itemId) {
      detailRequestRef.current += 1;
      setSelectedId('');
      setDetail(null);
      setMovieLocale('default');
      return;
    }
    await loadDetail(item);
  }

  async function openListItem(item) {
    if (!item.available) return;
    if (item.kind === 'live') {
      selectTab('live');
      await selectChannel(item);
      return;
    }
    setActiveTab(item.kind);
    setCategoryId('');
    setQuery(mediaTitle(item));
    setPage(1);
    await loadDetail(item);
  }

  async function playListItem(item) {
    if (item.kind === 'live') {
      selectTab('live');
      await selectChannel(item);
      return;
    }
    await playItem(item);
  }

  async function playItem(item, options = {}) {
    if (item.movie_key && !options.itemId && Number(item.source_count || item.sources?.length || 1) > 1) {
      try {
        const sources = item.sources || (await iptvApi.movieSources(activeProviderId, item.movie_key)).items || [];
        setSourceChooser({ movie: item, sources });
      } catch (requestError) {
        setError(requestError.message);
      }
      return;
    }
    const requestedProviderId = activeProviderId;
    setPlaybackLoading(true);
    setError('');
    try {
      if (playbackRef.current?.token) await iptvApi.stopPlayback(playbackRef.current.provider_id, playbackRef.current.token).catch(() => {});
      const result = await iptvApi.startPlayback(requestedProviderId, {
        kind: options.kind || item.kind,
        item_id: options.itemId || item.item_id,
        extension: options.extension || item.container_extension,
        title: options.title || item.name || item.title
      });
      if (activeProviderRef.current !== requestedProviderId) {
        await iptvApi.stopPlayback(requestedProviderId, result.token).catch(() => {});
        return;
      }
      const next = {
        ...result,
        provider_id: requestedProviderId,
        kind: options.kind || item.kind,
        item_id: options.itemId || item.item_id,
        title: options.title || item.name || item.title,
        historyKind: options.historyKind,
        historyId: options.historyId
      };
      playbackRef.current = next;
      setPlayback(next);
    } catch (requestError) {
      if (activeProviderRef.current === requestedProviderId) setError(requestError.message);
    } finally {
      if (activeProviderRef.current === requestedProviderId) setPlaybackLoading(false);
    }
  }

  async function chooseMovieSource(source) {
    const movie = sourceChooser?.movie;
    setSourceChooser(null);
    if (!movie) return;
    await playItem(movie, {
      kind: 'movie',
      itemId: source.item_id,
      extension: source.container_extension,
      title: source.name || movie.name || movie.title
    });
  }

  function updateMovieFilter(name, value) {
    setMovieFilters((state) => {
      if (name === 'view' && value === 'provider') {
        const defaults = createIPTVMovieFilters();
        return {
          ...defaults,
          view: 'provider',
          q: state.q,
          playlist_id: state.playlist_id,
          list_id: state.list_id,
          sort: state.sort
        };
      }
      return { ...state, [name]: value };
    });
    setPage(1);
    setSelectedId('');
    setDetail(null);
  }

  async function saveMetadataCredential() {
    if (!metadataCredential.trim()) return;
    setMetadataBusy(true);
    setError('');
    try {
      const saved = await iptvApi.saveMetadataSettings({
        credential: metadataCredential,
        credential_type: metadataCredentialType
      });
      setMetadataCredential('');
      setMetadataSettings(saved);
      setMetadataEditing(false);
      const validation = await iptvApi.testMetadata();
      notify?.(validation.valid ? 'IPTV TMDB credential validated' : 'IPTV TMDB validation failed');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setMetadataBusy(false);
    }
  }

  async function testSavedMetadataCredential() {
    setMetadataBusy(true);
    setError('');
    try {
      const validation = await iptvApi.testMetadata();
      notify?.(validation.valid ? 'Saved IPTV TMDB credential is valid' : 'Saved IPTV TMDB credential is invalid');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setMetadataBusy(false);
    }
  }

  async function controlEnrichment(action) {
    const requestedProviderId = activeProviderId;
    const sequence = enrichmentControlRef.current.sequence + 1;
    enrichmentControlRef.current = { sequence, providerId: requestedProviderId };
    setError('');
    setEnrichmentControl({ action, providerId: requestedProviderId });
    try {
      const apiAction = action === 'start-diagnostic' ? 'start' : action;
      const payload = apiAction === 'start'
        ? { consent: !movieStatus?.consent, diagnostic: action === 'start-diagnostic' }
        : action === 'resume' && movieStatus?.restart_confirmation_required
          ? { continue_after_restart: true }
          : {};
      const response = await iptvApi.movieEnrichment(requestedProviderId, apiAction, payload);
      if (enrichmentControlRef.current.sequence !== sequence || activeProviderRef.current !== requestedProviderId) return;
      const next = response?.status || response;
      setMovieStatus((current) => mergeIPTVMovieStatus(current, next));
      setEnrichmentControl(null);
      setMovieRefresh((value) => value + 1);
      notify?.(`IPTV movie metadata ${action.replaceAll('-', ' ')}`);
    } catch (requestError) {
      if (enrichmentControlRef.current.sequence !== sequence || activeProviderRef.current !== requestedProviderId) return;
      setEnrichmentControl(null);
      setError(requestError.message);
      iptvApi.movieStatus(requestedProviderId).then((next) => {
        if (enrichmentControlRef.current.sequence === sequence && activeProviderRef.current === requestedProviderId) {
          setMovieStatus((current) => mergeIPTVMovieStatus(current, next));
        }
      }).catch(() => {});
    }
  }

  async function retryProjection() {
    try {
      const projection = await iptvApi.retryMovieProjection(activeProviderId);
      setMovieStatus((state) => ({ ...(state || {}), projection }));
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function switchMovieLocale(locale) {
    if (!detail?.movie_key) return;
    if (locale === 'en-US' && detail.base_display) {
      setDetail((state) => movieWithDisplay(state, state.base_display));
      setMovieLocale('en-US');
      return;
    }
    try {
      const localized = detail.arabic_display || await iptvApi.movieLocalization(activeProviderId, detail.movie_key, 'ar-SA');
      setDetail((state) => movieWithDisplay({ ...state, arabic_display: localized }, localized));
      setMovieLocale('ar-SA');
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  function openMatchMetadata(movie) {
    const identity = iptvMovieIdentity(
      movie.provider_title || movie.name || '',
      movie.provider_year || movie.year || ''
    );
    setMatchDialog(movie);
    setMatchQuery(identity.title);
    setMatchYear(identity.year);
    setMatchResults([]);
  }

  async function searchMatchMetadata() {
    if (!matchDialog) return;
    setMatchBusy(true);
    setError('');
    try {
      const result = await iptvApi.movieMatchSearch(activeProviderId, matchDialog.movie_key, {
        q: matchQuery.trim(),
        year: matchYear.trim()
      });
      setMatchResults(result.items || []);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setMatchBusy(false);
    }
  }

  async function applyMovieMatch(candidate) {
    if (!matchDialog) return;
    setMatchBusy(true);
    try {
      await iptvApi.setMovieMatch(activeProviderId, matchDialog.movie_key, candidate.tmdb_id);
      setMatchDialog(null);
      setMatchResults([]);
      setSelectedId('');
      setDetail(null);
      setMovieRefresh((value) => value + 1);
      notify?.('IPTV movie metadata match saved');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setMatchBusy(false);
    }
  }

  async function removeMovieMatch(movie, reprocess = false) {
    try {
      await iptvApi.removeMovieMatch(activeProviderId, movie.movie_key, reprocess);
      setSelectedId('');
      setDetail(null);
      setMovieRefresh((value) => value + 1);
      notify?.(reprocess ? 'IPTV movie queued for a new match' : 'IPTV metadata match removed');
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function saveOllamaConfiguration() {
    setMetadataBusy(true);
    setError('');
    try {
      const saved = await iptvApi.saveMetadataSettings({
        ollama: { enabled: ollamaEnabled, url: ollamaUrl.trim(), model: ollamaModel.trim() }
      });
      setMetadataSettings(saved);
      setOllamaEnabled(Boolean(saved.ollama_enabled));
      setOllamaUrl(saved.ollama_url || 'http://127.0.0.1:11434');
      setOllamaModel(saved.ollama_model || '');
      notify?.(saved.ollama_enabled ? 'IPTV Ollama assistance configured' : 'IPTV Ollama assistance disabled');
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setMetadataBusy(false);
    }
  }

  function metadataSelectionPayload() {
    return {
      selection_mode: metadataAllFiltered ? 'all-filtered' : 'explicit',
      selected_keys: metadataAllFiltered ? [] : [...metadataSelection],
      filters: { review_view: metadataView, ...metadataFilters, view: 'provider' },
      page: metadataPage,
      page_size: metadataReview.page_size || 50
    };
  }

  function toggleMetadataSelection(sourceKey) {
    setMetadataAllFiltered(false);
    setMetadataSelection((current) => {
      const next = new Set(current);
      if (next.has(sourceKey)) next.delete(sourceKey); else next.add(sourceKey);
      return next;
    });
  }

  function selectMetadataPage() {
    setMetadataAllFiltered(false);
    setMetadataSelection((current) => new Set([
      ...current,
      ...(metadataReview.items || []).map((item) => item.source_key)
    ]));
  }

  async function previewBulkClassification(category) {
    setProposalBusy(true);
    setError('');
    try {
      const preview = await iptvApi.movieClassificationPreview(activeProviderId, {
        ...metadataSelectionPayload(), category
      });
      setClassificationPreview(preview);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setProposalBusy(false);
    }
  }

  async function applyBulkClassification(proposalIds) {
    if (!classificationPreview) return;
    setProposalBusy(true);
    try {
      const selected = new Set(proposalIds || []);
      const result = await iptvApi.movieClassificationApply(activeProviderId, {
        catalog_generation: classificationPreview.catalog_generation,
        proposals: classificationPreview.proposals.map((proposal) => ({ ...proposal, selected: selected.has(proposal.proposal_id) }))
      });
      notify?.(`${formatCount(result.applied?.length || 0)} IPTV classifications applied`);
      setClassificationPreview(null);
      setMetadataSelection(new Set());
      setMetadataAllFiltered(false);
      setMovieRefresh((value) => value + 1);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setProposalBusy(false);
    }
  }

  async function createBulkMatchJob(method) {
    setProposalBusy(true);
    setError('');
    try {
      const job = await iptvApi.createMovieMatchJob(activeProviderId, {
        ...metadataSelectionPayload(), method
      });
      setProposalJob(job);
      setLastProposalJob(job);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setProposalBusy(false);
    }
  }

  async function applyBulkMatchJob(proposalIds) {
    if (!proposalJob) return;
    setProposalBusy(true);
    try {
      const result = await iptvApi.applyMovieMatchJob(activeProviderId, proposalJob.job_id, { proposal_ids: proposalIds });
      setProposalJob(result.job);
      setLastProposalJob(result.job);
      notify?.(`${formatCount(result.applied?.length || 0)} IPTV metadata proposals applied`);
      setMetadataSelection(new Set());
      setMetadataAllFiltered(false);
      setMovieRefresh((value) => value + 1);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setProposalBusy(false);
    }
  }

  async function cancelBulkMatchJob() {
    if (!proposalJob) return;
    try {
      const cancelled = await iptvApi.cancelMovieMatchJob(activeProviderId, proposalJob.job_id);
      setProposalJob(cancelled);
      setLastProposalJob(cancelled);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function previewRebuild() {
    setProposalBusy(true);
    try {
      const job = await iptvApi.movieRebuildPreview(activeProviderId, { scope: { automatic: true } });
      setRebuildJob(job);
      setLastRebuildJob(job);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setProposalBusy(false);
    }
  }

  async function cancelRebuildPreview() {
    if (!rebuildJob) return;
    try {
      const cancelled = await iptvApi.cancelMovieRebuild(activeProviderId, rebuildJob.job_id);
      setRebuildJob(cancelled);
      setLastRebuildJob(cancelled);
    } catch (requestError) {
      setError(requestError.message);
    }
  }

  async function previewFusionRepairs() {
    setProposalBusy(true);
    setError('');
    try {
      setFusionPreview(await iptvApi.movieFusionPreview(activeProviderId, { limit: 500 }));
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setProposalBusy(false);
    }
  }

  async function applyFusionRepairs(proposalIds) {
    if (!fusionPreview) return;
    setProposalBusy(true);
    try {
      const result = await iptvApi.applyMovieFusion(activeProviderId, {
        catalog_generation: fusionPreview.catalog_generation,
        proposal_ids: proposalIds
      });
      notify?.(`${formatCount(result.applied?.length || 0)} same-movie source repairs applied`);
      setFusionPreview(null);
      setMovieStatus((current) => mergeIPTVMovieStatus(current, result.status));
      setMovieRefresh((value) => value + 1);
    } catch (requestError) {
      setError(requestError.message);
    } finally {
      setProposalBusy(false);
    }
  }

  async function closePlayback() {
    const current = playbackRef.current;
    playbackRef.current = null;
    setPlayback(null);
    if (current?.token) await iptvApi.stopPlayback(current.provider_id, current.token).catch(() => {});
  }

  async function selectChannel(channel) {
    setSelectedLive(channel);
    setEpg([]);
    const requestedProviderId = activeProviderId;
    iptvApi.epg(requestedProviderId, channel.item_id)
      .then((result) => {
        if (activeProviderRef.current === requestedProviderId) setEpg(result.items || []);
      })
      .catch(() => {
        if (activeProviderRef.current === requestedProviderId) setEpg([]);
      });
    await playItem(channel);
  }

  if (loading && !status) return <div className="iptv-loading"><Loader2 className="spin" size={22} /> Loading IPTV...</div>;

  return (
    <section className="iptv-workspace">
      <header className="iptv-header">
        <div>
          <h1>IPTV</h1>
          <p className="screen-kicker">Provider television</p>
          <p>{status?.last_sync ? `Updated ${relativeSyncTime(status.last_sync)}` : 'Provider catalog kept separate from the Cinema Paradiso archive.'}</p>
        </div>
        <div className="iptv-header-status">
          {providers.length ? (
            <label className="iptv-provider-select">
              <ServerCog size={15} />
              <select aria-label="Active IPTV provider" value={activeProviderId} onChange={(event) => switchProvider(event.target.value)}>
                {providers.map((provider) => <option key={provider.provider_id} value={provider.provider_id}>{provider.name}</option>)}
              </select>
            </label>
          ) : <span><ServerCog size={15} /> No providers</span>}
          {status?.configured ? (
            <button type="button" className="icon-button" onClick={syncCatalog} disabled={status?.sync?.state === 'running'} aria-label="Sync IPTV catalog" title="Sync catalog">
              <RefreshCcw size={17} className={status?.sync?.state === 'running' ? 'spin' : ''} />
            </button>
          ) : null}
        </div>
      </header>

      <nav className="iptv-tabs" aria-label="IPTV sections">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button type="button" key={id} className={activeTab === id ? 'is-active' : ''} onClick={() => selectTab(id)}>
            <Icon size={17} /> {label}
          </button>
        ))}
      </nav>

      {error ? <div className="iptv-error"><span>{error}</span><button type="button" onClick={() => setError('')} aria-label="Dismiss error"><X size={16} /></button></div> : null}
      {!activeProviderId ? <IPTVSetupRequired /> : null}
      {status?.configured && status?.sync?.state === 'running' ? <SyncBanner status={status.sync} /> : null}
      {status?.configured && status?.sync?.state === 'error' ? <div className="iptv-error"><span>{status.sync.error}</span></div> : null}

      {status?.configured && activeTab === 'home' ? (
        <IPTVHome providerId={activeProviderId} status={status} recent={recent} onBrowse={selectTab} onPlay={playItem} onFavorite={toggleFavorite} onAddToList={openListPicker} />
      ) : null}
      {status?.configured && isBrowseTab ? (
        <>
          {activeTab === 'movie' ? (
            <MovieToolbar
              filters={movieFilters}
              facets={movieFacets}
              total={catalog.total}
              onFilter={updateMovieFilter}
              onReset={() => { setMovieFilters({ ...createIPTVMovieFilters(), view: movieFilters.view }); setPage(1); setSelectedId(''); setDetail(null); }}
            />
          ) : (
            <BrowseToolbar
              kind={browseKind}
              categories={categories[browseKind] || []}
              categoryId={categoryId}
              onCategory={(value) => { setCategoryId(value); setPage(1); }}
              query={query}
              onQuery={(value) => { setQuery(value); setPage(1); }}
              activeTab={activeTab}
              favoriteKind={favoriteKind}
              onFavoriteKind={(value) => { setFavoriteKind(value); setCategoryId(''); setPage(1); setSelectedId(''); setDetail(null); }}
              total={catalog.total}
            />
          )}
          {activeTab === 'favorites' ? (
            <FavoritesView
              providerId={activeProviderId}
              catalog={catalog}
              followed={followed}
              selectedId={selectedId}
              detail={detail}
              detailLoading={detailLoading}
              selectedSeason={selectedSeason}
              onSeason={setSelectedSeason}
              onToggle={openDetail}
              onPlay={playItem}
              onFavorite={toggleFavorite}
              onAddToList={openListPicker}
              onOpenChannel={(channel) => { selectTab('live'); selectChannel(channel); }}
              loading={loading}
              gridRef={activeCardGridRef}
            />
          ) : browseKind === 'live' ? (
            <LiveView
              providerId={activeProviderId}
              categories={categories.live || []}
              categoryId={categoryId}
              onCategory={(value) => { setCategoryId(value); setPage(1); }}
              catalog={catalog}
              selected={selectedLive}
              epg={epg}
              playback={playback}
              loading={loading || playbackLoading}
              onSelect={selectChannel}
              onFavorite={toggleFavorite}
              onAddToList={openListPicker}
              onClosePlayback={closePlayback}
            />
          ) : browseKind === 'movie' ? (
            <MovieView
              providerId={activeProviderId}
              catalog={catalog}
              followed={followed}
              selectedId={selectedId}
              detail={detail}
              detailLoading={detailLoading}
              onToggle={openDetail}
              onPlay={playItem}
              onFavorite={toggleFavorite}
              onAddToList={openListPicker}
              onMatch={openMatchMetadata}
              onRemoveMatch={removeMovieMatch}
              projection={catalog.projection || movieStatus?.projection}
              locale={movieLocale}
              onLocale={switchMovieLocale}
              onRetryProjection={retryProjection}
              loading={movieLoading}
              gridRef={activeCardGridRef}
            />
          ) : (
            <SeriesView providerId={activeProviderId} catalog={catalog} detail={detail} detailLoading={detailLoading} selectedId={selectedId} selectedSeason={selectedSeason} onSeason={setSelectedSeason} onToggle={openDetail} onPlay={playItem} onFavorite={toggleFavorite} onAddToList={openListPicker} gridRef={activeCardGridRef} />
          )}
          <Pagination page={catalog.page || page} pageSize={catalog.page_size || browsePageSize} total={catalog.total || 0} onPage={setPage} />
        </>
      ) : null}

      {status?.configured && activeTab === 'metadata' ? (
        <MetadataDashboard
          provider={providers.find((provider) => provider.provider_id === activeProviderId)}
          settings={metadataSettings}
          credential={metadataCredential}
          credentialType={metadataCredentialType}
          editing={metadataEditing}
          busy={metadataBusy}
          worker={movieStatus}
          enrichmentControl={enrichmentControl}
          view={metadataView}
          review={metadataReview}
          reviewLoading={metadataReviewLoading}
          filters={metadataFilters}
          facets={movieFacets}
          providerId={activeProviderId}
          page={metadataPage}
          selection={metadataSelection}
          allFiltered={metadataAllFiltered}
          proposalBusy={proposalBusy}
          proposalJob={proposalJob}
          lastProposalJob={lastProposalJob}
          classificationPreview={classificationPreview}
          rebuildJob={rebuildJob}
          lastRebuildJob={lastRebuildJob}
          fusionPreview={fusionPreview}
          selectedId={selectedId}
          detail={detail}
          detailLoading={detailLoading}
          locale={movieLocale}
          ollamaEnabled={ollamaEnabled}
          ollamaUrl={ollamaUrl}
          ollamaModel={ollamaModel}
          onView={(value) => { setMetadataView(value); setMetadataPage(1); setMetadataSelection(new Set()); setMetadataAllFiltered(false); }}
          onPage={setMetadataPage}
          onFilter={(name, value) => { setMetadataFilters((current) => ({ ...current, [name]: value })); setMetadataPage(1); setMetadataSelection(new Set()); setMetadataAllFiltered(false); }}
          onCredential={setMetadataCredential}
          onCredentialType={setMetadataCredentialType}
          onSave={saveMetadataCredential}
          onTestSaved={testSavedMetadataCredential}
          onReplace={() => { setMetadataCredential(''); setMetadataCredentialType(metadataSettings.credential_type || 'bearer'); setMetadataEditing(true); }}
          onCancelReplace={() => { setMetadataCredential(''); setMetadataEditing(false); }}
          onOllamaEnabled={setOllamaEnabled}
          onOllamaUrl={setOllamaUrl}
          onOllamaModel={setOllamaModel}
          onSaveOllama={saveOllamaConfiguration}
          onControl={controlEnrichment}
          onRetryProjection={retryProjection}
          onSelect={toggleMetadataSelection}
          onSelectPage={selectMetadataPage}
          onSelectAllFiltered={() => { setMetadataSelection(new Set()); setMetadataAllFiltered(true); }}
          onClearSelection={() => { setMetadataSelection(new Set()); setMetadataAllFiltered(false); }}
          onClassify={previewBulkClassification}
          onApplyClassification={applyBulkClassification}
          onCancelClassification={() => setClassificationPreview(null)}
          onMatchSelected={createBulkMatchJob}
          onApplyMatchJob={applyBulkMatchJob}
          onCancelMatchJob={cancelBulkMatchJob}
          onCloseMatchJob={() => setProposalJob(null)}
          onReopenMatchJob={() => setProposalJob(lastProposalJob)}
          onPreviewRebuild={() => window.confirm('Create a provider-local logical rebuild preview? This does not apply changes, sync the provider, or start enrichment.') && previewRebuild()}
          onCancelRebuild={cancelRebuildPreview}
          onCloseRebuild={() => setRebuildJob(null)}
          onReopenRebuild={() => setRebuildJob(lastRebuildJob)}
          onPreviewFusion={previewFusionRepairs}
          onApplyFusion={applyFusionRepairs}
          onCloseFusion={() => setFusionPreview(null)}
          onToggle={openDetail}
          onPlay={playItem}
          onFavorite={toggleFavorite}
          onAddToList={openListPicker}
          onMatch={openMatchMetadata}
          onRemoveMatch={removeMovieMatch}
          onLocale={switchMovieLocale}
        />
      ) : null}

      {status?.configured && activeTab === 'lists' ? (
        <IPTVListsWorkspace
          providerId={activeProviderId}
          lists={lists}
          selectedListId={selectedListId}
          catalog={listCatalog}
          loading={listLoading}
          query={listQuery}
          kindFilter={listKind}
          newListName={newListName}
          renameName={renameListName}
          onSelectList={(value) => { setSelectedListId(value); setListPage(1); setListQuery(''); setListKind('all'); }}
          onQuery={(value) => { setListQuery(value); setListPage(1); }}
          onKindFilter={(value) => { setListKind(value); setListPage(1); }}
          onNewListName={setNewListName}
          onRenameName={setRenameListName}
          onCreate={createIPTVList}
          onRename={renameIPTVList}
          onDelete={deleteIPTVList}
          onRemove={removeIPTVListItem}
          onMove={moveIPTVListItem}
          onPlay={playListItem}
          onOpen={openListItem}
          onPage={setListPage}
        />
      ) : null}

      {playback && playback.kind !== 'live' ? (
        <div className="iptv-playback-backdrop" role="presentation" onClick={closePlayback}>
          <div className="iptv-playback-dialog" onClick={(event) => event.stopPropagation()}>
            <IPTVPlayer playback={playback} onClose={closePlayback} />
          </div>
        </div>
      ) : null}
      <IPTVListPickerModal
        item={listPickerItem}
        lists={listPickerLists}
        busy={listPickerBusy}
        newName={listPickerName}
        onNewName={setListPickerName}
        onCreate={createPickerList}
        onToggle={togglePickerList}
        onClose={() => { if (!listPickerBusy) setListPickerItem(null); }}
      />
      <SourceChooserModal chooser={sourceChooser} onChoose={chooseMovieSource} onClose={() => setSourceChooser(null)} />
      <MatchMetadataModal
        movie={matchDialog}
        query={matchQuery}
        year={matchYear}
        results={matchResults}
        busy={matchBusy}
        onQuery={setMatchQuery}
        onYear={setMatchYear}
        onSearch={searchMatchMetadata}
        onApply={applyMovieMatch}
        onClose={() => { if (!matchBusy) setMatchDialog(null); }}
      />
    </section>
  );
}

function IPTVSetupRequired() {
  return (
    <div className="iptv-setup">
      <ServerCog size={34} />
      <div><strong>Connect an Xtream provider first</strong><span>Enter the server, username, and password in Settings. Cinema Paradiso does not supply IPTV subscriptions.</span></div>
      <button type="button" className="btn btn-primary" onClick={() => window.location.assign('/settings#settings-iptv')}>Open Settings</button>
    </div>
  );
}

function SyncBanner({ status }) {
  return <div className="iptv-sync"><Loader2 className="spin" size={16} /><strong>{status.phase || 'Syncing IPTV catalog'}</strong><span>The current catalog remains usable until the replacement is complete.</span></div>;
}

function IPTVHome({ providerId, status, recent, onBrowse, onPlay, onFavorite, onAddToList }) {
  const counts = status.counts || {};
  return (
    <div className="iptv-home">
      <div className="iptv-stat-grid">
        <HomeStat icon={Radio} label="Live channels" count={counts.live} onClick={() => onBrowse('live')} />
        <HomeStat icon={Film} label="Provider movies" count={counts.movie} onClick={() => onBrowse('movie')} />
        <HomeStat icon={Tv} label="Provider series" count={counts.series} onClick={() => onBrowse('series')} />
      </div>
      <section className="iptv-home-section">
        <header><div><p className="screen-kicker">Continue watching</p><h2>Recent IPTV</h2></div><Clock3 size={20} /></header>
        {recent.length ? (
          <div className="iptv-recent-row">
            {recent.map((item) => <PosterTile providerId={providerId} key={`${item.kind}-${item.item_id}`} item={item} onClick={() => item.kind === 'movie' ? onPlay(item) : onBrowse(item.kind)} onFavorite={onFavorite} onAddToList={onAddToList} />)}
          </div>
        ) : <div className="iptv-empty"><ListVideo size={28} /><span>Played movies and series will appear here.</span></div>}
      </section>
    </div>
  );
}

function HomeStat({ icon: Icon, label, count = 0, onClick }) {
  return <button type="button" className="iptv-stat" onClick={onClick}><span><Icon size={21} /></span><strong>{formatCount(count)}</strong><small>{label}</small><ChevronRight size={18} /></button>;
}

function BrowseToolbar({ kind, categories, categoryId, onCategory, query, onQuery, activeTab, favoriteKind, onFavoriteKind, total }) {
  return (
    <div className={`iptv-browse-toolbar ${activeTab === 'favorites' ? 'is-favorites' : ''}`}>
      {activeTab === 'favorites' ? (
        <div className="iptv-segmented" aria-label="Favorite type">
          {[['all', 'All'], ['live', 'Channels'], ['movie', 'Movies'], ['series', 'Series']].map(([id, label]) => <button type="button" key={id} className={favoriteKind === id ? 'is-active' : ''} onClick={() => onFavoriteKind(id)}>{label}</button>)}
        </div>
      ) : <strong>{kind === 'live' ? 'Live channels' : kind === 'movie' ? 'Movies' : 'Series'}</strong>}
      {activeTab !== 'favorites' ? <label className="iptv-category-select">
        <Layers3 size={16} />
        <select value={categoryId} onChange={(event) => onCategory(event.target.value)} aria-label="Provider category">
          <option value="">All provider categories</option>
          {categories.map((category) => <option value={category.category_id} key={category.category_id}>{category.name} ({formatCount(category.item_count)})</option>)}
        </select>
      </label> : null}
      <label className="iptv-search"><Search size={16} /><input value={query} onChange={(event) => onQuery(event.target.value)} placeholder={activeTab === 'favorites' ? 'Search favorites...' : `Search ${kind === 'live' ? 'channels' : kind}...`} dir="auto" /></label>
      <span>{formatCount(total)} results</span>
    </div>
  );
}

function MovieToolbar({ filters, facets, total, onFilter, onReset }) {
  const cpView = filters.view === 'cp';
  return (
    <div className="iptv-movie-toolbar">
      <div className="iptv-movie-view-switch" role="group" aria-label="IPTV Movies view">
        {IPTV_MOVIE_VIEWS.map(([id, label]) => <button type="button" key={id} className={filters.view === id ? 'is-active' : ''} aria-pressed={filters.view === id} onClick={() => onFilter('view', id)}>{label}</button>)}
      </div>
      <div className="iptv-movie-toolbar-primary">
        <strong>{cpView ? 'CP View' : 'Provider View'}</strong>
        <label><span>Provider playlist</span><select value={filters.playlist_id} onChange={(event) => onFilter('playlist_id', event.target.value)} aria-label="Provider playlist"><option value="">All provider playlists</option>{facets.playlists.map((playlist) => <option key={playlist.id} value={playlist.id}>{playlist.name} ({formatCount(playlist.source_count)})</option>)}</select></label>
        <label><span>My list</span><select value={filters.list_id} onChange={(event) => onFilter('list_id', event.target.value)} aria-label="My list"><option value="">All movies</option>{facets.lists.map((list) => <option key={list.list_id} value={list.list_id}>{list.name} ({formatCount(list.movie_count)})</option>)}</select></label>
        <label className="iptv-search"><Search size={16} /><input value={filters.q} onChange={(event) => onFilter('q', event.target.value)} placeholder="Search movie..." dir="auto" /></label>
        <label><span>Sort</span><select value={filters.sort} onChange={(event) => onFilter('sort', event.target.value)}>{IPTV_MOVIE_SORTS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <span>{formatCount(total)} results</span>
      </div>
      {cpView ? <div className="iptv-movie-category-row" role="group" aria-label="IPTV Movies category">
        <button type="button" className={!filters.category ? 'is-active' : ''} onClick={() => onFilter('category', '')}>All categories</button>
        {IPTV_MOVIE_CATEGORIES.map(([id, label]) => {
          const facet = facets.categories?.find((row) => row.id === id);
          return <button type="button" key={id} className={filters.category === id ? 'is-active' : ''} onClick={() => onFilter('category', id)}>{label} <small>{formatCount(facet?.source_count || 0)}</small></button>;
        })}
      </div> : <p className="iptv-provider-view-note">Every provider movie source remains visible here, whether classified, matched, or unresolved.</p>}
      {cpView ? <div className="iptv-movie-filter-row">
        <label><span>Genre</span><select value={filters.genre_id} onChange={(event) => onFilter('genre_id', event.target.value)}><option value="">All genres</option>{facets.genres.map((genre) => <option key={genre.id} value={genre.id}>{genre.name}</option>)}</select></label>
        <label title="Language remains the existing matched-metadata filter; its parked semantics are unchanged."><span>Language (matched metadata)</span><select value={filters.language} onChange={(event) => onFilter('language', event.target.value)}><option value="">All languages</option>{facets.languages.map((language) => <option key={language.code} value={language.code}>{language.name || language.code}</option>)}</select></label>
        <label><span>Country</span><select value={filters.country} onChange={(event) => onFilter('country', event.target.value)}><option value="">All countries</option>{facets.countries.map((country) => <option key={country.code} value={country.code}>{country.name || country.code}</option>)}</select></label>
        <label><span>From</span><input type="number" min="1888" max="2200" value={filters.year_from} onChange={(event) => onFilter('year_from', event.target.value)} placeholder="Year" /></label>
        <label><span>To</span><input type="number" min="1888" max="2200" value={filters.year_to} onChange={(event) => onFilter('year_to', event.target.value)} placeholder="Year" /></label>
        <label><span>Rating</span><select value={filters.min_rating} onChange={(event) => onFilter('min_rating', event.target.value)}><option value="">Any rating</option>{[5, 6, 7, 8, 9].map((rating) => <option key={rating} value={rating}>{rating}+</option>)}</select></label>
        <label><span>Metadata</span><select value={filters.metadata_status} onChange={(event) => onFilter('metadata_status', event.target.value)}><option value="">All states</option><option value="matched">Matched</option><option value="unmatched">Unmatched</option><option value="ambiguous">Ambiguous</option><option value="failed">Failed</option><option value="unprocessed">Unprocessed</option></select></label>
        <label><span>Claimed quality</span><select value={filters.quality} onChange={(event) => onFilter('quality', event.target.value)}><option value="">Any quality</option>{facets.qualities.map((quality) => <option key={quality} value={quality}>{quality}</option>)}</select></label>
        <label><span>Watched</span><select value={filters.watched} onChange={(event) => onFilter('watched', event.target.value)}><option value="">Any state</option><option value="unwatched">Unwatched</option><option value="watched">Watched</option></select></label>
        <label className="iptv-claim-check"><input type="checkbox" checked={filters.dubbed} onChange={(event) => onFilter('dubbed', event.target.checked)} /> Dubbed claim</label>
        <label className="iptv-claim-check"><input type="checkbox" checked={filters.subtitled} onChange={(event) => onFilter('subtitled', event.target.checked)} /> Subtitle claim</label>
        <button type="button" className="btn btn-secondary" onClick={onReset}>Reset filters</button>
      </div> : <div className="iptv-movie-filter-row iptv-provider-view-actions"><button type="button" className="btn btn-secondary" onClick={onReset}>Reset filters</button></div>}
    </div>
  );
}

function MetadataDashboard({
  provider, providerId, settings, credential, credentialType, editing, busy, worker, enrichmentControl, view, review, reviewLoading,
  filters, facets, page, selection, allFiltered, proposalBusy, proposalJob, lastProposalJob, classificationPreview,
  rebuildJob, lastRebuildJob, fusionPreview, selectedId, detail, detailLoading, locale, ollamaEnabled, ollamaUrl, ollamaModel,
  onView, onPage, onFilter, onCredential, onCredentialType, onSave, onTestSaved, onReplace, onCancelReplace,
  onOllamaEnabled, onOllamaUrl, onOllamaModel, onSaveOllama, onControl, onRetryProjection, onSelect, onSelectPage,
  onSelectAllFiltered, onClearSelection, onClassify, onApplyClassification, onCancelClassification,
  onMatchSelected, onApplyMatchJob, onCancelMatchJob, onCloseMatchJob, onReopenMatchJob, onPreviewRebuild,
  onCancelRebuild, onCloseRebuild, onReopenRebuild, onPreviewFusion, onApplyFusion, onCloseFusion,
  onToggle, onPlay, onFavorite, onAddToList, onMatch,
  onRemoveMatch, onLocale
}) {
  const state = worker?.state || 'idle';
  const running = ['starting', 'running', 'pausing', 'cancelling'].includes(state);
  const paused = state === 'paused';
  const waiting = state === 'waiting-capacity';
  const restartOffer = state === 'awaiting-continuation' || worker?.restart_confirmation_required;
  const automaticRemaining = Number(worker?.automatic_remaining || 0);
  const readyToContinue = state === 'complete' && automaticRemaining > 0;
  const continueOffer = restartOffer || readyToContinue;
  const controlAction = enrichmentControl?.providerId === providerId ? enrichmentControl.action : '';
  const controlPending = Boolean(controlAction);
  const startRequested = ['start', 'resume', 'start-diagnostic'].includes(controlAction);
  const pauseRequested = controlAction === 'pause';
  const cancelRequested = controlAction === 'cancel';
  const controlLabel = startRequested ? 'Starting metadata requested' : pauseRequested ? 'Pause requested' : cancelRequested ? 'Cancel requested' : controlAction === 'retry-failures' ? 'Failure retry requested' : controlAction === 're-evaluate-stale' ? 'Stale-item re-evaluation requested' : 'Control request pending';
  const canPause = ['starting', 'running'].includes(state) || startRequested;
  const canCancel = running || paused || waiting || restartOffer || startRequested || pauseRequested;
  const sources = Number(worker?.sources || 0);
  const evaluated = Math.min(sources, Number(worker?.evaluated || 0));
  const percent = sources ? Math.min(100, (evaluated / sources) * 100) : 0;
  const matches = worker?.matches || {};
  const accepted = Number(matches['matched-auto'] || 0) + Number(matches['matched-manual'] || 0);
  const needsReview = Number(worker?.needs_review ?? (Number(matches.ambiguous || 0) + Number(worker?.stale || 0)));
  const unmatched = Number(matches.unmatched || 0);
  const failed = Number(matches['error-terminal'] || 0) + Number(matches['error-retryable'] || 0);
  const projection = worker?.projection || {};
  const views = [['overview', 'Overview'], ['needs-review', 'Needs review'], ['unmatched', 'Unmatched'], ['failed', 'Failed'], ['manual', 'Manual matches']];
  return (
    <section className="iptv-metadata-dashboard">
      <header className="iptv-metadata-header"><div><p className="screen-kicker">Provider-local Movies metadata</p><h2>{provider?.name || 'Selected provider'}</h2><p>Every provider keeps independent databases, queues, decisions, and progress.</p></div><span className={`iptv-worker-state is-${state}`}>{waiting ? 'Waiting for global worker capacity' : continueOffer ? 'Ready to continue' : state}{controlPending ? ` · ${controlLabel}` : ''}</span></header>
      <div className="iptv-enrichment-progress">
        <div className="iptv-progress-heading"><strong>{formatCount(evaluated)} of {formatCount(sources)} provider sources evaluated ({percent.toFixed(2)}%)</strong><span>{formatCount(Math.max(0, sources - evaluated))} remaining</span></div>
        <div className="iptv-progress-track" role="progressbar" aria-valuemin="0" aria-valuemax={sources || 1} aria-valuenow={evaluated} aria-label="IPTV metadata evaluation progress"><span className="is-accepted" style={{ width: `${sources ? accepted / sources * 100 : 0}%` }} /><span className="is-review" style={{ width: `${sources ? needsReview / sources * 100 : 0}%` }} /><span className="is-unmatched" style={{ width: `${sources ? unmatched / sources * 100 : 0}%` }} /><span className="is-failed" style={{ width: `${sources ? failed / sources * 100 : 0}%` }} /></div>
        <div className="iptv-progress-legend"><span className="is-accepted">{formatCount(accepted)} accepted</span><span className="is-review">{formatCount(needsReview)} needs review</span><span className="is-unmatched">{formatCount(unmatched)} unmatched</span><span className="is-failed">{formatCount(failed)} failed</span></div>
        <div className="iptv-progress-facts"><span>Automatic work remaining <strong>{formatCount(automaticRemaining)}</strong></span><span>Classification review <strong>{formatCount(worker?.classification_review || 0)}</strong></span><span>Distinct TMDB movies <strong>{formatCount(worker?.distinct_tmdb_movies || 0)}</strong></span><span>Worker checkpoint <strong>{formatCount(worker?.checkpoint || 0)}</strong></span><span>Counter revision <strong>{formatCount(worker?.summary_revision || 0)}</strong></span><span>{worker?.heartbeat_at ? `Last heartbeat ${relativeSyncTime(worker.heartbeat_at)}` : 'Worker has not started yet'}</span>{worker?.status_stale ? <span>Status refresh delayed; showing the last exact totals.</span> : null}</div>
      </div>
      <div className="iptv-stage-grid">
        <article><span>Provider sync</span><strong>{formatCount(sources)} available sources</strong><small>Raw catalog and playback authority.</small></article>
        <article><span>Local projection</span><strong>{projection.state || 'not started'}</strong><small>{formatCount(projection.processed || 0)} of {formatCount(projection.total || 0)} projected · {formatCount(projection.published || 0)} browseable</small>{['failed', 'not-started'].includes(projection.state) ? <button type="button" className="btn btn-secondary" onClick={onRetryProjection}>Retry projection</button> : null}</article>
        <article><span>TMDB enrichment worker</span><strong>{waiting ? 'Waiting for capacity' : continueOffer ? 'Ready to continue' : state}</strong><small>{controlPending ? `${controlLabel}. Last confirmed worker state: ${state}.` : worker?.retry_reason || worker?.worker_error || (continueOffer ? `${formatCount(automaticRemaining)} automatic items can still be processed.` : 'Provider-local, bounded, and checkpointed.')}</small></article>
      </div>
      <div className="iptv-worker-controls iptv-dashboard-controls">
        {startRequested ? <button type="button" className="btn btn-primary" disabled><WandSparkles size={15} /> Starting metadata…</button> : null}
        {!controlPending && !running && !paused && !waiting && !restartOffer && state !== 'complete' ? <button type="button" className="btn btn-primary" disabled={!settings.tmdb_configured || projection.state !== 'complete'} onClick={() => onControl('start')}><WandSparkles size={15} /> Improve this provider&apos;s Movies</button> : null}
        {!controlPending && continueOffer ? <button type="button" className="btn btn-primary" disabled={!settings.tmdb_configured} onClick={() => onControl('resume')}><Play size={15} /> Continue metadata improvement</button> : null}
        {pauseRequested ? <button type="button" className="btn btn-secondary" disabled><Pause size={15} /> Pause requested…</button> : !cancelRequested && canPause ? <button type="button" className="btn btn-secondary" onClick={() => onControl('pause')}><Pause size={15} /> Pause</button> : null}
        {!controlPending && paused ? <button type="button" className="btn btn-primary" onClick={() => onControl('resume')}><Play size={15} /> Resume</button> : null}
        {cancelRequested ? <button type="button" className="btn btn-secondary" disabled><Square size={14} /> Cancel requested…</button> : canCancel ? <button type="button" className="btn btn-secondary" onClick={() => onControl('cancel')}><Square size={14} /> Cancel future work</button> : null}
        <button type="button" className="btn btn-secondary" disabled={controlPending || !Number(worker?.queue?.failed || 0)} onClick={() => onControl('retry-failures')}><RefreshCcw size={15} /> Retry failures</button>
        <button type="button" className="btn btn-secondary" disabled={controlPending || !Number(worker?.stale || 0)} onClick={() => onControl('re-evaluate-stale')}><RefreshCcw size={15} /> Re-evaluate stale automatic results</button>
        <details className="iptv-diagnostic-controls"><summary>Diagnostics</summary><button type="button" className="btn btn-secondary" disabled={!settings.tmdb_configured || running || controlPending} onClick={() => onControl('start-diagnostic')}>Run next {formatCount(worker?.batch_limit || 100)}</button></details>
      </div>
      <nav className="iptv-metadata-subtabs" aria-label="Metadata review queues">{views.map(([id, label]) => <button type="button" key={id} className={view === id ? 'is-active' : ''} onClick={() => onView(id)}>{label}</button>)}</nav>
      {view === 'overview' ? <div className="iptv-metadata-overview"><p>Evaluated means a terminal classification or matching decision; it does not mean matched. Worker state describes the current run, while Automatic work remaining determines whether Continue is available. Classification review requires an explicit decision.</p></div> : (
        <MetadataReviewWorkspace
          providerId={providerId}
          review={review}
          loading={reviewLoading}
          filters={filters}
          facets={facets}
          selection={selection}
          allFiltered={allFiltered}
          busy={proposalBusy}
          tmdbConfigured={settings.tmdb_configured}
          ollamaConfigured={settings.ollama_enabled}
          selectedId={selectedId}
          detail={detail}
          detailLoading={detailLoading}
          locale={locale}
          onFilter={onFilter}
          onSelect={onSelect}
          onSelectPage={onSelectPage}
          onSelectAllFiltered={onSelectAllFiltered}
          onClearSelection={onClearSelection}
          onClassify={onClassify}
          onMatchSelected={onMatchSelected}
          onToggle={onToggle}
          onPlay={onPlay}
          onFavorite={onFavorite}
          onAddToList={onAddToList}
          onMatch={onMatch}
          onRemoveMatch={onRemoveMatch}
          onLocale={onLocale}
        />
      )}
      {view !== 'overview' ? <Pagination page={review.page || page} pageSize={review.page_size || 50} total={review.total || 0} onPage={onPage} /> : null}
      {classificationPreview ? <ClassificationPreviewPanel preview={classificationPreview} busy={proposalBusy} onApply={onApplyClassification} onCancel={onCancelClassification} /> : null}
      {proposalJob ? <MatchProposalPanel job={proposalJob} busy={proposalBusy} onApply={onApplyMatchJob} onCancel={onCancelMatchJob} onClose={onCloseMatchJob} onManualMatch={onMatch} /> : lastProposalJob ? <button type="button" className="btn btn-secondary iptv-reopen-job" onClick={onReopenMatchJob}>Reopen last {lastProposalJob.method?.toUpperCase()} proposal job · {lastProposalJob.state}</button> : null}
      <details className="iptv-rebuild-controls">
        <summary>Logical rebuild preview</summary>
        <p>Shadow-evaluate automatic decisions only. Preview never synchronizes a provider, deletes its database, applies identity changes, or starts enrichment.</p>
        {!rebuildJob ? <button type="button" className="btn btn-secondary" disabled={proposalBusy} onClick={onPreviewRebuild}><RefreshCcw size={15} /> Preview automatic rebuild</button> : <RebuildPreviewPanel job={rebuildJob} onCancel={onCancelRebuild} onClose={onCloseRebuild} />}
        {!rebuildJob && lastRebuildJob ? <button type="button" className="btn btn-secondary" onClick={onReopenRebuild}>Reopen last rebuild preview · {lastRebuildJob.state}</button> : null}
      </details>
      <details className="iptv-rebuild-controls">
        <summary>Same-movie source fusion</summary>
        <p>Preview existing manual-classification repairs and independently validated quality variants. Provider View remains one raw source per card; CP View fuses accepted Film sources by TMDB identity.</p>
        {!fusionPreview ? <button type="button" className="btn btn-secondary" disabled={proposalBusy} onClick={onPreviewFusion}><Layers3 size={15} /> Preview source fusion repairs</button> : <FusionPreviewPanel preview={fusionPreview} busy={proposalBusy} onApply={onApplyFusion} onClose={onCloseFusion} />}
      </details>
      <div className="iptv-metadata-panel">
        <div className="iptv-metadata-copy"><span className={settings.tmdb_configured ? 'is-ready' : ''}><KeyRound size={18} /> {settings.tmdb_configured ? 'IPTV TMDB stored on this device' : 'IPTV TMDB not configured'}</span><p>This credential belongs only to IPTV Movies. Saving or testing it never starts enrichment and never uses Cinema Paradiso&apos;s TMDB setting.</p></div>
        {editing || !settings.tmdb_configured ? <><label><span>Credential type</span><select value={credentialType} onChange={(event) => onCredentialType(event.target.value)}><option value="bearer">Read access token</option><option value="api_key">API key</option></select></label><label className="iptv-metadata-secret"><span>IPTV TMDB credential</span><input type="password" autoComplete="new-password" value={credential} onChange={(event) => onCredential(event.target.value)} placeholder={settings.tmdb_configured ? 'Enter replacement credential' : 'Enter credential'} /></label><div className="iptv-metadata-actions"><button type="button" className="btn btn-primary" disabled={busy || !credential.trim()} onClick={onSave}>{busy ? <Loader2 className="spin" size={15} /> : <KeyRound size={15} />} Save &amp; validate</button>{settings.tmdb_configured ? <button type="button" className="btn btn-secondary" disabled={busy} onClick={onCancelReplace}>Cancel</button> : null}</div></> : <div className="iptv-metadata-actions iptv-metadata-saved-actions"><button type="button" className="btn btn-secondary" disabled={busy} onClick={onTestSaved}>{busy ? <Loader2 className="spin" size={15} /> : <KeyRound size={15} />} Test saved credential</button><button type="button" className="btn btn-secondary" disabled={busy} onClick={onReplace}>Replace credential</button></div>}
      </div>
      <div className="iptv-metadata-panel iptv-ollama-panel">
        <div className="iptv-metadata-copy"><span className={settings.ollama_enabled ? 'is-ready' : ''}><WandSparkles size={18} /> {settings.ollama_enabled ? 'IPTV Ollama assistance configured' : 'IPTV Ollama assistance disabled'}</span><p>Ollama may classify unclear sources or rank real IPTV TMDB candidates. It cannot invent or directly apply an identity.</p></div>
        <label className="iptv-claim-check"><input type="checkbox" checked={ollamaEnabled} onChange={(event) => onOllamaEnabled(event.target.checked)} /> Enable IPTV Ollama</label>
        <label><span>Ollama URL</span><input value={ollamaUrl} onChange={(event) => onOllamaUrl(event.target.value)} placeholder="http://127.0.0.1:11434" /></label>
        <label><span>Model</span><input value={ollamaModel} onChange={(event) => onOllamaModel(event.target.value)} placeholder="Configured local model" /></label>
        <button type="button" className="btn btn-secondary" disabled={busy || (ollamaEnabled && !ollamaModel.trim())} onClick={onSaveOllama}>Save Ollama settings</button>
      </div>
    </section>
  );
}

function metadataReviewMovie(item) {
  return {
    ...item,
    movie_key: `source:${item.source_key}`,
    name: item.provider_title,
    title: item.provider_title,
    year: item.provider_year,
    kind: 'movie',
    item_id: item.source_id,
    source_count: 1,
    matched: Boolean(item.tmdb_id),
    metadata_status: item.state,
    classification_review_reason: item.classification_review_reason || item.error_message || ''
  };
}

function MetadataReviewWorkspace({ providerId, review, loading, filters, facets, selection, allFiltered, busy, tmdbConfigured, ollamaConfigured, selectedId, detail, detailLoading, locale, onFilter, onSelect, onSelectPage, onSelectAllFiltered, onClearSelection, onClassify, onMatchSelected, onToggle, onPlay, onFavorite, onAddToList, onMatch, onRemoveMatch, onLocale }) {
  const selectedCount = allFiltered ? Number(review.total || 0) : selection.size;
  const canAct = selectedCount > 0 && !busy;
  return (
    <section className="iptv-review-workspace">
      <div className="iptv-review-filters">
        <label className="iptv-search"><Search size={16} /><input value={filters.q} onChange={(event) => onFilter('q', event.target.value)} placeholder="Search this review queue..." dir="auto" /></label>
        <select aria-label="Review classification" value={filters.category} onChange={(event) => onFilter('category', event.target.value)}><option value="">All classifications</option>{IPTV_MOVIE_CATEGORIES.map(([id, label]) => <option value={id} key={id}>{label}</option>)}</select>
        <select aria-label="Review provider playlist" value={filters.playlist_id} onChange={(event) => onFilter('playlist_id', event.target.value)}><option value="">All provider playlists</option>{facets.playlists.map((playlist) => <option value={playlist.id} key={playlist.id}>{playlist.name}</option>)}</select>
      </div>
      <div className="iptv-selection-toolbar">
        <strong>{allFiltered ? `${formatCount(review.total)} filtered sources selected` : `${formatCount(selection.size)} selected`}</strong>
        <button type="button" className="btn btn-secondary" disabled={!review.items?.length || busy} onClick={onSelectPage}><CheckSquare size={15} /> Add current page</button>
        <button type="button" className="btn btn-secondary" disabled={!review.total || busy} onClick={onSelectAllFiltered}>Select all filtered</button>
        <button type="button" className="btn btn-secondary" disabled={!selectedCount || busy} onClick={onClearSelection}>Clear selection</button>
      </div>
      <div className="iptv-bulk-actions">
        <span>Classify selected</span>
        {IPTV_MOVIE_CATEGORIES.map(([id, label]) => <button type="button" className="btn btn-secondary" key={id} disabled={!canAct} onClick={() => onClassify(id)}>{label}</button>)}
        <button type="button" className="btn btn-primary" disabled={!canAct || !tmdbConfigured} onClick={() => onMatchSelected('tmdb')}><WandSparkles size={15} /> Match selected with TMDB</button>
        <button type="button" className="btn btn-secondary" disabled={!canAct || !tmdbConfigured || !ollamaConfigured} onClick={() => onMatchSelected('ai')}><WandSparkles size={15} /> Match selected with AI</button>
      </div>
      {loading ? <div className="iptv-empty iptv-grid-empty"><Loader2 className="spin" size={28} /><strong>Loading provider-local review cards</strong></div> : null}
      {!loading && !review.items?.length ? <div className="iptv-empty"><Database size={28} /><span>No provider-local sources match this review queue and filter.</span></div> : null}
      {!loading && review.items?.length ? <div className="discover-grid iptv-movie-grid iptv-review-card-grid">{review.items.map((item) => {
        const movie = metadataReviewMovie(item);
        return <IPTVMovieCard key={item.source_key} providerId={providerId} movie={movie} selectedId={selectedId} detail={detail} detailLoading={detailLoading} onToggle={onToggle} onPlay={onPlay} onFavorite={onFavorite} onAddToList={onAddToList} onMatch={onMatch} onRemoveMatch={onRemoveMatch} locale={locale} onLocale={onLocale} selectable checked={allFiltered || selection.has(item.source_key)} onSelect={() => onSelect(item.source_key)} />;
      })}</div> : null}
    </section>
  );
}

function ClassificationPreviewPanel({ preview, busy, onApply, onCancel }) {
  const [selected, setSelected] = useState(() => new Set());
  useEffect(() => setSelected(new Set((preview.proposals || []).filter((item) => !item.locked).map((item) => item.proposal_id))), [preview]);
  const toggle = (id) => setSelected((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  return <section className="iptv-proposal-panel"><header><div><p className="screen-kicker">Classification preview</p><h3>{formatCount(preview.proposals?.length || 0)} provider sources</h3></div><button type="button" onClick={onCancel} aria-label="Close classification preview"><X size={18} /></button></header><div className="iptv-classification-proposals">{(preview.proposals || []).map((item) => <label key={item.proposal_id} className={item.locked ? 'is-locked' : ''}><input type="checkbox" checked={selected.has(item.proposal_id)} disabled={item.locked} onChange={() => toggle(item.proposal_id)} /><span><strong dir="auto">{item.provider_title}</strong><small>{item.previous_category} → {item.category} · {item.method} · {(Number(item.confidence || 0) * 100).toFixed(0)}%</small>{item.review_reason ? <em>{item.review_reason}</em> : null}</span></label>)}</div><footer><span>Preview changes no current classification.</span><button type="button" className="btn btn-primary" disabled={busy || !selected.size} onClick={() => onApply([...selected])}>Apply {formatCount(selected.size)} selected classifications</button></footer></section>;
}

function FusionPreviewPanel({ preview, busy, onApply, onClose }) {
  const [selected, setSelected] = useState(() => new Set());
  const proposals = preview.proposals || [];
  function toggle(proposalId) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(proposalId)) next.delete(proposalId); else next.add(proposalId);
      return next;
    });
  }
  return <section className="iptv-proposal-panel"><header><div><p className="screen-kicker">Fusion repair preview</p><h3>{formatCount(proposals.length)} safe repairs · {formatCount(preview.conflicts?.length || 0)} conflicts unchanged</h3></div><button type="button" onClick={onClose} aria-label="Close fusion preview"><X size={18} /></button></header><div className="iptv-classification-proposals">{proposals.map((item) => <label key={item.proposal_id}><input type="checkbox" checked={selected.has(item.proposal_id)} onChange={() => toggle(item.proposal_id)} /><span><strong dir="auto">{item.provider_title}</strong><small>{item.type === 'sibling' ? `Validate into TMDB ${item.tmdb_id}` : `${item.current_category || 'unclassified'} → Film`} · {item.quality_claim || item.playlist_name || 'provider source'}</small><em>{item.reason}</em></span></label>)}</div><footer><span>Preview is read-only. Unselected and conflicting sources remain unchanged.</span><button type="button" className="btn btn-primary" disabled={busy || !selected.size} onClick={() => onApply([...selected])}>Apply {formatCount(selected.size)} selected repairs</button></footer></section>;
}

function MatchProposalPanel({ job, busy, onApply, onCancel, onClose, onManualMatch }) {
  const [selected, setSelected] = useState(() => new Set());
  useEffect(() => setSelected(new Set()), [job.job_id]);
  const toggle = (id) => setSelected((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });
  const ready = job.state === 'ready';
  return <section className="iptv-proposal-panel"><header><div><p className="screen-kicker">{job.method === 'ai' ? 'AI-assisted' : 'TMDB'} provider-local proposal job</p><h3>{formatCount(job.processed || job.proposals?.length || 0)} of {formatCount(job.total || job.proposals?.length || 0)} reviewed · {job.state}</h3></div><button type="button" onClick={onClose} aria-label="Close proposal review"><X size={18} /></button></header>{job.error ? <div className="iptv-error"><span>{job.error}</span></div> : null}<div className="iptv-match-proposals">{(job.proposals || []).map((proposal) => {
    const candidate = proposal.evidence?.candidate || {};
    const selectable = ready && Number(proposal.candidate_tmdb_id || 0) > 0 && !proposal.match_manual_lock;
    return <article key={proposal.proposal_id} className={`is-${proposal.recommendation || 'review'}`}><label><input type="checkbox" checked={selected.has(proposal.proposal_id)} disabled={!selectable} onChange={() => toggle(proposal.proposal_id)} /><span>{proposal.recommendation || 'Review'}</span></label><div className="iptv-proposal-comparison"><div><small>Provider source</small><strong dir="auto">{proposal.provider_title}</strong><span>{proposal.provider_year || 'Year unknown'} · {proposal.category || 'unclassified'}</span></div><div><small>Proposed TMDB identity</small><strong dir="auto">{candidate.title || (proposal.candidate_tmdb_id ? `TMDB ${proposal.candidate_tmdb_id}` : 'No credible match')}</strong><span>{candidate.year || 'Year unknown'}{proposal.candidate_tmdb_id ? ` · TMDB ${proposal.candidate_tmdb_id}` : ''}</span></div></div><p>Confidence {Number(proposal.confidence || 0).toFixed(1)}{proposal.evidence?.runner_up_gap !== null && proposal.evidence?.runner_up_gap !== undefined ? ` · runner-up gap ${Number(proposal.evidence.runner_up_gap).toFixed(1)}` : ''}</p>{(proposal.warnings || []).map((warning) => <em key={warning}>{warning}</em>)}<button type="button" className="btn btn-secondary" onClick={() => onManualMatch({ movie_key: `source:${proposal.source_key}`, provider_title: proposal.provider_title, provider_year: proposal.provider_year, name: proposal.provider_title })}>Manual search</button>{proposal.apply_state && proposal.apply_state !== 'pending' ? <strong className={`is-${proposal.apply_state}`}>{proposal.apply_state}: {proposal.apply_result}</strong> : null}</article>;
  })}</div><footer><button type="button" className="btn btn-secondary" disabled={!ready} onClick={() => setSelected(new Set((job.proposals || []).filter((item) => item.recommendation === 'recommended' && Number(item.candidate_tmdb_id || 0) > 0 && !item.match_manual_lock).map((item) => item.proposal_id)))}>Select recommended</button>{ready ? <button type="button" className="btn btn-secondary" disabled={busy} onClick={onCancel}>Cancel job</button> : null}<button type="button" className="btn btn-primary" disabled={!ready || busy || !selected.size} onClick={() => onApply([...selected])}>Apply {formatCount(selected.size)} selected proposals</button></footer></section>;
}

function RebuildPreviewPanel({ job, onCancel, onClose }) {
  const counts = job.report?.transition_counts || {};
  return <section className="iptv-rebuild-preview"><header><strong>Preview {job.job_id?.slice(0, 8)} · {job.state}</strong><button type="button" onClick={onClose} aria-label="Close rebuild preview"><X size={16} /></button></header><div>{Object.entries(counts).map(([label, count]) => <span key={label}><strong>{formatCount(count)}</strong>{label.replaceAll('-', ' ')}</span>)}</div><p>{job.report?.note || 'Preview only. No provider decisions were applied.'}</p><footer>{job.state === 'ready' ? <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel preview</button> : null}<strong>Live rebuild apply is not available from this Gate 4–6 surface.</strong></footer></section>;
}

function LiveView({ providerId, categories, categoryId, onCategory, catalog, selected, epg, playback, loading, onSelect, onFavorite, onAddToList, onClosePlayback }) {
  return (
    <div className="iptv-live-layout">
      <aside className="iptv-category-rail">
        <button type="button" className={!categoryId ? 'is-active' : ''} onClick={() => onCategory('')}><span>All channels</span><small>{formatCount(catalog.total)}</small></button>
        {categories.map((category) => <button type="button" key={category.category_id} className={categoryId === category.category_id ? 'is-active' : ''} onClick={() => onCategory(category.category_id)}><span dir="auto">{category.name}</span><small>{formatCount(category.item_count)}</small></button>)}
      </aside>
      <section className="iptv-channel-list" aria-label="Channels">
        {catalog.items.map((channel) => (
          <button type="button" key={channel.item_id} className={selected?.item_id === channel.item_id ? 'is-active' : ''} onClick={() => onSelect(channel)}>
            <span className="iptv-channel-number">{channel.channel_num || '–'}</span>
            <span className="iptv-channel-logo"><ProviderImage src={channel.image_url ? iptvImage(providerId, 'live', channel.item_id) : ''} alt="" fallback={Radio} /></span>
            <span className="iptv-channel-name" dir="auto">{channel.name}</span>
            <span className="iptv-live-mark">Live</span>
            <span className="iptv-row-favorite" role="button" tabIndex="0" onClick={(event) => { event.stopPropagation(); onFavorite(channel); }} aria-label={`${channel.favorite ? 'Remove' : 'Add'} favorite`}><Heart size={15} fill={channel.favorite ? 'currentColor' : 'none'} /></span>
            <span className="iptv-row-list" role="button" tabIndex="0" onClick={(event) => { event.stopPropagation(); onAddToList(channel); }} aria-label={`Add ${channel.name} to list`} title="Add to list"><ListPlus size={15} /></span>
          </button>
        ))}
        {!catalog.items.length && !loading ? <div className="iptv-empty"><Radio size={28} /><span>No channels in this view.</span></div> : null}
      </section>
      <div className="iptv-live-player-column">
        <IPTVPlayer playback={playback?.kind === 'live' ? playback : null} compact onClose={playback?.kind === 'live' ? onClosePlayback : undefined} />
        {selected ? <div className="iptv-guide"><header><div><span>Selected channel</span><strong dir="auto">{selected.name}</strong></div><span className="iptv-guide-actions"><button type="button" onClick={() => onAddToList(selected)} aria-label="Add channel to list" title="Add to list"><ListPlus size={17} /></button><button type="button" onClick={() => onFavorite(selected)} aria-label="Toggle channel favorite" title="Favorite"><Heart size={17} fill={selected.favorite ? 'currentColor' : 'none'} /></button></span></header>{epg.length ? epg.map((entry, index) => <div className="iptv-guide-row" key={`${entry.start || index}-${entry.title || ''}`}><span>{index === 0 ? 'Now' : 'Next'}</span><div><strong dir="auto">{entry.title || 'Untitled program'}</strong>{entry.description ? <small dir="auto">{entry.description}</small> : null}</div></div>) : <p>Program guide is unavailable for this channel.</p>}</div> : null}
      </div>
    </div>
  );
}

function MovieView({ providerId, catalog, followed = [], selectedId, detail, detailLoading, onToggle, onPlay, onFavorite, onAddToList, onMatch, onRemoveMatch, projection, locale, onLocale, onRetryProjection, loading, gridRef }) {
  return (
    <div ref={gridRef} className="discover-grid iptv-movie-grid">
      {!loading ? catalog.items.map((movie) => <IPTVMovieCard key={movie.movie_key} providerId={providerId} movie={movie} followed={followed} selectedId={selectedId} detail={detail} detailLoading={detailLoading} onToggle={onToggle} onPlay={onPlay} onFavorite={onFavorite} onAddToList={onAddToList} onMatch={onMatch} onRemoveMatch={onRemoveMatch} locale={locale} onLocale={onLocale} />) : null}
      {loading ? <div className="iptv-empty iptv-grid-empty"><Loader2 className="spin" size={30} /><strong>Searching provider movies</strong><span>{catalog.query ? `Filtering for “${catalog.query}”` : 'Loading this provider-scoped view.'}</span></div> : null}
      {!loading && !catalog.items.length && catalog.failed ? <div className="iptv-empty iptv-grid-empty"><CircleAlert size={30} /><strong>Movies could not be loaded</strong><span>The previous grid was cleared because it does not represent the current search and filters.</span></div> : null}
      {!loading && !catalog.failed && !catalog.items.length && projection?.state === 'running' ? <div className="iptv-empty iptv-grid-empty"><Loader2 className="spin" size={30} /><strong>Preparing provider movies</strong><span>{formatCount(projection.processed || 0)} of {formatCount(projection.total || 0)} sources projected. Browseable cards will appear in committed batches.</span></div> : null}
      {!loading && !catalog.failed && !catalog.items.length && ['failed', 'not-started'].includes(projection?.state) ? <div className="iptv-empty iptv-grid-empty"><CircleAlert size={30} /><strong>Provider movie preparation needs attention</strong><span>{projection?.error || 'Projection has not completed.'}</span><button type="button" className="btn btn-secondary" onClick={onRetryProjection}>Retry projection</button></div> : null}
      {!loading && !catalog.failed && !catalog.items.length && !['running', 'failed', 'not-started'].includes(projection?.state) ? <div className="iptv-empty iptv-grid-empty"><Film size={30} /><strong>{catalog.query ? `No movies match “${catalog.query}”` : 'No movies in this view'}</strong><span>{catalog.query ? 'Clear or change the search while keeping the selected provider and view.' : 'No provider-local cards match the current filters.'}</span></div> : null}
    </div>
  );
}

function IPTVMovieCard({ providerId, movie, followed = [], selectedId, detail, detailLoading, onToggle, onPlay, onFavorite, onAddToList, onMatch, onRemoveMatch, locale = 'default', onLocale, selectable = false, checked = false, onSelect }) {
  const expanded = selectedId === movie.movie_key;
  const current = expanded && detail ? { ...movie, ...detail } : movie;
  const genres = movieGenreLabels(current);
  const languageLabel = current.languages?.map((row) => row.name || row.code).filter(Boolean).join(', ') || '';
  const countryLabel = current.countries?.map((row) => row.name || row.code).filter(Boolean).join(', ') || '';
  const sourceLabels = [
    current.category && current.category !== 'unclassified' ? current.category.replace(/^./, (value) => value.toUpperCase()) : '',
    expanded ? languageLabel : '',
    expanded ? countryLabel : '',
    expanded ? current.certification : '',
    Number(movie.source_count || 1) > 1 ? `${movie.source_count} sources` : '',
    movie.quality_claim ? `${movie.quality_claim} claimed` : ''
  ].filter(Boolean);
  const statusLabel = movie.metadata_status === 'matched-manual' ? 'Manual match' : movie.metadata_status === 'matched-auto' ? 'Matched' : movie.metadata_status === 'error-retryable' || movie.metadata_status === 'error-terminal' ? 'Metadata failed' : movie.metadata_status === 'ambiguous' ? 'Ambiguous' : movie.metadata_status === 'unprocessed' ? 'Not processed' : movie.metadata_status === 'classified-non-film' ? 'Classified' : 'Unmatched';
  const isArabic = locale === 'ar-SA' || (locale === 'default' && current.display_locale === 'ar-SA');
  const selectionControl = selectable ? <label className="iptv-card-selection" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={checked} onChange={onSelect} aria-label={`Select ${movie.provider_title || movie.name}`} /><CheckSquare size={15} /></label> : null;
  return (
    <UnifiedMovieCard
      title={mediaTitle(current)}
      year={current.year || movie.year}
      posterUrl={movie.matched ? (current.image_url || movie.image_url) : (movie.image_url ? iptvImage(providerId, 'movie', movie.item_id) : '')}
      rating={current.rating ? Number(current.rating).toFixed(1) : ''}
      voteCount={formatVoteCount(current.vote_count)}
      chips={genres}
      mutedChips={sourceLabels}
      following={followed.some((item) => movieKey(item) === movieKey({ title: mediaTitle(movie), year: movie.year }))}
      expanded={expanded}
      selected={expanded}
      showPlayOverlay
      onPlay={() => onPlay(current)}
      onToggle={() => onToggle(movie)}
      className={`iptv-movie-card${selectable ? ' is-review-card' : ''}`}
      cornerControls={<div className="iptv-movie-corner-actions">{selectionControl}<span className={`iptv-metadata-badge is-${String(movie.metadata_status || 'unmatched').replace(/[^a-z-]/g, '')}`}>{statusLabel}</span><FavoriteButton item={movie} onFavorite={onFavorite} /><ListActionButton item={movie} onAddToList={onAddToList} /></div>}
      headerActions={expanded && current.external_url ? <IPTVMovieExternalLink movie={current} /> : null}
      metadataActions={expanded && current.matched && onLocale ? <IPTVMovieLanguageToggle isArabic={isArabic} onLocale={onLocale} /> : null}
      expandedFooter={expanded && !detailLoading && current.matched ? <IPTVPeopleCredits directors={current.directors} cast={current.cast} /> : null}
    >
      {expanded ? detailLoading ? <div className="iptv-detail-loading"><Loader2 className="spin" size={17} /> Loading provider metadata...</div> : (
        <>
          <p className="movie-card-plot discover-plot-visible" dir={isArabic ? 'rtl' : 'auto'}>{current.plot || current.classification_review_reason || 'No plot supplied by the provider.'}</p>
          <MovieKeywordRow keywords={current.keywords} />
          <div className="card-actions">
            <button type="button" className="btn btn-primary" onClick={() => onPlay(current)}><Play size={15} /> {Number(current.source_count || 1) > 1 ? 'Choose source' : 'Play'}</button>
            <button type="button" className="btn btn-secondary" onClick={() => onFavorite(current)}><Heart size={15} fill={current.favorite ? 'currentColor' : 'none'} /> {current.favorite ? 'Favorited' : 'Favorite'}</button>
            <button type="button" className="btn btn-secondary" onClick={() => onAddToList(current)}><ListPlus size={15} /> Add to list</button>
            {onMatch ? <button type="button" className="btn btn-secondary" onClick={() => onMatch(current)}><WandSparkles size={15} /> {current.matched ? 'Correct match' : 'Match metadata'}</button> : null}
            {current.matched && onRemoveMatch ? <button type="button" className="btn btn-secondary" onClick={() => window.confirm('Remove this provider-local metadata match? Raw provider playback will remain available.') && onRemoveMatch(current)}><X size={15} /> Remove match</button> : null}
          </div>
          <MovieExpandedFacts movie={current} details={current} />
          <div className="iptv-expanded-provider-facts">
            <span>Provider playlist <strong dir="auto">{current.playlist_name || 'Unknown'}</strong></span>
            <span>Classification <strong>{current.category || 'unclassified'}</strong></span>
            <span>Sources <strong>{formatCount(current.source_count || current.sources?.length || 1)}</strong></span>
            {current.provider_title ? <span>Raw provider title <strong dir="auto">{current.provider_title}{current.provider_year ? ` (${current.provider_year})` : ''}</strong></span> : null}
            {current.detail_title ? <span>Provider detail title <strong dir="auto">{current.detail_title}{current.detail_year ? ` (${current.detail_year})` : ''}</strong></span> : null}
            {current.provider_tmdb_id ? <span>Provider TMDB evidence <strong>{current.provider_tmdb_id}</strong></span> : null}
            {current.tmdb_id ? <span>Accepted TMDB identity <strong>{current.tmdb_id}</strong></span> : null}
            {current.classification_method ? <span>Classification method <strong>{current.classification_method}</strong></span> : null}
            {current.classification_review_reason ? <span>Classification review <strong>{current.classification_review_reason}</strong></span> : null}
            {current.method ? <span>Match evidence <strong>{current.method} · {Number(current.confidence || 0).toFixed(1)}</strong></span> : null}
            {current.collection?.name ? <span>Collection <strong dir="auto">{current.collection.name}</strong></span> : null}
          </div>
        </>
      ) : null}
    </UnifiedMovieCard>
  );
}

function IPTVMovieExternalLink({ movie }) {
  const isIMDb = movie.original_language !== 'ar' && Boolean(movie.imdb_id);
  return <a className={isIMDb ? 'movie-imdb-link' : 'iptv-tmdb-link'} href={movie.external_url} target="_blank" rel="noreferrer" aria-label={`Open ${movie.title || movie.name || 'movie'} on ${isIMDb ? 'IMDb' : 'TMDB'}`}>{isIMDb ? 'IMDb' : 'TMDB'} <ExternalLink size={12} /></a>;
}

function IPTVMovieLanguageToggle({ isArabic, onLocale }) {
  return <div className="movie-language-toolbar"><button type="button" className="mini-action movie-language-toggle" onClick={() => onLocale(isArabic ? 'en-US' : 'ar-SA')} aria-pressed={isArabic}><Languages size={14} />{isArabic ? 'English' : 'العربية'}</button></div>;
}

function IPTVPeopleCredits({ directors = [], cast = [] }) {
  const credits = [
    ...directors.slice(0, 2).map((person) => ({ ...person, role: 'Director', director: true })),
    ...cast.slice(0, 8).map((person) => ({ ...person, role: person.character || 'Cast', director: false }))
  ];
  if (!credits.length) return null;
  return <div className="movie-expanded-details iptv-movie-expanded-details"><section className="movie-expanded-credits-panel" aria-label="Director and top cast"><span className="mini-label">Director &amp; top cast</span><div className="movie-expanded-people-grid">{credits.map((person, index) => <article className={`person-card discover-person-static${person.director ? ' director-person' : ''}`} key={`${person.director ? 'director' : 'cast'}-${person.id || person.name}-${index}`}><span className="person-avatar" aria-hidden="true">{person.profile_url ? <img src={person.profile_url} alt="" loading="lazy" /> : String(person.name || '?').trim().slice(0, 1).toUpperCase()}</span><strong dir="auto">{person.name}</strong><small dir="auto">{person.role}</small></article>)}</div></section></div>;
}

function SeriesView({ providerId, catalog, detail, detailLoading, selectedId, selectedSeason, onSeason, onToggle, onPlay, onFavorite, onAddToList, gridRef }) {
  const seasonNumbers = useMemo(() => [...new Set((detail?.episodes || []).map((episode) => episode.season))].sort((a, b) => a - b), [detail]);
  return (
    <>
      <div ref={gridRef} className="iptv-poster-grid">
        {catalog.items.map((series) => <PosterTile providerId={providerId} key={series.item_id} item={series} active={selectedId === series.item_id} onClick={() => onToggle(series)} onFavorite={onFavorite} onAddToList={onAddToList} />)}
      </div>
      {selectedId ? (
        <section className="iptv-series-detail">
          {detailLoading || !detail ? <div className="iptv-detail-loading"><Loader2 className="spin" size={18} /> Loading seasons...</div> : (
            <>
              <div className="iptv-series-summary">
                <div className="iptv-series-backdrop"><ProviderImage src={detail.backdrop_url ? iptvImage(providerId, 'series', detail.item_id, true) : iptvImage(providerId, 'series', detail.item_id)} fallbackSrc={iptvImage(providerId, 'series', detail.item_id)} alt={`${detail.name} artwork`} fallback={Tv} /></div>
                <div><p className="screen-kicker">Series details</p><h2 dir="auto">{detail.name}</h2><div className="iptv-series-meta">{detail.year ? <span>{String(detail.year).slice(0, 4)}</span> : null}{detail.rating ? <span><Star size={14} fill="currentColor" /> {detail.rating}</span> : null}{detail.genre ? <span dir="auto">{detail.genre}</span> : null}</div><p dir="auto">{detail.plot || 'No plot supplied by the provider.'}</p><div className="iptv-card-actions"><button type="button" className="btn btn-secondary" onClick={() => onFavorite(detail)}><Heart size={15} fill={detail.favorite ? 'currentColor' : 'none'} /> {detail.favorite ? 'Favorited' : 'Favorite'}</button><button type="button" className="btn btn-secondary" onClick={() => onAddToList(detail)}><ListPlus size={15} /> Add to list</button></div></div>
              </div>
              <div className="iptv-season-toolbar"><strong>Episodes</strong><div className="iptv-segmented">{seasonNumbers.map((season) => <button type="button" key={season} className={selectedSeason === season ? 'is-active' : ''} onClick={() => onSeason(season)}>Season {season}</button>)}</div></div>
              <div className="iptv-episode-list">{(detail.episodes || []).filter((episode) => episode.season === selectedSeason).map((episode) => <button type="button" key={episode.id} onClick={() => onPlay(detail, { kind: 'episode', itemId: episode.id, extension: episode.container_extension, title: `${detail.name} · S${episode.season} E${episode.episode} · ${episode.title}`, historyKind: 'series', historyId: detail.item_id })}><span>{episode.episode}</span><div><strong dir="auto">{episode.title}</strong><small dir="auto">{episode.plot || episode.duration || 'Play episode'}</small></div><Play size={18} /></button>)}</div>
            </>
          )}
        </section>
      ) : null}
      {!catalog.items.length ? <div className="iptv-empty"><Tv size={30} /><span>No series in this view.</span></div> : null}
    </>
  );
}

function PosterTile({ providerId, item, active, onClick, onFavorite, onAddToList }) {
  return (
    <article className={`iptv-poster-tile ${active ? 'is-active' : ''}`} onClick={onClick} tabIndex="0" onKeyDown={(event) => { if (event.key === 'Enter') onClick(); }}>
      <div><ProviderImage src={item.image_url ? iptvImage(providerId, item.kind, item.item_id) : ''} alt={`${item.name} poster`} fallback={Clapperboard} /><div className="iptv-poster-actions"><FavoriteButton item={item} onFavorite={onFavorite} /><ListActionButton item={item} onAddToList={onAddToList} /></div></div>
      <strong dir="auto">{mediaTitle(item)}</strong>
      <span>{item.year || (item.kind === 'live' ? 'Live channel' : 'Provider title')}</span>
    </article>
  );
}

function FavoriteButton({ item, onFavorite, className = '' }) {
  const action = item.favorite ? 'Remove from favorites' : 'Add to favorites';
  return (
    <button
      type="button"
      className={className}
      aria-label={`${action}: ${item.name}`}
      title={action}
      onClick={(event) => { event.stopPropagation(); onFavorite(item); }}
    >
      <Heart size={16} fill={item.favorite ? 'currentColor' : 'none'} />
    </button>
  );
}

function ListActionButton({ item, onAddToList, className = '' }) {
  return (
    <button
      type="button"
      className={className}
      aria-label={`Add ${item.name} to list`}
      title="Add to list"
      onClick={(event) => { event.stopPropagation(); onAddToList(item); }}
    >
      <ListPlus size={16} />
    </button>
  );
}

function SourceChooserModal({ chooser, onChoose, onClose }) {
  if (!chooser) return null;
  return (
    <div className="iptv-modal-backdrop" role="presentation" onClick={onClose}>
      <section className="iptv-source-dialog" role="dialog" aria-modal="true" aria-label="Choose provider source" onClick={(event) => event.stopPropagation()}>
        <header><div><p className="screen-kicker">Provider-local sources</p><h2 dir="auto">{chooser.movie.name || chooser.movie.title}</h2></div><button type="button" onClick={onClose} aria-label="Close source chooser"><X size={18} /></button></header>
        <div className="iptv-source-list">
          {chooser.sources.map((source) => (
            <button type="button" key={source.source_key} disabled={!source.available} onClick={() => onChoose(source)}>
              <span><strong dir="auto">{source.playlist_name || source.name}</strong><small>{[source.quality_claim ? `${source.quality_claim} provider claim` : '', source.dubbed_claim ? 'Dubbed claim' : '', source.subtitled_claim ? 'Subtitle claim' : ''].filter(Boolean).join(' · ') || 'Provider source'}</small></span>
              {source.available ? <Play size={18} /> : <small>Unavailable</small>}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function MatchMetadataModal({ movie, query, year, results, busy, onQuery, onYear, onSearch, onApply, onClose }) {
  if (!movie) return null;
  const orderedResults = [...results].sort((left, right) => {
    const rank = { validated: 0, plausible: 1, 'low-relevance': 2 };
    return (rank[left.result_class] ?? 1) - (rank[right.result_class] ?? 1) || Number(right.score || 0) - Number(left.score || 0);
  });
  return (
    <div className="iptv-modal-backdrop" role="presentation" onClick={onClose}>
      <section className="iptv-match-dialog" role="dialog" aria-modal="true" aria-label="Match IPTV movie metadata" onClick={(event) => event.stopPropagation()}>
        <header><div><p className="screen-kicker">Provider-local metadata</p><h2>Match metadata</h2><span dir="auto">{movie.provider_title || movie.name}</span></div><button type="button" onClick={onClose} aria-label="Close metadata matching"><X size={18} /></button></header>
        <div className="iptv-match-search">
          <label><span>Title</span><input value={query} onChange={(event) => onQuery(event.target.value)} dir="auto" /></label>
          <label><span>Year</span><input type="number" value={year} onChange={(event) => onYear(event.target.value)} /></label>
          <button type="button" className="btn btn-primary" disabled={busy || !query.trim()} onClick={onSearch}>{busy ? <Loader2 className="spin" size={15} /> : <Search size={15} />} Search TMDB</button>
        </div>
        <p className="iptv-match-warning">A selection is locked to this provider until you correct or remove it.</p>
        <div className="iptv-match-results">
          {orderedResults.map((candidate) => (
            <article key={candidate.tmdb_id} className={`is-${candidate.result_class || 'plausible'}`}>
              <div className="iptv-match-poster">{candidate.poster_url ? <img src={candidate.poster_url} alt="" /> : <Film size={24} />}</div>
              <div><strong dir="auto">{candidate.title}</strong><span>{candidate.year || 'Year unknown'} · TMDB {candidate.tmdb_id}</span><p dir="auto">{candidate.plot || 'No plot supplied by TMDB.'}</p></div>
              <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => onApply(candidate)}>{candidate.result_class === 'low-relevance' ? 'Review and use' : 'Use this match'}</button>
            </article>
          ))}
          {!busy && !results.length ? <div className="iptv-match-empty"><WandSparkles size={22} /><span>Search for the correct TMDB movie. Nothing is matched automatically from this dialog.</span></div> : null}
        </div>
      </section>
    </div>
  );
}

function FavoritesView({ providerId, catalog, followed = [], selectedId, detail, detailLoading, selectedSeason, onSeason, onToggle, onPlay, onFavorite, onAddToList, onOpenChannel, loading, gridRef }) {
  const channels = catalog.items.filter((item) => item.kind === 'live');
  const movies = catalog.items.filter((item) => item.kind === 'movie');
  const series = catalog.items.filter((item) => item.kind === 'series');
  if (!catalog.items.length && !loading) {
    return <div className="iptv-empty iptv-favorites-empty"><Heart size={34} /><strong>No favorites yet</strong><span>Saved channels, movies, and series will appear here.</span></div>;
  }
  return (
    <div className="iptv-favorites-view">
      {channels.length ? (
        <section className="iptv-favorite-section">
          <header><Radio size={18} /><h2>Channels</h2><span>{formatCount(channels.length)}</span></header>
          <div className="iptv-favorite-channels">
            {channels.map((channel) => (
              <article key={channel.item_id}>
                <button type="button" className="iptv-favorite-channel-main" onClick={() => onOpenChannel(channel)}>
                  <span className="iptv-channel-logo"><ProviderImage src={channel.image_url ? iptvImage(providerId, 'live', channel.item_id) : ''} alt="" fallback={Radio} /></span>
                  <strong dir="auto">{channel.name}</strong>
                  <Play size={17} fill="currentColor" />
                </button>
                <span className="iptv-favorite-channel-actions"><ListActionButton item={channel} onAddToList={onAddToList} /><FavoriteButton item={channel} onFavorite={onFavorite} /></span>
              </article>
            ))}
          </div>
        </section>
      ) : null}
      {movies.length ? (
        <section className="iptv-favorite-section">
          <header><Film size={18} /><h2>Movies</h2><span>{formatCount(movies.length)}</span></header>
          <MovieView providerId={providerId} catalog={{ ...catalog, items: movies }} followed={followed} selectedId={selectedId} detail={detail} detailLoading={detailLoading} onToggle={onToggle} onPlay={onPlay} onFavorite={onFavorite} onAddToList={onAddToList} gridRef={gridRef} />
        </section>
      ) : null}
      {series.length ? (
        <section className="iptv-favorite-section">
          <header><Tv size={18} /><h2>Series</h2><span>{formatCount(series.length)}</span></header>
          <SeriesView providerId={providerId} catalog={{ ...catalog, items: series }} detail={detail} detailLoading={detailLoading} selectedId={selectedId} selectedSeason={selectedSeason} onSeason={onSeason} onToggle={onToggle} onPlay={onPlay} onFavorite={onFavorite} onAddToList={onAddToList} gridRef={gridRef} />
        </section>
      ) : null}
    </div>
  );
}

function ProviderImage({ src, fallbackSrc = '', alt, fallback: Fallback }) {
  const [failedSources, setFailedSources] = useState(0);
  useEffect(() => setFailedSources(0), [src, fallbackSrc]);
  const secondarySource = fallbackSrc && fallbackSrc !== src ? fallbackSrc : '';
  const activeSource = failedSources === 0 ? src : failedSources === 1 ? secondarySource : '';
  if (!activeSource) return <Fallback size={24} />;
  return <img src={activeSource} alt={alt} loading="lazy" onError={() => setFailedSources((value) => value + 1)} />;
}

function Pagination({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return <div className="iptv-pagination"><button type="button" className="icon-button" onClick={() => onPage(Math.max(1, page - 1))} disabled={page <= 1} aria-label="Previous IPTV page"><ChevronLeft size={18} /></button><span>Page {page} of {pages}</span><button type="button" className="icon-button" onClick={() => onPage(Math.min(pages, page + 1))} disabled={page >= pages} aria-label="Next IPTV page"><ChevronRight size={18} /></button></div>;
}
