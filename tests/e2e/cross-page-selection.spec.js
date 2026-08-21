import { expect, test } from '@playwright/test';

const libraryCardsRoute = /\/api\/library(?:\?view=cards.*|\/search\/advanced)$/;

function discoverMovie(tmdbId, title) {
  return {
    tmdb_id: String(tmdbId),
    title,
    year: '2026',
    poster_url: '',
    genres: ['Drama'],
    tmdb_rating: '7.0',
    tmdb_vote_count: 100
  };
}

test('Discover keeps selected movies and bulk payloads across server pages', async ({ page }) => {
  const pages = {
    1: [discoverMovie(101, 'Page One Alpha'), discoverMovie(102, 'Page One Beta')],
    2: [discoverMovie(201, 'Page Two Alpha'), discoverMovie(202, 'Page Two Beta')]
  };
  let bulkPayload = null;

  await page.route('**/api/tmdb/discover**', (route) => {
    const requestedPage = Number(route.request().postDataJSON()?.page || new URL(route.request().url()).searchParams.get('page') || 1);
    return route.fulfill({ json: {
      results: pages[requestedPage] || [],
      page: requestedPage,
      total_pages: 2,
      total_results: 4
    } });
  });
  await page.route('**/api/library/check', async (route) => {
    const movies = route.request().postDataJSON()?.movies || [];
    await route.fulfill({ json: {
      results: movies.map((movie) => ({ ...movie, found: false })),
      catalog_generation: 1
    } });
  });
  await page.route('**/api/user/lists**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/movies/bulk')) {
      bulkPayload = route.request().postDataJSON();
      await route.fulfill({ json: { added: bulkPayload.movies.length, curation_generation: 2 } });
      return;
    }
    await route.fulfill({ json: {
      lists: [{ id: 'cross-page-list', name: 'Cross-page list', movies: [] }],
      curation_generation: bulkPayload ? 2 : 1
    } });
  });

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Page One Alpha', exact: true })).toBeVisible();
  const topPagination = page.getByRole('navigation', { name: 'TMDB movie page controls above results', exact: true });
  const bottomPagination = page.getByRole('navigation', { name: 'TMDB movie pagination', exact: true });
  await expect(topPagination.getByText('Page 1 of 2', { exact: true })).toBeVisible();
  await expect(bottomPagination.getByText('Page 1 of 2', { exact: true })).toBeVisible();

  await page.getByLabel('Select Page One Alpha').click({ force: true });
  await expect(page.getByText('1 selected', { exact: true })).toBeVisible();

  await topPagination.getByRole('button', { name: 'Next' }).click();
  await expect(topPagination.getByText('Page 2 of 2', { exact: true })).toBeVisible();
  await expect(bottomPagination.getByText('Page 2 of 2', { exact: true })).toBeVisible();
  await expect(page.getByText('1 selected', { exact: true })).toBeVisible();

  await page.getByLabel('Select Page Two Alpha').click({ force: true });
  await expect(page.getByText('2 selected', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Add to list', exact: true }).click();
  await expect(page.getByText('2 selected movies will be added.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Cross-page list', exact: true }).click();

  await expect.poll(() => bulkPayload).not.toBeNull();
  expect(bulkPayload.movies.map((movie) => movie.tmdb_id)).toEqual(['101', '201']);
});

function libraryItem(path, tmdbId, title) {
  return {
    path,
    filename: path.split('/').pop(),
    title: `${title} (2026)`,
    year: '2026',
    metadata_accepted: true,
    resolution: '1080p',
    rip_source: 'Blu-ray',
    canonical_metadata: {
      accepted: true,
      tmdb_id: String(tmdbId),
      title,
      year: '2026',
      poster_url: '',
      genres: ['Drama'],
      rating: '7.0',
      tmdb_vote_count: 100
    }
  };
}

test('Library keeps selected movies and resolved bulk items across server pages', async ({ page }) => {
  const items = [
    libraryItem('C:/Movies/library-page-one.mkv', 301, 'Library Page One'),
    libraryItem('C:/Movies/library-page-two.mkv', 302, 'Library Page Two')
  ];
  let selectionPayload = null;

  await page.route(libraryCardsRoute, (route) => {
    const requestedPage = Number(route.request().postDataJSON()?.page || new URL(route.request().url()).searchParams.get('page') || 1);
    return route.fulfill({ json: {
      items: [items[requestedPage - 1]],
      count: 1,
      total: 2,
      page: requestedPage,
      total_pages: 2,
      page_start: requestedPage - 1,
      page_end: requestedPage,
      facets: { genres: ['Drama'], sources: ['Blu-ray'], languages: [], countries: [] },
      stats: { total: 2, low: 0, matched: 2, pending: 0, unmatched: 0 },
      catalog_generation: 1
    } });
  });
  await page.route('**/api/library/selection/items', async (route) => {
    selectionPayload = route.request().postDataJSON();
    await route.fulfill({ json: {
      items: items.filter((item) => selectionPayload.paths.includes(item.path)),
      catalog_generation: 1
    } });
  });
  await page.route('**/api/config', (route) => route.fulfill({ json: { show_adult_movies: true } }));
  await page.route('**/api/user/lists', (route) => route.fulfill({ json: {
    lists: [{ id: 'library-list', name: 'Library list', movies: [] }],
    curation_generation: 1
  } }));

  await page.goto('/library', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Library Page One', exact: true })).toBeVisible();
  await page.getByLabel('Select Library Page One').click({ force: true });
  await expect(page.getByText('1 selected', { exact: true })).toBeVisible();

  await page.getByRole('navigation', { name: 'Library pagination' }).first().getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Page 2 of 2', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('1 selected', { exact: true })).toBeVisible();
  await page.getByLabel('Select Library Page Two').click({ force: true });
  await expect(page.getByText('2 selected', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Add to list', exact: true }).click();
  await expect(page.getByText('2 selected movies will be added.', { exact: true })).toBeVisible();
  expect(selectionPayload.paths).toEqual(items.map((item) => item.path));
});

test('Movie Lists keeps selection and source-review payloads across client pages', async ({ page }) => {
  const movies = Array.from({ length: 41 }, (_, index) => discoverMovie(400 + index, `List Movie ${index + 1}`));
  let reviewPayload = null;

  await page.route('**/api/user/lists', (route) => route.fulfill({ json: {
    lists: [{ id: 'long-list', name: 'Long list', movies }],
    curation_generation: 1
  } }));
  await page.route('**/api/library/check', async (route) => {
    const requested = route.request().postDataJSON()?.movies || [];
    await route.fulfill({ json: {
      results: requested.map((movie) => ({ ...movie, found: false })),
      catalog_generation: 1
    } });
  });
  await page.route('**/api/tmdb/card-projections', (route) => route.fulfill({ json: { items: {}, catalog_generation: 1 } }));
  await page.route('**/api/sources/review/preview', async (route) => {
    reviewPayload = route.request().postDataJSON();
    await route.fulfill({ json: { rows: [], blocked: [], defaults: {} } });
  });

  await page.goto('/movie-lists', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'List Movie 1', exact: true })).toBeVisible();
  const topPagination = page.getByRole('navigation', { name: 'Movie list pagination', exact: true });
  const bottomPagination = page.getByRole('navigation', { name: 'Movie list page controls below results', exact: true });
  await expect(topPagination.getByText('Page 1 of 2', { exact: true })).toBeVisible();
  await expect(bottomPagination.getByText('Page 1 of 2', { exact: true })).toBeVisible();
  await page.getByLabel('Select List Movie 1', { exact: true }).click({ force: true });
  await expect(page.getByText('1 selected', { exact: true })).toBeVisible();

  await bottomPagination.getByRole('button', { name: 'Next' }).click();
  await expect(topPagination.getByText('Page 2 of 2', { exact: true })).toBeVisible();
  await expect(bottomPagination.getByText('Page 2 of 2', { exact: true })).toBeVisible();
  await expect(page.getByText('1 selected', { exact: true })).toBeVisible();
  await page.getByLabel('Select List Movie 41').click({ force: true });
  await expect(page.getByText('2 selected', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Find sources', exact: true }).click();
  await expect.poll(() => reviewPayload).not.toBeNull();
  expect(reviewPayload.movies.map((movie) => movie.tmdb_id)).toEqual(['400', '440']);
});

function maintenancePage(pageNumber) {
  const prefix = pageNumber === 1 ? 'page-one' : 'page-two';
  return {
    summary: {
      duplicate_groups: 2,
      reclaimable_size_human: '2.0 GB',
      recommended_removals: 2,
      upgrade_candidates: 0,
      unmatched_files: 0,
      actionable_identities: 0
    },
    storage: {
      groups: [{
        key: `${prefix}-group`,
        title: `${prefix} duplicate`,
        recommended_count: 1,
        files: [
          {
            path: `C:/Movies/${prefix}-keep.mkv`,
            filename: `${prefix}-keep.mkv`,
            recommendation: 'keep',
            verdict_tone: 'success'
          },
          {
            path: `C:/Movies/${prefix}-remove.mkv`,
            filename: `${prefix}-remove.mkv`,
            recommendation: 'recommended',
            verdict_tone: 'warning'
          }
        ]
      }],
      pagination: {
        page: pageNumber,
        total_pages: 2,
        total: 2,
        page_start: pageNumber - 1,
        page_end: pageNumber
      }
    },
    identity: { items: [], pagination: { page: 1, total_pages: 1, total: 0, page_start: 0, page_end: 0 } }
  };
}

test('Maintenance keeps selected paths across pages and previews the complete delete set', async ({ page }) => {
  let deletePreviewPayload = null;

  await page.route('**/api/maintenance/audit**', (route) => {
    const requestedPage = Number(new URL(route.request().url()).searchParams.get('page') || 1);
    return route.fulfill({ json: maintenancePage(requestedPage) });
  });
  await page.route('**/api/ollama/config', (route) => route.fulfill({ json: {} }));
  await page.route('**/api/metadata/smart-match', (route) => route.fulfill({ json: { status: 'idle', providers: { tmdb: true, plex: false } } }));
  await page.route('**/api/delete', async (route) => {
    deletePreviewPayload = route.request().postDataJSON();
    await route.fulfill({ json: {
      preview: true,
      actions: deletePreviewPayload.paths.map((path) => ({ target: path, target_type: 'file' })),
      file_count: deletePreviewPayload.paths.length,
      folder_count: 0
    } });
  });

  await page.goto('/cleanup', { waitUntil: 'domcontentloaded' });
  const pageOneRow = page.locator('.cleanup-file-row').filter({ hasText: 'page-one-remove.mkv' });
  await pageOneRow.locator('input[type="checkbox"]').check();
  await expect(page.getByText('1 selected', { exact: true })).toBeVisible();

  await page.locator('.cleanup-workspace .library-pagination').getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Page 2 of 2', { exact: true })).toBeVisible();
  await expect(page.getByText('2 selected', { exact: true })).toBeVisible();

  const pageTwoRow = page.locator('.cleanup-file-row').filter({ hasText: 'page-two-remove.mkv' });
  await expect(pageTwoRow.locator('input[type="checkbox"]')).toBeChecked();
  await expect(page.getByText('2 selected', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Delete selected (2)', exact: true }).click();
  await expect.poll(() => deletePreviewPayload).not.toBeNull();
  expect(deletePreviewPayload.preview).toBe(true);
  expect(deletePreviewPayload.paths).toEqual([
    'C:/Movies/page-one-remove.mkv',
    'C:/Movies/page-two-remove.mkv'
  ]);
  await expect(page.getByRole('dialog')).toBeVisible();
});
