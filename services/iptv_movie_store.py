import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


MOVIE_SCHEMA_VERSION = 2
PARSER_VERSION = 2
MATCHER_VERSION = 2
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
PROVIDER_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MOVIE_KEY_RE = re.compile(r"^(tmdb:[1-9][0-9]*|source:s_[0-9a-f]{24})$")
ARABIC_TEXT_RE = re.compile(r"[\u0600-\u06ff]")


def _text(value):
    return str(value or "").strip()


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
        if existing_version == 1:
            self._migration_backup = self._create_migration_backup()
        try:
            self._initialize()
        except Exception:
            if self._migration_backup:
                shutil.copy2(self._migration_backup, self.database_path)
            raise

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

    def _create_migration_backup(self):
        backup_root = self.root / "migration-backups"
        backup_root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        backup = backup_root / f"movies-schema-v1-{stamp}-{uuid.uuid4().hex[:8]}.sqlite"
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

    def _connect(self):
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    @contextmanager
    def connection(self, immediate=False):
        connection = self._connect()
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
            if current_version not in {0, 1, MOVIE_SCHEMA_VERSION}:
                raise RuntimeError("The IPTV movie database has an unsupported schema")
            if current_version != MOVIE_SCHEMA_VERSION:
                self._migrate_schema_v2(connection)
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
            quality, dubbed, subtitled = _source_claims(title, playlist_name)
            watch = history.get(source_id_value) or {}
            projected.append((
                source_key(source_id_value), source_id_value,
                _text(row.get("category_id") or row.get("playlist_id")), playlist_name,
                title, title.casefold(), _provider_year(row.get("year"), title), _number(row.get("rating")),
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
            connection.executemany(
                """INSERT INTO movie_sources(
                    source_key,source_id,playlist_id,playlist_name,provider_title,sort_title,
                    provider_year,provider_rating,provider_poster_url,provider_backdrop_url,
                    provider_plot,provider_cast,provider_director,provider_genre,provider_duration,
                    container_extension,provider_tmdb_id,added,position,quality_claim,dubbed_claim,
                    subtitled_claim,available,source_generation,watched_position,watched_duration,
                    watched_completed,last_watched,raw_json,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?,?,?)
                ON CONFLICT(source_key) DO UPDATE SET
                    source_id=excluded.source_id,playlist_id=excluded.playlist_id,playlist_name=excluded.playlist_name,
                    provider_title=excluded.provider_title,sort_title=excluded.sort_title,
                    provider_year=excluded.provider_year,provider_rating=excluded.provider_rating,
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
        with self._lock, self.connection(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE movie_sources SET
                    provider_title=COALESCE(NULLIF(?,''),provider_title),
                    sort_title=COALESCE(NULLIF(?,''),sort_title),
                    provider_year=CASE WHEN ?>0 THEN ? ELSE provider_year END,
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
                    updated_at=? WHERE source_key=?""",
                (
                    _text(detail.get("name")), _text(detail.get("name")).casefold(),
                    _provider_year(detail.get("year"), detail.get("name")),
                    _provider_year(detail.get("year"), detail.get("name")),
                    _number(detail.get("rating")), _number(detail.get("rating")),
                    _text(detail.get("image_url")), _text(detail.get("backdrop_url")),
                    _text(detail.get("plot")), _text(detail.get("cast_names")),
                    _text(detail.get("director")), _text(detail.get("genre")),
                    _text(detail.get("duration")), _text(detail.get("container_extension")),
                    _integer(detail.get("tmdb_id")), _integer(detail.get("tmdb_id")),
                    time.time(), _text(source_key_value),
                ),
            )
            if not cursor.rowcount:
                raise KeyError("IPTV movie source was not found")

    def source(self, source_key_value):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM movie_sources WHERE source_key=?", (_text(source_key_value),)
            ).fetchone()
        return dict(row) if row else None

    def set_match_state(self, source_keys, state, *, tmdb_id=None, method="", confidence=0, manual_lock=False, evidence=None, error_code="", error_message="", parser_version=PARSER_VERSION, matcher_version=MATCHER_VERSION):
        if state not in MATCH_STATES:
            raise ValueError("Unsupported IPTV movie match state")
        keys = list(dict.fromkeys(_text(key) for key in source_keys if _text(key)))
        if not keys:
            raise KeyError("IPTV movie source was not found")
        with self._lock, self.connection(immediate=True) as connection:
            for key in keys:
                if not connection.execute("SELECT 1 FROM movie_sources WHERE source_key=?", (key,)).fetchone():
                    raise KeyError("IPTV movie source was not found")
                connection.execute(
                    """UPDATE source_matches SET state=?,tmdb_id=?,method=?,confidence=?,manual_lock=?,
                       evidence_json=?,error_code=?,error_message=?,parser_version=?,matcher_version=?,
                       terminal_at=?,stale=0,updated_at=? WHERE source_key=?""",
                    (
                        state, int(tmdb_id) if tmdb_id else None, _text(method), float(confidence or 0),
                        int(bool(manual_lock)), json.dumps(evidence or {}, ensure_ascii=False),
                        _text(error_code), _text(error_message)[:500], int(parser_version), int(matcher_version),
                        time.time() if state in ACCEPTED_STATES | {"ambiguous", "unmatched", "error-terminal"} else 0,
                        time.time(), key,
                    ),
                )

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

    def apply_match(self, movie_key, movie, *, manual=False, method="manual", confidence=100, evidence=None):
        movie_key = validate_movie_key(movie_key)
        tmdb_id = _integer(movie.get("tmdb_id"))
        if tmdb_id <= 0:
            raise ValueError("A valid TMDB movie snapshot is required")
        with self._lock, self.connection(immediate=True) as connection:
            keys = self._source_keys_for_movie(connection, movie_key)
            if not keys:
                raise KeyError("IPTV movie was not found")
            old_keys = [self._current_movie_key(connection, key) for key in keys]
            self._save_tmdb_movie(connection, movie)
            state = "matched-manual" if manual else "matched-auto"
            for key in keys:
                row = connection.execute("SELECT manual_lock FROM source_matches WHERE source_key=?", (key,)).fetchone()
                if row and row[0] and not manual:
                    continue
                connection.execute(
                    """UPDATE source_matches SET state=?,tmdb_id=?,method=?,confidence=?,manual_lock=?,
                       evidence_json=?,error_code='',error_message='',parser_version=?,matcher_version=?,
                       terminal_at=?,stale=0,updated_at=? WHERE source_key=?""",
                    (state, tmdb_id, _text(method), float(confidence or 0), int(bool(manual)),
                     json.dumps(evidence or {}, ensure_ascii=False), PARSER_VERSION, MATCHER_VERSION,
                     time.time(), time.time(), key),
                )
            new_key = f"tmdb:{tmdb_id}"
            self._merge_memberships(connection, old_keys, new_key)
            self._set_meta(connection, "movie_generation", _integer(self._meta(connection, "movie_generation", 0)) + 1)
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
    def _cards_cte():
        return """
            WITH accepted AS (
                SELECT s.*,m.state,m.tmdb_id,m.manual_lock,m.error_code,m.error_message
                FROM movie_sources s JOIN source_matches m USING(source_key)
                WHERE s.available=1 AND m.state IN ('matched-auto','matched-manual') AND m.tmdb_id IS NOT NULL
            ),
            matched_cards AS (
                SELECT 'tmdb:'||tmdb_id movie_key,tmdb_id,MIN(source_key) representative_source_key,
                       COUNT(*) source_count,MIN(position) source_position,MAX(CAST(NULLIF(added,'') AS REAL)) recent_added,
                       MAX(last_watched) last_watched,MAX(watched_completed) watched_completed,
                       CASE WHEN MAX(manual_lock)>0 THEN 'matched-manual' ELSE 'matched-auto' END metadata_status,
                       '' error_code,'' error_message
                FROM accepted GROUP BY tmdb_id
            ),
            unmatched_cards AS (
                SELECT 'source:'||s.source_key movie_key,NULL tmdb_id,s.source_key representative_source_key,
                       1 source_count,s.position source_position,CAST(NULLIF(s.added,'') AS REAL) recent_added,
                       s.last_watched,s.watched_completed,m.state metadata_status,m.error_code,m.error_message
                FROM movie_sources s JOIN source_matches m USING(source_key)
                WHERE s.available=1 AND NOT (m.state IN ('matched-auto','matched-manual') AND m.tmdb_id IS NOT NULL)
            ),
            cards AS (SELECT * FROM matched_cards UNION ALL SELECT * FROM unmatched_cards)
        """

    @staticmethod
    def _member_clause(extra="1=1"):
        return f"""EXISTS(
            SELECT 1 FROM movie_sources ms JOIN source_matches mm USING(source_key)
            WHERE ms.available=1 AND
              ((c.tmdb_id IS NOT NULL AND mm.tmdb_id=c.tmdb_id AND mm.state IN ('matched-auto','matched-manual'))
               OR (c.tmdb_id IS NULL AND ms.source_key=c.representative_source_key))
              AND ({extra})
        )"""

    def list_movies(self, filters=None, *, page=1, page_size=30, favorite_list_id=""):
        filters = filters or {}
        page = max(1, _integer(page) or 1)
        page_size = min(100, max(1, _integer(page_size) or 30))
        clauses = []
        params = []
        query = _text(filters.get("q"))
        if query:
            needle = f"%{query.casefold()}%"
            clauses.append(f"(LOWER(COALESCE(t.title,'')) LIKE ? OR {self._member_clause('ms.sort_title LIKE ?')})")
            params.extend([needle, needle])
        playlist_id = _text(filters.get("playlist_id"))
        if playlist_id:
            clauses.append(self._member_clause("ms.playlist_id=?"))
            params.append(playlist_id)
        list_id = _text(filters.get("list_id"))
        if list_id:
            clauses.append("EXISTS(SELECT 1 FROM movie_list_memberships ml WHERE ml.movie_key=c.movie_key AND ml.list_id=?)")
            params.append(list_id)
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
            clauses.append(self._member_clause("ms.quality_claim=?"))
            params.append(quality)
        if str(filters.get("dubbed") or "").lower() in {"1", "true", "yes"}:
            clauses.append(self._member_clause("ms.dubbed_claim=1"))
        if str(filters.get("subtitled") or "").lower() in {"1", "true", "yes"}:
            clauses.append(self._member_clause("ms.subtitled_claim=1"))
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
        select = """SELECT c.*,rep.source_id,rep.provider_title,rep.provider_year,rep.provider_rating,
                    rep.provider_poster_url,rep.provider_backdrop_url,rep.provider_plot,rep.provider_cast,
                    rep.provider_director,rep.provider_genre,rep.provider_duration,rep.container_extension,
                    rep.playlist_id,rep.playlist_name,rep.quality_claim,rep.dubbed_claim,rep.subtitled_claim,
                    t.title,t.original_title,t.plot,t.poster_url,t.backdrop_url,t.rating,t.vote_count,
                    t.release_date,t.year,t.runtime,t.original_language,t.certification,t.imdb_id,
                    ar.title ar_title,ar.original_title ar_original_title,ar.plot ar_plot,
                    ar.poster_url ar_poster_url,ar.backdrop_url ar_backdrop_url,
                    EXISTS(SELECT 1 FROM movie_list_memberships fav WHERE fav.movie_key=c.movie_key AND fav.list_id=?) favorite
             FROM cards c JOIN movie_sources rep ON rep.source_key=c.representative_source_key
             LEFT JOIN tmdb_movies t ON t.tmdb_id=c.tmdb_id
             LEFT JOIN tmdb_movie_localizations ar ON ar.tmdb_id=c.tmdb_id AND ar.locale='ar-SA'"""
        with self.connection() as connection:
            total = connection.execute(
                self._cards_cte() + f" SELECT COUNT(*) FROM cards c JOIN movie_sources rep ON rep.source_key=c.representative_source_key LEFT JOIN tmdb_movies t ON t.tmdb_id=c.tmdb_id WHERE {where}",
                params,
            ).fetchone()[0]
            rows = connection.execute(
                self._cards_cte() + f" {select} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
                [favorite_list_id, *params, page_size, (page - 1) * page_size],
            ).fetchall()
            items = [self._public_card(connection, row) for row in rows]
            generation = _integer(self._meta(connection, "movie_generation", 0))
        return {"items": items, "page": page, "page_size": page_size, "total": int(total), "generation": generation}

    def _public_card(self, connection, row):
        data = dict(row)
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
        with self.connection() as connection:
            row = connection.execute(
                self._cards_cte() + """
                SELECT c.*,rep.source_id,rep.provider_title,rep.provider_year,rep.provider_rating,
                       rep.provider_poster_url,rep.provider_backdrop_url,rep.provider_plot,rep.provider_cast,
                       rep.provider_director,rep.provider_genre,rep.provider_duration,rep.container_extension,
                       rep.playlist_id,rep.playlist_name,rep.quality_claim,rep.dubbed_claim,rep.subtitled_claim,
                       t.title,t.original_title,t.plot,t.poster_url,t.backdrop_url,t.rating,t.vote_count,
                       t.release_date,t.year,t.runtime,t.original_language,t.certification,t.imdb_id,
                       ar.title ar_title,ar.original_title ar_original_title,ar.plot ar_plot,
                       ar.poster_url ar_poster_url,ar.backdrop_url ar_backdrop_url,
                       EXISTS(SELECT 1 FROM movie_list_memberships fav WHERE fav.movie_key=c.movie_key AND fav.list_id=?) favorite
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
        return {"playlists": playlists, "genres": genres, "languages": languages, "countries": countries, "qualities": qualities}

    def prepare_enrichment(self, *, consent=False, diagnostic_limit=0):
        now = time.time()
        token = uuid.uuid4().hex
        with self._lock, self.connection(immediate=True) as connection:
            lease = connection.execute("SELECT * FROM worker_lease WHERE lease_id=1").fetchone()
            if not bool(lease["consent"]) and not consent:
                raise ValueError("Confirm Improve this provider's Movies before starting metadata enrichment")
            connection.execute("UPDATE enrichment_queue SET status='pending',claimed_at=0,updated_at=? WHERE status='running'", (now,))
            connection.execute(
                """INSERT INTO enrichment_queue(source_key,status,attempts,next_attempt_at,last_error,updated_at,priority,work_key,claimed_at,completed_at)
                   SELECT s.source_key,'pending',0,0,'',?,0,
                          CASE WHEN s.provider_tmdb_id>0 THEN 'tmdb:'||s.provider_tmdb_id
                               ELSE 'query:'||LOWER(s.provider_title)||':'||s.provider_year END,0,0
                   FROM movie_sources s JOIN source_matches m USING(source_key)
                   WHERE s.available=1 AND m.manual_lock=0
                     AND m.state IN ('unprocessed','provider-id-pending','search-pending','error-retryable')
                   ON CONFLICT(source_key) DO UPDATE SET
                     status=CASE WHEN enrichment_queue.status IN ('cancelled','failed') THEN 'pending' ELSE enrichment_queue.status END,
                     next_attempt_at=0,last_error='',work_key=excluded.work_key,claimed_at=0,updated_at=excluded.updated_at""",
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
        return token

    def worker_waiting_for_capacity(self, token):
        with self._lock, self.connection(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE worker_lease SET pid=0,state='waiting-capacity',command='run',
                       heartbeat_at=?,lease_expires_at=0 WHERE lease_id=1 AND token=?""",
                (time.time(), _text(token)),
            )
            if not cursor.rowcount:
                raise RuntimeError("The IPTV metadata worker lease was lost")

    def current_worker_token(self):
        with self.connection() as connection:
            row = connection.execute("SELECT token FROM worker_lease WHERE lease_id=1").fetchone()
        return _text(row[0]) if row else ""

    def resume_worker(self, *, continue_after_restart=False):
        status = self.worker_status()
        if status["restart_confirmation_required"] and not continue_after_restart:
            raise ValueError("Confirm Continue metadata improvement after restart")
        if not status["consent"]:
            raise ValueError("Confirm Improve this provider's Movies before starting metadata enrichment")
        token = uuid.uuid4().hex
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
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
        with self._lock, self.connection(immediate=True) as connection:
            lease = connection.execute("SELECT pid FROM worker_lease WHERE lease_id=1").fetchone()
            self._set_meta(connection, "worker_command", command)
            next_state = "pausing" if command == "pause" else "cancelling" if command == "cancel" else "starting" if command == "run" else "idle"
            if command == "pause" and (not lease or not _integer(lease["pid"])):
                next_state = "paused"
            if command == "cancel" and (not lease or not _integer(lease["pid"])):
                next_state = "cancelled"
                connection.execute(
                    "UPDATE enrichment_queue SET status='cancelled',last_error='',updated_at=? WHERE status IN ('pending','running')",
                    (time.time(),),
                )
                command = "idle"
            connection.execute(
                "UPDATE worker_lease SET command=?,state=?,heartbeat_at=? WHERE lease_id=1",
                (command, next_state, time.time()),
            )
            if command == "pause":
                self._set_meta(connection, "worker_state", "pausing")
            elif command == "cancel":
                self._set_meta(connection, "worker_state", "cancelling")
        return self.worker_status()

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
        with self._lock, self.connection(immediate=True) as connection:
            connection.execute(
                """UPDATE enrichment_queue SET status='cancelled',last_error='',updated_at=?
                   WHERE status IN ('pending','running')""",
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
        return self.worker_status()

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
            connection.execute(
                "UPDATE enrichment_queue SET status='running',attempts=attempts+1,claimed_at=?,updated_at=? WHERE source_key=?",
                (time.time(), time.time(), row[0]),
            )
            if lease:
                connection.execute(
                    "UPDATE worker_lease SET heartbeat_at=?,lease_expires_at=? WHERE lease_id=1",
                    (time.time(), time.time() + 90),
                )
            return row[0]

    def finish_job(self, source_key_value, *, status="done", retry_after=0, error=""):
        if status not in {"pending", "done", "cancelled", "failed"}:
            raise ValueError("Unsupported IPTV enrichment queue status")
        with self._lock, self.connection(immediate=True) as connection:
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

    def retry_failures(self):
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
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
        return int(cursor.rowcount)

    def mark_stale_automatic_results(self):
        with self._lock, self.connection(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE source_matches SET stale=1
                   WHERE manual_lock=0 AND state IN ('ambiguous','unmatched')
                     AND (parser_version<>? OR matcher_version<>?)""",
                (PARSER_VERSION, MATCHER_VERSION),
            )
        return int(cursor.rowcount)

    def re_evaluate_stale(self):
        now = time.time()
        with self._lock, self.connection(immediate=True) as connection:
            rows = [row[0] for row in connection.execute(
                "SELECT source_key FROM source_matches WHERE stale=1 AND manual_lock=0 ORDER BY source_key"
            )]
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

    def worker_status(self):
        with self.connection() as connection:
            meta = {row["key"]: row["value"] for row in connection.execute("SELECT key,value FROM movie_meta")}
            lease = connection.execute("SELECT * FROM worker_lease WHERE lease_id=1").fetchone()
            queue = {row["status"]: int(row["count"]) for row in connection.execute("SELECT status,COUNT(*) count FROM enrichment_queue GROUP BY status")}
            matches = {row["state"]: int(row["count"]) for row in connection.execute("SELECT state,COUNT(*) count FROM source_matches GROUP BY state")}
            sources = connection.execute("SELECT COUNT(*) FROM movie_sources WHERE available=1").fetchone()[0]
            evaluated = connection.execute(
                """SELECT COUNT(*) FROM source_matches m JOIN movie_sources s USING(source_key)
                   WHERE s.available=1 AND m.stale=0 AND m.matcher_version=?
                     AND m.state IN ('matched-auto','matched-manual','ambiguous','unmatched','error-terminal')""",
                (MATCHER_VERSION,),
            ).fetchone()[0]
            grouped = connection.execute(self._cards_cte() + " SELECT COUNT(*) FROM cards").fetchone()[0]
            distinct_tmdb = connection.execute(
                "SELECT COUNT(DISTINCT tmdb_id) FROM source_matches WHERE state IN ('matched-auto','matched-manual') AND tmdb_id IS NOT NULL"
            ).fetchone()[0]
            stale = connection.execute("SELECT COUNT(*) FROM source_matches WHERE stale=1 AND manual_lock=0").fetchone()[0]
        lease_data = dict(lease) if lease else {}
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
            "consent": bool(lease_data.get("consent")),
            "restart_confirmation_required": restart_offer or bool(lease_data.get("restart_confirmation_required")),
            "checkpoint": _integer(lease_data.get("checkpoint")),
            "heartbeat_at": _number(lease_data.get("heartbeat_at")),
            "backoff_until": _number(lease_data.get("backoff_until")),
            "retry_reason": _text(lease_data.get("retry_reason")),
            "diagnostic_limit": _integer(lease_data.get("diagnostic_limit")),
        }

    def review_queue(self, view="needs-review", *, page=1, page_size=50):
        page = max(1, _integer(page) or 1)
        page_size = min(100, max(1, _integer(page_size) or 50))
        clauses = {
            "needs-review": "m.state='ambiguous' OR m.stale=1",
            "unmatched": "m.state='unmatched'",
            "failed": "m.state IN ('error-retryable','error-terminal')",
            "manual": "m.state='matched-manual' OR (m.manual_lock=1 AND m.method='manual-unmatched')",
        }
        where = clauses.get(_text(view), clauses["needs-review"])
        with self.connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM source_matches m JOIN movie_sources s USING(source_key) WHERE s.available=1 AND ({where})"
            ).fetchone()[0]
            rows = connection.execute(
                f"""SELECT s.source_key,s.source_id,s.provider_title,s.provider_year,s.provider_tmdb_id,
                           s.playlist_name,m.state,m.tmdb_id,m.method,m.confidence,m.manual_lock,
                           m.evidence_json,m.error_code,m.error_message,m.parser_version,m.matcher_version,m.stale
                    FROM source_matches m JOIN movie_sources s USING(source_key)
                    WHERE s.available=1 AND ({where})
                    ORDER BY m.stale DESC,m.updated_at DESC,s.position,s.source_key LIMIT ? OFFSET ?""",
                (page_size, (page - 1) * page_size),
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

    def integrity(self):
        with self.connection() as connection:
            return connection.execute("PRAGMA integrity_check").fetchone()[0]
