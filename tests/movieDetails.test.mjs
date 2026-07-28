import assert from 'node:assert/strict';
import test from 'node:test';

import {
  markMovieDetailsCacheStale,
  mergeCanonicalMovieDetails,
  mergeTransientMovieLanguage,
  movieCollectionCacheKey,
  movieCollectionView
} from '../src/api/movieDetails.js';

test('catalog changes retain visible movie details while marking them for refresh', () => {
  const cache = {
    'owned:c:\\movies\\one.mkv': {
      plot: 'The visible plot',
      certification: 'R',
      writers: [{ name: 'A Writer' }],
      keywords: ['horror']
    }
  };

  const staleCache = markMovieDetailsCacheStale(cache);

  assert.notEqual(staleCache, cache);
  assert.notEqual(staleCache['owned:c:\\movies\\one.mkv'], cache['owned:c:\\movies\\one.mkv']);
  assert.equal(staleCache['owned:c:\\movies\\one.mkv'].plot, 'The visible plot');
  assert.equal(staleCache['owned:c:\\movies\\one.mkv'].certification, 'R');
  assert.deepEqual(staleCache['owned:c:\\movies\\one.mkv'].writers, [{ name: 'A Writer' }]);
  assert.deepEqual(staleCache['owned:c:\\movies\\one.mkv'].keywords, ['horror']);
  assert.equal(staleCache['owned:c:\\movies\\one.mkv'].stale, true);
  assert.equal(cache['owned:c:\\movies\\one.mkv'].stale, undefined);
});

test('owned detail merges preserve valid card summaries when deferred fields are empty', () => {
  const summary = {
    projection_contract: 'canonical_movie_card',
    title: 'Correct Movie',
    year: '2020',
    plot: 'Stored plot',
    summary: 'Stored plot',
    poster_url: 'local-or-provider-poster.jpg',
    genres: ['Drama'],
    rating: '8.4'
  };
  const details = {
    projection_contract: 'canonical_movie_details',
    title: '',
    plot: '',
    summary: '',
    poster_url: '',
    genres: [],
    cast: [{ id: '1', name: 'Lead Actor' }]
  };

  const merged = mergeCanonicalMovieDetails(summary, details);

  assert.equal(merged.title, 'Correct Movie');
  assert.equal(merged.plot, 'Stored plot');
  assert.equal(merged.summary, 'Stored plot');
  assert.equal(merged.poster_url, 'local-or-provider-poster.jpg');
  assert.deepEqual(merged.genres, ['Drama']);
  assert.equal(merged.cast[0].name, 'Lead Actor');
  assert.equal(merged.projection_contract, 'canonical_movie_details');
});

test('transient language overlay replaces display fields without mutating canonical data', () => {
  const movie = {
    title: 'Fight Club',
    plot: 'English plot',
    summary: 'English plot',
    poster_url: 'english.jpg',
    genres: ['Drama']
  };
  const details = { runtime: 139, tagline: 'English tagline', loading: false };
  const localized = {
    title: 'نادي القتال',
    plot: 'حبكة عربية',
    poster_url: 'arabic.jpg',
    genres: ['دراما'],
    tagline: 'شعار عربي',
    runtime: 139,
    transient: true
  };

  const result = mergeTransientMovieLanguage(movie, details, localized);

  assert.equal(result.displayMovie.title, 'نادي القتال');
  assert.equal(result.displayMovie.summary, 'حبكة عربية');
  assert.equal(result.displayMovie.poster_url, 'arabic.jpg');
  assert.deepEqual(result.displayMovie.genres, ['دراما']);
  assert.equal(result.displayDetails.tagline, 'شعار عربي');
  assert.equal(movie.title, 'Fight Club');
  assert.equal(details.tagline, 'English tagline');
});

test('collection caches keep Library and TMDB payloads separate for the same collection', () => {
  const libraryDetails = {
    detail_source: 'library_sql',
    collection: { id: '7001', name: 'SQL Collection' }
  };
  const tmdbDetails = {
    detail_source: 'tmdb_live',
    collection: { id: '7001', name: 'SQL Collection' }
  };

  assert.equal(movieCollectionCacheKey(libraryDetails), 'library:7001');
  assert.equal(movieCollectionCacheKey(tmdbDetails), 'tmdb:7001');
  assert.notEqual(movieCollectionCacheKey(libraryDetails), movieCollectionCacheKey(tmdbDetails));
});

test('partial collection identity remains loading-capable instead of becoming a false zero', () => {
  const details = {
    detail_source: 'tmdb_live',
    collection: { id: '7001', name: 'SQL Collection' }
  };

  const pendingView = movieCollectionView({}, details);
  assert.equal(pendingView.status, 'idle');
  assert.equal(pendingView.data.name, 'SQL Collection');
  assert.equal(pendingView.data.parts, undefined);

  const loadedView = movieCollectionView({
    'tmdb:7001': {
      status: 'loaded',
      data: {
        id: '7001',
        name: 'SQL Collection',
        parts: [{ tmdb_id: '1' }, { tmdb_id: '2' }]
      },
      error: ''
    }
  }, details);

  assert.equal(loadedView.status, 'loaded');
  assert.equal(loadedView.data.parts.length, 2);
});
