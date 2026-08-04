import { expect, test } from '@playwright/test';

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function sourceVariant({ title, indexer, seeders, size }) {
  return {
    title,
    indexer,
    seeders,
    size,
    size_human: `${size} GB`,
    resolution: '1080p',
    magnet_url: `magnet:?xt=urn:btih:${encodeURIComponent(title)}`
  };
}

test('keeps an indexer filter active while progressive source results continue arriving', async ({ page }) => {
  const movie = {
    tmdb_id: '90901',
    imdb_id: 'tt0090901',
    title: 'Progressive Filter Movie',
    year: '2026',
    poster_url: '',
    tmdb_rating: '7.5',
    genres: ['Drama'],
    plot: 'A source-search filter regression fixture.'
  };
  const initialYts = sourceVariant({
    title: 'Progressive Filter Movie 2026 1080p YTS',
    indexer: 'YTS',
    seeders: 50,
    size: 2
  });
  const initialOther = sourceVariant({
    title: 'Progressive Filter Movie 2026 1080p Initial Other',
    indexer: 'The Pirate Bay',
    seeders: 40,
    size: 3
  });
  const laterOther = sourceVariant({
    title: 'Progressive Filter Movie 2026 1080p Later Other',
    indexer: '1337x',
    seeders: 30,
    size: 4
  });
  const laterYts = sourceVariant({
    title: 'Progressive Filter Movie 2026 1080p Later YTS',
    indexer: 'YTS',
    seeders: 20,
    size: 1
  });
  const firstPoll = deferred();
  const finalPoll = deferred();
  let statusPolls = 0;

  await page.route('**/api/tmdb/discover**', (route) => route.fulfill({ json: {
    results: [movie],
    page: 1,
    total_pages: 1,
    total_results: 1
  } }));
  await page.route('**/api/library/check', (route) => route.fulfill({ json: {
    results: [{ found: false, tmdb_id: movie.tmdb_id }],
    catalog_generation: 1
  } }));
  await page.route('**/api/tmdb/details**', (route) => route.fulfill({ json: {
    ...movie,
    summary: movie.plot,
    cast: [],
    directors: [],
    writers: [],
    keywords: []
  } }));
  await page.route('**/api/explore/search/jobs', (route) => route.fulfill({ json: {
    search_id: 'progressive-filter-job',
    status: 'running',
    variants: [initialYts, initialOther],
    pending_indexers: ['1337x', 'YTS'],
    searching_indexers: [],
    timed_out_indexers: []
  } }));
  await page.route('**/api/explore/search/jobs/**', async (route) => {
    statusPolls += 1;
    if (statusPolls === 1) {
      await firstPoll.promise;
      await route.fulfill({ json: {
        search_id: 'progressive-filter-job',
        status: 'running',
        variants: [initialYts, initialOther, laterOther],
        pending_indexers: ['YTS'],
        searching_indexers: [],
        timed_out_indexers: []
      } });
      return;
    }
    await finalPoll.promise;
    await route.fulfill({ json: {
      search_id: 'progressive-filter-job',
      status: 'complete',
      variants: [initialYts, initialOther, laterOther, laterYts],
      pending_indexers: [],
      searching_indexers: [],
      timed_out_indexers: []
    } });
  });

  await page.goto('/discover', { waitUntil: 'domcontentloaded' });
  const card = page.locator('.discover-movie-card').filter({ hasText: movie.title });
  await expect(card).toBeVisible();
  await card.click();
  await card.getByRole('button', { name: 'Find sources', exact: true }).click();

  const dialog = page.getByRole('dialog', { name: 'Torrent results' });
  const indexerFilter = dialog.locator('.torrent-filter-row select').nth(1);
  await expect(dialog.getByText(initialYts.title, { exact: true })).toBeVisible();
  await indexerFilter.selectOption('YTS');
  await expect(dialog.getByText(initialOther.title, { exact: true })).toHaveCount(0);

  firstPoll.resolve();
  await expect.poll(() => statusPolls).toBeGreaterThanOrEqual(1);
  await expect(dialog.getByText('Still searching', { exact: true })).toBeVisible();
  await expect(indexerFilter).toHaveValue('YTS');
  await expect(dialog.getByText(initialYts.title, { exact: true })).toBeVisible();
  await expect(dialog.getByText(laterOther.title, { exact: true })).toHaveCount(0);

  finalPoll.resolve();
  await expect.poll(() => statusPolls).toBeGreaterThanOrEqual(2);
  await expect(dialog.getByText(laterYts.title, { exact: true })).toBeVisible();
  await expect(indexerFilter).toHaveValue('YTS');
  await expect(dialog.getByText(initialOther.title, { exact: true })).toHaveCount(0);
  await expect(dialog.getByText(laterOther.title, { exact: true })).toHaveCount(0);
});
