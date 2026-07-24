import os
import re
import stat
import shutil
import time
import uuid
import hashlib
import threading
import subprocess
import socket
import tempfile
import concurrent.futures
import urllib.request
import urllib.parse
import json as _json
import gzip
import xml.etree.ElementTree as _ET
from pathlib import Path

from services.movie_identity import (
    group_identity_records,
    normalize_movie_title as _norm_movie_title,
    ownership_keys as _ownership_keys,
    same_public_identity as _same_public_identity,
)
from services.catalog_repository import CatalogRepository
from services.canonical_catalog import canonical_card_projection, canonical_details_projection
from services.curation_store import UserCurationStore, normalize_curated_movie as _normalize_curated_movie
from services.curation_routes import register_curation_routes
from services.frontend_routes import register_frontend_routes
from services.iptv_routes import register_iptv_routes
from services.iptv_service import IPTVService
from services.metadata_migration import MetadataMigrationCoordinator
from services.identity_audit import IdentityAuditCoordinator
from services.identity_decision import (
    DECISION_ORIGIN_IDENTITY_AUDIT,
    DECISION_ORIGIN_LIBRARY_RECONCILE,
    DECISION_ORIGIN_SMART_MATCH,
    DECISION_ORIGIN_USER_MANUAL,
    IDENTITY_AUDIT_RULE_VERSION,
    evaluate_identity,
    infer_decision_origin,
    resolve_collection_membership,
)
from services.authoritative_identity import (
    accepted_identity_patch,
    resolve_authoritative_identity,
)
from services.identity_repair import build_identity_repair
from services.maintenance_audit import build_maintenance_audit
from services.identity_verification import build_identity_verification_audit, verify_catalog_identity
from services import ai_control
from services.plex_match import PlexMatchAdapter, PlexMatchError
from services.smart_match import (
    SmartMatchCoordinator,
    build_rename_filename,
    parse_ai_match_response,
    parse_release_filename,
    rank_candidates,
    validate_rename_filename,
)
from services.qbittorrent import (
    DEFAULT_WEBUI_PORT,
    HOP_BY_HOP_HEADERS,
    QBittorrentError,
    QBittorrentManager,
    build_downloads_html,
    is_allowed_prowlarr_url,
    is_path_within,
    magnet_hash,
)
from flask import Flask, jsonify, request, make_response, send_file, send_from_directory
from services.library_mutations import LibraryMutationError, LibraryMutationService
from services.source_search import ProwlarrClient
from services.download_monitor import DownloadImportMonitor
from services.media_assets import MediaAssetError, MediaAssetService

app = Flask(__name__)
_process_started_at = time.perf_counter()
_startup_metrics = {
    'process_started_at': time.time(),
    'database_open_ms': 0.0,
    'migration_check_ms': 0.0,
    'generation_check_ms': 0.0,
    'reconcile_decision_ms': 0.0,
    'reconcile_decision': 'not_checked',
    'reconcile_reason': '',
    'background_queue_started': False,
    'api_ready_ms': 0.0,
    'first_library_query_ms': 0.0,
}
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SLOW_ROUTE_MS = int(os.environ.get('CP_SLOW_ROUTE_MS', '250') or '250')
register_frontend_routes(app, _BASE_DIR)

# Config file stored next to app.py
_CONFIG_FILE = os.path.join(_BASE_DIR, 'config.json')


@app.before_request
def _start_route_timer():
    request._cp_started_at = time.perf_counter()


@app.after_request
def _finish_route_timer(response):
    started_at = getattr(request, '_cp_started_at', None)
    if started_at is None:
        return response
    if (
        response.status_code == 200
        and response.mimetype == 'application/json'
        and 'gzip' in request.headers.get('Accept-Encoding', '').lower()
        and not response.headers.get('Content-Encoding')
        and not response.direct_passthrough
    ):
        payload = response.get_data()
        if len(payload) >= 256 * 1024:
            compressed = gzip.compress(payload, compresslevel=5)
            if len(compressed) < len(payload):
                response.set_data(compressed)
                response.headers['Content-Encoding'] = 'gzip'
                response.headers['Vary'] = 'Accept-Encoding'
    duration_ms = (time.perf_counter() - started_at) * 1000
    if request.endpoint == 'library' and request.args.get('view') == 'cards' and not _startup_metrics['first_library_query_ms']:
        _startup_metrics['first_library_query_ms'] = round(duration_ms, 3)
    response.headers['Server-Timing'] = f'app;dur={duration_ms:.1f}'
    response.headers['X-CP-Route-MS'] = f'{duration_ms:.1f}'
    if request.path.startswith('/api/') and duration_ms >= _SLOW_ROUTE_MS:
        print(f"[perf] {request.method} {request.path} {duration_ms:.1f}ms", flush=True)
    return response

def _load_config():
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return _json.load(f)
        except Exception:
            pass
    return {}

def _save_config(data):
    try:
        with open(_CONFIG_FILE, 'w', encoding='utf-8') as f:
            _json.dump(data, f, indent=2)
    except Exception:
        pass

_cfg = _load_config()
OLLAMA_CANDIDATE_LIMIT_DEFAULT = 15
OLLAMA_CANDIDATE_LIMIT_MIN = 1
OLLAMA_CANDIDATE_LIMIT_MAX = 50
SOURCE_SEARCH_ALIAS_LIMIT = 6
SOURCE_SEARCH_QUERY_LIMIT = 10
SOURCE_SEARCH_RESULTS_PER_INDEXER = 100
SOURCE_SEARCH_QUERY_TIMEOUT_SECONDS = 10
SOURCE_SEARCH_DEADLINE_SECONDS = 35
SOURCE_SEARCH_INDEXER_TIMEOUT_SECONDS = 12
SOURCE_SEARCH_JOB_DEADLINE_SECONDS = 60
SOURCE_SEARCH_JOB_WORKERS = 5
SOURCE_SEARCH_JOB_TTL_SECONDS = 900
FOLLOWED_RELEASE_QUERY_TIMEOUT_SECONDS = 8
FOLLOWED_RELEASE_DEADLINE_SECONDS = 25
_source_search_jobs = {}
_source_search_jobs_lock = threading.Lock()
_ai_control_plan_store = ai_control.PlanStore(ttl_seconds=900)


def _coerce_ollama_candidate_limit(value, default=OLLAMA_CANDIDATE_LIMIT_DEFAULT):
    try:
        candidate_limit = int(value)
    except (TypeError, ValueError):
        return default
    if candidate_limit < OLLAMA_CANDIDATE_LIMIT_MIN or candidate_limit > OLLAMA_CANDIDATE_LIMIT_MAX:
        return default
    return candidate_limit


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {'1', 'true', 'yes', 'on'}:
        return True
    if text in {'0', 'false', 'no', 'off'}:
        return False
    return default

def _coerce_movie_dirs(config):
    raw_dirs = config.get('movies_dirs')
    if isinstance(raw_dirs, list):
        dirs = [str(path or '').strip() for path in raw_dirs if str(path or '').strip()]
    else:
        dirs = []
    legacy_dir = str(config.get('movies_dir', r"E:\Movies") or '').strip()
    if legacy_dir and legacy_dir not in dirs:
        dirs.insert(0, legacy_dir)
    seen = set()
    result = []
    for path in dirs:
        norm = os.path.normcase(os.path.normpath(path))
        if norm not in seen:
            seen.add(norm)
            result.append(path)
    return result or [r"E:\Movies"]

_movies_dirs    = _coerce_movie_dirs(_cfg)
_movies_dir     = _movies_dirs[0]
_prowlarr_url   = _cfg.get('prowlarr_url', '')
_prowlarr_key   = _cfg.get('prowlarr_key', '')
_trusted_release_indexers = [str(value).strip() for value in _cfg.get('trusted_release_indexers', []) if str(value).strip()]
_trusted_release_indexers_configured = 'trusted_release_indexers' in _cfg
_download_default_quality = str(_cfg.get('download_default_quality', '1080p') or '1080p').strip() or '1080p'
_download_indexer_mode = str(_cfg.get('download_indexer_mode', 'release') or 'release').strip() or 'release'
_download_trusted_indexers = [str(value).strip() for value in _cfg.get('download_trusted_indexers', []) if str(value).strip()]
_yts_rss_feeds = [
    str(value).strip()
    for value in _cfg.get('yts_rss_feeds', ['https://yts.gg/rss', 'https://yts.bz/rss', 'https://yts.lt/rss'])
    if str(value).strip()
]
_tmdb_key       = _cfg.get('tmdb_key', '')
_tmdb_include_adult = _coerce_bool(_cfg.get('tmdb_include_adult'), False)
_library_show_adult = _coerce_bool(_cfg.get('library_show_adult'), True)
_plex_url       = _cfg.get('plex_url', 'http://localhost:32400')
_plex_token     = _cfg.get('plex_token', '')
_ollama_url     = _cfg.get('ollama_url', 'http://localhost:11434')
_ollama_model   = _cfg.get('ollama_model', 'gemma4:31b-cloud')
_ollama_candidate_limit = _coerce_ollama_candidate_limit(_cfg.get('ollama_candidate_limit'))
_ai_control_config = ai_control.coerce_config({
    'enabled': _cfg.get('ai_control_enabled', True),
    'trusted_indexers': _cfg.get('ai_control_trusted_indexers', []),
    'max_matched_movies': _cfg.get('ai_control_max_matched_movies', 25),
    'max_download_searches': _cfg.get('ai_control_max_download_searches', 10),
    'ollama_curated_lists': _cfg.get('ai_control_ollama_curated_lists', False),
})
_ai_control_trusted_indexers_configured = 'ai_control_trusted_indexers' in _cfg
_streaming_enabled = _coerce_bool(_cfg.get('streaming_enabled'), True)
_streaming_label = str(_cfg.get('streaming_label', 'Stream') or 'Stream').strip() or 'Stream'
_streaming_url_template = str(
    _cfg.get('streaming_url_template', 'https://streamimdb.ru/embed/movie/{tmdb_id}') or ''
).strip()
_user_data_dir  = _cfg.get('user_data_dir', os.path.join(_BASE_DIR, 'data'))
_tmdb_cache_dir = _cfg.get('tmdb_cache_dir', os.path.join(_BASE_DIR, 'cache'))
_qbt_mode       = _cfg.get('qbt_mode', 'embedded')
_qbt_download_dir = _cfg.get('qbt_download_dir', '')
_qbt_incomplete_dir = _cfg.get('qbt_incomplete_dir', '')
_qbt_webui_port = int(_cfg.get('qbt_webui_port', DEFAULT_WEBUI_PORT) or DEFAULT_WEBUI_PORT)
_iptv_service = IPTVService(_user_data_dir)
register_iptv_routes(app, lambda: _iptv_service)
_plex_cache     = {}   # _norm(file_path) -> {plex_title, plex_year, plex_genres}
_plex_unmatched = {}   # _norm(path) -> {rating_key, plex_title}  (Plex has file but no metadata)
_plex_matched_by_fname   = {}  # filename.lower() -> matched entry   (path-mismatch fallback)
_plex_unmatched_by_fname = {}  # filename.lower() -> unmatched entry (path-mismatch fallback)

_catalog_repository_cache = {}
_media_asset_service_cache = {}


def _catalog_repository_for(base_dir):
    base_dir = Path(base_dir).resolve()
    cache_key = str(base_dir)
    repository = _catalog_repository_cache.get(cache_key)
    if repository is None:
        repository_started = time.perf_counter()
        configured = Path(_user_data_dir).resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        is_temporary = base_dir == temporary_root or temporary_root in base_dir.parents
        database_path = (
            base_dir / '.catalog-test.sqlite'
            if is_temporary or base_dir != configured
            else None
        )
        repository = CatalogRepository(
            base_dir,
            database_path=database_path,
            export_delay=0 if is_temporary else 0.5,
        )
        _startup_metrics['database_open_ms'] = round((time.perf_counter() - repository_started) * 1000, 3)
        migration_started = time.perf_counter()
        repository.activate_from_json()
        _startup_metrics['migration_check_ms'] = round((time.perf_counter() - migration_started) * 1000, 3)
        _catalog_repository_cache[cache_key] = repository
    return repository


def _catalog_repository():
    return _catalog_repository_for(_user_data_dir)


def _media_asset_service():
    repository = _catalog_repository()
    cache_key = str(repository.database_path)
    service = _media_asset_service_cache.get(cache_key)
    if service is None:
        metadata_root = Path(os.environ.get('LOCALAPPDATA') or Path(_user_data_dir).resolve()) / 'Cinema Paradiso' / 'Metadata'
        service = MediaAssetService(repository, metadata_root)
        _media_asset_service_cache[cache_key] = service
    return service

def _norm(path):
    """Normalise a file path for use as a cache key.
    Uses normcase so Windows drive-letter case differences don't cause misses.
    e.g. Plex returns 'e:\\...' while os.walk gives 'E:\\...'
    """
    return os.path.normcase(os.path.normpath(path))
_plex_section_ids = [] # movie section keys — used for triggering rescans
_metadata_cache  = {}  # "{title}_{year}" -> {poster_url, genres, plot, tmdb_rating} — memory-only
_tmdb_genres     = {}  # genre_id -> genre_name, lazy-loaded once from TMDB
_TMDB_CACHE_DIR = _tmdb_cache_dir
_TMDB_LIBRARY_CACHE_FILE = os.path.join(_TMDB_CACHE_DIR, 'tmdb_library_cache.json')
_TMDB_COLLECTION_CACHE_FILE = os.path.join(_TMDB_CACHE_DIR, 'tmdb_collection_cache.json')


def _tmdb_image_url(path, size='w185'):
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else ''


def _load_tmdb_library_cache():
    try:
        with open(_TMDB_LIBRARY_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_tmdb_library_cache(data):
    try:
        os.makedirs(_TMDB_CACHE_DIR, exist_ok=True)
        with open(_TMDB_LIBRARY_CACHE_FILE, 'w', encoding='utf-8') as f:
            _json.dump(data, f, indent=2)
    except Exception:
        pass


def _load_tmdb_collection_cache():
    try:
        with open(_TMDB_COLLECTION_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_tmdb_collection_cache(data):
    try:
        os.makedirs(_TMDB_CACHE_DIR, exist_ok=True)
        with open(_TMDB_COLLECTION_CACHE_FILE, 'w', encoding='utf-8') as f:
            _json.dump(data, f, indent=2)
    except Exception:
        pass


_tmdb_library_cache = _load_tmdb_library_cache()
_tmdb_collection_cache = _load_tmdb_collection_cache()


_curation_store_cache = {'base_dir': '', 'store': None}


def _curation_store():
    base_dir = str(Path(_user_data_dir).resolve())
    if _curation_store_cache.get('base_dir') != base_dir or _curation_store_cache.get('store') is None:
        _curation_store_cache['base_dir'] = base_dir
        _curation_store_cache['store'] = UserCurationStore(
            Path(_user_data_dir),
            catalog=_catalog_repository_for(_user_data_dir),
        )
    return _curation_store_cache['store']


def _prowlarr_client():
    return ProwlarrClient(_prowlarr_url, _prowlarr_key, opener=urllib.request.urlopen)


def _fetch_enabled_prowlarr_indexers():
    return _prowlarr_client().enabled_indexers(timeout=8)


def _is_default_trusted_release_indexer(name):
    text = str(name or '').lower()
    return 'yts' in text or 'yify' in text


def _default_trusted_release_indexer_ids(indexers):
    return [ix['id'] for ix in indexers if _is_default_trusted_release_indexer(ix.get('name'))]


def _effective_trusted_release_indexer_ids(indexers):
    if _trusted_release_indexers_configured:
        return list(_trusted_release_indexers)
    return _default_trusted_release_indexer_ids(indexers)


def _is_yts_indexer_name(name):
    text = str(name or '').lower()
    return 'yts' in text or 'yify' in text


def _enabled_prowlarr_indexer_ids():
    return [indexer['id'] for indexer in _fetch_enabled_prowlarr_indexers()]


def _prowlarr_search(indexer_ids=None, query='', limit=100, categories='2000', timeout=30):
    return _prowlarr_client().search(
        query=query,
        indexer_ids=indexer_ids,
        limit=limit,
        categories=categories,
        timeout=timeout,
    )


def _movie_imdb_id(movie):
    imdb_id = str((movie or {}).get('imdb_id', '') or '').strip()
    if imdb_id:
        return imdb_id
    tmdb_id = str((movie or {}).get('tmdb_id', '') or '').strip()
    if not tmdb_id:
        return ''
    try:
        return str((_fetch_tmdb_metadata_by_id(tmdb_id) or {}).get('imdb_id', '') or '').strip()
    except Exception:
        return ''


def _release_year(value):
    match = re.search(r'(?<!\d)(?:18|19|20|21)\d{2}(?!\d)', str(value or ''))
    return match.group(0) if match else ''


def _release_year_values(values):
    years = []
    for value in values or []:
        year = _release_year(value)
        if year and year not in years:
            years.append(year)
    return years


def _tmdb_release_year_values(movie):
    movie = movie or {}
    values = [movie.get('release_date'), movie.get('year')]
    release_dates = movie.get('release_dates') or {}
    if isinstance(release_dates, dict):
        for country in release_dates.get('results', []) or []:
            for release in (country or {}).get('release_dates', []) or []:
                values.append((release or {}).get('release_date'))
    values.extend(movie.get('release_years') or [])
    return _release_year_values(values)


def _movie_tmdb_metadata_for_source_search(movie):
    tmdb_id = str((movie or {}).get('tmdb_id', '') or '').strip()
    if not tmdb_id:
        return {}
    try:
        store = _metadata_store()
        cached = store.get_tmdb_metadata(tmdb_id) or {}
        refresh = bool(
            _tmdb_key
            and cached
            and not cached.get('release_years_checked_at')
        )
        return _fetch_tmdb_metadata_by_id(tmdb_id, store=store, refresh=refresh) or cached
    except Exception:
        return {}


def _append_source_title_alias(aliases, seen, title):
    title = str(title or '').strip()
    if not title:
        return
    key = _norm_movie_title(title)
    if not key or key in seen:
        return
    seen.add(key)
    aliases.append(title)


def _iter_alternative_title_values(value):
    for item in value or []:
        if isinstance(item, dict):
            yield item.get('title', '')
        else:
            yield item


def _movie_source_title_aliases(movie, metadata=None):
    metadata = metadata or {}
    aliases = []
    seen = set()
    for title in (
        (movie or {}).get('title', ''),
        (movie or {}).get('original_title', ''),
        metadata.get('original_title', ''),
    ):
        _append_source_title_alias(aliases, seen, title)
        if len(aliases) >= SOURCE_SEARCH_ALIAS_LIMIT:
            return aliases

    for title in _iter_alternative_title_values((movie or {}).get('alternative_titles')):
        _append_source_title_alias(aliases, seen, title)
        if len(aliases) >= SOURCE_SEARCH_ALIAS_LIMIT:
            return aliases

    for title in _iter_alternative_title_values((movie or {}).get('title_aliases')):
        _append_source_title_alias(aliases, seen, title)
        if len(aliases) >= SOURCE_SEARCH_ALIAS_LIMIT:
            return aliases

    tmdb_id = str((movie or {}).get('tmdb_id', '') or '').strip()
    if tmdb_id:
        try:
            for title in _smart_match_tmdb_alternative_titles(tmdb_id):
                _append_source_title_alias(aliases, seen, title)
                if len(aliases) >= SOURCE_SEARCH_ALIAS_LIMIT:
                    return aliases
        except Exception:
            pass
    return aliases


def _movie_with_source_title_aliases(movie):
    enriched = dict(movie or {})
    metadata = _movie_tmdb_metadata_for_source_search(enriched)
    if metadata and not enriched.get('imdb_id'):
        enriched['imdb_id'] = metadata.get('imdb_id', '')
    enriched['title_aliases'] = _movie_source_title_aliases(enriched, metadata)
    evidence = _movie_source_release_year_evidence(enriched, metadata)
    enriched['release_year_evidence'] = evidence
    enriched['release_years'] = [item['year'] for item in evidence]
    return enriched


def _movie_source_release_year_evidence(movie, metadata=None):
    movie = movie or {}
    metadata = metadata or {}
    evidence = {}

    def add(value, source):
        year = _release_year(value)
        if not year:
            return
        evidence.setdefault(year, [])
        if source not in evidence[year]:
            evidence[year].append(source)

    add(movie.get('year'), 'requested_year')
    for year in movie.get('release_years') or []:
        add(year, 'provided_release_year')

    primary_year = _release_year(metadata.get('release_date') or metadata.get('year'))
    add(primary_year, 'tmdb_primary_release')
    tmdb_years = _tmdb_release_year_values(metadata)
    if tmdb_years:
        earliest_year = min(tmdb_years, key=int)
        if earliest_year != primary_year:
            add(earliest_year, 'tmdb_earliest_release')

    return [
        {'year': year, 'sources': sources}
        for year, sources in evidence.items()
    ]


def _movie_release_query_plan(movie):
    title = str((movie or {}).get('title', '') or '').strip()
    years = _release_year_values(
        (movie or {}).get('release_years')
        or [(movie or {}).get('year', '')]
    )
    aliases = list((movie or {}).get('title_aliases') or [title])
    plan = []

    def add(query, kind):
        query = str(query or '').strip()
        if not query or any(item['query'] == query for item in plan):
            return
        if len(plan) < SOURCE_SEARCH_QUERY_LIMIT:
            plan.append({'query': query, 'kind': kind})

    imdb_id = _movie_imdb_id(movie)
    if imdb_id:
        add(imdb_id, 'identity')
    if aliases:
        primary_alias, remaining_aliases = aliases[0], aliases[1:]
        for year in years or ['']:
            add(f"{primary_alias} {year}", 'primary_title')
        primary_year = years[0] if years else ''
        for alias in remaining_aliases:
            add(f"{alias} {primary_year}", 'alias')
        for year in years[1:]:
            for alias in remaining_aliases:
                add(f"{alias} {year}", 'alias')
    return plan


def _movie_release_queries(movie):
    return [item['query'] for item in _movie_release_query_plan(movie)]


def _prowlarr_result_matches_movie(result, movie):
    wanted_titles = {
        _norm_movie_title(title)
        for title in [(movie or {}).get('title', ''), *((movie or {}).get('title_aliases') or [])]
        if _norm_movie_title(title)
    }
    wanted_years = set(_release_year_values(
        (movie or {}).get('release_years')
        or [(movie or {}).get('year', '')]
    ))
    if not wanted_titles:
        return True
    torrent_title = str((result or {}).get('title', '') or '')
    parsed_title, parsed_year = parse_movie_title(torrent_title)
    result_title = _norm_movie_title(parsed_title or torrent_title)
    if result_title not in wanted_titles:
        return False
    if not wanted_years:
        return True
    if str(parsed_year or '') in wanted_years:
        return True
    return any(
        re.search(rf'(?<!\d){re.escape(year)}(?!\d)', torrent_title)
        for year in wanted_years
    )


def _is_timeout_error(error):
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(error, 'reason', None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def _remaining_timeout(deadline_at, timeout):
    if deadline_at is None:
        return timeout
    remaining = int(deadline_at - time.monotonic())
    if remaining <= 0:
        return 0
    return max(1, min(timeout, remaining))


def _prowlarr_search_movie(indexer_ids, movie, limit=100, categories='2000', timeout=30, deadline_seconds=None):
    movie = _movie_with_source_title_aliases(movie)
    deadline_at = None
    if deadline_seconds:
        deadline_at = time.monotonic() + max(1, int(deadline_seconds))
    merged = []
    seen = set()
    for query_item in _movie_release_query_plan(movie):
        query = query_item['query']
        if merged and query_item['kind'] == 'alias':
            break
        query_timeout = _remaining_timeout(deadline_at, timeout)
        if query_timeout <= 0:
            break
        try:
            results = _prowlarr_search(
                indexer_ids=indexer_ids,
                query=query,
                limit=limit,
                categories=categories,
                timeout=query_timeout,
            )
        except Exception as error:
            if _is_timeout_error(error):
                continue
            raise
        for result in results:
            if not _prowlarr_result_matches_movie(result, movie):
                continue
            key = _prowlarr_result_key(result)
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
            if len(merged) >= limit:
                return merged
    return merged


def _magnet_url_from_info_hash(info_hash, title=''):
    value = str(info_hash or '').strip()
    if not re.fullmatch(r'[A-Fa-f0-9]{40}', value):
        return ''
    magnet = f"magnet:?xt=urn:btih:{value.upper()}"
    title = str(title or '').strip()
    if title:
        magnet += f"&dn={urllib.parse.quote(title)}"
    return magnet


def _prowlarr_result_links(result):
    raw_magnet = str((result or {}).get('magnetUrl') or '').strip()
    raw_download = str((result or {}).get('downloadUrl') or '').strip()
    magnet_url = ''
    download_url = raw_download
    if raw_magnet.lower().startswith('magnet:'):
        magnet_url = raw_magnet
    elif raw_download.lower().startswith('magnet:'):
        magnet_url = raw_download
        download_url = ''
    else:
        magnet_url = _magnet_url_from_info_hash((result or {}).get('infoHash'), (result or {}).get('title', ''))
        if not download_url and re.match(r'^https?://', raw_magnet, flags=re.I):
            download_url = raw_magnet
    return {'magnet_url': magnet_url, 'download_url': download_url}


def _magnet_from_http_redirect(error):
    if getattr(error, 'code', None) not in (301, 302, 303, 307, 308):
        return ''
    location = ''
    headers = getattr(error, 'headers', None)
    if headers:
        location = headers.get('Location', '')
    location = str(location or '').strip()
    return location if location.lower().startswith('magnet:') else ''


def _torrent_resolution_from_title(title):
    text = str(title or '').lower()
    if '2160p' in text or '4k' in text or 'uhd' in text:
        return '4K'
    if '1080p' in text or re.search(r'[\.\-_ \[\(]1080[\.\-_ \]\)\[]', text):
        return '1080p'
    if '720p' in text or re.search(r'[\.\-_ \[\(]720[\.\-_ \]\)\[]', text):
        return '720p'
    if '480p' in text or re.search(r'[\.\-_ \[\(]480[\.\-_ \]\)\[]', text):
        return '480p'
    return 'Unknown'


def _yts_rss_variant_from_item(item):
    title = item.findtext('title') or ''
    link = item.findtext('link') or ''
    enclosure = item.find('enclosure')
    enclosure_url = enclosure.get('url', '') if enclosure is not None else ''
    hash_match = re.search(r'([A-Fa-f0-9]{40})$', enclosure_url)
    if not title or not link or not hash_match:
        return None
    info_hash = hash_match.group(1).upper()
    parsed_title, parsed_year = parse_movie_title(title)
    parsed_title = parsed_title.title() if parsed_title else re.sub(r'\s*\[[^\]]+\]', '', title).strip()
    title_match = re.match(r'^(.*?)\s*\((\d{4})\)', title)
    if title_match:
        parsed_title = title_match.group(1).strip()
        parsed_year = title_match.group(2)
    return {
        'parsed_title': parsed_title,
        'parsed_year': parsed_year or '',
        'variant': {
            'resolution': _torrent_resolution_from_title(title),
            'seeders': 0,
            'magnet_url': f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(title)}",
            'download_url': '',
            'info_url': link,
            'indexer': 'YTS RSS',
            'size_human': '?',
            'title': title,
        },
    }


def _fetch_yts_rss_latest(limit=100):
    for feed_url in _yts_rss_feeds:
        try:
            req = urllib.request.Request(feed_url, headers={
                'Accept': 'application/rss+xml, application/xml, text/xml',
                'User-Agent': 'CinemaParadiso/2.6 (+https://local.app)',
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                root = _ET.fromstring(resp.read())
            movies = {}
            for item in root.findall('./channel/item'):
                parsed = _yts_rss_variant_from_item(item)
                if not parsed:
                    continue
                key = f"{parsed['parsed_title'].lower()}_{parsed['parsed_year']}"
                if key not in movies:
                    movies[key] = {
                        'parsed_title': parsed['parsed_title'],
                        'parsed_year': parsed['parsed_year'],
                        'variants': [],
                    }
                movies[key]['variants'].append(parsed['variant'])
            rows = []
            for movie in movies.values():
                variants = sorted(
                    movie['variants'],
                    key=lambda item: (get_resolution_rank_str(item.get('resolution')), NumberSafe(item.get('seeders'))),
                    reverse=True,
                )
                best = variants[0] if variants else {}
                rows.append({
                    'parsed_title': movie['parsed_title'],
                    'parsed_year': movie['parsed_year'],
                    'best_seeders': best.get('seeders', 0),
                    'best_resolution': best.get('resolution', 'Unknown'),
                    'indexer': best.get('indexer', 'YTS RSS'),
                    'variants': variants,
                })
            if rows:
                return rows[:limit]
        except Exception:
            continue
    return []


class MetadataStoreError(RuntimeError):
    pass


def _accepted_identity_record_patch(
    current_record,
    identity,
    *,
    provider,
    source,
    facts=None,
    manual_lock=False,
    manual_locked=None,
    metadata_status='accepted',
    metadata_source=None,
    metadata_accepted=True,
    migration_status=None,
    identity_decision_version=None,
    extra=None,
):
    patch = {
        **(facts or {}),
        **accepted_identity_patch(
            current_record,
            identity,
            source=source,
            manual_lock=manual_lock,
        ),
        'display_provider': provider,
        'metadata_status': metadata_status,
        'metadata_source': metadata_source or source,
        'metadata_accepted': bool(metadata_accepted),
    }
    if manual_locked is not None:
        patch['manual_locked'] = bool(manual_locked)
    elif manual_lock:
        patch['manual_locked'] = True
    if migration_status is not None:
        patch['migration_status'] = migration_status
    if identity_decision_version is not None:
        patch['identity_decision_version'] = identity_decision_version
    if extra:
        patch.update(extra)
    return patch


class AppMetadataStore:
    _lock_guard = threading.Lock()
    _path_locks = {}
    _identity_operation_lock = threading.RLock()

    def __init__(self, base_dir):
        self.user_data_dir = Path(base_dir).resolve()
        self.base_dir = self.user_data_dir / 'app_metadata'
        self.files_file = self.base_dir / 'files.json'
        self.tmdb_metadata_file = self.base_dir / 'tmdb_metadata.json'
        self.plex_metadata_file = self.base_dir / 'plex_metadata.json'
        self.manual_matches_file = self.base_dir / 'manual_matches.json'
        self.conflicts_file = self.base_dir / 'conflicts.json'
        self.authority_file = self.base_dir / 'metadata_authority.json'
        self.migration_file = self.base_dir / 'metadata_migration.json'
        self.smart_match_file = self.base_dir / 'smart_match.json'
        self.identity_audit_file = self.base_dir / 'identity_audit.json'
        self.identity_audit_fingerprints_file = self.base_dir / 'identity_audit_fingerprints.json'
        self.smart_rename_file = self.base_dir / 'smart_rename_preview.json'
        self.library_inventory_file = self.base_dir / 'library_inventory.json'
        self.poster_overrides_file = self.base_dir / 'poster_overrides.json'
        self.metadata_overrides_file = self.base_dir / 'metadata_overrides.json'
        self.posters_dir = self.base_dir / 'posters'
        self.catalog = _catalog_repository_for(self.user_data_dir)

    def _document_name(self, path):
        return Path(path).resolve().relative_to(self.user_data_dir).as_posix()

    @classmethod
    def _path_lock(cls, path):
        key = os.path.normcase(os.path.abspath(str(path)))
        with cls._lock_guard:
            return cls._path_locks.setdefault(key, threading.RLock())

    @staticmethod
    def _validated_json(raw, fallback, path):
        try:
            data = _json.loads(raw)
        except Exception as error:
            raise MetadataStoreError(f'Invalid metadata JSON: {path}') from error
        if not isinstance(data, type(fallback)):
            raise MetadataStoreError(f'Unexpected metadata JSON type: {path}')
        return data

    def _read_json(self, path, fallback):
        path = Path(path)
        lock = self._path_lock(path)
        with lock:
            try:
                return self.catalog.read_document(self._document_name(path), fallback)
            except Exception as error:
                raise MetadataStoreError(f'Catalog read failed: {path}') from error

    @staticmethod
    def _atomic_write_text(path, text):
        path = Path(path)
        temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
        try:
            with open(temporary, 'w', encoding='utf-8', newline='\n') as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _write_json(self, path, data):
        path = Path(path)
        serialized = _json.dumps(data, indent=2)
        self._validated_json(serialized, data, path)
        lock = self._path_lock(path)
        with lock:
            self.catalog.replace_document(self._document_name(path), data)
            self.catalog.flush_exports()

    def _mutate_json(self, path, fallback, mutate):
        lock = self._path_lock(path)
        with lock:
            data = self._read_json(path, fallback)
            result = mutate(data)
            self._write_json(path, data)
            return result

    def _key(self, path):
        return _norm(str(path or ''))

    def record_file(self, path, facts):
        with self._identity_operation_lock:
            key = self._key(path)
            record = {**(facts or {}), 'path': str(path or ''), 'updated_at': time.time()}
            return self.catalog.upsert_record('app_metadata/files.json', key, record)

    def update_file_record(self, path, patch):
        with self._identity_operation_lock:
            key = self._key(path)
            current = self.catalog.get_record('app_metadata/files.json', key, {})
            record = {
                **current,
                **(patch or {}),
                'path': str(path or current.get('path', '')),
                'updated_at': time.time(),
            }
            return self.catalog.upsert_record('app_metadata/files.json', key, record)

    def update_file_records_bulk(self, records_by_path):
        updates = dict(records_by_path or {})
        if not updates:
            return 0
        with self._identity_operation_lock:
            files = self.catalog.read_document('app_metadata/files.json', {'files': {}}).get('files', {})
            changed = {}
            for path, patch in updates.items():
                key = self._key(path)
                current = files.get(key, {})
                changed[key] = {
                    **current,
                    **(patch or {}),
                    'path': str(path or current.get('path', '')),
                    'updated_at': time.time(),
                }
            self.catalog.upsert_records('app_metadata/files.json', changed)
            return len(changed)

    def save_tmdb_metadata(self, metadata):
        tmdb_id = str((metadata or {}).get('tmdb_id', '') or '').strip()
        if not tmdb_id:
            return {}
        current = self.catalog.get_record('app_metadata/tmdb_metadata.json', tmdb_id, {})
        saved = {**current, **metadata, 'tmdb_id': tmdb_id, 'updated_at': time.time()}
        release_years = _release_year_values([
            *(current.get('release_years') or []),
            *((metadata or {}).get('release_years') or []),
        ])
        if release_years:
            saved['release_years'] = release_years
        saved['release_years_checked_at'] = max(
            float(current.get('release_years_checked_at', 0) or 0),
            float((metadata or {}).get('release_years_checked_at', 0) or 0),
        )
        return self.catalog.upsert_record('app_metadata/tmdb_metadata.json', tmdb_id, saved)

    def get_tmdb_metadata(self, tmdb_id):
        return self.catalog.get_record('app_metadata/tmdb_metadata.json', str(tmdb_id or ''), {})

    def snapshot(self):
        poster_overrides = self._read_json(self.poster_overrides_file, {'overrides': []}).get('overrides', [])
        metadata_overrides = self._read_json(self.metadata_overrides_file, {'overrides': []}).get('overrides', [])
        return {
            'files': self._read_json(self.files_file, {'files': {}}).get('files', {}),
            'tmdb_movies': self._read_json(self.tmdb_metadata_file, {'movies': {}}).get('movies', {}),
            'plex_files': self._read_json(self.plex_metadata_file, {'files': {}}).get('files', {}),
            'manual_matches': self._read_json(self.manual_matches_file, {'matches': {}}).get('matches', {}),
            'conflicts': self._read_json(self.conflicts_file, {'conflicts': {}}).get('conflicts', {}),
            'poster_overrides': poster_overrides,
            'metadata_overrides': metadata_overrides,
            '_poster_override_index': self._index_overrides(poster_overrides),
            '_metadata_override_index': self._index_overrides(metadata_overrides),
        }

    @staticmethod
    def _index_overrides(overrides):
        index = {}
        for override in overrides or []:
            for key in override.get('identity_keys') or _ownership_keys(override.get('identity', {})):
                index.setdefault(key, []).append(override)
        return index

    @staticmethod
    def _indexed_override(candidate, snapshot, index_name):
        index = (snapshot or {}).get(index_name, {})
        seen = set()
        for key in _ownership_keys(candidate):
            for override in index.get(key, []):
                marker = id(override)
                if marker in seen:
                    continue
                seen.add(marker)
                if len(group_identity_records([candidate, override.get('identity', {})])) == 1:
                    return dict(override)
        return {}

    def repair_authoritative_identities(self, dry_run=True):
        backup_dir = None
        if not dry_run:
            timestamp = time.strftime('%Y%m%d-%H%M%S')
            backup_dir = self.base_dir / 'backups' / timestamp
            backup_dir.mkdir(parents=True, exist_ok=False)
            for source in self.base_dir.glob('*.json'):
                shutil.copy2(source, backup_dir / source.name)
        snapshot = self.snapshot()
        repair = build_identity_repair(
            snapshot.get('files', {}),
            snapshot.get('manual_matches', {}),
            snapshot.get('tmdb_movies', {}),
            snapshot.get('plex_files', {}),
        )
        inventory = self.get_library_inventory()
        recordless = [
            record.get('path') or key
            for key, record in inventory.items()
            if key not in repair['files']
        ]
        report = {
            **repair['report'],
            'recordless_inventory': len(recordless),
            'recordless_paths': recordless,
            'rejected_jobs': 0,
            'dry_run': bool(dry_run),
            'created_at': time.time(),
        }
        storage_errors = []
        try:
            smart_state = self.get_smart_match_state()
        except MetadataStoreError as error:
            smart_state = {}
            storage_errors.append(str(error))
        smart_paths = list(smart_state.get('paths') or [])
        accepted_keys = {
            key for key, record in repair['files'].items()
            if record.get('identity_status') == 'accepted'
        }
        invalid_smart_job = bool(
            smart_paths
            and all(self._key(path) in accepted_keys for path in smart_paths)
        )
        if invalid_smart_job:
            report['rejected_jobs'] = 1
        if storage_errors:
            report['storage_errors'] = storage_errors
            report['rejected_jobs'] += 1
        if dry_run:
            return report

        self._write_json(self.files_file, {
            'files': repair['files'],
            'identity_schema_version': 1,
            'updated_at': time.time(),
        })
        if invalid_smart_job or storage_errors:
            self.save_smart_match_state({
                **smart_state,
                'status': 'invalidated',
                'invalidated_reason': (
                    'Smart Match preview storage was corrupt and has been preserved in the repair backup'
                    if storage_errors
                    else 'All preview paths already have accepted authoritative identities'
                ),
                'updated_at': time.time(),
            })
        audit_state = self.get_identity_audit_state()
        self.save_identity_audit_state({
            **audit_state,
            'status': 'paused' if audit_state.get('status') == 'running' else audit_state.get('status', 'idle'),
            'requires_refresh': True,
            'updated_at': time.time(),
        })
        report['backup_dir'] = str(backup_dir)
        report['dry_run'] = False
        self._write_json(self.base_dir / 'identity_repair_report.json', report)
        return report

    def get_tmdb_metadata_from_snapshot(self, tmdb_id, snapshot):
        return (snapshot or {}).get('tmdb_movies', {}).get(str(tmdb_id or ''), {})

    def get_manual_match_from_snapshot(self, path, snapshot):
        return (snapshot or {}).get('manual_matches', {}).get(self._key(path), {})

    def save_plex_metadata(self, path, metadata):
        key = self._key(path)
        record = {**(metadata or {}), 'path': str(path or ''), 'updated_at': time.time()}
        return self.catalog.upsert_record('app_metadata/plex_metadata.json', key, record)

    def get_plex_metadata(self, path):
        return self.catalog.get_record('app_metadata/plex_metadata.json', self._key(path), {})

    def get_plex_metadata_by_poster_url(self, poster_url):
        thumb = _plex_thumb_from_poster_url(poster_url)
        if not thumb:
            return {}
        return self.catalog.find_plex_metadata_by_thumbs([thumb]).get(thumb, {})

    def accept_tmdb_identity(
        self,
        path,
        tmdb_metadata,
        *,
        source,
        decision_origin,
        manual_lock=False,
        persist_manual=False,
        facts=None,
    ):
        with self._identity_operation_lock:
            metadata = self.save_tmdb_metadata(_normalize_tmdb_metadata(tmdb_metadata))
            tmdb_id = str(metadata.get('tmdb_id', '') or '').strip()
            if not tmdb_id:
                raise ValueError('tmdb_id is required')
            key = self._key(path)
            match = {
                'path': str(path or ''),
                'provider': 'tmdb',
                'source': source,
                'decision_origin': decision_origin,
                'decision_actor': 'user' if decision_origin == 'user_manual' else 'system',
                'tmdb_id': tmdb_id,
                'title': metadata.get('title', ''),
                'year': str(metadata.get('year', '') or ''),
                'imdb_id': str(metadata.get('imdb_id', '') or ''),
                'poster_url': metadata.get('poster_url', ''),
                'accepted': True,
                'updated_at': time.time(),
            }
            if persist_manual:
                self.catalog.upsert_record('app_metadata/manual_matches.json', key, match)
            else:
                self.catalog.delete_records('app_metadata/manual_matches.json', [key])
            current = self._read_json(self.files_file, {'files': {}}).get('files', {}).get(key, {})
            self.update_file_record(path, _accepted_identity_record_patch(
                current,
                metadata,
                provider='tmdb',
                source=source,
                facts=facts,
                manual_lock=manual_lock,
                manual_locked=manual_lock,
                migration_status='matched',
                extra={
                    'decision_origin': decision_origin,
                    'decision_actor': match['decision_actor'],
                    'manual_lock': bool(manual_lock),
                    'manual_locked': bool(manual_lock),
                },
            ))
            return match

    def apply_tmdb_match(self, path, tmdb_metadata, *, facts=None):
        return self.accept_tmdb_identity(
            path,
            tmdb_metadata,
            source='manual_tmdb',
            decision_origin='user_manual',
            manual_lock=True,
            persist_manual=True,
            facts=facts,
        )

    def accept_plex_identity(
        self,
        path,
        plex_metadata,
        *,
        source,
        decision_origin,
        manual_lock=False,
        persist_manual=False,
        facts=None,
    ):
        with self._identity_operation_lock:
            saved = self.save_plex_metadata(path, plex_metadata)
            key = self._key(path)
            match = {
                'path': str(path or ''),
                'provider': 'plex',
                'source': source,
                'decision_origin': decision_origin,
                'decision_actor': 'user' if decision_origin == 'user_manual' else 'system',
                'rating_key': str((plex_metadata or {}).get('rating_key', '') or ''),
                'accepted': True,
                'updated_at': time.time(),
            }
            if persist_manual:
                self.catalog.upsert_record('app_metadata/manual_matches.json', key, match)
            else:
                self.catalog.delete_records('app_metadata/manual_matches.json', [key])
            current = self._read_json(self.files_file, {'files': {}}).get('files', {}).get(key, {})
            self.update_file_record(path, _accepted_identity_record_patch(
                current,
                {
                    'title': saved.get('plex_title', ''),
                    'year': saved.get('plex_year', ''),
                    'tmdb_id': saved.get('tmdb_id', ''),
                    'imdb_id': saved.get('imdb_id', ''),
                    'plex_guid': saved.get('plex_guid', ''),
                    'rating_key': saved.get('rating_key', ''),
                },
                provider='plex',
                source=source,
                facts=facts,
                manual_lock=manual_lock,
                manual_locked=manual_lock,
                migration_status='matched',
                extra={
                    'decision_origin': decision_origin,
                    'decision_actor': match['decision_actor'],
                    'manual_lock': bool(manual_lock),
                    'manual_locked': bool(manual_lock),
                },
            ))
            return {**match, **saved}

    def apply_plex_match(self, path, plex_metadata, *, facts=None):
        return self.accept_plex_identity(
            path,
            plex_metadata,
            source='manual_plex',
            decision_origin='user_manual',
            manual_lock=True,
            persist_manual=True,
            facts=facts,
        )

    def get_manual_match(self, path):
        return self.catalog.get_record('app_metadata/manual_matches.json', self._key(path), {})

    def record_conflict(self, path, conflict):
        data = self._read_json(self.conflicts_file, {'conflicts': {}})
        data.setdefault('conflicts', {})
        key = self._key(path)
        data['conflicts'][key] = {**(conflict or {}), 'path': str(path or ''), 'updated_at': time.time()}
        self._write_json(self.conflicts_file, data)
        return data['conflicts'][key]

    def get_authority_state(self):
        return self._read_json(self.authority_file, {})

    def save_authority_state(self, state):
        payload = {**(state or {}), 'updated_at': time.time()}
        self._write_json(self.authority_file, payload)
        return payload

    def get_migration_state(self):
        return self._read_json(self.migration_file, {})

    def save_migration_state(self, state):
        self._write_json(self.migration_file, state or {})
        return state or {}

    def get_smart_match_state(self):
        return self._read_json(self.smart_match_file, {})

    def save_smart_match_state(self, state):
        self._write_json(self.smart_match_file, state or {})
        return state or {}

    def get_identity_audit_state(self):
        return self._read_json(self.identity_audit_file, {})

    def save_identity_audit_state(self, state):
        self._write_json(self.identity_audit_file, state or {})
        return state or {}

    def get_identity_audit_fingerprints(self):
        return self._read_json(
            self.identity_audit_fingerprints_file,
            {'files': {}},
        ).get('files', {})

    def get_identity_audit_fingerprint(self, path):
        return self.catalog.get_record(
            'app_metadata/identity_audit_fingerprints.json',
            self._key(path),
            {},
        )

    def save_identity_audit_fingerprint(self, path, fingerprint):
        payload = {
            **(fingerprint or {}),
            'path': str(path or ''),
            'verified_at': time.time(),
        }
        return self.catalog.upsert_record(
            'app_metadata/identity_audit_fingerprints.json',
            self._key(path),
            payload,
        )

    def get_smart_rename_preview(self):
        return self._read_json(self.smart_rename_file, {})

    def save_smart_rename_preview(self, preview):
        self._write_json(self.smart_rename_file, preview or {})
        return preview or {}

    def get_library_inventory(self):
        return self._read_json(self.library_inventory_file, {'files': {}}).get('files', {})

    def save_library_inventory(self, inventory):
        payload = {'files': inventory or {}, 'updated_at': time.time()}
        self._write_json(self.library_inventory_file, payload)
        return payload['files']

    def migrate_path_records(self, old_path, new_path):
        old_key = self._key(old_path)
        new_key = self._key(new_path)
        filename = os.path.basename(new_path)
        parsed_title, parsed_year = parse_movie_title(filename)
        self.catalog.migrate_path_records(old_key, new_key, new_path, file_patch={
            'filename': filename,
            'library_root': _path_library_root(new_path) or '',
            'parsed_title': parsed_title,
            'parsed_year': parsed_year,
            'identity_evidence_changed': True,
            'resolution': get_resolution_from_file(new_path),
            'rip_source': get_rip_source(filename),
            'updated_at': time.time(),
        })
        migration = self.get_migration_state()
        changed = False
        for field in ('paths', 'review_paths', 'failed_paths'):
            values = migration.get(field, [])
            replaced = [str(new_path) if self._key(value) == old_key else value for value in values]
            if replaced != values:
                migration[field] = replaced
                changed = True
        if changed:
            self.save_migration_state(migration)
        audit = self.get_identity_audit_state()
        audit_paths = audit.get('paths', [])
        replaced = [str(new_path) if self._key(value) == old_key else value for value in audit_paths]
        if replaced != audit_paths:
            audit['paths'] = replaced
            self.save_identity_audit_state(audit)

    def remove_path_records(self, path):
        self._remove_path_keys({self._key(path)})

    def prune_missing_path_records(self, current_path_keys):
        current = {self._key(path) for path in current_path_keys}
        records = self._read_json(self.files_file, {'files': {}}).get('files', {})
        stale = set(records) - current
        if stale:
            self._remove_path_keys(stale)
        return len(stale)

    def _remove_path_keys(self, path_keys):
        path_keys = {self._key(path) for path in path_keys}
        self.catalog.remove_path_records(path_keys)
        migration = self.get_migration_state()
        changed = False
        for field in ('paths', 'review_paths', 'failed_paths'):
            values = migration.get(field, [])
            kept = [value for value in values if self._key(value) not in path_keys]
            if kept != values:
                migration[field] = kept
                changed = True
        if changed:
            self.save_migration_state(migration)
        audit = self.get_identity_audit_state()
        audit_paths = audit.get('paths', [])
        kept = [value for value in audit_paths if self._key(value) not in path_keys]
        if kept != audit_paths:
            audit['paths'] = kept
            self.save_identity_audit_state(audit)

    def get_poster_override(self, identity, snapshot=None):
        candidate = _poster_identity(identity)
        if not _ownership_keys(candidate):
            return {}
        if snapshot is not None:
            return self._indexed_override(candidate, snapshot, '_poster_override_index')
        overrides = (
            self._read_json(self.poster_overrides_file, {'overrides': []}).get('overrides', [])
        )
        for override in overrides:
            if len(group_identity_records([candidate, override.get('identity', {})])) == 1:
                return dict(override)
        return {}

    def save_poster_override(self, identity, source, image_bytes, extension):
        identity = _poster_identity(identity)
        if not _ownership_keys(identity):
            raise ValueError('Stable movie identity is required')
        extension = str(extension or '').lower()
        if extension not in {'.jpg', '.png', '.webp'}:
            raise ValueError('Unsupported poster image format')
        self.posters_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}{extension}"
        destination = self.posters_dir / filename
        with open(destination, 'wb') as file:
            file.write(image_bytes)
        data = self._read_json(self.poster_overrides_file, {'overrides': []})
        overrides = data.setdefault('overrides', [])
        replaced = []
        kept = []
        for override in overrides:
            if len(group_identity_records([identity, override.get('identity', {})])) == 1:
                replaced.append(override)
            else:
                kept.append(override)
        record = {
            'id': uuid.uuid4().hex,
            'identity': identity,
            'identity_keys': _ownership_keys(identity),
            'source': source,
            'filename': filename,
            'poster_url': f"/api/library/posters/image/{filename}",
            'locked': True,
            'updated_at': time.time(),
        }
        data['overrides'] = [*kept, record]
        self._write_json(self.poster_overrides_file, data)
        referenced = {item.get('filename') for item in data['overrides']}
        for override in replaced:
            old_filename = override.get('filename')
            if old_filename and old_filename not in referenced:
                try:
                    (self.posters_dir / old_filename).unlink()
                except OSError:
                    pass
        return record

    def reset_poster_override(self, identity):
        identity = _poster_identity(identity)
        data = self._read_json(self.poster_overrides_file, {'overrides': []})
        removed = []
        kept = []
        for override in data.setdefault('overrides', []):
            if len(group_identity_records([identity, override.get('identity', {})])) == 1:
                removed.append(override)
            else:
                kept.append(override)
        data['overrides'] = kept
        self._write_json(self.poster_overrides_file, data)
        referenced = {item.get('filename') for item in kept}
        for override in removed:
            filename = override.get('filename')
            if filename and filename not in referenced:
                try:
                    (self.posters_dir / filename).unlink()
                except OSError:
                    pass
        return bool(removed)

    def get_metadata_override(self, identity, snapshot=None):
        candidate = _poster_identity(identity)
        if not _ownership_keys(candidate):
            return {}
        if snapshot is not None:
            return self._indexed_override(candidate, snapshot, '_metadata_override_index')
        overrides = (
            self._read_json(self.metadata_overrides_file, {'overrides': []}).get('overrides', [])
        )
        for override in overrides:
            if len(group_identity_records([candidate, override.get('identity', {})])) == 1:
                return dict(override)
        return {}

    def save_metadata_override(self, identity, title, year):
        identity = _poster_identity(identity)
        if not _ownership_keys(identity):
            raise ValueError('Stable movie identity is required')
        title = re.sub(r'\s+', ' ', str(title or '').strip())
        year = str(year or '').strip()
        if not title:
            raise ValueError('Title is required')
        if year and (len(year) != 4 or not year.isdigit()):
            raise ValueError('Year must be four digits')
        data = self._read_json(self.metadata_overrides_file, {'overrides': []})
        kept = [
            override for override in data.setdefault('overrides', [])
            if len(group_identity_records([identity, override.get('identity', {})])) != 1
        ]
        record = {
            'id': uuid.uuid4().hex,
            'identity': identity,
            'identity_keys': _ownership_keys(identity),
            'title': title,
            'year': year,
            'locked': True,
            'updated_at': time.time(),
        }
        data['overrides'] = [*kept, record]
        self._write_json(self.metadata_overrides_file, data)
        return record

    def reset_metadata_override(self, identity):
        identity = _poster_identity(identity)
        data = self._read_json(self.metadata_overrides_file, {'overrides': []})
        overrides = data.setdefault('overrides', [])
        kept = [
            override for override in overrides
            if len(group_identity_records([identity, override.get('identity', {})])) != 1
        ]
        changed = len(kept) != len(overrides)
        data['overrides'] = kept
        self._write_json(self.metadata_overrides_file, data)
        return changed


def _metadata_store():
    return AppMetadataStore(Path(_user_data_dir))


def _migrate_library_path(old_path, new_path):
    _metadata_store().migrate_path_records(old_path, new_path)
    old_norm = _norm(old_path)
    new_norm = _norm(new_path)
    for cache in (_plex_cache, _plex_unmatched):
        if old_norm in cache:
            record = dict(cache.pop(old_norm) or {})
            record['path'] = str(new_path)
            cache[new_norm] = record
    old_filename = os.path.basename(old_path).lower()
    new_filename = os.path.basename(new_path).lower()
    for cache in (_plex_matched_by_fname, _plex_unmatched_by_fname):
        if old_filename in cache:
            record = dict(cache.pop(old_filename) or {})
            record['path'] = str(new_path)
            cache[new_filename] = record
    _library_cache.clear()


def _evict_removed_library_path_from_caches(path):
    path_norm = _norm(path)
    for cache in (_plex_cache, _plex_unmatched):
        cache.pop(path_norm, None)
    filename = os.path.basename(path).lower()
    for cache in (_plex_matched_by_fname, _plex_unmatched_by_fname):
        cached = cache.get(filename) or {}
        if not cached or _norm(cached.get('path', '')) == path_norm:
            cache.pop(filename, None)
    _library_cache.clear()


def _delete_library_file(path, *, use_trash=True):
    service = LibraryMutationService(
        get_movies_dirs(),
        _metadata_store(),
        VIDEO_EXTENSIONS,
    )
    result = service.delete(path, use_trash=use_trash)
    _evict_removed_library_path_from_caches(result['deleted'])
    return result


def _year_from_movie(movie, fallback=''):
    release = str((movie or {}).get('release_date', '') or '')
    year = str((movie or {}).get('year', '') or '')
    return release[:4] if release else year or str(fallback or '')


def _normalize_tmdb_genres(raw):
    if not raw:
        return []
    genres = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get('name')
            if name:
                genres.append(name)
        elif isinstance(item, int) and item in _tmdb_genres:
            genres.append(_tmdb_genres[item])
        elif isinstance(item, str):
            genres.append(item)
    return genres[:5]


def _normalize_tmdb_metadata(movie):
    movie = movie or {}
    tmdb_id = str(movie.get('tmdb_id', '') or movie.get('id', '') or '').strip()
    poster = movie.get('poster_url') or _tmdb_image_url(movie.get('poster_path'), 'w342')
    backdrop = movie.get('backdrop_url') or _tmdb_image_url(movie.get('backdrop_path'), 'w780')
    vote = movie.get('tmdb_rating', '')
    if not vote:
        raw_vote = movie.get('vote_average', 0)
        vote = f"{raw_vote:.1f}" if isinstance(raw_vote, (int, float)) and raw_vote else ''
    vote_count = movie.get('tmdb_vote_count', movie.get('vote_count', 0) or 0)
    try:
        vote_count = int(vote_count or 0)
    except Exception:
        vote_count = 0
    lang = movie.get('original_language', '')
    country = movie.get('country', '')
    countries = movie.get('origin_country') or movie.get('production_countries') or []
    if not country and countries:
        first = countries[0]
        country = first.get('iso_3166_1', '') if isinstance(first, dict) else str(first or '')
    if not country and lang:
        country = _LANG_COUNTRY.get(lang, '')
    return {
        'tmdb_id': tmdb_id,
        'imdb_id': str(movie.get('imdb_id', '') or ''),
        'title': movie.get('title') or movie.get('name') or '',
        'original_title': movie.get('original_title') or movie.get('original_name') or '',
        'original_language': lang,
        'year': _year_from_movie(movie),
        'poster_url': poster,
        'backdrop_url': backdrop,
        'genres': _normalize_tmdb_genres(movie.get('genres') or movie.get('genre_ids') or []),
        'tmdb_rating': str(vote or ''),
        'tmdb_vote_count': vote_count,
        'popularity': float(movie.get('popularity', 0) or 0),
        'plot': movie.get('plot') or movie.get('overview', ''),
        'language': movie.get('language') or _LANG_NAMES.get(lang, lang.upper() if lang else ''),
        'country': country,
        'country_flag': movie.get('country_flag') or _country_flag(country),
        'release_date': movie.get('release_date', '') or '',
        'release_years': _tmdb_release_year_values(movie),
        'release_years_checked_at': float(movie.get('release_years_checked_at', 0) or 0),
        'runtime': movie.get('runtime'),
        'tagline': movie.get('tagline', ''),
        'directors': movie.get('directors', []),
        'director': movie.get('director', {}),
        'cast': movie.get('cast', []),
        'collection': movie.get('collection', {}),
        'trailer_url': movie.get('trailer_url', ''),
        'match_source': movie.get('match_source', ''),
        'adult': bool(movie.get('adult', False)),
    }


def _tmdb_is_auto_accepted(file_facts, tmdb_data):
    if not tmdb_data:
        return False
    if tmdb_data.get('match_source') == 'plex_tmdb_id':
        return True
    return _same_public_identity(
        file_facts.get('parsed_title', ''),
        file_facts.get('parsed_year', ''),
        tmdb_data.get('title', ''),
        tmdb_data.get('year', ''),
    )


def _metadata_is_pending(file_facts):
    return str((file_facts or {}).get('ingest_status') or '') == 'pending'


def _metadata_missing_status(file_facts):
    if _metadata_is_pending(file_facts):
        return 'pending'
    if str((file_facts or {}).get('stored_metadata_status') or '') == 'needs_review':
        return 'needs_review'
    return 'unmatched'


def _plex_to_canonical(plex_data, source='plex'):
    return {
        'accepted': True,
        'status': 'accepted',
        'source': source,
        'title': plex_data.get('plex_title', ''),
        'year': str(plex_data.get('plex_year', '') or ''),
        'tmdb_id': str(plex_data.get('tmdb_id', '') or ''),
        'imdb_id': str(plex_data.get('imdb_id', '') or ''),
        'plex_guid': str(plex_data.get('plex_guid', '') or ''),
        'poster_url': plex_data.get('plex_poster', ''),
        'genres': plex_data.get('plex_genres', []),
        'plot': plex_data.get('plex_summary', ''),
        'summary': plex_data.get('plex_summary', ''),
        'rating': plex_data.get('plex_rating', ''),
        'plex_rating': plex_data.get('plex_rating', ''),
        'tmdb_rating': '',
        'tmdb_vote_count': 0,
        'language': plex_data.get('plex_language', ''),
        'country': plex_data.get('plex_country', ''),
        'country_flag': plex_data.get('plex_country_flag', ''),
        'directors': plex_data.get('plex_directors', []),
        'director': (plex_data.get('plex_directors') or [{}])[0] if plex_data.get('plex_directors') else {},
        'cast': plex_data.get('plex_cast', []),
    }


def _tmdb_to_canonical(tmdb_data, source='tmdb'):
    metadata = _normalize_tmdb_metadata(tmdb_data)
    return {
        **metadata,
        'accepted': True,
        'status': 'accepted',
        'source': source,
        'summary': metadata.get('plot', ''),
        'rating': metadata.get('tmdb_rating', ''),
    }


def _canonical_provider_metadata(display_provider='', tmdb_data=None, plex_data=None):
    """Select and normalize the single provider payload used for display metadata."""
    tmdb_data = tmdb_data or {}
    plex_data = plex_data or {}
    has_tmdb = bool(tmdb_data.get('tmdb_id') and tmdb_data.get('title'))
    has_plex = bool(plex_data.get('plex_title'))
    if display_provider == 'plex' and has_plex:
        return _plex_to_canonical(plex_data, 'plex_snapshot')
    if display_provider == 'tmdb' and has_tmdb:
        return _tmdb_to_canonical(tmdb_data, 'tmdb_snapshot')
    if has_tmdb:
        return _tmdb_to_canonical(tmdb_data, 'tmdb_snapshot')
    if has_plex:
        return _plex_to_canonical(plex_data, 'plex_snapshot')
    return {}


def _build_canonical_metadata(
    file_facts,
    plex_data=None,
    tmdb_data=None,
    manual_match=None,
    display_provider='',
    file_record=None,
):
    authoritative_record_supplied = file_record is not None
    file_facts = file_facts or {}
    plex_data = plex_data or {}
    tmdb_data = tmdb_data or {}
    manual_match = manual_match or {}
    file_record = file_record or {}
    has_plex = bool(plex_data.get('plex_title'))
    has_tmdb = bool(tmdb_data.get('tmdb_id') and tmdb_data.get('title'))
    provider_metadata = _canonical_provider_metadata(display_provider, tmdb_data, plex_data)

    resolved = resolve_authoritative_identity(
        file_record,
        provider_metadata=provider_metadata,
        fallback={
            'title': file_facts.get('parsed_title', ''),
            'year': file_facts.get('parsed_year', ''),
        },
    )
    if resolved.get('accepted'):
        canonical = provider_metadata or {
            'poster_url': '',
            'genres': [],
            'plot': '',
            'summary': '',
            'rating': '',
            'tmdb_rating': '',
            'tmdb_vote_count': 0,
        }
        return {
            **canonical,
            'accepted': True,
            'status': 'accepted',
            'identity_status': 'accepted',
            'enrichment_status': resolved.get('enrichment_state', 'incomplete'),
            'source': resolved.get('identity_source') or canonical.get('source', ''),
            'detail_provider': canonical.get('source', ''),
            'title': resolved.get('title') or canonical.get('title', ''),
            'year': resolved.get('year') or canonical.get('year', ''),
            'tmdb_id': resolved.get('tmdb_id') or canonical.get('tmdb_id', ''),
            'imdb_id': resolved.get('imdb_id') or canonical.get('imdb_id', ''),
            'plex_guid': resolved.get('plex_guid') or canonical.get('plex_guid', ''),
            'identity_revision': resolved.get('identity_revision', 0),
        }

    if authoritative_record_supplied:
        identity_status = resolved.get('identity_state', 'unmatched')
        if file_record.get('ingest_status') == 'pending' or file_record.get('metadata_status') == 'pending':
            identity_status = 'pending'
        candidate = tmdb_data if has_tmdb else {}
        return {
            **(_tmdb_to_canonical(candidate, 'tmdb_candidate') if candidate else {}),
            'accepted': False,
            'status': 'needs_review' if identity_status == 'review' else identity_status,
            'identity_status': identity_status,
            'enrichment_status': resolved.get('enrichment_state', 'incomplete'),
            'source': '',
            'detail_provider': _tmdb_to_canonical(candidate, 'tmdb_candidate').get('source', '') if candidate else '',
            'title': candidate.get('title', '') if candidate else '',
            'year': str(candidate.get('year', '') or '') if candidate else '',
            'tmdb_id': str(candidate.get('tmdb_id', '') or '') if candidate else '',
            'imdb_id': str(candidate.get('imdb_id', '') or '') if candidate else '',
            'poster_url': candidate.get('poster_url', '') if candidate else '',
            'genres': candidate.get('genres', []) if candidate else [],
            'plot': candidate.get('plot', '') if candidate else '',
            'summary': candidate.get('summary', '') if candidate else '',
            'rating': candidate.get('tmdb_rating', '') if candidate else '',
            'tmdb_rating': candidate.get('tmdb_rating', '') if candidate else '',
            'tmdb_vote_count': candidate.get('tmdb_vote_count', 0) if candidate else 0,
            'identity_revision': resolved.get('identity_revision', 0),
        }

    if manual_match.get('provider') == 'tmdb' and has_tmdb:
        return _tmdb_to_canonical(tmdb_data, 'manual_tmdb')

    if display_provider == 'tmdb':
        if has_tmdb:
            return _tmdb_to_canonical(tmdb_data, 'tmdb_snapshot')
        status = _metadata_missing_status(file_facts)
        return {
            'accepted': False,
            'status': status,
            'source': 'filename',
            'title': '',
            'year': '',
            'tmdb_id': '',
            'imdb_id': '',
            'poster_url': '',
            'genres': [],
            'plot': '',
            'summary': '',
            'rating': '',
            'tmdb_rating': '',
            'tmdb_vote_count': 0,
        }

    if display_provider == 'plex':
        if has_plex:
            return _plex_to_canonical(plex_data, 'plex_snapshot')
        status = _metadata_missing_status(file_facts)
        return {
            'accepted': False,
            'status': status,
            'source': 'filename',
            'title': '',
            'year': '',
            'tmdb_id': '',
            'imdb_id': '',
            'poster_url': '',
            'genres': [],
            'plot': '',
            'summary': '',
            'rating': '',
            'tmdb_rating': '',
            'tmdb_vote_count': 0,
        }

    if display_provider == 'filename':
        status = _metadata_missing_status(file_facts)
        return {
            'accepted': False,
            'status': status,
            'source': 'filename',
            'title': '',
            'year': '',
            'tmdb_id': '',
            'imdb_id': '',
            'poster_url': '',
            'genres': [],
            'plot': '',
            'summary': '',
            'rating': '',
            'tmdb_rating': '',
            'tmdb_vote_count': 0,
        }

    if manual_match.get('provider') == 'plex' and has_plex and not has_tmdb:
        return _plex_to_canonical(plex_data, 'manual_plex')

    if has_plex and has_tmdb and tmdb_data.get('match_source') != 'plex_tmdb_id':
        if not _same_public_identity(
            plex_data.get('plex_title', ''),
            plex_data.get('plex_year', ''),
            tmdb_data.get('title', ''),
            tmdb_data.get('year', ''),
        ):
            return {
                'accepted': False,
                'status': 'conflict',
                'source': '',
                'title': '',
                'year': '',
                'tmdb_id': str(tmdb_data.get('tmdb_id', '') or ''),
                'plex_title': plex_data.get('plex_title', ''),
                'plex_year': str(plex_data.get('plex_year', '') or ''),
                'tmdb_title': tmdb_data.get('title', ''),
                'tmdb_year': str(tmdb_data.get('year', '') or ''),
            }

    if has_tmdb and _tmdb_is_auto_accepted(file_facts, tmdb_data):
        return _tmdb_to_canonical(tmdb_data, 'tmdb')

    if has_tmdb:
        return {
            **_tmdb_to_canonical(tmdb_data, 'tmdb_candidate'),
            'accepted': False,
            'status': 'needs_review',
            'source': '',
        }

    if has_plex:
        return _plex_to_canonical(plex_data, 'plex')

    status = _metadata_missing_status(file_facts)
    return {
        'accepted': False,
        'status': status,
        'source': '',
        'title': '',
        'year': '',
        'tmdb_id': '',
        'imdb_id': '',
        'poster_url': '',
        'genres': [],
        'plot': '',
        'summary': '',
        'rating': '',
        'tmdb_rating': '',
        'tmdb_vote_count': 0,
    }


def _poster_identity(identity):
    identity = identity or {}
    return {
        'tmdb_id': str(identity.get('tmdb_id', '') or '').strip(),
        'imdb_id': str(identity.get('imdb_id', '') or '').strip(),
        'plex_guid': str(identity.get('plex_guid', '') or '').strip(),
        'title': str(identity.get('title', '') or '').strip(),
        'year': str(identity.get('year', '') or '').strip(),
    }


def _poster_identity_for_movie(file_facts, canonical, plex_data=None):
    plex_data = plex_data or {}
    return _poster_identity({
        'tmdb_id': canonical.get('tmdb_id') or plex_data.get('tmdb_id'),
        'imdb_id': canonical.get('imdb_id') or plex_data.get('imdb_id'),
        'plex_guid': canonical.get('plex_guid') or plex_data.get('plex_guid'),
        'title': canonical.get('title') or plex_data.get('plex_title') or file_facts.get('parsed_title'),
        'year': canonical.get('year') or plex_data.get('plex_year') or file_facts.get('parsed_year'),
    })


def _apply_poster_override(canonical, identity, store=None, snapshot=None):
    canonical = dict(canonical or {})
    if not canonical.get('accepted'):
        return canonical
    store = store or _metadata_store()
    override = store.get_poster_override(identity, snapshot=snapshot)
    if not override:
        return canonical
    return {
        **canonical,
        'poster_url': override.get('poster_url', canonical.get('poster_url', '')),
        'poster_override': True,
        'poster_override_source': override.get('source', ''),
        'poster_override_locked': bool(override.get('locked')),
    }


def _apply_metadata_override(canonical, identity, store=None, snapshot=None):
    canonical = dict(canonical or {})
    if not canonical.get('accepted'):
        return canonical
    store = store or _metadata_store()
    override = store.get_metadata_override(identity, snapshot=snapshot)
    if not override:
        return canonical
    return {
        **canonical,
        'provider_title': canonical.get('title', ''),
        'provider_year': str(canonical.get('year', '') or ''),
        'title': override.get('title', canonical.get('title', '')),
        'year': str(override.get('year', canonical.get('year', '')) or ''),
        'metadata_override': True,
        'metadata_override_locked': bool(override.get('locked')),
    }
_TV_RE = re.compile(
    r'(?:s\d{1,2}e\d{1,2}|\d{1,2}x\d{2}|season[\s._-]*\d|episode[\s._-]*\d'
    r'|\bep[\s._-]*\d{1,3}\b|complete[\s._-]+series|\bcomplete[\s._-]+season)',
    re.IGNORECASE
)
_MOVIE_FOLDER_RE = re.compile(r'\b(19|20)\d{2}\b')  # folder name looks like a movie title
_LANG_NAMES = {
    'en':'English','fr':'French','es':'Spanish','de':'German','it':'Italian',
    'pt':'Portuguese','ru':'Russian','ja':'Japanese','ko':'Korean','zh':'Chinese',
    'ar':'Arabic','hi':'Hindi','tr':'Turkish','nl':'Dutch','sv':'Swedish',
    'pl':'Polish','da':'Danish','fi':'Finnish','no':'Norwegian','th':'Thai',
    'vi':'Vietnamese','id':'Indonesian','cs':'Czech','hu':'Hungarian','ro':'Romanian',
}
_LANG_COUNTRY = {
    'en':'US','fr':'FR','es':'ES','de':'DE','it':'IT','pt':'PT','ru':'RU',
    'ja':'JP','ko':'KR','zh':'CN','ar':'SA','hi':'IN','tr':'TR','nl':'NL',
    'sv':'SE','pl':'PL','da':'DK','fi':'FI','no':'NO','th':'TH','vi':'VN',
    'id':'ID','cs':'CZ','hu':'HU','ro':'RO',
}
def _country_flag(code):
    if not code or len(code) != 2: return ''
    return chr(ord(code[0].upper())+127397) + chr(ord(code[1].upper())+127397)

_res_cache = {}  # (abspath, mtime) -> resolution_str  — resolution probe cache
_res_cache_reprobe = set()  # legacy cache entries that need one width-aware probe
_RES_CACHE_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'res_cache.json')
_RES_CACHE_VERSION = 2
_library_status  = ''  # live status string polled by the browser during a scan
_plex_cache_time = 0.0
_PLEX_TTL        = 300  # seconds before auto-refresh
_library_cache   = {}   # keys: items, plex_enabled, plex_cached, time
_LIBRARY_TTL     = 300  # seconds — same as Plex TTL
_LIBRARY_FAST_CACHE_TTL = 2  # seconds: avoid repeat directory walks during one UI workflow
_stats_cache = {}
_maintenance_audit_cache = {'generation': None, 'audit': None}
_identity_verification_audit_cache = {'revision': None, 'audit': None}
_STATS_CACHE_TTL = 10
_FILE_STABILITY_SECONDS = 15
FILE_FACTS_VERSION = 1
IDENTITY_DECISION_VERSION = 5
_metadata_migration_coordinator = None
_metadata_migration_store_dir = ''
_smart_match_coordinator = None
_smart_match_store_dir = ''
_identity_audit_coordinator = None
_identity_audit_store_dir = ''
_smart_match_tmdb_alias_cache = {}
_library_reconcile_lock = threading.RLock()
_library_reconcile_run_lock = threading.Lock()
_library_reconcile_thread = None
_library_reconcile_state = {
    'status': 'idle',
    'checked': 0,
    'matched': 0,
    'review': 0,
    'pending': 0,
    'failed': 0,
    'updated_at': 0,
}
_qbittorrent_manager = None
_qbittorrent_manager_key = None

def _all_config():
    config = {
        'movies_dir': _movies_dir,
        'movies_dirs': _movies_dirs,
        'prowlarr_url': _prowlarr_url,
        'prowlarr_key': _prowlarr_key,
        'plex_url': _plex_url,
        'plex_token': _plex_token,
        'tmdb_key': _tmdb_key,
        'tmdb_include_adult': _tmdb_include_adult,
        'library_show_adult': _library_show_adult,
        'ollama_url': _ollama_url,
        'ollama_model': _ollama_model,
        'ollama_candidate_limit': _ollama_candidate_limit,
        'ai_control_enabled': _ai_control_config['enabled'],
        'ai_control_max_matched_movies': _ai_control_config['max_matched_movies'],
        'ai_control_max_download_searches': _ai_control_config['max_download_searches'],
        'ai_control_ollama_curated_lists': _ai_control_config['ollama_curated_lists'],
        'streaming_enabled': _streaming_enabled,
        'streaming_label': _streaming_label,
        'streaming_url_template': _streaming_url_template,
        'user_data_dir': _user_data_dir,
        'tmdb_cache_dir': _tmdb_cache_dir,
        'qbt_mode': _qbt_mode,
        'qbt_download_dir': _qbt_download_dir,
        'qbt_incomplete_dir': _qbt_incomplete_dir,
        'qbt_webui_port': _qbt_webui_port,
        'download_default_quality': _download_default_quality,
        'download_indexer_mode': _download_indexer_mode,
        'download_trusted_indexers': _download_trusted_indexers,
    }
    if _ai_control_trusted_indexers_configured:
        config['ai_control_trusted_indexers'] = _ai_control_config['trusted_indexers']
    if _trusted_release_indexers_configured:
        config['trusted_release_indexers'] = _trusted_release_indexers
    return config

VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.m4v', '.mov', '.wmv', '.flv', '.ts', '.m2ts', '.iso'}

try:
    from pymediainfo import MediaInfo as _MediaInfo
    _MEDIAINFO_AVAILABLE = True
except ImportError:
    _MediaInfo = None
    _MEDIAINFO_AVAILABLE = False


def get_movies_dir():
    return _movies_dir


def get_movies_dirs():
    return list(_movies_dirs)


def _get_qbittorrent_manager():
    global _qbittorrent_manager, _qbittorrent_manager_key
    settings = {
        'mode': _qbt_mode,
        'download_dir': _qbt_download_dir,
        'incomplete_dir': _qbt_incomplete_dir,
        'webui_port': _qbt_webui_port,
    }
    key = (
        os.path.abspath(_user_data_dir),
        tuple(get_movies_dirs()),
        tuple(sorted(settings.items())),
    )
    if _qbittorrent_manager is None or _qbittorrent_manager_key != key:
        _qbittorrent_manager = QBittorrentManager(_user_data_dir, settings, get_movies_dirs())
        _qbittorrent_manager_key = key
    return _qbittorrent_manager


def _completed_download_video_paths(imported_paths):
    videos = []
    seen = set()
    for imported_path in imported_paths or []:
        candidate = os.path.abspath(str(imported_path or ''))
        if not candidate:
            continue
        if os.path.isfile(candidate):
            paths = [candidate]
        elif os.path.isdir(candidate):
            paths = [
                os.path.join(root, filename)
                for root, _, filenames in os.walk(candidate)
                for filename in filenames
            ]
        else:
            paths = []
        for path in paths:
            if os.path.splitext(path)[1].lower() not in VIDEO_EXTENSIONS:
                continue
            key = _norm(path)
            if key in seen:
                continue
            seen.add(key)
            videos.append(path)
    return sorted(videos, key=lambda path: (-int(_metadata_file_facts(path).get('size') or 0), _norm(path)))


def _apply_completed_download_identity(job, store=None):
    job = dict(job or {})
    tmdb_id = str(job.get('tmdb_id') or '').strip()
    imdb_id = str(job.get('imdb_id') or '').strip()
    if not tmdb_id and not imdb_id:
        return {
            'state': 'deferred',
            'reason': 'The download job has no stable identity',
            'paths': [],
        }
    paths = _completed_download_video_paths(job.get('imported_paths') or [])
    if not paths:
        return {
            'state': 'deferred',
            'reason': 'No imported video file is available for identity handoff',
            'paths': [],
        }
    path = paths[0]
    store = store or _metadata_store()
    if tmdb_id:
        metadata = _fetch_tmdb_metadata_by_id(
            tmdb_id,
            store=store,
            refresh=not bool(store.get_tmdb_metadata(tmdb_id)),
            match_source='download_submission',
        )
    else:
        metadata = _fetch_tmdb_metadata_by_imdb(imdb_id, store=store, match_source='download_submission')
        tmdb_id = str(metadata.get('tmdb_id') or '').strip()
    if not tmdb_id:
        return {
            'state': 'deferred',
            'reason': 'The download identity could not be resolved to TMDB',
            'paths': [],
            'imdb_id': imdb_id,
        }
    metadata = {
        **metadata,
        'tmdb_id': tmdb_id,
        'imdb_id': str(metadata.get('imdb_id') or imdb_id).strip(),
        'title': str(metadata.get('title') or job.get('title') or '').strip(),
        'year': str(metadata.get('year') or job.get('year') or '').strip(),
    }
    store.accept_tmdb_identity(
        path,
        metadata,
        source='download_submission',
        decision_origin=DECISION_ORIGIN_LIBRARY_RECONCILE,
        facts=_metadata_file_facts(path),
    )
    return {'state': 'applied', 'paths': [path], 'tmdb_id': tmdb_id}


def _handle_completed_qbittorrent_imports(manager, results):
    global _library_cache
    completed = [
        item for item in (results or [])
        if item.get('state') in {'imported', 'cleanup_failed'}
        and (
            item.get('library_scan_pending', item.get('state') == 'imported')
            or not str((item.get('identity_handoff') or {}).get('state') or '')
        )
    ]
    pending = [
        item for item in completed
        if any(
            is_path_within(path, root)
            for path in item.get('imported_paths', [])
            for root in get_movies_dirs()
        )
    ]
    outside_library = [
        item for item in completed
        if item.get('state') == 'imported' and item not in pending
    ]
    if not pending and not outside_library:
        return False
    if pending:
        _library_cache = {}
        store = _metadata_store()
        handoffs = {}
        for item in pending:
            key = str(item.get('hash') or '')
            try:
                handoffs[key] = _apply_completed_download_identity(item, store=store)
            except Exception as error:
                handoffs[key] = {
                    'state': 'failed',
                    'reason': str(error),
                    'paths': [],
                }
        if any(handoff.get('state') != 'failed' for handoff in handoffs.values()):
            _start_library_reconcile(force=True)
        for item in pending:
            if not item.get('hash'):
                continue
            handoff = handoffs.get(str(item.get('hash') or ''), {})
            manager.jobs.upsert(item['hash'], {
                'library_scan_pending': handoff.get('state') == 'failed',
                'identity_handoff': handoff,
            })
    for item in outside_library:
        if item.get('hash'):
            manager.jobs.upsert(item['hash'], {
                'library_scan_pending': False,
                'identity_handoff': {
                    'state': 'deferred',
                    'reason': 'Imported payload is outside the configured movie libraries',
                    'paths': list(item.get('imported_paths') or []),
                },
            })
    return True


_qbittorrent_import_monitor = DownloadImportMonitor(
    _get_qbittorrent_manager,
    _handle_completed_qbittorrent_imports,
)


def _metadata_cache_revision(store=None):
    repository = (store or _metadata_store()).catalog
    return ('catalog', str(repository.database_path), repository.generation('media'))


def _library_roots_revision():
    return tuple(_norm(path) for path in get_movies_dirs())


def _library_roots_stat_revision():
    revision = []
    for movies_dir in get_movies_dirs():
        root = os.path.abspath(movies_dir)
        try:
            stat_result = os.stat(root)
            revision.append((_norm(root), stat_result.st_mtime_ns, stat_result.st_size))
        except OSError:
            revision.append((_norm(root), 0, 0))
    return tuple(revision)


def _current_catalog_store(store=None):
    return (store or _metadata_store()).catalog.store


def _library_cache_key(directory_revision=None, metadata_revision=None, store=None):
    return (
        _library_roots_revision(),
        directory_revision if directory_revision is not None else _library_directory_revision(),
        metadata_revision if metadata_revision is not None else _metadata_cache_revision(store),
    )


def _fresh_library_cache_items():
    if _library_cache.get('items') is None:
        return None
    cache_time = float(_library_cache.get('time', 0) or 0)
    age = time.time() - cache_time
    if age >= _LIBRARY_TTL:
        return None
    metadata_revision = _metadata_cache_revision()
    cached_metadata_revision = _library_cache.get('metadata_revision')
    if cached_metadata_revision is not None and cached_metadata_revision != metadata_revision:
        return None
    if (
        age <= _LIBRARY_FAST_CACHE_TTL
        and _library_cache.get('roots') == _library_roots_revision()
        and _library_cache.get('roots_stat') == _library_roots_stat_revision()
    ):
        return _library_cache.get('items') or []
    cache_key = _library_cache_key(metadata_revision=metadata_revision)
    if _library_cache.get('dir') == cache_key:
        return _library_cache.get('items') or []
    return None


def _fresh_catalog_library_items(store=None):
    if _library_cache.get('source') != 'catalog' or _library_cache.get('items') is None:
        return None
    if _library_cache.get('roots') != _library_roots_revision():
        return None
    if _library_cache.get('metadata_revision') != _metadata_cache_revision(store):
        return None
    return _library_cache.get('items') or []


def _store_library_cache(items, plex_enabled, plex_cached, cache_key=None):
    cache_key = cache_key or _library_cache_key()
    _library_cache['items'] = items
    _library_cache['plex_enabled'] = bool(plex_enabled)
    _library_cache['plex_cached'] = bool(plex_cached)
    _library_cache['time'] = time.time()
    _library_cache['dir'] = cache_key
    _library_cache['roots'] = cache_key[0]
    _library_cache['metadata_revision'] = cache_key[2]
    _library_cache['roots_stat'] = _library_roots_stat_revision()


def _stats_cache_key():
    return (
        _library_roots_revision(),
        _library_roots_stat_revision(),
        _metadata_cache_revision(),
        _plex_cache_time,
    )


def _fresh_stats_cache(cache_key=None):
    if not _stats_cache.get('payload'):
        return None
    cache_key = cache_key or _stats_cache_key()
    if _stats_cache.get('key') != cache_key:
        return None
    if time.time() - float(_stats_cache.get('time', 0) or 0) >= _STATS_CACHE_TTL:
        return None
    return dict(_stats_cache.get('payload') or {})


def _store_stats_cache(payload, cache_key=None):
    _stats_cache['payload'] = dict(payload or {})
    _stats_cache['key'] = cache_key or _stats_cache_key()
    _stats_cache['time'] = time.time()


def _trim_people_for_card(people, limit=8):
    result = []
    for person in (people or [])[:limit]:
        if not isinstance(person, dict):
            continue
        result.append({
            'id': str(person.get('id', '') or ''),
            'name': person.get('name', '') or '',
            'character': person.get('character', '') or '',
            'profile_url': person.get('profile_url', '') or '',
        })
    return result


def _movie_list_library_item(item, include_people=False, upgrade_paths=None):
    source_canonical = item.get('canonical_metadata') or {}
    canonical = (
        canonical_details_projection(source_canonical)
        if include_people
        else canonical_card_projection(source_canonical)
    )
    accepted = bool(source_canonical.get('accepted'))
    if include_people:
        canonical['cast'] = _trim_people_for_card(source_canonical.get('cast'))
        canonical['directors'] = _trim_people_for_card(
            source_canonical.get('directors'),
            limit=4,
        )
    projected = {
        'title': item.get('title', ''),
        'filename': item.get('filename', ''),
        'path': item.get('path', ''),
        'library_root': item.get('library_root', ''),
        'resolution': item.get('resolution', 'Unknown'),
        'rip_source': item.get('rip_source', 'Unknown'),
        'size': item.get('size', 0),
        'size_human': item.get('size_human', ''),
        'added_time': item.get('added_time', 0),
        'modified_time': item.get('modified_time', 0),
        'plex_title': item.get('plex_title', ''),
        'plex_year': item.get('plex_year', ''),
        'plex_genres': item.get('plex_genres', []),
        'plex_summary': '' if accepted else item.get('plex_summary', ''),
        'plex_rating': item.get('plex_rating', ''),
        'plex_language': item.get('plex_language', ''),
        'plex_country_flag': item.get('plex_country_flag', ''),
        'plex_country': item.get('plex_country', ''),
        'plex_directors': [],
        'plex_cast': [],
        'tmdb_id': item.get('tmdb_id', ''),
        'imdb_id': item.get('imdb_id', ''),
        'plex_guid': item.get('plex_guid', ''),
        'plex_poster': item.get('plex_poster', ''),
        'plex_matched': bool(item.get('plex_matched')),
        'canonical_metadata': canonical,
        'metadata_status': item.get('metadata_status', ''),
        'metadata_source': item.get('metadata_source', ''),
        'metadata_accepted': bool(item.get('metadata_accepted')),
    }
    if upgrade_paths is not None:
        projected['maintenance_upgrade_candidate'] = _norm(item.get('path', '')) in upgrade_paths
    return projected


def _library_card_item(item, upgrade_paths=None):
    full = _movie_list_library_item(item, upgrade_paths=upgrade_paths)
    compact = {
        key: full.get(key)
        for key in (
            'title', 'filename', 'path', 'library_root', 'resolution', 'rip_source',
            'size', 'size_human', 'added_time', 'modified_time', 'canonical_metadata',
            'metadata_status', 'metadata_source', 'metadata_accepted',
            'maintenance_upgrade_candidate',
        )
    }
    canonical = compact.get('canonical_metadata') or {}
    if not canonical.get('accepted'):
        compact.update({
            key: full.get(key)
            for key in (
                'plex_title', 'plex_year', 'plex_genres', 'plex_rating', 'plex_language',
                'plex_country_flag', 'plex_country', 'tmdb_id', 'imdb_id', 'plex_guid',
                'plex_poster', 'plex_matched',
            )
        })
    return compact


def _library_directory_revision():
    digest = hashlib.blake2b(digest_size=16)
    for movies_dir in get_movies_dirs():
        root = os.path.abspath(movies_dir)
        digest.update(_norm(root).encode('utf-8', errors='surrogatepass'))
        if not os.path.isdir(root):
            digest.update(b'\0missing')
            continue
        for current, dirs, files in os.walk(root):
            dirs.sort(key=str.lower)
            digest.update(_norm(current).encode('utf-8', errors='surrogatepass'))
            for file in sorted(files, key=str.lower):
                if os.path.splitext(file)[1].lower() in VIDEO_EXTENSIONS:
                    digest.update(b'\0')
                    digest.update(file.encode('utf-8', errors='surrogatepass'))
    return digest.hexdigest()


def _iter_movie_roots():
    for root in get_movies_dirs():
        if root and os.path.isdir(root):
            yield root


def _iter_video_files():
    for movies_dir in _iter_movie_roots():
        for root, _, files in os.walk(movies_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in VIDEO_EXTENSIONS:
                    yield movies_dir, root, file, os.path.join(root, file)


def _video_file_facts(movies_dir, filename, full_path, *, include_timestamps=False, probe_resolution=True):
    try:
        size = os.path.getsize(full_path)
        size_known = True
    except OSError:
        size = 0
        size_known = False

    parsed_title, parsed_year = parse_movie_title(filename)
    facts = {
        'path': full_path,
        'filename': filename,
        'library_root': movies_dir,
        'parsed_title': parsed_title,
        'parsed_year': parsed_year,
        'resolution': get_resolution_from_file(full_path) if probe_resolution else get_resolution(filename),
        'rip_source': get_rip_source(filename),
        'size': size,
        'size_known': size_known,
        'size_human': format_size(size),
    }
    if include_timestamps:
        try:
            facts['added_time'] = os.path.getctime(full_path)
        except OSError:
            facts['added_time'] = 0
        try:
            facts['modified_time'] = os.path.getmtime(full_path)
        except OSError:
            facts['modified_time'] = 0
    return facts


def _walk_movie_dirs():
    for movies_dir in _iter_movie_roots():
        for root, dirs, files in os.walk(movies_dir):
            yield movies_dir, root, dirs, files


def _path_library_root(path):
    abs_path = os.path.abspath(path)
    for root in _iter_movie_roots():
        abs_root = os.path.abspath(root)
        if abs_path == abs_root or abs_path.startswith(abs_root + os.sep):
            return abs_root
    return ''


def _classify_dimensions(width, height):
    """Classify actual video dimensions, allowing normal cinematic crop."""
    w = int(width or 0)
    h = int(height or 0)
    if w >= 3800 or h >= 2000:
        return '4K'
    if w >= 1900 or h >= 1000:
        return '1080p'
    if w >= 1200 or h >= 700:
        return '720p'
    if w >= 700 or h >= 450:
        return '480p'
    if h > 0:
        return f'{h}p'
    return None


def _probe_resolution(filepath):
    """Use pymediainfo to read actual video dimensions. Returns resolution string or None."""
    if not _MEDIAINFO_AVAILABLE:
        return None
    try:
        info = _MediaInfo.parse(filepath)
        for track in info.tracks:
            if track.track_type == 'Video':
                w = int(track.width or 0)
                h = int(track.height or 0)
                return _classify_dimensions(w, h)
        return None
    except Exception:
        return None


def get_resolution_from_file(filepath):
    """Return resolution string for a video file.
    Probes actual video stream dimensions first so cropped 1080p files are not
    mislabeled as 720p. Falls back to filename parsing when probing is not
    available.
    Falls back gracefully if pymediainfo is not installed."""
    filename = os.path.basename(filepath)
    filename_res = get_resolution(filename)
    # Probe with mediainfo before trusting filename-derived resolution.
    try:
        mtime = os.path.getmtime(filepath)
    except OSError:
        return filename_res
    key = (os.path.abspath(filepath), mtime)
    if key in _res_cache and key not in _res_cache_reprobe:
        return _res_cache[key]
    probed = _probe_resolution(filepath)
    result = probed if probed else filename_res
    _res_cache[key] = result
    _res_cache_reprobe.discard(key)
    return result


def get_resolution_rank_str(resolution):
    """Return numeric rank for an already-resolved resolution string."""
    order = {'4K': 4, '1080p': 3, '720p': 2, '480p': 1, 'Unknown': 0}
    return order.get(resolution, 0)


def _load_res_cache():
    """Load persisted resolution cache from disk into _res_cache."""
    global _res_cache, _res_cache_reprobe
    try:
        with open(_RES_CACHE_FILE, 'r', encoding='utf-8') as f:
            data = _json.load(f)
        if not isinstance(data, dict):
            return
        if data.get('_version') == _RES_CACHE_VERSION:
            entries = data.get('entries', {})
            legacy = False
        else:
            entries = data
            legacy = True
        for path, v in entries.items():
            if not isinstance(v, dict) or 'mtime' not in v or 'res' not in v:
                continue
            res = v['res']
            if legacy and res == '720p':
                filename_res = get_resolution(os.path.basename(path))
                path_has_1080_hint = bool(re.search(r'(^|[^\d])1080p?([^\d]|$)', path, re.IGNORECASE))
                if filename_res == 'Unknown' and path_has_1080_hint:
                    res = '1080p'
            key = (path, float(v['mtime']))
            _res_cache[key] = res
    except Exception:
        pass


def _save_res_cache():
    """Persist resolution cache to disk so probed results survive app restarts."""
    try:
        data = {'_version': _RES_CACHE_VERSION, 'entries': {}}
        for (path, mtime), res in _res_cache.items():
            data['entries'][path] = {'mtime': mtime, 'res': res}
        with open(_RES_CACHE_FILE, 'w', encoding='utf-8') as f:
            _json.dump(data, f, indent=2)
    except Exception:
        pass


_load_res_cache()  # populate cache from disk at startup

def parse_movie_title(filename):
    """Return a (title, year) key so remakes with the same name are not grouped together."""
    name = os.path.splitext(filename)[0]

    # Extract year — handles: .2003. / (2003) / [2003] / {2003} / _2003_ / -2003- / space
    year_match = re.search(
        r'[\.\s_\-\(\[\{]((19|20)\d{2})(?=(?:[\.\s_\-\)\]\}]|$|'
        r'bluray|blu-ray|bdrip|webrip|web-dl|dvdrip|hdtv|x264|x265|h264|h265))',
        name,
        flags=re.IGNORECASE,
    )
    year = year_match.group(1) if year_match else ''

    if year_match:
        name = name[:year_match.start()]
    else:
        name = re.sub(
            r'[\.\s_\-]*(1080p|720p|480p|2160p|4k|uhd|bluray|blu-ray|bdrip|bdremux|'
            r'hdrip|webrip|web-dl|dvdrip|hdtv|x264|x265|hevc|avc|aac|dts|ac3|h264|h265|'
            r'10bit|remux|extended|theatrical|remastered|directors\.cut).*',
            '', name, flags=re.IGNORECASE
        )

    name = re.sub(r'\balternate[\s._-]*ending\b', ' ', name, flags=re.IGNORECASE)
    name = re.sub(r'[\._\-]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip().lower()
    return (name, year)


def get_resolution(filename):
    name = filename.lower()
    if '2160p' in name or '4k' in name or 'uhd' in name:
        return '4K'
    elif '1080p' in name or re.search(r'[\.\-_ \[\(]1080[\.\-_ \]\)\[]', name):
        return '1080p'
    elif '720p' in name or re.search(r'[\.\-_ \[\(]720[\.\-_ \]\)\[]', name):
        return '720p'
    elif '480p' in name or re.search(r'[\.\-_ \[\(]480[\.\-_ \]\)\[]', name):
        return '480p'
    return 'Unknown'


def get_rip_rank(rip_source):
    order = {
        'BD Remux': 9, 'Remux': 8, 'Blu-ray': 7, 'BDRip': 6,
        'WEB-DL': 5, 'WEBRip': 4, 'HDRip': 3, 'HDTV': 2,
        'DVDRip': 1, 'DVDScr': 0, 'CAMRip': -1, 'HDCAM': -2, 'Unknown': -3,
    }
    return order.get(rip_source, -3)


def get_rip_source(filename):
    name = filename.lower()
    # Order matters — check more specific terms first
    if 'bdremux' in name or 'bd remux' in name:
        return 'BD Remux'
    elif 'bluray' in name or 'blu-ray' in name or 'bluray' in name:
        return 'Blu-ray'
    elif 'brrip' in name or 'br-rip' in name or 'bdrip' in name or 'bd-rip' in name:
        return 'BDRip'
    elif 'web-dl' in name or 'webdl' in name:
        return 'WEB-DL'
    elif 'webrip' in name or 'web-rip' in name:
        return 'WEBRip'
    elif 'hdrip' in name:
        return 'HDRip'
    elif 'hdtv' in name:
        return 'HDTV'
    elif 'dvdrip' in name or 'dvd-rip' in name:
        return 'DVDRip'
    elif 'dvdscr' in name or 'dvd-scr' in name:
        return 'DVDScr'
    elif 'hdcam' in name:
        return 'HDCAM'
    elif 'camrip' in name or 'cam-rip' in name or name.endswith('.cam'):
        return 'CAMRip'
    elif 'remux' in name:
        return 'Remux'
    return 'Unknown'


def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def _torrent_variants_from_prowlarr_results(results):
    variants = []
    for r in results or []:
        t = r.get('title', '')
        if _TV_RE.search(t):
            continue
        tl = t.lower()
        res = 'Unknown'
        if '2160p' in tl or '4k' in tl or 'uhd' in tl:
            res = '4K'
        elif '1080p' in tl or re.search(r'[.\-_ \[(]1080[.\-_ \])]', tl):
            res = '1080p'
        elif '720p' in tl or re.search(r'[.\-_ \[(]720[.\-_ \])]', tl):
            res = '720p'
        elif '480p' in tl or re.search(r'[.\-_ \[(]480[.\-_ \])]', tl):
            res = '480p'
        size = r.get('size', 0)
        seeders = r.get('seeders', 0)
        links = _prowlarr_result_links(r)
        entry = {
            'resolution': res,
            'seeders': seeders,
            'magnet_url': links['magnet_url'],
            'download_url': links['download_url'],
            'info_url': r.get('infoUrl', ''),
            'indexer': r.get('indexer', ''),
            'size_human': format_size(size) if size else '?',
            'size_bytes': size,
            'title': t,
        }
        variants.append(entry)
    return _sort_source_variants(variants)


def _sort_source_variants(variants):
    rows = list(variants or [])
    has_hd = any((row.get('resolution') in ('4K', '1080p')) for row in rows)
    if has_hd:
        rows.sort(key=lambda row: (
            0 if row.get('resolution') == '4K' else 1 if row.get('resolution') == '1080p' else 2,
            -int(row.get('seeders') or 0),
        ))
    else:
        rows.sort(key=lambda row: -int(row.get('seeders') or 0))
    return rows


def _source_variant_key(variant):
    return (
        str((variant or {}).get('title', '')).casefold(),
        str((variant or {}).get('indexer', '')).casefold(),
        str((variant or {}).get('magnet_url', '') or (variant or {}).get('download_url', '')).casefold(),
    )


def _prowlarr_result_key(result):
    result = result or {}
    identity = (
        result.get('infoHash')
        or result.get('magnetUrl')
        or result.get('downloadUrl')
        or result.get('infoUrl')
        or result.get('title')
        or ''
    )
    return (
        str(result.get('indexer', '') or '').casefold(),
        str(result.get('title', '') or '').casefold(),
        str(identity).casefold(),
    )


def _source_indexer_sort_key(indexer):
    name = str((indexer or {}).get('name', '') or '').lower()
    preferred = (
        ('yts', 0),
        ('yify', 0),
        ('limetorrents', 1),
        ('1337x', 2),
        ('zamunda', 3),
        ('bigfan', 4),
        ('torrent9', 5),
        ('world-torrent', 6),
        ('rutor', 7),
        ('pirate bay', 8),
    )
    for needle, rank in preferred:
        if needle in name:
            return (rank, name)
    return (50, name)


def _source_search_job_snapshot(job):
    return {
        'search_id': job.get('search_id', ''),
        'status': job.get('status', 'running'),
        'title': job.get('title', ''),
        'year': job.get('year', ''),
        'imdb_id': job.get('imdb_id', ''),
        'tmdb_id': job.get('tmdb_id', ''),
        'variants': list(job.get('variants', [])),
        'pending_indexers': list(job.get('pending_indexers', [])),
        'searching_indexers': list(job.get('searching_indexers', [])),
        'completed_indexers': list(job.get('completed_indexers', [])),
        'timed_out_indexers': list(job.get('timed_out_indexers', [])),
        'failed_indexers': list(job.get('failed_indexers', [])),
        'total_indexers': int(job.get('total_indexers', 0) or 0),
        'finished_indexers': int(job.get('finished_indexers', 0) or 0),
        'error': job.get('error', ''),
        'queries': list(job.get('queries', [])),
        'release_years': list(job.get('release_years', [])),
        'release_year_evidence': list(job.get('release_year_evidence', [])),
    }


def _source_search_job_response(search_id):
    with _source_search_jobs_lock:
        job = _source_search_jobs.get(search_id)
        if not job:
            return None
        return _source_search_job_snapshot(job)


def _update_source_search_job(search_id, updater):
    with _source_search_jobs_lock:
        job = _source_search_jobs.get(search_id)
        if not job:
            return None
        updater(job)
        job['updated_at'] = time.time()
        return _source_search_job_snapshot(job)


def _prune_source_search_jobs():
    cutoff = time.time() - SOURCE_SEARCH_JOB_TTL_SECONDS
    with _source_search_jobs_lock:
        stale = [
            search_id for search_id, job in _source_search_jobs.items()
            if float(job.get('updated_at', job.get('started_at', 0)) or 0) < cutoff
        ]
        for search_id in stale:
            _source_search_jobs.pop(search_id, None)


def _search_movie_on_single_indexer(
    indexer,
    movie,
    queries,
    timeout=SOURCE_SEARCH_INDEXER_TIMEOUT_SECONDS,
    deadline_seconds=SOURCE_SEARCH_DEADLINE_SECONDS,
):
    indexer_id = str((indexer or {}).get('id', '') or '')
    if not indexer_id:
        return {'indexer': indexer, 'results': [], 'timed_out': False, 'error': ''}
    deadline_at = time.monotonic() + max(1, int(deadline_seconds)) if deadline_seconds else None
    merged = []
    seen = set()
    timed_out = False
    errors = []
    alias_queries = {
        item['query']
        for item in _movie_release_query_plan(movie)
        if item['kind'] == 'alias'
    }
    for query in queries:
        if merged and query in alias_queries:
            break
        query_timeout = _remaining_timeout(deadline_at, timeout)
        if query_timeout <= 0:
            timed_out = True
            break
        try:
            rows = _prowlarr_search(
                indexer_ids=[indexer_id],
                query=query,
                limit=100,
                categories='2000',
                timeout=query_timeout,
            )
        except Exception as error:
            if _is_timeout_error(error):
                timed_out = True
                continue
            errors.append(str(error))
            continue
        for result in rows:
            if not _prowlarr_result_matches_movie(result, movie):
                continue
            key = _prowlarr_result_key(result)
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)
            if len(merged) >= SOURCE_SEARCH_RESULTS_PER_INDEXER:
                break
        if len(merged) >= SOURCE_SEARCH_RESULTS_PER_INDEXER:
            break
    return {
        'indexer': indexer,
        'results': merged,
        'timed_out': bool(timed_out and not merged),
        'error': '' if merged or not errors else errors[-1],
    }


def _run_source_search_job(search_id):
    snapshot = _source_search_job_response(search_id)
    if not snapshot:
        return
    movie = {
        'title': snapshot.get('title', ''),
        'year': snapshot.get('year', ''),
        'imdb_id': snapshot.get('imdb_id', ''),
        'tmdb_id': snapshot.get('tmdb_id', ''),
    }
    try:
        enriched = _movie_with_source_title_aliases(movie)
        queries = _movie_release_queries(enriched)
        indexers = sorted(_fetch_enabled_prowlarr_indexers(), key=_source_indexer_sort_key)
        indexer_names = [indexer.get('name') or f"Indexer {indexer.get('id')}" for indexer in indexers]

        def initialize(job):
            job['queries'] = queries
            job['release_years'] = list(enriched.get('release_years', []))
            job['release_year_evidence'] = list(enriched.get('release_year_evidence', []))
            job['pending_indexers'] = indexer_names
            job['total_indexers'] = len(indexers)

        _update_source_search_job(search_id, initialize)
        if not indexers:
            _update_source_search_job(search_id, lambda job: job.update({'status': 'complete'}))
            return

        max_workers = max(1, min(SOURCE_SEARCH_JOB_WORKERS, len(indexers)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    _search_movie_on_single_indexer,
                    indexer,
                    enriched,
                    queries,
                    SOURCE_SEARCH_INDEXER_TIMEOUT_SECONDS,
                ): indexer
                for indexer in indexers
            }
            for future in concurrent.futures.as_completed(futures):
                indexer = futures[future]
                indexer_name = indexer.get('name') or f"Indexer {indexer.get('id')}"

                def mark_searching(job, name=indexer_name):
                    if name in job.get('pending_indexers', []):
                        job['pending_indexers'].remove(name)
                    if name not in job.get('searching_indexers', []):
                        job['searching_indexers'].append(name)

                _update_source_search_job(search_id, mark_searching)
                try:
                    outcome = future.result()
                except Exception as error:
                    outcome = {'indexer': indexer, 'results': [], 'timed_out': False, 'error': str(error)}
                variants = _torrent_variants_from_prowlarr_results(outcome.get('results', []))

                def merge_results(job, name=indexer_name, new_variants=variants, result=outcome):
                    if name in job.get('searching_indexers', []):
                        job['searching_indexers'].remove(name)
                    if name in job.get('pending_indexers', []):
                        job['pending_indexers'].remove(name)
                    if result.get('timed_out'):
                        if name not in job.get('timed_out_indexers', []):
                            job['timed_out_indexers'].append(name)
                    elif result.get('error'):
                        job['failed_indexers'].append({'indexer': name, 'error': result.get('error', '')})
                    else:
                        if name not in job.get('completed_indexers', []):
                            job['completed_indexers'].append(name)
                    existing = {_source_variant_key(variant) for variant in job.get('variants', [])}
                    for variant in new_variants:
                        key = _source_variant_key(variant)
                        if key in existing:
                            continue
                        existing.add(key)
                        job['variants'].append(variant)
                    job['variants'] = _sort_source_variants(job.get('variants', []))
                    job['finished_indexers'] = (
                        len(job.get('completed_indexers', []))
                        + len(job.get('timed_out_indexers', []))
                        + len(job.get('failed_indexers', []))
                    )

                _update_source_search_job(search_id, merge_results)

        _update_source_search_job(search_id, lambda job: job.update({'status': 'complete', 'searching_indexers': [], 'pending_indexers': []}))
    except Exception as error:
        _update_source_search_job(search_id, lambda job: job.update({'status': 'error', 'error': str(error)}))


def _create_source_search_job(movie):
    _prune_source_search_jobs()
    search_id = str(uuid.uuid4())
    job = {
        'search_id': search_id,
        'status': 'running',
        'title': str((movie or {}).get('title', '') or ''),
        'year': str((movie or {}).get('year', '') or ''),
        'imdb_id': str((movie or {}).get('imdb_id', '') or ''),
        'tmdb_id': str((movie or {}).get('tmdb_id', '') or ''),
        'variants': [],
        'pending_indexers': [],
        'searching_indexers': [],
        'completed_indexers': [],
        'timed_out_indexers': [],
        'failed_indexers': [],
        'total_indexers': 0,
        'finished_indexers': 0,
        'queries': [],
        'release_years': [],
        'release_year_evidence': [],
        'error': '',
        'started_at': time.time(),
        'updated_at': time.time(),
    }
    with _source_search_jobs_lock:
        _source_search_jobs[search_id] = job
    worker = threading.Thread(target=_run_source_search_job, args=(search_id,), daemon=True)
    worker.start()
    return _source_search_job_response(search_id)


_GOOD_RELEASE_SOURCES = {'WEBRip', 'Blu-ray', 'BDRip'}
_BAD_RELEASE_RE = re.compile(
    r'(^|[.\-_\s\[\(])(cam|camrip|hdcam|ts|hdts|tele[.\-_\s]*sync|tc|telecine|scr|screener|dvdscr)',
    re.IGNORECASE
)


def _proper_release_from_title(title):
    if not title or _BAD_RELEASE_RE.search(title):
        return None
    source = get_rip_source(title)
    resolution = get_resolution(title)
    if source not in _GOOD_RELEASE_SOURCES or get_resolution_rank_str(resolution) < 3:
        return None
    return {'source': source, 'resolution': resolution}


def _catalog_owned_entries(candidates, store, metadata_snapshot):
    entries = []
    for candidate in candidates or []:
        path = candidate.get('path', '')
        if not path or not os.path.isfile(path):
            continue
        item = _catalog_library_item(candidate, store, metadata_snapshot)
        canonical = item.get('canonical_metadata') or {}
        if not canonical.get('accepted'):
            continue
        entries.append({
            'item': item,
            'keys': set(candidate.get('identity_keys') or []),
            'title': canonical.get('title') or item.get('plex_title') or '',
            'year': str(canonical.get('year') or item.get('plex_year') or ''),
            'tmdb_id': str(item.get('tmdb_id') or ''),
            'imdb_id': str(item.get('imdb_id') or ''),
            'plex_guid': str(item.get('plex_guid') or ''),
        })
    return entries


def _catalog_owned_movie(movie, *, store=None, metadata_snapshot=None, entries=None):
    """Resolve one owned movie through the catalog's stable identity keys."""
    movie = movie or {}
    if entries is None:
        if not any(True for _ in _iter_movie_roots()):
            return None
        store = store or _metadata_store()
        metadata_snapshot = metadata_snapshot or store.snapshot()
        candidates = _current_catalog_store(store).ownership_candidates(_ownership_keys(movie))
        entries = _catalog_owned_entries(candidates, store, metadata_snapshot)
    if not entries:
        return None

    def best_match(matches):
        return max(matches, key=lambda row: get_resolution_rank_str(row['item'].get('resolution'))) if matches else None

    for key in _ownership_keys(movie):
        if key.startswith(('tmdb:', 'imdb:', 'plex:')):
            match = best_match([entry for entry in entries if key in entry['keys']])
            if match:
                return match
    year = str(movie.get('year', '') or '').strip()
    title = _norm_movie_title(movie.get('title', ''))
    title_key = f"title:{title}|{year}" if title and year else ''
    exact = best_match([entry for entry in entries if title_key and title_key in entry['keys']])
    if not exact:
        return None
    for field in ('tmdb_id', 'imdb_id', 'plex_guid'):
        query_id = str(movie.get(field, '') or '').lower()
        match_id = str(exact.get(field, '') or '').lower()
        if query_id and match_id and query_id != match_id:
            return None
    return exact


def _find_owned_movie(movie):
    match = _catalog_owned_movie(movie)
    if not match:
        return None
    item = match['item']
    return {
        'found': True,
        'path': item['path'],
        'filename': item.get('filename', os.path.basename(item['path'])),
        'resolution': item.get('resolution', 'Unknown'),
        'size_human': item.get('size_human', ''),
    }


def NumberSafe(value):
    try:
        return int(value or 0)
    except Exception:
        return 0


def _find_best_followed_release(movie):
    if not _prowlarr_url or not _prowlarr_key:
        return None
    title = str(movie.get('title', '') or '').strip()
    year = str(movie.get('year', '') or '').strip()
    if not title:
        return None
    query = f"{title} {year}".strip()
    try:
        selected_indexers = []
        try:
            enabled_indexers = _fetch_enabled_prowlarr_indexers()
            trusted_ids = set(_effective_trusted_release_indexer_ids(enabled_indexers))
            selected_indexers = [ix for ix in enabled_indexers if ix['id'] in trusted_ids]
        except Exception:
            selected_indexers = []
        if not selected_indexers:
            return None
        indexer_ids = [ix['id'] for ix in selected_indexers]
        trusted_indexer_names = {ix.get('name', '') for ix in selected_indexers if ix.get('name')}
        results = _prowlarr_search_movie(
            indexer_ids,
            movie,
            timeout=FOLLOWED_RELEASE_QUERY_TIMEOUT_SECONDS,
            deadline_seconds=FOLLOWED_RELEASE_DEADLINE_SECONDS,
        )
    except Exception:
        return None

    candidates = []
    for r in results:
        torrent_title = r.get('title', '')
        result_indexer = r.get('indexer', '')
        if result_indexer and trusted_indexer_names and result_indexer not in trusted_indexer_names:
            continue
        if _TV_RE.search(torrent_title):
            continue
        quality = _proper_release_from_title(torrent_title)
        if not quality:
            continue
        size = NumberSafe(r.get('size'))
        links = _prowlarr_result_links(r)
        candidates.append({
            'title': torrent_title,
            'resolution': quality['resolution'],
            'source': quality['source'],
            'seeders': NumberSafe(r.get('seeders')),
            'size_bytes': size,
            'size_human': format_size(size) if size else '?',
            'indexer': result_indexer,
            'magnet_url': links['magnet_url'],
            'download_url': links['download_url'],
            'info_url': r.get('infoUrl', ''),
        })
    if not candidates:
        return None
    candidates.sort(key=lambda item: (
        get_resolution_rank_str(item.get('resolution')),
        get_rip_rank(item.get('source')),
        NumberSafe(item.get('seeders')),
        NumberSafe(item.get('size_bytes')),
    ), reverse=True)
    return candidates[0]


def _sort_followed_releases(items):
    status_rank = {'available': 0, 'watching': 1, 'owned': 2}
    return sorted(items, key=lambda item: (
        status_rank.get(item.get('status'), 3),
        -float(item.get('updated_at') or item.get('followed_at') or 0),
    ))


def _backfill_followed_release_dates(store, movies):
    enriched = []
    changed = False
    for item in movies or []:
        updated = dict(item or {})
        if not updated.get('release_date') and updated.get('tmdb_id'):
            metadata = _fetch_tmdb_metadata_by_id(updated.get('tmdb_id'))
            release_date = str(metadata.get('release_date', '') or '')
            if release_date:
                updated['release_date'] = release_date
                changed = True
        enriched.append(updated)
    if changed:
        store.save_followed_all(enriched)
    return enriched


def _check_followed_releases():
    store = _curation_store()
    current = _backfill_followed_release_dates(store, store.followed_all())
    checked = []
    removed_owned = []
    newly_available = []
    now = time.time()
    for item in current:
        before_status = item.get('status', 'watching')
        owned = _find_owned_movie(item)
        if owned:
            removed_owned.append({**item, 'status': 'owned', 'owned': owned, 'updated_at': now, 'last_checked': now})
            continue
        best_release = _find_best_followed_release(item)
        updated = {**item, 'last_checked': now}
        if best_release:
            updated['status'] = 'available'
            updated['best_release'] = best_release
            updated['updated_at'] = now if before_status != 'available' else item.get('updated_at', now)
            if before_status != 'available':
                newly_available.append(updated)
        else:
            updated['status'] = 'watching'
            updated['best_release'] = {}
        checked.append(updated)
    checked = _sort_followed_releases(checked)
    store.save_followed_all(checked)
    return {
        'movies': checked,
        'removed_owned': removed_owned,
        'newly_available': newly_available,
        'checked_at': now,
    }


def _auto_sync_plex(force=False):
    """Refresh _plex_cache if Plex is configured and cache is stale (>5 min). Silent on errors.
    Pass force=True to bypass the TTL and always fetch fresh data."""
    global _plex_cache, _plex_unmatched, _plex_matched_by_fname, _plex_unmatched_by_fname, \
           _plex_section_ids, _plex_cache_time, _library_cache
    if not _plex_url or not _plex_token:
        return
    if not force and time.time() - _plex_cache_time < _PLEX_TTL:
        return  # cache is still fresh
    try:
        _plex_cache, _plex_unmatched, _plex_matched_by_fname, _plex_unmatched_by_fname, \
            _plex_section_ids = _fetch_plex_library()
        _plex_cache_time = time.time()
        store = _metadata_store()
        snapshot = store.snapshot()
        changed = {}
        for path_key, plex_record in _plex_cache.items():
            file_record = (snapshot.get('files') or {}).get(path_key) or {}
            path = str(file_record.get('path') or '')
            if not path:
                continue
            current = (snapshot.get('plex_files') or {}).get(path_key) or {}
            candidate = {**plex_record, 'path': path}
            comparable_current = {
                key: value for key, value in current.items()
                if key != 'updated_at'
            }
            if comparable_current != candidate:
                changed[path_key] = {**candidate, 'updated_at': time.time()}
        if changed:
            store.catalog.upsert_records('app_metadata/plex_metadata.json', changed)
        _library_cache = {}  # Plex data refreshed — bust library cache so titles update
    except Exception:
        pass  # don't break scan if Plex is unreachable


def _plex_person_list(item, field_name):
    people = []
    for person in item.get(field_name, []) or []:
        name = person.get('tag') or person.get('title') or person.get('name') or ''
        if not name:
            continue
        people.append({
            'id': str(person.get('id', '') or ''),
            'name': name,
            'character': person.get('role', '') if field_name == 'Role' else '',
            'profile_url': (
                f"{_plex_url}{person.get('thumb')}?X-Plex-Token={_plex_token}"
                if _plex_url and _plex_token and person.get('thumb') else ''
            ),
        })
    return people


def _extract_tmdb_id_from_plex_item(item):
    ids = [item.get('guid', '')]
    ids.extend(g.get('id', '') for g in item.get('Guid', []) or [])
    for value in ids:
        match = re.search(r'tmdb://(\d+)', str(value))
        if match:
            return match.group(1)
    return ''


def _extract_imdb_id_from_plex_item(item):
    ids = [item.get('guid', '')]
    ids.extend(g.get('id', '') for g in item.get('Guid', []) or [])
    for value in ids:
        match = re.search(r'imdb://(tt\d+)', str(value), re.IGNORECASE)
        if match:
            return match.group(1).lower()
    return ''


def _fetch_plex_library():
    """Fetch all movie file paths + metadata from Plex.
    Returns (matched_cache, unmatched_cache, matched_by_fname, unmatched_by_fname, section_ids).
    matched_cache:    normpath -> {plex_title, plex_year, plex_genres}
    unmatched_cache:  normpath -> {rating_key, plex_title}  (Plex has file but no match)
    matched_by_fname:   filename.lower() -> matched entry   (fallback for path-mismatch cases)
    unmatched_by_fname: filename.lower() -> unmatched entry (fallback for path-mismatch cases)
    section_ids: list of movie library section keys
    """
    if not _plex_url or not _plex_token:
        return {}, {}, {}, {}, []

    def plex_get(path):
        sep = '&' if '?' in path else '?'
        url = f"{_plex_url}{path}{sep}X-Plex-Token={_plex_token}"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return _json.loads(resp.read().decode())

    data = plex_get('/library/sections')
    sections = data.get('MediaContainer', {}).get('Directory', [])
    movie_sections = [s['key'] for s in sections if s.get('type') == 'movie']

    matched = {}
    unmatched = {}
    matched_by_fname = {}
    unmatched_by_fname = {}
    for section_key in movie_sections:
        data = plex_get(f'/library/sections/{section_key}/all')
        for item in data.get('MediaContainer', {}).get('Metadata', []):
            guid        = item.get('guid', '')
            rating_key  = item.get('ratingKey', '')
            title       = item.get('title', '')
            year        = str(item.get('year', '')) if item.get('year') else ''
            genres      = [g['tag'] for g in item.get('Genre', [])]
            summary     = item.get('summary', '')
            rating      = str(item.get('rating', '') or item.get('audienceRating', '') or '')
            thumb       = item.get('thumb', '')
            tmdb_id     = _extract_tmdb_id_from_plex_item(item)
            imdb_id     = _extract_imdb_id_from_plex_item(item)
            directors   = _plex_person_list(item, 'Director')
            cast        = _plex_person_list(item, 'Role')[:7]
            is_local    = (not guid) or guid.startswith('local://')
            for media in item.get('Media', []):
                for part in media.get('Part', []):
                    fp = part.get('file', '')
                    if fp:
                        norm  = _norm(fp)
                        fname = os.path.basename(fp).lower()
                        if is_local:
                            entry = {'rating_key': rating_key, 'plex_title': title}
                            unmatched[norm] = entry
                            # filename fallback — only store first hit to avoid collisions
                            unmatched_by_fname.setdefault(fname, entry)
                        else:
                            lang = item.get('originalLanguage', '')
                            countries_raw = [c['tag'] for c in item.get('Country', [])]
                            lang_name    = _LANG_NAMES.get(lang, lang.upper() if lang else '')
                            cc           = _LANG_COUNTRY.get(lang, '')
                            flag         = _country_flag(cc) if cc else ''
                            entry = {'rating_key': rating_key,
                                     'plex_title': title, 'plex_year': year, 'plex_genres': genres,
                                     'plex_summary': summary, 'plex_rating': rating, 'plex_thumb': thumb,
                                     'plex_language': lang_name,
                                     'plex_country_flag': flag,
                                     'plex_country': countries_raw[0] if countries_raw else '',
                                     'plex_directors': directors,
                                     'plex_cast': cast,
                                     'tmdb_id': tmdb_id,
                                     'imdb_id': imdb_id,
                                     'plex_guid': guid}
                            matched[norm] = entry
                            matched_by_fname.setdefault(fname, entry)
    return matched, unmatched, matched_by_fname, unmatched_by_fname, movie_sections


def _qbittorrent_proxy_response(path='', prepare_embedded_html=False):
    try:
        status, headers, payload = _get_qbittorrent_manager().proxy(
            path,
            method=request.method,
            headers=dict(request.headers.items()),
            body=request.get_data() or None,
        )
    except QBittorrentError as error:
        response = make_response(str(error), 503)
        response.mimetype = 'text/plain'
        return response
    if prepare_embedded_html and 'text/html' in headers.get('Content-Type', '').lower():
        payload = build_downloads_html(payload.decode('utf-8', errors='replace')).encode('utf-8')
    response = make_response(payload, status)
    for key, value in headers.items():
        if key.lower() in HOP_BY_HOP_HEADERS or key.lower() == 'content-length':
            continue
        response.headers[key] = value
    response.headers['Content-Length'] = str(len(payload))
    return response


@app.route('/qbittorrent/')
def qbittorrent_webui():
    manager = _get_qbittorrent_manager()
    if _qbt_mode != 'embedded':
        return make_response(
            '<!doctype html><title>Downloads</title><p>Embedded qBittorrent is disabled. '
            '<a href="/settings">Open Cinema Paradiso Settings</a>.</p>',
            409,
        )
    try:
        if not manager.ensure_running():
            return make_response(
                '<!doctype html><title>Downloads</title><p>Embedded qBittorrent is not installed. '
                '<a href="/settings">Open Cinema Paradiso Settings</a> to install it.</p>',
                503,
            )
    except QBittorrentError as error:
        return make_response(f'<!doctype html><title>Downloads</title><p>{error}</p>', 503)
    return _qbittorrent_proxy_response('', prepare_embedded_html=True)


@app.route('/qbittorrent/<path:filename>', methods=['GET', 'POST'])
def qbittorrent_webui_asset(filename):
    return _qbittorrent_proxy_response(filename)


@app.route('/api/v2/<path:filename>', methods=['GET', 'POST'])
@app.route('/scripts/<path:filename>')
@app.route('/css/<path:filename>')
@app.route('/images/<path:filename>')
@app.route('/icons/<path:filename>')
@app.route('/lang/<path:filename>')
@app.route('/views/<path:filename>')
def qbittorrent_proxy_asset(filename):
    prefix = request.path.split('/', 2)[1]
    if request.path.startswith('/api/v2/'):
        return _qbittorrent_proxy_response(f'api/v2/{filename}')
    return _qbittorrent_proxy_response(f'{prefix}/{filename}')


@app.route('/api/plex/config', methods=['GET'])
def get_plex_config():
    return jsonify({'url': _plex_url, 'token': _plex_token})


@app.route('/api/plex/config', methods=['POST'])
def set_plex_config():
    global _plex_url, _plex_token
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    _plex_url   = data.get('url', 'http://localhost:32400').rstrip('/')
    _plex_token = data.get('token', '')
    _save_config(_all_config())
    return jsonify({'success': True})


@app.route('/api/plex/test')
def plex_test():
    if not _plex_url or not _plex_token:
        return jsonify({'error': 'URL or token missing — configure Plex first.'}), 400
    try:
        sep = '&' if '?' in '/library/sections' else '?'
        url = f"{_plex_url}/library/sections{sep}X-Plex-Token={_plex_token}"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        sections = data.get('MediaContainer', {}).get('Directory', [])
        movie_libs = [s for s in sections if s.get('type') == 'movie']
        return jsonify({'success': True, 'movie_libraries': len(movie_libs), 'total_libraries': len(sections)})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid token — Plex → Settings → General → Advanced → X-Plex-Token.'}), 401
        return jsonify({'error': f'Plex returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': f'Cannot reach Plex: {e}'}), 502


@app.route('/api/plex/image')
def plex_image():
    url = request.args.get('url', '').strip()
    plex_path = request.args.get('path', '').strip()
    if plex_path:
        if not plex_path.startswith('/') or '://' in plex_path:
            return '', 403
        url = f"{_plex_url}{plex_path}"
    if not url:
        return '', 400
    # Security: only proxy to the configured Plex server — reject any other origin
    if not _plex_url or not url.startswith(_plex_url):
        return '', 403
    try:
        req = urllib.request.Request(url, headers={'X-Plex-Token': _plex_token})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            ct   = resp.headers.get('Content-Type', 'image/jpeg')
        response = make_response(data)
        response.headers['Content-Type']  = ct
        response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception:
        return '', 502


@app.route('/api/plex/sync')
def plex_sync():
    global _plex_cache, _plex_unmatched, _plex_matched_by_fname, _plex_unmatched_by_fname, \
           _plex_section_ids, _plex_cache_time, _library_cache
    if not _plex_url or not _plex_token:
        return jsonify({'error': 'Plex not configured.'}), 400
    try:
        _plex_cache, _plex_unmatched, _plex_matched_by_fname, _plex_unmatched_by_fname, \
            _plex_section_ids = _fetch_plex_library()
        _plex_cache_time = time.time()
        _library_cache = {}  # bust library cache so new language/country fields appear
        return jsonify({'success': True, 'cached': len(_plex_cache)})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid Plex token.'}), 401
        return jsonify({'error': f'Plex returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify({
        'directory': get_movies_dir(),
        'directories': get_movies_dirs(),
        'show_adult_movies': _library_show_adult,
    })


@app.route('/api/config', methods=['POST'])
def set_config():
    global _movies_dir, _movies_dirs, _library_cache, _library_show_adult
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No directory provided'}), 400
    if isinstance(data.get('directories'), list):
        requested_dirs = [str(path or '').strip() for path in data.get('directories', []) if str(path or '').strip()]
    elif 'directory' in data:
        requested_dirs = [str(data.get('directory') or '').strip()]
    else:
        requested_dirs = []
    if not requested_dirs:
        return jsonify({'error': 'At least one movie directory is required'}), 400
    normalized_dirs = []
    seen = set()
    for path in requested_dirs:
        if not os.path.isdir(path):
            return jsonify({'error': f'Directory not found: {path}'}), 400
        norm = _norm(path)
        if norm in seen:
            continue
        abs_path = os.path.abspath(path)
        for existing in normalized_dirs:
            abs_existing = os.path.abspath(existing)
            try:
                common = os.path.commonpath([abs_path, abs_existing])
            except ValueError:
                common = ''
            if common == abs_existing or common == abs_path:
                return jsonify({'error': f'Library folders cannot be nested: {path}'}), 400
        seen.add(norm)
        normalized_dirs.append(path)
    _movies_dirs = normalized_dirs
    _movies_dir = _movies_dirs[0]
    if 'show_adult_movies' in data:
        _library_show_adult = _coerce_bool(data.get('show_adult_movies'), True)
    _library_cache = {}  # directory changed — bust library cache
    _save_config(_all_config())
    return jsonify({
        'success': True,
        'directory': _movies_dir,
        'directories': get_movies_dirs(),
        'show_adult_movies': _library_show_adult,
    })


@app.route('/api/system/folders')
def system_folders():
    try:
        return jsonify(_browse_system_folder(request.args.get('path', '')))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/app-data/config', methods=['GET', 'POST'])
def app_data_config():
    global _user_data_dir, _tmdb_cache_dir, _TMDB_CACHE_DIR, _TMDB_LIBRARY_CACHE_FILE, \
           _TMDB_COLLECTION_CACHE_FILE, _tmdb_library_cache, _tmdb_collection_cache, _iptv_service
    if request.method == 'GET':
        return jsonify({'user_data_dir': _user_data_dir, 'tmdb_cache_dir': _tmdb_cache_dir})
    data = request.get_json(force=True, silent=True) or {}
    user_dir = str(data.get('user_data_dir', _user_data_dir) or '').strip()
    cache_dir = str(data.get('tmdb_cache_dir', _tmdb_cache_dir) or '').strip()
    if not user_dir or not cache_dir:
        return jsonify({'error': 'User data and TMDB cache folders are required'}), 400
    try:
        os.makedirs(user_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)
        next_iptv_service = IPTVService(user_dir)
    except Exception as e:
        return jsonify({'error': f'Cannot create folder: {e}'}), 400
    previous_iptv_service = _iptv_service
    _user_data_dir = user_dir
    _tmdb_cache_dir = cache_dir
    _TMDB_CACHE_DIR = _tmdb_cache_dir
    _TMDB_LIBRARY_CACHE_FILE = os.path.join(_TMDB_CACHE_DIR, 'tmdb_library_cache.json')
    _TMDB_COLLECTION_CACHE_FILE = os.path.join(_TMDB_CACHE_DIR, 'tmdb_collection_cache.json')
    _tmdb_library_cache = _load_tmdb_library_cache()
    _tmdb_collection_cache = _load_tmdb_collection_cache()
    _iptv_service = next_iptv_service
    previous_iptv_service.close()
    _save_config(_all_config())
    return jsonify({'success': True, 'user_data_dir': _user_data_dir, 'tmdb_cache_dir': _tmdb_cache_dir})


@app.route('/api/prowlarr/config', methods=['GET'])
def get_prowlarr_config():
    indexers = []
    if _prowlarr_url and _prowlarr_key:
        try:
            indexers = sorted(_fetch_enabled_prowlarr_indexers(), key=lambda ix: ix['name'].lower())
        except Exception:
            indexers = []
    return jsonify({
        'url': _prowlarr_url,
        'key': _prowlarr_key,
        'indexers': indexers,
        'trusted_release_indexers': _effective_trusted_release_indexer_ids(indexers),
        'trusted_release_indexers_configured': _trusted_release_indexers_configured,
        'download_default_quality': _download_default_quality,
        'download_indexer_mode': _download_indexer_mode,
        'download_trusted_indexers': _download_trusted_indexers,
    })


@app.route('/api/prowlarr/config', methods=['POST'])
def set_prowlarr_config():
    global _prowlarr_url, _prowlarr_key, _trusted_release_indexers, _trusted_release_indexers_configured
    global _download_default_quality, _download_indexer_mode, _download_trusted_indexers
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    _prowlarr_url = data.get('url', '').rstrip('/')
    _prowlarr_key = data.get('key', '')
    _trusted_release_indexers = [
        str(value).strip()
        for value in data.get('trusted_release_indexers', [])
        if str(value).strip()
    ]
    _trusted_release_indexers_configured = True
    quality = str(data.get('download_default_quality', _download_default_quality) or '1080p').strip()
    _download_default_quality = '4K' if quality.lower() in {'4k', '2160p'} else '1080p'
    mode = str(data.get('download_indexer_mode', _download_indexer_mode) or 'release').strip().lower()
    _download_indexer_mode = mode if mode in {'release', 'all', 'custom'} else 'release'
    _download_trusted_indexers = [
        str(value).strip()
        for value in data.get('download_trusted_indexers', _download_trusted_indexers)
        if str(value).strip()
    ]
    _save_config(_all_config())
    return jsonify({'success': True})


def _ai_control_available_indexers():
    if not _prowlarr_url or not _prowlarr_key:
        return []
    try:
        return sorted(_fetch_enabled_prowlarr_indexers(), key=lambda ix: ix['name'].lower())
    except Exception:
        return []


def _is_ai_control_default_indexer(indexer):
    return bool(re.search(r'yts|yify', str(indexer.get('name') or ''), flags=re.I))


def _effective_ai_control_config(indexers=None):
    config = dict(_ai_control_config)
    available_indexers = _ai_control_available_indexers() if indexers is None else indexers
    if not _ai_control_trusted_indexers_configured:
        config['trusted_indexers'] = [
            str(indexer.get('id'))
            for indexer in available_indexers
            if indexer.get('id') is not None and _is_ai_control_default_indexer(indexer)
        ]
    return ai_control.coerce_config(config)


def _ai_control_config_payload():
    indexers = _ai_control_available_indexers()
    effective_config = _effective_ai_control_config(indexers)
    return {
        **effective_config,
        'download_quality': '1080p',
        'delete_mode': 'recycle_bin',
        'trusted_indexers_configured': _ai_control_trusted_indexers_configured,
        'indexers': indexers,
        'capabilities': ai_control.load_capabilities(),
    }


@app.route('/api/ai-control/config', methods=['GET', 'POST'])
def ai_control_config():
    global _ai_control_config, _ai_control_trusted_indexers_configured
    if request.method == 'GET':
        return jsonify(_ai_control_config_payload())
    data = request.get_json(silent=True) or {}
    if 'trusted_indexers' in data:
        _ai_control_trusted_indexers_configured = True
    _ai_control_config = ai_control.coerce_config({
        **_ai_control_config,
        'enabled': data.get('enabled', _ai_control_config['enabled']),
        'trusted_indexers': data.get('trusted_indexers', _ai_control_config['trusted_indexers']),
        'max_matched_movies': data.get('max_matched_movies', _ai_control_config['max_matched_movies']),
        'max_download_searches': data.get('max_download_searches', _ai_control_config['max_download_searches']),
        'ollama_curated_lists': data.get('ollama_curated_lists', _ai_control_config['ollama_curated_lists']),
    })
    _save_config(_all_config())
    return jsonify(_ai_control_config_payload())


def _ai_control_library_items():
    cached_items = _fresh_library_cache_items()
    if cached_items is not None:
        return list(cached_items)
    items = []
    for _, _, filename, path in _iter_video_files():
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        title, year = parse_movie_title(filename)
        plex_data = _plex_cache.get(_norm(path), {})
        genres = plex_data.get('plex_genres', [])
        directors = plex_data.get('plex_directors', [])
        cast = plex_data.get('plex_cast', [])
        resolution = get_resolution(filename)
        items.append({
            'path': path,
            'filename': filename,
            'title': plex_data.get('plex_title') or title or os.path.splitext(filename)[0],
            'year': str(plex_data.get('plex_year') or year or ''),
            'size': size,
            'size_human': format_size(size) if size else '',
            'resolution': resolution,
            'poster_url': plex_data.get('plex_poster', ''),
            'genres': genres,
            'plex_genres': genres,
            'plot': plex_data.get('plex_summary', ''),
            'summary': plex_data.get('plex_summary', ''),
            'tmdb_rating': plex_data.get('plex_rating', ''),
            'language': plex_data.get('plex_language', ''),
            'country': plex_data.get('plex_country', ''),
            'country_flag': plex_data.get('plex_country_flag', ''),
            'directors': directors,
            'director': directors[0] if directors else {},
            'plex_directors': directors,
            'cast': cast,
            'plex_cast': cast,
            'tmdb_id': str(plex_data.get('tmdb_id', '') or ''),
            'imdb_id': str(plex_data.get('imdb_id', '') or ''),
            'plex_guid': str(plex_data.get('plex_guid', '') or ''),
            'source': 'Library',
        })
    return items


def _ai_control_tmdb_movie_payload(raw):
    release = raw.get('release_date', '') or ''
    year = release[:4] if release else str(raw.get('year', '') or '')
    poster_path = raw.get('poster_path', '')
    genre_ids = raw.get('genre_ids', []) or []
    genres = [_tmdb_genres[gid] for gid in genre_ids if gid in _tmdb_genres][:3]
    vote = raw.get('vote_average', 0)
    lang = raw.get('original_language', '')
    countries = raw.get('origin_country', []) or []
    country_code = countries[0] if countries else _LANG_COUNTRY.get(lang, '')
    return {
        'tmdb_id': str(raw.get('id') or raw.get('tmdb_id') or ''),
        'title': raw.get('title') or raw.get('name') or '',
        'year': year,
        'poster_url': raw.get('poster_url') or (f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else ''),
        'genres': raw.get('genres') or genres,
        'tmdb_rating': raw.get('tmdb_rating') or (f"{vote:.1f}" if isinstance(vote, (int, float)) and vote else ''),
        'tmdb_vote_count': int(raw.get('vote_count', raw.get('tmdb_vote_count', 0)) or 0),
        'plot': raw.get('overview') or raw.get('plot') or '',
        'language': _LANG_NAMES.get(lang, lang.upper() if lang else ''),
        'country': country_code,
        'country_flag': _country_flag(country_code),
        'release_date': release,
        'source': 'TMDB',
    }


_AI_CONTROL_SKIP_CREDIT_TITLE_RE = re.compile(
    r'\b('
    r'behind the scenes|making of|tribute|hall of fame|anniversary special|'
    r'many faces|interview|close up|lifetime of|induction ceremony'
    r')\b',
    re.I,
)


def _ai_control_credit_genre_names(row):
    names = []
    for genre_id in row.get('genre_ids', []) or []:
        name = _tmdb_genres.get(genre_id) or _tmdb_genres.get(str(genre_id))
        if name:
            names.append(str(name))
    for genre in row.get('genres', []) or []:
        if isinstance(genre, dict):
            names.append(str(genre.get('name') or ''))
        else:
            names.append(str(genre))
    return [name for name in names if name]


def _ai_control_filter_person_credit_rows(rows, role='actor'):
    today = time.strftime('%Y-%m-%d')
    filtered = []
    seen = set()
    for row in rows or []:
        tmdb_id = str(row.get('id') or row.get('tmdb_id') or '').strip()
        title = str(row.get('title') or row.get('name') or '').strip()
        if not tmdb_id or not title or tmdb_id in seen:
            continue
        release_date = str(row.get('release_date') or '').strip()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', release_date) and release_date > today:
            continue
        genre_names = {name.lower() for name in _ai_control_credit_genre_names(row)}
        if 'documentary' in genre_names:
            continue
        if _AI_CONTROL_SKIP_CREDIT_TITLE_RE.search(title):
            continue
        credit = str(row.get('character') if role != 'director' else row.get('job') or '').strip().lower()
        if role != 'director' and (credit == 'self' or credit.startswith('self ') or 'archive footage' in credit):
            continue
        filtered.append(row)
        seen.add(tmdb_id)
    filtered.sort(key=lambda row: (
        float(row.get('popularity') or 0),
        float(row.get('vote_average') or 0),
        int(row.get('vote_count') or 0),
        str(row.get('release_date') or ''),
    ), reverse=True)
    return filtered


def _ai_control_tmdb_discover(intent, config):
    if not _tmdb_key:
        return []
    _ensure_tmdb_genres()
    filters = intent.get('filters') or []
    year_filter = next((item for item in filters if item.get('field') == 'year'), {})
    genre_filter = next((item for item in filters if item.get('field') == 'genre'), {})
    genre_name = _ai_control_normalized_genre_name(genre_filter.get('value'))
    genre_id = next((str(key) for key, value in _tmdb_genres.items() if _ai_control_normalized_genre_name(value) == genre_name), '')
    list_name = str(intent.get('list') or intent.get('source') or 'popular')
    if list_name not in {'trending_week', 'trending_today', 'now_playing', 'popular', 'upcoming', 'top_rated', 'best_all_time'}:
        list_name = 'popular'
    sort_text = str(intent.get('sort') or intent.get('rating') or intent.get('name') or '').lower()
    sort_by = 'vote_average.desc' if any(token in sort_text for token in ('top_rated', 'top rated', 'high rated', 'high')) else 'popularity.desc'
    params = {
        'api_key': _tmdb_key,
        'language': 'en-US',
        'page': '1',
    }
    if genre_id or year_filter:
        params['sort_by'] = sort_by
        url = f"https://api.themoviedb.org/3/discover/movie?{urllib.parse.urlencode(params)}"
        if genre_id:
            url += '&with_genres=' + urllib.parse.quote(genre_id)
        year_start, year_end = _ai_control_year_filter_range(year_filter)
        if year_start and year_end:
            url += '&primary_release_date.gte=' + urllib.parse.quote(f'{year_start}-01-01')
            url += '&primary_release_date.lte=' + urllib.parse.quote(f'{year_end}-12-31')
        if sort_by == 'vote_average.desc':
            url += '&vote_count.gte=500'
    elif list_name == 'trending_today':
        url = f"https://api.themoviedb.org/3/trending/movie/day?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US&page=1"
    elif list_name == 'trending_week':
        url = f"https://api.themoviedb.org/3/trending/movie/week?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US&page=1"
    else:
        endpoint_map = {
            'popular': 'popular',
            'top_rated': 'top_rated',
            'now_playing': 'now_playing',
            'upcoming': 'upcoming',
            'best_all_time': 'top_rated',
        }
        endpoint = endpoint_map.get(list_name, 'popular')
        url = f"https://api.themoviedb.org/3/movie/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = _json.loads(response.read().decode())
    return [_ai_control_tmdb_movie_payload(row) for row in data.get('results', [])]


def _ai_control_normalized_genre_name(value):
    clean = re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower()).strip()
    if clean in {'sci fi', 'scifi', 'science fiction'}:
        return 'science fiction'
    return clean


def _ai_control_year_filter_range(year_filter):
    if not year_filter:
        return '', ''
    value = year_filter.get('value')
    if str(year_filter.get('op') or '') == 'between' and isinstance(value, (list, tuple)) and len(value) >= 2:
        start = re.search(r'(?:19|20)\d{2}', str(value[0] or ''))
        end = re.search(r'(?:19|20)\d{2}', str(value[1] or ''))
        if start and end:
            start_year, end_year = start.group(0), end.group(0)
            return (start_year, end_year) if start_year <= end_year else (end_year, start_year)
    year_value = str(value or '')
    if re.fullmatch(r'(?:19|20)\d{2}', year_value):
        return year_value, year_value
    year_range = re.findall(r'(?:19|20)\d{2}', year_value)
    if len(year_range) >= 2:
        start_year, end_year = year_range[0], year_range[1]
        return (start_year, end_year) if start_year <= end_year else (end_year, start_year)
    return '', ''


def _ai_control_tmdb_search(query, config):
    if not _tmdb_key:
        return []
    _ensure_tmdb_genres()
    params = urllib.parse.urlencode({
        'query': query,
        'api_key': _tmdb_key,
        'language': 'en-US',
        'page': '1',
        'include_adult': _tmdb_include_adult_value(False),
    })
    req = urllib.request.Request(f"https://api.themoviedb.org/3/search/movie?{params}", headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = _json.loads(response.read().decode())
    return [_ai_control_tmdb_movie_payload(row) for row in data.get('results', [])]


def _ai_control_person_movies(name, role, config):
    if not _tmdb_key:
        return []
    _ensure_tmdb_genres()
    params = urllib.parse.urlencode({
        'query': name,
        'api_key': _tmdb_key,
        'language': 'en-US',
        'page': '1',
        'include_adult': _tmdb_include_adult_value(False),
    })
    req = urllib.request.Request(f"https://api.themoviedb.org/3/search/person?{params}", headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        data = _json.loads(response.read().decode())
    person = next((row for row in data.get('results', []) if str(row.get('known_for_department', '')).lower() in {'acting', 'directing'}), None)
    person = person or next(iter(data.get('results', [])), None)
    if not person:
        return []
    person_id = str(person.get('id') or '')
    safe_id = urllib.parse.quote(person_id)
    url = f"https://api.themoviedb.org/3/person/{safe_id}/movie_credits?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US"
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        credits = _json.loads(response.read().decode())
    rows = credits.get('crew', []) if role == 'director' else credits.get('cast', [])
    if role == 'director':
        rows = [row for row in rows if row.get('job') == 'Director']
    rows = _ai_control_filter_person_credit_rows(rows, role)
    movies = [_ai_control_tmdb_movie_payload(row) for row in rows if row.get('title')]
    return movies


def _ai_control_source_search(movie, config):
    if not _prowlarr_url or not _prowlarr_key:
        return []
    enabled_indexers = _fetch_enabled_prowlarr_indexers()
    trusted_ids = {str(value) for value in config.get('trusted_indexers') or []}
    selected = [ix for ix in enabled_indexers if ix['id'] in trusted_ids]
    if not selected:
        return []
    indexer_ids = [ix['id'] for ix in selected]
    indexer_name_to_id = {ix['name']: ix['id'] for ix in selected}
    results = _prowlarr_search_movie(
        indexer_ids,
        movie,
        limit=50,
        timeout=SOURCE_SEARCH_QUERY_TIMEOUT_SECONDS,
        deadline_seconds=SOURCE_SEARCH_DEADLINE_SECONDS,
    )
    variants = _torrent_variants_from_prowlarr_results(results)
    rows = []
    for variant in variants:
        indexer_name = variant.get('indexer', '')
        if indexer_name_to_id and indexer_name not in indexer_name_to_id:
            continue
        rows.append({**variant, 'indexer_id': indexer_name_to_id.get(indexer_name, indexer_name)})
    return rows


def _ai_control_create_list(list_name, movies):
    store = _curation_store()
    created = store.create_list(list_name, movies=movies)
    return {**created, 'count': len(created.get('movies') or [])}


def _ai_control_delete_file(path):
    return _delete_library_file(path, use_trash=True)


def _ai_control_submit_download(item):
    variant = item.get('variant') or {}
    metadata = _qbittorrent_submission_metadata({
        'title': item.get('title', ''),
        'year': item.get('year', ''),
        'tmdb_id': item.get('tmdb_id', ''),
        'imdb_id': item.get('imdb_id', ''),
        'source_title': variant.get('title', ''),
        'indexer': variant.get('indexer', ''),
    })
    magnet = str(variant.get('magnet_url', '') or '').strip()
    download_url = str(variant.get('download_url', '') or '').strip()
    manager = _get_qbittorrent_manager()
    if magnet:
        return manager.submit_magnet(magnet, metadata)
    if not download_url:
        raise ValueError('No usable magnet or torrent URL was provided')
    candidate = urllib.parse.urljoin(f"{_prowlarr_url}/", download_url)
    if not is_allowed_prowlarr_url(candidate, _prowlarr_url):
        raise ValueError('Torrent URL is not from the configured Prowlarr server')
    req = urllib.request.Request(candidate, headers={
        'X-Api-Key': _prowlarr_key,
        'Accept': 'application/x-bittorrent, application/octet-stream',
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        torrent_bytes = response.read(10 * 1024 * 1024 + 1)
        if len(torrent_bytes) > 10 * 1024 * 1024:
            raise ValueError('Torrent file is larger than 10 MB')
        content_disposition = response.headers.get('Content-Disposition', '')
    filename_match = re.search(r'filename="?([^";]+)', content_disposition, flags=re.I)
    filename = filename_match.group(1) if filename_match else 'ai-control-result.torrent'
    if not filename.lower().endswith('.torrent'):
        filename += '.torrent'
    return manager.submit_torrent(torrent_bytes, os.path.basename(filename), metadata)


@app.route('/api/ai-control/preview', methods=['POST'])
def ai_control_preview():
    data = request.get_json(silent=True) or {}
    prompt = str(data.get('prompt', '') or '').strip()
    if not prompt:
        return jsonify({'error': 'Prompt cannot be empty'}), 400
    try:
        result = ai_control.preview_command(
            prompt,
            config=_effective_ai_control_config(),
            library_items=_ai_control_library_items(),
            library_roots=get_movies_dirs(),
            plan_store=_ai_control_plan_store,
            ollama_chat=_ollama_chat_content if _ollama_url and _ollama_model else None,
            tmdb_discover=_ai_control_tmdb_discover,
            tmdb_search=_ai_control_tmdb_search,
            person_movies=_ai_control_person_movies,
            source_search=_ai_control_source_search,
            owned_movie_lookup=_find_owned_movie,
        )
        return jsonify(result)
    except Exception as error:
        return jsonify({'error': str(error)}), 500


@app.route('/api/ai-control/execute', methods=['POST'])
def ai_control_execute():
    data = request.get_json(silent=True) or {}
    plan_id = str(data.get('plan_id', '') or '').strip()
    if not plan_id:
        return jsonify({'error': 'plan_id is required'}), 400
    try:
        result = ai_control.execute_plan(
            plan_id,
            plan_store=_ai_control_plan_store,
            confirmation_phrase=str(data.get('confirmation_phrase', '') or ''),
            library_roots=get_movies_dirs(),
            delete_file=_ai_control_delete_file,
            create_list=_ai_control_create_list,
            submit_download=_ai_control_submit_download,
        )
        status = 409 if result.get('state') in {'unsafe', 'unsupported'} else 200
        return jsonify(result), status
    except Exception as error:
        return jsonify({'error': str(error)}), 500


@app.route('/api/streaming/config', methods=['GET', 'POST'])
def streaming_config():
    global _streaming_enabled, _streaming_label, _streaming_url_template
    if request.method == 'GET':
        return jsonify({
            'enabled': _streaming_enabled,
            'label': _streaming_label,
            'url_template': _streaming_url_template,
        })
    data = request.get_json(silent=True) or {}
    label = str(data.get('label', _streaming_label) or '').strip() or 'Stream'
    url_template = str(data.get('url_template', _streaming_url_template) or '').strip()
    if url_template and not re.match(r'^https?://', url_template, flags=re.IGNORECASE):
        return jsonify({'error': 'Streaming URL template must start with http:// or https://'}), 400
    _streaming_enabled = _coerce_bool(data.get('enabled'), _streaming_enabled)
    _streaming_label = label
    _streaming_url_template = url_template
    _save_config(_all_config())
    return jsonify({
        'success': True,
        'enabled': _streaming_enabled,
        'label': _streaming_label,
        'url_template': _streaming_url_template,
    })


@app.route('/api/prowlarr/test')
def prowlarr_test():
    if not _prowlarr_url or not _prowlarr_key:
        return jsonify({'error': 'URL or API key is missing — please fill in both fields and save.'}), 400
    try:
        indexers = _fetch_enabled_prowlarr_indexers()
        return jsonify({'success': True, 'indexers': len(indexers)})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid API key — check Prowlarr → Settings → General.'}), 401
        return jsonify({'error': f'Prowlarr returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': f'Cannot reach Prowlarr: {e}'}), 502


@app.route('/api/qbittorrent/config', methods=['GET', 'POST'])
def qbittorrent_config():
    global _qbt_mode, _qbt_download_dir, _qbt_incomplete_dir, _qbt_webui_port
    if request.method == 'GET':
        return jsonify(_get_qbittorrent_manager().status())
    data = request.get_json(silent=True) or {}
    mode = str(data.get('mode', _qbt_mode) or '').strip().lower()
    if mode not in {'embedded', 'system'}:
        return jsonify({'error': 'Torrent handling mode must be embedded or system'}), 400
    download_dir = str(data.get('download_dir', _qbt_download_dir) or '').strip()
    incomplete_dir = str(data.get('incomplete_dir', _qbt_incomplete_dir) or '').strip()
    try:
        port = int(data.get('webui_port', _qbt_webui_port) or DEFAULT_WEBUI_PORT)
    except (TypeError, ValueError):
        return jsonify({'error': 'qBittorrent WebUI port is invalid'}), 400
    if port < 1024 or port > 65535:
        return jsonify({'error': 'qBittorrent WebUI port must be between 1024 and 65535'}), 400
    effective_incomplete = incomplete_dir or os.path.join(_user_data_dir, 'qbittorrent', 'incomplete')
    if any(is_path_within(effective_incomplete, root) for root in get_movies_dirs()):
        return jsonify({'error': 'Incomplete downloads folder must be outside every movie library'}), 400
    try:
        if download_dir:
            os.makedirs(download_dir, exist_ok=True)
        os.makedirs(effective_incomplete, exist_ok=True)
    except OSError as error:
        return jsonify({'error': f'Cannot create qBittorrent folder: {error}'}), 400
    _qbt_mode = mode
    _qbt_download_dir = download_dir
    _qbt_incomplete_dir = incomplete_dir
    _qbt_webui_port = port
    _save_config(_all_config())
    return jsonify(_get_qbittorrent_manager().configuration())


@app.route('/api/qbittorrent/status')
def qbittorrent_status():
    try:
        return jsonify({
            **_get_qbittorrent_manager().status(),
            'import_monitor': _qbittorrent_import_monitor.snapshot(),
        })
    except QBittorrentError as error:
        return jsonify({'error': str(error)}), 502


@app.route('/api/qbittorrent/update', methods=['POST'])
def qbittorrent_update():
    if _qbt_mode != 'embedded':
        return jsonify({'error': 'Switch torrent handling to embedded qBittorrent before updating it'}), 409
    try:
        return jsonify(_get_qbittorrent_manager().update_latest())
    except QBittorrentError as error:
        return jsonify({'error': str(error)}), 502


def _qbittorrent_submission_metadata(data):
    return {
        'title': str(data.get('title', '') or '').strip(),
        'year': str(data.get('year', '') or '').strip(),
        'tmdb_id': str(data.get('tmdb_id', '') or '').strip(),
        'imdb_id': str(data.get('imdb_id', '') or '').strip(),
        'identity_handoff': {'state': 'pending'},
        'release_title': str(data.get('release_title', data.get('title', '')) or '').strip(),
        'indexer': str(data.get('indexer', '') or '').strip(),
    }


def _download_job_has_stable_identity(data):
    return bool(str((data or {}).get('tmdb_id') or '').strip() or str((data or {}).get('imdb_id') or '').strip())


def _existing_qbittorrent_job_for_magnet(manager, magnet):
    torrent_hash = magnet_hash(magnet)
    if not torrent_hash:
        return None
    jobs = getattr(manager, 'jobs', None)
    if not jobs:
        return None
    get_job = getattr(jobs, 'get', None)
    if callable(get_job):
        return get_job(torrent_hash)
    all_jobs = getattr(jobs, 'all', None)
    return all_jobs().get(torrent_hash) if callable(all_jobs) else None


@app.route('/api/qbittorrent/submit', methods=['POST'])
def qbittorrent_submit():
    if _qbt_mode != 'embedded':
        return jsonify({'error': 'Cinema Paradiso is configured to use the system torrent client'}), 409
    data = request.get_json(silent=True) or {}
    if not _download_job_has_stable_identity(data):
        return jsonify({'error': 'A TMDB or IMDb identity is required before CP can submit a download'}), 400
    if _curated_movie_is_owned(data) and not bool(data.get('upgrade')):
        return jsonify({'error': 'Movie is already in the library. Submit it as an upgrade to continue.'}), 409
    manager = _get_qbittorrent_manager()
    metadata = _qbittorrent_submission_metadata(data)
    magnet = str(data.get('magnet_url', '') or '').strip()
    download_url = str(data.get('download_url', '') or '').strip()
    try:
        if magnet:
            job = manager.submit_magnet(magnet, metadata)
        elif download_url:
            candidate = urllib.parse.urljoin(f"{_prowlarr_url}/", download_url)
            if not is_allowed_prowlarr_url(candidate, _prowlarr_url):
                return jsonify({'error': 'Torrent URL is not from the configured Prowlarr server'}), 400
            req = urllib.request.Request(candidate, headers={
                'X-Api-Key': _prowlarr_key,
                'Accept': 'application/x-bittorrent, application/octet-stream',
            })
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    torrent_bytes = response.read(10 * 1024 * 1024 + 1)
                    if len(torrent_bytes) > 10 * 1024 * 1024:
                        return jsonify({'error': 'Torrent file is larger than 10 MB'}), 400
                    content_disposition = response.headers.get('Content-Disposition', '')
                filename_match = re.search(r'filename="?([^";]+)', content_disposition, flags=re.I)
                filename = filename_match.group(1) if filename_match else 'prowlarr-result.torrent'
                if not filename.lower().endswith('.torrent'):
                    filename += '.torrent'
                job = manager.submit_torrent(torrent_bytes, os.path.basename(filename), metadata)
            except urllib.error.HTTPError as error:
                redirect_magnet = _magnet_from_http_redirect(error)
                if not redirect_magnet:
                    raise
                job = manager.submit_magnet(redirect_magnet, metadata)
        else:
            return jsonify({'error': 'No usable magnet or torrent URL was provided'}), 400
        return jsonify(job)
    except urllib.error.HTTPError as error:
        if magnet and getattr(error, 'code', None) == 409:
            existing_job = _existing_qbittorrent_job_for_magnet(manager, magnet)
            if existing_job:
                return jsonify({**existing_job, 'already_exists': True})
        return jsonify({'error': f'Prowlarr torrent download returned HTTP {error.code}'}), 502
    except (QBittorrentError, OSError) as error:
        return jsonify({'error': str(error)}), 400


@app.route('/api/qbittorrent/jobs')
def qbittorrent_jobs():
    return jsonify({'jobs': list(_get_qbittorrent_manager().jobs.all().values())})


@app.route('/api/qbittorrent/finalize', methods=['POST'])
def qbittorrent_finalize():
    try:
        manager = _get_qbittorrent_manager()
        results = manager.process_completed()
        _handle_completed_qbittorrent_imports(manager, results)
        return jsonify({'results': results})
    except QBittorrentError as error:
        return jsonify({'error': str(error)}), 502


@app.route('/api/prowlarr/search')
def prowlarr_search():
    if not _prowlarr_url or not _prowlarr_key:
        return jsonify({'error': 'Prowlarr not configured — click ⚙ Prowlarr in the header to enter your URL and API key.'}), 400
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'No query provided'}), 400
    try:
        # Fetch all enabled indexer IDs so every indexer is queried, not just the default subset
        indexer_ids = []
        try:
            indexer_ids = _enabled_prowlarr_indexer_ids()
        except Exception:
            pass  # fall back to Prowlarr default if indexer fetch fails

        results = _prowlarr_search(
            indexer_ids=indexer_ids,
            query=query,
            limit=1000,
            categories='',
            timeout=30,
        )
        # Detect resolution from torrent title and format results (all resolutions)
        filtered = []
        for r in results:
            title = r.get('title', '')
            tl = title.lower()
            res = 'Unknown'
            res_rank = 0
            if '2160p' in tl or '4k' in tl or 'uhd' in tl:
                res, res_rank = '4K', 4
            elif '1080p' in tl or re.search(r'[\.\-_ \[\(]1080[\.\-_ \]\)\[]', tl):
                res, res_rank = '1080p', 3
            elif '720p' in tl or re.search(r'[\.\-_ \[\(]720[\.\-_ \]\)\[]', tl):
                res, res_rank = '720p', 2
            elif '480p' in tl or re.search(r'[\.\-_ \[\(]480[\.\-_ \]\)\[]', tl):
                res, res_rank = '480p', 1
            size = r.get('size', 0)
            links = _prowlarr_result_links(r)
            filtered.append({
                'title': title,
                'indexer': r.get('indexer', ''),
                'size_human': format_size(size) if size else '?',
                'size': size,
                'seeders': r.get('seeders', 0),
                'resolution': res,
                'download_url': links['download_url'],
                'magnet_url': links['magnet_url'],
                'info_url': r.get('infoUrl', ''),
            })
        # Sort: resolution desc, then seeders desc
        filtered.sort(key=lambda x: (x['size'], x['seeders']), reverse=True)
        return jsonify({'results': filtered})
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'Prowlarr returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/open-file', methods=['POST'])
def open_file():
    data = request.get_json(silent=True)
    path = (data or {}).get('path', '').strip()
    if not path or not os.path.isfile(path):
        return jsonify({'error': 'File not found'}), 404
    try:
        os.startfile(path)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/delete', methods=['POST'])
def delete_file():
    data = request.get_json(silent=True)
    if not data or 'path' not in data:
        return jsonify({'error': 'No path provided'}), 400

    path = data['path']
    use_trash = data.get('trash', True)  # default: Recycle Bin
    abs_path = os.path.abspath(path)
    try:
        return jsonify(_delete_library_file(abs_path, use_trash=use_trash))
    except LibraryMutationError as error:
        return jsonify({'error': str(error)}), 403
    except FileNotFoundError:
        return jsonify({'error': 'File not found'}), 404
    except PermissionError:
        return jsonify({
            'error': 'Access denied. The file may be open in Plex or another program. '
                     'Try pausing Plex Media Server and then delete again.'
        }), 500
    except OSError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/library/status')
def library_status():
    return jsonify({
        'status': _library_status,
        'catalog_generation': _catalog_repository().generation('media'),
    })


@app.route('/api/library/reconcile', methods=['GET', 'POST'])
def library_reconcile():
    if request.method == 'GET':
        return jsonify(_library_reconcile_status())
    return jsonify(_start_library_reconcile(force=True))


def _catalog_file_record(candidate):
    """Expose the normalized SQL-backed file contract."""
    raw_record = candidate.get('raw_json')
    file_record = dict(raw_record) if isinstance(raw_record, dict) else {}
    for field in (
        'path', 'filename', 'library_root', 'size', 'added_time', 'modified_time',
        'resolution', 'rip_source', 'parsed_title', 'parsed_year', 'identity_status',
        'identity_title', 'identity_year', 'identity_source', 'identity_revision',
        'identity_decision_version', 'identity_evidence_fingerprint', 'tmdb_id',
        'imdb_id', 'plex_guid', 'plex_rating_key', 'display_provider',
        'metadata_status', 'metadata_source', 'metadata_accepted', 'enrichment_status',
        'ingest_status', 'manual_lock', 'manual_locked',
    ):
        if field in candidate:
            file_record[field] = candidate[field]
    return file_record


def _relational_canonical_for_path(path, store=None, include_overrides=True):
    store = store or _metadata_store()
    connection = store.catalog.store.connect()
    try:
        return store.catalog.store.canonical.project_path(
            connection,
            store._key(path),
            include_overrides=include_overrides,
        )
    finally:
        connection.close()


def _catalog_library_item(candidate, store, metadata_snapshot):
    file_record = _catalog_file_record(candidate)
    path = candidate.get('path', '')
    plex_data = candidate.get('plex_json') or {}
    tmdb_data = candidate.get('tmdb_json') or {}
    canonical = dict(candidate.get('relational_canonical') or {})
    if not canonical:
        canonical = _build_canonical_metadata(
            file_record,
            plex_data=plex_data,
            tmdb_data=tmdb_data,
            manual_match=candidate.get('manual_json') or {},
            display_provider=file_record.get('display_provider', ''),
            file_record=file_record,
        )
        identity = _poster_identity_for_movie(file_record, canonical, plex_data)
        canonical = _apply_metadata_override(canonical, identity, store=store, snapshot=metadata_snapshot)
        canonical = _apply_poster_override(canonical, identity, store=store, snapshot=metadata_snapshot)
    parsed_title = file_record.get('parsed_title', '')
    parsed_year = str(file_record.get('parsed_year', '') or '')
    fallback_title = str(parsed_title or Path(path).stem).title()
    display_title = fallback_title + (f' ({parsed_year})' if parsed_year else '')
    return {
        'title': display_title,
        'filename': file_record.get('filename') or os.path.basename(path),
        'path': path,
        'library_root': file_record.get('library_root', ''),
        'resolution': candidate.get('resolution') or 'Unknown',
        'resolution_rank': get_resolution_rank_str(candidate.get('resolution')),
        'rip_source': candidate.get('rip_source') or 'Unknown',
        'rip_rank': get_rip_rank(candidate.get('rip_source')),
        'size': int(candidate.get('size') or 0),
        'size_human': format_size(candidate.get('size') or 0),
        'added_time': candidate.get('added_time') or 0,
        'modified_time': candidate.get('modified_time') or 0,
        'plex_title': plex_data.get('plex_title', '') or canonical.get('plex_title', ''),
        'plex_year': str(plex_data.get('plex_year', '') or canonical.get('plex_year', '') or ''),
        'plex_genres': plex_data.get('plex_genres', []) or canonical.get('plex_genres', []),
        'plex_summary': plex_data.get('plex_summary', '') or canonical.get('plex_summary', ''),
        'plex_rating': plex_data.get('plex_rating', '') or canonical.get('plex_rating', ''),
        'plex_language': plex_data.get('plex_language', '') or canonical.get('plex_language', ''),
        'plex_country_flag': plex_data.get('plex_country_flag', '') or canonical.get('plex_country_flag', ''),
        'plex_country': plex_data.get('plex_country', '') or canonical.get('plex_country', ''),
        'plex_directors': plex_data.get('plex_directors', []) or canonical.get('plex_directors', []),
        'plex_cast': plex_data.get('plex_cast', []) or canonical.get('plex_cast', []),
        'tmdb_id': canonical.get('tmdb_id') or plex_data.get('tmdb_id', ''),
        'imdb_id': canonical.get('imdb_id') or plex_data.get('imdb_id', ''),
        'plex_guid': canonical.get('plex_guid') or plex_data.get('plex_guid', ''),
        'plex_poster': plex_data.get('plex_poster', '') or canonical.get('plex_poster', ''),
        'plex_matched': bool(plex_data) or bool(canonical.get('plex_title')) or canonical.get('detail_provider') == 'plex_snapshot',
        'canonical_metadata': canonical,
        'metadata_status': canonical.get('status', 'unmatched'),
        'metadata_source': canonical.get('source', ''),
        'metadata_accepted': bool(canonical.get('accepted')),
    }


@app.route('/api/library/details')
def library_details():
    path = str(request.args.get('path') or '').strip()
    if not path:
        return jsonify({'error': 'Library path is required'}), 400
    store = _metadata_store()
    candidate = store.catalog.owned_movie(path=path)
    if not candidate:
        return jsonify({'error': 'Library item was not found'}), 404
    return jsonify({
        'item': _catalog_library_item(candidate, store, None),
        'catalog_generation': store.catalog.generation('media'),
    })


def _maintenance_audit_from_catalog():
    """Project maintenance queues from the SQLite catalog, never from a tab scan."""
    repository = _catalog_repository()
    generation = repository.generation('media')
    if _maintenance_audit_cache.get('generation') == generation and _maintenance_audit_cache.get('audit') is not None:
        return _maintenance_audit_cache['audit']
    candidates = [
        candidate
        for candidate in _catalog_identity_candidates(repository)
        if candidate.get('path') and os.path.isfile(candidate['path'])
    ]
    audit = build_maintenance_audit(candidates, generation=generation)
    _maintenance_audit_cache['generation'] = generation
    _maintenance_audit_cache['audit'] = audit
    return audit


def _catalog_identity_candidates(repository=None):
    repository = repository or _catalog_repository()
    fingerprints = _metadata_store().get_identity_audit_fingerprints()
    candidates = repository.store.audit_library_candidates()
    for candidate in candidates:
        path = str(candidate.get('path') or (candidate.get('raw_json') or {}).get('path') or '')
        candidate['audit_fingerprint_json'] = dict(fingerprints.get(_norm(path), {}) or {})
    return candidates


def _identity_verification_audit_from_catalog():
    """Verify persisted identities from SQLite without writes or provider calls."""
    repository = _catalog_repository()
    generation = repository.generation('media')
    revision = (str(repository.database_path), generation)
    if (
        _identity_verification_audit_cache.get('revision') == revision
        and _identity_verification_audit_cache.get('audit') is not None
    ):
        return _identity_verification_audit_cache['audit']
    audit = build_identity_verification_audit(
        _catalog_identity_candidates(repository),
        generation=generation,
    )
    _identity_verification_audit_cache['revision'] = revision
    _identity_verification_audit_cache['audit'] = audit
    return audit


def _enrich_unverified_identity_aliases(limit=25):
    if not _tmdb_key:
        raise ValueError('TMDB is not configured')
    repository = _catalog_repository()
    candidates = _catalog_identity_candidates(repository)
    report = build_identity_verification_audit(
        candidates,
        generation=repository.generation('media'),
        sample_limit=len(candidates),
    )
    tmdb_ids = list(dict.fromkeys(
        str(item.get('tmdb_id', '') or '')
        for item in report.get('samples', {}).get('unverified', {}).get('items', [])
        if item.get('enrichment_needed') and item.get('tmdb_id')
    ))[:max(1, min(int(limit or 25), 50))]
    if not tmdb_ids:
        return {
            'requested': 0,
            'updated': 0,
            'failed': 0,
            'errors': [],
        }

    fetched = {}
    errors = []

    def fetch(tmdb_id):
        return tmdb_id, _fetch_tmdb_alternative_titles(tmdb_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(tmdb_ids))) as executor:
        futures = {executor.submit(fetch, tmdb_id): tmdb_id for tmdb_id in tmdb_ids}
        for future in concurrent.futures.as_completed(futures):
            tmdb_id = futures[future]
            try:
                _, aliases = future.result()
                fetched[tmdb_id] = aliases
            except Exception as error:
                errors.append({'tmdb_id': tmdb_id, 'error': str(error)})

    checked_at = time.time()
    store = _metadata_store()
    for tmdb_id, aliases in fetched.items():
        current = store.get_tmdb_metadata(tmdb_id) or {'tmdb_id': tmdb_id}
        store.save_tmdb_metadata({
            **current,
            'tmdb_id': tmdb_id,
            'alternative_titles': aliases,
            'alternative_titles_checked_at': checked_at,
        })
        _smart_match_tmdb_alias_cache[tmdb_id] = list(aliases)
    return {
        'requested': len(tmdb_ids),
        'updated': len(fetched),
        'failed': len(errors),
        'errors': errors,
    }


def _library_people_item(item):
    canonical = item.get('canonical_metadata') or {}
    return {
        'path': item.get('path', ''),
        'canonical_metadata': {
            'cast': _trim_people_for_card(canonical.get('cast')),
            'directors': _trim_people_for_card(canonical.get('directors'), limit=4),
        },
        'plex_cast': _trim_people_for_card(item.get('plex_cast')),
        'plex_directors': _trim_people_for_card(item.get('plex_directors'), limit=4),
    }


_maintenance_upgrade_key_cache = {'generation': None, 'paths': set()}


def _maintenance_upgrade_path_keys():
    repository = _catalog_repository()
    generation = repository.generation('media')
    if _maintenance_upgrade_key_cache['generation'] == generation:
        return set(_maintenance_upgrade_key_cache['paths'])
    fingerprints = _metadata_store().get_identity_audit_fingerprints()
    candidates = repository.store.maintenance_upgrade_candidates()
    for candidate in candidates:
        candidate['audit_fingerprint_json'] = dict(
            fingerprints.get(_norm(candidate.get('path', '')), {}) or {}
        )
    paths = {
        _norm(candidate.get('path', ''))
        for candidate in candidates
        if candidate.get('path') and verify_catalog_identity(candidate).get('classification') == 'verified'
    }
    _maintenance_upgrade_key_cache.update({'generation': generation, 'paths': paths})
    return set(paths)


def _library_query_filters(values=None):
    values = values or request.args

    def value(name, default=''):
        candidate = values.get(name, default)
        return str(candidate if candidate is not None else default).strip()

    collection_paths = values.get('collection_paths', [])
    if isinstance(collection_paths, str):
        try:
            collection_paths = _json.loads(collection_paths) if collection_paths else []
        except ValueError:
            collection_paths = []
    if not isinstance(collection_paths, list):
        collection_paths = []
    return {
        'query': value('q', value('query')),
        'quality': value('quality', 'all'),
        'resolution': value('resolution', 'all'),
        'source': value('source', 'all'),
        'genre': value('genre', 'all'),
        'language': value('language', 'all'),
        'country': value('country', 'all'),
        'year_from': value('year_from'),
        'year_to': value('year_to'),
        'min_rating': value('min_rating', 'all'),
        'sort': value('sort', 'added'),
        'role': value('role'),
        'person_id': value('person_id'),
        'person_name': value('person_name'),
        'collection_id': value('collection_id'),
        'collection_path_keys': collection_paths,
        'list_id': value('list_id'),
        'viewing_state': value('viewing_state', 'all'),
    }


def _paged_library_cards(store, *, reconcile_result=None, force_scan=False, force_plex=False):
    filters = _library_query_filters()
    upgrade_paths = _maintenance_upgrade_path_keys()
    filters['upgrade_path_keys'] = list(upgrade_paths)
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 40, type=int)
    result = store.catalog.library_page(filters, page=page, page_size=page_size)
    items = [
        _library_card_item(
            _catalog_library_item(candidate, store, None),
            upgrade_paths=upgrade_paths,
        )
        for candidate in result.pop('candidates')
    ]
    reconcile_result = reconcile_result or {}
    return jsonify({
        **result,
        'items': items,
        'count': result['total'],
        'page_count': len(items),
        'plex_enabled': bool(_plex_token),
        'plex_cached': any(bool(item.get('plex_matched')) for item in items),
        'cached': not (force_scan or force_plex),
        'source': 'catalog',
        'new_files': int(reconcile_result.get('checked', 0) or 0) if force_scan else 0,
        'metadata_matched': int(reconcile_result.get('matched', 0) or 0),
        'metadata_pending': int(reconcile_result.get('pending', 0) or 0),
        'metadata_review': int(reconcile_result.get('review', 0) or 0),
        'catalog_generation': store.catalog.generation('media'),
    })


@app.route('/api/library')
def library():
    global _library_cache, _library_status
    force_plex = request.args.get('force_plex') == '1'
    force_scan = request.args.get('force_scan') == '1'
    refresh_metadata = request.args.get('refresh_metadata') == '1'
    view = request.args.get('view', '').strip()
    try:
        previous_paths = {
            _norm(item.get('path', ''))
            for item in (_library_cache.get('items') or [])
            if item.get('path')
        }
        reconcile_result = _reconcile_library_files(force_unresolved=True) if force_scan else {}
        if force_plex or refresh_metadata:
            _auto_sync_plex(force=force_plex)
        if not refresh_metadata:
            store = _metadata_store()
            if view == 'cards':
                return _paged_library_cards(
                    store,
                    reconcile_result=reconcile_result,
                    force_scan=force_scan,
                    force_plex=force_plex,
                )
            needs_details = view in {'people', ''}
            items = None if (force_scan or force_plex or needs_details) else _fresh_catalog_library_items(store)
            if items is None:
                catalog = _current_catalog_store(store)
                items = [
                    _catalog_library_item(candidate, store, None)
                    for candidate in catalog.library_projection(include_details=needs_details)
                    if candidate.get('path') and os.path.isfile(candidate['path'])
                ]
                _store_library_cache(
                    items,
                    bool(_plex_token),
                    any(item.get('plex_matched') for item in items),
                    cache_key=(_library_roots_revision(), ('catalog',), _metadata_cache_revision(store)),
                )
                _library_cache['source'] = 'catalog'
            new_files = sum(1 for item in items if _norm(item['path']) not in previous_paths)
            if view in {'movie-list', 'cards'}:
                upgrade_paths = _maintenance_upgrade_path_keys()
                response_items = [_library_card_item(item, upgrade_paths=upgrade_paths) for item in items]
            elif view == 'files':
                response_items = [_movie_list_library_item(item) for item in items]
            elif view == 'people':
                response_items = [_library_people_item(item) for item in items]
            else:
                response_items = items
            return jsonify({
                'items': response_items,
                'count': len(response_items),
                'plex_enabled': bool(_plex_token),
                'plex_cached': any(item.get('plex_matched') for item in items),
                'cached': not (force_scan or force_plex),
                'source': 'catalog',
                'new_files': new_files if (force_scan or force_plex) else 0,
                'metadata_matched': int(reconcile_result.get('matched', 0) or 0),
                'metadata_pending': int(reconcile_result.get('pending', 0) or 0),
                'metadata_review': int(reconcile_result.get('review', 0) or 0),
                'catalog_generation': store.catalog.generation('media'),
            })
        _library_status = 'Scanning directory\u2026'
        total = sum(1 for _ in _iter_video_files())
        _library_status = f'Reading metadata for {total} files\u2026'
        n = 0
        store = _metadata_store()
        metadata_snapshot = store.snapshot()
        for movies_dir, root, file, full_path in _iter_video_files():
            n += 1
            if n % 50 == 0:
                _library_status = f'Reading metadata\u2026 {n}\u00a0/\u00a0{total}'
            file_facts = _video_file_facts(movies_dir, file, full_path, include_timestamps=True)
            norm_path = _norm(full_path)
            plex_data = dict(_plex_cache.get(norm_path, {}) or _plex_matched_by_fname.get(file.lower(), {}) or {})
            file_record = metadata_snapshot.get('files', {}).get(store._key(full_path), {})
            display_provider = file_record.get('display_provider', '')
            if display_provider == 'plex':
                plex_data = {
                    **plex_data,
                    **dict(metadata_snapshot.get('plex_files', {}).get(store._key(full_path), {}) or {}),
                }
            _tmdb_metadata_for_file(
                file_facts,
                plex_data=plex_data,
                store=store,
                refresh=True,
                snapshot=metadata_snapshot,
            )
        _library_status = ''
        items = [
            _catalog_library_item(candidate, store, None)
            for candidate in _current_catalog_store(store).library_projection(include_details=view == 'people')
            if candidate.get('path') and os.path.isfile(candidate['path'])
        ]
        items.sort(key=lambda item: (-float(item.get('added_time') or 0), item['title']))
        _save_res_cache()
        _store_library_cache(items, bool(_plex_token), len(_plex_cache) > 0)
        _library_cache['source'] = 'catalog'
        new_files = sum(1 for item in items if _norm(item['path']) not in previous_paths)
        if view == 'cards':
            return _paged_library_cards(
                store,
                reconcile_result=reconcile_result,
                force_scan=force_scan,
                force_plex=force_plex,
            )
        if view in {'movie-list', 'cards'}:
            upgrade_paths = _maintenance_upgrade_path_keys()
            response_items = [_library_card_item(item, upgrade_paths=upgrade_paths) for item in items]
        elif view == 'files':
            response_items = [_movie_list_library_item(item) for item in items]
        elif view == 'people':
            response_items = [_library_people_item(item) for item in items]
        else:
            response_items = items
        return jsonify({'items': response_items, 'count': len(response_items),
                        'plex_enabled': bool(_plex_token), 'plex_cached': len(_plex_cache) > 0,
                        'cached': False, 'new_files': new_files,
                        'metadata_matched': int(reconcile_result.get('matched', 0) or 0),
                        'metadata_pending': int(reconcile_result.get('pending', 0) or 0),
                        'metadata_review': int(reconcile_result.get('review', 0) or 0),
                        'catalog_generation': store.catalog.generation('media')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _library_check_v26():
    body = request.get_json(force=True, silent=True) or {}
    queries = body.get('movies', [])
    include_items = bool(body.get('include_items'))
    if not queries:
        return jsonify({'results': [], 'catalog_generation': _catalog_repository().generation('media')})
    store = _metadata_store()
    metadata_snapshot = store.snapshot()
    if any(True for _ in _iter_movie_roots()):
        requested_keys = [key for query in queries for key in _ownership_keys(query)]
        candidates = _current_catalog_store(store).ownership_candidates(requested_keys)
        entries = _catalog_owned_entries(candidates, store, metadata_snapshot)
    else:
        entries = []
    results = []
    upgrade_paths = _maintenance_upgrade_path_keys() if entries else set()
    for q in queries:
        match = _catalog_owned_movie(q, entries=entries)
        if match:
            item = match['item']
            canonical_card = _movie_list_library_item(item, upgrade_paths=upgrade_paths)
            results.append({
                'title': q.get('title', ''),
                'year': q.get('year', ''),
                'tmdb_id': str(q.get('tmdb_id', '') or match.get('tmdb_id', '') or ''),
                'imdb_id': str(q.get('imdb_id', '') or match.get('imdb_id', '') or ''),
                'found': True,
                'path': item['path'],
                'resolution': item.get('resolution', 'Unknown'),
                'size_human': item.get('size_human', ''),
                'maintenance_upgrade_candidate': canonical_card.get('maintenance_upgrade_candidate', False),
                'poster_url': item.get('canonical_metadata', {}).get('poster_url', ''),
                'canonical_card': canonical_card,
                **({'library_item': _movie_list_library_item(item, include_people=True, upgrade_paths=upgrade_paths)} if include_items else {}),
            })
        else:
            results.append({
                'title': q.get('title', ''),
                'year': q.get('year', ''),
                'tmdb_id': str(q.get('tmdb_id', '') or ''),
                'imdb_id': str(q.get('imdb_id', '') or ''),
                'found': False,
                'path': '',
                'resolution': '',
                'size_human': '',
            })
    return jsonify({
        'results': results,
        'catalog_generation': store.catalog.generation('media'),
    })


@app.route('/api/library/check', methods=['POST'])
def library_check():
    return _library_check_v26()


@app.route('/api/library/selection', methods=['POST'])
def library_selection():
    body = request.get_json(silent=True) or {}
    filters = _library_query_filters(body.get('filters') or body)
    filters['upgrade_path_keys'] = list(_maintenance_upgrade_path_keys())
    paths = _catalog_repository().library_selection_paths(filters)
    return jsonify({
        'paths': paths,
        'count': len(paths),
        'catalog_generation': _catalog_repository().generation('media'),
    })


@app.route('/api/library/selection/items', methods=['POST'])
def library_selection_items():
    body = request.get_json(silent=True) or {}
    paths = [str(path or '').strip() for path in body.get('paths', []) if str(path or '').strip()]
    if len(paths) > 10000:
        return jsonify({'error': 'Library selection is too large'}), 400
    store = _metadata_store()
    upgrade_paths = _maintenance_upgrade_path_keys()
    items = [
        _library_card_item(
            _catalog_library_item(candidate, store, None),
            upgrade_paths=upgrade_paths,
        )
        for candidate in store.catalog.library_candidates_for_paths(paths)
    ]
    return jsonify({
        'items': items,
        'count': len(items),
        'catalog_generation': store.catalog.generation('media'),
    })


def _maintenance_page(items, page=1, page_size=50):
    page_size = min(max(int(page_size or 50), 1), 200)
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(int(page or 1), 1), total_pages)
    start = (page - 1) * page_size
    return items[start:start + page_size], {
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_pages': total_pages,
        'page_start': start,
        'page_end': min(start + page_size, total),
    }


def _maintenance_search_text(*values):
    return ' '.join(str(value or '') for value in values).lower()


def _maintenance_workspace_payload(section=None, page=1, page_size=50, query=''):
    audit = _maintenance_audit_from_catalog()
    identity_review = _public_identity_audit_state(_get_identity_audit_coordinator().status())
    actionable = len(identity_review.get('proposals') or [])
    summary = {
        key: value
        for key, value in (audit.get('summary') or {}).items()
        if key not in {
            'verification_gaps',
            'automated_identity_checks',
            'hard_conflicts',
            'metadata_drift',
        }
    }
    summary['actionable_identities'] = actionable
    summary['identity_issues'] = int(summary.get('unmatched_files', 0) or 0) + actionable
    base = {
        **audit,
        'summary': summary,
        'identity': {'items': list((audit.get('identity') or {}).get('items') or [])},
        'identity_review': identity_review,
    }
    if not section:
        return base

    section = str(section).strip().lower()
    if section not in {'storage', 'upgrades', 'identity'}:
        raise ValueError('section must be storage, upgrades, or identity')
    needle = str(query or '').strip().lower()
    output = {
        'source': audit.get('source', 'catalog'),
        'generation': audit.get('generation', 0),
        'generated_at': audit.get('generated_at'),
        'summary': summary,
    }

    if section == 'storage':
        groups = list((audit.get('storage') or {}).get('groups') or [])
        if needle:
            groups = [
                group for group in groups
                if needle in _maintenance_search_text(
                    group.get('title'),
                    *[
                        value
                        for file in (group.get('files') or [])
                        for value in (file.get('filename'), file.get('path'), file.get('accepted_title'))
                    ],
                )
            ]
        visible, pagination = _maintenance_page(groups, page, page_size)
        output['storage'] = {'groups': visible, 'pagination': pagination}
        return output

    if section == 'upgrades':
        items = list((audit.get('upgrades') or {}).get('items') or [])
        resolutions = sorted({str(item.get('resolution') or '') for item in items if item.get('resolution')})
        sources = sorted({str(item.get('rip_source') or '') for item in items if item.get('rip_source')})
        resolution = str(request.args.get('resolution') or 'all')
        source = str(request.args.get('source') or 'all')
        items = [
            item for item in items
            if (not needle or needle in _maintenance_search_text(
                item.get('title'), item.get('year'), item.get('filename'), item.get('path')
            ))
            and (resolution == 'all' or item.get('resolution') == resolution)
            and (source == 'all' or item.get('rip_source') == source)
        ]
        visible, pagination = _maintenance_page(items, page, page_size)
        output['upgrades'] = {
            'items': visible,
            'pagination': pagination,
            'options': {'resolutions': resolutions, 'sources': sources},
        }
        return output

    items = list((audit.get('identity') or {}).get('items') or [])
    if needle:
        items = [
            item for item in items
            if needle in _maintenance_search_text(
                item.get('filename'), item.get('path'), item.get('accepted_title'),
                item.get('suggested_title'), item.get('suggested_year'), item.get('metadata_hint'),
            )
        ]
    visible, pagination = _maintenance_page(items, page, page_size)
    output['identity'] = {'items': visible, 'pagination': pagination}
    output['identity_review'] = identity_review
    return output


@app.route('/api/maintenance/audit')
def maintenance_audit():
    try:
        return jsonify(_maintenance_workspace_payload(
            section=request.args.get('section'),
            page=request.args.get('page', 1, type=int),
            page_size=request.args.get('page_size', 50, type=int),
            query=request.args.get('q', ''),
        ))
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    except Exception as error:
        return jsonify({'error': str(error)}), 500


@app.route('/api/metadata/identity-verification')
def identity_verification_audit():
    try:
        return jsonify(_identity_verification_audit_from_catalog())
    except Exception as error:
        return jsonify({'error': str(error)}), 500


@app.route('/api/metadata/identity-verification/enrich', methods=['POST'])
def identity_verification_enrich():
    try:
        body = request.get_json(silent=True) or {}
        enrichment = _enrich_unverified_identity_aliases(body.get('limit', 25))
        return jsonify({
            'enrichment': enrichment,
            'verification': _identity_verification_audit_from_catalog(),
            'audit': _maintenance_workspace_payload(),
        })
    except ValueError as error:
        return jsonify({'error': str(error)}), 400
    except Exception as error:
        return jsonify({'error': str(error)}), 500


@app.route('/api/stats')
def library_stats():
    try:
        force_plex = request.args.get('force_plex') == '1'
        if force_plex:
            _auto_sync_plex(force=True)
        stats_cache_key = _stats_cache_key()
        if not force_plex:
            cached_stats = _fresh_stats_cache(stats_cache_key)
            if cached_stats is not None:
                cached_stats.setdefault('catalog_generation', _catalog_repository().generation('media'))
                cached_stats['cached'] = True
                return jsonify(cached_stats)

        all_files = []
        title_set = set()
        by_resolution = {}
        by_source = {}
        by_decade = {}
        RES_RANK = {'4K': 4, '1080p': 3, '720p': 2, '480p': 1, 'Unknown': 0}

        file_rows = []
        for candidate in _current_catalog_store(_metadata_store()).file_inventory():
            full_path = candidate.get('path', '')
            if not full_path or not os.path.isfile(full_path):
                continue
            file = candidate.get('filename') or os.path.basename(full_path)
            parsed_title = candidate.get('parsed_title', '')
            parsed_year = str(candidate.get('parsed_year', '') or '')
            size = int(candidate.get('size') or 0)
            file_rows.append({
                'title': parsed_title.title() + (f' ({parsed_year})' if parsed_year else ''),
                'filename': file,
                'path': full_path,
                'library_root': candidate.get('library_root', ''),
                'size': size,
                'size_human': format_size(size),
                'resolution': candidate.get('resolution') or 'Unknown',
                'rip_source': candidate.get('rip_source') or 'Unknown',
                'year': parsed_year,
                'tmdb_id': candidate.get('tmdb_id', ''),
                'imdb_id': candidate.get('imdb_id', ''),
                'title_identity': candidate.get('identity_title', ''),
                'year_identity': candidate.get('identity_year', ''),
                'plex_title': candidate.get('plex_title', ''),
                'plex_year': candidate.get('plex_year', ''),
                'metadata_status': candidate.get('metadata_status', ''),
                'metadata_accepted': bool(candidate.get('metadata_accepted')),
            })

        for file_info in file_rows:
            size = file_info['size']
            res = file_info['resolution']
            rip = file_info['rip_source']
            parsed_title, parsed_year = parse_movie_title(file_info['filename'])
            if parsed_title:
                title_set.add((parsed_title, parsed_year))
            all_files.append(file_info)
            br = by_resolution.setdefault(res, {'count': 0, 'size': 0})
            br['count'] += 1
            br['size'] += size
            bs = by_source.setdefault(rip, {'count': 0, 'size': 0})
            bs['count'] += 1
            bs['size'] += size
            if parsed_year:
                try:
                    decade = f"{(int(parsed_year) // 10) * 10}s"
                except ValueError:
                    decade = 'Unknown'
            else:
                decade = 'Unknown'
            by_decade[decade] = by_decade.get(decade, 0) + 1

        maintenance_summary = _current_catalog_store(_metadata_store()).maintenance_storage_statistics()
        maintenance_summary['upgrade_candidates'] = len(_maintenance_upgrade_path_keys())

        total_size = sum(f['size'] for f in all_files)
        avg_size = total_size // len(all_files) if all_files else 0

        # Format sizes
        for k in by_resolution:
            by_resolution[k]['size_human'] = format_size(by_resolution[k]['size'])
        for k in by_source:
            by_source[k]['size_human'] = format_size(by_source[k]['size'])

        top_largest = sorted(all_files, key=lambda x: x['size'], reverse=True)[:10]

        plex_matched = None
        plex_unmatched = None
        if _plex_cache or _plex_matched_by_fname:
            plex_matched = sum(
                1
                for f in all_files
                if _norm(f['path']) in _plex_cache
                or os.path.basename(f['path']).lower() in _plex_matched_by_fname
            )
            plex_unmatched = len(all_files) - plex_matched

        unmatched_count = sum(
            1 for item in file_rows
            if item.get('metadata_status') != 'pending' and not item.get('metadata_accepted')
        )
        audit_state = _get_identity_audit_coordinator().status()
        audit_proposals = list(audit_state.get('proposals') or [])
        identity_review_recommended = sum(
            1 for proposal in audit_proposals
            if proposal.get('classification') == 'recommended'
        )

        payload = {
            'catalog_generation': _catalog_repository().generation('media'),
            'total_files': len(all_files),
            'unique_titles': len(title_set),
            'total_size': total_size,
            'total_size_human': format_size(total_size),
            'avg_size': avg_size,
            'avg_size_human': format_size(avg_size),
            'duplicate_groups': maintenance_summary['duplicate_groups'],
            'extra_copies': maintenance_summary['extra_copies'],
            'wasted_bytes': maintenance_summary['reclaimable_bytes'],
            'wasted_human': format_size(maintenance_summary['reclaimable_bytes']),
            'low_quality_count': maintenance_summary['upgrade_candidates'],
            'by_resolution': by_resolution,
            'by_source': by_source,
            'by_decade': by_decade,
            'top_largest': top_largest,
            'plex_matched': plex_matched,
            'plex_unmatched': plex_unmatched,
            'plex_enabled': bool(_plex_token),
            'unmatched_count': unmatched_count,
            'identity_review_count': len(audit_proposals),
            'identity_review_recommended': identity_review_recommended,
            'identity_review_last_checked_at': audit_state.get('last_checked_at', 0),
            'identity_review_status': audit_state.get('status', 'idle'),
            'identity_automatically_verified': int(audit_state.get('automatically_verified', 0) or 0),
            'cached': False,
        }
        _store_stats_cache(payload, stats_cache_key)
        return jsonify(payload)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Fix Unmatched ──────────────────────────────────────────────────────────────

def _plex_rescan():
    """Trigger a Plex library refresh for all movie sections. Silent on errors."""
    if not _plex_url or not _plex_token or not _plex_section_ids:
        return
    for sid in _plex_section_ids:
        try:
            url = f"{_plex_url}/library/sections/{sid}/refresh?X-Plex-Token={_plex_token}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception:
            pass


@app.route('/api/rename-file', methods=['POST'])
def rename_file():
    data = request.get_json(silent=True)
    if not data or 'path' not in data:
        return jsonify({'error': 'No path provided'}), 400
    old_path  = data['path']
    new_title = data.get('title', '').strip()
    new_year  = data.get('year', '').strip()
    if not new_title:
        return jsonify({'error': 'Title is required'}), 400

    abs_old = os.path.abspath(old_path)
    abs_dir = _path_library_root(abs_old)
    if not abs_dir:
        return jsonify({'error': 'Path is outside the allowed movies directory'}), 403
    if not os.path.isfile(abs_old):
        return jsonify({'error': 'File not found'}), 404

    ext = os.path.splitext(abs_old)[1]
    orig_basename = os.path.basename(abs_old)
    orig_res = get_resolution_from_file(abs_old)
    orig_rip = get_rip_source(orig_basename)
    quality_tag = ' '.join(t for t in [orig_res, orig_rip] if t and t != 'Unknown')
    new_filename = new_title + (f' ({new_year})' if new_year else '')
    if quality_tag:
        new_filename += f' [{quality_tag}]'
    new_filename += ext
    # Strip characters not allowed in Windows filenames
    new_filename = re.sub(r'[<>:"/\\|?*]', '', new_filename).strip()
    new_path = os.path.join(os.path.dirname(abs_old), new_filename)

    if os.path.exists(new_path) and os.path.normpath(new_path) != os.path.normpath(abs_old):
        return jsonify({'error': f'A file named "{new_filename}" already exists in that folder'}), 409

    try:
        os.rename(abs_old, new_path)
        _migrate_library_path(abs_old, new_path)
        # Ask Plex to rescan so it picks up the renamed file
        _plex_rescan()
        return jsonify({'success': True, 'new_path': new_path, 'new_filename': new_filename})
    except OSError as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/plex/force-scan', methods=['POST'])
def plex_force_scan():
    global _plex_cache_time
    if not _plex_url or not _plex_token:
        return jsonify({'error': 'Plex not configured'}), 400
    try:
        _plex_rescan()
        _plex_cache_time = 0.0
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/fix-path', methods=['POST'])
def fix_path():
    """Move a file (or its containing folder) one directory level up so Plex can find it.
    When the parent folder contains only this one video file, the whole folder is moved
    so Plex retains the folder-name metadata hint (e.g. 'Batman (2010)') after the move.
    Only allowed on files that are NOT already in Plex's matched cache."""
    data = request.get_json(silent=True)
    if not data or 'path' not in data:
        return jsonify({'error': 'No path provided'}), 400

    abs_path = os.path.abspath(data['path'])
    abs_dir  = _path_library_root(abs_path)
    if not abs_dir:
        return jsonify({'error': 'Path is outside the allowed movies directory'}), 403
    if not os.path.isfile(abs_path):
        return jsonify({'error': 'File not found'}), 404

    # Safety: refuse to move files Plex already matched (full-path check + filename fallback)
    norm = _norm(abs_path)
    fname_lower = os.path.basename(abs_path).lower()
    if norm in _plex_cache or fname_lower in _plex_matched_by_fname:
        return jsonify({'error': 'This file is already matched in Plex — not moving it'}), 409

    parent      = os.path.dirname(abs_path)
    grandparent = os.path.dirname(parent)

    try:
        relative_parts = Path(os.path.relpath(abs_path, abs_dir)).parts
    except ValueError:
        return jsonify({'error': 'Cannot move file - path is outside library'}), 400
    if len(relative_parts) <= 2:
        return jsonify({'error': 'File is already at the correct depth - no move needed'}), 409

    # Grandparent must still be inside (or equal to) the movies root
    if not (os.path.normpath(grandparent) == os.path.normpath(abs_dir) or
            os.path.normpath(grandparent).startswith(os.path.normpath(abs_dir) + os.sep)):
        return jsonify({'error': 'Cannot move file — destination would be outside library'}), 400

    # Decide: move entire folder or just the file?
    # Count video files in parent to decide.
    _JUNK = {'desktop.ini', 'thumbs.db', '.ds_store', 'folder.jpg', 'folder.png'}
    try:
        sibling_videos = [
            f for f in os.listdir(parent)
            if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS
        ]
    except OSError:
        sibling_videos = [os.path.basename(abs_path)]

    try:
        parent_name = os.path.basename(parent)
        # Use whole-folder move only when:
        #   1. There is exactly one video in the folder (folder acts as a Plex hint), AND
        #   2. The folder name contains a year — i.e. it looks like a movie title.
        # Generic names like "Downloads", "1080p", "Featurettes" would be useless as a hint.
        use_folder_move = (len(sibling_videos) == 1 and
                           bool(_MOVIE_FOLDER_RE.search(parent_name)))

        if use_folder_move:
            # ── Whole-folder move ────────────────────────────────────────────
            # Move the folder one level up so Plex can discover it using the
            # folder name (e.g. "Batman (2010)") as a metadata hint.
            great_grandparent = os.path.dirname(grandparent)
            dest_folder = os.path.join(great_grandparent, parent_name)
            if not is_path_within(dest_folder, abs_dir):
                return jsonify({'error': 'Cannot move file - destination would be outside library'}), 400
            if os.path.normpath(dest_folder) == os.path.normpath(parent):
                return jsonify({'error': 'File is already at the correct depth — no move needed'}), 409
            if os.path.exists(dest_folder):
                return jsonify({'error': f'A folder named "{parent_name}" already exists in the destination'}), 409
            os.rename(parent, dest_folder)
            new_path = os.path.join(dest_folder, os.path.basename(abs_path))
            _plex_cache.pop(norm, None)
            _plex_unmatched.pop(norm, None)
        else:
            # ── File-only move (multiple videos, or generic folder name) ──────
            new_path = os.path.join(grandparent, os.path.basename(abs_path))
            if not is_path_within(new_path, abs_dir):
                return jsonify({'error': 'Cannot move file - destination would be outside library'}), 400
            if os.path.normpath(new_path) == os.path.normpath(abs_path):
                return jsonify({'error': 'File is already at the correct depth — no move needed'}), 409
            if os.path.exists(new_path):
                return jsonify({'error': f'A file named "{os.path.basename(abs_path)}" already exists in the destination folder'}), 409
            os.rename(abs_path, new_path)
            # Try to clean up junk files and remove folder if now empty
            try:
                for f in os.listdir(parent):
                    if f.lower() in _JUNK:
                        try:
                            os.remove(os.path.join(parent, f))
                        except OSError:
                            pass
            except OSError:
                pass
            try:
                os.rmdir(parent)
            except OSError:
                pass
            _plex_cache.pop(norm, None)
            _plex_unmatched.pop(norm, None)

        _migrate_library_path(abs_path, new_path)
        # Ask Plex to rescan so it picks up the new location
        _plex_rescan()
        return jsonify({'success': True, 'new_path': new_path})
    except OSError as e:
        return jsonify({'error': str(e)}), 500


def _plex_metadata_for_path(path):
    abs_path = os.path.abspath(str(path or ''))
    filename = os.path.basename(abs_path).lower()
    store = _metadata_store()
    snapshot = store.snapshot()
    exact_candidates = (
        _plex_cache.get(_norm(abs_path), {}),
        _plex_unmatched.get(_norm(abs_path), {}),
        snapshot.get('plex_files', {}).get(store._key(abs_path), {}),
        snapshot.get('manual_matches', {}).get(store._key(abs_path), {}),
        snapshot.get('files', {}).get(store._key(abs_path), {}),
    )
    filename_candidates = (
        _plex_matched_by_fname.get(filename, {}),
        _plex_unmatched_by_fname.get(filename, {}),
    )

    def merge(candidates):
        merged = {}
        for candidate in reversed(candidates):
            for key, value in (candidate or {}).items():
                if value not in (None, '', [], {}):
                    merged[key] = value
        return merged

    exact = merge(exact_candidates)
    if any(exact.get(key) for key in ('rating_key', 'plex_guid', 'plex_title')):
        return exact
    return merge(filename_candidates)


def _plex_rating_key_for_path(path):
    return str(_plex_metadata_for_path(path).get('rating_key', '') or '').strip()


def _plex_match_identity_hints(path, plex_data=None):
    plex_data = dict(plex_data or {})
    if not path:
        return {
            'imdb_id': str(plex_data.get('imdb_id', '') or ''),
            'tmdb_id': str(plex_data.get('tmdb_id', '') or ''),
        }
    store = _metadata_store()
    snapshot = store.snapshot()
    key = store._key(path)
    record = snapshot.get('files', {}).get(key, {})
    manual = snapshot.get('manual_matches', {}).get(key, {})
    tmdb_id = str(
        record.get('tmdb_id')
        or manual.get('tmdb_id')
        or plex_data.get('tmdb_id')
        or ''
    )
    tmdb_data = snapshot.get('tmdb_movies', {}).get(tmdb_id, {}) if tmdb_id else {}
    return {
        'imdb_id': str(
            record.get('imdb_id')
            or manual.get('imdb_id')
            or plex_data.get('imdb_id')
            or tmdb_data.get('imdb_id')
            or ''
        ),
        'tmdb_id': tmdb_id,
    }


@app.route('/api/plex/match-search')
def plex_match_search():
    if not _plex_url or not _plex_token:
        return jsonify({'error': 'Plex not configured'}), 400
    path = request.args.get('path', '').strip()
    rating_key = request.args.get('rating_key', '').strip()
    title      = request.args.get('title', '').strip()
    year       = request.args.get('year', '').strip()
    plex_data = {}
    abs_path = ''
    if path:
        abs_path = os.path.abspath(path)
        if not _path_library_root(abs_path):
            return jsonify({'error': 'Path is outside the allowed movies directory'}), 403
        if not os.path.isfile(abs_path):
            return jsonify({'error': 'File not found'}), 404
        plex_data = _plex_metadata_for_path(abs_path)
        rating_key = str(plex_data.get('rating_key', '') or '').strip() or rating_key
        if not rating_key:
            _auto_sync_plex(force=True)
            plex_data = _plex_metadata_for_path(abs_path)
            rating_key = str(plex_data.get('rating_key', '') or '').strip()
    if not rating_key:
        return jsonify({
            'error': 'Plex has not indexed this file yet.',
            'code': 'plex_item_not_indexed',
        }), 409
    try:
        hints = _plex_match_identity_hints(abs_path, plex_data)
        results = _smart_match_plex_candidates(
            rating_key,
            title,
            year,
            imdb_id=hints.get('imdb_id', ''),
            tmdb_id=hints.get('tmdb_id', ''),
        )
        return jsonify({'results': results, 'rating_key': rating_key})
    except PlexMatchError as e:
        return jsonify({
            'error': str(e),
            'provider_status': e.status,
        }), 502
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'Plex returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/metadata/health')
def metadata_health():
    try:
        store = _metadata_store()
        snapshot = store.snapshot()
        counts = {
            'accepted': 0,
            'unmatched': 0,
            'review': 0,
            'conflict': 0,
            'pending': 0,
            'incomplete_enrichment': 0,
            'invariant_violations': 0,
        }
        for _, _, file, path in _iter_video_files():
            key = store._key(path)
            record = snapshot.get('files', {}).get(key, {})
            if record.get('ingest_status') == 'pending' or record.get('metadata_status') == 'pending':
                counts['pending'] += 1
                continue
            resolved = resolve_authoritative_identity(
                record,
                provider_metadata=_canonical_provider_metadata(
                    record.get('display_provider', ''),
                    snapshot.get('tmdb_movies', {}).get(str(record.get('tmdb_id') or ''), {}),
                    snapshot.get('plex_files', {}).get(key, {}),
                ),
                fallback={
                    'title': record.get('parsed_title') or parse_movie_title(file)[0],
                    'year': record.get('parsed_year') or parse_movie_title(file)[1],
                },
            )
            state = resolved.get('identity_state', 'unmatched')
            if state not in {'accepted', 'unmatched', 'review', 'conflict'}:
                state = 'unmatched'
                counts['invariant_violations'] += 1
            counts[state] += 1
            if state == 'accepted':
                if resolved.get('enrichment_state') != 'complete':
                    counts['incomplete_enrichment'] += 1
                if not (
                    resolved.get('tmdb_id')
                    or resolved.get('imdb_id')
                    or resolved.get('plex_guid')
                    or (resolved.get('title') and resolved.get('year'))
                ):
                    counts['invariant_violations'] += 1
        jobs = {
            'migration': _get_metadata_migration_coordinator().status().get('status', 'idle'),
            'smart_match': _get_smart_match_coordinator().status().get('status', 'idle'),
            'identity_audit': _get_identity_audit_coordinator().status().get('status', 'idle'),
        }
        return jsonify({**counts, 'active_identity_jobs': jobs})
    except Exception as error:
        return jsonify({'error': str(error)}), 500


@app.route('/api/plex/match-apply', methods=['POST'])
def plex_match_apply():
    global _library_cache
    if not _plex_url or not _plex_token:
        return jsonify({'error': 'Plex not configured'}), 400
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    rating_key = data.get('rating_key', '').strip()
    guid       = data.get('guid', '').strip()
    name       = data.get('name', '').strip()
    path       = data.get('path', '').strip()
    if not rating_key or not guid:
        return jsonify({'error': 'rating_key and guid are required'}), 400
    abs_path = os.path.abspath(path)
    if not path or not _path_library_root(abs_path):
        return jsonify({'error': 'Path is outside the allowed movies directory'}), 403
    if not os.path.isfile(abs_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        store = _metadata_store()
        facts = _metadata_file_facts(abs_path)
        poster_value = str(data.get('poster_url', '') or '')
        plex_thumb = poster_value if poster_value.startswith('/') and not poster_value.startswith('/api/plex/image') else ''
        if poster_value.startswith('/api/plex/image'):
            poster_query = urllib.parse.parse_qs(urllib.parse.urlparse(poster_value).query)
            plex_thumb = str((poster_query.get('path') or [''])[0] or '')
        match = store.apply_plex_match(abs_path, {
            'rating_key': rating_key,
            'plex_title': name,
            'plex_year': str(data.get('year', '') or ''),
            'plex_guid': guid,
            'plex_thumb': plex_thumb,
            'plex_summary': str(data.get('summary', '') or ''),
        }, facts=facts)
        _resolve_identity_audit_path(abs_path)
        _library_cache = {}
        return jsonify({'success': True, 'match': match})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── TMDB / Trending ──────────────────────────────────────────────────────────

@app.route('/api/tmdb/config', methods=['GET'])
def get_tmdb_config():
    return jsonify({'key': _tmdb_key, 'include_adult': _tmdb_include_adult})


@app.route('/api/tmdb/config', methods=['POST'])
def set_tmdb_config():
    global _tmdb_key, _tmdb_include_adult, _tmdb_genres
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    _tmdb_key = data.get('key', '').strip()
    if 'include_adult' in data:
        _tmdb_include_adult = _coerce_bool(data.get('include_adult'), False)
    _tmdb_genres = {}  # reset genre cache when key changes
    _save_config(_all_config())
    return jsonify({'success': True})


@app.route('/api/tmdb/test')
def tmdb_test():
    key = request.args.get('key', _tmdb_key).strip()
    if not key:
        return jsonify({'error': 'No API key — enter your TMDB key in Settings.'}), 400
    try:
        url = f"https://api.themoviedb.org/3/configuration?api_key={urllib.parse.quote(key)}"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            _json.loads(resp.read().decode())
        return jsonify({'success': True})
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid API key — check your TMDB account settings.'}), 401
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': f'Cannot reach TMDB: {e}'}), 502


def _ensure_tmdb_genres():
    """Lazy-load TMDB genre list into _tmdb_genres. Silent on error."""
    global _tmdb_genres
    if _tmdb_genres or not _tmdb_key:
        return
    try:
        url = f"https://api.themoviedb.org/3/genre/movie/list?api_key={urllib.parse.quote(_tmdb_key)}&language=en"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        _tmdb_genres = {g['id']: g['name'] for g in data.get('genres', [])}
    except Exception:
        pass


def _tmdb_include_adult_value(value=None):
    return 'true' if _coerce_bool(value, _tmdb_include_adult) else 'false'


@app.route('/api/metadata')
def get_metadata():
    title = request.args.get('title', '').strip()
    year  = request.args.get('year', '').strip()
    if not title:
        return jsonify({'error': 'title is required'}), 400
    cache_key = f"{title.lower()}_{year}"
    if cache_key in _metadata_cache:
        return jsonify(_metadata_cache[cache_key])
    if not _tmdb_key:
        return jsonify({'poster_url': '', 'genres': [], 'plot': '', 'tmdb_rating': '', 'tmdb_vote_count': 0})
    _ensure_tmdb_genres()
    try:
        params = urllib.parse.urlencode({
            'query': title,
            'api_key': _tmdb_key,
            'language': 'en-US',
            'page': 1,
            'include_adult': _tmdb_include_adult_value(),
        })
        if year:
            params += '&year=' + urllib.parse.quote(year)
        url = f"https://api.themoviedb.org/3/search/movie?{params}"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        results = data.get('results', [])
        result = results[0] if results else {}
        poster_path = result.get('poster_path', '')
        poster_url  = f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else ''
        genre_ids   = result.get('genre_ids', [])
        genres      = [_tmdb_genres[gid] for gid in genre_ids if gid in _tmdb_genres][:3]
        plot        = result.get('overview', '')
        vote        = result.get('vote_average', 0)
        tmdb_rating = f"{vote:.1f}" if isinstance(vote, (int, float)) and vote else ''
        meta = {'poster_url': poster_url, 'genres': genres, 'plot': plot, 'tmdb_rating': tmdb_rating,
                'tmdb_vote_count': int(result.get('vote_count', 0) or 0), 'tmdb_id': result.get('id', None)}
        _metadata_cache[cache_key] = meta
        return jsonify(meta)
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/explore/browse')
def explore_browse():
    browse_query = request.args.get('q', '').strip()
    latest = request.args.get('latest') == '1'
    selected_indexer_id = request.args.get('indexer_id', '').strip()
    if not browse_query and not latest:
        return jsonify({'results': [], 'tmdb_enabled': bool(_tmdb_key), 'all_indexers': [], 'requires_query': True})
    if not _prowlarr_url or not _prowlarr_key:
        return jsonify({'error': 'Prowlarr not configured — click ⚙ Settings to enter your Prowlarr URL and API key.'}), 400
    try:
        # Fetch all enabled indexer IDs
        indexers = []
        try:
            indexers = _fetch_enabled_prowlarr_indexers()
        except Exception:
            pass
        indexer_ids = [ix['id'] for ix in indexers]
        if selected_indexer_id:
            if selected_indexer_id not in indexer_ids:
                return jsonify({'error': 'Selected indexer is not available in Prowlarr.'}), 400
            indexer_ids = [selected_indexer_id]
        indexer_names = [ix['name'] for ix in indexers]
        selected_indexers = [ix for ix in indexers if ix['id'] in indexer_ids]

        def _fetch(query=''):
            return _prowlarr_search(
                indexer_ids=indexer_ids,
                query=query,
                limit=100,
                categories='2000',
                timeout=30,
            )

        results = _fetch(browse_query)
        if not browse_query and len(results) < 20:
            fallback = _fetch('2025')
            if len(fallback) > len(results):
                results = fallback

        # Build deduplicated movie list
        movies = {}  # key -> {parsed_title, parsed_year, variants[]}
        for r in results:
            title = r.get('title', '')
            # Skip TV episodes
            if _TV_RE.search(title):
                continue
            tl = title.lower()
            res = 'Unknown'
            if '2160p' in tl or '4k' in tl or 'uhd' in tl:
                res = '4K'
            elif '1080p' in tl or re.search(r'[\.\-_ \[\(]1080[\.\-_ \]\)\[]', tl):
                res = '1080p'
            elif '720p' in tl or re.search(r'[\.\-_ \[\(]720[\.\-_ \]\)\[]', tl):
                res = '720p'
            elif '480p' in tl or re.search(r'[\.\-_ \[\(]480[\.\-_ \]\)\[]', tl):
                res = '480p'
            parsed = parse_movie_title(title)
            parsed_title = parsed[0].title() if parsed[0] else title
            parsed_year  = parsed[1] or ''
            size = r.get('size', 0)
            links = _prowlarr_result_links(r)
            variant = {
                'resolution': res,
                'seeders': r.get('seeders', 0),
                'magnet_url': links['magnet_url'],
                'download_url': links['download_url'],
                'info_url': r.get('infoUrl', ''),
                'indexer': r.get('indexer', ''),
                'size_human': format_size(size) if size else '?',
                'title': title,
            }
            key = f"{parsed_title.lower()}_{parsed_year}"
            if key not in movies:
                movies[key] = {'parsed_title': parsed_title, 'parsed_year': parsed_year, 'variants': [variant]}
            else:
                movies[key]['variants'].append(variant)

        # Sort variants within each movie by seeders desc; deduplicate by resolution (keep best per res)
        processed = []
        for m in movies.values():
            by_res = {}
            for v in m['variants']:
                r = v['resolution']
                if r not in by_res or v['seeders'] > by_res[r]['seeders']:
                    by_res[r] = v
            RES_ORDER = ['4K', '1080p', '720p', '480p', 'Unknown']
            variants  = [by_res[r] for r in RES_ORDER if r in by_res]
            best = variants[0]
            processed.append({
                'parsed_title': m['parsed_title'],
                'parsed_year':  m['parsed_year'],
                'best_seeders': best['seeders'],
                'best_resolution': best['resolution'],
                'indexer': best['indexer'],
                'variants': variants,
            })

        rss_prioritized = False
        if latest and not browse_query and any(_is_yts_indexer_name(ix.get('name')) for ix in selected_indexers):
            by_key = {f"{row.get('parsed_title', '').lower()}_{row.get('parsed_year', '')}": row for row in processed}
            merged = []
            for row in _fetch_yts_rss_latest(limit=100):
                key = f"{row.get('parsed_title', '').lower()}_{row.get('parsed_year', '')}"
                existing = by_key.pop(key, None)
                if existing:
                    seen = {
                        (variant.get('magnet_url'), variant.get('download_url'), variant.get('info_url'))
                        for variant in row.get('variants', [])
                    }
                    extra_variants = [
                        variant for variant in existing.get('variants', [])
                        if (variant.get('magnet_url'), variant.get('download_url'), variant.get('info_url')) not in seen
                    ]
                    row['variants'] = row.get('variants', []) + extra_variants
                merged.append(row)
            if merged:
                processed = merged + list(by_key.values())
                rss_prioritized = True

        if not rss_prioritized:
            processed.sort(key=lambda x: x['best_seeders'], reverse=True)
        return jsonify({
            'results': processed[:100],
            'tmdb_enabled': bool(_tmdb_key),
            'all_indexers': sorted(indexer_names),
            'indexers': sorted(indexers, key=lambda ix: ix['name'].lower()),
            'selected_indexer_id': selected_indexer_id,
        })
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'Prowlarr returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/explore/indexers')
def explore_indexers():
    if not _prowlarr_url or not _prowlarr_key:
        return jsonify({'error': 'Prowlarr not configured â€” click âš™ Settings to enter your Prowlarr URL and API key.'}), 400
    try:
        return jsonify({'indexers': sorted(_fetch_enabled_prowlarr_indexers(), key=lambda ix: ix['name'].lower())})
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'Prowlarr returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tmdb/discover')
def tmdb_discover():
    if not _tmdb_key:
        return jsonify({'error': 'TMDB key not configured — add it in ⚙ Settings.'}), 400
    list_name = request.args.get('list', 'trending_week')
    genre_id  = request.args.get('genre', '').strip()
    min_votes = request.args.get('min_votes', '').strip()
    year_from = request.args.get('year_from', '').strip()
    year_to = request.args.get('year_to', '').strip()
    min_rating = request.args.get('min_rating', '').strip()
    sort_override = request.args.get('sort', '').strip()
    try:
        page = max(1, min(int(request.args.get('page', '1')), 10))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get('page_size', '20'))
    except ValueError:
        page_size = 20
    page_size = 40 if page_size >= 40 else 20

    # Sort strategy per list when using genre filter via /discover/movie
    _list_sort = {
        'trending_week': 'popularity.desc',
        'trending_today': 'popularity.desc',
        'now_playing':   'popularity.desc',
        'popular':       'popularity.desc',
        'upcoming':      'primary_release_date.desc',
        'top_rated':     'vote_average.desc',
        'best_all_time': 'vote_count.desc',
    }

    _ensure_tmdb_genres()
    try:
        advanced_discover = bool(
            list_name == 'catalog'
            or genre_id
            or year_from
            or year_to
            or min_rating
            or min_votes
            or sort_override
        )
        tmdb_pages = [page]
        if page_size == 40:
            tmdb_pages = [(page - 1) * 2 + 1, (page - 1) * 2 + 2]

        if advanced_discover:
            sort_by = 'original_title.asc' if sort_override == 'title.asc' else (sort_override or _list_sort.get(list_name, 'popularity.desc'))
            params = urllib.parse.urlencode({
                'api_key':        _tmdb_key,
                'language':       'en-US',
                'sort_by':        sort_by,
                'page':           tmdb_pages[0],
            })
            if genre_id:
                params += '&with_genres=' + urllib.parse.quote(genre_id)
            if min_votes:
                params += '&vote_count.gte=' + urllib.parse.quote(min_votes)
            elif genre_id:
                params += '&vote_count.gte=50'
            if year_from:
                params += '&primary_release_date.gte=' + urllib.parse.quote(f'{year_from}-01-01')
            if year_to:
                params += '&primary_release_date.lte=' + urllib.parse.quote(f'{year_to}-12-31')
            if min_rating:
                params += '&vote_average.gte=' + urllib.parse.quote(min_rating)
            if list_name == 'top_rated':
                params += '&vote_average.gte=6.0'
            elif list_name == 'best_all_time':
                params += f"&vote_average.gte=7.5&vote_count.gte={urllib.parse.quote(min_votes or '5000')}"
            url = f"https://api.themoviedb.org/3/discover/movie?{params}"
        elif list_name == 'best_all_time':
            params = urllib.parse.urlencode({
                'api_key':            _tmdb_key,
                'language':           'en-US',
                'sort_by':            'vote_count.desc',
                'vote_average.gte':   '7.5',
                'vote_count.gte':     min_votes or '5000',
                'page':               tmdb_pages[0],
            })
            url = f"https://api.themoviedb.org/3/discover/movie?{params}"
        elif list_name == 'trending_today':
            url = (f"https://api.themoviedb.org/3/trending/movie/day"
                   f"?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US&page={tmdb_pages[0]}")
        else:
            endpoint_map = {
                'trending_week': 'https://api.themoviedb.org/3/trending/movie/week',
                'now_playing':   'https://api.themoviedb.org/3/movie/now_playing',
                'popular':       'https://api.themoviedb.org/3/movie/popular',
                'upcoming':      'https://api.themoviedb.org/3/movie/upcoming',
                'top_rated':     'https://api.themoviedb.org/3/movie/top_rated',
            }
            base_url = endpoint_map.get(list_name, endpoint_map['trending_week'])
            url = f"{base_url}?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US&page={tmdb_pages[0]}"

        data = {'results': [], 'total_pages': 1, 'total_results': 0}
        urls = [url]
        if page_size == 40:
            if 'page=' in url:
                urls.append(re.sub(r'page=\d+', f'page={tmdb_pages[1]}', url))
            else:
                urls.append(url + f'&page={tmdb_pages[1]}')
        for index, page_url in enumerate(urls):
            req = urllib.request.Request(page_url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                page_data = _json.loads(resp.read().decode())
            if index == 0:
                data['total_pages'] = page_data.get('total_pages', 1)
                data['total_results'] = page_data.get('total_results', 0)
            data['results'].extend(page_data.get('results', []))
        movies = []
        for m in data.get('results', []):
            poster_path = m.get('poster_path', '')
            release = m.get('release_date', '') or ''
            year    = release[:4] if release else ''
            genre_ids = m.get('genre_ids', [])
            genres  = [_tmdb_genres[gid] for gid in genre_ids if gid in _tmdb_genres][:3]
            vote    = m.get('vote_average', 0)
            lang    = m.get('original_language', '')
            countries = m.get('origin_country', [])
            country_code = countries[0] if countries else _LANG_COUNTRY.get(lang, '')
            movies.append({
                'tmdb_id':    m.get('id'),
                'title':      m.get('title', ''),
                'year':       year,
                'poster_url': f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else '',
                'genres':     genres,
                'tmdb_rating': f"{vote:.1f}" if isinstance(vote, (int, float)) and vote else '',
                'tmdb_vote_count': int(m.get('vote_count', 0) or 0),
                'plot':       m.get('overview', ''),
                'language':   _LANG_NAMES.get(lang, lang.upper() if lang else ''),
                'country':    country_code,
                'country_flag': _country_flag(country_code),
                'release_date': release,
                'adult': bool(m.get('adult', False)),
            })
        total_pages = int(data.get('total_pages', 1) or 1)
        if page_size == 40:
            total_pages = (total_pages + 1) // 2
        return jsonify({
            'results': movies[:page_size],
            'total_pages': min(total_pages, 10),
            'page': page,
            'total_results': data.get('total_results', len(movies)),
        })
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid TMDB API key — check Settings.'}), 401
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/explore/search')
def explore_search():
    title = request.args.get('title', '').strip()
    year  = request.args.get('year', '').strip()
    if not title:
        return jsonify({'error': 'title required'}), 400
    if not _prowlarr_url or not _prowlarr_key:
        return jsonify({'error': 'Prowlarr not configured — add it in ⚙ Settings.'}), 400
    try:
        indexer_ids = []
        try:
            indexer_ids = _enabled_prowlarr_indexer_ids()
        except Exception:
            pass
        results = _prowlarr_search_movie(
            indexer_ids,
            {
                'title': title,
                'year': year,
                'imdb_id': request.args.get('imdb_id', '').strip(),
                'tmdb_id': request.args.get('tmdb_id', '').strip(),
            },
            timeout=SOURCE_SEARCH_QUERY_TIMEOUT_SECONDS,
            deadline_seconds=SOURCE_SEARCH_DEADLINE_SECONDS,
        )
        variants = _torrent_variants_from_prowlarr_results(results)
        return jsonify({'variants': variants})
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'Prowlarr returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/explore/search/jobs', methods=['POST'])
def explore_search_job_start():
    data = request.get_json(silent=True) or {}
    title = str(data.get('title', '') or '').strip()
    year = str(data.get('year', '') or '').strip()
    if not title:
        return jsonify({'error': 'title required'}), 400
    if not _prowlarr_url or not _prowlarr_key:
        return jsonify({'error': 'Prowlarr not configured — add it in ⚙ Settings.'}), 400
    snapshot = _create_source_search_job({
        'title': title,
        'year': year,
        'imdb_id': str(data.get('imdb_id', '') or '').strip(),
        'tmdb_id': str(data.get('tmdb_id', '') or '').strip(),
    })
    return jsonify(snapshot)


@app.route('/api/explore/search/jobs/<search_id>')
def explore_search_job_status(search_id):
    snapshot = _source_search_job_response(search_id)
    if not snapshot:
        return jsonify({'error': 'Source search job not found'}), 404
    return jsonify(snapshot)


@app.route('/api/tmdb/search')
def tmdb_search():
    if not _tmdb_key:
        return jsonify({'error': 'TMDB key not configured — add it in ⚙ Settings.'}), 400
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': 'q (query) parameter required'}), 400
    year = request.args.get('year', '').strip()
    genre_id = request.args.get('genre', '').strip()
    min_votes_raw = request.args.get('min_votes', '').strip()
    year_from = request.args.get('year_from', '').strip()
    year_to = request.args.get('year_to', '').strip()
    min_rating_raw = request.args.get('min_rating', '').strip()
    sort_override = request.args.get('sort', '').strip()
    try:
        min_votes = int(min_votes_raw or 0)
    except ValueError:
        min_votes = 0
    try:
        min_rating = float(min_rating_raw or 0)
    except ValueError:
        min_rating = 0
    try:
        page = max(1, min(int(request.args.get('page', '1')), 10))
    except ValueError:
        page = 1
    try:
        page_size = int(request.args.get('page_size', '20'))
    except ValueError:
        page_size = 20
    page_size = 40 if page_size >= 40 else 20
    _ensure_tmdb_genres()
    try:
        tmdb_pages = [page]
        if page_size == 40:
            tmdb_pages = [(page - 1) * 2 + 1, (page - 1) * 2 + 2]
        params = urllib.parse.urlencode({
            'query': q, 'api_key': _tmdb_key,
            'language': 'en-US',
            'page': tmdb_pages[0],
            'include_adult': _tmdb_include_adult_value(request.args.get('include_adult')),
        })
        if year:
            params += '&year=' + urllib.parse.quote(year)
        url = f"https://api.themoviedb.org/3/search/movie?{params}"
        data = {'results': [], 'total_pages': 1, 'total_results': 0}
        urls = [url]
        if page_size == 40:
            urls.append(re.sub(r'page=\d+', f'page={tmdb_pages[1]}', url))
        for index, page_url in enumerate(urls):
            req = urllib.request.Request(page_url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                page_data = _json.loads(resp.read().decode())
            if index == 0:
                data['total_pages'] = page_data.get('total_pages', 1)
                data['total_results'] = page_data.get('total_results', 0)
            data['results'].extend(page_data.get('results', []))
        movies = []
        for m in data.get('results', []):
            vote_count = int(m.get('vote_count', 0) or 0)
            if min_votes and vote_count < min_votes:
                continue
            genre_ids = m.get('genre_ids', [])
            if genre_id and genre_id not in {str(value) for value in genre_ids}:
                continue
            release = m.get('release_date', '') or ''
            release_year = release[:4]
            if year_from and (not release_year or release_year < year_from):
                continue
            if year_to and (not release_year or release_year > year_to):
                continue
            vote = m.get('vote_average', 0)
            if min_rating and float(vote or 0) < min_rating:
                continue
            poster_path = m.get('poster_path', '')
            movie_year = release[:4] if release else ''
            genres  = [_tmdb_genres[gid] for gid in genre_ids if gid in _tmdb_genres][:3]
            lang    = m.get('original_language', '')
            country_code = _LANG_COUNTRY.get(lang, '')
            movies.append({
                'tmdb_id':    m.get('id'),
                'title':      m.get('title', ''),
                'year':       movie_year,
                'poster_url': f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else '',
                'genres':     genres,
                'tmdb_rating': f"{vote:.1f}" if isinstance(vote, (int, float)) and vote else '',
                'tmdb_vote_count': vote_count,
                'popularity': float(m.get('popularity', 0) or 0),
                'plot':       m.get('overview', ''),
                'language':   _LANG_NAMES.get(lang, lang.upper() if lang else ''),
                'country':    country_code,
                'country_flag': _country_flag(country_code),
                'release_date': release,
            })
        if sort_override == 'popularity.desc':
            movies.sort(key=lambda movie: float(movie.get('popularity') or 0), reverse=True)
        elif sort_override == 'vote_average.desc':
            movies.sort(key=lambda movie: float(movie.get('tmdb_rating') or 0), reverse=True)
        elif sort_override == 'vote_count.desc':
            movies.sort(key=lambda movie: int(movie.get('tmdb_vote_count') or 0), reverse=True)
        elif sort_override == 'primary_release_date.desc':
            movies.sort(key=lambda movie: movie.get('release_date') or '', reverse=True)
        elif sort_override == 'title.asc':
            movies.sort(key=lambda movie: str(movie.get('title') or '').casefold())
        return jsonify({
            'results': movies[:page_size],
            'total_pages': min(((int(data.get('total_pages', 1) or 1) + 1) // 2) if page_size == 40 else int(data.get('total_pages', 1) or 1), 10),
            'page': page,
            'total_results': data.get('total_results', 0),
            'criteria_applied': bool(genre_id or min_votes or year_from or year_to or min_rating or sort_override),
        })
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid TMDB API key — check Settings.'}), 401
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tmdb/people/search')
def tmdb_people_search():
    if not _tmdb_key:
        return jsonify({'error': 'TMDB key not configured — add it in ⚙ Settings.'}), 400
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'q (query) parameter required'}), 400
    try:
        page = max(1, min(int(request.args.get('page', '1')), 10))
    except ValueError:
        page = 1
    try:
        def fetch_people(search_query):
            params = urllib.parse.urlencode({
                'api_key': _tmdb_key,
                'query': search_query,
                'language': 'en-US',
                'include_adult': _tmdb_include_adult_value(request.args.get('include_adult')),
                'page': page,
            })
            url = f"https://api.themoviedb.org/3/search/person?{params}"
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return _json.loads(resp.read().decode())

        data = fetch_people(query)
        people = data.get('results', []) or []
        used_split_fallback = False
        normalized_query = re.sub(r'[^a-z0-9]', '', query.casefold())
        if not people and page == 1 and normalized_query == query.casefold() and len(normalized_query) >= 5:
            candidates = {}
            for index in range(2, len(query) - 1):
                split_data = fetch_people(f"{query[:index]} {query[index:]}")
                for person in split_data.get('results', []) or []:
                    normalized_name = re.sub(r'[^a-z0-9]', '', str(person.get('name', '') or '').casefold())
                    if normalized_name == normalized_query:
                        candidates[str(person.get('id', '') or '')] = person
                if candidates:
                    break
            if candidates:
                people = list(candidates.values())
                used_split_fallback = True
        results = []
        for person in people:
            person_id = str(person.get('id', '') or '').strip()
            if not person_id:
                continue
            known_for = []
            for credit in (person.get('known_for') or [])[:3]:
                title = str(credit.get('title') or credit.get('name') or '').strip()
                if title:
                    known_for.append(title)
            results.append({
                'tmdb_id': person_id,
                'name': person.get('name', ''),
                'profile_url': _tmdb_image_url(person.get('profile_path'), 'w185'),
                'known_for_department': person.get('known_for_department', ''),
                'known_for': known_for,
                'popularity': float(person.get('popularity', 0) or 0),
            })
        return jsonify({
            'results': results,
            'page': data.get('page', page),
            'total_pages': 1 if used_split_fallback else min(int(data.get('total_pages', 1) or 1), 10),
            'total_results': len(results) if used_split_fallback else data.get('total_results', len(results)),
        })
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid TMDB API key — check Settings.'}), 401
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tmdb/match-apply', methods=['POST'])
def tmdb_match_apply():
    global _library_cache
    body = request.get_json(force=True, silent=True) or {}
    path = str(body.get('path', '') or '').strip()
    tmdb_id = str(body.get('tmdb_id', '') or '').strip()
    if not path:
        return jsonify({'error': 'path is required'}), 400
    if not tmdb_id:
        return jsonify({'error': 'tmdb_id is required'}), 400
    abs_path = os.path.abspath(path)
    if not _path_library_root(abs_path):
        return jsonify({'error': 'Path is outside the allowed movies directory'}), 403
    if not os.path.isfile(abs_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        store = _metadata_store()
        metadata = _fetch_tmdb_metadata_by_id(tmdb_id, store=store, refresh=True, match_source='manual_tmdb')
        if not metadata:
            movie = body.get('movie') or body
            metadata = _normalize_tmdb_metadata({**movie, 'tmdb_id': tmdb_id, 'match_source': 'manual_tmdb'})
        facts = _metadata_file_facts(abs_path)
        match = store.apply_tmdb_match(abs_path, metadata, facts=facts)
        canonical = _relational_canonical_for_path(abs_path, store=store)
        _resolve_identity_audit_path(abs_path)
        _library_cache.pop('items', None)
        return jsonify({
            'success': True,
            'match': match,
            'canonical_metadata': canonical,
            'catalog_generation': store.catalog.generation('media'),
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/metadata/refresh', methods=['POST'])
def refresh_file_metadata():
    global _library_cache
    body = request.get_json(force=True, silent=True) or {}
    path = str(body.get('path', '') or '').strip()
    if not path:
        return jsonify({'error': 'path is required'}), 400
    abs_path = os.path.abspath(path)
    if not _path_library_root(abs_path):
        return jsonify({'error': 'Path is outside the allowed movies directory'}), 403
    if not os.path.isfile(abs_path):
        return jsonify({'error': 'File not found'}), 404
    try:
        store = _metadata_store()
        _auto_sync_plex(force=bool(body.get('force_plex')))
        parsed_title, parsed_year = parse_movie_title(os.path.basename(abs_path))
        plex_data = dict(_plex_cache.get(_norm(abs_path), {}) or _plex_matched_by_fname.get(os.path.basename(abs_path).lower(), {}) or {})
        file_facts = {'path': abs_path, 'filename': os.path.basename(abs_path), 'parsed_title': parsed_title, 'parsed_year': parsed_year}
        tmdb_data = _tmdb_metadata_for_file(file_facts, plex_data=plex_data, store=store, refresh=True)
        file_record = store._read_json(store.files_file, {'files': {}}).get('files', {}).get(store._key(abs_path), {})
        canonical = _relational_canonical_for_path(abs_path, store=store)
        if not canonical:
            canonical = _build_canonical_metadata(
                file_facts,
                plex_data=plex_data,
                tmdb_data=tmdb_data,
                manual_match=store.get_manual_match(abs_path),
                display_provider=file_record.get('display_provider', ''),
                file_record=file_record,
            )
        store.update_file_record(abs_path, {
            **file_facts,
            'metadata_status': canonical.get('status', 'unmatched'),
            'metadata_source': canonical.get('source', ''),
            'metadata_accepted': bool(canonical.get('accepted')),
            'display_provider': file_record.get('display_provider', ''),
            'tmdb_id': canonical.get('tmdb_id', ''),
            'imdb_id': canonical.get('imdb_id', ''),
        })
        canonical = _relational_canonical_for_path(abs_path, store=store)
        _resolve_identity_audit_path(abs_path)
        _library_cache.pop('items', None)
        return jsonify({
            'success': True,
            'canonical_metadata': canonical,
            'tmdb_candidate': tmdb_data,
            'catalog_generation': store.catalog.generation('media'),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _metadata_override_context_for_path(path):
    abs_path = os.path.abspath(str(path or '').strip())
    if not path:
        raise ValueError('path is required')
    if not _path_library_root(abs_path):
        raise PermissionError('Path is outside the allowed movies directory')
    if not os.path.isfile(abs_path):
        raise FileNotFoundError('File not found')
    store = _metadata_store()
    snapshot = store.snapshot()
    facts = _metadata_file_facts(abs_path)
    key = store._key(abs_path)
    plex_data = dict(
        snapshot.get('plex_files', {}).get(key, {})
        or _plex_cache.get(_norm(abs_path), {})
        or _plex_matched_by_fname.get(facts['filename'].lower(), {})
        or {}
    )
    provider = _relational_canonical_for_path(abs_path, store=store, include_overrides=False)
    if not provider.get('accepted'):
        raise RuntimeError('Metadata correction requires an accepted Library movie')
    identity = _poster_identity_for_movie(facts, provider, plex_data)
    override = store.get_metadata_override(identity, snapshot=snapshot)
    effective = _relational_canonical_for_path(abs_path, store=store, include_overrides=True)
    return {
        'path': abs_path,
        'store': store,
        'provider': provider,
        'effective': effective,
        'identity': identity,
        'override': override,
    }


def _metadata_override_api_error(error):
    if isinstance(error, PermissionError):
        return jsonify({'error': str(error)}), 403
    if isinstance(error, FileNotFoundError):
        return jsonify({'error': str(error)}), 404
    if isinstance(error, RuntimeError):
        return jsonify({'error': str(error)}), 409
    return jsonify({'error': str(error)}), 400


@app.route('/api/metadata/override', methods=['GET', 'POST', 'DELETE'])
def metadata_override():
    global _library_cache
    body = request.get_json(silent=True) or {}
    path = request.args.get('path', '') if request.method == 'GET' else body.get('path', '')
    try:
        context = _metadata_override_context_for_path(path)
        if request.method == 'POST':
            title = str(body.get('title') or context['provider'].get('title') or '').strip()
            year = str(body.get('year') or '').strip()
            override = context['store'].save_metadata_override(
                context['identity'],
                title=title,
                year=year,
            )
            _resolve_identity_audit_path(context['path'])
            _library_cache = {}
            effective = _apply_metadata_override(
                context['provider'],
                context['identity'],
                store=context['store'],
            )
            return jsonify({
                'success': True,
                'identity': context['identity'],
                'provider': context['provider'],
                'effective': effective,
                'override': override,
            })
        if request.method == 'DELETE':
            context['store'].reset_metadata_override(context['identity'])
            _library_cache = {}
            return jsonify({
                'success': True,
                'identity': context['identity'],
                'provider': context['provider'],
                'effective': context['provider'],
                'override': {},
            })
        return jsonify({
            'identity': context['identity'],
            'provider': context['provider'],
            'effective': context['effective'],
            'override': context['override'],
        })
    except Exception as error:
        return _metadata_override_api_error(error)


_MAX_POSTER_BYTES = 10 * 1024 * 1024


def _poster_image_extension(data):
    if data.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return '.webp'
    return ''


def _download_poster_image(url):
    parsed = urllib.parse.urlparse(str(url or ''))
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('Poster URL must use HTTP or HTTPS')
    req = urllib.request.Request(url, headers={'Accept': 'image/*', 'User-Agent': 'CinemaParadiso/2.6'})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read(_MAX_POSTER_BYTES + 1)
    if len(data) > _MAX_POSTER_BYTES:
        raise ValueError('Poster image exceeds 10 MB')
    extension = _poster_image_extension(data)
    if not extension:
        raise ValueError('Poster must be a JPEG, PNG, or WebP image')
    return data, extension


def _poster_context_for_path(path):
    abs_path = os.path.abspath(str(path or '').strip())
    if not path:
        raise ValueError('path is required')
    if not _path_library_root(abs_path):
        raise PermissionError('Path is outside the allowed movies directory')
    if not os.path.isfile(abs_path):
        raise FileNotFoundError('File not found')
    store = _metadata_store()
    snapshot = store.snapshot()
    facts = _metadata_file_facts(abs_path)
    filename = facts['filename']
    plex_data = dict(_plex_cache.get(_norm(abs_path), {}) or _plex_matched_by_fname.get(filename.lower(), {}) or {})
    file_record = snapshot.get('files', {}).get(store._key(abs_path), {})
    display_provider = file_record.get('display_provider', '')
    if display_provider == 'plex':
        plex_data = {
            **plex_data,
            **dict(snapshot.get('plex_files', {}).get(store._key(abs_path), {}) or {}),
        }
    plex_thumb = plex_data.get('plex_thumb', '')
    if plex_thumb and _plex_url and _plex_token and not plex_data.get('plex_poster'):
        plex_data['plex_poster'] = f"{_plex_url}{plex_thumb}?X-Plex-Token={_plex_token}"
    tmdb_data = store.get_tmdb_metadata_from_snapshot(file_record.get('tmdb_id'), snapshot)
    base_canonical = _relational_canonical_for_path(abs_path, store=store, include_overrides=False)
    if not base_canonical.get('accepted'):
        raise RuntimeError('Poster editing requires an accepted Library movie')
    identity = _poster_identity_for_movie(facts, base_canonical, plex_data)
    canonical = _relational_canonical_for_path(abs_path, store=store, include_overrides=True)
    return {
        'path': abs_path,
        'store': store,
        'snapshot': snapshot,
        'facts': facts,
        'plex_data': plex_data,
        'tmdb_data': tmdb_data,
        'base_canonical': base_canonical,
        'canonical': canonical,
        'identity': identity,
    }


def _tmdb_poster_options(tmdb_id):
    tmdb_id = str(tmdb_id or '').strip()
    if not tmdb_id or not _tmdb_key:
        return []
    params = urllib.parse.urlencode({'api_key': _tmdb_key, 'include_image_language': 'en,null'})
    req = urllib.request.Request(
        f"https://api.themoviedb.org/3/movie/{urllib.parse.quote(tmdb_id)}/images?{params}",
        headers={'Accept': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        data = _json.loads(response.read().decode())
    return [
        {
            'source': 'tmdb',
            'url': _tmdb_image_url(poster.get('file_path'), 'w500'),
            'label': 'TMDB poster',
            'width': poster.get('width', 0),
            'height': poster.get('height', 0),
        }
        for poster in (data.get('posters') or [])[:24]
        if poster.get('file_path')
    ]


def _poster_options_result_for_path(path):
    context = _poster_context_for_path(path)
    canonical = context['canonical']
    plex_data = context['plex_data']
    options = []
    providers = {
        'tmdb': {'available': False, 'message': ''},
        'plex': {'available': False, 'message': ''},
    }
    tmdb_id = canonical.get('tmdb_id') or context['tmdb_data'].get('tmdb_id')
    if not tmdb_id and _tmdb_key:
        title = canonical.get('title', '')
        year = canonical.get('year', '')
        if title:
            try:
                candidates = _smart_match_tmdb_search(title, year)
                exact = next((
                    candidate for candidate in candidates
                    if _same_public_identity(
                        title,
                        year,
                        candidate.get('title') or candidate.get('name', ''),
                        _year_from_movie(candidate),
                    )
                ), None)
                if exact:
                    tmdb_id = str(exact.get('id', '') or '').strip()
                else:
                    providers['tmdb']['message'] = 'No exact TMDB identity matched this movie title and year.'
            except Exception as error:
                providers['tmdb']['message'] = f'TMDB poster lookup failed: {error}'
        else:
            providers['tmdb']['message'] = 'Accepted movie metadata has no title for TMDB lookup.'
    elif not tmdb_id and not _tmdb_key:
        providers['tmdb']['message'] = 'TMDB is not configured.'
    if tmdb_id:
        try:
            tmdb_options = _tmdb_poster_options(tmdb_id)
            options.extend(tmdb_options)
            providers['tmdb']['available'] = bool(tmdb_options)
            if not tmdb_options:
                providers['tmdb']['message'] = 'TMDB has no poster images for this movie.'
        except Exception as error:
            current_tmdb = context['tmdb_data'].get('poster_url', '')
            if current_tmdb:
                options.append({'source': 'tmdb', 'url': current_tmdb, 'label': 'Current TMDB poster'})
                providers['tmdb']['available'] = True
                providers['tmdb']['message'] = f'TMDB image list failed; showing the saved TMDB poster: {error}'
            else:
                providers['tmdb']['message'] = f'TMDB poster lookup failed: {error}'
    plex_poster = plex_data.get('plex_poster', '')
    if plex_poster:
        options.append({'source': 'plex', 'url': plex_poster, 'label': 'Plex poster'})
        providers['plex']['available'] = True
    else:
        providers['plex']['message'] = 'No Plex poster is available for this movie.'
    unique = []
    seen = set()
    for option in options:
        url = option.get('url', '')
        if url and url not in seen:
            unique.append(option)
            seen.add(url)
    return {
        'options': unique,
        'identity': context['identity'],
        'providers': providers,
        'default_poster_url': context['base_canonical'].get('poster_url', ''),
    }


def _poster_options_for_path(path):
    result = _poster_options_result_for_path(path)
    return result['options'], result['identity']


def _poster_api_error(error):
    if isinstance(error, PermissionError):
        return jsonify({'error': str(error)}), 403
    if isinstance(error, FileNotFoundError):
        return jsonify({'error': str(error)}), 404
    if isinstance(error, RuntimeError):
        return jsonify({'error': str(error)}), 409
    return jsonify({'error': str(error)}), 400


def _ingest_saved_custom_poster(path, override):
    try:
        candidate = _catalog_repository().owned_movie(path=path)
        movie_key = (candidate.get('relational_canonical') or {}).get('movie_key', '') if candidate else ''
        filename = Path(urllib.parse.unquote(urllib.parse.urlsplit(override.get('poster_url', '')).path)).name
        source_path = (_metadata_store().posters_dir / filename).resolve()
        if movie_key and source_path.is_file():
            _media_asset_service().ingest_custom_file(
                movie_key, source_path, source_name=override.get('id') or filename
            )
    except (OSError, ValueError, MediaAssetError):
        # The legacy custom route remains a safe fallback until the resumable migration retries it.
        return None
    return True


@app.route('/api/library/posters')
def library_poster_options():
    try:
        result = _poster_options_result_for_path(request.args.get('path', ''))
        store = _metadata_store()
        return jsonify({
            **result,
            'override': store.get_poster_override(result['identity']),
        })
    except Exception as error:
        return _poster_api_error(error)


@app.route('/api/library/posters/select', methods=['POST'])
def library_poster_select():
    global _library_cache
    body = request.get_json(silent=True) or {}
    try:
        options, identity = _poster_options_for_path(body.get('path', ''))
        source = str(body.get('source', '') or '')
        url = str(body.get('url', '') or '')
        selected = next((option for option in options if option.get('source') == source and option.get('url') == url), None)
        if not selected:
            raise ValueError('Poster option is not available for this Library movie')
        image_bytes, extension = _download_poster_image(url)
        override = _metadata_store().save_poster_override(identity, source, image_bytes, extension)
        _ingest_saved_custom_poster(body.get('path', ''), override)
        _library_cache = {}
        return jsonify({'success': True, 'override': override})
    except Exception as error:
        return _poster_api_error(error)


@app.route('/api/library/posters/upload', methods=['POST'])
def library_poster_upload():
    global _library_cache
    try:
        context = _poster_context_for_path(request.form.get('path', ''))
        upload = request.files.get('poster')
        if upload is None:
            raise ValueError('poster file is required')
        image_bytes = upload.stream.read(_MAX_POSTER_BYTES + 1)
        if len(image_bytes) > _MAX_POSTER_BYTES:
            raise ValueError('Poster image exceeds 10 MB')
        extension = _poster_image_extension(image_bytes)
        if not extension:
            raise ValueError('Poster must be a JPEG, PNG, or WebP image')
        override = context['store'].save_poster_override(context['identity'], 'local', image_bytes, extension)
        _ingest_saved_custom_poster(request.form.get('path', ''), override)
        _library_cache = {}
        return jsonify({'success': True, 'override': override})
    except Exception as error:
        return _poster_api_error(error)


@app.route('/api/library/posters/reset', methods=['POST'])
def library_poster_reset():
    global _library_cache
    body = request.get_json(silent=True) or {}
    try:
        context = _poster_context_for_path(body.get('path', ''))
        movie_key = (context.get('base_canonical') or {}).get('movie_key', '')
        context['store'].reset_poster_override(context['identity'])
        if movie_key:
            _media_asset_service().reset_custom_poster(movie_key)
        _library_cache = {}
        return jsonify({
            'success': True,
            'override': {},
            'poster_url': context['base_canonical'].get('poster_url', ''),
        })
    except Exception as error:
        return _poster_api_error(error)


@app.route('/api/library/posters/image/<path:filename>')
def library_poster_image(filename):
    if Path(filename).name != filename:
        return jsonify({'error': 'Invalid poster filename'}), 400
    return send_from_directory(_metadata_store().posters_dir, filename)


@app.route('/api/assets/<checksum>')
def local_media_asset(checksum):
    checksum = str(checksum or '').lower()
    if not re.fullmatch(r'[a-f0-9]{64}', checksum):
        return jsonify({'error': 'Invalid asset checksum'}), 400
    service = _media_asset_service()
    asset = service.lookup(checksum=checksum)
    if not asset:
        return jsonify({'error': 'Artwork asset was not found'}), 404
    path = Path(asset['local_path']).resolve()
    try:
        path.relative_to(service.assets_root)
    except ValueError:
        return jsonify({'error': 'Artwork path is outside managed storage'}), 409
    if not path.is_file():
        return jsonify({'error': 'Artwork file is unavailable'}), 404
    response = send_file(path, mimetype=asset['mime_type'], conditional=True, max_age=31536000)
    response.set_etag(checksum)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.route('/api/artwork/backfill', methods=['GET', 'POST'])
def artwork_backfill():
    service = _media_asset_service()
    if request.method == 'GET':
        return jsonify(service.status())
    body = request.get_json(silent=True) or {}
    if body.get('queue', True):
        service.migrate_custom_posters(_metadata_store().posters_dir)
        service.queue_owned_artwork()
    if body.get('background', True):
        threading.Thread(
            target=service.run_backfill,
            kwargs={
                'limit': min(max(int(body.get('limit', 200) or 200), 1), 2000),
                'workers': min(max(int(body.get('workers', 4) or 4), 1), 8),
            },
            name='cinema-artwork-backfill', daemon=True,
        ).start()
        return jsonify({**service.status(), 'started': True}), 202
    return jsonify(service.run_backfill(
        limit=min(max(int(body.get('limit', 200) or 200), 1), 2000),
        workers=min(max(int(body.get('workers', 4) or 4), 1), 8),
    ))


@app.route('/api/artwork/cleanup', methods=['POST'])
def artwork_cleanup():
    body = request.get_json(silent=True) or {}
    return jsonify(_media_asset_service().cleanup_temporary(
        grace_seconds=max(int(body.get('grace_seconds', 7 * 86400) or 0), 0)
    ))


def _run_startup_artwork_backfill():
    service = _media_asset_service()
    service.migrate_custom_posters(_metadata_store().posters_dir)
    service.queue_owned_artwork()
    while True:
        state = service.run_backfill(limit=200, workers=4)
        remaining = int(state.get('counts', {}).get('queued', 0))
        retryable = int(state.get('counts', {}).get('failed', 0))
        if not remaining and not retryable:
            return
        if not remaining and retryable and state.get('failed', 0) == 0:
            return
        time.sleep(2)


def _normalize_tmdb_person(person, include_character=False):
    name = person.get('name', '')
    if not name:
        return None
    result = {
        'id': str(person.get('id', '') or ''),
        'name': name,
        'profile_url': _tmdb_image_url(person.get('profile_path')),
    }
    if include_character:
        result['character'] = person.get('character', '')
    return result


def _normalize_tmdb_person_details_payload(data):
    return {
        'id': str(data.get('id', '') or ''),
        'name': data.get('name', '') or '',
        'profile_url': _tmdb_image_url(data.get('profile_path'), 'w342'),
        'biography': data.get('biography', '') or '',
        'birthday': data.get('birthday', '') or '',
        'deathday': data.get('deathday', '') or '',
        'place_of_birth': data.get('place_of_birth', '') or '',
        'known_for_department': data.get('known_for_department', '') or '',
        'homepage': data.get('homepage', '') or '',
    }


def _normalize_tmdb_details_payload(data):
    directors = []
    for person in data.get('credits', {}).get('crew', []) or []:
        if person.get('job') != 'Director':
            continue
        normalized = _normalize_tmdb_person(person)
        if normalized:
            directors.append(normalized)

    cast = []
    for person in (data.get('credits', {}).get('cast', []) or [])[:7]:
        normalized = _normalize_tmdb_person(person, include_character=True)
        if normalized:
            cast.append(normalized)

    collection = {}
    raw_collection = data.get('belongs_to_collection') or {}
    if raw_collection.get('id') and raw_collection.get('name'):
        collection = {
            'id': str(raw_collection.get('id')),
            'name': raw_collection.get('name', ''),
            'poster_url': _tmdb_image_url(raw_collection.get('poster_path')),
            'backdrop_url': _tmdb_image_url(raw_collection.get('backdrop_path'), 'w780'),
        }

    trailer_url = ''
    videos = data.get('videos', {}).get('results', []) or []
    official_trailers = [
        v for v in videos
        if v.get('site') == 'YouTube'
        and v.get('type') == 'Trailer'
        and v.get('key')
        and v.get('official', False)
    ]
    trailer = official_trailers[0] if official_trailers else next(
        (v for v in videos if v.get('site') == 'YouTube' and v.get('type') == 'Trailer' and v.get('key')),
        None
    )
    if trailer:
        trailer_url = f"https://www.youtube.com/watch?v={trailer.get('key')}"

    return {
        'director': directors[0] if directors else {},
        'directors': directors,
        'cast': cast,
        'collection': collection,
        'trailer_url': trailer_url,
        'runtime': data.get('runtime'),
        'tagline': data.get('tagline', ''),
        'release_date': data.get('release_date', '') or '',
        'release_years': _tmdb_release_year_values(data),
        'release_years_checked_at': time.time() if 'release_dates' in data else 0,
    }


def _normalize_tmdb_movie_summary(movie, fallback_title='', fallback_year=''):
    normalized = _normalize_tmdb_metadata({
        **(movie or {}),
        'title': movie.get('title') or movie.get('name') or fallback_title,
        'year': _year_from_movie(movie, fallback_year),
    })
    normalized['genres'] = normalized.get('genres', [])[:3]
    return normalized


def _fetch_tmdb_metadata_by_id(tmdb_id, store=None, refresh=False, match_source=''):
    tmdb_id = str(tmdb_id or '').strip()
    if not tmdb_id:
        return {}
    store = store or _metadata_store()
    cached = store.get_tmdb_metadata(tmdb_id)
    if cached and not refresh and (_tmdb_metadata_contract_complete(cached) or not _tmdb_key):
        return {**cached, **({'match_source': match_source} if match_source else {})}
    if not _tmdb_key:
        return cached or {}
    try:
        safe_id = urllib.parse.quote(tmdb_id)
        url = (f"https://api.themoviedb.org/3/movie/{safe_id}"
               f"?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US"
               f"&append_to_response=credits,videos,release_dates")
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = _json.loads(resp.read().decode())
        metadata = _normalize_tmdb_metadata(raw)
        metadata.update(_normalize_tmdb_details_payload(raw))
        metadata['tmdb_id'] = tmdb_id
        if match_source:
            metadata['match_source'] = match_source
        return store.save_tmdb_metadata(metadata)
    except Exception:
        return cached or {}


def _fetch_tmdb_metadata_by_imdb(imdb_id, store=None, match_source=''):
    imdb_id = str(imdb_id or '').strip()
    if not imdb_id or not _tmdb_key:
        return {}
    store = store or _metadata_store()
    try:
        safe_id = urllib.parse.quote(imdb_id)
        url = (f"https://api.themoviedb.org/3/find/{safe_id}"
               f"?api_key={urllib.parse.quote(_tmdb_key)}&external_source=imdb_id&language=en-US")
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = _json.loads(resp.read().decode())
        movie = next(iter(raw.get('movie_results') or []), {})
        tmdb_id = str(movie.get('id') or '')
        if not tmdb_id:
            return {}
        metadata = _normalize_tmdb_metadata(movie)
        metadata.update(_normalize_tmdb_details_payload(movie))
        metadata.update({
            'tmdb_id': tmdb_id,
            'imdb_id': imdb_id,
        })
        if match_source:
            metadata['match_source'] = match_source
        return store.save_tmdb_metadata(metadata)
    except Exception:
        return {}


def _tmdb_card_projection_is_complete(metadata):
    metadata = metadata or {}
    return bool(
        metadata.get('tmdb_id')
        and metadata.get('title')
        and (
            metadata.get('genres')
            or metadata.get('tmdb_rating')
            or metadata.get('plot')
            or metadata.get('backdrop_url')
        )
    )


def _tmdb_metadata_contract_complete(metadata):
    metadata = metadata or {}
    return bool(
        _tmdb_card_projection_is_complete(metadata)
        and 'cast' in metadata
        and 'directors' in metadata
    )


def _tmdb_card_projection_by_id(tmdb_id, store=None):
    tmdb_id = str(tmdb_id or '').strip()
    if not tmdb_id:
        return {}
    store = store or _metadata_store()
    cached = store.get_tmdb_metadata(tmdb_id) or {}
    return cached if _tmdb_card_projection_is_complete(cached) else {}


def _plex_thumb_from_poster_url(poster_url):
    path = urllib.parse.urlparse(str(poster_url or '')).path
    if not re.fullmatch(r'/library/metadata/[^/]+/thumb/[^/]+', path):
        return ''
    return path


def _plex_card_projection_by_poster_url(poster_url, store=None):
    store = store or _metadata_store()
    plex_metadata = store.get_plex_metadata_by_poster_url(poster_url) or {}
    if not plex_metadata:
        return {}
    tmdb_id = str(plex_metadata.get('tmdb_id', '') or '').strip()
    if tmdb_id:
        return _tmdb_card_projection_by_id(tmdb_id, store=store)
    directors = list(plex_metadata.get('plex_directors') or [])
    return {
        'tmdb_id': '',
        'imdb_id': str(plex_metadata.get('imdb_id', '') or ''),
        'title': plex_metadata.get('plex_title', ''),
        'year': str(plex_metadata.get('plex_year', '') or ''),
        'poster_url': plex_metadata.get('plex_poster', '') or str(poster_url or ''),
        'genres': list(plex_metadata.get('plex_genres') or []),
        'tmdb_rating': str(plex_metadata.get('plex_rating', '') or ''),
        'tmdb_vote_count': 0,
        'plot': plex_metadata.get('plex_summary', ''),
        'language': plex_metadata.get('plex_language', ''),
        'country': plex_metadata.get('plex_country', ''),
        'country_flag': plex_metadata.get('plex_country_flag', ''),
        'directors': directors,
        'director': directors[0] if directors else {},
        'cast': list(plex_metadata.get('plex_cast') or []),
        'collection': {},
        'trailer_url': '',
        'match_source': 'plex_cache',
    }


def _movie_card_projection(movie, store=None):
    movie = movie or {}
    tmdb_id = str(movie.get('tmdb_id', '') or '').strip()
    if tmdb_id:
        return _tmdb_card_projection_by_id(tmdb_id, store=store)
    return _plex_card_projection_by_poster_url(movie.get('poster_url', ''), store=store)


def _search_tmdb_library_candidate(title, year='', store=None, queries=None):
    title = str(title or '').strip()
    year = str(year or '').strip()
    if not title or not _tmdb_key:
        return {}
    try:
        identity_queries = queries or [{'title': title, 'year': year, 'source': 'filename'}]
        decision = evaluate_identity(identity_queries, _identity_tmdb_candidates(identity_queries))
        selected = decision.get('candidate', {})
        if not selected:
            return {}
        match_source = 'auto_tmdb' if decision.get('outcome') == 'accepted' else 'candidate_tmdb'
        selected = {**selected, 'match_source': match_source}
        if match_source == 'auto_tmdb':
            return _fetch_tmdb_metadata_by_id(
                selected.get('tmdb_id'),
                store=store,
                match_source=match_source,
            ) or selected
        return selected
    except Exception:
        return {}


def _tmdb_metadata_for_file(file_facts, plex_data=None, store=None, refresh=False, snapshot=None):
    store = store or _metadata_store()
    path = file_facts.get('path', '')
    manual_match = store.get_manual_match_from_snapshot(path, snapshot) if snapshot is not None else store.get_manual_match(path)
    if manual_match.get('provider') == 'tmdb':
        tmdb_id = str(manual_match.get('tmdb_id', '') or '').strip()
        if snapshot is not None:
            cached = store.get_tmdb_metadata_from_snapshot(tmdb_id, snapshot) or {}
        else:
            cached = store.get_tmdb_metadata(tmdb_id) or {}
        if cached:
            return cached
        if refresh:
            fetched = _fetch_tmdb_metadata_by_id(tmdb_id, store=store, refresh=True, match_source='manual_tmdb')
            if fetched:
                return fetched
        fallback_title = str(manual_match.get('title') or file_facts.get('parsed_title') or '').strip()
        fallback_year = str(manual_match.get('year') or file_facts.get('parsed_year') or '').strip()
        if tmdb_id and fallback_title:
            return {
                'tmdb_id': tmdb_id,
                'imdb_id': str(manual_match.get('imdb_id', '') or ''),
                'title': fallback_title.title(),
                'year': fallback_year,
                'poster_url': manual_match.get('poster_url', ''),
                'genres': [],
                'plot': '',
                'summary': '',
                'tmdb_rating': '',
                'tmdb_vote_count': 0,
                'match_source': 'manual_tmdb',
            }
        return {}
    plex_tmdb_id = str((plex_data or {}).get('tmdb_id', '') or '').strip()
    if plex_tmdb_id:
        cached = (
            store.get_tmdb_metadata_from_snapshot(plex_tmdb_id, snapshot)
            if snapshot is not None else store.get_tmdb_metadata(plex_tmdb_id)
        ) or {}
        if cached:
            return {**cached, 'match_source': 'plex_tmdb_id'}
        if refresh:
            return _fetch_tmdb_metadata_by_id(plex_tmdb_id, store=store, refresh=True, match_source='plex_tmdb_id')
        return {}
    file_record = ((snapshot or {}).get('files', {}) if snapshot is not None
                   else store._read_json(store.files_file, {'files': {}}).get('files', {})).get(store._key(path), {})
    accepted_tmdb_id = str(file_record.get('tmdb_id', '') or '').strip()
    if accepted_tmdb_id:
        cached = (
            store.get_tmdb_metadata_from_snapshot(accepted_tmdb_id, snapshot)
            if snapshot is not None else store.get_tmdb_metadata(accepted_tmdb_id)
        ) or {}
        if cached:
            return cached
        if refresh:
            return _fetch_tmdb_metadata_by_id(
                accepted_tmdb_id,
                store=store,
                refresh=True,
                match_source='saved_tmdb_id',
            )
        return {}
    if refresh:
        queries = _identity_queries(path, file_facts, plex_data or {})
        return _search_tmdb_library_candidate(
            file_facts.get('parsed_title', ''),
            file_facts.get('parsed_year', ''),
            store=store,
            queries=queries,
        )
    return {}


def _metadata_provider_status():
    return {
        'tmdb': {
            'available': bool(_tmdb_key),
            'label': 'TMDB',
        },
        'plex': {
            'available': bool(_plex_url and _plex_token),
            'label': 'Plex snapshot',
        },
        'filename': {
            'available': True,
            'label': 'Filename only',
        },
    }


def _active_metadata_provider(store=None):
    store = store or _metadata_store()
    saved = store.get_authority_state()
    active = saved.get('active_provider', '')
    if active in {'tmdb', 'plex', 'filename'}:
        return active
    if _plex_url and _plex_token:
        return 'plex'
    if _tmdb_key:
        return 'tmdb'
    return 'filename'


def _metadata_migration_paths():
    return [full_path for _, _, _, full_path in _iter_video_files()]


def _metadata_file_facts(path):
    filename = os.path.basename(path)
    parsed_title, parsed_year = parse_movie_title(filename)
    try:
        stat_result = os.stat(path)
        size = stat_result.st_size
        added_time = stat_result.st_ctime
        modified_time = stat_result.st_mtime
    except OSError:
        size = 0
        added_time = 0
        modified_time = 0
    return {
        'path': path,
        'filename': filename,
        'library_root': _path_library_root(path) or '',
        'parsed_title': parsed_title,
        'parsed_year': parsed_year,
        'resolution': get_resolution_from_file(path),
        'rip_source': get_rip_source(filename),
        'size': size,
        'added_time': added_time,
        'modified_time': modified_time,
        'file_facts_version': FILE_FACTS_VERSION,
    }


def _file_copy_is_stable(file_facts, previous=None, now=None):
    previous = previous or {}
    now = time.time() if now is None else float(now)
    size = int(file_facts.get('size') or 0)
    modified_time = float(file_facts.get('modified_time') or 0)
    if modified_time and now - modified_time >= _FILE_STABILITY_SECONDS:
        return True
    same_observation = (
        int(previous.get('observed_size') or -1) == size
        and float(previous.get('observed_modified_time') or -1) == modified_time
    )
    observed_at = float(previous.get('observed_at') or 0)
    return bool(same_observation and observed_at and now - observed_at >= _FILE_STABILITY_SECONDS)


def _reconcile_library_path(path, provider, store=None, previous=None):
    store = store or _metadata_store()
    previous = previous or {}
    facts = _metadata_file_facts(path)
    if not _file_copy_is_stable(facts, previous):
        pending_patch = {
            **facts,
            'ingest_status': 'pending',
            'observed_size': facts.get('size', 0),
            'observed_modified_time': facts.get('modified_time', 0),
            'observed_at': time.time(),
        }
        if not resolve_authoritative_identity(previous).get('accepted'):
            pending_patch.update({
                'metadata_status': 'pending',
                'metadata_accepted': False,
            })
        store.update_file_record(path, pending_patch)
        return 'pending'

    if provider == 'filename':
        store.update_file_record(path, {
            **facts,
            'display_provider': 'filename',
            'metadata_status': 'unmatched',
            'metadata_source': 'filename',
            'metadata_accepted': False,
            'ingest_status': 'stable',
            'identity_decision_version': IDENTITY_DECISION_VERSION,
            'observed_size': facts.get('size', 0),
            'observed_modified_time': facts.get('modified_time', 0),
            'observed_at': time.time(),
        })
        return 'review'

    outcome = _migrate_metadata_path(
        path,
        provider,
        store=store,
        revalidate_accepted=bool(previous.get('_revalidate_identity')),
    )
    patch = {
        **facts,
        'ingest_status': 'stable',
        'observed_size': facts.get('size', 0),
        'observed_modified_time': facts.get('modified_time', 0),
        'observed_at': time.time(),
    }
    if outcome == 'review':
        post_migration = store.snapshot().get('files', {}).get(store._key(path), {})
        post_status = str(post_migration.get('identity_status') or '')
        if post_status == 'conflict':
            patch.update({
                'identity_status': 'conflict',
                'metadata_status': 'conflict',
                'metadata_accepted': False,
                'identity_decision_version': IDENTITY_DECISION_VERSION,
            })
        elif post_status == 'unmatched':
            patch.update({
                'metadata_status': 'unmatched',
                'metadata_accepted': False,
                'identity_decision_version': IDENTITY_DECISION_VERSION,
            })
        else:
            patch.update({
                'identity_status': 'review',
                'metadata_status': 'needs_review',
                'metadata_accepted': False,
                'identity_decision_version': IDENTITY_DECISION_VERSION,
            })
    elif outcome == 'failed':
        patch.update({
            'metadata_status': 'unmatched',
            'metadata_accepted': False,
            'identity_decision_version': IDENTITY_DECISION_VERSION,
        })
    store.update_file_record(path, patch)
    return outcome


def _library_inventory_bootstrap_cutoff(store):
    try:
        return store.files_file.stat().st_mtime
    except OSError:
        return 0


def _record_has_unresolved_identity(record):
    record = record or {}
    if record.get('metadata_accepted') or record.get('metadata_status') == 'accepted':
        return False
    return bool(
        record.get('identity_status') in {'unmatched', 'review', 'conflict'}
        or record.get('metadata_status') in {'unmatched', 'needs_review', 'conflict'}
    )


def _record_needs_metadata_enrichment(record, path_key, snapshot):
    record = record or {}
    if not (record.get('metadata_accepted') or record.get('metadata_status') == 'accepted'):
        return False
    selected_provider = str(record.get('display_provider') or '').strip()
    tmdb_metadata = (snapshot or {}).get('tmdb_movies', {}).get(str(record.get('tmdb_id') or ''), {})
    plex_metadata = (snapshot or {}).get('plex_files', {}).get(path_key, {})
    if selected_provider == 'tmdb':
        return not _tmdb_metadata_contract_complete(tmdb_metadata)
    if selected_provider == 'plex':
        return not bool(plex_metadata.get('plex_title'))
    provider_metadata = _canonical_provider_metadata(selected_provider, tmdb_metadata, plex_metadata)
    resolved = resolve_authoritative_identity(record, provider_metadata=provider_metadata)
    return resolved.get('enrichment_state') != 'complete'


def _identity_evidence_fingerprint(path, file_facts=None, plex_data=None):
    file_facts = file_facts or _metadata_file_facts(path)
    plex_data = plex_data or {}
    payload = {
        'queries': [
            {
                'source': query.get('source', ''),
                'title': _norm_movie_title(query.get('title', '')),
                'year': str(query.get('year', '') or ''),
            }
            for query in _identity_queries(path, file_facts, plex_data)
        ],
        'plex': {
            'tmdb_id': str(plex_data.get('tmdb_id', '') or ''),
            'imdb_id': str(plex_data.get('imdb_id', '') or '').lower(),
            'plex_guid': str(plex_data.get('plex_guid') or plex_data.get('guid') or '').lower(),
            'rating_key': str(plex_data.get('rating_key', '') or ''),
        },
    }
    encoded = _json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _identity_is_manually_protected(record):
    record = dict(record or {})
    source = str(record.get('identity_source') or record.get('metadata_source') or '').lower()
    return bool(
        record.get('manual_lock')
        or record.get('manual_locked')
        or infer_decision_origin(record) == DECISION_ORIGIN_USER_MANUAL
        or source.startswith('manual_')
    )


def _stable_identity_evidence_conflicts(record, plex_data):
    record = dict(record or {})
    plex_data = dict(plex_data or {})
    for key in ('tmdb_id', 'imdb_id', 'plex_guid'):
        accepted_id = str(record.get(key) or '').strip().lower()
        provider_value = (
            plex_data.get('plex_guid') or plex_data.get('guid')
            if key == 'plex_guid'
            else plex_data.get(key)
        )
        provider_id = str(provider_value or '').strip().lower()
        if accepted_id and provider_id and accepted_id != provider_id:
            return True
    return False


def _accepted_identity_evidence_changed(path, record, file_facts, plex_data):
    record = dict(record or {})
    file_facts = dict(file_facts or {})
    if _identity_is_manually_protected(record):
        return False
    if record.get('identity_evidence_changed'):
        return True
    if _stable_identity_evidence_conflicts(record, plex_data):
        return True
    parsed_changed = any(
        str(record.get(key) or '') != str(file_facts.get(key) or '')
        for key in ('filename', 'parsed_title', 'parsed_year')
        if record.get(key)
    )
    if parsed_changed:
        return True
    previous_fingerprint = str(record.get('identity_evidence_fingerprint') or '')
    if not previous_fingerprint:
        return False
    return previous_fingerprint != _identity_evidence_fingerprint(path, file_facts, plex_data)


def _record_needs_identity_decision_refresh(record, current_fingerprint=''):
    record = record or {}
    if not _record_has_unresolved_identity(record):
        return False
    if int(record.get('identity_decision_version') or 0) >= IDENTITY_DECISION_VERSION:
        previous_fingerprint = str(record.get('identity_evidence_fingerprint') or '')
        if current_fingerprint and previous_fingerprint and previous_fingerprint != current_fingerprint:
            return True
        return False
    return True


def _reconcile_library_files(force_unresolved=False):
    global _library_cache
    with _library_reconcile_run_lock:
        store = _metadata_store()
        snapshot = store.snapshot()
        records = snapshot.get('files', {})
        inventory_exists = store.library_inventory_file.exists()
        previous_inventory = store.get_library_inventory()
        bootstrap_cutoff = _library_inventory_bootstrap_cutoff(store) if not inventory_exists else 0
        provider = _active_metadata_provider(store)
        candidates = []
        current_inventory = {}
        file_fact_updates = {}
        for _, _, file, path in _iter_video_files():
            try:
                stat_result = os.stat(path)
            except OSError:
                continue
            key = store._key(path)
            fingerprint = {
                'path': path,
                'size': int(stat_result.st_size),
                'modified_time': float(stat_result.st_mtime),
            }
            current_inventory[key] = fingerprint
            record = records.get(key, {})
            if record.get('metadata_accepted') or record.get('metadata_status') == 'accepted':
                facts_changed = (
                    int(record.get('file_facts_version') or 0) < FILE_FACTS_VERSION
                    or
                    int(record.get('size') or -1) != fingerprint['size']
                    or float(record.get('modified_time') or -1) != fingerprint['modified_time']
                    or record.get('filename') != file
                )
                facts = records[key]
                if facts_changed:
                    facts = _metadata_file_facts(path)
                    file_fact_updates[path] = facts
                    records[key] = {**record, **facts}
                plex_data = dict(
                    snapshot.get('plex_files', {}).get(key, {})
                    or _plex_cache.get(_norm(path), {})
                    or _plex_matched_by_fname.get(str(file).lower(), {})
                    or {}
                )
                if provider in {'tmdb', 'plex'} and _accepted_identity_evidence_changed(
                    path,
                    record,
                    facts,
                    plex_data,
                ):
                    candidates.append((path, {**record, '_revalidate_identity': True}))
                    continue
                if provider in {'tmdb', 'plex'} and _record_needs_metadata_enrichment(records[key], key, snapshot):
                    candidates.append((path, records[key]))
                continue
            if force_unresolved and (
                record.get('identity_status') in {'unmatched', 'review', 'conflict'}
                or record.get('metadata_status') in {'unmatched', 'needs_review', 'conflict'}
            ):
                candidates.append((path, record))
                continue
            current_identity_fingerprint = ''
            if _record_has_unresolved_identity(record):
                file_facts = _metadata_file_facts(path)
                filename = file_facts.get('filename', file)
                plex_data = dict(
                    snapshot.get('plex_files', {}).get(key, {})
                    or _plex_cache.get(_norm(path), {})
                    or _plex_matched_by_fname.get(str(filename).lower(), {})
                    or {}
                )
                current_identity_fingerprint = _identity_evidence_fingerprint(path, file_facts, plex_data)
            if _record_needs_identity_decision_refresh(record, current_identity_fingerprint):
                candidates.append((path, record))
                continue
            if not record:
                candidates.append((path, record))
                continue
            if record.get('metadata_status') == 'pending':
                candidates.append((path, record))
                continue
            if not inventory_exists:
                record_changed = (
                    record
                    and (
                        int(record.get('size') or -1) != fingerprint['size']
                        or float(record.get('modified_time') or -1) != fingerprint['modified_time']
                    )
                )
                try:
                    newly_added = os.path.getctime(path) > bootstrap_cutoff
                except OSError:
                    newly_added = False
                if record_changed or (not record and newly_added):
                    candidates.append((path, record))
                continue
            previous = previous_inventory.get(key, {})
            changed = (
                not previous
                or int(previous.get('size') or -1) != fingerprint['size']
                or float(previous.get('modified_time') or -1) != fingerprint['modified_time']
            )
            if changed:
                candidates.append((path, record))

        store.update_file_records_bulk(file_fact_updates)
        removed = 0
        configured_roots = [root for root in get_movies_dirs() if root]
        if configured_roots and all(os.path.isdir(root) for root in configured_roots):
            removed = store.prune_missing_path_records(current_inventory.keys())
        store.save_library_inventory(current_inventory)

        if provider == 'plex' and candidates:
            _plex_rescan()
            time.sleep(1)
            _auto_sync_plex(force=True)

        result = {
            'checked': 0,
            'matched': 0,
            'review': 0,
            'pending': 0,
            'failed': 0,
            'removed': removed,
            'facts_refreshed': len(file_fact_updates),
            'provider': provider,
        }
        for path, previous in candidates:
            result['checked'] += 1
            try:
                outcome = _reconcile_library_path(path, provider, store=store, previous=previous)
            except Exception:
                outcome = 'failed'
            key = outcome if outcome in result else 'failed'
            result[key] += 1
        if result['checked'] or result['removed']:
            _library_cache = {}
        return result

def _library_reconcile_status():
    with _library_reconcile_lock:
        return {
            **_library_reconcile_state,
            'catalog_generation': _catalog_repository().generation('media'),
        }


def _run_library_reconcile_loop():
    global _library_reconcile_state
    while True:
        result = _reconcile_library_files()
        with _library_reconcile_lock:
            _library_reconcile_state = {
                **result,
                'status': 'running' if result.get('pending') else 'completed',
                'updated_at': time.time(),
            }
        if not result.get('pending'):
            _mark_library_reconcile_complete()
            return
        time.sleep(_FILE_STABILITY_SECONDS)


def _library_root_signature():
    roots = []
    for configured in get_movies_dirs():
        path = os.path.abspath(str(configured or ''))
        try:
            stat_result = os.stat(path)
            roots.append({
                'path': os.path.normcase(os.path.normpath(path)),
                'exists': True,
                'modified_ns': int(stat_result.st_mtime_ns),
            })
        except OSError:
            roots.append({
                'path': os.path.normcase(os.path.normpath(path)),
                'exists': False,
                'modified_ns': 0,
            })
    payload = _json.dumps(roots, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _startup_reconcile_decision():
    started = time.perf_counter()
    repository = _catalog_repository()
    generation_started = time.perf_counter()
    media_generation = repository.generation('media')
    _startup_metrics['generation_check_ms'] = round((time.perf_counter() - generation_started) * 1000, 3)
    store = _metadata_store()
    current_signature = _library_root_signature()
    previous_signature = repository.catalog_meta('last_library_root_signature')
    previous_generation = repository.catalog_meta('last_library_reconcile_generation')
    inventory_exists = store.library_inventory_file.exists() or repository.has_document(
        store._document_name(store.library_inventory_file)
    )
    if not inventory_exists:
        decision, reason = 'run', 'missing_inventory'
    elif previous_signature and previous_signature != current_signature:
        decision, reason = 'run', 'library_root_changed'
    elif previous_generation and int(previous_generation or 0) > media_generation:
        decision, reason = 'run', 'invalid_reconcile_generation'
    else:
        decision = 'skip'
        reason = 'current_inventory' if previous_signature else 'bootstrapped_existing_inventory'
        if not previous_signature:
            repository.set_operational_meta('last_library_root_signature', current_signature)
            repository.set_operational_meta('last_library_reconcile_generation', media_generation)
    _startup_metrics['reconcile_decision_ms'] = round((time.perf_counter() - started) * 1000, 3)
    _startup_metrics['reconcile_decision'] = decision
    _startup_metrics['reconcile_reason'] = reason
    return {'run': decision == 'run', 'reason': reason}


def _mark_library_reconcile_complete():
    repository = _catalog_repository()
    repository.set_operational_meta('last_library_root_signature', _library_root_signature())
    repository.set_operational_meta('last_library_reconcile_generation', repository.generation('media'))


def _start_library_reconcile(force=False):
    global _library_reconcile_thread, _library_reconcile_state
    with _library_reconcile_lock:
        if _library_reconcile_thread and _library_reconcile_thread.is_alive():
            return dict(_library_reconcile_state)
        decision = {'run': True, 'reason': 'explicit'} if force else _startup_reconcile_decision()
        if not decision['run']:
            _library_reconcile_state = {
                **_library_reconcile_state,
                'status': 'completed',
                'skipped': True,
                'reason': decision['reason'],
                'updated_at': time.time(),
            }
            return dict(_library_reconcile_state)
        _library_reconcile_state = {
            **_library_reconcile_state,
            'status': 'running',
            'skipped': False,
            'reason': decision['reason'],
            'updated_at': time.time(),
        }
        _library_reconcile_thread = threading.Thread(
            target=_run_library_reconcile_loop,
            name='cinema-library-reconcile',
            daemon=True,
        )
        _library_reconcile_thread.start()
        return dict(_library_reconcile_state)


@app.route('/api/startup/status')
def startup_status():
    return jsonify({
        **_startup_metrics,
        'api_ready_ms': _startup_metrics['api_ready_ms'] or round((time.perf_counter() - _process_started_at) * 1000, 3),
        'reconcile': _library_reconcile_status(),
    })


def _identity_resolution(outcome, metadata=None, decision=None, *, manual_locked=False, source=''):
    return {
        'outcome': str(outcome or 'unmatched'),
        'metadata': dict(metadata or {}),
        'decision': dict(decision or {}),
        'manual_locked': bool(manual_locked),
        'source': str(source or ''),
    }


def _resolve_tmdb_identity(path, file_facts, plex_data, store):
    manual_match = store.get_manual_match(path)
    if manual_match.get('provider') == 'tmdb':
        tmdb_id = str(manual_match.get('tmdb_id', '') or '')
        metadata = _fetch_tmdb_metadata_by_id(
            tmdb_id,
            store=store,
            refresh=not bool(store.get_tmdb_metadata(tmdb_id)),
            match_source='manual_tmdb',
        )
        if metadata:
            return _identity_resolution(
                'accepted',
                metadata,
                {'status': 'accepted', 'outcome': 'accepted', 'automatic': False},
                manual_locked=True,
                source='manual_tmdb',
            )

    file_record = store._read_json(store.files_file, {'files': {}}).get('files', {}).get(store._key(path), {})
    accepted = resolve_authoritative_identity(file_record).get('accepted')
    plex_tmdb_id = str(plex_data.get('tmdb_id') or '')
    saved_tmdb_id = str(file_record.get('tmdb_id') or '') if accepted else ''
    if saved_tmdb_id:
        metadata = _fetch_tmdb_metadata_by_id(
            saved_tmdb_id,
            store=store,
            refresh=not bool(store.get_tmdb_metadata(saved_tmdb_id)),
            match_source='saved_tmdb_id',
        )
        if metadata:
            return _identity_resolution(
                'accepted',
                metadata,
                {
                    'status': 'accepted',
                    'outcome': 'accepted',
                    'automatic': False,
                    'candidate': metadata,
                    'reasons': ['accepted TMDB identity retained'],
                },
                source='saved_tmdb_id',
            )
        fallback = {
            'tmdb_id': saved_tmdb_id,
            'imdb_id': str(file_record.get('imdb_id') or ''),
            'title': str(
                file_record.get('identity_title')
                or file_record.get('accepted_title')
                or file_facts.get('parsed_title')
                or ''
            ),
            'year': str(
                file_record.get('identity_year')
                or file_record.get('accepted_year')
                or file_facts.get('parsed_year')
                or ''
            ),
            'match_source': 'saved_tmdb_id',
            'enrichment_status': 'incomplete',
        }
        return _identity_resolution(
            'accepted',
            fallback,
            {
                'status': 'accepted',
                'outcome': 'accepted',
                'automatic': False,
                'candidate': fallback,
                'reasons': ['stable TMDB identity retained while enrichment is unavailable'],
            },
            source='saved_tmdb_id',
        )

    queries = [
        query for query in _identity_queries(path, file_facts, plex_data)
        if query.get('source') in {'filename', 'folder'}
    ]
    candidates = _identity_tmdb_candidates(queries)
    if plex_tmdb_id:
        plex_candidate = _fetch_tmdb_metadata_by_id(
            plex_tmdb_id,
            store=store,
            refresh=not bool(store.get_tmdb_metadata(plex_tmdb_id)),
            match_source='plex_tmdb_id',
        ) or {
            'tmdb_id': plex_tmdb_id,
            'imdb_id': str(plex_data.get('imdb_id') or ''),
            'title': plex_data.get('plex_title') or '',
            'year': str(plex_data.get('plex_year') or ''),
            'provider_rank': 1,
        }
        plex_candidate_id = str(plex_candidate.get('tmdb_id') or plex_tmdb_id)
        existing_index = next(
            (
                index for index, candidate in enumerate(candidates)
                if str(candidate.get('tmdb_id') or candidate.get('id') or '') == plex_candidate_id
            ),
            None,
        )
        if existing_index is None:
            candidates.append(plex_candidate)
        else:
            candidates[existing_index] = {**candidates[existing_index], **plex_candidate}

    independent_claims = [plex_data] if plex_data else []
    has_independent_content = bool(
        plex_data
        and any(plex_data.get(key) for key in (
            'plot', 'summary', 'plex_summary', 'genres', 'directors', 'director', 'cast'
        ))
    )
    if has_independent_content:
        enriched_candidates = _enriched_identity_tmdb_candidates(queries, candidates, store=store)
        if enriched_candidates != candidates:
            candidates = enriched_candidates
    decision = evaluate_identity(
        queries,
        candidates,
        independent_claims=independent_claims,
    )
    if decision.get('outcome') in {'ambiguous', 'unmatched'} and not has_independent_content:
        enriched_candidates = _enriched_identity_tmdb_candidates(queries, candidates, store=store)
        if enriched_candidates != candidates:
            decision = evaluate_identity(
                queries,
                enriched_candidates,
                independent_claims=independent_claims,
            )
    candidate = decision.get('candidate', {})
    outcome = decision.get('outcome', 'unmatched')
    if outcome == 'accepted' and candidate.get('tmdb_id'):
        metadata = _fetch_tmdb_metadata_by_id(
            candidate.get('tmdb_id'),
            store=store,
            refresh=True,
            match_source='auto_tmdb',
        ) or candidate
        match_source = (
            'plex_tmdb_id'
            if plex_tmdb_id and str(candidate.get('tmdb_id') or '') == plex_tmdb_id
            else 'auto_tmdb'
        )
        metadata['match_source'] = match_source
        return _identity_resolution(
            'accepted',
            metadata,
            decision,
            source=match_source,
        )
    metadata = {**candidate, 'match_source': 'candidate_tmdb'} if candidate else {}
    return _identity_resolution(outcome, metadata, decision, source='candidate_tmdb')


def _query_from_parsed(parsed, source):
    if isinstance(parsed, tuple):
        title, year = parsed
        parsed = {'title': title, 'year': year}
    query = dict(parsed or {})
    if not query.get('title'):
        return {}
    return {
        **query,
        'title': str(query.get('title') or ''),
        'year': str(query.get('year') or ''),
        'source': source,
    }


def _append_parsed_query(queries, parsed, source):
    query = _query_from_parsed(parsed, source)
    if query:
        queries.append(query)


def _append_folder_query(queries, path, parser):
    library_root = _path_library_root(path)
    parent = os.path.dirname(path)
    if library_root and _norm(parent) != _norm(library_root):
        _append_parsed_query(queries, parser(os.path.basename(parent)), 'folder')


def _dedupe_title_year_queries(queries):
    unique = []
    seen = set()
    for query in queries:
        key = (
            _norm_movie_title(query.get('title', '')),
            str(query.get('year', '') or ''),
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        unique.append(query)
    return unique


def _identity_queries(path, file_facts=None, plex_data=None):
    file_facts = file_facts or _metadata_file_facts(path)
    plex_data = plex_data or {}
    queries = []
    _append_parsed_query(queries, {
        'title': file_facts.get('parsed_title'),
        'year': file_facts.get('parsed_year'),
    }, 'filename')
    _append_parsed_query(queries, {
        'title': plex_data.get('plex_title'),
        'year': plex_data.get('plex_year'),
    }, 'plex_hint')
    _append_folder_query(queries, path, parse_movie_title)
    return _dedupe_title_year_queries(queries)


def _identity_tmdb_candidates(queries):
    merged = {}
    for query in queries or []:
        for candidate in _smart_match_tmdb_candidates(query.get('title', ''), query.get('year', '')):
            identity = str(candidate.get('tmdb_id') or candidate.get('id') or '')
            if not identity:
                continue
            current = merged.get(identity)
            sources = list(dict.fromkeys([
                query.get('source', ''),
                *((candidate.get('query_sources') or [])),
            ]))
            if current is None:
                merged[identity] = {**candidate, 'query_sources': [source for source in sources if source]}
            else:
                current['provider_rank'] = min(
                    int(current.get('provider_rank', 999) or 999),
                    int(candidate.get('provider_rank', 999) or 999),
                )
                current['query_sources'] = list(dict.fromkeys([
                    *(current.get('query_sources') or []),
                    *[source for source in sources if source],
                ]))
    return list(merged.values())


def _enriched_identity_tmdb_candidates(queries, candidates, store=None):
    enriched = []
    for candidate in (candidates or [])[:5]:
        tmdb_id = str(candidate.get('tmdb_id') or candidate.get('id') or '')
        if not tmdb_id:
            enriched.append(candidate)
            continue
        details = _fetch_tmdb_metadata_by_id(tmdb_id, store=store, refresh=False) or {}
        if details:
            enriched.append({
                **candidate,
                **details,
                'provider_rank': candidate.get('provider_rank', details.get('provider_rank', 999)),
                'query_sources': candidate.get('query_sources', []),
                'alternative_titles': candidate.get('alternative_titles') or details.get('alternative_titles', []),
                'original_title': candidate.get('original_title', details.get('original_title', '')),
            })
        else:
            enriched.append(candidate)
    enriched.extend(list(candidates or [])[5:])
    return enriched


def _migrate_locked_manual_match(path, facts, plex_data, store):
    manual_match = store.get_manual_match(path)
    provider = manual_match.get('provider')
    if provider == 'tmdb':
        tmdb_id = str(manual_match.get('tmdb_id', '') or '')
        metadata = store.get_tmdb_metadata(tmdb_id)
        if not metadata and tmdb_id and _tmdb_key:
            metadata = _fetch_tmdb_metadata_by_id(
                tmdb_id,
                store=store,
                refresh=True,
                match_source='manual_tmdb',
            )
        metadata = store.save_tmdb_metadata(metadata or manual_match)
        current = store.snapshot().get('files', {}).get(store._key(path), {})
        store.update_file_record(path, _accepted_identity_record_patch(
            current,
            metadata,
            provider='tmdb',
            source='manual_tmdb',
            facts=facts,
            manual_lock=True,
            migration_status='matched',
            identity_decision_version=IDENTITY_DECISION_VERSION,
            extra={
                'tmdb_id': tmdb_id,
                'imdb_id': str(metadata.get('imdb_id', '') or manual_match.get('imdb_id', '') or ''),
            },
        ))
        return 'matched'
    if provider == 'plex':
        metadata = store.get_plex_metadata(path) or plex_data
        current = store.snapshot().get('files', {}).get(store._key(path), {})
        store.update_file_record(path, _accepted_identity_record_patch(
            current,
            {
                'title': metadata.get('plex_title', ''),
                'year': metadata.get('plex_year', ''),
                'tmdb_id': metadata.get('tmdb_id', ''),
                'imdb_id': metadata.get('imdb_id', ''),
                'plex_guid': metadata.get('plex_guid', ''),
                'rating_key': metadata.get('rating_key', ''),
            },
            provider='plex',
            source='manual_plex',
            facts=facts,
            manual_lock=True,
            migration_status='matched',
            identity_decision_version=IDENTITY_DECISION_VERSION,
            extra={
                'tmdb_id': str(metadata.get('tmdb_id', '') or ''),
                'imdb_id': str(metadata.get('imdb_id', '') or ''),
                'rating_key': str(metadata.get('rating_key', '') or manual_match.get('rating_key', '') or ''),
            },
        ))
        return 'matched'
    return ''


def _revalidate_accepted_identity(path, provider, store, current_record, facts, plex_data):
    decision = _process_identity_audit_path(path, provider=provider, force_deep=True)
    outcome = str(decision.get('outcome') or 'ambiguous')
    reasons = list(decision.get('reasons') or [])
    evidence_fingerprint = _identity_evidence_fingerprint(path, facts, plex_data)
    if outcome in {'verified', 'tolerated', 'manual'}:
        store.update_file_record(path, {
            **facts,
            'ingest_status': 'stable',
            'migration_status': 'matched',
            'identity_decision_outcome': 'accepted',
            'identity_decision_reasons': reasons,
            'identity_decision_version': IDENTITY_DECISION_VERSION,
            'identity_evidence_fingerprint': evidence_fingerprint,
            'identity_evidence_changed': False,
        })
        return 'matched'

    candidate = dict(decision.get('candidate') or {})
    contradicted = outcome == 'actionable'
    previous_identity = resolve_authoritative_identity(current_record)
    patch = {
        **facts,
        'ingest_status': 'stable',
        'identity_status': 'conflict' if contradicted else 'unmatched',
        'metadata_status': 'conflict' if contradicted else 'unmatched',
        'metadata_accepted': False,
        'migration_status': 'needs_review' if contradicted else 'unmatched',
        'identity_decision_outcome': (
            'contradicted' if contradicted
            else 'ambiguous' if outcome == 'ambiguous'
            else 'unmatched'
        ),
        'identity_decision_reasons': reasons,
        'identity_decision_version': IDENTITY_DECISION_VERSION,
        'identity_evidence_fingerprint': evidence_fingerprint,
        'identity_evidence_changed': False,
        'candidate_tmdb_id': str(candidate.get('tmdb_id') or ''),
        'candidate_plex_guid': str(candidate.get('plex_guid') or candidate.get('guid') or ''),
        'candidate_title': candidate.get('title') or candidate.get('name') or '',
        'candidate_year': str(candidate.get('year') or ''),
        'previous_accepted_identity': {
            'title': previous_identity.get('title', ''),
            'year': previous_identity.get('year', ''),
            'tmdb_id': previous_identity.get('tmdb_id', ''),
            'imdb_id': previous_identity.get('imdb_id', ''),
            'plex_guid': previous_identity.get('plex_guid', ''),
        },
        'identity_conflict': {
            'reason': 'changed file evidence contradicts the accepted identity',
            'candidate_tmdb_id': str(candidate.get('tmdb_id') or ''),
            'candidate_plex_guid': str(candidate.get('plex_guid') or candidate.get('guid') or ''),
            'reasons': reasons,
        } if contradicted else {},
    }
    store.update_file_record(path, patch)
    return 'review'


def _migrate_metadata_path(path, target, store=None, revalidate_accepted=False):
    if not os.path.isfile(path) or not _path_library_root(path):
        return 'failed'
    store = store or _metadata_store()
    snapshot = store.snapshot()
    path_key = store._key(path)
    current_record = snapshot.get('files', {}).get(path_key, {})
    facts = _metadata_file_facts(path)
    filename = facts['filename']
    plex_data = dict(
        snapshot.get('plex_files', {}).get(path_key, {})
        or _plex_cache.get(_norm(path), {})
        or _plex_matched_by_fname.get(filename.lower(), {})
        or {}
    )
    locked_outcome = _migrate_locked_manual_match(path, facts, plex_data, store)
    if locked_outcome:
        return locked_outcome
    if (
        revalidate_accepted
        and target in {'tmdb', 'plex'}
        and resolve_authoritative_identity(current_record).get('accepted')
    ):
        return _revalidate_accepted_identity(
            path,
            target,
            store,
            current_record,
            facts,
            plex_data,
        )

    if target == 'filename':
        if resolve_authoritative_identity(current_record).get('accepted'):
            store.update_file_record(path, {
                **facts,
                'display_provider': 'filename',
                'enrichment_status': 'incomplete',
                'migration_status': 'matched',
            })
            return 'matched'
        store.update_file_record(path, {
            **facts,
            'display_provider': 'filename',
            'metadata_status': 'unmatched',
            'metadata_source': 'filename',
            'metadata_accepted': False,
            'identity_evidence_fingerprint': _identity_evidence_fingerprint(path, facts, {}),
            'identity_decision_version': IDENTITY_DECISION_VERSION,
        })
        return 'matched'

    if target == 'plex':
        if not plex_data.get('plex_title'):
            if resolve_authoritative_identity(current_record).get('accepted'):
                store.update_file_record(path, {
                    **facts,
                    'display_provider': 'plex',
                    'enrichment_status': 'incomplete',
                    'migration_status': 'matched',
                    'identity_decision_version': IDENTITY_DECISION_VERSION,
                })
                return 'matched'
            if _tmdb_key:
                return _migrate_metadata_path(path, 'tmdb', store=store)
            store.update_file_record(path, {
                **facts,
                'migration_status': 'needs_review',
                'identity_evidence_fingerprint': _identity_evidence_fingerprint(path, facts, plex_data),
                'identity_decision_version': IDENTITY_DECISION_VERSION,
            })
            return 'review'
        current_identity = resolve_authoritative_identity(current_record)
        for key, plex_key in (
            ('tmdb_id', 'tmdb_id'),
            ('imdb_id', 'imdb_id'),
            ('plex_guid', 'plex_guid'),
        ):
            current_id = str(current_identity.get(key, '') or '').lower()
            plex_id = str(plex_data.get(plex_key, '') or '').lower()
            if current_id and plex_id and current_id != plex_id:
                store.update_file_record(path, {
                    **facts,
                    'identity_status': 'conflict',
                    'metadata_status': 'conflict',
                    'metadata_accepted': False,
                    'migration_status': 'needs_review',
                    'identity_decision_outcome': 'contradicted',
                    'identity_decision_reasons': [f'Plex {key} contradicts the accepted identity'],
                    'identity_conflict': {
                        'field': key,
                        'accepted': current_id,
                        'plex': plex_id,
                    },
                    'identity_evidence_fingerprint': _identity_evidence_fingerprint(path, facts, plex_data),
                    'identity_decision_version': IDENTITY_DECISION_VERSION,
                })
                return 'review'
        queries = [
            query for query in _identity_queries(path, facts, plex_data)
            if query.get('source') in {'filename', 'folder'}
        ]
        plex_candidate = {
            'plex_guid': plex_data.get('plex_guid', ''),
            'tmdb_id': plex_data.get('tmdb_id', ''),
            'imdb_id': plex_data.get('imdb_id', ''),
            'title': plex_data.get('plex_title', ''),
            'year': plex_data.get('plex_year', ''),
            'provider_rank': 1,
        }
        plex_decision = evaluate_identity(queries, [plex_candidate])
        plex_outcome = plex_decision.get('outcome', 'unmatched')
        evidence_fingerprint = _identity_evidence_fingerprint(path, facts, plex_data)
        if plex_outcome != 'accepted':
            contradicted = plex_outcome == 'contradicted'
            unresolved_patch = {
                **facts,
                'migration_status': 'needs_review' if contradicted else 'unmatched',
                'candidate_plex_guid': str(plex_data.get('plex_guid', '') or ''),
                'candidate_title': plex_data.get('plex_title', ''),
                'candidate_year': str(plex_data.get('plex_year', '') or ''),
                'identity_decision_outcome': plex_outcome,
                'identity_decision_reasons': list(plex_decision.get('reasons') or []),
                'identity_evidence_fingerprint': evidence_fingerprint,
                'identity_evidence_changed': False,
                'identity_decision_version': IDENTITY_DECISION_VERSION,
            }
            if not current_identity.get('accepted'):
                unresolved_patch.update({
                    'identity_status': 'conflict' if contradicted else 'unmatched',
                    'metadata_status': 'conflict' if contradicted else 'unmatched',
                    'metadata_accepted': False,
                })
            store.update_file_record(path, unresolved_patch)
            return 'review'
        store.save_plex_metadata(path, plex_data)
        decision_origin = str(current_record.get('decision_origin') or DECISION_ORIGIN_LIBRARY_RECONCILE)
        store.update_file_record(path, _accepted_identity_record_patch(
            current_record,
            {
                'title': plex_data.get('plex_title', ''),
                'year': plex_data.get('plex_year', ''),
                'tmdb_id': plex_data.get('tmdb_id', ''),
                'imdb_id': plex_data.get('imdb_id', ''),
                'plex_guid': plex_data.get('plex_guid', ''),
                'rating_key': plex_data.get('rating_key', ''),
            },
            provider='plex',
            source='plex_snapshot',
            facts=facts,
            migration_status='matched',
            identity_decision_version=IDENTITY_DECISION_VERSION,
            extra={
                'tmdb_id': str(plex_data.get('tmdb_id', '') or ''),
                'imdb_id': str(plex_data.get('imdb_id', '') or ''),
                'decision_origin': decision_origin,
                'decision_actor': 'system',
                'identity_decision_outcome': 'accepted',
                'identity_decision_reasons': list(plex_decision.get('reasons') or []),
                'identity_evidence_fingerprint': evidence_fingerprint,
                'identity_evidence_changed': False,
                'identity_conflict': {},
                'candidate_plex_guid': '',
                'candidate_title': '',
                'candidate_year': '',
            },
        ))
        return 'matched'

    if target != 'tmdb' or not _tmdb_key:
        return 'failed'

    resolution = _resolve_tmdb_identity(path, facts, plex_data, store)
    metadata = resolution.get('metadata', {})
    decision = resolution.get('decision', {})
    outcome = resolution.get('outcome', 'unmatched')
    manual_locked = bool(resolution.get('manual_locked'))
    evidence_fingerprint = _identity_evidence_fingerprint(path, facts, plex_data)
    if outcome != 'accepted':
        contradicted = outcome == 'contradicted'
        unresolved_patch = {
            **facts,
            'migration_status': 'needs_review' if contradicted else 'unmatched',
            'candidate_tmdb_id': str(metadata.get('tmdb_id', '') or ''),
            'candidate_title': metadata.get('title', ''),
            'candidate_year': str(metadata.get('year', '') or ''),
            'identity_decision_outcome': outcome,
            'identity_decision_reasons': list(decision.get('reasons') or []),
            'identity_evidence_fingerprint': evidence_fingerprint,
            'identity_evidence_changed': False,
            'identity_decision_version': IDENTITY_DECISION_VERSION,
        }
        if not resolve_authoritative_identity(current_record).get('accepted'):
            unresolved_patch.update({
                'identity_status': 'conflict' if contradicted else 'unmatched',
                'metadata_status': 'conflict' if contradicted else 'unmatched',
                'metadata_accepted': False,
            })
            if contradicted:
                unresolved_patch['identity_conflict'] = {
                    'reason': 'automatic identity evidence conflicts with the provider candidate',
                    'candidate_tmdb_id': str(metadata.get('tmdb_id', '') or ''),
                    'reasons': list(decision.get('reasons') or []),
                }
        store.update_file_record(path, unresolved_patch)
        return 'review'
    tmdb_id = str(metadata.get('tmdb_id', '') or '')
    if not tmdb_id:
        store.update_file_record(path, {
            **facts,
            'identity_status': 'unmatched',
            'metadata_status': 'unmatched',
            'metadata_accepted': False,
            'identity_decision_outcome': 'unmatched',
            'identity_evidence_fingerprint': evidence_fingerprint,
            'identity_evidence_changed': False,
            'identity_decision_version': IDENTITY_DECISION_VERSION,
        })
        return 'review'
    saved = store.save_tmdb_metadata(metadata)
    decision_origin = (
        DECISION_ORIGIN_USER_MANUAL
        if manual_locked
        else str(current_record.get('decision_origin') or DECISION_ORIGIN_LIBRARY_RECONCILE)
    )
    identity_source = (
        'manual_tmdb'
        if manual_locked
        else str(current_record.get('identity_source') or resolution.get('source') or 'auto_tmdb')
    )
    store.update_file_record(path, _accepted_identity_record_patch(
        current_record,
        saved,
        provider='tmdb',
        source=identity_source,
        facts=facts,
        manual_lock=manual_locked,
        manual_locked=manual_locked,
        metadata_source='manual_tmdb' if manual_locked else 'tmdb_snapshot',
        migration_status='matched',
        identity_decision_version=IDENTITY_DECISION_VERSION,
        extra={
            'tmdb_id': tmdb_id,
            'imdb_id': str(saved.get('imdb_id', '') or ''),
            'decision_origin': decision_origin,
            'decision_actor': 'user' if decision_origin == DECISION_ORIGIN_USER_MANUAL else 'system',
            'identity_decision_outcome': 'accepted',
            'identity_decision_reasons': list(decision.get('reasons') or []),
            'identity_evidence_fingerprint': evidence_fingerprint,
            'identity_evidence_changed': False,
            'identity_conflict': {},
            'candidate_tmdb_id': '',
            'candidate_title': '',
            'candidate_year': '',
        },
    ))
    return 'matched'


def _complete_metadata_migration(state):
    global _library_cache
    store = _metadata_store()
    target = state.get('target', '')
    provider = _metadata_provider_status().get(target, {})
    if not provider.get('available'):
        failed_state = {
            **state,
            'status': 'failed',
            'failure_reason': f"{provider.get('label', target or 'Target provider')} is no longer configured",
            'updated_at': time.time(),
        }
        store.save_migration_state(failed_state)
        _library_cache = {}
        return
    for path in state.get('review_paths', []):
        record = store.snapshot().get('files', {}).get(store._key(path), {})
        if resolve_authoritative_identity(record).get('accepted'):
            store.update_file_record(path, {
                'display_provider': target,
                'enrichment_status': 'incomplete',
                'migration_status': 'needs_review',
            })
        else:
            store.update_file_record(path, {
                'display_provider': 'filename',
                'identity_status': 'review',
                'metadata_status': 'needs_review',
                'metadata_source': 'filename',
                'metadata_accepted': False,
                'migration_status': 'needs_review',
            })
    store.save_authority_state({
        'active_provider': state.get('target', ''),
        'previous_provider': state.get('source', ''),
        'last_migration': {
            'matched': state.get('matched', 0),
            'review': state.get('review', 0),
            'failed': state.get('failed', 0),
            'completed_at': state.get('completed_at', time.time()),
        },
    })
    _library_cache = {}
    if target in {'tmdb', 'plex'} and state.get('status') == 'completed' and int(state.get('total', 0) or 0) > 0:
        audit_state = store.get_identity_audit_state()
        store.save_identity_audit_state({
            **audit_state,
            'requires_refresh': True,
            'updated_at': time.time(),
        })


def _get_metadata_migration_coordinator():
    global _metadata_migration_coordinator, _metadata_migration_store_dir
    store_dir = str(Path(_user_data_dir).resolve())
    if _metadata_migration_coordinator is None or _metadata_migration_store_dir != store_dir:
        store = _metadata_store()
        _metadata_migration_coordinator = MetadataMigrationCoordinator(
            load_state=store.get_migration_state,
            save_state=store.save_migration_state,
            list_paths=_metadata_migration_paths,
            process_path=_migrate_metadata_path,
            on_complete=_complete_metadata_migration,
            batch_size=8,
            batch_delay=0.15,
        )
        _metadata_migration_store_dir = store_dir
    return _metadata_migration_coordinator


def _public_migration_state(state):
    state = dict(state or {})
    state.pop('paths', None)
    state.pop('review_paths', None)
    state.pop('failed_paths', None)
    total = int(state.get('total', 0) or 0)
    processed = int(state.get('processed', 0) or 0)
    state['progress_percent'] = round((processed / total) * 100, 1) if total else 0
    return state


@app.route('/api/metadata/authority')
def metadata_authority():
    store = _metadata_store()
    return jsonify({
        'active_provider': _active_metadata_provider(store),
        'providers': _metadata_provider_status(),
        'migration': _public_migration_state(_get_metadata_migration_coordinator().status()),
        'authority': store.get_authority_state(),
    })


@app.route('/api/metadata/authority/preview', methods=['POST'])
def metadata_authority_preview():
    body = request.get_json(silent=True) or {}
    target = str(body.get('target', '') or '')
    providers = _metadata_provider_status()
    if target not in providers:
        return jsonify({'error': 'Unknown metadata provider'}), 400
    if not providers[target]['available']:
        return jsonify({'error': f"{providers[target]['label']} is not configured"}), 400
    preview = _get_metadata_migration_coordinator().preview(target)
    preview.pop('paths', None)
    preview['source'] = _active_metadata_provider()
    return jsonify(preview)


@app.route('/api/metadata/authority/migrate', methods=['POST'])
def metadata_authority_migrate():
    body = request.get_json(silent=True) or {}
    target = str(body.get('target', '') or '')
    providers = _metadata_provider_status()
    if target not in providers:
        return jsonify({'error': 'Unknown metadata provider'}), 400
    if not providers[target]['available']:
        return jsonify({'error': f"{providers[target]['label']} is not configured"}), 400
    if _get_identity_audit_coordinator().status().get('status') == 'running':
        return jsonify({'error': 'Library identity audit is already active'}), 409
    try:
        state = _get_metadata_migration_coordinator().start(
            target,
            source=_active_metadata_provider(),
            background=True,
        )
    except RuntimeError as error:
        return jsonify({'error': str(error)}), 409
    return jsonify(_public_migration_state(state))


@app.route('/api/metadata/migration')
def metadata_migration_status():
    return jsonify(_public_migration_state(_get_metadata_migration_coordinator().status()))


@app.route('/api/metadata/migration/<action>', methods=['POST'])
def metadata_migration_action(action):
    coordinator = _get_metadata_migration_coordinator()
    actions = {
        'pause': coordinator.pause,
        'resume': coordinator.resume,
        'cancel': coordinator.cancel,
        'retry': coordinator.retry_failed,
    }
    handler = actions.get(action)
    if not handler:
        return jsonify({'error': 'Unknown migration action'}), 404
    return jsonify(_public_migration_state(handler()))


def _identity_audit_paths():
    _auto_sync_plex(force=False)
    return [full_path for _, _, _, full_path in _iter_video_files()]


def _identity_audit_fingerprint(
    path,
    provider,
    store=None,
    snapshot=None,
    plex_data=None,
    record=None,
    tmdb_data=None,
):
    store = store or _metadata_store()
    key = store._key(path)
    if record is None:
        record = (
            snapshot.get('files', {}).get(key, {})
            if snapshot is not None
            else store.catalog.get_record('app_metadata/files.json', key, {})
        )
    filename = os.path.basename(path)
    plex_data = dict(
        plex_data
        or (
            snapshot.get('plex_files', {}).get(key, {})
            if snapshot is not None
            else store.get_plex_metadata(path)
        )
        or _plex_cache.get(_norm(path), {})
        or _plex_matched_by_fname.get(filename.lower(), {})
        or {}
    )
    try:
        stat_result = os.stat(path)
    except OSError:
        return {}
    provider_id = (
        str(plex_data.get('plex_guid') or plex_data.get('guid') or '')
        if provider == 'plex'
        else str(record.get('tmdb_id') or '')
    )
    if tmdb_data is None and provider == 'tmdb' and provider_id:
        tmdb_data = (
            snapshot.get('tmdb_movies', {}).get(provider_id, {})
            if snapshot is not None
            else store.get_tmdb_metadata(provider_id)
        )
    tmdb_data = dict(tmdb_data or {})
    title = (
        plex_data.get('plex_title')
        if provider == 'plex'
        else tmdb_data.get('title')
    ) or plex_data.get('plex_title') or record.get('metadata_title') or ''
    year = (
        plex_data.get('plex_year')
        if provider == 'plex'
        else tmdb_data.get('year')
    ) or plex_data.get('plex_year') or record.get('metadata_year') or ''
    return {
        'rule_version': IDENTITY_AUDIT_RULE_VERSION,
        'provider': provider,
        'size': int(stat_result.st_size),
        'modified_time_ns': int(stat_result.st_mtime_ns),
        'provider_id': provider_id,
        'title': _norm_movie_title(title),
        'year': str(year or ''),
    }


def _identity_plex_candidates(path, queries, plex_data):
    rating_key = str((plex_data or {}).get('rating_key', '') or _plex_rating_key_for_path(path))
    if not rating_key:
        return []
    merged = {}
    for query in queries or []:
        for candidate in _smart_match_plex_candidates(
            rating_key,
            query.get('title', ''),
            query.get('year', ''),
        ):
            identity = str(candidate.get('guid') or '')
            if not identity:
                continue
            candidate = {
                **candidate,
                'plex_guid': identity,
                'title': candidate.get('title') or candidate.get('name') or '',
                'query_sources': [query.get('source', '')],
            }
            current = merged.get(identity)
            if current is None:
                merged[identity] = candidate
            else:
                current['provider_rank'] = min(
                    int(current.get('provider_rank', 999) or 999),
                    int(candidate.get('provider_rank', 999) or 999),
                )
                current['query_sources'] = list(dict.fromkeys([
                    *(current.get('query_sources') or []),
                    *[source for source in candidate.get('query_sources', []) if source],
                ]))
    return list(merged.values())


def _process_identity_audit_path(path, provider='tmdb', force_deep=False):
    if not os.path.isfile(path) or not _path_library_root(path):
        return {
            'outcome': 'unmatched',
            'reason': 'File is no longer available in the Library',
        }
    store = _metadata_store()
    key = store._key(path)
    record = store.catalog.get_record('app_metadata/files.json', key, {})
    manual_match = store.get_manual_match(path)
    fingerprint = store.get_identity_audit_fingerprint(path)
    facts = _metadata_file_facts(path)
    filename = facts['filename']
    plex_data = dict(
        store.get_plex_metadata(path)
        or _plex_cache.get(_norm(path), {})
        or _plex_matched_by_fname.get(filename.lower(), {})
        or {}
    )
    current_id = str(record.get('tmdb_id', '') or '')
    current_tmdb = store.get_tmdb_metadata(current_id) if current_id else {}
    verification = verify_catalog_identity({
        **record,
        'path': path,
        'raw_json': {**facts, **record, 'path': path},
        'manual_json': manual_match,
        'tmdb_json': current_tmdb,
        'plex_json': plex_data,
        'audit_fingerprint_json': fingerprint,
    })
    if verification.get('decision_origin') == DECISION_ORIGIN_USER_MANUAL:
        return {
            'outcome': 'manual',
            'filename': filename,
            'reasons': ['explicit user identity is protected'],
        }
    if not verification.get('accepted'):
        return {
            'outcome': 'unmatched',
            'filename': filename,
            'reasons': verification.get('reasons', []),
        }
    if verification.get('classification') == 'verified' and not force_deep:
        return {
            'outcome': 'verified',
            'filename': filename,
            'reasons': verification.get('reasons', []),
            'drift_reasons': verification.get('drift_reasons', []),
        }

    if provider == 'plex':
        current = {
            **plex_data,
            'plex_guid': str(plex_data.get('plex_guid') or plex_data.get('guid') or ''),
            'tmdb_id': str(plex_data.get('tmdb_id') or ''),
            'imdb_id': str(plex_data.get('imdb_id') or ''),
            'title': plex_data.get('plex_title') or facts.get('parsed_title', ''),
            'year': str(plex_data.get('plex_year') or facts.get('parsed_year', '')),
        }
    else:
        current = {
            **current_tmdb,
            'tmdb_id': current_id,
            'imdb_id': str(
                current_tmdb.get('imdb_id')
                or record.get('imdb_id')
                or plex_data.get('imdb_id')
                or ''
            ),
            'title': current_tmdb.get('title') or plex_data.get('plex_title') or facts.get('parsed_title', ''),
            'year': str(current_tmdb.get('year') or plex_data.get('plex_year') or facts.get('parsed_year', '')),
        }
    queries = _identity_queries(path, facts, plex_data)
    candidates = (
        _identity_plex_candidates(path, queries, plex_data)
        if provider == 'plex'
        else _identity_tmdb_candidates(queries)
    )
    if provider == 'tmdb':
        candidates = _enriched_identity_tmdb_candidates(queries, candidates, store=store)
        merged_candidates = []
        found_current = False
        for candidate in candidates:
            candidate_id = str(candidate.get('tmdb_id') or candidate.get('id') or '')
            if current_id and candidate_id == current_id:
                found_current = True
                merged_candidates.append({
                    **candidate,
                    **current_tmdb,
                    'tmdb_id': current_id,
                    'provider_rank': candidate.get('provider_rank', 999),
                    'query_sources': candidate.get('query_sources', []),
                })
            else:
                merged_candidates.append(candidate)
        if current_id and not found_current:
            merged_candidates.append({
                **current_tmdb,
                'tmdb_id': current_id,
                'title': current_tmdb.get('title') or current.get('title', ''),
                'year': str(current_tmdb.get('year') or current.get('year', '')),
                'provider_rank': 999,
                'query_sources': ['accepted_provider'],
            })
        candidates = merged_candidates

    independent_claims = [
        plex_data if provider == 'tmdb' else current_tmdb
    ] if (plex_data if provider == 'tmdb' else current_tmdb) else []
    decision = evaluate_identity(
        queries,
        candidates,
        current=current,
        provider=provider,
        mode='audit',
        independent_claims=independent_claims,
    )
    candidate = decision.get('candidate', {})
    candidate_id = str(
        candidate.get('plex_guid') or candidate.get('guid') or ''
        if provider == 'plex'
        else candidate.get('tmdb_id', '') or ''
    )
    if not candidate_id:
        return {
            'filename': filename,
            'reason': f'No {provider.upper()} identity candidate',
            'current': current,
            **decision,
            'outcome': 'ambiguous',
        }
    if decision.get('outcome') == 'verified':
        verified_fingerprint = _identity_audit_fingerprint(
            path,
            provider,
            store=store,
            plex_data=plex_data,
            record=record,
            tmdb_data=current_tmdb,
        )
        if verified_fingerprint:
            decision_origin = verification.get('decision_origin') or infer_decision_origin(
                record,
                manual_match,
                fingerprint,
            )
            store.save_identity_audit_fingerprint(path, {
                **verified_fingerprint,
                **({'decision_origin': decision_origin} if decision_origin else {}),
            })
        return {
            'outcome': 'verified',
            'filename': filename,
            'reasons': decision.get('reasons', []),
        }
    outcome = {
        'accepted': 'tolerated',
        'contradicted': 'actionable',
        'ambiguous': 'ambiguous',
        'unmatched': 'unmatched',
    }.get(decision.get('outcome'), 'ambiguous')
    return {
        'outcome': outcome,
        'path': path,
        'filename': filename,
        'current': current,
        'candidate': candidate,
        'alternatives': decision.get('alternatives', []),
        'status': decision.get('status', 'review'),
        'classification': 'actionable' if outcome == 'actionable' else decision.get('classification', 'review'),
        'automatic': False,
        'evidence_score': decision.get('evidence_score', 0),
        'runner_up_gap': decision.get('runner_up_gap', 0),
        'reasons': list(dict.fromkeys(decision.get('reasons') or [])),
        'query_sources': decision.get('query_sources', []),
        'preselected': False,
        'provider': provider,
        'identity_revision': int(record.get('identity_revision', 0) or 0),
    }


def _get_identity_audit_coordinator():
    global _identity_audit_coordinator, _identity_audit_store_dir
    store_dir = str(Path(_user_data_dir).resolve())
    if _identity_audit_coordinator is None or _identity_audit_store_dir != store_dir:
        store = _metadata_store()
        _identity_audit_coordinator = IdentityAuditCoordinator(
            load_state=store.get_identity_audit_state,
            save_state=store.save_identity_audit_state,
            list_paths=_identity_audit_paths,
            process_path=_process_identity_audit_path,
            batch_size=24,
            batch_delay=0.05,
            max_workers=3,
        )
        _identity_audit_store_dir = store_dir
    return _identity_audit_coordinator


def _public_identity_audit_state(state):
    state = dict(state or {})
    state.pop('paths', None)
    state['shadow_mode'] = state.get('shadow_mode') is not False
    state['mutates_metadata'] = False
    state['outcome_counts'] = {
        'verified': 0,
        'manual': 0,
        'tolerated': 0,
        'ambiguous': 0,
        'actionable': 0,
        'unmatched': 0,
        **dict(state.get('outcome_counts') or {}),
    }
    state['automatic_fixes'] = list(state.get('automatic_fixes') or [])
    proposals = []
    for proposal in state.get('proposals', []) or []:
        classification = proposal.get('classification') or (
            'recommended' if proposal.get('preselected') else 'review'
        )
        proposals.append({**proposal, 'classification': classification})
    state['proposals'] = proposals
    state['recommended_count'] = sum(
        1 for proposal in proposals
        if proposal.get('classification') == 'recommended'
    )
    state['review_count'] = len(proposals) - state['recommended_count']
    state['automatically_verified'] = int(state.get('automatically_verified', 0) or 0)
    state['last_checked_at'] = state.get('last_checked_at') or state.get('completed_at', 0)
    total = int(state.get('total', 0) or 0)
    processed = int(state.get('processed', 0) or 0)
    state['progress_percent'] = round((processed / total) * 100, 1) if total else 0
    return state


def _resolve_identity_audit_path(path):
    store = _metadata_store()
    state = store.get_identity_audit_state()
    proposals = list(state.get('proposals') or [])
    automatic_fixes = list(state.get('automatic_fixes') or [])
    normalized = _norm(path)
    remaining = [
        proposal for proposal in proposals
        if _norm(proposal.get('path', '')) != normalized
    ]
    remaining_automatic = [
        item for item in automatic_fixes
        if _norm(item.get('path', '')) != normalized
    ]
    if len(remaining) == len(proposals) and len(remaining_automatic) == len(automatic_fixes):
        return state
    state['proposals'] = remaining
    state['automatic_fixes'] = remaining_automatic
    state['recommended_count'] = sum(
        1 for proposal in remaining
        if proposal.get('classification') == 'recommended'
    )
    state['review_count'] = len(remaining) - state['recommended_count']
    state['updated_at'] = time.time()
    store.save_identity_audit_state(state)
    return state


@app.route('/api/metadata/identity-audit', methods=['GET', 'POST'])
def identity_audit():
    coordinator = _get_identity_audit_coordinator()
    if request.method == 'GET':
        return jsonify(_public_identity_audit_state(coordinator.status()))
    if _get_metadata_migration_coordinator().status().get('status') in {'running', 'paused'}:
        return jsonify({'error': 'Metadata migration is already active'}), 409
    body = request.get_json(silent=True) or {}
    provider = str(body.get('provider') or _active_metadata_provider() or 'tmdb')
    if provider not in {'tmdb', 'plex'}:
        provider = 'tmdb'
    if provider == 'tmdb' and not _tmdb_key:
        return jsonify({'error': 'TMDB is not configured'}), 400
    if provider == 'plex' and not (_plex_url and _plex_token):
        return jsonify({'error': 'Plex is not configured'}), 400
    try:
        state = coordinator.start(provider=provider, background=body.get('background') is not False)
    except RuntimeError as error:
        return jsonify({'error': str(error)}), 409
    return jsonify(_public_identity_audit_state(state))


@app.route('/api/metadata/identity-audit/<job_id>')
def identity_audit_status(job_id):
    state = _get_identity_audit_coordinator().status()
    if state.get('id') != job_id:
        return jsonify({'error': 'Identity audit job not found'}), 404
    return jsonify(_public_identity_audit_state(state))


@app.route('/api/metadata/identity-audit/<job_id>/cancel', methods=['POST'])
def identity_audit_cancel(job_id):
    coordinator = _get_identity_audit_coordinator()
    if coordinator.status().get('id') != job_id:
        return jsonify({'error': 'Identity audit job not found'}), 404
    return jsonify(_public_identity_audit_state(coordinator.cancel()))


@app.route('/api/metadata/identity-audit/<job_id>/pause', methods=['POST'])
def identity_audit_pause(job_id):
    coordinator = _get_identity_audit_coordinator()
    if coordinator.status().get('id') != job_id:
        return jsonify({'error': 'Identity audit job not found'}), 404
    return jsonify(_public_identity_audit_state(coordinator.pause()))


@app.route('/api/metadata/identity-audit/<job_id>/resume', methods=['POST'])
def identity_audit_resume(job_id):
    coordinator = _get_identity_audit_coordinator()
    if coordinator.status().get('id') != job_id:
        return jsonify({'error': 'Identity audit job not found'}), 404
    try:
        return jsonify(_public_identity_audit_state(coordinator.resume(background=True)))
    except RuntimeError as error:
        return jsonify({'error': str(error)}), 409


@app.route('/api/metadata/identity-audit/<job_id>/apply', methods=['POST'])
def identity_audit_apply(job_id):
    global _library_cache
    state = _get_identity_audit_coordinator().status()
    if state.get('id') != job_id:
        return jsonify({'error': 'Identity audit job not found'}), 404
    if state.get('shadow_mode') is not False:
        return jsonify({
            'error': 'Shadow identity audits are read-only; review the report before enabling corrections',
        }), 409
    selected = set((request.get_json(silent=True) or {}).get('proposal_ids', []))
    results = []
    for proposal in state.get('proposals', []):
        if proposal.get('id') not in selected:
            continue
        try:
            path = os.path.abspath(proposal.get('path', ''))
            if not os.path.isfile(path) or not _path_library_root(path):
                raise ValueError('File is outside the authorized Library or no longer exists')
            store = _metadata_store()
            record = store.snapshot().get('files', {}).get(store._key(path), {})
            if (
                'identity_revision' in proposal
                and int(proposal.get('identity_revision', 0) or 0)
                != int(record.get('identity_revision', 0) or 0)
            ):
                raise ValueError('File identity changed after audit; start a new Identity Review scan')
            candidate = proposal.get('candidate', {})
            provider = proposal.get('provider') or state.get('provider') or 'tmdb'
            facts = _metadata_file_facts(path)
            if proposal.get('proposal_type') == 'metadata_discrepancy':
                context = _metadata_override_context_for_path(path)
                _metadata_store().save_metadata_override(
                    context['identity'],
                    title=candidate.get('title') or context['provider'].get('title', ''),
                    year=str(candidate.get('year', '') or ''),
                )
            elif provider == 'plex':
                _metadata_store().accept_plex_identity(path, {
                    'rating_key': candidate.get('rating_key') or _plex_rating_key_for_path(path),
                    'plex_guid': candidate.get('plex_guid') or candidate.get('guid'),
                    'plex_title': candidate.get('title') or candidate.get('name'),
                    'plex_year': str(candidate.get('year', '') or ''),
                },
                    source='identity_audit_plex',
                    decision_origin=DECISION_ORIGIN_IDENTITY_AUDIT,
                    facts=facts,
                )
            else:
                metadata = _fetch_tmdb_metadata_by_id(
                    candidate.get('tmdb_id'),
                    store=_metadata_store(),
                    refresh=True,
                    match_source='identity_audit_tmdb',
                ) or candidate
                _metadata_store().accept_tmdb_identity(
                    path,
                    metadata,
                    source='identity_audit_tmdb',
                    decision_origin=DECISION_ORIGIN_IDENTITY_AUDIT,
                    facts=facts,
                )
            fingerprint = _identity_audit_fingerprint(path, provider, store=_metadata_store())
            if fingerprint:
                _metadata_store().save_identity_audit_fingerprint(path, fingerprint)
            results.append({'id': proposal.get('id'), 'path': path, 'success': True})
        except Exception as error:
            results.append({'id': proposal.get('id'), 'path': proposal.get('path'), 'success': False, 'error': str(error)})
    successful_ids = {result.get('id') for result in results if result.get('success')}
    if successful_ids:
        state['proposals'] = [
            proposal for proposal in state.get('proposals', [])
            if proposal.get('id') not in successful_ids
        ]
        state['recommended_count'] = sum(
            1 for proposal in state['proposals']
            if proposal.get('classification') == 'recommended'
        )
        state['review_count'] = len(state['proposals']) - state['recommended_count']
        state['applied'] = int(state.get('applied', 0) or 0) + len(successful_ids)
        state['updated_at'] = time.time()
        _metadata_store().save_identity_audit_state(state)
    _library_cache = {}
    return jsonify({
        'applied': sum(1 for result in results if result.get('success')),
        'failed': sum(1 for result in results if not result.get('success')),
        'results': results,
    })


def _smart_match_tmdb_search(title, year=''):
    if not _tmdb_key:
        raise RuntimeError('TMDB is not configured')
    params = urllib.parse.urlencode({
        'query': title,
        'api_key': _tmdb_key,
        'language': 'en-US',
        'page': 1,
        'include_adult': _tmdb_include_adult_value(),
    })
    if year:
        params += '&year=' + urllib.parse.quote(str(year))
    req = urllib.request.Request(
        f"https://api.themoviedb.org/3/search/movie?{params}",
        headers={'Accept': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        data = _json.loads(response.read().decode())
    return (data.get('results') or [])[:10]


def _fetch_tmdb_alternative_titles(tmdb_id):
    tmdb_id = str(tmdb_id or '').strip()
    if not tmdb_id or not _tmdb_key:
        return []
    params = urllib.parse.urlencode({'api_key': _tmdb_key})
    req = urllib.request.Request(
        f"https://api.themoviedb.org/3/movie/{urllib.parse.quote(tmdb_id)}/alternative_titles?{params}",
        headers={'Accept': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        data = _json.loads(response.read().decode())
    return list(dict.fromkeys(
        str(item.get('title', '') or '').strip()
        for item in (data.get('titles') or [])
        if str(item.get('title', '') or '').strip()
    ))


def _smart_match_tmdb_alternative_titles(tmdb_id):
    tmdb_id = str(tmdb_id or '').strip()
    if not tmdb_id or not _tmdb_key:
        return []
    if tmdb_id in _smart_match_tmdb_alias_cache:
        return list(_smart_match_tmdb_alias_cache[tmdb_id])
    try:
        titles = _fetch_tmdb_alternative_titles(tmdb_id)
    except Exception:
        titles = []
    _smart_match_tmdb_alias_cache[tmdb_id] = titles
    return list(titles)


def _smart_match_tmdb_candidates(title, year=''):
    merged = {}
    for query_year, source in ((year, 'title_with_year'), ('', 'title_without_year')):
        if not query_year and source == 'title_with_year':
            continue
        for rank, movie in enumerate(_smart_match_tmdb_search(title, query_year), 1):
            normalized = _normalize_tmdb_movie_summary(movie, title, year)
            normalized['original_title'] = str(movie.get('original_title', '') or '')
            identity = str(normalized.get('tmdb_id', '') or '')
            if not identity:
                continue
            current = merged.get(identity)
            if current is None:
                normalized['provider_rank'] = rank
                normalized['query_sources'] = [source]
                merged[identity] = normalized
            else:
                current['provider_rank'] = min(int(current.get('provider_rank', rank)), rank)
                current['query_sources'] = list(dict.fromkeys([*current.get('query_sources', []), source]))
    candidates = sorted(merged.values(), key=lambda item: int(item.get('provider_rank', 999)))
    for candidate in candidates[:3]:
        candidate['alternative_titles'] = _smart_match_tmdb_alternative_titles(candidate.get('tmdb_id'))
    for candidate in candidates[3:]:
        candidate.setdefault('alternative_titles', [])
    return candidates


def _smart_match_plex_candidates(rating_key, title, year='', imdb_id='', tmdb_id=''):
    if not _plex_url or not _plex_token:
        raise RuntimeError('Plex is not configured')
    if not rating_key:
        return []
    results = PlexMatchAdapter(
        _plex_url,
        _plex_token,
        open_url=urllib.request.urlopen,
    ).search(
        rating_key,
        title=title,
        year=year,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
    )
    for candidate in results:
        poster_url = str(candidate.get('poster_url') or '')
        if poster_url.startswith('/'):
            candidate['poster_url'] = f"/api/plex/image?path={urllib.parse.quote(poster_url, safe='')}"
    return results


def _ollama_chat_content(messages):
    if not _ollama_url or not _ollama_model:
        raise RuntimeError('Ollama is not configured')
    body = _json.dumps({
        'model': _ollama_model,
        'messages': messages,
        'stream': False,
        'format': 'json',
        'options': {'temperature': 0},
    }).encode()
    req = urllib.request.Request(
        f"{_ollama_url}/api/chat",
        data=body,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = _json.loads(response.read().decode())
    return str(raw.get('message', {}).get('content', '') or '')


def _smart_match_ai_batch(items):
    safe_items = [{
        'id': str(item.get('id', '') or ''),
        'filename': os.path.basename(str(item.get('filename', '') or '')),
        'folder_name': os.path.basename(str(item.get('folder_name', '') or '')),
        'title_hint': str(item.get('title_hint', '') or ''),
        'year_hint': str(item.get('year_hint', '') or ''),
    } for item in (items or [])[:8]]
    expected_ids = [item['id'] for item in safe_items if item['id']]
    system_message = (
        'For every supplied movie file, infer the canonical theatrical movie title and original '
        'release year. Preserve each id. Hints may be malformed and are not authoritative. '
        'Return one JSON object shaped as '
        '{"matches":[{"id":"item-1","title":"Movie","year":"YYYY",'
        '"alternatives":[{"title":"Alias","year":"YYYY"}]}]}. '
        'Include up to three alternatives only when useful. Do not omit an id or include markdown.'
    )
    initial_content = ''
    first_error = ''
    try:
        initial_content = _ollama_chat_content([
            {'role': 'system', 'content': system_message},
            {'role': 'user', 'content': _json.dumps({'files': safe_items})},
        ])
        parsed = parse_ai_match_response(initial_content, expected_ids)
    except Exception as error:
        parsed = {'matches': {}, 'missing_ids': expected_ids, 'duplicate_ids': []}
        first_error = str(error)
    retry_ids = list(dict.fromkeys([*parsed.get('missing_ids', []), *parsed.get('duplicate_ids', [])]))
    if retry_ids:
        retry_items = [item for item in safe_items if item['id'] in retry_ids]
        try:
            repaired_content = _ollama_chat_content([
                {
                    'role': 'system',
                    'content': (
                        'Repair the prior response. Return only valid JSON in the requested matches '
                        'shape, exactly once for every supplied id, with no markdown.'
                    ),
                },
                {
                    'role': 'user',
                    'content': _json.dumps({
                        'files': retry_items,
                        'invalid_response': initial_content,
                    }),
                },
            ])
            repaired = parse_ai_match_response(repaired_content, retry_ids)
            parsed['matches'].update(repaired.get('matches', {}))
            retry_ids = list(dict.fromkeys([
                *repaired.get('missing_ids', []),
                *repaired.get('duplicate_ids', []),
            ]))
        except Exception as error:
            first_error = first_error or str(error)
    errors = {
        item_id: f"AI response invalid after repair{': ' + first_error if first_error else ''}"
        for item_id in retry_ids
    }
    return {'matches': parsed.get('matches', {}), 'errors': errors}


def _smart_match_context(path):
    abs_path = os.path.abspath(str(path or ''))
    if not _path_library_root(abs_path):
        raise PermissionError('Path is outside the allowed movies directory')
    if not os.path.isfile(abs_path):
        raise FileNotFoundError('File not found')
    filename = os.path.basename(abs_path)
    store = _metadata_store()
    snapshot = store.snapshot()
    record = snapshot.get('files', {}).get(store._key(abs_path), {})
    plex_data = dict(
        snapshot.get('plex_files', {}).get(store._key(abs_path), {})
        or _plex_cache.get(_norm(abs_path), {})
        or _plex_matched_by_fname.get(filename.lower(), {})
        or _plex_unmatched.get(_norm(abs_path), {})
        or _plex_unmatched_by_fname.get(filename.lower(), {})
        or {}
    )
    if not plex_data.get('rating_key'):
        plex_data['rating_key'] = _plex_rating_key_for_path(abs_path)
    return abs_path, filename, store, record, plex_data


def _smart_match_queries(abs_path, filename, record, plex_data, ai_match=None):
    parsed = parse_release_filename(filename)
    queries = []
    _append_parsed_query(queries, parsed, 'filename')
    _append_folder_query(queries, abs_path, parse_release_filename)
    for title, year, source in (
        (record.get('candidate_title'), record.get('candidate_year'), 'saved_hint'),
        (plex_data.get('plex_title'), plex_data.get('plex_year'), 'plex_hint'),
    ):
        _append_parsed_query(queries, {'title': title, 'year': year}, source)
    if ai_match and ai_match.get('title'):
        _append_parsed_query(queries, {
            'title': ai_match['title'],
            'year': ai_match.get('year') or parsed.get('year', ''),
        }, 'ai_primary')
        for alternative in (ai_match.get('alternatives') or [])[:3]:
            _append_parsed_query(queries, {
                'title': alternative.get('title'),
                'year': alternative.get('year') or parsed.get('year', ''),
            }, 'ai_alternative')
    return parsed, _dedupe_title_year_queries(queries)


def _smart_match_candidates_for_queries(queries, provider, rating_key=''):
    candidates = []
    for query in queries:
        if provider == 'tmdb':
            found = _smart_match_tmdb_candidates(query.get('title', ''), query.get('year', ''))
        else:
            found = _smart_match_plex_candidates(
                rating_key,
                query.get('title', ''),
                query.get('year', ''),
            )
        for candidate in found:
            candidates.append({
                **candidate,
                'query_sources': list(dict.fromkeys([
                    query.get('source', 'filename'),
                    *(candidate.get('query_sources', []) or []),
                ])),
            })
    return candidates


def _process_smart_match_context(context, provider, ai_match=None, ai_warning=''):
    abs_path, filename, _, record, plex_data = context
    parsed, queries = _smart_match_queries(abs_path, filename, record, plex_data, ai_match)
    known_identity = {
        'tmdb_id': record.get('tmdb_id') or plex_data.get('tmdb_id'),
        'imdb_id': record.get('imdb_id') or plex_data.get('imdb_id'),
        'plex_guid': record.get('plex_guid') or plex_data.get('plex_guid') or plex_data.get('guid'),
    }
    rating_key = str(plex_data.get('rating_key') or record.get('rating_key') or '')
    if provider == 'plex' and not rating_key:
        return {
            'path': abs_path,
            'filename': filename,
            'parsed': parsed,
            'query': queries[0] if queries else parsed,
            'query_sources': [query.get('source') for query in queries],
            'ai_status': 'classic_fallback' if ai_warning else 'not_used',
            'ai_warning': ai_warning,
            'reason': 'Plex does not expose a usable rating key for this file',
        }
    candidates = _smart_match_candidates_for_queries(queries, provider, rating_key)
    ranked = rank_candidates(queries, candidates, known_identity=known_identity)
    primary_query = next(
        (query for query in queries if query.get('source') == 'ai_primary'),
        queries[0] if queries else parsed,
    )
    if not ranked:
        return {
            'path': abs_path,
            'filename': filename,
            'parsed': parsed,
            'query': primary_query,
            'query_sources': [query.get('source') for query in queries],
            'ai_status': 'classic_fallback' if ai_warning else ('used' if ai_match else 'not_used'),
            'ai_warning': ai_warning,
            'reason': 'No provider candidates found',
        }
    candidate = ranked[0]
    return {
        'path': abs_path,
        'filename': filename,
        'provider': provider,
        'method': 'ai' if ai_match or ai_warning else 'classic',
        'parsed': parsed,
        'query': primary_query,
        'queries': queries,
        'query_sources': list(dict.fromkeys(
            source
            for query in queries
            for source in [query.get('source')]
            if source
        )),
        'candidate': candidate,
        'confidence': candidate.get('evidence_score', candidate.get('confidence', 0)),
        'evidence_score': candidate.get('evidence_score', candidate.get('confidence', 0)),
        'runner_up_gap': candidate.get('runner_up_gap', 0),
        'recommendation': candidate.get('recommendation', 'weak'),
        'reasons': candidate.get('reasons', []),
        'preselected': bool(candidate.get('preselected')),
        'rating_key': rating_key,
        'ai_status': 'classic_fallback' if ai_warning else ('used' if ai_match else 'not_used'),
        'ai_warning': ai_warning,
        'identity_revision': int(record.get('identity_revision', 0) or 0),
    }


def _process_smart_match_batch(paths, provider, method):
    contexts = [_smart_match_context(path) for path in paths]
    ai_result = {'matches': {}, 'errors': {}}
    item_ids = [f'item-{index}' for index in range(len(contexts))]
    if method == 'ai':
        ai_items = []
        for item_id, context in zip(item_ids, contexts):
            abs_path, filename, _, record, plex_data = context
            parsed = parse_release_filename(filename)
            ai_items.append({
                'id': item_id,
                'filename': filename,
                'folder_name': os.path.basename(os.path.dirname(abs_path)),
                'title_hint': record.get('candidate_title') or plex_data.get('plex_title') or parsed.get('title'),
                'year_hint': record.get('candidate_year') or plex_data.get('plex_year') or parsed.get('year'),
            })
        ai_result = _smart_match_ai_batch(ai_items)
    results = []
    for item_id, context in zip(item_ids, contexts):
        ai_match = ai_result.get('matches', {}).get(item_id) if method == 'ai' else None
        ai_warning = ai_result.get('errors', {}).get(item_id, '') if method == 'ai' else ''
        results.append(_process_smart_match_context(
            context,
            provider,
            ai_match=ai_match,
            ai_warning=ai_warning,
        ))
    return results


def _process_smart_match_path(path, provider, method):
    return _process_smart_match_batch([path], provider, method)[0]


def _get_smart_match_coordinator():
    global _smart_match_coordinator, _smart_match_store_dir
    store_dir = str(Path(_user_data_dir).resolve())
    if _smart_match_coordinator is None or _smart_match_store_dir != store_dir:
        store = _metadata_store()
        _smart_match_coordinator = SmartMatchCoordinator(
            load_state=store.get_smart_match_state,
            save_state=store.save_smart_match_state,
            process_path=_process_smart_match_path,
            process_batch=_process_smart_match_batch,
            batch_size=8,
            batch_delay=0.15,
        )
        _smart_match_store_dir = store_dir
    return _smart_match_coordinator


def _public_smart_match_state(state):
    state = dict(state or {})
    state.pop('paths', None)
    total = int(state.get('total', 0) or 0)
    processed = int(state.get('processed', 0) or 0)
    state['progress_percent'] = round((processed / total) * 100, 1) if total else 0
    state['ollama_available'] = bool(_ollama_url and _ollama_model)
    state['providers'] = {
        'tmdb': bool(_tmdb_key),
        'plex': bool(_plex_url and _plex_token),
    }
    return state


@app.route('/api/metadata/smart-match', methods=['GET', 'POST'])
def smart_match_start():
    if request.method == 'GET':
        return jsonify(_public_smart_match_state(_get_smart_match_coordinator().status()))
    body = request.get_json(silent=True) or {}
    paths = list(dict.fromkeys(str(path or '') for path in body.get('paths', []) if path))
    provider = str(body.get('provider', 'tmdb') or 'tmdb').lower()
    method = str(body.get('method', 'classic') or 'classic').lower()
    if not paths:
        return jsonify({'error': 'Select at least one file'}), 400
    if provider not in {'tmdb', 'plex'} or method not in {'classic', 'ai'}:
        return jsonify({'error': 'Unknown Smart Match provider or method'}), 400
    if provider == 'tmdb' and not _tmdb_key:
        return jsonify({'error': 'TMDB is not configured'}), 400
    if provider == 'plex' and not (_plex_url and _plex_token):
        return jsonify({'error': 'Plex is not configured'}), 400
    if method == 'ai' and not (_ollama_url and _ollama_model):
        return jsonify({'error': 'Ollama is not configured'}), 400
    store = _metadata_store()
    snapshot = store.snapshot()
    ineligible = []
    for path in paths:
        abs_path = os.path.abspath(path)
        if not _path_library_root(abs_path):
            return jsonify({'error': 'Path is outside the allowed movies directory'}), 403
        if not os.path.isfile(abs_path):
            return jsonify({'error': f'File not found: {path}'}), 404
        record = snapshot.get('files', {}).get(store._key(abs_path), {})
        resolved = resolve_authoritative_identity(record)
        if resolved.get('accepted'):
            ineligible.append({'path': abs_path, 'code': 'accepted'})
            continue
        if record.get('ingest_status') == 'pending' or record.get('metadata_status') == 'pending':
            ineligible.append({'path': abs_path, 'code': 'pending'})
            continue
        try:
            stat_result = os.stat(abs_path)
            if (
                record
                and record.get('size') is not None
                and int(record.get('size') or 0) != int(stat_result.st_size)
            ):
                ineligible.append({'path': abs_path, 'code': 'stale'})
        except OSError:
            ineligible.append({'path': abs_path, 'code': 'missing'})
    if ineligible:
        return jsonify({
            'error': 'One or more files are not eligible for Smart Match',
            'code': 'smart_match_ineligible',
            'items': ineligible,
        }), 409
    try:
        state = _get_smart_match_coordinator().start(
            paths,
            provider,
            method,
            background=body.get('background') is not False,
        )
    except RuntimeError as error:
        return jsonify({'error': str(error)}), 409
    return jsonify(_public_smart_match_state(state))


@app.route('/api/metadata/smart-match/<job_id>')
def smart_match_status(job_id):
    state = _get_smart_match_coordinator().status()
    if state.get('id') != job_id:
        return jsonify({'error': 'Smart Match job not found'}), 404
    return jsonify(_public_smart_match_state(state))


@app.route('/api/metadata/smart-match/<job_id>/cancel', methods=['POST'])
def smart_match_cancel(job_id):
    coordinator = _get_smart_match_coordinator()
    if coordinator.status().get('id') != job_id:
        return jsonify({'error': 'Smart Match job not found'}), 404
    return jsonify(_public_smart_match_state(coordinator.cancel()))


def _apply_plex_smart_match(proposal):
    candidate = proposal.get('candidate', {})
    rating_key = str(proposal.get('rating_key', '') or '')
    guid = str(candidate.get('guid', '') or '')
    if not rating_key or not guid:
        raise ValueError('Plex proposal is missing rating key or GUID')
    return _metadata_store().accept_plex_identity(proposal['path'], {
        'rating_key': rating_key,
        'plex_title': candidate.get('title') or candidate.get('name', ''),
        'plex_year': str(candidate.get('year', '') or ''),
        'plex_guid': guid,
    },
        source='smart_match_plex',
        decision_origin=DECISION_ORIGIN_SMART_MATCH,
        facts=_metadata_file_facts(proposal['path']),
    )


@app.route('/api/metadata/smart-match/<job_id>/apply', methods=['POST'])
def smart_match_apply(job_id):
    global _library_cache
    state = _get_smart_match_coordinator().status()
    if state.get('id') != job_id:
        return jsonify({'error': 'Smart Match job not found'}), 404
    selected = set((request.get_json(silent=True) or {}).get('proposal_ids', []))
    proposals = [proposal for proposal in state.get('proposals', []) if proposal.get('id') in selected]
    results = []
    for proposal in proposals:
        try:
            _, _, store, record, _ = _smart_match_context(proposal.get('path'))
            preview_revision = int(proposal.get('identity_revision', 0) or 0)
            current_revision = int(record.get('identity_revision', 0) or 0)
            if current_revision != preview_revision:
                raise ValueError('File identity changed after preview; run Smart Match again')
            candidate = proposal.get('candidate', {})
            if proposal.get('provider') == 'tmdb':
                metadata = _fetch_tmdb_metadata_by_id(
                    candidate.get('tmdb_id'),
                    store=store,
                    refresh=True,
                    match_source='manual_tmdb',
                ) or candidate
                store.accept_tmdb_identity(
                    proposal['path'],
                    metadata,
                    source='smart_match_tmdb',
                    decision_origin=DECISION_ORIGIN_SMART_MATCH,
                    facts=_metadata_file_facts(proposal['path']),
                )
            else:
                _apply_plex_smart_match(proposal)
            results.append({'id': proposal.get('id'), 'path': proposal.get('path'), 'success': True})
        except Exception as error:
            results.append({'id': proposal.get('id'), 'path': proposal.get('path'), 'success': False, 'error': str(error)})
    _library_cache = {}
    persisted = {
        **state,
        'status': 'applied',
        'applied_ids': [result['id'] for result in results if result['success']],
        'updated_at': time.time(),
    }
    _metadata_store().save_smart_match_state(persisted)
    return jsonify({
        'applied': sum(1 for result in results if result['success']),
        'failed': sum(1 for result in results if not result['success']),
        'results': results,
    })


@app.route('/api/metadata/smart-rename/preview', methods=['POST'])
def smart_rename_preview():
    body = request.get_json(silent=True) or {}
    items = body.get('items', [])
    if not items:
        return jsonify({'error': 'No rename items provided'}), 400
    token = uuid.uuid4().hex
    preview_items = []
    destinations = {}
    for item in items:
        old_path = os.path.abspath(str(item.get('path', '') or ''))
        blocked = ''
        if not _path_library_root(old_path):
            blocked = 'Path is outside the allowed movies directory'
        elif not os.path.isfile(old_path):
            blocked = 'File not found'
        extension = os.path.splitext(old_path)[1]
        release = item.get('release') or parse_release_filename(os.path.basename(old_path))
        new_filename = build_rename_filename(item.get('title'), item.get('year'), release, extension)
        new_path = os.path.join(os.path.dirname(old_path), new_filename)
        destination_key = _norm(new_path)
        if not blocked and not validate_rename_filename(new_filename):
            blocked = 'Generated filename is invalid'
        if not blocked and os.path.exists(new_path) and _norm(old_path) != destination_key:
            blocked = 'Destination file already exists'
        if not blocked and destination_key in destinations and destinations[destination_key] != _norm(old_path):
            blocked = 'Another selected file has the same destination'
        destinations[destination_key] = _norm(old_path)
        preview_items.append({
            'path': old_path,
            'old_filename': os.path.basename(old_path),
            'new_path': new_path,
            'new_filename': new_filename,
            'blocked': blocked,
        })
    preview = {'token': token, 'created_at': time.time(), 'items': preview_items}
    _metadata_store().save_smart_rename_preview(preview)
    return jsonify(preview)


@app.route('/api/metadata/smart-rename/apply', methods=['POST'])
def smart_rename_apply():
    global _library_cache
    body = request.get_json(silent=True) or {}
    preview = _metadata_store().get_smart_rename_preview()
    if not preview or body.get('token') != preview.get('token'):
        return jsonify({'error': 'Rename preview is missing or stale'}), 409
    selected = {_norm(path) for path in body.get('paths', [])}
    results = []
    renamed = 0
    for item in preview.get('items', []):
        if _norm(item.get('path')) not in selected:
            continue
        if item.get('blocked'):
            results.append({'path': item.get('path'), 'success': False, 'error': item['blocked']})
            continue
        old_path = item['path']
        new_path = item['new_path']
        try:
            if (
                not _path_library_root(old_path)
                or not _path_library_root(new_path)
                or not os.path.isfile(old_path)
            ):
                raise ValueError('File is no longer available inside the library')
            if os.path.exists(new_path) and _norm(old_path) != _norm(new_path):
                raise FileExistsError('Destination file already exists')
            os.rename(old_path, new_path)
            _migrate_library_path(old_path, new_path)
            results.append({'path': old_path, 'new_path': new_path, 'success': True})
            renamed += 1
        except Exception as error:
            results.append({'path': old_path, 'success': False, 'error': str(error)})
    if renamed:
        _library_cache = {}
        _plex_rescan()
    return jsonify({'renamed': renamed, 'failed': len(results) - renamed, 'results': results})


def _normalize_tmdb_collection_payload(data):
    parts = []
    for movie in data.get('parts', []) or []:
        parts.append(_normalize_tmdb_movie_summary(movie))
    parts.sort(key=lambda item: item.get('release_date') or item.get('year') or '')
    return {
        'id': str(data.get('id', '') or ''),
        'name': data.get('name', ''),
        'poster_url': _tmdb_image_url(data.get('poster_path')),
        'backdrop_url': _tmdb_image_url(data.get('backdrop_path'), 'w780'),
        'parts': parts,
    }


@app.route('/api/tmdb/person_movies')
def tmdb_person_movies():
    person_id = request.args.get('person_id', '').strip()
    role = request.args.get('role', 'actor').strip().lower()
    if role not in ('actor', 'director'):
        role = 'actor'
    if not person_id or not _tmdb_key:
        return jsonify({'error': 'person_id and TMDB key required'}), 400
    genre_id = request.args.get('genre', '').strip()
    min_votes_raw = request.args.get('min_votes', '').strip()
    year_from = request.args.get('year_from', '').strip()
    year_to = request.args.get('year_to', '').strip()
    min_rating_raw = request.args.get('min_rating', '').strip()
    sort_override = request.args.get('sort', '').strip()
    try:
        min_votes = int(min_votes_raw or 0)
    except ValueError:
        min_votes = 0
    try:
        min_rating = float(min_rating_raw or 0)
    except ValueError:
        min_rating = 0
    try:
        page = max(1, min(int(request.args.get('page', '1')), 10))
    except ValueError:
        page = 1
    _ensure_tmdb_genres()
    try:
        safe_id = urllib.parse.quote(str(person_id))
        url = (f"https://api.themoviedb.org/3/person/{safe_id}/movie_credits"
               f"?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US")
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = _json.loads(resp.read().decode())

        credits = raw.get('cast', []) or []
        if role == 'director':
            credits = [
                item for item in (raw.get('crew', []) or [])
                if item.get('job') == 'Director'
            ]

        movies = []
        seen = set()
        for item in credits:
            tmdb_id = str(item.get('id', '') or '')
            if not tmdb_id or tmdb_id in seen:
                continue
            seen.add(tmdb_id)
            movies.append(_normalize_tmdb_movie_summary(item))

        genre_name = ''
        if genre_id:
            try:
                genre_name = _tmdb_genres.get(int(genre_id), '')
            except ValueError:
                genre_name = ''

        def matches_criteria(movie):
            release_year = str(movie.get('release_date') or movie.get('year') or '')[:4]
            if genre_id and (not genre_name or genre_name not in (movie.get('genres') or [])):
                return False
            if min_votes and int(movie.get('tmdb_vote_count') or 0) < min_votes:
                return False
            if year_from and (not release_year or release_year < year_from):
                return False
            if year_to and (not release_year or release_year > year_to):
                return False
            if min_rating and float(movie.get('tmdb_rating') or 0) < min_rating:
                return False
            return True

        movies = [movie for movie in movies if matches_criteria(movie)]
        if sort_override == 'vote_average.desc':
            movies.sort(key=lambda movie: float(movie.get('tmdb_rating') or 0), reverse=True)
        elif sort_override == 'vote_count.desc':
            movies.sort(key=lambda movie: int(movie.get('tmdb_vote_count') or 0), reverse=True)
        elif sort_override == 'primary_release_date.desc':
            movies.sort(key=lambda movie: movie.get('release_date') or '', reverse=True)
        elif sort_override == 'title.asc':
            movies.sort(key=lambda movie: str(movie.get('title') or '').casefold())
        else:
            movies.sort(key=lambda movie: (
                float(movie.get('popularity') or 0),
                movie.get('release_date') or ''
            ), reverse=True)

        page_size = 20
        total_results = len(movies)
        total_pages = min(max(1, (total_results + page_size - 1) // page_size), 10)
        start = (page - 1) * page_size
        end = start + page_size
        return jsonify({
            'results': movies[start:end],
            'total_pages': total_pages,
            'page': page,
            'total_results': total_results,
            'role': role,
            'person_id': person_id,
        })
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid TMDB API key — check Settings.'}), 401
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tmdb/person')
def tmdb_person():
    person_id = request.args.get('person_id', '').strip()
    if not person_id or not _tmdb_key:
        return jsonify({'error': 'person_id and TMDB key required'}), 400
    try:
        safe_id = urllib.parse.quote(str(person_id))
        url = (f"https://api.themoviedb.org/3/person/{safe_id}"
               f"?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US")
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = _json.loads(resp.read().decode())
        return jsonify(_normalize_tmdb_person_details_payload(raw))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return jsonify({'error': 'Invalid TMDB API key - check Settings.'}), 401
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/tmdb/card-projections', methods=['POST'])
def tmdb_card_projections():
    body = request.get_json(silent=True) or {}
    raw_movies = body.get('movies')
    if not isinstance(raw_movies, list):
        return jsonify({'error': 'movies must be an array'}), 400

    movies = []
    seen = set()
    for raw_movie in raw_movies:
        if not isinstance(raw_movie, dict):
            continue
        key = str(raw_movie.get('key', '') or '').strip()
        tmdb_id = str(raw_movie.get('tmdb_id', '') or '').strip()
        poster_url = str(raw_movie.get('poster_url', '') or '').strip()
        if not key or key in seen or (tmdb_id and not tmdb_id.isdigit()):
            continue
        if not tmdb_id and not _plex_thumb_from_poster_url(poster_url):
            continue
        seen.add(key)
        movies.append({'key': key, 'tmdb_id': tmdb_id, 'poster_url': poster_url})
        if len(movies) == 50:
            break

    if not movies:
        return jsonify({'items': {}, 'requested': 0, 'resolved': 0})

    store = _metadata_store()
    items = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(movies))) as executor:
        futures = {
            executor.submit(_movie_card_projection, movie, store): movie['key']
            for movie in movies
        }
        for future in concurrent.futures.as_completed(futures):
            key = futures[future]
            try:
                projection = future.result()
            except Exception:
                projection = {}
            if projection:
                items[key] = projection

    return jsonify({
        'items': items,
        'requested': len(movies),
        'resolved': len(items),
        'catalog_generation': store.catalog.generation('media'),
    })


@app.route('/api/tmdb/details')
def tmdb_details():
    global _tmdb_library_cache
    tmdb_id = request.args.get('tmdb_id', '').strip()
    language = request.args.get('language', 'en-US').strip() or 'en-US'
    refresh = request.args.get('refresh') == '1'
    if not tmdb_id or not _tmdb_key:
        return jsonify({'error': 'tmdb_id and TMDB key required'}), 400
    if language not in {'en-US', 'ar-SA'}:
        return jsonify({'error': 'Unsupported TMDB display language'}), 400
    transient = language != 'en-US'
    try:
        cached = None if transient else _tmdb_library_cache.get(str(tmdb_id))
        if cached and not refresh and cached.get('data', {}).get('release_date'):
            data = dict(cached.get('data', {}))
            data['cached'] = True
            data['fetched_at'] = cached.get('fetched_at', 0)
            return jsonify(data)

        safe_id = urllib.parse.quote(str(tmdb_id))
        query = urllib.parse.urlencode({
            'api_key': _tmdb_key,
            'language': language,
            'append_to_response': 'credits,videos',
        })
        url = f"https://api.themoviedb.org/3/movie/{safe_id}?{query}"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = _json.loads(resp.read().decode())

        details = _normalize_tmdb_metadata(raw) if transient else {}
        details.update(_normalize_tmdb_details_payload(raw))
        details['tmdb_id'] = str(tmdb_id)
        fetched_at = time.time()
        if not transient:
            _tmdb_library_cache[str(tmdb_id)] = {'fetched_at': fetched_at, 'data': details}
            _save_tmdb_library_cache(_tmdb_library_cache)
        result = dict(details)
        result['cached'] = False
        result['fetched_at'] = fetched_at
        if transient:
            result['display_language'] = language
            result['transient'] = True
        return jsonify(result)
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _effective_tmdb_collection(collection_id, refresh=False):
    global _tmdb_collection_cache
    if not collection_id or not _tmdb_key:
        raise ValueError('collection_id and TMDB key required')
    cached = _tmdb_collection_cache.get(str(collection_id))
    if cached and not refresh:
        data = _curation_store().effective_collection(dict(cached.get('data', {})))
        data['cached'] = True
        data['fetched_at'] = cached.get('fetched_at', 0)
        return data
    safe_id = urllib.parse.quote(str(collection_id))
    url = (f"https://api.themoviedb.org/3/collection/{safe_id}"
           f"?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US")
    req = urllib.request.Request(url, headers={'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = _json.loads(resp.read().decode())
    tmdb_details = _normalize_tmdb_collection_payload(raw)
    fetched_at = time.time()
    _tmdb_collection_cache[str(collection_id)] = {'fetched_at': fetched_at, 'data': tmdb_details}
    _save_tmdb_collection_cache(_tmdb_collection_cache)
    result = _curation_store().effective_collection(tmdb_details)
    result['cached'] = False
    result['fetched_at'] = fetched_at
    return result


def _curation_payload(payload, store=None):
    store = store or _curation_store()
    return {
        **dict(payload or {}),
        'curation_generation': store.catalog.generation('curation'),
    }


@app.route('/api/tmdb/collection')
def tmdb_collection():
    collection_id = request.args.get('collection_id', '').strip()
    refresh = request.args.get('refresh') == '1'
    try:
        return jsonify(_curation_payload(_effective_tmdb_collection(collection_id, refresh=refresh)))
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _library_identity_records():
    store = _metadata_store()
    cached_items = _fresh_catalog_library_items(store)
    if cached_items is not None:
        return list(cached_items)
    return [
        _catalog_library_item(candidate, store, None)
        for candidate in store.catalog.store.library_projection(include_details=True)
        if candidate.get('path') and os.path.isfile(candidate['path'])
    ]


def _library_collection_from_catalog(collection_id, records=None):
    collection_id = str(collection_id or '').strip()
    if not collection_id:
        return None
    parts = []
    collection_metadata = {}
    seen = set()
    for record in records if records is not None else _library_identity_records():
        canonical = dict((record or {}).get('canonical_metadata') or {})
        collection = dict(canonical.get('collection') or {})
        if str(collection.get('id') or '') != collection_id:
            continue
        collection_metadata = collection_metadata or collection
        identity_key = str(canonical.get('tmdb_id') or record.get('path') or '').strip()
        if not identity_key or identity_key in seen:
            continue
        seen.add(identity_key)
        parts.append({
            'path': record.get('path', ''),
            'tmdb_id': str(canonical.get('tmdb_id') or ''),
            'imdb_id': str(canonical.get('imdb_id') or ''),
            'title': canonical.get('title', ''),
            'year': str(canonical.get('year') or ''),
            'release_date': canonical.get('release_date', ''),
            'poster_url': canonical.get('poster_url', ''),
        })
    if not parts:
        return None
    parts.sort(key=lambda part: (part.get('release_date') or f"{part.get('year', '')}-00-00", part.get('title', '')))
    effective = _curation_store().effective_collection({
        'id': collection_id,
        'name': collection_metadata.get('name', '') or f'Collection {collection_id}',
        'poster_url': collection_metadata.get('poster_url', ''),
        'backdrop_url': collection_metadata.get('backdrop_url', ''),
        'parts': parts,
    })
    if not effective.get('is_edited'):
        effective['source'] = 'library_sql'
    effective['detail_source'] = 'library_sql'
    return effective


@app.route('/api/library/collection/<collection_id>')
def library_collection(collection_id):
    try:
        records = _library_identity_records()
        collection = _library_collection_from_catalog(collection_id, records=records)
        if collection is None:
            collection = _effective_tmdb_collection(collection_id, refresh=request.args.get('refresh') == '1')
        resolution = resolve_collection_membership(collection, records)
        return jsonify({
            **collection,
            **resolution,
            'owned_count': len(resolution['owned_paths']),
            'unresolved_count': len(resolution['unresolved_parts']),
            'catalog_generation': _catalog_repository().generation('media'),
            'curation_generation': _catalog_repository().generation('curation'),
        })
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/collection', methods=['POST'])
def save_user_collection():
    body = request.get_json(force=True, silent=True) or {}
    collection_id = str(body.get('collection_id', '') or '').strip()
    original = body.get('original') or {}
    parts = body.get('parts') or []
    if not collection_id or not original.get('name'):
        return jsonify({'error': 'collection_id and original collection are required'}), 400
    try:
        store = _curation_store()
        return jsonify(_curation_payload(store.save_collection_override(collection_id, original, parts), store))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/collection/<collection_id>/reset', methods=['POST'])
def reset_user_collection(collection_id):
    try:
        store = _curation_store()
        reset = store.reset_collection(collection_id)
        return jsonify(_curation_payload({'success': True, 'reset': reset}, store))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/followed-releases', methods=['GET', 'POST', 'DELETE'])
def user_followed_releases():
    store = _curation_store()
    if request.method == 'GET':
        if request.args.get('check') == '1':
            return jsonify(_curation_payload(_check_followed_releases(), store))
        movies = _backfill_followed_release_dates(store, store.followed_all())
        return jsonify(_curation_payload({'movies': _sort_followed_releases(movies)}, store))
    body = request.get_json(force=True, silent=True) or {}
    movie = body.get('movie') or body
    try:
        if request.method == 'POST':
            followed = store.follow_movie(movie)
            return jsonify(_curation_payload({'movie': followed, 'movies': _sort_followed_releases(store.followed_all())}, store))
        removed = store.unfollow_movie(movie)
        return jsonify(_curation_payload({'success': True, 'removed': removed, 'movies': _sort_followed_releases(store.followed_all())}, store))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/user/followed-releases/check', methods=['POST'])
def check_user_followed_releases():
    try:
        return jsonify(_curation_payload(_check_followed_releases()))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _normalize_download_quality(value):
    text = str(value or '').strip().lower()
    return '4K' if text in {'4k', '2160p', 'uhd'} else '1080p'


def _effective_download_trusted_indexer_ids(indexers=None):
    if _download_indexer_mode == 'custom':
        return [str(value) for value in _download_trusted_indexers if str(value).strip()]
    available = indexers
    if available is None:
        try:
            available = _fetch_enabled_prowlarr_indexers()
        except Exception:
            available = []
    if _download_indexer_mode == 'all':
        return [str(indexer.get('id')) for indexer in available if indexer.get('id') is not None]
    return _effective_trusted_release_indexer_ids(available)


def _best_download_variant(variants, quality, trusted_ids):
    wanted = _normalize_download_quality(quality)
    trusted = {str(value) for value in trusted_ids or []}
    candidates = []
    for variant in variants or []:
        indexer_id = str(variant.get('indexer_id') or variant.get('indexer') or '')
        if trusted and indexer_id not in trusted:
            continue
        if _normalize_download_quality(variant.get('resolution')) != wanted:
            continue
        candidates.append(variant)
    candidates.sort(key=lambda item: (
        int(item.get('seeders') or 0),
        int(item.get('size') or item.get('size_bytes') or 0),
    ), reverse=True)
    return candidates[0] if candidates else None


@app.route('/api/sources/review/preview', methods=['POST'])
def source_review_preview():
    body = request.get_json(force=True, silent=True) or {}
    movies = body.get('movies') or []
    if not isinstance(movies, list) or not movies:
        return jsonify({'error': 'At least one movie is required'}), 400
    quality = _normalize_download_quality(body.get('quality') or _download_default_quality)
    try:
        enabled_indexers = _fetch_enabled_prowlarr_indexers() if _prowlarr_url and _prowlarr_key else []
    except Exception:
        enabled_indexers = []
    trusted_ids = _effective_download_trusted_indexer_ids(enabled_indexers)
    config = {'trusted_indexers': trusted_ids}
    rows = []
    blocked = []
    for movie in movies:
        payload = _normalize_curated_movie(movie)
        if not _download_job_has_stable_identity(payload):
            row = {
                **payload,
                'quality': quality,
                'selected': False,
                'status': 'identity_required',
                'variant': None,
                'reason': 'A TMDB or IMDb identity is required before download',
            }
            blocked.append(row)
            rows.append(row)
            continue
        if _curated_movie_is_owned(payload):
            row = {
                **payload,
                'quality': quality,
                'selected': False,
                'status': 'owned',
                'variant': None,
                'reason': 'Already in library',
            }
            blocked.append(row)
            rows.append(row)
            continue
        try:
            variants = _ai_control_source_search(payload, config)
        except Exception as error:
            variants = []
            payload['source_error'] = str(error)
        variant = _best_download_variant(variants, quality, trusted_ids)
        row = {
            **payload,
            'quality': quality,
            'selected': bool(variant),
            'status': 'ready' if variant else 'blocked',
            'variant': variant,
            'reason': '' if variant else payload.get('source_error') or f'No trusted {quality} source found',
        }
        if variant:
            rows.append(row)
        else:
            blocked.append(row)
            rows.append(row)
    return jsonify({
        'rows': rows,
        'blocked': blocked,
        'defaults': {
            'quality': quality,
            'download_indexer_mode': _download_indexer_mode,
            'trusted_indexers': trusted_ids,
        },
    })


@app.route('/api/sources/review/submit', methods=['POST'])
def source_review_submit():
    body = request.get_json(force=True, silent=True) or {}
    rows = body.get('rows') or []
    if not isinstance(rows, list):
        return jsonify({'error': 'Rows must be a list'}), 400
    selected = [
        row for row in rows
        if row.get('selected', True) is not False and row.get('status') == 'ready' and row.get('variant')
    ]
    if not selected:
        return jsonify({'error': 'No selected ready downloads were submitted'}), 400
    results = []
    for row in selected:
        if _curated_movie_is_owned(row):
            results.append({
                'movie': row.get('title', ''),
                'skipped': True,
                'reason': 'Already in library',
            })
            continue
        try:
            results.append({'movie': row.get('title', ''), 'result': _ai_control_submit_download(row)})
        except Exception as error:
            results.append({'movie': row.get('title', ''), 'error': str(error)})
    return jsonify({
        'submitted_count': len([result for result in results if not result.get('error') and not result.get('skipped')]),
        'skipped_count': len([result for result in results if result.get('skipped')]),
        'results': results,
    })


def _curated_movie_is_owned(movie):
    path = str((movie or {}).get('path') or '')
    if path and os.path.isfile(path) and _path_library_root(path):
        return True
    return bool(_find_owned_movie(movie or {}))


register_curation_routes(app, _curation_store, _curated_movie_is_owned)


_copy_export_jobs = {}
_copy_export_lock = threading.RLock()
_COPY_EXPORT_CHUNK_SIZE = 1024 * 1024


def _folder_browser_entry(path):
    return {
        'name': os.path.basename(os.path.normpath(path)) or path,
        'path': path,
        'type': 'folder',
    }


def _folder_browser_roots():
    candidates = []
    for path in _coerce_movie_dirs(_cfg):
        if os.path.isdir(path):
            candidates.append(path)
    home = Path.home()
    candidates.extend([
        str(home),
        str(home / 'Desktop'),
        str(home / 'Downloads'),
    ])
    if os.name == 'nt':
        for code in range(ord('A'), ord('Z') + 1):
            drive = f'{chr(code)}:\\'
            if os.path.isdir(drive):
                candidates.append(drive)
    seen = set()
    roots = []
    for path in candidates:
        try:
            resolved = str(Path(os.path.abspath(os.path.expanduser(path))).resolve())
        except OSError:
            continue
        key = os.path.normcase(os.path.normpath(resolved))
        if key in seen or not os.path.isdir(resolved):
            continue
        seen.add(key)
        roots.append(_folder_browser_entry(resolved))
    return sorted(roots, key=lambda entry: entry['name'].lower())


def _browse_system_folder(path):
    clean = str(path or '').strip()
    if not clean:
        return {
            'current_path': '',
            'parent': '',
            'roots': _folder_browser_roots(),
            'entries': [],
        }
    target = os.path.abspath(os.path.expanduser(clean))
    if not os.path.isdir(target):
        raise ValueError('Folder does not exist')
    current = str(Path(target).resolve())
    parent_path = os.path.dirname(current)
    parent = parent_path if parent_path and os.path.normcase(parent_path) != os.path.normcase(current) else ''
    entries = []
    try:
        with os.scandir(current) as scan:
            for entry in scan:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        entries.append(_folder_browser_entry(str(Path(entry.path).resolve())))
                except OSError:
                    continue
    except OSError as error:
        raise ValueError(f'Could not open folder: {error}')
    return {
        'current_path': current,
        'parent': parent,
        'roots': _folder_browser_roots(),
        'entries': sorted(entries, key=lambda entry: entry['name'].lower()),
    }


def _copy_export_job_snapshot(job_id):
    with _copy_export_lock:
        job = _copy_export_jobs.get(str(job_id))
        if not job:
            raise KeyError('Export job not found')
        public = {key: value for key, value in job.items() if key != 'cancel_event'}
        public['items'] = [dict(item) for item in job.get('items', [])]
        return public


def _set_copy_export_job(job_id, **updates):
    with _copy_export_lock:
        job = _copy_export_jobs[str(job_id)]
        job.update(updates)
        job['updated_at'] = time.time()


def _prepare_copy_export_destination(destination):
    clean = str(destination or '').strip()
    if not clean:
        raise ValueError('Destination folder is required')
    abs_destination = os.path.abspath(os.path.expanduser(clean))
    if os.path.isfile(abs_destination):
        raise ValueError('Destination must be a folder')
    os.makedirs(abs_destination, exist_ok=True)
    return abs_destination


def _copy_export_entry(movie, destination):
    normalized = _normalize_curated_movie(movie or {})
    title = normalized.get('title') or 'Untitled movie'
    source = normalized.get('path', '')
    entry = {
        'title': title,
        'year': normalized.get('year', ''),
        'source': source,
        'destination': '',
        'status': 'pending',
        'reason': '',
        'bytes_total': 0,
        'bytes_done': 0,
    }
    if not source:
        entry.update({'status': 'skipped', 'reason': 'No local file path'})
        return entry
    abs_source = os.path.abspath(source)
    entry['source'] = abs_source
    if not os.path.isfile(abs_source):
        entry.update({'status': 'skipped', 'reason': 'Local file is missing'})
        return entry
    if os.path.splitext(abs_source)[1].lower() not in VIDEO_EXTENSIONS:
        entry.update({'status': 'skipped', 'reason': 'Not a supported video file'})
        return entry
    destination_path = os.path.join(destination, os.path.basename(abs_source))
    entry['destination'] = destination_path
    if _norm(abs_source) == _norm(destination_path):
        entry.update({'status': 'skipped', 'reason': 'Source and destination are the same file'})
        return entry
    try:
        source_size = os.path.getsize(abs_source)
    except OSError:
        entry.update({'status': 'skipped', 'reason': 'Could not read local file'})
        return entry
    entry['bytes_total'] = source_size
    if os.path.exists(destination_path):
        try:
            existing_size = os.path.getsize(destination_path)
        except OSError:
            existing_size = -1
        reason = 'File already exists' if existing_size == source_size else 'Filename conflict exists'
        entry.update({'status': 'skipped', 'reason': reason})
    return entry


def _create_copy_export_job(movies, destination, start=True):
    abs_destination = _prepare_copy_export_destination(destination)
    items = [_copy_export_entry(movie, abs_destination) for movie in (movies or [])]
    if not items:
        raise ValueError('At least one movie is required')
    job_id = uuid.uuid4().hex
    pending_items = [item for item in items if item.get('status') == 'pending']
    skipped_items = [item for item in items if item.get('status') == 'skipped']
    job = {
        'id': job_id,
        'status': 'queued' if pending_items else 'completed',
        'destination': abs_destination,
        'total_count': len(items),
        'copyable_count': len(pending_items),
        'copied_count': 0,
        'skipped_count': len(skipped_items),
        'failed_count': 0,
        'bytes_total': sum(int(item.get('bytes_total') or 0) for item in pending_items),
        'bytes_done': 0,
        'current': '',
        'error': '',
        'items': items,
        'created_at': time.time(),
        'updated_at': time.time(),
        'cancel_event': threading.Event(),
    }
    with _copy_export_lock:
        _copy_export_jobs[job_id] = job
    if start and pending_items:
        threading.Thread(target=_run_copy_export_job, args=(job_id,), daemon=True).start()
    return _copy_export_job_snapshot(job_id)


def _mark_copy_export_item(job_id, index, **updates):
    with _copy_export_lock:
        job = _copy_export_jobs[str(job_id)]
        job['items'][index].update(updates)
        job['updated_at'] = time.time()


def _copy_file_with_progress(job_id, index, item):
    source = item['source']
    destination = item['destination']
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(source, 'rb') as src, open(destination, 'wb') as dst:
        while True:
            with _copy_export_lock:
                cancel_event = _copy_export_jobs[str(job_id)]['cancel_event']
            if cancel_event.is_set():
                raise InterruptedError('Copy cancelled')
            chunk = src.read(_COPY_EXPORT_CHUNK_SIZE)
            if not chunk:
                break
            dst.write(chunk)
            with _copy_export_lock:
                job = _copy_export_jobs[str(job_id)]
                item_state = job['items'][index]
                item_state['bytes_done'] = int(item_state.get('bytes_done') or 0) + len(chunk)
                job['bytes_done'] = int(job.get('bytes_done') or 0) + len(chunk)
                job['updated_at'] = time.time()
    shutil.copystat(source, destination)


def _run_copy_export_job(job_id):
    job_id = str(job_id)
    try:
        _set_copy_export_job(job_id, status='running')
        with _copy_export_lock:
            item_count = len(_copy_export_jobs[job_id].get('items', []))
        for index in range(item_count):
            with _copy_export_lock:
                job = _copy_export_jobs[job_id]
                item = dict(job['items'][index])
                if job['cancel_event'].is_set():
                    job['status'] = 'cancelled'
                    job['updated_at'] = time.time()
                    return _copy_export_job_snapshot(job_id)
            if item.get('status') != 'pending':
                continue
            if os.path.exists(item.get('destination', '')):
                _mark_copy_export_item(job_id, index, status='skipped', reason='File already exists')
                with _copy_export_lock:
                    _copy_export_jobs[job_id]['skipped_count'] += 1
                continue
            _mark_copy_export_item(job_id, index, status='copying')
            _set_copy_export_job(job_id, current=os.path.basename(item.get('source', '')))
            try:
                _copy_file_with_progress(job_id, index, item)
                _mark_copy_export_item(job_id, index, status='copied')
                with _copy_export_lock:
                    _copy_export_jobs[job_id]['copied_count'] += 1
            except InterruptedError:
                try:
                    if os.path.exists(item.get('destination', '')):
                        os.remove(item.get('destination', ''))
                except OSError:
                    pass
                _mark_copy_export_item(job_id, index, status='cancelled', reason='Copy cancelled')
                _set_copy_export_job(job_id, status='cancelled', current='')
                return _copy_export_job_snapshot(job_id)
            except Exception as error:
                _mark_copy_export_item(job_id, index, status='failed', reason=str(error))
                with _copy_export_lock:
                    _copy_export_jobs[job_id]['failed_count'] += 1
        final_status = 'completed'
        with _copy_export_lock:
            if _copy_export_jobs[job_id]['failed_count']:
                final_status = 'completed_with_errors'
        _set_copy_export_job(job_id, status=final_status, current='')
    except Exception as error:
        _set_copy_export_job(job_id, status='failed', error=str(error), current='')
    return _copy_export_job_snapshot(job_id)


@app.route('/api/library/export-jobs', methods=['POST'])
def library_export_jobs():
    body = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify(_create_copy_export_job(body.get('movies') or [], body.get('destination', '')))
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/library/export-jobs/<job_id>')
def library_export_job_detail(job_id):
    try:
        return jsonify(_copy_export_job_snapshot(job_id))
    except KeyError:
        return jsonify({'error': 'Export job not found'}), 404


@app.route('/api/library/export-jobs/<job_id>/cancel', methods=['POST'])
def library_export_job_cancel(job_id):
    with _copy_export_lock:
        job = _copy_export_jobs.get(str(job_id))
        if not job:
            return jsonify({'error': 'Export job not found'}), 404
        job['cancel_event'].set()
        if job.get('status') == 'queued':
            job['status'] = 'cancelled'
        job['updated_at'] = time.time()
    return jsonify(_copy_export_job_snapshot(job_id))


@app.route('/api/tmdb/imdb_id')
def tmdb_imdb_id():
    tmdb_id = request.args.get('tmdb_id', '').strip()
    if not tmdb_id or not _tmdb_key:
        return jsonify({'error': 'tmdb_id and TMDB key required'}), 400
    try:
        url = (f"https://api.themoviedb.org/3/movie/{urllib.parse.quote(str(tmdb_id))}"
               f"?api_key={urllib.parse.quote(_tmdb_key)}&language=en-US")
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read().decode())
        imdb_id = data.get('imdb_id', '')
        if not imdb_id:
            return jsonify({'error': 'No IMDB ID found for this title'}), 404
        return jsonify({'imdb_id': imdb_id})
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'TMDB returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Ollama / Pick My Movie ───────────────────────────────────────────────────

@app.route('/api/ollama/config', methods=['GET'])
def get_ollama_config():
    return jsonify({
        'url': _ollama_url,
        'model': _ollama_model,
        'candidate_limit': _ollama_candidate_limit,
    })


@app.route('/api/ollama/config', methods=['POST'])
def set_ollama_config():
    global _ollama_url, _ollama_model, _ollama_candidate_limit
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    if 'candidate_limit' in data:
        try:
            candidate_limit = int(data.get('candidate_limit'))
        except (TypeError, ValueError):
            return jsonify({'error': 'candidate_limit must be an integer from 1 to 50'}), 400
        if candidate_limit < OLLAMA_CANDIDATE_LIMIT_MIN or candidate_limit > OLLAMA_CANDIDATE_LIMIT_MAX:
            return jsonify({'error': 'candidate_limit must be an integer from 1 to 50'}), 400
        _ollama_candidate_limit = candidate_limit
    _ollama_url   = data.get('url', 'http://localhost:11434').strip().rstrip('/')
    _ollama_model = data.get('model', '').strip()
    _save_config(_all_config())
    return jsonify({'success': True})


@app.route('/api/ollama/test')
def ollama_test():
    url = request.args.get('url', _ollama_url).strip().rstrip('/')
    if not url:
        return jsonify({'error': 'No Ollama URL configured — add it in Settings.'}), 400
    try:
        req = urllib.request.Request(f"{url}/api/tags", headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            _json.loads(resp.read().decode())
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f'Cannot reach Ollama: {e}'}), 502


def _ollama_enrich_with_tmdb(title, year):
    """Search TMDB for a single title and return enriched movie dict. Returns None on failure."""
    if not _tmdb_key:
        return None
    _ensure_tmdb_genres()
    try:
        params = urllib.parse.urlencode({
            'query': title, 'api_key': _tmdb_key,
            'language': 'en-US', 'page': 1, 'include_adult': 'false',
            **(({'year': year}) if year else {})
        })
        url = f"https://api.themoviedb.org/3/search/movie?{params}"
        req = urllib.request.Request(url, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
        results = data.get('results', [])
        if not results:
            return None
        m = results[0]
        poster_path = m.get('poster_path', '')
        release = m.get('release_date', '') or ''
        yr = release[:4] if release else year
        genre_ids = m.get('genre_ids', [])
        genres = [_tmdb_genres[gid] for gid in genre_ids if gid in _tmdb_genres][:3]
        vote = m.get('vote_average', 0)
        lang = m.get('original_language', '')
        country_code = _LANG_COUNTRY.get(lang, '')
        return {
            'tmdb_id':      m.get('id'),
            'title':        m.get('title', title),
            'year':         yr,
            'poster_url':   f"https://image.tmdb.org/t/p/w342{poster_path}" if poster_path else '',
            'genres':       genres,
            'tmdb_rating':  f"{vote:.1f}" if isinstance(vote, (int, float)) and vote else '',
            'tmdb_vote_count': int(m.get('vote_count', 0) or 0),
            'plot':         m.get('overview', ''),
            'language':     _LANG_NAMES.get(lang, lang.upper() if lang else ''),
            'country':      country_code,
            'country_flag': _country_flag(country_code),
            'release_date': release,
        }
    except Exception:
        return None


def _ollama_candidate_key(title, year):
    clean_title = _norm_movie_title(str(title or '').strip())
    clean_year = str(year or '').strip()
    year_match = re.search(r'\b(19|20)\d{2}\b', clean_year)
    return clean_title, year_match.group(0) if year_match else clean_year


@app.route('/api/ollama/recommend', methods=['POST'])
def ollama_recommend():
    if not _ollama_url or not _ollama_model:
        return jsonify({'error': 'Ollama not configured — add URL and model in Settings.'}), 400
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    prompt = data.get('prompt', '').strip()
    if not prompt:
        return jsonify({'error': 'Prompt cannot be empty.'}), 400

    candidate_limit = _coerce_ollama_candidate_limit(_ollama_candidate_limit)
    system_msg = (
        'You are a movie recommendation expert. '
        'The user will describe a movie or what they want to watch by mood, memory, feeling, actors, or any detail. '
        'Return ONLY valid JSON with this exact shape: '
        '{"recommendations":[{"title":"...","year":"...","reason":"one sentence why this matches"}]}. '
        f'Return at most {candidate_limit} feature-length movie candidates. '
        'Exclude TV series, miniseries, episodes, books, games, and unreleased films. '
        'Use the official movie title and release year. '
        'No markdown, no explanation, no extra text — only the JSON object.'
    )

    body = _json.dumps({
        'model': _ollama_model,
        'messages': [
            {'role': 'system', 'content': system_msg},
            {'role': 'user',   'content': prompt}
        ],
        'stream': False,
        'format': 'json'
    }).encode()

    try:
        req = urllib.request.Request(
            f"{_ollama_url}/api/chat",
            data=body,
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = _json.loads(resp.read().decode())
        parsed = _json.loads(raw['message']['content'])
        recs = parsed.get('recommendations', [])
    except _json.JSONDecodeError:
        return jsonify({'error': 'Ollama returned invalid JSON. Try a different prompt.'}), 502
    except urllib.error.HTTPError as e:
        return jsonify({'error': f'Ollama returned HTTP {e.code}'}), 502
    except Exception as e:
        return jsonify({'error': f'Cannot reach Ollama: {e}'}), 502

    results = []
    seen_candidates = set()
    for rec in recs:
        title  = rec.get('title', '').strip()
        year   = rec.get('year', '').strip()
        reason = rec.get('reason', '')
        if not title:
            continue
        candidate_key = _ollama_candidate_key(title, year)
        if candidate_key in seen_candidates:
            continue
        seen_candidates.add(candidate_key)
        enriched = _ollama_enrich_with_tmdb(title, year)
        if enriched:
            enriched['reason'] = reason
            results.append(enriched)
        elif _tmdb_key:
            continue
        else:
            results.append({'title': title, 'year': year, 'reason': reason,
                            'poster_url': '', 'genres': [], 'tmdb_rating': '',
                            'tmdb_vote_count': 0, 'plot': '', 'tmdb_id': None})
        if len(results) >= candidate_limit:
            break

    return jsonify({'results': results, 'model': _ollama_model})


if __name__ == '__main__':
    _start_library_reconcile()
    threading.Thread(
        target=_qbittorrent_import_monitor.run_forever,
        args=(lambda: _qbt_mode == 'embedded',),
        daemon=True,
    ).start()
    _startup_metrics['background_queue_started'] = True
    _startup_metrics['api_ready_ms'] = round((time.perf_counter() - _process_started_at) * 1000, 3)
    artwork_timer = threading.Timer(1.0, _run_startup_artwork_backfill)
    artwork_timer.daemon = True
    artwork_timer.start()
    app.run(debug=False, port=5000, use_reloader=False)
