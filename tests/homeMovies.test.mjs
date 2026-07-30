import test from 'node:test';
import assert from 'node:assert/strict';

import { buildUpcomingHomeMovies, uniqueHomeMovies } from '../src/utils/homeMovies.js';

test('upcoming Home movies exclude past, duplicate, and Trending titles then sort by release date', () => {
  const trending = [{ tmdb_id: 2, title: 'Already Trending', year: '2026' }];
  const results = [
    { tmdb_id: 1, title: 'Later', release_date: '2026-09-10', popularity: 20 },
    { tmdb_id: 2, title: 'Already Trending', release_date: '2026-08-02' },
    { tmdb_id: 3, title: 'Past', release_date: '2026-07-01' },
    { tmdb_id: 4, title: 'Soon', release_date: '2026-08-02', popularity: 10 },
    { tmdb_id: 4, title: 'Soon duplicate', release_date: '2026-08-02', popularity: 100 },
    { tmdb_id: 5, title: 'Soon popular', release_date: '2026-08-02', popularity: 30 }
  ];

  assert.deepEqual(
    buildUpcomingHomeMovies(results, trending, new Date(2026, 6, 28)).map((movie) => movie.title),
    ['Soon popular', 'Soon', 'Later']
  );
});

test('unique Home movies prefer the first authoritative projection', () => {
  const first = { tmdb_id: 10, title: 'First' };
  const second = { tmdb_id: 10, title: 'Duplicate' };
  const titleOnly = { title: 'No ID', year: '2026' };

  assert.deepEqual(uniqueHomeMovies([first], [second, titleOnly, { ...titleOnly }]), [first, titleOnly]);
});
