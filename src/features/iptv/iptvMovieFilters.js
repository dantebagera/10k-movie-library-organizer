export const IPTV_MOVIE_SORTS = [
  ['recent', 'Recently added'],
  ['title', 'Title'],
  ['rating', 'Rating'],
  ['year-newest', 'Year: newest'],
  ['year-oldest', 'Year: oldest']
];

export const IPTV_MOVIE_VIEWS = [
  ['provider', 'Provider View'],
  ['cp', 'CP View']
];

export const IPTV_MOVIE_CATEGORIES = [
  ['film', 'Film'],
  ['sports', 'Sports'],
  ['plays', 'Plays'],
  ['music', 'Music'],
  ['misc', 'Misc']
];

const MAX_FILTER_LENGTH = 512;
const MOVIE_VIEW_IDS = new Set(IPTV_MOVIE_VIEWS.map(([id]) => id));
const MOVIE_CATEGORY_IDS = new Set(IPTV_MOVIE_CATEGORIES.map(([id]) => id));
const MOVIE_SORT_IDS = new Set(IPTV_MOVIE_SORTS.map(([id]) => id));

function boundedText(value, maximum = MAX_FILTER_LENGTH) {
  if (!['string', 'number'].includes(typeof value)) return '';
  return String(value).slice(0, maximum);
}

function boundedInteger(value, fallback, minimum, maximum) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(maximum, Math.max(minimum, Math.trunc(parsed)));
}

export function normalizeIPTVMovieSearchQuery(value) {
  return boundedText(value).normalize('NFKC').trim();
}

export function createIPTVMovieFilters() {
  return {
    view: 'provider',
    category: '',
    q: '',
    playlist_id: '',
    list_id: '',
    genre_id: '',
    language: '',
    country: '',
    year_from: '',
    year_to: '',
    min_rating: '',
    metadata_status: '',
    quality: '',
    dubbed: false,
    subtitled: false,
    watched: '',
    sort: 'recent'
  };
}

export function iptvMovieIdentity(value, explicitYear = '') {
  const rawTitle = String(value || '').trim();
  const yearMatch = rawTitle.match(/[\[(]\s*(19\d{2}|20\d{2}|21\d{2})\s*[\])]/);
  const explicitMatch = String(explicitYear || '').match(/\b(19\d{2}|20\d{2}|21\d{2})\b/);
  const title = rawTitle
    .replace(/[\[(]\s*(?:19\d{2}|20\d{2}|21\d{2})\s*[\])]/g, ' ')
    .replace(/\b(?:2160p|1080p|720p|4k|uhd|fhd|hdcam|camrip|web[- .]?dl|webrip|bluray|brrip|hdrip|x26[45]|hevc)\b/gi, ' ')
    .replace(/\s+/g, ' ')
    .replace(/[|\-–—:]+\s*$/, '')
    .trim();
  return {
    title: title || rawTitle,
    year: explicitMatch?.[1] || yearMatch?.[1] || ''
  };
}

export function iptvMovieQuery(filters, page, pageSize) {
  const source = { ...createIPTVMovieFilters(), ...(filters || {}) };
  return {
    view: MOVIE_VIEW_IDS.has(source.view) ? source.view : 'provider',
    category: MOVIE_CATEGORY_IDS.has(source.category) ? source.category : '',
    q: normalizeIPTVMovieSearchQuery(source.q),
    playlist_id: boundedText(source.playlist_id),
    list_id: boundedText(source.list_id),
    genre_id: boundedText(source.genre_id),
    language: boundedText(source.language),
    country: boundedText(source.country),
    year_from: boundedText(source.year_from, 4),
    year_to: boundedText(source.year_to, 4),
    min_rating: boundedText(source.min_rating, 8),
    metadata_status: boundedText(source.metadata_status, 64),
    quality: boundedText(source.quality, 64),
    dubbed: source.dubbed ? 1 : '',
    subtitled: source.subtitled ? 1 : '',
    watched: boundedText(source.watched, 32),
    sort: MOVIE_SORT_IDS.has(source.sort) ? source.sort : 'recent',
    page: boundedInteger(page, 1, 1, Number.MAX_SAFE_INTEGER),
    page_size: boundedInteger(pageSize || 30, 30, 1, 100)
  };
}

export function iptvMovieQuerySignature(providerId, filters, page, pageSize, generation = 0) {
  return JSON.stringify({
    provider_id: boundedText(providerId),
    generation: boundedInteger(generation, 0, 0, Number.MAX_SAFE_INTEGER),
    query: iptvMovieQuery(filters, page, pageSize)
  });
}
