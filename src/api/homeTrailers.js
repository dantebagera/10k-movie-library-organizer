import { fetchJson } from './client.js';
import {
  mergeTrailerMovieCandidates,
  parseHomeTrailerTitle,
  selectConfidentTrailerMovie
} from '../utils/homeTrailers.js';

export async function fetchHomeTrailers({ cursor = '', source = 'all', signal } = {}) {
  const params = new URLSearchParams();
  if (cursor) params.set('cursor', cursor);
  if (source && source !== 'all') params.set('source', source);
  const query = params.toString();
  return fetchJson(`/api/home/trailers${query ? `?${query}` : ''}`, { signal });
}

export async function searchYouTubeMovieTrailers(movie, { signal } = {}) {
  return fetchJson('/api/youtube/trailer-search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: movie?.title || '', year: movie?.year || '' }),
    signal
  });
}

async function searchTmdbMovies(title, year, signal) {
  const params = new URLSearchParams({
    q: String(title || '').trim(),
    page: '1',
    page_size: '10',
    include_adult: 'false'
  });
  if (year) params.set('year', year);
  const data = await fetchJson(`/api/tmdb/search?${params.toString()}`, { signal });
  return data.results || [];
}

export async function resolveHomeTrailerMovie(videoTitle, { signal } = {}) {
  const hint = parseHomeTrailerTitle(videoTitle);
  if (!hint.title) {
    return { status: 'unmatched', hint, candidates: [], reason: 'missing_title' };
  }

  const scoped = hint.year ? await searchTmdbMovies(hint.title, hint.year, signal) : [];
  let candidates = mergeTrailerMovieCandidates(scoped);
  let selected = selectConfidentTrailerMovie(hint, candidates);
  if (selected.movie) {
    return { status: 'matched', hint, candidates, movie: selected.movie, reason: selected.reason };
  }

  const unscoped = await searchTmdbMovies(hint.title, '', signal);
  candidates = mergeTrailerMovieCandidates(scoped, unscoped);
  selected = selectConfidentTrailerMovie(hint, candidates);
  return selected.movie
    ? { status: 'matched', hint, candidates, movie: selected.movie, reason: selected.reason }
    : { status: 'unmatched', hint, candidates, movie: null, reason: selected.reason };
}

export async function searchHomeTrailerMovieCandidates(title, year, { signal } = {}) {
  const query = String(title || '').trim();
  if (!query) return [];
  const scoped = year ? await searchTmdbMovies(query, year, signal) : [];
  const unscoped = !year || scoped.length === 0
    ? await searchTmdbMovies(query, '', signal)
    : [];
  return mergeTrailerMovieCandidates(scoped, unscoped);
}
