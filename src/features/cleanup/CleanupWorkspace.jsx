import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Clapperboard,
  Film,
  Folder,
  Loader2,
  Play,
  RefreshCcw,
  ScanSearch,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react'
import { fetchJson } from '../../api/client.js'
import { announceLibraryChanged } from '../../api/library.js'
import {
  applyPlexMetadataMatch,
  applyTmdbMetadataMatch,
  requestPlexLibraryScan,
  searchPlexMetadata,
  searchTmdbMetadata,
} from '../../api/metadata.js'
import IdentityReviewPanel from '../../components/IdentityReviewPanel.jsx'
import { ConfirmDialog, LibraryRenameModal, LibraryStat } from '../../components/LibraryControls.jsx'
import Pagination from '../../components/Pagination.jsx'
import { SmartMatchControls, SmartMatchReviewModal } from '../../components/SmartMatchPanel.jsx'
import { cx, formatCount } from '../../utils/appUtils.js'
import { deletionPlanSummary } from '../../utils/deletionPlan.js'
import {
  metadataStatusChipClass,
  metadataStatusLabel,
  renameModalItem,
} from '../../utils/cleanupUtils.js'
import { getQualityFactsLabel, isLowQuality, rootLabel } from '../../utils/libraryUtils.js'
import { formatVoteCount } from '../../utils/moviePresentation.js'

const maintenanceTabs = [
  { id: 'storage', label: 'Storage', icon: ShieldCheck },
  { id: 'identity', label: 'Identity', icon: ScanSearch },
];
const MAINTENANCE_PAGE_SIZE = 50;

function maintenanceTab(initialTab) {
  if (initialTab === 'unmatched' || initialTab === 'identity') return 'identity';
  return 'storage';
}

function duplicateVerdictLabel(file) {
  if (file.verdict_label) return file.verdict_label;
  if (file.role === 'keep') return 'Recommended keep';
  if (file.recommendation === 'recommended') return 'Recommended removal';
  return 'Manual comparison';
}

function duplicateVerdictClass(tone) {
  if (tone === 'success') return 'status-owned';
  if (tone === 'neutral') return 'chip-muted';
  return 'chip-warning';
}

function formatDurationMs(value) {
  const totalSeconds = Math.round(Number(value || 0) / 1000);
  if (!totalSeconds) return '';
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours ? `${hours}h` : '', `${minutes}m`, `${seconds}s`].filter(Boolean).join(' ');
}

export default function CleanupWorkspace({ notify, onPlay, initialTab = 'storage', onHealthChanged, onOpenLibraryUpgrades }) {
  const [activeTab, setActiveTab] = useState(maintenanceTab(initialTab));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [audit, setAudit] = useState({ summary: {}, storage: { groups: [], pagination: {} }, identity: { items: [], pagination: {} } });
  const [selected, setSelected] = useState({ storage: new Set(), identity: new Set() });
  const [pages, setPages] = useState({ storage: 1, identity: 1 });
  const [filters, setFilters] = useState({ query: '' });
  const [confirmAction, setConfirmAction] = useState(null);
  const [renameTarget, setRenameTarget] = useState(null);
  const [matchModal, setMatchModal] = useState(null);
  const [rowStatus, setRowStatus] = useState({});
  const [smartMatchJob, setSmartMatchJob] = useState(null);
  const [lastSmartMatchJob, setLastSmartMatchJob] = useState(null);
  const [identityAudit, setIdentityAudit] = useState(null);
  const [identityApprovedProposal, setIdentityApprovedProposal] = useState(null);
  const [identityHealthJob, setIdentityHealthJob] = useState('');
  const [ollamaAvailable, setOllamaAvailable] = useState(false);
  const [smartMatchProviders, setSmartMatchProviders] = useState({ tmdb: true, plex: true });
  const maintenanceSelectionScope = `${activeTab}|${filters.query.trim()}`;
  const previousMaintenanceSelectionScopeRef = useRef(maintenanceSelectionScope);
  const duplicateSelectionTrackingRef = useRef({
    scope: maintenanceSelectionScope,
    userTouched: new Set(),
    autoSelected: new Set(),
  });

  useEffect(() => {
    setActiveTab(maintenanceTab(initialTab));
  }, [initialTab]);

  const loadMaintenanceSection = useCallback(async (section, page, query) => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        section,
        page: String(page || 1),
        page_size: String(MAINTENANCE_PAGE_SIZE),
      });
      if (query.trim()) params.set('q', query.trim());
      const state = await fetchJson(`/api/maintenance/audit?${params.toString()}`);
      setAudit((current) => ({
        ...current,
        ...state,
        storage: state.storage
          ? { ...state.storage, selection_scope: `${section}|${query.trim()}` }
          : current.storage,
        identity: state.identity || current.identity,
      }));
      if (state.identity_review) setIdentityAudit(state.identity_review);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      loadMaintenanceSection(activeTab, pages[activeTab] || 1, filters.query);
    }, filters.query ? 180 : 0);
    return () => window.clearTimeout(timer);
  }, [activeTab, filters.query, loadMaintenanceSection, pages]);

  useEffect(() => {
    if (previousMaintenanceSelectionScopeRef.current === maintenanceSelectionScope) return;
    previousMaintenanceSelectionScopeRef.current = maintenanceSelectionScope;
    duplicateSelectionTrackingRef.current = {
      scope: maintenanceSelectionScope,
      userTouched: new Set(),
      autoSelected: new Set(),
    };
    setSelected({ storage: new Set(), identity: new Set() });
  }, [maintenanceSelectionScope]);

  useEffect(() => {
    if (activeTab !== 'storage' || audit.storage.selection_scope !== maintenanceSelectionScope) return;
    const groups = audit.storage.groups || [];
    const visiblePaths = new Set(groups.flatMap((group) => (group.files || []).map((file) => file.path)));
    const recommendedPaths = new Set(groups.flatMap((group) => {
      const files = group.files || [];
      return files
        .filter((file) => file.recommendation === 'recommended')
        .slice(0, Math.max(0, files.length - 1))
        .map((file) => file.path);
    }));
    const tracking = duplicateSelectionTrackingRef.current;
    if (tracking.scope !== maintenanceSelectionScope) return;

    setSelected((state) => {
      const next = new Set(state.storage);
      let changed = false;
      for (const path of [...tracking.autoSelected]) {
        if (visiblePaths.has(path) && !recommendedPaths.has(path) && !tracking.userTouched.has(path)) {
          tracking.autoSelected.delete(path);
          if (next.delete(path)) changed = true;
        }
      }
      for (const path of recommendedPaths) {
        if (tracking.userTouched.has(path) || tracking.autoSelected.has(path)) continue;
        tracking.autoSelected.add(path);
        if (!next.has(path)) {
          next.add(path);
          changed = true;
        }
      }
      return changed ? { ...state, storage: next } : state;
    });
  }, [activeTab, audit.storage.groups, audit.storage.selection_scope, maintenanceSelectionScope]);

  useEffect(() => {
    const refreshForLibraryChange = () => {
      setPages((current) => ({ ...current, [activeTab]: 1 }));
      loadMaintenanceSection(activeTab, 1, filters.query);
    };
    window.addEventListener('cp-library-changed', refreshForLibraryChange);
    return () => window.removeEventListener('cp-library-changed', refreshForLibraryChange);
  }, [activeTab, filters.query, loadMaintenanceSection]);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      fetchJson('/api/ollama/config'),
      fetchJson('/api/metadata/smart-match')
    ]).then(([ollama, smart]) => {
      if (cancelled) return;
      if (ollama.status === 'fulfilled') {
        setOllamaAvailable(Boolean(ollama.value.url && ollama.value.model));
      }
      if (smart.status === 'fulfilled') {
        setSmartMatchProviders(smart.value.providers || { tmdb: true, plex: true });
        if (['running', 'paused'].includes(smart.value.status) && smart.value.id) {
          setSmartMatchJob(smart.value);
        } else if (smart.value.status === 'completed' && smart.value.id) {
          setLastSmartMatchJob(smart.value);
        }
      }
    })
      .catch(() => {});
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (identityAudit?.status !== 'running' || !identityAudit.id) return undefined;
    const timer = window.setInterval(async () => {
      try {
        setIdentityAudit(await fetchJson(`/api/metadata/identity-audit/${encodeURIComponent(identityAudit.id)}`));
      } catch (pollError) {
        setError(pollError.message);
      }
    }, 900);
    return () => window.clearInterval(timer);
  }, [identityAudit?.id, identityAudit?.status]);

  useEffect(() => {
    if (identityAudit?.status !== 'completed' || !identityAudit.id || identityHealthJob === identityAudit.id) return;
    setIdentityHealthJob(identityAudit.id);
    onHealthChanged();
  }, [identityAudit?.id, identityAudit?.status, identityHealthJob, onHealthChanged]);

  const identityItems = useMemo(() => audit.identity.items || [], [audit.identity.items]);
  const visibleUnmatched = useMemo(() => identityItems.filter((item) => !item.metadata_accepted), [identityItems]);

  const summary = audit.summary;

  function updateFilter(key, value) {
    setFilters((state) => ({ ...state, [key]: value }));
    setPages({ storage: 1, identity: 1 });
  }

  function selectMaintenanceTab(tab) {
    setActiveTab(tab);
    setPages((state) => ({ ...state, [tab]: 1 }));
  }

  function toggleSelected(tab, path, checked) {
    setSelected((state) => {
      const next = new Set(state[tab]);
      if (checked) next.add(path);
      else next.delete(path);
      return { ...state, [tab]: next };
    });
  }

  function toggleDuplicateSelected(groupPaths, path, checked) {
    const tracking = duplicateSelectionTrackingRef.current;
    tracking.userTouched.add(path);
    tracking.autoSelected.delete(path);
    setSelected((state) => {
      const next = new Set(state.storage);
      if (checked) {
        next.add(path);
        if (groupPaths.length > 1 && groupPaths.every((groupPath) => next.has(groupPath))) {
          notify('Keep at least one copy in each duplicate group.', 'error');
          return state;
        }
      } else {
        next.delete(path);
      }
      return { ...state, storage: next };
    });
  }

  function setSelectedPaths(tab, paths, checked) {
    if (tab === 'storage') {
      const tracking = duplicateSelectionTrackingRef.current;
      paths.forEach((path) => {
        tracking.userTouched.add(path);
        tracking.autoSelected.delete(path);
      });
    }
    setSelected((state) => {
      const next = new Set(state[tab]);
      paths.forEach((path) => {
        if (checked) next.add(path);
        else next.delete(path);
      });
      return { ...state, [tab]: next };
    });
  }

  async function requestDelete(tab, paths, title) {
    const uniquePaths = [...new Set(paths.filter(Boolean))];
    if (!uniquePaths.length) return;
    try {
      const plan = await fetchJson('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths: uniquePaths, trash: true, preview: true })
      });
      setConfirmAction({
        type: 'delete',
        tab,
        paths: uniquePaths,
        title,
        plan,
        body: deletionPlanSummary(plan)
      });
    } catch (previewError) {
      notify(`Delete preview failed: ${previewError.message}`, 'error');
    }
  }

  function requestFixPath(item) {
    setConfirmAction({
      type: 'fix-path',
      item,
      title: 'Move file for metadata scan?',
      body: `Fix Path will move this file or its movie folder within the library root, then refresh metadata scan paths.\n\n${item.path}`
    });
  }

  async function runConfirmedAction() {
    if (!confirmAction) return;
    if (confirmAction.type === 'delete') {
      await deletePaths(confirmAction.tab, confirmAction.paths, confirmAction.plan);
    } else if (confirmAction.type === 'fix-path') {
      await fixPath(confirmAction.item);
    }
    setConfirmAction(null);
  }

  async function deletePaths(tab, paths, plan) {
    const folderTargets = (plan?.actions || [])
      .filter((action) => action.target_type === 'folder')
      .map((action) => action.target);
    try {
      const result = await fetchJson('/api/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paths, trash: true, folder_targets: folderTargets })
      });
      const deletedPaths = result.deleted_paths || [];
      if (deletedPaths.length) {
        removeDeletedPaths(deletedPaths);
        announceLibraryChanged({
          source: 'maintenance-delete',
          deleted_paths: deletedPaths,
          catalog_generation: result.catalog_generation
        });
        const folderNote = result.folder_count
          ? `, including ${result.folder_count} complete folder${result.folder_count === 1 ? '' : 's'}`
          : '';
        notify(`${deletedPaths.length} movie file${deletedPaths.length === 1 ? '' : 's'} moved to Recycle Bin${folderNote}`);
      }
      (result.failures || []).forEach((failure) => notify(`Delete failed: ${failure.error}`, 'error'));
    } catch (error) {
      notify(`Delete failed: ${error.message}`, 'error');
    }
    setSelected((state) => ({ ...state, [tab]: new Set() }));
  }

  function removeDeletedPaths(paths) {
    const pathSet = new Set(paths);
    setAudit((state) => ({
      ...state,
      storage: {
        groups: state.storage.groups
        .map((group) => ({ ...group, files: (group.files || []).filter((file) => !pathSet.has(file.path)) }))
        .filter((group) => (group.files || []).length > 1),
      },
      identity: {
        ...state.identity,
        items: state.identity.items.filter((item) => !pathSet.has(item.path)),
      },
    }));
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
      const result = await fetchJson('/api/rename-file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: renameTarget.path, title, year })
      });
      setAudit((state) => ({
        ...state,
        identity: {
          ...state.identity,
          items: state.identity.items.map((item) => item.path === renameTarget.path ? {
          ...item,
          path: result.new_path,
          filename: result.new_filename,
          suggested_title: title,
          suggested_year: year
          } : item),
        },
      }));
      setRenameTarget(null);
      notify(`Renamed to ${result.new_filename}`);
    } catch (error) {
      notify(`Rename failed: ${error.message}`, 'error');
    }
  }

  async function fixPath(item) {
    setRowStatus((state) => ({ ...state, [item.path]: { tone: 'neutral', text: 'Moving file...' } }));
    try {
      const result = await fetchJson('/api/fix-path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: item.path })
      });
      setRowStatus((state) => ({ ...state, [result.new_path || item.path]: { tone: 'success', text: `Moved to ${result.new_path}` } }));
      setAudit((state) => ({
        ...state,
        identity: {
          ...state.identity,
          items: state.identity.items.map((entry) => entry.path === item.path ? { ...entry, path: result.new_path || entry.path, fixable_path: false } : entry),
        },
      }));
      notify('File moved, metadata rescan requested');
    } catch (error) {
      setRowStatus((state) => ({ ...state, [item.path]: { tone: 'error', text: error.message } }));
      notify(`Fix Path failed: ${error.message}`, 'error');
    }
  }

  function openPlexMatch(item, context = 'unmatched') {
    setMatchModal({
      provider: 'plex',
      context,
      item,
      ratingKey: item.rating_key || '',

      title: item.suggested_title || item.current?.title || item.candidate?.title || '',
      year: item.suggested_year || item.current?.year || item.candidate?.year || '',
      loading: false,
      scanBusy: false,
      scanRequested: false,
      needsPlexScan: false,
      applying: '',
      error: '',
      results: []
    });
  }

  function openTmdbMatch(item, context = 'unmatched') {
    setMatchModal({
      provider: 'tmdb',
      context,
      item,
      title: item.suggested_title || item.current?.title || item.tmdb_title || item.candidate?.title || '',
      year: item.suggested_year || item.current?.year || item.tmdb_year || item.candidate?.year || '',
      loading: false,
      applying: '',
      error: '',
      results: []
    });
  }

  async function runPlexMatchSearch() {
    if (!matchModal?.item?.path) return;
    setMatchModal((state) => ({ ...state, loading: true, error: '', results: [] }));
    try {
      const result = await searchPlexMetadata({
        path: matchModal.item.path,
        title: matchModal.title,
        year: matchModal.year,
        ratingKey: matchModal.ratingKey,
        forceSearch: matchModal.context === 'identity',
      });
      setMatchModal((state) => ({
        ...state,
        loading: false,
        needsPlexScan: false,
        ratingKey: result.rating_key || state.ratingKey,
        results: result.results || []
      }));
    } catch (error) {
      setMatchModal((state) => ({
        ...state,
        loading: false,
        needsPlexScan: error.data?.code === 'plex_item_not_indexed',
        error: error.message
      }));
    }
  }

  async function searchPlexMatch(event) {
    event.preventDefault();
    await runPlexMatchSearch();
  }

  async function requestPlexScanAndRetry() {
    if (!matchModal?.item?.path) return;
    setMatchModal((state) => ({ ...state, scanBusy: true, error: '' }));
    try {
      await requestPlexLibraryScan();
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      setMatchModal((state) => ({ ...state, scanRequested: true }));
      await runPlexMatchSearch();
      setMatchModal((state) => ({ ...state, scanBusy: false }));
    } catch (error) {
      setMatchModal((state) => ({ ...state, scanBusy: false, scanRequested: true, error: error.message }));
    }
  }

  async function searchTmdbMatch(event) {
    event.preventDefault();
    if (!matchModal?.item) return;
    setMatchModal((state) => ({ ...state, loading: true, error: '', results: [] }));
    try {
      const result = await searchTmdbMetadata({
        title: matchModal.title,
        year: matchModal.year,
        fallback: matchModal.item.filename,
      });
      setMatchModal((state) => ({ ...state, loading: false, results: result.results || [] }));
    } catch (error) {
      setMatchModal((state) => ({ ...state, loading: false, error: error.message }));
    }
  }

  async function applyPlexMatch(match) {
    const ratingKey = matchModal?.ratingKey || matchModal?.item?.rating_key;
    if (!ratingKey || !match?.guid) return;
    setMatchModal((state) => ({ ...state, applying: match.guid, error: '' }));
    try {
      await applyPlexMetadataMatch({
        path: matchModal.item.path,
        ratingKey,
        match,
      });
      setRowStatus((state) => ({ ...state, [matchModal.item.path]: { tone: 'success', text: `Plex match applied: ${match.name}` } }));
      if (matchModal.context === 'identity') {
        setIdentityApprovedProposal({
          ...matchModal.item,
          candidate: {
            plex_guid: match.guid,
            title: match.name || match.title,
            year: match.year || ''
          }
        });
        setIdentityAudit(await fetchJson('/api/metadata/identity-audit'));
      } else {
        await loadMaintenanceSection(activeTab, pages[activeTab] || 1, filters.query);
      }
      setMatchModal(null);
      onHealthChanged();
      notify('Plex match applied');
    } catch (error) {
      setMatchModal((state) => ({ ...state, applying: '', error: error.message }));
    }
  }

  async function applyTmdbMatch(match) {
    if (!matchModal?.item?.path || !match?.tmdb_id) return;
    setMatchModal((state) => ({ ...state, applying: String(match.tmdb_id), error: '' }));
    try {
      await applyTmdbMetadataMatch({
        path: matchModal.item.path,
        match,
      });
      if (matchModal.context === 'identity') {
        setIdentityApprovedProposal({ ...matchModal.item, candidate: match });
        setIdentityAudit(await fetchJson('/api/metadata/identity-audit'));
      } else {
        await loadMaintenanceSection(activeTab, pages[activeTab] || 1, filters.query);
      }
      setRowStatus((state) => ({ ...state, [matchModal.item.path]: { tone: 'success', text: `TMDB match applied: ${match.title}` } }));
      setMatchModal(null);
      onHealthChanged();
      notify('TMDB match applied');
    } catch (error) {
      setMatchModal((state) => ({ ...state, applying: '', error: error.message }));
    }

  }

  async function startIdentityAudit() {
    if (!window.confirm('Start a new identity scan? Current scan progress and displayed results will be cleared. Previously verified unchanged movies will remain skipped.')) return;
    try {
      setIdentityAudit(await fetchJson('/api/metadata/identity-audit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      }));
      setError('');
    } catch (auditError) {
      setError(auditError.message);
    }
  }

  async function pauseIdentityAudit() {
    if (!identityAudit?.id) return;
    try {
      setIdentityAudit(await fetchJson(`/api/metadata/identity-audit/${encodeURIComponent(identityAudit.id)}/pause`, {
        method: 'POST'
      }));
    } catch (auditError) {
      setError(auditError.message);
    }
  }

  async function resumeIdentityAudit() {
    if (!identityAudit?.id) return;
    try {
      setIdentityAudit(await fetchJson(`/api/metadata/identity-audit/${encodeURIComponent(identityAudit.id)}/resume`, {
        method: 'POST'
      }));
      setError('');
    } catch (auditError) {
      setError(auditError.message);
    }
  }

  async function refreshIdentityAudit() {
    try {
      setIdentityAudit(await fetchJson('/api/metadata/identity-audit'));
    } catch (auditError) {
      setError(auditError.message);
    }
  }

  const activeSelectedCount = selected[activeTab]?.size || 0;

  return (
    <section className="cleanup-workspace">
      <div className="library-header cleanup-header">
        <div>
          <p className="screen-kicker">Catalog-backed maintenance</p>
          <h2>Library Maintenance <span className="offline-badge">Local</span></h2>
          <p>Archive integrity for duplicate files and movie identity. Upgrade discovery now lives in Library.</p>
        </div>
        <div className="library-header-actions">
          <div className="library-action-row">
            <button type="button" className="btn btn-secondary" onClick={() => loadMaintenanceSection(activeTab, pages[activeTab] || 1, filters.query)} disabled={loading}>
              <RefreshCcw size={15} /> Refresh
            </button>
            {activeTab !== 'storage' && activeSelectedCount > 0 && (
              <button type="button" className="btn btn-danger" onClick={() => requestDelete(activeTab, [...selected[activeTab]], `Move ${activeSelectedCount} selected file${activeSelectedCount === 1 ? '' : 's'} to Recycle Bin?`)}>
                <Trash2 size={15} /> Delete selected ({activeSelectedCount})
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="library-stat-strip cleanup-stat-strip">
        <LibraryStat icon={ShieldCheck} label="Duplicate groups" value={formatCount(summary.duplicate_groups)} tone="amber" onClick={() => selectMaintenanceTab('storage')} />
        <LibraryStat icon={Trash2} label="Recommended reclaimable" value={summary.reclaimable_human || '0 B'} tone="red" onClick={() => selectMaintenanceTab('storage')} />
        <LibraryStat icon={CheckCircle2} label="Recommended removals" value={formatCount(summary.recommended_removals)} tone="green" onClick={() => selectMaintenanceTab('storage')} />
        <LibraryStat icon={Clapperboard} label="Upgrade candidates" value={formatCount(summary.upgrade_candidates)} tone="amber" onClick={onOpenLibraryUpgrades} />
        <LibraryStat icon={ScanSearch} label="Unmatched files" value={formatCount(summary.unmatched_files)} tone="violet" onClick={() => selectMaintenanceTab('identity')} />
        <LibraryStat icon={AlertTriangle} label="Actionable identities" value={formatCount(summary.actionable_identities)} tone="amber" onClick={() => selectMaintenanceTab('identity')} />
        {summary.metadata_pending > 0 && <LibraryStat icon={Loader2} label="Metadata pending" value={formatCount(summary.metadata_pending)} tone="amber" />}
      </div>

      <div className="cleanup-tabs" role="tablist" aria-label="Cleanup workspace tabs">
        {maintenanceTabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button type="button" role="tab" aria-selected={activeTab === tab.id} className={cx(activeTab === tab.id && 'cleanup-tab-active')} key={tab.id} onClick={() => selectMaintenanceTab(tab.id)}>
              <Icon size={16} /> {tab.label}
            </button>
          );
        })}
      </div>

      <div className="library-toolbar cleanup-toolbar">
        <label className="library-search cleanup-search">
          <Search size={17} />
          <input value={filters.query} onChange={(event) => updateFilter('query', event.target.value)} placeholder="Search files, paths, or catalog titles..." />
        </label>
      </div>

      {error && (
        <div className="library-status library-status-error">
          <AlertTriangle size={16} />
          <span>{error}</span>
        </div>
      )}

      {loading ? (
        <div className="library-status">
          <Loader2 size={16} className="spin" />
          <span>Refreshing the maintenance audit...</span>
        </div>
      ) : (
        <>
          {activeTab === 'storage' && (
            <>
              <MaintenancePagination pagination={audit.storage.pagination} onPageChange={(page) => setPages((state) => ({ ...state, storage: page }))} />
              <DuplicatesCleanupTab groups={audit.storage.groups} selected={selected.storage} onToggle={toggleDuplicateSelected} onSelectPaths={setSelectedPaths} onDelete={requestDelete} onPlay={onPlay} />
            </>
          )}
          {activeTab === 'identity' && (
            <>
              <MaintenancePagination pagination={audit.identity.pagination} onPageChange={(page) => setPages((state) => ({ ...state, identity: page }))} />
              {visibleUnmatched.length > 0 && (
                <UnmatchedCleanupTab
                  items={visibleUnmatched}
                  selected={selected.identity}
                  rowStatus={rowStatus}
                  onToggle={toggleSelected}
                  onPlay={onPlay}
                  onDelete={requestDelete}
                  onRename={setRenameTarget}
                  onFixPath={requestFixPath}
                  onPlexMatch={openPlexMatch}
                  onTmdbMatch={openTmdbMatch}
                  plexAvailable={smartMatchProviders.plex !== false}
                  smartControls={selected.identity.size > 0 ? (
                    <SmartMatchControls
                      selectedPaths={[...selected.identity]}
                      ollamaAvailable={ollamaAvailable}
                      providers={smartMatchProviders}
                      onStarted={setSmartMatchJob}
                      notify={notify}
                    />
                  ) : null}
                  lastSmartMatchControl={lastSmartMatchJob ? (
                    <button type="button" className="btn btn-secondary" onClick={() => setSmartMatchJob(lastSmartMatchJob)}>
                      Open last Smart Match review
                    </button>
                  ) : null}
                />
              )}
              {identityItems.length === 0 && <CleanupEmpty title="No unmatched files." text="New unmatched files appear here after normal catalog reconciliation." />}
            </>
          )}
          {activeTab === 'identity' && (
            <IdentityReviewPanel
              audit={identityAudit}
              items={identityAudit?.proposals || []}
              loading={false}
              error=""
              plexAvailable={smartMatchProviders.plex !== false}
              onStart={startIdentityAudit}
              onPause={pauseIdentityAudit}
              onResume={resumeIdentityAudit}
              onRefresh={refreshIdentityAudit}
              onAuditChanged={setIdentityAudit}
              onPlay={onPlay}
              onTmdbMatch={(proposal) => openTmdbMatch(proposal, 'identity')}
              onPlexMatch={(proposal) => openPlexMatch(proposal, 'identity')}
              onHealthChanged={onHealthChanged}
              externalApproved={identityApprovedProposal}
              onExternalApprovedConsumed={() => setIdentityApprovedProposal(null)}
              notify={notify}
            />
          )}
        </>
      )}

      {confirmAction && (
        <ConfirmDialog
          title={confirmAction.title}
          body={confirmAction.body}
          confirmLabel={confirmAction.type === 'delete' ? 'Move to Recycle Bin' : 'Move file'}
          danger={confirmAction.type === 'delete'}
          onCancel={() => setConfirmAction(null)}
          onConfirm={runConfirmedAction}
        />
      )}
      {renameTarget && (
        <LibraryRenameModal
          item={renameModalItem(renameTarget)}
          onClose={() => setRenameTarget(null)}
          onSubmit={submitRename}
        />
      )}
      {matchModal && (
        matchModal.provider === 'tmdb' ? (
          <TmdbMatchModal
            state={matchModal}
            onClose={() => setMatchModal(null)}
            onChange={(patch) => setMatchModal((state) => ({ ...state, ...patch }))}
            onSearch={searchTmdbMatch}
            onApply={applyTmdbMatch}
          />
        ) : (
          <PlexMatchModal
            state={matchModal}
            onClose={() => setMatchModal(null)}
            onChange={(patch) => setMatchModal((state) => ({ ...state, ...patch }))}
            onSearch={searchPlexMatch}
            onScanRetry={requestPlexScanAndRetry}
            onApply={applyPlexMatch}
          />
        )
      )}
      {smartMatchJob && (
        <SmartMatchReviewModal
          job={smartMatchJob}
          items={audit.identity.items}
          onJobChange={setSmartMatchJob}
          onClose={() => setSmartMatchJob(null)}
          onApplied={(paths) => {
            const applied = new Set(paths);
            setAudit((state) => ({ ...state, identity: { ...state.identity, items: state.identity.items.filter((item) => !applied.has(item.path)) } }));
            setSelected((state) => ({ ...state, identity: new Set() }));
          }}
          onTmdbMatch={(item) => { setSmartMatchJob(null); openTmdbMatch(item); }}
          onPlexMatch={(item) => { setSmartMatchJob(null); openPlexMatch(item); }}
          plexAvailable={smartMatchProviders.plex !== false}
          notify={notify}
        />
      )}
    </section>
  );
}

function DuplicatesCleanupTab({ groups, selected, onToggle, onSelectPaths, onDelete, onPlay }) {
  const visibleRecommended = groups.flatMap((group) => (group.files || []).filter((file) => file.recommendation === 'recommended').map((file) => file.path));
  const selectedPaths = [...selected];
  return (
    <div className="cleanup-panel">
      <CleanupSelectionBar
        label={`${formatCount(groups.length)} duplicate groups`}
        selectedCount={selected.size}
        selectableCount={visibleRecommended.length}
        selectLabel="Select recommended"
        onSelectAll={() => onSelectPaths('storage', visibleRecommended, true)}
        onClear={() => onSelectPaths('storage', selectedPaths, false)}
        onDeleteSelected={() => onDelete('storage', selectedPaths, `Move ${selected.size} selected file${selected.size === 1 ? '' : 's'} to Recycle Bin?`)}
      />
      {groups.length ? groups.map((group) => {
        const groupPaths = (group.files || []).map((file) => file.path);
        return (
          <article className="duplicate-group-card" key={group.key || group.title}>
            <header>
              <div>
                <h3>{group.title}</h3>
                <p>{formatCount((group.files || []).length)} copies found. {formatCount(group.recommended_count)} recommended removal{group.recommended_count === 1 ? '' : 's'}; play any copy before changing the selection.</p>
                {group.needs_identity_review && <p className="cleanup-hint">The shared movie identity needs manual confirmation, so CP has not preselected a deletion.</p>}
                {group.comparison_scope && <p className="cleanup-hint">Evidence scope: {group.comparison_scope}. Verdicts separate content equivalence, technical quality, and storage efficiency.</p>}
              </div>
            </header>
            <div className="cleanup-file-list">
              {(group.files || []).map((file) => (
                <CleanupFileRow
                  key={file.path}
                  item={file}
                  selected={selected.has(file.path)}
                  selectable
                  badge={duplicateVerdictLabel(file)}
                  badgeTone={file.verdict_tone}
                  onToggle={(checked) => onToggle(groupPaths, file.path, checked)}
                  onDelete={() => onDelete('storage', [file.path], `Move ${file.filename} to Recycle Bin?`)}
                  actions={(
                    <button type="button" className="btn btn-primary btn-green" onClick={() => onPlay(file.path)}>
                      <Play size={15} /> Play file
                    </button>
                  )}
                />
              ))}
            </div>
          </article>
        );
      }) : <CleanupEmpty title="No duplicate groups match this view." text="Refresh or adjust search when new files are added." />}
    </div>
  );
}

function UnmatchedCleanupTab({ items, selected, rowStatus, onToggle, onPlay, onDelete, onRename, onFixPath, onPlexMatch, onTmdbMatch, plexAvailable, smartControls, lastSmartMatchControl }) {
  return (
    <div className="cleanup-panel">
      <CleanupSelectionBar
        label={`${formatCount(items.length)} unmatched files`}
        selectedCount={selected.size}
        selectableCount={items.length}
        onSelectAll={() => items.forEach((item) => onToggle('identity', item.path, true))}
        onClear={() => [...selected].forEach((path) => onToggle('identity', path, false))}
      />
      {smartControls}
      {lastSmartMatchControl && <div className="cleanup-secondary-action">{lastSmartMatchControl}</div>}
      {items.length ? (
        <div className="cleanup-file-list">
          {items.map((item) => (
            <article className="cleanup-file-row unmatched-row" key={item.path}>
              <label className="cleanup-check">
                <input type="checkbox" checked={selected.has(item.path)} onChange={(event) => onToggle('identity', item.path, event.target.checked)} />
                <span>Select</span>
              </label>
              <div className="cleanup-file-main">
                <div className="cleanup-title-line">
                  <h3>{item.filename}</h3>
                  <span className={cx('chip', metadataStatusChipClass(item))}>{metadataStatusLabel(item)}</span>
                </div>
                <div className="cleanup-path" title={item.path}>{item.path}</div>
                <div className="cleanup-meta-row">
                  <span className="chip chip-muted">{getQualityFactsLabel(item)}</span>
                  <span className="chip chip-muted">{item.rip_source || 'Unknown source'}</span>
                  <span className="chip chip-muted">{item.file_size || '?'}</span>
                  {item.library_root && <span className="chip chip-muted">{rootLabel(item.library_root)}</span>}
                  {item.fixable_path && <span className="chip chip-warning">Folder depth {item.depth}</span>}
                </div>
                <p className="cleanup-hint">{item.metadata_hint || item.plex_hint || 'No metadata hint available.'}</p>
                {rowStatus[item.path] && <p className={cx('cleanup-row-status', `cleanup-row-${rowStatus[item.path].tone}`)}>{rowStatus[item.path].text}</p>}
              </div>
              <div className="cleanup-row-actions">
                <button type="button" className="btn btn-primary btn-green" onClick={() => onPlay(item.path)}>
                  <Play size={15} /> Play file
                </button>
                <button type="button" className="btn btn-primary btn-violet" onClick={() => onTmdbMatch(item)}>
                  <Search size={15} /> Search TMDB
                </button>
                {plexAvailable && (
                  <button type="button" className="btn btn-secondary" onClick={() => onPlexMatch(item)}>
                    <Clapperboard size={15} /> Search Plex
                  </button>
                )}
                {item.fixable_path && (
                  <button type="button" className="btn btn-secondary" onClick={() => onFixPath(item)}>
                    <Folder size={15} /> Fix path
                  </button>
                )}
                {!plexAvailable && !item.fixable_path && (
                  <span className="cleanup-action-note">Plex optional</span>
                )}
                <button type="button" className="btn btn-secondary" onClick={() => onRename(item)}>
                  <Clapperboard size={15} /> Rename
                </button>
                <button type="button" className="btn btn-danger" onClick={() => onDelete('identity', [item.path], `Move ${item.filename} to Recycle Bin?`)}>
                  <Trash2 size={15} /> Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : <CleanupEmpty title="No identity issues match this view." text="New library files appear here after the normal catalog reconciliation." />}
    </div>
  );
}

function CleanupSelectionBar({ label, selectedCount, selectableCount, selectLabel = 'Select all', onSelectAll, onClear, onDeleteSelected }) {
  return (
    <div className="cleanup-selection-bar">
      <span>{label}</span>
      <strong>{formatCount(selectedCount)} selected</strong>
      <div>
        <button type="button" className="mini-action" onClick={onSelectAll} disabled={!selectableCount}>{selectLabel}</button>
        <button type="button" className="mini-action" onClick={onClear} disabled={!selectedCount}>Clear</button>
        {onDeleteSelected && (
          <button type="button" className="mini-action mini-action-danger" onClick={onDeleteSelected} disabled={!selectedCount}>
            <Trash2 size={13} /> Delete selected ({formatCount(selectedCount)})
          </button>
        )}
      </div>
    </div>
  );
}

function MaintenancePagination({ pagination = {}, onPageChange }) {
  const total = Number(pagination.total || 0);
  return (
    <Pagination
      total={total}
      page={Number(pagination.page || 1)}
      totalPages={Number(pagination.total_pages || 1)}
      pageStart={Number(pagination.page_start || 0)}
      pageEnd={Number(pagination.page_end || 0)}
      onPageChange={onPageChange}
    />
  );
}

function DuplicateDecisionEvidence({ item }) {
  const blockers = item.decision_blockers || [];
  const warnings = item.decision_warnings || [];
  const passed = item.decision_passed || [];
  const needsReview = item.recommendation === 'review';
  if (!blockers.length && !warnings.length && !passed.length) return null;

  return (
    <div className="duplicate-decision-evidence">
      {needsReview && blockers.length > 0 && (
        <section className="duplicate-decision-blockers" aria-label="Why CP did not automatically select this file">
          <strong>Why CP did not automatically select this file</strong>
          <ul>{blockers.map((message) => <li key={message}>{message}</li>)}</ul>
          <small>You can still select it manually; deletion always requires confirmation.</small>
        </section>
      )}
      {warnings.length > 0 && (
        <section className="duplicate-decision-warnings" aria-label="Comparison warnings">
          <strong>Warnings to review</strong>
          <ul>{warnings.map((message) => <li key={message}>{message}</li>)}</ul>
        </section>
      )}
      {passed.length > 0 && (
        <details className="duplicate-decision-passed">
          <summary>Evidence that passed ({passed.length})</summary>
          <ul>{passed.map((message) => <li key={message}>{message}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function CleanupFileRow({ item, selected, selectable, badge, badgeTone, onToggle, onDelete, actions }) {
  return (
    <article className="cleanup-file-row">
      <label className="cleanup-check">
        <input type="checkbox" disabled={!selectable} checked={selectable && selected} onChange={(event) => onToggle(event.target.checked)} />
        <span>{selectable ? 'Select' : 'Keep'}</span>
      </label>
      <div className="cleanup-file-main">
        <div className="cleanup-title-line">
          <h3>{item.filename}</h3>
          <span className={cx('chip', duplicateVerdictClass(badgeTone || (badge === 'Recommended keep' ? 'success' : 'warning')))}>{badge}</span>
        </div>
        <div className="cleanup-path" title={item.path}>{item.path}</div>
        <div className="cleanup-meta-row">
          <span className={cx('chip', isLowQuality(item.resolution) && 'chip-warning')}>{getQualityFactsLabel(item)}</span>
          {item.video_codec && <span className="chip chip-muted">{item.video_codec}{item.video_bit_depth ? ` · ${item.video_bit_depth}-bit` : ''}{item.video_bitrate ? ` · ${(item.video_bitrate / 1000000).toFixed(2)} Mbps` : ''}</span>}
          {item.audio_codec && <span className="chip chip-muted">{item.audio_codec}{item.audio_channels ? ` · ${item.audio_channels} ch` : ''}</span>}
          {item.duration_ms > 0 && <span className="chip chip-muted">{formatDurationMs(item.duration_ms)}</span>}
          {item.comparison_uses_frame_rate && item.video_frame_rate > 0 && <span className="chip chip-muted">{Number(item.video_frame_rate).toFixed(3).replace(/0+$/, '').replace(/\.$/, '')} fps</span>}
          {item.comparison_uses_aspect_ratio && item.aspect_delta_percent != null && <span className="chip chip-muted">Framing Δ {Number(item.aspect_delta_percent).toFixed(2)}%</span>}
          <span className="chip chip-muted">{item.rip_source || 'Unknown source'}</span>
          <span className="chip chip-muted">{item.size_human || item.file_size || '?'}</span>
          {item.library_root && <span className="chip chip-muted">{rootLabel(item.library_root)}</span>}
        </div>
        {item.reason && <p className={cx('cleanup-comparison-reason', `cleanup-comparison-${item.verdict_tone || 'warning'}`)}>{item.reason}</p>}
        <DuplicateDecisionEvidence item={item} />
      </div>
      <div className="cleanup-row-actions">
        {actions}
        {selectable && (
          <button type="button" className="btn btn-danger" onClick={onDelete}>
            <Trash2 size={15} /> Delete
          </button>
        )}
      </div>
    </article>
  );
}

function CleanupEmpty({ title, text }) {
  return (
    <div className="empty-state library-empty cleanup-empty">
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

function TmdbMatchModal({ state, onClose, onChange, onSearch, onApply }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="torrent-dialog cleanup-match-dialog" role="dialog" aria-modal="true" aria-label="TMDB match search" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">TMDB match</p>
            <h2>{state.item.filename}</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close TMDB match dialog">
            <X size={18} />
          </button>
        </div>
        <form className="cleanup-match-form" onSubmit={onSearch}>
          <label className="dialog-field">
            <span>Search title</span>
            <input value={state.title} onChange={(event) => onChange({ title: event.target.value })} />
          </label>
          <label className="dialog-field">
            <span>Year</span>
            <input value={state.year} onChange={(event) => onChange({ year: event.target.value })} inputMode="numeric" />
          </label>
          <button type="submit" className="btn btn-primary btn-violet cleanup-match-submit" disabled={state.loading}>
            {state.loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} Search TMDB
          </button>
        </form>
        {state.error && <p className="settings-inline-status settings-inline-error"><AlertTriangle size={15} /><span>{state.error}</span></p>}
        <div className="match-result-list">
          {state.results.length ? state.results.map((match) => (
            <article className="match-result-row tmdb-match-result-row" key={match.tmdb_id}>
              <span className="match-result-poster">
                {match.poster_url ? <img src={match.poster_url} alt="" loading="lazy" /> : <Film size={18} />}
              </span>
              <div>
                <strong>{match.title}</strong>
                <span>{match.year || 'Unknown year'} | {match.tmdb_rating ? `${match.tmdb_rating} - ${formatVoteCount(match.tmdb_vote_count) || 'no votes'}` : 'No rating'}</span>
                <small>{match.plot || 'No plot summary available.'}</small>
              </div>
              <button type="button" className="btn btn-secondary" onClick={() => onApply(match)} disabled={Boolean(state.applying)}>
                {state.applying === String(match.tmdb_id) ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />} Apply match
              </button>
            </article>
          )) : (
            <div className="cleanup-empty-match">Search TMDB, then choose the exact public movie identity.</div>
          )}
        </div>
      </section>
    </div>
  );
}

function PlexMatchModal({ state, onClose, onChange, onSearch, onScanRetry, onApply }) {
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="torrent-dialog cleanup-match-dialog" role="dialog" aria-modal="true" aria-label="Plex match search" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">Plex match</p>
            <h2>{state.item.filename}</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close Plex match dialog">
            <X size={18} />
          </button>
        </div>
        <form className="cleanup-match-form" onSubmit={onSearch}>
          <label className="dialog-field">
            <span>Search title</span>
            <input value={state.title} onChange={(event) => onChange({ title: event.target.value })} />
          </label>
          <label className="dialog-field">
            <span>Year</span>
            <input value={state.year} onChange={(event) => onChange({ year: event.target.value })} inputMode="numeric" />
          </label>
          <button type="submit" className="btn btn-primary cleanup-match-submit" disabled={state.loading}>
            {state.loading ? <Loader2 size={15} className="spin" /> : <Search size={15} />} Search Plex
          </button>
        </form>
        {state.error && <p className="settings-inline-status settings-inline-error"><AlertTriangle size={15} /><span>{state.error}</span></p>}
        {state.needsPlexScan && (
          <div className="cleanup-match-recovery">
            <span>Plex must index this file before its matching agents can be searched.</span>
            <button type="button" className="btn btn-secondary" onClick={onScanRetry} disabled={state.scanBusy}>
              {state.scanBusy ? <Loader2 size={15} className="spin" /> : <RefreshCcw size={15} />}
              {state.scanRequested ? 'Retry Plex lookup' : 'Request Plex scan'}
            </button>
          </div>
        )}
        <div className="match-result-list">
          {state.results.length ? state.results.map((match) => (
            <article className="match-result-row plex-match-result-row" key={match.guid}>
              <span className="match-result-poster">
                {match.poster_url ? <img src={match.poster_url} alt="" loading="lazy" /> : <Film size={18} />}
              </span>
              <div>
                <strong>{match.title || match.name}</strong>
                <span>
                  {match.year || 'Unknown year'}
                  {match.exact_external_id ? ' | Exact external ID' : ''}
                  {match.rank ? ` | Plex rank ${match.rank}` : ''}
                </span>
                <small>{match.summary || 'No plot summary available.'}</small>
                {match.match_reasons?.length > 0 && (
                  <small className="plex-match-reasons">{match.match_reasons.join(' | ')}</small>
                )}
              </div>
              <button type="button" className="btn btn-secondary" onClick={() => onApply(match)} disabled={Boolean(state.applying)}>
                {state.applying === match.guid ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />} Apply match
              </button>
            </article>
          )) : (
            <div className="cleanup-empty-match">Search Plex agents, then choose the exact metadata match.</div>
          )}

        </div>
      </section>
    </div>
  );
}
