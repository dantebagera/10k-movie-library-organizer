import {
  AlertTriangle, Bell, Bookmark, BookOpen, Check, Clapperboard, ExternalLink, Film, Loader2,
  FileText, MonitorPlay, Pencil, Play, RefreshCcw, Search, Sparkles, Trash2, Wand2, X
} from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { fetchJson } from '../api/client.js';
import { mergeCanonicalMovieDetails } from '../api/movieDetails.js';
import SelectionCheckbox from './SelectionCheckbox.jsx';
import { MovieLanguageToggle, useTransientMovieLanguage } from './MovieLanguageToggle.jsx';
import { UnifiedMovieCard } from './movie-card/MovieCard.jsx';
import { cx, formatCount } from '../utils/appUtils.js';
import {
  getCompactQualityLabel, getLocaleTag, getMovieIdentity, getRolePeople
} from '../utils/libraryUtils.js';
import {
  formatReleaseDateLabel, formatVoteCount, isUnreleasedMovie
} from '../utils/moviePresentation.js';
import { canonicalOwnedMovie } from '../discoverUtils.js';

function usePendingPlay(onPlay, path) {
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);

  const play = useCallback(async () => {
    if (!onPlay || !path || pendingRef.current) return null;
    pendingRef.current = true;
    setPending(true);
    try {
      return await onPlay(path);
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }, [onPlay, path]);

  return { pending, play };
}

function MoviePlayButton({ pending, onPlay }) {
  return (
    <button
      type="button"
      className="btn btn-primary btn-green movie-play-action"
      onClick={onPlay}
      disabled={pending}
      aria-busy={pending || undefined}
    >
      {pending ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
      {pending ? 'Opening player…' : 'Play'}
    </button>
  );
}

export function PosterEditButton({ title, onEdit }) {
  if (!onEdit) return null;
  return (
    <button
      type="button"
      className="poster-edit-trigger"
      aria-label={`Edit poster for ${title || 'movie'}`}
      title="Edit poster"
      onClick={(event) => {
        event.stopPropagation();
        onEdit();
      }}
    >
      <Pencil size={17} />
    </button>
  );
}

export function OwnedFileDetailsButton({ owned, onOpenFileDetails }) {
  const ownedItem = owned?.canonical_card || owned?.library_item || owned;
  if (!ownedItem?.path || !onOpenFileDetails) return null;
  return (
    <button type="button" className="btn btn-secondary" onClick={() => onOpenFileDetails(ownedItem)}>
      <FileText size={15} /> File details
    </button>
  );
}

export function PosterStateControls({
  title,
  watched,
  watchlisted,
  onToggleWatched,
  onToggleWatchlist,
  notify
}) {
  if (!onToggleWatched && !onToggleWatchlist) return null;
  return (
    <>
      {onToggleWatched && (
        <button
          type="button"
          className={cx('poster-state-control', 'poster-state-watched', watched && 'poster-state-control-active')}
          aria-label={watched ? `Mark ${title} as unwatched` : `Mark ${title} as watched`}
          title={watched ? 'Mark as unwatched' : 'Mark as watched'}
          onClick={(event) => {
            event.stopPropagation();
            onToggleWatched();
          }}
        >
          <Check size={17} />
        </button>
      )}
      {onToggleWatchlist && (
        <button
          type="button"
          className={cx('poster-state-control', 'poster-state-watchlist', watchlisted && 'poster-state-control-active')}
          aria-label={watchlisted ? `Remove ${title} from watchlist` : `Add ${title} to watchlist`}
          title={watchlisted ? 'Remove from watchlist' : 'Add to watchlist'}
          onClick={(event) => {
            event.stopPropagation();
            onToggleWatchlist();
          }}
        >
          <Bookmark size={16} fill={watchlisted ? 'currentColor' : 'none'} />
        </button>
      )}
    </>
  );
}

export function DiscoverMovieCard({
  movie,
  reason,
  owned,
  followed,
  expanded,
  details,
  collection,
  collectionStatus,
  collectionError,
  itemLists,
  onPlay,
  onStream,
  streamingAvailable,
  streamingLabel,
  onFindTorrent,
  onFollow,
  onTrailer,
  onToggleDetails,
  onPersonBrowse,
  onCollectionBrowse,
  onCollectionRetry,
  onListBrowse,
  onEditLists,
  onRemoveFromList,
  onEditPoster,
  onOpenFileDetails,
  watched,
  watchlisted,
  onToggleWatched,
  onToggleWatchlist,
  selected,
  onSelect
}) {
  const ownedItem = owned?.canonical_card || owned?.library_item || {};
  const ownedCanonical = ownedItem.canonical_metadata || {};
  const baseDisplayMovie = canonicalOwnedMovie(movie, owned);
  const baseDisplayDetails = ownedCanonical.accepted ? {
    ...mergeCanonicalMovieDetails(ownedCanonical, details || {}),
    loading: details?.loading,
    error: details?.error,
    trailer_url: details?.trailer_url || ownedCanonical.trailer_url || ''
  } : details;
  const languageView = useTransientMovieLanguage({
    movie: baseDisplayMovie,
    details: baseDisplayDetails,
    expanded
  });
  const displayMovie = languageView.displayMovie;
  const displayDetails = languageView.displayDetails;
  const displayCollection = languageView.isArabic && displayDetails?.collection?.id
    ? { ...(collection || {}), ...displayDetails.collection }
    : (collection?.id ? collection : displayMovie.collection || {});
  const lowQuality = Boolean(owned?.maintenance_upgrade_candidate);
  const unreleased = !owned && isUnreleasedMovie(displayMovie);
  const ownedPath = owned?.path || '';
  const playAction = usePendingPlay(onPlay, ownedPath);
  return (
    <UnifiedMovieCard
      className={cx('discover-movie-card', expanded && 'discover-card-expanded')}
      title={displayMovie.title}
      year={displayMovie.year}
      posterUrl={displayMovie.poster_url}
      rating={displayMovie.tmdb_rating}
      voteCount={formatVoteCount(displayMovie.tmdb_vote_count)}
      chips={(displayMovie.genres || []).slice(0, 2)}
      mutedChips={[
        displayMovie.language,
        displayMovie.country_flag || displayMovie.country,
        {
          label: expanded ? displayDetails?.certification || displayMovie.certification : '',
          tone: 'certification'
        },
        owned ? getCompactQualityLabel(ownedItem) : ''
      ]}
      statusLabel={owned ? (lowQuality ? 'Upgrade candidate' : '') : (unreleased ? 'Unreleased' : (followed ? '' : 'Not in library'))}
      statusTone={owned ? (lowQuality ? 'warning' : 'neutral') : (unreleased ? 'warning' : 'missing')}
      following={followed}
      ownedBadge={Boolean(owned)}
      expanded={expanded}
      onToggle={onToggleDetails}
      headerActions={expanded ? (
        <MovieImdbLink
          imdbId={displayDetails?.imdb_id || displayMovie.imdb_id}
          title={displayMovie.title}
        />
      ) : null}
      metadataActions={expanded ? (
        <MovieLanguageToggle {...languageView.toggleProps} />
      ) : null}
      showPlayOverlay={Boolean(owned)}
      onPlay={ownedPath ? playAction.play : undefined}
      playPending={playAction.pending}
      cornerControls={(
        <>
          <PosterStateControls
            title={displayMovie.title}
            watched={watched}
            watchlisted={watchlisted}
            onToggleWatched={owned ? onToggleWatched : undefined}
            onToggleWatchlist={onToggleWatchlist}
          />
          <PosterEditButton title={displayMovie.title} onEdit={owned ? onEditPoster : undefined} />
          <SelectionCheckbox
            className="discover-selection-checkbox"
            checked={Boolean(selected)}
            onChange={onSelect}
            label={`Select ${displayMovie.title}`}
          />
        </>
      )}
      expandedBody={expanded ? (
        <MovieExpandedCuration
          movie={displayMovie}
          details={displayDetails}
          collection={displayCollection}
          collectionStatus={collectionStatus}
          collectionError={collectionError}
          itemLists={itemLists}
          onCollectionBrowse={onCollectionBrowse}
          onCollectionRetry={onCollectionRetry}
          onListBrowse={onListBrowse}
          onEditLists={onEditLists}
          onRemoveFromList={onRemoveFromList}
        />
      ) : null}
      expandedFooter={expanded ? (
        <MovieExpandedDetails
          details={displayDetails}
          directors={displayMovie.directors}
          cast={displayMovie.cast}
          onPersonBrowse={onPersonBrowse}
        />
      ) : null}
    >
      {expanded && (
        <>
          {reason && <p className="ai-reason"><Sparkles size={14} /> {reason}</p>}
          <p className="movie-card-plot discover-plot-visible" dir={languageView.isArabic ? 'rtl' : undefined}>
            {displayMovie.summary || displayMovie.plot || 'No plot summary is available yet.'}
          </p>
          <MovieKeywordRow keywords={displayDetails?.keywords || displayMovie.keywords} />
          <div className="card-actions">
            {owned ? (
              <>
                <MoviePlayButton pending={playAction.pending} onPlay={playAction.play} />
                <OwnedFileDetailsButton owned={ownedItem} onOpenFileDetails={onOpenFileDetails} />
                {lowQuality && (
                  <button type="button" className="btn btn-secondary" onClick={() => onFindTorrent(displayMovie, true)}>
                    <Wand2 size={15} /> Find upgrade
                  </button>
                )}
              </>
            ) : (
              <>
                {!unreleased && (
                  <button type="button" className="btn btn-primary" onClick={() => onFindTorrent(movie)}>
                    <Search size={15} /> Find sources
                  </button>
                )}
                {!unreleased && streamingAvailable && (
                  <button type="button" className="btn btn-secondary btn-green-outline" onClick={() => onStream(movie)}>
                    <MonitorPlay size={15} /> {streamingLabel}
                  </button>
                )}
              </>
            )}
            <button type="button" className="btn btn-secondary" onClick={() => onTrailer(displayMovie)}>
              <Film size={15} /> Trailer
            </button>
            {!owned && (
              <button type="button" className="btn btn-secondary" onClick={() => onFollow(movie)}>
                <Bell size={15} /> {followed ? 'Following' : 'Follow'}
              </button>
            )}
          </div>
          <MovieExpandedFacts movie={displayMovie} details={displayDetails} />
        </>
      )}
    </UnifiedMovieCard>
  );
}

export function MovieExpandedFacts({ movie, details }) {
  const releaseDate = movie?.release_date || details?.release_date || '';
  const releaseDateLabel = isUnreleasedMovie({ release_date: releaseDate }) ? formatReleaseDateLabel(releaseDate) : '';
  const writers = (details?.writers || movie?.writers || []).filter((writer) => writer?.name);
  const visibleWriters = writers.slice(0, 2);
  const remainingWriters = Math.max(0, writers.length - visibleWriters.length);

  if (!details?.tagline && !details?.runtime && !releaseDateLabel && !writers.length) return null;

  return (
    <div className="movie-expanded-facts">
      {releaseDateLabel || details?.tagline ? (
        <div className="movie-expanded-primary-facts">
          {releaseDateLabel && <div><span>Release date</span><strong>Releases {releaseDateLabel}</strong></div>}
          {details?.tagline && <div><span>Tagline</span><strong dir="auto">{details.tagline}</strong></div>}
        </div>
      ) : null}
      {writers.length ? (
        <div className="movie-expanded-writers">
          <span>Writer{writers.length === 1 ? '' : 's'}</span>
          <strong dir="auto">
            {visibleWriters.map((writer) => writer.name).join(', ')}
            {remainingWriters ? ` +${remainingWriters} more` : ''}
          </strong>
        </div>
      ) : null}
      {details?.runtime ? (
        <div className="movie-expanded-runtime">
          <span>Runtime</span>
          <strong>{details.runtime} min</strong>
        </div>
      ) : null}
    </div>
  );
}

export function MovieKeywordRow({ keywords = [] }) {
  const normalizedKeywords = keywords
    .map((keyword) => typeof keyword === 'string' ? keyword : keyword?.name)
    .filter(Boolean);
  if (!normalizedKeywords.length) return null;
  const visibleKeywords = normalizedKeywords.slice(0, 4);
  const remainingKeywords = normalizedKeywords.length - visibleKeywords.length;

  return (
    <div className="movie-keyword-row" aria-label="Movie keywords">
      <span className="movie-keyword-label">Keywords</span>
      {visibleKeywords.map((keyword) => (
        <span className="movie-keyword-chip" dir="auto" key={keyword}>{keyword}</span>
      ))}
      {remainingKeywords > 0 ? <span className="movie-keyword-more">+{remainingKeywords}</span> : null}
    </div>
  );
}

export function MovieImdbLink({ imdbId, title }) {
  const normalizedId = String(imdbId || '').trim();
  if (!/^tt\d+$/i.test(normalizedId)) return null;
  return (
    <a
      className="movie-imdb-link"
      href={`https://www.imdb.com/title/${encodeURIComponent(normalizedId)}/`}
      target="_blank"
      rel="noreferrer"
      aria-label={`Open ${title || 'movie'} on IMDb`}
      title="Open on IMDb"
    >
      IMDb <ExternalLink size={12} />
    </a>
  );
}

export function MovieExpandedCuration({
  movie,
  details,
  collection,
  collectionStatus = 'empty',
  collectionError = '',
  itemLists = [],
  onCollectionBrowse,
  onCollectionRetry,
  onListBrowse,
  onEditLists,
  onRemoveFromList,
  onEditCollection,
  onResetCollection,
  emptyListText = 'Not in any user list yet.'
}) {
  const activeCollection = collection?.id ? collection : details?.collection || {};
  const canBrowseCollection = Boolean(onCollectionBrowse);
  const canBrowseLists = Boolean(onListBrowse);
  const collectionTotal = Array.isArray(activeCollection.parts) ? activeCollection.parts.length : null;
  const collectionOwned = Number.isFinite(activeCollection.owned_count) ? activeCollection.owned_count : null;
  const collectionDetail = ['idle', 'loading'].includes(collectionStatus)
    ? 'Loading collection...'
    : collectionStatus === 'error'
      ? 'Collection details unavailable'
      : collectionTotal !== null && collectionTotal > 0 && collectionOwned !== null
        ? `${formatCount(collectionTotal)} movies • ${formatCount(collectionOwned)} owned`
        : collectionTotal !== null && collectionTotal > 0
          ? `${formatCount(collectionTotal)} movies`
          : collectionOwned !== null
            ? `${formatCount(collectionOwned)} owned`
            : 'Collection members unavailable';

  return (
    <aside className="movie-expanded-curation" aria-label="Collection and lists">
      {activeCollection?.id && (
        <div className="collection-panel">
          {canBrowseCollection ? (
            <button
              type="button"
              className="collection-main-action"
              onClick={() => onCollectionBrowse(activeCollection)}
              aria-busy={collectionStatus === 'loading'}
            >
              <Clapperboard size={17} />
              <span>
                <strong dir="auto">{activeCollection.name}</strong>
                <small>{collectionDetail}</small>
              </span>
            </button>
          ) : null}
          {(collectionStatus === 'error' && onCollectionRetry) || onEditCollection ? (
            <div className="collection-actions">
              {collectionStatus === 'error' && onCollectionRetry ? (
                <button
                  type="button"
                  className="mini-action"
                  onClick={onCollectionRetry}
                  title={collectionError || 'Retry loading collection details'}
                >
                  <RefreshCcw size={13} /> Retry
                </button>
              ) : null}
              {onEditCollection ? (
                <button type="button" className="mini-action" onClick={() => onEditCollection(activeCollection)}>Edit</button>
              ) : null}
              {activeCollection.is_edited && onResetCollection ? (
                <button type="button" className="mini-action mini-action-danger" onClick={() => onResetCollection(activeCollection)}>
                  <RefreshCcw size={13} /> Reset
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
      <div className="lists-panel">
        <div className="lists-panel-header">
          <span className="mini-label">Lists</span>
          {onEditLists ? <button type="button" className="mini-action" onClick={onEditLists}>Add to list</button> : null}
        </div>
        {itemLists.length ? (
          <div className="list-chip-row">
            {itemLists.map((list) => (
              <span className="list-chip" key={list.id}>
                <button type="button" onClick={canBrowseLists ? () => onListBrowse(list) : undefined}>{list.name}</button>
                {onRemoveFromList ? (
                  <button type="button" aria-label={`Remove ${movie.title} from ${list.name}`} onClick={() => onRemoveFromList(list.id)}>
                    <Trash2 size={13} />
                  </button>
                ) : null}
              </span>
            ))}
          </div>
        ) : (
          <small>{emptyListText}</small>
        )}
      </div>
    </aside>
  );
}

export function MovieExpandedDetails({
  details,
  directors,
  cast,
  onPersonBrowse,
  onPersonDiscover
}) {
  const [personBio, setPersonBio] = useState(null);
  const loading = details?.loading;
  const expandedDirectors = directors?.length ? directors : details?.directors?.length ? details.directors : details?.director?.name ? [details.director] : [];
  const expandedCast = (cast?.length ? cast : details?.cast || []).slice(0, 8);
  const canBrowsePeople = Boolean(onPersonBrowse);
  const personFilmographyAction = onPersonDiscover || onPersonBrowse;

  async function openPersonBio(role, person) {
    if (!person?.id) {
      setPersonBio({ loading: false, error: 'No TMDB person ID is available for this credit.', person, role });
      return;
    }
    setPersonBio({ loading: true, error: '', person, role });
    try {
      const data = await fetchJson(`/api/tmdb/person?person_id=${encodeURIComponent(person.id)}`);
      setPersonBio({ loading: false, error: '', person, role, data });
    } catch (error) {
      setPersonBio({ loading: false, error: error.message, person, role });
    }
  }

  return (
    <div className="movie-expanded-details">
      {loading ? (
        <div className="people-loading"><Loader2 size={15} className="spin" /> Loading TMDB details...</div>
      ) : details?.error ? (
        <p className="discover-detail-error"><AlertTriangle size={15} /> {details.error}</p>
      ) : (
        <section className="movie-expanded-credits-panel" aria-label="Director and top cast">
          <span className="mini-label">Director &amp; top cast</span>
          <div className="movie-expanded-people-grid">
            {expandedDirectors.length ? (
              expandedDirectors.slice(0, 2).map((person) => (
                <PersonCreditCard
                  key={`director-${person.id || person.name}`}
                  person={person}
                  role="director"
                  canBrowse={canBrowsePeople}
                  onBrowse={onPersonBrowse}
                  onDiscover={personFilmographyAction}
                  onBio={openPersonBio}
                />
              ))
            ) : (
              <small className="movie-expanded-credit-empty">No director data found.</small>
            )}
            {expandedCast.length ? (
              expandedCast.map((person) => (
                <PersonCreditCard
                  key={`${person.id || person.name}-${person.character || ''}`}
                  person={person}
                  role="actor"
                  canBrowse={canBrowsePeople}
                  onBrowse={onPersonBrowse}
                  onDiscover={personFilmographyAction}
                  onBio={openPersonBio}
                />
              ))
            ) : (
              <small className="movie-expanded-credit-empty">No cast data found.</small>
            )}
          </div>
        </section>
      )}
      {personBio && (
        <PersonBioModal
          state={personBio}
          onClose={() => setPersonBio(null)}
        />
      )}
    </div>
  );
}

function PersonCreditCard({ person, role, canBrowse, onBrowse, onDiscover, onBio }) {
  const isDirector = role === 'director';
  const className = cx('person-card', isDirector && 'director-person', !canBrowse && 'discover-person-static', canBrowse && 'person-credit-browse');
  const browseLabel = isDirector ? 'Director' : (person.character || 'Cast');
  const canDiscover = Boolean(onDiscover && person?.id);

  function browse() {
    if (canBrowse) onBrowse(role, person);
  }

  function handleKeyDown(event) {
    if (event.target !== event.currentTarget) return;
    if (!canBrowse || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    browse();
  }

  function handleBioClick(event) {
    event.stopPropagation();
    onBio(role, person);
  }

  function handleDiscoverClick(event) {
    event.stopPropagation();
    onDiscover(role, person);
  }

  return (
    <div
      className={className}
      role={canBrowse ? 'button' : undefined}
      tabIndex={canBrowse ? 0 : undefined}
      onClick={canBrowse ? browse : undefined}
      onKeyDown={handleKeyDown}
    >
      <button
        type="button"
        className="person-bio-button"
        onClick={handleBioClick}
        aria-label={`Open biography for ${person.name}`}
        title="Biography"
      >
        <BookOpen size={14} />
      </button>
      {canDiscover ? (
        <button
          type="button"
          className="person-discover-button"
          onClick={handleDiscoverClick}
          aria-label={`Open filmography for ${person.name}`}
          title="Filmography"
        >
          <Film size={14} />
        </button>
      ) : null}
      <PersonAvatar person={person} />
      <strong dir="auto">{person.name}</strong>
      <small>{browseLabel}</small>
    </div>
  );
}

function PersonBioModal({ state, onClose }) {
  const data = state.data || {};
  const fallback = state.person || {};
  const name = data.name || fallback.name || 'TMDB person';
  const profileUrl = data.profile_url || fallback.profile_url || '';
  const roleLabel = state.role === 'director' ? 'Director' : 'Actor';
  const biography = String(data.biography || '').trim();
  const facts = [
    data.known_for_department || roleLabel,
    data.birthday ? `Born ${data.birthday}` : '',
    data.deathday ? `Died ${data.deathday}` : '',
    data.place_of_birth || ''
  ].filter(Boolean);
  const initial = String(name).trim().slice(0, 1).toUpperCase() || '?';

  const modal = (
    <div className="modal-backdrop person-bio-backdrop" role="presentation" onClick={onClose}>
      <section className="person-bio-dialog" role="dialog" aria-modal="true" aria-label={`Biography for ${name}`} onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header person-bio-header">
          <div>
            <p className="screen-kicker">{roleLabel} profile</p>
            <h2>{name}</h2>
          </div>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close biography">
            <X size={18} />
          </button>
        </div>
        <div className="person-bio-content">
          <div className="person-bio-photo">
            {profileUrl ? <img src={profileUrl} alt={`${name} portrait`} /> : <span>{initial}</span>}
          </div>
          <div className="person-bio-copy">
            {state.loading ? (
              <div className="dialog-loading person-bio-loading">
                <Loader2 size={18} className="spin" />
                <span className="dialog-loading-copy">
                  <strong>Loading TMDB profile...</strong>
                  <small>Fetching biography and portrait.</small>
                </span>
              </div>
            ) : state.error ? (
              <p className="dialog-error person-bio-error"><AlertTriangle size={15} /> {state.error}</p>
            ) : (
              <>
                {facts.length ? (
                  <div className="person-bio-facts">
                    {facts.map((fact) => <span key={fact}>{fact}</span>)}
                  </div>
                ) : null}
                <p>{biography || 'No biography available from TMDB.'}</p>
              </>
            )}
          </div>
        </div>
      </section>
    </div>
  );

  return typeof document === 'undefined' ? modal : createPortal(modal, document.body);
}

function PersonAvatar({ person }) {
  const initial = String(person?.name || '?').trim().slice(0, 1).toUpperCase() || '?';
  return (
    <span className="person-avatar" aria-hidden="true">
      {person?.profile_url ? <img src={person.profile_url} alt="" loading="lazy" /> : initial}
    </span>
  );
}

export function LibraryMovieCard({
  item,
  followed = false,
  expanded,
  details,
  collection,
  collectionStatus,
  collectionError,
  itemLists,
  onToggle,
  onPlay,
  onFindTorrent,
  onTrailer,
  onPersonFilter,
  onPersonDiscover,
  onCollectionBrowse,
  onCollectionRetry,
  onEditCollection,
  onResetCollection,
  onListFilter,
  onEditLists,
  onRemoveFromList,
  onEditPoster,
  onCorrectMetadata,
  onOpenFileDetails,
  watched,
  watchlisted,
  onToggleWatched,
  onToggleWatchlist,
  showOwnedBadge = true,
  selected,
  onSelect
}) {
  const identity = getMovieIdentity(item);
  const canonical = item.canonical_metadata || {};
  const lowQuality = item.maintenance_upgrade_candidate === true;
  const genres = (canonical.genres?.length ? canonical.genres : item.plex_genres || []).slice(0, expanded ? 10 : 3);
  const directors = getRolePeople(item, details, 'director');
  const cast = getRolePeople(item, details, 'actor').slice(0, 8);
  const locale = getLocaleTag(item);
  const movieForSearch = {
    title: identity.title,
    year: identity.year,
    imdb_id: canonical.imdb_id || item.imdb_id || '',
    tmdb_id: canonical.tmdb_id || item.tmdb_id || ''
  };
  const posterUrl = canonical.poster_url || item.plex_poster || '';
  const canonicalDetails = details ? {
    ...details,
    ...canonical,
    loading: details.loading,
    error: details.error,
    trailer_url: details.trailer_url || canonical.trailer_url || ''
  } : canonical;
  const baseDisplayMovie = {
    ...canonical,
    title: identity.title,
    year: identity.year,
    tmdb_id: canonical.tmdb_id || item.tmdb_id || '',
    poster_url: posterUrl,
    genres,
    summary: canonical.summary || canonical.plot || details?.summary || details?.plot || item.plex_summary || '',
    plot: canonical.plot || canonical.summary || details?.plot || details?.summary || item.plex_summary || ''
  };
  const languageView = useTransientMovieLanguage({
    movie: baseDisplayMovie,
    details: canonicalDetails,
    expanded
  });
  const displayMovie = languageView.displayMovie;
  const displayDetails = languageView.displayDetails;
  const displayCollection = languageView.isArabic && displayDetails?.collection?.id
    ? { ...(collection || {}), ...displayDetails.collection }
    : (collection?.id ? collection : canonical.collection || {});
  const playAction = usePendingPlay(onPlay, item.path);

  return (
    <UnifiedMovieCard
      className={cx('library-movie-card', expanded && 'library-movie-card-expanded')}
      title={displayMovie.title}
      year={displayMovie.year}
      posterUrl={displayMovie.poster_url}
      rating={displayMovie.rating || displayMovie.tmdb_rating || item.plex_rating}
      voteCount={formatVoteCount(displayMovie.tmdb_vote_count)}
      chips={(displayMovie.genres || genres).slice(0, 2)}
      mutedChips={[
        locale,
        {
          label: expanded ? displayDetails?.certification || displayMovie.certification : '',
          tone: 'certification'
        },
        getCompactQualityLabel(item)
      ]}
      statusLabel={lowQuality ? 'Upgrade candidate' : ''}
      statusTone={lowQuality ? 'warning' : 'neutral'}
      following={followed}
      ownedBadge={showOwnedBadge}
      expanded={expanded}
      selected={selected}
      onToggle={onToggle}
      headerActions={expanded ? (
        <MovieImdbLink
          imdbId={displayDetails?.imdb_id || displayMovie.imdb_id}
          title={displayMovie.title}
        />
      ) : null}
      metadataActions={expanded ? (
        <MovieLanguageToggle {...languageView.toggleProps} />
      ) : null}
      showPlayOverlay={Boolean(item.path)}
      onPlay={playAction.play}
      playPending={playAction.pending}
      cornerControls={(
        <>
          <PosterStateControls
            title={identity.title}
            watched={watched}
            watchlisted={watchlisted}
            onToggleWatched={onToggleWatched}
            onToggleWatchlist={onToggleWatchlist}
          />
          <PosterEditButton title={identity.title} onEdit={onEditPoster} />
          <SelectionCheckbox
            className="library-selection-checkbox"
            checked={Boolean(selected)}
            onChange={onSelect}
            label={`Select ${identity.title}`}
          />
        </>
      )}
      expandedBody={expanded ? (
        <MovieExpandedCuration
          movie={displayMovie}
          details={displayDetails}
          collection={displayCollection}
          collectionStatus={collectionStatus}
          collectionError={collectionError}
          itemLists={itemLists}
          onCollectionBrowse={onCollectionBrowse}
          onCollectionRetry={onCollectionRetry}
          onListBrowse={onListFilter}
          onEditLists={onEditLists}
          onRemoveFromList={onRemoveFromList}
          onEditCollection={onEditCollection}
          onResetCollection={onResetCollection}
          emptyListText="No user lists yet."
        />
      ) : null}
      expandedFooter={expanded ? (
        <MovieExpandedDetails
          details={displayDetails}
          directors={languageView.isArabic ? displayDetails?.directors : directors}
          cast={languageView.isArabic ? displayDetails?.cast : cast}
          onPersonBrowse={onPersonFilter}
          onPersonDiscover={onPersonDiscover ? (role, person) => onPersonDiscover({ title: identity.title, year: identity.year }, role, person) : undefined}
        />
      ) : null}
    >
      {expanded && (
        <>
          <p className="library-summary movie-summary-expanded" dir={languageView.isArabic ? 'rtl' : undefined}>
            {displayMovie.summary || displayMovie.plot || 'No plot summary is available yet.'}
          </p>
          <MovieKeywordRow keywords={displayDetails?.keywords || displayMovie.keywords} />
          <div className="library-card-actions">
            <MoviePlayButton pending={playAction.pending} onPlay={playAction.play} />
            <button type="button" className="btn btn-secondary" onClick={onTrailer}>
              <Film size={15} /> Trailer
            </button>
            <button type="button" className="btn btn-secondary" onClick={onCorrectMetadata}>
              <Pencil size={15} /> Correct metadata
            </button>
            <OwnedFileDetailsButton owned={item} onOpenFileDetails={onOpenFileDetails} />
            {lowQuality && (
              <button type="button" className="btn btn-upgrade" onClick={() => onFindTorrent(movieForSearch, true)}>
                <Wand2 size={15} /> Find upgrade
              </button>
            )}
          </div>
          <MovieExpandedFacts movie={displayMovie} details={displayDetails} />
        </>
      )}
    </UnifiedMovieCard>
  );
}
