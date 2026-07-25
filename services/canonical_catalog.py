import hashlib
import json
import re
import sqlite3
import unicodedata

from services.movie_identity import normalize_movie_title, ownership_keys


CANONICAL_CONTRACT_VERSION = 4
WRITER_JOBS = frozenset({"Writer", "Screenplay", "Story", "Novel"})
CANONICAL_CARD_CONTRACT = "canonical_movie_card"
CANONICAL_DETAILS_CONTRACT = "canonical_movie_details"
CANONICAL_CARD_FIELDS = (
    "accepted", "adult", "status", "identity_status", "enrichment_status",
    "metadata_contract_version", "source", "detail_provider", "selected_provider",
    "selected_provider_snapshot", "fallback_active", "people_status", "movie_key",
    "title", "year", "tmdb_id", "imdb_id", "plex_guid", "identity_revision",
    "poster_url", "genres", "plot", "summary", "rating", "tmdb_rating",
    "plex_rating", "tmdb_vote_count", "language", "country", "country_flag",
    "release_date",
)
CANONICAL_DEFERRED_DETAIL_FIELDS = (
    "backdrop_url", "runtime", "tagline", "trailer_url", "collection",
    "cast", "directors", "director", "writers", "certification", "keywords",
)


_CANONICAL_DEFAULTS = {
    "accepted": False,
    "adult": False,
    "status": "",
    "identity_status": "",
    "enrichment_status": "incomplete",
    "metadata_contract_version": CANONICAL_CONTRACT_VERSION,
    "source": "",
    "detail_provider": "",
    "selected_provider": "",
    "selected_provider_snapshot": False,
    "fallback_active": False,
    "people_status": "missing",
    "movie_key": "",
    "title": "",
    "year": "",
    "tmdb_id": "",
    "imdb_id": "",
    "plex_guid": "",
    "identity_revision": 0,
    "poster_url": "",
    "genres": [],
    "plot": "",
    "summary": "",
    "rating": "",
    "tmdb_rating": "",
    "plex_rating": "",
    "tmdb_vote_count": 0,
    "language": "",
    "country": "",
    "country_flag": "",
    "release_date": "",
    "backdrop_url": "",
    "runtime": None,
    "tagline": "",
    "trailer_url": "",
    "collection": {},
    "cast": [],
    "directors": [],
    "director": {},
    "writers": [],
    "certification": "",
    "keywords": [],
}


def _projection_value(metadata, field):
    if field in metadata:
        return metadata[field]
    default = _CANONICAL_DEFAULTS[field]
    if isinstance(default, (list, dict)):
        return default.copy()
    return default


def canonical_card_projection(metadata):
    metadata = dict(metadata or {})
    projected = {
        field: _projection_value(metadata, field)
        for field in CANONICAL_CARD_FIELDS
    }
    for field in (
        "metadata_override", "poster_override", "poster_override_source",
        "poster_override_locked", "local_poster_url", "remote_poster_url", "asset_generation",
    ):
        if field in metadata:
            projected[field] = metadata[field]
    projected["projection_contract"] = CANONICAL_CARD_CONTRACT
    projected["deferred_fields"] = list(CANONICAL_DEFERRED_DETAIL_FIELDS)
    return projected


def canonical_details_projection(metadata):
    metadata = dict(metadata or {})
    projected = dict(metadata)
    for field in (*CANONICAL_CARD_FIELDS, *CANONICAL_DEFERRED_DETAIL_FIELDS):
        projected[field] = _projection_value(metadata, field)
    projected["projection_contract"] = CANONICAL_DETAILS_CONTRACT
    projected["deferred_fields"] = []
    return projected


def _text(value):
    return str(value or "").strip()


def _number(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _execute_schema(connection, script):
    statement = ""
    for line in str(script or "").splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete canonical schema statement")


def _identity_key(record):
    record = record or {}
    if _text(record.get("tmdb_id")):
        return f"tmdb:{_text(record.get('tmdb_id'))}"
    if _text(record.get("imdb_id")):
        return f"imdb:{_text(record.get('imdb_id')).lower()}"
    if _text(record.get("plex_guid")):
        return f"plex:{_text(record.get('plex_guid')).lower()}"
    title = normalize_movie_title(
        record.get("identity_title")
        or record.get("accepted_title")
        or record.get("title")
    )
    year = _text(
        record.get("identity_year")
        or record.get("accepted_year")
        or record.get("year")
    )
    return f"title:{title}|{year}" if title and year else ""


def _provider_person_key(provider, snapshot_key, credit_type, position, person):
    person_id = _text((person or {}).get("id"))
    if provider == "tmdb" and person_id:
        return f"tmdb:{person_id}"
    if provider == "plex" and person_id:
        return f"plex:{person_id}"
    seed = f"{snapshot_key}|{credit_type}|{position}|{_text((person or {}).get('name')).lower()}"
    return f"{provider}-credit:{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def normalize_keyword_name(value):
    return " ".join(unicodedata.normalize("NFKC", _text(value)).casefold().split())


def _keyword_key(normalized_name):
    return f"keyword:{hashlib.sha256(normalized_name.encode('utf-8')).hexdigest()}"


def _provider_details_state(provider, record):
    record = record or {}
    title = record.get("title") if provider == "tmdb" else record.get("plex_title")
    if not _text(title):
        return "missing"
    detail_fields = (
        ("plot", "poster_url", "genres", "tmdb_rating", "release_date", "backdrop_url")
        if provider == "tmdb"
        else ("plex_summary", "plex_poster", "plex_genres", "plex_rating")
    )
    if not any(record.get(field) for field in detail_fields):
        return "partial"
    if provider == "tmdb" and not all(
        field in record for field in ("writers", "certification", "keywords")
    ):
        return "partial"
    return "complete"


def _provider_people_state(provider, record):
    record = record or {}
    cast_key = "cast" if provider == "tmdb" else "plex_cast"
    director_key = "directors" if provider == "tmdb" else "plex_directors"
    if cast_key not in record or director_key not in record:
        return "missing"
    people = [
        person
        for person in [*(record.get(cast_key) or []), *(record.get(director_key) or [])]
        if isinstance(person, dict) and _text(person.get("name"))
    ]
    if not people:
        return "empty"
    if provider == "tmdb" and all(_text(person.get("id")) for person in people):
        return "complete"
    if provider == "plex" and all(
        _text(person.get("id")) and _text(person.get("profile_url"))
        for person in people
    ):
        return "complete"
    return "partial"


class CanonicalCatalog:
    """Relational movie-domain projection built from persisted catalog sources."""

    def initialize(self, connection):
        _execute_schema(connection, """
            CREATE TABLE IF NOT EXISTS canonical_movies (
                movie_key TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                tmdb_id TEXT NOT NULL DEFAULT '',
                imdb_id TEXT NOT NULL DEFAULT '',
                plex_guid TEXT NOT NULL DEFAULT '',
                identity_status TEXT NOT NULL DEFAULT '',
                identity_source TEXT NOT NULL DEFAULT '',
                selected_provider TEXT NOT NULL DEFAULT '',
                requested_enrichment_status TEXT NOT NULL DEFAULT '',
                identity_revision INTEGER NOT NULL DEFAULT 0,
                manual_lock INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS canonical_movie_files (
                path_key TEXT PRIMARY KEY,
                movie_key TEXT NOT NULL,
                FOREIGN KEY (path_key) REFERENCES media_files(path_key) ON DELETE CASCADE,
                FOREIGN KEY (movie_key) REFERENCES canonical_movies(movie_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS provider_movie_snapshots (
                snapshot_key TEXT PRIMARY KEY,
                movie_key TEXT NOT NULL,
                provider TEXT NOT NULL CHECK(provider IN ('tmdb', 'plex')),
                provider_id TEXT NOT NULL DEFAULT '',
                path_key TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                imdb_id TEXT NOT NULL DEFAULT '',
                poster_url TEXT NOT NULL DEFAULT '',
                backdrop_url TEXT NOT NULL DEFAULT '',
                plot TEXT NOT NULL DEFAULT '',
                rating TEXT NOT NULL DEFAULT '',
                vote_count INTEGER NOT NULL DEFAULT 0,
                language TEXT NOT NULL DEFAULT '',
                country TEXT NOT NULL DEFAULT '',
                country_flag TEXT NOT NULL DEFAULT '',
                release_date TEXT NOT NULL DEFAULT '',
                runtime INTEGER,
                tagline TEXT NOT NULL DEFAULT '',
                trailer_url TEXT NOT NULL DEFAULT '',
                details_state TEXT NOT NULL DEFAULT 'missing',
                people_state TEXT NOT NULL DEFAULT 'missing',
                updated_at REAL NOT NULL DEFAULT 0,
                source_json TEXT NOT NULL,
                FOREIGN KEY (movie_key) REFERENCES canonical_movies(movie_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS people (
                person_key TEXT PRIMARY KEY,
                tmdb_id TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                provider_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                profile_url TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS genres (
                genre_key TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS movie_genres (
                snapshot_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                genre_key TEXT NOT NULL,
                PRIMARY KEY (snapshot_key, position),
                FOREIGN KEY (snapshot_key) REFERENCES provider_movie_snapshots(snapshot_key) ON DELETE CASCADE,
                FOREIGN KEY (genre_key) REFERENCES genres(genre_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS collections (
                collection_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                provider_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL DEFAULT '',
                poster_url TEXT NOT NULL DEFAULT '',
                backdrop_url TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS movie_collections (
                snapshot_key TEXT PRIMARY KEY,
                collection_key TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                poster_url TEXT NOT NULL DEFAULT '',
                backdrop_url TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (snapshot_key) REFERENCES provider_movie_snapshots(snapshot_key) ON DELETE CASCADE,
                FOREIGN KEY (collection_key) REFERENCES collections(collection_key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS movie_overrides (
                override_id TEXT PRIMARY KEY,
                override_type TEXT NOT NULL CHECK(override_type IN ('metadata', 'poster')),
                title TEXT NOT NULL DEFAULT '',
                year TEXT NOT NULL DEFAULT '',
                poster_url TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                locked INTEGER NOT NULL DEFAULT 1,
                updated_at REAL NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS movie_override_identity_keys (
                override_id TEXT NOT NULL,
                identity_key TEXT NOT NULL,
                PRIMARY KEY (override_id, identity_key),
                FOREIGN KEY (override_id) REFERENCES movie_overrides(override_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS identity_decisions (
                path_key TEXT PRIMARY KEY,
                movie_key TEXT,
                status TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                provider_id TEXT NOT NULL DEFAULT '',
                revision INTEGER NOT NULL DEFAULT 0,
                manual_lock INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL DEFAULT 0,
                raw_json TEXT NOT NULL,
                FOREIGN KEY (path_key) REFERENCES media_files(path_key) ON DELETE CASCADE,
                FOREIGN KEY (movie_key) REFERENCES canonical_movies(movie_key) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_canonical_movies_tmdb ON canonical_movies(tmdb_id);
            CREATE INDEX IF NOT EXISTS idx_canonical_movies_imdb ON canonical_movies(imdb_id);
            CREATE INDEX IF NOT EXISTS idx_canonical_movies_plex ON canonical_movies(plex_guid);
            CREATE INDEX IF NOT EXISTS idx_canonical_movie_files_movie ON canonical_movie_files(movie_key);
            CREATE INDEX IF NOT EXISTS idx_provider_snapshots_movie ON provider_movie_snapshots(movie_key, provider);
            CREATE INDEX IF NOT EXISTS idx_provider_snapshots_path ON provider_movie_snapshots(path_key);
            CREATE INDEX IF NOT EXISTS idx_people_tmdb ON people(tmdb_id);
            CREATE INDEX IF NOT EXISTS idx_people_name ON people(name COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_override_identity ON movie_override_identity_keys(identity_key);
        """)
        self.create_v8_search_schema(connection)

    @staticmethod
    def create_movie_credits_v8(connection, table="movie_credits", *, if_not_exists=True):
        if table not in {"movie_credits", "movie_credits_v8_new"}:
            raise ValueError("Unsupported movie_credits table name")
        existence = "IF NOT EXISTS " if if_not_exists else ""
        connection.execute(f"""
            CREATE TABLE {existence}{table} (
                snapshot_key TEXT NOT NULL,
                credit_type TEXT NOT NULL CHECK(credit_type IN ('cast', 'director', 'writer')),
                position INTEGER NOT NULL,
                person_key TEXT NOT NULL,
                credited_name TEXT NOT NULL DEFAULT '',
                character TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL DEFAULT '',
                job TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (snapshot_key, credit_type, position),
                FOREIGN KEY (snapshot_key) REFERENCES provider_movie_snapshots(snapshot_key) ON DELETE CASCADE,
                FOREIGN KEY (person_key) REFERENCES people(person_key) ON DELETE CASCADE
            )
        """)

    @staticmethod
    def create_keyword_schema(connection, *, if_not_exists=True):
        existence = "IF NOT EXISTS " if if_not_exists else ""
        connection.execute(f"""
            CREATE TABLE {existence}keywords (
                keyword_key TEXT PRIMARY KEY,
                tmdb_id TEXT NOT NULL DEFAULT '',
                name TEXT NOT NULL,
                normalized_name TEXT NOT NULL UNIQUE
            )
        """)
        connection.execute(f"""
            CREATE TABLE {existence}movie_keywords (
                snapshot_key TEXT NOT NULL,
                position INTEGER NOT NULL,
                keyword_key TEXT NOT NULL,
                PRIMARY KEY (snapshot_key, position),
                UNIQUE (snapshot_key, keyword_key),
                FOREIGN KEY (snapshot_key) REFERENCES provider_movie_snapshots(snapshot_key) ON DELETE CASCADE,
                FOREIGN KEY (keyword_key) REFERENCES keywords(keyword_key) ON DELETE CASCADE
            )
        """)

    @staticmethod
    def create_search_indexes(connection, *, if_not_exists=True):
        existence = "IF NOT EXISTS " if if_not_exists else ""
        connection.execute(
            f"CREATE INDEX {existence}idx_movie_credits_person ON movie_credits(person_key)"
        )
        connection.execute(f"""
            CREATE UNIQUE INDEX {existence}idx_keywords_tmdb
            ON keywords(tmdb_id) WHERE tmdb_id <> ''
        """)
        connection.execute(
            f"CREATE INDEX {existence}idx_keywords_normalized_name ON keywords(normalized_name)"
        )
        connection.execute(
            f"CREATE INDEX {existence}idx_movie_keywords_keyword "
            "ON movie_keywords(keyword_key, snapshot_key)"
        )

    def create_v8_search_schema(self, connection):
        self.create_movie_credits_v8(connection)
        self.create_keyword_schema(connection)
        self.create_search_indexes(connection)

    @staticmethod
    def upgrade_v6_additive_columns(connection):
        additive_columns = {
            "movie_credits": (
                ("credited_name", "TEXT NOT NULL DEFAULT ''"),
                ("profile_url", "TEXT NOT NULL DEFAULT ''"),
            ),
            "movie_collections": (
                ("name", "TEXT NOT NULL DEFAULT ''"),
                ("poster_url", "TEXT NOT NULL DEFAULT ''"),
                ("backdrop_url", "TEXT NOT NULL DEFAULT ''"),
            ),
        }
        for table, columns in additive_columns.items():
            existing = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for column, definition in columns:
                if column not in existing:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def rebuild(self, connection):
        for table in (
            "identity_decisions",
            "movie_override_identity_keys",
            "movie_overrides",
            "movie_collections",
            "collections",
            "movie_keywords",
            "keywords",
            "movie_genres",
            "genres",
            "movie_credits",
            "people",
            "provider_movie_snapshots",
            "canonical_movie_files",
            "canonical_movies",
        ):
            connection.execute(f"DELETE FROM {table}")

        rows = connection.execute("""
            SELECT mf.*, pf.raw_json AS plex_json, mm.raw_json AS manual_json,
                   tm.raw_json AS tmdb_json
            FROM media_files mf
            LEFT JOIN plex_files pf ON pf.path_key = mf.path_key
            LEFT JOIN manual_matches mm ON mm.path_key = mf.path_key
            LEFT JOIN tmdb_movies tm ON tm.tmdb_id = mf.tmdb_id
            ORDER BY mf.path_key
        """).fetchall()
        for row in rows:
            self._sync_row(connection, row)
        self._sync_overrides(connection)

    def sync_changes(self, connection, document_name, keys=()):
        """Refresh relational projections inside the caller's catalog transaction."""
        document_name = str(document_name or "").replace("\\", "/")
        keys = [str(key) for key in keys]
        if document_name in {
            "app_metadata/files.json",
            "app_metadata/plex_metadata.json",
            "app_metadata/manual_matches.json",
        }:
            for path_key in keys:
                self._sync_path(connection, path_key)
            self._remove_orphans(connection)
            return
        if document_name == "app_metadata/tmdb_metadata.json":
            for tmdb_id in keys:
                snapshot_key = f"tmdb:{tmdb_id}"
                connection.execute(
                    "DELETE FROM provider_movie_snapshots WHERE snapshot_key = ?",
                    (snapshot_key,),
                )
                metadata_row = connection.execute(
                    "SELECT raw_json FROM tmdb_movies WHERE tmdb_id = ?", (tmdb_id,)
                ).fetchone()
                if not metadata_row:
                    continue
                record = json.loads(metadata_row[0])
                movies = connection.execute(
                    "SELECT movie_key FROM canonical_movies WHERE tmdb_id = ?", (tmdb_id,)
                ).fetchall()
                for movie in movies:
                    path_row = connection.execute(
                        "SELECT path_key FROM canonical_movie_files WHERE movie_key = ? ORDER BY path_key LIMIT 1",
                        (movie[0],),
                    ).fetchone()
                    self._sync_provider_snapshot(
                        connection,
                        movie[0],
                        "tmdb",
                        path_row[0] if path_row else "",
                        record,
                    )
            self._remove_orphans(connection)
            return
        if document_name in {
            "app_metadata/metadata_overrides.json",
            "app_metadata/poster_overrides.json",
        }:
            self._sync_overrides(connection)

    def _sync_path(self, connection, path_key):
        old = connection.execute(
            "SELECT movie_key FROM canonical_movie_files WHERE path_key = ?", (path_key,)
        ).fetchone()
        old_movie_key = old[0] if old else ""
        connection.execute("DELETE FROM identity_decisions WHERE path_key = ?", (path_key,))
        connection.execute("DELETE FROM canonical_movie_files WHERE path_key = ?", (path_key,))
        connection.execute(
            "DELETE FROM provider_movie_snapshots WHERE provider = 'plex' AND path_key = ?",
            (path_key,),
        )
        row = connection.execute("""
            SELECT mf.*, pf.raw_json AS plex_json, mm.raw_json AS manual_json,
                   tm.raw_json AS tmdb_json
            FROM media_files mf
            LEFT JOIN plex_files pf ON pf.path_key = mf.path_key
            LEFT JOIN manual_matches mm ON mm.path_key = mf.path_key
            LEFT JOIN tmdb_movies tm ON tm.tmdb_id = mf.tmdb_id
            WHERE mf.path_key = ?
        """, (path_key,)).fetchone()
        if row:
            self._sync_row(connection, row)
        if old_movie_key:
            connection.execute("""
                DELETE FROM canonical_movies
                WHERE movie_key = ?
                  AND NOT EXISTS(
                      SELECT 1 FROM canonical_movie_files cmf
                      WHERE cmf.movie_key = canonical_movies.movie_key
                  )
            """, (old_movie_key,))

    @staticmethod
    def _remove_orphans(connection):
        connection.execute("""
            DELETE FROM canonical_movies
            WHERE NOT EXISTS(
                SELECT 1 FROM canonical_movie_files cmf
                WHERE cmf.movie_key = canonical_movies.movie_key
            )
        """)
        connection.execute("""
            DELETE FROM people
            WHERE NOT EXISTS(
                SELECT 1 FROM movie_credits mc WHERE mc.person_key = people.person_key
            )
        """)
        connection.execute("""
            DELETE FROM genres
            WHERE NOT EXISTS(
                SELECT 1 FROM movie_genres mg WHERE mg.genre_key = genres.genre_key
            )
        """)
        connection.execute("""
            DELETE FROM collections
            WHERE NOT EXISTS(
                SELECT 1 FROM movie_collections mc WHERE mc.collection_key = collections.collection_key
            )
        """)
        connection.execute("""
            DELETE FROM keywords
            WHERE NOT EXISTS(
                SELECT 1 FROM movie_keywords mk WHERE mk.keyword_key = keywords.keyword_key
            )
        """)

    def _sync_row(self, connection, row):
        row = dict(row)
        file_record = json.loads(row.get("raw_json") or "{}")
        plex_record = json.loads(row.get("plex_json") or "{}")
        manual_record = json.loads(row.get("manual_json") or "{}")
        tmdb_record = json.loads(row.get("tmdb_json") or "{}")
        authoritative = {**file_record, **{
            key: row.get(key)
            for key in (
                "path_key", "path", "identity_status", "identity_title", "identity_year",
                "identity_source", "identity_revision", "tmdb_id", "imdb_id", "plex_guid",
                "display_provider", "enrichment_status", "manual_lock", "manual_locked",
                "metadata_status", "metadata_accepted",
            )
        }}
        movie_key = _identity_key(authoritative)
        accepted = bool(row.get("metadata_accepted") or row.get("identity_status") == "accepted")
        if not movie_key or not accepted:
            self._sync_identity_decision(connection, row, "", file_record, manual_record)
            return

        selected_provider = _text(row.get("display_provider"))
        if selected_provider not in {"tmdb", "plex"}:
            selected_provider = "tmdb" if _text(row.get("tmdb_id")) else "plex"
        title = _text(row.get("identity_title") or file_record.get("accepted_title") or file_record.get("title"))
        year = _text(
            row.get("identity_year")
            or file_record.get("accepted_year")
            or file_record.get("year")
            or row.get("parsed_year")
        )
        connection.execute("""
            INSERT INTO canonical_movies(
                movie_key, title, year, tmdb_id, imdb_id, plex_guid, identity_status,
                identity_source, selected_provider, requested_enrichment_status,
                identity_revision, manual_lock, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(movie_key) DO UPDATE SET
                title=CASE WHEN excluded.title<>'' THEN excluded.title ELSE canonical_movies.title END,
                year=CASE WHEN excluded.year<>'' THEN excluded.year ELSE canonical_movies.year END,
                tmdb_id=CASE WHEN excluded.tmdb_id<>'' THEN excluded.tmdb_id ELSE canonical_movies.tmdb_id END,
                imdb_id=CASE WHEN excluded.imdb_id<>'' THEN excluded.imdb_id ELSE canonical_movies.imdb_id END,
                plex_guid=CASE WHEN excluded.plex_guid<>'' THEN excluded.plex_guid ELSE canonical_movies.plex_guid END,
                identity_status=excluded.identity_status,
                identity_source=CASE WHEN excluded.identity_source<>'' THEN excluded.identity_source ELSE canonical_movies.identity_source END,
                selected_provider=excluded.selected_provider,
                requested_enrichment_status=excluded.requested_enrichment_status,
                identity_revision=MAX(canonical_movies.identity_revision, excluded.identity_revision),
                manual_lock=MAX(canonical_movies.manual_lock, excluded.manual_lock),
                updated_at=MAX(canonical_movies.updated_at, excluded.updated_at)
        """, (
            movie_key, title, year, _text(row.get("tmdb_id")), _text(row.get("imdb_id")),
            _text(row.get("plex_guid")), "accepted", _text(row.get("identity_source")),
            selected_provider, _text(row.get("enrichment_status")),
            int(row.get("identity_revision") or 0),
            1 if row.get("manual_lock") or row.get("manual_locked") else 0,
            _number(file_record.get("updated_at")),
        ))
        connection.execute(
            "INSERT OR REPLACE INTO canonical_movie_files(path_key, movie_key) VALUES(?, ?)",
            (row["path_key"], movie_key),
        )
        if tmdb_record:
            self._sync_provider_snapshot(connection, movie_key, "tmdb", row["path_key"], tmdb_record)
        if plex_record:
            self._sync_provider_snapshot(connection, movie_key, "plex", row["path_key"], plex_record)
        self._sync_identity_decision(connection, row, movie_key, file_record, manual_record)

    def _sync_provider_snapshot(self, connection, movie_key, provider, path_key, record):
        if provider == "tmdb":
            provider_id = _text(record.get("tmdb_id") or record.get("id"))
            if not provider_id:
                return
            snapshot_key = f"tmdb:{provider_id}"
            title = _text(record.get("title") or record.get("name"))
            year = _text(record.get("year") or _text(record.get("release_date"))[:4])
            values = {
                "imdb_id": record.get("imdb_id"), "poster_url": record.get("poster_url"),
                "backdrop_url": record.get("backdrop_url"), "plot": record.get("plot") or record.get("overview"),
                "rating": record.get("tmdb_rating") or record.get("vote_average"),
                "vote_count": record.get("tmdb_vote_count") or record.get("vote_count"),
                "language": record.get("language") or record.get("original_language"),
                "country": record.get("country"), "country_flag": record.get("country_flag"),
                "release_date": record.get("release_date"), "runtime": record.get("runtime"),
                "tagline": record.get("tagline"), "trailer_url": record.get("trailer_url"),
            }
            cast = record.get("cast") or []
            directors = record.get("directors") or []
            writers = record.get("writers") or []
            keywords = record.get("keywords") or []
            genres = record.get("genres") or []
            collection = record.get("collection") or {}
            snapshot_path = ""
        else:
            provider_id = _text(record.get("rating_key") or record.get("plex_guid") or path_key)
            snapshot_key = f"plex-file:{path_key}"
            title = _text(record.get("plex_title"))
            year = _text(record.get("plex_year"))
            values = {
                "imdb_id": record.get("imdb_id"), "poster_url": record.get("plex_poster"),
                "backdrop_url": "", "plot": record.get("plex_summary"),
                "rating": record.get("plex_rating"), "vote_count": 0,
                "language": record.get("plex_language"), "country": record.get("plex_country"),
                "country_flag": record.get("plex_country_flag"), "release_date": "", "runtime": None,
                "tagline": "", "trailer_url": "",
            }
            cast = record.get("plex_cast") or []
            directors = record.get("plex_directors") or []
            writers = []
            keywords = []
            genres = record.get("plex_genres") or []
            collection = {}
            snapshot_path = path_key

        connection.execute("""
            INSERT OR REPLACE INTO provider_movie_snapshots(
                snapshot_key, movie_key, provider, provider_id, path_key, title, year,
                imdb_id, poster_url, backdrop_url, plot, rating, vote_count, language,
                country, country_flag, release_date, runtime, tagline, trailer_url,
                details_state, people_state, updated_at, source_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            snapshot_key, movie_key, provider, provider_id, snapshot_path, title, year,
            _text(values["imdb_id"]), _text(values["poster_url"]), _text(values["backdrop_url"]),
            _text(values["plot"]), _text(values["rating"]), int(_number(values["vote_count"])),
            _text(values["language"]), _text(values["country"]), _text(values["country_flag"]),
            _text(values["release_date"]), int(_number(values["runtime"])) if values["runtime"] not in (None, "") else None,
            _text(values["tagline"]), _text(values["trailer_url"]),
            _provider_details_state(provider, record), _provider_people_state(provider, record),
            _number(record.get("updated_at")), _json(record),
        ))
        connection.execute("DELETE FROM movie_credits WHERE snapshot_key = ?", (snapshot_key,))
        for credit_type, people in (("director", directors), ("cast", cast), ("writer", writers)):
            seen_writer_credits = set()
            for position, person in enumerate(people if isinstance(people, list) else []):
                if not isinstance(person, dict) or not _text(person.get("name")):
                    continue
                job = _text(person.get("job")) if credit_type == "writer" else ""
                if credit_type == "writer" and job not in WRITER_JOBS:
                    continue
                person_id = _text(person.get("id"))
                writer_identity = person_id or _text(person.get("name")).casefold()
                if credit_type == "writer" and (writer_identity, job) in seen_writer_credits:
                    continue
                if credit_type == "writer":
                    seen_writer_credits.add((writer_identity, job))
                person_key = _provider_person_key(provider, snapshot_key, credit_type, position, person)
                connection.execute("""
                    INSERT INTO people(person_key, tmdb_id, provider, provider_id, name, profile_url, updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(person_key) DO UPDATE SET
                        name=excluded.name,
                        profile_url=CASE
                            WHEN excluded.profile_url<>'' AND excluded.updated_at>=people.updated_at
                            THEN excluded.profile_url
                            ELSE people.profile_url
                        END,
                        updated_at=MAX(people.updated_at, excluded.updated_at)
                """, (
                    person_key, person_id if provider == "tmdb" else "", provider, person_id,
                    _text(person.get("name")), _text(person.get("profile_url")),
                    _number(record.get("updated_at")),
                ))
                connection.execute(
                    "INSERT INTO movie_credits(snapshot_key, credit_type, position, person_key, credited_name, character, profile_url, job) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        snapshot_key, credit_type, position, person_key,
                        _text(person.get("name")), _text(person.get("character")),
                        _text(person.get("profile_url")), job,
                    ),
                )

        self._replace_snapshot_keywords(connection, snapshot_key, keywords)

        connection.execute("DELETE FROM movie_genres WHERE snapshot_key = ?", (snapshot_key,))
        for position, genre in enumerate(genres if isinstance(genres, list) else []):
            name = _text(genre.get("name") if isinstance(genre, dict) else genre)
            if not name:
                continue
            genre_key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or hashlib.sha256(name.encode()).hexdigest()
            connection.execute("INSERT OR IGNORE INTO genres(genre_key, name) VALUES(?, ?)", (genre_key, name))
            connection.execute(
                "INSERT INTO movie_genres(snapshot_key, position, genre_key) VALUES(?,?,?)",
                (snapshot_key, position, genre_key),
            )

        connection.execute("DELETE FROM movie_collections WHERE snapshot_key = ?", (snapshot_key,))
        if isinstance(collection, dict) and _text(collection.get("id")):
            collection_id = _text(collection.get("id"))
            collection_key = f"{provider}:{collection_id}"
            connection.execute("""
                INSERT INTO collections(
                    collection_key, provider, provider_id, name, poster_url, backdrop_url, updated_at
                ) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(collection_key) DO UPDATE SET
                    name=CASE WHEN excluded.name<>'' AND excluded.updated_at>=collections.updated_at THEN excluded.name ELSE collections.name END,
                    poster_url=CASE WHEN excluded.poster_url<>'' AND excluded.updated_at>=collections.updated_at THEN excluded.poster_url ELSE collections.poster_url END,
                    backdrop_url=CASE WHEN excluded.backdrop_url<>'' AND excluded.updated_at>=collections.updated_at THEN excluded.backdrop_url ELSE collections.backdrop_url END,
                    updated_at=MAX(collections.updated_at, excluded.updated_at)
            """, (
                collection_key, provider, collection_id, _text(collection.get("name")),
                _text(collection.get("poster_url")), _text(collection.get("backdrop_url")),
                _number(record.get("updated_at")),
            ))
            connection.execute("""
                INSERT INTO movie_collections(
                    snapshot_key, collection_key, name, poster_url, backdrop_url
                ) VALUES(?,?,?,?,?)
            """, (
                snapshot_key, collection_key, _text(collection.get("name")),
                _text(collection.get("poster_url")), _text(collection.get("backdrop_url")),
            ))

    @staticmethod
    def _replace_snapshot_keywords(connection, snapshot_key, values, report=None):
        report = report if report is not None else {}
        connection.execute("DELETE FROM movie_keywords WHERE snapshot_key = ?", (snapshot_key,))
        if not isinstance(values, list):
            report["keyword_arrays_malformed"] = report.get("keyword_arrays_malformed", 0) + 1
            return
        if not values:
            report["keyword_snapshots_empty"] = report.get("keyword_snapshots_empty", 0) + 1
            return
        seen = set()
        for position, value in enumerate(values):
            report["keyword_entries_processed"] = report.get("keyword_entries_processed", 0) + 1
            if isinstance(value, dict):
                name = _text(value.get("name"))
                tmdb_id = _text(value.get("id"))
            else:
                name = _text(value)
                tmdb_id = ""
            normalized_name = normalize_keyword_name(name)
            if not name or not normalized_name:
                report["keyword_entries_rejected"] = report.get("keyword_entries_rejected", 0) + 1
                continue
            keyword_key = _keyword_key(normalized_name)
            if keyword_key in seen:
                report["keyword_entries_deduplicated"] = report.get("keyword_entries_deduplicated", 0) + 1
                continue
            seen.add(keyword_key)
            existing = connection.execute(
                "SELECT tmdb_id, normalized_name FROM keywords WHERE keyword_key = ?",
                (keyword_key,),
            ).fetchone()
            if existing and existing["normalized_name"] != normalized_name:
                report["keyword_entries_rejected"] = report.get("keyword_entries_rejected", 0) + 1
                continue
            if existing and tmdb_id and existing["tmdb_id"] not in {"", tmdb_id}:
                report["keyword_entries_rejected"] = report.get("keyword_entries_rejected", 0) + 1
                continue
            if tmdb_id:
                id_owner = connection.execute(
                    "SELECT keyword_key FROM keywords WHERE tmdb_id = ?",
                    (tmdb_id,),
                ).fetchone()
                if id_owner and id_owner["keyword_key"] != keyword_key:
                    report["keyword_entries_rejected"] = report.get("keyword_entries_rejected", 0) + 1
                    continue
            connection.execute("""
                INSERT INTO keywords(keyword_key, tmdb_id, name, normalized_name)
                VALUES(?,?,?,?)
                ON CONFLICT(keyword_key) DO UPDATE SET
                    tmdb_id=CASE
                        WHEN keywords.tmdb_id='' AND excluded.tmdb_id<>'' THEN excluded.tmdb_id
                        ELSE keywords.tmdb_id
                    END
            """, (keyword_key, tmdb_id, name, normalized_name))
            connection.execute(
                "INSERT INTO movie_keywords(snapshot_key, position, keyword_key) VALUES(?,?,?)",
                (snapshot_key, position, keyword_key),
            )
            report["keyword_relationships_inserted"] = report.get("keyword_relationships_inserted", 0) + 1

    def backfill_search_relations(self, connection, credit_table, checkpoint=None):
        if credit_table not in {"movie_credits", "movie_credits_v8_new"}:
            raise ValueError("Unsupported movie credit migration target")
        report = {
            "snapshots_processed": 0,
            "snapshots_invalid_json": 0,
            "writer_snapshots_missing": 0,
            "writer_snapshots_empty": 0,
            "writer_arrays_malformed": 0,
            "writer_entries_processed": 0,
            "writer_entries_inserted": 0,
            "writer_entries_deduplicated": 0,
            "writer_entries_rejected": 0,
            "writer_people_inserted": 0,
            "writer_people_reused": 0,
            "keyword_snapshots_missing": 0,
            "keyword_snapshots_empty": 0,
            "keyword_arrays_malformed": 0,
            "keyword_entries_processed": 0,
            "keyword_relationships_inserted": 0,
            "keyword_entries_deduplicated": 0,
            "keyword_entries_rejected": 0,
        }
        writer_checkpoint_done = False
        keyword_checkpoint_done = False
        rows = connection.execute("""
            SELECT snapshot_key, provider, updated_at, source_json
            FROM provider_movie_snapshots
            ORDER BY snapshot_key
        """).fetchall()
        for row in rows:
            report["snapshots_processed"] += 1
            try:
                record = json.loads(row["source_json"])
            except (TypeError, ValueError, json.JSONDecodeError):
                report["snapshots_invalid_json"] += 1
                continue
            if not isinstance(record, dict):
                report["snapshots_invalid_json"] += 1
                continue

            if "writers" not in record:
                report["writer_snapshots_missing"] += 1
                writers = []
            else:
                writers = record.get("writers")
                if not isinstance(writers, list):
                    report["writer_arrays_malformed"] += 1
                    writers = []
                elif not writers:
                    report["writer_snapshots_empty"] += 1
            seen_writers = set()
            for position, person in enumerate(writers):
                report["writer_entries_processed"] += 1
                if not isinstance(person, dict):
                    report["writer_entries_rejected"] += 1
                    continue
                name = _text(person.get("name"))
                job = _text(person.get("job"))
                if not name or job not in WRITER_JOBS:
                    report["writer_entries_rejected"] += 1
                    continue
                person_key = _provider_person_key(
                    row["provider"], row["snapshot_key"], "writer", position, person
                )
                person_id = _text(person.get("id"))
                duplicate_key = (person_id or name.casefold(), job)
                if duplicate_key in seen_writers:
                    report["writer_entries_deduplicated"] += 1
                    continue
                seen_writers.add(duplicate_key)
                exists = connection.execute(
                    "SELECT 1 FROM people WHERE person_key = ?",
                    (person_key,),
                ).fetchone()
                connection.execute("""
                    INSERT OR IGNORE INTO people(
                        person_key, tmdb_id, provider, provider_id, name, profile_url, updated_at
                    ) VALUES(?,?,?,?,?,?,?)
                """, (
                    person_key,
                    person_id if row["provider"] == "tmdb" else "",
                    row["provider"],
                    person_id,
                    name,
                    _text(person.get("profile_url")),
                    _number(row["updated_at"]),
                ))
                report["writer_people_reused" if exists else "writer_people_inserted"] += 1
                connection.execute(f"""
                    INSERT INTO {credit_table}(
                        snapshot_key, credit_type, position, person_key,
                        credited_name, character, profile_url, job
                    ) VALUES(?, 'writer', ?, ?, ?, '', ?, ?)
                """, (
                    row["snapshot_key"], position, person_key, name,
                    _text(person.get("profile_url")), job,
                ))
                report["writer_entries_inserted"] += 1
                if checkpoint and not writer_checkpoint_done:
                    checkpoint("during_writer_backfill")
                    writer_checkpoint_done = True

            if "keywords" not in record:
                report["keyword_snapshots_missing"] += 1
                keywords = []
            else:
                keywords = record.get("keywords")
            before = report["keyword_relationships_inserted"]
            self._replace_snapshot_keywords(connection, row["snapshot_key"], keywords, report)
            if checkpoint and not keyword_checkpoint_done and report["keyword_relationships_inserted"] > before:
                checkpoint("during_keyword_backfill")
                keyword_checkpoint_done = True
        return report

    def _sync_identity_decision(self, connection, row, movie_key, file_record, manual_record):
        provider = _text(manual_record.get("provider") or row.get("display_provider"))
        provider_id = _text(
            manual_record.get("tmdb_id") or manual_record.get("plex_guid")
            or row.get("tmdb_id") or row.get("plex_guid")
        )
        connection.execute("""
            INSERT OR REPLACE INTO identity_decisions(
                path_key, movie_key, status, source, provider, provider_id, revision,
                manual_lock, updated_at, raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (
            row["path_key"], movie_key or None,
            _text(row.get("identity_status") or row.get("metadata_status")),
            _text(row.get("identity_source") or row.get("metadata_source")),
            provider, provider_id, int(row.get("identity_revision") or 0),
            1 if row.get("manual_lock") or row.get("manual_locked") else 0,
            max(_number(file_record.get("updated_at")), _number(manual_record.get("updated_at"))),
            _json({"file": file_record, "manual_match": manual_record}),
        ))

    def _sync_overrides(self, connection):
        connection.execute("DELETE FROM movie_override_identity_keys")
        connection.execute("DELETE FROM movie_overrides")
        specs = (
            ("app_metadata/metadata_overrides.json", "metadata"),
            ("app_metadata/poster_overrides.json", "poster"),
        )
        for document_name, override_type in specs:
            row = connection.execute(
                "SELECT payload_json FROM source_documents WHERE name = ?", (document_name,)
            ).fetchone()
            if not row:
                continue
            try:
                overrides = json.loads(row[0]).get("overrides", [])
            except (TypeError, ValueError):
                overrides = []
            for position, override in enumerate(overrides if isinstance(overrides, list) else []):
                if not isinstance(override, dict):
                    continue
                override_id = _text(override.get("id")) or f"{override_type}:{position}"
                connection.execute("""
                    INSERT OR REPLACE INTO movie_overrides(
                        override_id, override_type, title, year, poster_url, source,
                        locked, updated_at, raw_json
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                """, (
                    override_id, override_type, _text(override.get("title")),
                    _text(override.get("year")), _text(override.get("poster_url")),
                    _text(override.get("source")), 1 if override.get("locked", True) else 0,
                    _number(override.get("updated_at")), _json(override),
                ))
                keys = override.get("identity_keys") or ownership_keys(override.get("identity") or {})
                for identity_key in dict.fromkeys(_text(key) for key in keys if _text(key)):
                    connection.execute(
                        "INSERT OR IGNORE INTO movie_override_identity_keys(override_id, identity_key) VALUES(?, ?)",
                        (override_id, identity_key),
                    )

    def project_path(self, connection, path_key, include_overrides=True):
        return self.project_paths(
            connection, [path_key], include_details=True, include_overrides=include_overrides
        ).get(path_key, {})

    def tmdb_detail_contract_backfill_ids(self, connection, *, limit=None):
        """Return selected TMDB identities whose stored snapshot predates the detail contract."""
        query = """
            SELECT DISTINCT cm.tmdb_id
            FROM canonical_movies cm
            LEFT JOIN provider_movie_snapshots pms
              ON pms.movie_key = cm.movie_key
             AND pms.provider = 'tmdb'
             AND pms.snapshot_key = 'tmdb:' || cm.tmdb_id
            WHERE cm.selected_provider = 'tmdb'
              AND cm.tmdb_id <> ''
              AND (
                    pms.snapshot_key IS NULL
                 OR json_valid(pms.source_json) = 0
                 OR json_type(pms.source_json, '$.writers') IS NULL
                 OR json_type(pms.source_json, '$.certification') IS NULL
                 OR json_type(pms.source_json, '$.keywords') IS NULL
              )
            ORDER BY cm.tmdb_id
        """
        parameters = ()
        if limit is not None:
            query += " LIMIT ?"
            parameters = (max(0, int(limit)),)
        return [_text(row[0]) for row in connection.execute(query, parameters).fetchall() if _text(row[0])]

    def project_paths(self, connection, path_keys, *, include_details=False, include_overrides=True):
        """Project a bounded path set with a constant number of relational queries."""
        path_keys = list(dict.fromkeys(_text(key) for key in path_keys if _text(key)))
        if not path_keys:
            return {}
        encoded_paths = _json(path_keys)
        movie_rows = [dict(row) for row in connection.execute("""
            SELECT cmf.path_key, cm.*
            FROM canonical_movie_files cmf
            JOIN canonical_movies cm ON cm.movie_key = cmf.movie_key
            WHERE cmf.path_key IN (SELECT value FROM json_each(?))
        """, (encoded_paths,)).fetchall()]
        if not movie_rows:
            return {}
        movie_keys = list(dict.fromkeys(row["movie_key"] for row in movie_rows))
        asset_generation_row = connection.execute(
            "SELECT value FROM catalog_meta WHERE key='asset_generation'"
        ).fetchone()
        asset_generation = int(asset_generation_row[0]) if asset_generation_row else 0
        movie_assets = {
            row[0]: {"url": f"/api/assets/{row[1]}", "retention_class": row[2]}
            for row in connection.execute("""
                SELECT ma.movie_key, a.checksum, a.retention_class
                FROM movie_assets ma JOIN media_assets a ON a.asset_key=ma.asset_key
                WHERE ma.selected=1 AND ma.asset_type='poster' AND a.status='ready' AND a.checksum<>''
                  AND ma.movie_key IN (SELECT value FROM json_each(?))
            """, (_json(movie_keys),)).fetchall()
        }
        snapshots = [dict(row) for row in connection.execute("""
            SELECT * FROM provider_movie_snapshots
            WHERE movie_key IN (SELECT value FROM json_each(?))
        """, (_json(movie_keys),)).fetchall()]
        snapshots_by_movie = {}
        for snapshot in snapshots:
            snapshots_by_movie.setdefault(snapshot["movie_key"], []).append(snapshot)

        chosen = {}
        selected_present = {}
        for movie in movie_rows:
            candidates = snapshots_by_movie.get(movie["movie_key"], [])
            selected = [row for row in candidates if row["provider"] == movie["selected_provider"]]
            if movie["selected_provider"] == "tmdb" and movie.get("tmdb_id"):
                selected = [row for row in selected if row["snapshot_key"] == f"tmdb:{movie['tmdb_id']}"]
            selected.sort(key=lambda row: (
                0 if row.get("path_key") == movie["path_key"] else 1,
                -_number(row.get("updated_at")), row["snapshot_key"],
            ))
            selected_present[movie["path_key"]] = bool(selected)
            if selected:
                chosen[movie["path_key"]] = selected[0]
                continue
            fallback = [row for row in candidates if row["provider"] != movie["selected_provider"]]
            fallback.sort(key=lambda row: (
                0 if row["provider"] == ("plex" if movie["selected_provider"] == "tmdb" else "tmdb") else 1,
                0 if row.get("path_key") == movie["path_key"] else 1,
                -_number(row.get("updated_at")), row["snapshot_key"],
            ))
            chosen[movie["path_key"]] = fallback[0] if fallback else {}

        relation_snapshots = snapshots if include_details else list(chosen.values())
        snapshot_keys = list(dict.fromkeys(
            snapshot.get("snapshot_key", "") for snapshot in relation_snapshots if snapshot.get("snapshot_key")
        ))
        genres = {key: [] for key in snapshot_keys}
        if snapshot_keys:
            for row in connection.execute("""
                SELECT mg.snapshot_key, g.name FROM movie_genres mg
                JOIN genres g ON g.genre_key = mg.genre_key
                WHERE mg.snapshot_key IN (SELECT value FROM json_each(?))
                ORDER BY mg.snapshot_key, mg.position
            """, (_json(snapshot_keys),)).fetchall():
                genres[row[0]].append(row[1])

        credits = {
            (key, credit_type): []
            for key in snapshot_keys
            for credit_type in ("cast", "director", "writer")
        }
        keywords = {key: [] for key in snapshot_keys}
        collections = {}
        if include_details and snapshot_keys:
            for row in connection.execute("""
                SELECT mc.snapshot_key, mc.credit_type,
                       CASE WHEN p.tmdb_id<>'' THEN p.tmdb_id ELSE p.provider_id END AS person_id,
                       CASE WHEN mc.credited_name<>'' THEN mc.credited_name ELSE p.name END AS name,
                       CASE WHEN a.status='ready' AND a.checksum<>''
                            THEN '/api/assets/' || a.checksum ELSE mc.profile_url END AS profile_url,
                       mc.character, mc.profile_url AS remote_profile_url, mc.job
                FROM movie_credits mc JOIN people p ON p.person_key=mc.person_key
                LEFT JOIN person_assets pa ON pa.person_key=p.person_key
                    AND pa.asset_type='portrait' AND pa.selected=1
                LEFT JOIN media_assets a ON a.asset_key=pa.asset_key
                WHERE mc.snapshot_key IN (SELECT value FROM json_each(?))
                ORDER BY mc.snapshot_key, mc.credit_type, mc.position
            """, (_json(snapshot_keys),)).fetchall():
                person = {"id": _text(row[2]), "name": _text(row[3]), "profile_url": _text(row[4])}
                if _text(row[6]) and _text(row[6]) != person["profile_url"]:
                    person["remote_profile_url"] = _text(row[6])
                if row[1] == "cast":
                    person["character"] = _text(row[5])
                elif row[1] == "writer":
                    person["job"] = _text(row[7])
                credits[(row[0], row[1])].append(person)
            for row in connection.execute("""
                SELECT mk.snapshot_key, k.name
                FROM movie_keywords mk
                JOIN keywords k ON k.keyword_key = mk.keyword_key
                WHERE mk.snapshot_key IN (SELECT value FROM json_each(?))
                ORDER BY mk.snapshot_key, mk.position
            """, (_json(snapshot_keys),)).fetchall():
                keywords[row[0]].append(row[1])
            for row in connection.execute("""
                SELECT mc.snapshot_key, c.provider_id, mc.name, mc.poster_url, mc.backdrop_url
                FROM movie_collections mc JOIN collections c ON c.collection_key=mc.collection_key
                WHERE mc.snapshot_key IN (SELECT value FROM json_each(?))
            """, (_json(snapshot_keys),)).fetchall():
                collections[row[0]] = {
                    "id": _text(row[1]), "name": _text(row[2]),
                    "poster_url": _text(row[3]), "backdrop_url": _text(row[4]),
                }

        identity_keys = {row["path_key"]: {row["movie_key"]} for row in movie_rows}
        if include_overrides:
            for row in connection.execute("""
                SELECT path_key, identity_key FROM media_identity_keys
                WHERE path_key IN (SELECT value FROM json_each(?))
            """, (encoded_paths,)).fetchall():
                identity_keys.setdefault(row[0], set()).add(row[1])
        all_identity_keys = sorted({key for keys in identity_keys.values() for key in keys})
        overrides = []
        if include_overrides and all_identity_keys:
            overrides = [dict(row) for row in connection.execute("""
                SELECT mo.*, mk.identity_key FROM movie_overrides mo
                JOIN movie_override_identity_keys mk ON mk.override_id=mo.override_id
                WHERE mk.identity_key IN (SELECT value FROM json_each(?))
                ORDER BY mo.updated_at, mo.override_id
            """, (_json(all_identity_keys),)).fetchall()]

        result = {}
        for movie in movie_rows:
            path_key = movie["path_key"]
            snapshot = chosen.get(path_key, {})
            snapshot_key = snapshot.get("snapshot_key", "")
            selected_snapshot_present = selected_present.get(path_key, False)
            source_details = {}
            if include_details and snapshot.get("source_json"):
                try:
                    source_details = json.loads(snapshot["source_json"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    source_details = {}
            requested = _text(movie.get("requested_enrichment_status")).lower()
            selected_complete = bool(
                selected_snapshot_present and snapshot.get("details_state") == "complete"
                and snapshot.get("people_state") in {"complete", "empty"}
            )
            canonical = {
                "accepted": True, "status": "accepted", "identity_status": "accepted",
                "enrichment_status": requested if requested in {"stale", "unavailable"} else (
                    "complete" if selected_complete else "incomplete"
                ),
                "metadata_contract_version": CANONICAL_CONTRACT_VERSION,
                "source": movie.get("identity_source", ""),
                "detail_provider": f"{snapshot.get('provider')}_snapshot" if snapshot else "",
                "selected_provider": movie.get("selected_provider", ""),
                "selected_provider_snapshot": selected_snapshot_present,
                "fallback_active": bool(snapshot) and not selected_snapshot_present,
                "people_status": snapshot.get("people_state", "missing"),
                "movie_key": movie.get("movie_key", ""),
                "title": movie.get("title") or snapshot.get("title", ""),
                "year": movie.get("year") or snapshot.get("year", ""),
                "tmdb_id": movie.get("tmdb_id", ""),
                "imdb_id": movie.get("imdb_id") or snapshot.get("imdb_id", ""),
                "plex_guid": movie.get("plex_guid", ""),
                "identity_revision": int(movie.get("identity_revision") or 0),
                "poster_url": snapshot.get("poster_url", ""),
                "backdrop_url": snapshot.get("backdrop_url", ""),
                "genres": genres.get(snapshot_key, []),
                "plot": snapshot.get("plot", ""), "summary": snapshot.get("plot", ""),
                "rating": snapshot.get("rating", ""),
                "tmdb_rating": snapshot.get("rating", "") if snapshot.get("provider") == "tmdb" else "",
                "plex_rating": snapshot.get("rating", "") if snapshot.get("provider") == "plex" else "",
                "tmdb_vote_count": int(snapshot.get("vote_count") or 0),
                "language": snapshot.get("language", ""), "country": snapshot.get("country", ""),
                "country_flag": snapshot.get("country_flag", ""),
                "release_date": snapshot.get("release_date", ""),
                "runtime": snapshot.get("runtime"), "tagline": snapshot.get("tagline", ""),
                "trailer_url": snapshot.get("trailer_url", ""),
                "collection": collections.get(snapshot_key, {}),
                "cast": credits.get((snapshot_key, "cast"), []),
                "directors": credits.get((snapshot_key, "director"), []),
                "writers": credits.get((snapshot_key, "writer"), []),
                "certification": _text(source_details.get("certification")),
                "keywords": keywords.get(snapshot_key, []),
            }
            if include_details:
                plex_candidates = [
                    row for row in snapshots_by_movie.get(movie["movie_key"], []) if row["provider"] == "plex"
                ]
                plex_candidates.sort(key=lambda row: (
                    0 if row.get("path_key") == path_key else 1,
                    -_number(row.get("updated_at")), row["snapshot_key"],
                ))
                plex = plex_candidates[0] if plex_candidates else {}
                plex_key = plex.get("snapshot_key", "")
                canonical.update({
                    "plex_title": plex.get("title", ""), "plex_year": plex.get("year", ""),
                    "plex_summary": plex.get("plot", ""), "plex_rating": plex.get("rating", ""),
                    "plex_language": plex.get("language", ""), "plex_country": plex.get("country", ""),
                    "plex_country_flag": plex.get("country_flag", ""),
                    "plex_poster": plex.get("poster_url", ""),
                    "plex_genres": genres.get(plex_key, []),
                    "plex_cast": credits.get((plex_key, "cast"), []),
                    "plex_directors": credits.get((plex_key, "director"), []),
                })
            canonical["director"] = canonical["directors"][0] if canonical["directors"] else {}
            for override in overrides:
                if override["identity_key"] not in identity_keys.get(path_key, set()):
                    continue
                if override["override_type"] == "metadata":
                    if override.get("title"): canonical["title"] = override["title"]
                    if override.get("year"): canonical["year"] = override["year"]
                    canonical["metadata_override"] = True
                elif override["override_type"] == "poster" and override.get("poster_url"):
                    canonical["poster_url"] = override["poster_url"]
                    canonical["poster_override"] = True
                    canonical["poster_override_source"] = override.get("source", "")
                    canonical["poster_override_locked"] = bool(override.get("locked"))
            local_asset = movie_assets.get(movie["movie_key"])
            if local_asset and (local_asset["retention_class"] == "custom" or not canonical.get("poster_override")):
                canonical["remote_poster_url"] = canonical.get("poster_url", "")
                canonical["poster_url"] = local_asset["url"]
                canonical["local_poster_url"] = local_asset["url"]
            canonical["asset_generation"] = asset_generation
            result[path_key] = (
                canonical_details_projection(canonical) if include_details else canonical_card_projection(canonical)
            )
        return result

    @staticmethod
    def _selected_snapshot(connection, movie, path_key, provider):
        if provider == "tmdb" and _text(movie.get("tmdb_id")):
            return connection.execute(
                "SELECT * FROM provider_movie_snapshots WHERE snapshot_key = ?",
                (f"tmdb:{movie['tmdb_id']}",),
            ).fetchone()
        if provider == "plex":
            return connection.execute("""
                SELECT * FROM provider_movie_snapshots
                WHERE movie_key = ? AND provider = 'plex'
                ORDER BY CASE WHEN path_key = ? THEN 0 ELSE 1 END, updated_at DESC
                LIMIT 1
            """, (movie["movie_key"], path_key)).fetchone()
        return None

    @staticmethod
    def _fallback_snapshot(connection, movie_key, path_key, selected_provider):
        order = "CASE provider WHEN 'tmdb' THEN 0 ELSE 1 END" if selected_provider != "tmdb" else "CASE provider WHEN 'plex' THEN 0 ELSE 1 END"
        return connection.execute(f"""
            SELECT * FROM provider_movie_snapshots
            WHERE movie_key = ? AND provider <> ?
            ORDER BY {order}, CASE WHEN path_key = ? THEN 0 ELSE 1 END, updated_at DESC
            LIMIT 1
        """, (movie_key, selected_provider, path_key)).fetchone()

    @staticmethod
    def _credits(connection, snapshot_key, credit_type):
        if not snapshot_key:
            return []
        result = []
        for row in connection.execute("""
                SELECT CASE WHEN p.tmdb_id<>'' THEN p.tmdb_id ELSE p.provider_id END,
                       CASE WHEN mc.credited_name<>'' THEN mc.credited_name ELSE p.name END,
                       mc.profile_url, mc.character, mc.job
                FROM movie_credits mc
                JOIN people p ON p.person_key = mc.person_key
                WHERE mc.snapshot_key = ? AND mc.credit_type = ?
                ORDER BY mc.position
            """, (snapshot_key, credit_type)).fetchall():
            person = {
                "id": _text(row[0]), "name": _text(row[1]),
                "profile_url": _text(row[2]),
            }
            if credit_type == "cast":
                person["character"] = _text(row[3])
            elif credit_type == "writer":
                person["job"] = _text(row[4])
            result.append(person)
        return result

    @staticmethod
    def _apply_overrides(connection, path_key, movie, canonical):
        identity_keys = {movie["movie_key"]}
        identity_keys.update(
            row[0]
            for row in connection.execute(
                "SELECT identity_key FROM media_identity_keys WHERE path_key = ?", (path_key,)
            ).fetchall()
        )
        if not identity_keys:
            return
        placeholders = ",".join("?" for _ in identity_keys)
        rows = connection.execute(f"""
            SELECT DISTINCT mo.* FROM movie_overrides mo
            JOIN movie_override_identity_keys mk ON mk.override_id = mo.override_id
            WHERE mk.identity_key IN ({placeholders})
            ORDER BY mo.updated_at
        """, sorted(identity_keys)).fetchall()
        for row in rows:
            override = dict(row)
            if override["override_type"] == "metadata":
                if override.get("title"):
                    canonical["title"] = override["title"]
                if override.get("year"):
                    canonical["year"] = override["year"]
                canonical["metadata_override"] = True
            elif override["override_type"] == "poster" and override.get("poster_url"):
                canonical["poster_url"] = override["poster_url"]
                canonical["poster_override"] = True

    def strict_report(self, connection, max_errors=100):
        violations = []
        rows = connection.execute("""
            SELECT cmf.path_key, cm.movie_key, cm.selected_provider, cm.tmdb_id
            FROM canonical_movie_files cmf
            JOIN canonical_movies cm ON cm.movie_key = cmf.movie_key
            ORDER BY cmf.path_key
        """).fetchall()
        provider_counts = {}
        incomplete = 0
        for row in rows:
            projection = self.project_path(connection, row["path_key"])
            provider = projection.get("detail_provider", "")
            provider_counts[provider] = provider_counts.get(provider, 0) + 1
            if projection.get("enrichment_status") != "complete":
                incomplete += 1
            if row["selected_provider"] == "tmdb" and row["tmdb_id"] and not projection.get("selected_provider_snapshot"):
                if len(violations) < max_errors:
                    violations.append({
                        "path_key": row["path_key"],
                        "movie_key": row["movie_key"],
                        "message": "TMDB-selected identity has no relational TMDB snapshot",
                    })
        return {
            "contract_version": CANONICAL_CONTRACT_VERSION,
            "checked_files": len(rows),
            "canonical_movies": int(connection.execute("SELECT COUNT(*) FROM canonical_movies").fetchone()[0]),
            "people": int(connection.execute("SELECT COUNT(*) FROM people").fetchone()[0]),
            "credits": int(connection.execute("SELECT COUNT(*) FROM movie_credits").fetchone()[0]),
            "writer_credits": int(connection.execute(
                "SELECT COUNT(*) FROM movie_credits WHERE credit_type='writer'"
            ).fetchone()[0]),
            "keywords": int(connection.execute("SELECT COUNT(*) FROM keywords").fetchone()[0]),
            "movie_keywords": int(connection.execute("SELECT COUNT(*) FROM movie_keywords").fetchone()[0]),
            "incomplete_files": incomplete,
            "detail_providers": dict(sorted(provider_counts.items())),
            "violations": violations,
            "passed": not violations,
        }
