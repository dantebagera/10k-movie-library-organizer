import { ownershipKeys } from '../discoverUtils.js';
import { fetchJson } from './client.js';

const OWNERSHIP_CHECK_CACHE_TTL = 30000;
export const CATALOG_GENERATION_CHANGED_EVENT = 'cp-catalog-generation-changed';
let ownershipCheckCache = new Map();
let ownershipCatalogGeneration = null;

export function clearOwnershipCheckCache() {
  ownershipCheckCache = new Map();
}

export function observeCatalogGeneration(generation) {
  const nextGeneration = Number(generation);
  if (!Number.isFinite(nextGeneration)) return false;
  if (ownershipCatalogGeneration !== null && nextGeneration < ownershipCatalogGeneration) return false;
  const changed = ownershipCatalogGeneration !== null && ownershipCatalogGeneration !== nextGeneration;
  if (changed) {
    clearOwnershipCheckCache();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent(CATALOG_GENERATION_CHANGED_EVENT, {
        detail: { previousGeneration: ownershipCatalogGeneration, generation: nextGeneration }
      }));
    }
  }
  ownershipCatalogGeneration = nextGeneration;
  return changed;
}

function ownershipCheckQuery(movie) {
  return {
    tmdb_id: String(movie?.tmdb_id || ''),
    imdb_id: String(movie?.imdb_id || ''),
    plex_guid: String(movie?.plex_guid || ''),
    title: movie?.title || '',
    year: String(movie?.year || '')
  };
}

function freshOwnershipCheck(keys, now = Date.now()) {
  for (const key of keys) {
    const cached = ownershipCheckCache.get(key);
    if (cached && now - cached.time < OWNERSHIP_CHECK_CACHE_TTL) return cached.result;
  }
  return null;
}

function storeOwnershipCheck(query, result, now = Date.now()) {
  const keys = [...new Set([...ownershipKeys(query), ...ownershipKeys(result)])];
  for (const key of keys) ownershipCheckCache.set(key, { result, time: now });
}

export async function fetchOwnershipChecks(movies = []) {
  const now = Date.now();
  const results = [];
  const missing = [];
  const seenMissing = new Set();
  for (const movie of movies || []) {
    const query = ownershipCheckQuery(movie);
    const keys = ownershipKeys(query);
    if (!keys.length) continue;
    const cached = freshOwnershipCheck(keys, now);
    if (cached) {
      results.push(cached);
      continue;
    }
    if (seenMissing.has(keys[0])) continue;
    seenMissing.add(keys[0]);
    missing.push(query);
  }
  if (missing.length) {
    const check = await fetchJson('/api/library/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ movies: missing })
    });
    observeCatalogGeneration(check.catalog_generation);
    const freshTime = Date.now();
    (check.results || []).forEach((result, index) => {
      storeOwnershipCheck(missing[index] || result, result, freshTime);
      results.push(result);
    });
  }
  return results;
}

export function announceLibraryChanged(detail = {}) {
  clearOwnershipCheckCache();
  observeCatalogGeneration(detail?.catalog_generation);
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('cp-library-changed', { detail }));
  }
}

export function announceLibraryReconciled(state) {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('cp-library-reconciled', { detail: state }));
  }
  announceLibraryChanged({ source: 'reconcile', reconcile: state });
}
