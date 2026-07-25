import assert from 'node:assert/strict';
import test from 'node:test';

import { deletionPlanSummary } from '../src/utils/deletionPlan.js';

test('deletion preview explains complete folders and included sidecars', () => {
  const summary = deletionPlanSummary({
    actions: [{
      target_type: 'folder',
      target: 'E:\\Movies\\Project Hail Mary (2026)',
      paths: ['E:\\Movies\\Project Hail Mary (2026)\\movie.mkv'],
      sidecar_count: 4,
    }]
  });

  assert.match(summary, /1 complete movie folder will move to the Recycle Bin/);
  assert.match(summary, /including 4 sidecar files/);
  assert.match(summary, /E:\\Movies\\Project Hail Mary \(2026\)/);
});

test('deletion preview explains why an individual file keeps its folder', () => {
  const summary = deletionPlanSummary({
    actions: [{
      target_type: 'file',
      target: 'E:\\Movies\\Collection\\movie.mkv',
      paths: ['E:\\Movies\\Collection\\movie.mkv'],
      sidecar_count: 0,
    }]
  });

  assert.match(summary, /1 individual movie file will move to the Recycle Bin/);
  assert.match(summary, /folders will stay because they contain another movie or an unrecognized file/);
});
