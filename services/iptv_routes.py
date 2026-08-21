from flask import Response, jsonify, request, send_file, stream_with_context

from .iptv_tmdb import IPTVTMDBClient, IPTVTMDBError
from .iptv_xtream import XtreamError


def _iter_upstream_chunks(upstream, chunk_size=64 * 1024):
    reader = getattr(upstream, "read1", None) or upstream.read
    try:
        while True:
            chunk = reader(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        upstream.close()


def register_iptv_routes(app, manager_provider):
    def current_manager():
        return manager_provider() if callable(manager_provider) else manager_provider

    def service(provider_id):
        return current_manager().service(provider_id)

    def movie_service(provider_id):
        return current_manager().movie_service(provider_id)

    def error_response(error, provider_id="", status=400):
        if isinstance(error, KeyError):
            status = 404
        message = current_manager().redacted_error(error, provider_id).strip("'")
        return jsonify({"error": message}), status

    @app.get("/api/iptv/providers")
    def iptv_providers():
        try:
            return jsonify(current_manager().list_providers())
        except RuntimeError as error:
            return error_response(error, status=500)

    @app.route("/api/iptv/metadata/settings", methods=["GET", "PATCH"])
    def iptv_metadata_settings():
        manager = current_manager()
        try:
            if request.method == "GET":
                return jsonify(manager.metadata_settings.public())
            data = request.get_json(silent=True) or {}
            if "ollama" in data:
                ollama = data.get("ollama") if isinstance(data.get("ollama"), dict) else {}
                return jsonify(manager.metadata_settings.save_ollama(
                    enabled=bool(ollama.get("enabled")),
                    url=ollama.get("url", ""),
                    model=ollama.get("model", ""),
                ))
            return jsonify(manager.metadata_settings.save(
                data.get("credential", ""),
                data.get("credential_type"),
                clear=bool(data.get("clear")),
            ))
        except (ValueError, RuntimeError) as error:
            return error_response(error)

    @app.post("/api/iptv/metadata/test")
    def iptv_metadata_test():
        manager = current_manager()
        try:
            configured = IPTVTMDBClient(manager.metadata_settings).validate()
            return jsonify({"tmdb_configured": bool(configured), "valid": bool(configured)})
        except (ValueError, RuntimeError, IPTVTMDBError) as error:
            return error_response(error)

    @app.post("/api/iptv/providers")
    def iptv_provider_create():
        data = request.get_json(silent=True) or {}
        try:
            provider = current_manager().create_provider(
                data.get("name"),
                data.get("server_url"),
                data.get("username"),
                data.get("password"),
                data.get("allow_insecure_tls", False),
            )
            return jsonify(provider), 201
        except (ValueError, RuntimeError) as error:
            return error_response(error)

    @app.route("/api/iptv/providers/<provider_id>", methods=["GET", "PATCH", "DELETE"])
    def iptv_provider_detail(provider_id):
        manager = current_manager()
        try:
            if request.method == "GET":
                return jsonify(manager.get_provider(provider_id))
            data = request.get_json(silent=True) or {}
            if request.method == "DELETE":
                return jsonify(manager.remove_provider(provider_id, data.get("confirm_name")))
            return jsonify(manager.update_provider(
                provider_id,
                name=data.get("name"),
                server_url=data.get("server_url"),
                username=data.get("username"),
                password=data.get("password"),
                allow_insecure_tls=data.get("allow_insecure_tls"),
            ))
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/selection")
    def iptv_provider_selection():
        data = request.get_json(silent=True) or {}
        try:
            return jsonify(current_manager().set_selection(data.get("provider_id")))
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, str(data.get("provider_id") or ""))

    @app.post("/api/iptv/providers/<provider_id>/test")
    def iptv_provider_test(provider_id):
        try:
            return jsonify(current_manager().test_provider(provider_id))
        except (KeyError, ValueError, RuntimeError, XtreamError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/sync")
    def iptv_provider_sync(provider_id):
        try:
            return jsonify(current_manager().start_sync(provider_id))
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/status")
    def iptv_provider_status(provider_id):
        try:
            return jsonify(current_manager().get_provider(provider_id))
        except (KeyError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/categories")
    def iptv_categories(provider_id):
        try:
            return jsonify({"items": service(provider_id).store.categories(request.args.get("kind", "live"))})
        except (KeyError, ValueError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/items")
    def iptv_items(provider_id):
        try:
            return jsonify(service(provider_id).list_items(
                request.args.get("kind", "live"),
                category_id=request.args.get("category_id", ""),
                query=request.args.get("q", ""),
                page=request.args.get("page", 1),
                page_size=request.args.get("page_size", 30),
                favorites_only=request.args.get("favorites", "").lower() in {"1", "true", "yes"},
            ))
        except (KeyError, TypeError, ValueError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies")
    def iptv_movies(provider_id):
        try:
            filters = {
                "view": request.args.get("view", "provider"),
                "category": request.args.get("category", ""),
                "q": request.args.get("q", ""),
                "playlist_id": request.args.get("playlist_id", ""),
                "list_id": request.args.get("list_id", ""),
                "genre_id": request.args.get("genre_id", ""),
                "language": request.args.get("language", ""),
                "country": request.args.get("country", ""),
                "year_from": request.args.get("year_from", ""),
                "year_to": request.args.get("year_to", ""),
                "min_rating": request.args.get("min_rating", ""),
                "metadata_status": request.args.get("metadata_status", ""),
                "quality": request.args.get("quality", ""),
                "dubbed": request.args.get("dubbed", ""),
                "subtitled": request.args.get("subtitled", ""),
                "watched": request.args.get("watched", ""),
                "sort": request.args.get("sort", "recent"),
            }
            return jsonify(movie_service(provider_id).list_movies(
                filters, page=request.args.get("page", 1), page_size=request.args.get("page_size", 30)
            ))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/facets")
    def iptv_movie_facets(provider_id):
        try:
            return jsonify(movie_service(provider_id).facets())
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/projection/status")
    def iptv_movie_projection_status(provider_id):
        try:
            return jsonify(movie_service(provider_id).projection_status())
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/projection/retry")
    def iptv_movie_projection_retry(provider_id):
        try:
            return jsonify(movie_service(provider_id).retry_projection())
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/status")
    def iptv_movie_status(provider_id):
        try:
            return jsonify(movie_service(provider_id).enrichment_status())
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/metadata/status")
    def iptv_movie_metadata_status(provider_id):
        try:
            return jsonify(movie_service(provider_id).metadata_status(
                control_only=request.args.get("control_only", "").strip().lower() in {"1", "true", "yes"}
            ))
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/metadata/review")
    def iptv_movie_metadata_review(provider_id):
        try:
            return jsonify(movie_service(provider_id).metadata_review(
                request.args.get("view", "needs-review"),
                request.args.get("page", 1), request.args.get("page_size", 50),
                filters={
                    "q": request.args.get("q", ""),
                    "category": request.args.get("category", ""),
                    "playlist_id": request.args.get("playlist_id", ""),
                },
            ))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/classification/preview")
    def iptv_movie_classification_preview(provider_id):
        try:
            return jsonify(movie_service(provider_id).classification_preview(request.get_json(silent=True) or {}))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/classification/apply")
    def iptv_movie_classification_apply(provider_id):
        try:
            return jsonify(movie_service(provider_id).classification_apply(request.get_json(silent=True) or {}))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/match-jobs")
    def iptv_movie_match_jobs(provider_id):
        try:
            return jsonify(movie_service(provider_id).create_match_job(request.get_json(silent=True) or {}))
        except (KeyError, TypeError, ValueError, RuntimeError, IPTVTMDBError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/match-jobs/<job_id>")
    def iptv_movie_match_job(provider_id, job_id):
        try:
            return jsonify(movie_service(provider_id).match_job(job_id))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/match-jobs/<job_id>/cancel")
    def iptv_movie_match_job_cancel(provider_id, job_id):
        try:
            return jsonify(movie_service(provider_id).cancel_match_job(job_id))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/match-jobs/<job_id>/apply")
    def iptv_movie_match_job_apply(provider_id, job_id):
        try:
            return jsonify(movie_service(provider_id).apply_match_job(job_id, request.get_json(silent=True) or {}))
        except (KeyError, TypeError, ValueError, RuntimeError, IPTVTMDBError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/rebuild/preview")
    def iptv_movie_rebuild_preview(provider_id):
        try:
            return jsonify(movie_service(provider_id).rebuild_preview(request.get_json(silent=True) or {}))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/rebuild/<job_id>")
    def iptv_movie_rebuild_job(provider_id, job_id):
        try:
            return jsonify(movie_service(provider_id).rebuild_job(job_id))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/rebuild/<job_id>/apply")
    def iptv_movie_rebuild_apply(provider_id, job_id):
        try:
            return jsonify(movie_service(provider_id).apply_rebuild(job_id, request.get_json(silent=True) or {}))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/rebuild/<job_id>/cancel")
    def iptv_movie_rebuild_cancel(provider_id, job_id):
        try:
            return jsonify(movie_service(provider_id).cancel_rebuild(job_id))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/fusion/preview")
    def iptv_movie_fusion_preview(provider_id):
        try:
            data = request.get_json(silent=True) or {}
            return jsonify(movie_service(provider_id).fusion_preview(limit=data.get("limit", 500)))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/fusion/apply")
    def iptv_movie_fusion_apply(provider_id):
        try:
            return jsonify(movie_service(provider_id).fusion_apply(request.get_json(silent=True) or {}))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/prioritize")
    def iptv_movie_prioritize(provider_id):
        try:
            data = request.get_json(silent=True) or {}
            return jsonify({"prioritized": movie_service(provider_id).prioritize_movies(data.get("movie_keys") or [])})
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/enrichment/<action>")
    def iptv_movie_enrichment(provider_id, action):
        data = request.get_json(silent=True) or {}
        try:
            provider_movies = movie_service(provider_id)
            if action == "start":
                result = provider_movies.start_enrichment(consent=bool(data.get("consent")), diagnostic=bool(data.get("diagnostic")))
            elif action == "pause":
                result = provider_movies.pause_enrichment()
            elif action == "resume":
                result = provider_movies.resume_enrichment(continue_after_restart=bool(data.get("continue_after_restart")))
            elif action == "cancel":
                result = provider_movies.cancel_enrichment()
            elif action == "retry-failures":
                result = provider_movies.retry_failures()
            elif action == "re-evaluate-stale":
                result = provider_movies.re_evaluate_stale()
            else:
                raise KeyError("IPTV enrichment action was not found")
            return jsonify(result)
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/<movie_key>")
    def iptv_movie_detail(provider_id, movie_key):
        try:
            return jsonify(movie_service(provider_id).movie(movie_key))
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/<movie_key>/sources")
    def iptv_movie_sources(provider_id, movie_key):
        try:
            return jsonify({"items": movie_service(provider_id).sources(movie_key)})
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/<movie_key>/localization/<locale>")
    def iptv_movie_localization(provider_id, movie_key, locale):
        try:
            return jsonify(movie_service(provider_id).localization(movie_key, locale))
        except (KeyError, ValueError, RuntimeError, IPTVTMDBError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/movies/<movie_key>/match/search")
    def iptv_movie_match_search(provider_id, movie_key):
        try:
            return jsonify(movie_service(provider_id).manual_search(
                movie_key, request.args.get("q", ""), request.args.get("year", 0)
            ))
        except (KeyError, TypeError, ValueError, RuntimeError, IPTVTMDBError) as error:
            return error_response(error, provider_id)

    @app.route("/api/iptv/providers/<provider_id>/movies/<movie_key>/match", methods=["POST", "DELETE"])
    def iptv_movie_match(provider_id, movie_key):
        data = request.get_json(silent=True) or {}
        try:
            provider_movies = movie_service(provider_id)
            if request.method == "DELETE":
                provider_movies.remove_match(
                    movie_key,
                    reprocess=request.args.get("reprocess", "").lower() in {"1", "true", "yes"},
                )
                return jsonify({"success": True})
            next_key = provider_movies.manual_match(movie_key, data.get("tmdb_id"))
            return jsonify({"success": True, "movie_key": next_key})
        except (KeyError, TypeError, ValueError, RuntimeError, IPTVTMDBError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/movies/<movie_key>/favorite")
    def iptv_movie_favorite(provider_id, movie_key):
        data = request.get_json(silent=True) or {}
        try:
            favorite = movie_service(provider_id).set_favorite(movie_key, bool(data.get("favorite", True)))
            return jsonify({"success": True, "favorite": favorite})
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.route("/api/iptv/providers/<provider_id>/movies/<movie_key>/lists/<list_id>", methods=["POST", "DELETE"])
    def iptv_movie_list_membership(provider_id, movie_key, list_id):
        try:
            included = request.method == "POST"
            changed = movie_service(provider_id).set_list_membership(movie_key, list_id, included)
            return jsonify({"success": True, "included": changed})
        except (KeyError, ValueError, RuntimeError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/favorites")
    def iptv_favorites(provider_id):
        try:
            return jsonify(service(provider_id).list_favorites(
                kind=request.args.get("kind", ""),
                query=request.args.get("q", ""),
                page=request.args.get("page", 1),
                page_size=request.args.get("page_size", 60),
            ))
        except (KeyError, TypeError, ValueError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/items/<kind>/<item_id>")
    def iptv_item_detail(provider_id, kind, item_id):
        try:
            return jsonify(service(provider_id).detail(kind, item_id))
        except (KeyError, ValueError, XtreamError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/epg/<stream_id>")
    def iptv_epg(provider_id, stream_id):
        try:
            return jsonify({"items": service(provider_id).epg(stream_id, request.args.get("limit", 4))})
        except (KeyError, ValueError, XtreamError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/favorites/<kind>/<item_id>")
    def iptv_favorite(provider_id, kind, item_id):
        data = request.get_json(silent=True) or {}
        try:
            favorite = service(provider_id).set_favorite(kind, item_id, bool(data.get("favorite", True)))
            return jsonify({"success": True, "favorite": favorite})
        except (KeyError, ValueError) as error:
            return error_response(error, provider_id)

    @app.route("/api/iptv/providers/<provider_id>/lists", methods=["GET", "POST"])
    def iptv_lists(provider_id):
        provider_service = None
        try:
            provider_service = service(provider_id)
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                return jsonify(provider_service.create_list(data.get("name", ""))), 201
            return jsonify({"items": provider_service.lists(
                kind=request.args.get("kind", ""),
                item_id=request.args.get("item_id", ""),
                include_system=request.args.get("include_system", "").lower() in {"1", "true", "yes"},
            )})
        except (KeyError, ValueError) as error:
            return error_response(error, provider_id)

    @app.route("/api/iptv/providers/<provider_id>/lists/<list_id>", methods=["PATCH", "DELETE"])
    def iptv_list_detail(provider_id, list_id):
        try:
            provider_service = service(provider_id)
            if request.method == "DELETE":
                return jsonify({"success": provider_service.delete_list(list_id)})
            data = request.get_json(silent=True) or {}
            return jsonify(provider_service.rename_list(list_id, data.get("name", "")))
        except (KeyError, ValueError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/lists/<list_id>/items")
    def iptv_list_items(provider_id, list_id):
        try:
            return jsonify(service(provider_id).list_entries(
                list_id,
                kind=request.args.get("kind", ""),
                query=request.args.get("q", ""),
                page=request.args.get("page", 1),
                page_size=request.args.get("page_size", 60),
            ))
        except (KeyError, TypeError, ValueError) as error:
            return error_response(error, provider_id)

    @app.route(
        "/api/iptv/providers/<provider_id>/lists/<list_id>/items/<kind>/<item_id>",
        methods=["POST", "DELETE", "PATCH"],
    )
    def iptv_list_item(provider_id, list_id, kind, item_id):
        data = request.get_json(silent=True) or {}
        try:
            provider_service = service(provider_id)
            if request.method == "PATCH":
                changed = provider_service.move_list_item(list_id, kind, item_id, data.get("direction"))
            else:
                changed = provider_service.set_list_item(list_id, kind, item_id, request.method == "POST")
            return jsonify({"success": True, "changed": bool(changed)})
        except (KeyError, ValueError) as error:
            return error_response(error, provider_id)

    @app.post("/api/iptv/providers/<provider_id>/history/<kind>/<item_id>")
    def iptv_history(provider_id, kind, item_id):
        data = request.get_json(silent=True) or {}
        try:
            service(provider_id).store.update_history(
                kind,
                item_id,
                data.get("position_seconds"),
                data.get("duration_seconds"),
                data.get("completed"),
            )
            return jsonify({"success": True})
        except (KeyError, TypeError, ValueError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/recent")
    def iptv_recent(provider_id):
        try:
            return jsonify({"items": service(provider_id).recent(request.args.get("limit", 12))})
        except (KeyError, TypeError, ValueError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/image/<kind>/<item_id>")
    def iptv_image(provider_id, kind, item_id):
        try:
            path = service(provider_id).cached_image(
                kind,
                item_id,
                backdrop=request.args.get("backdrop") == "1",
            )
            return send_file(path, max_age=86400, conditional=True)
        except (KeyError, FileNotFoundError, ValueError):
            return "", 404

    @app.post("/api/iptv/providers/<provider_id>/playback")
    def iptv_playback_start(provider_id):
        data = request.get_json(silent=True) or {}
        try:
            port = request.environ.get("SERVER_PORT") or "5000"
            local_base_url = f"http://127.0.0.1:{port}"
            return jsonify(service(provider_id).start_playback(
                data.get("kind"),
                data.get("item_id"),
                data.get("extension"),
                data.get("title"),
                local_base_url=local_base_url,
            ))
        except (KeyError, ValueError, RuntimeError, XtreamError) as error:
            return error_response(error, provider_id)

    @app.get("/api/iptv/providers/<provider_id>/playback/<token>/<filename>")
    def iptv_playback_file(provider_id, token, filename):
        try:
            path = service(provider_id).playback_file(token, filename)
            response = send_file(path, conditional=False)
            response.headers["Cache-Control"] = "no-store" if filename.endswith(".m3u8") else "public, max-age=60"
            return response
        except (KeyError, FileNotFoundError):
            return "", 404

    @app.get("/api/iptv/providers/<provider_id>/upstream/<token>")
    def iptv_playback_upstream(provider_id, token):
        try:
            upstream = service(provider_id).open_upstream(token, request.headers.get("Range", ""))
        except (KeyError, FileNotFoundError):
            return "", 404
        headers = {}
        for name in ("Content-Length", "Content-Range", "Accept-Ranges"):
            value = upstream.headers.get(name)
            if value:
                headers[name] = value
        return Response(
            stream_with_context(_iter_upstream_chunks(upstream)),
            status=getattr(upstream, "status", 200),
            content_type=upstream.headers.get("Content-Type", "application/octet-stream"),
            headers=headers,
            direct_passthrough=True,
        )

    @app.delete("/api/iptv/providers/<provider_id>/playback/<token>")
    def iptv_playback_stop(provider_id, token):
        try:
            return jsonify({"success": service(provider_id).stop_playback(token)})
        except KeyError as error:
            return error_response(error, provider_id)
