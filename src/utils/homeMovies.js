function homeMovieKey(movie) {
  const tmdbId = String(movie?.tmdb_id || movie?.id || '').trim();
  if (tmdbId) return `tmdb:${tmdbId}`;
  return [
    String(movie?.title || '').trim().toLocaleLowerCase(),
    String(movie?.year || '').trim()
  ].join('|');
}

function localDateKey(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function buildUpcomingHomeMovies(results, excludedMovies = [], now = new Date()) {
  const excluded = new Set((excludedMovies || []).map(homeMovieKey));
  const seen = new Set();
  const today = localDateKey(now);

  return (results || [])
    .filter((movie) => {
      const key = homeMovieKey(movie);
      const releaseDate = String(movie?.release_date || '').trim();
      if (!key || seen.has(key) || excluded.has(key) || releaseDate < today) return false;
      seen.add(key);
      return true;
    })
    .sort((left, right) => (
      String(left.release_date || '').localeCompare(String(right.release_date || ''))
      || Number(right.popularity || 0) - Number(left.popularity || 0)
      || String(left.title || '').localeCompare(String(right.title || ''))
    ));
}

export function uniqueHomeMovies(...groups) {
  const seen = new Set();
  return groups.flat().filter((movie) => {
    const key = homeMovieKey(movie);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
