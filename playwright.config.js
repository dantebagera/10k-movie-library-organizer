import { defineConfig } from '@playwright/test';

const port = 5117;
const captureIngestionEvidence = process.env.CP_CAPTURE_INGESTION_EVIDENCE === '1';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 45_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  outputDir: captureIngestionEvidence
    ? './docs/verification/online-library-ingestion/after/playwright-artifacts'
    : './test-results',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    browserName: 'chromium',
    headless: true,
    viewport: { width: 1600, height: 1000 },
    video: captureIngestionEvidence ? 'on' : 'off',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  }
});
