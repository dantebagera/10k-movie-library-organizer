import base64
import ctypes
import hashlib
import http.cookiejar
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


QBT_RELEASES_API = "https://api.github.com/repos/qbittorrent/qBittorrent/releases/latest"
SEVEN_ZIP_RELEASES_API = "https://api.github.com/repos/ip7z/7zip/releases/latest"
QBT_TAG = "cinema-paradiso"
DEFAULT_WEBUI_PORT = 8686
BUNDLED_QBT_VERSION = "5.2.2"
PAYLOAD_COLLISION_RULE_VERSION = 3
MISSING_TORRENT_GRACE_SECONDS = 10
MISSING_TORRENT_MIN_CHECKS = 3
TORRENT_METADATA_MAX_WAIT_SECONDS = 15 * 60
TORRENT_SIZE_TOLERANCE_RATIO = 0.10
TORRENT_SIZE_TOLERANCE_BYTES = 64 * 1024 * 1024
TORRENT_MINIMUM_VIDEO_SHARE = 0.80
MOVIE_VIDEO_EXTENSIONS = {
    ".avi", ".flv", ".iso", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4",
    ".mpeg", ".mpg", ".ts", ".vob", ".webm", ".wmv",
}
DANGEROUS_TORRENT_EXTENSIONS = {
    ".appref-ms", ".bat", ".chm", ".cmd", ".com", ".cpl", ".dll", ".exe",
    ".gadget", ".hta", ".inf", ".jar", ".js", ".jse", ".lnk", ".msi", ".pif",
    ".ps1", ".reg", ".scf", ".scr", ".url", ".vbs", ".wsf", ".wsh",
}
HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


class QBittorrentError(RuntimeError):
    pass


class TorrentValidationError(QBittorrentError):
    pass


class TorrentIdentityMismatch(TorrentValidationError):
    pass


def normalize_architecture(value=None):
    raw = str(value or platform.machine() or "").strip().lower()
    if raw in {"amd64", "x86_64", "x64"}:
        return "x86_64"
    if raw in {"arm64", "aarch64"}:
        return "arm64"
    if raw in {"x86", "i386", "i686"}:
        return "x86"
    return raw or "unknown"


def normalize_system(value=None):
    raw = str(value or platform.system() or "").strip().lower()
    return {"win32": "windows", "windows": "windows", "darwin": "darwin", "linux": "linux"}.get(raw, raw)


def select_release_asset(assets, system=None, architecture=None):
    system = normalize_system(system)
    architecture = normalize_architecture(architecture)
    if architecture != "x86_64":
        return None
    patterns = {
        "windows": re.compile(r"^qbittorrent_[\d.]+_x64_setup\.exe$", re.I),
        "darwin": re.compile(r"^qbittorrent-[\d.]+\.dmg$", re.I),
        "linux": re.compile(r"^qbittorrent-[\d.]+_x86_64\.AppImage$", re.I),
    }
    pattern = patterns.get(system)
    if not pattern:
        return None
    return next((asset for asset in assets if pattern.match(str(asset.get("name", "")))), None)


def platform_is_supported(system=None, architecture=None):
    return normalize_system(system) in {"windows", "darwin", "linux"} and normalize_architecture(architecture) == "x86_64"


def bundled_runtime_root(app_root):
    return Path(app_root) / "runtime" / "qbittorrent" / "versions" / BUNDLED_QBT_VERSION


def process_launch_kwargs(os_name=None):
    os_name = os_name or os.name
    kwargs = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os_name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    return kwargs


def hide_process_windows(process_id):
    if os.name != "nt" or not process_id:
        return 0
    user32 = ctypes.windll.user32
    hidden = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def hide_window(window_handle, _):
        nonlocal hidden
        owner_process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(window_handle, ctypes.byref(owner_process_id))
        if owner_process_id.value == int(process_id) and user32.IsWindowVisible(window_handle):
            user32.ShowWindow(window_handle, subprocess.SW_HIDE)
            hidden += 1
        return True

    user32.EnumWindows(hide_window, 0)
    return hidden


def validate_magnet_url(value):
    try:
        parsed = urllib.parse.urlsplit(str(value or "").strip())
    except ValueError:
        return False
    if parsed.scheme.lower() != "magnet":
        return False
    exact_topics = urllib.parse.parse_qs(parsed.query).get("xt", [])
    return any(
        re.fullmatch(r"urn:btih:(?:[A-Fa-f0-9]{40}|[A-Za-z2-7]{32})", topic)
        or re.fullmatch(r"urn:btmh:1220[A-Fa-f0-9]{64}", topic)
        for topic in exact_topics
    )


def magnet_hash(value):
    if not validate_magnet_url(value):
        return ""
    topics = urllib.parse.parse_qs(urllib.parse.urlsplit(value).query).get("xt", [])
    for topic in topics:
        if topic.lower().startswith("urn:btih:"):
            raw = topic.split(":", 2)[2]
            if len(raw) == 32:
                return base64.b32decode(raw.upper()).hex()
            return raw.lower()
        if topic.lower().startswith("urn:btmh:1220"):
            return topic.split(":", 2)[2][4:].lower()
    return ""


def normalize_torrent_info_hash(value):
    raw = str(value or "").strip()
    lowered = raw.lower()
    for prefix in ("urn:btih:", "urn:btmh:1220"):
        if lowered.startswith(prefix):
            raw = raw[len(prefix):]
            break
    if re.fullmatch(r"[A-Fa-f0-9]{40}", raw) or re.fullmatch(r"[A-Fa-f0-9]{64}", raw):
        return raw.lower()
    if re.fullmatch(r"[A-Za-z2-7]{32}", raw):
        try:
            return base64.b32decode(raw.upper()).hex()
        except ValueError:
            return ""
    return ""


def is_allowed_prowlarr_url(candidate, prowlarr_origin):
    try:
        candidate_url = urllib.parse.urlsplit(str(candidate or "").strip())
        configured = urllib.parse.urlsplit(str(prowlarr_origin or "").strip())
    except ValueError:
        return False
    if candidate_url.scheme not in {"http", "https"} or configured.scheme not in {"http", "https"}:
        return False
    try:
        candidate_port = candidate_url.port or (443 if candidate_url.scheme == "https" else 80)
        configured_port = configured.port or (443 if configured.scheme == "https" else 80)
    except ValueError:
        return False
    return (
        candidate_url.scheme.lower() == configured.scheme.lower()
        and (candidate_url.hostname or "").lower() == (configured.hostname or "").lower()
        and candidate_port == configured_port
    )


def is_path_within(path, root):
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except (OSError, ValueError, TypeError):
        return False


def destination_library_root(destination, library_roots):
    destination = os.path.realpath(destination)
    for root in library_roots or []:
        if is_path_within(destination, root):
            return str(root)
    return ""


def build_downloads_html(original_html):
    rendered = str(original_html or "")
    bridge = """
<script id="cp-qbt-frame-bridge">
(() => {
  if (window.parent === window) return;
  try {
    Object.defineProperty(window.parent, "qBittorrent", {
      configurable: true,
      get: () => window.qBittorrent
    });
  } catch (_) {}
})();
</script>
"""
    return rendered.replace("</head>", f"{bridge}</head>", 1)


def proxy_request_headers(headers, upstream_origin):
    parsed = urllib.parse.urlsplit(upstream_origin)
    result = {
        key: value for key, value in (headers or {}).items()
        if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "accept-encoding"
    }
    result["Host"] = parsed.netloc
    if result.get("Origin"):
        result["Origin"] = upstream_origin
    if result.get("Referer"):
        ref = urllib.parse.urlsplit(result["Referer"])
        result["Referer"] = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, ref.path, ref.query, ""))
    return result


def _atomic_json_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_entries(path):
    path = Path(path)
    if path.is_symlink():
        return None
    if path.is_file():
        return {".": ("file", path.stat().st_size)}
    if not path.is_dir():
        return None
    entries = {}
    for child in sorted(path.rglob("*"), key=lambda item: str(item.relative_to(path)).lower()):
        relative = str(child.relative_to(path)).replace("\\", "/")
        if child.is_symlink():
            return None
        if child.is_dir():
            entries[relative] = ("directory", 0)
        elif child.is_file():
            entries[relative] = ("file", child.stat().st_size)
        else:
            return None
    return entries


def _payload_is_contained_by(source, destination):
    source = Path(source)
    destination = Path(destination)
    source_entries = _payload_entries(source)
    destination_entries = _payload_entries(destination)
    if source_entries is None or destination_entries is None:
        return False
    if source.is_file():
        return destination.is_file() and source_entries == destination_entries \
            and _sha256_file(source) == _sha256_file(destination)
    if not destination.is_dir() or any(
        destination_entries.get(relative) != details
        for relative, details in source_entries.items()
    ):
        return False
    for relative, (kind, _size) in source_entries.items():
        if kind != "file":
            continue
        if _sha256_file(source / relative) != _sha256_file(destination / relative):
            return False
    return True


def _payload_signature(path):
    if not str(path or "").strip():
        return {"kind": "missing"}
    path = Path(path)
    if not path.exists():
        return {"kind": "missing"}
    entries = _payload_entries(path)
    if entries is None:
        return {"kind": "unsupported"}
    if path.is_file():
        stat = path.stat()
        return {"kind": "file", "size": stat.st_size, "modified_ns": stat.st_mtime_ns}
    signature = []
    for relative, (kind, size) in entries.items():
        child = path / relative
        signature.append([relative, kind, size, child.stat().st_mtime_ns])
    return {"kind": "directory", "entries": signature}


def _numbered_collision_target(target, source_is_file, reserved_targets):
    target = Path(target)
    for number in range(2, 10000):
        if source_is_file:
            candidate = target.with_name(f"{target.stem} ({number}){target.suffix}")
        else:
            candidate = target.with_name(f"{target.name} ({number})")
        if not candidate.exists() and str(candidate) not in reserved_targets:
            return candidate
    raise QBittorrentError(f"Could not reserve an upgrade destination for: {target.name}")


def _normalized_torrent_manifest(manifest):
    if isinstance(manifest, list):
        manifest = manifest[0] if manifest else {}
    if not isinstance(manifest, dict):
        raise TorrentValidationError("qBittorrent returned an invalid torrent manifest")
    info = manifest.get("info")
    if not isinstance(info, dict):
        raise TorrentValidationError("qBittorrent could not read the torrent manifest")
    files = info.get("files")
    if not isinstance(files, list) or not files:
        name = str(info.get("name") or "").strip()
        length = info.get("length")
        files = [{"path": name, "length": length}] if name and length is not None else []
    return manifest, info, files


def _torrent_manifest_hashes(manifest):
    candidates = manifest if isinstance(manifest, list) else [manifest]
    hashes = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("hash", "info_hash", "infoHash", "infohash_v1", "infohash_v2"):
            normalized = normalize_torrent_info_hash(candidate.get(key))
            if normalized:
                hashes.add(normalized)
    return hashes


def validate_torrent_manifest(manifest, expected_size=0, expected_hash=""):
    manifest_hashes = _torrent_manifest_hashes(manifest)
    expected_hash = normalize_torrent_info_hash(expected_hash)
    if expected_hash:
        if not manifest_hashes:
            raise TorrentIdentityMismatch(
                "Blocked torrent because qBittorrent could not verify its advertised infohash"
            )
        if expected_hash not in manifest_hashes:
            raise TorrentIdentityMismatch(
                "Blocked torrent because its infohash does not match the selected release"
            )
    manifest, info, raw_files = _normalized_torrent_manifest(manifest)
    files = []
    total_size = 0
    video_size = 0
    dangerous = []
    for item in raw_files:
        if not isinstance(item, dict):
            raise TorrentValidationError("Torrent manifest contains an invalid file entry")
        path_text = str(item.get("path") or item.get("name") or "").replace("\\", "/").strip()
        path = Path(path_text)
        if (
            not path_text
            or path.is_absolute()
            or path.drive
            or any(ord(character) < 32 for character in path_text)
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise TorrentValidationError("Torrent manifest contains an unsafe file path")
        try:
            length = int(item.get("length"))
        except (TypeError, ValueError):
            raise TorrentValidationError("Torrent manifest contains an invalid file size")
        if length < 0:
            raise TorrentValidationError("Torrent manifest contains an invalid file size")
        if path.suffix.lower() in DANGEROUS_TORRENT_EXTENSIONS:
            dangerous.append(path_text)
        if path.suffix.lower() in MOVIE_VIDEO_EXTENSIONS:
            video_size += length
        total_size += length
        files.append({"path": path_text, "length": length})
    if not files or total_size <= 0:
        raise TorrentValidationError("Torrent manifest contains no downloadable movie data")
    if dangerous:
        names = ", ".join(dangerous[:3])
        raise TorrentValidationError(f"Blocked unsafe torrent payload: {names}")
    if video_size <= 0:
        raise TorrentValidationError("Blocked torrent because it contains no recognized movie file")
    if video_size / total_size < TORRENT_MINIMUM_VIDEO_SHARE:
        raise TorrentValidationError("Blocked torrent because movie files are not the main payload")
    try:
        expected_size = int(expected_size or 0)
    except (TypeError, ValueError):
        expected_size = 0
    if expected_size > 0:
        tolerance = max(TORRENT_SIZE_TOLERANCE_BYTES, int(expected_size * TORRENT_SIZE_TOLERANCE_RATIO))
        if abs(total_size - expected_size) > tolerance:
            raise TorrentValidationError(
                f"Blocked torrent because its payload size ({total_size} bytes) does not match "
                f"the advertised size ({expected_size} bytes)"
            )
    return {
        "name": str(info.get("name") or manifest.get("name") or "").strip(),
        "total_size": total_size,
        "video_size": video_size,
        "file_count": len(files),
        "info_hash": expected_hash or (sorted(manifest_hashes)[0] if manifest_hashes else ""),
    }


class QBittorrentJobStore:
    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"jobs": {}}
        except (OSError, ValueError):
            return {"jobs": {}}

    def all(self):
        with self._lock:
            return dict(self._read().get("jobs", {}))

    def get(self, torrent_hash):
        return self.all().get(str(torrent_hash or "").lower())

    def upsert(self, torrent_hash, patch):
        key = str(torrent_hash or "").lower()
        if not key:
            raise QBittorrentError("Torrent hash is required")
        with self._lock:
            data = self._read()
            jobs = data.setdefault("jobs", {})
            jobs[key] = {**jobs.get(key, {}), **(patch or {}), "hash": key, "updated_at": time.time()}
            _atomic_json_write(self.path, data)
            return jobs[key]

    def move_completed_payload(self, torrent_hash, allowed_staging_root):
        job = self.get(torrent_hash)
        if not job:
            raise QBittorrentError("Download job was not found")
        destination_text = str(job.get("destination", "") or "").strip()
        if not destination_text:
            raise QBittorrentError("Download destination is missing")
        destination = Path(destination_text)
        destination.mkdir(parents=True, exist_ok=True)
        payloads = [Path(item) for item in job.get("payload_paths", [])]
        if not payloads:
            raise QBittorrentError("Completed payload path is missing")
        previous_transfers = {
            str(item.get("source", "")): item
            for item in (job.get("transfer_plan") or [])
            if item.get("source")
        }
        resolved_targets = dict(job.get("resolved_targets") or {})
        reserved_targets = set(resolved_targets.values())
        transfers = []
        collisions = []
        for source in payloads:
            if not is_path_within(source, allowed_staging_root):
                raise QBittorrentError("Completed payload escaped the staging folder")
            source_key = str(source)
            default_target = destination / source.name
            resolved_target = resolved_targets.get(source_key)
            target = Path(resolved_target) if resolved_target else default_target
            if target.parent != destination:
                raise QBittorrentError("Resolved payload destination escaped the library folder")
            if source.exists() and target.exists():
                if _payload_is_contained_by(source, target):
                    transfers.append({"source": str(source), "target": str(target), "action": "duplicate"})
                elif job.get("upgrade") and not resolved_target:
                    target = _numbered_collision_target(default_target, source.is_file(), reserved_targets)
                    resolved_targets[source_key] = str(target)
                    reserved_targets.add(str(target))
                    transfers.append({"source": str(source), "target": str(target), "action": "move"})
                else:
                    collisions.append({
                        "source": str(source),
                        "target": str(target),
                        "source_signature": _payload_signature(source),
                        "target_signature": _payload_signature(target),
                    })
                continue
            if not source.exists() and not target.exists():
                raise QBittorrentError(f"Completed payload is missing: {source}")
            if not source.exists():
                previous = previous_transfers.get(str(source), {})
                if previous.get("target") != str(target) or previous.get("action") not in {
                    "move", "duplicate",
                } or previous.get("status") not in {
                    "started", "completed",
                }:
                    collisions.append({
                        "source": str(source),
                        "target": str(target),
                        "source_signature": _payload_signature(source),
                        "target_signature": _payload_signature(target),
                        "reason": "Source is missing and no CP transfer journal proves this target was imported",
                    })
                    continue
            transfers.append({
                "source": str(source),
                "target": str(target),
                "action": "move" if source.exists() else "resumed",
            })
        if collisions:
            targets = ", ".join(item["target"] for item in collisions)
            return self.upsert(torrent_hash, {
                "state": "destination_conflict",
                "collision": collisions,
                "resolved_targets": resolved_targets,
                "collision_rule_version": PAYLOAD_COLLISION_RULE_VERSION,
                "last_error": f"Different content already exists at: {targets}",
            })

        self.upsert(torrent_hash, {
            "state": "moving",
            "transfer_plan": transfers,
            "resolved_targets": resolved_targets,
            "collision": [],
            "last_error": "",
        })
        imported = []
        deduplicated = []
        for index, transfer in enumerate(transfers):
            source = Path(transfer["source"])
            target = Path(transfer["target"])
            if transfer["action"] in {"move", "duplicate"} and source.exists():
                transfers[index]["status"] = "started"
                self.upsert(torrent_hash, {"state": "moving", "transfer_plan": transfers})
            if transfer["action"] == "move" and source.exists():
                shutil.move(str(source), str(target))
            elif transfer["action"] == "duplicate" and source.exists():
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
                deduplicated.append(str(target))
            if not target.exists():
                raise QBittorrentError(f"Imported payload is missing: {target}")
            transfers[index]["status"] = "completed"
            imported.append(str(target))
            self.upsert(torrent_hash, {"state": "moving", "transfer_plan": transfers})
        return self.upsert(torrent_hash, {
            "state": "payload_imported",
            "imported_at": time.time(),
            "imported_paths": imported,
            "deduplicated_paths": deduplicated,
            "already_in_library": bool(imported) and len(deduplicated) == len(imported),
            "library_scan_pending": True,
            "last_error": "",
        })


class QBittorrentClient:
    def __init__(self, base_url):
        self.base_url = str(base_url).rstrip("/")
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))

    def request(self, path, fields=None, files=None, method=None, timeout=20):
        url = f"{self.base_url}{path}"
        headers = {"Referer": f"{self.base_url}/"}
        body = None
        if files:
            boundary = f"----CinemaParadiso{uuid.uuid4().hex}"
            chunks = []
            for key, value in (fields or {}).items():
                chunks.extend([
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode(),
                ])
            for key, item in files.items():
                filename, content, content_type = item
                chunks.extend([
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n'.encode(),
                    f"Content-Type: {content_type}\r\n\r\n".encode(),
                    content,
                    b"\r\n",
                ])
            chunks.append(f"--{boundary}--\r\n".encode())
            body = b"".join(chunks)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif fields is not None:
            body = urllib.parse.urlencode(fields).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers, method=method or ("POST" if body is not None else "GET"))
        with self.opener.open(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()

    def version(self):
        return self.request("/api/v2/app/version", timeout=3)[2].decode("utf-8")

    def add_magnet(self, magnet, save_path, *, stop_after_metadata=False):
        fields = {
            "urls": magnet, "savepath": save_path, "tags": QBT_TAG, "paused": "false",
            "root_folder": "true",
        }
        if stop_after_metadata:
            fields["stopCondition"] = "MetadataReceived"
        self.request("/api/v2/torrents/add", fields)

    def parse_torrent_metadata(self, content, filename):
        payload = self.request(
            "/api/v2/torrents/parseMetadata",
            files={"torrents": (filename, content, "application/x-bittorrent")},
            timeout=10,
        )[2]
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise QBittorrentError("qBittorrent returned an invalid torrent manifest") from error

    def add_torrent(self, content, filename, save_path):
        self.request(
            "/api/v2/torrents/add",
            fields={"savepath": save_path, "tags": QBT_TAG, "paused": "false", "root_folder": "true"},
            files={"torrents": (filename, content, "application/x-bittorrent")},
        )

    def torrents(self):
        payload = self.request("/api/v2/torrents/info", timeout=10)[2]
        return json.loads(payload.decode("utf-8"))

    def files(self, torrent_hash):
        payload = self.request(f"/api/v2/torrents/files?hash={urllib.parse.quote(torrent_hash)}", timeout=10)[2]
        return json.loads(payload.decode("utf-8"))

    def pause(self, torrent_hash):
        self.request("/api/v2/torrents/stop", {"hashes": torrent_hash})

    def resume(self, torrent_hash):
        self.request("/api/v2/torrents/start", {"hashes": torrent_hash})

    def remove_without_files(self, torrent_hash):
        self.request("/api/v2/torrents/delete", {"hashes": torrent_hash, "deleteFiles": "false"})

    def shutdown(self):
        self.request("/api/v2/app/shutdown", fields={})


class QBittorrentManager:
    _release_cache = {}
    _release_cache_lock = threading.Lock()

    def __init__(self, user_data_dir, settings, library_roots, app_root=None):
        self.user_data_dir = Path(user_data_dir)
        self.app_root = Path(app_root) if app_root else Path(__file__).resolve().parent.parent
        self.settings = dict(settings or {})
        self.library_roots = list(library_roots or [])
        self.root = self.user_data_dir / "qbittorrent"
        self.versions_dir = self.root / "versions"
        self.profile_dir = self.root / "profile"
        self.staging_dir = Path(self.settings.get("incomplete_dir") or (self.root / "incomplete"))
        self.state_file = self.root / "runtime.json"
        self.jobs = QBittorrentJobStore(self.root / "jobs.json")
        self.port = int(self.settings.get("webui_port") or DEFAULT_WEBUI_PORT)
        self.client = QBittorrentClient(f"http://127.0.0.1:{self.port}")
        self._process = None
        self._completion_lock = threading.Lock()
        self._update_lock = threading.Lock()

    @property
    def destination(self):
        return Path(self.settings.get("download_dir") or (self.library_roots[0] if self.library_roots else ""))

    def configuration(self):
        destination = str(self.destination) if str(self.destination) != "." else ""
        incomplete = str(self.staging_dir)
        return {
            "mode": self.settings.get("mode", "embedded"),
            "download_dir": self.settings.get("download_dir", ""),
            "effective_download_dir": destination,
            "download_dir_in_library": bool(destination_library_root(destination, self.library_roots)) if destination else False,
            "incomplete_dir": self.settings.get("incomplete_dir", ""),
            "effective_incomplete_dir": incomplete,
            "incomplete_dir_in_library": any(is_path_within(incomplete, root) for root in self.library_roots),
            "webui_port": self.port,
        }

    def _runtime_state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_runtime_state(self, data):
        _atomic_json_write(self.state_file, data)

    def active_executable(self):
        state = self._runtime_state()
        path = Path(state.get("executable", ""))
        if path.is_file():
            return path
        if normalize_system() == "windows":
            bundled = bundled_runtime_root(self.app_root) / "qbittorrent.exe"
            if bundled.is_file():
                return bundled
        return None

    def _github_release(self, url):
        with self._release_cache_lock:
            cached = self._release_cache.get(url)
            if cached and (time.time() - cached["time"]) < 900:
                return cached["data"]
        request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "Cinema-Paradiso"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        with self._release_cache_lock:
            self._release_cache[url] = {"time": time.time(), "data": data}
        return data

    @staticmethod
    def _download_verified(asset, destination):
        expected = str(asset.get("digest", ""))
        if not expected.startswith("sha256:"):
            raise QBittorrentError("Official release asset did not provide a SHA-256 digest")
        request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "Cinema-Paradiso"})
        digest = hashlib.sha256()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(request, timeout=120) as response, open(destination, "wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest().lower() != expected.split(":", 1)[1].lower():
            destination.unlink(missing_ok=True)
            raise QBittorrentError("Downloaded release failed SHA-256 verification")
        return destination

    def latest_release(self):
        release = self._github_release(QBT_RELEASES_API)
        asset = select_release_asset(release.get("assets", []))
        if not asset:
            raise QBittorrentError("No official qBittorrent build is available for this OS and CPU architecture")
        return {"version": str(release.get("tag_name", "")).removeprefix("release-"), "asset": asset}

    def _windows_extract(self, package, destination):
        tools = self.root / "tools" / "7zip"
        seven = tools / "7z.exe"
        if not seven.exists():
            release = self._github_release(SEVEN_ZIP_RELEASES_API)
            assets = {asset.get("name"): asset for asset in release.get("assets", [])}
            compact = next((asset for name, asset in assets.items() if name == "7zr.exe"), None)
            installer = next((asset for name, asset in assets.items() if re.fullmatch(r"7z\d+-x64\.exe", name or "")), None)
            if not compact or not installer:
                raise QBittorrentError("Official 7-Zip extraction tools were not available")
            tools.mkdir(parents=True, exist_ok=True)
            seven_r = self._download_verified(compact, tools / "7zr.exe")
            seven_installer = self._download_verified(installer, tools / installer["name"])
            subprocess.run([str(seven_r), "x", str(seven_installer), f"-o{tools}", "-y"], check=True, capture_output=True)
        subprocess.run([str(seven), "x", str(package), f"-o{destination}", "-y"], check=True, capture_output=True)
        plugin_dir = destination / "$PLUGINSDIR"
        if plugin_dir.exists():
            shutil.rmtree(plugin_dir)
        executable = destination / "qbittorrent.exe"
        if not executable.exists():
            raise QBittorrentError("Extracted qBittorrent executable was not found")
        return executable

    def _mac_extract(self, package, destination):
        mount = Path(tempfile.mkdtemp(prefix="cp-qbt-dmg-"))
        try:
            subprocess.run(["hdiutil", "attach", str(package), "-mountpoint", str(mount), "-nobrowse", "-readonly"], check=True, capture_output=True)
            app = next(mount.glob("*.app"), None)
            if not app:
                raise QBittorrentError("qBittorrent app was not found in the DMG")
            target = destination / app.name
            shutil.copytree(app, target)
            return target / "Contents" / "MacOS" / "qbittorrent"
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=False, capture_output=True)
            shutil.rmtree(mount, ignore_errors=True)

    def _stop_running(self):
        try:
            self.client.shutdown()
        except Exception:
            return
        for _ in range(40):
            time.sleep(0.25)
            try:
                self.client.version()
            except Exception:
                return
        raise QBittorrentError("Embedded qBittorrent did not stop for the update")

    def shutdown(self):
        """Stop the CP-managed qBittorrent process after its state is checkpointed."""
        if self.settings.get("mode", "embedded") != "embedded":
            raise QBittorrentError("Cinema Paradiso cannot stop a system-managed qBittorrent client")
        self._stop_running()

    def _restore_runtime_state(self, state):
        if state:
            self._save_runtime_state(state)
        else:
            self.state_file.unlink(missing_ok=True)

    def update_latest(self):
        if not self._update_lock.acquire(blocking=False):
            raise QBittorrentError("A qBittorrent update is already running")
        staging = None
        package = None
        try:
            release = self.latest_release()
            version = str(release.get("version") or "").strip()
            if not version:
                raise QBittorrentError("The latest qBittorrent release has no version")
            current_status = self.status()
            current_version = str(current_status.get("version") or "").strip()
            if current_version == version:
                return {
                    **current_status,
                    "latest_version": version,
                    "update_available": False,
                    "update_result": "current",
                }

            destination = self.versions_dir / version
            staging = self.versions_dir / f".{version}.{uuid.uuid4().hex}.staging"
            staging.mkdir(parents=True, exist_ok=False)
            package = self.root / "downloads" / release["asset"]["name"]
            self._download_verified(release["asset"], package)
            system = normalize_system()
            if system == "windows":
                staged_executable = self._windows_extract(package, staging)
            elif system == "darwin":
                staged_executable = self._mac_extract(package, staging)
            elif system == "linux":
                staged_executable = staging / release["asset"]["name"]
                shutil.copy2(package, staged_executable)
                staged_executable.chmod(staged_executable.stat().st_mode | 0o111)
            else:
                raise QBittorrentError("Unsupported operating system")
            relative_executable = staged_executable.relative_to(staging)
            previous_state = self._runtime_state()

            with self._completion_lock:
                self._stop_running()
                if destination.exists():
                    shutil.rmtree(destination)
                staging.replace(destination)
                staging = None
                executable = destination / relative_executable
                self._save_runtime_state({
                    "version": version,
                    "executable": str(executable),
                    "previous": previous_state,
                    "updated_at": time.time(),
                })
                try:
                    if not self.ensure_running():
                        raise QBittorrentError("Updated qBittorrent did not start")
                    running_version = self.client.version().lstrip("v")
                    if running_version != version:
                        raise QBittorrentError(
                            f"Updated qBittorrent reported version {running_version or 'unknown'} instead of {version}"
                        )
                except Exception as error:
                    try:
                        self._stop_running()
                    except Exception:
                        pass
                    self._restore_runtime_state(previous_state)
                    try:
                        self.ensure_running()
                    except Exception as rollback_error:
                        raise QBittorrentError(
                            f"qBittorrent update failed and the previous runtime could not restart: {rollback_error}"
                        ) from error
                    raise QBittorrentError(f"qBittorrent update failed; the previous runtime was restored: {error}") from error

            return {
                **self.status(),
                "latest_version": version,
                "update_available": False,
                "update_result": "updated",
                "previous_version": current_version,
            }
        except QBittorrentError:
            raise
        except Exception as error:
            raise QBittorrentError(f"qBittorrent update failed: {error}") from error
        finally:
            if staging and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if package:
                package.unlink(missing_ok=True)
            self._update_lock.release()

    def _write_profile(self):
        config_dir = self.profile_dir / "qBittorrent" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        if any(is_path_within(self.staging_dir, root) for root in self.library_roots):
            raise QBittorrentError("Incomplete downloads folder must be outside every movie library")
        salt = b"CinemaParadisoQB"
        key = hashlib.pbkdf2_hmac("sha512", b"cinema-paradiso-local", salt, 100000, dklen=64)
        password = f"{base64.b64encode(salt).decode()}:{base64.b64encode(key).decode()}"
        config = (
            "[LegalNotice]\nAccepted=true\n\n[Preferences]\n"
            "General\\NoSplashScreen=true\nGeneral\\StartMinimized=true\n"
            "WebUI\\Address=127.0.0.1\nWebUI\\CSRFProtection=true\n"
            "WebUI\\ClickjackingProtection=true\nWebUI\\Enabled=true\n"
            "WebUI\\HostHeaderValidation=true\nWebUI\\LocalHostAuth=false\n"
            f'WebUI\\Password_PBKDF2="@ByteArray({password})"\n'
            f"WebUI\\Port={self.port}\nWebUI\\SecureCookie=false\n"
            "WebUI\\ServerDomains=127.0.0.1,localhost\nWebUI\\UseUPnP=false\n"
            "WebUI\\Username=admin\n"
        )
        (config_dir / "qBittorrent.ini").write_text(config, encoding="utf-8")

    def ensure_running(self):
        try:
            self.client.version()
            return True
        except Exception:
            pass
        executable = self.active_executable()
        if not executable:
            return False
        self._write_profile()
        args = [str(executable), f"--profile={self.profile_dir}", f"--webui-port={self.port}", "--no-splash"]
        self._process = subprocess.Popen(args, **process_launch_kwargs())
        for _ in range(60):
            time.sleep(0.25)
            try:
                self.client.version()
                hide_process_windows(getattr(self._process, "pid", 0))
                return True
            except Exception:
                continue
        raise QBittorrentError("Embedded qBittorrent did not start")

    def status(self):
        installed = bool(self.active_executable())
        running = False
        version = self._runtime_state().get("version", "")
        if installed:
            try:
                version = self.client.version().lstrip("v")
                running = True
            except Exception:
                running = False
            if not version:
                version = BUNDLED_QBT_VERSION
        latest = ""
        update_available = False
        supported = platform_is_supported()
        return {
            **self.configuration(),
            "installed": installed,
            "running": running,
            "version": version,
            "latest_version": latest,
            "update_available": update_available,
            "update_policy": "manual_github",
            "supported": supported,
        }

    def _submission_patch(self, metadata, source_type, submitted_at, *, resubmitted=False):
        return {
            **(metadata or {}),
            "state": "downloading",
            "destination": str(self.destination),
            "submitted_at": submitted_at,
            "resubmitted_at": submitted_at if resubmitted else None,
            "source_type": source_type,
            "payload_paths": [],
            "imported_paths": [],
            "deduplicated_paths": [],
            "transfer_plan": [],
            "resolved_targets": {},
            "collision": [],
            "library_scan_pending": False,
            "missing_since": None,
            "missing_checks": 0,
            "cancelled_at": None,
            "abandoned_at": None,
            "terminal_reason": "",
            "last_error": "",
        }

    @staticmethod
    def _expected_info_hash(metadata, magnet=""):
        return normalize_torrent_info_hash((metadata or {}).get("expected_info_hash")) or magnet_hash(magnet)

    def _queue_magnet_validation(self, magnet, metadata, *, existing=None):
        torrent_hash = self._expected_info_hash(metadata, magnet)
        if not torrent_hash:
            raise QBittorrentError("Magnet does not contain a usable torrent identity")
        now = time.time()
        self.client.add_magnet(magnet, str(self.staging_dir), stop_after_metadata=True)
        queued = self._submission_patch(metadata, "magnet", now, resubmitted=bool(existing))
        queued.update({
            "state": "validating",
            "validation_mode": "stopped_after_metadata",
            "validation_started_at": now,
            "validation_last_checked_at": now,
            "validation_attempts": 1,
            "last_error": "Waiting for qBittorrent to resolve the magnet metadata",
        })
        return self.jobs.upsert(torrent_hash, queued)

    def _process_pending_magnet_validation(self, torrent_hash, job, torrent):
        now = time.time()
        started_at = float(job.get("validation_started_at") or now)
        attempts = int(job.get("validation_attempts") or 0) + 1
        if now - started_at >= TORRENT_METADATA_MAX_WAIT_SECONDS:
            return self.jobs.upsert(torrent_hash, {
                "state": "validation_failed",
                "validation_last_checked_at": now,
                "validation_attempts": attempts,
                "last_error": "qBittorrent could not resolve the magnet metadata within 15 minutes",
            })
        if not torrent:
            return self.jobs.upsert(torrent_hash, {
                "validation_last_checked_at": now,
                "validation_attempts": attempts,
                "last_error": "Waiting for qBittorrent to add the magnet",
            })
        try:
            files = self.client.files(torrent_hash)
            if not files:
                return self.jobs.upsert(torrent_hash, {
                    "validation_last_checked_at": now,
                    "validation_attempts": attempts,
                    "last_error": "Waiting for qBittorrent to resolve the magnet metadata",
                })
            manifest = validate_torrent_manifest({
                "hash": torrent_hash,
                "info": {
                    "name": str(torrent.get("name") or ""),
                    "files": [{"path": item.get("name"), "length": item.get("size")} for item in files],
                },
            }, job.get("expected_size"), torrent_hash)
        except TorrentValidationError as error:
            cleanup_error = ""
            try:
                self.client.remove_without_files(torrent_hash)
            except (QBittorrentError, OSError) as cleanup:
                cleanup_error = f" qBittorrent cleanup failed: {cleanup}"
            return self.jobs.upsert(torrent_hash, {
                "state": "validation_failed",
                "validation_last_checked_at": now,
                "validation_attempts": attempts,
                "last_error": f"{error}{cleanup_error}",
            })
        except (QBittorrentError, OSError) as error:
            return self.jobs.upsert(torrent_hash, {
                "validation_last_checked_at": now,
                "validation_attempts": attempts,
                "last_error": f"Waiting for qBittorrent to resolve the magnet metadata: {error}",
            })
        try:
            self.client.resume(torrent_hash)
            return self.jobs.upsert(torrent_hash, {
                **self._submission_patch(
                    {**job, "validated_manifest": {**manifest, "checked_at": now}},
                    "magnet",
                    float(job.get("submitted_at") or now),
                    resubmitted=bool(job.get("resubmitted_at")),
                ),
                "validation_mode": None,
                "validation_started_at": None,
                "validation_last_checked_at": now,
                "validation_attempts": attempts,
            })
        except (QBittorrentError, OSError) as error:
            return self.jobs.upsert(torrent_hash, {
                "validation_last_checked_at": now,
                "validation_attempts": attempts,
                "last_error": str(error),
            })

    def submit_magnet(self, magnet, metadata):
        if not validate_magnet_url(magnet):
            raise QBittorrentError("Invalid magnet link")
        metadata = {
            **(metadata or {}),
            "expected_info_hash": self._expected_info_hash(metadata, magnet),
        }
        torrent_hash = metadata["expected_info_hash"]
        existing = self.jobs.get(torrent_hash)
        if existing and existing.get("state") == "imported":
            return {**existing, "already_exists": True}
        if existing and existing.get("state") == "validating":
            return {**existing, "already_exists": True}
        if not self.ensure_running():
            raise QBittorrentError("Embedded qBittorrent is not installed")
        if existing and torrent_hash:
            active_hashes = {
                str(item.get("hash", "")).lower()
                for item in self.client.torrents()
            }
            if torrent_hash in active_hashes:
                return {**existing, "already_exists": True}
            recoverable_paths = [
                *existing.get("payload_paths", []),
                *existing.get("imported_paths", []),
                *[
                    value
                    for collision in existing.get("collision", [])
                    for value in (collision.get("source"), collision.get("target"))
                    if value
                ],
            ]
            if any(Path(path).exists() for path in recoverable_paths):
                return {**existing, "already_exists": True, "recovery_pending": True}
        return self._queue_magnet_validation(magnet, metadata, existing=existing)

    def submit_torrent(self, content, filename, metadata):
        if not content or not str(filename or "").lower().endswith(".torrent"):
            raise QBittorrentError("Invalid torrent file")
        if not self.ensure_running():
            raise QBittorrentError("Embedded qBittorrent is not installed")
        manifest = validate_torrent_manifest(
            self.client.parse_torrent_metadata(content, filename),
            (metadata or {}).get("expected_size"),
            (metadata or {}).get("expected_info_hash"),
        )
        before = {item.get("hash") for item in self.client.torrents()}
        self.client.add_torrent(content, filename, str(self.staging_dir))
        torrent_hash = ""
        for _ in range(20):
            time.sleep(0.2)
            after = self.client.torrents()
            added = [item for item in after if item.get("hash") not in before]
            if added:
                torrent_hash = str(added[0].get("hash", ""))
                break
        if not torrent_hash:
            raise QBittorrentError("qBittorrent accepted the torrent but its hash could not be identified")
        submitted_at = time.time()
        return self.jobs.upsert(
            torrent_hash,
            self._submission_patch(
                {**(metadata or {}), "validated_manifest": {**manifest, "checked_at": submitted_at}},
                "torrent",
                submitted_at,
                resubmitted=bool(self.jobs.get(torrent_hash)),
            ),
        )

    def _payload_paths(self, torrent, files):
        save_path = Path(torrent.get("save_path") or self.staging_dir)
        names = [str(item.get("name", "")).replace("\\", "/").strip("/") for item in files if item.get("name")]
        if len(names) == 1 and "/" not in names[0]:
            return [str(save_path / names[0])]
        top_levels = []
        for name in names:
            top = name.split("/", 1)[0]
            if top and top not in top_levels:
                top_levels.append(top)
        return [str(save_path / top) for top in top_levels]

    @staticmethod
    def _collision_is_unchanged(job):
        collisions = job.get("collision") or []
        return job.get("collision_rule_version") == PAYLOAD_COLLISION_RULE_VERSION \
            and bool(collisions) and all(
            _payload_signature(item.get("source", "")) == item.get("source_signature")
            and _payload_signature(item.get("target", "")) == item.get("target_signature")
            for item in collisions
        )

    def _finish_completed_import(self, torrent_hash, torrent_present):
        if torrent_present:
            try:
                self.client.remove_without_files(torrent_hash)
            except Exception as error:
                return self.jobs.upsert(torrent_hash, {
                    "state": "cleanup_failed",
                    "last_error": f"Payload imported, but qBittorrent cleanup failed: {error}",
                })
        return self.jobs.upsert(torrent_hash, {"state": "imported", "last_error": ""})

    @staticmethod
    def _recoverable_job_paths(job):
        paths = [
            *(job.get("payload_paths") or []),
            *(job.get("imported_paths") or []),
        ]
        for transfer in job.get("transfer_plan") or []:
            paths.extend((transfer.get("source"), transfer.get("target")))
        for collision in job.get("collision") or []:
            paths.extend((collision.get("source"), collision.get("target")))
        return [Path(path) for path in paths if path]

    @classmethod
    def _has_recoverable_job_path(cls, job):
        return any(path.exists() for path in cls._recoverable_job_paths(job))

    def _mark_missing_job(self, torrent_hash, job, now):
        state = str(job.get("state") or "")
        if state not in {"downloading", "finalizing", "moving", "move_failed", "destination_conflict"}:
            return None
        if self._has_recoverable_job_path(job):
            return None

        missing_since = float(job.get("missing_since") or 0)
        missing_checks = int(job.get("missing_checks") or 0) + 1
        if not missing_since:
            self.jobs.upsert(torrent_hash, {
                "missing_since": now,
                "missing_checks": 1,
            })
            return None
        if missing_checks < MISSING_TORRENT_MIN_CHECKS or now - missing_since < MISSING_TORRENT_GRACE_SECONDS:
            self.jobs.upsert(torrent_hash, {"missing_checks": missing_checks})
            return None

        if state == "downloading":
            return self.jobs.upsert(torrent_hash, {
                "state": "cancelled",
                "cancelled_at": now,
                "terminal_reason": "Removed from qBittorrent before completion",
                "identity_handoff": {
                    "state": "not_required",
                    "reason": "Download was cancelled before import",
                    "paths": [],
                },
                "last_error": "",
            })
        return self.jobs.upsert(torrent_hash, {
            "state": "abandoned",
            "abandoned_at": now,
            "terminal_reason": "qBittorrent and the completed payload are no longer available",
            "last_error": "",
        })

    def _reactivate_terminal_job(self, torrent_hash, job):
        handoff = dict(job.get("identity_handoff") or {})
        if job.get("tmdb_id") or job.get("imdb_id"):
            handoff = {"state": "pending"}
        return self.jobs.upsert(torrent_hash, {
            "state": "downloading",
            "missing_since": None,
            "missing_checks": 0,
            "cancelled_at": None,
            "abandoned_at": None,
            "terminal_reason": "",
            "identity_handoff": handoff,
            "last_error": "",
        })

    def process_completed(self):
        with self._completion_lock:
            return self._process_completed_locked()

    def _process_completed_locked(self):
        if not self.ensure_running():
            return []
        jobs = self.jobs.all()
        torrents = {str(item.get("hash", "")).lower(): item for item in self.client.torrents()}
        results = []
        for torrent_hash, job in jobs.items():
            torrent = torrents.get(torrent_hash)
            if job.get("state") == "validating":
                results.append(self._process_pending_magnet_validation(torrent_hash, job, torrent))
                continue
            if job.get("state") in {"cancelled", "abandoned"}:
                if not torrent:
                    continue
                job = self._reactivate_terminal_job(torrent_hash, job)
            if job.get("state") == "imported":
                handoff_state = str((job.get("identity_handoff") or {}).get("state") or "")
                if job.get("library_scan_pending") or not handoff_state:
                    results.append(job)
                continue
            if torrent and (job.get("missing_since") or job.get("missing_checks")):
                job = self.jobs.upsert(torrent_hash, {
                    "missing_since": None,
                    "missing_checks": 0,
                })
            if job.get("state") in {"payload_imported", "cleanup_failed"}:
                results.append(self._finish_completed_import(torrent_hash, bool(torrent)))
                continue
            if job.get("state") == "destination_conflict" and self._collision_is_unchanged(job):
                results.append(job)
                continue
            if not torrent and job.get("payload_paths") and self._has_recoverable_job_path(job) and job.get("state") in {
                "finalizing", "moving", "move_failed", "destination_conflict",
            }:
                try:
                    result = self.jobs.move_completed_payload(torrent_hash, self.staging_dir)
                    if result.get("state") == "payload_imported":
                        result = self._finish_completed_import(torrent_hash, False)
                    results.append(result)
                except Exception as error:
                    results.append(self.jobs.upsert(torrent_hash, {"state": "move_failed", "last_error": str(error)}))
                continue
            if not torrent:
                missing_result = self._mark_missing_job(torrent_hash, job, time.time())
                if missing_result:
                    results.append(missing_result)
                continue
            if float(torrent.get("progress", 0)) < 1:
                continue
            try:
                files = self.client.files(torrent_hash)
                payload_paths = self._payload_paths(torrent, files)
                self.jobs.upsert(torrent_hash, {"state": "finalizing", "payload_paths": payload_paths})
                self.client.pause(torrent_hash)
                result = self.jobs.move_completed_payload(torrent_hash, self.staging_dir)
                if result.get("state") == "payload_imported":
                    result = self._finish_completed_import(torrent_hash, True)
                results.append(result)
            except Exception as error:
                results.append(self.jobs.upsert(torrent_hash, {"state": "move_failed", "last_error": str(error)}))
        return results

    def proxy(self, path, method="GET", headers=None, body=None):
        if not self.ensure_running():
            raise QBittorrentError("Embedded qBittorrent is not running")
        upstream = f"http://127.0.0.1:{self.port}"
        request = urllib.request.Request(
            f"{upstream}/{str(path or '').lstrip('/')}",
            data=body,
            headers=proxy_request_headers(headers or {}, upstream),
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        return response.status, response.headers, response.read()
