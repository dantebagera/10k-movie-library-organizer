import { Languages, Loader2 } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { fetchTransientMovieLanguage, mergeTransientMovieLanguage } from '../api/movieDetails.js';

export function useTransientMovieLanguage({ movie, details, expanded }) {
  const tmdbId = String(movie?.tmdb_id || details?.tmdb_id || '').trim();
  const [localized, setLocalized] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestId = useRef(0);

  useEffect(() => {
    requestId.current += 1;
    setLocalized(null);
    setLoading(false);
    setError('');
  }, [expanded, tmdbId]);

  async function toggleLanguage() {
    if (localized) {
      requestId.current += 1;
      setLocalized(null);
      setLoading(false);
      setError('');
      return;
    }
    if (!tmdbId || loading) return;

    const activeRequest = requestId.current + 1;
    requestId.current = activeRequest;
    setLoading(true);
    setError('');
    try {
      const data = await fetchTransientMovieLanguage(tmdbId);
      if (requestId.current === activeRequest) setLocalized(data);
    } catch (caught) {
      if (requestId.current === activeRequest) setError(caught.message);
    } finally {
      if (requestId.current === activeRequest) setLoading(false);
    }
  }

  const activeLocalized = expanded ? localized : null;
  const { displayMovie, displayDetails } = mergeTransientMovieLanguage(movie, details, activeLocalized);

  return {
    displayMovie,
    displayDetails,
    isArabic: Boolean(activeLocalized),
    toggleProps: {
      available: Boolean(tmdbId),
      isArabic: Boolean(activeLocalized),
      loading,
      error,
      onToggle: toggleLanguage
    }
  };
}

export function MovieLanguageToggle({ available, isArabic, loading, error, onToggle }) {
  if (!available) return null;
  return (
    <div className="movie-language-toolbar">
      {error ? <small className="movie-language-error">{error}</small> : null}
      <button
        type="button"
        className="mini-action movie-language-toggle"
        onClick={onToggle}
        disabled={loading}
        aria-pressed={isArabic}
      >
        {loading ? <Loader2 size={14} className="spin" /> : <Languages size={14} />}
        {loading ? 'Loading Arabic...' : (isArabic ? 'English' : 'العربية')}
      </button>
    </div>
  );
}
