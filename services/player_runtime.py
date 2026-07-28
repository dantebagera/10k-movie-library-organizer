import hashlib
import json
import platform
from pathlib import Path, PurePosixPath


PLAYER_RUNTIME_SCHEMA = "cinema-paradiso-player-runtime-v1"
PLAYER_SELECTOR_SCHEMA = "cinema-paradiso-player-selector-v1"
SUPPORTED_IPC_PROTOCOL = 1
VALID_STATES = {"ready", "missing", "damaged", "incompatible"}


class PlayerRuntimeError(ValueError):
    pass


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def _safe_relative_path(value, field):
    text = str(value or "").replace("\\", "/").strip()
    candidate = PurePosixPath(text)
    if (
        not text
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.parts[0] in {"", "."}
    ):
        raise PlayerRuntimeError(f"{field} contains an unsafe path")
    return candidate


def _load_json(path, label):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise PlayerRuntimeError(f"{label} is missing") from error
    except (OSError, json.JSONDecodeError) as error:
        raise PlayerRuntimeError(f"{label} is unreadable") from error
    if not isinstance(data, dict):
        raise PlayerRuntimeError(f"{label} must contain an object")
    return data


def validate_player_manifest(bundle_root, app_version=None, verify_hashes=True):
    bundle_root = Path(bundle_root).resolve()
    manifest_path = bundle_root / "cinema-paradiso-player.json"
    manifest = _load_json(manifest_path, "Player runtime manifest")
    if manifest.get("schema") != PLAYER_RUNTIME_SCHEMA:
        raise PlayerRuntimeError("Player runtime manifest schema is incompatible")

    required_text = (
        "bundle_version",
        "player_version",
        "mpv_version",
        "mpv_commit",
        "qt_version",
        "architecture",
    )
    if any(not str(manifest.get(field) or "").strip() for field in required_text):
        raise PlayerRuntimeError("Player runtime manifest is incomplete")
    if int(manifest.get("ipc_protocol_version") or 0) != SUPPORTED_IPC_PROTOCOL:
        raise PlayerRuntimeError("Player IPC protocol is incompatible")
    if str(manifest["bundle_version"]).strip() != bundle_root.name:
        raise PlayerRuntimeError("Player bundle directory does not match its manifest")

    compatible_versions = manifest.get("compatible_cp_versions")
    if not isinstance(compatible_versions, list) or not compatible_versions:
        raise PlayerRuntimeError("Compatible Cinema Paradiso versions are missing")
    if app_version and app_version not in compatible_versions:
        raise PlayerRuntimeError("Player runtime is not compatible with this Cinema Paradiso version")

    architecture = str(manifest["architecture"]).lower()
    machine = platform.machine().lower()
    if architecture not in {"x86_64", "amd64"}:
        raise PlayerRuntimeError("Player runtime architecture is incompatible")
    if machine and machine not in {"amd64", "x86_64"}:
        raise PlayerRuntimeError("This computer architecture is incompatible with the player runtime")

    build_flags = manifest.get("build_flags")
    sources = manifest.get("sources")
    required_files = manifest.get("required_files")
    hashes = manifest.get("sha256")
    licenses = manifest.get("licenses")
    if not isinstance(build_flags, list) or not build_flags:
        raise PlayerRuntimeError("Player build flags are missing")
    if not isinstance(sources, list) or not sources:
        raise PlayerRuntimeError("Player upstream sources are missing")
    if not isinstance(required_files, list) or not required_files:
        raise PlayerRuntimeError("Player required-file inventory is missing")
    if not isinstance(hashes, dict) or not hashes:
        raise PlayerRuntimeError("Player runtime hashes are missing")
    if not isinstance(licenses, list) or not licenses:
        raise PlayerRuntimeError("Player license notices are missing")

    normalized_required = []
    for raw_path in required_files:
        relative = _safe_relative_path(raw_path, "required_files")
        normalized = relative.as_posix()
        if normalized in normalized_required:
            raise PlayerRuntimeError("Player required-file inventory contains duplicates")
        normalized_required.append(normalized)
    for essential in ("cp-player.exe", str(manifest.get("mpv_dll") or "")):
        if essential not in normalized_required:
            raise PlayerRuntimeError("Player essential runtime files are missing from the manifest")
    if not any(
        PurePosixPath(path).name.lower().startswith("qt6")
        and PurePosixPath(path).suffix.lower() == ".dll"
        for path in normalized_required
    ):
        raise PlayerRuntimeError("Qt runtime files are missing from the manifest")
    if not any(path.lower().startswith("licenses/") for path in normalized_required):
        raise PlayerRuntimeError("Player license files are missing from the manifest")
    for required_notice in (
        "licenses/RELINKING.md",
        "licenses/THIRD-PARTY-NOTICES.md",
    ):
        if required_notice not in normalized_required:
            raise PlayerRuntimeError("Player compliance material is incomplete")
    if not any(path.lower().startswith("plugins/") for path in normalized_required):
        raise PlayerRuntimeError("Qt plugin files are missing from the manifest")
    if not any(path.lower().startswith("qml/") for path in normalized_required):
        raise PlayerRuntimeError("Qt QML files are missing from the manifest")
    if not any(path.lower().startswith("assets/") for path in normalized_required):
        raise PlayerRuntimeError("Player assets are missing from the manifest")

    license_paths = []
    for entry in licenses:
        if not isinstance(entry, dict):
            raise PlayerRuntimeError("Player license notice is invalid")
        if not str(entry.get("component") or "").strip() or not str(entry.get("spdx") or "").strip():
            raise PlayerRuntimeError("Player license notice is incomplete")
        license_paths.append(_safe_relative_path(entry.get("path"), "licenses").as_posix())
    if any(path not in normalized_required for path in license_paths):
        raise PlayerRuntimeError("Player license file is not in the required-file inventory")

    for source in sources:
        if not isinstance(source, dict) or not str(source.get("name") or "").strip():
            raise PlayerRuntimeError("Player upstream source is invalid")
        if not str(source.get("url") or "").startswith("https://"):
            raise PlayerRuntimeError("Player upstream source URL is invalid")
        if not str(source.get("revision") or "").strip():
            raise PlayerRuntimeError("Player upstream source revision is missing")

    for relative_path in normalized_required:
        expected_hash = str(hashes.get(relative_path) or "").strip().upper()
        if len(expected_hash) != 64 or any(character not in "0123456789ABCDEF" for character in expected_hash):
            raise PlayerRuntimeError("Player runtime hash inventory is incomplete")
        file_path = bundle_root.joinpath(*PurePosixPath(relative_path).parts)
        if not file_path.is_file():
            raise PlayerRuntimeError(f"Player runtime file is missing: {relative_path}")
        if verify_hashes and sha256_file(file_path) != expected_hash:
            raise PlayerRuntimeError(f"Player runtime file is damaged: {relative_path}")

    return manifest


class PlayerRuntime:
    def __init__(self, runtime_root, app_version):
        self.runtime_root = Path(runtime_root).resolve()
        self.app_version = str(app_version)

    @property
    def selector_path(self):
        return self.runtime_root / "current.json"

    def status(self, verify_hashes=False):
        base = {
            "state": "missing",
            "ready": False,
            "os_fallback_available": True,
            "player_version": "",
            "mpv_version": "",
            "qt_version": "",
            "architecture": "",
            "bundle_version": "",
            "ipc_protocol_version": SUPPORTED_IPC_PROTOCOL,
            "notices": [],
            "detail": "The built-in player runtime is not installed. OS-default playback remains available.",
        }
        if not self.selector_path.is_file():
            return base
        try:
            selector = _load_json(self.selector_path, "Player runtime selector")
            if selector.get("schema") != PLAYER_SELECTOR_SCHEMA:
                raise PlayerRuntimeError("Player runtime selector schema is incompatible")
            bundle_version = str(selector.get("bundle_version") or "").strip()
            if not bundle_version or Path(bundle_version).name != bundle_version:
                raise PlayerRuntimeError("Player runtime selector is invalid")
            bundle_root = self.runtime_root / "versions" / bundle_version
            manifest = validate_player_manifest(
                bundle_root,
                app_version=self.app_version,
                verify_hashes=verify_hashes,
            )
        except PlayerRuntimeError as error:
            detail = str(error)
            state = "incompatible" if "compatible" in detail.lower() else "damaged"
            return {**base, "state": state, "detail": detail}

        notices = [
            {
                "component": entry["component"],
                "spdx": entry["spdx"],
                "source": entry.get("source", ""),
            }
            for entry in manifest["licenses"]
        ]
        return {
            **base,
            "state": "ready",
            "ready": True,
            "player_version": str(manifest["player_version"]),
            "mpv_version": str(manifest["mpv_version"]),
            "qt_version": str(manifest["qt_version"]),
            "architecture": str(manifest["architecture"]),
            "bundle_version": str(manifest["bundle_version"]),
            "ipc_protocol_version": int(manifest["ipc_protocol_version"]),
            "notices": notices,
            "detail": "The built-in player runtime is ready.",
        }
