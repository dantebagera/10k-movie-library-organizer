import {
  ADVANCED_SEARCH_LIMITS,
  criterionFor,
  criterionOrder
} from './advancedSearchRegistry.js';

const scopes = new Set(['library', 'discover']);
const modes = new Set(['simple', 'advanced']);
const roles = new Set(['actor', 'director', 'writer']);
const numericOperators = new Set(['exactly', 'at_least', 'at_most', 'between']);
const runtimePresets = new Set(['short', 'feature', 'long', 'custom']);
const feeds = new Set(['trending_week', 'catalog', 'trending_today', 'now_playing', 'upcoming', 'popular', 'top_rated', 'best_all_time']);
const sortKeys = Object.freeze({
  library: new Set(['added', 'title', 'rating', 'year-desc', 'year-asc', 'quality']),
  discover: new Set(['auto', 'popularity.desc', 'vote_average.desc', 'vote_count.desc', 'primary_release_date.desc', 'title.asc'])
});

function fail(message) {
  throw new Error(message);
}

function text(value, maximum = 160) {
  const normalized = String(value ?? '').trim();
  if (normalized.length > maximum) fail(`Value exceeds ${maximum} characters`);
  return normalized;
}

function finiteNumber(value, label) {
  const number = Number(value);
  if (!Number.isFinite(number)) fail(`${label} must be a number`);
  return number;
}

function integer(value, label, minimum, maximum) {
  const number = finiteNumber(value, label);
  if (!Number.isInteger(number) || number < minimum || number > maximum) {
    fail(`${label} must be between ${minimum} and ${maximum}`);
  }
  return number;
}

function identityValue(value, type) {
  const id = text(value?.id, 120);
  const label = text(value?.label, 160);
  if (!id || !label) fail(`${type} requires a controlled identity`);
  const normalized = { id, label };
  if (type === 'person') {
    const role = text(value?.role, 20).toLowerCase();
    if (!roles.has(role)) fail('Person role must be actor, director, or writer');
    normalized.role = role;
  }
  return normalized;
}

function numericValue(value, type) {
  const operator = text(value?.operator, 20).toLowerCase();
  if (!numericOperators.has(operator)) fail(`Unknown ${type} operator`);
  const bounds = type === 'year' ? [1888, 2100] : [0, 10];
  const read = type === 'year'
    ? (candidate, label) => integer(candidate, label, ...bounds)
    : (candidate, label) => {
        const number = finiteNumber(candidate, label);
        if (number < bounds[0] || number > bounds[1]) fail(`${label} must be between 0 and 10`);
        return Number(number.toFixed(1));
      };
  if (operator === 'between') {
    const from = read(value?.from, `${type} from`);
    const to = read(value?.to, `${type} to`);
    if (from > to) fail(`${type} range cannot be reversed`);
    return { operator, from, to };
  }
  return { operator, value: read(value?.value, type) };
}

function runtimeValue(value) {
  const preset = text(value?.preset, 20).toLowerCase();
  if (!runtimePresets.has(preset)) fail('Unknown runtime preset');
  if (preset !== 'custom') return { preset };
  const from = integer(value?.from, 'Runtime from', 0, 1440);
  const to = integer(value?.to, 'Runtime to', 0, 1440);
  if (from > to) fail('Runtime range cannot be reversed');
  return { preset, from, to };
}

function normalizeValue(type, value) {
  if (type === 'title') {
    const title = text(value?.text, ADVANCED_SEARCH_LIMITS.titleCharacters);
    if (!title) fail('Title cannot be empty');
    return { text: title };
  }
  if (['genre', 'person', 'keyword', 'language', 'country', 'movie_list'].includes(type)) {
    return identityValue(value, type);
  }
  if (['year', 'rating'].includes(type)) return numericValue(value, type);
  if (type === 'minimum_votes') return { value: integer(value?.value, 'Minimum votes', 0, 10000000) };
  if (type === 'runtime') return runtimeValue(value);
  if (['viewing_status', 'resolution', 'library_source', 'availability'].includes(type)) {
    const id = text(value?.id, 80);
    const label = text(value?.label, 120);
    if (!id || !label) fail(`${type} requires a controlled value`);
    return { id, label };
  }
  fail(`Unsupported criterion type: ${type}`);
}

function valueKey(type, value) {
  if (type === 'title') return value.text.toLocaleLowerCase();
  if (type === 'person') return `${value.id}|${value.role}`;
  if (value.id != null) return String(value.id);
  return JSON.stringify(value);
}

function normalizeGroup(scope, group) {
  const type = text(group?.type, 40).toLowerCase();
  const definition = criterionFor(scope, type);
  if (!definition || type === 'sort') fail(`Criterion ${type || '(missing)'} is not supported in ${scope}`);
  const incoming = Array.isArray(group?.values) ? group.values : [];
  if (!incoming.length) fail(`${type} requires at least one value`);
  if (incoming.length > ADVANCED_SEARCH_LIMITS.valuesPerGroup) fail(`${type} exceeds the per-group limit`);
  const values = [];
  const seen = new Set();
  for (const candidate of incoming) {
    const value = normalizeValue(type, candidate);
    const key = valueKey(type, value);
    if (seen.has(key)) continue;
    seen.add(key);
    values.push(value);
  }
  if (!definition.repeatable && values.length !== 1) fail(`${type} accepts one value`);
  values.sort((left, right) => valueKey(type, left).localeCompare(valueKey(type, right)));
  const allowedJoins = definition.joinOptions || ['and', 'or'];
  const requestedJoin = text(group?.join || 'or', 10).toLowerCase();
  const join = allowedJoins.includes(requestedJoin) ? requestedJoin : allowedJoins[0];
  return definition.repeatable ? { type, join, values } : { type, values };
}

export function createEmptyQuery(scope, mode = 'advanced') {
  if (!scopes.has(scope)) fail('Search scope must be library or discover');
  return {
    version: 1,
    scope,
    mode,
    groups: [],
    sort: scope === 'library' ? { key: 'added', direction: 'desc' } : { key: 'auto', direction: 'desc' },
    ...(scope === 'discover' ? { feed: 'trending_week' } : {})
  };
}

export function normalizeAdvancedQuery(input, expectedScope) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) fail('Search query must be an object');
  if (Number(input.version) !== 1) fail('Search query version must be 1');
  const scope = text(input.scope, 20).toLowerCase();
  if (!scopes.has(scope) || (expectedScope && scope !== expectedScope)) fail('Search query scope is invalid');
  const mode = text(input.mode || 'advanced', 20).toLowerCase();
  if (!modes.has(mode)) fail('Search query mode is invalid');
  if (!Array.isArray(input.groups)) fail('Search query groups must be an array');
  const groups = [];
  const seenTypes = new Set();
  for (const candidate of input.groups) {
    const group = normalizeGroup(scope, candidate);
    if (seenTypes.has(group.type)) fail(`Duplicate ${group.type} group`);
    seenTypes.add(group.type);
    groups.push(group);
  }
  const valueCount = groups.reduce((count, group) => count + group.values.length, 0);
  if (valueCount > ADVANCED_SEARCH_LIMITS.totalValues) fail('Search query exceeds the total value limit');
  groups.sort((left, right) => criterionOrder(scope, left.type) - criterionOrder(scope, right.type));

  const sort = input.sort && typeof input.sort === 'object' ? input.sort : {};
  const defaultSort = scope === 'library' ? 'added' : 'auto';
  const sortKey = text(sort.key || defaultSort, 40);
  if (!sortKeys[scope].has(sortKey)) fail(`Sort ${sortKey} is not supported in ${scope}`);
  const direction = text(sort.direction || 'desc', 10).toLowerCase();
  if (!['asc', 'desc'].includes(direction)) fail('Sort direction must be asc or desc');
  const normalized = { version: 1, scope, mode, groups, sort: { key: sortKey, direction } };
  if (scope === 'discover') {
    const feed = text(input.feed || 'trending_week', 40);
    if (!feeds.has(feed)) fail('Discover feed is invalid');
    normalized.feed = feed;
  }
  return normalized;
}

export function querySignature(query) {
  const normalized = normalizeAdvancedQuery(query, query?.scope);
  return JSON.stringify({
    version: normalized.version,
    scope: normalized.scope,
    groups: normalized.groups.map((group) => ({
      ...group,
      values: group.values.map(({ label: _label, ...value }) => value)
    })),
    sort: normalized.sort,
    ...(normalized.scope === 'discover' ? { feed: normalized.feed } : {})
  });
}

function compactGroups(groups) {
  return groups.filter((group) => group?.values?.length);
}

function singleIdentity(type, id, label = id) {
  const value = text(id);
  return value ? { type, values: [{ id: value, label: text(label) || value }] } : null;
}

function rangeGroup(type, from, to) {
  const cleanFrom = text(from);
  const cleanTo = text(to);
  if (cleanFrom && cleanTo) return { type, values: [{ operator: 'between', from: Number(cleanFrom), to: Number(cleanTo) }] };
  if (cleanFrom) return { type, values: [{ operator: 'at_least', value: Number(cleanFrom) }] };
  if (cleanTo) return { type, values: [{ operator: 'at_most', value: Number(cleanTo) }] };
  return null;
}

export function compileLibrarySimpleQuery(state = {}) {
  const groups = compactGroups([
    text(state.query) ? { type: 'title', values: [{ text: state.query }] } : null,
    singleIdentity('resolution', state.resolution !== 'all' ? state.resolution : '', state.resolution),
    singleIdentity('library_source', state.source !== 'all' ? state.source : '', state.source),
    singleIdentity('genre', state.genre !== 'all' ? state.genre : '', state.genre),
    singleIdentity('language', state.language !== 'all' ? state.language : '', state.language),
    singleIdentity('country', state.country !== 'all' ? state.country : '', state.country),
    rangeGroup('year', state.yearFrom, state.yearTo),
    state.minRating && state.minRating !== 'all'
      ? { type: 'rating', values: [{ operator: 'at_least', value: Number(state.minRating) }] }
      : null,
    singleIdentity('viewing_status', state.viewingState !== 'all' ? state.viewingState : '', state.viewingState),
    state.person?.id || state.person?.name
      ? { type: 'person', values: [{ id: state.person.id || state.person.name, label: state.person.name, role: state.person.role || 'actor' }] }
      : null,
    state.keyword?.tmdb_id || state.keyword?.name
      ? { type: 'keyword', values: [{ id: state.keyword.tmdb_id || state.keyword.name, label: state.keyword.name }] }
      : null,
    state.movieList?.id ? { type: 'movie_list', values: [{ id: state.movieList.id, label: state.movieList.name || state.movieList.id }] } : null
  ]);
  return normalizeAdvancedQuery({
    ...createEmptyQuery('library', 'simple'),
    groups,
    sort: { key: state.sort || 'added', direction: state.sort === 'year-asc' || state.sort === 'title' ? 'asc' : 'desc' }
  }, 'library');
}

export function compileDiscoverSimpleQuery(state = {}) {
  const groups = compactGroups([
    text(state.query) ? { type: 'title', values: [{ text: state.query }] } : null,
    singleIdentity('genre', state.genre, state.genreLabel || state.genre),
    singleIdentity('language', state.language, state.languageLabel || state.language),
    singleIdentity('country', state.country, state.countryLabel || state.country),
    state.minimumVotes && String(state.minimumVotes) !== '0'
      ? { type: 'minimum_votes', values: [{ value: Number(state.minimumVotes) }] }
      : null,
    rangeGroup('year', state.yearFrom, state.yearTo),
    state.minRating && String(state.minRating) !== '0'
      ? { type: 'rating', values: [{ operator: 'at_least', value: Number(state.minRating) }] }
      : null,
    singleIdentity('availability', state.availability !== 'all' ? state.availability : '', state.availability)
  ]);
  return normalizeAdvancedQuery({
    ...createEmptyQuery('discover', 'simple'),
    groups,
    feed: state.feed || 'trending_week',
    sort: { key: state.sort || 'auto', direction: state.sort === 'title.asc' ? 'asc' : 'desc' }
  }, 'discover');
}

export function queryGroup(query, type) {
  return normalizeAdvancedQuery(query, query?.scope).groups.find((group) => group.type === type) || null;
}

export function withCriterion(query, type, value, join = 'or') {
  const normalized = normalizeAdvancedQuery(query, query?.scope);
  const definition = criterionFor(normalized.scope, type);
  if (!definition || type === 'sort') fail(`Criterion ${type} is not supported`);
  const groups = normalized.groups.filter((group) => group.type !== type);
  const previous = normalized.groups.find((group) => group.type === type);
  groups.push({
    type,
    join: previous?.join || join,
    values: definition.repeatable ? [...(previous?.values || []), value] : [value]
  });
  return normalizeAdvancedQuery({ ...normalized, groups }, normalized.scope);
}

export function withoutCriterionValue(query, type, index) {
  const normalized = normalizeAdvancedQuery(query, query?.scope);
  const groups = normalized.groups.flatMap((group) => {
    if (group.type !== type) return [group];
    const values = group.values.filter((_value, valueIndex) => valueIndex !== index);
    return values.length ? [{ ...group, values }] : [];
  });
  return normalizeAdvancedQuery({ ...normalized, groups }, normalized.scope);
}

export function withGroupJoin(query, type, join) {
  const normalized = normalizeAdvancedQuery(query, query?.scope);
  return normalizeAdvancedQuery({
    ...normalized,
    groups: normalized.groups.map((group) => group.type === type ? { ...group, join } : group)
  }, normalized.scope);
}
