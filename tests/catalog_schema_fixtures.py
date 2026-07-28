from services.catalog_store import MEDIA_FILE_FACT_COLUMNS


def downgrade_media_files_to_v8(connection):
    """Remove version 9 file-facts columns from an isolated fixture."""
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(media_files)")
    }
    if not set(MEDIA_FILE_FACT_COLUMNS).intersection(columns):
        return
    connection.execute("DROP INDEX IF EXISTS idx_media_files_facts_stale")
    connection.execute("DROP INDEX IF EXISTS idx_media_files_quality")
    for column in reversed(MEDIA_FILE_FACT_COLUMNS):
        if column in columns:
            connection.execute(f'ALTER TABLE media_files DROP COLUMN "{column}"')
    connection.execute(
        "CREATE INDEX idx_media_files_quality ON media_files(resolution, rip_source)"
    )


def downgrade_catalog_to_v8(store):
    with store.transaction() as connection:
        downgrade_media_files_to_v8(connection)
        connection.execute(
            "UPDATE catalog_meta SET value='8' WHERE key='schema_version'"
        )


def downgrade_catalog_to_v7(store):
    """Turn an isolated version 9 fixture into the exact version 7 relation shape."""
    with store.transaction() as connection:
        downgrade_media_files_to_v8(connection)
        connection.execute("DROP TABLE movie_keywords")
        connection.execute("DROP TABLE keywords")
        connection.execute("""
            CREATE TABLE movie_credits_v7_fixture (
                snapshot_key TEXT NOT NULL,
                credit_type TEXT NOT NULL CHECK(credit_type IN ('cast', 'director')),
                position INTEGER NOT NULL,
                person_key TEXT NOT NULL,
                credited_name TEXT NOT NULL DEFAULT '',
                character TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (snapshot_key, credit_type, position),
                FOREIGN KEY (snapshot_key) REFERENCES provider_movie_snapshots(snapshot_key) ON DELETE CASCADE,
                FOREIGN KEY (person_key) REFERENCES people(person_key) ON DELETE CASCADE
            )
        """)
        connection.execute("""
            INSERT INTO movie_credits_v7_fixture(
                snapshot_key, credit_type, position, person_key,
                credited_name, character, profile_url
            )
            SELECT snapshot_key, credit_type, position, person_key,
                   credited_name, character, profile_url
            FROM movie_credits
            WHERE credit_type IN ('cast', 'director')
            ORDER BY snapshot_key, credit_type, position
        """)
        connection.execute("DROP TABLE movie_credits")
        connection.execute("ALTER TABLE movie_credits_v7_fixture RENAME TO movie_credits")
        connection.execute(
            "CREATE INDEX idx_movie_credits_person ON movie_credits(person_key)"
        )
        connection.execute("""
            DELETE FROM people
            WHERE NOT EXISTS(
                SELECT 1 FROM movie_credits mc WHERE mc.person_key = people.person_key
            )
        """)
        connection.execute(
            "UPDATE catalog_meta SET value='7' WHERE key='schema_version'"
        )


def use_historical_v7_credit_column_order(store):
    """Reproduce the physical column order found in upgraded schema-7 catalogues."""
    with store.transaction() as connection:
        connection.execute("""
            CREATE TABLE movie_credits_v7_historical (
                snapshot_key TEXT NOT NULL,
                credit_type TEXT NOT NULL CHECK(credit_type IN ('cast', 'director')),
                position INTEGER NOT NULL,
                person_key TEXT NOT NULL,
                character TEXT NOT NULL DEFAULT '',
                profile_url TEXT NOT NULL DEFAULT '',
                credited_name TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (snapshot_key, credit_type, position),
                FOREIGN KEY (snapshot_key) REFERENCES provider_movie_snapshots(snapshot_key) ON DELETE CASCADE,
                FOREIGN KEY (person_key) REFERENCES people(person_key) ON DELETE CASCADE
            )
        """)
        connection.execute("""
            INSERT INTO movie_credits_v7_historical(
                snapshot_key, credit_type, position, person_key,
                character, profile_url, credited_name
            )
            SELECT snapshot_key, credit_type, position, person_key,
                   character, profile_url, credited_name
            FROM movie_credits
            ORDER BY snapshot_key, credit_type, position
        """)
        connection.execute("DROP TABLE movie_credits")
        connection.execute(
            "ALTER TABLE movie_credits_v7_historical RENAME TO movie_credits"
        )
        connection.execute(
            "CREATE INDEX idx_movie_credits_person ON movie_credits(person_key)"
        )


def downgrade_catalog_to_v6_asset_fixture(store):
    """Build the known version 6 shape supported by the existing asset migration."""
    downgrade_catalog_to_v7(store)
    with store.transaction() as connection:
        for table in ("curated_asset_refs", "person_assets", "movie_assets", "media_assets"):
            connection.execute(f"DROP TABLE {table}")
        connection.execute(
            "UPDATE catalog_meta SET value='6' WHERE key='schema_version'"
        )
