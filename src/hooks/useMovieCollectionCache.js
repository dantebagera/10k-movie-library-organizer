import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchCurationJson } from '../api/curation.js';
import {
  movieCollectionCacheKey,
  movieCollectionUrl,
  movieCollectionView
} from '../api/movieDetails.js';

export default function useMovieCollectionCache() {
  const [cache, setCache] = useState({});
  const cacheRef = useRef(cache);
  const pendingRef = useRef(new Map());
  const generationRef = useRef(0);
  const loadRef = useRef(null);

  const updateCache = useCallback((updater) => {
    setCache((current) => {
      const next = updater(current);
      cacheRef.current = next;
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    const interrupted = Array.from(pendingRef.current.values(), ({ details }) => details).filter(Boolean);
    generationRef.current += 1;
    pendingRef.current.forEach(({ controller }) => controller.abort());
    pendingRef.current.clear();
    cacheRef.current = {};
    setCache({});
    if (interrupted.length) {
      queueMicrotask(() => interrupted.forEach((details) => loadRef.current?.(details, { force: true })));
    }
  }, []);

  const storeLoaded = useCallback((details, data) => {
    const cacheKey = movieCollectionCacheKey(details);
    if (!cacheKey) return;
    if (pendingRef.current.has(cacheKey)) {
      pendingRef.current.get(cacheKey).controller.abort();
      pendingRef.current.delete(cacheKey);
    }
    updateCache((current) => ({
      ...current,
      [cacheKey]: { status: 'loaded', data, error: '' }
    }));
  }, [updateCache]);

  const load = useCallback((details, options = {}) => {
    const cacheKey = movieCollectionCacheKey(details);
    const url = movieCollectionUrl(details);
    if (!cacheKey || !url) return Promise.resolve(null);

    const existing = cacheRef.current[cacheKey];
    if (!options.force && existing?.status === 'loaded') return Promise.resolve(existing.data);
    if (!options.force && pendingRef.current.has(cacheKey)) return pendingRef.current.get(cacheKey).promise;

    if (options.force && pendingRef.current.has(cacheKey)) {
      pendingRef.current.get(cacheKey).controller.abort();
      pendingRef.current.delete(cacheKey);
    }

    const controller = new AbortController();
    const generation = generationRef.current;
    updateCache((current) => ({
      ...current,
      [cacheKey]: {
        status: 'loading',
        data: current[cacheKey]?.data || details.collection || {},
        error: ''
      }
    }));

    const promise = fetchCurationJson(url, { signal: controller.signal })
      .then((data) => {
        if (generation !== generationRef.current) return null;
        updateCache((current) => ({
          ...current,
          [cacheKey]: { status: 'loaded', data, error: '' }
        }));
        return data;
      })
      .catch((error) => {
        if (error?.name === 'AbortError' || generation !== generationRef.current) return null;
        updateCache((current) => ({
          ...current,
          [cacheKey]: {
            status: 'error',
            data: current[cacheKey]?.data || details.collection || {},
            error: error.message || 'Collection details are unavailable.'
          }
        }));
        return null;
      })
      .finally(() => {
        const pending = pendingRef.current.get(cacheKey);
        if (pending?.promise === promise) pendingRef.current.delete(cacheKey);
      });

    pendingRef.current.set(cacheKey, { controller, promise, details });
    return promise;
  }, [updateCache]);

  loadRef.current = load;

  const getView = useCallback((details) => movieCollectionView(cache, details), [cache]);

  useEffect(() => () => {
    pendingRef.current.forEach(({ controller }) => controller.abort());
    pendingRef.current.clear();
  }, []);

  return {
    clear,
    getView,
    load,
    storeLoaded
  };
}
