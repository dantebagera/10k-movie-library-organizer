import os
import re
import time
from pathlib import Path

from services.catalog_repository import CatalogRepository
from services.movie_identity import normalize_movie_title


def normalize_curated_movie(movie):
    movie = movie or {}
    return {
        'movie_key': str(movie.get('movie_key', '') or ''),
        'tmdb_id': str(movie.get('tmdb_id', '') or ''),
        'imdb_id': str(movie.get('imdb_id', '') or ''),
        'plex_guid': str(movie.get('plex_guid', '') or ''),
        'title': str(movie.get('title', '') or ''),
        'year': str(movie.get('year', '') or ''),
        'path': str(movie.get('path', '') or ''),
        'poster_url': str(movie.get('poster_url', '') or ''),
        'release_date': str(movie.get('release_date', '') or ''),
    }


def curated_movies_share_identity(left, right):
    left = normalize_curated_movie(left)
    right = normalize_curated_movie(right)
    left_path = left.get('path', '')
    right_path = right.get('path', '')
    if left_path and right_path and os.path.normcase(os.path.normpath(left_path)) == os.path.normcase(os.path.normpath(right_path)):
        return True
    left_movie_key = left.get('movie_key', '')
    right_movie_key = right.get('movie_key', '')
    if left_movie_key and right_movie_key:
        return left_movie_key == right_movie_key
    left_tmdb = left.get('tmdb_id')
    right_tmdb = right.get('tmdb_id')
    if left_tmdb and right_tmdb and left_tmdb != right_tmdb:
        return False
    left_imdb = left.get('imdb_id', '').lower()
    right_imdb = right.get('imdb_id', '').lower()
    if left_imdb and right_imdb and left_imdb != right_imdb:
        return False
    left_plex = left.get('plex_guid', '').lower()
    right_plex = right.get('plex_guid', '').lower()
    if left_plex and right_plex and left_plex != right_plex:
        return False
    if left_tmdb and right_tmdb and left_tmdb == right_tmdb:
        return True
    if left_imdb and right_imdb and left_imdb == right_imdb:
        return True
    if left_plex and right_plex and left_plex == right_plex:
        return True
    left_title = normalize_movie_title(left.get('title', ''))
    right_title = normalize_movie_title(right.get('title', ''))
    return bool(
        left_title
        and left_title == right_title
        and str(left.get('year') or '') == str(right.get('year') or '')
    )


def _movie_identity_key(movie):
    movie_key = str(movie.get('movie_key', '') or '').strip()
    if movie_key:
        return movie_key
    tmdb_id = str(movie.get('tmdb_id', '') or '').strip()
    if tmdb_id:
        return f"tmdb:{tmdb_id}"
    imdb_id = str(movie.get('imdb_id', '') or '').strip()
    if imdb_id:
        return f"imdb:{imdb_id.lower()}"
    path = str(movie.get('path', '') or '').strip()
    if path:
        return f"path:{os.path.normcase(os.path.normpath(path))}"
    title = re.sub(r'\s+', ' ', str(movie.get('title', '') or '').lower()).strip()
    year = str(movie.get('year', '') or '').strip()
    return f"title:{title}|{year}"


class UserCurationStore:
    SYSTEM_LISTS = (
        {'id': 'watched', 'name': 'Watched', 'system_type': 'watched'},
        {'id': 'watchlist', 'name': 'Watchlist', 'system_type': 'watchlist'},
    )

    def __init__(self, base_dir, catalog=None):
        self.base_dir = Path(base_dir).resolve()
        self.collections_file = self.base_dir / 'user_collections.json'
        self.lists_file = self.base_dir / 'user_lists.json'
        self.followed_file = self.base_dir / 'followed_releases.json'
        if catalog is None:
            catalog = CatalogRepository(
                self.base_dir,
                database_path=self.base_dir / '.catalog-test.sqlite',
                export_delay=0,
            )
            catalog.activate_from_json()
        self.catalog = catalog

    def _document_name(self, path):
        return Path(path).resolve().relative_to(self.base_dir).as_posix()

    def _read_json(self, path, fallback):
        return self.catalog.read_document(self._document_name(path), fallback)

    def _write_json(self, path, data):
        self.catalog.replace_document(self._document_name(path), data)
        self.catalog.flush_exports()

    def _collections(self):
        data = self._read_json(self.collections_file, {'overrides': {}})
        data.setdefault('overrides', {})
        return data

    def _save_collections(self, data):
        self._write_json(self.collections_file, data)

    def _lists(self):
        data = self._read_json(self.lists_file, {'lists': []})
        data.setdefault('lists', [])
        existing = {item.get('id'): item for item in data['lists']}
        persisted_changed = False
        system_lists = []
        for definition in self.SYSTEM_LISTS:
            current = existing.get(definition['id'])
            if current is None:
                current = {
                    **definition,
                    'movies': [],
                    'created_at': time.time(),
                    'updated_at': time.time(),
                }
                data['lists'].append(current)
                persisted_changed = True
            else:
                for key, value in definition.items():
                    if current.get(key) != value:
                        current[key] = value
                        persisted_changed = True
                if 'movies' not in current:
                    current['movies'] = []
                    persisted_changed = True
            system_lists.append(current)
        system_ids = {definition['id'] for definition in self.SYSTEM_LISTS}
        custom_lists = [item for item in data['lists'] if item.get('id') not in system_ids]
        if persisted_changed:
            self._save_lists(data)
        return {**data, 'lists': [*system_lists, *custom_lists]}

    def _save_lists(self, data):
        self._write_json(self.lists_file, data)

    def _followed(self):
        data = self._read_json(self.followed_file, {'movies': []})
        data.setdefault('movies', [])
        return data

    def _save_followed(self, data):
        self._write_json(self.followed_file, data)

    def effective_collection(self, tmdb_collection):
        collection_id = str(tmdb_collection.get('id', '') or '')
        override = self._collections().get('overrides', {}).get(collection_id)
        if override:
            return {**tmdb_collection, **override, 'id': collection_id, 'source': 'User', 'is_edited': True}
        return {**tmdb_collection, 'source': 'TMDB', 'is_edited': False}

    def save_collection_override(self, collection_id, original_collection, parts):
        collection_id = str(collection_id)
        data = self._collections()
        override = {
            'id': collection_id,
            'name': original_collection.get('name', ''),
            'parts': [normalize_curated_movie(movie) for movie in parts],
            'updated_at': time.time(),
        }
        data['overrides'][collection_id] = override
        self._save_collections(data)
        return {**override, 'source': 'User', 'is_edited': True}

    def reset_collection(self, collection_id):
        data = self._collections()
        existed = str(collection_id) in data['overrides']
        data['overrides'].pop(str(collection_id), None)
        self._save_collections(data)
        return existed

    def list_all(self):
        return self._lists()['lists']

    def create_list(self, name, movies=None):
        data = self._lists()
        clean_name = re.sub(r'\s+', ' ', str(name or '').strip())
        if not clean_name:
            raise ValueError('List name is required')
        list_id = re.sub(r'[^a-z0-9]+', '-', clean_name.lower()).strip('-') or f"list-{int(time.time())}"
        existing_ids = {item.get('id') for item in data['lists']}
        base_id = list_id
        suffix = 2
        while list_id in existing_ids:
            list_id = f"{base_id}-{suffix}"
            suffix += 1
        created = {
            'id': list_id,
            'name': clean_name,
            'movies': [],
            'created_at': time.time(),
            'updated_at': time.time(),
        }
        self._add_movies_to_target(created, movies or [])
        data['lists'].append(created)
        self._save_lists(data)
        return created

    def rename_list(self, list_id, name):
        data = self._lists()
        target = self._find_list(data, list_id)
        if target is None:
            raise KeyError('List not found')
        if target.get('system_type'):
            raise ValueError('System lists cannot be renamed')
        clean_name = re.sub(r'\s+', ' ', str(name or '').strip())
        if not clean_name:
            raise ValueError('List name is required')
        target['name'] = clean_name
        target['updated_at'] = time.time()
        self._save_lists(data)
        return target

    def delete_list(self, list_id):
        data = self._lists()
        target = self._find_list(data, list_id)
        if target and target.get('system_type'):
            raise ValueError('System lists cannot be deleted')
        before = len(data['lists'])
        data['lists'] = [item for item in data['lists'] if item.get('id') != list_id]
        self._save_lists(data)
        return len(data['lists']) != before

    @staticmethod
    def _find_list(data, list_id):
        return next((item for item in data['lists'] if item.get('id') == list_id), None)

    def add_movie_to_list(self, list_id, movie):
        return self.add_movies_to_list(list_id, [movie])

    def add_movies_to_list(self, list_id, movies):
        data = self._lists()
        target = self._find_list(data, list_id)
        if target is None:
            raise KeyError('List not found')
        self._add_movies_to_target(target, movies)
        self._save_lists(data)
        return target

    @staticmethod
    def _add_movies_to_target(target, movies):
        existing = target.setdefault('movies', [])
        for movie in movies or []:
            normalized = normalize_curated_movie(movie or {})
            if not any(normalized.get(key) for key in ('movie_key', 'tmdb_id', 'imdb_id', 'plex_guid', 'title', 'path')):
                continue
            matched = next((
                current for current in existing
                if curated_movies_share_identity(current, normalized)
            ), None)
            if matched is not None:
                for key, value in normalized.items():
                    if value:
                        matched[key] = value
                continue
            if target.get('system_type') == 'watched':
                normalized['watched_at'] = time.time()
            elif target.get('system_type') == 'watchlist':
                normalized['added_at'] = time.time()
            existing.append(normalized)
        target['updated_at'] = time.time()

    def remove_movie_from_list(self, list_id, movie):
        data = self._lists()
        target = self._find_list(data, list_id)
        if target is None:
            raise KeyError('List not found')
        normalized = normalize_curated_movie(movie)
        target['movies'] = [
            existing for existing in target.get('movies', [])
            if not curated_movies_share_identity(existing, normalized)
        ]
        target['updated_at'] = time.time()
        self._save_lists(data)
        return target

    def lists_for_movie(self, movie):
        result = []
        for item in self._lists()['lists']:
            if any(curated_movies_share_identity(existing, movie) for existing in item.get('movies', [])):
                result.append({
                    'id': item.get('id'),
                    'name': item.get('name'),
                    'system_type': item.get('system_type', ''),
                })
        return result

    def system_states_for_movie(self, movie):
        states = {'watched': False, 'watchlist': False}
        for item in self._lists()['lists']:
            system_type = item.get('system_type')
            if system_type not in states:
                continue
            states[system_type] = any(
                curated_movies_share_identity(existing, movie)
                for existing in item.get('movies', [])
            )
        return states

    def set_system_list_state(self, system_type, movie, active):
        if system_type not in {'watched', 'watchlist'}:
            raise KeyError('System list not found')
        if active:
            target = self.add_movie_to_list(system_type, movie)
        else:
            target = self.remove_movie_from_list(system_type, movie)
        return {
            'active': bool(active),
            'system_type': system_type,
            'list': target,
            'states': self.system_states_for_movie(movie),
        }

    def followed_all(self):
        return self._followed()['movies']

    def follow_movie(self, movie):
        data = self._followed()
        normalized = normalize_curated_movie(movie)
        key = _movie_identity_key(normalized)
        now = time.time()
        existing = next((item for item in data['movies'] if _movie_identity_key(item) == key), None)
        if existing:
            existing.update({key: value for key, value in normalized.items() if value})
            existing['updated_at'] = now
            self._save_followed(data)
            return existing
        created = {
            **normalized,
            'status': 'watching',
            'followed_at': now,
            'updated_at': now,
            'last_checked': 0,
            'best_release': {},
        }
        data['movies'].insert(0, created)
        self._save_followed(data)
        return created

    def unfollow_movie(self, movie):
        data = self._followed()
        key = _movie_identity_key(normalize_curated_movie(movie))
        before = len(data['movies'])
        data['movies'] = [item for item in data['movies'] if _movie_identity_key(item) != key]
        self._save_followed(data)
        return len(data['movies']) != before

    def save_followed_all(self, movies):
        data = {'movies': movies}
        self._save_followed(data)
        return movies
