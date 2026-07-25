import { ArrowRight, Tags } from 'lucide-react';

export default function KeywordSearchCard({ keyword, scope, meta, onOpen }) {
  const isLibrary = scope === 'library';
  const actionLabel = isLibrary ? 'View owned movies' : 'Discover movies';

  return (
    <article className="keyword-search-card">
      <div className="keyword-search-icon" aria-hidden="true">
        <Tags size={22} />
      </div>
      <div className="keyword-search-copy">
        <h3>{keyword.name}</h3>
        <span>{meta || (isLibrary ? 'Stored keyword' : 'TMDB keyword')}</span>
      </div>
      <button type="button" className="btn btn-secondary" onClick={() => onOpen(keyword)}>
        {actionLabel} <ArrowRight size={15} />
      </button>
    </article>
  );
}
