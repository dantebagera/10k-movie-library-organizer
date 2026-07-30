import concurrent.futures
import hashlib
import io
import json
import math
import os
import re
import secrets
import struct
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from difflib import SequenceMatcher
from pathlib import Path, PurePosixPath


SEARCH_TIMEOUT_SECONDS = 10
DOWNLOAD_TIMEOUT_SECONDS = 20
MAX_PROVIDER_RESULTS = 60
MAX_PUBLIC_RESULTS = 40
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_SUBTITLE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 64
MAX_ARCHIVE_EXPANDED_BYTES = 20 * 1024 * 1024
RESULT_TTL_SECONDS = 15 * 60
APPROVED_EXTENSIONS = {".srt", ".ass", ".ssa", ".vtt"}


class SubtitleServiceError(RuntimeError):
    pass


class SubtitleProviderError(SubtitleServiceError):
    def __init__(self, code, *, retry_after=0):
        super().__init__(str(code))
        self.code = str(code)[:64] or "provider_error"
        self.retry_after = max(0, int(retry_after or 0))


def redact_sensitive_text(value):
    text = str(value or "")
    text = re.sub(
        r"(?i)(api[_-]?key|token|authorization|password|username)=([^&\s]+)",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [redacted]", text)
    return text[:512]


def _safe_number(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _language(value):
    return re.sub(r"[^a-z0-9-]", "", str(value or "").strip().lower())[:16] or "und"


def _release_tokens(value):
    return {
        token
        for token in re.split(r"[^a-z0-9]+", str(value or "").lower())
        if len(token) > 1
    }


def opensubtitles_hash(path):
    size = os.path.getsize(path)
    if size < 131072:
        return ""
    value = size
    with open(path, "rb") as handle:
        for block_offset in (0, size - 65536):
            handle.seek(block_offset)
            block = handle.read(65536)
            if len(block) != 65536:
                return ""
            for offset in range(0, 65536, 8):
                value = (value + struct.unpack("<Q", block[offset:offset + 8])[0]) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


class _HttpProvider:
    name = ""

    def __init__(self, credentials, opener):
        self.credentials = dict(credentials or {})
        self.opener = opener

    def _open(self, request, timeout):
        try:
            return self.opener(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            retry = error.headers.get("Retry-After", "0") if error.headers else "0"
            try:
                retry_after = min(max(int(retry), 0), 86400)
            except (TypeError, ValueError):
                retry_after = 60 if error.code == 429 else 0
            code = "rate_limited" if error.code == 429 else f"http_{error.code}"
            raise SubtitleProviderError(code, retry_after=retry_after) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SubtitleProviderError("network_unavailable") from None

    def _json(self, request):
        with self._open(request, SEARCH_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(payload) > MAX_DOWNLOAD_BYTES:
            raise SubtitleProviderError("response_too_large")
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SubtitleProviderError("invalid_response") from None
        if not isinstance(value, dict):
            raise SubtitleProviderError("invalid_response")
        return value

    def _bytes(self, request):
        chunks = []
        total = 0
        with self._open(request, DOWNLOAD_TIMEOUT_SECONDS) as response:
            while True:
                chunk = response.read(min(64 * 1024, MAX_DOWNLOAD_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise SubtitleProviderError("download_too_large")
        return b"".join(chunks)


class OpenSubtitlesProvider(_HttpProvider):
    name = "opensubtitles"
    api_root = "https://api.opensubtitles.com/api/v1"

    def _headers(self, *, json_body=False, token=""):
        headers = {
            "Accept": "application/json",
            "Api-Key": self.credentials.get("api_key", ""),
            "User-Agent": "CinemaParadiso v2.8",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def search(self, identity, languages):
        if not self.credentials.get("api_key"):
            raise SubtitleProviderError("not_configured")
        params = {
            "languages": ",".join(languages),
            "query": identity["title"],
            "year": identity["year"],
            "moviehash": identity["file_hash"],
            "moviebytesize": identity["file_size"],
            "tmdb_id": identity["tmdb_id"],
        }
        imdb = re.sub(r"\D", "", identity["imdb_id"])
        if imdb:
            params["imdb_id"] = imdb
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value not in ("", 0)})
        request = urllib.request.Request(
            f"{self.api_root}/subtitles?{query}",
            headers=self._headers(),
        )
        payload = self._json(request)
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise SubtitleProviderError("invalid_response")
        results = []
        for row in rows[:MAX_PROVIDER_RESULTS]:
            attributes = row.get("attributes") if isinstance(row, dict) else None
            if not isinstance(attributes, dict):
                continue
            files = attributes.get("files") if isinstance(attributes.get("files"), list) else []
            for file_row in files[:3]:
                if not isinstance(file_row, dict) or not file_row.get("file_id"):
                    continue
                feature = attributes.get("feature_details")
                feature = feature if isinstance(feature, dict) else {}
                releases = attributes.get("release")
                if isinstance(releases, str):
                    releases = [releases]
                if not isinstance(releases, list):
                    releases = []
                results.append({
                    "provider": self.name,
                    "provider_ref": {"file_id": str(file_row["file_id"])[:128]},
                    "provider_identity": str(row.get("id") or "")[:128],
                    "language": _language(attributes.get("language")),
                    "release_name": str((releases or [file_row.get("file_name") or ""])[0])[:512],
                    "release_names": [str(value)[:512] for value in releases[:8]],
                    "file_name": str(file_row.get("file_name") or "")[:512],
                    "frame_rate": _safe_number(attributes.get("fps")),
                    "rating": _safe_number(attributes.get("ratings")),
                    "download_count": int(_safe_number(attributes.get("download_count"))),
                    "hearing_impaired": bool(attributes.get("hearing_impaired")),
                    "forced": bool(attributes.get("foreign_parts_only")),
                    "hash_match": bool(attributes.get("moviehash_match")),
                    "imdb_id": str(feature.get("imdb_id") or ""),
                    "tmdb_id": str(feature.get("tmdb_id") or ""),
                    "title": str(feature.get("title") or ""),
                    "year": str(feature.get("year") or ""),
                })
        return results

    def _login_token(self):
        authentication_mode = self.credentials.get(
            "authentication_mode", "api_key_only"
        )
        if authentication_mode == "api_key_only":
            return ""
        if authentication_mode != "account":
            raise SubtitleProviderError("not_configured")
        username = self.credentials.get("username", "")
        password = self.credentials.get("password", "")
        if not username or not password:
            raise SubtitleProviderError("not_configured")
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_root}/login",
            data=body,
            headers=self._headers(json_body=True),
            method="POST",
        )
        token = str(self._json(request).get("token") or "")[:4096]
        if not token:
            raise SubtitleProviderError("authentication_failed")
        return token

    def download(self, provider_ref):
        file_id = str(provider_ref.get("file_id") or "")
        if not file_id:
            raise SubtitleProviderError("invalid_result")
        token = self._login_token()
        body = json.dumps({"file_id": file_id}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_root}/download",
            data=body,
            headers=self._headers(json_body=True, token=token),
            method="POST",
        )
        payload = self._json(request)
        link = str(payload.get("link") or "")
        parsed = urllib.parse.urlsplit(link)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            host == "opensubtitles.com" or host.endswith(".opensubtitles.com")
        ):
            raise SubtitleProviderError("unsafe_download_url")
        download = urllib.request.Request(link, headers={"User-Agent": "CinemaParadiso v2.8"})
        return self._bytes(download), str(payload.get("file_name") or "")


class SubDLProvider(_HttpProvider):
    name = "subdl"
    api_root = "https://api.subdl.com/api/v1/subtitles"

    def search(self, identity, languages):
        api_key = self.credentials.get("api_key", "")
        if not api_key:
            raise SubtitleProviderError("not_configured")
        params = {
            "api_key": api_key,
            "film_name": identity["title"],
            "file_name": identity["filename"],
            "imdb_id": identity["imdb_id"],
            "tmdb_id": identity["tmdb_id"],
            "year": identity["year"],
            "type": "movie",
            "languages": ",".join(language.upper() for language in languages),
            "subs_per_page": 30,
            "releases": 1,
            "hi": 1,
            "unpack": 1,
            "client": "custom_integration",
        }
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value not in ("", 0)})
        request = urllib.request.Request(
            f"{self.api_root}?{query}",
            headers={"Accept": "application/json", "User-Agent": "CinemaParadiso v2.8"},
        )
        payload = self._json(request)
        if payload.get("status") is not True:
            raise SubtitleProviderError("provider_rejected")
        identity_row = (payload.get("results") or [{}])[0]
        identity_row = identity_row if isinstance(identity_row, dict) else {}
        results = []
        for row in (payload.get("subtitles") or [])[:MAX_PROVIDER_RESULTS]:
            if not isinstance(row, dict):
                continue
            unpacked = row.get("unpack_files") if isinstance(row.get("unpack_files"), list) else []
            candidates = unpacked or [row]
            for candidate in candidates[:8]:
                if not isinstance(candidate, dict):
                    continue
                relative_url = str(candidate.get("url") or row.get("url") or "")
                if not relative_url.startswith("/subtitle/"):
                    continue
                releases = candidate.get("releases") or row.get("releases") or []
                if isinstance(releases, str):
                    releases = [releases]
                release_name = str(
                    candidate.get("release_name")
                    or row.get("release_name")
                    or candidate.get("name")
                    or row.get("name")
                    or ""
                )[:512]
                results.append({
                    "provider": self.name,
                    "provider_ref": {"path": relative_url[:1024]},
                    "provider_identity": str(candidate.get("file_n_id") or row.get("n_id") or "")[:128],
                    "language": _language(candidate.get("language") or row.get("lang") or row.get("language")),
                    "release_name": release_name,
                    "release_names": [str(value)[:512] for value in releases[:8]],
                    "file_name": str(candidate.get("name") or row.get("name") or "")[:512],
                    "frame_rate": _safe_number(candidate.get("fps") or row.get("fps")),
                    "rating": _safe_number(candidate.get("rating") or row.get("rating")),
                    "download_count": int(_safe_number(candidate.get("downloads") or row.get("downloads"))),
                    "hearing_impaired": bool(candidate.get("hi", row.get("hi", False))),
                    "forced": bool(candidate.get("forced", row.get("forced", False))),
                    "hash_match": False,
                    "imdb_id": str(identity_row.get("imdb_id") or ""),
                    "tmdb_id": str(identity_row.get("tmdb_id") or ""),
                    "title": str(identity_row.get("name") or ""),
                    "year": str(identity_row.get("year") or ""),
                })
        return results

    def download(self, provider_ref):
        relative = str(provider_ref.get("path") or "")
        if not relative.startswith("/subtitle/") or ".." in PurePosixPath(relative).parts:
            raise SubtitleProviderError("invalid_result")
        url = urllib.parse.urljoin("https://dl.subdl.com/", relative.lstrip("/"))
        headers = {"User-Agent": "CinemaParadiso v2.8"}
        if self.credentials.get("api_key"):
            headers["x-api-key"] = self.credentials["api_key"]
        request = urllib.request.Request(url, headers=headers)
        return self._bytes(request), Path(urllib.parse.urlsplit(relative).path).name


class SubtitleService:
    """Backend authority for subtitle providers, ranking, cache, and diagnostics."""

    def __init__(
        self,
        player_config,
        cache_root_provider,
        *,
        opener=urllib.request.urlopen,
        clock=time.time,
        provider_classes=None,
    ):
        self.player_config = player_config
        self.cache_root_provider = cache_root_provider
        self.opener = opener
        self.clock = clock
        self.provider_classes = provider_classes or {
            "opensubtitles": OpenSubtitlesProvider,
            "subdl": SubDLProvider,
        }
        self._lock = threading.RLock()
        self._results = {}
        self._search_revision = {}
        self._diagnostics = {
            name: {
                "state": "disabled",
                "last_error": "",
                "last_result_count": 0,
                "last_latency_ms": 0,
                "rate_limited_until": 0,
            }
            for name in self.provider_classes
        }

    def diagnostics(self):
        config = self.player_config.storage_payload().get("providers", {})
        with self._lock:
            payload = json.loads(json.dumps(self._diagnostics))
        now = int(self.clock())
        for name, state in payload.items():
            enabled = bool(config.get(name, {}).get("enabled"))
            if not enabled:
                state["state"] = "disabled"
            elif state["rate_limited_until"] > now:
                state["state"] = "rate_limited"
            state["configured"] = bool(
                config.get(name, {}).get("api_key")
            )
        return payload

    def search_async(self, session_id, media, callback):
        with self._lock:
            revision = self._search_revision.get(session_id, 0) + 1
            self._search_revision[session_id] = revision

        def run():
            try:
                payload = self.search(session_id, media)
            except Exception:
                payload = {
                    "status": "error",
                    "results": [],
                    "diagnostics": self.diagnostics(),
                }
            with self._lock:
                current = self._search_revision.get(session_id) == revision
            if current:
                callback(payload)

        threading.Thread(
            target=run,
            name=f"cp-subtitles-{str(session_id)[:8]}",
            daemon=True,
        ).start()

    def search(self, session_id, media):
        self._purge()
        identity = self._search_identity(media)
        config = self.player_config.storage_payload()
        languages = [
            _language(value)
            for value in config.get("preferred_subtitle_languages", [])
        ][:10] or ["en"]
        providers = {}
        now = int(self.clock())
        with self._lock:
            cooldowns = {
                name: int(self._diagnostics[name]["rate_limited_until"])
                for name in self.provider_classes
            }
        for name, provider_class in self.provider_classes.items():
            provider_config = config.get("providers", {}).get(name, {})
            if provider_config.get("enabled") and cooldowns[name] <= now:
                providers[name] = provider_class(provider_config, self.opener)

        provider_rows = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(providers)))
        futures = {
            executor.submit(provider.search, identity, languages): name
            for name, provider in providers.items()
        }
        done, pending = concurrent.futures.wait(
            futures,
            timeout=SEARCH_TIMEOUT_SECONDS,
        )
        for future in pending:
            name = futures[future]
            future.cancel()
            self._record_diagnostic(name, "timeout", 0, 0)
        for future in done:
            name = futures[future]
            started = self.clock()
            try:
                rows = future.result()
                provider_rows.extend(rows)
                self._record_diagnostic(name, "ready", len(rows), 0)
            except SubtitleProviderError as error:
                self._record_diagnostic(
                    name,
                    error.code,
                    0,
                    error.retry_after,
                )
            except Exception:
                self._record_diagnostic(name, "provider_error", 0, 0)
            finally:
                elapsed = int(max(0, (self.clock() - started) * 1000))
                with self._lock:
                    self._diagnostics[name]["last_latency_ms"] = elapsed
        executor.shutdown(wait=False, cancel_futures=True)

        ranked = self._rank(provider_rows, identity, languages, config)
        public = []
        expires = int(self.clock()) + RESULT_TTL_SECONDS
        with self._lock:
            for row in ranked[:MAX_PUBLIC_RESULTS]:
                result_id = secrets.token_urlsafe(12)
                self._results[(session_id, result_id)] = {
                    "expires": expires,
                    "row": row,
                    "media_path_key": str(media.get("path_key") or ""),
                }
                public.append({
                    "result_id": result_id,
                    "provider": row["provider"],
                    "language": row["language"],
                    "release_name": row["release_name"],
                    "file_name": row["file_name"],
                    "frame_rate": row["frame_rate"],
                    "rating": row["rating"],
                    "download_count": row["download_count"],
                    "hearing_impaired": row["hearing_impaired"],
                    "forced": row["forced"],
                    "match_reason": row["match_reason"],
                })
        return {
            "status": "complete",
            "results": public,
            "diagnostics": self.diagnostics(),
        }

    def download(self, session_id, result_id, media):
        self._purge()
        with self._lock:
            stored = self._results.get((session_id, result_id))
        if not stored or stored["media_path_key"] != str(media.get("path_key") or ""):
            raise SubtitleServiceError("The subtitle result expired")
        row = stored["row"]
        config = self.player_config.storage_payload()
        provider_config = config.get("providers", {}).get(row["provider"], {})
        provider_class = self.provider_classes.get(row["provider"])
        if not provider_class or not provider_config.get("enabled"):
            raise SubtitleServiceError("The subtitle provider is unavailable")
        provider = provider_class(provider_config, self.opener)
        try:
            payload, suggested_name = provider.download(row["provider_ref"])
        except SubtitleProviderError as error:
            self._record_diagnostic(row["provider"], error.code, 0, error.retry_after)
            raise SubtitleServiceError("The subtitle could not be downloaded") from None
        subtitle_bytes, extension, source_name = self._validate_download(
            payload,
            suggested_name or row["file_name"],
            row,
        )
        destination = self._store(
            subtitle_bytes,
            extension,
            source_name,
            row,
            media,
            config.get("subtitle_storage", "cache"),
        )
        return {
            "path": str(destination),
            "provider": row["provider"],
            "language": row["language"],
            "release_name": row["release_name"],
            "save_available": (
                destination.parent
                == Path(self.cache_root_provider()).resolve()
            ),
        }

    def save_beside_movie(self, cached_path, media):
        """Copy one service-owned cached subtitle beside its catalog movie."""
        cache_root = Path(self.cache_root_provider()).resolve()
        source = Path(str(cached_path or "")).resolve()
        if (
            source.parent != cache_root
            or source.suffix.lower() not in APPROVED_EXTENSIONS
            or not source.is_file()
        ):
            raise SubtitleServiceError("The cached subtitle is unavailable")
        try:
            if source.stat().st_size > MAX_SUBTITLE_BYTES:
                raise SubtitleServiceError("The cached subtitle is too large")
            payload = self._normalize_text(source.read_bytes())
            metadata_path = source.with_suffix(source.suffix + ".json")
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except SubtitleServiceError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise SubtitleServiceError("The cached subtitle metadata is invalid") from None
        if not isinstance(metadata, dict):
            raise SubtitleServiceError("The cached subtitle metadata is invalid")
        digest = hashlib.sha256(payload).hexdigest()
        if metadata.get("sha256") != digest:
            raise SubtitleServiceError("The cached subtitle failed validation")
        provider = str(metadata.get("provider") or "")[:32]
        provider_identity = str(metadata.get("provider_identity") or "")[:128]
        language = _language(metadata.get("language"))
        release_name = str(metadata.get("release_name") or "")[:512]
        source_name = Path(str(metadata.get("source_name") or source.name)).name[:512]
        if not provider or not provider_identity or not language or not source_name:
            raise SubtitleServiceError("The cached subtitle metadata is invalid")
        destination = self._store(
            payload,
            source.suffix.lower(),
            source_name,
            {
                "provider": provider,
                "provider_identity": provider_identity,
                "language": language,
                "release_name": release_name,
            },
            media,
            "beside_movie",
        )
        return {
            "path": str(destination),
            "provider": provider,
            "language": language,
            "release_name": release_name,
        }

    def _search_identity(self, media):
        path = str(media.get("path") or "")
        return {
            "title": str(media.get("title") or Path(path).stem)[:512],
            "year": str(media.get("year") or "")[:16],
            "filename": str(media.get("filename") or Path(path).name)[:512],
            "file_size": int(media.get("file_size") or os.path.getsize(path)),
            "file_hash": opensubtitles_hash(path),
            "frame_rate": _safe_number(media.get("frame_rate")),
            "imdb_id": str(media.get("imdb_id") or "")[:64],
            "tmdb_id": str(media.get("tmdb_id") or "")[:64],
        }

    def _rank(self, rows, identity, languages, config):
        release_tokens = _release_tokens(Path(identity["filename"]).stem)
        preferred_hi = bool(config.get("prefer_hearing_impaired_subtitles"))
        preferred_forced = bool(config.get("prefer_forced_subtitles"))
        ranked = []
        for row in rows:
            reasons = []
            score = 0.0
            if row["hash_match"]:
                score += 10000
                reasons.append("Exact file hash")
            candidates = row.get("release_names") or [row.get("release_name")]
            similarity = max(
                (
                    SequenceMatcher(
                        None,
                        " ".join(sorted(release_tokens)),
                        " ".join(sorted(_release_tokens(candidate))),
                    ).ratio()
                    for candidate in candidates
                    if candidate
                ),
                default=0,
            )
            if similarity >= 0.55:
                score += 3000 + similarity * 1000
                reasons.append("Release-name match")
            imdb_match = (
                identity["imdb_id"]
                and re.sub(r"\D", "", identity["imdb_id"])
                == re.sub(r"\D", "", row.get("imdb_id", ""))
            )
            tmdb_match = (
                identity["tmdb_id"]
                and identity["tmdb_id"] == str(row.get("tmdb_id") or "")
            )
            if imdb_match or tmdb_match:
                score += 2000
                reasons.append("Verified movie identity")
            title_match = (
                identity["title"].casefold() == str(row.get("title") or "").casefold()
                and (not row.get("year") or identity["year"] == str(row["year"]))
            )
            if title_match:
                score += 1000
                reasons.append("Title and year match")
            fps = _safe_number(row.get("frame_rate"))
            if fps and identity["frame_rate"] and abs(fps - identity["frame_rate"]) <= 0.02:
                score += 500
                reasons.append("Frame-rate match")
            if row["language"] in languages:
                score += 250 - languages.index(row["language"]) * 10
                if not reasons:
                    reasons.append("Preferred language")
            if bool(row["hearing_impaired"]) == preferred_hi:
                score += 25
            if bool(row["forced"]) == preferred_forced:
                score += 25
            score += min(max(row["rating"], 0), 10) * 2
            score += min(math.log10(max(row["download_count"], 1)), 6)
            row = dict(row)
            row["match_reason"] = reasons[0] if reasons else "Provider metadata match"
            row["_score"] = score
            ranked.append(row)

        ranked.sort(
            key=lambda row: (
                -row["_score"],
                languages.index(row["language"]) if row["language"] in languages else 999,
                row["provider"],
                row["release_name"].casefold(),
                row["provider_identity"],
            )
        )
        deduplicated = []
        seen = set()
        for row in ranked:
            key = (
                row["language"],
                re.sub(r"[^a-z0-9]", "", row["release_name"].casefold()),
                round(row["frame_rate"], 3),
                row["hearing_impaired"],
                row["forced"],
            )
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(row)
        return deduplicated

    def _validate_download(self, payload, suggested_name, row):
        if not payload:
            raise SubtitleServiceError("The subtitle download was empty")
        candidates = []
        if payload.startswith(b"PK\x03\x04"):
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    infos = archive.infolist()
                    if len(infos) > MAX_ARCHIVE_ENTRIES:
                        raise SubtitleServiceError("The subtitle archive has too many entries")
                    total = 0
                    for info in infos:
                        normalized = info.filename.replace("\\", "/")
                        parts = PurePosixPath(normalized).parts
                        if (
                            info.is_dir()
                            or not parts
                            or PurePosixPath(normalized).is_absolute()
                            or ".." in parts
                            or info.external_attr >> 16 & 0o170000 == 0o120000
                        ):
                            if not info.is_dir():
                                raise SubtitleServiceError("The subtitle archive is unsafe")
                            continue
                        extension = Path(parts[-1]).suffix.lower()
                        if extension not in APPROVED_EXTENSIONS:
                            continue
                        total += int(info.file_size)
                        if info.file_size > MAX_SUBTITLE_BYTES or total > MAX_ARCHIVE_EXPANDED_BYTES:
                            raise SubtitleServiceError("The subtitle archive is too large")
                        data = archive.read(info)
                        candidates.append((data, extension, parts[-1]))
            except SubtitleServiceError:
                raise
            except (zipfile.BadZipFile, RuntimeError):
                raise SubtitleServiceError("The subtitle archive is invalid") from None
        else:
            extension = Path(str(suggested_name or "")).suffix.lower()
            if extension not in APPROVED_EXTENSIONS:
                raise SubtitleServiceError("The subtitle format is not supported")
            candidates.append((payload, extension, Path(str(suggested_name)).name))
        if not candidates:
            raise SubtitleServiceError("The download contains no supported subtitle")
        release = _release_tokens(row.get("release_name"))
        candidates.sort(
            key=lambda candidate: (
                -len(release & _release_tokens(candidate[2])),
                candidate[2].casefold(),
            )
        )
        data, extension, name = candidates[0]
        if len(data) > MAX_SUBTITLE_BYTES:
            raise SubtitleServiceError("The subtitle file is too large")
        return self._normalize_text(data), extension, name

    @staticmethod
    def _normalize_text(payload):
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = payload.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise SubtitleServiceError("The subtitle text encoding is invalid")
        if "\x00" in text:
            raise SubtitleServiceError("The subtitle text is invalid")
        return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")

    def _store(self, payload, extension, source_name, row, media, storage_mode):
        digest = hashlib.sha256(payload).hexdigest()
        if storage_mode == "beside_movie":
            root = Path(str(media["path"])).resolve().parent
            stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(str(media["path"])).stem)[:120]
        else:
            root = Path(self.cache_root_provider()).resolve()
            stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(source_name).stem)[:80] or "subtitle"
        root.mkdir(parents=True, exist_ok=True)
        filename = f"{stem}.cp.{row['language']}.{digest[:12]}{extension}"
        destination = (root / filename).resolve()
        if destination.parent != root:
            raise SubtitleServiceError("The subtitle destination is invalid")
        if not destination.exists():
            handle = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".cp-subtitle-",
                suffix=".tmp",
                dir=root,
                delete=False,
            )
            temporary = Path(handle.name)
            try:
                with handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
        metadata = {
            "provider": row["provider"],
            "provider_identity": row["provider_identity"],
            "language": row["language"],
            "release_name": row["release_name"],
            "source_name": Path(source_name).name[:512],
            "sha256": digest,
        }
        metadata_path = destination.with_suffix(destination.suffix + ".json")
        if not metadata_path.exists():
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
        return destination

    def _record_diagnostic(self, provider, state, count, retry_after):
        now = int(self.clock())
        with self._lock:
            diagnostic = self._diagnostics[provider]
            diagnostic["state"] = "rate_limited" if state == "rate_limited" else (
                "ready" if state == "ready" else "error"
            )
            diagnostic["last_error"] = "" if state == "ready" else redact_sensitive_text(state)
            diagnostic["last_result_count"] = int(count)
            if retry_after:
                diagnostic["rate_limited_until"] = now + int(retry_after)

    def _purge(self):
        now = int(self.clock())
        with self._lock:
            expired = [
                key for key, value in self._results.items()
                if int(value["expires"]) <= now
            ]
            for key in expired:
                self._results.pop(key, None)
