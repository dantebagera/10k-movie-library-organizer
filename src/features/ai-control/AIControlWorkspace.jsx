import { AlertTriangle, Bot, Check, CirclePlus, Loader2, Search, Sparkles, X } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchJson } from '../../api/client.js';
import { CATALOG_GENERATION_CHANGED_EVENT, fetchOwnershipChecks } from '../../api/library.js';
import { fetchCanonicalMovieDetails, markMovieDetailsCacheStale, movieDetailsCacheKey } from '../../api/movieDetails.js';
import { addMoviePayloadsToList, announceCurationChanged, clearUserListsCache, CURATION_GENERATION_CHANGED_EVENT, fetchCurationJson, fetchUserListsCached } from '../../api/curation.js';
import { previewSourceReview } from '../../api/sourceReview.js';
import DiscoverResultGrid from '../../components/DiscoverResultGrid.jsx';
import ExperimentalBadge from '../../components/ExperimentalBadge.jsx';
import ListEditorModal from '../../components/ListEditorModal.jsx';
import SelectionCheckbox from '../../components/SelectionCheckbox.jsx';
import SourceReviewDialog from '../../components/SourceReviewDialog.jsx';
import { DiscoverMovieCard } from '../../components/SharedMovieCards.jsx';
import useCardGridMetrics from '../../hooks/useCardGridMetrics.js';
import useMovieCollectionCache from '../../hooks/useMovieCollectionCache.js';
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
  onEditPoster,
  onOpenFileDetails,
  onOpenDiscoverPerson = () => {},
  onOpenDiscoverCollection = () => {}
}) {
  const [prompt, setPrompt] = useState('');
  const [aiControlPlan, setAiControlPlan] = useState(null);
  const [aiControlReceipt, setAiControlReceipt] = useState(null);
  const [aiControlBusy, setAiControlBusy] = useState(false);
  const [aiControlError, setAiControlError] = useState('');
  const [aiControlLoadingStep, setAiControlLoadingStep] = useState(null);
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

  async function executeAiControlPlan({ confirmationPhrase = '', selectedKeys = [], reviewedDownloads = [] } = {}) {
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
          confirmation_phrase: confirmationPhrase,
          selected_keys: selectedKeys,
          reviewed_downloads: reviewedDownloads
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
          <button type="button" className="btn btn-secondary" onClick={() => { setPrompt(''); setAiControlPlan(null); setAiControlReceipt(null); setAiControlError(''); }} disabled={aiControlBusy}>
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
        onOpenFileDetails={onOpenFileDetails}
        onOpenDiscoverPerson={onOpenDiscoverPerson}
        onOpenDiscoverCollection={onOpenDiscoverCollection}
      />
    </section>
  );
}

function AIControlResult({
  aiControlPlan,
  aiControlReceipt,
  busy,
  onExecute,
  followed,
  notify,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onOpenTrailer,
  onFollow,
  onEditPoster,
  onOpenFileDetails,
  onOpenDiscoverPerson,
  onOpenDiscoverCollection
}) {
  const plan = aiControlPlan;
  const [currentPage, setCurrentPage] = useState(1);
  const [aiControlDangerPhrase, setAiControlDangerPhrase] = useState('');
  const [selectedAiControlKeys, setSelectedAiControlKeys] = useState(() => new Set());
  const [reviewedDownloads, setReviewedDownloads] = useState([]);
  const [sourceReview, setSourceReview] = useState(null);
  const planKey = `${plan?.plan_id || ''}-${plan?.summary || ''}-${plan?.message || ''}-${aiControlReceipt?.summary || ''}`;
  const targetPageSize = Number(plan?.page_size || 20);
  const {
    gridRef: aiControlGridRef,
    pageSize
  } = useCardGridMetrics({ target: targetPageSize, max: 200, bias: 'lower' });

  useEffect(() => {
    setCurrentPage(1);
    setAiControlDangerPhrase('');
    setSelectedAiControlKeys(new Set((plan?.items || []).map((item) => item.selection_key).filter(Boolean)));
    setReviewedDownloads([]);
    setSourceReview(null);
  }, [planKey]);

  if (aiControlReceipt) {
    const executedCount = Number(aiControlReceipt.submitted_count ?? aiControlReceipt.total_matches ?? aiControlReceipt.created?.count ?? 0);
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
  const totalMatches = Number(plan.total_matches || rows.length);
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safeCurrentPage = Math.min(currentPage, totalPages);
  const pageStart = (safeCurrentPage - 1) * pageSize;
  const visibleRows = rows.slice(pageStart, pageStart + pageSize);
  const pageLabel = rows.length > pageSize
    ? `Showing ${formatCount(pageStart + 1)}-${formatCount(Math.min(pageStart + pageSize, rows.length))} of ${formatCount(totalMatches)}`
    : `${formatCount(totalMatches)} total`;
  const selectedKeys = rows
    .map((row) => row.selection_key)
    .filter((selectionKey) => selectionKey && selectedAiControlKeys.has(selectionKey));
  const selectedRows = rows.filter((row) => row.selection_key && selectedAiControlKeys.has(row.selection_key));
  const selectedCount = selectedRows.length;
  const allResultsSelected = rows.length > 0 && selectedCount === rows.length;
  const customizedSelection = selectedCount !== rows.length;
  const requiresDeletePhrase = ready && plan.action === 'delete' && selectedCount > 50;
  const expectedDeletePhrase = requiresDeletePhrase ? `DELETE ${selectedCount} FILES` : '';
  const deletePhraseConfirmed = !requiresDeletePhrase || aiControlDangerPhrase.trim() === expectedDeletePhrase;
  const reviewedForSelection = reviewedDownloads.filter((row) => selectedAiControlKeys.has(row.selection_key));

  function toggleSelection(selectionKey, checked) {
    setSelectedAiControlKeys((current) => {
      const next = new Set(current);
      if (checked) next.add(selectionKey);
      else next.delete(selectionKey);
      return next;
    });
  }

  function selectAllResults() {
    setSelectedAiControlKeys(new Set(rows.map((row) => row.selection_key).filter(Boolean)));
  }

  function clearSelection() {
    setSelectedAiControlKeys(new Set());
  }

  async function openSourceReview() {
    if (!selectedRows.length) {
      notify?.('Select movies before finding sources.', 'neutral');
      return;
    }
    setSourceReview({ loading: true, rows: [], error: '', title: 'Find sources' });
    try {
      const data = await previewSourceReview(selectedRows, { policy: 'ai_control' });
      setSourceReview({
        loading: false,
        submitting: false,
        rows: data.rows || [],
        blocked: data.blocked || [],
        defaults: data.defaults || {},
        error: '',
        title: 'Find sources'
      });
    } catch (error) {
      setSourceReview((current) => ({ ...current, loading: false, error: error.message }));
    }
  }

  function confirmAction() {
    onExecute({
      confirmationPhrase: aiControlDangerPhrase,
      selectedKeys,
      reviewedDownloads: reviewedForSelection
    });
  }

  return (
    <section className={cx('ai-control-result', ready ? 'ai-control-result-ready' : 'ai-control-result-blocked')}>
      <div className="ai-control-result-header">
        <div>
          <p className="screen-kicker">{plan.state || 'AI Control'}</p>
          <h3>{plan.summary || plan.message || 'Command result'}</h3>
          {plan.message && <p>{plan.message}</p>}
          {ready && <p>{customizedSelection ? `Customized selection: ${formatCount(selectedCount)} of ${formatCount(rows.length)} results.` : `Exact command selection: all ${formatCount(rows.length)} results.`}</p>}
        </div>
      </div>
      {(plan.warnings || []).map((warning) => (
        <div className="library-status library-status-warning" key={warning}><AlertTriangle size={16} /> {warning}</div>
      ))}
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
          <span>Type the confirmation phrase before deleting this selection.</span>
          <strong>{expectedDeletePhrase}</strong>
          <input
            value={aiControlDangerPhrase}
            onChange={(event) => setAiControlDangerPhrase(event.target.value)}
            placeholder="Type the confirmation phrase"
          />
        </label>
      )}
      {ready && visibleRows.length > 0 ? (
        <AIControlCardResults
          plan={plan}
          allRows={rows}
          rows={visibleRows}
          selectedKeys={selectedAiControlKeys}
          allResultsSelected={allResultsSelected}
          onToggleSelection={toggleSelection}
          onSelectAll={selectAllResults}
          onClearSelection={clearSelection}
          onFindSources={openSourceReview}
          onConfirm={confirmAction}
          confirmDisabled={!aiControlPlan?.plan_id || busy || !deletePhraseConfirmed || !selectedCount}
          busy={busy}
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
          onOpenFileDetails={onOpenFileDetails}
          onOpenDiscoverPerson={onOpenDiscoverPerson}
          onOpenDiscoverCollection={onOpenDiscoverCollection}
          gridRef={aiControlGridRef}
        />
      ) : null}
      {blocked.length > 0 && <p className="settings-empty-note">{formatCount(blocked.length)} result{blocked.length === 1 ? '' : 's'} could not be included in the selectable plan.</p>}
      {sourceReview && (
        <SourceReviewDialog
          state={sourceReview}
          setState={setSourceReview}
          onClose={() => setSourceReview(null)}
          onReviewComplete={(rowsToApply) => setReviewedDownloads(rowsToApply)}
          notify={notify}
        />
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
  allRows,
  rows,
  selectedKeys,
  allResultsSelected,
  onToggleSelection,
  onSelectAll,
  onClearSelection,
  onFindSources,
  onConfirm,
  confirmDisabled,
  busy,
  followed,
  notify,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onOpenTrailer,
  onFollow,
  onEditPoster,
  onOpenFileDetails,
  onOpenDiscoverPerson,
  onOpenDiscoverCollection,
  gridRef
}) {
  const [ownership, setOwnership] = useState(() => buildAiControlOwnershipMap(rows));
  const [userLists, setUserLists] = useState([]);
  const [detailsCache, setDetailsCache] = useState({});
  const {
    clear: clearCollectionCache,
    getView: getCollectionView,
    load: loadMovieCollection
  } = useMovieCollectionCache();
  const [expandedMovieKey, setExpandedMovieKey] = useState('');
  const [listEditorTarget, setListEditorTarget] = useState(null);
  const ownershipRequestSeq = useRef(0);
  const movies = rows || [];
  const ownershipScopeKey = useMemo(() => (
    `${plan?.plan_id || ''}:${movies.map((movie) => movieIdentityKey(movie)).join('|')}`
  ), [plan?.plan_id, movies]);

  useEffect(() => {
    const clearDetailCaches = () => {
      setDetailsCache(markMovieDetailsCacheStale);
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
    loadMovieCollection(details);
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

  const selectedAiControlMovies = useMemo(() => (
    (allRows || [])
      .filter((movie) => selectedKeys.has(movie.selection_key))
      .map((movie) => discoverMoviePayload(movie, movie.path ? movie : null))
  ), [allRows, selectedKeys]);

  return (
    <div className="ai-control-card-results">
      <div className="bulk-selection-bar discover-bulk-selection ai-control-card-toolbar">
        <SelectionCheckbox
          className="discover-selection-master"
          checked={allResultsSelected}
          onChange={(checked) => { if (checked) onSelectAll(); else onClearSelection(); }}
          label="Select all AI Control results"
        />
        <span>{formatCount(selectedAiControlMovies.length)} selected</span>
        <button type="button" className="mini-action" onClick={onSelectAll}>Select all results</button>
        <button type="button" className="mini-action" onClick={onClearSelection} disabled={!selectedAiControlMovies.length}>Clear</button>
        <button type="button" className="mini-action" onClick={() => setListEditorTarget({ bulkItems: selectedAiControlMovies })} disabled={!selectedAiControlMovies.length}>
          <CirclePlus size={13} /> Add to list
        </button>
        <button type="button" className="mini-action mini-action-source" onClick={onFindSources} disabled={!selectedAiControlMovies.length || busy}>
          <Search size={13} /> Find sources
        </button>
        <button type="button" className="btn btn-primary ai-control-confirm-action" onClick={onConfirm} disabled={confirmDisabled}>
          {busy ? <Loader2 size={15} className="spin" /> : <Check size={15} />} Confirm action
        </button>
      </div>

      <DiscoverResultGrid gridRef={gridRef} emptyText="No AI Control movies are available for card display.">
        {movies.map((movie, index) => {
          const owned = ownedMovieFor(movie, ownership) || (movie.path ? movie : null);
          const details = detailsCache[movieDetailsCacheKey(movie, owned)] || null;
          const collectionView = getCollectionView(details);
          const movieWithDetails = details ? { ...movie, plot: movie.plot || details.plot || '', release_date: movie.release_date || details.release_date || '' } : movie;
          return (
            <DiscoverMovieCard
              key={`${movie.tmdb_id || movie.path || movie.title}-${movie.year}-${index}`}
              movie={movieWithDetails}
              owned={owned}
              followed={followed.some((item) => movieKey(item) === movieKey(movie))}
              expanded={expandedMovieKey === movieKey(movie)}
              details={details}
              collection={collectionView.data}
              collectionStatus={collectionView.status}
              collectionError={collectionView.error}
              itemLists={listsForDiscoverMovie(movie, userLists, owned)}
              watched={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watched')}
              watchlisted={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watchlist')}
              onToggleWatched={owned ? () => toggleAiControlSystemList('watched', movie, owned) : undefined}
              onToggleWatchlist={() => toggleAiControlSystemList('watchlist', movie, owned)}
              selected={selectedKeys.has(movie.selection_key)}
              onSelect={(checked) => onToggleSelection(movie.selection_key, checked)}
              onPlay={onPlay}
              onStream={onStream}
              streamingAvailable={streamingAvailable}
              streamingLabel={streamingLabel}
              onFindTorrent={onFindTorrent}
              onFollow={onFollow}
              onTrailer={openAiControlTrailer}
              onToggleDetails={() => toggleAiControlDetails(movie, owned)}
              onPersonBrowse={(role, person) => onOpenDiscoverPerson(movieWithDetails, role, person)}
              onCollectionBrowse={(collection) => onOpenDiscoverCollection(movieWithDetails, collection)}
              onCollectionRetry={() => loadMovieCollection(details, { force: true })}
              onEditLists={() => setListEditorTarget(discoverMoviePayload(movie, owned))}
              onRemoveFromList={(listId) => removeAiControlMovieFromList(listId, discoverMoviePayload(movie, owned))}
              onEditPoster={owned?.path ? () => onEditPoster?.(owned, movie) : undefined}
              onOpenFileDetails={onOpenFileDetails}
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
