from flask import jsonify, request

from services.player_catalog import PlayerMediaError
from services.player_config import PlayerConfigError
from services.player_manager import PlayerLaunchError


def register_player_routes(
    app,
    player_config,
    player_runtime,
    player_manager,
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
        return jsonify(player_runtime.status(verify_hashes=False))

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
        try:
            return jsonify(player_manager.play(data["path_key"]))
        except PlayerMediaError as error:
            status = 404 if "missing" in str(error).lower() else 400
            return jsonify({"error": str(error)}), status
        except PlayerLaunchError as error:
            return jsonify({"error": str(error)}), 503
