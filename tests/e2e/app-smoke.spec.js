import { expect, test } from '@playwright/test';

const parityMovie = {
  tmdb_id: '42',
  imdb_id: 'tt0000042',
  title: 'Render Parity Movie',
  year: '2024',
  poster_url: '',
  tmdb_rating: '8.4',
  tmdb_vote_count: 120,
  genres: ['Drama'],
  plot: 'Stored SQL detail.'
};

const parityLibraryItem = {
  path: 'E:/Movies/Render.Parity.Movie.2024.mkv',
  filename: 'Render.Parity.Movie.2024.mkv',
  title: 'Render Parity Movie (2024)',
  resolution: '1080p',
  size: 100,
  size_human: '100 B',
  metadata_status: 'accepted',
  metadata_accepted: true,
  canonical_metadata: {
    projection_contract: 'canonical_movie_card',
    deferred_fields: ['backdrop_url', 'runtime', 'tagline', 'trailer_url', 'collection', 'cast', 'directors', 'director'],
    accepted: true,
    title: parityMovie.title,
    year: parityMovie.year,
    tmdb_id: parityMovie.tmdb_id,
    imdb_id: parityMovie.imdb_id,
    poster_url: parityMovie.poster_url,
    genres: parityMovie.genres,
    plot: parityMovie.plot,
    summary: parityMovie.plot,
    rating: parityMovie.tmdb_rating,
    tmdb_vote_count: parityMovie.tmdb_vote_count,
    detail_provider: 'tmdb_snapshot'
  }
};

const parityDeferredDetails = {
  ...parityLibraryItem,
  canonical_metadata: {
    ...parityLibraryItem.canonical_metadata,
    projection_contract: 'canonical_movie_details',
    deferred_fields: [],
    cast: [{ id: '1001', name: 'SQL Cast Member', character: 'Archivist' }],
    directors: [{ id: '1002', name: 'SQL Director' }],
    writers: [{ id: '1003', name: 'SQL Writer', job: 'Screenplay' }],
    keywords: ['catalogue', 'memory'],
    certification: 'PG-13',
    runtime: 118,
    collection: { id: '7001', name: 'SQL Collection' },
    trailer_url: 'https://www.youtube.com/watch?v=sql-parity'
  }
};

async function mockCardParityApis(page) {
  await page.route('**/api/library?view=cards*', async (route) => {
    await route.fulfill({ json: { items: [parityLibraryItem], count: 1, catalog_generation: 1 } });
  });
  await page.route('**/api/library/check', async (route) => {
    await route.fulfill({ json: {
      results: [{
        found: true,
        path: parityLibraryItem.path,
        resolution: parityLibraryItem.resolution,
        size_human: parityLibraryItem.size_human,
        tmdb_id: parityMovie.tmdb_id,
        imdb_id: parityMovie.imdb_id,
        title: parityMovie.title,
        year: parityMovie.year,
        canonical_card: parityLibraryItem,
        library_item: parityLibraryItem
      }]
      , catalog_generation: 1
    } });
  });
  await page.route('**/api/user/lists', async (route) => {
    await route.fulfill({ json: { lists: [{ id: 'render-parity', name: 'Render Parity', movies: [parityMovie] }], curation_generation: 1 } });
  });
  await page.route('**/api/tmdb/discover**', async (route) => {
    await route.fulfill({ json: { results: [parityMovie], page: 1, total_pages: 1, total_results: 1 } });
  });
}

const workspaces = [
  ['/', 'heading', 'Home'],
  ['/library', 'heading', 'Movie View'],
  ['/movie-lists', 'heading', 'Movie Lists'],
  ['/cleanup', 'heading', /^Library Maintenance/],
  ['/discover', 'heading', 'Discover'],
  ['/ai-control', 'heading', /^AI Control/],
  ['/iptv', 'heading', 'IPTV'],
  ['/downloads', 'region', 'Downloads powered by qBittorrent'],
  ['/help', 'heading', 'Help'],
  ['/settings', 'heading', 'Settings']
];

for (const [path, role, name] of workspaces) {
  test(`${path} renders without a workspace crash`, async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));

    const response = await page.goto(path, { waitUntil: 'domcontentloaded' });

    expect(response?.ok()).toBeTruthy();
    await expect(page.getByRole(role, { name, exact: typeof name === 'string' })).toBeVisible();
    await expect(page.locator('.app-crash-screen')).toHaveCount(0);
    expect(pageErrors).toEqual([]);
  });
}

test('Downloads shows qBittorrent without migration-only review records', async ({ page }) => {
  await page.goto('/downloads', { waitUntil: 'domcontentloaded' });

  await expect(page.getByTitle('qBittorrent Downloads')).toBeVisible();
  await expect(page.getByText('Legacy import audit')).toHaveCount(0);
  await expect(page.getByText('deferred completed imports')).toHaveCount(0);
});

test('Settings selects a free Ollama cloud model and tests that exact model', async ({ page }) => {
  let savedModel = '';
  let testedModel = '';

  await page.route('**/api/ollama/config', async (route) => {
    if (route.request().method() === 'POST') {
      savedModel = (await route.request().postDataJSON()).model;
      await route.fulfill({ json: { success: true } });
      return;
    }
    await route.fulfill({ json: {
      url: 'http://localhost:11434',
      model: 'gemma4:31b-cloud',
      candidate_limit: 20
    } });
  });
  await page.route('**/api/ollama/models', (route) => route.fulfill({ json: {
    configured_model: 'gemma4:31b-cloud',
    free_cloud_models: [
      { model: 'minimax-m3:cloud', description: 'Free cloud model', required_plan: 'free' },
      { model: 'nemotron-3-super:cloud', description: 'Free cloud model', required_plan: 'free' }
    ],
    local_models: [{ model: 'gemma3:12b', description: '12B' }],
    warnings: []
  } }));
  await page.route('**/api/ollama/test?*', async (route) => {
    testedModel = new URL(route.request().url()).searchParams.get('model') || '';
    await route.fulfill({ json: { success: true, model: testedModel, elapsed_ms: 1250 } });
  });

  await page.goto('/settings', { waitUntil: 'domcontentloaded' });

  const modelSelector = page.getByLabel('Ollama model');
  await expect(modelSelector).toHaveValue('gemma4:31b-cloud');
  await expect(modelSelector.locator('optgroup[label="Free cloud models"] option')).toHaveCount(2);
  await modelSelector.selectOption('minimax-m3:cloud');
  await page.getByRole('button', { name: 'Save Ollama' }).click();
  await expect.poll(() => savedModel).toBe('minimax-m3:cloud');

  await page.getByRole('button', { name: 'Test Model' }).click();
  await expect.poll(() => testedModel).toBe('minimax-m3:cloud');
  await expect(page.getByText('Ollama model answered correctly.')).toBeVisible();
  await expect(page.getByText('minimax-m3:cloud returned valid JSON in 1,250 ms.')).toBeVisible();

  await modelSelector.selectOption('__custom_ollama_model__');
  await page.getByLabel('Exact Ollama cloud model').fill('gemma4:31b-cloud');
  await page.getByRole('button', { name: 'Verify & use' }).click();
  await expect.poll(() => testedModel).toBe('gemma4:31b-cloud');
  await expect(modelSelector).toHaveValue('gemma4:31b-cloud');
  await expect(page.getByText('Cloud model verified and selected.')).toBeVisible();
  await page.getByRole('button', { name: 'Save Ollama' }).click();
  await expect.poll(() => savedModel).toBe('gemma4:31b-cloud');
});

test('Library switches between canonical movie and raw file views', async ({ page }) => {
  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Movie View' })).toBeVisible();

  await page.getByRole('button', { name: 'File View' }).click();
  await expect(page.getByRole('heading', { name: 'File View' })).toBeVisible();

  await page.getByRole('button', { name: 'Movie View' }).click();
  await expect(page.getByRole('heading', { name: 'Movie View' })).toBeVisible();
});

test('Library people search renders stored actors and writers from canonical metadata', async ({ page }) => {
  const profileUrl = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
  let writerFilterUrl = '';
  const peopleItem = {
    path: 'E:/Movies/Apollo.13.1995.mkv',
    canonical_metadata: {
      accepted: true,
      title: 'Apollo 13',
      year: '1995',
      cast: [{ id: '31', name: 'Tom Hanks', profile_url: profileUrl }],
      directors: [],
      writers: [{ id: '99', name: 'William Broyles Jr.', profile_url: profileUrl }]
    },
    plex_cast: [],
    plex_directors: []
  };
  await page.route('**/api/library?view=cards*', async (route) => {
    const url = route.request().url();
    if (new URL(url).searchParams.get('role') === 'writer') writerFilterUrl = url;
    await route.fulfill({ json: {
      items: [{
        path: peopleItem.path,
        canonical_metadata: { accepted: true, title: 'Apollo 13', year: '1995' }
      }],
      count: 1,
      catalog_generation: 1
    } });
  });
  await page.route('**/api/library?view=people*', async (route) => {
    await route.fulfill({ json: { items: [peopleItem], count: 1, catalog_generation: 1 } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Library search type').selectOption('people');
  await page.getByPlaceholder('Search people in your library...').fill('Tom Hanks');

  const card = page.locator('.person-search-card').filter({ hasText: 'Tom Hanks' });
  const portrait = card.getByRole('img', { name: 'Tom Hanks profile' });
  await expect(portrait).toBeVisible();
  await expect.poll(() => portrait.evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);

  await page.getByPlaceholder('Search people in your library...').fill('William Broyles');
  const writerCard = page.locator('.person-search-card').filter({ hasText: 'William Broyles Jr.' });
  await expect(writerCard).toBeVisible();
  const writerAction = writerCard.getByRole('button', { name: 'Written films' });
  await expect(writerAction).toBeVisible();
  await writerAction.click();
  await expect.poll(() => writerFilterUrl).not.toBe('');
  expect(new URL(writerFilterUrl).searchParams.get('person_id')).toBe('99');
});

test('existing actor and director People search remains available in Library and Discover', async ({ page }) => {
  const person = {
    id: '55',
    tmdb_id: '55',
    name: 'Parity Filmmaker',
    known_for_department: 'Directing',
    known_for: ['Parity Feature']
  };
  const peopleItem = {
    path: parityLibraryItem.path,
    canonical_metadata: {
      accepted: true,
      title: parityMovie.title,
      year: parityMovie.year,
      cast: [{ id: person.id, name: person.name }],
      directors: [{ id: person.id, name: person.name }],
      writers: [{ id: person.id, name: person.name, job: 'Writer' }]
    },
    plex_cast: [],
    plex_directors: []
  };
  let discoverWriterUrl = '';
  await page.route('**/api/library?view=cards*', (route) => route.fulfill({ json: {
    items: [parityLibraryItem],
    count: 1,
    total: 1,
    page: 1,
    total_pages: 1,
    catalog_generation: 1
  } }));
  await page.route('**/api/library?view=people*', (route) => route.fulfill({ json: {
    items: [peopleItem],
    count: 1,
    catalog_generation: 1
  } }));
  await page.route('**/api/tmdb/people/search**', (route) => route.fulfill({ json: {
    results: [person],
    page: 1,
    total_pages: 1,
    total_results: 1
  } }));
  await page.route('**/api/tmdb/person_movies**', (route) => {
    discoverWriterUrl = route.request().url();
    return route.fulfill({ json: {
      results: [parityMovie],
      page: 1,
      total_pages: 1,
      total_results: 1,
      role: 'writer',
      person_id: person.id
    } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Library search type').selectOption('people');
  await page.getByPlaceholder('Search people in your library...').fill(person.name);
  const libraryPerson = page.locator('.person-search-card').filter({ hasText: person.name });
  await expect(libraryPerson.getByRole('button', { name: 'Acting credits' })).toBeVisible();
  await expect(libraryPerson.getByRole('button', { name: 'Directed films' })).toBeVisible();
  await expect(libraryPerson.getByRole('button', { name: 'Written films' })).toBeVisible();

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('TMDB search type').selectOption('people');
  await page.getByLabel('Search TMDB people').fill(person.name);
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  const discoverPerson = page.locator('.person-search-card').filter({ hasText: person.name });
  await expect(discoverPerson.getByRole('button', { name: 'Acting credits' })).toBeVisible();
  await expect(discoverPerson.getByRole('button', { name: 'Directed films' })).toBeVisible();
  const discoverWriterAction = discoverPerson.getByRole('button', { name: 'Written films' });
  await expect(discoverWriterAction).toBeVisible();
  await discoverWriterAction.click();
  await expect.poll(() => discoverWriterUrl).not.toBe('');
  expect(new URL(discoverWriterUrl).searchParams.get('role')).toBe('writer');
});

test('Library Keywords resolves a stored identity and filters owned SQL movies', async ({ page }) => {
  const keywordMovie = {
    ...parityLibraryItem,
    path: 'E:/Movies/Space.Archive.2024.mkv',
    canonical_metadata: {
      ...parityLibraryItem.canonical_metadata,
      title: 'Space Archive',
      year: '2024',
      tmdb_id: '5010'
    }
  };
  let selectedKeywordUrl = '';

  await page.route('**/api/library?view=keywords*', (route) => route.fulfill({ json: {
    items: [{ keyword_key: 'tmdb:501', tmdb_id: '501', name: 'space opera', normalized_name: 'space opera', movie_count: 1 }],
    count: 1,
    source: 'catalog',
    catalog_generation: 1
  } }));
  await page.route('**/api/library?view=cards*', (route) => {
    const url = route.request().url();
    const selectedKeyword = new URL(url).searchParams.get('keyword_id');
    if (selectedKeyword === '501') {
      selectedKeywordUrl = url;
      return route.fulfill({ json: {
        items: [keywordMovie],
        count: 1,
        total: 1,
        page: 1,
        total_pages: 1,
        page_start: 1,
        page_end: 1,
        catalog_generation: 1
      } });
    }
    return route.fulfill({ json: {
      items: [parityLibraryItem],
      count: 1,
      total: 1,
      page: 1,
      total_pages: 1,
      page_start: 1,
      page_end: 1,
      catalog_generation: 1
    } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Library search type').selectOption('keywords');
  await page.getByPlaceholder('Search keywords in your library...').fill('space');

  const keywordCard = page.locator('.keyword-search-card').filter({ hasText: 'space opera' });
  await expect(keywordCard).toContainText('1 owned movie');
  await keywordCard.getByRole('button', { name: 'View owned movies' }).click();

  await expect(page.getByLabel('Library search type')).toHaveValue('movies');
  await expect(page.getByText('Space Archive', { exact: true })).toBeVisible();
  await expect(page.locator('.metadata-filter-chip')).toContainText('Keyword: space opera');
  expect(new URL(selectedKeywordUrl).searchParams.get('keyword_id')).toBe('501');
});

test('Library Keywords ignores an older in-flight SQL suggestion response', async ({ page }) => {
  let releaseSlowSearch;
  let slowSearchStarted = false;
  const slowSearchGate = new Promise((resolve) => {
    releaseSlowSearch = resolve;
  });

  await page.route('**/api/library?view=cards*', (route) => route.fulfill({ json: {
    items: [],
    count: 0,
    total: 0,
    page: 1,
    total_pages: 1,
    page_start: 0,
    page_end: 0,
    catalog_generation: 1
  } }));
  await page.route('**/api/library?view=keywords*', async (route) => {
    const query = new URL(route.request().url()).searchParams.get('q');
    if (query === 'slow') {
      slowSearchStarted = true;
      await slowSearchGate;
      await route.fulfill({ json: {
        items: [{ keyword_key: 'tmdb:1', tmdb_id: '1', name: 'slow keyword', movie_count: 1 }],
        count: 1,
        catalog_generation: 1
      } });
      return;
    }
    await route.fulfill({ json: {
      items: [{ keyword_key: 'tmdb:2', tmdb_id: '2', name: 'current keyword', movie_count: 1 }],
      count: 1,
      catalog_generation: 1
    } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Library search type').selectOption('keywords');
  const keywordInput = page.getByLabel('Search keywords in your library');
  await keywordInput.fill('slow');
  await expect.poll(() => slowSearchStarted).toBe(true);

  await keywordInput.fill('current');
  await expect(page.locator('.keyword-search-card').filter({ hasText: 'current keyword' })).toBeVisible();
  releaseSlowSearch();
  await expect(page.locator('.keyword-search-card').filter({ hasText: 'slow keyword' })).toHaveCount(0);
});

test('Discover Keywords keeps TMDB identity, ownership attachment, and back navigation', async ({ page }) => {
  const keywordMovie = {
    tmdb_id: '8801',
    title: 'Remote Space Archive',
    year: '2024',
    poster_url: '',
    genres: ['Science Fiction'],
    tmdb_rating: '7.8',
    tmdb_vote_count: 900,
    plot: 'A remote keyword result.'
  };
  let selectedKeywordUrl = '';

  await page.route('**/api/tmdb/keywords/search**', (route) => route.fulfill({ json: {
    results: [{ tmdb_id: '501', name: 'space opera' }],
    page: 1,
    total_pages: 1,
    total_results: 1
  } }));
  await page.route('**/api/tmdb/discover**', (route) => {
    const url = route.request().url();
    if (new URL(url).searchParams.get('keyword_id') === '501') {
      selectedKeywordUrl = url;
      return route.fulfill({ json: {
        results: [keywordMovie],
        keyword: { tmdb_id: '501', name: 'space opera' },
        page: 1,
        total_pages: 1,
        total_results: 1
      } });
    }
    return route.fulfill({ json: { results: [], page: 1, total_pages: 1, total_results: 0 } });
  });
  await page.route('**/api/library/check', async (route) => route.fulfill({ json: {
    results: [{
      found: true,
      path: 'E:/Movies/Remote.Space.Archive.2024.mkv',
      resolution: '1080p',
      size_human: '4 GB',
      tmdb_id: keywordMovie.tmdb_id,
      title: keywordMovie.title,
      year: keywordMovie.year,
      canonical_card: {
        path: 'E:/Movies/Remote.Space.Archive.2024.mkv',
        canonical_metadata: { accepted: true, ...keywordMovie }
      }
    }],
    catalog_generation: 1
  } }));

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('TMDB search type').selectOption('keywords');
  await page.getByLabel('Search TMDB keywords').fill('space');
  await page.getByRole('button', { name: 'Search', exact: true }).click();

  const keywordCard = page.locator('.keyword-search-card').filter({ hasText: 'space opera' });
  await expect(keywordCard).toBeVisible();
  await keywordCard.getByRole('button', { name: 'Discover movies' }).click();

  await expect(page.getByText('Remote Space Archive', { exact: true })).toBeVisible();
  await expect(page.locator('.unified-owned-badge').filter({ hasText: 'Owned' })).toBeVisible();
  expect(new URL(selectedKeywordUrl).searchParams.get('keyword_id')).toBe('501');

  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByLabel('TMDB search type')).toHaveValue('keywords');
  await expect(page.locator('.keyword-search-card').filter({ hasText: 'space opera' })).toBeVisible();
});

test('Discover Keywords ignores a stale TMDB keyword response', async ({ page }) => {
  let releaseSlowSearch;
  let slowSearchStarted = false;
  const slowSearchGate = new Promise((resolve) => {
    releaseSlowSearch = resolve;
  });

  await page.route('**/api/tmdb/keywords/search**', async (route) => {
    const query = new URL(route.request().url()).searchParams.get('q');
    if (query === 'slow') {
      slowSearchStarted = true;
      await slowSearchGate;
      await route.fulfill({ json: {
        results: [{ tmdb_id: '1', name: 'slow keyword' }],
        page: 1,
        total_pages: 1,
        total_results: 1
      } });
      return;
    }
    await route.fulfill({ json: {
      results: [{ tmdb_id: '2', name: 'current keyword' }],
      page: 1,
      total_pages: 1,
      total_results: 1
    } });
  });

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('TMDB search type').selectOption('keywords');
  const keywordInput = page.getByLabel('Search TMDB keywords');
  await keywordInput.fill('slow');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect.poll(() => slowSearchStarted).toBe(true);

  await keywordInput.fill('current');
  await page.locator('form.discover-search-panel').evaluate((form) => form.requestSubmit());
  await expect(page.locator('.keyword-search-card').filter({ hasText: 'current keyword' })).toBeVisible();
  releaseSlowSearch();
  await expect(page.locator('.keyword-search-card').filter({ hasText: 'slow keyword' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled();
});

test('Keyword modes surface their authoritative SQL and TMDB errors', async ({ page }) => {
  await page.route('**/api/library?view=keywords*', (route) => route.fulfill({
    status: 500,
    json: { error: 'Stored keyword lookup failed.' }
  }));
  await page.route('**/api/tmdb/keywords/search**', (route) => route.fulfill({
    status: 502,
    json: { error: 'TMDB keyword lookup failed.' }
  }));

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Library search type').selectOption('keywords');
  await expect(page.getByText('Search keywords in your library.')).toBeVisible();
  await page.getByLabel('Search keywords in your library').fill('broken');
  await expect(page.getByText('Could not search stored keywords.')).toBeVisible();
  await expect(page.getByText('Stored keyword lookup failed.')).toBeVisible();

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('TMDB search type').selectOption('keywords');
  await expect(page.getByText('Search TMDB keywords by name.')).toBeVisible();
  await page.getByLabel('Search TMDB keywords').fill('broken');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText('Could not search TMDB keywords.')).toBeVisible();
  await expect(page.getByText('TMDB keyword lookup failed.')).toBeVisible();
});

test('Discover People search ignores a stale response and clears its loading state', async ({ page }) => {
  let releaseSlowSearch;
  let slowSearchStarted = false;
  const slowSearchGate = new Promise((resolve) => {
    releaseSlowSearch = resolve;
  });

  await page.route('**/api/tmdb/people/search**', async (route) => {
    const query = new URL(route.request().url()).searchParams.get('q');
    if (query === 'Slow Person') {
      slowSearchStarted = true;
      await slowSearchGate;
      await route.fulfill({ json: {
        results: [{ tmdb_id: '701', name: 'Slow Person', known_for_department: 'Acting', known_for: [] }],
        page: 1,
        total_pages: 1,
        total_results: 1
      } });
      return;
    }
    await route.fulfill({ json: {
      results: [{ tmdb_id: '702', name: 'Current Person', known_for_department: 'Writing', known_for: [] }],
      page: 1,
      total_pages: 1,
      total_results: 1
    } });
  });

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('TMDB search type').selectOption('people');
  const searchInput = page.getByLabel('Search TMDB people');
  await searchInput.fill('Slow Person');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect.poll(() => slowSearchStarted).toBe(true);

  await searchInput.fill('Current Person');
  await page.locator('form.discover-search-panel').evaluate((form) => form.requestSubmit());
  await expect(page.locator('.person-search-card').filter({ hasText: 'Current Person' })).toBeVisible();

  releaseSlowSearch();
  await expect(page.locator('.person-search-card').filter({ hasText: 'Slow Person' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Search', exact: true })).toBeEnabled();
});

test('Library credit clicks load the people projection before filtering owned work', async ({ page }) => {
  const cards = [
    {
      path: 'E:/Movies/Awakenings.1990.mkv',
      title: 'Awakenings (1990)',
      resolution: '1080p',
      canonical_metadata: { accepted: true, title: 'Awakenings', year: '1990', plot: 'First plot.' }
    },
    {
      path: 'E:/Movies/Heat.1995.mkv',
      title: 'Heat (1995)',
      resolution: '1080p',
      canonical_metadata: { accepted: true, title: 'Heat', year: '1995', plot: 'Second plot.' }
    }
  ];
  const person = { id: '380', name: 'Robert De Niro', character: 'Lead' };
  await page.route('**/api/library?view=cards*', (route) => route.fulfill({ json: { items: cards, count: 2, total: 2, page: 1, total_pages: 1, catalog_generation: 1 } }));
  await page.route('**/api/library?view=people*', (route) => route.fulfill({ json: {
    items: cards.map((item) => ({
      path: item.path,
      canonical_metadata: {
        accepted: item.canonical_metadata.accepted,
        title: item.canonical_metadata.title,
        year: item.canonical_metadata.year,
        cast: [person],
        directors: []
      },
      plex_cast: [],
      plex_directors: []
    })),
    count: 2,
    catalog_generation: 1
  } }));
  await page.route('**/api/library/details**', (route) => route.fulfill({ json: {
    item: { ...cards[0], canonical_metadata: { ...cards[0].canonical_metadata, cast: [person], directors: [] } },
    catalog_generation: 1
  } }));

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  const awakenings = page.locator('.library-movie-card').filter({ hasText: 'Awakenings' });
  await awakenings.click();
  await expect(awakenings).toHaveClass(/library-movie-card-expanded/);
  await expect(page.getByText('Robert De Niro', { exact: true }).first()).toBeVisible();
  await page.waitForTimeout(250);
  await page.getByText('Robert De Niro', { exact: true }).first().click({ force: true });

  await expect(page.locator('.library-movie-card')).toHaveCount(2);
  await expect(page.getByText('Actor: Robert De Niro', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Maintenance', exact: true }).click();
  await page.getByRole('button', { name: /Upgrade candidates/ }).click();

  await expect(page).toHaveURL(/\/library$/);
  await expect(page.getByText('Actor: Robert De Niro', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Open Filters' }).click();
  await expect(page.getByLabel('Library quality filter')).toHaveValue('upgrade');
});

test('Library server paging, filtered selection, and navigation preserve exact result state', async ({ page }) => {
  const makeItem = (label, index) => ({
    path: `E:/Movies/${label}.${index}.mkv`,
    title: `${label} (${2020 + index})`,
    resolution: '1080p',
    canonical_metadata: { accepted: true, title: label, year: String(2020 + index), plot: `${label} plot.` }
  });
  const requests = [];
  await page.route('**/api/library?view=cards*', (route) => {
    const url = new URL(route.request().url());
    const pageNumber = Number(url.searchParams.get('page') || 1);
    const query = url.searchParams.get('q') || '';
    requests.push({ page: pageNumber, query });
    const filtered = query === 'Needle';
    const items = [makeItem(filtered ? 'Needle Result' : `Server Page ${pageNumber}`, pageNumber)];
    return route.fulfill({ json: {
      items, count: filtered ? 1 : 81, total: filtered ? 1 : 81,
      page: filtered ? 1 : pageNumber, total_pages: filtered ? 1 : 3,
      page_start: filtered ? 0 : (pageNumber - 1) * 40,
      page_end: filtered ? 1 : Math.min(pageNumber * 40, 81),
      facets: { genres: [], sources: [], languages: [], countries: [] },
      stats: { total: 81, low: 0, matched: 81, pending: 0, unmatched: 0 },
      catalog_generation: 1
    } });
  });
  await page.route('**/api/library/selection', async (route) => {
    const body = route.request().postDataJSON();
    expect(body.filters.query).toBe('');
    await route.fulfill({ json: { paths: Array.from({ length: 81 }, (_, index) => `path-${index}`), count: 81 } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('Page 1 of 3', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Select all filtered', exact: true }).click();
  await expect(page.getByText('81 selected', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).first().click();
  await expect(page.getByText('Server Page 2', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Discover', exact: true }).click();
  await page.getByRole('button', { name: 'Library', exact: true }).click();
  await expect(page.getByText('Page 2 of 3', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('Server Page 2', { exact: true })).toBeVisible();

  await page.getByPlaceholder('Search your offline library...').fill('Needle');
  await expect(page.getByText('Needle Result', { exact: true })).toBeVisible();
  await expect(page.locator('.library-movie-card')).toHaveCount(1);
  expect(requests.some((entry) => entry.page === 2 && entry.query === '')).toBeTruthy();
  expect(requests.some((entry) => entry.page === 1 && entry.query === 'Needle')).toBeTruthy();
});

test('owned Library posters render from immutable local assets without detail providers', async ({ page }) => {
  let providerDetailCalls = 0;
  const localPosterUrl = '/api/assets/e2e-local-poster';
  const localPoster = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    'base64'
  );
  const localPosterItem = {
    ...parityLibraryItem,
    canonical_metadata: {
      ...parityLibraryItem.canonical_metadata,
      poster_url: localPosterUrl
    }
  };
  await page.route('**/api/library?view=cards*', (route) => route.fulfill({ json: {
    items: [localPosterItem],
    count: 1,
    total: 1,
    page: 1,
    total_pages: 1,
    catalog_generation: 1
  } }));
  await page.route('**/api/library/details**', (route) => route.fulfill({ json: {
    item: {
      ...localPosterItem,
      canonical_metadata: {
        ...localPosterItem.canonical_metadata,
        projection_contract: 'canonical_movie_details',
        deferred_fields: [],
        cast: [],
        directors: []
      }
    },
    catalog_generation: 1
  } }));
  await page.route('**/api/assets/e2e-local-poster', (route) => route.fulfill({
    status: 200,
    contentType: 'image/png',
    headers: { 'Cache-Control': 'public, max-age=31536000, immutable' },
    body: localPoster
  }));
  await page.route('**/api/tmdb/details**', (route) => {
    providerDetailCalls += 1;
    return route.abort();
  });
  const assetResponse = page.waitForResponse((response) => response.url().endsWith(localPosterUrl));
  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  const response = await assetResponse;
  const poster = page.locator('.library-movie-card img[src^="/api/assets/"]').first();
  await expect(poster).toBeVisible();
  await expect.poll(() => poster.evaluate((image) => image.naturalWidth)).toBeGreaterThan(0);
  expect(response.ok()).toBeTruthy();
  expect(response.headers()['cache-control']).toContain('immutable');
  await page.waitForTimeout(750);
  providerDetailCalls = 0;
  const card = poster.locator('xpath=ancestor::article[contains(@class,"library-movie-card")]');
  await card.click();
  await expect(card).toHaveClass(/library-movie-card-expanded/);
  await page.waitForTimeout(500);
  expect(providerDetailCalls).toBe(0);
});

test('Discover unowned cards keep remote actions and do not acquire an ownership badge', async ({ page }) => {
  const remoteMovie = {
    tmdb_id: '84',
    imdb_id: 'tt0000084',
    title: 'Remote Parity Movie',
    year: '2025',
    poster_url: '',
    tmdb_rating: '7.1',
    tmdb_vote_count: 84,
    genres: ['Mystery'],
    plot: 'Remote provider detail.'
  };
  await page.route('**/api/tmdb/discover**', (route) => route.fulfill({ json: {
    results: [remoteMovie],
    page: 1,
    total_pages: 1,
    total_results: 1
  } }));
  await page.route('**/api/library/check', (route) => route.fulfill({ json: {
    results: [{ found: false, tmdb_id: remoteMovie.tmdb_id }],
    catalog_generation: 1
  } }));
  await page.route('**/api/tmdb/details**', (route) => route.fulfill({ json: {
    ...remoteMovie,
    summary: remoteMovie.plot,
    cast: [],
    directors: [],
    writers: [],
    keywords: []
  } }));

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  const card = page.locator('.discover-movie-card').filter({ hasText: remoteMovie.title });
  await expect(card.getByText('Owned', { exact: true })).toHaveCount(0);
  await expect(card).toContainText('Not in library');
  await card.click();
  await expect(card.getByRole('button', { name: 'Find sources', exact: true })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Follow', exact: true })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Play', exact: true })).toHaveCount(0);
});

test('Maintenance tabs remain interactive after the audit loads', async ({ page }) => {
  await page.goto('/cleanup', { waitUntil: 'domcontentloaded' });
  const storage = page.getByRole('tab', { name: 'Storage' });
  const identity = page.getByRole('tab', { name: 'Identity' });

  await expect(storage).toHaveAttribute('aria-selected', 'true');
  await identity.click();
  await expect(identity).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('.app-crash-screen')).toHaveCount(0);
});

test('Duplicate cleanup confirms and submits the complete safe movie folder', async ({ page }) => {
  const candidatePath = 'E:\\Movies\\Project Hail Mary (2026) [720p]\\Project.Hail.Mary.2026.720p.mkv';
  const keepPath = 'E:\\Movies\\Project Hail Mary (2026) [1080p]\\Project.Hail.Mary.2026.1080p.mkv';
  const folderTarget = 'E:\\Movies\\Project Hail Mary (2026) [720p]';
  let executedRequest = null;

  await page.route('**/api/maintenance/audit?*', async (route) => {
    await route.fulfill({ json: {
      summary: {
        duplicate_groups: 1,
        extra_copies: 1,
        reclaimable_human: '2.0 GB',
        unmatched_files: 0,
        upgrade_candidates: 0,
      },
      storage: {
        groups: [{
          title: 'Project Hail Mary (2026)',
          recommended_count: 1,
          files: [
            { path: keepPath, filename: 'Project.Hail.Mary.2026.1080p.mkv', role: 'keep', recommendation: 'keep', resolution: '1080p', size_human: '4.0 GB' },
            { path: candidatePath, filename: 'Project.Hail.Mary.2026.720p.mkv', role: 'candidate', recommendation: 'recommended', resolution: '720p', size_human: '2.0 GB' },
          ]
        }],
        pagination: { total: 1, page: 1, total_pages: 1, page_start: 1, page_end: 1 }
      },
      identity: { items: [], pagination: { total: 0, page: 1, total_pages: 1 } }
    } });
  });
  await page.route('**/api/delete', async (route) => {
    const body = await route.request().postDataJSON();
    if (body.preview) {
      await route.fulfill({ json: {
        paths: [candidatePath],
        folder_count: 1,
        file_count: 0,
        actions: [{
          target_type: 'folder',
          target: folderTarget,
          folder: folderTarget,
          paths: [candidatePath],
          sidecar_count: 4,
        }]
      } });
      return;
    }
    executedRequest = body;
    await route.fulfill({ json: {
      success: true,
      deleted_paths: [candidatePath],
      folder_count: 1,
      file_count: 0,
      actions: [],
      failures: [],
      trashed: true,
    } });
  });

  await page.goto('/cleanup', { waitUntil: 'domcontentloaded' });
  const candidateRow = page.locator('.cleanup-file-row').filter({ hasText: 'Project.Hail.Mary.2026.720p.mkv' });
  await candidateRow.getByRole('button', { name: 'Delete' }).click();

  const dialog = page.getByRole('dialog', { name: /Move Project\.Hail\.Mary\.2026\.720p\.mkv to Recycle Bin/ });
  await expect(dialog).toContainText('1 complete movie folder will move to the Recycle Bin');
  await expect(dialog).toContainText('including 4 sidecar files');
  await expect(dialog).toContainText(folderTarget);
  await dialog.getByRole('button', { name: 'Move to Recycle Bin' }).click();

  await expect.poll(() => executedRequest).not.toBeNull();
  expect(executedRequest.paths).toEqual([candidatePath]);
  expect(executedRequest.folder_targets).toEqual([folderTarget]);
  await expect(page.getByText('1 movie file moved to Recycle Bin, including 1 complete folder')).toBeVisible();
});

test('Maintenance upgrade summary opens the authoritative Library filter', async ({ page }) => {
  const upgradeItem = {
    ...parityLibraryItem,
    resolution: '720p',
    maintenance_upgrade_candidate: true,
    canonical_metadata: {
      ...parityLibraryItem.canonical_metadata,
      title: 'Upgrade Fixture'
    }
  };
  await page.route('**/api/maintenance/audit?*', (route) => route.fulfill({ json: {
    summary: {
      duplicate_groups: 0,
      extra_copies: 0,
      reclaimable_human: '0 B',
      unmatched_files: 0,
      upgrade_candidates: 1
    },
    storage: {
      groups: [],
      pagination: { total: 0, page: 1, total_pages: 1, page_start: 0, page_end: 0 }
    },
    identity: { items: [], pagination: { total: 0, page: 1, total_pages: 1 } }
  } }));
  await page.route('**/api/library?view=cards*', (route) => route.fulfill({ json: {
    items: [upgradeItem],
    count: 1,
    total: 1,
    page: 1,
    total_pages: 1,
    facets: { genres: [], sources: [], languages: [], countries: [] },
    stats: { total: 1, low: 1, matched: 1, pending: 0, unmatched: 0 },
    catalog_generation: 1
  } }));
  await page.goto('/cleanup', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Upgrade candidates/ }).click();

  await expect(page).toHaveURL(/\/library$/);
  await expect(page.getByRole('heading', { name: 'Movie View' })).toBeVisible();
  await page.getByRole('button', { name: 'Open Filters' }).click();
  await expect(page.getByLabel('Library quality filter')).toHaveValue('upgrade');
  await expect(page.getByText('Upgrade candidate', { exact: true }).first()).toBeVisible();

  await page.getByLabel('Library quality filter').selectOption('all');
  await page.getByRole('button', { name: 'Discover', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Discover', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Library', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Movie View', exact: true })).toBeVisible();
  await expect(page.getByLabel('Library quality filter')).toHaveValue('all');
});

test('every stateful workspace preserves its page state after sidebar navigation', async ({ page }) => {
  await mockCardParityApis(page);
  await page.route('**/api/iptv/status', (route) => route.fulfill({ json: {
    configured: true,
    generation: 1,
    counts: { live: 0, movie: 0, series: 0 },
    sync: { state: 'idle' }
  } }));
  await page.route('**/api/iptv/recent**', (route) => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/iptv/categories**', (route) => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/iptv/items**', (route) => route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 30 } }));

  const openSection = (name) => page.getByRole('button', { name: name === 'AI Control' ? /AI Control/ : name, exact: name !== 'AI Control' }).click();

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Open Filters' }).click();
  await page.getByLabel('Library quality filter').selectOption('upgrade');

  await openSection('Discover');
  await page.getByLabel('Library ownership').selectOption('owned');

  await openSection('Movie Lists');
  await page.getByPlaceholder('Search the selected list...').fill('parity list state');

  await openSection('Maintenance');
  await page.getByRole('tab', { name: 'Identity' }).click();
  await page.getByPlaceholder('Search files, paths, or catalog titles...').fill('identity state');
  await page.locator('.workspace-panel:visible').evaluate((panel) => panel.style.minHeight = '1800px');
  const maintenanceScrollTop = await page.locator('main.workspace').evaluate((workspace) => {
    workspace.scrollTop = Math.min(300, Math.max(0, workspace.scrollHeight - workspace.clientHeight));
    return workspace.scrollTop;
  });
  expect(maintenanceScrollTop).toBeGreaterThan(0);

  await openSection('AI Control');
  await page.getByPlaceholder('Tell CP what to find, list, download, or delete...').fill('show my horror films');

  await openSection('IPTV');
  await page.getByRole('button', { name: 'Movies', exact: true }).click();
  await page.getByPlaceholder('Search movie...').fill('matrix');

  await openSection('Settings');
  await page.getByLabel('Button label').fill('Temporary state');

  await openSection('Downloads');
  const downloadsFrame = page.getByTitle('qBittorrent Downloads');
  await downloadsFrame.evaluate((frame) => frame.dataset.stateToken = 'preserved');

  await openSection('Library');
  await expect(page.getByLabel('Library quality filter')).toHaveValue('upgrade');
  await openSection('Discover');
  await expect(page.getByLabel('Library ownership')).toHaveValue('owned');
  await openSection('Movie Lists');
  await expect(page.getByPlaceholder('Search the selected list...')).toHaveValue('parity list state');
  await openSection('Maintenance');
  await expect(page.getByRole('tab', { name: 'Identity' })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByPlaceholder('Search files, paths, or catalog titles...')).toHaveValue('identity state');
  await expect.poll(() => page.locator('main.workspace').evaluate((workspace) => workspace.scrollTop)).toBe(maintenanceScrollTop);
  await openSection('AI Control');
  await expect(page.getByPlaceholder('Tell CP what to find, list, download, or delete...')).toHaveValue('show my horror films');
  await openSection('IPTV');
  await expect(page.getByRole('button', { name: 'Movies', exact: true })).toHaveClass(/is-active/);
  await expect(page.getByPlaceholder('Search movie...')).toHaveValue('matrix');
  await openSection('Settings');
  await expect(page.getByLabel('Button label')).toHaveValue('Temporary state');
  await openSection('Downloads');
  await expect(downloadsFrame).toHaveAttribute('data-state-token', 'preserved');
});

test('Library, Discover-owned, and Movie List cards render one canonical movie contract', async ({ page }) => {
  await mockCardParityApis(page);
  let tmdbDetailsRequests = 0;
  let localizedDetailsRequests = 0;
  let libraryDetailsRequests = 0;
  await page.route('**/api/library/details**', async (route) => {
    libraryDetailsRequests += 1;
    await route.fulfill({ json: { item: parityDeferredDetails, catalog_generation: 1 } });
  });
  await page.route('**/api/tmdb/details**', async (route) => {
    const requestUrl = new URL(route.request().url());
    if (requestUrl.searchParams.get('language') === 'ar-SA') {
      localizedDetailsRequests += 1;
      await route.fulfill({ json: {
        tmdb_id: parityMovie.tmdb_id,
        imdb_id: parityMovie.imdb_id,
        title: 'فيلم تكافؤ العرض',
        year: parityMovie.year,
        plot: 'حبكة عربية مؤقتة.',
        summary: 'حبكة عربية مؤقتة.',
        genres: ['دراما'],
        certification: 'PG-13',
        writers: [{ id: '1003', name: 'كاتب SQL', job: 'Screenplay' }],
        keywords: ['فهرس', 'ذاكرة'],
        cast: [{ id: '1001', name: 'ممثل SQL', character: 'أمين الأرشيف' }],
        directors: [{ id: '1002', name: 'مخرج SQL' }],
        collection: { id: '7001', name: 'مجموعة SQL' }
      } });
      return;
    }
    if (requestUrl.searchParams.get('tmdb_id') === parityMovie.tmdb_id) tmdbDetailsRequests += 1;
    await route.fulfill({ status: 503, json: { error: 'TMDB unavailable' } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  const libraryCard = page.locator('.library-movie-card').first();
  await expect(libraryCard.getByRole('heading', { name: parityMovie.title })).toBeVisible();
  await expect(libraryCard).toContainText(parityMovie.year);
  const libraryRequestsBeforeExpand = tmdbDetailsRequests;
  await libraryCard.click();
  await expect(libraryCard).toContainText(parityMovie.plot);
  await expect(libraryCard).toContainText('SQL Director');
  await expect(libraryCard).toContainText('SQL Cast Member');
  await expect(libraryCard).toContainText('SQL Collection');
  await expect(libraryCard).toContainText('SQL Writer');
  await expect(libraryCard).toContainText('catalogue');
  await expect(libraryCard).toContainText('PG-13');
  await expect(libraryCard.getByRole('link', { name: `Open ${parityMovie.title} on IMDb` })).toHaveAttribute(
    'href',
    `https://www.imdb.com/title/${parityMovie.imdb_id}/`
  );
  await expect(libraryCard.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await expect(libraryCard.getByRole('button', { name: 'Follow', exact: true })).toHaveCount(0);
  expect(tmdbDetailsRequests).toBe(libraryRequestsBeforeExpand);
  await libraryCard.locator('.movie-language-toggle').click();
  await expect(libraryCard).toContainText('حبكة عربية مؤقتة.');
  await expect(libraryCard.locator('.library-summary')).toHaveAttribute('dir', 'rtl');
  expect(localizedDetailsRequests).toBe(1);
  expect(tmdbDetailsRequests).toBe(libraryRequestsBeforeExpand);
  await libraryCard.locator('.movie-language-toggle').click();
  await expect(libraryCard).toContainText(parityMovie.plot);
  await libraryCard.getByRole('heading', { name: parityMovie.title }).click();
  await expect(libraryCard).not.toHaveClass(/library-movie-card-expanded/);
  await libraryCard.getByRole('heading', { name: parityMovie.title }).click();
  await expect(libraryCard).toHaveClass(/library-movie-card-expanded/);
  await expect(libraryCard).toContainText(parityMovie.plot);
  await expect(libraryCard).toContainText('SQL Cast Member');
  expect(tmdbDetailsRequests).toBe(libraryRequestsBeforeExpand);

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  const discoverCard = page.locator('.discover-movie-card').filter({ hasText: parityMovie.title });
  await expect(discoverCard.getByRole('heading', { name: parityMovie.title })).toBeVisible();
  await expect(discoverCard).toContainText(parityMovie.year);
  await expect(discoverCard.getByText('Owned', { exact: true })).toBeVisible();
  const discoverRequestsBeforeExpand = tmdbDetailsRequests;
  await discoverCard.click();
  await expect(discoverCard).toContainText(parityMovie.plot);
  await expect(discoverCard).toContainText('SQL Director');
  await expect(discoverCard).toContainText('SQL Cast Member');
  await expect(discoverCard).toContainText('SQL Collection');
  await expect(discoverCard.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await expect(discoverCard.getByRole('button', { name: 'Follow', exact: true })).toHaveCount(0);
  expect(tmdbDetailsRequests).toBe(discoverRequestsBeforeExpand);

  await page.goto('/movie-lists', { waitUntil: 'domcontentloaded' });
  const listCard = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await expect(listCard.getByRole('heading', { name: parityMovie.title })).toBeVisible();
  await expect(listCard).toContainText(parityMovie.year);
  const listRequestsBeforeExpand = tmdbDetailsRequests;
  await listCard.click();
  await expect(listCard).toContainText(parityMovie.plot);
  await expect(listCard).toContainText('SQL Director');
  await expect(listCard).toContainText('SQL Cast Member');
  await expect(listCard).toContainText('SQL Collection');
  await expect(listCard.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await expect(listCard.getByRole('button', { name: 'Follow', exact: true })).toHaveCount(0);
  expect(tmdbDetailsRequests).toBe(listRequestsBeforeExpand);

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.inspector')).toContainText(parityMovie.plot);
  await expect(page.locator('.inspector')).toContainText('SQL Cast Member');

  await page.route('**/api/ai-control/preview', async (route) => {
    await route.fulfill({ json: {
      state: 'valid_plan',
      plan_id: 'sql-parity-plan',
      action: 'find',
      summary: 'SQL parity plan',
      message: 'One owned result',
      total_matches: 1,
      items: [parityMovie]
    } });
  });
  await page.goto('/ai-control', { waitUntil: 'domcontentloaded' });
  await page.getByPlaceholder('Tell CP what to find, list, download, or delete...').fill('Find my parity movie');
  await page.getByRole('button', { name: 'Preview command' }).click();
  await page.getByRole('button', { name: 'Display as cards' }).click();
  const aiCard = page.locator('.discover-movie-card').filter({ hasText: parityMovie.title });
  await aiCard.click();
  await expect(aiCard).toContainText('SQL Director');
  await expect(aiCard).toContainText('SQL Cast Member');
  await expect(aiCard).toContainText('SQL Collection');

  expect(libraryDetailsRequests).toBeGreaterThanOrEqual(5);
  expect(tmdbDetailsRequests).toBe(0);
});

test('curation generation refresh keeps an expanded Discover card open', async ({ page }) => {
  await mockCardParityApis(page);
  await page.route('**/api/library/details**', (route) => route.fulfill({ json: {
    item: parityDeferredDetails,
    catalog_generation: 1
  } }));

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  const card = page.locator('.discover-movie-card').filter({ hasText: parityMovie.title });
  await card.click();
  await expect(card).toContainText('SQL Director');

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('cp-curation-generation-changed', {
      detail: { previousGeneration: 1, generation: 2 }
    }));
  });

  await expect(card).toContainText('SQL Director');
  await expect(card).toHaveClass(/unified-movie-card-expanded/);
});
