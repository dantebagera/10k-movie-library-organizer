import { fetchJson } from './client.js';

export function previewSourceReview(movies, options = {}) {
  return fetchJson('/api/sources/review/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      movies,
      ...(options.quality ? { quality: options.quality } : {}),
      ...(options.policy ? { policy: options.policy } : {})
    })
  });
}

export function submitSourceReview(rows) {
  return fetchJson('/api/sources/review/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rows })
  });
}
