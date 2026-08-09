function normalizedTitle(value) {
  return String(value || '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function candidateYear(candidate) {
  return String(candidate?.year || candidate?.release_date || '').slice(0, 4);
}

export function parseHomeTrailerTitle(value) {
  const sourceTitle = String(value || '').normalize('NFKC').trim();
  const parenthesizedYears = [...sourceTitle.matchAll(/\(((?:19|20)\d{2})\)/g)];
  const looseYears = [...sourceTitle.matchAll(/\b((?:19|20)\d{2})\b/g)];
  const year = parenthesizedYears.at(-1)?.[1] || looseYears.at(-1)?.[1] || '';
  let title = sourceTitle
    .replace(/\|.*$/, ' ')
    .replace(/\(((?:19|20)\d{2})\)/g, ' ')
    .replace(/#[\p{L}\p{N}_-]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  const markers = [...title.matchAll(/\b(?:trailer|teaser|featurette|clip)\b/gi)];
  if (markers.length) {
    title = title.slice(0, markers.at(-1).index).trim();
    let previous = '';
    while (title && title !== previous) {
      previous = title;
      title = title
        .replace(/(?:[-–—:]\s*)?(?:official|final|exclusive|teaser|comic[- ]con)\s*$/i, '')
        .replace(/(?:[-–—:]\s*)?\d+(?:st|nd|rd|th)\s+anniversary\s*$/i, '')
        .trim();
    }
  }

  title = title.replace(/\s*[-–—:]\s*$/, '').replace(/\s+/g, ' ').trim();
  return { sourceTitle, title, year };
}

export function mergeTrailerMovieCandidates(...groups) {
  const merged = new Map();
  for (const candidate of groups.flat()) {
    const tmdbId = String(candidate?.tmdb_id || '');
    if (!tmdbId || merged.has(tmdbId)) continue;
    merged.set(tmdbId, candidate);
  }
  return [...merged.values()];
}

export function selectConfidentTrailerMovie(hint, candidates = []) {
  const queryTitle = normalizedTitle(hint?.title);
  if (!queryTitle) return { movie: null, reason: 'missing_title' };

  const exactTitleCandidates = candidates.filter((candidate) => (
    normalizedTitle(candidate?.title) === queryTitle
  ));
  if (!exactTitleCandidates.length) return { movie: null, reason: 'no_exact_title' };

  const expectedYear = String(hint?.year || '').slice(0, 4);
  if (expectedYear) {
    const sameYear = exactTitleCandidates.filter((candidate) => candidateYear(candidate) === expectedYear);
    if (sameYear.length === 1) return { movie: sameYear[0], reason: 'exact_title_year' };
    if (sameYear.length > 1) return { movie: null, reason: 'ambiguous_title_year' };

    const nearbyYear = exactTitleCandidates.filter((candidate) => {
      const year = candidateYear(candidate);
      return year && Math.abs(Number(year) - Number(expectedYear)) === 1;
    });
    if (nearbyYear.length === 1) return { movie: nearbyYear[0], reason: 'exact_title_nearby_year' };
    if (nearbyYear.length > 1) return { movie: null, reason: 'ambiguous_nearby_year' };

    const missingYear = exactTitleCandidates.filter((candidate) => !candidateYear(candidate));
    if (exactTitleCandidates.length === 1 && missingYear.length === 1) {
      return { movie: missingYear[0], reason: 'exact_title_provider_year_missing' };
    }
    return { movie: null, reason: 'year_conflict' };
  }

  if (exactTitleCandidates.length === 1) {
    return { movie: exactTitleCandidates[0], reason: 'unique_exact_title' };
  }
  return { movie: null, reason: 'ambiguous_title' };
}
