import { Clapperboard, Film, PenLine } from 'lucide-react';
import { useState } from 'react';

function PersonPortrait({ person }) {
  const profileUrl = String(person?.profile_url || '').trim();
  const [failedUrl, setFailedUrl] = useState('');

  if (profileUrl && failedUrl !== profileUrl) {
    return (
      <img
        src={profileUrl}
        alt={`${person.name} profile`}
        loading="lazy"
        onError={() => setFailedUrl(profileUrl)}
      />
    );
  }

  return <div className="person-search-avatar"><Film size={24} /></div>;
}

export default function PersonSearchCard({ person, meta, knownFor = [], roles = [], onOpenFilmography }) {
  const canBrowseActing = roles.includes('actor');
  const canBrowseDirecting = roles.includes('director');
  const canBrowseWriting = roles.includes('writer');

  return (
    <article className="person-search-card">
      <PersonPortrait person={person} />
      <div className="person-search-copy">
        <h3>{person.name}</h3>
        <span>{meta}</span>
        {knownFor.length > 0 && <p>{knownFor.join(' · ')}</p>}
      </div>
      <div className="person-search-actions">
        {canBrowseActing && (
          <button type="button" className="btn btn-secondary" onClick={() => onOpenFilmography(person, 'actor')}>
            <Film size={15} /> Acting credits
          </button>
        )}
        {canBrowseDirecting && (
          <button type="button" className="btn btn-secondary" onClick={() => onOpenFilmography(person, 'director')}>
            <Clapperboard size={15} /> Directed films
          </button>
        )}
        {canBrowseWriting && (
          <button type="button" className="btn btn-secondary" onClick={() => onOpenFilmography(person, 'writer')}>
            <PenLine size={15} /> Written films
          </button>
        )}
      </div>
    </article>
  );
}
