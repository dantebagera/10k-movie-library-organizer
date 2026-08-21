import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path

from .iptv_movie_classifier import CLASSIFIER_VERSION
from .iptv_tmdb import MATCHER_VERSION, PARSER_VERSION, combine_provider_title_evidence


MOVIE_SCHEMA_VERSION = 4
STATUS_PROJECTION_VERSION = 1
SEARCH_VERSION = 1
CONTROL_BUSY_TIMEOUT_MS = 250
ENRICHMENT_STAGE_BATCH_SIZE = 100
ENRICHMENT_CLUSTER_MEMBER_LIMIT = 8
CATEGORIES = {"film", "sports", "plays", "music", "misc", "unclassified"}
ACCEPTED_STATES = {"matched-auto", "matched-manual"}
MATCH_STATES = {
    "unprocessed",
    "provider-id-pending",
    "search-pending",
    "matched-auto",
    "matched-manual",
    "ambiguous",
    "unmatched",
    "error-retryable",
    "error-terminal",
}
STATUS_COUNTER_COLUMNS = (
    "available_sources", "unavailable_sources",
    "classified_film", "classified_sports", "classified_plays",
    "classified_music", "classified_misc", "classified_unclassified",
    "classification_review", "classification_manual_locks",
    "match_unprocessed", "match_provider_id_pending", "match_search_pending",
    "matched_auto", "matched_manual", "match_ambiguous", "match_unmatched",
    "match_error_retryable", "match_error_terminal", "match_manual_locks",
    "stale", "needs_review", "evaluated", "automatic_remaining", "grouped_member_sources",
    "queue_pending", "queue_running", "queue_done", "queue_cancelled", "queue_failed",
)
PROVIDER_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MOVIE_KEY_RE = re.compile(r"^(tmdb:[1-9][0-9]*|source:s_[0-9a-f]{24})$")
ARABIC_TEXT_RE = re.compile(r"[\u0600-\u06ff]")
ARABIC_MARKS_RE = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")


def _text(value):
    return str(value or "").strip()


def normalize_search_text(value):
    """Normalize lookup text without changing the provider's display evidence."""
    value = unicodedata.normalize("NFKC", _text(value)).casefold().replace("ـ", "")
    value = ARABIC_MARKS_RE.sub("", value)
    value = "".join(character if character.isalnum() else " " for character in value)
    return re.sub(r"\s+", " ", value).strip()


def movie_work_identity(raw_title, raw_year=0, detail_title="", detail_year=0):
    """Return the parser-owned title/year identity used for bounded sibling work."""
    parsed = combine_provider_title_evidence(
        raw_title, raw_year, detail_title, detail_year,
    )
    return normalize_search_text(parsed.get("primary_alias")), _integer(parsed.get("year"))


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _arabic_title(*values):
    candidates = [_text(value) for value in values if _text(value)]
    return next((value for value in candidates if ARABIC_TEXT_RE.search(value)), candidates[0] if candidates else "")


def _arabic_text(value):
    value = _text(value)
    return value if ARABIC_TEXT_RE.search(value) else ""


def _provider_year(value, title=""):
    match = re.search(
        r"\b(19\d{2}|20\d{2}|21\d{2})\b",
        f"{_text(value)} {_text(title)}",
    )
    return int(match.group(1)) if match else 0


def source_key(source_id):
    value = _text(source_id)
    if not value:
        raise ValueError("An IPTV movie source ID is required")
    return "s_" + hashlib.blake2b(value.encode("utf-8", "surrogatepass"), digest_size=12).hexdigest()


def validate_movie_key(movie_key):
    movie_key = _text(movie_key)
    if not MOVIE_KEY_RE.fullmatch(movie_key):
        raise KeyError("IPTV movie was not found")
    return movie_key


def _source_claims(title, playlist_name):
    evidence = f"{_text(title)} {_text(playlist_name)}".casefold()
    if re.search(r"\b(?:4k|2160p|uhd)\b", evidence):
        quality = "4K"
    elif re.search(r"\b(?:1080p|fhd)\b", evidence):
        quality = "1080p"
    elif re.search(r"\b720p\b", evidence):
        quality = "720p"
    elif re.search(r"\b(?:hdcam|camrip|cam)\b", evidence):
        quality = "HDCAM"
    elif re.search(r"\bhd\b", evidence):
        quality = "HD"
    else:
        quality = ""
    dubbed = bool(re.search(r"\b(?:dubbed|dublaj|مدبلج)\b", evidence))
    subtitled = bool(re.search(r"\b(?:subbed|subtitle|subtitles|مترجم)\b", evidence))
    return quality, dubbed, subtitled


class IPTVMovieStore:
    """One provider's enriched IPTV movie database.

    The database path is fixed to the validated provider root. No provider ID is
    stored in rows because the file itself is the provider boundary.
    """

    def __init__(self, provider_root, provider_id):
        self.provider_id = _text(provider_id)
        if not PROVIDER_ID_RE.fullmatch(self.provider_id):
            raise ValueError("A valid IPTV provider ID is required")
        self.root = Path(provider_root).resolve()
        if self.root.name != self.provider_id:
            raise ValueError("The IPTV movie database must be inside its provider root")
        self.database_path = (self.root / "movies.sqlite").resolve()
        if self.database_path.parent != self.root:
            raise ValueError("The IPTV movie database path escaped its provider root")
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._migration_backup = None
        existing_version = self.inspect_schema_version(self.database_path)
        if existing_version in {1, 2, 3}:
            self._migration_backup = self._create_migration_backup()
        try:
            self._initialize()
            self._enable_wal()
        except Exception:
            if self._migration_backup:
                shutil.copy2(self._migration_backup, self.database_path)
            raise

    def _enable_wal(self):
        """Persist reader/writer concurrency for responsive status and browse paths."""
        connection = sqlite3.connect(self.database_path, timeout=5)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
        finally:
            connection.close()

    @staticmethod
    def inspect_schema_version(database_path):
        database_path = Path(database_path).resolve()
        if not database_path.is_file():
            return 0
        connection = sqlite3.connect(
            f"file:{database_path.as_posix()}?mode=ro&immutable=1", uri=True, timeout=5
        )
        try:
            row = connection.execute(
                "SELECT value FROM movie_meta WHERE key='schema_version'"
            ).fetchone()
            return _integer(row[0]) if row else 0
        except sqlite3.DatabaseError:
            return 0
        finally:
            connection.close()

    @classmethod
    def migrate_explicit(cls, provider_root, provider_id, *, expected_version=3):
        """Run an approval-gated provider-local migration; never used by GET paths."""
        database_path = (Path(provider_root).resolve() / "movies.sqlite").resolve()
        current = cls.inspect_schema_version(database_path)
        if current != _integer(expected_version):
            raise RuntimeError(
                f"Expected IPTV Movies schema v{int(expected_version)}, found v{current}"
            )
        return cls(provider_root, provider_id)

    def _create_migration_backup(self):
        backup_root = self.root / "migration-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        version = self.inspect_schema_version(self.database_path)
        backup = backup_root / f"movies-schema-v{version}-{stamp}-{uuid.uuid4().hex[:8]}.sqlite"
        shutil.copy2(self.database_path, backup)
        if hashlib.sha256(self.database_path.read_bytes()).digest() != hashlib.sha256(backup.read_bytes()).digest():
            backup.unlink(missing_ok=True)
            raise RuntimeError("The IPTV movie migration backup could not be verified")
        return backup

    def rollback_migration(self):
        if not self._migration_backup or not Path(self._migration_backup).is_file():
            raise RuntimeError("No provider-local IPTV movie migration backup is available")
        temporary = self.database_path.with_name(f".{self.database_path.name}.{uuid.uuid4().hex}.restore")
        shutil.copy2(self._migration_backup, temporary)
        os.replace(temporary, self.database_path)
        return str(self._migration_backup)

    def _connect(self, *, control=False):
        timeout_ms = CONTROL_BUSY_TIMEOUT_MS if control else 5000
        connection = sqlite3.connect(self.database_path, timeout=timeout_ms / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(f"PRAGMA busy_timeout={timeout_ms}")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def connection(self, immediate=False, *, control=False):
        connection = self._connect(control=control)
        try:
            if immediate:
                connection.execute("BEGIN IMMEDIATE")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self):
        with self._lock, self.connection(immediate=True) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS movie_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS movie_sources (
                    source_key TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL UNIQUE,
                    playlist_id TEXT NOT NULL DEFAULT '',
                    playlist_name TEXT NOT NULL DEFAULT '',
                    provider_title TEXT NOT NULL,
                    sort_title TEXT NOT NULL,
                    provider_year INTEGER NOT NULL DEFAULT 0,
                    provider_rating REAL NOT NULL DEFAULT 0,
                    provider_poster_url TEXT NOT NULL DEFAULT '',
                    provider_backdrop_url TEXT NOT NULL DEFAULT '',
                    provider_plot TEXT NOT NULL DEFAULT '',
                    provider_cast TEXT NOT NULL DEFAULT '',
                    provider_director TEXT NOT NULL DEFAULT '',
                    provider_genre TEXT NOT NULL DEFAULT '',
                    provider_duration TEXT NOT NULL DEFAULT '',
                    container_extension TEXT NOT NULL DEFAULT '',
                    provider_tmdb_id INTEGER NOT NULL DEFAULT 0,
                    added TEXT NOT NULL DEFAULT '',
                    position INTEGER NOT NULL DEFAULT 0,
                    quality_claim TEXT NOT NULL DEFAULT '',
                    dubbed_claim INTEGER NOT NULL DEFAULT 0,
                    subtitled_claim INTEGER NOT NULL DEFAULT 0,
                    available INTEGER NOT NULL DEFAULT 1,
                    source_generation INTEGER NOT NULL DEFAULT 0,
                    watched_position REAL NOT NULL DEFAULT 0,
                    watched_duration REAL NOT NULL DEFAULT 0,
                    watched_completed INTEGER NOT NULL DEFAULT 0,
                    last_watched REAL NOT NULL DEFAULT 0,
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_movie_sources_playlist
                    ON movie_sources(available, playlist_id, position);
                CREATE INDEX IF NOT EXISTS idx_movie_sources_title
                    ON movie_sources(available, sort_title, source_key);
                CREATE INDEX IF NOT EXISTS idx_movie_sources_claims
                    ON movie_sources(available, quality_claim, dubbed_claim, subtitled_claim);
                CREATE TABLE IF NOT EXISTS source_matches (
                    source_key TEXT PRIMARY KEY,
                    state TEXT NOT NULL DEFAULT 'unprocessed',
                    tmdb_id INTEGER,
                    method TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL DEFAULT 0,
                    manual_lock INTEGER NOT NULL DEFAULT 0,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    error_code TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (source_key) REFERENCES movie_sources(source_key) ON DELETE CASCADE,
                    CHECK (state IN ('unprocessed','provider-id-pending','search-pending','matched-auto','matched-manual','ambiguous','unmatched','error-retryable','error-terminal'))
                );
                CREATE INDEX IF NOT EXISTS idx_source_matches_state ON source_matches(state, manual_lock);
                CREATE INDEX IF NOT EXISTS idx_source_matches_tmdb ON source_matches(tmdb_id, state);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_source_matches_accepted_identity
                    ON source_matches(source_key, tmdb_id)
                    WHERE state IN ('matched-auto','matched-manual') AND tmdb_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS tmdb_movies (
                    tmdb_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    original_title TEXT NOT NULL DEFAULT '',
                    plot TEXT NOT NULL DEFAULT '',
                    poster_url TEXT NOT NULL DEFAULT '',
                    backdrop_url TEXT NOT NULL DEFAULT '',
                    rating REAL NOT NULL DEFAULT 0,
                    vote_count INTEGER NOT NULL DEFAULT 0,
                    release_date TEXT NOT NULL DEFAULT '',
                    year INTEGER NOT NULL DEFAULT 0,
                    runtime INTEGER NOT NULL DEFAULT 0,
                    original_language TEXT NOT NULL DEFAULT '',
                    certification TEXT NOT NULL DEFAULT '',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tmdb_movies_title ON tmdb_movies(title, tmdb_id);
                CREATE INDEX IF NOT EXISTS idx_tmdb_movies_year_rating ON tmdb_movies(year, rating, tmdb_id);
                CREATE TABLE IF NOT EXISTS genres (genre_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS movie_genres (
                    tmdb_id INTEGER NOT NULL, genre_id INTEGER NOT NULL,
                    PRIMARY KEY (tmdb_id, genre_id),
                    FOREIGN KEY (tmdb_id) REFERENCES tmdb_movies(tmdb_id) ON DELETE CASCADE,
                    FOREIGN KEY (genre_id) REFERENCES genres(genre_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS people (person_id INTEGER PRIMARY KEY, name TEXT NOT NULL, profile_url TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS movie_credits (
                    tmdb_id INTEGER NOT NULL, person_id INTEGER NOT NULL,
                    department TEXT NOT NULL, job TEXT NOT NULL DEFAULT '', character_name TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (tmdb_id, person_id, department, job, character_name),
                    FOREIGN KEY (tmdb_id) REFERENCES tmdb_movies(tmdb_id) ON DELETE CASCADE,
                    FOREIGN KEY (person_id) REFERENCES people(person_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_movie_credits_person ON movie_credits(person_id, department, tmdb_id);
                CREATE TABLE IF NOT EXISTS keywords (keyword_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS movie_keywords (
                    tmdb_id INTEGER NOT NULL, keyword_id INTEGER NOT NULL,
                    PRIMARY KEY (tmdb_id, keyword_id),
                    FOREIGN KEY (tmdb_id) REFERENCES tmdb_movies(tmdb_id) ON DELETE CASCADE,
                    FOREIGN KEY (keyword_id) REFERENCES keywords(keyword_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS collections (collection_id INTEGER PRIMARY KEY, name TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS movie_collections (
                    tmdb_id INTEGER NOT NULL PRIMARY KEY, collection_id INTEGER NOT NULL,
                    FOREIGN KEY (tmdb_id) REFERENCES tmdb_movies(tmdb_id) ON DELETE CASCADE,
                    FOREIGN KEY (collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS movie_languages (
                    tmdb_id INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (tmdb_id, code),
                    FOREIGN KEY (tmdb_id) REFERENCES tmdb_movies(tmdb_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS movie_countries (
                    tmdb_id INTEGER NOT NULL, code TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (tmdb_id, code),
                    FOREIGN KEY (tmdb_id) REFERENCES tmdb_movies(tmdb_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS movie_list_memberships (
                    list_id TEXT NOT NULL,
                    movie_key TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    added_at REAL NOT NULL,
                    source_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (list_id, movie_key)
                );
                CREATE INDEX IF NOT EXISTS idx_movie_membership_movie ON movie_list_memberships(movie_key, list_id);
                CREATE TABLE IF NOT EXISTS enrichment_queue (
                    source_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    FOREIGN KEY (source_key) REFERENCES movie_sources(source_key) ON DELETE CASCADE,
                    CHECK (status IN ('pending','running','done','cancelled','failed'))
                );
                CREATE INDEX IF NOT EXISTS idx_enrichment_queue_next ON enrichment_queue(status, next_attempt_at, updated_at);
                """
            )
            version = connection.execute(
                "SELECT value FROM movie_meta WHERE key='schema_version'"
            ).fetchone()
            current_version = _integer(version[0]) if version else 0
            if current_version not in {0, 1, 2, 3, MOVIE_SCHEMA_VERSION}:
                raise RuntimeError("The IPTV movie database has an unsupported schema")
            if current_version in {0, 1}:
                self._migrate_schema_v2(connection)
            if current_version in {0, 1, 2}:
                self._migrate_schema_v3(connection)
            if current_version != MOVIE_SCHEMA_VERSION:
                self._migrate_schema_v4(connection)
            defaults = {
                "schema_version": str(MOVIE_SCHEMA_VERSION),
                "source_catalog_generation": "0",
                "movie_generation": "0",
                "worker_state": "idle",
                "worker_command": "idle",
                "worker_pid": "0",
                "worker_error": "",
                "worker_started_at": "0",
                "worker_finished_at": "0",
                "parser_version": str(PARSER_VERSION),
                "matcher_version": str(MATCHER_VERSION),
                "classifier_version": str(CLASSIFIER_VERSION),
                "search_version": str(SEARCH_VERSION),
                "status_projection_version": str(STATUS_PROJECTION_VERSION),
            }
            connection.executemany(
                "INSERT OR IGNORE INTO movie_meta(key,value) VALUES (?,?)",
                defaults.items(),
            )
        if current_version == 1:
            self.repair_relationships_from_snapshots()

    @staticmethod
    def _columns(connection, table):
        return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}

    @classmethod
    def _add_column(cls, connection, table, definition):
        name = definition.split()[0]
        if name not in cls._columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def _migrate_schema_v2(self, connection):
        self._add_column(connection, "source_matches", "parser_version INTEGER NOT NULL DEFAULT 1")
        self._add_column(connection, "source_matches", "matcher_version INTEGER NOT NULL DEFAULT 1")
        self._add_column(connection, "source_matches", "terminal_at REAL NOT NULL DEFAULT 0")
        self._add_column(connection, "source_matches", "stale INTEGER NOT NULL DEFAULT 0")
        self._add_column(connection, "tmdb_movies", "imdb_id TEXT NOT NULL DEFAULT ''")
        self._add_column(connection, "enrichment_queue", "priority INTEGER NOT NULL DEFAULT 0")
        self._add_column(connection, "enrichment_queue", "work_key TEXT NOT NULL DEFAULT ''")
        self._add_column(connection, "enrichment_queue", "claimed_at REAL NOT NULL DEFAULT 0")
        self._add_column(connection, "enrichment_queue", "completed_at REAL NOT NULL DEFAULT 0")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tmdb_movie_localizations (
                tmdb_id INTEGER NOT NULL,
                locale TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                original_title TEXT NOT NULL DEFAULT '',
                plot TEXT NOT NULL DEFAULT '',
                poster_url TEXT NOT NULL DEFAULT '',
                backdrop_url TEXT NOT NULL DEFAULT '',
                genres_json TEXT NOT NULL DEFAULT '[]',
                collection_json TEXT NOT NULL DEFAULT '{}',
                credits_json TEXT NOT NULL DEFAULT '{}',
                raw_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL NOT NULL,
                PRIMARY KEY (tmdb_id, locale),
                FOREIGN KEY (tmdb_id) REFERENCES tmdb_movies(tmdb_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS projection_jobs (
                job_id INTEGER PRIMARY KEY CHECK (job_id=1),
                state TEXT NOT NULL DEFAULT 'idle',
                phase TEXT NOT NULL DEFAULT '',
                source_generation INTEGER NOT NULL DEFAULT 0,
                previous_generation INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                processed INTEGER NOT NULL DEFAULT 0,
                checkpoint INTEGER NOT NULL DEFAULT 0,
                lease_token TEXT NOT NULL DEFAULT '',
                lease_expires_at REAL NOT NULL DEFAULT 0,
                heartbeat_at REAL NOT NULL DEFAULT 0,
                started_at REAL NOT NULL DEFAULT 0,
                finished_at REAL NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT ''
            );
            INSERT OR IGNORE INTO projection_jobs(job_id) VALUES (1);
            CREATE TABLE IF NOT EXISTS worker_lease (
                lease_id INTEGER PRIMARY KEY CHECK (lease_id=1),
                token TEXT NOT NULL DEFAULT '',
                pid INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'idle',
                command TEXT NOT NULL DEFAULT 'idle',
                consent INTEGER NOT NULL DEFAULT 0,
                restart_confirmation_required INTEGER NOT NULL DEFAULT 0,
                diagnostic_limit INTEGER NOT NULL DEFAULT 0,
                heartbeat_at REAL NOT NULL DEFAULT 0,
                lease_expires_at REAL NOT NULL DEFAULT 0,
                started_at REAL NOT NULL DEFAULT 0,
                finished_at REAL NOT NULL DEFAULT 0,
                checkpoint INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                retry_reason TEXT NOT NULL DEFAULT '',
                backoff_until REAL NOT NULL DEFAULT 0
            );
            INSERT OR IGNORE INTO worker_lease(lease_id) VALUES (1);
            CREATE INDEX IF NOT EXISTS idx_enrichment_queue_priority
                ON enrichment_queue(status, next_attempt_at, priority DESC, updated_at, source_key);
            CREATE INDEX IF NOT EXISTS idx_source_matches_versions
                ON source_matches(stale, manual_lock, matcher_version, state);
            """
        )
        connection.execute(
            """UPDATE source_matches SET
                   parser_version=CASE WHEN parser_version<=0 THEN 1 ELSE parser_version END,
                   matcher_version=CASE WHEN matcher_version<=0 THEN 1 ELSE matcher_version END,
                   terminal_at=CASE
                     WHEN terminal_at<=0 AND state IN ('matched-auto','matched-manual','ambiguous','unmatched','error-terminal')
                     THEN updated_at ELSE terminal_at END"""
        )
        connection.execute(
            """UPDATE source_matches SET parser_version=?,matcher_version=?,stale=0
               WHERE state IN ('matched-auto','matched-manual','error-terminal') OR manual_lock=1""",
            (PARSER_VERSION, MATCHER_VERSION),
        )
        connection.execute(
            """UPDATE source_matches SET stale=1
               WHERE manual_lock=0 AND state IN ('ambiguous','unmatched')
                 AND (parser_version<>? OR matcher_version<>?)""",
            (PARSER_VERSION, MATCHER_VERSION),
        )
        source_count = connection.execute(
            "SELECT COUNT(*) FROM movie_sources WHERE available=1"
        ).fetchone()[0]
        source_generation = _integer(self._meta(connection, "source_catalog_generation", 0))
        if source_count:
            projected_at = _number(self._meta(connection, "source_projected_at", 0))
            connection.execute(
                """UPDATE projection_jobs SET state='complete',phase='',source_generation=?,
                       previous_generation=?,total=?,processed=?,checkpoint=?,lease_token='',
                       lease_expires_at=0,heartbeat_at=?,finished_at=?,error=''
                   WHERE job_id=1""",
                (
                    source_generation, source_generation, source_count, source_count,
                    source_count, projected_at, projected_at,
                ),
            )
        self._set_meta(connection, "schema_version", MOVIE_SCHEMA_VERSION)

    def _migrate_schema_v3(self, connection):
        """Add smart Movies ownership while preserving v2 provider state.

        `provider_title` and `provider_year` remain the authoritative raw catalog
        evidence.  The v2 values are retained as detail evidence before raw
        identity is reconstructed from the preserved catalog payload.
        """
        self._add_column(connection, "movie_sources", "detail_title TEXT NOT NULL DEFAULT ''")
        self._add_column(connection, "movie_sources", "detail_sort_title TEXT NOT NULL DEFAULT ''")
        self._add_column(connection, "movie_sources", "detail_year INTEGER NOT NULL DEFAULT 0")
        self._add_column(connection, "movie_sources", "detail_json TEXT NOT NULL DEFAULT '{}'")
        self._add_column(connection, "source_matches", "classifier_version INTEGER NOT NULL DEFAULT 0")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS playlist_classifications (
                playlist_id TEXT PRIMARY KEY,
                playlist_name TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'unclassified',
                status TEXT NOT NULL DEFAULT 'review',
                confidence REAL NOT NULL DEFAULT 0,
                method TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                classifier_version INTEGER NOT NULL DEFAULT 0,
                mixed INTEGER NOT NULL DEFAULT 0,
                manual_lock INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_classifications (
                source_key TEXT PRIMARY KEY,
                category TEXT NOT NULL DEFAULT 'unclassified',
                status TEXT NOT NULL DEFAULT 'pending',
                confidence REAL NOT NULL DEFAULT 0,
                method TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                classifier_version INTEGER NOT NULL DEFAULT 0,
                manual_lock INTEGER NOT NULL DEFAULT 0,
                review_reason TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                FOREIGN KEY (source_key) REFERENCES movie_sources(source_key) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_source_classification_queue
                ON source_classifications(category,status,manual_lock,classifier_version,source_key);
            CREATE TABLE IF NOT EXISTS movie_search_aliases (
                alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL DEFAULT '',
                tmdb_id INTEGER NOT NULL DEFAULT 0,
                alias_kind TEXT NOT NULL,
                normalized_text TEXT NOT NULL,
                display_text TEXT NOT NULL DEFAULT '',
                UNIQUE(source_key,tmdb_id,alias_kind,normalized_text)
            );
            CREATE INDEX IF NOT EXISTS idx_movie_search_alias_text
                ON movie_search_aliases(normalized_text,source_key,tmdb_id);
            CREATE INDEX IF NOT EXISTS idx_movie_search_alias_source
                ON movie_search_aliases(source_key,normalized_text);
            CREATE INDEX IF NOT EXISTS idx_movie_search_alias_tmdb
                ON movie_search_aliases(tmdb_id,normalized_text);
            CREATE TABLE IF NOT EXISTS work_clusters (
                work_key TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'pending',
                lease_token TEXT NOT NULL DEFAULT '',
                claimed_at REAL NOT NULL DEFAULT 0,
                completed_at REAL NOT NULL DEFAULT 0,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                member_count INTEGER NOT NULL DEFAULT 0,
                accepted_count INTEGER NOT NULL DEFAULT 0,
                review_count INTEGER NOT NULL DEFAULT 0,
                rejected_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_work_clusters_claim
                ON work_clusters(state,updated_at,work_key);
            CREATE TABLE IF NOT EXISTS proposal_jobs (
                job_id TEXT PRIMARY KEY,
                method TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued',
                selection_mode TEXT NOT NULL,
                filters_json TEXT NOT NULL DEFAULT '{}',
                selected_keys_json TEXT NOT NULL DEFAULT '[]',
                catalog_generation INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                processed INTEGER NOT NULL DEFAULT 0,
                expires_at REAL NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
                proposal_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                work_key TEXT NOT NULL DEFAULT '',
                candidate_tmdb_id INTEGER NOT NULL DEFAULT 0,
                recommendation TEXT NOT NULL DEFAULT 'review',
                confidence REAL NOT NULL DEFAULT 0,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                selected INTEGER NOT NULL DEFAULT 0,
                apply_state TEXT NOT NULL DEFAULT 'pending',
                apply_result TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY (job_id) REFERENCES proposal_jobs(job_id) ON DELETE CASCADE,
                FOREIGN KEY (source_key) REFERENCES movie_sources(source_key) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_proposals_job ON proposals(job_id,recommendation,source_key);
            CREATE TABLE IF NOT EXISTS decision_audit (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL,
                domain TEXT NOT NULL,
                previous_json TEXT NOT NULL DEFAULT '{}',
                current_json TEXT NOT NULL DEFAULT '{}',
                method TEXT NOT NULL DEFAULT '',
                job_id TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_decision_audit_source
                ON decision_audit(source_key,created_at DESC,audit_id DESC);
            CREATE TABLE IF NOT EXISTS rebuild_jobs (
                job_id TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'previewing',
                scope_json TEXT NOT NULL DEFAULT '{}',
                catalog_generation INTEGER NOT NULL DEFAULT 0,
                classifier_version INTEGER NOT NULL DEFAULT 0,
                parser_version INTEGER NOT NULL DEFAULT 0,
                matcher_version INTEGER NOT NULL DEFAULT 0,
                checkpoint INTEGER NOT NULL DEFAULT 0,
                backup_reference TEXT NOT NULL DEFAULT '',
                report_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rebuild_items (
                job_id TEXT NOT NULL,
                source_key TEXT NOT NULL,
                previous_classification TEXT NOT NULL DEFAULT 'unclassified',
                proposed_classification TEXT NOT NULL DEFAULT 'unclassified',
                previous_match_state TEXT NOT NULL DEFAULT '',
                proposed_match_state TEXT NOT NULL DEFAULT '',
                transition TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                apply_state TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY(job_id,source_key),
                FOREIGN KEY(job_id) REFERENCES rebuild_jobs(job_id) ON DELETE CASCADE,
                FOREIGN KEY(source_key) REFERENCES movie_sources(source_key) ON DELETE CASCADE
            );
            """
        )
        now = time.time()
        rows = connection.execute(
            """SELECT source_key,provider_title,provider_year,provider_rating,
                      provider_poster_url,provider_backdrop_url,provider_plot,
                      provider_cast,provider_director,provider_genre,provider_duration,
                      container_extension,provider_tmdb_id,raw_json
                 FROM movie_sources"""
        ).fetchall()
        for row in rows:
            legacy_title = _text(row["provider_title"])
            legacy_year = _integer(row["provider_year"])
            try:
                raw = json.loads(row["raw_json"] or "{}")
            except json.JSONDecodeError:
                raw = {}
            raw_title = _text(raw.get("name") or raw.get("title")) or legacy_title
            raw_year = _provider_year(raw.get("year"), raw_title) or legacy_year
            detail_title = legacy_title if legacy_title != raw_title else ""
            detail_year = legacy_year if detail_title or legacy_year != raw_year else 0
            detail_payload = {
                "name": legacy_title,
                "year": legacy_year,
                "rating": _number(row["provider_rating"]),
                "image_url": _text(row["provider_poster_url"]),
                "backdrop_url": _text(row["provider_backdrop_url"]),
                "plot": _text(row["provider_plot"]),
                "cast_names": _text(row["provider_cast"]),
                "director": _text(row["provider_director"]),
                "genre": _text(row["provider_genre"]),
                "duration": _text(row["provider_duration"]),
                "container_extension": _text(row["container_extension"]),
                "tmdb_id": _integer(row["provider_tmdb_id"]),
                "migration_evidence": "schema-v2-provider-detail",
            }
            connection.execute(
                """UPDATE movie_sources SET provider_title=?,sort_title=?,provider_year=?,
                          detail_title=?,detail_sort_title=?,detail_year=?,detail_json=?
                    WHERE source_key=?""",
                (
                    raw_title, normalize_search_text(raw_title), raw_year,
                    detail_title, normalize_search_text(detail_title), detail_year,
                    json.dumps(detail_payload, ensure_ascii=False, separators=(",", ":")),
                    row["source_key"],
                ),
            )
        connection.execute(
            """INSERT OR IGNORE INTO source_classifications(
                   source_key,category,status,confidence,method,evidence_json,classifier_version,
                   manual_lock,review_reason,updated_at)
               SELECT source_key,'unclassified','pending',0,'','{}',0,0,'',?
               FROM movie_sources""",
            (now,),
        )
        connection.execute(
            "UPDATE source_matches SET classifier_version=0 WHERE classifier_version<0"
        )
        self._refresh_search_aliases(connection)
        self._set_meta(connection, "classifier_version", CLASSIFIER_VERSION)
        self._set_meta(connection, "search_version", SEARCH_VERSION)
        self._set_meta(connection, "schema_version", MOVIE_SCHEMA_VERSION)

    def _migrate_schema_v4(self, connection):
        """Add the provider-local exact status projection and identity refcounts."""
        self._add_column(connection, "movie_sources", "work_title TEXT NOT NULL DEFAULT ''")
        self._add_column(connection, "movie_sources", "work_year INTEGER NOT NULL DEFAULT 0")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS movie_status_summary (
                summary_id INTEGER PRIMARY KEY CHECK (summary_id=1),
                projection_version INTEGER NOT NULL DEFAULT 1,
                source_generation INTEGER NOT NULL DEFAULT 0,
                movie_generation INTEGER NOT NULL DEFAULT 0,
                classifier_version INTEGER NOT NULL DEFAULT 0,
                matcher_version INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0,
                available_sources INTEGER NOT NULL DEFAULT 0,
                unavailable_sources INTEGER NOT NULL DEFAULT 0,
                classified_film INTEGER NOT NULL DEFAULT 0,
                classified_sports INTEGER NOT NULL DEFAULT 0,
                classified_plays INTEGER NOT NULL DEFAULT 0,
                classified_music INTEGER NOT NULL DEFAULT 0,
                classified_misc INTEGER NOT NULL DEFAULT 0,
                classified_unclassified INTEGER NOT NULL DEFAULT 0,
                classification_review INTEGER NOT NULL DEFAULT 0,
                classification_manual_locks INTEGER NOT NULL DEFAULT 0,
                match_unprocessed INTEGER NOT NULL DEFAULT 0,
                match_provider_id_pending INTEGER NOT NULL DEFAULT 0,
                match_search_pending INTEGER NOT NULL DEFAULT 0,
                matched_auto INTEGER NOT NULL DEFAULT 0,
                matched_manual INTEGER NOT NULL DEFAULT 0,
                match_ambiguous INTEGER NOT NULL DEFAULT 0,
                match_unmatched INTEGER NOT NULL DEFAULT 0,
                match_error_retryable INTEGER NOT NULL DEFAULT 0,
                match_error_terminal INTEGER NOT NULL DEFAULT 0,
                match_manual_locks INTEGER NOT NULL DEFAULT 0,
                stale INTEGER NOT NULL DEFAULT 0,
                needs_review INTEGER NOT NULL DEFAULT 0,
                evaluated INTEGER NOT NULL DEFAULT 0,
                automatic_remaining INTEGER NOT NULL DEFAULT 0,
                grouped_member_sources INTEGER NOT NULL DEFAULT 0,
                grouped_identity_count INTEGER NOT NULL DEFAULT 0,
                distinct_tmdb_movies INTEGER NOT NULL DEFAULT 0,
                queue_pending INTEGER NOT NULL DEFAULT 0,
                queue_running INTEGER NOT NULL DEFAULT 0,
                queue_done INTEGER NOT NULL DEFAULT 0,
                queue_cancelled INTEGER NOT NULL DEFAULT 0,
                queue_failed INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0,
                verified_at REAL NOT NULL DEFAULT 0,
                reference_digest TEXT NOT NULL DEFAULT ''
            );
            INSERT OR IGNORE INTO movie_status_summary(summary_id) VALUES (1);
            CREATE TABLE IF NOT EXISTS accepted_tmdb_refcounts (
                tmdb_id INTEGER PRIMARY KEY,
                accepted_source_count INTEGER NOT NULL DEFAULT 0,
                grouped_source_count INTEGER NOT NULL DEFAULT 0,
                CHECK (accepted_source_count>=0),
                CHECK (grouped_source_count>=0)
            );
            CREATE INDEX IF NOT EXISTS idx_status_sibling_identity
                ON movie_sources(available,work_title,work_year,source_key);
            """
        )
        rows = connection.execute(
            """SELECT source_key,provider_title,provider_year,detail_title,detail_year
                 FROM movie_sources"""
        ).fetchall()
        connection.executemany(
            "UPDATE movie_sources SET work_title=?,work_year=? WHERE source_key=?",
            [
                (*movie_work_identity(
                    row["provider_title"], row["provider_year"],
                    row["detail_title"], row["detail_year"],
                ), row["source_key"])
                for row in rows
            ],
        )
        self._seed_status_summary(connection)
        self._set_meta(connection, "status_projection_version", STATUS_PROJECTION_VERSION)
        self._set_meta(connection, "schema_version", MOVIE_SCHEMA_VERSION)

    @staticmethod
    def _empty_status_contribution():
        return {column: 0 for column in STATUS_COUNTER_COLUMNS}

    @classmethod
    def _status_contribution_from_row(cls, row):
        contribution = cls._empty_status_contribution()
        if row is None:
            return {**contribution, "accepted_tmdb_id": 0, "grouped_tmdb_id": 0}
        available = bool(row["available"])
        category = _text(row["category"]).casefold() or "unclassified"
        if category not in CATEGORIES:
            category = "unclassified"
        classification_status = _text(row["classification_status"])
        state = _text(row["match_state"]) or "unprocessed"
        if available:
            contribution["available_sources"] = 1
            contribution[f"classified_{category}"] = 1
            contribution["classification_review"] = int(classification_status == "review")
            contribution["classification_manual_locks"] = int(bool(row["classification_manual_lock"]))
            match_column = {
                "unprocessed": "match_unprocessed",
                "provider-id-pending": "match_provider_id_pending",
                "search-pending": "match_search_pending",
                "matched-auto": "matched_auto",
                "matched-manual": "matched_manual",
                "ambiguous": "match_ambiguous",
                "unmatched": "match_unmatched",
                "error-retryable": "match_error_retryable",
                "error-terminal": "match_error_terminal",
            }.get(state)
            if match_column:
                contribution[match_column] = 1
            contribution["match_manual_locks"] = int(bool(row["match_manual_lock"]))
            contribution["stale"] = int(bool(row["stale"]) and not bool(row["match_manual_lock"]))
            contribution["needs_review"] = int(
                state == "ambiguous" or (bool(row["stale"]) and not bool(row["match_manual_lock"]))
            )
            contribution["evaluated"] = int(
                classification_status == "classified"
                and _integer(row["classification_version"]) == CLASSIFIER_VERSION
                and (
                    category != "film"
                    or (
                        not bool(row["stale"])
                        and _integer(row["match_version"]) == MATCHER_VERSION
                        and state in ACCEPTED_STATES | {"ambiguous", "unmatched", "error-terminal"}
                    )
                )
            )
            contribution["automatic_remaining"] = int(
                (
                    not bool(row["classification_manual_lock"])
                    and (
                        classification_status == "pending"
                        or _integer(row["classification_version"]) != CLASSIFIER_VERSION
                    )
                )
                or (
                    category == "film"
                    and classification_status == "classified"
                    and not bool(row["match_manual_lock"])
                    and state in {"unprocessed", "provider-id-pending", "search-pending", "error-retryable"}
                )
            )
        else:
            contribution["unavailable_sources"] = 1
        queue_status = _text(row["queue_status"])
        if queue_status in {"pending", "running", "done", "cancelled", "failed"}:
            contribution[f"queue_{queue_status}"] = 1
        tmdb_id = _integer(row["tmdb_id"])
        accepted_tmdb_id = tmdb_id if available and state in ACCEPTED_STATES and tmdb_id > 0 else 0
        grouped_tmdb_id = (
            accepted_tmdb_id
            if category == "film" and classification_status == "classified"
            else 0
        )
        contribution["grouped_member_sources"] = int(bool(grouped_tmdb_id))
        return {
            **contribution,
            "accepted_tmdb_id": accepted_tmdb_id,
            "grouped_tmdb_id": grouped_tmdb_id,
        }

    @classmethod
    def _status_contributions(cls, connection, source_keys=None):
        keys = None if source_keys is None else list(dict.fromkeys(_text(key) for key in source_keys if _text(key)))
        if keys == []:
            return {}
        if keys is not None and len(keys) > 500:
            result = {}
            for offset in range(0, len(keys), 500):
                result.update(cls._status_contributions(connection, keys[offset:offset + 500]))
            return result
        where = ""
        parameters = []
        if keys is not None:
            placeholders = ",".join("?" for _ in keys)
            where = f"WHERE s.source_key IN ({placeholders})"
            parameters = keys
        rows = connection.execute(
            f"""SELECT s.source_key,s.available,
                       COALESCE(sc.category,'unclassified') category,
                       COALESCE(sc.status,'pending') classification_status,
                       COALESCE(sc.classifier_version,0) classification_version,
                       COALESCE(sc.manual_lock,0) classification_manual_lock,
                       COALESCE(m.state,'unprocessed') match_state,
                       COALESCE(m.tmdb_id,0) tmdb_id,
                       COALESCE(m.matcher_version,0) match_version,
                       COALESCE(m.manual_lock,0) match_manual_lock,
                       COALESCE(m.stale,0) stale,
                       COALESCE(q.status,'') queue_status
                  FROM movie_sources s
                  LEFT JOIN source_classifications sc USING(source_key)
                  LEFT JOIN source_matches m USING(source_key)
                  LEFT JOIN enrichment_queue q USING(source_key)
                  {where}""",
            parameters,
        ).fetchall()
        return {row["source_key"]: cls._status_contribution_from_row(row) for row in rows}

    @classmethod
    def _compute_status_reference(cls, connection):
        contributions = cls._status_contributions(connection)
        counters = {column: 0 for column in STATUS_COUNTER_COLUMNS}
        accepted = {}
        grouped = {}
        for contribution in contributions.values():
            for column in STATUS_COUNTER_COLUMNS:
                counters[column] += _integer(contribution[column])
            accepted_id = _integer(contribution.get("accepted_tmdb_id"))
            grouped_id = _integer(contribution.get("grouped_tmdb_id"))
            if accepted_id:
                accepted[accepted_id] = accepted.get(accepted_id, 0) + 1
            if grouped_id:
                grouped[grouped_id] = grouped.get(grouped_id, 0) + 1
        counters["distinct_tmdb_movies"] = len(accepted)
        counters["grouped_identity_count"] = len(grouped)
        return counters, accepted, grouped

    def _seed_status_summary(self, connection):
        counters, accepted, grouped = self._compute_status_reference(connection)
        connection.execute("DELETE FROM accepted_tmdb_refcounts")
        connection.executemany(
            """INSERT INTO accepted_tmdb_refcounts(
                   tmdb_id,accepted_source_count,grouped_source_count) VALUES (?,?,?)""",
            [
                (tmdb_id, count, grouped.get(tmdb_id, 0))
                for tmdb_id, count in sorted(accepted.items())
            ] + [
                (tmdb_id, 0, count)
                for tmdb_id, count in sorted(grouped.items()) if tmdb_id not in accepted
            ],
        )
        payload = {
            **{column: counters[column] for column in STATUS_COUNTER_COLUMNS},
            "grouped_identity_count": counters["grouped_identity_count"],
            "distinct_tmdb_movies": counters["distinct_tmdb_movies"],
        }
        digest = hashlib.sha256(
            json.dumps(
                {"counters": payload, "accepted": accepted, "grouped": grouped},
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        columns = [*STATUS_COUNTER_COLUMNS, "grouped_identity_count", "distinct_tmdb_movies"]
        assignments = ",".join(f"{column}=?" for column in columns)
        now = time.time()
        connection.execute(
            f"""UPDATE movie_status_summary SET projection_version=?,source_generation=?,
                       movie_generation=?,classifier_version=?,matcher_version=?,revision=1,
                       {assignments},updated_at=?,verified_at=?,reference_digest=?
                   WHERE summary_id=1""",
            [
                STATUS_PROJECTION_VERSION,
                _integer(self._meta(connection, "source_catalog_generation", 0)),
                _integer(self._meta(connection, "movie_generation", 0)),
                CLASSIFIER_VERSION, MATCHER_VERSION,
                *[payload[column] for column in columns], now, now, digest,
            ],
        )
        return payload

    @staticmethod
    def _status_refcount_delta(connection, tmdb_id, field, delta):
        tmdb_id = _integer(tmdb_id)
        delta = _integer(delta)
        if not tmdb_id or not delta:
            return 0
        row = connection.execute(
            "SELECT accepted_source_count,grouped_source_count FROM accepted_tmdb_refcounts WHERE tmdb_id=?",
            (tmdb_id,),
        ).fetchone()
        before_accepted = _integer(row["accepted_source_count"] if row else 0)
        before_grouped = _integer(row["grouped_source_count"] if row else 0)
        after_accepted = before_accepted + (delta if field == "accepted" else 0)
        after_grouped = before_grouped + (delta if field == "grouped" else 0)
        if after_accepted < 0 or after_grouped < 0:
            raise RuntimeError("IPTV Movies status refcount would become negative")
        if after_accepted or after_grouped:
            connection.execute(
                """INSERT INTO accepted_tmdb_refcounts(tmdb_id,accepted_source_count,grouped_source_count)
                   VALUES (?,?,?) ON CONFLICT(tmdb_id) DO UPDATE SET
                     accepted_source_count=excluded.accepted_source_count,
                     grouped_source_count=excluded.grouped_source_count""",
                (tmdb_id, after_accepted, after_grouped),
            )
        else:
            connection.execute("DELETE FROM accepted_tmdb_refcounts WHERE tmdb_id=?", (tmdb_id,))
        if field == "accepted":
            return int(before_accepted == 0 and after_accepted > 0) - int(before_accepted > 0 and after_accepted == 0)
        return int(before_grouped == 0 and after_grouped > 0) - int(before_grouped > 0 and after_grouped == 0)

    def _apply_status_transitions(self, connection, before, source_keys):
        after = self._status_contributions(connection, source_keys)
        keys = set(before) | set(after)
        deltas = {column: 0 for column in STATUS_COUNTER_COLUMNS}
        distinct_delta = 0
        grouped_identity_delta = 0
        empty = self._empty_status_contribution()
        for key in keys:
            old = before.get(key) or {**empty, "accepted_tmdb_id": 0, "grouped_tmdb_id": 0}
            new = after.get(key) or {**empty, "accepted_tmdb_id": 0, "grouped_tmdb_id": 0}
            for column in STATUS_COUNTER_COLUMNS:
                deltas[column] += _integer(new.get(column)) - _integer(old.get(column))
            old_id = _integer(old.get("accepted_tmdb_id"))
            new_id = _integer(new.get("accepted_tmdb_id"))
            if old_id != new_id:
                distinct_delta += self._status_refcount_delta(connection, old_id, "accepted", -1)
                distinct_delta += self._status_refcount_delta(connection, new_id, "accepted", 1)
            old_grouped = _integer(old.get("grouped_tmdb_id"))
            new_grouped = _integer(new.get("grouped_tmdb_id"))
            if old_grouped != new_grouped:
                grouped_identity_delta += self._status_refcount_delta(connection, old_grouped, "grouped", -1)
                grouped_identity_delta += self._status_refcount_delta(connection, new_grouped, "grouped", 1)
        changed = any(deltas.values()) or distinct_delta or grouped_identity_delta
        if changed:
            assignments = ",".join(f"{column}={column}+?" for column in STATUS_COUNTER_COLUMNS)
            checked_columns = (*STATUS_COUNTER_COLUMNS, "distinct_tmdb_movies", "grouped_identity_count")
            row = connection.execute(
                f"""UPDATE movie_status_summary SET {assignments},
                           distinct_tmdb_movies=distinct_tmdb_movies+?,
                           grouped_identity_count=grouped_identity_count+?,
                           source_generation=CAST(COALESCE((SELECT value FROM movie_meta WHERE key='source_catalog_generation'),'0') AS INTEGER),
                           movie_generation=CAST(COALESCE((SELECT value FROM movie_meta WHERE key='movie_generation'),'0') AS INTEGER),
                           classifier_version=?,matcher_version=?,revision=revision+1,updated_at=?
                     WHERE summary_id=1
                     RETURNING {','.join(checked_columns)}""",
                [
                    *[deltas[column] for column in STATUS_COUNTER_COLUMNS],
                    distinct_delta, grouped_identity_delta,
                    CLASSIFIER_VERSION, MATCHER_VERSION, time.time(),
                ],
            ).fetchone()
            for column in checked_columns:
                if _integer(row[column]) < 0:
                    raise RuntimeError(f"IPTV Movies status counter {column} would become negative")
        return after

    def status_diagnostic(self):
        """Explicit read-only comparison; never called from status or control paths."""
        started = time.perf_counter()
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM movie_status_summary WHERE summary_id=1").fetchone()
            counters, accepted, grouped = self._compute_status_reference(connection)
            source_generation = _integer(self._meta(connection, "source_catalog_generation", 0))
            movie_generation = _integer(self._meta(connection, "movie_generation", 0))
        stored = dict(row) if row else {}
        columns = [*STATUS_COUNTER_COLUMNS, "grouped_identity_count", "distinct_tmdb_movies"]
        differences = {
            column: {"stored": _integer(stored.get(column)), "reference": _integer(counters.get(column))}
            for column in columns
            if _integer(stored.get(column)) != _integer(counters.get(column))
        }
        return {
            "ok": not differences,
            "schema_version": MOVIE_SCHEMA_VERSION,
            "projection_version": _integer(stored.get("projection_version")),
            "revision": _integer(stored.get("revision")),
            "source_generation": source_generation,
            "movie_generation": movie_generation,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "differences": differences,
            "reference_tmdb_ids": len(accepted),
            "reference_grouped_ids": len(grouped),
        }

    @staticmethod
    def _insert_search_alias(connection, *, source_key_value="", tmdb_id=0, kind, value):
        display = _text(value)
        normalized = normalize_search_text(display)
        if not normalized:
            return
        connection.execute(
            """INSERT OR IGNORE INTO movie_search_aliases(
                   source_key,tmdb_id,alias_kind,normalized_text,display_text)
               VALUES (?,?,?,?,?)""",
            (_text(source_key_value), _integer(tmdb_id), _text(kind), normalized, display),
        )

    def _refresh_search_aliases(self, connection, source_keys=None, tmdb_ids=None):
        if source_keys is None:
            connection.execute("DELETE FROM movie_search_aliases WHERE source_key<>''")
            source_rows = connection.execute(
                "SELECT source_key,provider_title,detail_title FROM movie_sources"
            ).fetchall()
        else:
            keys = list(dict.fromkeys(_text(key) for key in source_keys if _text(key)))
            if not keys:
                source_rows = []
            else:
                placeholders = ",".join("?" for _ in keys)
                connection.execute(
                    f"DELETE FROM movie_search_aliases WHERE source_key IN ({placeholders})", keys
                )
                source_rows = connection.execute(
                    f"SELECT source_key,provider_title,detail_title FROM movie_sources WHERE source_key IN ({placeholders})",
                    keys,
                ).fetchall()
        for row in source_rows:
            self._insert_search_alias(connection, source_key_value=row["source_key"], kind="provider-raw", value=row["provider_title"])
            self._insert_search_alias(connection, source_key_value=row["source_key"], kind="provider-detail", value=row["detail_title"])

        if tmdb_ids is None:
            connection.execute("DELETE FROM movie_search_aliases WHERE source_key='' AND tmdb_id>0")
            tmdb_rows = connection.execute(
                "SELECT tmdb_id,title,original_title FROM tmdb_movies"
            ).fetchall()
        else:
            ids = list(dict.fromkeys(_integer(value) for value in tmdb_ids if _integer(value)))
            if not ids:
                tmdb_rows = []
            else:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(
                    f"DELETE FROM movie_search_aliases WHERE source_key='' AND tmdb_id IN ({placeholders})", ids
                )
                tmdb_rows = connection.execute(
                    f"SELECT tmdb_id,title,original_title FROM tmdb_movies WHERE tmdb_id IN ({placeholders})", ids
                ).fetchall()
        for row in tmdb_rows:
            self._insert_search_alias(connection, tmdb_id=row["tmdb_id"], kind="tmdb-title", value=row["title"])
            self._insert_search_alias(connection, tmdb_id=row["tmdb_id"], kind="tmdb-original", value=row["original_title"])
            for localized in connection.execute(
                "SELECT locale,title,original_title FROM tmdb_movie_localizations WHERE tmdb_id=?",
                (row["tmdb_id"],),
            ):
                self._insert_search_alias(connection, tmdb_id=row["tmdb_id"], kind=f"localized-{localized['locale']}", value=localized["title"])
                self._insert_search_alias(connection, tmdb_id=row["tmdb_id"], kind=f"localized-original-{localized['locale']}", value=localized["original_title"])

    def migration_report(self):
        with self.connection() as connection:
            accepted = connection.execute(
                "SELECT COUNT(*) FROM source_matches WHERE state IN ('matched-auto','matched-manual') AND tmdb_id IS NOT NULL"
            ).fetchone()[0]
            manual = connection.execute(
                "SELECT COUNT(*) FROM source_matches WHERE manual_lock=1"
            ).fetchone()[0]
            snapshots = connection.execute("SELECT COUNT(*) FROM tmdb_movies").fetchone()[0]
            terminal = connection.execute(
                "SELECT COUNT(*) FROM source_matches WHERE terminal_at>0"
            ).fetchone()[0]
        return {
            "schema_version": MOVIE_SCHEMA_VERSION,
            "accepted_matches": int(accepted),
            "manual_locks": int(manual),
            "tmdb_snapshots": int(snapshots),
            "terminal_evaluations": int(terminal),
            "backup": str(self._migration_backup) if self._migration_backup else "",
        }

    def repair_relationships_from_snapshots(self):
        repaired = 0
        skipped = 0
        from .iptv_tmdb import normalize_tmdb_movie

        with self._lock, self.connection(immediate=True) as connection:
            rows = connection.execute(
                "SELECT tmdb_id,raw_json FROM tmdb_movies ORDER BY tmdb_id"
            ).fetchall()
            for row in rows:
                try:
                    payload = json.loads(row["raw_json"] or "{}")
                except json.JSONDecodeError:
                    skipped += 1
                    continue
                if not isinstance(payload, dict) or _integer(payload.get("id")) != _integer(row["tmdb_id"]):
                    skipped += 1
                    continue
                self._save_tmdb_movie(connection, normalize_tmdb_movie(payload))
                repaired += 1
            self._set_meta(connection, "relationship_repaired_at", time.time())
            self._set_meta(connection, "relationship_repaired_snapshots", repaired)
        return {"repaired_snapshots": repaired, "skipped_snapshots": skipped}

    @staticmethod
    def _meta(connection, key, default=""):
        row = connection.execute("SELECT value FROM movie_meta WHERE key=?", (str(key),)).fetchone()
        return str(row[0]) if row else str(default)

    @staticmethod
    def _set_meta(connection, key, value):
        connection.execute(
            """INSERT INTO movie_meta(key,value) VALUES (?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (str(key), str(value)),
        )

    def source_generation(self):
        with self.connection() as connection:
            return _integer(self._meta(connection, "source_catalog_generation", 0))

    @staticmethod
    def _current_movie_key(connection, source_key_value):
        row = connection.execute(
            "SELECT state,tmdb_id FROM source_matches WHERE source_key=?",
            (source_key_value,),
        ).fetchone()
        if row and row["state"] in ACCEPTED_STATES and row["tmdb_id"]:
            return f"tmdb:{int(row['tmdb_id'])}"
        return f"source:{source_key_value}"

    def begin_projection(self, generation, total=0, lease_token=""):
        generation = max(0, _integer(generation))
        token = _text(lease_token) or uuid.uuid4().hex
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            job = connection.execute("SELECT * FROM projection_jobs WHERE job_id=1").fetchone()
            if job and job["state"] == "running" and job["lease_expires_at"] > now and job["lease_token"] != token:
                return ""
            self._set_meta(connection, "source_projection_generation", generation)
            connection.execute(
                """UPDATE projection_jobs SET state='running',phase='projecting',source_generation=?,
                       previous_generation=?,total=?,processed=0,checkpoint=0,lease_token=?,
                       lease_expires_at=?,heartbeat_at=?,started_at=?,finished_at=0,error=''
                   WHERE job_id=1""",
                (generation, _integer(self._meta(connection, "source_catalog_generation", 0)), max(0, _integer(total)), token, now + 60, now, now),
            )
        return token

    def project_source_batch(self, rows, generation, memberships=(), history=None, lease_token=""):
        generation = max(0, _integer(generation))
        now = time.time()
        history = history or {}
        projected = []
        for position, row in enumerate(rows or []):
            if not isinstance(row, dict):
                continue
            source_id_value = _text(row.get("item_id") or row.get("source_id"))
            if not source_id_value:
                continue
            playlist_name = _text(row.get("playlist_name") or row.get("category_name"))
            title = _text(row.get("name") or row.get("provider_title")) or "Untitled"
            provider_year = _provider_year(row.get("year"), title)
            work_title, work_year = movie_work_identity(title, provider_year)
            quality, dubbed, subtitled = _source_claims(title, playlist_name)
            watch = history.get(source_id_value) or {}
            projected.append((
                source_key(source_id_value), source_id_value,
                _text(row.get("category_id") or row.get("playlist_id")), playlist_name,
                title, normalize_search_text(title), provider_year, work_title, work_year,
                _number(row.get("rating")),
                _text(row.get("image_url") or row.get("provider_poster_url")),
                _text(row.get("backdrop_url") or row.get("provider_backdrop_url")),
                _text(row.get("plot")), _text(row.get("cast_names") or row.get("cast")),
                _text(row.get("director")), _text(row.get("genre")), _text(row.get("duration")),
                _text(row.get("container_extension")), _integer(row.get("tmdb_id")),
                _text(row.get("added")), _integer(row.get("position", position)), quality,
                int(dubbed), int(subtitled), generation,
                _number(watch.get("position_seconds")), _number(watch.get("duration_seconds")),
                int(bool(watch.get("completed"))), _number(watch.get("last_watched")),
                json.dumps(row.get("raw") or row, ensure_ascii=False, separators=(",", ":")), now,
            ))
        with self._lock, self.connection(immediate=True) as connection:
            if lease_token:
                job = connection.execute("SELECT lease_token,state FROM projection_jobs WHERE job_id=1").fetchone()
                if not job or job["state"] != "running" or job["lease_token"] != _text(lease_token):
                    raise RuntimeError("The IPTV movie projection lease was lost")
            projected_keys = [row[0] for row in projected]
            status_before = self._status_contributions(connection, projected_keys)
            connection.executemany(
                """INSERT INTO movie_sources(
                    source_key,source_id,playlist_id,playlist_name,provider_title,sort_title,
                    provider_year,work_title,work_year,provider_rating,provider_poster_url,provider_backdrop_url,
                    provider_plot,provider_cast,provider_director,provider_genre,provider_duration,
                    container_extension,provider_tmdb_id,added,position,quality_claim,dubbed_claim,
                    subtitled_claim,available,source_generation,watched_position,watched_duration,
                    watched_completed,last_watched,raw_json,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?)
                ON CONFLICT(source_key) DO UPDATE SET
                    source_id=excluded.source_id,playlist_id=excluded.playlist_id,playlist_name=excluded.playlist_name,
                    provider_title=excluded.provider_title,sort_title=excluded.sort_title,
                    provider_year=excluded.provider_year,work_title=excluded.work_title,
                    work_year=excluded.work_year,provider_rating=excluded.provider_rating,
                    provider_poster_url=excluded.provider_poster_url,provider_backdrop_url=excluded.provider_backdrop_url,
                    provider_plot=excluded.provider_plot,provider_cast=excluded.provider_cast,
                    provider_director=excluded.provider_director,provider_genre=excluded.provider_genre,
                    provider_duration=excluded.provider_duration,container_extension=excluded.container_extension,
                    provider_tmdb_id=CASE WHEN excluded.provider_tmdb_id>0 THEN excluded.provider_tmdb_id ELSE movie_sources.provider_tmdb_id END,
                    added=excluded.added,position=excluded.position,quality_claim=excluded.quality_claim,
                    dubbed_claim=excluded.dubbed_claim,subtitled_claim=excluded.subtitled_claim,
                    available=1,source_generation=excluded.source_generation,
                    watched_position=excluded.watched_position,watched_duration=excluded.watched_duration,
                    watched_completed=excluded.watched_completed,last_watched=excluded.last_watched,
                    raw_json=excluded.raw_json,updated_at=excluded.updated_at""",
                projected,
            )
            connection.execute(
                """INSERT OR IGNORE INTO source_matches(source_key,state,updated_at)
                   SELECT source_key,'unprocessed',? FROM movie_sources WHERE source_generation=?""",
                (now, generation),
            )
            connection.execute(
                """INSERT OR IGNORE INTO source_classifications(
                       source_key,category,status,confidence,method,evidence_json,classifier_version,
                       manual_lock,review_reason,updated_at)
                   SELECT source_key,'unclassified','pending',0,'','{}',0,0,'',?
                   FROM movie_sources WHERE source_generation=?""",
                (now, generation),
            )
            self._refresh_search_aliases(
                connection, source_keys=[row[0] for row in projected], tmdb_ids=[]
            )
            for membership in memberships or ():
                if not isinstance(membership, dict):
                    continue
                source_id_value = _text(membership.get("source_id") or membership.get("item_id"))
                list_id = _text(membership.get("list_id"))
                if not source_id_value or not list_id:
                    continue
                source_key_value = source_key(source_id_value)
                exists = connection.execute(
                    "SELECT 1 FROM movie_sources WHERE source_key=?", (source_key_value,)
                ).fetchone()
                if not exists:
                    continue
                movie_key = self._current_movie_key(connection, source_key_value)
                self._upsert_membership(
                    connection, list_id, movie_key,
                    _integer(membership.get("position")),
                    _number(membership.get("added_at")) or now,
                    membership.get("snapshot") or {},
                )
            connection.execute(
                """UPDATE projection_jobs SET processed=MIN(total,processed+?),
                       checkpoint=checkpoint+?,heartbeat_at=?,lease_expires_at=?
                   WHERE job_id=1""",
                (len(projected), len(projected), time.time(), time.time() + 60),
            )
            self._apply_status_transitions(connection, status_before, projected_keys)
        return len(projected)

    def finish_projection(self, generation, lease_token=""):
        generation = max(0, _integer(generation))
        with self._lock, self.connection(immediate=True) as connection:
            if lease_token:
                job = connection.execute("SELECT lease_token FROM projection_jobs WHERE job_id=1").fetchone()
                if not job or job["lease_token"] != _text(lease_token):
                    raise RuntimeError("The IPTV movie projection lease was lost")
            expected = _integer(self._meta(connection, "source_projection_generation", -1))
            if expected != generation:
                completed = _integer(self._meta(connection, "source_catalog_generation", -1))
                if completed == generation:
                    return
                raise RuntimeError("IPTV movie source projection generation changed unexpectedly")
            self._set_meta(connection, "source_catalog_generation", generation)
            self._set_meta(connection, "source_projected_at", time.time())
            self._set_meta(connection, "source_projection_generation", "")
            unavailable_keys = [row[0] for row in connection.execute(
                "SELECT source_key FROM movie_sources WHERE available=1 AND source_generation<>?",
                (generation,),
            )]
            status_before = self._status_contributions(connection, unavailable_keys)
            connection.execute(
                "UPDATE movie_sources SET available=0 WHERE source_generation<>?",
                (generation,),
            )
            connection.execute(
                """UPDATE projection_jobs SET state='complete',phase='',processed=total,
                       checkpoint=total,heartbeat_at=?,lease_expires_at=0,finished_at=?,error=''
                   WHERE job_id=1""",
                (time.time(), time.time()),
            )
            self._apply_status_transitions(connection, status_before, unavailable_keys)

    def project_sources(self, rows, generation, memberships=(), history=None):
        token = self.begin_projection(generation, len(rows or []))
        if not token:
            raise RuntimeError("An IPTV movie projection is already running")
        count = self.project_source_batch(
            rows, generation, memberships=memberships, history=history, lease_token=token
        )
        self.finish_projection(generation, lease_token=token)
        return count

    def projection_failed(self, lease_token, error):
        with self._lock, self.connection(immediate=True) as connection:
            job = connection.execute("SELECT lease_token FROM projection_jobs WHERE job_id=1").fetchone()
            if job and job["lease_token"] == _text(lease_token):
                connection.execute(
                    """UPDATE projection_jobs SET state='failed',phase='',lease_expires_at=0,
                           heartbeat_at=?,finished_at=?,retry_count=retry_count+1,error=? WHERE job_id=1""",
                    (time.time(), time.time(), _text(error)[:500]),
                )

    def projection_status(self):
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM projection_jobs WHERE job_id=1").fetchone()
            published = connection.execute("SELECT COUNT(*) FROM movie_sources WHERE available=1").fetchone()[0]
        data = dict(row) if row else {}
        data.update({
            "published": int(published),
            "total": _integer(data.get("total")),
            "processed": _integer(data.get("processed")),
            "source_generation": _integer(data.get("source_generation")),
            "previous_generation": _integer(data.get("previous_generation")),
        })
        data.pop("lease_token", None)
        return data

    @staticmethod
    def _upsert_membership(connection, list_id, movie_key, position, added_at, snapshot):
        connection.execute(
            """INSERT INTO movie_list_memberships(list_id,movie_key,position,added_at,source_snapshot_json)
               VALUES (?,?,?,?,?)
               ON CONFLICT(list_id,movie_key) DO UPDATE SET
                 position=MIN(movie_list_memberships.position,excluded.position),
                 added_at=MIN(movie_list_memberships.added_at,excluded.added_at),
                 source_snapshot_json=CASE WHEN movie_list_memberships.source_snapshot_json='{}'
                                           THEN excluded.source_snapshot_json ELSE movie_list_memberships.source_snapshot_json END""",
            (
                _text(list_id), validate_movie_key(movie_key), max(0, _integer(position)),
                float(added_at or time.time()),
                json.dumps(snapshot if isinstance(snapshot, dict) else {}, ensure_ascii=False),
            ),
        )

    def set_list_membership(self, list_id, movie_key, included, *, position=0, snapshot=None):
        movie_key = validate_movie_key(movie_key)
        with self._lock, self.connection(immediate=True) as connection:
            if not self._source_keys_for_movie(connection, movie_key):
                raise KeyError("IPTV movie was not found")
            if included:
                self._upsert_membership(connection, list_id, movie_key, position, time.time(), snapshot or {})
            else:
                connection.execute(
                    "DELETE FROM movie_list_memberships WHERE list_id=? AND movie_key=?",
                    (_text(list_id), movie_key),
                )
        return bool(included)

    @staticmethod
    def _source_keys_for_movie(connection, movie_key):
        movie_key = validate_movie_key(movie_key)
        if movie_key.startswith("tmdb:"):
            tmdb_id = int(movie_key.split(":", 1)[1])
            rows = connection.execute(
                """SELECT s.source_key FROM movie_sources s JOIN source_matches m USING(source_key)
                   WHERE m.tmdb_id=? AND m.state IN ('matched-auto','matched-manual')
                   ORDER BY s.position,s.source_key""",
                (tmdb_id,),
            ).fetchall()
            return [row[0] for row in rows]
        key = movie_key.split(":", 1)[1]
        return [key] if connection.execute("SELECT 1 FROM movie_sources WHERE source_key=?", (key,)).fetchone() else []

    def source_keys_for_movie(self, movie_key):
        with self.connection() as connection:
            return self._source_keys_for_movie(connection, movie_key)

    def update_provider_detail(self, source_key_value, detail):
        detail = detail if isinstance(detail, dict) else {}
        detail_title = _text(detail.get("name"))
        detail_year = _provider_year(detail.get("year"), detail_title)
        with self._lock, self.connection(immediate=True) as connection:
            current = connection.execute(
                """SELECT provider_title,provider_year,detail_title,detail_year
                     FROM movie_sources WHERE source_key=?""",
                (_text(source_key_value),),
            ).fetchone()
            if not current:
                raise KeyError("IPTV movie source was not found")
            effective_detail_title = detail_title or current["detail_title"]
            effective_detail_year = detail_year or _integer(current["detail_year"])
            work_title, work_year = movie_work_identity(
                current["provider_title"], current["provider_year"],
                effective_detail_title, effective_detail_year,
            )
            cursor = connection.execute(
                """UPDATE movie_sources SET
                    detail_title=COALESCE(NULLIF(?,''),detail_title),
                    detail_sort_title=COALESCE(NULLIF(?,''),detail_sort_title),
                    detail_year=CASE WHEN ?>0 THEN ? ELSE detail_year END,
                    detail_json=?,
                    provider_rating=CASE WHEN ?>0 THEN ? ELSE provider_rating END,
                    provider_poster_url=COALESCE(NULLIF(?,''),provider_poster_url),
                    provider_backdrop_url=COALESCE(NULLIF(?,''),provider_backdrop_url),
                    provider_plot=COALESCE(NULLIF(?,''),provider_plot),
                    provider_cast=COALESCE(NULLIF(?,''),provider_cast),
                    provider_director=COALESCE(NULLIF(?,''),provider_director),
                    provider_genre=COALESCE(NULLIF(?,''),provider_genre),
                    provider_duration=COALESCE(NULLIF(?,''),provider_duration),
                    container_extension=COALESCE(NULLIF(?,''),container_extension),
                    provider_tmdb_id=CASE WHEN ?>0 THEN ? ELSE provider_tmdb_id END,
                    work_title=?,work_year=?,
                    updated_at=? WHERE source_key=?""",
                (
                    detail_title, normalize_search_text(detail_title), detail_year, detail_year,
                    json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                    _number(detail.get("rating")), _number(detail.get("rating")),
                    _text(detail.get("image_url")), _text(detail.get("backdrop_url")),
                    _text(detail.get("plot")), _text(detail.get("cast_names")),
                    _text(detail.get("director")), _text(detail.get("genre")),
                    _text(detail.get("duration")), _text(detail.get("container_extension")),
                    _integer(detail.get("tmdb_id")), _integer(detail.get("tmdb_id")),
                    work_title, work_year,
                    time.time(), _text(source_key_value),
                ),
            )
            self._refresh_search_aliases(
                connection, source_keys=[_text(source_key_value)], tmdb_ids=[]
            )

    def source(self, source_key_value):
        with self.connection() as connection:
            row = connection.execute(
                """SELECT s.*,COALESCE(sc.category,'unclassified') category,
                          COALESCE(sc.status,'pending') classification_status,
                          COALESCE(sc.confidence,0) classification_confidence,
                          COALESCE(sc.manual_lock,0) classification_manual_lock,
                          COALESCE(sc.review_reason,'') classification_review_reason
                   FROM movie_sources s LEFT JOIN source_classifications sc USING(source_key)
                   WHERE s.source_key=?""", (_text(source_key_value),)
            ).fetchone()
        return dict(row) if row else None

    def stored_tmdb_snapshot(self, tmdb_id):
        """Return a normalized provider-local snapshot without any network call."""
        tmdb_id = _integer(tmdb_id)
        if tmdb_id <= 0:
            return None
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM tmdb_movies WHERE tmdb_id=?", (tmdb_id,),
            ).fetchone()
        if not row:
            return None
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except json.JSONDecodeError:
            raw = {}
        if isinstance(raw, dict) and _integer(raw.get("id")) == tmdb_id:
            from .iptv_tmdb import normalize_tmdb_movie
            return normalize_tmdb_movie(raw)
        return {
            "tmdb_id": tmdb_id,
            "title": _text(row["title"]),
            "original_title": _text(row["original_title"]),
            "plot": _text(row["plot"]),
            "poster_url": _text(row["poster_url"]),
            "backdrop_url": _text(row["backdrop_url"]),
            "rating": _number(row["rating"]),
            "vote_count": _integer(row["vote_count"]),
            "release_date": _text(row["release_date"]),
            "year": _integer(row["year"]),
            "runtime": _integer(row["runtime"]),
            "original_language": _text(row["original_language"]),
            "certification": _text(row["certification"]),
            "imdb_id": _text(row["imdb_id"]),
            "genres": [], "directors": [], "writers": [], "cast": [],
            "keywords": [], "collection": None, "languages": [], "countries": [],
            "raw": raw if isinstance(raw, dict) else {},
        }

    def accepted_sibling_candidate(self, source_key_value):
        """Resolve one unique accepted Film identity for the same indexed work key."""
        source_key_value = _text(source_key_value)
        with self.connection() as connection:
            source = connection.execute(
                "SELECT work_title,work_year FROM movie_sources WHERE source_key=? AND available=1",
                (source_key_value,),
            ).fetchone()
            if not source or not _text(source["work_title"]):
                return {"state": "none", "tmdb_id": 0, "sibling_count": 0}
            rows = connection.execute(
                """SELECT m.tmdb_id,COUNT(*) sibling_count
                     FROM movie_sources s
                     JOIN source_matches m USING(source_key)
                     JOIN source_classifications sc USING(source_key)
                    WHERE s.available=1 AND s.source_key<>?
                      AND s.work_title=? AND s.work_year=?
                      AND sc.category='film' AND sc.status='classified'
                      AND m.state IN ('matched-auto','matched-manual') AND m.tmdb_id>0
                    GROUP BY m.tmdb_id ORDER BY sibling_count DESC,m.tmdb_id LIMIT 3""",
                (source_key_value, source["work_title"], source["work_year"]),
            ).fetchall()
        if not rows:
            return {"state": "none", "tmdb_id": 0, "sibling_count": 0}
        if len(rows) != 1:
            return {
                "state": "conflict", "tmdb_id": 0,
                "candidate_tmdb_ids": [int(row["tmdb_id"]) for row in rows],
                "sibling_count": sum(int(row["sibling_count"]) for row in rows),
            }
        return {
            "state": "candidate", "tmdb_id": int(rows[0]["tmdb_id"]),
            "sibling_count": int(rows[0]["sibling_count"]),
            "work_title": _text(source["work_title"]),
            "work_year": _integer(source["work_year"]),
        }

    def fusion_candidate_rows(self, limit=500):
        """Return bounded legacy classification and unresolved-sibling candidates."""
        limit = max(1, min(2000, _integer(limit) or 500))
        with self.connection() as connection:
            classification_rows = connection.execute(
                """SELECT s.source_key,s.provider_title,s.provider_year,s.playlist_name,
                          s.quality_claim,m.tmdb_id,sc.category,sc.manual_lock
                     FROM source_matches m
                     JOIN movie_sources s USING(source_key)
                     JOIN source_classifications sc USING(source_key)
                    WHERE s.available=1 AND m.state='matched-manual' AND m.tmdb_id>0
                      AND (sc.category<>'film' OR sc.status<>'classified')
                    ORDER BY s.position,s.source_key LIMIT ?""",
                (limit,),
            ).fetchall()
            remaining = max(0, limit - len(classification_rows))
            sibling_rows = []
            if remaining:
                sibling_rows = connection.execute(
                    """WITH accepted_keys AS MATERIALIZED (
                           SELECT s.work_title,s.work_year,MIN(m.tmdb_id) tmdb_id,
                                  COUNT(DISTINCT m.tmdb_id) identity_count,
                                  COUNT(*) accepted_count
                             FROM movie_sources s
                             JOIN source_matches m USING(source_key)
                             JOIN source_classifications sc USING(source_key)
                            WHERE s.available=1 AND s.work_title<>''
                              AND sc.category='film' AND sc.status='classified'
                              AND m.state IN ('matched-auto','matched-manual') AND m.tmdb_id>0
                            GROUP BY s.work_title,s.work_year
                           HAVING COUNT(DISTINCT m.tmdb_id)=1
                           ORDER BY MIN(s.position),s.work_title,s.work_year
                           LIMIT ?
                       )
                       SELECT u.source_key,u.provider_title,u.provider_year,u.detail_title,u.detail_year,
                              u.playlist_name,u.quality_claim,a.tmdb_id,a.accepted_count,
                              um.state match_state
                         FROM accepted_keys a
                         JOIN movie_sources u INDEXED BY idx_status_sibling_identity
                           ON u.available=1 AND u.work_title=a.work_title AND u.work_year=a.work_year
                         JOIN source_matches um ON um.source_key=u.source_key
                         JOIN source_classifications uc ON uc.source_key=u.source_key
                        WHERE uc.category='film' AND uc.status='classified'
                          AND um.manual_lock=0
                          AND um.state NOT IN ('matched-auto','matched-manual')
                        ORDER BY u.position,u.source_key LIMIT ?""",
                    (remaining, remaining),
                ).fetchall()
        return {
            "classification": [dict(row) for row in classification_rows],
            "siblings": [dict(row) for row in sibling_rows],
        }

    def set_match_state(self, source_keys, state, *, tmdb_id=None, method="", confidence=0, manual_lock=False, evidence=None, error_code="", error_message="", parser_version=PARSER_VERSION, matcher_version=MATCHER_VERSION):
        if state not in MATCH_STATES:
            raise ValueError("Unsupported IPTV movie match state")
        keys = list(dict.fromkeys(_text(key) for key in source_keys if _text(key)))
        if not keys:
            raise KeyError("IPTV movie source was not found")
        with self._lock, self.connection(immediate=True) as connection:
            status_before = self._status_contributions(connection, keys)
            for key in keys:
                if not connection.execute("SELECT 1 FROM movie_sources WHERE source_key=?", (key,)).fetchone():
                    raise KeyError("IPTV movie source was not found")
                connection.execute(
                    """UPDATE source_matches SET state=?,tmdb_id=?,method=?,confidence=?,manual_lock=?,
                       evidence_json=?,error_code=?,error_message=?,parser_version=?,matcher_version=?,
                       classifier_version=?,terminal_at=?,stale=0,updated_at=? WHERE source_key=?""",
                    (
                        state, int(tmdb_id) if tmdb_id else None, _text(method), float(confidence or 0),
                        int(bool(manual_lock)), json.dumps(evidence or {}, ensure_ascii=False),
                        _text(error_code), _text(error_message)[:500], int(parser_version), int(matcher_version), CLASSIFIER_VERSION,
                        time.time() if state in ACCEPTED_STATES | {"ambiguous", "unmatched", "error-terminal"} else 0,
                        time.time(), key,
                    ),
                )
            self._apply_status_transitions(connection, status_before, keys)

    @staticmethod
    def _person_row(row):
        if not isinstance(row, dict) or not row.get("id"):
            return None
        profile = _text(row.get("profile_path"))
        if profile and not profile.startswith("http"):
            profile = f"https://image.tmdb.org/t/p/w185/{profile.lstrip('/')}"
        return int(row["id"]), _text(row.get("name")) or "Unknown", profile

    @staticmethod
    def _public_profile_url(row):
        if not isinstance(row, dict):
            return ""
        profile = _text(row.get("profile_url") or row.get("profile_path"))
        if profile and not profile.startswith(("http://", "https://")):
            profile = f"https://image.tmdb.org/t/p/w185/{profile.lstrip('/')}"
        return profile

    @classmethod
    def _merge_localized_people(cls, base_people, localized_people):
        base_people = [dict(row) for row in (base_people or []) if isinstance(row, dict)]
        localized_people = [dict(row) for row in (localized_people or []) if isinstance(row, dict)]
        base_by_id = {_integer(row.get("id")): row for row in base_people if _integer(row.get("id"))}
        merged = []
        seen = set()
        for localized in localized_people:
            person_id = _integer(localized.get("id"))
            if not person_id or person_id in seen:
                continue
            base = dict(base_by_id.get(person_id) or {})
            person = {**base, "id": person_id}
            for key in ("name", "character", "job"):
                localized_text = _arabic_text(localized.get(key))
                if localized_text:
                    person[key] = localized_text
            person["profile_url"] = cls._public_profile_url(localized) or cls._public_profile_url(base)
            merged.append(person)
            seen.add(person_id)
        for base in base_people:
            person_id = _integer(base.get("id"))
            if not person_id or person_id in seen:
                continue
            person = dict(base)
            person["profile_url"] = cls._public_profile_url(base)
            merged.append(person)
            seen.add(person_id)
        return merged

    @classmethod
    def _localized_display(cls, item, localized, locale="ar-SA"):
        localized = dict(localized or {})
        base = dict(item.get("base_display") or {})
        credits = localized.get("credits") if isinstance(localized.get("credits"), dict) else localized
        arabic_original = _text(item.get("original_language")) == "ar"
        if arabic_original:
            title = _arabic_title(
                localized.get("title"), localized.get("original_title"), item.get("original_title"),
                item.get("provider_title"), base.get("title"),
            )
        else:
            title = _arabic_text(localized.get("title")) or _text(base.get("title"))
        base_genres = [dict(row) if isinstance(row, dict) else {"name": _text(row)} for row in (base.get("genres") or [])]
        base_genres_by_id = {_integer(row.get("id")): row for row in base_genres if _integer(row.get("id"))}
        localized_genres = localized.get("genres") if isinstance(localized.get("genres"), list) else []
        genres = []
        seen_genres = set()
        for row in localized_genres:
            if not isinstance(row, dict):
                continue
            genre_id = _integer(row.get("id"))
            localized_name = _arabic_text(row.get("name"))
            if not localized_name:
                continue
            genres.append({**base_genres_by_id.get(genre_id, {}), **row, "name": localized_name})
            if genre_id:
                seen_genres.add(genre_id)
        genres.extend(row for row in base_genres if not _integer(row.get("id")) or _integer(row.get("id")) not in seen_genres)
        base_collection = base.get("collection") if isinstance(base.get("collection"), dict) else {}
        localized_collection = localized.get("collection") if isinstance(localized.get("collection"), dict) else {}
        collection_name = _arabic_text(localized_collection.get("name"))
        collection = {**base_collection, **({**localized_collection, "name": collection_name} if collection_name else {})}
        return {
            "locale": _text(locale) or "ar-SA",
            "title": title,
            "original_title": _text(item.get("original_title") or base.get("original_title") or title),
            "plot": _arabic_text(localized.get("plot")) or _arabic_text(item.get("provider_plot")) or _text(base.get("plot")),
            "poster_url": _text(localized.get("poster_url") or base.get("poster_url")),
            "backdrop_url": _text(localized.get("backdrop_url") or base.get("backdrop_url")),
            "genres": genres,
            "collection": collection,
            "directors": cls._merge_localized_people(base.get("directors"), credits.get("directors")),
            "writers": cls._merge_localized_people(base.get("writers"), credits.get("writers")),
            "cast": cls._merge_localized_people(base.get("cast"), credits.get("cast")),
        }

    def _save_tmdb_movie(self, connection, movie):
        tmdb_id = _integer(movie.get("tmdb_id"))
        if tmdb_id <= 0:
            raise ValueError("A valid TMDB movie snapshot is required")
        connection.execute(
            """INSERT INTO tmdb_movies(
                tmdb_id,title,original_title,plot,poster_url,backdrop_url,rating,vote_count,
                release_date,year,runtime,original_language,certification,raw_json,updated_at,imdb_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(tmdb_id) DO UPDATE SET
                title=excluded.title,original_title=excluded.original_title,plot=excluded.plot,
                poster_url=excluded.poster_url,backdrop_url=excluded.backdrop_url,rating=excluded.rating,
                vote_count=excluded.vote_count,release_date=excluded.release_date,year=excluded.year,
                runtime=excluded.runtime,original_language=excluded.original_language,
                certification=excluded.certification,raw_json=excluded.raw_json,
                updated_at=excluded.updated_at,imdb_id=excluded.imdb_id""",
            (
                tmdb_id, _text(movie.get("title")) or "Untitled", _text(movie.get("original_title")),
                _text(movie.get("plot")), _text(movie.get("poster_url")), _text(movie.get("backdrop_url")),
                _number(movie.get("rating")), _integer(movie.get("vote_count")), _text(movie.get("release_date")),
                _integer(movie.get("year")), _integer(movie.get("runtime")), _text(movie.get("original_language")),
                _text(movie.get("certification")), json.dumps(movie.get("raw") or {}, ensure_ascii=False, separators=(",", ":")), time.time(),
                _text(movie.get("imdb_id")) if re.fullmatch(r"tt[0-9]{5,12}", _text(movie.get("imdb_id"))) else "",
            ),
        )
        for table in ("movie_genres", "movie_credits", "movie_keywords", "movie_collections", "movie_languages", "movie_countries"):
            connection.execute(f"DELETE FROM {table} WHERE tmdb_id=?", (tmdb_id,))
        for genre in movie.get("genres") or []:
            if not isinstance(genre, dict) or not genre.get("id"):
                continue
            connection.execute("""INSERT INTO genres(genre_id,name) VALUES (?,?)
                                  ON CONFLICT(genre_id) DO UPDATE SET name=excluded.name""", (int(genre["id"]), _text(genre.get("name"))))
            connection.execute("INSERT INTO movie_genres(tmdb_id,genre_id) VALUES (?,?)", (tmdb_id, int(genre["id"])))
        credits = (
            [(row, "director", "Director") for row in movie.get("directors") or []]
            + [(row, "writer", _text(row.get("job")) or "Writer") for row in movie.get("writers") or [] if isinstance(row, dict)]
            + [(row, "cast", "Actor") for row in movie.get("cast") or []]
        )
        for position, (row, department, job) in enumerate(credits):
            person = self._person_row(row)
            if not person:
                continue
            connection.execute("""INSERT INTO people(person_id,name,profile_url) VALUES (?,?,?)
                                  ON CONFLICT(person_id) DO UPDATE SET name=excluded.name,profile_url=excluded.profile_url""", person)
            connection.execute(
                """INSERT OR IGNORE INTO movie_credits(tmdb_id,person_id,department,job,character_name,position)
                   VALUES (?,?,?,?,?,?)""",
                (tmdb_id, person[0], department, job, _text(row.get("character")), position),
            )
        for keyword in movie.get("keywords") or []:
            if not isinstance(keyword, dict) or not keyword.get("id"):
                continue
            connection.execute("""INSERT INTO keywords(keyword_id,name) VALUES (?,?)
                                  ON CONFLICT(keyword_id) DO UPDATE SET name=excluded.name""", (int(keyword["id"]), _text(keyword.get("name"))))
            connection.execute("INSERT INTO movie_keywords(tmdb_id,keyword_id) VALUES (?,?)", (tmdb_id, int(keyword["id"])))
        collection = movie.get("collection") if isinstance(movie.get("collection"), dict) else {}
        if collection.get("id"):
            connection.execute("""INSERT INTO collections(collection_id,name) VALUES (?,?)
                                  ON CONFLICT(collection_id) DO UPDATE SET name=excluded.name""", (int(collection["id"]), _text(collection.get("name"))))
            connection.execute("INSERT INTO movie_collections(tmdb_id,collection_id) VALUES (?,?)", (tmdb_id, int(collection["id"])))
        for language in movie.get("languages") or []:
            if isinstance(language, dict) and _text(language.get("code")):
                connection.execute("INSERT INTO movie_languages(tmdb_id,code,name) VALUES (?,?,?)", (tmdb_id, _text(language.get("code")), _text(language.get("name"))))
        for country in movie.get("countries") or []:
            if isinstance(country, dict) and _text(country.get("code")):
                connection.execute("INSERT INTO movie_countries(tmdb_id,code,name) VALUES (?,?,?)", (tmdb_id, _text(country.get("code")), _text(country.get("name"))))
        self._refresh_search_aliases(connection, source_keys=[], tmdb_ids=[tmdb_id])

    def apply_match(self, movie_key, movie, *, manual=False, method="manual", confidence=100, evidence=None):
        movie_key = validate_movie_key(movie_key)
        tmdb_id = _integer(movie.get("tmdb_id"))
        if tmdb_id <= 0:
            raise ValueError("A valid TMDB movie snapshot is required")
        with self._lock, self.connection(immediate=True) as connection:
            keys = self._source_keys_for_movie(connection, movie_key)
            if not keys:
                raise KeyError("IPTV movie was not found")
            status_before = self._status_contributions(connection, keys)
            old_keys = [self._current_movie_key(connection, key) for key in keys]
            self._save_tmdb_movie(connection, movie)
            state = "matched-manual" if manual else "matched-auto"
            for key in keys:
                row = connection.execute("SELECT manual_lock FROM source_matches WHERE source_key=?", (key,)).fetchone()
                if row and row[0] and not manual:
                    continue
                if manual:
                    classification = connection.execute(
                        "SELECT * FROM source_classifications WHERE source_key=?", (key,)
                    ).fetchone()
                    if classification and classification["manual_lock"] and classification["category"] != "film":
                        raise ValueError(
                            "Resolve the source's manual non-Film classification before matching it to a TMDB movie"
                        )
                    previous = dict(classification) if classification else {}
                    classification_evidence = {
                        "tmdb_id": tmdb_id,
                        "reason": "manual TMDB movie identity",
                    }
                    connection.execute(
                        """UPDATE source_classifications SET category='film',status='classified',
                               confidence=1,method='manual-tmdb-match',evidence_json=?,classifier_version=?,
                               manual_lock=1,review_reason='',updated_at=? WHERE source_key=?""",
                        (
                            json.dumps(classification_evidence, ensure_ascii=False, separators=(",", ":")),
                            CLASSIFIER_VERSION, time.time(), key,
                        ),
                    )
                    connection.execute(
                        """INSERT INTO decision_audit(
                               source_key,domain,previous_json,current_json,method,created_at)
                           VALUES (?,'classification',?,?,?,?)""",
                        (
                            key, json.dumps(previous, ensure_ascii=False, default=str),
                            json.dumps(
                                {"category": "film", "status": "classified", "manual_lock": 1,
                                 "evidence": classification_evidence},
                                ensure_ascii=False,
                            ),
                            "manual-tmdb-match", time.time(),
                        ),
                    )
                connection.execute(
                    """UPDATE source_matches SET state=?,tmdb_id=?,method=?,confidence=?,manual_lock=?,
                       evidence_json=?,error_code='',error_message='',parser_version=?,matcher_version=?,
                       classifier_version=?,terminal_at=?,stale=0,updated_at=? WHERE source_key=?""",
                    (state, tmdb_id, _text(method), float(confidence or 0), int(bool(manual)),
                     json.dumps(evidence or {}, ensure_ascii=False), PARSER_VERSION, MATCHER_VERSION, CLASSIFIER_VERSION,
                     time.time(), time.time(), key),
                )
            new_key = f"tmdb:{tmdb_id}"
            self._merge_memberships(connection, old_keys, new_key)
            self._set_meta(connection, "movie_generation", _integer(self._meta(connection, "movie_generation", 0)) + 1)
            self._apply_status_transitions(connection, status_before, keys)
        return new_key

    @staticmethod
    def _merge_memberships(connection, old_keys, new_key):
        old_keys = list(dict.fromkeys(old_keys))
        if not old_keys:
            return
        placeholders = ",".join("?" for _ in old_keys)
        rows = connection.execute(
            f"""SELECT list_id,MIN(position) position,MIN(added_at) added_at,
                       MIN(source_snapshot_json) snapshot
                FROM movie_list_memberships WHERE movie_key IN ({placeholders})
                GROUP BY list_id""",
            old_keys,
        ).fetchall()
        connection.execute(f"DELETE FROM movie_list_memberships WHERE movie_key IN ({placeholders})", old_keys)
        for row in rows:
            IPTVMovieStore._upsert_membership(connection, row["list_id"], new_key, row["position"], row["added_at"], json.loads(row["snapshot"] or "{}"))

    def remove_match(self, movie_key, *, reprocess=False):
        movie_key = validate_movie_key(movie_key)
        with self._lock, self.connection(immediate=True) as connection:
            keys = self._source_keys_for_movie(connection, movie_key)
            if not keys:
                raise KeyError("IPTV movie was not found")
            status_before = self._status_contributions(connection, keys)
            memberships = connection.execute(
                "SELECT * FROM movie_list_memberships WHERE movie_key=?", (movie_key,)
            ).fetchall()
            connection.execute("DELETE FROM movie_list_memberships WHERE movie_key=?", (movie_key,))
            next_state = "unprocessed" if reprocess else "unmatched"
            next_lock = 0 if reprocess else 1
            for key in keys:
                connection.execute(
                    """UPDATE source_matches SET state=?,tmdb_id=NULL,method=?,confidence=0,manual_lock=?,
                       evidence_json='{}',error_code='',error_message='',parser_version=?,matcher_version=?,
                       terminal_at=?,stale=0,updated_at=? WHERE source_key=?""",
                    (next_state, "reset" if reprocess else "manual-unmatched", next_lock,
                     PARSER_VERSION, MATCHER_VERSION, 0 if reprocess else time.time(), time.time(), key),
                )
                for membership in memberships:
                    self._upsert_membership(
                        connection, membership["list_id"], f"source:{key}",
                        membership["position"], membership["added_at"],
                        json.loads(membership["source_snapshot_json"] or "{}"),
                    )
            self._set_meta(connection, "movie_generation", _integer(self._meta(connection, "movie_generation", 0)) + 1)
            self._apply_status_transitions(connection, status_before, keys)
        return True

    def save_localization(self, tmdb_id, locale, movie):
        tmdb_id = _integer(tmdb_id)
        locale = _text(locale)
        if tmdb_id <= 0 or locale not in {"ar-SA", "en-US"}:
            raise ValueError("Unsupported IPTV movie localization")
        movie = movie if isinstance(movie, dict) else {}
        credits = {
            "directors": movie.get("directors") or [],
            "writers": movie.get("writers") or [],
            "cast": movie.get("cast") or [],
        }
        with self._lock, self.connection(immediate=True) as connection:
            if not connection.execute("SELECT 1 FROM tmdb_movies WHERE tmdb_id=?", (tmdb_id,)).fetchone():
                raise KeyError("IPTV movie metadata was not found")
            connection.execute(
                """INSERT INTO tmdb_movie_localizations(
                       tmdb_id,locale,title,original_title,plot,poster_url,backdrop_url,
                       genres_json,collection_json,credits_json,raw_json,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(tmdb_id,locale) DO UPDATE SET
                       title=excluded.title,original_title=excluded.original_title,plot=excluded.plot,
                       poster_url=excluded.poster_url,backdrop_url=excluded.backdrop_url,
                       genres_json=excluded.genres_json,collection_json=excluded.collection_json,
                       credits_json=excluded.credits_json,raw_json=excluded.raw_json,updated_at=excluded.updated_at""",
                (
                    tmdb_id, locale, _text(movie.get("title")), _text(movie.get("original_title")),
                    _text(movie.get("plot")), _text(movie.get("poster_url")), _text(movie.get("backdrop_url")),
                    json.dumps(movie.get("genres") or [], ensure_ascii=False),
                    json.dumps(movie.get("collection") or {}, ensure_ascii=False),
                    json.dumps(credits, ensure_ascii=False),
                    json.dumps(movie.get("raw") or {}, ensure_ascii=False, separators=(",", ":")),
                    time.time(),
                ),
            )
            self._refresh_search_aliases(connection, source_keys=[], tmdb_ids=[tmdb_id])
        return self.localization(tmdb_id, locale)

    def localization(self, tmdb_id, locale):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM tmdb_movie_localizations WHERE tmdb_id=? AND locale=?",
                (_integer(tmdb_id), _text(locale)),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        for source, target, fallback in (
            ("genres_json", "genres", []),
            ("collection_json", "collection", {}),
            ("credits_json", "credits", {}),
        ):
            try:
                data[target] = json.loads(data.pop(source) or json.dumps(fallback))
            except json.JSONDecodeError:
                data[target] = fallback
        data.pop("raw_json", None)
        return data

    @staticmethod
    def _cards_cte(view="cp"):
        if _text(view) == "provider":
            return """
                WITH cards AS (
                    SELECT 'source:'||s.source_key movie_key,
                           CASE WHEN m.state IN ('matched-auto','matched-manual') THEN m.tmdb_id ELSE NULL END tmdb_id,
                           s.source_key representative_source_key,1 source_count,0 grouped,
                           s.position source_position,CAST(NULLIF(s.added,'') AS REAL) recent_added,
                           s.last_watched,s.watched_completed,m.state metadata_status,
                           m.error_code,m.error_message,COALESCE(sc.category,'unclassified') category,
                           COALESCE(sc.status,'pending') classification_status,
                           COALESCE(sc.confidence,0) classification_confidence,
                           COALESCE(sc.review_reason,'') classification_review_reason
                    FROM movie_sources s
                    JOIN source_matches m USING(source_key)
                    LEFT JOIN source_classifications sc USING(source_key)
                    WHERE s.available=1
                )
            """
        return """
            WITH accepted AS (
                SELECT s.*,m.state,m.tmdb_id,m.manual_lock,m.error_code,m.error_message,
                       COALESCE(sc.category,'unclassified') category,
                       COALESCE(sc.status,'pending') classification_status,
                       COALESCE(sc.confidence,0) classification_confidence,
                       COALESCE(sc.review_reason,'') classification_review_reason
                FROM movie_sources s JOIN source_matches m USING(source_key)
                LEFT JOIN source_classifications sc USING(source_key)
                WHERE s.available=1 AND sc.category='film'
                  AND m.state IN ('matched-auto','matched-manual') AND m.tmdb_id IS NOT NULL
            ),
            matched_cards AS (
                SELECT 'tmdb:'||tmdb_id movie_key,tmdb_id,MIN(source_key) representative_source_key,
                       COUNT(*) source_count,1 grouped,MIN(position) source_position,
                       MAX(CAST(NULLIF(added,'') AS REAL)) recent_added,
                       MAX(last_watched) last_watched,MAX(watched_completed) watched_completed,
                       CASE WHEN MAX(manual_lock)>0 THEN 'matched-manual' ELSE 'matched-auto' END metadata_status,
                       '' error_code,'' error_message,'film' category,'classified' classification_status,
                       MAX(classification_confidence) classification_confidence,'' classification_review_reason
                FROM accepted GROUP BY tmdb_id
            ),
            source_cards AS (
                SELECT 'source:'||s.source_key movie_key,
                       CASE WHEN m.state IN ('matched-auto','matched-manual') THEN m.tmdb_id ELSE NULL END tmdb_id,
                       s.source_key representative_source_key,1 source_count,0 grouped,
                       s.position source_position,CAST(NULLIF(s.added,'') AS REAL) recent_added,
                       s.last_watched,s.watched_completed,m.state metadata_status,m.error_code,m.error_message,
                       COALESCE(sc.category,'unclassified') category,COALESCE(sc.status,'pending') classification_status,
                       COALESCE(sc.confidence,0) classification_confidence,
                       COALESCE(sc.review_reason,'') classification_review_reason
                FROM movie_sources s JOIN source_matches m USING(source_key)
                LEFT JOIN source_classifications sc USING(source_key)
                WHERE s.available=1 AND NOT (
                    COALESCE(sc.category,'unclassified')='film'
                    AND m.state IN ('matched-auto','matched-manual') AND m.tmdb_id IS NOT NULL
                )
            ),
            cards AS (SELECT * FROM matched_cards UNION ALL SELECT * FROM source_cards)
        """

    @staticmethod
    def _member_clause(extra="1=1"):
        return f"""EXISTS(
            SELECT 1 FROM movie_sources ms JOIN source_matches mm USING(source_key)
            WHERE ms.available=1 AND
              ((c.grouped=1 AND mm.tmdb_id=c.tmdb_id AND mm.state IN ('matched-auto','matched-manual'))
               OR (c.grouped=0 AND ms.source_key=c.representative_source_key))
               AND ({extra})
        )"""

    @staticmethod
    def _search_card_ctes(view):
        if _text(view) == "provider":
            card_keys = "SELECT 'source:'||source_key movie_key FROM search_source_hits"
        else:
            card_keys = """
                SELECT DISTINCT CASE
                    WHEN sc.category='film'
                     AND sm.state IN ('matched-auto','matched-manual')
                     AND sm.tmdb_id IS NOT NULL
                    THEN 'tmdb:'||sm.tmdb_id
                    ELSE 'source:'||ssh.source_key
                END movie_key
                FROM search_source_hits ssh
                JOIN movie_sources s ON s.source_key=ssh.source_key AND s.available=1
                JOIN source_matches sm ON sm.source_key=ssh.source_key
                LEFT JOIN source_classifications sc ON sc.source_key=ssh.source_key
            """
        return f""",
            search_alias_hits AS MATERIALIZED (
                SELECT source_key,tmdb_id
                FROM movie_search_aliases
                WHERE instr(normalized_text,?)>0
            ),
            search_source_hits(source_key) AS MATERIALIZED (
                SELECT source_key FROM search_alias_hits WHERE source_key<>''
                UNION
                SELECT sm.source_key
                FROM search_alias_hits sah
                JOIN source_matches sm
                  ON sah.source_key='' AND sah.tmdb_id=sm.tmdb_id
                 AND sm.state IN ('matched-auto','matched-manual')
                JOIN movie_sources s ON s.source_key=sm.source_key AND s.available=1
                WHERE sah.tmdb_id>0
            ),
            search_card_keys(movie_key) AS MATERIALIZED (
                {card_keys}
            )
        """

    @staticmethod
    def _source_filter_clause(view, direct_clause, grouped_clause):
        if _text(view) == "provider":
            return direct_clause
        return f"""((c.grouped=0 AND {direct_clause}) OR
                     (c.grouped=1 AND c.tmdb_id IN (
                         SELECT mm.tmdb_id
                         FROM movie_sources ms JOIN source_matches mm USING(source_key)
                         WHERE ms.available=1
                           AND mm.state IN ('matched-auto','matched-manual')
                           AND mm.tmdb_id IS NOT NULL AND ({grouped_clause})
                     )))"""

    def list_movies(self, filters=None, *, page=1, page_size=30, favorite_list_id=""):
        filters = filters or {}
        view = "cp" if _text(filters.get("view")) == "cp" else "provider"
        cards_cte = self._cards_cte(view)
        page = max(1, _integer(page) or 1)
        page_size = min(100, max(1, _integer(page_size) or 30))
        clauses = []
        params = []
        cte_params = []
        query = normalize_search_text(filters.get("q"))
        if query:
            cards_cte += self._search_card_ctes(view)
            clauses.append("c.movie_key IN (SELECT movie_key FROM search_card_keys)")
            cte_params.append(query)
        category = _text(filters.get("category")).casefold()
        if view == "cp" and category in CATEGORIES - {"unclassified"}:
            clauses.append("c.category=?")
            params.append(category)
        playlist_id = _text(filters.get("playlist_id"))
        if playlist_id:
            clauses.append(self._source_filter_clause(view, "rep.playlist_id=?", "ms.playlist_id=?"))
            params.extend([playlist_id] if view == "provider" else [playlist_id, playlist_id])
        list_id = _text(filters.get("list_id"))
        if list_id:
            clauses.append("""EXISTS(SELECT 1 FROM movie_list_memberships ml
                               WHERE ml.list_id=? AND (ml.movie_key=c.movie_key OR
                                 (c.tmdb_id IS NOT NULL AND ml.movie_key='tmdb:'||c.tmdb_id)))""")
            params.append(list_id)
        if view == "cp":
            genre_id = _integer(filters.get("genre_id"))
            if genre_id:
                clauses.append("c.tmdb_id IS NOT NULL AND EXISTS(SELECT 1 FROM movie_genres mg WHERE mg.tmdb_id=c.tmdb_id AND mg.genre_id=?)")
                params.append(genre_id)
            language = _text(filters.get("language"))
            if language:
                clauses.append("c.tmdb_id IS NOT NULL AND EXISTS(SELECT 1 FROM movie_languages ml WHERE ml.tmdb_id=c.tmdb_id AND ml.code=?)")
                params.append(language)
            country = _text(filters.get("country"))
            if country:
                clauses.append("c.tmdb_id IS NOT NULL AND EXISTS(SELECT 1 FROM movie_countries mc WHERE mc.tmdb_id=c.tmdb_id AND mc.code=?)")
                params.append(country)
            year_from = _integer(filters.get("year_from"))
            year_to = _integer(filters.get("year_to"))
            if year_from:
                clauses.append("c.tmdb_id IS NOT NULL AND t.year>=?")
                params.append(year_from)
            if year_to:
                clauses.append("c.tmdb_id IS NOT NULL AND t.year<=?")
                params.append(year_to)
            rating = _number(filters.get("min_rating"))
            if rating:
                clauses.append("c.tmdb_id IS NOT NULL AND t.rating>=?")
                params.append(rating)
            status = _text(filters.get("metadata_status"))
            if status == "matched":
                clauses.append("c.tmdb_id IS NOT NULL")
            elif status == "failed":
                clauses.append("c.metadata_status IN ('error-retryable','error-terminal')")
            elif status in MATCH_STATES:
                clauses.append("c.metadata_status=?")
                params.append(status)
        quality = _text(filters.get("quality"))
        if quality:
            clauses.append(self._source_filter_clause(view, "rep.quality_claim=?", "ms.quality_claim=?"))
            params.extend([quality] if view == "provider" else [quality, quality])
        if str(filters.get("dubbed") or "").lower() in {"1", "true", "yes"}:
            clauses.append(self._source_filter_clause(view, "rep.dubbed_claim=1", "ms.dubbed_claim=1"))
        if str(filters.get("subtitled") or "").lower() in {"1", "true", "yes"}:
            clauses.append(self._source_filter_clause(view, "rep.subtitled_claim=1", "ms.subtitled_claim=1"))
        watched = _text(filters.get("watched"))
        if watched == "watched":
            clauses.append("c.last_watched>0")
        elif watched == "unwatched":
            clauses.append("c.last_watched<=0")
        where = " AND ".join(clauses) if clauses else "1=1"
        sort = _text(filters.get("sort")) or "recent"
        order = {
            "title": "LOWER(COALESCE(t.title,rep.provider_title)),c.movie_key",
            "rating": "COALESCE(t.rating,rep.provider_rating) DESC,LOWER(COALESCE(t.title,rep.provider_title)),c.movie_key",
            "year-newest": "COALESCE(t.year,rep.provider_year) DESC,LOWER(COALESCE(t.title,rep.provider_title)),c.movie_key",
            "year-oldest": "CASE WHEN COALESCE(t.year,rep.provider_year)=0 THEN 1 ELSE 0 END,COALESCE(t.year,rep.provider_year),LOWER(COALESCE(t.title,rep.provider_title)),c.movie_key",
            "recent": "c.recent_added DESC,c.source_position,c.movie_key",
        }.get(sort, "c.recent_added DESC,c.source_position,c.movie_key")
        page_cte = f""",
            page_cards AS MATERIALIZED (
                SELECT c.*,COUNT(*) OVER() result_total
                FROM cards c
                JOIN movie_sources rep ON rep.source_key=c.representative_source_key
                LEFT JOIN tmdb_movies t ON t.tmdb_id=c.tmdb_id
                WHERE {where}
                ORDER BY {order}
                LIMIT ? OFFSET ?
            )
        """
        select = """SELECT c.*,
                    rep.source_id,rep.provider_title,rep.provider_year,rep.provider_rating,
                    rep.detail_title,rep.detail_year,
                    rep.provider_poster_url,rep.provider_backdrop_url,rep.provider_plot,rep.provider_cast,
                    rep.provider_director,rep.provider_genre,rep.provider_duration,rep.container_extension,
                    rep.playlist_id,rep.playlist_name,rep.quality_claim,rep.dubbed_claim,rep.subtitled_claim,
                    t.title,t.original_title,t.plot,t.poster_url,t.backdrop_url,t.rating,t.vote_count,
                    t.release_date,t.year,t.runtime,t.original_language,t.certification,t.imdb_id,
                    ar.title ar_title,ar.original_title ar_original_title,ar.plot ar_plot,
                    ar.poster_url ar_poster_url,ar.backdrop_url ar_backdrop_url,
                    EXISTS(SELECT 1 FROM movie_list_memberships fav WHERE fav.list_id=? AND
                      (fav.movie_key=c.movie_key OR (c.tmdb_id IS NOT NULL AND fav.movie_key='tmdb:'||c.tmdb_id))) favorite
             FROM page_cards c JOIN movie_sources rep ON rep.source_key=c.representative_source_key
             LEFT JOIN tmdb_movies t ON t.tmdb_id=c.tmdb_id
             LEFT JOIN tmdb_movie_localizations ar ON ar.tmdb_id=c.tmdb_id AND ar.locale='ar-SA'"""
        with self.connection() as connection:
            rows = connection.execute(
                cards_cte + page_cte + select + f" ORDER BY {order}",
                [*cte_params, *params, page_size, (page - 1) * page_size, favorite_list_id],
            ).fetchall()
            total = _integer(rows[0]["result_total"]) if rows else 0
            if not rows and page > 1:
                # A stale out-of-range page still needs an honest total. The
                # common first-page and valid-page paths never repeat the scan.
                total = connection.execute(
                    cards_cte
                    + f""" SELECT COUNT(*) FROM cards c
                           JOIN movie_sources rep ON rep.source_key=c.representative_source_key
                           LEFT JOIN tmdb_movies t ON t.tmdb_id=c.tmdb_id
                           WHERE {where}""",
                    [*cte_params, *params],
                ).fetchone()[0]
            items = [self._public_card(connection, row) for row in rows]
            generation = _integer(self._meta(connection, "movie_generation", 0))
        return {"items": items, "page": page, "page_size": page_size, "total": int(total), "generation": generation, "view": view, "query": query}

    def _public_card(self, connection, row):
        data = dict(row)
        data.pop("result_total", None)
        matched = bool(data.get("tmdb_id"))
        tmdb_id = _integer(data.get("tmdb_id"))
        arabic_default = matched and data.get("original_language") == "ar"
        display_title = (
            _arabic_title(
                data.get("ar_title"), data.get("ar_original_title"), data.get("original_title"),
                data.get("provider_title"), data.get("title"),
            )
            if arabic_default else data.get("title")
        )
        display_plot = _text(data.get("ar_plot") or data.get("provider_plot") or data.get("plot")) if arabic_default else data.get("plot")
        display_poster = data.get("ar_poster_url") if arabic_default and data.get("ar_poster_url") else data.get("poster_url")
        display_backdrop = data.get("ar_backdrop_url") if arabic_default and data.get("ar_backdrop_url") else data.get("backdrop_url")
        data.update({
            "kind": "movie",
            "item_id": data.pop("source_id"),
            "name": display_title if matched else data.get("provider_title"),
            "year": data.get("year") if matched else data.get("provider_year"),
            "rating": data.get("rating") if matched else data.get("provider_rating"),
            "image_url": display_poster if matched else data.get("provider_poster_url"),
            "backdrop_url": display_backdrop if matched else data.get("provider_backdrop_url"),
            "plot": display_plot if matched else data.get("provider_plot"),
            "cast_names": data.get("provider_cast"),
            "director": data.get("provider_director"),
            "genre": data.get("provider_genre"),
            "duration": data.get("runtime") if matched else data.get("provider_duration"),
            "favorite": bool(data.get("favorite")),
            "matched": matched,
            "base_title": data.get("title") if matched else "",
            "base_plot": data.get("plot") if matched else "",
            "base_poster_url": data.get("poster_url") if matched else "",
            "base_backdrop_url": data.get("backdrop_url") if matched else "",
            "display_locale": "ar-SA" if arabic_default else "en-US",
            "external_url": (
                f"https://www.themoviedb.org/movie/{tmdb_id}"
                if matched and (data.get("original_language") == "ar" or not re.fullmatch(r"tt[0-9]{5,12}", _text(data.get("imdb_id"))))
                else f"https://www.imdb.com/title/{data.get('imdb_id')}/" if matched else ""
            ),
        })
        if matched:
            data["genres"] = [dict(item) for item in connection.execute(
                "SELECT g.genre_id id,g.name FROM genres g JOIN movie_genres mg USING(genre_id) WHERE mg.tmdb_id=? ORDER BY g.name,g.genre_id", (tmdb_id,)
            )]
            data["genre"] = ", ".join(row["name"] for row in data["genres"])
        else:
            data["genres"] = []
        for key in ("provider_poster_url", "provider_backdrop_url", "poster_url", "ar_poster_url", "ar_backdrop_url"):
            data.pop(key, None)
        return data

    def movie(self, movie_key, favorite_list_id=""):
        movie_key = validate_movie_key(movie_key)
        view = "provider" if movie_key.startswith("source:") else "cp"
        with self.connection() as connection:
            row = connection.execute(
                self._cards_cte(view) + """
                SELECT c.*,rep.source_id,rep.provider_title,rep.provider_year,rep.provider_rating,
                       rep.detail_title,rep.detail_year,
                       rep.provider_poster_url,rep.provider_backdrop_url,rep.provider_plot,rep.provider_cast,
                       rep.provider_director,rep.provider_genre,rep.provider_duration,rep.container_extension,
                       rep.playlist_id,rep.playlist_name,rep.quality_claim,rep.dubbed_claim,rep.subtitled_claim,
                       t.title,t.original_title,t.plot,t.poster_url,t.backdrop_url,t.rating,t.vote_count,
                       t.release_date,t.year,t.runtime,t.original_language,t.certification,t.imdb_id,
                       ar.title ar_title,ar.original_title ar_original_title,ar.plot ar_plot,
                       ar.poster_url ar_poster_url,ar.backdrop_url ar_backdrop_url,
                       EXISTS(SELECT 1 FROM movie_list_memberships fav WHERE fav.list_id=? AND
                         (fav.movie_key=c.movie_key OR (c.tmdb_id IS NOT NULL AND fav.movie_key='tmdb:'||c.tmdb_id))) favorite
                FROM cards c JOIN movie_sources rep ON rep.source_key=c.representative_source_key
                LEFT JOIN tmdb_movies t ON t.tmdb_id=c.tmdb_id
                LEFT JOIN tmdb_movie_localizations ar ON ar.tmdb_id=c.tmdb_id AND ar.locale='ar-SA'
                WHERE c.movie_key=?
                """,
                (favorite_list_id, movie_key),
            ).fetchone()
            if row is None:
                raise KeyError("IPTV movie was not found")
            item = self._public_card(connection, row)
            item["list_ids"] = [row[0] for row in connection.execute("SELECT list_id FROM movie_list_memberships WHERE movie_key=? ORDER BY list_id", (movie_key,))]
            if item.get("tmdb_id"):
                tmdb_id = int(item["tmdb_id"])
                item["directors"] = [dict(row) for row in connection.execute("SELECT p.person_id id,p.name,p.profile_url FROM people p JOIN movie_credits c USING(person_id) WHERE c.tmdb_id=? AND c.department='director' ORDER BY c.position,p.person_id", (tmdb_id,))]
                item["writers"] = [dict(row) for row in connection.execute("SELECT p.person_id id,p.name,p.profile_url,c.job FROM people p JOIN movie_credits c USING(person_id) WHERE c.tmdb_id=? AND c.department='writer' ORDER BY c.position,p.person_id", (tmdb_id,))]
                item["cast"] = [dict(row) for row in connection.execute("SELECT p.person_id id,p.name,p.profile_url,c.character_name character FROM people p JOIN movie_credits c USING(person_id) WHERE c.tmdb_id=? AND c.department='cast' ORDER BY c.position,p.person_id LIMIT 40", (tmdb_id,))]
                item["keywords"] = [dict(row) for row in connection.execute("SELECT k.keyword_id id,k.name FROM keywords k JOIN movie_keywords mk USING(keyword_id) WHERE mk.tmdb_id=? ORDER BY k.name,k.keyword_id", (tmdb_id,))]
                collection = connection.execute("SELECT c.collection_id id,c.name FROM collections c JOIN movie_collections mc USING(collection_id) WHERE mc.tmdb_id=?", (tmdb_id,)).fetchone()
                item["collection"] = dict(collection) if collection else None
                item["languages"] = [dict(row) for row in connection.execute("SELECT code,name FROM movie_languages WHERE tmdb_id=? ORDER BY name,code", (tmdb_id,))]
                item["countries"] = [dict(row) for row in connection.execute("SELECT code,name FROM movie_countries WHERE tmdb_id=? ORDER BY name,code", (tmdb_id,))]
                localization = connection.execute(
                    "SELECT title,original_title,plot,poster_url,backdrop_url,genres_json,collection_json,credits_json FROM tmdb_movie_localizations WHERE tmdb_id=? AND locale='ar-SA'",
                    (tmdb_id,),
                ).fetchone()
                item["available_locales"] = ["en-US"] + (["ar-SA"] if localization else [])
                item["base_display"] = {
                    "locale": "en-US", "title": item.get("base_title") or item.get("name") or "",
                    "original_title": item.get("original_title") or "", "plot": item.get("base_plot") or "",
                    "poster_url": item.get("base_poster_url") or "", "backdrop_url": item.get("base_backdrop_url") or "",
                    "genres": item.get("genres") or [], "collection": item.get("collection") or {},
                    "directors": item.get("directors") or [], "writers": item.get("writers") or [],
                    "cast": item.get("cast") or [],
                }
                localized = dict(localization) if localization else {}
                if localization:
                    for json_key, output_key, fallback in (
                        ("genres_json", "genres", []), ("collection_json", "collection", {}),
                        ("credits_json", "credits", {}),
                    ):
                        try:
                            localized[output_key] = json.loads(localized.pop(json_key) or json.dumps(fallback))
                        except json.JSONDecodeError:
                            localized[output_key] = fallback
                    item["arabic_display"] = self._localized_display(item, localized, "ar-SA")
                if item.get("original_language") == "ar":
                    # A preserved accepted match can predate localization storage.
                    # Present its Arabic identity immediately, but do not claim a
                    # real Arabic overlay exists: the UI must still retrieve one
                    # when the user returns from English.
                    display = item.get("arabic_display") or self._localized_display(item, {}, "ar-SA")
                    item.update({
                        "name": display["title"], "plot": display["plot"],
                        "image_url": display["poster_url"], "backdrop_url": display["backdrop_url"],
                        "genres": display["genres"],
                        "genre": ", ".join(_text(row.get("name") if isinstance(row, dict) else row) for row in display["genres"] if _text(row.get("name") if isinstance(row, dict) else row)),
                        "collection": display["collection"], "directors": display["directors"],
                        "writers": display["writers"], "cast": display["cast"],
                    })
        item["sources"] = self.sources(movie_key)
        return item

    def merge_localization_display(self, movie, localized, locale="ar-SA"):
        movie = dict(movie or {})
        if not movie.get("base_display"):
            raise ValueError("A complete IPTV movie detail is required")
        return self._localized_display(movie, localized, locale)

    def missing_arabic_localizations(self, limit=100):
        limit = max(1, min(1000, _integer(limit) or 100))
        with self.connection() as connection:
            rows = connection.execute(
                """SELECT DISTINCT t.tmdb_id
                   FROM tmdb_movies t
                   JOIN source_matches m ON m.tmdb_id=t.tmdb_id AND m.state IN ('matched-auto','matched-manual')
                   LEFT JOIN tmdb_movie_localizations ar ON ar.tmdb_id=t.tmdb_id AND ar.locale='ar-SA'
                   WHERE t.original_language='ar' AND ar.tmdb_id IS NULL
                   ORDER BY t.tmdb_id LIMIT ?""",
                (limit,),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def sources(self, movie_key):
        movie_key = validate_movie_key(movie_key)
        with self.connection() as connection:
            keys = self._source_keys_for_movie(connection, movie_key)
            if not keys:
                raise KeyError("IPTV movie was not found")
            placeholders = ",".join("?" for _ in keys)
            rows = connection.execute(
                f"""SELECT source_key,source_id item_id,'movie' kind,provider_title name,provider_year year,
                           provider_rating rating,provider_poster_url image_url,provider_backdrop_url backdrop_url,
                           provider_plot plot,provider_cast cast_names,provider_director director,provider_genre genre,
                           provider_duration duration,container_extension,playlist_id,playlist_name,quality_claim,
                           dubbed_claim,subtitled_claim,available,last_watched,watched_completed
                    FROM movie_sources WHERE source_key IN ({placeholders})
                    ORDER BY available DESC,position,source_key""",
                keys,
            ).fetchall()
        return [dict(row) for row in rows]

    def facets(self):
        with self.connection() as connection:
            playlists = [dict(row) for row in connection.execute(
                """SELECT playlist_id id,playlist_name name,COUNT(*) source_count
                   FROM movie_sources WHERE available=1 GROUP BY playlist_id,playlist_name
                   ORDER BY MIN(position),playlist_name,playlist_id"""
            )]
            genres = [dict(row) for row in connection.execute(
                """SELECT g.genre_id id,g.name,COUNT(DISTINCT mg.tmdb_id) movie_count
                   FROM genres g JOIN movie_genres mg USING(genre_id)
                   JOIN source_matches sm ON sm.tmdb_id=mg.tmdb_id AND sm.state IN ('matched-auto','matched-manual')
                   GROUP BY g.genre_id,g.name ORDER BY g.name,g.genre_id"""
            )]
            languages = [dict(row) for row in connection.execute(
                """SELECT ml.code,ml.name,COUNT(DISTINCT ml.tmdb_id) movie_count
                   FROM movie_languages ml JOIN source_matches sm ON sm.tmdb_id=ml.tmdb_id AND sm.state IN ('matched-auto','matched-manual')
                   GROUP BY ml.code,ml.name ORDER BY ml.name,ml.code"""
            )]
            countries = [dict(row) for row in connection.execute(
                """SELECT mc.code,mc.name,COUNT(DISTINCT mc.tmdb_id) movie_count
                   FROM movie_countries mc JOIN source_matches sm ON sm.tmdb_id=mc.tmdb_id AND sm.state IN ('matched-auto','matched-manual')
                   GROUP BY mc.code,mc.name ORDER BY mc.name,mc.code"""
            )]
            qualities = [row[0] for row in connection.execute("SELECT DISTINCT quality_claim FROM movie_sources WHERE available=1 AND quality_claim<>'' ORDER BY quality_claim")]
            category_counts = {
                row["category"]: int(row["source_count"])
                for row in connection.execute(
                    """SELECT COALESCE(sc.category,'unclassified') category,COUNT(*) source_count
                       FROM movie_sources s LEFT JOIN source_classifications sc USING(source_key)
                       WHERE s.available=1 GROUP BY COALESCE(sc.category,'unclassified')"""
                )
            }
        categories = [
            {"id": category, "name": category.title(), "source_count": category_counts.get(category, 0)}
            for category in ("film", "sports", "plays", "music", "misc")
        ]
        return {"playlists": playlists, "categories": categories, "unclassified": category_counts.get("unclassified", 0), "genres": genres, "languages": languages, "countries": countries, "qualities": qualities}

    def prepare_enrichment(self, *, consent=False, diagnostic_limit=0):
        now = time.time()
        token = uuid.uuid4().hex
        with self._lock, self.connection(immediate=True) as connection:
            affected_keys = [row[0] for row in connection.execute("SELECT source_key FROM movie_sources")]
            status_before = self._status_contributions(connection, affected_keys)
            lease = connection.execute("SELECT * FROM worker_lease WHERE lease_id=1").fetchone()
            if not bool(lease["consent"]) and not consent:
                raise ValueError("Confirm Improve this provider's Movies before starting metadata enrichment")
            connection.execute("UPDATE enrichment_queue SET status='pending',claimed_at=0,updated_at=? WHERE status='running'", (now,))
            connection.execute(
                """INSERT INTO enrichment_queue(source_key,status,attempts,next_attempt_at,last_error,updated_at,priority,work_key,claimed_at,completed_at)
                   SELECT s.source_key,'pending',0,0,'',?,0,
                           CASE WHEN s.work_title<>'' THEN 'query:'||s.work_title||':'||s.work_year
                                WHEN s.provider_tmdb_id>0 THEN 'tmdb:'||s.provider_tmdb_id
                                ELSE 'source:'||s.source_key END,0,0
                    FROM movie_sources s JOIN source_matches m USING(source_key)
                    JOIN source_classifications sc USING(source_key)
                    WHERE s.available=1 AND m.manual_lock=0
                      AND sc.category='film' AND sc.status='classified'
                      AND m.state IN ('unprocessed','provider-id-pending','search-pending','error-retryable')
                   ON CONFLICT(source_key) DO UPDATE SET
                     status=CASE WHEN enrichment_queue.status IN ('cancelled','failed') THEN 'pending' ELSE enrichment_queue.status END,
                     next_attempt_at=0,last_error='',work_key=excluded.work_key,claimed_at=0,updated_at=excluded.updated_at""",
                (now,),
            )
            connection.execute(
                """INSERT INTO work_clusters(work_key,state,member_count,updated_at)
                   SELECT work_key,'pending',COUNT(*),? FROM enrichment_queue
                   WHERE status='pending' AND work_key<>'' GROUP BY work_key
                   ON CONFLICT(work_key) DO UPDATE SET
                     state=CASE WHEN work_clusters.state='running' THEN work_clusters.state ELSE 'pending' END,
                     member_count=excluded.member_count,updated_at=excluded.updated_at""",
                (now,),
            )
            connection.execute(
                """UPDATE worker_lease SET token=?,pid=0,state='starting',command='run',
                       consent=CASE WHEN ? THEN 1 ELSE consent END,restart_confirmation_required=0,
                       diagnostic_limit=?,heartbeat_at=?,lease_expires_at=?,started_at=?,finished_at=0,
                       error='',retry_reason='',backoff_until=0 WHERE lease_id=1""",
                (token, int(bool(consent)), max(0, _integer(diagnostic_limit)), now, now + 90, now),
            )
            self._set_meta(connection, "worker_command", "run")
            self._set_meta(connection, "worker_state", "starting")
            self._apply_status_transitions(connection, status_before, affected_keys)
        return token

    def schedule_enrichment(self, *, consent=False, diagnostic_limit=0):
        """Persist worker intent without classifying or populating the catalog queue."""
        now = time.time()
        token = uuid.uuid4().hex
        with self._lock, self.connection(immediate=True, control=True) as connection:
            lease = connection.execute(
                "SELECT consent FROM worker_lease WHERE lease_id=1"
            ).fetchone()
            if not bool(lease["consent"]) and not consent:
                raise ValueError("Confirm Improve this provider's Movies before starting metadata enrichment")
            affected_keys = [row[0] for row in connection.execute(
                "SELECT source_key FROM enrichment_queue WHERE status='running'"
            )]
            status_before = self._status_contributions(connection, affected_keys)
            # At most one bounded cluster can be running. Releasing it makes a
            # previous crash or forced shutdown restart-safe without scanning
            # or rewriting the complete queue.
            connection.execute(
                """UPDATE enrichment_queue SET status='pending',claimed_at=0,updated_at=?
                   WHERE status='running'""",
                (now,),
            )
            connection.execute(
                """UPDATE worker_lease SET token=?,pid=0,state='starting',command='run',
                       consent=CASE WHEN ? THEN 1 ELSE consent END,
                       restart_confirmation_required=0,diagnostic_limit=?,heartbeat_at=?,
                       lease_expires_at=?,started_at=CASE WHEN started_at=0 THEN ? ELSE started_at END,
                       finished_at=0,error='',retry_reason='',backoff_until=0 WHERE lease_id=1""",
                (
                    token, int(bool(consent)), max(0, _integer(diagnostic_limit)),
                    now, now + 90, now,
                ),
            )
            self._set_meta(connection, "worker_command", "run")
            self._set_meta(connection, "worker_state", "starting")
            self._apply_status_transitions(connection, status_before, affected_keys)
        return token

    def stage_enrichment_batch(self, limit=ENRICHMENT_STAGE_BATCH_SIZE):
        """Queue one bounded page of eligible Film sources on the worker."""
        limit = min(ENRICHMENT_STAGE_BATCH_SIZE, max(1, _integer(limit) or 1))
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            rows = connection.execute(
                """SELECT s.source_key,
                          CASE WHEN s.work_title<>'' THEN 'query:'||s.work_title||':'||s.work_year
                               WHEN s.provider_tmdb_id>0 THEN 'tmdb:'||s.provider_tmdb_id
                               ELSE 'source:'||s.source_key END work_key
                     FROM movie_sources s
                     JOIN source_matches m USING(source_key)
                     JOIN source_classifications sc USING(source_key)
                     LEFT JOIN enrichment_queue q USING(source_key)
                    WHERE s.available=1 AND m.manual_lock=0
                      AND sc.category='film' AND sc.status='classified'
                      AND m.state IN ('unprocessed','provider-id-pending','search-pending','error-retryable')
                      AND (q.source_key IS NULL OR q.status IN ('cancelled','failed'))
                    ORDER BY s.position,s.source_key LIMIT ?""",
                (limit,),
            ).fetchall()
            if not rows:
                return 0
            staged_keys = [row["source_key"] for row in rows]
            status_before = self._status_contributions(connection, staged_keys)
            connection.executemany(
                """INSERT INTO enrichment_queue(
                       source_key,status,attempts,next_attempt_at,last_error,updated_at,
                       priority,work_key,claimed_at,completed_at)
                   VALUES (?,'pending',0,0,'',?,0,?,0,0)
                   ON CONFLICT(source_key) DO UPDATE SET status='pending',next_attempt_at=0,
                       last_error='',work_key=excluded.work_key,claimed_at=0,completed_at=0,
                       updated_at=excluded.updated_at""",
                [(row["source_key"], now, row["work_key"]) for row in rows],
            )
            clusters = {}
            for row in rows:
                clusters[row["work_key"]] = clusters.get(row["work_key"], 0) + 1
            connection.executemany(
                """INSERT INTO work_clusters(work_key,state,member_count,updated_at)
                   VALUES (?,'pending',?,?)
                   ON CONFLICT(work_key) DO UPDATE SET
                     state=CASE WHEN work_clusters.state='running' THEN 'running' ELSE 'pending' END,
                     member_count=work_clusters.member_count+excluded.member_count,
                     updated_at=excluded.updated_at""",
                [(key, count, now) for key, count in clusters.items() if key],
            )
            self._apply_status_transitions(connection, status_before, staged_keys)
        return len(rows)

    def worker_waiting_for_capacity(self, token):
        with self._lock, self.connection(immediate=True, control=True) as connection:
            cursor = connection.execute(
                """UPDATE worker_lease SET pid=0,state='waiting-capacity',command='run',
                       heartbeat_at=?,lease_expires_at=0 WHERE lease_id=1 AND token=?""",
                (time.time(), _text(token)),
            )
            if not cursor.rowcount:
                raise RuntimeError("The IPTV metadata worker lease was lost")

    def current_worker_token(self):
        with self.connection(control=True) as connection:
            row = connection.execute("SELECT token FROM worker_lease WHERE lease_id=1").fetchone()
        return _text(row[0]) if row else ""

    def resume_worker(self, *, continue_after_restart=False):
        status = self.worker_control_status()
        if status["restart_confirmation_required"] and not continue_after_restart:
            raise ValueError("Confirm Continue metadata improvement after restart")
        if not status["consent"]:
            raise ValueError("Confirm Improve this provider's Movies before starting metadata enrichment")
        token = uuid.uuid4().hex
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            affected_keys = [row[0] for row in connection.execute(
                "SELECT source_key FROM enrichment_queue WHERE status='running'"
            )]
            status_before = self._status_contributions(connection, affected_keys)
            connection.execute(
                """UPDATE enrichment_queue SET status='pending',claimed_at=0,updated_at=? WHERE status='running'""",
                (now,),
            )
            connection.execute(
                """UPDATE worker_lease SET token=?,pid=0,state='starting',command='run',
                       restart_confirmation_required=0,heartbeat_at=?,lease_expires_at=?,
                       started_at=CASE WHEN started_at=0 THEN ? ELSE started_at END,
                       finished_at=0,error='',retry_reason='',backoff_until=0 WHERE lease_id=1""",
                (token, now, now + 90, now),
            )
            self._apply_status_transitions(connection, status_before, affected_keys)
        return token

    def worker_backoff(self, token, reason, until):
        with self._lock, self.connection(immediate=True) as connection:
            connection.execute(
                """UPDATE worker_lease SET retry_reason=?,backoff_until=?,heartbeat_at=?
                   WHERE lease_id=1 AND token=?""",
                (_text(reason)[:200], float(until or 0), time.time(), _text(token)),
            )

    def worker_command(self, command):
        if command not in {"run", "pause", "cancel", "idle"}:
            raise ValueError("Unsupported IPTV enrichment command")
        with self._lock, self.connection(immediate=True, control=True) as connection:
            lease = connection.execute("SELECT pid FROM worker_lease WHERE lease_id=1").fetchone()
            self._set_meta(connection, "worker_command", command)
            next_state = "pausing" if command == "pause" else "cancelling" if command == "cancel" else "starting" if command == "run" else "idle"
            if command == "pause" and (not lease or not _integer(lease["pid"])):
                next_state = "paused"
            if command == "cancel" and (not lease or not _integer(lease["pid"])):
                next_state = "cancelled"
                command = "idle"
            connection.execute(
                "UPDATE worker_lease SET command=?,state=?,heartbeat_at=? WHERE lease_id=1",
                (command, next_state, time.time()),
            )
            if command == "pause":
                self._set_meta(connection, "worker_state", "pausing")
            elif command == "cancel":
                self._set_meta(connection, "worker_state", "cancelling")
        return self.worker_control_status()

    def worker_run_requested(self, token=""):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT token,command FROM worker_lease WHERE lease_id=1"
            ).fetchone()
        return bool(
            row
            and (not token or row["token"] == _text(token))
            and row["command"] == "run"
        )

    def worker_command_state(self, token=""):
        """Read only the cooperative worker command with the data-path wait."""
        with self.connection() as connection:
            row = connection.execute(
                "SELECT token,command,state FROM worker_lease WHERE lease_id=1"
            ).fetchone()
        if token and (not row or row["token"] != _text(token)):
            raise RuntimeError("The IPTV metadata worker lease was lost")
        return {
            "command": row["command"] if row else "idle",
            "state": row["state"] if row else "idle",
        }

    def worker_started(self, pid, token=""):
        with self._lock, self.connection(immediate=True) as connection:
            lease = connection.execute("SELECT token FROM worker_lease WHERE lease_id=1").fetchone()
            effective = _text(token) or (lease["token"] if lease else "")
            if token and (not lease or lease["token"] != effective):
                raise RuntimeError("The IPTV metadata worker lease was lost")
            command = connection.execute("SELECT command FROM worker_lease WHERE lease_id=1").fetchone()[0]
            state = "running" if command == "run" else "pausing" if command == "pause" else "cancelling" if command == "cancel" else "idle"
            self._set_meta(connection, "worker_pid", int(pid or 0))
            self._set_meta(connection, "worker_state", state)
            connection.execute(
                """UPDATE worker_lease SET pid=?,state=?,heartbeat_at=?,lease_expires_at=?
                   WHERE lease_id=1 AND token=?""",
                (int(pid or 0), state, time.time(), time.time() + 90, effective),
            )

    def worker_heartbeat(self, token):
        with self._lock, self.connection(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE worker_lease SET heartbeat_at=?,lease_expires_at=?
                   WHERE lease_id=1 AND token=? AND state IN ('starting','running','pausing','cancelling')""",
                (time.time(), time.time() + 90, _text(token)),
            )
            if not cursor.rowcount:
                raise RuntimeError("The IPTV metadata worker lease was lost")

    def worker_finished(self, state="complete", error="", token=""):
        with self._lock, self.connection(immediate=True) as connection:
            clause = " AND token=?" if token else ""
            cursor = connection.execute(
                f"""UPDATE worker_lease SET pid=0,state=?,command=?,heartbeat_at=?,lease_expires_at=0,
                           finished_at=?,error=?,restart_confirmation_required=0
                       WHERE lease_id=1{clause}""",
                [state, "pause" if state == "paused" else "idle", time.time(), time.time(), _text(error)[:500], *([_text(token)] if token else [])],
            )
            if token and not cursor.rowcount:
                return False
            self._set_meta(connection, "worker_pid", 0)
            self._set_meta(connection, "worker_state", state)
            self._set_meta(connection, "worker_command", "idle" if state != "paused" else "pause")
            self._set_meta(connection, "worker_error", _text(error)[:500])
            self._set_meta(connection, "worker_finished_at", time.time())
        return True

    def cancel_enrichment(self):
        now = time.time()
        with self._lock, self.connection(immediate=True, control=True) as connection:
            affected_keys = [row[0] for row in connection.execute(
                "SELECT source_key FROM enrichment_queue WHERE status='running'"
            )]
            status_before = self._status_contributions(connection, affected_keys)
            connection.execute(
                """UPDATE enrichment_queue SET status='pending',claimed_at=0,updated_at=?
                   WHERE status='running'""",
                (now,),
            )
            self._set_meta(connection, "worker_pid", 0)
            self._set_meta(connection, "worker_state", "cancelled")
            self._set_meta(connection, "worker_command", "idle")
            self._set_meta(connection, "worker_error", "")
            self._set_meta(connection, "worker_finished_at", now)
            connection.execute(
                """UPDATE worker_lease SET pid=0,state='cancelled',command='idle',heartbeat_at=?,
                       lease_expires_at=0,finished_at=?,error='',retry_reason='',backoff_until=0
                   WHERE lease_id=1""",
                (now, now),
            )
            self._apply_status_transitions(connection, status_before, affected_keys)
        return self.worker_control_status()

    def checkpoint_paused_after_stop(self, reason=""):
        """Reconcile a terminated worker in one bounded shutdown transaction."""
        now = time.time()
        with self._lock, self.connection(immediate=True, control=True) as connection:
            affected_keys = [row[0] for row in connection.execute(
                "SELECT source_key FROM enrichment_queue WHERE status='running'"
            )]
            status_before = self._status_contributions(connection, affected_keys)
            connection.execute(
                """UPDATE enrichment_queue SET status='pending',claimed_at=0,updated_at=?
                   WHERE status='running'""",
                (now,),
            )
            connection.execute(
                """UPDATE work_clusters SET state='pending',lease_token='',claimed_at=0,
                       updated_at=? WHERE state='running'""",
                (now,),
            )
            connection.execute(
                """UPDATE worker_lease SET pid=0,state='paused',command='pause',heartbeat_at=?,
                       lease_expires_at=0,finished_at=?,error=?,restart_confirmation_required=0
                   WHERE lease_id=1""",
                (now, now, _text(reason)[:500]),
            )
            self._set_meta(connection, "worker_pid", 0)
            self._set_meta(connection, "worker_state", "paused")
            self._set_meta(connection, "worker_command", "pause")
            self._set_meta(connection, "worker_error", _text(reason)[:500])
            self._set_meta(connection, "worker_finished_at", now)
            self._apply_status_transitions(connection, status_before, affected_keys)

    def claim_next(self, token=""):
        with self._lock, self.connection(immediate=True) as connection:
            lease = connection.execute("SELECT * FROM worker_lease WHERE lease_id=1").fetchone()
            if token and (not lease or lease["token"] != _text(token)):
                raise RuntimeError("The IPTV metadata worker lease was lost")
            command = lease["command"] if lease else self._meta(connection, "worker_command", "idle")
            if command != "run":
                return None
            row = connection.execute(
                """SELECT q.source_key FROM enrichment_queue q JOIN movie_sources s USING(source_key)
                   WHERE q.status='pending' AND q.next_attempt_at<=? AND s.available=1
                   ORDER BY q.priority DESC,q.updated_at,s.position,q.source_key LIMIT 1""",
                (time.time(),),
            ).fetchone()
            if not row:
                return None
            status_before = self._status_contributions(connection, [row[0]])
            connection.execute(
                "UPDATE enrichment_queue SET status='running',attempts=attempts+1,claimed_at=?,updated_at=? WHERE source_key=?",
                (time.time(), time.time(), row[0]),
            )
            if lease:
                connection.execute(
                    "UPDATE worker_lease SET heartbeat_at=?,lease_expires_at=? WHERE lease_id=1",
                    (time.time(), time.time() + 90),
                )
            self._apply_status_transitions(connection, status_before, [row[0]])
            return row[0]

    def claim_next_cluster(self, token="", limit=ENRICHMENT_CLUSTER_MEMBER_LIMIT):
        """Atomically claim one provider-local work cluster and all pending members."""
        with self._lock, self.connection(immediate=True) as connection:
            lease = connection.execute("SELECT * FROM worker_lease WHERE lease_id=1").fetchone()
            if token and (not lease or lease["token"] != _text(token)):
                raise RuntimeError("The IPTV metadata worker lease was lost")
            if not lease or lease["command"] != "run":
                return None
            row = connection.execute(
                """SELECT q.work_key FROM enrichment_queue q
                   JOIN movie_sources s USING(source_key)
                   JOIN source_classifications sc USING(source_key)
                   WHERE q.status='pending' AND q.next_attempt_at<=? AND s.available=1
                     AND sc.category='film' AND q.work_key<>''
                   ORDER BY q.priority DESC,q.updated_at,s.position,q.source_key LIMIT 1""",
                (time.time(),),
            ).fetchone()
            if not row:
                return None
            work_key = row["work_key"]
            limit = min(ENRICHMENT_CLUSTER_MEMBER_LIMIT, max(1, _integer(limit) or 1))
            members = [item[0] for item in connection.execute(
                """SELECT q.source_key FROM enrichment_queue q
                   JOIN movie_sources s USING(source_key)
                   JOIN source_classifications sc USING(source_key)
                   WHERE q.work_key=? AND q.status='pending' AND q.next_attempt_at<=?
                     AND s.available=1 AND sc.category='film'
                   ORDER BY q.priority DESC,s.position,q.source_key LIMIT ?""",
                (work_key, time.time(), limit),
            )]
            if not members:
                return None
            status_before = self._status_contributions(connection, members)
            placeholders = ",".join("?" for _ in members)
            now = time.time()
            connection.execute(
                f"""UPDATE enrichment_queue SET status='running',attempts=attempts+1,
                           claimed_at=?,updated_at=? WHERE source_key IN ({placeholders})""",
                (now, now, *members),
            )
            connection.execute(
                """INSERT INTO work_clusters(work_key,state,lease_token,claimed_at,member_count,updated_at)
                   VALUES (?,'running',?,?,?,?)
                   ON CONFLICT(work_key) DO UPDATE SET state='running',lease_token=excluded.lease_token,
                     claimed_at=excluded.claimed_at,completed_at=0,member_count=excluded.member_count,
                     accepted_count=0,review_count=0,rejected_count=0,failed_count=0,
                     updated_at=excluded.updated_at""",
                (work_key, _text(token), now, len(members), now),
            )
            connection.execute(
                "UPDATE worker_lease SET heartbeat_at=?,lease_expires_at=? WHERE lease_id=1",
                (now, now + 90),
            )
            self._apply_status_transitions(connection, status_before, members)
            return {"work_key": work_key, "source_keys": members}

    def release_cluster(self, work_key, token=""):
        """Return unprocessed claimed members to the durable pending queue."""
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            members = [row[0] for row in connection.execute(
                "SELECT source_key FROM enrichment_queue WHERE work_key=? AND status='running'",
                (_text(work_key),),
            )]
            status_before = self._status_contributions(connection, members)
            row = connection.execute(
                "SELECT lease_token FROM work_clusters WHERE work_key=?", (_text(work_key),)
            ).fetchone()
            if row and token and row["lease_token"] != _text(token):
                raise RuntimeError("The IPTV metadata cluster lease was lost")
            connection.execute(
                """UPDATE enrichment_queue SET status='pending',claimed_at=0,updated_at=?
                   WHERE work_key=? AND status='running'""",
                (now, _text(work_key)),
            )
            connection.execute(
                """UPDATE work_clusters SET state='pending',lease_token='',claimed_at=0,
                       updated_at=? WHERE work_key=?""",
                (now, _text(work_key)),
            )
            self._apply_status_transitions(connection, status_before, members)

    def finish_cluster(self, work_key, token=""):
        with self._lock, self.connection(immediate=True, control=True) as connection:
            row = connection.execute(
                "SELECT lease_token FROM work_clusters WHERE work_key=?", (_text(work_key),)
            ).fetchone()
            if not row or (token and row["lease_token"] != _text(token)):
                raise RuntimeError("The IPTV metadata cluster lease was lost")
            counts = {"accepted": 0, "review": 0, "rejected": 0, "failed": 0}
            for item in connection.execute(
                """SELECT m.state,q.status FROM enrichment_queue q
                   JOIN source_matches m USING(source_key) WHERE q.work_key=?""",
                (_text(work_key),),
            ):
                if item["state"] in ACCEPTED_STATES:
                    counts["accepted"] += 1
                elif item["state"] == "ambiguous":
                    counts["review"] += 1
                elif item["state"] in {"unmatched"}:
                    counts["rejected"] += 1
                elif item["state"] in {"error-retryable", "error-terminal"} or item["status"] == "failed":
                    counts["failed"] += 1
            connection.execute(
                """UPDATE work_clusters SET state='complete',lease_token='',completed_at=?,
                       accepted_count=?,review_count=?,rejected_count=?,failed_count=?,updated_at=?
                   WHERE work_key=?""",
                (
                    time.time(), counts["accepted"], counts["review"], counts["rejected"],
                    counts["failed"], time.time(), _text(work_key),
                ),
            )
        return counts

    def finish_job(self, source_key_value, *, status="done", retry_after=0, error=""):
        if status not in {"pending", "done", "cancelled", "failed"}:
            raise ValueError("Unsupported IPTV enrichment queue status")
        with self._lock, self.connection(immediate=True) as connection:
            key = _text(source_key_value)
            status_before = self._status_contributions(connection, [key])
            connection.execute(
                """UPDATE enrichment_queue SET status=?,next_attempt_at=?,last_error=?,updated_at=?
                   WHERE source_key=?""",
                (status, time.time() + max(0, int(retry_after or 0)), _text(error)[:500], time.time(), _text(source_key_value)),
            )
            if status == "done":
                self._set_meta(connection, "movie_generation", _integer(self._meta(connection, "movie_generation", 0)) + 1)
                connection.execute(
                    "UPDATE enrichment_queue SET completed_at=? WHERE source_key=?",
                    (time.time(), _text(source_key_value)),
                )
                connection.execute("UPDATE worker_lease SET checkpoint=checkpoint+1 WHERE lease_id=1")
            self._apply_status_transitions(connection, status_before, [key])

    def retry_failures(self):
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            affected_keys = [row[0] for row in connection.execute(
                """SELECT source_key FROM source_matches WHERE manual_lock=0 AND state='error-terminal'
                   UNION SELECT source_key FROM enrichment_queue WHERE status='failed'"""
            )]
            status_before = self._status_contributions(connection, affected_keys)
            connection.execute(
                """UPDATE source_matches SET state='error-retryable',terminal_at=0,error_message='',updated_at=?
                   WHERE manual_lock=0 AND state='error-terminal'""",
                (now,),
            )
            cursor = connection.execute(
                """UPDATE enrichment_queue SET status='pending',next_attempt_at=0,last_error='',claimed_at=0,updated_at=?
                   WHERE status='failed'""",
                (now,),
            )
            self._apply_status_transitions(connection, status_before, affected_keys)
        return int(cursor.rowcount)

    def mark_stale_automatic_results(self):
        with self._lock, self.connection(immediate=True) as connection:
            affected_keys = [row[0] for row in connection.execute(
                """SELECT source_key FROM source_matches
                   WHERE manual_lock=0 AND state IN ('ambiguous','unmatched')
                     AND (parser_version<>? OR matcher_version<>?)""",
                (PARSER_VERSION, MATCHER_VERSION),
            )]
            status_before = self._status_contributions(connection, affected_keys)
            cursor = connection.execute(
                """UPDATE source_matches SET stale=1
                   WHERE manual_lock=0 AND state IN ('ambiguous','unmatched')
                     AND (parser_version<>? OR matcher_version<>?)""",
                (PARSER_VERSION, MATCHER_VERSION),
            )
            self._apply_status_transitions(connection, status_before, affected_keys)
        return int(cursor.rowcount)

    def re_evaluate_stale(self):
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            rows = [row[0] for row in connection.execute(
                "SELECT source_key FROM source_matches WHERE stale=1 AND manual_lock=0 ORDER BY source_key"
            )]
            status_before = self._status_contributions(connection, rows)
            for key in rows:
                connection.execute(
                    """UPDATE source_matches SET state='unprocessed',tmdb_id=NULL,method='stale-re-evaluation',
                           confidence=0,evidence_json='{}',error_code='',error_message='',terminal_at=0,
                           stale=0,updated_at=? WHERE source_key=?""",
                    (now, key),
                )
                connection.execute(
                    """INSERT INTO enrichment_queue(source_key,status,attempts,next_attempt_at,last_error,updated_at,priority,work_key,claimed_at,completed_at)
                       VALUES (?,'pending',0,0,'',?,25,'',0,0)
                       ON CONFLICT(source_key) DO UPDATE SET status='pending',next_attempt_at=0,
                           last_error='',priority=MAX(priority,25),claimed_at=0,completed_at=0,updated_at=excluded.updated_at""",
                    (key, now),
                )
            self._apply_status_transitions(connection, status_before, rows)
        return len(rows)

    def prioritize_sources(self, source_keys, priority=100):
        keys = list(dict.fromkeys(_text(key) for key in source_keys if _text(key)))[:100]
        if not keys:
            return 0
        with self._lock, self.connection(immediate=True) as connection:
            placeholders = ",".join("?" for _ in keys)
            cursor = connection.execute(
                f"UPDATE enrichment_queue SET priority=MAX(priority,?),updated_at=MIN(updated_at,?) WHERE source_key IN ({placeholders}) AND status='pending'",
                (max(0, _integer(priority)), time.time(), *keys),
            )
        return int(cursor.rowcount)

    def _worker_status_payload(self, meta, lease_data, queue, *, matches=None,
                               sources=0, evaluated=0, grouped=0,
                               distinct_tmdb=0, stale=0, automatic_remaining=0,
                               classification_review=0, needs_review=0,
                               summary_revision=0, summary_updated_at=0,
                               categories=None, summary_available=True):
        matches = matches or {}
        state = lease_data.get("state") or meta.get("worker_state", "idle")
        restart_offer = bool(
            state in {"starting", "running", "pausing", "cancelling"}
            and _number(lease_data.get("lease_expires_at")) < time.time()
        )
        if restart_offer:
            state = "awaiting-continuation"
        return {
            "state": state,
            "command": lease_data.get("command") or meta.get("worker_command", "idle"),
            "pid": _integer(lease_data.get("pid")),
            "error": lease_data.get("error") or meta.get("worker_error", ""),
            "started_at": _number(lease_data.get("started_at")),
            "finished_at": _number(lease_data.get("finished_at")),
            "generation": _integer(meta.get("movie_generation")),
            "source_generation": _integer(meta.get("source_catalog_generation")),
            "sources": int(sources),
            "queue": queue,
            "matches": matches,
            "evaluated": int(evaluated),
            "remaining": max(0, int(sources) - int(evaluated)),
            "grouped_movies": int(grouped),
            "distinct_tmdb_movies": int(distinct_tmdb),
            "stale": int(stale),
            "needs_review": int(needs_review),
            "automatic_remaining": int(automatic_remaining),
            "classification_review": int(classification_review),
            "summary_revision": int(summary_revision),
            "summary_updated_at": float(summary_updated_at or 0),
            "categories": categories or {},
            "summary_available": bool(summary_available),
            "consent": bool(lease_data.get("consent")),
            "restart_confirmation_required": restart_offer or bool(lease_data.get("restart_confirmation_required")),
            "checkpoint": _integer(lease_data.get("checkpoint")),
            "heartbeat_at": _number(lease_data.get("heartbeat_at")),
            "backoff_until": _number(lease_data.get("backoff_until")),
            "retry_reason": _text(lease_data.get("retry_reason")),
            "diagnostic_limit": _integer(lease_data.get("diagnostic_limit")),
            "classifier_version": CLASSIFIER_VERSION,
            "parser_version": PARSER_VERSION,
            "matcher_version": MATCHER_VERSION,
        }

    @staticmethod
    def _status_summary_arguments(summary):
        data = dict(summary or {})
        queue = {
            "pending": _integer(data.get("queue_pending")),
            "running": _integer(data.get("queue_running")),
            "done": _integer(data.get("queue_done")),
            "cancelled": _integer(data.get("queue_cancelled")),
            "failed": _integer(data.get("queue_failed")),
        }
        matches = {
            "unprocessed": _integer(data.get("match_unprocessed")),
            "provider-id-pending": _integer(data.get("match_provider_id_pending")),
            "search-pending": _integer(data.get("match_search_pending")),
            "matched-auto": _integer(data.get("matched_auto")),
            "matched-manual": _integer(data.get("matched_manual")),
            "ambiguous": _integer(data.get("match_ambiguous")),
            "unmatched": _integer(data.get("match_unmatched")),
            "error-retryable": _integer(data.get("match_error_retryable")),
            "error-terminal": _integer(data.get("match_error_terminal")),
        }
        categories = {
            category: _integer(data.get(f"classified_{category}"))
            for category in ("film", "sports", "plays", "music", "misc", "unclassified")
        }
        sources = _integer(data.get("available_sources"))
        grouped = max(
            0,
            sources - _integer(data.get("grouped_member_sources"))
            + _integer(data.get("grouped_identity_count")),
        )
        return {
            "queue": queue,
            "matches": matches,
            "sources": sources,
            "evaluated": _integer(data.get("evaluated")),
            "grouped": grouped,
            "distinct_tmdb": _integer(data.get("distinct_tmdb_movies")),
            "stale": _integer(data.get("stale")),
            "needs_review": _integer(data.get("needs_review")),
            "automatic_remaining": _integer(data.get("automatic_remaining")),
            "classification_review": _integer(data.get("classification_review")),
            "summary_revision": _integer(data.get("revision")),
            "summary_updated_at": _number(data.get("updated_at")),
            "categories": categories,
        }

    def worker_control_status(self):
        """Constant-time exact status for control responses and active polling."""
        with self.connection(control=True) as connection:
            meta = {row["key"]: row["value"] for row in connection.execute(
                """SELECT key,value FROM movie_meta
                   WHERE key IN ('worker_state','worker_command','worker_error',
                                 'movie_generation','source_catalog_generation')"""
            )}
            lease = connection.execute("SELECT * FROM worker_lease WHERE lease_id=1").fetchone()
            summary = connection.execute(
                "SELECT * FROM movie_status_summary WHERE summary_id=1"
            ).fetchone()
        arguments = self._status_summary_arguments(summary)
        return self._worker_status_payload(meta, dict(lease) if lease else {}, **arguments)

    def worker_status(self):
        with self.connection() as connection:
            meta = {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM movie_meta")}
            lease = connection.execute("SELECT * FROM worker_lease WHERE lease_id=1").fetchone()
            summary = connection.execute(
                "SELECT * FROM movie_status_summary WHERE summary_id=1"
            ).fetchone()
        return self._worker_status_payload(
            meta, dict(lease) if lease else {}, **self._status_summary_arguments(summary)
        )

    def review_queue(self, view="needs-review", *, page=1, page_size=50, filters=None):
        page = max(1, _integer(page) or 1)
        page_size = min(100, max(1, _integer(page_size) or 50))
        filters = filters or {}
        clauses = {
            "needs-review": "m.state='ambiguous' OR m.stale=1",
            "unmatched": "m.state='unmatched'",
            "failed": "m.state IN ('error-retryable','error-terminal')",
            "manual": "m.state='matched-manual' OR (m.manual_lock=1 AND m.method='manual-unmatched')",
        }
        where = clauses.get(_text(view), clauses["needs-review"])
        parameters = []
        query = normalize_search_text(filters.get("q"))
        if query:
            where = f"({where}) AND EXISTS(SELECT 1 FROM movie_search_aliases a WHERE a.source_key=s.source_key AND instr(a.normalized_text,?)>0)"
            parameters.append(query)
        category = _text(filters.get("category")).casefold()
        if category in CATEGORIES:
            where = f"({where}) AND COALESCE(sc.category,'unclassified')=?"
            parameters.append(category)
        playlist_id = _text(filters.get("playlist_id"))
        if playlist_id:
            where = f"({where}) AND s.playlist_id=?"
            parameters.append(playlist_id)
        with self.connection() as connection:
            total = connection.execute(
                f"""SELECT COUNT(*) FROM source_matches m JOIN movie_sources s USING(source_key)
                    LEFT JOIN source_classifications sc USING(source_key)
                    WHERE s.available=1 AND ({where})""",
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                f"""SELECT s.source_key,s.source_id,s.provider_title,s.provider_year,s.detail_title,s.detail_year,s.provider_tmdb_id,
                            s.playlist_name,m.state,m.tmdb_id,m.method,m.confidence,m.manual_lock,
                            m.evidence_json,m.error_code,m.error_message,m.parser_version,m.matcher_version,m.stale,
                            COALESCE(sc.category,'unclassified') category,COALESCE(sc.status,'pending') classification_status,
                            COALESCE(sc.confidence,0) classification_confidence,
                            COALESCE(sc.method,'') classification_method,COALESCE(sc.review_reason,'') classification_review_reason,
                            COALESCE(sc.manual_lock,0) classification_manual_lock
                     FROM source_matches m JOIN movie_sources s USING(source_key)
                     LEFT JOIN source_classifications sc USING(source_key)
                     WHERE s.available=1 AND ({where})
                     ORDER BY m.stale DESC,m.updated_at DESC,s.position,s.source_key LIMIT ? OFFSET ?""",
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            try:
                item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            except json.JSONDecodeError:
                item["evidence"] = {}
            items.append(item)
        return {"view": _text(view), "items": items, "page": page, "page_size": page_size, "total": int(total)}

    def classification_rows(self, *, only_pending=False, limit=1000, offset=0):
        clause = "AND sc.manual_lock=0 AND (sc.status='pending' OR sc.classifier_version<>?)" if only_pending else ""
        params = [CLASSIFIER_VERSION] if only_pending else []
        with self.connection() as connection:
            rows = connection.execute(
                f"""SELECT s.*,sc.category,sc.status classification_status,sc.confidence classification_confidence,
                           sc.method classification_method,sc.evidence_json classification_evidence_json,
                           sc.classifier_version,sc.manual_lock classification_manual_lock,sc.review_reason
                    FROM movie_sources s JOIN source_classifications sc USING(source_key)
                    WHERE s.available=1 {clause}
                    ORDER BY s.position,s.source_key LIMIT ? OFFSET ?""",
                [*params, min(5000, max(1, _integer(limit) or 1000)), max(0, _integer(offset))],
            ).fetchall()
        return [dict(row) for row in rows]

    def save_playlist_classification(self, playlist_id, playlist_name, decision):
        decision = decision if isinstance(decision, dict) else {}
        category = _text(decision.get("category")).casefold()
        if category not in CATEGORIES:
            category = "unclassified"
        with self._lock, self.connection(immediate=True) as connection:
            connection.execute(
                """INSERT INTO playlist_classifications(playlist_id,playlist_name,category,status,
                       confidence,method,evidence_json,classifier_version,mixed,manual_lock,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(playlist_id) DO UPDATE SET playlist_name=excluded.playlist_name,
                     category=CASE WHEN playlist_classifications.manual_lock=1 THEN playlist_classifications.category ELSE excluded.category END,
                     status=CASE WHEN playlist_classifications.manual_lock=1 THEN playlist_classifications.status ELSE excluded.status END,
                     confidence=CASE WHEN playlist_classifications.manual_lock=1 THEN playlist_classifications.confidence ELSE excluded.confidence END,
                     method=CASE WHEN playlist_classifications.manual_lock=1 THEN playlist_classifications.method ELSE excluded.method END,
                     evidence_json=CASE WHEN playlist_classifications.manual_lock=1 THEN playlist_classifications.evidence_json ELSE excluded.evidence_json END,
                     classifier_version=CASE WHEN playlist_classifications.manual_lock=1 THEN playlist_classifications.classifier_version ELSE excluded.classifier_version END,
                     mixed=CASE WHEN playlist_classifications.manual_lock=1 THEN playlist_classifications.mixed ELSE excluded.mixed END,
                     updated_at=excluded.updated_at""",
                (
                    _text(playlist_id), _text(playlist_name), category,
                    _text(decision.get("status")) or "review", float(decision.get("confidence") or 0),
                    _text(decision.get("method")), json.dumps(decision.get("evidence") or {}, ensure_ascii=False),
                    _integer(decision.get("classifier_version")) or CLASSIFIER_VERSION,
                    int(bool(decision.get("mixed"))), int(bool(decision.get("manual_lock"))), time.time(),
                ),
            )

    def playlist_classification(self, playlist_id):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM playlist_classifications WHERE playlist_id=?", (_text(playlist_id),)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        try:
            result["evidence"] = json.loads(result.pop("evidence_json") or "{}")
        except json.JSONDecodeError:
            result["evidence"] = {}
        return result

    def apply_classification(self, source_keys, category, *, method, confidence=0, evidence=None, manual=False, review_reason=""):
        category = _text(category).casefold()
        if category not in CATEGORIES:
            raise ValueError("Unsupported IPTV movie classification")
        keys = list(dict.fromkeys(_text(key) for key in source_keys if _text(key)))[:5000]
        if not keys:
            return {"applied": [], "locked": [], "missing": []}
        result = {"applied": [], "locked": [], "missing": []}
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            status_before = self._status_contributions(connection, keys)
            for key in keys:
                row = connection.execute(
                    "SELECT * FROM source_classifications WHERE source_key=?", (key,)
                ).fetchone()
                if not row:
                    result["missing"].append(key)
                    continue
                if row["manual_lock"] and not manual:
                    result["locked"].append(key)
                    continue
                previous = dict(row)
                status = "review" if category == "unclassified" else "classified"
                current = {
                    "category": category, "status": status, "confidence": float(confidence or 0),
                    "method": _text(method), "classifier_version": CLASSIFIER_VERSION,
                    "manual_lock": int(bool(manual)), "review_reason": _text(review_reason),
                }
                connection.execute(
                    """UPDATE source_classifications SET category=?,status=?,confidence=?,method=?,
                           evidence_json=?,classifier_version=?,manual_lock=?,review_reason=?,updated_at=?
                       WHERE source_key=?""",
                    (
                        category, status, float(confidence or 0), _text(method),
                        json.dumps(evidence or {}, ensure_ascii=False), CLASSIFIER_VERSION,
                        int(bool(manual)), _text(review_reason)[:300], now, key,
                    ),
                )
                connection.execute(
                    """INSERT INTO decision_audit(source_key,domain,previous_json,current_json,method,created_at)
                       VALUES (?,'classification',?,?,?,?)""",
                    (
                        key, json.dumps(previous, ensure_ascii=False, default=str),
                        json.dumps(current, ensure_ascii=False), _text(method), now,
                    ),
                )
                result["applied"].append(key)
            if result["applied"]:
                self._set_meta(connection, "movie_generation", _integer(self._meta(connection, "movie_generation", 0)) + 1)
            self._apply_status_transitions(connection, status_before, keys)
        return result

    def apply_classification_decisions(self, decisions, *, manual=False):
        rows = [row for row in list(decisions or [])[:1000] if isinstance(row, dict) and _text(row.get("source_key"))]
        result = {"applied": [], "locked": [], "missing": []}
        if not rows:
            return result
        now = time.time()
        decision_keys = [_text(row.get("source_key")) for row in rows]
        with self._lock, self.connection(immediate=True) as connection:
            status_before = self._status_contributions(connection, decision_keys)
            for decision in rows:
                key = _text(decision.get("source_key"))
                current_row = connection.execute(
                    "SELECT * FROM source_classifications WHERE source_key=?", (key,)
                ).fetchone()
                if not current_row:
                    result["missing"].append(key)
                    continue
                if current_row["manual_lock"] and not manual:
                    result["locked"].append(key)
                    continue
                category = _text(decision.get("category")).casefold()
                if category not in CATEGORIES:
                    category = "unclassified"
                status = "review" if category == "unclassified" else "classified"
                current = {
                    "category": category, "status": status,
                    "confidence": float(decision.get("confidence") or 0),
                    "method": _text(decision.get("method")),
                    "classifier_version": _integer(decision.get("classifier_version")) or CLASSIFIER_VERSION,
                    "manual_lock": int(bool(manual or decision.get("manual_lock"))),
                    "review_reason": _text(decision.get("review_reason")),
                }
                connection.execute(
                    """UPDATE source_classifications SET category=?,status=?,confidence=?,method=?,
                           evidence_json=?,classifier_version=?,manual_lock=?,review_reason=?,updated_at=?
                       WHERE source_key=?""",
                    (
                        category, status, current["confidence"], current["method"],
                        json.dumps(decision.get("evidence") or {}, ensure_ascii=False),
                        current["classifier_version"], current["manual_lock"],
                        current["review_reason"][:300], now, key,
                    ),
                )
                connection.execute(
                    """INSERT INTO decision_audit(source_key,domain,previous_json,current_json,method,created_at)
                       VALUES (?,'classification',?,?,?,?)""",
                    (
                        key, json.dumps(dict(current_row), ensure_ascii=False, default=str),
                        json.dumps(current, ensure_ascii=False), current["method"], now,
                    ),
                )
                result["applied"].append(key)
            if result["applied"]:
                self._set_meta(connection, "movie_generation", _integer(self._meta(connection, "movie_generation", 0)) + 1)
            self._apply_status_transitions(connection, status_before, decision_keys)
        return result

    def resolve_selection(self, *, mode="explicit", selected_keys=None, filters=None, page=1, page_size=50, max_selection=5000):
        mode = _text(mode) or "explicit"
        filters = dict(filters or {})
        max_selection = min(5000, max(1, _integer(max_selection) or 5000))
        keys = []
        if mode == "explicit":
            candidates = list(dict.fromkeys(_text(key) for key in (selected_keys or []) if _text(key)))
            if len(candidates) > max_selection:
                raise ValueError("The IPTV Movies selection is too large")
            with self.connection() as connection:
                for value in candidates:
                    if value.startswith("source:"):
                        source_value = value.split(":", 1)[1]
                        if connection.execute("SELECT 1 FROM movie_sources WHERE source_key=? AND available=1", (source_value,)).fetchone():
                            keys.append(source_value)
                    elif value.startswith("s_") and connection.execute(
                        "SELECT 1 FROM movie_sources WHERE source_key=? AND available=1", (value,)
                    ).fetchone():
                        keys.append(value)
                    elif value.startswith("tmdb:"):
                        keys.extend(self._source_keys_for_movie(connection, value))
        else:
            requested_page = max(1, _integer(page) or 1)
            query_page = requested_page if mode == "page" else 1
            while True:
                bounded_page_size = min(100, max(1, _integer(page_size) or 50))
                if filters.get("review_view"):
                    result = self.review_queue(
                        filters.get("review_view"), page=query_page, page_size=bounded_page_size,
                        filters=filters,
                    )
                    keys.extend(item["source_key"] for item in result["items"])
                else:
                    result = self.list_movies(filters, page=query_page, page_size=bounded_page_size)
                    for movie in result["items"]:
                        with self.connection() as connection:
                            keys.extend(self._source_keys_for_movie(connection, movie["movie_key"]))
                keys = list(dict.fromkeys(keys))
                if len(keys) > max_selection:
                    raise ValueError("The filtered IPTV Movies selection exceeds the safe limit")
                if mode == "page" or query_page * result["page_size"] >= result["total"]:
                    break
                query_page += 1
        keys = list(dict.fromkeys(keys))
        if len(keys) > max_selection:
            raise ValueError("The IPTV Movies selection exceeds the safe limit")
        return {"source_keys": keys, "catalog_generation": self.source_generation(), "mode": mode, "filters": filters}

    def create_proposal_job(self, *, method, selection, ttl=86400):
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            connection.execute(
                """INSERT INTO proposal_jobs(job_id,method,state,selection_mode,filters_json,
                       selected_keys_json,catalog_generation,total,processed,expires_at,created_at,updated_at)
                   VALUES (?,?,'running',?,?,?,?,?,0,?,?,?)""",
                (
                    job_id, _text(method), _text(selection.get("mode")),
                    json.dumps(selection.get("filters") or {}, ensure_ascii=False),
                    json.dumps(selection.get("source_keys") or [], ensure_ascii=False),
                    _integer(selection.get("catalog_generation")), len(selection.get("source_keys") or []),
                    now + max(300, _integer(ttl) or 86400), now, now,
                ),
            )
        return job_id

    def save_proposal(self, job_id, source_key_value, *, candidate_tmdb_id=0, recommendation="review", confidence=0, evidence=None, warnings=None, work_key=""):
        proposal_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            job = connection.execute("SELECT state FROM proposal_jobs WHERE job_id=?", (_text(job_id),)).fetchone()
            if not job or job["state"] not in {"running", "ready"}:
                raise KeyError("IPTV movie proposal job was not found")
            connection.execute(
                """INSERT INTO proposals(proposal_id,job_id,source_key,work_key,candidate_tmdb_id,
                       recommendation,confidence,evidence_json,warnings_json,selected,apply_state,
                       created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,0,'pending',?,?)""",
                (
                    proposal_id, _text(job_id), _text(source_key_value), _text(work_key),
                    _integer(candidate_tmdb_id), _text(recommendation), float(confidence or 0),
                    json.dumps(evidence or {}, ensure_ascii=False),
                    json.dumps(warnings or [], ensure_ascii=False), now, now,
                ),
            )
            connection.execute(
                "UPDATE proposal_jobs SET processed=processed+1,updated_at=? WHERE job_id=?",
                (now, _text(job_id)),
            )
        return proposal_id

    def finish_proposal_job(self, job_id, *, state="ready", error=""):
        if state not in {"ready", "cancelled", "failed", "complete"}:
            raise ValueError("Unsupported IPTV movie proposal state")
        with self._lock, self.connection(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE proposal_jobs SET state=?,error=?,updated_at=? WHERE job_id=?",
                (state, _text(error)[:500], time.time(), _text(job_id)),
            )
            if not cursor.rowcount:
                raise KeyError("IPTV movie proposal job was not found")
        return self.proposal_job(job_id)

    def proposal_job(self, job_id):
        with self.connection() as connection:
            job = connection.execute("SELECT * FROM proposal_jobs WHERE job_id=?", (_text(job_id),)).fetchone()
            if not job:
                raise KeyError("IPTV movie proposal job was not found")
            proposals = connection.execute(
                """SELECT p.*,s.provider_title,s.provider_year,s.detail_title,s.detail_year,
                          sc.category,sc.manual_lock classification_manual_lock,m.manual_lock match_manual_lock
                   FROM proposals p JOIN movie_sources s USING(source_key)
                   JOIN source_classifications sc USING(source_key)
                   JOIN source_matches m USING(source_key)
                   WHERE p.job_id=? ORDER BY s.position,p.source_key,p.proposal_id""",
                (_text(job_id),),
            ).fetchall()
        result = dict(job)
        for key in ("filters_json", "selected_keys_json"):
            try:
                result[key.removesuffix("_json")] = json.loads(result.pop(key) or ("[]" if "keys" in key else "{}"))
            except json.JSONDecodeError:
                result[key.removesuffix("_json")] = [] if "keys" in key else {}
        result["proposals"] = []
        for row in proposals:
            item = dict(row)
            for key, fallback in (("evidence_json", {}), ("warnings_json", [])):
                try:
                    item[key.removesuffix("_json")] = json.loads(item.pop(key) or json.dumps(fallback))
                except json.JSONDecodeError:
                    item[key.removesuffix("_json")] = fallback
            result["proposals"].append(item)
        return result

    def latest_job_references(self):
        with self.connection() as connection:
            proposal = connection.execute(
                """SELECT job_id,method,state,total,processed,error,created_at,updated_at
                   FROM proposal_jobs ORDER BY created_at DESC,job_id DESC LIMIT 1"""
            ).fetchone()
            rebuild = connection.execute(
                """SELECT job_id,state,catalog_generation,checkpoint,error,created_at,updated_at
                   FROM rebuild_jobs ORDER BY created_at DESC,job_id DESC LIMIT 1"""
            ).fetchone()
        return {
            "match": dict(proposal) if proposal else None,
            "rebuild": dict(rebuild) if rebuild else None,
        }

    def mark_proposal_apply(self, proposal_id, state, result=""):
        with self._lock, self.connection(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE proposals SET apply_state=?,apply_result=?,updated_at=? WHERE proposal_id=?",
                (_text(state), _text(result)[:500], time.time(), _text(proposal_id)),
            )
            if not cursor.rowcount:
                raise KeyError("IPTV movie proposal was not found")

    def create_rebuild_job(self, items, report, *, scope=None):
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            connection.execute(
                """INSERT INTO rebuild_jobs(job_id,state,scope_json,catalog_generation,classifier_version,
                       parser_version,matcher_version,report_json,created_at,updated_at)
                   VALUES (?,'ready',?,?,?,?,?,?,?,?)""",
                (
                    job_id, json.dumps(scope or {}, ensure_ascii=False), self.source_generation(),
                    CLASSIFIER_VERSION, PARSER_VERSION, MATCHER_VERSION,
                    json.dumps(report or {}, ensure_ascii=False), now, now,
                ),
            )
            for item in items:
                connection.execute(
                    """INSERT INTO rebuild_items(job_id,source_key,previous_classification,
                           proposed_classification,previous_match_state,proposed_match_state,
                           transition,evidence_json) VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        job_id, _text(item.get("source_key")), _text(item.get("previous_classification")),
                        _text(item.get("proposed_classification")), _text(item.get("previous_match_state")),
                        _text(item.get("proposed_match_state")), _text(item.get("transition")),
                        json.dumps(item.get("evidence") or {}, ensure_ascii=False),
                    ),
                )
        return self.rebuild_job(job_id)

    @staticmethod
    def _public_rebuild_report(report, *, include_exact_keys=False):
        report = dict(report or {})
        exact = report.get("transition_keys") if isinstance(report.get("transition_keys"), dict) else {}
        if exact and not include_exact_keys:
            report["transition_key_samples"] = {
                key: list(values or [])[:20] for key, values in exact.items()
            }
            report["exact_transition_keys_stored"] = True
            report.pop("transition_keys", None)
        return report

    def rebuild_job(self, job_id, *, include_items=False, include_exact_keys=False):
        with self.connection() as connection:
            job = connection.execute("SELECT * FROM rebuild_jobs WHERE job_id=?", (_text(job_id),)).fetchone()
            if not job:
                raise KeyError("IPTV Movies rebuild job was not found")
            items = []
            if include_items:
                items = [dict(row) for row in connection.execute(
                    "SELECT * FROM rebuild_items WHERE job_id=? ORDER BY source_key LIMIT 500",
                    (_text(job_id),),
                )]
        result = dict(job)
        for key in ("scope_json", "report_json"):
            try:
                result[key.removesuffix("_json")] = json.loads(result.pop(key) or "{}")
            except json.JSONDecodeError:
                result[key.removesuffix("_json")] = {}
        result["report"] = self._public_rebuild_report(
            result.get("report"), include_exact_keys=include_exact_keys
        )
        for item in items:
            try:
                item["evidence"] = json.loads(item.pop("evidence_json") or "{}")
            except json.JSONDecodeError:
                item["evidence"] = {}
        if include_items:
            result["items"] = items
        return result

    def rebuild_pending_items(self, job_id, *, limit=500):
        limit = min(500, max(1, _integer(limit) or 500))
        with self.connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM rebuild_jobs WHERE job_id=?", (_text(job_id),)
            ).fetchone()
            if not exists:
                raise KeyError("IPTV Movies rebuild job was not found")
            rows = connection.execute(
                """SELECT source_key FROM rebuild_items
                   WHERE job_id=? AND apply_state='pending'
                   ORDER BY source_key LIMIT ?""",
                (_text(job_id), limit),
            ).fetchall()
        return [row[0] for row in rows]

    def set_rebuild_state(self, job_id, state, *, checkpoint=None, error=""):
        if state not in {"ready", "applying", "complete", "cancelled", "failed", "rolled-back"}:
            raise ValueError("Unsupported IPTV Movies rebuild state")
        with self._lock, self.connection(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE rebuild_jobs SET state=?,checkpoint=COALESCE(?,checkpoint),error=?,updated_at=?
                   WHERE job_id=?""",
                (state, checkpoint, _text(error)[:500], time.time(), _text(job_id)),
            )
            if not cursor.rowcount:
                raise KeyError("IPTV Movies rebuild job was not found")
        return self.rebuild_job(job_id)

    def apply_rebuild_item(self, job_id, source_key_value):
        job_id = _text(job_id)
        source_key_value = _text(source_key_value)
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            job = connection.execute("SELECT * FROM rebuild_jobs WHERE job_id=?", (job_id,)).fetchone()
            item = connection.execute(
                "SELECT * FROM rebuild_items WHERE job_id=? AND source_key=?", (job_id, source_key_value)
            ).fetchone()
            if not job or not item:
                raise KeyError("IPTV Movies rebuild item was not found")
            classification = connection.execute(
                "SELECT * FROM source_classifications WHERE source_key=?", (source_key_value,)
            ).fetchone()
            match = connection.execute(
                "SELECT * FROM source_matches WHERE source_key=?", (source_key_value,)
            ).fetchone()
            if not classification or not match:
                raise KeyError("IPTV movie source was not found")
            if classification["manual_lock"] or match["manual_lock"]:
                connection.execute(
                    "UPDATE rebuild_items SET apply_state='locked' WHERE job_id=? AND source_key=?",
                    (job_id, source_key_value),
                )
                return "locked"
            status_before = self._status_contributions(connection, [source_key_value])
            category = _text(item["proposed_classification"]).casefold()
            if category not in CATEGORIES:
                category = "unclassified"
            connection.execute(
                """UPDATE source_classifications SET category=?,status=?,confidence=1,
                       method='rebuild',classifier_version=?,review_reason=?,updated_at=?
                   WHERE source_key=?""",
                (
                    category, "review" if category == "unclassified" else "classified",
                    CLASSIFIER_VERSION, "rebuild-review" if category == "unclassified" else "", now,
                    source_key_value,
                ),
            )
            if category == "film":
                connection.execute(
                    """UPDATE source_matches SET state='unprocessed',tmdb_id=NULL,method='rebuild-requeue',
                           confidence=0,evidence_json='{}',error_code='',error_message='',parser_version=?,
                           matcher_version=?,classifier_version=?,terminal_at=0,stale=0,updated_at=?
                       WHERE source_key=? AND manual_lock=0""",
                    (PARSER_VERSION, MATCHER_VERSION, CLASSIFIER_VERSION, now, source_key_value),
                )
                source = connection.execute(
                    "SELECT provider_tmdb_id,work_title,work_year FROM movie_sources WHERE source_key=?",
                    (source_key_value,),
                ).fetchone()
                work_key = (
                    f"query:{_text(source['work_title'])}:{_integer(source['work_year'])}" if _text(source["work_title"])
                    else f"tmdb:{_integer(source['provider_tmdb_id'])}" if _integer(source["provider_tmdb_id"])
                    else f"source:{source_key_value}"
                )
                connection.execute(
                    """INSERT INTO enrichment_queue(source_key,status,attempts,next_attempt_at,last_error,
                           updated_at,priority,work_key,claimed_at,completed_at)
                       VALUES (?,'pending',0,0,'',?,50,?,0,0)
                       ON CONFLICT(source_key) DO UPDATE SET status='pending',attempts=0,next_attempt_at=0,
                         last_error='',priority=MAX(priority,50),work_key=excluded.work_key,
                         claimed_at=0,completed_at=0,updated_at=excluded.updated_at""",
                    (source_key_value, now, work_key),
                )
            else:
                connection.execute(
                    """UPDATE source_matches SET state='unprocessed',tmdb_id=NULL,method='classified-non-film',
                           confidence=0,evidence_json='{}',error_code='',error_message='',parser_version=?,
                           matcher_version=?,classifier_version=?,terminal_at=0,stale=0,updated_at=?
                       WHERE source_key=? AND manual_lock=0""",
                    (PARSER_VERSION, MATCHER_VERSION, CLASSIFIER_VERSION, now, source_key_value),
                )
                connection.execute(
                    "UPDATE enrichment_queue SET status='done',last_error='',completed_at=?,updated_at=? WHERE source_key=?",
                    (now, now, source_key_value),
                )
            connection.execute(
                "UPDATE rebuild_items SET apply_state='applied' WHERE job_id=? AND source_key=?",
                (job_id, source_key_value),
            )
            connection.execute(
                "UPDATE rebuild_jobs SET checkpoint=checkpoint+1,updated_at=? WHERE job_id=?",
                (now, job_id),
            )
            self._apply_status_transitions(connection, status_before, [source_key_value])
            return "applied"

    def integrity(self):
        with self.connection() as connection:
            return connection.execute("PRAGMA integrity_check").fetchone()[0]
