import os

from flask import make_response, send_from_directory


REACT_SECTION_PATHS = (
    "/styleguide",
    "/library",
    "/movie-lists",
    "/cleanup",
    "/discover",
    "/ai-control",
    "/iptv",
    "/downloads",
    "/help",
    "/settings",
    "/card-lab",
)


def register_frontend_routes(app, base_dir):
    test_root = os.environ.get("CP_TEST_ROOT", "") if os.environ.get("CP_TEST_MODE") == "1" else ""
    test_dist = os.environ.get("CP_TEST_DIST_DIR", "") if test_root else ""
    if test_dist:
        resolved_root = os.path.abspath(test_root)
        resolved_dist = os.path.abspath(test_dist)
        if os.path.commonpath((resolved_root, resolved_dist)) != resolved_root:
            raise RuntimeError("CP_TEST_DIST_DIR must be inside CP_TEST_ROOT")
        dist_dir = resolved_dist
    else:
        dist_dir = os.path.join(base_dir, "dist")

    def frontend_index():
        dist_index = os.path.join(dist_dir, "index.html")
        if os.path.exists(dist_index):
            return send_from_directory(dist_dir, "index.html")
        response = make_response(
            "React frontend has not been built. Run npm install and npm run build, "
            "or use run.bat on Windows.",
            503,
        )
        response.mimetype = "text/plain"
        return response

    app.add_url_rule("/", "frontend_index", frontend_index)
    for position, path in enumerate(REACT_SECTION_PATHS):
        app.add_url_rule(path, f"frontend_section_{position}", frontend_index)

    def frontend_asset(filename):
        return send_from_directory(os.path.join(dist_dir, "assets"), filename)

    app.add_url_rule(
        "/assets/<path:filename>",
        "frontend_asset",
        frontend_asset,
    )
