import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import app
from tools.catalog_json_shadow_compare import _canonical_projection, compare_json_shadow
from tools.catalog_migration_backup import create_backup


class CatalogJsonShadowCompareTest(unittest.TestCase):
    def test_shadow_projection_normalizes_empty_collections_and_people_whitespace(self):
        left = _canonical_projection({
            'collection': None,
            'cast': [{'id': '1', 'name': 'Actor ', 'character': ' Lead ', 'profile_url': ''}],
        })
        right = _canonical_projection({
            'collection': {},
            'cast': [{'id': 1, 'name': 'Actor', 'character': 'Lead', 'profile_url': ''}],
        })

        self.assertEqual(left, right)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_user_data_dir = app._user_data_dir
        self.original_repositories = dict(app._catalog_repository_cache)
        app._user_data_dir = self.tmp.name
        app._catalog_repository_cache.clear()
        self.store = app.AppMetadataStore(Path(self.tmp.name))
        self.path = 'E:/Movies/Legacy Shadow.2024.mkv'
        self.store.apply_tmdb_match(self.path, {
            'tmdb_id': '42',
            'imdb_id': 'tt0000042',
            'title': 'Legacy Shadow',
            'year': '2024',
            'plot': 'Persisted plot.',
            'genres': ['Drama'],
            'writers': [{'id': '19', 'name': 'Shadow Writer', 'job': 'Writer'}],
            'keywords': ['shadow keyword'],
            'certification': '',
        })
        self.store.update_file_record(self.path, {'filename': 'Legacy Shadow.2024.mkv', 'resolution': '1080p'})
        self.store.save_plex_metadata(self.path, {'plex_title': 'Legacy Shadow', 'plex_year': '2024', 'plex_summary': 'Plex summary.'})
        self._write_literal_json_snapshot()

    def tearDown(self):
        app._catalog_repository_cache.clear()
        app._catalog_repository_cache.update(self.original_repositories)
        app._user_data_dir = self.original_user_data_dir
        self.tmp.cleanup()

    def _write_literal_json_snapshot(self):
        documents = {
            'files.json': ('app_metadata/files.json', {'files': {}}),
            'tmdb_metadata.json': ('app_metadata/tmdb_metadata.json', {'movies': {}}),
            'plex_metadata.json': ('app_metadata/plex_metadata.json', {'files': {}}),
            'manual_matches.json': ('app_metadata/manual_matches.json', {'matches': {}}),
            'poster_overrides.json': ('app_metadata/poster_overrides.json', {'overrides': []}),
            'metadata_overrides.json': ('app_metadata/metadata_overrides.json', {'overrides': []}),
        }
        base = Path(self.tmp.name) / 'app_metadata'
        base.mkdir(parents=True, exist_ok=True)
        for filename, (document, fallback) in documents.items():
            payload = self.store.catalog.read_document(document, fallback)
            (base / filename).write_text(json.dumps(payload), encoding='utf-8')

    def _create_cutover_backup(self):
        project_root = Path(self.tmp.name) / 'project'
        project_root.mkdir(exist_ok=True)
        (project_root / 'config.json').write_text(
            json.dumps({'user_data_dir': self.tmp.name}), encoding='utf-8'
        )
        (project_root / 'package.json').write_text(
            json.dumps({'version': 'test'}), encoding='utf-8'
        )
        archive, _ = create_backup(project_root, output_dir=Path(self.tmp.name) / 'cutover-backups')
        return archive

    def test_literal_json_and_sql_canonical_records_match_without_provider_calls(self):
        report = compare_json_shadow(self.tmp.name)

        self.assertTrue(report['passed'])
        self.assertEqual(report['checked_records'], 1)
        self.assertEqual(report['provider_calls'], 0)
        self.assertEqual(report['post_snapshot_document_changes'], [])

    def test_literal_json_difference_is_reported_without_mutating_sql(self):
        files_path = Path(self.tmp.name) / 'app_metadata' / 'files.json'
        payload = json.loads(files_path.read_text(encoding='utf-8'))
        record = next(iter(payload['files'].values()))
        record['identity_title'] = 'Wrong legacy title'
        files_path.write_text(json.dumps(payload), encoding='utf-8')

        report = compare_json_shadow(self.tmp.name)
        sql_record = self.store.catalog.get_record('app_metadata/files.json', app._norm(self.path), {})

        self.assertFalse(report['passed'])
        self.assertEqual(len(report['violations']['canonical']), 1)
        self.assertEqual(len(report['violations']['document_changed']), 1)
        self.assertEqual(sql_record['identity_title'], 'Legacy Shadow')

    def test_relational_writer_keyword_drift_is_a_parity_failure(self):
        connection = self.store.catalog.store.connect()
        try:
            connection.execute(
                "DELETE FROM movie_keywords WHERE snapshot_key='tmdb:42'"
            )
            connection.commit()
        finally:
            connection.close()

        report = compare_json_shadow(self.tmp.name)

        self.assertFalse(report['passed'])
        self.assertEqual(len(report['violations']['canonical']), 1)

    def test_sql_record_created_after_the_frozen_json_snapshot_is_reported_but_not_a_parity_failure(self):
        new_path = 'E:/Movies/Added After Snapshot.2025.mkv'
        self.store.apply_tmdb_match(new_path, {
            'tmdb_id': '43',
            'title': 'Added After Snapshot',
            'year': '2025',
        })
        self.store.update_file_record(new_path, {'filename': 'Added After Snapshot.2025.mkv'})

        report = compare_json_shadow(self.tmp.name)

        self.assertTrue(report['passed'])
        self.assertEqual(len(report['post_snapshot_sql_only']), 1)
        self.assertEqual(len(report['post_snapshot_document_changes']), 3)
        self.assertEqual(report['record_counts']['differences'], {})

    def test_sql_record_older_than_the_frozen_json_snapshot_remains_a_failure(self):
        new_path = 'E:/Movies/Unexpected SQL Only.2025.mkv'
        self.store.apply_tmdb_match(new_path, {
            'tmdb_id': '44',
            'title': 'Unexpected SQL Only',
            'year': '2025',
        })
        self.store.update_file_record(new_path, {'filename': 'Unexpected SQL Only.2025.mkv'})
        files_path = Path(self.tmp.name) / 'app_metadata' / 'files.json'
        future = time.time() + 60
        os.utime(files_path, (future, future))

        report = compare_json_shadow(self.tmp.name)

        self.assertFalse(report['passed'])
        self.assertEqual(len(report['violations']['sql_only']), 1)
        self.assertEqual(len(report['violations']['document_sql_only']), 3)

    def test_verified_cutover_proves_a_later_file_deletion_is_not_a_migration_failure(self):
        archive = self._create_cutover_backup()
        Path(self.tmp.name, 'catalog-migration-cutover.json').write_text(json.dumps({
            'archive': archive.relative_to(self.tmp.name).as_posix(),
            'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        }), encoding='utf-8')
        self.store.catalog.delete_records('app_metadata/files.json', [app._norm(self.path)])

        report = compare_json_shadow(self.tmp.name)

        self.assertTrue(report['passed'])
        self.assertEqual(len(report['post_cutover_deletions']), 1)
        self.assertEqual(report['violations']['legacy_only'], [])
        self.assertEqual(report['record_counts']['differences'], {})

    def test_verified_cutover_proves_a_later_tmdb_refresh_changed_canonical_behavior(self):
        archive = self._create_cutover_backup()
        time.sleep(0.01)
        self.store.save_tmdb_metadata({
            'tmdb_id': '42',
            'imdb_id': 'tt0000042',
            'title': 'Legacy Shadow',
            'year': '2024',
            'plot': 'Refreshed after cutover.',
            'genres': ['Drama', 'Mystery'],
        })

        report = compare_json_shadow(self.tmp.name, cutover_archive=archive)

        self.assertTrue(report['passed'])
        self.assertEqual(len(report['post_cutover_canonical_changes']), 1)
        evidence = report['post_cutover_canonical_changes'][0]['evidence']
        self.assertEqual(evidence[0]['record_type'], 'tmdb_movies')
        self.assertEqual(report['violations']['canonical'], [])


if __name__ == '__main__':
    unittest.main()
