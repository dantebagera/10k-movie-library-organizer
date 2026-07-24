import { ChevronDown, Film, Play, Star } from 'lucide-react';
import { useEffect, useState } from 'react';

function cx(...classes) {
  return classes.filter(Boolean).join(' ');
}

function stopCardToggle(event) {
  event.stopPropagation();
}

export function UnifiedMoviePoster({
  title,
  posterUrl,
  large,
  className = '',
  children,
  showPlayOverlay,
  onPlay
}) {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => setImageFailed(false), [posterUrl]);

  return (
    <div className={cx('unified-movie-poster', large && 'unified-movie-poster-large', className)}>
      {posterUrl && !imageFailed ? (
        <img src={posterUrl} alt={`${title} poster`} loading="lazy" onError={() => setImageFailed(true)} />
      ) : (
        <Film size={large ? 42 : 30} />
      )}
      {children}
      {showPlayOverlay && onPlay ? (
        <button
          type="button"
          className="movie-card-play-overlay"
          aria-label={`Play ${title}`}
          title="Play"
          onClick={(event) => {
            event.stopPropagation();
            onPlay();
          }}
        >
          <Play size={34} fill="currentColor" />
        </button>
      ) : null}
    </div>
  );
}

export function UnifiedMovieCard({
  title,
  year,
  posterUrl,
  rating,
  voteCount,
  chips = [],
  mutedChips = [],
  statusLabel = '',
  statusTone = 'neutral',
  ownedBadge = false,
  expanded = false,
  selected = false,
  className = '',
  posterClassName = '',
  bodyClassName = '',
  cornerControls,
  showPlayOverlay = false,
  onPlay,
  onToggle,
  children,
  expandedBody,
  expandedFooter,
  aside
}) {
  const interactive = Boolean(onToggle);
  const displayTitle = title || 'Untitled';
  const titleLength = displayTitle.length;
  const longTitle = titleLength > 28;
  const veryLongTitle = titleLength > 46;

  function handleKeyDown(event) {
    if (!interactive) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onToggle();
    }
  }

  return (
    <article
      className={cx(
        'unified-movie-card',
        expanded && 'unified-movie-card-expanded',
        selected && 'unified-movie-card-selected',
        interactive && 'unified-movie-card-interactive',
        className
      )}
      onClick={onToggle}
      onKeyDown={handleKeyDown}
      tabIndex={interactive ? 0 : undefined}
      aria-expanded={interactive ? Boolean(expanded || selected) : undefined}
    >
      <UnifiedMoviePoster
        title={displayTitle}
        posterUrl={posterUrl}
        className={posterClassName}
        showPlayOverlay={showPlayOverlay}
        onPlay={onPlay}
        large={expanded}
      >
        {cornerControls}
      </UnifiedMoviePoster>

      <div className={cx('unified-movie-body', bodyClassName)}>
        <header className="unified-movie-header">
          <div className="unified-movie-title-block">
            <h3 dir="auto" className={cx(longTitle && 'unified-title-long', veryLongTitle && 'unified-title-very-long')}>
              {displayTitle}
            </h3>
            <span>{year || 'Unknown year'}</span>
          </div>
          <div className="unified-movie-header-meta">
            {rating && expanded ? (
              <div className="unified-expanded-rating" aria-label={`Rating ${rating}${voteCount ? `, ${voteCount}` : ''}`}>
                <span>
                  <Star size={18} fill="currentColor" />
                  <strong>{rating}</strong>
                </span>
                {voteCount ? <small>{voteCount}</small> : null}
              </div>
            ) : null}
            {interactive ? (
              <span className="unified-expand-affordance" aria-hidden="true">
                <ChevronDown size={18} />
              </span>
            ) : null}
          </div>
        </header>

        <div className="unified-chip-row" aria-label="Movie metadata">
          {chips.filter(Boolean).map((chip) => (
            <span className="unified-chip" dir="auto" key={chip}>{chip}</span>
          ))}
          {ownedBadge ? <span className="unified-owned-badge">Owned</span> : null}
          {mutedChips.filter(Boolean).map((chip) => (
            <span className="unified-chip unified-chip-muted" dir="auto" key={chip}>{chip}</span>
          ))}
          {statusLabel ? (
            <span className={cx('unified-status-chip', `unified-status-${statusTone}`)}>{statusLabel}</span>
          ) : null}
        </div>

        <div className="unified-movie-extra" onClick={stopCardToggle}>
          {children}
        </div>

        {expandedBody ? (
          <div className="unified-movie-expanded-body" onClick={stopCardToggle}>
            {expandedBody}
          </div>
        ) : null}

        {rating && !expanded ? (
          <div className="unified-rating-row">
            <span className="unified-rating">
              <Star size={16} fill="currentColor" />
              {rating}{voteCount ? ` - ${voteCount}` : ''}
            </span>
          </div>
        ) : null}
      </div>
      {aside ? (
        <div className="unified-movie-aside" onClick={stopCardToggle}>
          {aside}
        </div>
      ) : null}
      {expandedFooter ? (
        <div className="unified-movie-expanded-row" onClick={stopCardToggle}>
          {expandedFooter}
        </div>
      ) : null}
    </article>
  );
}
