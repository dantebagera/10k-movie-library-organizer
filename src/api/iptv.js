import { fetchJson } from './client.js';

function queryString(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== '' && value !== undefined && value !== null && value !== false) query.set(key, String(value));
  });
  return query.toString();
}

function providerPath(providerId, suffix = '') {
  if (!providerId) throw new Error('An IPTV provider must be selected');
  return `/api/iptv/providers/${encodeURIComponent(providerId)}${suffix}`;
}

export const iptvApi = {
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
