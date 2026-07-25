import { AlertTriangle, Bot, Check, CirclePlus, Film, Loader2, RefreshCcw, Sparkles, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from '../../api/client.js';
import { CATALOG_GENERATION_CHANGED_EVENT, fetchOwnershipChecks } from '../../api/library.js';
import { fetchCanonicalMovieDetails, markMovieDetailsCacheStale, movieCollectionUrl, movieDetailsCacheKey } from '../../api/movieDetails.js';
import { addMoviePayloadsToList, announceCurationChanged, clearUserListsCache, CURATION_GENERATION_CHANGED_EVENT, fetchCurationJson, fetchUserListsCached } from '../../api/curation.js';
import DiscoverResultGrid from '../../components/DiscoverResultGrid.jsx';
import ExperimentalBadge from '../../components/ExperimentalBadge.jsx';
import ListEditorModal from '../../components/ListEditorModal.jsx';
import SelectionCheckbox from '../../components/SelectionCheckbox.jsx';
import { DiscoverMovieCard } from '../../components/SharedMovieCards.jsx';
import { cx, formatCount, movieKey } from '../../utils/appUtils.js';
import { buildOwnershipMap, discoverMoviePayload, listsForDiscoverMovie, ownedMovieFor } from '../../discoverUtils.js';
import { movieIdentityKey, moviePayload } from '../../utils/libraryUtils.js';

const aiControlExamples = [
  'Find Tom Cruise movies I own',
  'Create a list of top rated sci-fi from 2010',
  'Download unowned Nolan movies in 1080p',
  'Delete files larger than 10 GB'
];

const aiControlPreviewStages = [
  'Understanding request with Ollama...',
  'Contacting TMDB...',
  'Checking your library...',
  'Searching trusted indexers...',
  'Preparing review...'
];

export default function AIControlWorkspace({
  followed = [],
  notify,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onOpenTrailer,
  onFollow,
  onEditPoster
}) {
  const [prompt, setPrompt] = useState('');
  const [aiControlPlan, setAiControlPlan] = useState(null);
  const [aiControlReceipt, setAiControlReceipt] = useState(null);
  const [aiControlBusy, setAiControlBusy] = useState(false);
  const [aiControlError, setAiControlError] = useState('');
  const [aiControlLoadingStep, setAiControlLoadingStep] = useState(null);
  const [aiControlCardView, setAiControlCardView] = useState(false);
  const aiControlStageTimersRef = useRef([]);

  function clearAiControlStageTimers() {
    aiControlStageTimersRef.current.forEach((timer) => window.clearTimeout(timer));
    aiControlStageTimersRef.current = [];
  }

  function startAiControlPreviewProgress() {
    clearAiControlStageTimers();
    setAiControlLoadingStep(0);
    aiControlStageTimersRef.current = aiControlPreviewStages.slice(1).map((_, index) => (
      window.setTimeout(() => setAiControlLoadingStep(index + 1), 1800 + index * 2600)
    ));
  }

  useEffect(() => () => clearAiControlStageTimers(), []);

  async function previewAiControlCommand(event) {
    event.preventDefault();
    const command = prompt.trim();
    if (!command) {
      setAiControlError('Enter a command first.');
      return;
    }
    setAiControlBusy(true);
    setAiControlError('');
    setAiControlReceipt(null);
    setAiControlCardView(false);
    startAiControlPreviewProgress();
    try {
      const data = await fetchJson('/api/ai-control/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: command })
      });
      setAiControlPlan(data);
      if (data.state === 'valid_plan') {
        notify(data.message || 'AI Control preview ready', 'success');
      } else {
        notify(data.message || 'AI Control needs clarification', 'neutral');
      }
    } catch (error) {
      setAiControlError(error.message);
      notify(`AI Control preview failed: ${error.message}`, 'error');
    } finally {
      clearAiControlStageTimers();
      setAiControlLoadingStep(null);
      setAiControlBusy(false);
    }
  }

  async function executeAiControlPlan(confirmationPhrase = '') {
    if (!aiControlPlan?.plan_id) return;
    setAiControlBusy(true);
    setAiControlError('');
    setAiControlLoadingStep(null);
    try {
      const data = await fetchJson('/api/ai-control/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plan_id: aiControlPlan.plan_id,
          confirmation_phrase: confirmationPhrase
        })
      });
      setAiControlPlan(null);
      setAiControlReceipt(data);
      if (data.action === 'create_list') {
        clearUserListsCache();
        announceCurationChanged();
      }
      notify(data.message || 'AI Control action executed', 'success');
    } catch (error) {
      setAiControlError(error.message);
      notify(`AI Control execute failed: ${error.message}`, 'error');
    } finally {
      setAiControlBusy(false);
    }
  }

  function useExample(example) {
    setPrompt(example);
    setAiControlError('');
  }

  return (
    <section className="ai-control-workspace">
      <header className="library-header ai-control-header">
        <div>
          <p className="screen-kicker">AI command console</p>
          <h2>AI Control <ExperimentalBadge /></h2>
          <p>Turn plain-language movie commands into reviewable CP actions for finding, lists, downloads, and cleanup.</p>
        </div>
      </header>

      <form className="ai-control-command" onSubmit={previewAiControlCommand}>
        <label className="ai-control-prompt">
          <span>Command</span>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            placeholder="Tell CP what to find, list, download, or delete..."
            rows={4}
          />
        </label>
        <div className="ai-control-command-actions">
          <button type="submit" className="btn btn-primary btn-violet" disabled={aiControlBusy}>
            {aiControlBusy ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />} Preview command
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => { setPrompt(''); setAiControlPlan(null); setAiControlReceipt(null); setAiControlError(''); setAiControlCardView(false); }} disabled={aiControlBusy}>
            <X size={15} /> Clear
          </button>
        </div>
      </form>

      <div className="ai-control-guide">
        <div className="ai-control-example-row">
          {aiControlExamples.map((example) => (
            <button type="button" className="mini-action" key={example} onClick={() => useExample(example)}>
              {example}
            </button>
          ))}
        </div>
        <strong>No action runs automatically. Every result is reviewed before you confirm it.</strong>
      </div>

      {aiControlBusy && aiControlLoadingStep !== null && (
        <div className="ai-control-progress" role="status" aria-live="polite">
          <Loader2 size={16} className="spin" />
          <div>
            <strong>{aiControlPreviewStages[aiControlLoadingStep]}</strong>
            <small>Large actor/director requests can take a while because CP reviews TMDB, your library, and trusted indexers before showing a plan.</small>
          </div>
        </div>
      )}

      {aiControlError && (
        <div className="library-status library-status-error">
          <AlertTriangle size={16} />
          <span>{aiControlError}</span>
        </div>
      )}

      <AIControlResult
        aiControlPlan={aiControlPlan}
        aiControlReceipt={aiControlReceipt}
        busy={aiControlBusy}
        onExecute={executeAiControlPlan}
        aiControlCardView={aiControlCardView}
        setAiControlCardView={setAiControlCardView}
        followed={followed}
        notify={notify}
        onPlay={onPlay}
        onStream={onStream}
        streamingAvailable={streamingAvailable}
        streamingLabel={streamingLabel}
        onFindTorrent={onFindTorrent}
        onOpenTrailer={onOpenTrailer}
        onFollow={onFollow}
        onEditPoster={onEditPoster}
      />
    </section>
  );
}

function AIControlResult({
  aiControlPlan,
  aiControlReceipt,
  busy,
  onExecute,
  aiControlCardView,
  setAiControlCardView,
  followed,
  notify,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onOpenTrailer,
  onFollow,
  onEditPoster
}) {
  const plan = aiControlPlan;
  const [currentPage, setCurrentPage] = useState(1);
  const [aiControlDangerPhrase, setAiControlDangerPhrase] = useState('');
  const planKey = `${plan?.plan_id || ''}-${plan?.summary || ''}-${plan?.message || ''}-${aiControlReceipt?.summary || ''}`;

  useEffect(() => {
    setCurrentPage(1);
    setAiControlDangerPhrase('');
    setAiControlCardView(false);
  }, [planKey, setAiControlCardView]);

  if (aiControlReceipt) {
    const executedCount = Number(aiControlReceipt.total_matches || aiControlReceipt.created?.count || 0);
    return (
      <section className="ai-control-result ai-control-result-ready ai-control-execution-receipt">
        <div className="ai-control-result-header">
          <div>
            <p className="screen-kicker">{aiControlReceipt.state || 'executed'}</p>
            <h3>{aiControlReceipt.summary || 'Action completed'}</h3>
            <p>{aiControlReceipt.message || 'AI Control completed the reviewed action.'}</p>
          </div>
          <div className="ai-control-execution-count">
            <strong>{formatCount(executedCount)}</strong>
            <span>{aiControlReceipt.action === 'create_list' ? 'movies saved' : 'actions completed'}</span>
          </div>
        </div>
      </section>
    );
  }
  if (!plan) {
    return (
      <div className="empty-state library-empty ai-control-empty">
        <Bot size={30} />
        <strong>No command preview yet.</strong>
        <span>Use an example or type a command to see the reviewed plan here.</span>
      </div>
    );
  }
  const ready = plan.state === 'valid_plan';
  const rows = plan.items || [];
  const blocked = plan.blocked || [];
  const pageSize = Number(plan.page_size || 50);
  const totalMatches = Number(plan.total_matches || rows.length);
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const pageStart = (safeCurrentPage - 1) * pageSize;
  const visibleRows = rows.slice(pageStart, pageStart + pageSize);
  const pageLabel = rows.length > pageSize
    ? `Showing ${formatCount(pageStart + 1)}-${formatCount(Math.min(pageStart + pageSize, rows.length))} of ${formatCount(totalMatches)}`
    : `${formatCount(totalMatches)} total`;
  const requiresDeletePhrase = ready && plan.action === 'delete' && plan.requires_extra_confirmation;
  const deletePhraseConfirmed = !requiresDeletePhrase || aiControlDangerPhrase.trim() === String(plan.confirmation_phrase || '').trim();
  const canDisplayCards = ready && plan.action === 'find' && visibleRows.length > 0;
  return (
    <section className={cx('ai-control-result', ready ? 'ai-control-result-ready' : 'ai-control-result-blocked')}>
      <div className="ai-control-result-header">
        <div>
          <p className="screen-kicker">{plan.state || 'AI Control'}</p>
          <h3>{plan.summary || plan.message || 'Command result'}</h3>
          {plan.message && <p>{plan.message}</p>}
        </div>
        <div className="ai-control-result-actions">
          {canDisplayCards && (
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                if (aiControlCardView) setAiControlCardView(false);
                else setAiControlCardView(true);
              }}
            >
              {aiControlCardView ? <RefreshCcw size={15} /> : <Film size={15} />} {aiControlCardView ? 'Back to table' : 'Display as cards'}
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onExecute(aiControlDangerPhrase)}
            disabled={!aiControlPlan?.plan_id || busy || !ready || !deletePhraseConfirmed}
          >
            {busy ? <Loader2 size={15} className="spin" /> : <Check size={15} />} Confirm action
          </button>
        </div>
      </div>
      {ready && (
        <AIControlPagination
          pageLabel={pageLabel}
          currentPage={safeCurrentPage}
          totalPages={totalPages}
          onPrevious={() => setCurrentPage((page) => Math.max(1, page - 1))}
          onNext={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
        />
      )}
      {requiresDeletePhrase && (
        <label className="ai-control-danger-confirm">
          <span>Type the confirmation phrase before deleting this batch.</span>
          <strong>{plan.confirmation_phrase}</strong>
          <input
            value={aiControlDangerPhrase}
            onChange={(event) => setAiControlDangerPhrase(event.target.value)}
            placeholder="Type the confirmation phrase"
          />
        </label>
      )}
      {canDisplayCards && aiControlCardView ? (
        <AIControlCardResults
          plan={plan}
          rows={visibleRows}
          followed={followed}
          notify={notify}
          onPlay={onPlay}
          onStream={onStream}
          streamingAvailable={streamingAvailable}
          streamingLabel={streamingLabel}
          onFindTorrent={onFindTorrent}
          onOpenTrailer={onOpenTrailer}
          onFollow={onFollow}
          onEditPoster={onEditPoster}
        />
      ) : (
        !aiControlCardView && visibleRows.length > 0 && <AIControlTable rows={visibleRows} action={plan.action} />
      )}
      {blocked.length > 0 && (
        <div className="ai-control-blocked">
          <h4>Blocked or skipped</h4>
          <AIControlTable rows={blocked} action={plan.action} compact />
        </div>
      )}
    </section>
  );
}

function AIControlPagination({ pageLabel, currentPage, totalPages, onPrevious, onNext }) {
  return (
    <div className="ai-control-pagination">
      <span>{pageLabel}</span>
      {totalPages > 1 && (
        <div>
          <button type="button" className="mini-action" onClick={onPrevious} disabled={currentPage <= 1}>
            Previous page
          </button>
          <strong>{formatCount(currentPage)} / {formatCount(totalPages)}</strong>
          <button type="button" className="mini-action" onClick={onNext} disabled={currentPage >= totalPages}>
            Next page
          </button>
        </div>
      )}
    </div>
  );
}

function AIControlCardResults({
  plan,
  rows,
  followed,
  notify,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onOpenTrailer,
  onFollow,
  onEditPoster
}) {
  const [ownership, setOwnership] = useState(() => buildAiControlOwnershipMap(rows));
  const [userLists, setUserLists] = useState([]);
  const [detailsCache, setDetailsCache] = useState({});
  const [collectionCache, setCollectionCache] = useState({});
  const [expandedMovieKey, setExpandedMovieKey] = useState('');
  const [selectedAiControlKeys, setSelectedAiControlKeys] = useState(() => new Set());
  const [listEditorTarget, setListEditorTarget] = useState(null);
  const ownershipRequestSeq = useRef(0);
  const movies = rows || [];
  const ownershipScopeKey = useMemo(() => (
    `${plan?.plan_id || ''}:${movies.map((movie) => movieIdentityKey(movie)).join('|')}`
  ), [plan?.plan_id, movies]);

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

  const loadUserLists = useCallback(async (options = {}) => {
    try {
      const data = await fetchUserListsCached({ force: Boolean(options?.force) });
      setUserLists(data.lists || []);
    } catch (error) {
      notify?.(`Lists unavailable: ${error.message}`, 'error');
    }
  }, [notify]);

  useEffect(() => {
    loadUserLists();
    window.addEventListener('cp-curation-changed', loadUserLists);
    return () => window.removeEventListener('cp-curation-changed', loadUserLists);
  }, [loadUserLists]);

  useEffect(() => {
    const requestSeq = ownershipRequestSeq.current + 1;
    ownershipRequestSeq.current = requestSeq;
    setOwnership(buildAiControlOwnershipMap(movies));
    setSelectedAiControlKeys(new Set());
    setExpandedMovieKey('');
    checkAiControlOwnership(movies, requestSeq);
    return () => {
      if (ownershipRequestSeq.current === requestSeq) ownershipRequestSeq.current += 1;
    };
  }, [ownershipScopeKey]);

  async function checkAiControlOwnership(items, requestSeq) {
    const payload = (items || []).filter((movie) => movie?.title);
    if (!payload.length) return;
    try {
      const ownershipResults = await fetchOwnershipChecks(payload);
      if (requestSeq !== ownershipRequestSeq.current) return;
      setOwnership((state) => ({ ...state, ...buildOwnershipMap(ownershipResults) }));
    } catch {
      // AI Control card view can still render without best-effort ownership enrichment.
    }
  }

  async function loadAiControlDetails(movie, owned = null) {
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

  function toggleAiControlDetails(movie, owned = null) {
    const key = movieKey(movie);
    const nextKey = expandedMovieKey === key ? '' : key;
    setExpandedMovieKey(nextKey);
    if (nextKey) loadAiControlDetails(movie, owned);
  }

  async function openAiControlTrailer(movie) {
    const owned = ownedMovieFor(movie, ownership) || (movie.path ? movie : null);
    if (!movieDetailsCacheKey(movie, owned)) {
      onOpenTrailer(movie, '');
      return;
    }
    const details = await loadAiControlDetails(movie, owned);
    onOpenTrailer(movie, details?.trailer_url || '');
  }

  async function createAiControlList(name) {
    const created = await fetchCurationJson('/api/user/lists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify?.(`List created: ${created.name}`);
    return created;
  }

  async function addAiControlMovieToList(listId, movie) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}/movies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie: moviePayload(movie) })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify?.('Movie added to list');
  }

  async function addAiControlMoviesToList(listId, moviesToAdd) {
    await addMoviePayloadsToList(listId, (moviesToAdd || []).map((movie) => moviePayload(movie)));
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify?.(`${formatCount((moviesToAdd || []).length)} movie${(moviesToAdd || []).length === 1 ? '' : 's'} added to list`);
    setSelectedAiControlKeys(new Set());
  }

  async function removeAiControlMovieFromList(listId, movie) {
    await fetchCurationJson(`/api/user/lists/${encodeURIComponent(listId)}/movies`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movie: moviePayload(movie) })
    });
    await loadUserLists({ force: true });
    announceCurationChanged();
    notify?.('Movie removed from list');
  }

  async function toggleAiControlSystemList(systemType, movie, owned) {
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
    notify?.(`${movie.title} ${active ? 'removed from' : 'added to'} ${systemType === 'watched' ? 'Watched' : 'Watchlist'}`);
  }

  function toggleAiControlSelection(movie, owned, checked) {
    const key = movieIdentityKey(discoverMoviePayload(movie, owned));
    setSelectedAiControlKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function selectAllAiControlMovies() {
    setSelectedAiControlKeys(new Set(movies.map((movie) => movieIdentityKey(discoverMoviePayload(movie, ownedMovieFor(movie, ownership))))));
  }

  function clearAiControlSelection() {
    setSelectedAiControlKeys(new Set());
  }

  const selectedAiControlMovies = useMemo(() => (
    movies
      .map((movie) => discoverMoviePayload(movie, ownedMovieFor(movie, ownership)))
      .filter((movie) => selectedAiControlKeys.has(movieIdentityKey(movie)))
  ), [movies, ownership, selectedAiControlKeys]);
  const allAiControlMoviesSelected = movies.length > 0 && movies.every((movie) => (
    selectedAiControlKeys.has(movieIdentityKey(discoverMoviePayload(movie, ownedMovieFor(movie, ownership))))
  ));

  return (
    <div className="ai-control-card-results">
      <div className="bulk-selection-bar discover-bulk-selection ai-control-card-toolbar">
        <SelectionCheckbox
          className="discover-selection-master"
          checked={allAiControlMoviesSelected}
          onChange={(checked) => { if (checked) selectAllAiControlMovies(); else clearAiControlSelection(); }}
          label="Select all AI Control results"
        />
        <span>{selectedAiControlMovies.length ? `${formatCount(selectedAiControlMovies.length)} selected` : `${formatCount(movies.length)} AI Control result${movies.length === 1 ? '' : 's'}`}</span>
        <button type="button" className="mini-action" onClick={selectAllAiControlMovies}>Select all results</button>
        <button type="button" className="mini-action" onClick={clearAiControlSelection} disabled={!selectedAiControlMovies.length}>Clear</button>
        <button type="button" className="mini-action" onClick={() => setListEditorTarget({ bulkItems: selectedAiControlMovies })} disabled={!selectedAiControlMovies.length}>
          <CirclePlus size={13} /> Add selected to list
        </button>
      </div>

      <DiscoverResultGrid emptyText="No AI Control movies are available for card display.">
        {movies.map((movie, index) => {
          const owned = ownedMovieFor(movie, ownership) || (movie.path ? movie : null);
          const key = movieIdentityKey(discoverMoviePayload(movie, owned));
          const details = detailsCache[movieDetailsCacheKey(movie, owned)] || null;
          const collection = details?.collection?.id ? collectionCache[details.collection.id] || details.collection : {};
          const movieWithDetails = details ? { ...movie, plot: movie.plot || details.plot || '', release_date: movie.release_date || details.release_date || '' } : movie;
          return (
            <DiscoverMovieCard
              key={`${movie.tmdb_id || movie.path || movie.title}-${movie.year}-${index}`}
              movie={movieWithDetails}
              owned={owned}
              followed={followed.some((item) => movieKey(item) === movieKey(movie))}
              expanded={expandedMovieKey === movieKey(movie)}
              details={details}
              collection={collection}
              itemLists={listsForDiscoverMovie(movie, userLists, owned)}
              watched={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watched')}
              watchlisted={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watchlist')}
              onToggleWatched={owned ? () => toggleAiControlSystemList('watched', movie, owned) : undefined}
              onToggleWatchlist={() => toggleAiControlSystemList('watchlist', movie, owned)}
              selected={selectedAiControlKeys.has(key)}
              onSelect={(checked) => toggleAiControlSelection(movie, owned, checked)}
              onPlay={onPlay}
              onStream={onStream}
              streamingAvailable={streamingAvailable}
              streamingLabel={streamingLabel}
              onFindTorrent={onFindTorrent}
              onFollow={onFollow}
              onTrailer={openAiControlTrailer}
              onToggleDetails={() => toggleAiControlDetails(movie, owned)}
              onEditLists={() => setListEditorTarget(discoverMoviePayload(movie, owned))}
              onRemoveFromList={(listId) => removeAiControlMovieFromList(listId, discoverMoviePayload(movie, owned))}
              onEditPoster={owned?.path ? () => onEditPoster?.(owned, movie) : undefined}
            />
          );
        })}
      </DiscoverResultGrid>

      {listEditorTarget && (
        <ListEditorModal
          item={listEditorTarget.bulkItems ? null : listEditorTarget}
          bulkItems={listEditorTarget.bulkItems || []}
          items={[]}
          lists={userLists}
          onClose={() => setListEditorTarget(null)}
          onCreate={createAiControlList}
          onAdd={addAiControlMovieToList}
          onAddBulk={addAiControlMoviesToList}
        />
      )}
    </div>
  );
}

function buildAiControlOwnershipMap(movies) {
  return buildOwnershipMap((movies || [])
    .filter((movie) => movie?.path)
    .map((movie) => ({ ...movie, found: true })));
}

function AIControlTable({ rows, action, compact = false }) {
  return (
    <div className={cx('ai-control-table', compact && 'ai-control-table-compact')}>
      <div className="ai-control-table-head">
        <span>Movie</span>
        <span>{action === 'delete' ? 'Path' : action === 'download' ? 'Source' : 'Source'}</span>
        <span>Status</span>
        <span>Reason</span>
      </div>
      {rows.map((row, index) => (
        <div className="ai-control-table-row" key={`${row.path || row.tmdb_id || row.title}-${index}`}>
          <span>
            <strong>{row.title || row.variant?.title || 'Untitled'}</strong>
            <small>{row.year || row.size_gb ? [row.year, row.size_gb ? `${row.size_gb} GB` : ''].filter(Boolean).join(' - ') : 'No year'}</small>
          </span>
          <span title={row.path || row.variant?.title || row.source || row.reason || ''}>
            {row.path || row.variant?.indexer || row.source || row.reason || 'Review'}
          </span>
          <span>{row.status || 'ready'}</span>
          <span title={row.reason || ''}>{row.reason || (row.status === 'ready' ? 'Ready for review' : 'Review')}</span>
        </div>
      ))}
    </div>
  );
}
