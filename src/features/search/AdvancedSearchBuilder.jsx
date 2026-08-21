import { ChevronDown, ChevronUp, Plus, RotateCcw, Search, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { ADVANCED_SEARCH_LIMITS, criteriaForScope, criterionFor } from './advancedSearchRegistry.js';
import {
  createEmptyQuery, normalizeAdvancedQuery, queryGroup, withCriterion,
  withGroupJoin, withoutCriterionValue
} from './advancedSearchModel.js';

const fixedOptions = {
  viewing_status: [
    { id: 'watched', label: 'Watched' }, { id: 'unwatched', label: 'Unwatched' }, { id: 'watchlist', label: 'Watchlist' }
  ],
  resolution: [
    { id: 'upgrade', label: 'Upgrade candidate' }, { id: '4k', label: '4K' }, { id: '1080p', label: '1080p' },
    { id: '720p', label: '720p' }, { id: 'below-720p', label: 'Below 720p' }
  ],
  availability: [{ id: 'owned', label: 'Owned' }, { id: 'unowned', label: 'Not owned' }]
};

const numericDefaults = {
  year: { operator: 'between', from: 2000, to: new Date().getFullYear() },
  rating: { operator: 'at_least', value: 7 }
};

function valueLabel(type, value) {
  if (type === 'title') return value.text;
  if (type === 'person') return `${value.label} · ${value.role}`;
  if (type === 'year' || type === 'rating') {
    return value.operator === 'between' ? `${value.from}–${value.to}` : `${value.operator.replace('_', ' ')} ${value.value}`;
  }
  if (type === 'minimum_votes') return `${Number(value.value).toLocaleString()}+ votes`;
  if (type === 'runtime') return value.preset === 'custom' ? `${value.from}–${value.to} min` : value.preset;
  return value.label || value.id;
}

function IdentityPicker({ scope, type, searchIdentities, onPick }) {
  const [text, setText] = useState('');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [retryToken, setRetryToken] = useState(0);
  const sequence = useRef(0);
  function retryIdentitySearch() {
    setRetryToken((value) => value + 1);
  }
  useEffect(() => {
    const normalized = text.trim();
    sequence.current += 1;
    const request = sequence.current;
    if (normalized.length < 2) {
      setItems([]);
      setLoading(false);
      setError('');
      return undefined;
    }
    setLoading(true);
    setError('');
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      Promise.resolve(searchIdentities?.(type, normalized, scope, controller.signal))
        .then((results) => { if (request === sequence.current) setItems((results || []).slice(0, ADVANCED_SEARCH_LIMITS.suggestions)); })
        .catch((requestError) => {
          if (request !== sequence.current || requestError?.name === 'AbortError') return;
          setItems([]);
          setError(requestError?.message || 'Identity lookup failed');
        })
        .finally(() => { if (request === sequence.current) setLoading(false); });
    }, ADVANCED_SEARCH_LIMITS.debounceMs);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [retryToken, scope, searchIdentities, text, type]);
  return (
    <div className="advanced-identity-picker">
      <label><Search size={14} /><input value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') { setText(''); setItems([]); } }} placeholder={`Find ${type}…`} aria-label={`Find ${type}`} /></label>
      {loading && <span className="advanced-picker-status">Searching…</span>}
      {!loading && !error && text.trim().length >= 2 && !items.length && <span className="advanced-picker-status">No matches</span>}
      {error && <span className="advanced-picker-error" role="alert">Request failed <button type="button" onClick={retryIdentitySearch}>Retry</button></span>}
      {!!items.length && <div className="advanced-picker-results" role="listbox" aria-label={`${type} suggestions`}>
        {items.map((item) => <button type="button" role="option" key={item.id} onClick={() => { onPick(item); setText(''); setItems([]); }}>{item.label}</button>)}
      </div>}
    </div>
  );
}

function NumericEditor({ type, value, onChange }) {
  const between = value.operator === 'between';
  return (
    <div className="advanced-inline-editor">
      <select value={value.operator} onChange={(event) => {
        const operator = event.target.value;
        onChange(operator === 'between'
          ? { operator, from: Number(value.value ?? value.from ?? (type === 'year' ? 2000 : 0)), to: Number(value.to ?? value.value ?? (type === 'year' ? new Date().getFullYear() : 10)) }
          : { operator, value: Number(value.value ?? value.from ?? (type === 'year' ? 2000 : 0)) });
      }} aria-label={`${type} operator`}>
        <option value="exactly">Exactly</option><option value="at_least">At least</option><option value="at_most">At most</option><option value="between">Between</option>
      </select>
      {between ? <>
        <input type="number" value={value.from} min={type === 'year' ? 1888 : 0} max={type === 'year' ? 2100 : 10} step={type === 'year' ? 1 : 0.1} onChange={(event) => onChange({ ...value, from: Number(event.target.value) })} aria-label={`${type} from`} />
        <span>to</span>
        <input type="number" value={value.to} min={type === 'year' ? 1888 : 0} max={type === 'year' ? 2100 : 10} step={type === 'year' ? 1 : 0.1} onChange={(event) => onChange({ ...value, to: Number(event.target.value) })} aria-label={`${type} to`} />
      </> : <input type="number" value={value.value} min={type === 'year' ? 1888 : 0} max={type === 'year' ? 2100 : 10} step={type === 'year' ? 1 : 0.1} onChange={(event) => onChange({ ...value, value: Number(event.target.value) })} aria-label={type} />}
    </div>
  );
}

function RuntimeEditor({ value, onChange }) {
  const custom = value.preset === 'custom';
  return (
    <div className="advanced-inline-editor">
      <select value={value.preset} onChange={(event) => {
        const preset = event.target.value;
        onChange(preset === 'custom' ? { preset, from: value.from ?? 60, to: value.to ?? 150 } : { preset });
      }} aria-label="Runtime preset">
        <option value="short">Short (under 60 min)</option>
        <option value="feature">Feature (60–149 min)</option>
        <option value="long">Long (150+ min)</option>
        <option value="custom">Custom range</option>
      </select>
      {custom && <>
        <input type="number" value={value.from} min="0" max="1440" onChange={(event) => onChange({ ...value, from: Number(event.target.value) })} aria-label="Runtime from" />
        <span>to</span>
        <input type="number" value={value.to} min="0" max="1440" onChange={(event) => onChange({ ...value, to: Number(event.target.value) })} aria-label="Runtime to" />
      </>}
    </div>
  );
}

export default function AdvancedSearchBuilder({
  scope, query, onChange, onRun, onReset, options = {}, searchIdentities, loading = false, error = ''
}) {
  const normalized = useMemo(() => normalizeAdvancedQuery(query, scope), [query, scope]);
  const [addType, setAddType] = useState('');
  const [pendingText, setPendingText] = useState('');
  const [pendingIdentity, setPendingIdentity] = useState(null);
  const [personRole, setPersonRole] = useState('actor');
  const [expanded, setExpanded] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const addTriggerRef = useRef(null);
  const groups = normalized.groups;
  const used = new Set(groups.map((group) => group.type));
  const hasTitle = used.has('title');
  const hasTitleUnsupported = used.has('keyword') || used.has('runtime');
  const available = criteriaForScope(scope).filter((definition) => {
    if (definition.type === 'sort') return false;
    if (used.has(definition.type) && !definition.repeatable) return false;
    if (scope === 'discover' && ((hasTitle && ['keyword', 'runtime'].includes(definition.type)) || (definition.type === 'title' && hasTitleUnsupported))) return false;
    return true;
  });
  const selectedDefinition = criterionFor(scope, addType);
  const selectedOptions = fixedOptions[addType] || options[addType] || [];
  const requiresOptions = ['genre', 'language', 'country', 'movie_list', 'library_source', 'resolution', 'viewing_status', 'availability'].includes(addType);

  function updateGroup(type, values) {
    try {
      onChange(normalizeAdvancedQuery({ ...normalized, groups: groups.map((group) => group.type === type ? { ...group, values } : group) }, scope));
    } catch {
      // Keep the last valid query while the user corrects an out-of-range edit.
    }
  }

  function addValue(value) {
    try {
      onChange(withCriterion(normalized, addType, value));
      setAddType('');
      setPendingText('');
      setPendingIdentity(null);
      window.setTimeout(() => addTriggerRef.current?.focus(), 0);
    } catch {
      // Validation feedback remains adjacent to the unfinished add controls.
    }
  }

  function addPending() {
    if (addType === 'title' && pendingText.trim()) addValue({ text: pendingText.trim() });
    else if (['person', 'keyword'].includes(addType) && pendingIdentity) addValue(addType === 'person' ? { ...pendingIdentity, role: personRole } : pendingIdentity);
    else if (selectedOptions.length) addValue(selectedOptions[0]);
    else if (addType === 'year' || addType === 'rating') addValue(numericDefaults[addType]);
    else if (addType === 'minimum_votes') addValue({ value: 500 });
    else if (addType === 'runtime') addValue({ preset: 'feature' });
  }

  function removeValue(type, index = 0) {
    onChange(withoutCriterionValue(normalized, type, index));
    window.setTimeout(() => addTriggerRef.current?.focus(), 0);
  }

  const collapsedCount = Math.max(0, groups.length - 6);
  const shownGroups = expanded ? groups : groups.slice(0, 6);
  return (
    <section className="advanced-search-builder" aria-label={`${scope} advanced search`}>
      <div className="advanced-strip-main">
        <button
          ref={addTriggerRef}
          type="button"
          className="advanced-add-trigger"
          onClick={() => setAddOpen((value) => !value)}
          aria-label="Add advanced search criterion"
          aria-expanded={addOpen}
        >
          <Plus size={17} />
        </button>
        {!groups.length && <span className="advanced-mode-warning">This field is not a normal text search</span>}
        <div className="advanced-builder-canvas" data-expanded={expanded || undefined}>
          {shownGroups.map((group, groupIndex) => {
          const definition = criterionFor(scope, group.type);
          const editableNumeric = ['year', 'rating'].includes(group.type);
          const singletonValue = group.values[0];
          const joinOptions = definition.joinOptions || ['and', 'or'];
          const nextJoin = joinOptions[(joinOptions.indexOf(group.join) + 1) % joinOptions.length];
          return <div className="advanced-criterion-cluster" key={group.type}>
            {groupIndex > 0 && <span className="advanced-type-join">AND</span>}
            <div className="advanced-criterion-block">
            <div className="advanced-block-header">
              <strong>{definition.label}</strong>
            </div>
            {editableNumeric ? <div className="advanced-single-editor"><NumericEditor type={group.type} value={singletonValue} onChange={(value) => updateGroup(group.type, [value])} /><button type="button" onClick={() => removeValue(group.type)} aria-label={`Remove ${definition.label.toLowerCase()}`}><X size={13} /></button></div>
              : group.type === 'title' ? <div className="advanced-single-editor"><input value={singletonValue.text} maxLength={ADVANCED_SEARCH_LIMITS.titleCharacters} onChange={(event) => updateGroup(group.type, [{ text: event.target.value }])} aria-label="Edit title" /><button type="button" onClick={() => removeValue(group.type)} aria-label="Remove title"><X size={13} /></button></div>
                : group.type === 'minimum_votes' ? <div className="advanced-single-editor"><input type="number" value={singletonValue.value} min="0" max="10000000" step="100" onChange={(event) => updateGroup(group.type, [{ value: Number(event.target.value) }])} aria-label="Minimum votes" /><button type="button" onClick={() => removeValue(group.type)} aria-label="Remove minimum votes"><X size={13} /></button></div>
                  : group.type === 'runtime' ? <div className="advanced-single-editor"><RuntimeEditor value={singletonValue} onChange={(value) => updateGroup(group.type, [value])} /><button type="button" onClick={() => removeValue(group.type)} aria-label="Remove runtime"><X size={13} /></button></div>
                    : <div className="advanced-value-list">
              {group.values.map((value, index) => <span className="advanced-value-unit" key={`${group.type}-${valueLabel(group.type, value)}-${index}`}>
                {index > 0 && (joinOptions.length > 1
                  ? <button
                    type="button"
                    className="advanced-join-toggle"
                    onClick={() => onChange(withGroupJoin(normalized, group.type, nextJoin))}
                    aria-label={`Combine ${definition.label} values with ${group.join.toUpperCase()}; click to use ${nextJoin.toUpperCase()}`}
                  >{group.join.toUpperCase()}</button>
                  : <span className="advanced-join-fixed">{group.join.toUpperCase()}</span>)}
                <span className="advanced-value-chip">
                  {group.type === 'person' ? <><span>{value.label}</span><select value={value.role} onChange={(event) => updateGroup(group.type, group.values.map((item, valueIndex) => valueIndex === index ? { ...item, role: event.target.value } : item))} aria-label={`Role for ${value.label}`}><option value="actor">Actor</option><option value="director">Director</option><option value="writer">Writer</option></select></> : valueLabel(group.type, value)}
                  <button type="button" onClick={() => removeValue(group.type, index)} aria-label={`Remove ${definition.label.toLowerCase()} ${valueLabel(group.type, value)}`}><X size={13} /></button>
                </span>
              </span>)}
            </div>}
            </div>
          </div>;
        })}
        </div>
        {collapsedCount > 0 && <button type="button" className="advanced-overflow-toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded} aria-label={expanded ? 'Show fewer criteria' : `+${collapsedCount} more criteria`}>
          {expanded ? <><ChevronUp size={14} /> Less</> : <><ChevronDown size={14} /> +{collapsedCount} more</>}
        </button>}
        <button type="button" className="advanced-reset-trigger" onClick={() => (onReset ? onReset() : onChange(createEmptyQuery(scope)))} aria-label="Reset advanced search" title="Reset advanced search"><RotateCcw size={14} /></button>
      </div>
      {addOpen && <div className="advanced-add-popover">
        <div className="advanced-popover-heading">
          <div><strong>Add criterion</strong><span>Different types use AND. Repeated values use the clickable AND/OR connector.</span></div>
          <div className="advanced-popover-actions">
            <button type="button" className="btn btn-secondary" onClick={() => (onReset ? onReset() : onChange(createEmptyQuery(scope)))}><RotateCcw size={14} /> Reset</button>
            <button type="button" className="advanced-popover-close" onClick={() => setAddOpen(false)} aria-label="Close criterion picker"><X size={15} /></button>
          </div>
        </div>
        <div className="advanced-add-row">
          <select value={addType} onChange={(event) => { setAddType(event.target.value); setPendingIdentity(null); setPendingText(''); }} aria-label="Criterion to add">
            <option value="">Choose criterion…</option>
            {available.map((definition) => <option key={definition.type} value={definition.type}>{definition.label}</option>)}
          </select>
          {addType === 'title' && <input value={pendingText} maxLength={ADVANCED_SEARCH_LIMITS.titleCharacters} onChange={(event) => setPendingText(event.target.value)} placeholder="Movie title" aria-label="Title value" />}
          {['person', 'keyword'].includes(addType) && <>
            {addType === 'person' && <select value={personRole} onChange={(event) => setPersonRole(event.target.value)} aria-label="Person role"><option value="actor">Actor</option><option value="director">Director</option><option value="writer">Writer</option></select>}
            <IdentityPicker scope={scope} type={addType} searchIdentities={searchIdentities} onPick={setPendingIdentity} />
            {pendingIdentity && <span className="advanced-pending-identity">{pendingIdentity.label}</span>}
          </>}
          {!!addType && !['title', 'person', 'keyword', 'year', 'rating', 'minimum_votes', 'runtime'].includes(addType) && <select value={pendingIdentity?.id || selectedOptions[0]?.id || ''} onChange={(event) => setPendingIdentity(selectedOptions.find((item) => item.id === event.target.value) || null)} aria-label={`${selectedDefinition?.label} value`}>
            {selectedOptions.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>}
          <button type="button" className="btn btn-secondary advanced-confirm-add" disabled={!addType || (addType === 'title' && !pendingText.trim()) || (['person', 'keyword'].includes(addType) && !pendingIdentity) || (requiresOptions && !selectedOptions.length)} onClick={() => {
            if (pendingIdentity && !['person', 'keyword'].includes(addType)) addValue(pendingIdentity); else addPending();
          }}><Plus size={14} /> Add criterion</button>
        </div>
        <div className="advanced-builder-footer">
          <label>Sort <select value={normalized.sort.key} onChange={(event) => onChange(normalizeAdvancedQuery({ ...normalized, sort: { key: event.target.value, direction: event.target.value === 'title' || event.target.value === 'title.asc' || event.target.value === 'year-asc' ? 'asc' : 'desc' } }, scope))}>
            {(scope === 'library' ? [
              ['added', 'Newly added'], ['title', 'Title'], ['rating', 'Rating'], ['year-desc', 'Year newest'], ['year-asc', 'Year oldest'], ['quality', 'Quality']
            ] : [
              ['auto', 'Default order'], ['popularity.desc', 'Popularity'], ['vote_average.desc', 'Rating'], ['vote_count.desc', 'Most voted'], ['primary_release_date.desc', 'Release date'], ['title.asc', 'Title A–Z']
            ]).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>
          {scope === 'discover' && <label>Feed <select value={normalized.feed} onChange={(event) => onChange(normalizeAdvancedQuery({ ...normalized, feed: event.target.value }, scope))}>
            {[['trending_week', 'Trending Week'], ['catalog', 'TMDB Catalog'], ['trending_today', 'Trending Today'], ['now_playing', 'Now Playing'], ['upcoming', 'Upcoming'], ['popular', 'Popular'], ['top_rated', 'Top Rated'], ['best_all_time', 'Best All Time']].map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select></label>}
        </div>
        {scope === 'discover' && hasTitle && <p className="advanced-capability-note">Title results use a bounded TMDB scan. Keyword and Runtime are unavailable with Title.</p>}
      </div>}
      {error && <div className="advanced-builder-error" role="alert">{error} <button type="button" onClick={onRun}>Retry</button></div>}
    </section>
  );
}
