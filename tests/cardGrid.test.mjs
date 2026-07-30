import assert from 'node:assert/strict';
import test from 'node:test';

import {
  countGridTemplateColumns,
  fullRowPageSize
} from '../src/utils/cardGrid.js';

test('fullRowPageSize chooses the closest complete row', () => {
  assert.equal(fullRowPageSize(40, 3), 39);
  assert.equal(fullRowPageSize(40, 2), 40);
  assert.equal(fullRowPageSize(20, 3), 21);
  assert.equal(fullRowPageSize(30, 8), 32);
});

test('fullRowPageSize honors tie bias and API limits', () => {
  assert.equal(fullRowPageSize(5, 2), 4);
  assert.equal(fullRowPageSize(5, 2, { bias: 'higher' }), 6);
  assert.equal(fullRowPageSize(50, 6, { max: 50 }), 48);
});

test('countGridTemplateColumns reads resolved and fixed-repeat tracks', () => {
  assert.equal(countGridTemplateColumns('582.9px 582.9px 582.9px'), 3);
  assert.equal(countGridTemplateColumns('repeat(8, minmax(155px, 1fr))'), 8);
  assert.equal(countGridTemplateColumns('minmax(0px, 1fr) minmax(0px, 1fr)'), 2);
  assert.equal(countGridTemplateColumns('none'), 0);
});
