import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const ingestionEvidenceDir = path.resolve(
  'docs/verification/online-library-ingestion/after'
);

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
  quality_class: '1080p',
  quality_display: '1080-class - 1800 x 960',
  rip_source: 'Blu-ray',
  video_width: 1800,
  video_height: 960,
  video_codec: 'HEVC',
  video_profile: 'Main 10@L4',
  video_bit_depth: 10,
  video_bitrate: 18400000,
  video_frame_rate: 23.976,
  duration_ms: 7080000,
  display_aspect_ratio: 1.875,
  rotation_degrees: 0,
  audio_codec: 'AAC',
  audio_channels: 6,
  audio_bitrate: 384000,
  filename_quality_claim: '720p',
  quality_source: 'measured_conflict',
  quality_conflict: true,
  quality_nonstandard: true,
  probe_status: 'ok',
  probed_at: 1785196800,
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

const parityCollectionParts = [
  parityMovie,
  {
    ...parityMovie,
    tmdb_id: '43',
    imdb_id: 'tt0000043',
    title: 'Missing Collection Part',
    year: '2025'
  },
  {
    ...parityMovie,
    tmdb_id: '44',
    imdb_id: 'tt0000044',
    title: 'Another Missing Collection Part',
    year: '2026'
  }
];

async function mockCardParityApis(page, options = {}) {
  await page.route('**/api/library?view=cards*', async (route) => {
    await route.fulfill({ json: { items: [parityLibraryItem], count: 1, catalog_generation: 1 } });
  });
  await page.route('**/api/library/check', async (route) => {
    const requested = route.request().postDataJSON()?.movies || [];
    await route.fulfill({ json: {
      results: requested.map((movie) => String(movie.tmdb_id || '') === parityMovie.tmdb_id ? {
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
        } : {
          found: false,
          tmdb_id: movie.tmdb_id || '',
          imdb_id: movie.imdb_id || '',
          title: movie.title || '',
          year: movie.year || ''
        })
      , catalog_generation: 1
    } });
  });
  await page.route('**/api/user/lists', async (route) => {
    await route.fulfill({ json: { lists: [{ id: 'render-parity', name: 'Render Parity', movies: [parityMovie] }], curation_generation: 1 } });
  });
  await page.route('**/api/tmdb/discover**', async (route) => {
    await route.fulfill({ json: { results: [parityMovie], page: 1, total_pages: 1, total_results: 1 } });
  });
  await page.route('**/api/library/collection/7001**', async (route) => {
    if (options.libraryCollectionGate) await options.libraryCollectionGate;
    await route.fulfill({ json: {
      id: '7001',
      name: 'SQL Collection',
      source: 'TMDB + Library',
      parts: parityCollectionParts,
      owned_count: 1,
      owned_paths: [parityLibraryItem.path],
      unresolved_count: 0
    } });
  });
  await page.route('**/api/tmdb/collection**', async (route) => {
    await route.fulfill({ json: {
      id: '7001',
      name: 'SQL Collection',
      source: 'TMDB',
      parts: parityCollectionParts
    } });
  });
  await page.route('**/api/tmdb/person_movies**', async (route) => {
    await route.fulfill({ json: {
      results: [parityCollectionParts[1]],
      page: 1,
      total_pages: 1,
      total_results: 1
    } });
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

test('release watcher keeps a three-row preview while View all and Following expose the complete set', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 });
  const followedMovies = Array.from({ length: 12 }, (_, index) => ({
    tmdb_id: String(9100 + index),
    title: `Followed Movie ${index + 1}`,
    year: '2026',
    status: index < 2 ? 'available' : 'watching',
    followed_at: 1000 - index,
    updated_at: 1000 - index,
    poster_url: ''
  }));
  let fullScanRequests = 0;
  let ownershipReconcileRequests = 0;
  let releaseInitialScan;
  const initialScanGate = new Promise((resolve) => { releaseInitialScan = resolve; });

  await page.route('**/api/user/followed-releases**', async (route) => {
    const url = new URL(route.request().url());
    if (route.request().method() === 'POST' && url.pathname.endsWith('/check')) {
      fullScanRequests += 1;
      if (fullScanRequests === 1) await initialScanGate;
    }
    if (route.request().method() === 'POST' && url.pathname.endsWith('/reconcile-owned')) ownershipReconcileRequests += 1;
    await route.fulfill({ json: {
      movies: followedMovies,
      newly_available: [],
      removed_owned: [],
      curation_generation: 1
    } });
  });
  await page.route('**/api/user/lists**', (route) => route.fulfill({ json: {
    lists: [
      { id: 'watched', name: 'Watched', system_type: 'watched', movies: [] },
      { id: 'watchlist', name: 'Watchlist', system_type: 'watchlist', movies: [] }
    ],
    curation_generation: 1
  } }));
  await page.route('**/api/library/check', async (route) => {
    const movies = route.request().postDataJSON()?.movies || [];
    await route.fulfill({ json: {
      results: movies.map((movie) => ({ ...movie, found: false })),
      catalog_generation: 1
    } });
  });
  await page.route('**/api/tmdb/card-projections', (route) => route.fulfill({ json: { items: {}, catalog_generation: 1 } }));

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const releasePanel = page.locator('.release-panel');
  await expect(releasePanel.locator('.release-item')).toHaveCount(3);
  await expect.poll(() => fullScanRequests).toBe(1);

  await releasePanel.getByRole('button', { name: 'View all' }).click();
  const drawer = page.getByRole('dialog', { name: 'Followed releases' });
  await expect(drawer.locator('.followed-row')).toHaveCount(12);
  await expect(drawer.getByRole('button', { name: 'All (12)' })).toBeVisible();
  await expect(drawer.getByRole('button', { name: 'Available (2)' })).toBeVisible();
  await expect(drawer.getByRole('button', { name: 'Watching (10)' })).toBeVisible();
  const lastFollowed = drawer.locator('[data-followed-title="Followed Movie 12"]');
  await lastFollowed.scrollIntoViewIfNeeded();
  await expect(lastFollowed).toBeInViewport();
  await drawer.getByRole('button', { name: 'Close followed releases' }).click();

  await expect(releasePanel.getByRole('button', { name: 'Scanning followed releases' })).toBeDisabled();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('cp-catalog-ready', {
    detail: { type: 'catalog-ready', generation: 2 }
  })));
  expect(ownershipReconcileRequests).toBe(0);
  releaseInitialScan();
  await expect.poll(() => ownershipReconcileRequests).toBe(1);
  await expect(releasePanel.getByRole('button', { name: 'Scan followed releases' })).toBeEnabled();
  await releasePanel.getByRole('button', { name: 'Scan followed releases' }).click();
  await expect.poll(() => fullScanRequests).toBe(2);

  await page.getByRole('button', { name: 'Movie Lists' }).click();
  const followingList = page.getByRole('button', { name: 'Following 12 movies' });
  await expect(followingList).toBeVisible();
  await followingList.click();
  await expect(page.getByLabel('Selected list name')).toHaveValue('Following');
  await expect(page.getByLabel('Selected list name')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Delete list' })).toBeDisabled();
  await expect(page.locator('.movie-lists-card-grid .discover-movie-card')).toHaveCount(12);
});

test('desktop sidebar collapses persistently while workspace margins stay fixed', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1000 });
  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Movie View' })).toBeVisible();

  const sidebar = page.getByRole('complementary', { name: 'Primary navigation' });
  const workspace = page.locator('.workspace');
  const pageContent = page.locator('.library-workspace');
  const collapseButton = page.getByRole('button', { name: 'Collapse sidebar' });

  await expect(sidebar).toHaveCSS('width', '280px');
  const expandedWorkspaceWidth = await workspace.evaluate((element) => element.getBoundingClientRect().width);
  const expandedContentWidth = await pageContent.evaluate((element) => element.getBoundingClientRect().width);
  const expandedPadding = await workspace.evaluate((element) => {
    const style = getComputedStyle(element);
    return [style.paddingLeft, style.paddingRight];
  });
  expect(expandedPadding).toEqual(['24px', '24px']);

  await collapseButton.click();
  await expect(sidebar).toHaveCSS('width', '84px');
  await expect(page.getByRole('button', { name: 'Expand sidebar' })).toHaveAttribute('aria-expanded', 'false');
  await expect(page.getByRole('button', { name: 'Library' })).toHaveAttribute('title', 'Library');
  const collapsedBrandOffset = await page.locator('.brand-mark').evaluate((logo) => {
    const sidebarRect = logo.closest('.sidebar').getBoundingClientRect();
    const logoRect = logo.getBoundingClientRect();
    return Math.abs((logoRect.left + logoRect.width / 2) - (sidebarRect.left + sidebarRect.width / 2));
  });
  expect(collapsedBrandOffset).toBeLessThanOrEqual(0.5);

  const collapsedWorkspaceWidth = await workspace.evaluate((element) => element.getBoundingClientRect().width);
  const collapsedContentWidth = await pageContent.evaluate((element) => element.getBoundingClientRect().width);
  const collapsedPadding = await workspace.evaluate((element) => {
    const style = getComputedStyle(element);
    return [style.paddingLeft, style.paddingRight];
  });
  expect(collapsedWorkspaceWidth - expandedWorkspaceWidth).toBeGreaterThanOrEqual(190);
  expect(collapsedContentWidth - expandedContentWidth).toBeGreaterThanOrEqual(190);
  expect(collapsedPadding).toEqual(['24px', '24px']);
  await expect.poll(() => page.evaluate(() => localStorage.getItem('cp.sidebarCollapsed'))).toBe('true');

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('complementary', { name: 'Primary navigation' })).toHaveCSS('width', '84px');
  await page.getByRole('button', { name: 'Expand sidebar' }).click();
  await expect(page.getByRole('complementary', { name: 'Primary navigation' })).toHaveCSS('width', '280px');
  await expect.poll(() => page.evaluate(() => localStorage.getItem('cp.sidebarCollapsed'))).toBe('false');
});

test('Continue Watching uses compact uncropped posters and centralized resume restart remove actions', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1000 });
  const poster = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900"><rect width="600" height="900" fill="#18181b"/><circle cx="300" cy="350" r="170" fill="#d4af37"/><text x="300" y="720" text-anchor="middle" fill="white" font-size="60">CP</text></svg>'
  );
  const items = Array.from({ length: 10 }, (_, index) => ({
    path_key: `e:\\movies\\continue-${index}.mkv`,
    movie_key: `tmdb:${1000 + index}`,
    title: `Continue Movie ${index + 1}`,
    year: '2026',
    poster_url: poster,
    position_ms: 300000,
    duration_ms: 600000,
    progress: 0.5,
    remaining_seconds: 300,
    last_played_at: 1000 - index
  }));
  let visibleItems = [...items];
  const playRequests = [];
  const clearRequests = [];

  await page.route('**/api/player/continue-watching**', (route) => route.fulfill({
    json: { items: visibleItems }
  }));
  await page.route('**/api/player/play', async (route) => {
    playRequests.push(route.request().postDataJSON());
    await route.fulfill({ json: { ok: true, mode: 'built_in', fallback: false } });
  });
  await page.route('**/api/player/progress/clear', async (route) => {
    const payload = route.request().postDataJSON();
    clearRequests.push(payload);
    visibleItems = visibleItems.filter((item) => item.path_key !== payload.path_key);
    await route.fulfill({ json: { ok: true, removed: true } });
  });

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const rail = page.getByRole('region', { name: 'Continue Watching movies' });
  await expect(page.getByRole('heading', { name: 'Continue Watching' })).toBeVisible();
  await expect(rail.locator('.continue-movie-card')).toHaveCount(10);
  const posterImage = rail.locator('.continue-movie-poster img').first();
  await expect(posterImage).toHaveCSS('object-fit', 'contain');
  await expect(rail.locator('.continue-movie-card').first()).toHaveCSS('width', '156px');
  await expect(rail.locator('.continue-movie-poster').first()).toHaveCSS('height', '234px');

  const expandedComplete = await rail.evaluate((viewport) => {
    const right = viewport.getBoundingClientRect().right;
    return [...viewport.querySelectorAll('.continue-movie-card')]
      .filter((card) => card.getBoundingClientRect().right <= right + 0.5).length;
  });
  expect(expandedComplete).toBeGreaterThanOrEqual(5);
  expect(expandedComplete).toBeLessThanOrEqual(6);
  if (process.env.CP_E2E_EVIDENCE_PATH) {
    await page.screenshot({
      path: process.env.CP_E2E_EVIDENCE_PATH,
      fullPage: true
    });
  }

  await page.getByRole('button', { name: 'Collapse sidebar' }).click();
  const collapsedComplete = await rail.evaluate((viewport) => {
    const right = viewport.getBoundingClientRect().right;
    return [...viewport.querySelectorAll('.continue-movie-card')]
      .filter((card) => card.getBoundingClientRect().right <= right + 0.5).length;
  });
  expect(collapsedComplete).toBeGreaterThanOrEqual(expandedComplete);

  await page.getByRole('button', { name: 'Play Continue Movie 1', exact: true }).click();
  await expect.poll(() => playRequests.length).toBe(1);
  expect(playRequests[0]).toEqual({ path_key: items[0].path_key, restart: false });

  await rail.locator('.continue-movie-card').first().locator('.continue-movie-menu summary').click();
  await page.getByRole('button', { name: 'Restart' }).click();
  await expect.poll(() => playRequests.length).toBe(2);
  expect(playRequests[1]).toEqual({ path_key: items[0].path_key, restart: true });

  await rail.locator('.continue-movie-card').nth(1).locator('.continue-movie-menu summary').click();
  await rail.locator('.continue-movie-card').nth(1).getByRole('button', { name: 'Remove' }).click();
  await expect.poll(() => clearRequests.length).toBe(1);
  await expect(rail.locator('.continue-movie-card')).toHaveCount(9);
});

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

test('Settings keeps OS playback default, redacts provider secrets, and verifies the native runtime', async ({ page }) => {
  let savedPlayer = null;
  const publicPlayerConfig = {
    mode: 'os_default',
    preferred_audio_languages: ['original', 'en'],
    preferred_subtitle_languages: ['en'],
    prefer_forced_subtitles: false,
    prefer_hearing_impaired_subtitles: false,
    resume_enabled: true,
    minimum_resume_seconds: 120,
    completion_threshold: 0.92,
    auto_mark_completed_watched: true,
    hardware_decoding: 'safe_auto',
    hdr_handling: 'auto',
    audio_output: 'auto',
    audio_passthrough: [],
    subtitle_storage: 'cache',
    auto_subtitle_search: false,
    keyboard_shortcuts: { play_pause: 'Space', subtitle_search: 'D' },
    providers: {
      opensubtitles: {
        enabled: false,
        username_configured: false,
        api_key_configured: false,
        password_configured: false
      },
      subdl: { enabled: false, api_key_configured: false }
    }
  };
  await page.route('**/api/player/config', async (route) => {
    if (route.request().method() === 'PUT') {
      savedPlayer = route.request().postDataJSON();
      await route.fulfill({ json: {
        ...publicPlayerConfig,
        mode: savedPlayer.mode,
        providers: {
          opensubtitles: {
            enabled: savedPlayer.providers.opensubtitles.enabled,
            username_configured: Boolean(savedPlayer.providers.opensubtitles.username),
            api_key_configured: Boolean(savedPlayer.providers.opensubtitles.api_key),
            password_configured: Boolean(savedPlayer.providers.opensubtitles.password)
          },
          subdl: {
            enabled: savedPlayer.providers.subdl.enabled,
            api_key_configured: Boolean(savedPlayer.providers.subdl.api_key)
          }
        }
      } });
      return;
    }
    await route.fulfill({ json: publicPlayerConfig });
  });
  await page.route('**/api/player/status', (route) => route.fulfill({ json: {
    state: 'missing',
    ready: false,
    detail: 'The built-in player runtime is not installed. OS-default playback remains available.',
    player_version: '',
    mpv_version: '',
    qt_version: '',
    architecture: '',
    notices: [],
    os_fallback_available: true
  } }));
  await page.route('**/api/player/verify', (route) => route.fulfill({ json: {
    state: 'ready',
    ready: true,
    detail: 'The built-in player runtime is ready.',
    player_version: '0.1.0',
    mpv_version: 'git-48e6c35c0e05',
    qt_version: '6.10.3',
    architecture: 'x86_64',
    notices: [
      { component: 'Qt', spdx: 'LGPL-3.0-only' },
      { component: 'mpv', spdx: 'LGPL-2.1-or-later' }
    ],
    os_fallback_available: true
  } }));

  await page.goto('/settings', { waitUntil: 'domcontentloaded' });

  const playerCard = page.locator('.player-settings-card');
  await expect(page.getByText('IPTV and movie-card streaming keep their existing players.', { exact: false })).toBeVisible();
  await expect(page.getByLabel('Local Library playback mode')).toHaveValue('os_default');
  await expect(playerCard).toContainText('Operating-system fallback is available.');
  await page.getByLabel('Local Library playback mode').selectOption('built_in');
  await page.getByLabel('OpenSubtitles API key', { exact: true }).fill('browser-secret');
  await page.getByRole('button', { name: 'Save player' }).click();

  await expect.poll(() => savedPlayer?.mode).toBe('built_in');
  expect(savedPlayer.providers.opensubtitles.api_key).toBe('browser-secret');
  await expect(page.getByLabel('OpenSubtitles API key', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('OpenSubtitles API key', { exact: true })).toHaveAttribute('placeholder', /Saved/);
  await expect(playerCard).not.toContainText('browser-secret');

  await page.getByRole('button', { name: 'Verify player' }).click();
  await expect(playerCard).toContainText('Cinema Paradiso Player is ready.');
  await expect(playerCard).toContainText('0.1.0');
  await expect(playerCard).toContainText('6.10.3');
  await expect(playerCard).toContainText('LGPL-3.0-only');
  if (process.env.CP_CAPTURE_PLAYER_EVIDENCE === '1') {
    await playerCard.evaluate((element) => element.scrollIntoView({ block: 'start' }));
    await page.screenshot({ path: 'test-results/player-phase1-settings-card-top.png' });
    await playerCard.locator('.settings-action-grid').scrollIntoViewIfNeeded();
    await page.screenshot({ path: 'test-results/player-phase1-settings-card-bottom.png' });
  }
});

test('Library switches between canonical movie and raw file views', async ({ page }) => {
  await mockCardParityApis(page);
  let resolvedFileSelection = [];
  await page.route('**/api/library/selection/items', async (route) => {
    resolvedFileSelection = route.request().postDataJSON()?.paths || [];
    await route.fulfill({ json: { items: [parityLibraryItem], count: 1, catalog_generation: 1 } });
  });
  await page.route('**/api/library?view=files', async (route) => {
    await route.fulfill({ json: { items: [parityLibraryItem], count: 1, catalog_generation: 1 } });
  });
  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Movie View' })).toBeVisible();

  await page.getByRole('button', { name: 'File View' }).click();
  await expect(page.getByRole('heading', { name: 'File View' })).toBeVisible();
  const fileRow = page.locator('.library-file-row').filter({ hasText: parityLibraryItem.filename });
  const fileSelectionBar = page.locator('.library-bulk-selection');
  const fileCheckbox = fileRow.getByLabel(`Select ${parityLibraryItem.filename}`);
  await expect(fileSelectionBar).toContainText('Select files');
  await expect(fileCheckbox).toBeVisible();

  await fileRow.locator('.file-selection-checkbox').click();
  await expect(fileSelectionBar).toContainText('1 selected');
  await expect(fileRow).toHaveAttribute('aria-expanded', 'false');
  await fileSelectionBar.getByRole('button', { name: 'Clear' }).click();
  await expect(fileCheckbox).not.toBeChecked();
  await fileSelectionBar.getByRole('button', { name: 'Select all filtered' }).click();
  await expect(fileCheckbox).toBeChecked();
  await fileSelectionBar.getByRole('button', { name: 'Add to list' }).click();
  await expect.poll(() => resolvedFileSelection).toEqual([parityLibraryItem.path]);
  await expect(page.getByRole('dialog', { name: 'List editor' })).toContainText('1 selected movie will be added.');
  await page.getByRole('button', { name: 'Close list editor' }).click();

  await fileRow.locator('.file-row-main').click();
  await fileRow.getByRole('button', { name: `Collapse file details for ${parityLibraryItem.filename}` }).click();
  await expect(fileRow).toHaveAttribute('aria-expanded', 'false');
  await fileRow.focus();
  await fileRow.press('Enter');
  const fileFacts = page.locator('.file-expanded-panel');
  await expect(fileFacts.getByText('Physical file facts')).toBeVisible();
  await fileFacts.click();
  await expect(fileRow).toHaveAttribute('aria-expanded', 'true');
  await expect(fileFacts.getByText('1800 × 960', { exact: true })).toBeVisible();
  await expect(fileFacts.getByText('HEVC · Main 10@L4 · 10-bit', { exact: true })).toBeVisible();
  await expect(fileFacts.getByText('18.4 Mbps', { exact: true })).toBeVisible();
  await expect(fileFacts.getByText('1h 58m 0s', { exact: true })).toBeVisible();
  await expect(fileFacts.getByText('23.976 fps', { exact: true })).toBeVisible();
  await expect(fileFacts.getByText('1.875:1', { exact: true })).toBeVisible();
  await expect(fileFacts.getByText('AAC · 6 channels · 384 kbps', { exact: true })).toBeVisible();
  await expect(fileFacts.locator('.file-expanded-quality-conflict')).toHaveCount(1);
  await expect(fileFacts.getByText('Conflict: filename claims 720p; measured 1800 × 960 classify as 1080p.', { exact: true })).toBeVisible();

  await fileRow.getByRole('button', { name: 'Movie View' }).click();
  await expect(page.getByRole('heading', { name: 'Movie View' })).toBeVisible();
  await expect(page.getByLabel('Library path')).toContainText(`${parityMovie.title} (${parityMovie.year})`);
  const focusedCard = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await expect(focusedCard).toHaveClass(/library-movie-card-expanded/);
  await page.getByLabel('Library path').getByRole('button', { name: 'Back' }).click();
  await expect(page.getByLabel('Library path')).toHaveCount(0);
  await focusedCard.click();
  await focusedCard.getByRole('button', { name: 'File details' }).click();
  await expect(page.getByRole('heading', { name: 'File View' })).toBeVisible();
  await expect(page.locator('.library-file-row-expanded')).toContainText(parityLibraryItem.path);
});

test('local Library playback uses the centralized player route without changing Stream', async ({ page }) => {
  await mockCardParityApis(page);
  let localPlaybackRequest = null;
  let streamingRequestCount = 0;
  await page.route('**/api/player/play', async (route) => {
    localPlaybackRequest = route.request().postDataJSON();
    await route.fulfill({ json: {
      ok: true,
      mode: 'built_in',
      fallback: false,
      session_id: 'browser-evidence-session'
    } });
  });
  await page.route('**/api/streaming/resolve', async (route) => {
    streamingRequestCount += 1;
    await route.fulfill({ status: 500, json: { error: 'Streaming route must remain separate.' } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  const movieCard = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await movieCard.click();
  await movieCard.getByRole('button', { name: 'Play', exact: true }).click();

  await expect.poll(() => localPlaybackRequest).toEqual({
    path_key: parityLibraryItem.path,
    restart: false
  });
  expect(streamingRequestCount).toBe(0);
  await expect(page.getByText('Playing in Cinema Paradiso Player', { exact: true })).toBeVisible();
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
    page: 1,
    page_size: 50,
    total_pages: 1,
    total_results: 1,
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
  await expect(page.getByLabel('Library path')).toContainText('Keyword: space opera');
  expect(new URL(selectedKeywordUrl).searchParams.get('keyword_id')).toBe('501');
});

test('Library keyword pagination replaces bounded pages and reaches every identity', async ({ page }) => {
  const requestedUrls = [];
  await page.route('**/api/library?view=cards*', (route) => route.fulfill({ json: {
    items: [],
    count: 0,
    total: 0,
    page: 1,
    total_pages: 1,
    page_start: 0,
    page_end: 0,
    facets: { genres: [], sources: [], languages: [], countries: [] },
    stats: { total: 0, low: 0, matched: 0, pending: 0, unmatched: 0 },
    catalog_generation: 1
  } }));
  await page.route('**/api/library?view=keywords*', (route) => {
    const url = new URL(route.request().url());
    requestedUrls.push(url);
    const requestedPage = Number(url.searchParams.get('page') || 1);
    const start = (requestedPage - 1) * 50;
    const count = requestedPage < 3 ? 50 : 25;
    const items = Array.from({ length: count }, (_, index) => {
      const identity = start + index + 1;
      return {
        keyword_key: `tmdb:${identity}`,
        tmdb_id: String(identity),
        name: `paged keyword ${String(identity).padStart(3, '0')}`,
        normalized_name: `paged keyword ${String(identity).padStart(3, '0')}`,
        movie_count: 1
      };
    });
    return route.fulfill({ json: {
      items,
      page: requestedPage,
      page_size: 50,
      total_pages: 3,
      total_results: 125,
      count: items.length,
      source: 'catalog',
      catalog_generation: 1
    } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Library search type').selectOption('keywords');
  await page.getByLabel('Search keywords in your library').fill('paged');

  const pagination = page.getByRole('navigation', { name: 'Library pagination' });
  await expect(pagination.getByText('Page 1 of 3', { exact: true })).toBeVisible();
  await expect(page.locator('.keyword-search-card')).toHaveCount(50);
  await expect(page.getByText('paged keyword 001', { exact: true })).toBeVisible();

  await pagination.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(pagination.getByText('Page 2 of 3', { exact: true })).toBeVisible();
  await expect(page.locator('.keyword-search-card')).toHaveCount(50);
  await expect(page.getByText('paged keyword 001', { exact: true })).toHaveCount(0);
  await expect(page.getByText('paged keyword 051', { exact: true })).toBeVisible();

  await pagination.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(pagination.getByText('Page 3 of 3', { exact: true })).toBeVisible();
  await expect(page.locator('.keyword-search-card')).toHaveCount(25);
  await expect(page.getByText('paged keyword 125', { exact: true })).toBeVisible();
  await expect(pagination.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();

  await pagination.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(pagination.getByText('Page 2 of 3', { exact: true })).toBeVisible();
  expect(requestedUrls.map((url) => url.searchParams.get('page'))).toEqual(['1', '2', '3', '2']);
  expect(requestedUrls.every((url) => url.searchParams.get('page_size') === '50')).toBe(true);
  expect(requestedUrls.every((url) => !url.searchParams.has('limit'))).toBe(true);
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
        page: 1,
        page_size: 50,
        total_pages: 1,
        total_results: 1,
        count: 1,
        catalog_generation: 1
      } });
      return;
    }
    await route.fulfill({ json: {
      items: [{ keyword_key: 'tmdb:2', tmdb_id: '2', name: 'current keyword', movie_count: 1 }],
      page: 1,
      page_size: 50,
      total_pages: 1,
      total_results: 1,
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

  await page.route('**/api/tmdb/keywords/search**', (route) => {
    const requestedPage = Number(new URL(route.request().url()).searchParams.get('page') || 1);
    const names = {
      1: { tmdb_id: '500', name: 'space station' },
      2: { tmdb_id: '501', name: 'space opera' },
      3: { tmdb_id: '502', name: 'deep space' }
    };
    return route.fulfill({ json: {
      results: [names[requestedPage]],
      page: requestedPage,
      total_pages: 3,
      total_results: 41
    } });
  });
  await page.route('**/api/tmdb/discover**', (route) => {
    const url = route.request().url();
    if (new URL(url).searchParams.get('keyword_id') === '501') {
      selectedKeywordUrl = url;
      const requestedPage = Number(new URL(url).searchParams.get('page') || 1);
      const movie = requestedPage === 1
        ? keywordMovie
        : { ...keywordMovie, tmdb_id: `880${requestedPage}`, title: `Remote Space Page ${requestedPage}` };
      return route.fulfill({ json: {
        results: [movie],
        keyword: { tmdb_id: '501', name: 'space opera' },
        page: requestedPage,
        page_size: 20,
        total_pages: 3,
        total_results: 41
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

  const keywordPager = page.getByRole('navigation', { name: 'TMDB keyword search pagination' });
  await expect(keywordPager.getByText('Page 1 of 3')).toBeVisible();
  await expect(keywordPager.getByRole('button', { name: 'Previous' })).toBeDisabled();
  await keywordPager.getByRole('button', { name: 'Next' }).click();
  await expect(keywordPager.getByText('Page 2 of 3')).toBeVisible();
  const keywordCard = page.locator('.keyword-search-card').filter({ hasText: 'space opera' });
  await expect(keywordCard).toBeVisible();
  await keywordCard.getByRole('button', { name: 'Discover movies' }).click();

  await expect(page.getByText('Remote Space Archive', { exact: true })).toBeVisible();
  await expect(page.locator('.unified-owned-badge').filter({ hasText: 'Owned' })).toBeVisible();
  expect(new URL(selectedKeywordUrl).searchParams.get('keyword_id')).toBe('501');

  const relationshipPager = page.getByRole('navigation', { name: 'TMDB relationship pagination' });
  await expect(relationshipPager.getByText('Page 1 of 3')).toBeVisible();
  await relationshipPager.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Remote Space Page 2', { exact: true })).toBeVisible();
  await expect(page.getByText('Remote Space Archive', { exact: true })).toHaveCount(0);
  await expect(relationshipPager.getByText('Page 2 of 3')).toBeVisible();

  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByLabel('TMDB search type')).toHaveValue('keywords');
  await expect(page.locator('.keyword-search-card').filter({ hasText: 'space opera' })).toBeVisible();
  await expect(keywordPager.getByText('Page 2 of 3')).toBeVisible();
  await keywordPager.getByRole('button', { name: 'Next' }).click();
  await expect(keywordPager.getByText('Page 3 of 3')).toBeVisible();
  await expect(keywordPager.getByRole('button', { name: 'Next' })).toBeDisabled();
  await keywordPager.getByRole('button', { name: 'Previous' }).click();
  await expect(keywordPager.getByText('Page 2 of 3')).toBeVisible();
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

test('Discover relationship paging rejects stale pages and follows shrinking provider totals', async ({ page }) => {
  let releaseSlowPage;
  let slowPageStarted = false;
  let totalsShrank = false;
  const requestedPages = [];
  const slowPageGate = new Promise((resolve) => {
    releaseSlowPage = resolve;
  });

  await page.route('**/api/tmdb/keywords/search**', (route) => route.fulfill({ json: {
    results: [{ tmdb_id: '601', name: 'time loop' }],
    page: 1,
    page_size: 20,
    total_pages: 1,
    total_results: 1
  } }));
  await page.route('**/api/tmdb/discover**', async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get('keyword_id') !== '601') {
      return route.fulfill({ json: { results: [], page: 1, total_pages: 1, total_results: 0 } });
    }
    const requestedPage = Number(url.searchParams.get('page') || 1);
    const genre = url.searchParams.get('genre') || '';
    requestedPages.push({ page: requestedPage, genre });
    if (requestedPage === 2 && !genre) {
      slowPageStarted = true;
      await slowPageGate;
      await route.fulfill({ json: {
        results: [{ tmdb_id: 'slow-2', title: 'Stale relationship page', year: '2024', genres: [] }],
        page: 2,
        page_size: 20,
        total_pages: 3,
        total_results: 41
      } }).catch(() => {});
      return;
    }
    if (requestedPage === 2 && genre === '28') {
      totalsShrank = true;
      return route.fulfill({ json: {
        results: [],
        page: 2,
        page_size: 20,
        total_pages: 1,
        total_results: 1
      } });
    }
    const title = totalsShrank ? 'Shrunk total page 1' : genre === '28' ? 'Filtered page 1' : 'Original page 1';
    return route.fulfill({ json: {
      results: [{ tmdb_id: `page-${requestedPage}`, title, year: '2024', genres: genre ? ['Action'] : [] }],
      page: requestedPage,
      page_size: 20,
      total_pages: totalsShrank ? 1 : 3,
      total_results: totalsShrank ? 1 : 41
    } });
  });
  await page.route('**/api/library/check', (route) => route.fulfill({
    json: { results: [], catalog_generation: 1 }
  }));

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('TMDB search type').selectOption('keywords');
  await page.getByLabel('Search TMDB keywords').fill('time');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await page.getByRole('button', { name: 'Discover movies' }).click();

  const pager = page.getByRole('navigation', { name: 'TMDB relationship pagination' });
  await expect(page.getByText('Original page 1', { exact: true })).toBeVisible();
  await pager.getByRole('button', { name: 'Next' }).click();
  await expect.poll(() => slowPageStarted).toBe(true);
  await page.locator('.discover-toolbar select').nth(2).selectOption('28');
  await expect(page.getByText('Filtered page 1', { exact: true })).toBeVisible();
  await expect(pager.getByText('Page 1 of 3')).toBeVisible();

  releaseSlowPage();
  await expect(page.getByText('Stale relationship page', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Could not load this view.')).toHaveCount(0);

  await pager.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Shrunk total page 1', { exact: true })).toBeVisible();
  await expect(pager).toHaveCount(0);
  expect(requestedPages.slice(-2)).toEqual([
    { page: 2, genre: '28' },
    { page: 1, genre: '28' }
  ]);
});

test('Discover collection navigation wins over an older in-flight list request', async ({ page }) => {
  let releaseSlowList;
  let slowListStarted = false;
  const slowListGate = new Promise((resolve) => {
    releaseSlowList = resolve;
  });
  const rootMovie = {
    tmdb_id: '8100',
    title: 'Relationship Race Root',
    year: '2024',
    poster_url: '',
    genres: ['Adventure'],
    tmdb_rating: '8.0',
    tmdb_vote_count: 500,
    plot: 'The movie used to start relationship navigation.'
  };
  const collectionMovie = {
    tmdb_id: '8101',
    title: 'Collection Navigation Winner',
    year: '2025',
    poster_url: '',
    genres: ['Adventure'],
    tmdb_rating: '7.5',
    tmdb_vote_count: 100,
    plot: 'The collection result must remain current.'
  };
  const slowListMovie = {
    tmdb_id: '8102',
    title: 'Stale List Navigation',
    year: '2020',
    poster_url: '',
    genres: ['Drama'],
    tmdb_rating: '6.5',
    tmdb_vote_count: 50,
    plot: 'This obsolete result must never replace the collection.'
  };

  await page.route('**/api/tmdb/discover**', (route) => route.fulfill({ json: {
    results: [rootMovie],
    page: 1,
    total_pages: 1,
    total_results: 1
  } }));
  await page.route('**/api/library/check', (route) => route.fulfill({
    json: { results: [], catalog_generation: 1 }
  }));
  await page.route('**/api/user/lists', (route) => route.fulfill({ json: {
    lists: [{
      id: 'slow-list',
      name: 'Slow List',
      movies: [
        rootMovie,
        { tmdb_id: slowListMovie.tmdb_id, title: slowListMovie.title, year: slowListMovie.year }
      ]
    }],
    curation_generation: 1
  } }));
  await page.route('**/api/tmdb/details**', (route) => route.fulfill({ json: {
    ...rootMovie,
    summary: rootMovie.plot,
    cast: [],
    directors: [],
    writers: [],
    keywords: [],
    collection: { id: 'race-collection', name: 'Race Collection' }
  } }));
  await page.route('**/api/tmdb/collection**', (route) => route.fulfill({ json: {
    id: 'race-collection',
    name: 'Race Collection',
    source: 'TMDB',
    parts: [collectionMovie],
    curation_generation: 1
  } }));
  await page.route('**/api/tmdb/search**', async (route) => {
    slowListStarted = true;
    await slowListGate;
    await route.fulfill({ json: {
      results: [slowListMovie],
      page: 1,
      total_pages: 1,
      total_results: 1
    } }).catch(() => {});
  });

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  const rootCard = page.locator('.discover-movie-card').filter({ hasText: rootMovie.title });
  await expect(rootCard).toBeVisible();
  await rootCard.getByRole('heading', { name: rootMovie.title }).click();
  await expect(rootCard.getByRole('button', { name: /Race Collection/ })).toBeVisible();
  await expect(rootCard.getByRole('button', { name: 'Slow List', exact: true })).toBeVisible();

  await rootCard.getByRole('button', { name: 'Slow List', exact: true }).click();
  await expect.poll(() => slowListStarted).toBe(true);
  await rootCard.getByRole('button', { name: /Race Collection/ }).click();

  await expect(page.getByText(collectionMovie.title, { exact: true })).toBeVisible();
  releaseSlowList();
  await expect(page.getByText(slowListMovie.title, { exact: true })).toHaveCount(0);
  await expect(page.getByText(collectionMovie.title, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByText(rootMovie.title, { exact: true })).toBeVisible();
});

test('Library collection never shows a false zero and opens the full collection in Discover with one click', async ({ page }) => {
  let releaseLibraryCollection;
  const libraryCollectionGate = new Promise((resolve) => {
    releaseLibraryCollection = resolve;
  });
  await mockCardParityApis(page, { libraryCollectionGate });
  await page.route('**/api/library/details**', (route) => route.fulfill({
    json: { item: parityDeferredDetails, catalog_generation: 1 }
  }));

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  const libraryCard = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await libraryCard.getByRole('heading', { name: parityMovie.title }).click();

  const collectionButton = libraryCard.getByRole('button', { name: /SQL Collection/ });
  await expect(collectionButton).toContainText('Loading collection...');
  await expect(libraryCard.getByText('0 movies', { exact: false })).toHaveCount(0);

  await collectionButton.click();
  await expect(page.getByRole('heading', { name: 'Discover', exact: true })).toBeVisible();
  await expect(page.getByLabel('Discovery path').getByText(`${parityMovie.title} > SQL Collection`, { exact: true })).toBeVisible();
  for (const movie of parityCollectionParts) {
    await expect(page.getByRole('heading', { name: movie.title, exact: true })).toBeVisible();
  }
  await expect(page.locator('.discover-movie-card').filter({ hasText: parityMovie.title }).getByText('Owned', { exact: true })).toBeVisible();
  const missingCollectionCard = page.locator('.discover-movie-card').filter({
    has: page.getByRole('heading', { name: parityCollectionParts[1].title, exact: true })
  });
  await expect(missingCollectionCard.getByText('Not in library', { exact: true })).toBeVisible();

  releaseLibraryCollection();
  await page.getByRole('button', { name: 'Library', exact: true }).click();
  await expect(libraryCard.getByRole('button', { name: /SQL Collection/ })).toContainText('3 movies • 1 owned');
  await expect(libraryCard.getByText('0 movies', { exact: false })).toHaveCount(0);
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

test('Discover People and Actor Director Writer relationships replace pages beyond ten', async ({ page }) => {
  const requestedRelationships = [];

  await page.route('**/api/tmdb/people/search**', (route) => {
    const requestedPage = Number(new URL(route.request().url()).searchParams.get('page') || 1);
    return route.fulfill({ json: {
      results: [{
        tmdb_id: '730',
        name: `Page Person ${requestedPage}`,
        known_for_department: 'Acting',
        known_for: [`Known page ${requestedPage}`]
      }],
      page: requestedPage,
      page_size: 20,
      total_pages: 12,
      total_results: 221
    } });
  });
  await page.route('**/api/tmdb/person_movies**', (route) => {
    const url = new URL(route.request().url());
    const requestedPage = Number(url.searchParams.get('page') || 1);
    const role = url.searchParams.get('role') || 'actor';
    const genre = url.searchParams.get('genre') || '';
    requestedRelationships.push({ page: requestedPage, role, genre });
    return route.fulfill({ json: {
      results: [{
        tmdb_id: `${role}-${requestedPage}`,
        title: `${role} page ${requestedPage}${genre ? ` genre ${genre}` : ''}`,
        year: '2024',
        poster_url: '',
        genres: genre === '28' ? ['Action'] : ['Drama'],
        tmdb_rating: '8.0',
        tmdb_vote_count: 500,
        plot: `${role} relationship page`
      }],
      role,
      person_id: '730',
      page: requestedPage,
      page_size: 20,
      total_pages: 12,
      total_results: 221
    } });
  });
  await page.route('**/api/library/check', (route) => route.fulfill({
    json: { results: [], catalog_generation: 1 }
  }));

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByLabel('TMDB search type').selectOption('people');
  await page.getByLabel('Search TMDB people').fill('Page Person');
  await page.getByRole('button', { name: 'Search', exact: true }).click();

  const peoplePager = page.getByRole('navigation', { name: 'TMDB People search pagination' });
  await expect(peoplePager.getByText('Page 1 of 12')).toBeVisible();
  await peoplePager.getByRole('button', { name: 'Next' }).click();
  await expect(page.locator('.person-search-card').filter({ hasText: 'Page Person 2' })).toBeVisible();
  await expect(page.locator('.person-search-card').filter({ hasText: 'Page Person 1' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Acting credits' }).click();
  const relationshipPager = page.getByRole('navigation', { name: 'TMDB relationship pagination' });
  await expect(relationshipPager.getByText('Page 1 of 12')).toBeVisible();
  await page.getByLabel('Select actor page 1').check({ force: true });
  await relationshipPager.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('actor page 2', { exact: true })).toBeVisible();
  await relationshipPager.getByRole('button', { name: 'Previous' }).click();
  await expect(page.getByLabel('Select actor page 1')).toBeChecked();
  for (let expectedPage = 2; expectedPage <= 11; expectedPage += 1) {
    await relationshipPager.getByRole('button', { name: 'Next' }).click();
    await expect(relationshipPager.getByText(`Page ${expectedPage} of 12`)).toBeVisible();
  }
  await expect(page.getByText('actor page 11', { exact: true })).toBeVisible();
  await expect(page.getByText('actor page 10', { exact: true })).toHaveCount(0);

  await page.getByLabel('Library ownership').selectOption('owned');
  await expect(page.getByText('No owned movies match this TMDB result page.')).toBeVisible();
  await expect(relationshipPager.getByRole('button', { name: 'Next' })).toBeEnabled();
  await relationshipPager.getByRole('button', { name: 'Next' }).click();
  await expect(relationshipPager.getByText('Page 12 of 12')).toBeVisible();
  await expect(relationshipPager.getByRole('button', { name: 'Next' })).toBeDisabled();

  await page.getByLabel('Library ownership').selectOption('all');
  await expect(page.getByText('actor page 12', { exact: true })).toBeVisible();
  await page.locator('.discover-toolbar select').nth(2).selectOption('28');
  await expect(page.getByText('actor page 1 genre 28', { exact: true })).toBeVisible();
  await expect(relationshipPager.getByText('Page 1 of 12')).toBeVisible();
  expect(requestedRelationships.at(-1)).toEqual({ page: 1, role: 'actor', genre: '28' });

  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.locator('.person-search-card').filter({ hasText: 'Page Person 2' })).toBeVisible();
  await expect(peoplePager.getByText('Page 2 of 12')).toBeVisible();
  await page.getByRole('button', { name: 'Directed films' }).click();
  await expect(page.getByText('director page 1', { exact: true })).toBeVisible();
  await relationshipPager.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('director page 2', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await page.getByRole('button', { name: 'Written films' }).click();
  await expect(page.getByText('writer page 1', { exact: true })).toBeVisible();
  await relationshipPager.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('writer page 2', { exact: true })).toBeVisible();
});

test('Pick relationship browsing uses shared Previous and Next replacement pages', async ({ page }) => {
  const pickMovie = {
    tmdb_id: '9400',
    title: 'AI Pick Root',
    year: '2024',
    poster_url: '',
    genres: ['Drama'],
    tmdb_rating: '8.0',
    tmdb_vote_count: 500,
    plot: 'The AI starting point.'
  };

  await page.route('**/api/ollama/recommend', (route) => route.fulfill({
    json: { results: [pickMovie], model: 'test-model' }
  }));
  await page.route('**/api/tmdb/details**', (route) => route.fulfill({ json: {
    ...pickMovie,
    summary: pickMovie.plot,
    cast: [{ id: '9900', name: 'Pick Actor', character: 'Lead' }],
    directors: [],
    writers: [],
    keywords: []
  } }));
  await page.route('**/api/tmdb/person_movies**', (route) => {
    const requestedPage = Number(new URL(route.request().url()).searchParams.get('page') || 1);
    return route.fulfill({ json: {
      results: [{
        tmdb_id: `pick-${requestedPage}`,
        title: `Pick actor page ${requestedPage}`,
        year: '2024',
        poster_url: '',
        genres: ['Drama'],
        tmdb_rating: '7.5',
        tmdb_vote_count: 100,
        plot: 'Pick relationship result.'
      }],
      page: requestedPage,
      page_size: 20,
      total_pages: 2,
      total_results: 21,
      role: 'actor',
      person_id: '9900'
    } });
  });
  await page.route('**/api/library/check', (route) => route.fulfill({
    json: { results: [], catalog_generation: 1 }
  }));

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Pick My Movie', exact: true }).click();
  await page.getByPlaceholder('Something funny but a little sad, maybe an indie movie with a warm ending...').fill('A thoughtful drama');
  await page.getByRole('button', { name: 'Ask AI' }).click();

  const rootCard = page.locator('.discover-movie-card').filter({ hasText: pickMovie.title });
  await expect(rootCard).toBeVisible();
  await rootCard.getByRole('heading', { name: pickMovie.title }).click();
  const pickActorCard = rootCard.locator('.person-card').filter({ hasText: 'Pick Actor' });
  const biographyButton = pickActorCard.getByRole('button', { name: 'Open biography for Pick Actor' });
  const filmographyButton = pickActorCard.getByRole('button', { name: 'Open filmography for Pick Actor' });
  await expect(biographyButton).toHaveAttribute('title', 'Biography');
  await expect(filmographyButton).toHaveAttribute('title', 'Filmography');
  const biographyBox = await biographyButton.boundingBox();
  const filmographyBox = await filmographyButton.boundingBox();
  expect(filmographyBox.y).toBeGreaterThan(biographyBox.y);
  expect(Math.abs(filmographyBox.y - (biographyBox.y + biographyBox.height) - 6)).toBeLessThanOrEqual(1);
  await filmographyButton.click();

  const pager = page.getByRole('navigation', { name: 'AI Pick relationship pagination' });
  await expect(page.getByText('Pick actor page 1', { exact: true })).toBeVisible();
  await expect(pager.getByText('Page 1 of 2')).toBeVisible();
  await expect(pager.getByRole('button', { name: 'Previous' })).toBeDisabled();
  await pager.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Pick actor page 2', { exact: true })).toBeVisible();
  await expect(page.getByText('Pick actor page 1', { exact: true })).toHaveCount(0);
  await expect(pager.getByRole('button', { name: 'Next' })).toBeDisabled();
  await expect(page.getByText('Load more', { exact: true })).toHaveCount(0);

  await page.getByRole('button', { name: 'Back', exact: true }).click();
  await expect(page.getByText(pickMovie.title, { exact: true })).toBeVisible();
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

test('bulk Find sources keeps owned movies as upgrades and switches the actual quality variant', async ({ page }) => {
  const ownedMovie = {
    tmdb_id: '8401',
    imdb_id: 'tt0008401',
    title: 'Owned Upgrade Movie',
    year: '2024',
    poster_url: '',
    genres: ['Action'],
    plot: 'An existing library movie selected for a better copy.'
  };
  const missingMovie = {
    tmdb_id: '8402',
    imdb_id: 'tt0008402',
    title: 'Missing Download Movie',
    year: '2025',
    poster_url: '',
    genres: ['Drama'],
    plot: 'A movie that is not yet in the library.'
  };
  const lowerOnlyMovie = {
    tmdb_id: '8403',
    imdb_id: 'tt0008403',
    title: 'Lower Quality Only Movie',
    year: '2023',
    poster_url: '',
    genres: ['Action'],
    plot: 'An owned movie for which YTS returned only 720p.'
  };
  const owned1080 = {
    title: 'Owned Upgrade Movie 2024 1080p',
    resolution: '1080p',
    indexer: 'Trusted',
    size_human: '2.0 GB',
    seeders: 20,
    magnet_url: 'magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  };
  const owned4K = {
    title: 'Owned Upgrade Movie 2024 4K',
    resolution: '4K',
    indexer: 'Trusted',
    size_human: '8.0 GB',
    seeders: 10,
    magnet_url: 'magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
  };
  const missing1080 = {
    title: 'Missing Download Movie 2025 1080p',
    resolution: '1080p',
    indexer: 'Trusted',
    size_human: '2.5 GB',
    seeders: 30,
    magnet_url: 'magnet:?xt=urn:btih:cccccccccccccccccccccccccccccccccccccccc'
  };
  let previewMovies = [];
  let submittedRows = [];

  await page.route('**/api/tmdb/discover**', (route) => route.fulfill({ json: {
    results: [ownedMovie, missingMovie, lowerOnlyMovie],
    page: 1,
    total_pages: 1,
    total_results: 3
  } }));
  await page.route('**/api/library/check', async (route) => {
    const movies = (await route.request().postDataJSON()).movies || [];
    await route.fulfill({ json: {
      results: movies.map((movie) => [ownedMovie.tmdb_id, lowerOnlyMovie.tmdb_id].includes(movie.tmdb_id) ? {
        found: true,
        path: `E:/Movies/${movie.title.replaceAll(' ', '.')}.${movie.year}.720p.mkv`,
        tmdb_id: movie.tmdb_id,
        imdb_id: movie.imdb_id,
        title: movie.title,
        year: movie.year,
        resolution: '720p',
        maintenance_upgrade_candidate: true
      } : {
        found: false,
        tmdb_id: movie.tmdb_id
      }),
      catalog_generation: 1
    } });
  });
  await page.route('**/api/sources/review/preview', async (route) => {
    previewMovies = (await route.request().postDataJSON()).movies || [];
    await route.fulfill({ json: {
      rows: [{
        ...ownedMovie,
        path: 'E:/Movies/Owned.Upgrade.Movie.2024.720p.mkv',
        upgrade: true,
        selected: true,
        status: 'ready',
        quality: '1080p',
        variant: owned1080,
        variants_by_quality: { '1080p': owned1080, '4K': owned4K },
        reason: ''
      }, {
        ...missingMovie,
        upgrade: false,
        selected: true,
        status: 'ready',
        quality: '1080p',
        variant: missing1080,
        variants_by_quality: { '1080p': missing1080, '4K': null },
        reason: ''
      }, {
        ...lowerOnlyMovie,
        path: 'E:/Movies/Lower.Quality.Only.Movie.2023.720p.mkv',
        upgrade: true,
        selected: false,
        status: 'blocked',
        quality: '1080p',
        variant: null,
        variants_by_quality: { '1080p': null, '4K': null },
        reason: 'No trusted 1080p source found'
      }],
      blocked: [{ ...lowerOnlyMovie, status: 'blocked', reason: 'No trusted 1080p source found' }],
      defaults: { quality: '1080p', trusted_indexers: ['7'] }
    } });
  });
  await page.route('**/api/sources/review/submit', async (route) => {
    submittedRows = (await route.request().postDataJSON()).rows || [];
    await route.fulfill({ json: {
      submitted_count: 2,
      skipped_count: 0,
      results: []
    } });
  });

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  const ownedCheckbox = page.getByRole('checkbox', { name: `Select ${ownedMovie.title}` });
  const missingCheckbox = page.getByRole('checkbox', { name: `Select ${missingMovie.title}` });
  const lowerOnlyCheckbox = page.getByRole('checkbox', { name: `Select ${lowerOnlyMovie.title}` });
  await ownedCheckbox.check({ force: true });
  await expect(ownedCheckbox).toBeChecked();
  await missingCheckbox.check({ force: true });
  await expect(missingCheckbox).toBeChecked();
  await lowerOnlyCheckbox.check({ force: true });
  await expect(lowerOnlyCheckbox).toBeChecked();
  await page.locator('.discover-bulk-selection').getByRole('button', { name: 'Find sources', exact: true }).click();

  const dialog = page.getByRole('dialog', { name: 'Find sources' });
  await expect(dialog).toBeVisible();
  await expect.poll(() => previewMovies.map((movie) => movie.tmdb_id)).toEqual([
    ownedMovie.tmdb_id,
    missingMovie.tmdb_id,
    lowerOnlyMovie.tmdb_id
  ]);
  const lowerOnlyRow = dialog.locator('.source-review-row').filter({ hasText: lowerOnlyMovie.title });
  await expect(lowerOnlyRow).toContainText('No trusted 1080p source found');
  await expect(lowerOnlyRow).not.toContainText('720p');
  await expect(lowerOnlyRow.getByRole('combobox')).toBeDisabled();
  await expect(lowerOnlyRow.getByRole('checkbox')).not.toBeChecked();
  await expect(dialog).toContainText('1 owned movie will be downloaded as an upgrade copy.');
  await expect(dialog).toContainText('Existing library files will be kept for comparison in Maintenance.');

  const ownedRow = dialog.locator('.source-review-row').filter({ hasText: ownedMovie.title });
  await expect(ownedRow).toContainText(owned1080.title);
  await expect(ownedRow).toContainText('Upgrade');
  await ownedRow.getByRole('combobox').selectOption('4K');
  await expect(ownedRow).toContainText(owned4K.title);
  await expect(ownedRow).not.toContainText(owned1080.title);

  await dialog.getByRole('button', { name: 'Submit selected to qBittorrent' }).click();
  await expect.poll(() => submittedRows.length).toBe(3);
  const submittedOwned = submittedRows.find((row) => row.tmdb_id === ownedMovie.tmdb_id);
  expect(submittedOwned.upgrade).toBe(true);
  expect(submittedOwned.quality).toBe('4K');
  expect(submittedOwned.variant.title).toBe(owned4K.title);
  const submittedLowerOnly = submittedRows.find((row) => row.tmdb_id === lowerOnlyMovie.tmdb_id);
  expect(submittedLowerOnly.status).toBe('blocked');
  expect(submittedLowerOnly.selected).toBe(false);
  expect(submittedLowerOnly.variant).toBeNull();
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
            {
              path: keepPath,
              filename: 'Project.Hail.Mary.2026.1080p.mkv',
              role: 'keep',
              recommendation: 'keep',
              verdict: 'recommended_keep',
              verdict_label: 'Recommended keep',
              verdict_tone: 'success',
              reason: 'Recommended keep — 2.25× the pixels of the 720p copy; identical runtime.',
              resolution: '1080p',
              quality_class: '1080p',
              quality_display: '1080-class - 1800 x 960',
              video_width: 1800,
              video_height: 960,
              video_codec: 'HEVC',
              video_bit_depth: 10,
              audio_codec: 'AAC',
              audio_channels: 2,
              size_human: '4.0 GB'
            },
            {
              path: candidatePath,
              filename: 'Project.Hail.Mary.2026.720p.mkv',
              role: 'candidate',
              recommendation: 'recommended',
              verdict: 'recommended_removal',
              verdict_label: 'Recommended removal',
              verdict_tone: 'danger',
              reason: 'Recommended removal — 2.25× fewer pixels; identical runtime.',
              resolution: '720p',
              quality_class: '720p',
              quality_display: '720p',
              video_width: 1280,
              video_height: 720,
              video_codec: 'HEVC',
              video_bit_depth: 10,
              audio_codec: 'AAC',
              audio_channels: 2,
              size_human: '2.0 GB'
            },
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
  const keepRow = page.locator('.cleanup-file-row').filter({ hasText: 'Project.Hail.Mary.2026.1080p.mkv' });
  const candidateCheckbox = candidateRow.getByRole('checkbox', { name: 'Select' });
  const keepCheckbox = keepRow.getByRole('checkbox', { name: 'Select' });
  await expect(candidateRow.getByText('Recommended removal', { exact: true })).toHaveClass(/chip-warning/);
  await expect(candidateRow).toContainText('2.25× fewer pixels');
  await expect(keepRow).toContainText('1080-class - 1800 x 960');
  await expect(keepRow).toContainText('HEVC');
  await expect(keepRow).toContainText('10-bit');
  await expect(candidateRow.getByRole('button', { name: 'Play file' })).toBeVisible();
  await expect(keepRow.getByRole('button', { name: 'Play file' })).toBeVisible();
  await expect(keepCheckbox).toBeEnabled();

  await page.getByRole('button', { name: 'Select recommended' }).click();
  await expect(candidateCheckbox).toBeChecked();
  await keepCheckbox.click();
  await expect(keepCheckbox).not.toBeChecked();
  await expect(page.getByText('Keep at least one copy in each duplicate group.')).toBeVisible();

  await candidateCheckbox.uncheck();
  await keepCheckbox.check();
  await expect(keepCheckbox).toBeChecked();
  await page.getByRole('button', { name: 'Clear' }).click();
  await page.getByRole('button', { name: 'Select recommended' }).click();
  await page.getByRole('button', { name: 'Delete selected (1)' }).click();

  const dialog = page.getByRole('dialog', { name: 'Move 1 selected file to Recycle Bin?' });
  await expect(dialog).toContainText('1 complete movie folder will move to the Recycle Bin');
  await expect(dialog).toContainText('including 4 sidecar files');
  await expect(dialog).toContainText(folderTarget);
  await dialog.getByRole('button', { name: 'Move to Recycle Bin' }).click();

  await expect.poll(() => executedRequest).not.toBeNull();
  expect(executedRequest.paths).toEqual([candidatePath]);
  expect(executedRequest.folder_targets).toEqual([folderTarget]);
  await expect(page.getByText('1 movie file moved to Recycle Bin, including 1 complete folder')).toBeVisible();
});

test('Maintenance explains quality, content, and frame-rate evidence without using fps as a quality score', async ({ page }) => {
  await page.route('**/api/maintenance/audit?*', async (route) => {
    await route.fulfill({ json: {
      summary: {
        duplicate_groups: 1,
        extra_copies: 1,
        reclaimable_human: '705.0 MB',
        recommended_removals: 1,
        unmatched_files: 0,
        upgrade_candidates: 0,
      },
      storage: {
        groups: [{
          title: 'Vamps (2012)',
          recommended_count: 1,
          comparison_scope: 'Measured video and primary audio',
          files: [
            {
              path: 'E:\\Movies\\Vamps.2012.1080p.mp4',
              filename: 'Vamps.2012.1080p.mp4',
              role: 'keep',
              recommendation: 'keep',
              verdict: 'recommended_keep',
              verdict_label: 'Recommended keep',
              verdict_tone: 'success',
              reason: 'Recommended keep — 9.49× the pixels; 23.976 to 25 fps speed conversion detected; estimated frame count matches within 0.01%.',
              resolution: '1080p',
              quality_class: '1080p',
              quality_display: '1080-class - 1920 x 1036',
              video_width: 1920,
              video_height: 1036,
              video_codec: 'AVC',
              video_bit_depth: 8,
              video_bitrate: 2062000,
              video_frame_rate: 23.976,
              duration_ms: 5558468,
              audio_codec: 'AAC',
              audio_channels: 2,
              comparison_uses_frame_rate: true,
              comparison_uses_aspect_ratio: true,
              aspect_delta_percent: 0.21,
              rip_source: 'BDRip',
              size_human: '1.4 GB',
            },
            {
              path: 'E:\\Movies\\Vamps.2012.DVDRip.avi',
              filename: 'Vamps.2012.DVDRip.avi',
              role: 'candidate',
              recommendation: 'recommended',
              verdict: 'recommended_removal',
              verdict_label: 'Recommended removal',
              verdict_tone: 'danger',
              reason: 'Recommended removal — 9.49× fewer pixels; 23.976 to 25 fps speed conversion detected; estimated frame count matches within 0.01%.',
              resolution: '336p',
              quality_class: '336p',
              quality_display: '336-class - 624 x 336',
              video_width: 624,
              video_height: 336,
              video_codec: 'MPEG-4 Visual',
              video_bit_depth: 8,
              video_bitrate: 968433,
              video_frame_rate: 25,
              duration_ms: 5330320,
              audio_codec: 'MPEG Audio',
              audio_channels: 2,
              comparison_uses_frame_rate: true,
              comparison_uses_aspect_ratio: true,
              aspect_delta_percent: 0.21,
              rip_source: 'DVDRip',
              size_human: '705.0 MB',
            },
          ],
        }],
        pagination: { total: 1, page: 1, total_pages: 1, page_start: 1, page_end: 1 },
      },
      identity: { items: [], pagination: { total: 0, page: 1, total_pages: 1 } },
    } });
  });

  await page.goto('/cleanup', { waitUntil: 'domcontentloaded' });
  const blurayRow = page.locator('.cleanup-file-row').filter({ hasText: 'Vamps.2012.1080p.mp4' });
  const dvdRow = page.locator('.cleanup-file-row').filter({ hasText: 'Vamps.2012.DVDRip.avi' });

  await expect(blurayRow.getByText('Recommended keep', { exact: true })).toBeVisible();
  await expect(dvdRow.getByText('Recommended removal', { exact: true })).toBeVisible();
  await expect(dvdRow).toContainText('9.49× fewer pixels');
  await expect(dvdRow).toContainText('speed conversion detected');
  await expect(blurayRow).toContainText('23.976 fps');
  await expect(dvdRow).toContainText('25 fps');
  await expect(dvdRow).toContainText('Framing Δ 0.21%');
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
  await page.route('**/api/iptv/providers', (route) => route.fulfill({ json: {
    providers: [{
      provider_id: 'provider-a',
      name: 'Provider A',
      configured: true,
      generation: 1,
      counts: { live: 0, movie: 0, series: 0 },
      sync: { state: 'idle' }
    }],
    last_selected_provider_id: 'provider-a',
    count: 1
  } }));
  await page.route('**/api/iptv/providers/provider-a/status', (route) => route.fulfill({ json: {
    provider_id: 'provider-a',
    name: 'Provider A',
    configured: true,
    generation: 1,
    counts: { live: 0, movie: 0, series: 0 },
    sync: { state: 'idle' }
  } }));
  await page.route('**/api/iptv/providers/provider-a/recent**', (route) => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/iptv/providers/provider-a/categories**', (route) => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/iptv/providers/provider-a/items**', (route) => route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 30 } }));

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

test('IPTV providers keep same IDs isolated, stop playback on switch, and remove only the selected provider', async ({ page }) => {
  const registry = await page.request.get('/api/iptv/providers');
  expect(registry.ok()).toBeTruthy();
  const registryPayload = await registry.json();
  const first = registryPayload.providers.find((provider) => provider.name === 'Provider One');
  const second = registryPayload.providers.find((provider) => provider.name === 'Provider Two');
  expect(first).toBeTruthy();
  expect(second).toBeTruthy();

  await page.route(`**/api/iptv/providers/${first.provider_id}/items?*`, async (route) => {
    const requestUrl = new URL(route.request().url());
    if (requestUrl.searchParams.get('kind') === 'movie') {
      await new Promise((resolve) => setTimeout(resolve, 650));
    }
    await route.continue();
  });

  const stoppedPlayback = [];
  await page.route(/\/api\/iptv\/providers\/([^/]+)\/playback$/, async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const providerId = route.request().url().match(/providers\/([^/]+)\/playback$/)[1];
    await route.fulfill({ json: {
      token: 'fixture-playback-token',
      provider_id: providerId,
      manifest_url: `/api/iptv/providers/${providerId}/playback/fixture-playback-token/index.m3u8`
    } });
  });
  await page.route(/\/api\/iptv\/providers\/([^/]+)\/playback\/fixture-playback-token$/, async (route) => {
    stoppedPlayback.push(route.request().url());
    await route.fulfill({ json: { success: true } });
  });

  await page.goto('/iptv', { waitUntil: 'domcontentloaded' });
  const selector = page.getByLabel('Active IPTV provider');
  await expect(selector).toHaveValue(first.provider_id);
  await page.getByRole('button', { name: 'Movies', exact: true }).click();
  await selector.selectOption(second.provider_id);
  await expect(page.getByText('Second Movie', { exact: true })).toBeVisible();
  await page.waitForTimeout(800);
  await expect(page.getByText('First Movie', { exact: true })).toHaveCount(0);

  await selector.selectOption(first.provider_id);
  await page.getByRole('button', { name: 'Live TV', exact: true }).click();
  await page.locator('.iptv-channel-list > button').filter({ hasText: 'First Channel' }).click();
  await expect.poll(() => stoppedPlayback.length).toBe(0);
  await selector.selectOption(second.provider_id);
  await expect.poll(() => stoppedPlayback.some((url) => url.includes(first.provider_id))).toBeTruthy();
  await expect(page.getByText('Second Channel', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  const secondRailButton = page.locator('.settings-provider-rail button').filter({ hasText: 'Provider Two' });
  await expect(secondRailButton).toBeVisible();
  await secondRailButton.click();
  page.once('dialog', async (dialog) => {
    expect(dialog.type()).toBe('prompt');
    await dialog.accept('Provider Two');
  });
  await page.getByRole('button', { name: 'Remove', exact: true }).click();
  await expect(secondRailButton).toHaveCount(0);
  await expect(page.locator('.settings-provider-rail button').filter({ hasText: 'Provider One' })).toBeVisible();

  const afterRemoval = await page.request.get('/api/iptv/providers');
  const afterPayload = await afterRemoval.json();
  expect(afterPayload.providers.map((provider) => provider.name)).toEqual(['Provider One']);
  const favorites = await page.request.get(`/api/iptv/providers/${first.provider_id}/favorites`);
  expect((await favorites.json()).total).toBe(1);
  const lists = await page.request.get(`/api/iptv/providers/${first.provider_id}/lists`);
  expect((await lists.json()).items.map((list) => list.name)).toEqual(['First fixture list']);
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
  await expect(libraryCard).toContainText('1080 · Blu-ray');
  await expect(libraryCard).not.toContainText('100 B');
  await expect(libraryCard).not.toContainText('1080-class - 1800 x 960');
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
  await expect(libraryCard.getByRole('button', { name: 'File details', exact: true })).toBeVisible();
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
  await expect(discoverCard).toContainText('1080 · Blu-ray');
  await expect(discoverCard).not.toContainText('100 B');
  await expect(discoverCard).not.toContainText('1080-class - 1800 x 960');
  await expect(discoverCard.getByText('Owned', { exact: true })).toBeVisible();
  const discoverRequestsBeforeExpand = tmdbDetailsRequests;
  await discoverCard.click();
  await expect(discoverCard).toContainText(parityMovie.plot);
  await expect(discoverCard).toContainText('SQL Director');
  await expect(discoverCard).toContainText('SQL Cast Member');
  await expect(discoverCard).toContainText('SQL Collection');
  await expect(discoverCard.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await expect(discoverCard.getByRole('button', { name: 'File details', exact: true })).toBeVisible();
  await expect(discoverCard.getByRole('button', { name: 'Follow', exact: true })).toHaveCount(0);
  expect(tmdbDetailsRequests).toBe(discoverRequestsBeforeExpand);

  await page.goto('/movie-lists', { waitUntil: 'domcontentloaded' });
  const listCard = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await expect(listCard.getByRole('heading', { name: parityMovie.title })).toBeVisible();
  await expect(listCard).toContainText(parityMovie.year);
  await expect(listCard).toContainText('1080 · Blu-ray');
  await expect(listCard).not.toContainText('100 B');
  await expect(listCard).not.toContainText('1080-class - 1800 x 960');
  const listRequestsBeforeExpand = tmdbDetailsRequests;
  await listCard.click();
  await expect(listCard).toContainText(parityMovie.plot);
  await expect(listCard).toContainText('SQL Director');
  await expect(listCard).toContainText('SQL Cast Member');
  await expect(listCard).toContainText('SQL Collection');
  await expect(listCard.getByRole('button', { name: 'Play', exact: true })).toBeVisible();
  await expect(listCard.getByRole('button', { name: 'File details', exact: true })).toBeVisible();
  await expect(listCard.getByRole('button', { name: 'Follow', exact: true })).toHaveCount(0);
  expect(tmdbDetailsRequests).toBe(listRequestsBeforeExpand);

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.inspector')).toContainText(parityMovie.plot);
  await expect(page.locator('.inspector')).toContainText('SQL Cast Member');
  await expect(page.locator('.inspector')).toContainText('1080 · Blu-ray');
  await expect(page.locator('.inspector')).not.toContainText('100 B');
  await expect(page.locator('.inspector')).not.toContainText('1080-class - 1800 x 960');
  const homeOwnedCard = page.locator('.home-smart-movie-card').filter({ hasText: parityMovie.title });
  await expect(homeOwnedCard).toContainText('1080 · Blu-ray');
  await expect(homeOwnedCard).not.toContainText('100 B');
  await expect(page.locator('.inspector').getByRole('button', { name: 'File details', exact: true })).toBeVisible();

  await page.route('**/api/ai-control/preview', async (route) => {
    await route.fulfill({ json: {
      state: 'valid_plan',
      plan_id: 'sql-parity-plan',
      action: 'find',
      summary: 'SQL parity plan',
      message: 'One owned result',
      total_matches: 1,
      page_size: 20,
      items: [{ ...parityMovie, selection_key: 'item-1' }]
    } });
  });
  await page.goto('/ai-control', { waitUntil: 'domcontentloaded' });
  await page.getByPlaceholder('Tell CP what to find, list, download, or delete...').fill('Find my parity movie');
  await page.getByRole('button', { name: 'Preview command' }).click();
  const aiCard = page.locator('.discover-movie-card').filter({ hasText: parityMovie.title });
  await expect(aiCard).toContainText('1080 · Blu-ray');
  await expect(aiCard).not.toContainText('100 B');
  await expect(aiCard).not.toContainText('1080-class - 1800 x 960');
  await aiCard.click();
  await expect(aiCard).toContainText('SQL Director');
  await expect(aiCard).toContainText('SQL Cast Member');
  await expect(aiCard).toContainText('SQL Collection');
  await expect(aiCard.getByRole('button', { name: /SQL Collection/ })).toBeVisible();
  await expect(aiCard.locator('.person-credit-browse').filter({ hasText: 'SQL Cast Member' })).toHaveAttribute('role', 'button');

  await aiCard.getByRole('button', { name: /SQL Collection/ }).click();
  await expect(page.getByRole('heading', { name: 'Discover', exact: true })).toBeVisible();
  await expect(page.getByLabel('Discovery path').getByText(`${parityMovie.title} > SQL Collection`, { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: parityCollectionParts[1].title, exact: true })).toBeVisible();

  await page.getByRole('complementary', { name: 'Primary navigation' }).getByRole('button', { name: /AI Control/ }).click();
  const restoredAiCard = page.locator('.workspace-panel:visible .discover-movie-card').filter({ hasText: parityMovie.title });
  await restoredAiCard.locator('.person-credit-browse').filter({ hasText: 'SQL Cast Member' }).click();
  await expect(page.getByRole('heading', { name: 'Discover', exact: true })).toBeVisible();
  await expect(page.getByLabel('Discovery path').getByText(/Actor: SQL Cast Member/, { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: parityCollectionParts[1].title, exact: true })).toBeVisible();

  expect(libraryDetailsRequests).toBeGreaterThanOrEqual(5);
  expect(tmdbDetailsRequests).toBe(0);
});

test('AI Control cards start fully selected, preserve custom selection across pages, and confirm exact server keys', async ({ page }) => {
  await mockCardParityApis(page);
  const movies = [
    { ...parityMovie, selection_key: 'item-1' },
    ...Array.from({ length: 20 }, (_, index) => ({
      tmdb_id: String(1000 + index),
      title: `AI Result ${index + 2}`,
      year: String(2000 + index),
      poster_url: '',
      genres: ['Drama'],
      selection_key: `item-${index + 2}`
    }))
  ];
  let executePayload = null;

  await page.route('**/api/ai-control/preview', (route) => route.fulfill({ json: {
    state: 'valid_plan',
    plan_id: 'complete-card-plan',
    action: 'download',
    summary: 'Download 21 movies in 1080p',
    message: 'Every result is selected.',
    total_matches: 21,
    page_size: 20,
    items: movies,
    blocked: [],
    warnings: []
  } }));
  await page.route('**/api/ai-control/execute', async (route) => {
    executePayload = await route.request().postDataJSON();
    await route.fulfill({ json: {
      state: 'executed',
      action: 'download',
      summary: 'Downloads submitted',
      message: 'Submitted 20 downloads to qBittorrent.',
      total_matches: 20,
      submitted_count: 20
    } });
  });

  await page.goto('/ai-control', { waitUntil: 'domcontentloaded' });
  await page.getByPlaceholder('Tell CP what to find, list, download, or delete...').fill('Download every matching movie in 1080p');
  await page.getByRole('button', { name: 'Preview command' }).click();

  await expect(page.getByText('Exact command selection: all 21 results.')).toBeVisible();
  await expect(page.locator('.discover-movie-card')).toHaveCount(20);
  await expect(page.getByText('21 selected', { exact: true })).toBeVisible();
  await expect(page.locator('.discover-movie-card').filter({ hasText: parityMovie.title }).getByText('Owned', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Next page' }).click();
  await expect(page.locator('.discover-movie-card')).toHaveCount(1);
  await page.getByLabel('Select AI Result 21').click({ force: true });
  await expect(page.getByText('Customized selection: 20 of 21 results.')).toBeVisible();
  await expect(page.getByText('20 selected', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Previous page' }).click();
  await expect(page.getByLabel(`Select ${parityMovie.title}`)).toBeChecked();
  await page.getByRole('button', { name: 'Confirm action' }).click();

  await expect.poll(() => executePayload).not.toBeNull();
  expect(executePayload.plan_id).toBe('complete-card-plan');
  expect(executePayload.selected_keys).toHaveLength(20);
  expect(executePayload.selected_keys).toContain('item-1');
  expect(executePayload.selected_keys).not.toContain('item-21');
  expect(executePayload.reviewed_downloads).toEqual([]);
  await expect(page.getByRole('heading', { name: 'Downloads submitted' })).toBeVisible();
});

test('Library metadata correction searches TMDB and Plex while keeping display edits separate', async ({ page }) => {
  await mockCardParityApis(page);
  await page.route('**/api/library/details**', (route) => route.fulfill({ json: {
    item: parityDeferredDetails,
    catalog_generation: 1
  } }));
  await page.route('**/api/metadata/override?path=*', (route) => route.fulfill({ json: {
    identity: { tmdb_id: parityMovie.tmdb_id, title: parityMovie.title, year: parityMovie.year },
    provider: { ...parityMovie, accepted: true },
    effective: { ...parityMovie, accepted: true },
    override: {},
    display_provider: 'tmdb',
    providers: {
      tmdb: { available: true, label: 'TMDB' },
      plex: { available: true, label: 'Plex snapshot' },
      filename: { available: true, label: 'Filename only' }
    }
  } }));
  await page.route('**/api/tmdb/search?*', (route) => route.fulfill({ json: {
    results: [{
      tmdb_id: '1091',
      title: 'Correct TMDB Movie',
      year: '1982',
      tmdb_rating: '8.1',
      tmdb_vote_count: 22000,
      plot: 'The exact TMDB identity.'
    }]
  } }));

  let plexSearch = null;
  let plexApply = null;
  await page.route('**/api/plex/match-search?*', (route) => {
    plexSearch = new URL(route.request().url());
    return route.fulfill({ json: {
      rating_key: 'plex-rating-42',
      results: [{
        guid: 'plex://movie/correct',
        name: 'Correct Plex Movie',
        year: '1982',
        summary: 'The exact Plex identity.',
        rank: 1
      }]
    } });
  });
  await page.route('**/api/plex/match-apply', async (route) => {
    plexApply = await route.request().postDataJSON();
    await route.fulfill({ json: { success: true, match: { provider: 'plex' } } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  const libraryCard = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await libraryCard.click();
  await libraryCard.getByRole('button', { name: 'Correct metadata' }).click();

  const dialog = page.getByRole('dialog', { name: 'Correct movie metadata' });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(`Current accepted match · TMDB`)).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Search TMDB' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Search Plex' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Save display title/year only' })).toBeVisible();

  await dialog.getByLabel('Search or display title').fill('Correct Movie');
  await dialog.getByLabel('Year').fill('1982');
  await dialog.getByRole('button', { name: 'Search TMDB' }).click();
  await expect(dialog.getByText('Correct TMDB Movie', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Apply TMDB match' })).toBeEnabled();

  await dialog.getByRole('button', { name: 'Search Plex' }).click();
  await expect(dialog.getByText('Correct Plex Movie', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Apply Plex match' })).toBeEnabled();
  expect(plexSearch.searchParams.get('title')).toBe('Correct Movie');
  expect(plexSearch.searchParams.get('year')).toBe('1982');

  await dialog.getByRole('button', { name: 'Apply Plex match' }).click();
  await expect(dialog).toHaveCount(0);
  expect(plexApply).toMatchObject({
    path: parityLibraryItem.path,
    rating_key: 'plex-rating-42',
    guid: 'plex://movie/correct',
    name: 'Correct Plex Movie',
    year: '1982'
  });
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

test('adaptive Discover paging fills the measured desktop card rows', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await mockCardParityApis(page);
  const requestedPageSizes = [];
  const movies = Array.from({ length: 100 }, (_, index) => ({
    ...parityMovie,
    tmdb_id: String(10000 + index),
    title: `Adaptive Movie ${index + 1}`,
    year: String(2000 + (index % 25))
  }));

  await page.route('**/api/tmdb/discover**', async (route) => {
    const url = new URL(route.request().url());
    const pageSize = Number(url.searchParams.get('page_size') || 20);
    requestedPageSizes.push(pageSize);
    await route.fulfill({ json: {
      results: movies.slice(0, pageSize),
      page: 1,
      page_size: pageSize,
      total_pages: Math.ceil(movies.length / pageSize),
      total_results: movies.length
    } });
  });

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  const grid = page.locator('.discover-panel .discover-grid');
  await expect(grid.locator(':scope > article')).toHaveCount(39);
  const metrics = await grid.evaluate((element) => ({
    cards: element.querySelectorAll(':scope > article').length,
    columns: getComputedStyle(element).gridTemplateColumns.split(' ').filter(Boolean).length
  }));

  expect(metrics).toEqual({ cards: 39, columns: 3 });
  expect(metrics.cards % metrics.columns).toBe(0);
  expect(requestedPageSizes).toContain(39);
});

test('Home fills both right-column spaces with playlist videos and inspector-aware upcoming movies', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await mockCardParityApis(page);
  const poster = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="900"><rect width="600" height="900" fill="#151515"/><text x="300" y="450" text-anchor="middle" fill="#d4af37" font-size="72">SOON</text></svg>'
  );
  const continueItems = Array.from({ length: 6 }, (_, index) => ({
    path_key: `e:\\movies\\home-${index}.mkv`,
    title: `Home Continue ${index + 1}`,
    poster_url: poster,
    progress: 0.4,
    remaining_seconds: 1200
  }));
  const upcoming = Array.from({ length: 6 }, (_, index) => ({
    tmdb_id: String(8100 + index),
    title: `Upcoming Feature ${index + 1}`,
    year: '2027',
    release_date: `2027-0${(index % 6) + 1}-15`,
    poster_url: poster,
    plot: `Upcoming plot ${index + 1}`,
    genres: ['Drama'],
    popularity: 100 - index
  }));
  const trending = Array.from({ length: 8 }, (_, index) => index === 0 ? parityMovie : ({
    ...parityMovie,
    tmdb_id: String(8200 + index),
    imdb_id: `tt-home-${index}`,
    title: `Trending Feature ${index + 1}`
  }));
  const videos = [
    {
      video_id: 'video-one',
      title: 'Hot Trailer One',
      url: 'https://www.youtube.com/watch?v=video-one',
      thumbnail_url: poster,
      published_at: '2026-07-28T10:00:00+00:00',
      views: 12000
    },
    {
      video_id: 'video-two',
      title: 'Hot Trailer Two',
      url: 'https://www.youtube.com/watch?v=video-two',
      thumbnail_url: poster,
      published_at: '2026-07-27T10:00:00+00:00',
      views: 8000
    }
  ];

  await page.route('**/api/player/continue-watching**', (route) => route.fulfill({
    json: { items: continueItems }
  }));
  await page.route('**/api/home/trailers', (route) => route.fulfill({ json: {
    playlist_id: 'PLScC8g4bqD47c-qHlsfhGH3j6Bg7jzFy-',
    title: 'HOT New Trailers & Exclusives',
    source_url: 'https://www.youtube.com/playlist?list=PLScC8g4bqD47c-qHlsfhGH3j6Bg7jzFy-',
    items: videos,
    stale: false
  } }));
  await page.route('**/api/tmdb/discover**', async (route) => {
    const url = new URL(route.request().url());
    const results = url.searchParams.get('list') === 'upcoming' ? upcoming : trending;
    await route.fulfill({ json: {
      results,
      page: 1,
      page_size: results.length,
      total_pages: 1,
      total_results: results.length
    } });
  });
  await page.route('**/api/tmdb/details**', async (route) => {
    const url = new URL(route.request().url());
    const movie = upcoming.find((item) => String(item.tmdb_id) === url.searchParams.get('tmdb_id')) || parityMovie;
    await route.fulfill({ json: {
      ...movie,
      summary: movie.plot,
      cast: [{ id: '1', name: 'Upcoming Cast' }],
      directors: [],
      writers: [],
      keywords: [],
      trailer_url: 'https://www.youtube.com/watch?v=upcoming-trailer'
    } });
  });
  await page.route('https://www.youtube.com/embed/**', (route) => route.fulfill({
    contentType: 'text/html',
    body: '<html><body>YouTube fixture</body></html>'
  }));

  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Continue Watching' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'HOT New Trailers & Exclusives' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Upcoming movies' })).toBeVisible();
  await expect(page.locator('.movie-list > .home-smart-movie-card')).toHaveCount(8);
  await page.locator('.inspector').evaluate(
    (element) => Promise.all(element.getAnimations().map((animation) => animation.finished))
  );

  const geometry = await page.evaluate(() => {
    const rect = (selector) => {
      const bounds = document.querySelector(selector).getBoundingClientRect();
      return { left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom, width: bounds.width };
    };
    return {
      continuePanel: rect('.continue-watching-panel'),
      trailers: rect('.home-trailers-panel'),
      discover: rect('.movie-rail'),
      inspector: rect('.inspector'),
      upcoming: rect('.coming-soon-panel')
    };
  });
  expect(Math.abs(geometry.continuePanel.left - geometry.discover.left)).toBeLessThan(1);
  expect(Math.abs(geometry.continuePanel.width - geometry.discover.width)).toBeLessThan(1);
  expect(Math.abs(geometry.trailers.left - geometry.inspector.left)).toBeLessThan(1);
  expect(Math.abs(geometry.trailers.width - geometry.inspector.width)).toBeLessThan(1);
  expect(Math.abs(geometry.upcoming.left - geometry.inspector.left)).toBeLessThan(1);
  expect(geometry.upcoming.top).toBeGreaterThanOrEqual(geometry.inspector.bottom + 17);

  const rowMetrics = await page.evaluate(() => {
    const metrics = (selector) => {
      const grid = document.querySelector(selector);
      return {
        cards: grid.children.length,
        columns: getComputedStyle(grid).gridTemplateColumns.split(' ').filter(Boolean).length
      };
    };
    return {
      trailers: metrics('.home-trailer-grid'),
      upcoming: metrics('.coming-soon-grid')
    };
  });
  expect(rowMetrics.trailers.cards % rowMetrics.trailers.columns).toBe(0);
  expect(rowMetrics.upcoming.cards % rowMetrics.upcoming.columns).toBe(0);
  expect(rowMetrics.upcoming).toEqual({ cards: 6, columns: 3 });

  await page.getByRole('button', { name: 'Play Hot Trailer One' }).click();
  const videoDialog = page.getByRole('dialog', { name: 'Hot New Trailers: Hot Trailer One' });
  await expect(videoDialog).toBeVisible();
  await expect(videoDialog.locator('iframe')).toHaveAttribute('src', 'https://www.youtube.com/embed/video-one?autoplay=1&rel=0&enablejsapi=1');
  await videoDialog.getByRole('button', { name: 'Play Hot Trailer Two in this player' }).click();
  const continuedVideoDialog = page.getByRole('dialog', { name: 'Hot New Trailers: Hot Trailer Two' });
  await expect(continuedVideoDialog).toBeVisible();
  await expect(continuedVideoDialog.locator('iframe')).toHaveAttribute('src', 'https://www.youtube.com/embed/video-two?autoplay=1&rel=0&enablejsapi=1');
  await continuedVideoDialog.getByRole('button', { name: 'Stop video' }).click();
  await expect(continuedVideoDialog).toHaveCount(0);

  await page.getByRole('button', { name: /Inspect Upcoming Feature 1/ }).click();
  await expect(page.locator('.inspector')).toContainText('Upcoming Feature 1');
  await expect(page.locator('.inspector')).toContainText('Upcoming Cast');
  await expect(page.locator('.inspector').getByRole('button', { name: 'Follow release' })).toBeVisible();

  await page.getByRole('button', { name: 'View all' }).click();
  await expect(page.getByRole('heading', { name: 'Discover', exact: true })).toBeVisible();
  await expect(page.locator('.discover-toolbar select').first()).toHaveValue('upcoming');
});

test('bootstrap paints before the frontend entry bundle executes', async ({ page }) => {
  let releaseEntry;
  let markEntryRequested;
  const entryGate = new Promise((resolve) => { releaseEntry = resolve; });
  const entryRequested = new Promise((resolve) => { markEntryRequested = resolve; });
  await page.route(/\/assets\/index-[^/]+\.js(?:\?.*)?$/, async (route) => {
    markEntryRequested();
    await entryGate;
    await route.continue();
  });

  await page.goto('/library', { waitUntil: 'commit' });
  await entryRequested;
  const bootstrap = page.locator('.app-bootstrap');
  await expect(bootstrap).toBeVisible();
  await expect(bootstrap).toContainText('Loading Cinema Paradiso');
  const bootstrapStyle = await bootstrap.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      color: style.color,
      display: style.display,
      fullViewport: Number.parseFloat(style.minHeight) >= window.innerHeight
    };
  });
  expect(bootstrapStyle).toEqual({
    color: 'rgb(212, 175, 55)',
    display: 'grid',
    fullViewport: true
  });

  releaseEntry();
  await expect(page.getByRole('heading', { name: 'Movie View' })).toBeVisible();
  await expect(bootstrap).toHaveCount(0);
});

test('cold Library navigation measures the grid once and defers unrelated startup work', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1000 });
  await page.addInitScript(() => {
    window.__cpInitialSyncEmitted = false;
    window.EventSource = class InitialSyncEventSource {
      constructor() {
        this.listeners = new Map();
        window.setTimeout(() => {
          window.__cpInitialSyncEmitted = true;
          this.listeners.get('catalog-sync')?.({
            data: JSON.stringify({ type: 'catalog-sync', generation: 1 })
          });
        }, 25);
      }
      addEventListener(name, handler) { this.listeners.set(name, handler); }
      close() {}
    };
  });

  const libraryRequests = [];
  const deferredHomeRequests = [];
  const deferredCurationRequests = [];
  let releaseLibrary;
  const libraryGate = new Promise((resolve) => { releaseLibrary = resolve; });
  await page.route('**/api/stats', (route) => {
    deferredHomeRequests.push('/api/stats');
    return route.fulfill({ json: {} });
  });
  await page.route('**/api/home/trailers', (route) => {
    deferredHomeRequests.push('/api/home/trailers');
    return route.fulfill({ json: { items: [] } });
  });
  await page.route('**/api/tmdb/discover**', (route) => {
    deferredHomeRequests.push('/api/tmdb/discover');
    return route.fulfill({ json: { results: [], page: 1, total_pages: 1, total_results: 0 } });
  });
  await page.route('**/api/user/followed-releases**', (route) => {
    const url = new URL(route.request().url());
    deferredCurationRequests.push(`${route.request().method()} ${url.pathname}`);
    return route.fulfill({ json: {
      movies: [], newly_available: [], removed_owned: [], curation_generation: 1
    } });
  });
  await page.route('**/api/streaming/config', (route) => {
    deferredCurationRequests.push(`${route.request().method()} /api/streaming/config`);
    return route.fulfill({ json: { enabled: false, label: 'Stream', url_template: '' } });
  });
  await page.route('**/api/library?view=cards*', async (route) => {
    libraryRequests.push(new URL(route.request().url()));
    await libraryGate;
    await route.fulfill({ json: {
      items: [parityLibraryItem], count: 1, total: 1, page: 1,
      page_size: Number(libraryRequests.at(-1).searchParams.get('page_size')),
      total_pages: 1, page_start: 1, page_end: 1,
      facets: { genres: [], sources: [], languages: [], countries: [] },
      stats: { total: 1, low: 0, matched: 1, pending: 0, unmatched: 0 },
      catalog_generation: 1
    } });
  });

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await expect.poll(() => libraryRequests.length).toBe(1);
  await expect.poll(() => page.evaluate(() => window.__cpInitialSyncEmitted)).toBe(true);
  await page.waitForTimeout(75);
  expect(libraryRequests).toHaveLength(1);
  expect(libraryRequests[0].searchParams.get('page_size')).toBe('39');
  expect(deferredHomeRequests).toEqual([]);
  expect(deferredCurationRequests).toEqual([]);

  releaseLibrary();
  const card = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await expect(card).toBeVisible();
  const grid = page.locator('.library-results').filter({ has: card });
  await grid.evaluate((element) => { element.dataset.initialMountProof = 'same-grid'; });
  await page.waitForTimeout(75);
  expect(libraryRequests).toHaveLength(1);
  await expect(grid).toHaveAttribute('data-initial-mount-proof', 'same-grid');
  await expect(page.locator('.library-status .spin')).toHaveCount(0);
  await expect(page.locator('.app-bootstrap')).toHaveCount(0);
  await expect.poll(() => deferredCurationRequests).toEqual([
    'GET /api/user/followed-releases',
    'GET /api/streaming/config',
    'POST /api/user/followed-releases/check'
  ]);
});

test('committed catalog event quietly adds a final Library card without unmounting or losing state', async ({ page }) => {
  await page.addInitScript(() => {
    window.EventSource = class SilentEventSource {
      addEventListener() {}
      close() {}
    };
  });
  const added = {
    ...parityLibraryItem,
    path: 'C:/fixture/Quiet Added Movie.mkv',
    filename: 'Quiet Added Movie.mkv',
    title: 'Quiet Added Movie',
    canonical_metadata: {
      ...parityLibraryItem.canonical_metadata,
      movie_key: 'tmdb:9002', tmdb_id: '9002', title: 'Quiet Added Movie', year: '2026'
    }
  };
  let requestCount = 0;
  let releaseRefresh;
  let markRefreshStarted;
  const refreshGate = new Promise((resolve) => { releaseRefresh = resolve; });
  const refreshStarted = new Promise((resolve) => { markRefreshStarted = resolve; });
  await page.route('**/api/library?view=cards*', async (route) => {
    requestCount += 1;
    if (requestCount > 1) {
      markRefreshStarted();
      await refreshGate;
    }
    const items = requestCount > 1 ? [parityLibraryItem, added] : [parityLibraryItem];
    await route.fulfill({ json: {
      items, count: items.length, total: items.length, page: 1, page_size: 40,
      total_pages: 1, page_start: 1, page_end: items.length,
      facets: { genres: [], sources: [], languages: [], countries: [] },
      stats: { total: items.length, low: 0, matched: items.length, pending: 0, unmatched: 0 },
      catalog_generation: requestCount > 1 ? 2 : 1
    } });
  });
  await page.route('**/api/library/details**', (route) => route.fulfill({
    json: { item: { ...parityDeferredDetails, collection: {} }, catalog_generation: 1 }
  }));

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  const firstCard = page.locator('.library-movie-card').filter({ hasText: parityMovie.title });
  await expect(firstCard).toBeVisible();
  await firstCard.getByRole('heading', { name: parityMovie.title }).click();
  await firstCard.getByRole('checkbox').check({ force: true });
  const search = page.getByLabel('Search your offline library');
  await search.focus();
  const grid = page.locator('.library-results');
  await grid.evaluate((element) => { element.dataset.quietMountProof = 'same-grid'; });

  await page.evaluate(() => window.dispatchEvent(new CustomEvent('cp-catalog-ready', {
    detail: { type: 'catalog-ready', generation: 2 }
  })));
  await refreshStarted;
  await expect(grid).toBeVisible();
  await expect(grid).toHaveAttribute('data-quiet-mount-proof', 'same-grid');
  await expect(page.locator('.library-status .spin')).toHaveCount(0);
  await expect(firstCard).toBeVisible();
  await expect(firstCard.getByRole('checkbox')).toBeChecked();
  await expect(firstCard).toHaveClass(/library-movie-card-expanded/);
  await expect(search).toBeFocused();
  if (process.env.CP_CAPTURE_INGESTION_EVIDENCE === '1') {
    fs.mkdirSync(ingestionEvidenceDir, { recursive: true });
    await page.screenshot({
      path: path.join(ingestionEvidenceDir, 'library-background-refresh-during.png'),
      fullPage: false
    });
  }

  releaseRefresh();
  await expect(page.getByRole('heading', { name: 'Quiet Added Movie', exact: true })).toBeVisible();
  await expect(grid).toHaveAttribute('data-quiet-mount-proof', 'same-grid');
  await expect(firstCard.getByRole('checkbox')).toBeChecked();
  await expect(firstCard).toHaveClass(/library-movie-card-expanded/);
  await expect(search).toBeFocused();
  if (process.env.CP_CAPTURE_INGESTION_EVIDENCE === '1') {
    await page.screenshot({
      path: path.join(ingestionEvidenceDir, 'library-background-refresh-complete.png'),
      fullPage: false
    });
  }
});
