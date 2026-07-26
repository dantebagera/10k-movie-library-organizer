import { AlertTriangle, Download, Loader2, X } from 'lucide-react';
import { submitSourceReview } from '../api/sourceReview.js';
import { formatCount } from '../utils/appUtils.js';
import SelectionCheckbox from './SelectionCheckbox.jsx';

function rowWithQuality(row, quality) {
  const variantsByQuality = row.variants_by_quality || {};
  if (!Object.prototype.hasOwnProperty.call(variantsByQuality, quality)) {
    return { ...row, quality };
  }
  const variant = variantsByQuality[quality] || null;
  const wasUnavailable = row.status === 'blocked' && !row.variant;
  return {
    ...row,
    quality,
    variant,
    status: variant ? 'ready' : 'blocked',
    selected: variant ? (wasUnavailable ? true : row.selected !== false) : false,
    reason: variant ? '' : `No trusted ${quality} source found`
  };
}

export default function SourceReviewDialog({ state, setState, onClose, notify, onReviewComplete = null }) {
  const readyRows = (state.rows || []).filter((row) => row.status === 'ready');
  const selectedCount = readyRows.filter((row) => row.selected !== false).length;
  const unavailableCount = (state.rows || []).filter((row) => row.status === 'blocked').length;
  const upgradeCount = readyRows.filter((row) => row.upgrade === true && row.selected !== false).length;

  function updateRows(updater) {
    setState((current) => ({ ...current, rows: updater(current.rows || []) }));
  }

  function setAllRows(selected) {
    updateRows((rows) => rows.map((row) => (row.status === 'ready' ? { ...row, selected } : row)));
  }

  function setSelectedQuality(quality) {
    updateRows((rows) => rows.map((row) => (
      row.status === 'ready' && row.selected !== false ? rowWithQuality(row, quality) : row
    )));
  }

  async function submitSelected() {
    setState((current) => ({ ...current, submitting: true, error: '' }));
    try {
      if (onReviewComplete) {
        await onReviewComplete(state.rows || []);
        notify?.(`Reviewed ${formatCount(selectedCount)} selected source${selectedCount === 1 ? '' : 's'}`);
        onClose();
        return;
      }
      const data = await submitSourceReview(state.rows || []);
      notify?.(`Submitted ${formatCount(data.submitted_count || 0)} movie${Number(data.submitted_count || 0) === 1 ? '' : 's'} to qBittorrent`);
      onClose();
    } catch (submitError) {
      setState((current) => ({ ...current, submitting: false, error: submitError.message }));
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="torrent-dialog source-review-dialog" role="dialog" aria-modal="true" aria-label={state.title || 'Source review'} onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">Trusted source review</p>
            <h2>{state.title || 'Find sources'}</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close source review">
            <X size={18} />
          </button>
        </div>

        {state.loading ? (
          <div className="source-loading-panel"><Loader2 size={20} className="spin" /><strong>Finding trusted sources...</strong><span>This may take some time depending on selected indexers.</span></div>
        ) : (
          <>
            <div className="bulk-selection-bar source-review-actions">
              <span>{formatCount(selectedCount)} selected for download</span>
              <button type="button" className="mini-action" onClick={() => setAllRows(true)}>Select all</button>
              <button type="button" className="mini-action" onClick={() => setAllRows(false)}>Select none</button>
              <button type="button" className="mini-action" onClick={() => setSelectedQuality('1080p')}>Set selected to 1080p</button>
              <button type="button" className="mini-action" onClick={() => setSelectedQuality('4K')}>Set selected to 4K</button>
            </div>
            {state.error ? <div className="library-status library-status-error"><AlertTriangle size={16} /> {state.error}</div> : null}
            <div className="source-review-table">
              <div className="source-review-head">
                <span>Pick</span>
                <span>Movie</span>
                <span>Release</span>
                <span>Indexer</span>
                <span>Quality</span>
                <span>Status</span>
              </div>
              {(state.rows || []).map((row, index) => (
                <div className="source-review-row" key={`${row.tmdb_id || row.title}-${index}`}>
                  <SelectionCheckbox
                    checked={row.status === 'ready' && row.selected !== false}
                    onChange={(checked) => updateRows((rows) => rows.map((item, itemIndex) => itemIndex === index ? { ...item, selected: checked } : item))}
                    label={`Select ${row.title}`}
                  />
                  <span><strong>{row.title}</strong><small>{row.year || 'Unknown year'}</small></span>
                  <span title={row.variant?.title || row.reason || ''}>{row.variant?.title || row.reason || 'No release'}</span>
                  <span>{row.variant?.indexer || '-'}</span>
                  <select
                    value={row.quality || state.defaults?.quality || '1080p'}
                    disabled={!Object.values(row.variants_by_quality || {}).some(Boolean)}
                    onChange={(event) => updateRows((rows) => rows.map((item, itemIndex) => (
                      itemIndex === index ? rowWithQuality(item, event.target.value) : item
                    )))}
                  >
                    <option value="1080p">1080p</option>
                    <option value="4K">4K</option>
                  </select>
                  <span>{row.status === 'ready' ? [row.upgrade ? 'Upgrade' : '', row.variant?.size_human, row.variant?.seeders ? `${row.variant.seeders} seeders` : ''].filter(Boolean).join(' - ') || 'Ready' : row.reason || row.status}</span>
                </div>
              ))}
            </div>
            {unavailableCount || upgradeCount ? (
              <p className="settings-empty-note">
                {unavailableCount ? `${formatCount(unavailableCount)} movie${unavailableCount === 1 ? '' : 's'} had no trusted source.` : ''}
                {unavailableCount && upgradeCount ? ' ' : ''}
                {upgradeCount ? `${formatCount(upgradeCount)} owned movie${upgradeCount === 1 ? '' : 's'} will be downloaded as ${upgradeCount === 1 ? 'an upgrade copy' : 'upgrade copies'}. Existing library files will be kept for comparison in Maintenance.` : ''}
              </p>
            ) : null}
          </>
        )}

        <div className="dialog-actions">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={submitSelected} disabled={state.loading || state.submitting || !selectedCount}>
            {state.submitting ? <Loader2 size={15} className="spin" /> : <Download size={15} />} {onReviewComplete ? 'Apply selected sources' : 'Submit selected to qBittorrent'}
          </button>
        </div>
      </section>
    </div>
  );
}
