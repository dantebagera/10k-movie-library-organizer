export function splitLibraryTitle(title) {
  const raw = String(title || '');
  const match = raw.match(/\s+\((\d{4})\)$/);
  return {
    title: match ? raw.slice(0, match.index) : raw,
    year: match ? match[1] : ''
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

export function isLowQuality(resolution) {
  return resolutionRank(resolution) < 3;
}

export function matchesLibraryResolutionFilter(resolution, filter) {
  const rank = resolutionRank(resolution);
  if (filter === 'all') return true;
  if (filter === '4k') return rank === 4;
  if (filter === '1080p') return rank === 3;
  if (filter === '720p') return rank === 2;
  if (filter === 'below-720p') return rank < 2;
  return true;
}

export function getMovieIdentity(item) {
  const canonical = item?.canonical_metadata || {};
  if (canonical.accepted && canonical.title) {
    return {
      title: canonical.title,
      year: String(canonical.year || '').trim()
    };
  }
  const parsed = splitLibraryTitle(item?.title);
  const plexTitle = String(item?.plex_title || '').trim();
  const title = plexTitle || parsed.title || String(item?.filename || '').replace(/\.[^.]+$/, '');
  const year = String(item?.plex_year || parsed.year || '').trim();
  return { title, year };
}

export function getTmdbCacheKey(item) {
  const identity = getMovieIdentity(item);
  const canonical = item?.canonical_metadata || {};
  return canonical?.tmdb_id ? `tmdb:${canonical.tmdb_id}` : item?.tmdb_id ? `tmdb:${item.tmdb_id}` : `${identity.title}|${identity.year}`;
}

export function normalizePersonName(name) {
  return String(name || '').trim().toLowerCase();
}

export function peopleMatch(person, filter) {
  if (!person || !filter) return false;
  const personId = String(person.id || '');
  const filterId = String(filter.id || '');
  if (personId && filterId) return personId === filterId;
  return normalizePersonName(person.name) === normalizePersonName(filter.name);
}

export function mergePeople(primary, fallback) {
  if (!primary.length) return fallback;
  if (!fallback.length) return primary;
  const merged = primary.map((person) => {
    const richMatch = fallback.find((candidate) => normalizePersonName(candidate.name) === normalizePersonName(person.name));
    if (!richMatch) return person;
    return {
      ...richMatch,
      ...person,
      id: person.id || richMatch.id,
      profile_url: person.profile_url || richMatch.profile_url,
      character: person.character || richMatch.character
    };
  });
  const existing = new Set(merged.map((person) => normalizePersonName(person.name)));
  fallback.forEach((person) => {
    const key = normalizePersonName(person.name);
    if (key && !existing.has(key)) {
      merged.push(person);
      existing.add(key);
    }
  });
  return merged;
}

export function getStoredRolePeople(item, role) {
  const canonical = item?.canonical_metadata || {};
  if (role === 'director') {
    return canonical.directors?.length ? canonical.directors : item?.plex_directors || [];
  }
  if (role === 'writer') {
    return canonical.writers || [];
  }
  return canonical.cast?.length ? canonical.cast : item?.plex_cast || [];
}

export function getRolePeople(item, details, role) {
  if (role === 'director') {
    const tmdbDirectors = details?.directors?.length ? details.directors : details?.director?.name ? [details.director] : [];
    return mergePeople(getStoredRolePeople(item, role), tmdbDirectors);
  }
  if (role === 'writer') {
    return mergePeople(getStoredRolePeople(item, role), details?.writers || []);
  }
  return mergePeople(getStoredRolePeople(item, role), details?.cast || []);
}

export function itemMatchesRoleFilter(item, details, filter) {
  if (!filter) return true;
  const people = filter.localOnly ? getStoredRolePeople(item, filter.role) : getRolePeople(item, details, filter.role);
  return people.some((person) => peopleMatch(person, filter));
}

function normalizePersonSearchText(value) {
  return normalizePersonName(value).replace(/[^a-z0-9]/g, '');
}

export function buildLibraryPeopleIndex(items = [], query = '') {
  const queryText = normalizePersonSearchText(query);
  const people = new Map();

  for (const item of items || []) {
    if (!item?.canonical_metadata?.accepted) continue;
    const identity = getMovieIdentity(item);
    const movieKey = item.path ? `path:${String(item.path).toLowerCase()}` : movieIdentityKey(moviePayload(item));
    for (const role of ['actor', 'director', 'writer']) {
      for (const person of getStoredRolePeople(item, role)) {
        const name = String(person?.name || '').trim();
        if (!name) continue;
        const id = String(person.id || person.tmdb_id || '').trim();
        const nameKey = normalizePersonSearchText(name);
        if (!nameKey) continue;
        const key = id ? `id:${id}` : `name:${nameKey}`;
        const entry = people.get(key) || {
          id,
          name,
          profile_url: String(person.profile_url || '').trim(),
          roles: new Set(),
          movies: new Map(),
          localIdentity: !id
        };
        if (!entry.profile_url && person.profile_url) {
          entry.profile_url = String(person.profile_url).trim();
        }
        entry.roles.add(role);
        entry.movies.set(movieKey, { title: identity.title || 'Untitled', year: identity.year || '' });
        people.set(key, entry);
      }
    }
  }

  const identifiedByName = new Map();
  for (const person of people.values()) {
    if (!person.id) continue;
    const nameKey = normalizePersonSearchText(person.name);
    const matches = identifiedByName.get(nameKey) || [];
    matches.push(person);
    identifiedByName.set(nameKey, matches);
  }
  for (const [key, person] of people.entries()) {
    if (person.id) continue;
    const matches = identifiedByName.get(normalizePersonSearchText(person.name)) || [];
    if (matches.length !== 1) continue;
    const identified = matches[0];
    if (!identified.profile_url && person.profile_url) identified.profile_url = person.profile_url;
    person.roles.forEach((role) => identified.roles.add(role));
    person.movies.forEach((movie, movieKey) => identified.movies.set(movieKey, movie));
    people.delete(key);
  }

  return [...people.values()]
    .filter((person) => !queryText || normalizePersonSearchText(person.name).includes(queryText))
    .map((person) => ({
      id: person.id,
      name: person.name,
      profile_url: person.profile_url,
      roles: [...person.roles].sort(),
      movieCount: person.movies.size,
      knownFor: [...person.movies.values()]
        .sort((left, right) => left.title.localeCompare(right.title))
        .slice(0, 3)
        .map((movie) => movie.year ? `${movie.title} (${movie.year})` : movie.title),
      localIdentity: person.localIdentity
    }))
    .sort((left, right) => right.movieCount - left.movieCount || left.name.localeCompare(right.name));
}

export function normalizeCollectionTitle(title) {
  return String(title || '')
    .toLowerCase()
    .replace(/[³ł]/g, ' 3 ')
    .replace(/[²]/g, ' 2 ')
    .replace(/\b(directors?|special|extended|theatrical|ultimate|final|anniversary|edition|cut|dc)\b/g, ' ')
    .replace(/[^\w\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function itemMatchesCollectionFilter(item, details, filter) {
  if (!filter) return true;
  if (Array.isArray(filter.owned_paths)) {
    const ownedPaths = new Set(filter.owned_paths.map((path) => String(path || '').toLowerCase()));
    return ownedPaths.has(String(item?.path || '').toLowerCase());
  }
  if (details?.collection?.id && String(details.collection.id) === String(filter.id)) return true;
  const identity = getMovieIdentity(item);
  const itemTitle = normalizeCollectionTitle(identity.title);
  const itemYear = String(identity.year || '');
  return (filter.parts || []).some((part) => {
    if (item?.tmdb_id && part.tmdb_id && String(item.tmdb_id) === String(part.tmdb_id)) return true;
    const partTitle = normalizeCollectionTitle(part.title);
    const partYear = String(part.year || '');
    return itemTitle === partTitle && (!partYear || !itemYear || partYear === itemYear);
  });
}

export function moviePayload(item) {
  const identity = getMovieIdentity(item);
  const canonical = item?.canonical_metadata || {};
  return {
    tmdb_id: String(canonical.tmdb_id || item?.tmdb_id || ''),
    imdb_id: String(canonical.imdb_id || item?.imdb_id || ''),
    plex_guid: String(canonical.plex_guid || item?.plex_guid || ''),
    title: identity.title || item?.title || '',
    year: identity.year || String(item?.year || '').trim(),
    path: item?.path || '',
    poster_url: canonical.poster_url || item?.plex_poster || item?.poster_url || ''
  };
}

export function movieIdentityKey(movie) {
  if (movie?.tmdb_id) return `tmdb:${movie.tmdb_id}`;
  if (movie?.path) return `path:${String(movie.path).toLowerCase()}`;
  return `title:${normalizeCollectionTitle(movie?.title)}|${String(movie?.year || '')}`;
}

export function movieIdentityKeys(movie) {
  const keys = [];
  if (movie?.tmdb_id) keys.push(`tmdb:${movie.tmdb_id}`);
  if (movie?.imdb_id) keys.push(`imdb:${String(movie.imdb_id).toLowerCase()}`);
  if (movie?.plex_guid) keys.push(`plex:${String(movie.plex_guid).toLowerCase()}`);
  if (movie?.path) keys.push(`path:${String(movie.path).toLowerCase()}`);
  const title = normalizeCollectionTitle(movie?.title);
  const year = String(movie?.year || '').trim();
  if (title && year) keys.push(`title:${title}|${year}`);
  return [...new Set(keys)];
}

export function moviesShareIdentity(left, right) {
  const leftTmdb = String(left?.tmdb_id || '');
  const rightTmdb = String(right?.tmdb_id || '');
  if (leftTmdb && rightTmdb && leftTmdb !== rightTmdb) return false;

  const leftImdb = String(left?.imdb_id || '').toLowerCase();
  const rightImdb = String(right?.imdb_id || '').toLowerCase();
  if (leftImdb && rightImdb && leftImdb !== rightImdb) return false;

  const leftPlex = String(left?.plex_guid || '').toLowerCase();
  const rightPlex = String(right?.plex_guid || '').toLowerCase();
  if (leftPlex && rightPlex && leftPlex !== rightPlex) return false;

  const rightKeys = new Set(movieIdentityKeys(right));
  return movieIdentityKeys(left).some((key) => rightKeys.has(key));
}

export function applyPosterOverrideToLibraryItems(items, selectedItem, posterUrl, override) {
  const selectedMovie = moviePayload(selectedItem);
  return (items || []).map((candidate) => {
    if (!moviesShareIdentity(selectedMovie, moviePayload(candidate))) return candidate;
    return {
      ...candidate,
      canonical_metadata: {
        ...(candidate.canonical_metadata || {}),
        poster_url: posterUrl,
        poster_override: Boolean(override?.id),
        poster_override_source: override?.source || '',
        poster_override_locked: Boolean(override?.id)
      }
    };
  });
}

export function listsForItem(item, lists) {
  const keys = new Set(movieIdentityKeys(moviePayload(item)));
  return (lists || []).filter((list) => (
    (list.movies || []).some((movie) => movieIdentityKeys(movie).some((key) => keys.has(key)))
  ));
}

export function listLibraryCoverage(items = [], list = null) {
  const movies = list?.movies || [];
  if (!list || !movies.length) {
    return { total: 0, matched: 0, missingCount: 0, missingMovies: [] };
  }
  const libraryKeys = new Set();
  for (const item of items || []) {
    for (const key of movieIdentityKeys(moviePayload(item))) {
      libraryKeys.add(key);
    }
  }
  const missingMovies = [];
  for (const movie of movies) {
    const matched = movieIdentityKeys(movie).some((key) => libraryKeys.has(key));
    if (!matched) missingMovies.push(movie);
  }
  return {
    total: movies.length,
    matched: movies.length - missingMovies.length,
    missingCount: missingMovies.length,
    missingMovies
  };
}

export function buildMovieListViewModel({
  libraryItems = [],
  list = null,
  query = '',
  statusFilter = 'all'
} = {}) {
  const ownership = new Map();
  for (const item of libraryItems || []) {
    const payload = moviePayload(item);
    for (const key of movieIdentityKeys(payload)) {
      if (!ownership.has(key)) ownership.set(key, item);
    }
  }

  const normalizedQuery = String(query || '').trim().toLowerCase();
  const rows = (list?.movies || []).map((movie) => {
    const ownedItem = movieIdentityKeys(movie).map((key) => ownership.get(key)).find(Boolean) || null;
    const ownedPayload = ownedItem ? moviePayload(ownedItem) : null;
    const upgrade = Boolean(ownedItem?.maintenance_upgrade_candidate);
    const title = ownedPayload?.title || movie.title || 'Untitled';
    const year = ownedPayload?.year || String(movie.year || '').trim();
    const poster = ownedItem ? (ownedPayload?.poster_url || '') : (movie.poster_url || '');
    return {
      ...movie,
      movie: {
        ...movie,
        title,
        year,
        poster_url: poster
      },
      title,
      year,
      poster_url: poster,
      ownedItem,
      ownedPayload,
      status: ownedItem ? (upgrade ? 'upgrade' : 'owned') : 'missing',
      upgrade,
      quality: ownedItem ? getQualityLabel(ownedItem) : 'Missing from Library',
      identityKey: movieIdentityKey(movie)
    };
  });

  const stats = {
    total: rows.length,
    owned: rows.filter((row) => row.ownedItem).length,
    missing: rows.filter((row) => !row.ownedItem).length,
    upgrades: rows.filter((row) => row.upgrade).length
  };

  const filteredRows = rows.filter((row) => {
    if (normalizedQuery) {
      const haystack = [row.title, row.year, row.quality].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(normalizedQuery)) return false;
    }
    if (statusFilter === 'owned') return row.status === 'owned';
    if (statusFilter === 'missing') return row.status === 'missing';
    if (statusFilter === 'upgrade') return row.status === 'upgrade';
    return true;
  });

  return { rows: filteredRows, allRows: rows, stats };
}

export function movieHasSystemState(item, lists, systemType) {
  return listsForItem(item, lists).some((list) => (
    list.system_type === systemType || list.id === systemType
  ));
}

export function buildLibraryViewModel({
  items = [],
  pageSize = 40,
  currentPage = 1,
  query = '',
  qualityFilter = 'all',
  identityFilter = '',
  plexFilter = 'all',
  sortMode = 'added',
  genreFilter = 'all',
  resolutionFilter = 'all',
  sourceFilter = 'all',
  languageFilter = 'all',
  countryFilter = 'all',
  yearFrom = '',
  yearTo = '',
  minRating = 'all',
  sizeFilter = 'all',
  mode = 'movie',
  roleFilter = null,
  collectionFilter = null,
  listFilter = null,
  lists = [],
  viewingStateFilter = 'all',
  tmdbCache = {},
  showAdultMovies = true
} = {}) {
  const fileIdentityFilter = identityFilter || plexFilter;
  const normalizedQuery = query.trim().toLowerCase();
  const result = items.filter((item) => {
    const canonical = item.canonical_metadata || {};
    if (mode === 'movie' && !canonical.accepted) return false;
    if (mode === 'movie' && !showAdultMovies && canonical.adult) return false;
    const identity = getMovieIdentity(item);
    const rating = Number(canonical.rating || item.plex_rating || 0);
    const year = Number(identity.year || 0);
    if (normalizedQuery) {
      const haystack = [
        identity.title,
        identity.year,
        item.filename,
        item.path,
        canonical.summary || canonical.plot || item.plex_summary,
        (canonical.genres?.length ? canonical.genres : item.plex_genres || []).join(' ')
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(normalizedQuery)) return false;
    }
    if (qualityFilter === 'upgrade' && item.maintenance_upgrade_candidate !== true) return false;
    if (qualityFilter === 'good' && resolutionRank(item.resolution) < 3) return false;
    if (qualityFilter === '4k' && resolutionRank(item.resolution) !== 4) return false;
    if (!matchesLibraryResolutionFilter(item.resolution, resolutionFilter)) return false;
    if (sourceFilter !== 'all' && item.rip_source !== sourceFilter) return false;
    if (genreFilter !== 'all' && !(canonical.genres?.length ? canonical.genres : item.plex_genres || []).includes(genreFilter)) return false;
    if (languageFilter !== 'all' && (canonical.language || item.plex_language) !== languageFilter) return false;
    if (countryFilter !== 'all' && (canonical.country_flag || canonical.country || item.plex_country_flag || item.plex_country) !== countryFilter) return false;
    if (mode === 'file' && fileIdentityFilter === 'matched' && !item.metadata_accepted) return false;
    if (mode === 'file' && fileIdentityFilter === 'unmatched' && item.metadata_accepted) return false;
    if (mode === 'movie' && minRating !== 'all' && rating < Number(minRating)) return false;
    if (mode === 'movie' && yearFrom && (!year || year < Number(yearFrom))) return false;
    if (mode === 'movie' && yearTo && (!year || year > Number(yearTo))) return false;
    if (mode === 'file' && sizeFilter === 'small' && Number(item.size || 0) > 1.5 * 1024 * 1024 * 1024) return false;
    if (mode === 'file' && sizeFilter === 'large' && Number(item.size || 0) < 6 * 1024 * 1024 * 1024) return false;
    const details = tmdbCache[getTmdbCacheKey(item)];
    if (mode === 'movie' && roleFilter && !itemMatchesRoleFilter(item, details, roleFilter)) return false;
    if (mode === 'movie' && collectionFilter && !itemMatchesCollectionFilter(item, details, collectionFilter)) return false;
    if (mode === 'movie' && listFilter && !listsForItem(item, [listFilter]).length) return false;
    if (mode === 'movie' && viewingStateFilter !== 'all') {
      const watched = movieHasSystemState(item, lists, 'watched');
      const watchlisted = movieHasSystemState(item, lists, 'watchlist');
      if (viewingStateFilter === 'watched' && !watched) return false;
      if (viewingStateFilter === 'unwatched' && watched) return false;
      if (viewingStateFilter === 'watchlist' && !watchlisted) return false;
    }
    return true;
  });

  const filteredItems = [...result];
  filteredItems.sort((a, b) => {
    const aIdentity = getMovieIdentity(a);
    const bIdentity = getMovieIdentity(b);
    if (sortMode === 'rating') return Number(b.plex_rating || 0) - Number(a.plex_rating || 0) || aIdentity.title.localeCompare(bIdentity.title);
    if (sortMode === 'added') return Number(b.added_time || b.modified_time || 0) - Number(a.added_time || a.modified_time || 0) || aIdentity.title.localeCompare(bIdentity.title);
    if (sortMode === 'year-desc') return Number(bIdentity.year || 0) - Number(aIdentity.year || 0) || aIdentity.title.localeCompare(bIdentity.title);
    if (sortMode === 'year-asc') return Number(aIdentity.year || 0) - Number(bIdentity.year || 0) || aIdentity.title.localeCompare(bIdentity.title);
    if (sortMode === 'quality') return resolutionRank(b.resolution) - resolutionRank(a.resolution) || aIdentity.title.localeCompare(bIdentity.title);
    if (sortMode === 'size') return Number(b.size || 0) - Number(a.size || 0) || a.filename.localeCompare(b.filename);
    if (sortMode === 'identity' || sortMode === 'plex') return Number(Boolean(b.metadata_accepted)) - Number(Boolean(a.metadata_accepted)) || a.filename.localeCompare(b.filename);
    if (sortMode === 'source') return String(a.rip_source || '').localeCompare(String(b.rip_source || '')) || a.filename.localeCompare(b.filename);
    if (sortMode === 'filename') return a.filename.localeCompare(b.filename);
    return aIdentity.title.localeCompare(bIdentity.title);
  });

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const pageStart = filteredItems.length ? (safePage - 1) * pageSize : 0;
  const pageEnd = Math.min(pageStart + pageSize, filteredItems.length);
  const visibleItems = filteredItems.slice(pageStart, pageEnd);
  const stats = {
    total: items.length,
    low: items.filter((item) => isLowQuality(item.resolution)).length,
    matched: items.filter((item) => item.canonical_metadata?.accepted).length,
    pending: items.filter((item) => item.metadata_status === 'pending').length,
    unmatched: items.filter((item) => !item.canonical_metadata?.accepted && item.metadata_status !== 'pending').length
  };

  return {
    filteredItems,
    totalPages,
    safePage,
    pageStart,
    pageEnd,
    visibleItems,
    stats
  };
}

export function getLocaleTag(item) {
  const canonical = item?.canonical_metadata || {};
  const countryMap = {
    'United States of America': 'US',
    'United States': 'US',
    'United Kingdom': 'UK',
    'Republic of Korea': 'KR',
    'South Korea': 'KR',
    France: 'FR',
    Germany: 'DE',
    Italy: 'IT',
    Spain: 'ES',
    Japan: 'JP',
    China: 'CN',
    Canada: 'CA',
    Australia: 'AU',
    Netherlands: 'NL',
    India: 'IN',
    Egypt: 'EG'
  };
  const languageMap = {
    English: 'EN',
    Korean: 'KO',
    French: 'FR',
    German: 'DE',
    Italian: 'IT',
    Spanish: 'ES',
    Japanese: 'JA',
    Chinese: 'ZH',
    Hindi: 'HI',
    Arabic: 'AR',
    Dutch: 'NL'
  };
  const rawCountry = String(canonical.country_flag || canonical.country || item?.plex_country_flag || item?.plex_country || '').trim();
  const rawLanguage = String(canonical.language || item?.plex_language || '').trim();
  const country = countryMap[rawCountry] || (rawCountry.length <= 3 ? rawCountry.toUpperCase() : rawCountry.slice(0, 2).toUpperCase());
  const language = languageMap[rawLanguage] || (rawLanguage.length <= 3 ? rawLanguage.toUpperCase() : rawLanguage.slice(0, 2).toUpperCase());
  if (country && language) return `${country} / ${language}`;
  return country || language || '';
}

export function getQualityLabel(item) {
  return [item?.resolution, item?.rip_source].filter((part) => part && part !== 'Unknown').join(' ') || 'Unknown quality';
}

export function rootLabel(path) {
  const value = String(path || '').replace(/[\\/]+$/, '');
  const parts = value.split(/[\\/]+/).filter(Boolean);
  return parts.length ? `Root: ${parts[parts.length - 1]}` : 'Library root';
}
