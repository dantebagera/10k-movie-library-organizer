import { fetchJson } from './client.js';

export async function searchTmdbMetadata({ title, year, fallback = '' }) {
  const query = String(title || fallback || '').trim();
  if (!query) throw new Error('Enter a movie title before searching TMDB');
  const params = new URLSearchParams({
    q: query,
    page: '1',
    metadata_context: 'unmatched'
  });
  const normalizedYear = String(year || '').trim();
  if (normalizedYear) params.set('year', normalizedYear);
  return fetchJson(`/api/tmdb/search?${params.toString()}`);
}

export async function searchPlexMetadata({
  path,
  title,
  year,
  ratingKey = '',
  forceSearch = false
}) {
  const params = new URLSearchParams({
    path: String(path || ''),
    title: String(title || '').trim(),
    year: String(year || '').trim()
  });
  if (ratingKey) params.set('rating_key', ratingKey);
  if (forceSearch) params.set('force_search', '1');
  return fetchJson(`/api/plex/match-search?${params.toString()}`);
}

export function applyTmdbMetadataMatch({ path, match }) {
  return fetchJson('/api/tmdb/match-apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      tmdb_id: match?.tmdb_id,
      movie: match
    })
  });
}

export function applyPlexMetadataMatch({ path, ratingKey, match }) {
  return fetchJson('/api/plex/match-apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path,
      rating_key: ratingKey,
      guid: match?.guid,
      name: match?.name || match?.title,
      year: match?.year || '',
      poster_url: match?.poster_url || '',
      summary: match?.summary || ''
    })
  });
}

export function requestPlexLibraryScan() {
  return fetchJson('/api/plex/force-scan', { method: 'POST' });
}
