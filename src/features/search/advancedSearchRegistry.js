export const ADVANCED_SEARCH_LIMITS = Object.freeze({
  totalValues: 24,
  valuesPerGroup: 10,
  titleCharacters: 100,
  pageSize: 100,
  suggestions: 20,
  debounceMs: 300
});

const shared = [
  { type: 'title', label: 'Title', editor: 'title', repeatable: false },
  { type: 'genre', label: 'Genre', editor: 'controlled', repeatable: true },
  { type: 'person', label: 'Person', editor: 'person', repeatable: true, roles: ['actor', 'director', 'writer'] },
  { type: 'keyword', label: 'Keyword', editor: 'keyword', repeatable: true },
  { type: 'year', label: 'Release year', editor: 'number-range', repeatable: false },
  { type: 'rating', label: 'Rating', editor: 'rating-range', repeatable: false },
  { type: 'language', label: 'Language', editor: 'controlled', repeatable: false },
  { type: 'country', label: 'Country', editor: 'controlled', repeatable: false },
  { type: 'runtime', label: 'Runtime', editor: 'runtime', repeatable: false },
  { type: 'viewing_status', label: 'Viewing status', editor: 'viewing-status', repeatable: false },
  { type: 'movie_list', label: 'Movie list', editor: 'movie-list', repeatable: true },
  { type: 'sort', label: 'Sort', editor: 'sort', repeatable: false }
];

const libraryOnly = [
  { type: 'resolution', label: 'Resolution', editor: 'resolution', repeatable: true, joinOptions: ['or'] },
  { type: 'library_source', label: 'Library source', editor: 'library-source', repeatable: true, joinOptions: ['or'] }
];

const discoverOnly = [
  { type: 'minimum_votes', label: 'Minimum votes', editor: 'minimum-votes', repeatable: false },
  { type: 'availability', label: 'Availability', editor: 'availability', repeatable: false }
];

export const advancedSearchRegistry = Object.freeze({
  library: Object.freeze([...shared, ...libraryOnly].map(Object.freeze)),
  discover: Object.freeze([...shared, ...discoverOnly].map(Object.freeze))
});

export function criteriaForScope(scope) {
  return advancedSearchRegistry[scope] || [];
}

export function criterionFor(scope, type) {
  return criteriaForScope(scope).find((criterion) => criterion.type === type) || null;
}

export function criterionOrder(scope, type) {
  const index = criteriaForScope(scope).findIndex((criterion) => criterion.type === type);
  return index < 0 ? Number.MAX_SAFE_INTEGER : index;
}
