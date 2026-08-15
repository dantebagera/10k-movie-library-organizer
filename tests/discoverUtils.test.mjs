import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildOwnershipMap,
  replaceOwnershipScope,
  canonicalOwnedMovie,
  discoverMoviePayload,
  discoverMovieKey,
  filterEnrichedIndexerResults,
  listsForDiscoverMovie,
  ownedMovieFor,
  ownershipKeys,
  sortTorrentVariants
} from '../src/discoverUtils.js';

test('canonicalOwnedMovie makes the owned SQL card authoritative on every surface', () => {
  const online = {
    tmdb_id: '42', title: 'Online Title', year: '2025', poster_url: 'online.jpg',
    genres: ['Online'], plot: 'Online plot', tmdb_rating: '7.0', tmdb_vote_count: 1600,
    language: 'French', country: 'FR'
  };
  const owned = {
    canonical_card: {
      canonical_metadata: {
        accepted: true,
        tmdb_id: '42',
        imdb_id: 'tt0000042',
        title: 'Canonical Title',
        year: '2024',
        poster_url: 'canonical.jpg',
        genres: ['Drama'],
        plot: 'Canonical plot',
        summary: 'Canonical plot',
        rating: '8.4',
        tmdb_vote_count: 120,
        language: 'English',
        country: 'US',
        cast: [{ id: '1', name: 'SQL Actor' }],
        directors: [{ id: '2', name: 'SQL Director' }]
      }
    }
  };

  const displayed = canonicalOwnedMovie(online, owned);
  assert.equal(displayed.title, 'Canonical Title');
  assert.equal(displayed.year, '2024');
  assert.equal(displayed.poster_url, 'canonical.jpg');
  assert.deepEqual(displayed.genres, ['Drama']);
  assert.equal(displayed.plot, 'Canonical plot');
  assert.equal(displayed.tmdb_rating, '8.4');
  assert.equal(displayed.tmdb_vote_count, 120);
  assert.equal(displayed.language, 'English');
  assert.equal(displayed.country, 'US');
  assert.deepEqual(displayed.cast, [{ id: '1', name: 'SQL Actor' }]);
  assert.deepEqual(displayed.directors, [{ id: '2', name: 'SQL Director' }]);
});

test('buildOwnershipMap keeps only found movies with local paths', () => {
  const map = buildOwnershipMap([
    { tmdb_id: 1091, title: 'The Thing', year: '1982', found: true, path: 'E:/Movies/The Thing.mkv', resolution: '1080p' },
    { title: 'Alien', year: '1979', found: false, path: '', resolution: '' },
    { title: 'Heat', year: '1995', found: true, path: '', resolution: '720p' }
  ]);

  assert.equal(map['the thing|1982'].resolution, '1080p');
  assert.equal(map['title:the thing|1982'].resolution, '1080p');
  assert.equal(map[discoverMovieKey({ title: 'The Thing', year: '1982' })].resolution, '1080p');
  assert.equal(map['tmdb:1091'].resolution, '1080p');
});

test('buildOwnershipMap matches title variants through tmdb id', () => {
  const map = buildOwnershipMap([
    { tmdb_id: 601, title: 'E.T.', year: '1982', found: true, path: 'E:/Movies/ET.mkv', resolution: '1080p' }
  ]);

  assert.equal(map['tmdb:601'].path, 'E:/Movies/ET.mkv');
});

test('ownership never falls back from a conflicting strong id or a yearless title', () => {
  const ownership = buildOwnershipMap([
    { tmdb_id: 601, title: 'E.T.', year: '1982', found: true, path: 'E:/Movies/ET.mkv' }
  ]);

  assert.equal(ownedMovieFor({ tmdb_id: 999, title: 'E.T.', year: '1982' }, ownership), null);
  assert.deepEqual(ownershipKeys({ title: 'Crash', year: '' }), []);
});

test('filterEnrichedIndexerResults keeps browse rows without TMDB metadata', () => {
  const rows = filterEnrichedIndexerResults([
    {
      parsed_title: 'Earth, Wind & Fire',
      parsed_year: '2026',
      metadata: {
        tmdb_id: 123,
        title: 'Earth, Wind & Fire',
        year: '2026',
        poster_url: 'https://image.tmdb.org/poster.jpg',
        genres: ['Documentary']
      },
      variants: [{ resolution: '1080p', seeders: 100, size_human: '2.2 GB', indexer: 'YTS' }]
    },
    {
      parsed_title: 'Strange.Indexer.Release.Name',
      parsed_year: '',
      metadata: {},
      variants: [{ resolution: '1080p', seeders: 4, size_human: '1.1 GB', indexer: 'Unknown' }]
    }
  ]);

  assert.equal(rows.length, 2);
  assert.equal(rows[0].title, 'Earth, Wind & Fire');
  assert.equal(rows[0].tmdb_id, 123);
  assert.equal(rows[0].variants[0].indexer, 'YTS');
  assert.equal(rows[1].title, 'Strange.Indexer.Release.Name');
  assert.equal(rows[1].best_resolution, '1080p');
  assert.equal(rows[1].best_seeders, 4);
});

test('sortTorrentVariants prioritizes quality then seeders', () => {
  const variants = sortTorrentVariants([
    { resolution: '1080p', seeders: 450, size_human: '2 GB' },
    { resolution: '4K', seeders: 10, size_human: '12 GB' },
    { resolution: '720p', seeders: 900, size_human: '1 GB' },
    { resolution: '1080p', seeders: 1200, size_human: '4 GB' }
  ]);

  assert.deepEqual(
    variants.map((variant) => `${variant.resolution}:${variant.seeders}`),
    ['4K:10', '1080p:1200', '1080p:450', '720p:900']
  );
});

test('discoverMoviePayload supports online movies and owned paths', () => {
  const payload = discoverMoviePayload(
    { tmdb_id: 155, title: 'The Dark Knight', year: '2008', release_date: '2008-07-18', poster_url: 'poster.jpg' },
    { path: 'E:/Movies/The Dark Knight.mkv' }
  );

  assert.deepEqual(payload, {
    movie_key: '',
    tmdb_id: '155',
    imdb_id: '',
    plex_guid: '',
    title: 'The Dark Knight',
    year: '2008',
    release_date: '2008-07-18',
    poster_url: 'poster.jpg',
    path: 'E:/Movies/The Dark Knight.mkv'
  });
});

test('listsForDiscoverMovie matches online movies by tmdb id without a file path', () => {
  const lists = [
    {
      id: 'favorites',
      name: 'Favorites',
      movies: [{ tmdb_id: '155', title: 'The Dark Knight', year: '2008', poster_url: 'poster.jpg' }]
    },
    {
      id: 'watch-later',
      name: 'Watch Later',
      movies: [{ title: 'Heat', year: '1995' }]
    }
  ];

  const matches = listsForDiscoverMovie({ tmdb_id: 155, title: 'The Dark Knight', year: '2008' }, lists);

  assert.deepEqual(matches.map((list) => list.name), ['Favorites']);
});

test('replaceOwnershipScope removes every stale alias when a movie becomes unowned', () => {
  const movie = { tmdb_id: 601, title: 'E.T.', year: '1982' };
  const ownership = buildOwnershipMap([{
    ...movie,
    found: true,
    path: 'E:/Movies/ET.mkv',
    movie_key: 'tmdb:601'
  }]);

  const refreshed = replaceOwnershipScope(ownership, [movie], [{ ...movie, found: false, path: '' }]);

  assert.equal(ownedMovieFor(movie, refreshed), null);
  assert.equal(Object.keys(refreshed).length, 0);
});

test('owned list membership uses the canonical CP movie key after legacy projection', () => {
  const movie = { tmdb_id: '936075', title: 'Michael', year: '2026' };
  const owned = {
    path: 'E:/Movies/Michael.2026.mkv',
    canonical_card: {
      canonical_metadata: {
        accepted: true,
        movie_key: 'tmdb:936075',
        tmdb_id: '936075',
        imdb_id: 'tt11378946',
        title: 'Michael',
        year: '2026'
      }
    }
  };
  const lists = [{
    id: 'watched',
    system_type: 'watched',
    movies: [{ movie_key: 'tmdb:936075', title: 'Michael', year: '2026' }]
  }];

  assert.equal(discoverMoviePayload(movie, owned).movie_key, 'tmdb:936075');
  assert.deepEqual(listsForDiscoverMovie(movie, lists, owned).map((list) => list.id), ['watched']);
});
