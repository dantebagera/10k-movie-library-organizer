import assert from 'node:assert/strict';
import test from 'node:test';

import {
  mergeTrailerMovieCandidates,
  parseHomeTrailerTitle,
  selectConfidentTrailerMovie
} from '../src/utils/homeTrailers.js';

test('parseHomeTrailerTitle removes Rotten Tomatoes marketing suffixes', () => {
  const cases = [
    ['Insidious: Out of the Further Final Trailer (2026)', 'Insidious: Out of the Further', '2026'],
    ['The Last Blossom Trailer #1 (2026)', 'The Last Blossom', '2026'],
    ['Your Name 10th Anniversary Trailer (2026)', 'Your Name', '2026'],
    ['The Dog Stars Teaser - Tickets on Sale (2026)', 'The Dog Stars', '2026'],
    ['Bad Lieutenant: Tokyo Teaser Trailer (2026)', 'Bad Lieutenant: Tokyo', '2026'],
    ['Matchbox The Movie Comic-Con Trailer (2026) | #SDCC #SDCC2026', 'Matchbox The Movie', '2026'],
    ['One Night Only Exclusive Featurette - Monica & Callum (2026)', 'One Night Only', '2026'],
    ['Trailer Park Boys Official Trailer (2006)', 'Trailer Park Boys', '2006']
  ];

  for (const [source, title, year] of cases) {
    assert.deepEqual(parseHomeTrailerTitle(source), { sourceTitle: source, title, year });
  }
});

test('selectConfidentTrailerMovie accepts exact identities and rejects risky collisions', () => {
  const exact = { tmdb_id: 1, title: 'The Thomas Crown Affair', year: '2027' };
  assert.equal(
    selectConfidentTrailerMovie({ title: 'The Thomas Crown Affair', year: '2027' }, [exact]).movie,
    exact
  );

  const missingYear = { tmdb_id: 2, title: 'Bad Lieutenant: Tokyo', year: '' };
  assert.equal(
    selectConfidentTrailerMovie({ title: 'Bad Lieutenant: Tokyo', year: '2026' }, [missingYear]).movie,
    missingYear
  );

  const anniversary = { tmdb_id: 3, title: 'Your Name.', year: '2016' };
  assert.equal(
    selectConfidentTrailerMovie({ title: 'Your Name', year: '2026' }, [anniversary]).movie,
    null
  );

  const duplicates = [
    { tmdb_id: 4, title: 'One Night Only', year: '2026' },
    { tmdb_id: 5, title: 'One Night Only', year: '2026' }
  ];
  assert.equal(
    selectConfidentTrailerMovie({ title: 'One Night Only', year: '2026' }, duplicates).movie,
    null
  );
});

test('mergeTrailerMovieCandidates preserves provider order and removes duplicate ids', () => {
  assert.deepEqual(
    mergeTrailerMovieCandidates(
      [{ tmdb_id: 1, title: 'First' }],
      [{ tmdb_id: 1, title: 'Duplicate' }, { tmdb_id: 2, title: 'Second' }]
    ).map((movie) => movie.title),
    ['First', 'Second']
  );
});
