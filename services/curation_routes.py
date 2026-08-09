from copy import deepcopy

from flask import jsonify, request


_CANONICAL_IDENTITY_FIELDS = (
    'movie_key', 'tmdb_id', 'imdb_id', 'plex_guid',
    'title', 'year', 'path', 'poster_url',
)


def merge_owned_curation_identity(movie, owned):
    merged = dict(movie or {})
    for field in _CANONICAL_IDENTITY_FIELDS:
        value = (owned or {}).get(field)
        if value not in (None, ''):
            merged[field] = str(value)
    return merged


def project_owned_list_identities(lists, owned_matches):
    projected = deepcopy(list(lists or []))
    movies = [movie for item in projected for movie in item.get('movies', [])]
    for movie, owned in zip(movies, owned_matches or []):
        if owned:
            movie.update(merge_owned_curation_identity(movie, owned))
    return projected


def register_curation_routes(
    app,
    store_provider,
    owned_checker,
    owned_resolver=None,
    owned_bulk_resolver=None,
):
    def resolve_owned(movie):
        return owned_resolver(movie) if owned_resolver else None

    def resolve_owned_many(movies):
        movies = list(movies or [])
        if owned_bulk_resolver:
            return list(owned_bulk_resolver(movies) or [])
        return [resolve_owned(movie) for movie in movies]

    def projected_lists(store):
        lists = store.list_all()
        movies = [movie for item in lists for movie in item.get('movies', [])]
        return project_owned_list_identities(lists, resolve_owned_many(movies))

    def curation_payload(payload, store=None):
        store = store or store_provider()
        return {
            **dict(payload or {}),
            'curation_generation': store.catalog.generation('curation'),
        }

    def user_lists():
        store = store_provider()
        if request.method == 'GET':
            movie = {
                'movie_key': request.args.get('movie_key', ''),
                'tmdb_id': request.args.get('tmdb_id', ''),
                'imdb_id': request.args.get('imdb_id', ''),
                'plex_guid': request.args.get('plex_guid', ''),
                'title': request.args.get('title', ''),
                'year': request.args.get('year', ''),
                'path': request.args.get('path', ''),
            }
            movie = merge_owned_curation_identity(movie, resolve_owned(movie))
            result = {'lists': projected_lists(store)}
            if any(movie.values()):
                result['movie_lists'] = store.lists_for_movie(movie)
            return jsonify(curation_payload(result, store))
        body = request.get_json(force=True, silent=True) or {}
        try:
            return jsonify(curation_payload(store.create_list(body.get('name', '')), store))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        except Exception as error:
            return jsonify({'error': str(error)}), 500

    def user_list_detail(list_id):
        store = store_provider()
        try:
            if request.method == 'DELETE':
                deleted = store.delete_list(list_id)
                return jsonify(curation_payload({'success': True, 'deleted': deleted}, store))
            body = request.get_json(force=True, silent=True) or {}
            return jsonify(curation_payload(store.rename_list(list_id, body.get('name', '')), store))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400
        except KeyError:
            return jsonify({'error': 'List not found'}), 404
        except Exception as error:
            return jsonify({'error': str(error)}), 500

    def user_list_movies(list_id):
        store = store_provider()
        body = request.get_json(force=True, silent=True) or {}
        movie = body.get('movie') or body
        try:
            owned = resolve_owned(movie)
            canonical_movie = merge_owned_curation_identity(movie, owned)
            if request.method == 'POST':
                if list_id == 'watched' and not owned_checker(movie):
                    return jsonify({'error': 'Watched is available only for owned Library movies'}), 400
                return jsonify(curation_payload(store.add_movie_to_list(list_id, canonical_movie), store))
            return jsonify(curation_payload(store.remove_movie_from_list(list_id, canonical_movie), store))
        except KeyError:
            return jsonify({'error': 'List not found'}), 404
        except Exception as error:
            return jsonify({'error': str(error)}), 500

    def user_list_movies_bulk(list_id):
        store = store_provider()
        body = request.get_json(force=True, silent=True) or {}
        movies = body.get('movies') or []
        if not isinstance(movies, list) or not movies:
            return jsonify({'error': 'At least one movie is required'}), 400
        try:
            owned_matches = resolve_owned_many(movies)
            canonical_movies = [
                merge_owned_curation_identity(movie, owned)
                for movie, owned in zip(movies, owned_matches)
            ]
            if list_id == 'watched':
                unowned = [movie for movie in movies if not owned_checker(movie)]
                if unowned:
                    return jsonify({'error': 'Watched is available only for owned Library movies'}), 400
            return jsonify(curation_payload(store.add_movies_to_list(list_id, canonical_movies), store))
        except KeyError:
            return jsonify({'error': 'List not found'}), 404
        except Exception as error:
            return jsonify({'error': str(error)}), 500

    def user_system_list_state():
        store = store_provider()
        movie = {
            'movie_key': request.args.get('movie_key', ''),
            'tmdb_id': request.args.get('tmdb_id', ''),
            'imdb_id': request.args.get('imdb_id', ''),
            'plex_guid': request.args.get('plex_guid', ''),
            'title': request.args.get('title', ''),
            'year': request.args.get('year', ''),
            'path': request.args.get('path', ''),
        }
        movie = merge_owned_curation_identity(movie, resolve_owned(movie))
        return jsonify(curation_payload(store.system_states_for_movie(movie), store))

    def user_system_list_toggle(system_type):
        if system_type not in {'watched', 'watchlist'}:
            return jsonify({'error': 'System list not found'}), 404
        body = request.get_json(force=True, silent=True) or {}
        movie = body.get('movie') or {}
        if not any(movie.get(key) for key in ('tmdb_id', 'imdb_id', 'title', 'path')):
            return jsonify({'error': 'Movie identity is required'}), 400
        if system_type == 'watched' and bool(body.get('active')) and not owned_checker(movie):
            return jsonify({'error': 'Watched is available only for owned Library movies'}), 400
        try:
            store = store_provider()
            canonical_movie = merge_owned_curation_identity(movie, resolve_owned(movie))
            result = store.set_system_list_state(system_type, canonical_movie, bool(body.get('active')))
            return jsonify(curation_payload(result, store))
        except KeyError:
            return jsonify({'error': 'System list not found'}), 404
        except Exception as error:
            return jsonify({'error': str(error)}), 500

    app.add_url_rule('/api/user/lists', 'user_lists', user_lists, methods=['GET', 'POST'])
    app.add_url_rule('/api/user/lists/<list_id>', 'user_list_detail', user_list_detail, methods=['PATCH', 'DELETE'])
    app.add_url_rule(
        '/api/user/lists/<list_id>/movies',
        'user_list_movies',
        user_list_movies,
        methods=['POST', 'DELETE'],
    )
    app.add_url_rule(
        '/api/user/lists/<list_id>/movies/bulk',
        'user_list_movies_bulk',
        user_list_movies_bulk,
        methods=['POST'],
    )
    app.add_url_rule('/api/user/system-lists/state', 'user_system_list_state', user_system_list_state)
    app.add_url_rule(
        '/api/user/system-lists/<system_type>/toggle',
        'user_system_list_toggle',
        user_system_list_toggle,
        methods=['POST'],
    )
