import json
import os
import re
import threading
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
        }

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
                }
            self._atomic_save(next_payload)
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
