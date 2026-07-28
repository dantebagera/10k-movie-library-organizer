import {
  AlertTriangle,
  CheckCircle2,
  Clapperboard,
  Film,
  Loader2,
  RefreshCcw,
  Save,
  Search,
  X
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { fetchJson } from '../api/client.js';
import {
  applyPlexMetadataMatch,
  applyTmdbMetadataMatch,
  requestPlexLibraryScan,
  searchPlexMetadata,
  searchTmdbMetadata
} from '../api/metadata.js';
import { formatVoteCount } from '../utils/moviePresentation.js';

function resultKey(provider, match) {
  return String(provider === 'plex' ? match?.guid || '' : match?.tmdb_id || '');
}

function resultTitle(match) {
  return match?.title || match?.name || 'Unknown title';
}

export default function MetadataCorrectionModal({
  item,
  onClose,
  onSaved,
  notify,
  resetLabel = 'Reset display title/year'
}) {
  const [context, setContext] = useState(null);
  const [title, setTitle] = useState('');
  const [year, setYear] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [searchProvider, setSearchProvider] = useState('tmdb');
  const [results, setResults] = useState([]);
  const [selectedKey, setSelectedKey] = useState('');
  const [plexRatingKey, setPlexRatingKey] = useState('');
  const [needsPlexScan, setNeedsPlexScan] = useState(false);
  const [scanRequested, setScanRequested] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError('');
      try {
        const data = await fetchJson(`/api/metadata/override?path=${encodeURIComponent(item.path)}`);
        if (cancelled) return;
        setContext(data);
        setTitle(data.effective?.title || data.provider?.title || item.title || item.suggested_title || '');
        setYear(String(data.effective?.year || data.provider?.year || item.year || item.suggested_year || ''));
        setPlexRatingKey(String(data.provider?.plex_rating_key || item.rating_key || ''));
      } catch (loadError) {
        if (!cancelled) setError(loadError.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [item.path]);

  const selectedMatch = useMemo(
    () => results.find((match) => resultKey(searchProvider, match) === selectedKey) || null,
    [results, searchProvider, selectedKey]
  );

  const provider = context?.provider || {};
  const hasOverride = Boolean(context?.override && Object.keys(context.override).length);
  const tmdbAvailable = Boolean(context?.providers?.tmdb?.available);
  const plexAvailable = Boolean(context?.providers?.plex?.available);
  const currentProviderLabel = context?.display_provider === 'plex'
    ? 'Plex'
    : context?.display_provider === 'tmdb'
      ? 'TMDB'
      : 'Accepted provider';

  async function saveDisplayOverride(event) {
    event.preventDefault();
    setBusy('save-display');
    setError('');
    try {
      const result = await fetchJson('/api/metadata/override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: item.path, title: title.trim(), year: year.trim() })
      });
      notify?.('Display title and year saved');
      onSaved?.(result);
      onClose();
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setBusy('');
    }
  }

  async function resetDisplayOverride() {
    setBusy('reset-display');
    setError('');
    try {
      const result = await fetchJson('/api/metadata/override', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: item.path })
      });
      notify?.('Display title and year reset to provider metadata');
      onSaved?.(result);
      onClose();
    } catch (resetError) {
      setError(resetError.message);
    } finally {
      setBusy('');
    }
  }

  async function search(providerName) {
    setBusy(`search-${providerName}`);
    setError('');
    setSearchProvider(providerName);
    setResults([]);
    setSelectedKey('');
    setNeedsPlexScan(false);
    try {
      const result = providerName === 'plex'
        ? await searchPlexMetadata({
          path: item.path,
          title,
          year,
          ratingKey: plexRatingKey
        })
        : await searchTmdbMetadata({
          title,
          year,
          fallback: item.filename || item.path
        });
      const nextResults = result.results || [];
      setResults(nextResults);
      if (providerName === 'plex') {
        setPlexRatingKey(String(result.rating_key || plexRatingKey || ''));
      }
      if (nextResults.length === 1) {
        setSelectedKey(resultKey(providerName, nextResults[0]));
      }
    } catch (searchError) {
      if (providerName === 'plex' && searchError.data?.code === 'plex_item_not_indexed') {
        setNeedsPlexScan(true);
      }
      setError(searchError.message);
    } finally {
      setBusy('');
    }
  }

  async function requestPlexScanAndRetry() {
    setBusy('plex-scan');
    setError('');
    try {
      await requestPlexLibraryScan();
      setScanRequested(true);
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      await search('plex');
    } catch (scanError) {
      setError(scanError.message);
      setBusy('');
    }
  }

  async function applySelectedMatch() {
    if (!selectedMatch) return;
    setBusy(`apply-${searchProvider}`);
    setError('');
    try {
      const result = searchProvider === 'plex'
        ? await applyPlexMetadataMatch({
          path: item.path,
          ratingKey: plexRatingKey,
          match: selectedMatch
        })
        : await applyTmdbMetadataMatch({
          path: item.path,
          match: selectedMatch
        });
      notify?.(`${searchProvider === 'plex' ? 'Plex' : 'TMDB'} metadata match applied`);
      onSaved?.(result);
      onClose();
    } catch (applyError) {
      setError(applyError.message);
    } finally {
      setBusy('');
    }
  }

  function submitDefaultSearch(event) {
    event.preventDefault();
    if (tmdbAvailable) search('tmdb');
    else if (plexAvailable) search('plex');
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="torrent-dialog metadata-correction-dialog" role="dialog" aria-modal="true" aria-label="Correct movie metadata" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">Correct movie identity</p>
            <h2>Correct metadata</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close metadata correction">
            <X size={18} />
          </button>
        </div>
        <p className="dialog-body-path">{item.filename || item.path}</p>
        {loading ? (
          <div className="library-status"><Loader2 size={16} className="spin" /><span>Loading accepted metadata...</span></div>
        ) : context ? (
          <>
            <div className="metadata-provider-comparison">
              <span>Current accepted match · {currentProviderLabel}</span>
              <strong>{provider.title || 'Unknown title'}{provider.year ? ` (${provider.year})` : ''}</strong>
              <small>Applying a provider result replaces the accepted movie identity and refreshes all metadata owned by that provider.</small>
            </div>

            <form className="metadata-correction-search" onSubmit={submitDefaultSearch}>
              <label className="dialog-field">
                <span>Search or display title</span>
                <input value={title} onChange={(event) => setTitle(event.target.value)} required />
              </label>
              <label className="dialog-field">
                <span>Year</span>
                <input value={year} onChange={(event) => setYear(event.target.value.replace(/\D/g, '').slice(0, 4))} inputMode="numeric" placeholder="Optional" />
              </label>
              <div className="metadata-provider-search-actions">
                <button type="button" className="btn btn-primary btn-violet" onClick={() => search('tmdb')} disabled={Boolean(busy) || !tmdbAvailable || !title.trim()}>
                  {busy === 'search-tmdb' ? <Loader2 size={15} className="spin" /> : <Search size={15} />}
                  {tmdbAvailable ? 'Search TMDB' : 'TMDB unavailable'}
                </button>
                <button type="button" className="btn btn-secondary" onClick={() => search('plex')} disabled={Boolean(busy) || !plexAvailable || !title.trim()}>
                  {busy === 'search-plex' ? <Loader2 size={15} className="spin" /> : <Clapperboard size={15} />}
                  {plexAvailable ? 'Search Plex' : 'Plex unavailable'}
                </button>
              </div>
            </form>

            {error && <p className="settings-inline-status settings-inline-error"><AlertTriangle size={15} /><span>{error}</span></p>}

            {needsPlexScan && (
              <div className="cleanup-match-recovery metadata-plex-recovery">
                <span>Plex must index this file before its matching agents can be searched.</span>
                <button type="button" className="btn btn-secondary" onClick={requestPlexScanAndRetry} disabled={Boolean(busy)}>
                  {busy === 'plex-scan' ? <Loader2 size={15} className="spin" /> : <RefreshCcw size={15} />}
                  {scanRequested ? 'Retry Plex lookup' : 'Request Plex scan'}
                </button>
              </div>
            )}

            <div className="metadata-match-results" aria-live="polite">
              {results.length ? (
                <>
                  <div className="metadata-match-results-heading">
                    <strong>Choose the exact {searchProvider === 'plex' ? 'Plex' : 'TMDB'} movie</strong>
                    <span>{results.length} result{results.length === 1 ? '' : 's'}</span>
                  </div>
                  {results.map((match) => {
                    const key = resultKey(searchProvider, match);
                    const selected = key === selectedKey;
                    return (
                      <label className={`metadata-match-result${selected ? ' metadata-match-result-selected' : ''}`} key={key}>
                        <input
                          type="radio"
                          name="metadata-provider-result"
                          checked={selected}
                          onChange={() => setSelectedKey(key)}
                        />
                        <span className="match-result-poster">
                          {match.poster_url ? <img src={match.poster_url} alt="" loading="lazy" /> : <Film size={18} />}
                        </span>
                        <span className="metadata-match-result-copy">
                          <strong>{resultTitle(match)}</strong>
                          <span>
                            {match.year || 'Unknown year'}
                            {searchProvider === 'tmdb' && match.tmdb_rating
                              ? ` · ${match.tmdb_rating} · ${formatVoteCount(match.tmdb_vote_count) || 'no votes'}`
                              : ''}
                            {searchProvider === 'plex' && match.exact_external_id ? ' · Exact external ID' : ''}
                            {searchProvider === 'plex' && match.rank ? ` · Plex rank ${match.rank}` : ''}
                          </span>
                          <small>{match.plot || match.summary || 'No plot summary available.'}</small>
                          {searchProvider === 'plex' && match.match_reasons?.length > 0 && (
                            <small className="plex-match-reasons">{match.match_reasons.join(' · ')}</small>
                          )}
                        </span>
                        <span className="metadata-match-result-id">
                          {searchProvider === 'plex' ? 'Plex' : `TMDB #${match.tmdb_id}`}
                        </span>
                      </label>
                    );
                  })}
                </>
              ) : (
                <div className="cleanup-empty-match metadata-match-empty">
                  Edit the title and year, then search TMDB or Plex for the exact movie.
                </div>
              )}
            </div>

            <div className="metadata-correction-footer">
              <div className="metadata-display-actions">
                {hasOverride && (
                  <button type="button" className="btn btn-secondary" onClick={resetDisplayOverride} disabled={Boolean(busy)}>
                    {busy === 'reset-display' ? <Loader2 size={15} className="spin" /> : <RefreshCcw size={15} />} {resetLabel}
                  </button>
                )}
                <button type="button" className="btn btn-secondary" onClick={saveDisplayOverride} disabled={Boolean(busy) || !title.trim()}>
                  {busy === 'save-display' ? <Loader2 size={15} className="spin" /> : <Save size={15} />}
                  Save display title/year only
                </button>
              </div>
              <div className="dialog-actions metadata-correction-actions">
                <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
                <button type="button" className="btn btn-primary" onClick={applySelectedMatch} disabled={Boolean(busy) || !selectedMatch}>
                  {busy.startsWith('apply-') ? <Loader2 size={15} className="spin" /> : <CheckCircle2 size={15} />}
                  Apply {searchProvider === 'plex' ? 'Plex' : 'TMDB'} match
                </button>
              </div>
            </div>
          </>
        ) : (
          error && <p className="settings-inline-status settings-inline-error"><AlertTriangle size={15} /><span>{error}</span></p>
        )}
      </section>
    </div>
  );
}
