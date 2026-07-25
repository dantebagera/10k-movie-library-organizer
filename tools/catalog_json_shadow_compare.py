import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app
from tools.catalog_migration_backup import verify_backup


CANONICAL_FIELDS = (
    'accepted', 'status', 'identity_status', 'source', 'detail_provider',
    'title', 'year', 'tmdb_id', 'imdb_id', 'plex_guid', 'poster_url',
    'poster_override', 'plot', 'summary', 'genres', 'cast', 'directors',
    'rating', 'tmdb_rating', 'collection', 'writers', 'keywords',
)

DOCUMENTS = {
    'files': ('app_metadata/files.json', {'files': {}}, 'files'),
    'tmdb_movies': ('app_metadata/tmdb_metadata.json', {'movies': {}}, 'movies'),
    'plex_files': ('app_metadata/plex_metadata.json', {'files': {}}, 'files'),
    'manual_matches': ('app_metadata/manual_matches.json', {'matches': {}}, 'matches'),
}


def _read_json(path, fallback):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def _legacy_snapshot(user_data_dir):
    base = Path(user_data_dir) / 'app_metadata'
    poster_overrides = _read_json(base / 'poster_overrides.json', {'overrides': []}).get('overrides', [])
    metadata_overrides = _read_json(base / 'metadata_overrides.json', {'overrides': []}).get('overrides', [])
    return {
        'files': _read_json(base / 'files.json', {'files': {}}).get('files', {}),
        'tmdb_movies': _read_json(base / 'tmdb_metadata.json', {'movies': {}}).get('movies', {}),
        'plex_files': _read_json(base / 'plex_metadata.json', {'files': {}}).get('files', {}),
        'manual_matches': _read_json(base / 'manual_matches.json', {'matches': {}}).get('matches', {}),
        'poster_overrides': poster_overrides,
        'metadata_overrides': metadata_overrides,
        '_poster_override_index': app.AppMetadataStore._index_overrides(poster_overrides),
        '_metadata_override_index': app.AppMetadataStore._index_overrides(metadata_overrides),
    }


def _archive_json(archive, name, fallback):
    try:
        data = json.loads(archive.read(name).decode('utf-8'))
    except (KeyError, UnicodeDecodeError, ValueError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def _cutover_snapshot(archive_path):
    archive_path = Path(archive_path).resolve()
    manifest = verify_backup(archive_path)
    with zipfile.ZipFile(archive_path, 'r') as archive:
        poster_overrides = _archive_json(
            archive, 'user-data/app_metadata/poster_overrides.json', {'overrides': []}
        ).get('overrides', [])
        metadata_overrides = _archive_json(
            archive, 'user-data/app_metadata/metadata_overrides.json', {'overrides': []}
        ).get('overrides', [])
        snapshot = {
            'files': _archive_json(archive, 'user-data/app_metadata/files.json', {'files': {}}).get('files', {}),
            'tmdb_movies': _archive_json(archive, 'user-data/app_metadata/tmdb_metadata.json', {'movies': {}}).get('movies', {}),
            'plex_files': _archive_json(archive, 'user-data/app_metadata/plex_metadata.json', {'files': {}}).get('files', {}),
            'manual_matches': _archive_json(archive, 'user-data/app_metadata/manual_matches.json', {'matches': {}}).get('matches', {}),
            'poster_overrides': poster_overrides,
            'metadata_overrides': metadata_overrides,
            '_poster_override_index': app.AppMetadataStore._index_overrides(poster_overrides),
            '_metadata_override_index': app.AppMetadataStore._index_overrides(metadata_overrides),
        }
    created_at = datetime.fromisoformat(str(manifest['created_at']).replace('Z', '+00:00')).timestamp()
    return snapshot, manifest, created_at


def _configured_cutover_archive(user_data_dir):
    user_data_dir = Path(user_data_dir).resolve()
    receipt_path = user_data_dir / 'catalog-migration-cutover.json'
    if not receipt_path.is_file() and user_data_dir == (PROJECT_ROOT / 'data').resolve():
        receipt_path = PROJECT_ROOT / 'docs' / 'sql-migration-cutover.json'
    receipt = _read_json(receipt_path, {})
    archive_name = str(receipt.get('archive') or '').strip()
    if not archive_name:
        return None
    archive_path = (user_data_dir / archive_name).resolve()
    if user_data_dir not in archive_path.parents:
        raise ValueError('Configured cutover archive escapes the user-data directory')
    expected_hash = str(receipt.get('sha256') or '').strip().lower()
    actual_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError('Configured cutover archive does not match its immutable receipt')
    return archive_path


def _legacy_canonical(record, key, snapshot, store):
    plex_data = snapshot['plex_files'].get(key, {})
    tmdb_data = snapshot['tmdb_movies'].get(str(record.get('tmdb_id') or ''), {})
    canonical = app._build_canonical_metadata(
        record,
        plex_data=plex_data,
        tmdb_data=tmdb_data,
        manual_match=snapshot['manual_matches'].get(key, {}),
        display_provider=record.get('display_provider', ''),
        file_record=record,
    )
    identity = app._poster_identity_for_movie(record, canonical, plex_data)
    canonical = app._apply_metadata_override(canonical, identity, store=store, snapshot=snapshot)
    return app._apply_poster_override(canonical, identity, store=store, snapshot=snapshot)


def _normal(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _canonical_value(field, value):
    if value in (None, '', [], {}):
        return None
    if field in {'cast', 'directors', 'writers'}:
        return [
            {
                'id': str(person.get('id', '') or '').strip(),
                'name': str(person.get('name', '') or '').strip(),
                'profile_url': str(person.get('profile_url', '') or '').strip(),
                **({'character': str(person.get('character', '') or '').strip()} if field == 'cast' else {}),
                **({'job': str(person.get('job', '') or '').strip()} if field == 'writers' else {}),
            }
            for person in (value or [])
            if isinstance(person, dict)
        ]
    return _normal(value)


def _canonical_projection(canonical):
    return {field: _canonical_value(field, canonical.get(field)) for field in CANONICAL_FIELDS}


def _add(violations, name, row, limit):
    if len(violations[name]) < limit:
        violations[name].append(row)


def _sql_counts(store):
    connection = store.catalog.store.connect()
    try:
        return {
            'files': int(connection.execute('SELECT COUNT(*) FROM media_files').fetchone()[0]),
            'tmdb_movies': int(connection.execute('SELECT COUNT(*) FROM tmdb_movies').fetchone()[0]),
            'plex_files': int(connection.execute('SELECT COUNT(*) FROM plex_files').fetchone()[0]),
            'manual_matches': int(connection.execute('SELECT COUNT(*) FROM manual_matches').fetchone()[0]),
        }
    finally:
        connection.close()


def _updated_at(record):
    try:
        return float((record or {}).get('updated_at') or 0)
    except (TypeError, ValueError):
        return 0


def _changed_source_records(key, record, cutover, current_documents, cutover_at):
    tmdb_id = str(record.get('tmdb_id') or cutover['files'].get(key, {}).get('tmdb_id') or '')
    candidates = [
        ('files', key),
        ('plex_files', key),
        ('manual_matches', key),
    ]
    if tmdb_id:
        candidates.append(('tmdb_movies', tmdb_id))
    evidence = []
    for name, source_key in candidates:
        before = cutover[name].get(source_key)
        after = current_documents[name].get(source_key)
        if after is None or _normal(before) == _normal(after):
            continue
        updated_at = _updated_at(after)
        if updated_at > cutover_at:
            evidence.append({
                'record_type': name,
                'key': source_key,
                'updated_at': updated_at,
                'change': 'created' if before is None else 'updated',
            })
    return evidence


def compare_json_shadow(user_data_dir, max_errors=100, cutover_archive=None):
    """Compare literal legacy JSON canonical behavior with the active SQL catalog."""
    user_data_dir = Path(user_data_dir)
    store = app.AppMetadataStore(user_data_dir)
    legacy = _legacy_snapshot(user_data_dir)
    cutover_archive = Path(cutover_archive).resolve() if cutover_archive else _configured_cutover_archive(user_data_dir)
    cutover = None
    cutover_manifest = None
    cutover_at = 0
    if cutover_archive:
        cutover, cutover_manifest, cutover_at = _cutover_snapshot(cutover_archive)
    sql_by_key = {
        str(candidate.get('path_key') or ''): candidate
        for candidate in store.catalog.store.audit_library_candidates()
    }
    connection = store.catalog.store.connect()
    try:
        relational_by_key = store.catalog.store.canonical.project_paths(
            connection,
            list(sql_by_key),
            include_details=True,
        )
    finally:
        connection.close()
    legacy_by_key = {
        app._norm(str(record.get('path') or key)): dict(record or {})
        for key, record in legacy['files'].items()
        if isinstance(record, dict)
    }
    cutover_by_key = {
        app._norm(str(record.get('path') or key)): dict(record or {})
        for key, record in (cutover or {}).get('files', {}).items()
        if isinstance(record, dict)
    }
    files_json = user_data_dir / 'app_metadata' / 'files.json'
    legacy_snapshot_at = files_json.stat().st_mtime if files_json.is_file() else 0
    sql_documents = {
        name: store.catalog.read_document(document, fallback).get(key, {})
        for name, (document, fallback, key) in DOCUMENTS.items()
    }
    violations = {
        'legacy_only': [],
        'sql_only': [],
        'canonical': [],
        'document_legacy_only': [],
        'document_sql_only': [],
        'document_changed': [],
    }
    post_snapshot_sql_only = []
    post_snapshot_document_changes = []
    post_cutover_deletions = []
    post_cutover_canonical_changes = []
    post_snapshot_record_counts = {name: 0 for name in DOCUMENTS}

    with patch('app.urllib.request.urlopen', side_effect=AssertionError('JSON shadow comparison must not call providers')):
        for key, record in legacy_by_key.items():
            candidate = sql_by_key.get(key)
            path = str(record.get('path') or key)
            if not candidate:
                cutover_record = cutover_by_key.get(key)
                if cutover_record and not Path(path).exists():
                    row = {
                        'path': path,
                        'message': 'Record existed in the verified SQL cutover and the file was deleted afterward',
                    }
                    if len(post_cutover_deletions) < max_errors:
                        post_cutover_deletions.append(row)
                    continue
                _add(violations, 'legacy_only', {'path': path, 'message': 'Legacy JSON file record is missing from SQL'}, max_errors)
                continue
            legacy_canonical = _legacy_canonical(record, key, legacy, store)
            sql_canonical = relational_by_key.get(key) or {}
            left = _canonical_projection(legacy_canonical)
            right = _canonical_projection(sql_canonical)
            differences = {
                field: {'legacy_json': left[field], 'sql': right[field]}
                for field in CANONICAL_FIELDS
                if left[field] != right[field]
            }
            if differences:
                cutover_record = cutover_by_key.get(key)
                cutover_projection = None
                cutover_differences = None
                change_evidence = []
                if cutover_record:
                    cutover_projection = _canonical_projection(_legacy_canonical(cutover_record, key, cutover, store))
                    cutover_differences = {
                        field: {'legacy_json': left[field], 'cutover_sql': cutover_projection[field]}
                        for field in CANONICAL_FIELDS
                        if left[field] != cutover_projection[field]
                    }
                    change_evidence = _changed_source_records(key, candidate.get('raw_json') or record, cutover, sql_documents, cutover_at)
                if cutover_record and not cutover_differences and change_evidence:
                    row = {
                        'path': path,
                        'message': 'Canonical behavior matched at the verified SQL cutover and changed with persisted source data afterward',
                        'differences': differences,
                        'evidence': change_evidence,
                    }
                    if len(post_cutover_canonical_changes) < max_errors:
                        post_cutover_canonical_changes.append(row)
                else:
                    row = {'path': path, 'differences': differences}
                    if cutover_differences:
                        row['cutover_differences'] = cutover_differences
                    _add(violations, 'canonical', row, max_errors)

        for key, candidate in sql_by_key.items():
            if key not in legacy_by_key:
                raw = candidate.get('raw_json') or {}
                updated_at = float(raw.get('updated_at') or candidate.get('updated_at') or 0)
                row = {
                    'path': str(candidate.get('path') or key),
                    'updated_at': updated_at,
                }
                if updated_at > legacy_snapshot_at:
                    row['message'] = 'SQL file record was created after the legacy JSON snapshot'
                    if len(post_snapshot_sql_only) < max_errors:
                        post_snapshot_sql_only.append(row)
                else:
                    row['message'] = 'SQL file record has no legacy JSON counterpart'
                    _add(violations, 'sql_only', row, max_errors)

        for name, (_, _, key_name) in DOCUMENTS.items():
            legacy_records = legacy[name]
            sql_records = sql_documents[name]
            cutover_records = (cutover or {}).get(name, {})
            for key, legacy_record in legacy_records.items():
                sql_record = sql_records.get(key)
                if sql_record is None:
                    if key in cutover_records:
                        row = {
                            'record_type': name,
                            'key': key,
                            'message': 'Record existed in the verified SQL cutover and was deleted afterward',
                        }
                        post_snapshot_record_counts[name] -= 1
                        if len(post_snapshot_document_changes) < max_errors:
                            post_snapshot_document_changes.append(row)
                        continue
                    _add(violations, 'document_legacy_only', {
                        'record_type': name,
                        'key': key,
                        'message': 'Legacy JSON record is missing from SQL',
                    }, max_errors)
                    continue
                if _normal(legacy_record) == _normal(sql_record):
                    continue
                row = {'record_type': name, 'key': key, 'message': 'Legacy JSON record differs from SQL'}
                cutover_record = cutover_records.get(key)
                changed_after_cutover = (
                    cutover_record is not None
                    and _normal(cutover_record) != _normal(sql_record)
                    and _updated_at(sql_record) > cutover_at
                )
                if changed_after_cutover:
                    row['message'] = 'SQL record matched at cutover and changed afterward'
                    if len(post_snapshot_document_changes) < max_errors:
                        post_snapshot_document_changes.append(row)
                elif (
                    cutover_record is not None
                    and _normal(cutover_record) == _normal(sql_record)
                    and _updated_at(cutover_record) > legacy_snapshot_at
                ):
                    row['message'] = 'SQL record changed after the legacy JSON snapshot and before the verified cutover'
                    if len(post_snapshot_document_changes) < max_errors:
                        post_snapshot_document_changes.append(row)
                elif _updated_at(sql_record) > legacy_snapshot_at and not cutover:
                    row['message'] = 'SQL record changed after the legacy JSON snapshot'
                    if len(post_snapshot_document_changes) < max_errors:
                        post_snapshot_document_changes.append(row)
                else:
                    _add(violations, 'document_changed', row, max_errors)
            for key, sql_record in sql_records.items():
                if key in legacy_records:
                    continue
                row = {'record_type': name, 'key': key, 'message': 'SQL record has no legacy JSON counterpart'}
                if _updated_at(sql_record) > legacy_snapshot_at:
                    row['message'] = 'SQL record was created after the legacy JSON snapshot'
                    post_snapshot_record_counts[name] += 1
                    if len(post_snapshot_document_changes) < max_errors:
                        post_snapshot_document_changes.append(row)
                else:
                    _add(violations, 'document_sql_only', row, max_errors)

    legacy_counts = {
        'files': len(legacy['files']),
        'tmdb_movies': len(legacy['tmdb_movies']),
        'plex_files': len(legacy['plex_files']),
        'manual_matches': len(legacy['manual_matches']),
    }
    sql_counts = _sql_counts(store)
    expected_sql_counts = {
        field: legacy_counts[field] + post_snapshot_record_counts[field]
        for field in legacy_counts
    }
    count_differences = {
        field: {'legacy_json': legacy_counts[field], 'expected_sql': expected_sql_counts[field], 'sql': sql_counts[field]}
        for field in legacy_counts
        if expected_sql_counts[field] != sql_counts[field]
    }
    violation_count = sum(len(rows) for rows in violations.values())
    return {
        'source': 'literal_legacy_json',
        'current_source': 'catalog',
        'database': str(store.catalog.database_path),
        'cutover_archive': str(cutover_archive) if cutover_archive else '',
        'cutover_created_at': cutover_manifest.get('created_at') if cutover_manifest else '',
        'catalog_generation': store.catalog.generation('media'),
        'legacy_snapshot_modified_at': legacy_snapshot_at,
        'checked_records': len(legacy_by_key),
        'provider_calls': 0,
        'record_counts': {
            'legacy_json': legacy_counts,
            'expected_sql': expected_sql_counts,
            'sql': sql_counts,
            'differences': count_differences,
        },
        'post_snapshot_sql_only': post_snapshot_sql_only,
        'post_snapshot_document_changes': post_snapshot_document_changes,
        'post_cutover_deletions': post_cutover_deletions,
        'post_cutover_canonical_changes': post_cutover_canonical_changes,
        'passed': not count_differences and violation_count == 0,
        'violations': violations,
    }


def main():
    parser = argparse.ArgumentParser(description='Compare literal legacy JSON behavior with the active SQL catalog.')
    parser.add_argument('--user-data-dir', default=PROJECT_ROOT / 'data')
    parser.add_argument('--max-errors', type=int, default=100)
    parser.add_argument('--cutover-archive')
    args = parser.parse_args()
    report = compare_json_shadow(
        args.user_data_dir,
        max_errors=max(1, args.max_errors),
        cutover_archive=args.cutover_archive,
    )
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
