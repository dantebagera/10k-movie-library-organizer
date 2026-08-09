import { CalendarDays, ChevronDown, Film, Loader2, MoreHorizontal, Play, RotateCcw, Star, X } from 'lucide-react';
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
  onPlay,
  playPending = false
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
          className={cx('movie-card-play-overlay', playPending && 'movie-card-play-overlay-pending')}
          aria-label={playPending ? `Opening ${title} in Cinema Paradiso Player` : `Play ${title}`}
          aria-busy={playPending || undefined}
          title={playPending ? 'Opening player…' : 'Play'}
          disabled={playPending}
          onClick={(event) => {
            event.stopPropagation();
            onPlay();
          }}
        >
          {playPending
            ? <Loader2 size={30} className="spin" />
            : <Play size={34} fill="currentColor" />}
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
  headerActions,
  metadataActions,
  showPlayOverlay = false,
  onPlay,
  playPending = false,
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
        playPending={playPending}
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
            {headerActions ? (
              <span className="unified-header-actions" onClick={stopCardToggle}>
                {headerActions}
              </span>
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
          {mutedChips.map((chip, index) => {
            const label = typeof chip === 'object' ? chip?.label : chip;
            if (!label) return null;
            const tone = typeof chip === 'object' ? chip?.tone : '';
            return (
              <span
                className={cx('unified-chip', 'unified-chip-muted', tone && `unified-chip-${tone}`)}
                dir="auto"
                key={`${label}-${index}`}
              >
                {label}
              </span>
            );
          })}
          {statusLabel ? (
            <span className={cx('unified-status-chip', `unified-status-${statusTone}`)}>{statusLabel}</span>
          ) : null}
          {metadataActions ? (
            <div className="unified-chip-row-actions" onClick={stopCardToggle}>
              {metadataActions}
            </div>
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

export function ContinueMovieCard({
  title,
  posterUrl,
  progress = 0,
  remainingLabel,
  onResume,
  onRestart,
  onRemove
}) {
  const displayTitle = title || 'Untitled';
  const boundedProgress = Math.max(0, Math.min(1, Number(progress) || 0));

  return (
    <article className="continue-movie-card">
      <UnifiedMoviePoster
        title={displayTitle}
        posterUrl={posterUrl}
        className="continue-movie-poster"
        showPlayOverlay
        onPlay={onResume}
      >
        <details className="continue-movie-menu" onClick={stopCardToggle}>
          <summary role="button" aria-label={`More options for ${displayTitle}`} title="More options">
            <MoreHorizontal size={17} />
          </summary>
          <div>
            <button
              type="button"
              onClick={(event) => {
                event.currentTarget.closest('details')?.removeAttribute('open');
                onRestart();
              }}
            >
              <RotateCcw size={14} /> Restart
            </button>
            <button
              type="button"
              onClick={(event) => {
                event.currentTarget.closest('details')?.removeAttribute('open');
                onRemove();
              }}
            >
              <X size={14} /> Remove
            </button>
          </div>
        </details>
      </UnifiedMoviePoster>
      <div
        className="continue-movie-progress"
        role="progressbar"
        aria-label={`${displayTitle} playback progress`}
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={Math.round(boundedProgress * 100)}
      >
        <span style={{ width: `${boundedProgress * 100}%` }} />
      </div>
      <h3 dir="auto" title={displayTitle}>{displayTitle}</h3>
      <p>{remainingLabel}</p>
    </article>
  );
}

export function UpcomingMovieCard({
  title,
  posterUrl,
  releaseLabel,
  selected = false,
  onSelect
}) {
  const displayTitle = title || 'Untitled';

  return (
    <button
      type="button"
      className={cx('upcoming-movie-card', selected && 'upcoming-movie-card-selected')}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Inspect ${displayTitle}${releaseLabel ? `, ${releaseLabel}` : ''}`}
    >
      <UnifiedMoviePoster
        title={displayTitle}
        posterUrl={posterUrl}
        className="upcoming-movie-poster"
      />
      <span className="upcoming-movie-copy">
        <strong dir="auto" title={displayTitle}>{displayTitle}</strong>
        <small><CalendarDays size={13} /> {releaseLabel || 'Release date pending'}</small>
      </span>
    </button>
  );
}
