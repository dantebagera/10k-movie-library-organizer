import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .iptv_metadata_settings import IPTVMetadataSettings
from .iptv_movie_service import IPTVMovieService
from .iptv_service import IPTVService
from .iptv_xtream import normalize_server_url


PROVIDER_ID_RE = re.compile(r"^[0-9a-f]{32}$")
REGISTRY_SCHEMA_VERSION = 1


def _atomic_json_write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _database_facts(path):
    path = Path(path)
    if not path.is_file():
        return None
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

        def scalar(statement, default=0):
            try:
                row = connection.execute(statement).fetchone()
                return row[0] if row else default
            except sqlite3.DatabaseError:
                return default

        item_counts = {}
        category_counts = {}
        if "items" in tables:
            item_counts = {
                str(kind): int(count)
                for kind, count in connection.execute(
                    "SELECT kind, COUNT(*) FROM items GROUP BY kind"
                )
            }
        if "categories" in tables:
            category_counts = {
                str(kind): int(count)
                for kind, count in connection.execute(
                    "SELECT kind, COUNT(*) FROM categories GROUP BY kind"
                )
            }
        meta = {}
        if "meta" in tables:
            meta = {
                str(key): str(value)
                for key, value in connection.execute("SELECT key, value FROM meta")
            }
        return {
            "items": {kind: item_counts.get(kind, 0) for kind in ("live", "movie", "series")},
            "categories": {kind: category_counts.get(kind, 0) for kind in ("live", "movie", "series")},
            "generation": int(float(meta.get("generation", 0) or 0)),
            "last_sync": float(meta.get("last_sync", 0) or 0),
            "details": int(scalar("SELECT COUNT(*) FROM details")) if "details" in tables else 0,
            "lists": int(scalar("SELECT COUNT(*) FROM iptv_lists")) if "iptv_lists" in tables else 0,
            "list_items": int(scalar("SELECT COUNT(*) FROM iptv_list_items")) if "iptv_list_items" in tables else 0,
            "history": int(scalar("SELECT COUNT(*) FROM watch_history")) if "watch_history" in tables else 0,
        }
    finally:
        connection.close()


def _file_digest(path):
    path = Path(path)
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_facts(path):
    path = Path(path)
    files = [candidate for candidate in path.rglob("*") if candidate.is_file()] if path.is_dir() else []
    return {
        "files": len(files),
        "bytes": sum(candidate.stat().st_size for candidate in files),
    }


class IPTVProviderManager:
    def __init__(self, user_data_dir, ffmpeg_path=None, migrate_legacy=True):
        self.root = (Path(user_data_dir).resolve() / "iptv").resolve()
        self.providers_root = self.root / "providers"
        self.backups_root = self.root / "migration-backups"
        self.registry_path = self.root / "providers.json"
        self.ffmpeg_path = ffmpeg_path
        self._lock = threading.RLock()
        self._services = {}
        self._movie_services = {}
        self.metadata_settings = IPTVMetadataSettings(Path(user_data_dir).resolve())
        self.root.mkdir(parents=True, exist_ok=True)
        self.providers_root.mkdir(parents=True, exist_ok=True)
        if migrate_legacy:
            self._migrate_legacy()
        if not self.registry_path.exists():
            self._save_registry(self._empty_registry())
        self._registry = self._load_registry()

    @staticmethod
    def _empty_registry():
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "last_selected_provider_id": "",
            "providers": [],
        }

    def _load_registry(self):
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("The IPTV provider registry is unreadable") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise RuntimeError("The IPTV provider registry has an unsupported schema")
        providers = payload.get("providers")
        if not isinstance(providers, list):
            raise RuntimeError("The IPTV provider registry is invalid")
        seen = set()
        normalized = []
        for position, provider in enumerate(providers):
            if not isinstance(provider, dict):
                raise RuntimeError("The IPTV provider registry is invalid")
            provider_id = str(provider.get("provider_id") or "")
            if not PROVIDER_ID_RE.fullmatch(provider_id) or provider_id in seen:
                raise RuntimeError("The IPTV provider registry contains an invalid provider ID")
            seen.add(provider_id)
            name = re.sub(r"\s+", " ", str(provider.get("name") or "").strip())
            if not name:
                raise RuntimeError("The IPTV provider registry contains an unnamed provider")
            normalized.append({
                "provider_id": provider_id,
                "name": name,
                "position": position,
                "created_at": float(provider.get("created_at") or 0),
                "updated_at": float(provider.get("updated_at") or 0),
            })
        selected = str(payload.get("last_selected_provider_id") or "")
        if selected and selected not in seen:
            selected = normalized[0]["provider_id"] if normalized else ""
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "last_selected_provider_id": selected,
            "providers": normalized,
        }

    def _save_registry(self, registry):
        _atomic_json_write(self.registry_path, registry)

    def _provider_path(self, provider_id):
        provider_id = str(provider_id or "")
        if not PROVIDER_ID_RE.fullmatch(provider_id):
            raise KeyError("IPTV provider was not found")
        candidate = (self.providers_root / provider_id).resolve()
        try:
            candidate.relative_to(self.providers_root.resolve())
        except ValueError:
            raise KeyError("IPTV provider was not found") from None
        return candidate

    def _record(self, provider_id):
        for provider in self._registry["providers"]:
            if provider["provider_id"] == str(provider_id):
                return provider
        raise KeyError("IPTV provider was not found")

    def service(self, provider_id):
        with self._lock:
            record = self._record(provider_id)
            service = self._services.get(record["provider_id"])
            if service is None:
                service = IPTVService(
                    self._provider_path(record["provider_id"]),
                    record["provider_id"],
                    ffmpeg_path=self.ffmpeg_path,
                    on_catalog_committed=self._catalog_committed,
                )
                self._services[record["provider_id"]] = service
            return service

    def movie_service(self, provider_id):
        with self._lock:
            record = self._record(provider_id)
            movie_service = self._movie_services.get(record["provider_id"])
            if movie_service is None:
                movie_service = IPTVMovieService(
                    self._provider_path(record["provider_id"]),
                    record["provider_id"],
                    self.service(record["provider_id"]),
                    self.metadata_settings,
                )
                self._movie_services[record["provider_id"]] = movie_service
            return movie_service

    def _catalog_committed(self, provider_id):
        """Begin TMDB-free provider-local projection after raw sync commits."""
        try:
            self.movie_service(provider_id).start_projection(wait=False)
        except Exception:
            # Projection owns and exposes its own retryable status. A local
            # preparation failure must never turn a successful raw sync into a
            # Live TV or Series failure.
            return False
        return True

    @staticmethod
    def _identity(server_url, username):
        return normalize_server_url(server_url), str(username or "").strip()

    def _assert_unique_account(self, server_url, username, excluding=""):
        identity = self._identity(server_url, username)
        for provider in self._registry["providers"]:
            if provider["provider_id"] == excluding:
                continue
            config_path = self._provider_path(provider["provider_id"]) / "provider.json"
            try:
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                other = self._identity(config.get("server_url"), config.get("username"))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if other == identity:
                raise ValueError("That Xtream account is already configured")

    @staticmethod
    def _clean_name(name):
        cleaned = re.sub(r"\s+", " ", str(name or "").strip())
        if not cleaned:
            raise ValueError("Provider display name is required")
        if len(cleaned) > 80:
            raise ValueError("Provider display name must be 80 characters or fewer")
        return cleaned

    def _summary(self, record):
        service = self.service(record["provider_id"])
        return {
            "provider_id": record["provider_id"],
            "name": record["name"],
            "position": record["position"],
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            **service.status(),
        }

    def list_providers(self):
        with self._lock:
            providers = [self._summary(record) for record in self._registry["providers"]]
            return {
                "providers": providers,
                "last_selected_provider_id": self._registry["last_selected_provider_id"],
                "count": len(providers),
            }

    def get_provider(self, provider_id):
        with self._lock:
            return self._summary(self._record(provider_id))

    def create_provider(self, name, server_url, username, password, allow_insecure_tls=False):
        with self._lock:
            clean_name = self._clean_name(name)
            normalized, clean_username = self._identity(server_url, username)
            if not clean_username or not str(password or ""):
                raise ValueError("Xtream username and password are required")
            self._assert_unique_account(normalized, clean_username)
            provider_id = uuid.uuid4().hex
            provider_root = self._provider_path(provider_id)
            now = time.time()
            record = {
                "provider_id": provider_id,
                "name": clean_name,
                "position": len(self._registry["providers"]),
                "created_at": now,
                "updated_at": now,
            }
            service = None
            try:
                service = IPTVService(provider_root, provider_id, ffmpeg_path=self.ffmpeg_path)
                service.save_config(normalized, clean_username, password, allow_insecure_tls)
                next_registry = {
                    **self._registry,
                    "providers": [*self._registry["providers"], record],
                    "last_selected_provider_id": self._registry["last_selected_provider_id"] or provider_id,
                }
                self._save_registry(next_registry)
                self._registry = next_registry
                self._services[provider_id] = service
                return self._summary(record)
            except Exception:
                if service:
                    service.close()
                self._services.pop(provider_id, None)
                shutil.rmtree(provider_root, ignore_errors=True)
                raise

    def update_provider(self, provider_id, name=None, server_url=None, username=None, password=None, allow_insecure_tls=None):
        with self._lock:
            record = self._record(provider_id)
            service = self.service(provider_id)
            current = service._load_config()
            next_server = server_url if str(server_url or "").strip() else current.get("server_url")
            next_username = username if str(username or "").strip() else current.get("username")
            next_password = password if str(password or "") else current.get("password")
            normalized, clean_username = self._identity(next_server, next_username)
            if not clean_username or not next_password:
                raise ValueError("Xtream username and password are required")
            self._assert_unique_account(normalized, clean_username, excluding=record["provider_id"])
            clean_name = self._clean_name(record["name"] if name is None else name)
            config_path = service.config_path
            previous_config = config_path.read_bytes() if config_path.exists() else None
            next_record = {
                **record,
                "name": clean_name,
                "updated_at": time.time(),
            }
            next_providers = [
                next_record if item["provider_id"] == record["provider_id"] else item
                for item in self._registry["providers"]
            ]
            try:
                service.save_config(
                    normalized,
                    clean_username,
                    next_password,
                    allow_insecure_tls,
                )
                next_registry = {**self._registry, "providers": next_providers}
                self._save_registry(next_registry)
                self._registry = next_registry
            except Exception:
                if previous_config is None:
                    try:
                        config_path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    temporary = config_path.with_name(f".{config_path.name}.rollback.tmp")
                    temporary.write_bytes(previous_config)
                    os.replace(temporary, config_path)
                raise
            return self._summary(next_record)

    def remove_provider(self, provider_id, confirm_name):
        with self._lock:
            record = self._record(provider_id)
            if str(confirm_name or "") != record["name"]:
                raise ValueError("Type the provider name exactly to remove it")
            movie_service = self._movie_services.pop(record["provider_id"], None)
            if movie_service:
                movie_service.close()
            service = self._services.pop(record["provider_id"], None)
            if service:
                service.close()
            provider_root = self._provider_path(record["provider_id"])
            tombstone = self.providers_root / f".{record['provider_id']}.deleting"
            if tombstone.exists():
                shutil.rmtree(tombstone)
            if provider_root.exists():
                os.replace(provider_root, tombstone)
            next_providers = [
                {**item, "position": position}
                for position, item in enumerate(self._registry["providers"])
                if item["provider_id"] != record["provider_id"]
            ]
            selected = self._registry["last_selected_provider_id"]
            if selected == record["provider_id"]:
                selected = next_providers[0]["provider_id"] if next_providers else ""
            next_registry = {
                **self._registry,
                "providers": next_providers,
                "last_selected_provider_id": selected,
            }
            try:
                self._save_registry(next_registry)
            except Exception:
                if tombstone.exists():
                    os.replace(tombstone, provider_root)
                raise
            self._registry = next_registry
            shutil.rmtree(tombstone, ignore_errors=True)
            return {
                "success": True,
                "removed_provider_id": record["provider_id"],
                "last_selected_provider_id": selected,
            }

    def set_selection(self, provider_id):
        with self._lock:
            self._record(provider_id)
            next_registry = {**self._registry, "last_selected_provider_id": str(provider_id)}
            self._save_registry(next_registry)
            self._registry = next_registry
            return {"success": True, "last_selected_provider_id": str(provider_id)}

    def test_provider(self, provider_id):
        return self.service(provider_id).test_connection()

    def start_sync(self, provider_id):
        service = self.service(provider_id)
        started = service.start_sync()
        return {"accepted": started, "status": self.get_provider(provider_id)}

    def redacted_error(self, error, provider_id=""):
        message = str(error or "IPTV request failed")
        configs = []
        if provider_id:
            try:
                configs.append(self.service(provider_id)._load_config())
            except (KeyError, RuntimeError):
                pass
        for config in configs:
            for secret in (config.get("username"), config.get("password")):
                if secret:
                    message = message.replace(str(secret), "[redacted]")
        message = re.sub(r"(?i)(username|password)=([^&\s]+)", r"\1=[redacted]", message)
        return self.metadata_settings.redact(message)[:300]

    def close(self):
        with self._lock:
            movie_services = list(self._movie_services.values())
            self._movie_services.clear()
            services = list(self._services.values())
            self._services.clear()
        for movie_service in movie_services:
            movie_service.close()
        for service in services:
            service.close()

    def _next_backup_path(self):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        candidate = self.backups_root / stamp
        suffix = 0
        while candidate.exists():
            suffix += 1
            candidate = self.backups_root / f"{stamp}-{suffix}"
        return candidate

    @staticmethod
    def _copy_file_if_present(source, target):
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _migrate_legacy(self):
        if self.registry_path.exists():
            return
        legacy_config = self.root / "provider.json"
        legacy_database = self.root / "iptv.sqlite"
        legacy_images = self.root / "images"
        if not legacy_config.exists() and not legacy_database.exists():
            return
        provider_id = uuid.uuid4().hex
        provider_root = self._provider_path(provider_id)
        backup_root = self._next_backup_path()
        stage_root = self.providers_root / f".{provider_id}.migration"
        source_facts = _database_facts(legacy_database)
        source_config_digest = _file_digest(legacy_config)
        source_image_facts = _tree_facts(legacy_images)
        activated = False
        try:
            backup_root.mkdir(parents=True, exist_ok=False)
            self._copy_file_if_present(legacy_config, backup_root / "provider.json")
            self._copy_file_if_present(legacy_database, backup_root / "iptv.sqlite")
            for suffix in ("-wal", "-shm"):
                self._copy_file_if_present(
                    Path(str(legacy_database) + suffix),
                    Path(str(backup_root / "iptv.sqlite") + suffix),
                )
            if legacy_images.is_dir():
                shutil.copytree(legacy_images, backup_root / "images")
            if source_facts != _database_facts(backup_root / "iptv.sqlite"):
                raise RuntimeError("The IPTV migration backup did not match the legacy catalog")
            if source_config_digest != _file_digest(backup_root / "provider.json"):
                raise RuntimeError("The IPTV migration backup did not match the legacy credentials")
            if source_image_facts != _tree_facts(backup_root / "images"):
                raise RuntimeError("The IPTV migration backup did not match the legacy image cache")

            stage_root.mkdir(parents=True, exist_ok=False)
            self._copy_file_if_present(backup_root / "provider.json", stage_root / "provider.json")
            self._copy_file_if_present(backup_root / "iptv.sqlite", stage_root / "iptv.sqlite")
            for suffix in ("-wal", "-shm"):
                self._copy_file_if_present(
                    Path(str(backup_root / "iptv.sqlite") + suffix),
                    Path(str(stage_root / "iptv.sqlite") + suffix),
                )
            if (backup_root / "images").is_dir():
                shutil.copytree(backup_root / "images", stage_root / "images")
            (stage_root / "playback").mkdir(exist_ok=True)
            if source_facts != _database_facts(stage_root / "iptv.sqlite"):
                raise RuntimeError("The migrated IPTV catalog did not match the legacy catalog")
            if source_config_digest != _file_digest(stage_root / "provider.json"):
                raise RuntimeError("The migrated IPTV credentials did not match the legacy credentials")
            if source_image_facts != _tree_facts(stage_root / "images"):
                raise RuntimeError("The migrated IPTV image cache did not match the legacy image cache")
            os.replace(stage_root, provider_root)
            now = time.time()
            registry = {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "last_selected_provider_id": provider_id,
                "providers": [{
                    "provider_id": provider_id,
                    "name": "Lionz",
                    "position": 0,
                    "created_at": now,
                    "updated_at": now,
                }],
            }
            self._save_registry(registry)
            activated = True
            for path in (
                legacy_config,
                legacy_database,
                Path(str(legacy_database) + "-wal"),
                Path(str(legacy_database) + "-shm"),
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            if legacy_images.exists():
                shutil.rmtree(legacy_images)
            legacy_playback = self.root / "playback"
            if legacy_playback.exists():
                shutil.rmtree(legacy_playback)
        except Exception:
            try:
                self.registry_path.unlink()
            except FileNotFoundError:
                pass
            shutil.rmtree(stage_root, ignore_errors=True)
            shutil.rmtree(provider_root, ignore_errors=True)
            if activated or backup_root.exists():
                self._copy_file_if_present(backup_root / "provider.json", legacy_config)
                self._copy_file_if_present(backup_root / "iptv.sqlite", legacy_database)
                for suffix in ("-wal", "-shm"):
                    self._copy_file_if_present(
                        Path(str(backup_root / "iptv.sqlite") + suffix),
                        Path(str(legacy_database) + suffix),
                    )
                if (backup_root / "images").is_dir():
                    if legacy_images.exists():
                        shutil.rmtree(legacy_images)
                    shutil.copytree(backup_root / "images", legacy_images)
            raise
