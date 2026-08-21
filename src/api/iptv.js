import { fetchJson } from './client.js';

export function queryString(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== undefined && value !== null && value !== false && ['string', 'number', 'boolean'].includes(typeof value)) {
      query.set(key, String(value));
    }
  });
  return query.toString();
}

function providerPath(providerId, suffix = '') {
  if (!providerId) throw new Error('An IPTV provider must be selected');
  return `/api/iptv/providers/${encodeURIComponent(providerId)}${suffix}`;
}

function withQuery(path, params = {}) {
  const query = queryString(params);
  return query ? `${path}?${query}` : path;
}

export const iptvApi = {
  metadataSettings: () => fetchJson('/api/iptv/metadata/settings'),
  saveMetadataSettings: (payload) => fetchJson('/api/iptv/metadata/settings', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  testMetadata: () => fetchJson('/api/iptv/metadata/test', { method: 'POST' }),
  providers: () => fetchJson('/api/iptv/providers'),
  provider: (providerId) => fetchJson(providerPath(providerId)),
  createProvider: (payload) => fetchJson('/api/iptv/providers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  updateProvider: (providerId, payload) => fetchJson(providerPath(providerId), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  removeProvider: (providerId, confirmName) => fetchJson(providerPath(providerId), {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_name: confirmName })
  }),
  selectProvider: (providerId) => fetchJson('/api/iptv/providers/selection', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider_id: providerId })
  }),
  test: (providerId) => fetchJson(providerPath(providerId, '/test'), { method: 'POST' }),
  status: (providerId) => fetchJson(providerPath(providerId, '/status')),
  sync: (providerId) => fetchJson(providerPath(providerId, '/sync'), { method: 'POST' }),
  categories: (providerId, kind) => fetchJson(`${providerPath(providerId, '/categories')}?${queryString({ kind })}`),
  items: (providerId, params) => fetchJson(`${providerPath(providerId, '/items')}?${queryString(params)}`),
  movies: (providerId, params, options) => fetchJson(`${providerPath(providerId, '/movies')}?${queryString(params)}`, options),
  movieFacets: (providerId, params = {}) => fetchJson(withQuery(providerPath(providerId, '/movies/facets'), params)),
  movieProjectionStatus: (providerId) => fetchJson(providerPath(providerId, '/movies/projection/status')),
  retryMovieProjection: (providerId) => fetchJson(providerPath(providerId, '/movies/projection/retry'), { method: 'POST' }),
  movieStatus: (providerId, params = {}) => fetchJson(withQuery(providerPath(providerId, '/movies/metadata/status'), params)),
  movieMetadataReview: (providerId, params = {}) => fetchJson(`${providerPath(providerId, '/movies/metadata/review')}?${queryString(params)}`),
  movieClassificationPreview: (providerId, payload = {}) => fetchJson(providerPath(providerId, '/movies/classification/preview'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  movieClassificationApply: (providerId, payload = {}) => fetchJson(providerPath(providerId, '/movies/classification/apply'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  createMovieMatchJob: (providerId, payload = {}) => fetchJson(providerPath(providerId, '/movies/match-jobs'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  movieMatchJob: (providerId, jobId) => fetchJson(providerPath(providerId, `/movies/match-jobs/${encodeURIComponent(jobId)}`)),
  cancelMovieMatchJob: (providerId, jobId) => fetchJson(providerPath(providerId, `/movies/match-jobs/${encodeURIComponent(jobId)}/cancel`), { method: 'POST' }),
  applyMovieMatchJob: (providerId, jobId, payload = {}) => fetchJson(providerPath(providerId, `/movies/match-jobs/${encodeURIComponent(jobId)}/apply`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  movieRebuildPreview: (providerId, payload = {}) => fetchJson(providerPath(providerId, '/movies/rebuild/preview'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  movieRebuildJob: (providerId, jobId) => fetchJson(providerPath(providerId, `/movies/rebuild/${encodeURIComponent(jobId)}`)),
  applyMovieRebuild: (providerId, jobId, payload = {}) => fetchJson(providerPath(providerId, `/movies/rebuild/${encodeURIComponent(jobId)}/apply`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  cancelMovieRebuild: (providerId, jobId) => fetchJson(providerPath(providerId, `/movies/rebuild/${encodeURIComponent(jobId)}/cancel`), { method: 'POST' }),
  movieFusionPreview: (providerId, payload = {}) => fetchJson(providerPath(providerId, '/movies/fusion/preview'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  applyMovieFusion: (providerId, payload = {}) => fetchJson(providerPath(providerId, '/movies/fusion/apply'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  movieEnrichment: (providerId, action, payload = {}) => fetchJson(providerPath(providerId, `/movies/enrichment/${encodeURIComponent(action)}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  prioritizeMovies: (providerId, movieKeys) => fetchJson(providerPath(providerId, '/movies/prioritize'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ movie_keys: movieKeys })
  }),
  movieDetail: (providerId, movieKey) => fetchJson(providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}`)),
  movieSources: (providerId, movieKey) => fetchJson(providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}/sources`)),
  movieLocalization: (providerId, movieKey, locale) => fetchJson(providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}/localization/${encodeURIComponent(locale)}`)),
  movieMatchSearch: (providerId, movieKey, params = {}) => fetchJson(`${providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}/match/search`)}?${queryString(params)}`),
  setMovieMatch: (providerId, movieKey, tmdbId) => fetchJson(providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}/match`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tmdb_id: tmdbId })
  }),
  removeMovieMatch: (providerId, movieKey, reprocess = false) => fetchJson(`${providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}/match`)}${reprocess ? '?reprocess=1' : ''}`, { method: 'DELETE' }),
  movieFavorite: (providerId, movieKey, favorite) => fetchJson(providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}/favorite`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ favorite })
  }),
  setMovieList: (providerId, movieKey, listId, included) => fetchJson(providerPath(providerId, `/movies/${encodeURIComponent(movieKey)}/lists/${encodeURIComponent(listId)}`), {
    method: included ? 'POST' : 'DELETE'
  }),
  favorites: (providerId, params) => fetchJson(`${providerPath(providerId, '/favorites')}?${queryString(params)}`),
  detail: (providerId, kind, itemId) => fetchJson(providerPath(providerId, `/items/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`)),
  epg: (providerId, streamId) => fetchJson(`${providerPath(providerId, `/epg/${encodeURIComponent(streamId)}`)}?limit=4`),
  recent: (providerId) => fetchJson(`${providerPath(providerId, '/recent')}?limit=12`),
  favorite: (providerId, kind, itemId, favorite) => fetchJson(providerPath(providerId, `/favorites/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ favorite })
  }),
  lists: (providerId, params = {}) => fetchJson(`${providerPath(providerId, '/lists')}?${queryString(params)}`),
  createList: (providerId, name) => fetchJson(providerPath(providerId, '/lists'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  }),
  renameList: (providerId, listId, name) => fetchJson(providerPath(providerId, `/lists/${encodeURIComponent(listId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name })
  }),
  deleteList: (providerId, listId) => fetchJson(providerPath(providerId, `/lists/${encodeURIComponent(listId)}`), { method: 'DELETE' }),
  listItems: (providerId, listId, params = {}) => fetchJson(`${providerPath(providerId, `/lists/${encodeURIComponent(listId)}/items`)}?${queryString(params)}`),
  setListItem: (providerId, listId, kind, itemId, included) => fetchJson(providerPath(providerId, `/lists/${encodeURIComponent(listId)}/items/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`), {
    method: included ? 'POST' : 'DELETE'
  }),
  moveListItem: (providerId, listId, kind, itemId, direction) => fetchJson(providerPath(providerId, `/lists/${encodeURIComponent(listId)}/items/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ direction })
  }),
  startPlayback: (providerId, payload) => fetchJson(providerPath(providerId, '/playback'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }),
  stopPlayback: (providerId, token) => fetchJson(providerPath(providerId, `/playback/${encodeURIComponent(token)}`), { method: 'DELETE' }),
  history: (providerId, kind, itemId, payload) => fetchJson(providerPath(providerId, `/history/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
};

export function iptvImage(providerId, kind, itemId, backdrop = false) {
  if (!providerId) return '';
  return `${providerPath(providerId, `/image/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`)}${backdrop ? '?backdrop=1' : ''}`;
}
