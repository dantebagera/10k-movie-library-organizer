from flask import Response, jsonify, request, send_file, stream_with_context

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
