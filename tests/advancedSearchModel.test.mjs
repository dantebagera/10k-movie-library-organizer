import assert from 'node:assert/strict';
import test from 'node:test';

import {
  compileDiscoverSimpleQuery,
  compileLibrarySimpleQuery,
  createEmptyQuery,
  normalizeAdvancedQuery,
  querySignature,
  withCriterion,
  withGroupJoin,
  withoutCriterionValue
} from '../src/features/search/advancedSearchModel.js';
import { ADVANCED_SEARCH_LIMITS, criteriaForScope } from '../src/features/search/advancedSearchRegistry.js';

test('normalization produces a stable reordered signature and removes exact duplicates', () => {
  const left = normalizeAdvancedQuery({
    version: 1,
    scope: 'library',
    mode: 'advanced',
    groups: [
      { type: 'year', values: [{ operator: 'between', from: 2000, to: 2020 }] },
      { type: 'genre', join: 'or', values: [{ id: '53', label: 'Thriller' }, { id: '18', label: 'Drama' }, { id: '53', label: 'Thriller' }] }
    ],
    sort: { key: 'rating', direction: 'desc' }
  });
  const right = {
    ...left,
    groups: [...left.groups].reverse().map((group) => ({ ...group, values: [...group.values].reverse() }))
  };
  assert.equal(querySignature(left), querySignature(right));
  assert.equal(left.groups.find((group) => group.type === 'genre').values.length, 2);
});

test('different person roles remain distinct and same-type join is explicit', () => {
  let query = createEmptyQuery('library');
  query = withCriterion(query, 'person', { id: '500', label: 'Example Person', role: 'actor' });
  query = withCriterion(query, 'person', { id: '500', label: 'Example Person', role: 'director' });
  query = withGroupJoin(query, 'person', 'and');
  assert.equal(query.groups[0].join, 'and');
  assert.deepEqual(query.groups[0].values.map((value) => value.role), ['actor', 'director']);
  query = withoutCriterionValue(query, 'person', 0);
  assert.equal(query.groups[0].values[0].role, 'director');
});

test('simple Library state compiles to the shared model', () => {
  const query = compileLibrarySimpleQuery({
    query: 'Alien', resolution: '1080p', source: 'Blu-ray', genre: 'Horror', language: 'English', country: 'US',
    yearFrom: '1979', yearTo: '1979', minRating: '7', viewingState: 'unwatched', sort: 'year-desc'
  });
  assert.equal(query.mode, 'simple');
  assert.deepEqual(query.groups.map((group) => group.type), ['title', 'genre', 'year', 'rating', 'language', 'country', 'viewing_status', 'resolution', 'library_source']);
});

test('simple Discover state keeps its feed and bounded criteria', () => {
  const query = compileDiscoverSimpleQuery({
    query: 'Alien', feed: 'catalog', genre: '27', genreLabel: 'Horror', language: 'en', languageLabel: 'English',
    country: 'US', countryLabel: 'United States', minimumVotes: '500', yearFrom: '1979', minRating: '6',
    availability: 'owned', sort: 'vote_average.desc'
  });
  assert.equal(query.feed, 'catalog');
  assert.equal(query.groups.find((group) => group.type === 'availability').values[0].id, 'owned');
});

test('malformed, unsupported, excessive, and reversed requests fail', () => {
  assert.throws(() => normalizeAdvancedQuery({ version: 2, scope: 'library', groups: [] }), /version/);
  assert.throws(() => normalizeAdvancedQuery({ ...createEmptyQuery('library'), groups: [{ type: 'minimum_votes', values: [{ value: 1 }] }] }), /not supported/);
  assert.throws(() => normalizeAdvancedQuery({ ...createEmptyQuery('library'), groups: [{ type: 'year', values: [{ operator: 'between', from: 2020, to: 2000 }] }] }), /reversed/);
  assert.throws(() => normalizeAdvancedQuery({ ...createEmptyQuery('discover'), groups: [{ type: 'keyword', values: Array.from({ length: 11 }, (_value, index) => ({ id: String(index), label: `Keyword ${index}` })) }] }), /per-group/);
});

test('registry omits unprovable first-release roles and Library vote count', () => {
  const library = criteriaForScope('library');
  const discover = criteriaForScope('discover');
  assert.deepEqual(library.find((criterion) => criterion.type === 'person').roles, ['actor', 'director', 'writer']);
  assert.equal(library.some((criterion) => criterion.type === 'minimum_votes'), false);
  assert.equal(discover.some((criterion) => criterion.type === 'minimum_votes'), true);
});

test('execution identity ignores editor mode and presentation labels', () => {
  const advanced = normalizeAdvancedQuery({
    ...createEmptyQuery('library'),
    mode: 'advanced',
    groups: [{ type: 'genre', join: 'or', values: [{ id: '18', label: 'Drama' }] }]
  });
  const simple = normalizeAdvancedQuery({
    ...advanced,
    mode: 'simple',
    groups: [{ type: 'genre', join: 'or', values: [{ id: '18', label: 'Localized Drama Label' }] }]
  });
  assert.equal(querySignature(advanced), querySignature(simple));
});

test('shared logical page size is capped at 100', () => {
  assert.equal(ADVANCED_SEARCH_LIMITS.pageSize, 100);
});
