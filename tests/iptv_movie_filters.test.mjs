import assert from 'node:assert/strict';
import test from 'node:test';

import {
  IPTV_MOVIE_SORTS,
  createIPTVMovieFilters,
  iptvMovieIdentity,
  iptvMovieQuery
} from '../src/features/iptv/iptvMovieFilters.js';

test('IPTV movie filters keep playlists, user lists, and temporary filters separate', () => {
  const filters = createIPTVMovieFilters();
  assert.equal(filters.playlist_id, '');
  assert.equal(filters.list_id, '');
  assert.equal(filters.sort, 'recent');
  assert.equal(IPTV_MOVIE_SORTS.length, 5);
});

test('IPTV movie query is bounded and serializes source claims explicitly', () => {
  const query = iptvMovieQuery({
    playlist_id: 'provider-playlist',
    list_id: 'user-list',
    genre_id: '18',
    dubbed: true,
    subtitled: false
  }, 0, 1000);
  assert.equal(query.playlist_id, 'provider-playlist');
  assert.equal(query.list_id, 'user-list');
  assert.equal(query.genre_id, '18');
  assert.equal(query.dubbed, 1);
  assert.equal(query.subtitled, '');
  assert.equal(query.page, 1);
  assert.equal(query.page_size, 100);
});

test('manual metadata identity separates spaced title year and technical claims', () => {
  assert.deepEqual(
    iptvMovieIdentity('ssss ( 2026 ) 4K'),
    { title: 'ssss', year: '2026' }
  );
  assert.deepEqual(
    iptvMovieIdentity('Provider Movie [2025]', '2024-03-01'),
    { title: 'Provider Movie', year: '2024' }
  );
});
