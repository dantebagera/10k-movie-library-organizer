from flask import jsonify, request

from services.player_catalog import PlayerMediaError
from services.player_config import PlayerConfigError
from services.player_manager import PlayerLaunchError
from services.playback_history import PlaybackHistoryError


def register_player_routes(
    app,
    player_config,
    player_runtime,
    player_manager,
    playback_history,
    subtitle_service,
    persist_config,
):
    @app.get("/api/player/config")
    def get_player_config():
        return jsonify(player_config.public_payload())

    @app.put("/api/player/config")
    def put_player_config():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Player configuration must be an object"}), 400
        try:
            payload = player_config.reset() if data.get("reset") is True else player_config.update(data)
        except PlayerConfigError as error:
            return jsonify({"error": str(error)}), 400
        persist_config()
        return jsonify(payload)

    @app.get("/api/player/status")
    def get_player_status():
        payload = player_runtime.status(verify_hashes=False)
        payload["subtitles"] = subtitle_service.diagnostics()
        return jsonify(payload)

    @app.post("/api/player/verify")
    def verify_player_runtime():
        return jsonify(player_runtime.status(verify_hashes=True))

    @app.post("/api/player/play")
    def play_library_file():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("path_key"), str):
            return jsonify({"error": "A library file identity is required"}), 400
        if "path" in data:
            return jsonify({"error": "Arbitrary media paths are not accepted"}), 400
        restart = data.get("restart", False)
        if not isinstance(restart, bool):
            return jsonify({"error": "restart must be true or false"}), 400
        try:
            return jsonify(player_manager.play(data["path_key"], restart=restart))
        except PlayerMediaError as error:
            status = 404 if "missing" in str(error).lower() else 400
            return jsonify({"error": str(error)}), status
        except PlaybackHistoryError as error:
            return jsonify({"error": str(error)}), 409
        except PlayerLaunchError as error:
            return jsonify({"error": str(error)}), 503

    @app.get("/api/player/continue-watching")
    def get_continue_watching():
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            return jsonify({"error": "limit must be an integer"}), 400
        return jsonify({"items": playback_history.continue_watching(limit=limit)})

    @app.post("/api/player/progress/clear")
    def clear_player_progress():
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("path_key"), str):
            return jsonify({"error": "A library file identity is required"}), 400
        path_key = data["path_key"].strip()
        if not path_key or len(path_key) > 32768 or "\x00" in path_key:
            return jsonify({"error": "The library file identity is invalid"}), 400
        return jsonify({
            "ok": True,
            "removed": playback_history.clear(path_key),
        })
