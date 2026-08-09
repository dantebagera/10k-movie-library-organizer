import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applySystemListState,
  applyPosterOverrideToLibraryItems,
  buildLibraryPeopleIndex,
  buildLibraryViewModel,
  buildMovieListViewModel,
  getCompactQualityLabel,
  getMovieIdentity,
  getQualityFactsLabel,
  getQualityLabel,
  getTmdbCacheKey,
  getLocaleTag,
  isLowQuality,
  getRolePeople,
  getStoredRolePeople,
  itemMatchesCollectionFilter,
  itemMatchesRoleFilter,
  listLibraryCoverage,
  listsForItem,
  movieHasSystemState,
  mergePeople,
  matchesLibraryResolutionFilter,
  movieIdentityKey,
  movieIdentityKeys,
  moviePayload,
  moviesShareIdentity,
  normalizeCollectionTitle,
  normalizePersonName,
  peopleMatch,
  resolutionRank,
  rootLabel,
  splitLibraryTitle
} from '../src/utils/libraryUtils.js';

test('movie list view model keeps owned and missing movies together with upgrade flags', () => {
  const libraryItems = [
    {
      title: 'Heat (1995)',
      resolution: '720p',
      rip_source: 'WEB-DL',
      path: 'E:/Movies/Heat.mkv',
      maintenance_upgrade_candidate: true,
      canonical_metadata: { accepted: true, title: 'Heat', year: '1995', tmdb_id: '949', poster_url: 'heat-owned.jpg' }
    },
    {
      title: 'Alien (1979)',
      resolution: '1080p',
      rip_source: 'BluRay',
      path: 'E:/Movies/Alien.mkv',
      canonical_metadata: { accepted: true, title: 'Alien', year: '1979', tmdb_id: '348' }
    }
  ];
  const list = {
    id: 'favorites',
    name: 'Favorites',
    movies: [
      { tmdb_id: '949', title: 'Heat', year: '1995', poster_url: 'heat-list.jpg' },
      { tmdb_id: '680', title: 'Pulp Fiction', year: '1994', poster_url: 'pulp.jpg' },
      { tmdb_id: '348', title: 'Alien', year: '1979', poster_url: 'alien-list.jpg' }
    ]
  };

  const model = buildMovieListViewModel({ libraryItems, list, query: '', statusFilter: 'all' });

  assert.deepEqual(model.stats, { total: 3, owned: 2, missing: 1, upgrades: 1 });
  assert.equal(model.rows.length, 3);
  assert.equal(model.rows[0].status, 'upgrade');
  assert.equal(model.rows[0].ownedItem.path, 'E:/Movies/Heat.mkv');
  assert.equal(model.rows[0].poster_url, 'heat-owned.jpg');
  assert.equal(model.rows[1].status, 'missing');
  assert.equal(model.rows[1].poster_url, 'pulp.jpg');
  assert.equal(model.rows[2].status, 'owned');
  assert.equal(model.rows[2].poster_url, '');

  const missing = buildMovieListViewModel({ libraryItems, list, query: 'pulp', statusFilter: 'missing' });
  assert.equal(missing.rows.length, 1);
  assert.equal(missing.rows[0].title, 'Pulp Fiction');
});

test('compact movie-view quality keeps only the class and source', () => {
  assert.equal(
    getCompactQualityLabel({
      quality_class: '1080p',
      resolution: '1080-class - 1904 x 800',
      rip_source: 'Blu-ray'
    }),
    '1080 · Blu-ray'
  );
  assert.equal(getCompactQualityLabel({ resolution: '2160p' }), '2160');
  assert.equal(getCompactQualityLabel({ rip_source: 'WEB-DL' }), 'WEB-DL');
});

test('ownership fallback requires a year and never crosses conflicting Plex identities', () => {
  assert.deepEqual(movieIdentityKeys({ title: 'Crash', year: '' }), []);
  assert.equal(
    moviesShareIdentity(
      { title: 'Crash', year: '1996', plex_guid: 'plex://movie/one' },
      { title: 'Crash', year: '1996', plex_guid: 'plex://movie/two' }
    ),
    false
  );
});

test('poster updates reach duplicate copies but not conflicting strong identities', () => {
  const selected = {
    path: 'E:/Movies/Alien.1979.1080p.mkv',
    canonical_metadata: {
      accepted: true,
      tmdb_id: '348',
      imdb_id: 'tt0078748',
      title: 'Alien',
      year: '1979',
      poster_url: 'provider-a.jpg'
    }
  };
  const duplicate = {
    path: 'F:/Movies/Alien.1979.4K.mkv',
    canonical_metadata: {
      accepted: true,
      tmdb_id: '348',
      title: 'Alien',
      year: '1979',
      poster_url: 'provider-b.jpg'
    }
  };
  const conflict = {
    path: 'G:/Movies/Alien.1979.Other.mkv',
    canonical_metadata: {
      accepted: true,
      tmdb_id: '999',
      title: 'Alien',
      year: '1979',
      poster_url: 'other-movie.jpg'
    }
  };

  const updated = applyPosterOverrideToLibraryItems(
    [selected, duplicate, conflict],
    selected,
    '/api/library/posters/image/saved.jpg',
    { id: 'override-id', source: 'local' }
  );

  assert.equal(updated[0].canonical_metadata.poster_url, '/api/library/posters/image/saved.jpg');
  assert.equal(updated[1].canonical_metadata.poster_url, '/api/library/posters/image/saved.jpg');
  assert.equal(updated[2].canonical_metadata.poster_url, 'other-movie.jpg');
  assert.equal(updated[0].canonical_metadata.poster_override_source, 'local');
});

test('splitLibraryTitle separates trailing release year only', () => {
  assert.deepEqual(splitLibraryTitle('Heat (1995)'), { title: 'Heat', year: '1995' });
  assert.deepEqual(splitLibraryTitle('Brazil (Director Cut)'), { title: 'Brazil (Director Cut)', year: '' });
  assert.deepEqual(splitLibraryTitle(''), { title: '', year: '' });
});

test('resolution helpers preserve current library bucket behavior', () => {
  assert.equal(resolutionRank('2160p HDR'), 4);
  assert.equal(resolutionRank('4K WEB'), 4);
  assert.equal(resolutionRank('1080p BluRay'), 3);
  assert.equal(resolutionRank('720p HDTV'), 2);
  assert.equal(resolutionRank('480p DVD'), 1);
  assert.equal(resolutionRank('Unknown'), 0);

  assert.equal(isLowQuality('720p'), true);
  assert.equal(isLowQuality('1080p'), false);
  assert.equal(matchesLibraryResolutionFilter('2160p', '4k'), true);
  assert.equal(matchesLibraryResolutionFilter('1080p', '1080p'), true);
  assert.equal(matchesLibraryResolutionFilter('720p', '720p'), true);
  assert.equal(matchesLibraryResolutionFilter('480p', 'below-720p'), true);
  assert.equal(matchesLibraryResolutionFilter('1080p', 'below-720p'), false);
  assert.equal(matchesLibraryResolutionFilter('Unknown', 'unexpected-filter'), true);
});

test('getMovieIdentity prefers accepted canonical metadata before Plex and file fallback', () => {
  assert.deepEqual(
    getMovieIdentity({
      title: 'Local Title (2000)',
      canonical_metadata: { accepted: true, title: 'Canonical Title', year: 1999 },
      plex_title: 'Plex Title',
      plex_year: 2001,
      filename: 'Fallback.mkv'
    }),
    { title: 'Canonical Title', year: '1999' }
  );

  assert.deepEqual(
    getMovieIdentity({
      title: 'Parsed Title (1984)',
      plex_title: 'Plex Title',
      plex_year: 1985,
      filename: 'Fallback.mkv'
    }),
    { title: 'Plex Title', year: '1985' }
  );

  assert.deepEqual(
    getMovieIdentity({ filename: 'Movie.File.Name.mkv' }),
    { title: 'Movie.File.Name', year: '' }
  );
});

test('getTmdbCacheKey preserves canonical id, item id, then identity fallback precedence', () => {
  assert.equal(
    getTmdbCacheKey({ canonical_metadata: { accepted: true, title: 'Heat', year: 1995, tmdb_id: 949 }, tmdb_id: 1 }),
    'tmdb:949'
  );
  assert.equal(
    getTmdbCacheKey({ title: 'The Thing (1982)', tmdb_id: 1091 }),
    'tmdb:1091'
  );
  assert.equal(
    getTmdbCacheKey({ title: 'The Thing (1982)' }),
    'The Thing|1982'
  );
});

test('display labels preserve current quality and root fallbacks', () => {
  assert.equal(getQualityLabel({ resolution: '1080p', rip_source: 'BluRay' }), '1080p BluRay');
  assert.equal(
    getQualityLabel({
      quality_display: '1080-class - 1800 x 960',
      quality_class: '1080p',
      resolution: '720p',
      rip_source: 'WEB-DL'
    }),
    '1080-class - 1800 x 960 WEB-DL'
  );
  assert.equal(
    getQualityFactsLabel({
      quality_display: 'Measured 954 x 576 - filename claims 1080p',
      resolution: '1080p'
    }),
    'Measured 954 x 576 - filename claims 1080p'
  );
  assert.equal(getQualityLabel({ resolution: 'Unknown', rip_source: 'WEB-DL' }), 'WEB-DL');
  assert.equal(getQualityLabel({ resolution: 'Unknown', rip_source: 'Unknown' }), 'Unknown quality');
  assert.equal(rootLabel('E:\\Movies\\'), 'Root: Movies');
  assert.equal(rootLabel('/mnt/media/library/'), 'Root: library');
  assert.equal(rootLabel(''), 'Library root');
});

test('getLocaleTag preserves canonical and Plex country/language abbreviations', () => {
  assert.equal(
    getLocaleTag({ canonical_metadata: { country: 'United States of America', language: 'English' } }),
    'US / EN'
  );
  assert.equal(
    getLocaleTag({ canonical_metadata: { country_flag: 'Republic of Korea', language: 'Korean' } }),
    'KR / KO'
  );
  assert.equal(
    getLocaleTag({ plex_country: 'France', plex_language: 'French' }),
    'FR / FR'
  );
  assert.equal(
    getLocaleTag({ canonical_metadata: { country: 'Argentina', language: 'Portuguese' } }),
    'AR / PO'
  );
  assert.equal(getLocaleTag({ canonical_metadata: {}, plex_language: 'Dutch' }), 'NL');
  assert.equal(getLocaleTag({}), '');
});

test('person helpers preserve current role matching and merge behavior', () => {
  assert.equal(normalizePersonName('  Park Chan-wook  '), 'park chan-wook');
  assert.equal(peopleMatch({ id: 10, name: 'Wrong Name' }, { id: '10', name: 'Other' }), true);
  assert.equal(peopleMatch({ name: 'Sigourney Weaver' }, { name: 'sigourney weaver' }), true);
  assert.equal(peopleMatch(null, { name: 'Nobody' }), false);

  assert.deepEqual(
    mergePeople(
      [{ name: 'Sigourney Weaver', character: 'Ripley' }],
      [
        { name: 'Sigourney Weaver', id: 42, profile_url: 'profile.jpg', character: 'Ellen Ripley' },
        { name: 'Tom Skerritt', id: 43 }
      ]
    ),
    [
      { name: 'Sigourney Weaver', id: 42, profile_url: 'profile.jpg', character: 'Ripley' },
      { name: 'Tom Skerritt', id: 43 }
    ]
  );
});

test('getRolePeople and itemMatchesRoleFilter preserve canonical, Plex, and TMDB fallbacks', () => {
  const item = {
    canonical_metadata: {
      directors: [{ name: 'Ridley Scott' }],
      cast: [{ name: 'Sigourney Weaver', character: 'Ripley' }]
    },
    plex_directors: [{ name: 'Plex Director' }],
    plex_cast: [{ name: 'Plex Actor' }]
  };
  const details = {
    director: { id: 1, name: 'Ridley Scott', profile_url: 'ridley.jpg' },
    cast: [
      { id: 2, name: 'Sigourney Weaver', profile_url: 'sigourney.jpg' },
      { id: 3, name: 'Ian Holm' }
    ]
  };

  assert.deepEqual(getRolePeople(item, details, 'director'), [
    { id: 1, name: 'Ridley Scott', profile_url: 'ridley.jpg', character: undefined }
  ]);
  assert.deepEqual(getRolePeople(item, details, 'actor'), [
    { id: 2, name: 'Sigourney Weaver', profile_url: 'sigourney.jpg', character: 'Ripley' },
    { id: 3, name: 'Ian Holm' }
  ]);
  assert.equal(itemMatchesRoleFilter(item, details, { role: 'director', name: 'ridley scott' }), true);
  assert.equal(itemMatchesRoleFilter(item, details, { role: 'actor', id: 3, name: 'Other' }), true);
  assert.equal(itemMatchesRoleFilter(item, details, { role: 'actor', name: 'Veronica Cartwright' }), false);
  assert.equal(itemMatchesRoleFilter(item, details, null), true);
});

test('library people index stays local to accepted movies and can enforce a local role filter', () => {
  const accepted = {
    path: 'E:/Movies/Braveheart.mkv',
    canonical_metadata: {
      accepted: true,
      title: 'Braveheart',
      year: '1995',
      directors: [{ id: 2461, name: 'Mel Gibson' }],
      cast: [{ id: 2461, name: 'Mel Gibson' }, { name: 'Sophie Marceau' }],
      writers: [{ id: 2461, name: 'Mel Gibson', job: 'Screenplay' }]
    }
  };
  const unaccepted = {
    path: 'E:/Movies/Unmatched.mkv',
    canonical_metadata: { accepted: false, cast: [{ name: 'Mel Gibson' }] }
  };
  const nameOnly = {
    path: 'E:/Movies/What Women Want.mkv',
    canonical_metadata: {
      accepted: true,
      title: 'What Women Want',
      year: '2000',
      cast: [{ name: 'Mel Gibson', profile_url: 'https://image.tmdb.org/mel.jpg' }]
    }
  };
  const index = buildLibraryPeopleIndex([accepted, unaccepted, nameOnly], 'melgibson');

  assert.deepEqual(index, [{
    id: '2461',
    name: 'Mel Gibson',
    profile_url: 'https://image.tmdb.org/mel.jpg',
    roles: ['actor', 'director', 'writer'],
    movieCount: 2,
    knownFor: ['Braveheart (1995)', 'What Women Want (2000)'],
    localIdentity: false
  }]);
  assert.deepEqual(getStoredRolePeople(accepted, 'actor'), accepted.canonical_metadata.cast);
  assert.deepEqual(getStoredRolePeople(accepted, 'writer'), accepted.canonical_metadata.writers);
  assert.equal(
    itemMatchesRoleFilter(
      accepted,
      {},
      { role: 'writer', id: '2461', name: 'Mel Gibson', localOnly: true }
    ),
    true
  );
  assert.equal(
    itemMatchesRoleFilter(
      { ...accepted, canonical_metadata: { ...accepted.canonical_metadata, cast: [] } },
      { cast: [{ id: 2461, name: 'Mel Gibson' }] },
      { role: 'actor', id: '2461', name: 'Mel Gibson', localOnly: true }
    ),
    false
  );
});

test('collection normalization preserves current title cleanup behavior', () => {
  assert.equal(normalizeCollectionTitle('Blade Runner 2049: The Final Cut'), 'blade runner 2049 the');
  assert.equal(normalizeCollectionTitle('Alien³ Special Edition'), 'alien 3');
  assert.equal(normalizeCollectionTitle('Terminator ² Director Cut'), 'terminator 2');
  assert.equal(normalizeCollectionTitle('Film ł Special Edition'), 'film 3');
});

test('movie payload and identity keys preserve canonical and path precedence', () => {
  const item = {
    title: 'Local Title (1995)',
    year: 1994,
    path: 'E:/Movies/Heat.mkv',
    tmdb_id: 1,
    imdb_id: 'tt0001',
    plex_poster: 'plex.jpg',
    poster_url: 'poster.jpg',
    canonical_metadata: {
      accepted: true,
      movie_key: 'tmdb:949',
      title: 'Heat',
      year: 1995,
      tmdb_id: 949,
      imdb_id: 'tt0113277',
      poster_url: 'canonical.jpg'
    }
  };

  assert.deepEqual(moviePayload(item), {
    movie_key: 'tmdb:949',
    tmdb_id: '949',
    imdb_id: 'tt0113277',
    plex_guid: '',
    title: 'Heat',
    year: '1995',
    path: 'E:/Movies/Heat.mkv',
    poster_url: 'canonical.jpg'
  });
  assert.equal(movieIdentityKey({ movie_key: 'plex:movie/heat', tmdb_id: 949 }), 'plex:movie/heat');
  assert.equal(movieIdentityKey({ tmdb_id: 949, title: 'Heat', year: '1995' }), 'tmdb:949');
  assert.equal(movieIdentityKey({ path: 'E:/Movies/Heat.mkv', title: 'Heat' }), 'path:e:/movies/heat.mkv');
  assert.equal(movieIdentityKey({ title: 'Alien³ Special Edition', year: '1992' }), 'title:alien 3|1992');
});

test('system list state updates immediately through the canonical movie key', () => {
  const michael = {
    movie_key: 'tmdb:936075',
    tmdb_id: '936075',
    title: 'Michael',
    year: '2026',
    path: 'E:/Movies/Michael.2026.mkv'
  };
  const lists = [
    { id: 'watched', system_type: 'watched', movies: [] },
    { id: 'watchlist', system_type: 'watchlist', movies: [] },
    { id: 'favorites', system_type: '', movies: [] }
  ];

  const watched = applySystemListState(lists, 'watched', michael, true);
  assert.equal(watched[0].movies.length, 1);
  assert.equal(watched[1].movies.length, 0);
  assert.equal(watched[2], lists[2]);

  const removed = applySystemListState(watched, 'watched', {
    ...michael,
    title: 'Different provider title'
  }, false);
  assert.equal(removed[0].movies.length, 0);

  const conflicting = applySystemListState(lists, 'watchlist', {
    ...michael,
    movie_key: 'tmdb:1'
  }, true);
  assert.equal(conflicting[1].movies[0].movie_key, 'tmdb:1');
});

test('collection and list filters preserve TMDB id and title-year matching', () => {
  const heatItem = {
    title: 'Heat (1995)',
    tmdb_id: 949,
    path: 'E:/Movies/Heat.mkv'
  };
  const alienItem = {
    canonical_metadata: { accepted: true, title: 'Alien³', year: 1992 },
    path: 'E:/Movies/Alien 3.mkv'
  };
  const lists = [
    { name: 'Favorites', movies: [{ tmdb_id: 949, title: 'Different Title', year: '1995' }] },
    { name: 'Sequels', movies: [{ title: 'Alien 3', year: '1992', path: 'E:/Movies/Alien 3.mkv' }] },
    { name: 'Other', movies: [{ title: 'Brazil', year: '1985' }] }
  ];

  assert.equal(
    itemMatchesCollectionFilter(heatItem, {}, { id: 10, parts: [{ tmdb_id: 949, title: 'Other' }] }),
    true
  );
  assert.equal(
    itemMatchesCollectionFilter(alienItem, {}, { id: 10, parts: [{ title: 'Alien 3', year: '1992' }] }),
    true
  );
  assert.equal(itemMatchesCollectionFilter(heatItem, { collection: { id: 10 } }, { id: '10', parts: [] }), true);
  assert.equal(itemMatchesCollectionFilter(heatItem, {}, { id: 10, parts: [{ title: 'Brazil', year: '1985' }] }), false);
  assert.deepEqual(listsForItem(heatItem, lists).map((list) => list.name), ['Favorites']);
  assert.deepEqual(listsForItem(alienItem, lists).map((list) => list.name), ['Sequels']);
});

test('resolved collection filters use backend-owned paths only', () => {
  const included = { path: 'E:/Movies/Star Wars.mkv', canonical_metadata: { accepted: true, title: 'Wrong', year: '2020' } };
  const excluded = { path: 'E:/Movies/The Last Jedi.mkv', canonical_metadata: { accepted: true, title: 'Star Wars: The Last Jedi', year: '2017' } };
  const filter = { id: '10', owned_paths: ['E:/Movies/Star Wars.mkv'] };

  assert.equal(itemMatchesCollectionFilter(included, {}, filter), true);
  assert.equal(itemMatchesCollectionFilter(excluded, {}, filter), false);
});

test('listsForItem matches saved list movies by path when TMDB ids are missing from library rows', () => {
  const libraryItem = {
    title: 'Full Metal Jacket (1987)',
    path: 'E:/Movies/Full Metal Jacket (1987)/Full.Metal.Jacket.mkv'
  };
  const lists = [
    {
      name: 'toty',
      movies: [
        {
          title: 'Full Metal Jacket',
          year: '1987',
          tmdb_id: '600',
          path: 'E:/Movies/Full Metal Jacket (1987)/Full.Metal.Jacket.mkv'
        }
      ]
    }
  ];

  assert.deepEqual(listsForItem(libraryItem, lists).map((list) => list.name), ['toty']);
});

test('listLibraryCoverage reports list movies missing from the current library', () => {
  const items = [
    {
      path: 'E:/Movies/Heat.mkv',
      canonical_metadata: { accepted: true, tmdb_id: '949', title: 'Heat', year: '1995' }
    },
    {
      title: 'Full Metal Jacket (1987)',
      path: 'E:/Movies/Full Metal Jacket.mkv'
    }
  ];
  const list = {
    name: 'toty',
    movies: [
      { tmdb_id: '949', title: 'Heat', year: '1995' },
      { tmdb_id: '77', title: 'Memento', year: '2000' },
      { title: 'Full Metal Jacket', year: '1987', path: 'E:/Movies/Full Metal Jacket.mkv' }
    ]
  };

  assert.deepEqual(listLibraryCoverage(items, list), {
    total: 3,
    matched: 2,
    missingCount: 1,
    missingMovies: [{ tmdb_id: '77', title: 'Memento', year: '2000' }]
  });
});

test('movieHasSystemState shares provider identity across duplicate paths', () => {
  const item = {
    path: 'F:/Movies/Alien-copy.mkv',
    canonical_metadata: { accepted: true, tmdb_id: '348', title: 'Alien', year: '1979' }
  };
  const lists = [{
    id: 'watched',
    system_type: 'watched',
    movies: [{ tmdb_id: '348', title: 'Alien', year: '1979', path: 'E:/Movies/Alien.mkv' }]
  }];

  assert.equal(movieHasSystemState(item, lists, 'watched'), true);
  assert.equal(movieHasSystemState(item, lists, 'watchlist'), false);
});

test('buildLibraryViewModel filters watched unwatched and watchlist states', () => {
  const alien = {
    path: 'E:/Movies/Alien.mkv',
    filename: 'Alien.mkv',
    canonical_metadata: { accepted: true, tmdb_id: '348', title: 'Alien', year: '1979' }
  };
  const heat = {
    path: 'E:/Movies/Heat.mkv',
    filename: 'Heat.mkv',
    canonical_metadata: { accepted: true, tmdb_id: '949', title: 'Heat', year: '1995' }
  };
  const lists = [
    { id: 'watched', system_type: 'watched', movies: [{ tmdb_id: '348', title: 'Alien', year: '1979' }] },
    { id: 'watchlist', system_type: 'watchlist', movies: [{ tmdb_id: '949', title: 'Heat', year: '1995' }] }
  ];
  const base = { items: [alien, heat], lists, pageSize: 40, mode: 'movie' };

  assert.deepEqual(buildLibraryViewModel({ ...base, viewingStateFilter: 'watched' }).filteredItems, [alien]);
  assert.deepEqual(buildLibraryViewModel({ ...base, viewingStateFilter: 'unwatched' }).filteredItems, [heat]);
  assert.deepEqual(buildLibraryViewModel({ ...base, viewingStateFilter: 'watchlist' }).filteredItems, [heat]);
});

test('buildLibraryViewModel preserves Library filtering sorting pagination and stats behavior', () => {
  const list = {
    name: 'Watch',
    movies: [{ title: 'Beta', year: '2001', path: 'E:/Movies/Beta.mkv' }]
  };
  const items = [
    {
      title: 'Alpha (2000)',
      filename: 'Alpha.mkv',
      path: 'E:/Movies/Alpha.mkv',
      resolution: '1080p',
      rip_source: 'Blu-ray',
      size: 7 * 1024 * 1024 * 1024,
      added_time: 10,
      canonical_metadata: { accepted: true, title: 'Alpha', year: '2000', genres: ['Drama'], rating: 8.5, language: 'English', country: 'US' },
      metadata_status: 'accepted',
      plex_matched: true
    },
    {
      title: 'Beta (2001)',
      filename: 'Beta.mkv',
      path: 'E:/Movies/Beta.mkv',
      resolution: '720p',
      rip_source: 'WEB-DL',
      size: 2 * 1024 * 1024 * 1024,
      added_time: 20,
      canonical_metadata: { accepted: true, title: 'Beta', year: '2001', genres: ['Action'], rating: 7.1, language: 'French', country: 'France' },
      metadata_status: 'accepted',
      maintenance_upgrade_candidate: true,
      plex_matched: true
    },
    {
      title: 'Gamma (2002)',
      filename: 'Gamma.mkv',
      path: 'E:/Movies/Gamma.mkv',
      resolution: '480p',
      rip_source: 'DVD',
      size: 1 * 1024 * 1024 * 1024,
      added_time: 30,
      canonical_metadata: { accepted: false },
      metadata_status: 'pending',
      plex_matched: false
    }
  ];

  const view = buildLibraryViewModel({
    items,
    pageSize: 1,
    currentPage: 2,
    query: '',
    qualityFilter: 'all',
    plexFilter: 'all',
    sortMode: 'year-asc',
    genreFilter: 'all',
    resolutionFilter: 'all',
    sourceFilter: 'all',
    languageFilter: 'all',
    countryFilter: 'all',
    yearFrom: '',
    yearTo: '',
    minRating: 'all',
    sizeFilter: 'all',
    mode: 'movie',
    roleFilter: null,
    collectionFilter: null,
    listFilter: null,
    tmdbCache: {},
    showAdultMovies: true
  });

  assert.deepEqual(view.filteredItems.map((item) => getMovieIdentity(item).title), ['Alpha', 'Beta']);
  assert.equal(view.totalPages, 2);
  assert.equal(view.safePage, 2);
  assert.equal(view.pageStart, 1);
  assert.equal(view.pageEnd, 2);
  assert.deepEqual(view.visibleItems.map((item) => getMovieIdentity(item).title), ['Beta']);
  assert.deepEqual(view.stats, { total: 3, low: 2, matched: 2, pending: 1, unmatched: 0 });

  const listView = buildLibraryViewModel({
    items,
    mode: 'movie',
    listFilter: list,
    sortMode: 'title',
    pageSize: 40,
    currentPage: 1
  });

  assert.deepEqual(listView.filteredItems.map((item) => getMovieIdentity(item).title), ['Beta']);

  const upgradeView = buildLibraryViewModel({
    items,
    mode: 'movie',
    qualityFilter: 'upgrade',
    pageSize: 40,
    currentPage: 1
  });
  assert.deepEqual(upgradeView.filteredItems.map((item) => getMovieIdentity(item).title), ['Beta']);
});
