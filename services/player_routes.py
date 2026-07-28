from flask import jsonify, request

from services.player_config import PlayerConfigError


def register_player_routes(app, player_config, player_runtime, persist_config):
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
