import {
  ChevronLeft,
  ChevronRight,
  Clapperboard,
  Clock3,
  Film,
  Heart,
  Home,
  Layers3,
  ListPlus,
  ListVideo,
  Loader2,
  Play,
  Radio,
  RefreshCcw,
  Search,
  ServerCog,
  Star,
  Tv,
  X
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { iptvApi, iptvImage } from '../../api/iptv.js';
import { UnifiedMovieCard } from '../../components/movie-card/MovieCard.jsx';
import { formatCount } from '../../utils/appUtils.js';
import IPTVPlayer from './IPTVPlayer.jsx';
import IPTVListsWorkspace, { IPTVListPickerModal } from './IPTVListsWorkspace.jsx';
import { shouldAutoSyncIPTVCatalog } from './iptvSyncPolicy.js';
import './iptv.css';

const TABS = [
  { id: 'home', label: 'Home', icon: Home },
  { id: 'live', label: 'Live TV', icon: Radio },
  { id: 'movie', label: 'Movies', icon: Film },
  { id: 'series', label: 'Series', icon: Tv },
  { id: 'favorites', label: 'Favorites', icon: Heart },
  { id: 'lists', label: 'My Lists', icon: ListVideo }
];

const EMPTY_PAGE = { items: [], total: 0, page: 1, page_size: 30 };

function mediaTitle(item) {
  const name = String(item?.name || item?.title || 'Untitled');
  const year = String(item?.year || '').slice(0, 4);
  return year ? name.replace(new RegExp(`\\s*\\(\\s*${year}\\s*\\)\\s*$`), '').trim() || name : name;
}

function relativeSyncTime(timestamp) {
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - Number(timestamp || 0)));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function IPTVWorkspace({ notify }) {
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
  const playbackRef = useRef(null);
  const activeProviderRef = useRef('');
  const categoryIdRef = useRef('');
  const autoSyncRequestedRef = useRef(new Set());

  const browseKind = activeTab === 'favorites' ? favoriteKind : activeTab;
  const isBrowseTab = ['live', 'movie', 'series', 'favorites'].includes(activeTab);
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
    if (!status?.configured || !['live', 'movie', 'series'].includes(activeTab)) return undefined;
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
    if (!status?.configured || !isBrowseTab) return undefined;
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
            page_size: 60
          });
          if (!cancelled) setCatalog(result);
          return;
        }
        const result = await iptvApi.items(activeProviderId, {
          kind: browseKind,
          category_id: categoryId,
          q: query.trim(),
          page,
          page_size: browseKind === 'live' ? 80 : 30,
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
  }, [activeProviderId, activeTab, browseKind, categoryId, query, page, status?.configured, status?.generation]);

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
    setStatus(null);
    setCategories({ live: [], movie: [], series: [] });
    setCategoryId('');
    setQuery('');
    setPage(1);
    setCatalog(EMPTY_PAGE);
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
      await iptvApi.favorite(activeProviderId, item.kind, item.item_id, next);
      setCatalog((state) => {
        const matches = (row) => row.kind === item.kind && row.item_id === item.item_id;
        if (activeTab === 'favorites' && !next) {
          return { ...state, items: state.items.filter((row) => !matches(row)), total: Math.max(0, Number(state.total || 0) - 1) };
        }
        return { ...state, items: state.items.map((row) => matches(row) ? { ...row, favorite: next } : row) };
      });
      setDetail((state) => state && state.kind === item.kind && state.item_id === item.item_id ? { ...state, favorite: next } : state);
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
      setListPickerLists(result.items || []);
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
      await iptvApi.setListItem(activeProviderId, list.list_id, listPickerItem.kind, listPickerItem.item_id, included);
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
      await iptvApi.setListItem(activeProviderId, created.list_id, listPickerItem.kind, listPickerItem.item_id, true);
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
    setSelectedId(item.item_id);
    setDetailLoading(true);
    setError('');
    try {
      const result = await iptvApi.detail(requestedProviderId, item.kind, item.item_id);
      if (activeProviderRef.current !== requestedProviderId) return;
      setDetail(result);
      const seasonNumbers = [...new Set((result.episodes || []).map((episode) => episode.season))].sort((a, b) => a - b);
      setSelectedSeason(seasonNumbers[0] || 1);
    } catch (requestError) {
      if (activeProviderRef.current === requestedProviderId) setError(requestError.message);
    } finally {
      if (activeProviderRef.current === requestedProviderId) setDetailLoading(false);
    }
  }

  async function openDetail(item) {
    if (selectedId === item.item_id) {
      setSelectedId('');
      setDetail(null);
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
          {activeTab === 'favorites' ? (
            <FavoritesView
              providerId={activeProviderId}
              catalog={catalog}
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
            <MovieView providerId={activeProviderId} catalog={catalog} selectedId={selectedId} detail={detail} detailLoading={detailLoading} onToggle={openDetail} onPlay={playItem} onFavorite={toggleFavorite} onAddToList={openListPicker} />
          ) : (
            <SeriesView providerId={activeProviderId} catalog={catalog} detail={detail} detailLoading={detailLoading} selectedId={selectedId} selectedSeason={selectedSeason} onSeason={setSelectedSeason} onToggle={openDetail} onPlay={playItem} onFavorite={toggleFavorite} onAddToList={openListPicker} />
          )}
          <Pagination page={catalog.page || page} pageSize={catalog.page_size || 30} total={catalog.total || 0} onPage={setPage} />
        </>
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

function MovieView({ providerId, catalog, selectedId, detail, detailLoading, onToggle, onPlay, onFavorite, onAddToList }) {
  return (
    <div className="iptv-movie-grid">
      {catalog.items.map((movie) => {
        const expanded = selectedId === movie.item_id;
        const current = expanded && detail ? detail : movie;
        const genres = String(current.genre || '').split(',').map((value) => value.trim()).filter(Boolean).slice(0, 3);
        return (
          <UnifiedMovieCard
            key={movie.item_id}
            title={mediaTitle(movie)}
            year={movie.year}
            posterUrl={movie.image_url ? iptvImage(providerId, 'movie', movie.item_id) : ''}
            rating={movie.rating ? Number(movie.rating).toFixed(1) : ''}
            chips={genres}
            mutedChips={movie.container_extension ? [movie.container_extension.toUpperCase()] : []}
            expanded={expanded}
            selected={expanded}
            showPlayOverlay
            onPlay={() => onPlay(current)}
            onToggle={() => onToggle(movie)}
            className="iptv-movie-card"
            cornerControls={<div className="iptv-movie-corner-actions"><FavoriteButton item={movie} onFavorite={onFavorite} /><ListActionButton item={movie} onAddToList={onAddToList} /></div>}
          >
            {expanded ? detailLoading ? <div className="iptv-detail-loading"><Loader2 className="spin" size={17} /> Loading provider metadata...</div> : (
              <div className="iptv-expanded-content">
                <p dir="auto">{current.plot || 'No plot supplied by the provider.'}</p>
                <dl><div><dt>Director</dt><dd dir="auto">{current.director || 'Unknown'}</dd></div><div><dt>Cast</dt><dd dir="auto">{current.cast_names || 'Not supplied'}</dd></div><div><dt>Runtime</dt><dd>{current.duration || 'Unknown'}</dd></div></dl>
                <div className="iptv-card-actions"><button type="button" className="btn btn-primary" onClick={() => onPlay(current)}><Play size={15} /> Play</button><button type="button" className="btn btn-secondary" onClick={() => onFavorite(current)}><Heart size={15} fill={current.favorite ? 'currentColor' : 'none'} /> {current.favorite ? 'Favorited' : 'Favorite'}</button><button type="button" className="btn btn-secondary" onClick={() => onAddToList(current)}><ListPlus size={15} /> Add to list</button></div>
              </div>
            ) : null}
          </UnifiedMovieCard>
        );
      })}
      {!catalog.items.length ? <div className="iptv-empty iptv-grid-empty"><Film size={30} /><span>No movies in this view.</span></div> : null}
    </div>
  );
}

function SeriesView({ providerId, catalog, detail, detailLoading, selectedId, selectedSeason, onSeason, onToggle, onPlay, onFavorite, onAddToList }) {
  const seasonNumbers = useMemo(() => [...new Set((detail?.episodes || []).map((episode) => episode.season))].sort((a, b) => a - b), [detail]);
  return (
    <>
      <div className="iptv-poster-grid">
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

function FavoritesView({ providerId, catalog, selectedId, detail, detailLoading, selectedSeason, onSeason, onToggle, onPlay, onFavorite, onAddToList, onOpenChannel, loading }) {
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
          <MovieView providerId={providerId} catalog={{ ...catalog, items: movies }} selectedId={selectedId} detail={detail} detailLoading={detailLoading} onToggle={onToggle} onPlay={onPlay} onFavorite={onFavorite} onAddToList={onAddToList} />
        </section>
      ) : null}
      {series.length ? (
        <section className="iptv-favorite-section">
          <header><Tv size={18} /><h2>Series</h2><span>{formatCount(series.length)}</span></header>
          <SeriesView providerId={providerId} catalog={{ ...catalog, items: series }} detail={detail} detailLoading={detailLoading} selectedId={selectedId} selectedSeason={selectedSeason} onSeason={onSeason} onToggle={onToggle} onPlay={onPlay} onFavorite={onFavorite} onAddToList={onAddToList} />
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
