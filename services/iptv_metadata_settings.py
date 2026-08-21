import json
import os
import re
import threading
import urllib.parse
import uuid
from pathlib import Path


SETTINGS_SCHEMA_VERSION = 1
_CREDENTIAL_TYPES = {"api_key", "bearer"}


class IPTVMetadataSettings:
    """Backend-only owner for the IPTV TMDB credential.

    This intentionally does not import or inspect Cinema Paradiso's main config.
    """

    def __init__(self, user_data_dir):
        self.root = (Path(user_data_dir).resolve() / "iptv").resolve()
        self.path = self.root / "metadata-settings.json"
        self._lock = threading.RLock()

    @staticmethod
    def _empty():
        return {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "credential_type": "bearer",
            "credential": "",
            "ollama_enabled": False,
            "ollama_url": "http://127.0.0.1:11434",
            "ollama_model": "",
        }

    def _load_private(self):
        if not self.path.is_file():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("IPTV metadata settings are unreadable") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != SETTINGS_SCHEMA_VERSION:
            raise RuntimeError("IPTV metadata settings have an unsupported schema")
        credential_type = str(payload.get("credential_type") or "bearer").strip().lower()
        if credential_type not in _CREDENTIAL_TYPES:
            raise RuntimeError("IPTV metadata settings contain an unsupported credential type")
        return {
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "credential_type": credential_type,
            "credential": str(payload.get("credential") or "").strip(),
            "ollama_enabled": bool(payload.get("ollama_enabled")),
            "ollama_url": self._validate_ollama_url(payload.get("ollama_url") or "http://127.0.0.1:11434"),
            "ollama_model": str(payload.get("ollama_model") or "").strip()[:120],
        }

    @staticmethod
    def _validate_ollama_url(value):
        value = str(value or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("IPTV Ollama must use a credential-free localhost HTTP address")
        if parsed.path not in {"", "/"}:
            raise ValueError("IPTV Ollama address must not include an API path")
        return value

    def _atomic_save(self, payload):
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def public(self):
        with self._lock:
            payload = self._load_private()
        return {
            "tmdb_configured": bool(payload["credential"]),
            "credential_type": payload["credential_type"],
            "ollama_enabled": bool(payload["ollama_enabled"] and payload["ollama_model"]),
            "ollama_url": payload["ollama_url"],
            "ollama_model": payload["ollama_model"],
        }

    def credential(self):
        with self._lock:
            payload = self._load_private()
        if not payload["credential"]:
            raise ValueError("Configure the IPTV TMDB credential first")
        return payload["credential_type"], payload["credential"]

    def save(self, credential="", credential_type=None, clear=False):
        with self._lock:
            current = self._load_private()
            if clear:
                next_payload = self._empty()
                next_payload["credential_type"] = str(
                    credential_type or current["credential_type"] or "bearer"
                ).strip().lower()
                next_payload.update({
                    "ollama_enabled": current["ollama_enabled"],
                    "ollama_url": current["ollama_url"],
                    "ollama_model": current["ollama_model"],
                })
            else:
                next_type = str(
                    credential_type or current["credential_type"] or "bearer"
                ).strip().lower()
                if next_type not in _CREDENTIAL_TYPES:
                    raise ValueError("IPTV TMDB credential type must be bearer or api_key")
                next_credential = str(credential or current["credential"] or "").strip()
                if not next_credential:
                    raise ValueError("An IPTV TMDB credential is required")
                next_payload = {
                    "schema_version": SETTINGS_SCHEMA_VERSION,
                    "credential_type": next_type,
                    "credential": next_credential,
                    "ollama_enabled": current["ollama_enabled"],
                    "ollama_url": current["ollama_url"],
                    "ollama_model": current["ollama_model"],
                }
            self._atomic_save(next_payload)
        return self.public()

    def save_ollama(self, *, enabled=False, url="", model=""):
        with self._lock:
            current = self._load_private()
            current["ollama_enabled"] = bool(enabled)
            current["ollama_url"] = self._validate_ollama_url(url or current["ollama_url"])
            current["ollama_model"] = str(model or "").strip()[:120]
            if current["ollama_enabled"] and not current["ollama_model"]:
                raise ValueError("Choose an IPTV Ollama model before enabling AI assistance")
            self._atomic_save(current)
        return self.public()

    def redact(self, value):
        message = str(value or "")
        try:
            credential = self._load_private().get("credential") or ""
        except RuntimeError:
            credential = ""
        if credential:
            message = message.replace(credential, "[redacted]")
        message = re.sub(
            r"(?i)(api_key\s*[=:]\s*)([^&\s,;]+)",
            r"\1[redacted]",
            message,
        )
        message = re.sub(
            r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)([^\s,;]+)",
            r"\1[redacted]",
            message,
        )
        message = re.sub(r"(?i)(bearer\s+)([A-Za-z0-9._~+/-]+)", r"\1[redacted]", message)
        return message[:500]
