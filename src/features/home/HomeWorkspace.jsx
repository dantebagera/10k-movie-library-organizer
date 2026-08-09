import {
  AlertTriangle, Bell, ChevronLeft, ChevronRight, ExternalLink, Film, HardDrive, Link as LinkIcon, Loader2, MonitorPlay,
  Play, RefreshCw, ScanSearch, Search, Sparkles, Trash2, Wand2, X, Youtube
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import headerCropUrl from '../../assets/header.png';
import Rating from '../../components/Rating.jsx';
import SelectionCheckbox from '../../components/SelectionCheckbox.jsx';
import { OwnedFileDetailsButton, PosterEditButton, PosterStateControls } from '../../components/SharedMovieCards.jsx';
import { ContinueMovieCard, UnifiedMovieCard, UpcomingMovieCard } from '../../components/movie-card/MovieCard.jsx';
import useCardGridMetrics from '../../hooks/useCardGridMetrics.js';
import { cx, formatCount, movieKey, sortFollowedReleases } from '../../utils/appUtils.js';
import { canonicalOwnedMovie, listsForDiscoverMovie, ownedMovieFor } from '../../discoverUtils.js';
import { getCompactQualityLabel } from '../../utils/libraryUtils.js';
import { formatReleaseDateLabel, formatVoteCount, isUnreleasedMovie } from '../../utils/moviePresentation.js';

export default function HomeWorkspace(props) {
  const {
    stats,
    loading,
    movies,
    upcomingMovies,
    upcomingError,
    homeTrailers,
    homeTrailersError,
    ownership,
    followed,
    followedChecking,
    onScanFollowed,
    selectedMovie,
    selectedOwnership,
    selectedDetails,
    onSelectSection,
    onOpenDiscoverList,
    onOpenCleanup,
    onSelectMovie,
    onOpenHomeTrailer,
    onRetryHomeTrailers,
    onLoadMoreHomeTrailers,
    onPlay,
    onStream,
    streamingAvailable,
    streamingLabel,
    onFindTorrent,
    onTrailer,
    onFollow,
    userLists,
    onToggleSystemList,
    onEditPoster,
    onOpenFileDetails,
    continueWatching = [],
    onResumeWatching,
    onRestartWatching,
    onRemoveWatching
  } = props;
  const [releaseDrawerOpen, setReleaseDrawerOpen] = useState(false);

  return (
    <div className="home-grid">
      <section className="hero-panel">
        <img className="home-hero-art" src={headerCropUrl} alt="" aria-hidden="true" />
        <div className="hero-copy">
          <h1 className="hero-page-title">Home</h1>
          <p className="screen-kicker">Cinematic archive console</p>
          <h2>Your movie archive, under command.</h2>
          <p>
            Cinema Paradiso brings local files, Plex metadata, cleanup tools, torrent sources, TMDB discovery,
            live streaming, and AI recommendations into one private console built for collectors who manage real libraries.
          </p>
        </div>
      </section>

      <div className="home-status-grid">
        <HealthPanel stats={stats} loading={loading.stats} onOpenCleanup={onOpenCleanup} />
        <ReleasePanel
          followed={followed}
          checking={followedChecking}
          onScan={onScanFollowed}
          onSelectMovie={onSelectMovie}
          onViewAll={() => setReleaseDrawerOpen(true)}
        />
      </div>

      <div className="home-media-grid">
        <HomeTrailersPanel
          feed={homeTrailers}
          loading={loading.trailers}
          loadingMore={loading.trailersMore}
          error={homeTrailersError}
          onOpenVideo={onOpenHomeTrailer}
          onRetry={onRetryHomeTrailers}
          onLoadMore={onLoadMoreHomeTrailers}
        />
      </div>

      <div className="home-main-grid">
        <div className="home-main-stack">
        {continueWatching.length > 0 && (
          <ContinueWatchingRail
            items={continueWatching}
            onResume={onResumeWatching}
            onRestart={onRestartWatching}
            onRemove={onRemoveWatching}
          />
        )}
        <section className="movie-rail">
          <div className="section-heading">
            <div>
              <p className="screen-kicker">Discover</p>
              <h3>Trending movies with archive-aware actions</h3>
            </div>
            <button type="button" className="ghost-link" onClick={() => onSelectSection('discover')}>
              Open Discover
            </button>
          </div>
          {loading.movies ? (
            <div className="skeleton-stack">
              <div className="movie-card skeleton-card" />
              <div className="movie-card skeleton-card" />
              <div className="movie-card skeleton-card" />
            </div>
          ) : (
            <div className="movie-list">
              {movies.slice(0, 6).map((movie) => {
                const owned = ownedMovieFor(movie, ownership);
                return (
                  <SmartMovieCard
                    key={movieKey(movie)}
                    movie={movie}
                    owned={owned}
                    selected={movieKey(movie) === movieKey(selectedMovie || {})}
                    followed={followed.some((item) => movieKey(item) === movieKey(movie))}
                    watched={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watched')}
                    watchlisted={listsForDiscoverMovie(movie, userLists, owned).some((list) => list.system_type === 'watchlist')}
                    details={movieKey(movie) === movieKey(selectedMovie || {}) ? selectedDetails : null}
                    onSelect={() => onSelectMovie(movie)}
                    onPlay={onPlay}
                    onStream={onStream}
                    streamingAvailable={streamingAvailable}
                    streamingLabel={streamingLabel}
                    onFindTorrent={onFindTorrent}
                    onTrailer={onTrailer}
                    onFollow={onFollow}
                    onToggleWatched={owned ? () => onToggleSystemList('watched', movie, owned) : undefined}
                    onToggleWatchlist={() => onToggleSystemList('watchlist', movie, owned)}
                    onEditPoster={owned ? () => onEditPoster(owned, movie) : undefined}
                  />
                );
              })}
            </div>
          )}
        </section>
        </div>

        <div className="home-side-stack">
          <MovieInspector
            movie={selectedMovie}
            owned={selectedOwnership}
            details={selectedDetails}
            followed={followed.some((item) => movieKey(item) === movieKey(selectedMovie || {}))}
            watched={listsForDiscoverMovie(selectedMovie || {}, userLists, selectedOwnership).some((list) => list.system_type === 'watched')}
            watchlisted={listsForDiscoverMovie(selectedMovie || {}, userLists, selectedOwnership).some((list) => list.system_type === 'watchlist')}
            onClose={() => onSelectMovie(null)}
            onPlay={onPlay}
            onStream={onStream}
            streamingAvailable={streamingAvailable}
            streamingLabel={streamingLabel}
            onFindTorrent={onFindTorrent}
            onTrailer={onTrailer}
            onFollow={onFollow}
            onToggleWatched={selectedOwnership ? () => onToggleSystemList('watched', selectedMovie, selectedOwnership) : undefined}
            onToggleWatchlist={selectedMovie ? () => onToggleSystemList('watchlist', selectedMovie, selectedOwnership) : undefined}
            onEditPoster={selectedOwnership ? () => onEditPoster(selectedOwnership, selectedMovie) : undefined}
            onOpenFileDetails={onOpenFileDetails}
          />
          <ComingSoonPanel
            movies={upcomingMovies}
            loading={loading.upcoming}
            error={upcomingError}
            selectedMovie={selectedMovie}
            onSelectMovie={onSelectMovie}
            onViewAll={() => onOpenDiscoverList('upcoming')}
          />
        </div>
      </div>
      {releaseDrawerOpen && (
        <FollowedReleasesDrawer
          followed={followed}
          checking={followedChecking}
          selectedMovie={selectedMovie}
          onClose={() => setReleaseDrawerOpen(false)}
          onSelectMovie={onSelectMovie}
          onFindTorrent={onFindTorrent}
          onUnfollow={onFollow}
        />
      )}
    </div>
  );
}

function publishedLabel(value) {
  const timestamp = Date.parse(value || '');
  if (!Number.isFinite(timestamp)) return '';
  const elapsedMinutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (elapsedMinutes < 60) return `${Math.max(1, elapsedMinutes)} min ago`;
  const hours = Math.floor(elapsedMinutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? '' : 's'} ago`;
  const months = Math.floor(days / 30);
  return `${months} month${months === 1 ? '' : 's'} ago`;
}

function HomeTrailersPanel({ feed, loading, loadingMore, error, onOpenVideo, onRetry, onLoadMore }) {
  const [page, setPage] = useState(0);
  const [sourceFilter, setSourceFilter] = useState('all');
  const { columns, gridRef } = useCardGridMetrics({ target: 5, max: 5, bias: 'lower' });
  const items = useMemo(
    () => (feed?.items || []).filter((video) => sourceFilter === 'all' || video.source_id === sourceFilter),
    [feed?.items, sourceFilter]
  );
  const sources = feed?.sources || [];
  const selectedSource = sources.find((source) => source.id === sourceFilter);
  const pageSize = Math.max(1, columns);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const visibleItems = useMemo(
    () => items.slice(safePage * pageSize, safePage * pageSize + pageSize),
    [items, pageSize, safePage]
  );

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages - 1));
  }, [totalPages]);

  useEffect(() => {
    setPage(0);
  }, [sourceFilter]);

  const showNextPage = async () => {
    if (safePage < totalPages - 1) {
      setPage((current) => current + 1);
      return;
    }
    if (!feed?.has_more || loadingMore) return;
    await onLoadMore?.();
    setPage((current) => current + 1);
  };

  return (
    <section className="home-trailers-panel" aria-labelledby="home-trailers-heading">
      <div className="section-heading home-trailers-heading">
        <div>
          <p className="screen-kicker">Trailer channels</p>
          <h3 id="home-trailers-heading">{feed?.title || 'New Trailers'}</h3>
        </div>
        <div className="home-trailer-heading-actions">
          {selectedSource?.source_url ? (
            <a className="ghost-link ghost-link-small" href={selectedSource.source_url} target="_blank" rel="noreferrer">
              <ExternalLink size={14} /> Channel
            </a>
          ) : null}
          <div className="continue-watching-controls">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              aria-label="Previous trailer videos"
              disabled={safePage === 0}
            >
              <ChevronLeft size={18} />
            </button>
            <button
              type="button"
              onClick={showNextPage}
              aria-label="Next trailer videos"
              disabled={(safePage >= totalPages - 1 && !feed?.has_more) || loadingMore}
            >
              {loadingMore ? <Loader2 className="spin" size={17} /> : <ChevronRight size={18} />}
            </button>
          </div>
        </div>
      </div>

      <div className="home-trailer-source-filters" aria-label="Trailer channel filter">
        <button type="button" className={cx(sourceFilter === 'all' && 'active')} onClick={() => setSourceFilter('all')}>All</button>
        {sources.map((source) => (
          <button type="button" key={source.id} className={cx(sourceFilter === source.id && 'active')} onClick={() => setSourceFilter(source.id)}>
            {source.name}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="home-trailer-grid" ref={gridRef}>
          {Array.from({ length: pageSize }, (_, index) => (
            <div className="home-video-card home-video-card-skeleton skeleton-card" key={index} />
          ))}
        </div>
      ) : error ? (
        <div className="home-feed-empty">
          <AlertTriangle size={22} />
          <strong>Hot New Trailers is temporarily unavailable.</strong>
          <span>{error}</span>
          <button type="button" className="ghost-link ghost-link-small" onClick={onRetry}>Retry</button>
        </div>
      ) : visibleItems.length ? (
        <div className="home-trailer-grid" ref={gridRef}>
          {visibleItems.map((video) => (
            <button
              type="button"
              className="home-video-card"
              key={video.video_id}
              onClick={() => onOpenVideo(video)}
              aria-label={`Play ${video.title}`}
            >
              <span className="home-video-thumbnail">
                <img src={video.thumbnail_url} alt="" loading="lazy" />
                <span className="home-video-play"><Youtube size={25} /></span>
              </span>
              <strong dir="auto" title={video.title}>{video.title}</strong>
              <small>
                <span className="home-video-source">{video.source_name || 'YouTube'}</span>
                {video.views ? `${formatCount(video.views)} views` : 'New video'}
                {publishedLabel(video.published_at) ? ` · ${publishedLabel(video.published_at)}` : ''}
              </small>
            </button>
          ))}
        </div>
      ) : (
        <div className="home-feed-empty">
          <Youtube size={22} />
          <strong>No playlist videos are available.</strong>
        </div>
      )}
      {(feed?.stale || feed?.fallback) && (
        <small className="home-feed-stale">
          {feed?.stale ? 'Showing the last successfully refreshed trailers.' : 'Using the public 15-video channel feeds until the YouTube API key is available.'}
        </small>
      )}
    </section>
  );
}

function ComingSoonPanel({ movies, loading, error, selectedMovie, onSelectMovie, onViewAll }) {
  const { gridRef, pageSize } = useCardGridMetrics({ target: 6, min: 6, max: 6 });
  const visibleMovies = useMemo(
    () => (movies || []).slice(0, pageSize),
    [movies, pageSize]
  );

  return (
    <section className="coming-soon-panel" aria-labelledby="coming-soon-heading">
      <div className="section-heading">
        <div>
          <p className="screen-kicker">Coming soon</p>
          <h3 id="coming-soon-heading">Upcoming movies</h3>
        </div>
        <button type="button" className="ghost-link ghost-link-small" onClick={onViewAll}>
          View all
        </button>
      </div>
      {loading ? (
        <div className="coming-soon-grid" ref={gridRef}>
          {Array.from({ length: pageSize }, (_, index) => (
            <div className="upcoming-movie-card upcoming-movie-card-skeleton skeleton-card" key={index} />
          ))}
        </div>
      ) : error ? (
        <div className="home-feed-empty">
          <AlertTriangle size={22} />
          <strong>Upcoming movies are temporarily unavailable.</strong>
          <span>{error}</span>
        </div>
      ) : visibleMovies.length ? (
        <div className="coming-soon-grid" ref={gridRef}>
          {visibleMovies.map((movie) => (
            <UpcomingMovieCard
              key={movieKey(movie)}
              title={movie.title}
              posterUrl={movie.poster_url}
              releaseLabel={formatReleaseDateLabel(movie.release_date)}
              selected={movieKey(movie) === movieKey(selectedMovie || {})}
              onSelect={() => onSelectMovie(movie)}
            />
          ))}
        </div>
      ) : (
        <div className="home-feed-empty">
          <Sparkles size={22} />
          <strong>No upcoming movies are available.</strong>
        </div>
      )}
    </section>
  );
}

function remainingLabel(seconds) {
  const minutes = Math.max(1, Math.ceil((Number(seconds) || 0) / 60));
  if (minutes < 60) return `${minutes} min remaining`;
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return remainder ? `${hours} hr ${remainder} min remaining` : `${hours} hr remaining`;
}

function ContinueWatchingRail({ items, onResume, onRestart, onRemove }) {
  const viewportRef = useRef(null);

  function scrollBy(direction) {
    viewportRef.current?.scrollBy({ left: direction * 680, behavior: 'smooth' });
  }

  function handleWheel(event) {
    if (!viewportRef.current || Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
    event.preventDefault();
    viewportRef.current.scrollLeft += event.deltaY;
  }

  return (
    <section className="continue-watching-panel" aria-labelledby="continue-watching-heading">
      <div className="section-heading">
        <div>
          <p className="screen-kicker">Your screening room</p>
          <h3 id="continue-watching-heading">Continue Watching</h3>
        </div>
        <div className="continue-watching-controls">
          <button type="button" onClick={() => scrollBy(-1)} aria-label="Scroll Continue Watching left">
            <ChevronLeft size={18} />
          </button>
          <button type="button" onClick={() => scrollBy(1)} aria-label="Scroll Continue Watching right">
            <ChevronRight size={18} />
          </button>
        </div>
      </div>
      <div
        className="continue-watching-viewport"
        ref={viewportRef}
        onWheel={handleWheel}
        tabIndex="0"
        role="region"
        aria-label="Continue Watching movies"
      >
        {items.map((item) => (
          <ContinueMovieCard
            key={item.path_key}
            title={item.title}
            posterUrl={item.poster_url}
            progress={item.progress}
            remainingLabel={remainingLabel(item.remaining_seconds)}
            onResume={() => onResume(item)}
            onRestart={() => onRestart(item)}
            onRemove={() => onRemove(item)}
          />
        ))}
      </div>
    </section>
  );
}

function HealthPanel({ stats, loading, onOpenCleanup }) {
  const cards = [
    {
      label: 'Files',
      value: stats?.total_files,
      detail: `${formatCount(stats?.unique_titles)} unique titles`,
      icon: HardDrive,
      tone: 'blue'
    },
    {
      label: 'Low quality',
      value: stats?.low_quality_count,
      detail: 'below 1080p',
      icon: AlertTriangle,
      tone: 'amber',
      tab: 'low'
    },
    {
      label: 'Duplicates',
      value: stats?.duplicate_groups,
      detail: `${formatCount(stats?.extra_copies)} extra copies`,
      icon: Trash2,
      tone: 'red',
      tab: 'duplicates'
    },
    {
      label: 'Unmatched',
      value: stats?.unmatched_count,
      detail: 'files without accepted metadata',
      icon: LinkIcon,
      tone: 'violet',
      tab: 'unmatched'
    },
    {
      label: 'Identity review',
      value: stats?.identity_review_count,
      detail: `${formatCount(stats?.identity_review_recommended)} recommended corrections`,
      icon: ScanSearch,
      tone: 'cyan',
      tab: 'identity'
    }
  ];

  return (
    <section className="health-panel">
      <div className="section-heading">
        <div>
          <p className="screen-kicker">Library health</p>
          <h3>Offline archive status</h3>
        </div>
        {loading && <Loader2 className="spin" size={18} />}
      </div>
      <div className="health-cards">
        {cards.map((card) => {
          const Icon = card.icon;
          const Card = card.tab ? 'button' : 'article';
          return (
            <Card
              type={card.tab ? 'button' : undefined}
              key={card.label}
              className={cx('health-card', card.tab && 'health-card-action', `tone-${card.tone}`)}
              onClick={card.tab ? () => onOpenCleanup(card.tab) : undefined}
            >
              <Icon size={18} />
              <strong>{loading ? '...' : formatCount(card.value)}</strong>
              <span>{card.label}</span>
              <small>{card.detail}</small>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

function releaseStatusLabel(movie) {
  if (movie.status === 'available') return 'Available';
  if (movie.status === 'owned') return 'Owned';
  return 'Watching';
}

function ReleasePanel({ followed, checking, onScan, onSelectMovie, onViewAll }) {
  const preview = sortFollowedReleases(followed).slice(0, 3);
  return (
    <section className="release-panel">
      <div className="section-heading">
        <div>
          <p className="screen-kicker">Release watchlist</p>
          <h3>Followed movies and upgrade signals</h3>
        </div>
        <div className="release-heading-actions">
          <Bell size={18} />
          <button
            type="button"
            className="release-sync-button"
            onClick={onScan}
            disabled={checking}
            aria-label={checking ? 'Scanning followed releases' : 'Scan followed releases'}
            title={checking ? 'Scanning followed releases' : 'Scan followed releases'}
          >
            <RefreshCw className={checking ? 'spin' : ''} size={17} />
          </button>
          {followed.length > 3 && (
            <button type="button" className="ghost-link ghost-link-small" onClick={onViewAll}>
              View all
            </button>
          )}
        </div>
      </div>
      <div className="release-list">
        {preview.length ? preview.map((movie, index) => (
          <button
            className={cx('release-item', `release-item-${movie.status || 'watching'}`)}
            key={`${movie.tmdb_id || movie.title}-${index}`}
            onClick={() => onSelectMovie(movie)}
            type="button"
          >
            <span className="release-pulse" />
            <span>
              <strong>{movie.title}</strong>
              <small>{movie.year || 'Unknown year'}</small>
            </span>
            <em>{releaseStatusLabel(movie)}</em>
          </button>
        )) : (
          <div className="empty-state">
            <strong>No followed releases yet.</strong>
            <span>Use Follow on a Discover card to watch for a proper WEB-DL or Blu-ray copy.</span>
          </div>
        )}
      </div>
    </section>
  );
}

function FollowedReleasesDrawer({ followed, checking, selectedMovie, onClose, onSelectMovie, onFindTorrent, onUnfollow }) {
  const [filter, setFilter] = useState('all');
  const sorted = sortFollowedReleases(followed);
  const visible = sorted.filter((movie) => filter === 'all' || (movie.status || 'watching') === filter);
  const availableCount = sorted.filter((movie) => movie.status === 'available').length;
  const watchingCount = sorted.filter((movie) => (movie.status || 'watching') === 'watching').length;
  const filterCounts = { all: sorted.length, available: availableCount, watching: watchingCount };

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="followed-drawer" role="dialog" aria-modal="true" aria-label="Followed releases" onClick={(event) => event.stopPropagation()}>
        <div className="dialog-header">
          <div>
            <p className="screen-kicker">Release watchlist</p>
            <h2>Followed Releases</h2>
          </div>
          <span className={cx('release-drawer-count', availableCount > 0 && 'release-drawer-count-hot')}>
            {formatCount(sorted.length)} followed · {checking ? 'Checking...' : `${formatCount(availableCount)} available`}
          </span>
          <button type="button" className="inspector-close" onClick={onClose} aria-label="Close followed releases">
            <X size={18} />
          </button>
        </div>

        <div className="release-filter-row">
          {['all', 'available', 'watching'].map((value) => (
            <button
              key={value}
              type="button"
              className={cx('release-filter-chip', filter === value && 'release-filter-chip-active')}
              onClick={() => setFilter(value)}
            >
              {value === 'all' ? 'All' : value === 'available' ? 'Available' : 'Watching'} ({formatCount(filterCounts[value])})
            </button>
          ))}
        </div>

        <div className="followed-list-full">
          {visible.length ? visible.map((movie, index) => (
            <div
              key={`${movie.tmdb_id || movie.title}-${index}`}
              data-followed-title={movie.title}
              className={cx(
                'followed-row',
                `followed-row-${movie.status || 'watching'}`,
                movieKey(movie) === movieKey(selectedMovie || {}) && 'followed-row-selected'
              )}
            >
              <button type="button" onClick={() => onSelectMovie(movie)}>
                <span className="followed-thumb">
                  {movie.poster_url ? <img src={movie.poster_url} alt="" loading="lazy" /> : <Film size={18} />}
                </span>
                <span>
                  <strong>{movie.title}</strong>
                  <small>{movie.year || 'Unknown year'}</small>
                </span>
                <em>{releaseStatusLabel(movie)}</em>
              </button>
              {movie.status === 'available' && (
                <button type="button" className="btn btn-secondary btn-green-outline" onClick={() => onFindTorrent(movie)}>
                  <Search size={15} /> Sources
                </button>
              )}
              <button
                type="button"
                className="followed-delete-button"
                onClick={() => onUnfollow(movie)}
                aria-label={`Remove ${movie.title} from followed releases`}
                title="Remove from watchlist"
              >
                <Trash2 size={15} />
              </button>
            </div>
          )) : (
            <div className="empty-state">
              <strong>No followed releases in this filter.</strong>
              <span>Available movies are always sorted to the top when the backend finds a proper WEB or Blu-ray source.</span>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function SmartMovieCard(props) {
  const {
    movie, owned, selected, followed, details, watched, watchlisted,
    onSelect, onPlay, onStream, streamingAvailable, streamingLabel, onFindTorrent, onFollow,
    onTrailer, onToggleWatched, onToggleWatchlist, onEditPoster
  } = props;
  const ownedItem = owned?.canonical_card || owned?.library_item || owned || {};
  const displayMovie = canonicalOwnedMovie(movie, owned);
  const lowQuality = Boolean(owned?.maintenance_upgrade_candidate);
  const unreleased = !owned && isUnreleasedMovie(displayMovie);
  const genres = (displayMovie.genres || []).slice(0, 2);

  return (
    <UnifiedMovieCard
      className="home-smart-movie-card"
      title={displayMovie.title}
      year={displayMovie.year}
      posterUrl={displayMovie.poster_url}
      rating={displayMovie.tmdb_rating}
      voteCount={formatVoteCount(displayMovie.tmdb_vote_count)}
      chips={genres}
      mutedChips={[
        displayMovie.language,
        displayMovie.country_flag || displayMovie.country,
        owned ? getCompactQualityLabel(ownedItem) : ''
      ]}
      statusLabel={owned ? (lowQuality ? 'Upgrade candidate' : '') : (unreleased ? 'Unreleased' : (followed ? 'Following' : 'Not in library'))}
      statusTone={owned ? (lowQuality ? 'warning' : 'neutral') : (unreleased ? 'warning' : 'missing')}
      ownedBadge={Boolean(owned)}
      selected={selected}
      onToggle={onSelect}
      showPlayOverlay={Boolean(owned?.path)}
      onPlay={owned?.path ? () => onPlay(owned.path) : undefined}
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
        </>
      )}
    />
  );
}

function MovieInspector({
  movie, owned, details, followed, watched, watchlisted,
  onClose, onPlay, onStream, streamingAvailable, streamingLabel, onFindTorrent, onFollow,
  onTrailer, onToggleWatched, onToggleWatchlist, onEditPoster, onOpenFileDetails
}) {
  if (!movie) {
    return (
      <aside className="inspector inspector-empty">
        <Sparkles size={22} />
        <h3>Select a movie</h3>
        <p>Movie details, cast, trailer, and archive actions will appear here.</p>
      </aside>
    );
  }

  const displayMovie = canonicalOwnedMovie(movie, owned);
  const ownedItem = owned?.canonical_card || owned?.library_item || {};
  const ownedCanonical = ownedItem.canonical_metadata || {};
  const displayDetails = ownedCanonical.accepted ? {
    ...(details || {}),
    ...ownedCanonical,
    loading: details?.loading,
    error: details?.error,
    trailer_url: details?.trailer_url || ownedCanonical.trailer_url || ''
  } : details;
  const lowQuality = Boolean(owned?.maintenance_upgrade_candidate);
  const unreleased = !owned && isUnreleasedMovie(displayMovie);
  const releaseDateLabel = unreleased ? formatReleaseDateLabel(displayMovie.release_date) : '';
  const cast = displayDetails?.cast || displayMovie.cast || [];
  const trailerUrl = displayDetails?.trailer_url || '';

  return (
    <aside className="inspector">
      <button className="inspector-close" type="button" onClick={onClose} aria-label="Close movie details">
        <X size={17} />
      </button>
      <div className="inspector-hero">
        <Poster
          movie={displayMovie}
          large
          onEditPoster={owned ? onEditPoster : undefined}
          watched={watched}
          watchlisted={watchlisted}
          onToggleWatched={owned ? onToggleWatched : undefined}
          onToggleWatchlist={onToggleWatchlist}
        />
        <div>
          <p className="screen-kicker">Selected movie</p>
          <h3>{displayMovie.title}</h3>
          <div className="inspector-meta">
            <span>{displayMovie.year || 'Unknown year'}</span>
            <Rating value={displayMovie.tmdb_rating} votes={displayMovie.tmdb_vote_count} />
            {unreleased && <span>Unreleased</span>}
            {releaseDateLabel && <span>Releases {releaseDateLabel}</span>}
            {displayMovie.language && <span>{displayMovie.language}</span>}
            {(displayMovie.country_flag || displayMovie.country) && <span>{displayMovie.country_flag || displayMovie.country}</span>}
            {owned && <span>{getCompactQualityLabel(ownedItem)}</span>}
          </div>
        </div>
      </div>
      <p className="plot-text">{displayMovie.summary || displayMovie.plot || 'No plot summary is available yet.'}</p>
      <div className="chip-row">
        {(displayMovie.genres || []).slice(0, 5).map((genre) => <span className="chip" key={genre}>{genre}</span>)}
      </div>
      <div className="cast-strip">
        <span className="mini-label">Top cast</span>
        {displayDetails ? (
          cast.length ? cast.slice(0, 5).map((person) => (
            <span key={person.name} className="cast-chip">{person.name}</span>
          )) : <small>No cast data found.</small>
        ) : (
          <small>Loading cast...</small>
        )}
      </div>
      <div className="inspector-actions">
        {owned ? (
          <>
            <button type="button" className="btn btn-primary btn-green" onClick={() => onPlay(owned.path)}>
              <Play size={15} /> Play from HDD
            </button>
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
              <button type="button" className="btn btn-primary" onClick={() => onFindTorrent(displayMovie)}>
                <Search size={15} /> Find torrent
              </button>
            )}
            <button type="button" className="btn btn-secondary" onClick={() => onFollow(displayMovie)}>
              <Bell size={15} /> {followed ? 'Following' : 'Follow release'}
            </button>
          </>
        )}
        {!unreleased && streamingAvailable && (
          <button type="button" className="btn btn-secondary" onClick={() => onStream(displayMovie)}>
            <MonitorPlay size={15} /> {streamingLabel}
          </button>
        )}
        {displayDetails && (
          <button type="button" className="btn btn-secondary" onClick={() => onTrailer(displayMovie, trailerUrl)}>
            <Film size={15} /> Play trailer
          </button>
        )}
      </div>
    </aside>
  );
}


function Poster({
  movie,
  large,
  onEditPoster,
  watched,
  watchlisted,
  onToggleWatched,
  onToggleWatchlist,
  selected,
  onSelect,
  selectionClassName
}) {
  return (
    <div className={cx('poster', large && 'poster-large')}>
      {movie.poster_url ? (
        <img src={movie.poster_url} alt={`${movie.title} poster`} loading="lazy" />
      ) : (
        <Film size={large ? 42 : 28} />
      )}
      <PosterStateControls
        title={movie.title}
        watched={watched}
        watchlisted={watchlisted}
        onToggleWatched={onToggleWatched}
        onToggleWatchlist={onToggleWatchlist}
      />
      <PosterEditButton title={movie.title} onEdit={onEditPoster} />
      {onSelect && (
        <SelectionCheckbox
          className={selectionClassName}
          checked={Boolean(selected)}
          onChange={onSelect}
          label={`Select ${movie.title}`}
        />
      )}
    </div>
  );
}
