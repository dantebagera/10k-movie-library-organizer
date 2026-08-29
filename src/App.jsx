import {
  AlertTriangle,
  Bell,
  Bookmark,
  Bot,
  Compass,
  Database,
  Download,
  ExternalLink,
  Film,
  Home,
  Info,
  Library,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Power,
  RefreshCw,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  MonitorOff,
  Tv,
  X
} from 'lucide-react';
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from './api/client.js';
import { cancelPowerAction, fetchPowerStatus, requestPowerAction, resumePowerAction } from './api/power.js';
import { announceLibraryReconciled, CATALOG_GENERATION_CHANGED_EVENT, fetchOwnershipChecks, observeCatalogGeneration } from './api/library.js';
import { CATALOG_READY_EVENT, startCatalogEvents } from './api/catalogEvents.js';
import { fetchCanonicalMovieDetails, markMovieDetailsCacheStale, movieDetailsCacheKey } from './api/movieDetails.js';
import {
  fetchHomeTrailers,
  resolveHomeTrailerMovie,
  searchHomeTrailerMovieCandidates,
  searchYouTubeMovieTrailers
} from './api/homeTrailers.js';
import {
  fetchCurationJson,
  fetchUserListsCached
} from './api/curation.js';
import logoUrl from './assets/logo.svg';
import ExperimentalBadge from './components/ExperimentalBadge.jsx';
import PosterEditorModal from './components/PosterEditorModal.jsx';
import TorrentActions from './components/TorrentActions.jsx';
import {
  cx,
  formatCount,
  getUniqueOptions,
  movieKey,
  sectionFromPath,
  sortFollowedReleases,
  buildStreamTemplateUrl,
  streamTemplateTokens,
  toYouTubeEmbedUrl,
  topBarSearchEnabled,
  torrentSizeBytes,
  youtubeTrailerSearchUrl
} from './utils/appUtils.js';
import {
  buildOwnershipMap,
  discoverMoviePayload,
  listsForDiscoverMovie,
  ownedMovieFor,
  removeOwnershipPaths,
  replaceOwnershipScope
} from './discoverUtils.js';
import { applySystemListState, resolutionRank } from './utils/libraryUtils.js';
import { buildUpcomingHomeMovies, uniqueHomeMovies } from './utils/homeMovies.js';

const HelpWorkspace = lazy(() => import('./features/help/HelpWorkspace.jsx'));
const LibraryWorkspace = lazy(() => import('./features/library/LibraryWorkspace.jsx'));
const MovieListsWorkspace = lazy(() => import('./features/movie-lists/MovieListsWorkspace.jsx'));
const DiscoverWorkspace = lazy(() => import('./features/discover/DiscoverWorkspace.jsx'));
const AIControlWorkspace = lazy(() => import('./features/ai-control/AIControlWorkspace.jsx'));
const IPTVWorkspace = lazy(() => import('./features/iptv/IPTVWorkspace.jsx'));
const HomeWorkspace = lazy(() => import('./features/home/HomeWorkspace.jsx'));
const DownloadsWorkspace = lazy(() => import('./features/downloads/DownloadsWorkspace.jsx'));
const CleanupWorkspace = lazy(() => import('./features/cleanup/CleanupWorkspace.jsx'));
const SettingsWorkspace = lazy(() => import('./features/settings/SettingsWorkspace.jsx'));
const CardLab = lazy(() => import('./features/card-lab/CardLab.jsx'));
const StyleGuide = lazy(() => import('./features/styleguide/StyleGuide.jsx'));

const navItems = [
  {
    id: 'home',
    label: 'Home',
    icon: Home,
    accent: 'gold'
  },
  {
    id: 'library',
    label: 'Library',
    icon: Library,
    accent: 'blue'
  },
  {
    id: 'movie-lists',
    label: 'Movie Lists',
    icon: Bookmark,
    accent: 'gold'
  },
  {
    id: 'cleanup',
    label: 'Maintenance',
    icon: ShieldCheck,
    accent: 'amber'
  },
  {
    id: 'discover',
    label: 'Discover',
    icon: Compass,
    accent: 'violet'
  },
  {
    id: 'ai-control',
    label: 'AI Control',
    icon: Bot,
    accent: 'violet',
    experimental: true
  },
  {
    id: 'iptv',
    label: 'IPTV',
    icon: Tv,
    accent: 'gold'
  },
  {
    id: 'downloads',
    label: 'Downloads',
    icon: Download,
    accent: 'gold'
  },
  {
    id: 'help',
    label: 'Help',
    icon: Info,
    accent: 'gold'
  },
  {
    id: 'settings',
    label: 'Settings',
    icon: Settings,
    accent: 'cyan'
  }
];

const APP_VERSION = `v${import.meta.env.VITE_APP_VERSION || '0.0.0'}`;
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'cp.sidebarCollapsed';
let youtubeIframeApiPromise = null;

function loadYouTubeIframeApi() {
  if (typeof window === 'undefined') return Promise.resolve(null);
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (youtubeIframeApiPromise) return youtubeIframeApiPromise;

  youtubeIframeApiPromise = new Promise((resolve) => {
    let settled = false;
    let timeoutId = 0;
    const previousReady = window.onYouTubeIframeAPIReady;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeoutId);
      resolve(window.YT?.Player ? window.YT : null);
    };

    window.onYouTubeIframeAPIReady = () => {
      if (typeof previousReady === 'function') previousReady();
      finish();
    };

    if (!document.querySelector('script[src="https://www.youtube.com/iframe_api"]')) {
      const script = document.createElement('script');
      script.src = 'https://www.youtube.com/iframe_api';
      script.async = true;
      script.onerror = finish;
      document.head.appendChild(script);
    }
    timeoutId = window.setTimeout(finish, 8000);
  });

  return youtubeIframeApiPromise;
}

function storedSidebarCollapsed() {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

const fallbackMovies = [
  {
    tmdb_id: 155,
    title: 'The Dark Knight',
    year: '2008',
    genres: ['Action', 'Crime', 'Drama'],
    tmdb_rating: '9.0',
    language: 'English',
    country: 'US',
    country_flag: 'US',
    plot: 'Batman raises the stakes in Gotham as a criminal mastermind forces the city to confront chaos, loyalty, and the cost of order.',
    poster_url: ''
  },
  {
    tmdb_id: 27205,
    title: 'Inception',
    year: '2010',
    genres: ['Action', 'Science Fiction'],
    tmdb_rating: '8.4',
    language: 'English',
    country: 'US',
    country_flag: 'US',
    plot: 'A thief who steals secrets through shared dreams is offered a chance to erase his past by planting an idea in a target mind.',
    poster_url: ''
  },
  {
    tmdb_id: 129,
    title: 'Spirited Away',
    year: '2001',
    genres: ['Animation', 'Fantasy'],
    tmdb_rating: '8.5',
    language: 'Japanese',
    country: 'JP',
    country_flag: 'JP',
    plot: 'A young girl enters a mysterious spirit world and must find courage, patience, and a way back to her family.',
    poster_url: ''
  }
];

function playReleaseAlertSound() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();
    oscillator.type = 'sine';
    oscillator.frequency.setValueAtTime(740, ctx.currentTime);
    oscillator.frequency.setValueAtTime(980, ctx.currentTime + 0.12);
    gain.gain.setValueAtTime(0.0001, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.34);
    oscillator.connect(gain);
    gain.connect(ctx.destination);
    oscillator.start();
    oscillator.stop(ctx.currentTime + 0.36);
    window.setTimeout(() => ctx.close().catch(() => {}), 520);
  } catch {
    // Browsers may block startup audio until the user interacts with the page.
  }
}


function wait(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}



function reconcileSignature(state) {
  return [
    state?.status || 'idle',
    Number(state?.updated_at || 0),
    Number(state?.checked || 0),
    Number(state?.matched || 0),
    Number(state?.review || 0),
    Number(state?.pending || 0),
    Number(state?.failed || 0)
  ].join(':');
}


function App() {
  if (typeof window !== 'undefined' && window.location.pathname === '/card-lab') {
    return <Suspense fallback={null}><CardLab /></Suspense>;
  }

  if (typeof window !== 'undefined' && window.location.pathname === '/styleguide') {
    return <Suspense fallback={null}><StyleGuide /></Suspense>;
  }

  return <ArchiveApp />;
}

function ArchiveApp() {
  const [activeSection, setActiveSection] = useState(() => (
    typeof window === 'undefined' ? 'home' : sectionFromPath(window.location.pathname, navItems)
  ));
  const [startupWorkAllowed, setStartupWorkAllowed] = useState(() => activeSection !== 'library');
  useEffect(() => startCatalogEvents(), []);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(storedSidebarCollapsed);
  const [mountedSections, setMountedSections] = useState(() => new Set([activeSection]));
  const [stats, setStats] = useState(null);
  const [movies, setMovies] = useState([]);
  const [upcomingMovies, setUpcomingMovies] = useState([]);
  const [upcomingError, setUpcomingError] = useState('');
  const [homeTrailers, setHomeTrailers] = useState({
    title: 'New Trailers',
    sources: [],
    items: [],
    next_cursor: '',
    has_more: false,
    stale: false,
    fallback: false
  });
  const [homeTrailersError, setHomeTrailersError] = useState('');
  const [ownership, setOwnership] = useState({});
  const [selectedMovie, setSelectedMovie] = useState(null);
  const [details, setDetails] = useState({});
  const [followed, setFollowed] = useState([]);
  const [followedChecking, setFollowedChecking] = useState(false);
  const [loading, setLoading] = useState({
    stats: true,
    movies: true,
    upcoming: true,
    trailers: true,
    trailersMore: false
  });
  const [toast, setToast] = useState(null);
  const [powerStatus, setPowerStatus] = useState({ active_downloads: 0, plan: {} });
  const [torrentModal, setTorrentModal] = useState(null);
  const [trailerModal, setTrailerModal] = useState(null);
  const [streamModal, setStreamModal] = useState(null);
  const [streamingConfig, setStreamingConfig] = useState({
    enabled: true,
    label: 'Stream',
    url_template: 'https://streamimdb.ru/embed/movie/{tmdb_id}'
  });
  const [posterEditor, setPosterEditor] = useState(null);
  const [libraryQuery, setLibraryQuery] = useState('');
  const [discoverQuery, setDiscoverQuery] = useState('');
  const [browseQuery, setBrowseQuery] = useState('');
  const [discoverActiveTab, setDiscoverActiveTab] = useState('explore');
  const [discoverSearchRequest, setDiscoverSearchRequest] = useState(0);
  const [discoverRelationshipRequest, setDiscoverRelationshipRequest] = useState(null);
  const [discoverListRequest, setDiscoverListRequest] = useState(null);
  const [discoverMovieRequest, setDiscoverMovieRequest] = useState(null);
  const [cleanupInitialTab, setCleanupInitialTab] = useState('storage');
  const [libraryFilterRequest, setLibraryFilterRequest] = useState(null);
  const [libraryFileRequest, setLibraryFileRequest] = useState(null);
  const [homeLists, setHomeLists] = useState([]);
  const [continueWatching, setContinueWatching] = useState([]);
  const workspaceRef = useRef(null);
  const activeSectionRef = useRef(activeSection);
  const sectionScrollPositionsRef = useRef({});
  const sourceSearchTokenRef = useRef(0);
  const libraryReconcileSignatureRef = useRef('');
  const homeTrailersRequestRef = useRef(0);
  const followedOperationRef = useRef(null);
  const followedOwnershipQueuedRef = useRef(false);
  const followedOwnershipRetryDelayRef = useRef(0);

  useEffect(() => {
    setMountedSections((sections) => (
      sections.has(activeSection) ? sections : new Set([...sections, activeSection])
    ));
    if (activeSection !== 'library') setStartupWorkAllowed(true);
  }, [activeSection]);

  const allowStartupWork = useCallback(() => setStartupWorkAllowed(true), []);

  useEffect(() => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(sidebarCollapsed));
    } catch {
      // The sidebar still works for the current session when storage is unavailable.
    }
  }, [sidebarCollapsed]);

  useLayoutEffect(() => {
    activeSectionRef.current = activeSection;
    const workspace = workspaceRef.current;
    if (workspace && mountedSections.has(activeSection)) {
      workspace.scrollTop = sectionScrollPositionsRef.current[activeSection] || 0;
    }
  }, [activeSection, mountedSections]);

  useEffect(() => {
    const clearDetailCache = () => setDetails(markMovieDetailsCacheStale);
    window.addEventListener(CATALOG_GENERATION_CHANGED_EVENT, clearDetailCache);
    return () => window.removeEventListener(CATALOG_GENERATION_CHANGED_EVENT, clearDetailCache);
  }, []);

  const consumeLibraryFilterRequest = useCallback((requestId) => {
    setLibraryFilterRequest((current) => (
      current?.id === requestId ? null : current
    ));
  }, []);

  const consumeLibraryFileRequest = useCallback((requestId) => {
    setLibraryFileRequest((current) => (
      current?.id === requestId ? null : current
    ));
  }, []);

  const notify = useCallback((message, tone = 'success') => {
    setToast({ message, tone });
    window.clearTimeout(window.__cpToastTimer);
    window.__cpToastTimer = window.setTimeout(() => setToast(null), 3200);
  }, []);

  const refreshHealthStats = useCallback(async () => {
    try {
      setStats(await fetchJson('/api/stats'));
    } catch (error) {
      notify(`Stats unavailable: ${error.message}`, 'error');
    }
  }, [notify]);

  useEffect(() => {
    if (activeSection !== 'home') return undefined;
    const refreshHomeLibraryState = async (event) => {
      refreshHealthStats();
      const scope = uniqueHomeMovies(movies, upcomingMovies);
      setOwnership((state) => removeOwnershipPaths(state, event?.detail?.deleted_paths));
      if (!scope.length) return;
      try {
        const ownershipResults = await fetchOwnershipChecks(scope);
        setOwnership((state) => replaceOwnershipScope(state, scope, ownershipResults));
      } catch {
        // Home remains usable while best-effort ownership refresh is unavailable.
      }
    };
    window.addEventListener('cp-library-changed', refreshHomeLibraryState);
    return () => window.removeEventListener('cp-library-changed', refreshHomeLibraryState);
  }, [activeSection, movies, refreshHealthStats, upcomingMovies]);

  const loadHomeLists = useCallback(async (options = {}) => {
    try {
      const data = await fetchUserListsCached({ force: Boolean(options?.force) });
      setHomeLists(data.lists || []);
    } catch {
      setHomeLists([]);
    }
  }, []);

  useEffect(() => {
    if (activeSection !== 'home') return undefined;
    loadHomeLists();
    window.addEventListener('cp-curation-changed', loadHomeLists);
    return () => window.removeEventListener('cp-curation-changed', loadHomeLists);
  }, [activeSection, loadHomeLists]);

  const loadContinueWatching = useCallback(async () => {
    try {
      const data = await fetchJson('/api/player/continue-watching?limit=50');
      setContinueWatching(data.items || []);
    } catch {
      // Playback history is optional while the OS player remains selected.
    }
  }, []);

  const refreshPowerStatus = useCallback(async () => {
    try {
      setPowerStatus(await fetchPowerStatus());
    } catch {
      // Power controls remain available for a later retry if the backend is restarting.
    }
  }, []);

  useEffect(() => {
    refreshPowerStatus();
    const interval = window.setInterval(refreshPowerStatus, 5000);
    return () => window.clearInterval(interval);
  }, [refreshPowerStatus]);

  const handleFrontendReset = useCallback(() => {
    const resetUrl = new URL(window.location.href);
    resetUrl.searchParams.set('_cp_reset', Date.now().toString());
    window.location.replace(resetUrl.toString());
  }, []);

  const handlePowerAction = useCallback(async (action, afterDownload, closeQbittorrent = false) => {
    try {
      const status = await requestPowerAction(action, afterDownload, closeQbittorrent);
      setPowerStatus(status);
      notify(
        action === 'restart'
          ? 'Restarting Cinema Paradiso'
          : afterDownload
          ? `${action === 'device' ? 'Device' : 'Cinema Paradiso'} will turn off after the selected downloads are recoverably checkpointed`
          : `Turning off ${action === 'device' ? 'the device' : 'Cinema Paradiso'}`,
        'neutral'
      );
    } catch (error) {
      notify(error.message, 'error');
    }
  }, [notify]);

  const handleCancelPowerAction = useCallback(async () => {
    try {
      const status = await cancelPowerAction();
      setPowerStatus(status);
      notify('Scheduled power action cancelled', 'neutral');
    } catch (error) {
      notify(error.message, 'error');
    }
  }, [notify]);

  const handleResumePowerAction = useCallback(async () => {
    try {
      const status = await resumePowerAction();
      setPowerStatus(status);
      notify('Scheduled power action resumed', 'neutral');
    } catch (error) {
      notify(error.message, 'error');
    }
  }, [notify]);

  useEffect(() => {
    if (activeSection !== 'home') return undefined;
    loadContinueWatching();
    const timer = window.setInterval(loadContinueWatching, 15000);
    return () => window.clearInterval(timer);
  }, [activeSection, loadContinueWatching]);

  async function toggleHomeSystemList(systemType, movie, owned) {
    const payload = discoverMoviePayload(movie, owned);
    const active = listsForDiscoverMovie(movie, homeLists, owned).some((list) => (
      list.system_type === systemType || list.id === systemType
    ));
    const nextActive = !active;
    setHomeLists((current) => applySystemListState(current, systemType, payload, nextActive));
    try {
      await fetchCurationJson(`/api/user/system-lists/${encodeURIComponent(systemType)}/toggle`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movie: payload, active: nextActive })
      });
    } catch (error) {
      setHomeLists((current) => applySystemListState(current, systemType, payload, active));
      notify(error.message, 'error');
      return;
    }
    notify(`${movie.title} ${active ? 'removed from' : 'added to'} ${systemType === 'watched' ? 'Watched' : 'Watchlist'}`);
  }

  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    async function checkReconcile() {
      try {
        const state = await fetchJson('/api/library/reconcile');
        if (cancelled) return;
        observeCatalogGeneration(state.catalog_generation);
        const status = state.status || 'idle';
        const signature = reconcileSignature(state);
        const isNewCompletedRun = status === 'completed' && signature !== libraryReconcileSignatureRef.current;
        if (isNewCompletedRun) {
          libraryReconcileSignatureRef.current = signature;
          announceLibraryReconciled(state);
        }
        if (isNewCompletedRun && state.matched > 0) {
          notify(`${formatCount(state.matched)} new movie${state.matched === 1 ? '' : 's'} identified`, 'success');
        }
        if (status === 'running') {
          timer = window.setTimeout(checkReconcile, 2000);
        }
      } catch {
        // Reconciliation is non-blocking; Library still exposes manual Rescan Files.
      }
    }
    checkReconcile();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [notify]);

  useEffect(() => {
    if (activeSection !== 'home') return undefined;
    let cancelled = false;
    async function loadStats() {
      setLoading((state) => ({ ...state, stats: true }));
      try {
        const data = await fetchJson('/api/stats');
        if (!cancelled) setStats(data);
      } catch (error) {
        if (!cancelled) notify(`Stats unavailable: ${error.message}`, 'error');
      } finally {
        if (!cancelled) setLoading((state) => ({ ...state, stats: false }));
      }
    }
    loadStats();
    return () => {
      cancelled = true;
    };
  }, [activeSection, notify]);

  useEffect(() => {
    if (activeSection !== 'home') return undefined;
    let cancelled = false;
    async function loadHomeMovies() {
      setLoading((state) => ({ ...state, movies: true, upcoming: true }));
      setUpcomingError('');
      const [trendingResult, upcomingResult] = await Promise.allSettled([
        fetchJson('/api/tmdb/discover?list=trending_week&page=1&page_size=20'),
        fetchJson('/api/tmdb/discover?list=upcoming&page=1&page_size=100')
      ]);
      if (cancelled) return;

      const trendingMovies = trendingResult.status === 'fulfilled' && trendingResult.value.results?.length
        ? trendingResult.value.results.slice(0, 8)
        : fallbackMovies;
      if (trendingResult.status === 'rejected') {
        notify(`Discover feed unavailable: ${trendingResult.reason.message}`, 'error');
      }

      const upcoming = upcomingResult.status === 'fulfilled'
        ? buildUpcomingHomeMovies(upcomingResult.value.results || [], trendingMovies)
        : [];
      if (upcomingResult.status === 'rejected') {
        setUpcomingError(upcomingResult.reason.message);
      }

      setMovies(trendingMovies);
      setUpcomingMovies(upcoming);
      setSelectedMovie((current) => current || trendingMovies[0] || upcoming[0] || null);

      try {
        const ownershipResults = await fetchOwnershipChecks(
          uniqueHomeMovies(trendingMovies, upcoming)
        );
        if (!cancelled) setOwnership(buildOwnershipMap(ownershipResults));
      } catch {
        if (!cancelled) setOwnership({});
      } finally {
        if (!cancelled) {
          setLoading((state) => ({ ...state, movies: false, upcoming: false }));
        }
      }
    }
    loadHomeMovies();
    return () => {
      cancelled = true;
    };
  }, [activeSection, notify]);

  const loadHomeTrailers = useCallback(async ({ cursor = '', append = false } = {}) => {
    const requestId = homeTrailersRequestRef.current + 1;
    homeTrailersRequestRef.current = requestId;
    setLoading((state) => ({ ...state, trailers: !append, trailersMore: append }));
    setHomeTrailersError('');
    try {
      const data = await fetchHomeTrailers({ cursor });
      if (homeTrailersRequestRef.current !== requestId) return;
      setHomeTrailers((current) => {
        const incoming = data.items || [];
        const items = append
          ? [...current.items, ...incoming].filter((item, index, all) => (
              all.findIndex((candidate) => String(candidate.video_id) === String(item.video_id)) === index
            ))
          : incoming;
        return {
          title: data.title || 'New Trailers',
          sources: data.sources || current.sources || [],
          items,
          next_cursor: data.next_cursor || '',
          has_more: Boolean(data.has_more),
          stale: Boolean(data.stale),
          fallback: Boolean(data.fallback)
        };
      });
    } catch (error) {
      if (homeTrailersRequestRef.current === requestId) {
        setHomeTrailersError(error.message);
      }
    } finally {
      if (homeTrailersRequestRef.current === requestId) {
        setLoading((state) => ({ ...state, trailers: false, trailersMore: false }));
      }
    }
  }, []);

  useEffect(() => {
    if (activeSection !== 'home') return undefined;
    loadHomeTrailers();
    return () => {
      homeTrailersRequestRef.current += 1;
    };
  }, [activeSection, loadHomeTrailers]);

  const executeFollowedOperation = useCallback((mode = 'full', options = {}) => {
    if (followedOperationRef.current) {
      if (mode === 'ownership') followedOwnershipQueuedRef.current = true;
      return followedOperationRef.current;
    }
    const operation = (async () => {
      setFollowedChecking(true);
      try {
        const endpoint = mode === 'ownership'
          ? '/api/user/followed-releases/reconcile-owned'
          : '/api/user/followed-releases/check';
        const result = await fetchCurationJson(endpoint, { method: 'POST' });
        setFollowed(sortFollowedReleases(result.movies || []));
        if (result.scan_in_progress) {
          if (mode === 'ownership') {
            followedOwnershipQueuedRef.current = true;
            followedOwnershipRetryDelayRef.current = 2000;
          } else if (options.announceCompletion) {
            notify('A Following scan is already running', 'neutral');
          }
          return result;
        }
        const newlyAvailable = result.newly_available || [];
        const removedOwned = result.removed_owned || [];
        if (newlyAvailable.length) {
          notify(`${formatCount(newlyAvailable.length)} followed release${newlyAvailable.length === 1 ? '' : 's'} now available`, 'success');
          playReleaseAlertSound();
        }
        if (removedOwned.length) {
          notify(`${formatCount(removedOwned.length)} followed release${removedOwned.length === 1 ? '' : 's'} already in library`, 'neutral');
        } else if (options.announceCompletion) {
          notify(`Following scan complete - ${formatCount((result.movies || []).length)} still followed`, 'success');
        }
        return result;
      } catch (error) {
        notify(`Release watchlist ${mode === 'ownership' ? 'reconciliation' : 'scan'} failed: ${error.message}`, 'error');
        return null;
      } finally {
        followedOperationRef.current = null;
        setFollowedChecking(false);
        if (followedOwnershipQueuedRef.current) {
          followedOwnershipQueuedRef.current = false;
          const retryDelay = followedOwnershipRetryDelayRef.current;
          followedOwnershipRetryDelayRef.current = 0;
          window.setTimeout(() => executeFollowedOperation('ownership'), retryDelay);
        }
      }
    })();
    followedOperationRef.current = operation;
    return operation;
  }, [notify]);

  useEffect(() => {
    if (!startupWorkAllowed) return undefined;
    let cancelled = false;
    async function loadFollowedReleases() {
      try {
        const initial = await fetchCurationJson('/api/user/followed-releases');
        let serverMovies = initial.movies || [];
        if (!cancelled) setFollowed(sortFollowedReleases(serverMovies));
        let legacy = [];
        try {
          legacy = JSON.parse(localStorage.getItem('cp.followedMovies') || '[]');
        } catch {
          legacy = [];
        }
        if (legacy.length && !serverMovies.length) {
          for (const movie of legacy) {
            const migrated = await fetchCurationJson('/api/user/followed-releases', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ movie })
            });
            serverMovies = migrated.movies || serverMovies;
          }
          localStorage.removeItem('cp.followedMovies');
          if (!cancelled) setFollowed(sortFollowedReleases(serverMovies));
        }
        if (!cancelled) executeFollowedOperation('full');
      } catch (error) {
        if (!cancelled) notify(`Release watchlist unavailable: ${error.message}`, 'error');
      }
    }
    loadFollowedReleases();
    return () => { cancelled = true; };
  }, [executeFollowedOperation, notify, startupWorkAllowed]);

  useEffect(() => {
    const reconcileCommittedMovie = (event) => {
      if (event?.detail?.type !== 'catalog-ready') return;
      executeFollowedOperation('ownership');
    };
    window.addEventListener(CATALOG_READY_EVENT, reconcileCommittedMovie);
    return () => window.removeEventListener(CATALOG_READY_EVENT, reconcileCommittedMovie);
  }, [executeFollowedOperation]);

  const selectedOwnership = selectedMovie ? ownedMovieFor(selectedMovie, ownership) : null;
  const selectedDetailsKey = movieDetailsCacheKey(selectedMovie, selectedOwnership);
  const selectedDetails = selectedDetailsKey ? details[selectedDetailsKey] : null;
  const selectedMovieWithDetails = selectedMovie ? {
    ...selectedMovie,
    plot: selectedDetails?.plot || selectedDetails?.summary || selectedMovie.plot || '',
    genres: selectedDetails?.genres?.length ? selectedDetails.genres : selectedMovie.genres,
    release_date: selectedMovie.release_date || selectedDetails?.release_date || '',
    tmdb_rating: selectedDetails?.rating || selectedMovie.tmdb_rating,
    tmdb_vote_count: selectedDetails?.tmdb_vote_count ?? selectedMovie.tmdb_vote_count
  } : null;

  useEffect(() => {
    if (activeSection !== 'home' || loading.movies || !selectedDetailsKey || (details[selectedDetailsKey] && !details[selectedDetailsKey].stale)) return;
    let cancelled = false;
    async function loadDetails() {
      try {
        const data = await fetchCanonicalMovieDetails(selectedMovie, selectedOwnership);
        if (!cancelled) {
          setDetails((state) => ({ ...state, [selectedDetailsKey]: data }));
        }
      } catch (error) {
        if (!cancelled) setDetails((state) => ({ ...state, [selectedDetailsKey]: { error: error.message, cast: [], directors: [], trailer_url: '' } }));
      }
    }
    loadDetails();
    return () => {
      cancelled = true;
    };
  }, [activeSection, details, loading.movies, selectedDetailsKey, selectedMovie, selectedOwnership]);
  const streamingAvailable = Boolean(streamingConfig.enabled && String(streamingConfig.url_template || '').trim());
  const streamingLabel = String(streamingConfig.label || '').trim() || 'Stream';

  useEffect(() => {
    if (!startupWorkAllowed) return undefined;
    let cancelled = false;
    fetchJson('/api/streaming/config')
      .then((config) => {
        if (!cancelled) setStreamingConfig(config);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [startupWorkAllowed]);

  useEffect(() => {
    function handlePopState() {
      activateSection(sectionFromPath(window.location.pathname, navItems));
    }
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  function selectSection(id) {
    if (typeof window === 'undefined') return;
    activateSection(id);
    const path = id === 'home' ? '/' : `/${id}`;
    if (window.location.pathname !== path) {
      window.history.pushState({}, '', path);
    }
  }

  function reviewUnmatchedMetadata() {
    setCleanupInitialTab('identity');
    selectSection('cleanup');
  }

  function openCleanupTab(tab) {
    if (tab === 'low' || tab === 'upgrades') {
      setLibraryFilterRequest({ id: Date.now(), resolution: 'upgrade' });
      selectSection('library');
      return;
    }
    setCleanupInitialTab(tab);
    selectSection('cleanup');
  }

  function activateSection(id) {
    const currentSection = activeSectionRef.current;
    const workspace = workspaceRef.current;
    if (workspace && currentSection) {
      sectionScrollPositionsRef.current[currentSection] = workspace.scrollTop;
    }
    activeSectionRef.current = id;
    setMountedSections((sections) => sections.has(id) ? sections : new Set([...sections, id]));
    setActiveSection(id);
  }

  function openPersonInDiscover(movie, role, person) {
    if (!person?.id) return;
    setDiscoverActiveTab('explore');
    setDiscoverRelationshipRequest((current) => ({
      requestId: Number(current?.requestId || 0) + 1,
      type: 'person',
      source: 'Library',
      movie: {
        title: movie?.title || 'Movie',
        year: movie?.year || ''
      },
      role: ['actor', 'director', 'writer'].includes(role) ? role : 'actor',
      person: {
        id: person.id,
        name: person.name || 'Unknown person'
      }
    }));
    selectSection('discover');
  }

  function openOwnedFileDetails(owned) {
    const item = owned?.canonical_card || owned?.library_item || owned;
    if (!item?.path) return;
    setLibraryFileRequest({ id: Date.now(), path: item.path, item });
    selectSection('library');
  }

  function openCollectionInDiscover(movie, collection) {
    if (!collection?.id) return;
    setDiscoverActiveTab('explore');
    setDiscoverRelationshipRequest((current) => ({
      requestId: Number(current?.requestId || 0) + 1,
      type: 'collection',
      source: 'Collection',
      movie: {
        title: movie?.title || 'Movie',
        year: movie?.year || ''
      },
      collection: {
        id: collection.id,
        name: collection.name || 'TMDB collection'
      }
    }));
    selectSection('discover');
  }

  function openDiscoverList(list) {
    setDiscoverActiveTab('explore');
    setDiscoverListRequest((current) => ({
      requestId: Number(current?.requestId || 0) + 1,
      list
    }));
    selectSection('discover');
  }

  function openMovieInDiscover(movie, source = 'Rotten Tomatoes') {
    if (!movie?.tmdb_id) return;
    setDiscoverActiveTab('explore');
    setDiscoverMovieRequest((current) => ({
      requestId: Number(current?.requestId || 0) + 1,
      source,
      movie
    }));
    sectionScrollPositionsRef.current.discover = 0;
    selectSection('discover');
  }

  async function toggleFollow(movie) {
    const key = movieKey(movie);
    const existing = followed.find((item) => movieKey(item) === key);
    const payload = { title: movie.title, year: movie.year, tmdb_id: movie.tmdb_id, imdb_id: movie.imdb_id || '', poster_url: movie.poster_url, release_date: movie.release_date || '' };
    try {
      const data = await fetchCurationJson('/api/user/followed-releases', {
        method: existing ? 'DELETE' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ movie: existing || payload })
      });
      setFollowed(sortFollowedReleases(data.movies || []));
      notify(existing ? `${movie.title} removed from release watchlist` : `${movie.title} added to release watchlist`, existing ? 'neutral' : 'success');
    } catch (error) {
      notify(`Release watchlist update failed: ${error.message}`, 'error');
    }
  }

  async function playLocal(path, options = {}) {
    try {
      const result = await fetchJson('/api/player/play', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path_key: path, restart: Boolean(options.restart) })
      });
      if (options.restart) await loadContinueWatching();
      notify(
        result.fallback
          ? 'Cinema Paradiso Player was unavailable. Opened the OS player.'
          : result.mode === 'built_in'
            ? 'Playing in Cinema Paradiso Player'
            : 'Opening in the OS player',
        result.fallback ? 'neutral' : 'success'
      );
      return result;
    } catch (error) {
      notify(`Could not play file: ${error.message}`, 'error');
      return null;
    }
  }

  async function removeContinueWatching(item) {
    try {
      await fetchJson('/api/player/progress/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path_key: item.path_key })
      });
      setContinueWatching((current) => current.filter((entry) => entry.path_key !== item.path_key));
      notify(`${item.title} removed from Continue Watching`, 'neutral');
    } catch (error) {
      notify(`Could not remove progress: ${error.message}`, 'error');
    }
  }

  async function streamMovie(movie) {
    const template = String(streamingConfig.url_template || '').trim();
    if (!streamingConfig.enabled || !template) return;
    try {
      const ids = {
        tmdb_id: movie?.tmdb_id,
        imdb_id: movie?.imdb_id
      };
      if (streamTemplateTokens(template).includes('imdb_id') && !ids.imdb_id) {
        if (!ids.tmdb_id) throw new Error('Missing TMDB ID for IMDB lookup');
        const data = await fetchJson(`/api/tmdb/imdb_id?tmdb_id=${encodeURIComponent(ids.tmdb_id)}`);
        ids.imdb_id = data.imdb_id;
      }
      const embedUrl = buildStreamTemplateUrl(template, ids);
      setStreamModal({
        title: movie?.title || streamingLabel,
        year: movie?.year || '',
        embedUrl
      });
    } catch (error) {
      notify(`Stream unavailable: ${error.message}`, 'error');
    }
  }

  function openYouTubeVideo({
    title,
    year = '',
    sourceUrl = '',
    searchUrl = '',
    kicker = 'Trailer',
    activeVideo = null,
    playlistItems = [],
    homeTrailerSession = false,
    movie = null
  }) {
    setTrailerModal({
      title,
      year,
      kicker,
      sourceUrl,
      embedUrl: toYouTubeEmbedUrl(sourceUrl),
      searchUrl: searchUrl || sourceUrl || youtubeTrailerSearchUrl(title, year),
      activeVideo,
      playlistItems,
      homeTrailerSession,
      movie
    });
  }

  function openTrailerModal(movie, trailerUrl = '') {
    const title = movie?.title || 'Trailer';
    const year = movie?.year || '';
    openYouTubeVideo({
      title,
      year,
      sourceUrl: trailerUrl,
      searchUrl: youtubeTrailerSearchUrl(title, year),
      movie: { ...movie, title, year }
    });
  }

  function openHomeTrailerVideo(video) {
    openYouTubeVideo({
      title: video?.title || 'YouTube video',
      sourceUrl: video?.url || '',
      kicker: video?.source_name || 'New Trailers',
      activeVideo: video,
      playlistItems: homeTrailers?.items || [],
      homeTrailerSession: true
    });
  }

  async function findTorrent(movie, upgrade = false) {
    const title = movie?.title || '';
    const year = movie?.year || '';
    if (!title) return;
    const searchToken = sourceSearchTokenRef.current + 1;
    sourceSearchTokenRef.current = searchToken;
    setTorrentModal({
      title,
      year,
      tmdb_id: movie?.tmdb_id || '',
      imdb_id: movie?.imdb_id || '',
      upgrade,
      loading: true,
      error: '',
      variants: [],
      sourceSearch: null,
    });
    try {
      const payload = { title, year };
      if (movie?.imdb_id) payload.imdb_id = movie.imdb_id;
      if (movie?.tmdb_id) payload.tmdb_id = movie.tmdb_id;
      let data = await fetchJson('/api/explore/search/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      while (sourceSearchTokenRef.current === searchToken) {
        const running = data.status === 'running';
        setTorrentModal({
          title,
          year,
          tmdb_id: movie?.tmdb_id || '',
          imdb_id: movie?.imdb_id || '',
          upgrade,
          loading: running,
          error: data.status === 'error' ? (data.error || 'Source search failed') : '',
          variants: data.variants || [],
          sourceSearch: data
        });
        if (!running || !data.search_id) break;
        await wait(1000);
        data = await fetchJson(`/api/explore/search/jobs/${encodeURIComponent(data.search_id)}`);
      }
    } catch (error) {
      if (sourceSearchTokenRef.current !== searchToken) return;
      setTorrentModal({ title, year, upgrade, loading: false, error: error.message, variants: [] });
    }
  }

  async function searchTorrents(query) {
    const q = String(query || '').trim();
    if (!q) return;
    sourceSearchTokenRef.current += 1;
    setTorrentModal({ title: q, year: '', upgrade: false, loading: true, error: '', variants: [] });
    try {
      const data = await fetchJson(`/api/prowlarr/search?q=${encodeURIComponent(q)}`);
      setTorrentModal({ title: q, year: '', upgrade: false, loading: false, error: '', variants: data.results || [] });
    } catch (error) {
      setTorrentModal({ title: q, year: '', upgrade: false, loading: false, error: error.message, variants: [] });
    }
  }

  function closeTorrentModal() {
    sourceSearchTokenRef.current += 1;
    setTorrentModal(null);
  }

  function updateOwnedPoster(path, posterUrl) {
    setOwnership((state) => Object.fromEntries(
      Object.entries(state).map(([key, value]) => [
        key,
        value?.path === path ? { ...value, poster_url: posterUrl } : value
      ])
    ));
  }

  return (
    <div className={cx('app-shell', sidebarCollapsed && 'app-shell-sidebar-collapsed')}>
      <Sidebar
        activeSection={activeSection}
        collapsed={sidebarCollapsed}
        onSelect={selectSection}
        onToggleCollapsed={() => setSidebarCollapsed((collapsed) => !collapsed)}
        powerStatus={powerStatus}
        onFrontendReset={handleFrontendReset}
        onPowerAction={handlePowerAction}
        onPowerCancel={handleCancelPowerAction}
        onPowerResume={handleResumePowerAction}
      />
      <main ref={workspaceRef} className={cx('workspace', activeSection === 'home' && 'workspace-home', activeSection === 'downloads' && 'workspace-downloads')}>
        {activeSection !== 'home' && activeSection !== 'library' && activeSection !== 'movie-lists' && activeSection !== 'cleanup' && activeSection !== 'discover' && activeSection !== 'ai-control' && activeSection !== 'iptv' && activeSection !== 'help' && activeSection !== 'settings' && (
          <TopBar
            activeSection={activeSection}
            stats={stats}
            libraryQuery={libraryQuery}
            onLibraryQueryChange={setLibraryQuery}
            discoverQuery={discoverQuery}
            onDiscoverQueryChange={setDiscoverQuery}
            browseQuery={browseQuery}
            onBrowseQueryChange={setBrowseQuery}
            discoverActiveTab={discoverActiveTab}
            onDiscoverSearch={() => {
              selectSection('discover');
              setDiscoverSearchRequest((value) => value + 1);
            }}
          />
        )}
        {mountedSections.has('home') && (
          <div className="workspace-panel" hidden={activeSection !== 'home'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <HomeWorkspace
                stats={stats}
                loading={loading}
                movies={movies}
                upcomingMovies={upcomingMovies}
                upcomingError={upcomingError}
                homeTrailers={homeTrailers}
                homeTrailersError={homeTrailersError}
                ownership={ownership}
                followed={followed}
                followedChecking={followedChecking}
                onScanFollowed={() => executeFollowedOperation('full', { announceCompletion: true })}
                selectedMovie={selectedMovieWithDetails}
                selectedOwnership={selectedOwnership}
                selectedDetails={selectedDetails}
                onSelectSection={selectSection}
                onOpenDiscoverList={openDiscoverList}
                onOpenCleanup={openCleanupTab}
                onSelectMovie={setSelectedMovie}
                onOpenHomeTrailer={openHomeTrailerVideo}
                onRetryHomeTrailers={() => loadHomeTrailers()}
                onLoadMoreHomeTrailers={() => loadHomeTrailers({ cursor: homeTrailers.next_cursor, append: true })}
                onPlay={playLocal}
                onStream={streamMovie}
                streamingAvailable={streamingAvailable}
                streamingLabel={streamingLabel}
                onFindTorrent={findTorrent}
                onTrailer={openTrailerModal}
                onFollow={toggleFollow}
                userLists={homeLists}
                onToggleSystemList={toggleHomeSystemList}
                onEditPoster={(owned, movie) => setPosterEditor({ path: owned.path, title: movie.title })}
                onOpenFileDetails={openOwnedFileDetails}
                continueWatching={continueWatching}
                onResumeWatching={(item) => playLocal(item.path_key)}
                onRestartWatching={(item) => playLocal(item.path_key, { restart: true })}
                onRemoveWatching={removeContinueWatching}
              />
            </Suspense>
          </div>
        )}
        {mountedSections.has('library') && (
          <div className="workspace-panel" hidden={activeSection !== 'library'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <LibraryWorkspace
                onPlay={playLocal}
                onFindTorrent={findTorrent}
                onOpenTrailer={openTrailerModal}
                notify={notify}
                query={libraryQuery}
                setQuery={setLibraryQuery}
                followed={followed}
                onOpenDiscoverPerson={openPersonInDiscover}
                onOpenDiscoverCollection={openCollectionInDiscover}
                filterRequest={libraryFilterRequest}
                onFilterRequestConsumed={consumeLibraryFilterRequest}
                fileDetailsRequest={libraryFileRequest}
                onFileDetailsRequestConsumed={consumeLibraryFileRequest}
                onInitialReady={allowStartupWork}
              />
            </Suspense>
          </div>
        )}
        {mountedSections.has('movie-lists') && (
          <div className="workspace-panel" hidden={activeSection !== 'movie-lists'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <MovieListsWorkspace
                notify={notify}
                onPlay={playLocal}
                onFindTorrent={findTorrent}
                onOpenTrailer={openTrailerModal}
                onStream={streamMovie}
                streamingAvailable={streamingAvailable}
                streamingLabel={streamingLabel}
                followed={followed}
                onFollow={toggleFollow}
                onEditPoster={(owned, movie) => setPosterEditor({ path: owned.path, title: movie.title })}
                onOpenDiscoverPerson={openPersonInDiscover}
                onOpenDiscoverCollection={openCollectionInDiscover}
                onOpenFileDetails={openOwnedFileDetails}
              />
            </Suspense>
          </div>
        )}
        {mountedSections.has('discover') && (
          <div className="workspace-panel" hidden={activeSection !== 'discover'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <DiscoverWorkspace
                followed={followed}
                notify={notify}
                onPlay={playLocal}
                onStream={streamMovie}
                streamingAvailable={streamingAvailable}
                streamingLabel={streamingLabel}
                onFindTorrent={findTorrent}
                onOpenTrailer={openTrailerModal}
                onManualTorrentSearch={searchTorrents}
                onFollow={toggleFollow}
                tmdbQuery={discoverQuery}
                setTmdbQuery={setDiscoverQuery}
                browseQuery={browseQuery}
                setBrowseQuery={setBrowseQuery}
                searchRequest={discoverSearchRequest}
                relationshipRequest={discoverRelationshipRequest}
                listRequest={discoverListRequest}
                movieRequest={discoverMovieRequest}
                activeTab={discoverActiveTab}
                setActiveTab={setDiscoverActiveTab}
                onOpenFileDetails={openOwnedFileDetails}
              />
            </Suspense>
          </div>
        )}
        {mountedSections.has('downloads') && (
          <div className="workspace-panel" hidden={activeSection !== 'downloads'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <DownloadsWorkspace />
            </Suspense>
          </div>
        )}
        {mountedSections.has('ai-control') && (
          <div className="workspace-panel" hidden={activeSection !== 'ai-control'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <AIControlWorkspace
                followed={followed}
                notify={notify}
                onPlay={playLocal}
                onStream={streamMovie}
                streamingAvailable={streamingAvailable}
                streamingLabel={streamingLabel}
                onFindTorrent={findTorrent}
                onOpenTrailer={openTrailerModal}
                onFollow={toggleFollow}
                onEditPoster={(owned, movie) => setPosterEditor({ path: owned.path, title: movie.title })}
                onOpenDiscoverPerson={openPersonInDiscover}
                onOpenDiscoverCollection={openCollectionInDiscover}
                onOpenFileDetails={openOwnedFileDetails}
              />
            </Suspense>
          </div>
        )}
        {mountedSections.has('iptv') && (
          <div className="workspace-panel" hidden={activeSection !== 'iptv'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <IPTVWorkspace notify={notify} followed={followed} />
            </Suspense>
          </div>
        )}
        {mountedSections.has('help') && (
          <div className="workspace-panel" hidden={activeSection !== 'help'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <HelpWorkspace />
            </Suspense>
          </div>
        )}
        {mountedSections.has('cleanup') && (
          <div className="workspace-panel" hidden={activeSection !== 'cleanup'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <CleanupWorkspace
                notify={notify}
                onPlay={playLocal}
                onFindTorrent={findTorrent}
                initialTab={cleanupInitialTab}
                onHealthChanged={refreshHealthStats}
                onOpenLibraryUpgrades={() => openCleanupTab('upgrades')}
              />
            </Suspense>
          </div>
        )}
        {mountedSections.has('settings') && (
          <div className="workspace-panel" hidden={activeSection !== 'settings'}>
            <Suspense fallback={<div className="loading-state"><Loader2 className="spin" size={20} /></div>}>
              <SettingsWorkspace
                notify={notify}
                onReviewUnmatched={reviewUnmatchedMetadata}
                onReviewIdentities={() => openCleanupTab('identity')}
                onStreamingConfigChanged={setStreamingConfig}
              />
            </Suspense>
          </div>
        )}
      </main>
      {toast && (
        <div className={cx('toast', `toast-${toast.tone}`)} role="status">
          {toast.message}
        </div>
      )}
      {torrentModal && (
        <TorrentModal
          state={torrentModal}
          notify={notify}
          onClose={closeTorrentModal}
        />
      )}
      {trailerModal && (
        <TrailerModal
          state={trailerModal}
          followed={followed}
          onFollow={toggleFollow}
          onViewDetails={(movie, source) => {
            setTrailerModal(null);
            openMovieInDiscover(movie, source || 'Home Trailers');
          }}
          onClose={() => setTrailerModal(null)}
        />
      )}
      {streamModal && (
        <StreamPlayerModal
          state={streamModal}
          onClose={() => setStreamModal(null)}
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
    </div>
  );
}

function Sidebar({
  activeSection,
  collapsed,
  onSelect,
  onToggleCollapsed,
  powerStatus,
  onFrontendReset,
  onPowerAction,
  onPowerCancel,
  onPowerResume
}) {
  const [navTooltip, setNavTooltip] = useState(null);
  const [powerMenuOpen, setPowerMenuOpen] = useState(false);
  const [afterDownload, setAfterDownload] = useState(false);
  const [closeQbittorrent, setCloseQbittorrent] = useState(false);
  const plan = powerStatus?.plan || {};
  const planActive = ['armed', 'draining', 'paused', 'failed', 'dispatch_claimed', 'dispatch_failed', 'dispatch_unknown'].includes(plan.state);
  const cancellable = ['armed', 'paused', 'failed', 'dispatch_failed', 'dispatch_unknown'].includes(plan.state);
  const checkpointed = (plan.target_status || []).filter((target) => target.checkpointed).length;
  const canCloseQbittorrent = powerStatus?.torrent_client?.can_close === true;
  const planLabel = plan.action === 'device'
    ? 'SHUT DOWN DEVICE'
    : plan.action === 'restart' ? 'RESTART' : 'TURN OFF';

  useEffect(() => {
    if (!canCloseQbittorrent) setCloseQbittorrent(false);
  }, [canCloseQbittorrent]);

  const showNavTooltip = useCallback((label, event) => {
    if (!collapsed) return;
    const anchor = event.currentTarget.getBoundingClientRect();
    setNavTooltip({
      label,
      top: anchor.top + anchor.height / 2
    });
  }, [collapsed]);

  const hideNavTooltip = useCallback(() => {
    setNavTooltip((current) => (
      current ? { ...current, label: '' } : null
    ));
  }, []);

  const selectNavItem = useCallback((section) => {
    hideNavTooltip();
    onSelect(section);
  }, [hideNavTooltip, onSelect]);

  const toggleCollapsed = useCallback(() => {
    setNavTooltip(null);
    onToggleCollapsed();
  }, [onToggleCollapsed]);

  useEffect(() => {
    if (!collapsed) setNavTooltip(null);
  }, [collapsed]);

  return (
    <>
      <aside className={cx('sidebar', collapsed && 'sidebar-collapsed')} aria-label="Primary navigation">
      <div className="brand-lockup">
        <img src={logoUrl} alt="" className="brand-mark" />
        <div>
          <div className="brand-title">Cinema</div>
          <div className="brand-title brand-title-accent">Paradiso</div>
        </div>
        <button
          type="button"
          className="sidebar-toggle"
          onClick={toggleCollapsed}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>
      <nav className="nav-stack" onScroll={hideNavTooltip}>
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = activeSection === item.id;
          return (
            <div key={item.id} className="nav-group">
              <button
                className={cx('nav-item', active && 'nav-item-active', `accent-${item.accent}`)}
                onClick={() => selectNavItem(item.id)}
                onMouseEnter={(event) => showNavTooltip(item.label, event)}
                onMouseLeave={hideNavTooltip}
                onFocus={(event) => showNavTooltip(item.label, event)}
                onBlur={hideNavTooltip}
                type="button"
                aria-label={collapsed ? item.label : undefined}
              >
                <span className="nav-icon-wrap"><Icon size={22} /></span>
                <span className="nav-label">
                  {item.label}
                  {item.experimental && <ExperimentalBadge className="ai-control-nav-badge" />}
                </span>
              </button>
            </div>
          );
        })}
      </nav>
      <div className={cx('sidebar-power-zone', planActive && 'sidebar-power-zone-active')}>
        <button
          type="button"
          className="sidebar-power-button"
          aria-label="Power options"
          aria-expanded={powerMenuOpen}
          title="Power options"
          onClick={() => setPowerMenuOpen((open) => !open)}
        >
          <Power size={21} />
          <span>{planActive ? 'Power action active' : 'Power'}</span>
        </button>
        <div
          className="sidebar-footer"
          title={collapsed ? APP_VERSION : undefined}
        >
          <span className="sidebar-version">{APP_VERSION}</span>
        </div>
        {powerMenuOpen && (
          <div className={cx('sidebar-power-menu', collapsed && 'sidebar-power-menu-collapsed')} role="menu" aria-label="Power options">
            <div className="sidebar-power-menu-heading">
              <strong>Power</strong>
              {planActive && <span>{plan.state.replace('_', ' ')}</span>}
            </div>
            {planActive ? (
              <div className="sidebar-power-plan">
                <strong>{planLabel}</strong>
                <span>{plan.detail}</span>
                {plan.action === 'cp' && plan.close_qbittorrent && <small>qBittorrent will also close</small>}
                {!!plan.target_status?.length && (
                  <small>{checkpointed} of {plan.target_status.length} downloads checkpointed</small>
                )}
                {plan.state === 'paused' && (
                  <button type="button" className="sidebar-power-action" onClick={onPowerResume}>Resume scheduled action</button>
                )}
                {cancellable && (
                  <button type="button" className="sidebar-power-action sidebar-power-cancel" onClick={onPowerCancel}>Cancel scheduled action</button>
                )}
              </div>
            ) : (
              <>
                <div className="sidebar-power-runtime-actions">
                  <button type="button" className="sidebar-power-action" role="menuitem" onClick={onFrontendReset}>
                    <RefreshCw size={18} /> <span>RESET</span>
                  </button>
                  <button type="button" className="sidebar-power-action" role="menuitem" onClick={() => onPowerAction('restart', false, false)}>
                    <RotateCcw size={18} /> <span>RESTART</span>
                  </button>
                </div>
                <label className="sidebar-power-after">
                  <input
                    type="checkbox"
                    checked={afterDownload}
                    disabled={!powerStatus?.active_downloads}
                    onChange={(event) => setAfterDownload(event.target.checked)}
                  />
                  <span>After current downloads finish</span>
                </label>
                {!powerStatus?.active_downloads && <small className="sidebar-power-note">No active CP downloads</small>}
                <label className="sidebar-power-after sidebar-power-torrent-option">
                  <input
                    type="checkbox"
                    checked={closeQbittorrent}
                    disabled={!canCloseQbittorrent}
                    onChange={(event) => setCloseQbittorrent(event.target.checked)}
                  />
                  <span>Close qBittorrent too</span>
                </label>
                {!canCloseQbittorrent && <small className="sidebar-power-note">System qBittorrent is not owned by CP</small>}
                <button type="button" className="sidebar-power-action" role="menuitem" onClick={() => onPowerAction('cp', afterDownload, closeQbittorrent)}>
                  <Power size={18} /> <span>TURN OFF</span>
                </button>
                <button type="button" className="sidebar-power-action" role="menuitem" onClick={() => onPowerAction('device', afterDownload, false)}>
                  <MonitorOff size={18} /> <span>SHUT DOWN DEVICE</span>
                </button>
              </>
            )}
          </div>
        )}
      </div>
      </aside>
      {collapsed && (
        <div
          className={cx('sidebar-tooltip', navTooltip?.label && 'sidebar-tooltip-visible')}
          role="tooltip"
          aria-hidden={!navTooltip?.label}
          style={{ top: `${navTooltip?.top ?? 0}px` }}
        >
          {navTooltip?.label || ''}
        </div>
      )}
    </>
  );
}



function TrailerModal({ state, followed = [], onFollow, onViewDetails, onClose }) {
  const {
    title,
    year,
    embedUrl,
    searchUrl,
    kicker = 'Trailer',
    activeVideo: initialVideo,
    playlistItems = [],
    homeTrailerSession = false,
    movie: requestedMovie = null
  } = state;
  const [activeVideo, setActiveVideo] = useState(initialVideo);
  const [fallbackVideo, setFallbackVideo] = useState(null);
  const [trailerSearch, setTrailerSearch] = useState({ status: 'idle', candidates: [], error: '' });
  const [playerError, setPlayerError] = useState('');
  const [showEndRecommendations, setShowEndRecommendations] = useState(false);
  const [movieResolution, setMovieResolution] = useState({ status: 'idle', hint: null, candidates: [], movie: null });
  const [manualMatchOpen, setManualMatchOpen] = useState(false);
  const [manualTitle, setManualTitle] = useState('');
  const [manualYear, setManualYear] = useState('');
  const [manualCandidates, setManualCandidates] = useState([]);
  const [manualLoading, setManualLoading] = useState(false);
  const [manualError, setManualError] = useState('');
  const iframeRef = useRef(null);
  const playerRef = useRef(null);
  const resolutionCacheRef = useRef(new Map());
  const manualSearchAbortRef = useRef(null);
  const trailerSearchAbortRef = useRef(null);
  const activeTitle = activeVideo?.title || title;
  const activeEmbedUrl = activeVideo?.url
    ? toYouTubeEmbedUrl(activeVideo.url)
    : fallbackVideo?.url
      ? toYouTubeEmbedUrl(fallbackVideo.url)
      : embedUrl;
  const titleLabel = [activeTitle, year].filter(Boolean).join(' ');
  const isMovieTrailer = kicker === 'Trailer';
  const isHomeTrailerSession = Boolean(homeTrailerSession && activeVideo?.video_id);
  const activeKicker = isHomeTrailerSession ? (activeVideo?.source_name || 'New Trailers') : kicker;
  const matchedMovie = movieResolution.movie;
  const matchedMovieFollowed = Boolean(matchedMovie && followed.some((movie) => (
    (matchedMovie.tmdb_id && String(movie?.tmdb_id || '') === String(matchedMovie.tmdb_id))
    || movieKey(movie) === movieKey(matchedMovie)
  )));
  const recommendations = useMemo(() => {
    if (!playlistItems.length) return [];
    const currentId = String(activeVideo?.video_id || '');
    const currentIndex = playlistItems.findIndex((item) => String(item?.video_id || '') === currentId);
    const rotated = currentIndex >= 0
      ? [...playlistItems.slice(currentIndex + 1), ...playlistItems.slice(0, currentIndex)]
      : playlistItems;
    return rotated
      .filter((item) => item?.video_id && String(item.video_id) !== currentId)
      .slice(0, 4);
  }, [activeVideo?.video_id, playlistItems]);

  useEffect(() => {
    setActiveVideo(initialVideo);
  }, [initialVideo]);

  const requestTrailerAlternatives = useCallback(() => {
    if (!isMovieTrailer || !requestedMovie?.title) return;
    trailerSearchAbortRef.current?.abort();
    const controller = new AbortController();
    trailerSearchAbortRef.current = controller;
    setTrailerSearch({ status: 'loading', candidates: [], error: '' });
    searchYouTubeMovieTrailers({ title: requestedMovie.title, year: requestedMovie.year }, { signal: controller.signal })
      .then((result) => {
        if (trailerSearchAbortRef.current !== controller) return;
        if (result.status === 'matched' && result.video) {
          setFallbackVideo(result.video);
          setTrailerSearch({ status: 'matched', candidates: result.candidates || [], error: '' });
        } else {
          setTrailerSearch({ status: result.status || 'choose', candidates: result.candidates || [], error: '' });
        }
      })
      .catch((error) => {
        if (error?.name !== 'AbortError' && trailerSearchAbortRef.current === controller) {
          setTrailerSearch({ status: 'error', candidates: [], error: error.message });
        }
      })
      .finally(() => {
        if (trailerSearchAbortRef.current === controller) trailerSearchAbortRef.current = null;
      });
  }, [isMovieTrailer, requestedMovie?.title, requestedMovie?.year]);

  useEffect(() => {
    setFallbackVideo(null);
    setTrailerSearch({ status: 'idle', candidates: [], error: '' });
    setPlayerError('');
    trailerSearchAbortRef.current?.abort();
    if (!isMovieTrailer || embedUrl || !requestedMovie?.title) return undefined;
    requestTrailerAlternatives();
    return () => trailerSearchAbortRef.current?.abort();
  }, [embedUrl, isMovieTrailer, requestedMovie?.title, requestedMovie?.year, requestTrailerAlternatives]);

  useEffect(() => {
    setPlayerError('');
  }, [activeEmbedUrl]);

  useEffect(() => {
    if (!isHomeTrailerSession) {
      setMovieResolution({ status: 'idle', hint: null, candidates: [], movie: null });
      return undefined;
    }

    manualSearchAbortRef.current?.abort();
    setManualMatchOpen(false);
    setManualLoading(false);
    setManualError('');
    const videoId = String(activeVideo.video_id);
    const cached = resolutionCacheRef.current.get(videoId);
    if (cached) {
      setMovieResolution(cached);
      setManualTitle(cached.hint?.title || '');
      setManualYear(cached.hint?.year || '');
      setManualCandidates(cached.candidates || []);
      return undefined;
    }

    const controller = new AbortController();
    setMovieResolution({ status: 'loading', hint: null, candidates: [], movie: null });
    resolveHomeTrailerMovie(activeVideo.title, { signal: controller.signal })
      .then((resolution) => {
        resolutionCacheRef.current.set(videoId, resolution);
        setMovieResolution(resolution);
        setManualTitle(resolution.hint?.title || '');
        setManualYear(resolution.hint?.year || '');
        setManualCandidates(resolution.candidates || []);
      })
      .catch((error) => {
        if (error?.name === 'AbortError') return;
        const resolution = {
          status: 'error',
          hint: { title: activeVideo.title || '', year: '' },
          candidates: [],
          movie: null,
          error: error.message
        };
        resolutionCacheRef.current.set(videoId, resolution);
        setMovieResolution(resolution);
        setManualTitle(activeVideo.title || '');
        setManualYear('');
        setManualCandidates([]);
      });
    return () => controller.abort();
  }, [activeVideo?.video_id, activeVideo?.title, isHomeTrailerSession]);

  useEffect(() => () => {
    manualSearchAbortRef.current?.abort();
    trailerSearchAbortRef.current?.abort();
  }, []);

  useEffect(() => {
    setShowEndRecommendations(false);
    if (!activeEmbedUrl || !iframeRef.current) return undefined;

    let disposed = false;
    let pollId = 0;
    let player = null;

    loadYouTubeIframeApi().then((YouTube) => {
      if (disposed || !YouTube?.Player || !iframeRef.current) return;
      player = new YouTube.Player(iframeRef.current, {
        events: {
          onReady: ({ target }) => {
            if (!recommendations.length) return;
            pollId = window.setInterval(() => {
              const duration = Number(target.getDuration?.() || 0);
              const elapsed = Number(target.getCurrentTime?.() || 0);
              const threshold = Math.min(20, Math.max(6, duration * 0.5));
              if (duration > 0 && duration - elapsed <= threshold) {
                setShowEndRecommendations(true);
              }
            }, 500);
          },
          onStateChange: ({ data }) => {
            if (data === 0 && recommendations.length) setShowEndRecommendations(true);
          },
          onError: ({ data }) => {
            if (isMovieTrailer && requestedMovie?.title) {
              setPlayerError('YouTube cannot play this upload in the embedded player. Try another official trailer.');
              requestTrailerAlternatives();
            } else if (recommendations.length) {
              setShowEndRecommendations(true);
            }
          }
        }
      });
      playerRef.current = player;
    });

    return () => {
      disposed = true;
      window.clearInterval(pollId);
      if (playerRef.current === player) playerRef.current = null;
      player?.destroy?.();
    };
  }, [activeEmbedUrl, isMovieTrailer, recommendations.length, requestTrailerAlternatives, requestedMovie?.title]);

  const selectRecommendation = (video) => {
    setShowEndRecommendations(false);
    setActiveVideo(video);
  };

  const chooseTrailerAlternative = (video) => {
    setPlayerError('');
    setFallbackVideo(video);
  };

  const trailerAlternativePanel = isMovieTrailer && requestedMovie?.title ? (
    <section className="trailer-alternative-panel" aria-live="polite">
      <div>
        {playerError ? <strong>{playerError}</strong> : <span>Having trouble with this trailer?</span>}
        <small>Cinema Paradiso only keeps this choice for this open trailer session.</small>
      </div>
      <button type="button" className="btn btn-secondary" onClick={requestTrailerAlternatives} disabled={trailerSearch.status === 'loading'}>
        {trailerSearch.status === 'loading' ? <Loader2 className="spin" size={15} /> : <RefreshCw size={15} />} Try another trailer
      </button>
      {trailerSearch.status === 'choose' && trailerSearch.candidates.length ? (
        <div className="trailer-fallback-candidates">
          {trailerSearch.candidates.map((video) => (
            <button type="button" key={video.video_id} onClick={() => chooseTrailerAlternative(video)}>
              <img src={video.thumbnail_url} alt="" />
              <span><strong>{video.title}</strong><small>{video.channel_title || 'YouTube'}</small></span>
            </button>
          ))}
        </div>
      ) : trailerSearch.status === 'error' ? <small className="trailer-alternative-error">{trailerSearch.error}</small> : null}
    </section>
  ) : null;

  const openManualMatch = () => {
    setManualTitle(movieResolution.hint?.title || activeTitle);
    setManualYear(movieResolution.hint?.year || '');
    setManualCandidates(movieResolution.candidates || []);
    setManualError('');
    setManualMatchOpen(true);
  };

  const runManualSearch = async (event) => {
    event.preventDefault();
    const query = manualTitle.trim();
    if (!query) return;
    manualSearchAbortRef.current?.abort();
    const controller = new AbortController();
    manualSearchAbortRef.current = controller;
    setManualLoading(true);
    setManualError('');
    try {
      const candidates = await searchHomeTrailerMovieCandidates(query, manualYear.trim(), { signal: controller.signal });
      setManualCandidates(candidates);
      if (!candidates.length) setManualError('TMDB returned no movies for that search.');
    } catch (error) {
      if (error?.name !== 'AbortError') setManualError(error.message);
    } finally {
      if (manualSearchAbortRef.current === controller) {
        manualSearchAbortRef.current = null;
        setManualLoading(false);
      }
    }
  };

  const chooseManualMovie = (movie) => {
    const resolution = {
      status: 'matched',
      hint: movieResolution.hint || { title: manualTitle, year: manualYear },
      candidates: manualCandidates,
      movie,
      reason: 'manual'
    };
    resolutionCacheRef.current.set(String(activeVideo.video_id), resolution);
    setMovieResolution(resolution);
    setManualMatchOpen(false);
    setManualError('');
  };

  return (
    <div className="modal-backdrop trailer-backdrop" role="presentation" onClick={onClose}>
      <section
        className={cx('trailer-dialog', isHomeTrailerSession && 'trailer-dialog-home')}
        role="dialog"
        aria-modal="true"
        aria-label={isMovieTrailer ? `Trailer for ${titleLabel}` : `${activeKicker}: ${titleLabel}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="dialog-header trailer-dialog-header">
          <div>
            <p className="screen-kicker">{activeKicker}</p>
            <h2>{titleLabel}</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label={isMovieTrailer ? 'Stop trailer' : 'Stop video'}>
            <X size={18} />
          </button>
        </div>
        {activeEmbedUrl ? (
          <>
          <div className="trailer-player-shell">
            <iframe
              key={activeEmbedUrl}
              ref={iframeRef}
              title={isMovieTrailer ? `${titleLabel} trailer` : titleLabel}
              src={`${activeEmbedUrl}&enablejsapi=1`}
              allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
              allowFullScreen
            />
            {showEndRecommendations && recommendations.length ? (
              <TrailerRecommendationGrid
                className="trailer-end-recommendations"
                title="Continue with more trailers"
                videos={recommendations}
                onSelect={selectRecommendation}
              />
            ) : null}
          </div>
          {trailerAlternativePanel}
          {isHomeTrailerSession && (
            <section className="trailer-movie-match" aria-label="Matched movie actions">
              {movieResolution.status === 'loading' ? (
                <div className="trailer-movie-match-status">
                  <Loader2 className="spin" size={18} />
                  <div><strong>Matching this trailer to TMDB…</strong><small>Playback continues while Cinema Paradiso checks the movie.</small></div>
                </div>
              ) : matchedMovie ? (
                <>
                  <div className="trailer-movie-identity">
                    {matchedMovie.poster_url ? <img src={matchedMovie.poster_url} alt="" /> : <span><Film size={20} /></span>}
                    <div>
                      <small>{movieResolution.reason === 'manual' ? 'Manually matched movie' : 'Matched TMDB movie'}</small>
                      <strong>{matchedMovie.title}</strong>
                      <span>{matchedMovie.year || matchedMovie.release_date || 'Release date unavailable'}</span>
                    </div>
                  </div>
                  <div className="trailer-movie-actions">
                    <button type="button" className="btn btn-primary" onClick={() => onFollow?.(matchedMovie)}>
                      <Bell size={15} /> {matchedMovieFollowed ? 'Following' : 'Follow'}
                    </button>
                    <button type="button" className="btn btn-secondary" onClick={() => onViewDetails?.(matchedMovie, activeVideo?.source_name || 'Home Trailers')}>
                      <Compass size={15} /> View details
                    </button>
                    <button type="button" className="ghost-link ghost-link-small" onClick={openManualMatch}>Change match</button>
                  </div>
                </>
              ) : (
                <>
                  <div className="trailer-movie-match-status">
                    <AlertTriangle size={18} />
                    <div>
                      <strong>No confident TMDB match</strong>
                      <small>{movieResolution.error || 'Choose the movie manually before following it or opening its card.'}</small>
                    </div>
                  </div>
                  <button type="button" className="btn btn-secondary" onClick={openManualMatch}>Manual match</button>
                </>
              )}
            </section>
          )}
          {isHomeTrailerSession && manualMatchOpen && (
            <section className="trailer-manual-match" aria-label="Manually match this trailer">
              <div className="trailer-manual-match-heading">
                <div><p className="screen-kicker">TMDB movie match</p><strong>Choose the movie represented by this trailer</strong></div>
                <button type="button" className="inspector-close" onClick={() => setManualMatchOpen(false)} aria-label="Close manual match"><X size={16} /></button>
              </div>
              <form onSubmit={runManualSearch} className="trailer-manual-search">
                <input value={manualTitle} onChange={(event) => setManualTitle(event.target.value)} aria-label="Movie title" placeholder="Movie title" />
                <input value={manualYear} onChange={(event) => setManualYear(event.target.value)} aria-label="Release year" placeholder="Year" inputMode="numeric" />
                <button type="submit" className="btn btn-secondary" disabled={manualLoading || !manualTitle.trim()}>
                  {manualLoading ? <Loader2 className="spin" size={15} /> : <Search size={15} />} Search TMDB
                </button>
              </form>
              {manualError && <small className="trailer-manual-error">{manualError}</small>}
              {manualCandidates.length > 0 && (
                <div className="trailer-manual-candidates">
                  {manualCandidates.slice(0, 6).map((movie) => (
                    <button type="button" key={movie.tmdb_id} onClick={() => chooseManualMovie(movie)} aria-label={`Match trailer to ${movie.title} ${movie.year || ''}`.trim()}>
                      {movie.poster_url ? <img src={movie.poster_url} alt="" /> : <span><Film size={20} /></span>}
                      <strong>{movie.title}</strong>
                      <small>{movie.year || 'Year unavailable'}</small>
                    </button>
                  ))}
                </div>
              )}
            </section>
          )}
          {recommendations.length ? (
            <TrailerRecommendationGrid
              className="trailer-session-recommendations"
              title="More trailers"
              videos={recommendations}
              onSelect={selectRecommendation}
            />
          ) : null}
          </>
        ) : (
          <div className="trailer-missing">
            {trailerSearch.status === 'loading' ? (
              <>
                <Loader2 className="spin" size={32} />
                <h3>Finding an embeddable trailer</h3>
                <p>TMDB had no trailer, so Cinema Paradiso is checking YouTube now.</p>
              </>
            ) : trailerSearch.status === 'choose' && trailerSearch.candidates.length ? (
              <>
                <Film size={32} />
                <h3>Choose the correct trailer</h3>
                <p>YouTube returned several possible matches. Nothing will be remembered permanently.</p>
                <div className="trailer-fallback-candidates">
                  {trailerSearch.candidates.map((video) => (
                    <button type="button" key={video.video_id} onClick={() => chooseTrailerAlternative(video)}>
                      <img src={video.thumbnail_url} alt="" />
                      <span><strong>{video.title}</strong><small>{video.channel_title || 'YouTube'}</small></span>
                    </button>
                  ))}
                </div>
                <a className="ghost-link ghost-link-small" href={searchUrl} target="_blank" rel="noreferrer">
                  <ExternalLink size={15} /> Search YouTube manually
                </a>
              </>
            ) : (
              <>
                <Film size={32} />
                <h3>No embeddable video found</h3>
                <p>{trailerSearch.error || 'Cinema Paradiso could not identify a safe automatic match.'}</p>
                <a className="btn btn-secondary" href={searchUrl} target="_blank" rel="noreferrer">
                  <ExternalLink size={15} /> Open YouTube
                </a>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function TrailerRecommendationGrid({ className, title, videos, onSelect }) {
  return (
    <section className={className} aria-label={title}>
      <p className="screen-kicker">{title}</p>
      <div>
        {videos.map((video) => (
          <button
            type="button"
            key={video.video_id}
            onClick={() => onSelect(video)}
            aria-label={`Play ${video.title} in this player`}
          >
            {video.thumbnail_url ? <img src={video.thumbnail_url} alt="" /> : <Film size={22} />}
            <strong dir="auto">{video.title}</strong>
          </button>
        ))}
      </div>
    </section>
  );
}

function StreamPlayerModal({ state, onClose }) {
  const { title, year, embedUrl } = state;
  const titleLabel = [title, year].filter(Boolean).join(' ');
  const [streamStatusVisible, setStreamStatusVisible] = useState(true);
  const [streamLoaded, setStreamLoaded] = useState(false);
  const [streamSlow, setStreamSlow] = useState(false);

  useEffect(() => {
    setStreamStatusVisible(true);
    setStreamLoaded(false);
    setStreamSlow(false);
    const slowTimer = window.setTimeout(() => setStreamSlow(true), 12000);
    const hideTimer = window.setTimeout(() => setStreamStatusVisible(false), 30000);
    return () => {
      window.clearTimeout(slowTimer);
      window.clearTimeout(hideTimer);
    };
  }, [embedUrl]);

  const statusTitle = streamLoaded ? 'Preparing stream...' : 'Loading stream...';
  const statusDetail = streamSlow
    ? 'This stream is taking longer than usual. You can keep waiting or close the player.'
    : 'The player can take a moment to initialize.';

  return (
    <div className="modal-backdrop trailer-backdrop" role="presentation" onClick={onClose}>
      <section className="trailer-dialog stream-dialog" role="dialog" aria-modal="true" aria-label={`Stream ${titleLabel}`} onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header trailer-dialog-header">
          <div>
            <p className="screen-kicker">Streaming</p>
            <h2>{titleLabel}</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close stream">
            <X size={18} />
          </button>
        </div>
        <div className="trailer-player-shell stream-player-shell">
          {streamStatusVisible && (
            <div className={`stream-loading-overlay ${streamLoaded ? 'is-compact' : ''}`} role="status" aria-live="polite">
              <Loader2 size={28} className="spin" />
              <strong>{statusTitle}</strong>
              <span className="stream-loading-bar" aria-hidden="true"><span /></span>
              <small>{statusDetail}</small>
            </div>
          )}
          <iframe
            key={embedUrl}
            title={`${titleLabel} stream`}
            src={embedUrl}
            allow="autoplay; fullscreen; picture-in-picture; encrypted-media"
            onLoad={() => setStreamLoaded(true)}
            allowFullScreen
          />
        </div>
      </section>
    </div>
  );
}

function TorrentModal({ state, onClose, notify }) {
  const initialQuery = `${state.title || ''} ${state.year || ''}`.trim();
  const [manualQuery, setManualQuery] = useState(initialQuery);
  const [titleFilter, setTitleFilter] = useState('');
  const [resolutionFilter, setResolutionFilter] = useState('all');
  const [indexerFilter, setIndexerFilter] = useState('all');
  const [sortMode, setSortMode] = useState('size-desc');
  const [variants, setVariants] = useState(state.variants || []);
  const [loading, setLoading] = useState(state.loading);
  const [error, setError] = useState(state.error || '');
  const [sourceSearch, setSourceSearch] = useState(state.sourceSearch || null);
  const [identity, setIdentity] = useState(() => ({
    tmdb_id: state.tmdb_id || '',
    imdb_id: state.imdb_id || '',
    title: state.title || '',
    year: state.year || '',
  }));
  const [identityCandidates, setIdentityCandidates] = useState([]);
  const [identityLoading, setIdentityLoading] = useState(false);
  const [identityError, setIdentityError] = useState('');

  useEffect(() => {
    setVariants(state.variants || []);
    setLoading(state.loading);
    setError(state.error || '');
    setSourceSearch(state.sourceSearch || null);
  }, [state.variants, state.loading, state.error, state.sourceSearch]);

  useEffect(() => {
    setManualQuery(`${state.title || ''} ${state.year || ''}`.trim());
    setIdentity({
      tmdb_id: state.tmdb_id || '',
      imdb_id: state.imdb_id || '',
      title: state.title || '',
      year: state.year || '',
    });
    setIdentityCandidates([]);
    setIdentityError('');
    setTitleFilter('');
    setResolutionFilter('all');
    setIndexerFilter('all');
    setSortMode('size-desc');
  }, [state.title, state.year, state.tmdb_id, state.imdb_id, state.upgrade]);

  async function resolveIdentity(query = manualQuery) {
    const q = String(query || '').trim();
    if (!q) return;
    setIdentityLoading(true);
    setIdentityError('');
    try {
      const params = new URLSearchParams({ q, page: '1', include_adult: 'false' });
      if (state.year) params.set('year', state.year);
      const data = await fetchJson(`/api/tmdb/search?${params.toString()}`);
      setIdentityCandidates((data.results || []).slice(0, 6));
    } catch (matchError) {
      setIdentityCandidates([]);
      setIdentityError(matchError.message);
    } finally {
      setIdentityLoading(false);
    }
  }

  useEffect(() => {
    if (!state.tmdb_id && !state.imdb_id) resolveIdentity(initialQuery);
  }, [state.tmdb_id, state.imdb_id, state.title, state.year]);

  const indexers = useMemo(() => getUniqueOptions(variants, (variant) => variant.indexer), [variants]);
  const resolutions = useMemo(() => {
    const preferred = ['4K', '1080p', '720p', '480p', 'Unknown'];
    const found = getUniqueOptions(variants, (variant) => variant.resolution || 'Unknown');
    return preferred.filter((value) => found.includes(value)).concat(found.filter((value) => !preferred.includes(value)));
  }, [variants]);

  const filteredVariants = useMemo(() => {
    const q = titleFilter.trim().toLowerCase();
    const rows = variants.filter((variant) => {
      if (q && !String(variant.title || '').toLowerCase().includes(q)) return false;
      if (resolutionFilter !== 'all' && (variant.resolution || 'Unknown') !== resolutionFilter) return false;
      if (indexerFilter !== 'all' && variant.indexer !== indexerFilter) return false;
      return true;
    });
    const sorted = [...rows];
    sorted.sort((a, b) => {
      if (sortMode === 'size-asc') return torrentSizeBytes(a) - torrentSizeBytes(b);
      if (sortMode === 'seeders-desc') return Number(b.seeders || 0) - Number(a.seeders || 0);
      if (sortMode === 'seeders-asc') return Number(a.seeders || 0) - Number(b.seeders || 0);
      if (sortMode === 'resolution-desc') return resolutionRank(b.resolution) - resolutionRank(a.resolution) || Number(b.seeders || 0) - Number(a.seeders || 0);
      if (sortMode === 'title-asc') return String(a.title || '').localeCompare(String(b.title || ''));
      return torrentSizeBytes(b) - torrentSizeBytes(a);
    });
    return sorted;
  }, [variants, titleFilter, resolutionFilter, indexerFilter, sortMode]);

  const stillSearching = loading || sourceSearch?.status === 'running';
  const pendingIndexers = [
    ...(sourceSearch?.searching_indexers || []),
    ...(sourceSearch?.pending_indexers || [])
  ].filter(Boolean);
  const timedOutIndexers = sourceSearch?.timed_out_indexers || [];

  async function runManualSearch(event) {
    event.preventDefault();
    const q = manualQuery.trim();
    if (!q) return;
    setLoading(true);
    setError('');
    setSourceSearch(null);
    setIdentity({ tmdb_id: '', imdb_id: '', title: '', year: '' });
    void resolveIdentity(q);
    try {
      const data = await fetchJson(`/api/prowlarr/search?q=${encodeURIComponent(q)}`);
      setVariants(data.results || []);
      setTitleFilter('');
      setResolutionFilter('all');
      setIndexerFilter('all');
      setSortMode('size-desc');
    } catch (searchError) {
      setVariants([]);
      setError(searchError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="torrent-dialog" role="dialog" aria-modal="true" aria-label="Torrent results" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">{state.upgrade ? 'Upgrade search' : 'Source search'}</p>
            <h2>{state.upgrade ? 'Upgrade sources' : 'Sources'}: {state.title}{state.year ? ` (${state.year})` : ''}</h2>
          </div>
          <span className="torrent-count">{formatCount(filteredVariants.length)} results</span>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close torrent results">
            <X size={18} />
          </button>
        </div>

        <form className="torrent-search-row" onSubmit={runManualSearch}>
          <label className="library-search">
            <Search size={17} />
            <input value={manualQuery} onChange={(event) => setManualQuery(event.target.value)} placeholder="Manual torrent search..." />
          </label>
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} Search
          </button>
        </form>

        {!identity.tmdb_id && !identity.imdb_id ? (
          <div className="source-search-progress source-search-progress-muted">
            <AlertTriangle size={15} />
            <span>
              <strong>{identityLoading ? 'Matching movie...' : 'Select a TMDB movie before embedded download.'}</strong>
              {identityError ? <small>{identityError}</small> : null}
            </span>
            {identityCandidates.length ? (
              <div className="torrent-action-group">
                {identityCandidates.map((candidate) => (
                  <button
                    key={candidate.tmdb_id}
                    type="button"
                    className="mini-action"
                    onClick={() => setIdentity({
                      tmdb_id: String(candidate.tmdb_id || ''),
                      imdb_id: String(candidate.imdb_id || ''),
                      title: candidate.title || '',
                      year: candidate.year || '',
                    })}
                  >
                    <Film size={14} /> {candidate.title || 'Untitled'}{candidate.year ? ` (${candidate.year})` : ''}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="torrent-filter-row">
          <label className="library-search">
            <Search size={17} />
            <input value={titleFilter} onChange={(event) => setTitleFilter(event.target.value)} placeholder="Filter by title..." />
          </label>
          <select value={resolutionFilter} onChange={(event) => setResolutionFilter(event.target.value)}>
            <option value="all">All resolutions</option>
            {resolutions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <select value={indexerFilter} onChange={(event) => setIndexerFilter(event.target.value)}>
            <option value="all">All indexers</option>
            {indexers.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <select value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
            <option value="size-desc">Size largest</option>
            <option value="size-asc">Size smallest</option>
            <option value="seeders-desc">Seeders most</option>
            <option value="seeders-asc">Seeders least</option>
            <option value="resolution-desc">Resolution best</option>
            <option value="title-asc">Title A-Z</option>
          </select>
        </div>

        {stillSearching && filteredVariants.length ? (
          <div className="source-search-progress" role="status" aria-live="polite">
            <Loader2 size={16} className="spin" />
            <span>
              <strong>Still searching</strong>
              <small>
                {pendingIndexers.length
                  ? `Checking ${pendingIndexers.slice(0, 4).join(', ')}${pendingIndexers.length > 4 ? ` and ${pendingIndexers.length - 4} more` : ''}.`
                  : 'Waiting for remaining indexers.'}
              </small>
            </span>
          </div>
        ) : null}

        {!stillSearching && timedOutIndexers.length ? (
          <div className="source-search-progress source-search-progress-muted">
            <AlertTriangle size={15} />
            <span>
              <strong>Some indexers timed out</strong>
              <small>{timedOutIndexers.slice(0, 4).join(', ')}{timedOutIndexers.length > 4 ? ` and ${timedOutIndexers.length - 4} more` : ''}</small>
            </span>
          </div>
        ) : null}

        {stillSearching && !filteredVariants.length ? (
          <div className="dialog-loading">
            <Loader2 size={20} className="spin" />
            <span className="dialog-loading-copy">
              <strong>Connecting to Prowlarr indexers...</strong>
              <small>This may take some time while source aliases and indexers respond.</small>
            </span>
          </div>
        ) : error ? (
          <div className="dialog-error">{error}</div>
        ) : filteredVariants.length ? (
          <div className="torrent-result-list">
            {filteredVariants.map((variant, index) => {
              return (
                <article className="torrent-result" key={`${variant.title}-${index}`}>
                  <span className="torrent-quality">{variant.resolution || 'Unknown'}</span>
                  <div className="torrent-title-block">
                    <strong>{variant.title}</strong>
                    <span>
                      <strong className="torrent-seeders">Seeders {formatCount(variant.seeders)}</strong>
                      <span>{variant.size_human || '?'}</span>
                      <span>{variant.indexer || 'Unknown indexer'}</span>
                    </span>
                  </div>
                  <TorrentActions
                    variant={variant}
                    movieTitle={identity.title || state.title}
                    movieYear={identity.year || state.year}
                    tmdbId={identity.tmdb_id}
                    imdbId={identity.imdb_id}
                    upgrade={state.upgrade}
                    notify={notify}
                  />
                </article>
              );
            })}
          </div>
        ) : (
          <div className="empty-state">
            <strong>No sources found.</strong>
            <span>Prowlarr returned no usable movie releases for this title.</span>
          </div>
        )}
      </section>
    </div>
  );
}

function TopBar({
  activeSection,
  stats,
  libraryQuery,
  onLibraryQueryChange,
  discoverQuery,
  onDiscoverQueryChange,
  browseQuery,
  onBrowseQueryChange,
  discoverActiveTab,
  onDiscoverSearch
}) {
  const section = navItems.find((item) => item.id === activeSection);
  const isLibrary = activeSection === 'library';
  const isDiscover = activeSection === 'discover';
  const isDownloads = activeSection === 'downloads';
  const isBrowseSearch = isDiscover && discoverActiveTab === 'browse';
  const isExploreSearch = isDiscover && discoverActiveTab === 'explore';
  const searchEnabled = topBarSearchEnabled(activeSection, discoverActiveTab);
  const searchValue = isLibrary ? libraryQuery : isBrowseSearch ? browseQuery : isExploreSearch ? discoverQuery : '';
  const searchPlaceholder = isLibrary
    ? 'Search your offline library...'
    : isBrowseSearch
      ? 'Search movie indexers...'
      : isExploreSearch
        ? 'Search TMDB discovery...'
        : isDiscover
          ? 'Use the AI prompt below...'
          : 'Search movies, actions, TMDB...';
  return (
    <header className="topbar">
      <div>
        <p className="screen-kicker">Cinematic archive console</p>
        <div className="topbar-title-row">
          <h1>
            {section?.label || 'Home'}
            {isLibrary && <span className="offline-badge">Offline</span>}
          </h1>
          {activeSection === 'downloads' && (
            <span className="downloads-title-credit">
              <img src="/qbittorrent/images/qbittorrent32.png" alt="" />
              <span>Powered by qBittorrent</span>
            </span>
          )}
        </div>
      </div>
      {!isDownloads && (
        <form
          className={cx('command-search', !searchEnabled && 'command-search-inactive')}
          aria-disabled={!searchEnabled}
          onSubmit={(event) => {
            event.preventDefault();
            if (searchEnabled && (isExploreSearch || isBrowseSearch)) onDiscoverSearch();
          }}
        >
          <Search size={17} />
          <input
            aria-label={isLibrary ? 'Search offline library' : isBrowseSearch ? 'Search movie indexers' : isExploreSearch ? 'Search TMDB discovery' : 'Command search'}
            value={searchValue}
            onChange={(event) => {
              if (isLibrary) onLibraryQueryChange(event.target.value);
              if (isExploreSearch) onDiscoverQueryChange(event.target.value);
              if (isBrowseSearch) onBrowseQueryChange(event.target.value);
            }}
            placeholder={searchPlaceholder}
            disabled={!searchEnabled}
          />
          {searchEnabled && <kbd>{isExploreSearch || isBrowseSearch ? 'Enter' : 'Ctrl K'}</kbd>}
        </form>
      )}
      {!isDownloads && (
        <div className="topbar-stat">
          <Database size={16} />
          <span>{formatCount(stats?.total_files)} files</span>
        </div>
      )}
    </header>
  );
}

export default App;
