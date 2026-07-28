import assert from 'node:assert/strict';
import test from 'node:test';

import {
  IPTV_AUTO_SYNC_MAX_AGE_MS,
  shouldAutoSyncIPTVCatalog
} from '../src/features/iptv/iptvSyncPolicy.js';

const NOW = Date.UTC(2026, 6, 26, 12, 0, 0);

function status(overrides = {}) {
  return {
    configured: true,
    last_sync: NOW / 1000,
    sync: { state: 'idle' },
    ...overrides
  };
}

test('requests a sync when no provider catalog has been saved', () => {
  assert.equal(shouldAutoSyncIPTVCatalog(status({ last_sync: 0 }), NOW), true);
});

test('requests a sync when the provider catalog is at least 24 hours old', () => {
  const lastSync = (NOW - IPTV_AUTO_SYNC_MAX_AGE_MS) / 1000;
  assert.equal(shouldAutoSyncIPTVCatalog(status({ last_sync: lastSync }), NOW), true);
});

test('keeps a recent provider catalog without starting another sync', () => {
  const lastSync = (NOW - IPTV_AUTO_SYNC_MAX_AGE_MS + 1) / 1000;
  assert.equal(shouldAutoSyncIPTVCatalog(status({ last_sync: lastSync }), NOW), false);
});

test('does not sync an unconfigured provider or duplicate a running sync', () => {
  assert.equal(shouldAutoSyncIPTVCatalog(status({ configured: false }), NOW), false);
  assert.equal(shouldAutoSyncIPTVCatalog(status({ sync: { state: 'running' } }), NOW), false);
});
