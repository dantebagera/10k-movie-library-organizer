import base64
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .iptv_store import IPTVStore
from .iptv_xtream import XtreamClient, XtreamError, normalize_server_url


def _decode_epg(value):
    text = str(value or "")
    if not text:
        return ""
    try:
        decoded = base64.b64decode(text, validate=True).decode("utf-8")
        return decoded if decoded else text
    except (ValueError, UnicodeDecodeError):
        return text


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class IPTVService:
    ORPHANED_PLAYBACK_MAX_AGE = 24 * 60 * 60

    def __init__(self, provider_root, provider_id, ffmpeg_path=None):
        self.provider_id = str(provider_id or "")
        if not self.provider_id:
            raise ValueError("An IPTV provider ID is required")
        self.root = Path(provider_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "provider.json"
        self.store = IPTVStore(self.root / "iptv.sqlite")
        self.image_cache = self.root / "images"
        self.playback_root = self.root / "playback"
        self.image_cache.mkdir(exist_ok=True)
        self.playback_root.mkdir(exist_ok=True)
        self._cleanup_orphaned_playback_directories()
        self.ffmpeg_path = self._find_ffmpeg(ffmpeg_path)
        self._sync_lock = threading.RLock()
        self._sync_state = {"state": "idle", "phase": "", "error": "", "started_at": 0, "finished_at": 0}
        self._sessions = {}
        self._session_lock = threading.RLock()

    def _cleanup_orphaned_playback_directories(self, max_age=None):
        cutoff = time.time() - max(60, int(max_age or self.ORPHANED_PLAYBACK_MAX_AGE))
        removed = 0
        for candidate in self.playback_root.iterdir():
            try:
                if candidate.is_dir() and candidate.stat().st_mtime < cutoff:
                    shutil.rmtree(candidate)
                    removed += 1
            except OSError:
                continue
        return removed

    def _find_ffmpeg(self, explicit):
        candidates = [
            explicit,
            os.environ.get("CP_FFMPEG_PATH"),
            Path(__file__).resolve().parents[1] / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe",
            shutil.which("ffmpeg"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return str(Path(candidate).resolve())
        return ""

    def _load_config(self):
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def public_config(self):
        config = self._load_config()
        username = str(config.get("username") or "")
        server_url = str(config.get("server_url") or "")
        return {
            "server_url": server_url,
            "username_hint": (f"{username[:2]}{'*' * max(2, len(username) - 4)}{username[-2:]}" if len(username) > 4 else "Configured") if username else "",
            "has_username": bool(username),
            "has_password": bool(config.get("password")),
            "allow_insecure_tls": bool(config.get("allow_insecure_tls")),
            "configured": bool(server_url and username and config.get("password")),
        }

    def save_config(self, server_url, username="", password="", allow_insecure_tls=None, clear=False):
        if clear:
            try:
                self.config_path.unlink()
            except FileNotFoundError:
                pass
            return self.public_config()
        current = self._load_config()
        normalized = normalize_server_url(server_url or current.get("server_url"))
        next_config = {
            "server_url": normalized,
            "username": str(username or current.get("username") or "").strip(),
            "password": str(password or current.get("password") or ""),
            "allow_insecure_tls": bool(current.get("allow_insecure_tls") if allow_insecure_tls is None else allow_insecure_tls),
        }
        if not next_config["username"] or not next_config["password"]:
            raise ValueError("Xtream username and password are required")
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(next_config, indent=2), encoding="utf-8")
        os.replace(temporary, self.config_path)
        return self.public_config()

    def client(self):
        config = self._load_config()
        if not config.get("server_url") or not config.get("username") or not config.get("password"):
            raise ValueError("Configure an Xtream provider in Settings first")
        return XtreamClient(
            config["server_url"],
            config["username"],
            config["password"],
            verify_tls=not bool(config.get("allow_insecure_tls")),
        )

    def _redact(self, value):
        message = str(value or "")
        config = self._load_config()
        for secret in (config.get("username"), config.get("password")):
            if secret:
                message = message.replace(str(secret), "[redacted]")
        message = re.sub(r"(?i)(username|password)=([^&\s]+)", r"\1=[redacted]", message)
        return message

    def provider_key(self):
        config = self._load_config()
        server_url = str(config.get("server_url") or "")
        username = str(config.get("username") or "")
        if not server_url or not username:
            raise ValueError("Configure an Xtream provider in Settings first")
        identity = json.dumps({"server_url": normalize_server_url(server_url), "username": username}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def list_items(self, kind, **options):
        return self.store.list_items(kind, provider_key=self.provider_key(), **options)

    def list_favorites(self, **options):
        return self.store.list_favorites(provider_key=self.provider_key(), **options)

    def set_favorite(self, kind, item_id, favorite):
        return self.store.set_favorite(kind, item_id, favorite, provider_key=self.provider_key())

    def lists(self, **options):
        return self.store.lists(self.provider_key(), **options)

    def create_list(self, name):
        return self.store.create_list(self.provider_key(), name)

    def rename_list(self, list_id, name):
        return self.store.rename_list(self.provider_key(), list_id, name)

    def delete_list(self, list_id):
        return self.store.delete_list(self.provider_key(), list_id)

    def list_entries(self, list_id, **options):
        return self.store.list_entries(self.provider_key(), list_id, **options)

    def set_list_item(self, list_id, kind, item_id, included):
        if included:
            return self.store.add_list_item(self.provider_key(), list_id, kind, item_id)
        return self.store.remove_list_item(self.provider_key(), list_id, kind, item_id)

    def move_list_item(self, list_id, kind, item_id, direction):
        return self.store.move_list_item(self.provider_key(), list_id, kind, item_id, direction)

    def recent(self, limit=12):
        return self.store.recent(limit, provider_key=self.provider_key())

    def test_connection(self):
        payload = self.client().authenticate()
        user = payload.get("user_info", {})
        server = payload.get("server_info", {})
        return {
            "connected": True,
            "status": str(user.get("status") or "Active"),
            "expires_at": str(user.get("exp_date") or ""),
            "server_timezone": str(server.get("timezone") or ""),
        }

    def status(self):
        self.cleanup_playback_sessions()
        with self._sync_lock:
            sync = dict(self._sync_state)
        return {
            "provider_id": self.provider_id,
            **self.public_config(),
            **self.store.status(),
            "sync": sync,
            "playback": {"ffmpeg_available": bool(self.ffmpeg_path)},
        }

    def start_sync(self):
        with self._sync_lock:
            if self._sync_state["state"] == "running":
                return False
            self._sync_state = {"state": "running", "phase": "Authenticating", "error": "", "started_at": time.time(), "finished_at": 0}
        threading.Thread(target=self._sync_worker, name="cp-iptv-sync", daemon=True).start()
        return True

    def _set_sync_phase(self, phase):
        with self._sync_lock:
            self._sync_state["phase"] = phase

    def _sync_worker(self):
        try:
            client = self.client()
            client.authenticate()
            catalog = {}
            steps = (
                ("live", "Loading live television", client.live_categories, client.live_streams),
                ("movie", "Loading movies", client.movie_categories, client.movies),
                ("series", "Loading series", client.series_categories, client.series),
            )
            for kind, phase, categories, items in steps:
                self._set_sync_phase(phase)
                catalog[kind] = {"categories": categories(), "items": items()}
            self._set_sync_phase("Saving IPTV catalog")
            self.store.replace_catalog(catalog)
            with self._sync_lock:
                self._sync_state.update({"state": "complete", "phase": "", "finished_at": time.time()})
        except Exception as error:
            message = self._redact(error)
            with self._sync_lock:
                self._sync_state.update({"state": "error", "phase": "", "error": message[:300], "finished_at": time.time()})

    def detail(self, kind, item_id):
        if kind not in {"movie", "series"}:
            raise ValueError("Details are available for movies and series")
        item = self.store.get_item(kind, item_id, provider_key=self.provider_key())
        if not item:
            raise KeyError("IPTV item was not found")
        cached = self.store.get_cached_detail(kind, item_id)
        if cached is None:
            cached = self.client().movie_info(item_id) if kind == "movie" else self.client().series_info(item_id)
            self.store.cache_detail(kind, item_id, cached)
        return self._normalize_movie_detail(item, cached) if kind == "movie" else self._normalize_series_detail(item, cached)

    @staticmethod
    def _normalize_movie_detail(item, payload):
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        movie = payload.get("movie_data") if isinstance(payload.get("movie_data"), dict) else {}
        merged = {**item}
        mapping = {
            "name": info.get("name") or movie.get("name"),
            "plot": info.get("plot") or info.get("description"),
            "cast_names": info.get("cast"),
            "director": info.get("director"),
            "genre": info.get("genre"),
            "duration": info.get("duration"),
            "year": info.get("year") or info.get("releasedate"),
            "rating": info.get("rating") or info.get("rating_5based"),
            "tmdb_id": info.get("tmdb_id") or info.get("tmdb"),
            "container_extension": movie.get("container_extension"),
        }
        for key, value in mapping.items():
            if value not in (None, ""):
                merged[key] = value
        backdrops = info.get("backdrop_path") or []
        if backdrops:
            merged["backdrop_url"] = backdrops[0] if isinstance(backdrops, list) else backdrops
        return merged

    @staticmethod
    def _normalize_series_detail(item, payload):
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        seasons = payload.get("seasons") if isinstance(payload.get("seasons"), list) else []
        episodes_payload = payload.get("episodes") if isinstance(payload.get("episodes"), dict) else {}
        episodes = []
        for season_key, season_rows in episodes_payload.items():
            for row in season_rows if isinstance(season_rows, list) else []:
                if not isinstance(row, dict):
                    continue
                episode_info = row.get("info") if isinstance(row.get("info"), dict) else {}
                episodes.append({
                    "id": str(row.get("id") or ""),
                    "season": _safe_int(row.get("season") or season_key),
                    "episode": _safe_int(row.get("episode_num")),
                    "title": str(row.get("title") or f"Episode {row.get('episode_num') or ''}").strip(),
                    "plot": str(episode_info.get("plot") or ""),
                    "duration": str(episode_info.get("duration") or ""),
                    "image_url": str(episode_info.get("movie_image") or episode_info.get("cover_big") or ""),
                    "container_extension": str(row.get("container_extension") or "mp4"),
                })
        merged = {**item}
        for key, value in {
            "name": info.get("name"), "plot": info.get("plot"), "cast_names": info.get("cast"),
            "director": info.get("director"), "genre": info.get("genre"), "year": info.get("releaseDate"),
            "rating": info.get("rating"),
        }.items():
            if value not in (None, ""):
                merged[key] = value
        merged["seasons"] = seasons
        merged["episodes"] = episodes
        return merged

    def epg(self, stream_id, limit=4):
        listings = self.client().short_epg(stream_id, limit)
        return [{**row, "title": _decode_epg(row.get("title")), "description": _decode_epg(row.get("description"))} for row in listings]

    def cached_image(self, kind, item_id, backdrop=False):
        url = self.store.image_url(kind, item_id, backdrop=backdrop)
        if not url:
            raise FileNotFoundError("IPTV image was not found")
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Provider image URL is invalid")
        provider_host = urllib.parse.urlsplit(str(self._load_config().get("server_url") or "")).hostname
        image_host = parsed.hostname
        if not image_host:
            raise ValueError("Provider image URL is invalid")
        if image_host.lower() != str(provider_host or "").lower():
            try:
                addresses = {entry[4][0] for entry in socket.getaddrinfo(image_host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
            except socket.gaierror:
                raise ValueError("Provider image host could not be resolved") from None
            for address in addresses:
                ip = ipaddress.ip_address(address)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                    raise ValueError("Provider image URL points to a private network")
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            suffix = ".img"
        target = self.image_cache / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}{suffix}"
        if target.is_file() and target.stat().st_size:
            return target
        request = urllib.request.Request(url, headers={"User-Agent": "Cinema-Paradiso/2.8", "Accept": "image/*"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                content_type = str(response.headers.get("Content-Type") or "")
                if not content_type.startswith("image/"):
                    raise ValueError("Provider returned a non-image response")
                body = response.read(8 * 1024 * 1024 + 1)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise FileNotFoundError(f"Provider image could not be loaded: {getattr(error, 'reason', error)}") from None
        if len(body) > 8 * 1024 * 1024:
            raise ValueError("Provider image exceeds the 8 MB limit")
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_bytes(body)
        os.replace(temporary, target)
        return target

    def start_playback(self, kind, item_id, extension="", title="", local_base_url=""):
        self.cleanup_playback_sessions()
        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg is required for integrated IPTV playback")
        parsed_local = urllib.parse.urlsplit(str(local_base_url or ""))
        if parsed_local.scheme != "http" or parsed_local.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("A loopback playback relay is required")
        store_kind = "series" if kind == "episode" else kind
        if kind != "episode" and not self.store.get_item(store_kind, item_id, provider_key=self.provider_key()):
            raise KeyError("IPTV item was not found")
        source_url = self.client().stream_url(kind, item_id, extension)
        token = uuid.uuid4().hex
        session_dir = self.playback_root / token
        session_dir.mkdir(parents=True, exist_ok=False)
        manifest = session_dir / "index.m3u8"
        live = kind == "live"
        relay_url = (
            f"{str(local_base_url).rstrip('/')}/api/iptv/providers/"
            f"{urllib.parse.quote(self.provider_id, safe='')}/upstream/{token}"
        )
        config = self._load_config()
        session = {
            "token": token,
            "process": None,
            "directory": session_dir,
            "kind": kind,
            "item_id": str(item_id),
            "title": str(title or ""),
            "created_at": time.time(),
            "source_url": source_url,
            "allow_insecure_tls": bool(config.get("allow_insecure_tls")),
            "stopping": False,
        }
        with self._session_lock:
            self._sessions[token] = session
        command = self._hls_command(relay_url, session_dir, manifest, live)
        try:
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except OSError:
            self.stop_playback(token)
            raise RuntimeError("FFmpeg could not be started") from None
        session["process"] = process
        session["stderr_tail"] = ""
        threading.Thread(target=self._drain_process_stderr, args=(session,), name=f"cp-iptv-ffmpeg-{token[:8]}", daemon=True).start()
        deadline = time.time() + 12
        while time.time() < deadline:
            if manifest.is_file() and manifest.stat().st_size:
                return {
                    "token": token,
                    "provider_id": self.provider_id,
                    "manifest_url": (
                        f"/api/iptv/providers/{urllib.parse.quote(self.provider_id, safe='')}"
                        f"/playback/{token}/index.m3u8"
                    ),
                }
            if process.poll() is not None:
                detail = self._redact(str(session.get("stderr_tail") or "")[-500:])
                self.stop_playback(token)
                raise RuntimeError(detail or "FFmpeg could not open this IPTV stream")
            time.sleep(0.2)
        self.stop_playback(token)
        raise RuntimeError("IPTV stream did not start within 12 seconds")

    def _hls_command(self, relay_url, session_dir, manifest, live):
        command = [self.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-nostdin"]
        command.extend([
            "-i", relay_url, "-map", "0:v:0?", "-map", "0:a:0?", "-c", "copy",
            "-f", "hls", "-hls_time", "3" if live else "6",
            "-hls_segment_filename", str(session_dir / "segment-%06d.ts"),
        ])
        if live:
            command.extend([
                "-hls_list_size", "16", "-hls_delete_threshold", "4",
                "-hls_flags", "delete_segments+omit_endlist+split_by_time",
            ])
        else:
            command.extend(["-hls_list_size", "0", "-hls_playlist_type", "event"])
        command.append(str(manifest))
        return command

    @staticmethod
    def _drain_process_stderr(session):
        stream = session.get("process").stderr if session.get("process") else None
        if not stream:
            return
        while True:
            chunk = stream.read(1024)
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            session["stderr_tail"] = (str(session.get("stderr_tail") or "") + text)[-2000:]

    def playback_file(self, token, filename):
        with self._session_lock:
            session = self._sessions.get(token)
        if not session or filename not in {"index.m3u8"} and not (filename.startswith("segment-") and filename.endswith(".ts")):
            raise FileNotFoundError("Playback session was not found")
        path = session["directory"] / filename
        if not path.is_file():
            raise FileNotFoundError("Playback segment is not ready")
        return path

    def open_upstream(self, token, range_header=""):
        with self._session_lock:
            session = self._sessions.get(token)
        if not session:
            raise FileNotFoundError("Playback session was not found")
        headers = {"User-Agent": "Cinema-Paradiso/2.8", "Accept": "*/*"}
        if range_header:
            headers["Range"] = str(range_header)
        request = urllib.request.Request(session["source_url"], headers=headers)
        context = None
        if session.get("allow_insecure_tls"):
            import ssl
            context = ssl._create_unverified_context()
        try:
            return urllib.request.urlopen(request, timeout=30, context=context)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as error:
            raise FileNotFoundError(f"Provider stream could not be opened: {getattr(error, 'reason', error)}") from None

    def stop_playback(self, token):
        with self._session_lock:
            session = self._sessions.get(token)
            if session and session.get("stopping"):
                return False
            if session:
                session["stopping"] = True
        if not session:
            return False
        process = session.get("process")
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    threading.Thread(
                        target=self._finish_stopping_playback,
                        args=(token, session),
                        name=f"cp-iptv-stop-{str(token)[:8]}",
                        daemon=True,
                    ).start()
                    return True
        self._finalize_playback_session(token, session)
        return True

    def _finish_stopping_playback(self, token, session):
        process = session.get("process")
        try:
            if process:
                process.wait()
        finally:
            self._finalize_playback_session(token, session)

    def _finalize_playback_session(self, token, session):
        with self._session_lock:
            if self._sessions.get(token) is session:
                self._sessions.pop(token, None)
        shutil.rmtree(session["directory"], ignore_errors=True)

    def cleanup_playback_sessions(self, max_age=6 * 60 * 60):
        cutoff = time.time() - max(60, int(max_age))
        with self._session_lock:
            stale_tokens = [token for token, session in self._sessions.items() if session.get("created_at", 0) < cutoff]
        for token in stale_tokens:
            self.stop_playback(token)
        return len(stale_tokens)

    def close(self):
        with self._session_lock:
            tokens = list(self._sessions)
        for token in tokens:
            self.stop_playback(token)
