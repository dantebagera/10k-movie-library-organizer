def downgrade_catalog_to_v7(store):
    """Turn an isolated version 8 fixture into the exact version 7 relation shape."""
    with store.transaction() as connection:
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
