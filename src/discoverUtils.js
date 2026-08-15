export function discoverMovieKey(movie) {
  return `${String(movie?.title || '').toLowerCase()}|${String(movie?.year || '')}`;
}

function normalizeMovieTitle(title) {
  return String(title || '')
    .toLowerCase()
    .replace(/[³ł]/g, ' ')
    .replace(/[²]/g, ' ')
    .replace(/[^\w\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function discoverIdentityKey(movie) {
  if (movie?.movie_key) return String(movie.movie_key);
  if (movie?.tmdb_id) return `tmdb:${String(movie.tmdb_id)}`;
  if (movie?.imdb_id) return `imdb:${String(movie.imdb_id).toLowerCase()}`;
  if (movie?.path) return `path:${String(movie.path).toLowerCase()}`;
  return `title:${normalizeMovieTitle(movie?.title)}|${String(movie?.year || '')}`;
}

export function discoverMoviePayload(movie, owned) {
  const ownedItem = owned?.canonical_card || owned?.library_item || {};
  const canonical = ownedItem.canonical_metadata || {};
  return {
    movie_key: String(canonical.movie_key || owned?.movie_key || movie?.movie_key || ''),
    tmdb_id: String(canonical.tmdb_id || owned?.tmdb_id || movie?.tmdb_id || ''),
    imdb_id: String(canonical.imdb_id || owned?.imdb_id || movie?.imdb_id || ''),
    plex_guid: String(canonical.plex_guid || owned?.plex_guid || movie?.plex_guid || ''),
    title: canonical.title || movie?.title || owned?.title || '',
    year: String(canonical.year || movie?.year || owned?.year || ''),
    release_date: movie?.release_date || '',
    poster_url: movie?.poster_url || '',
    path: owned?.path || movie?.path || ''
  };
}

export function listsForDiscoverMovie(movie, lists = [], owned) {
  const key = discoverIdentityKey(discoverMoviePayload(movie, owned));
  return lists.filter((list) => (
    (list.movies || []).some((listMovie) => discoverIdentityKey(listMovie) === key)
  ));
}

export function buildOwnershipMap(results = []) {
  const map = {};
  for (const item of results) {
    if (item?.found && item.path) {
      for (const key of ownershipKeys(item)) {
        map[key] = item;
      }
    }
  }
  return map;
}

export function replaceOwnershipScope(ownership = {}, movies = [], results = []) {
  const scopeKeys = new Set((movies || []).flatMap((movie) => ownershipKeys(movie)));
  const retained = Object.fromEntries(
    Object.entries(ownership || {}).filter(([key, value]) => (
      !scopeKeys.has(key)
      && !ownershipKeys(value).some((valueKey) => scopeKeys.has(valueKey))
    ))
  );
  return { ...retained, ...buildOwnershipMap(results) };
}

export function removeOwnershipPaths(ownership = {}, paths = []) {
  const removed = new Set((paths || []).map((path) => String(path || '').toLowerCase()).filter(Boolean));
  if (!removed.size) return ownership;
  return Object.fromEntries(
    Object.entries(ownership || {}).filter(([, value]) => (
      !removed.has(String(value?.path || '').toLowerCase())
    ))
  );
}

export function ownershipKeys(movie = {}) {
  const keys = [];
  if (movie.movie_key) keys.push(String(movie.movie_key));
  if (movie.tmdb_id) keys.push(`tmdb:${String(movie.tmdb_id)}`);
  if (movie.imdb_id) keys.push(`imdb:${String(movie.imdb_id).toLowerCase()}`);
  if (movie.plex_guid) keys.push(`plex:${String(movie.plex_guid).toLowerCase()}`);
  const title = normalizeMovieTitle(movie.title);
  const year = String(movie.year || '').trim();
  if (title && year) keys.push(`${String(movie.title || '').toLowerCase()}|${year}`);
  if (title && year) keys.push(`title:${title}|${year}`);
  return [...new Set(keys)];
}

export function ownedMovieFor(movie, ownership = {}) {
  const keys = ownershipKeys(movie);
  const strongKeys = keys.filter((key) => /^(?:tmdb|imdb|plex):/.test(key));
  for (const key of strongKeys) {
    if (ownership[key]) return ownership[key];
  }
  if (strongKeys.length) return null;
  for (const key of keys) {
    if (ownership[key]) return ownership[key];
  }
  return null;
}

export function canonicalOwnedMovie(movie = {}, owned = null) {
  const ownedItem = owned?.canonical_card || owned?.library_item || {};
  const canonical = ownedItem.canonical_metadata || {};
  if (!canonical.accepted) return movie;
  return {
    ...movie,
    movie_key: canonical.movie_key || owned?.movie_key || movie.movie_key,
    title: canonical.title || movie.title,
    year: canonical.year || movie.year,
    tmdb_id: canonical.tmdb_id || movie.tmdb_id,
    imdb_id: canonical.imdb_id || movie.imdb_id,
    poster_url: canonical.poster_url || movie.poster_url,
    genres: canonical.genres || movie.genres,
    plot: canonical.summary || canonical.plot || movie.plot || '',
    summary: canonical.summary || canonical.plot || movie.summary || '',
    tmdb_rating: canonical.rating || movie.tmdb_rating,
    tmdb_vote_count: canonical.tmdb_vote_count ?? movie.tmdb_vote_count,
    language: canonical.language || movie.language,
    country: canonical.country || movie.country,
    country_flag: canonical.country_flag || movie.country_flag,
    release_date: canonical.release_date || movie.release_date,
    runtime: canonical.runtime || movie.runtime,
    tagline: canonical.tagline || movie.tagline,
    collection: canonical.collection || movie.collection,
    cast: canonical.cast || movie.cast,
    directors: canonical.directors || movie.directors,
    detail_provider: canonical.detail_provider || movie.detail_provider,
  };
}

export function resolutionRank(resolution) {
  const value = String(resolution || '').toLowerCase();
  if (value.includes('2160') || value.includes('4k')) return 4;
  if (value.includes('1080')) return 3;
  if (value.includes('720')) return 2;
  if (value.includes('480')) return 1;
  return 0;
}

export function sortTorrentVariants(variants = []) {
  return [...variants].sort((a, b) => (
    resolutionRank(b.resolution) - resolutionRank(a.resolution)
    || Number(b.seeders || 0) - Number(a.seeders || 0)
    || String(a.indexer || '').localeCompare(String(b.indexer || ''))
  ));
}

export function hasTmdbMetadata(metadata = {}) {
  return Boolean(
    metadata.tmdb_id
    || metadata.poster_url
    || metadata.plot
    || metadata.tmdb_rating
    || (Array.isArray(metadata.genres) && metadata.genres.length)
  );
}

export function filterEnrichedIndexerResults(results = []) {
  return results
    .map((row) => {
      const metadata = row.metadata || {};
      const variants = sortTorrentVariants(row.variants || []);
      const best = variants[0] || {};
      return {
        ...row,
        ...metadata,
        title: metadata.title || row.parsed_title || row.title || '',
        year: metadata.year || row.parsed_year || row.year || '',
        parsed_title: row.parsed_title || metadata.title || '',
        parsed_year: row.parsed_year || metadata.year || '',
        variants,
        best_resolution: best.resolution || row.best_resolution || 'Unknown',
        best_seeders: Number(best.seeders || row.best_seeders || 0),
        indexer: best.indexer || row.indexer || ''
      };
    });
}
