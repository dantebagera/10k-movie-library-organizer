import hashlib
import json
from pathlib import Path

from services.player_runtime import PLAYER_RUNTIME_SCHEMA


def create_player_runtime_bundle(root, app_version="9.9.9", bundle_version="player-test-1"):
    bundle = Path(root) / bundle_version
    files = {
        "cp-player.exe": b"player",
        "libmpv-2.dll": b"mpv",
        "Qt6Core.dll": b"qt",
        "plugins/platforms/qwindows.dll": b"plugin",
        "qml/QtQuick/qtquick2plugin.dll": b"qml",
        "assets/player-theme.json": b"{}",
        "licenses/Qt-LGPL-3.0.txt": b"Qt license",
        "licenses/mpv-LGPL-2.1.txt": b"mpv license",
        "licenses/RELINKING.md": b"Relinking instructions",
        "licenses/THIRD-PARTY-NOTICES.md": b"Third-party notices",
    }
    for relative, content in files.items():
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "schema": PLAYER_RUNTIME_SCHEMA,
        "bundle_version": bundle_version,
        "player_version": "0.1.0",
        "ipc_protocol_version": 1,
        "mpv_version": "0.40.0",
        "mpv_commit": "48e6c35c0e056d9e4ff04b98e012416697736d8a",
        "mpv_dll": "libmpv-2.dll",
        "qt_version": "6.10.3",
        "architecture": "x86_64",
        "build_flags": ["-Dgpl=false", "--disable-gpl", "dynamic Qt linking"],
        "sources": [
            {
                "name": "mpv",
                "url": "https://github.com/mpv-player/mpv",
                "revision": "48e6c35c0e056d9e4ff04b98e012416697736d8a",
            },
            {
                "name": "Qt",
                "url": "https://download.qt.io/",
                "revision": "6.10.3",
            },
        ],
        "licenses": [
            {
                "component": "Qt",
                "spdx": "LGPL-3.0-only",
                "path": "licenses/Qt-LGPL-3.0.txt",
                "source": "https://www.qt.io/licensing/",
            },
            {
                "component": "mpv",
                "spdx": "LGPL-2.1-or-later",
                "path": "licenses/mpv-LGPL-2.1.txt",
                "source": "https://github.com/mpv-player/mpv",
            },
        ],
        "required_files": list(files),
        "sha256": {
            relative: hashlib.sha256(content).hexdigest().upper()
            for relative, content in files.items()
        },
    }
    (bundle / "cinema-paradiso-player.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return bundle
