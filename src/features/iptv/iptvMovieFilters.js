export const IPTV_MOVIE_SORTS = [
  ['recent', 'Recently added'],
  ['title', 'Title'],
  ['rating', 'Rating'],
  ['year-newest', 'Year: newest'],
  ['year-oldest', 'Year: oldest']
];

export function createIPTVMovieFilters() {
  return {
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
    ...source,
    dubbed: source.dubbed ? 1 : '',
    subtitled: source.subtitled ? 1 : '',
    page: Math.max(1, Number(page || 1)),
    page_size: Math.min(100, Math.max(1, Number(pageSize || 30)))
  };
}
