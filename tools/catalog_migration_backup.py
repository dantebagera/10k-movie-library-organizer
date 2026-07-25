import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.catalog_repository import CatalogRepository, catalog_database_path


BACKUP_FORMAT = "cinema-paradiso-catalog-migration-backup"
BACKUP_VERSION = 3
QBITTORRENT_STATE_FILES = {"jobs.json", "runtime.json"}
CATALOG_ROLLBACK_DOCUMENTS = {
    "app_metadata/files.json": {"files": {}},
    "app_metadata/tmdb_metadata.json": {"movies": {}},
    "app_metadata/plex_metadata.json": {"files": {}},
    "app_metadata/manual_matches.json": {"matches": {}},
    "app_metadata/identity_audit_fingerprints.json": {"files": {}},
    "app_metadata/poster_overrides.json": {"overrides": []},
    "app_metadata/metadata_overrides.json": {"overrides": []},
    "user_lists.json": {"lists": []},
    "user_collections.json": {"overrides": {}},
    "followed_releases.json": {"movies": []},
}


class BackupError(RuntimeError):
    pass


def _sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def _read_json(path, fallback):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback
    return data if isinstance(data, type(fallback)) else fallback


def resolve_backup_sources(project_root):
    project_root = Path(project_root).resolve()
    config_path = project_root / "config.json"
    config = _read_json(config_path, {})
    configured_user_data = str(config.get("user_data_dir") or "").strip()
    user_data_dir = Path(configured_user_data) if configured_user_data else project_root / "data"
    if not user_data_dir.is_absolute():
        user_data_dir = project_root / user_data_dir
    return {
        "project_root": project_root,
        "config_path": config_path,
        "user_data_dir": user_data_dir.resolve(),
        "catalog_path": catalog_database_path(user_data_dir),
        "metadata_dir": (Path(os.environ.get("LOCALAPPDATA") or project_root) / "Cinema Paradiso" / "Metadata").resolve(),
    }


def _include_user_data_file(relative_path):
    relative_path = Path(relative_path)
    parts = [part.lower() for part in relative_path.parts]
    if not parts:
        return False
    if parts[0] in {"backups", "catalog-migration-backups"} or parts[0].startswith("catalog-performance-"):
        return False
    if parts[0] != "qbittorrent":
        return True
    return len(parts) == 2 and parts[1] in QBITTORRENT_STATE_FILES


def _registered_metadata_files(catalog_path, metadata_dir):
    catalog_path = Path(catalog_path)
    metadata_dir = Path(metadata_dir).resolve()
    if not catalog_path.is_file() or not metadata_dir.is_dir():
        return []
    connection = None
    try:
        connection = sqlite3.connect(f"file:{catalog_path.as_posix()}?mode=ro", uri=True)
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='media_assets'"
        ).fetchone():
            return []
        paths = []
        for row in connection.execute(
            "SELECT DISTINCT local_path FROM media_assets WHERE status='ready' AND local_path<>''"
        ):
            path = Path(row[0]).resolve()
            try:
                path.relative_to(metadata_dir)
            except ValueError:
                continue
            if path.is_file():
                paths.append(path)
        return sorted(set(paths), key=lambda item: str(item).lower())
    finally:
        if connection is not None:
            connection.close()


def _backup_entries(project_root):
    sources = resolve_backup_sources(project_root)
    entries = []
    config_path = sources["config_path"]
    if config_path.is_file():
        entries.append((config_path, PurePosixPath("project/config.json"), "config"))
    user_data_dir = sources["user_data_dir"]
    if user_data_dir.is_dir():
        for path in sorted(user_data_dir.rglob("*"), key=lambda item: str(item).lower()):
            if not path.is_file():
                continue
            relative = path.relative_to(user_data_dir)
            if _include_user_data_file(relative):
                entries.append((path, PurePosixPath("user-data") / relative.as_posix(), "user_data"))
    metadata_dir = sources["metadata_dir"]
    if metadata_dir.is_dir():
        for path in _registered_metadata_files(sources["catalog_path"], metadata_dir):
            relative = path.relative_to(metadata_dir)
            entries.append((path, PurePosixPath("metadata") / relative.as_posix(), "metadata_asset"))
    return sources, entries


def _count_mapping(document, key):
    value = document.get(key, {}) if isinstance(document, dict) else {}
    return len(value) if isinstance(value, dict) else 0


def _count_list(document, key):
    value = document.get(key, []) if isinstance(document, dict) else []
    return len(value) if isinstance(value, list) else 0


def _semantic_counts(payloads):
    def document(name, fallback):
        payload = payloads.get(name)
        if payload is None:
            return fallback
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return fallback
        return value if isinstance(value, type(fallback)) else fallback

    files = document("user-data/app_metadata/files.json", {})
    tmdb = document("user-data/app_metadata/tmdb_metadata.json", {})
    plex = document("user-data/app_metadata/plex_metadata.json", {})
    manual = document("user-data/app_metadata/manual_matches.json", {})
    lists = document("user-data/user_lists.json", {})
    collections = document("user-data/user_collections.json", {})
    followed = document("user-data/followed_releases.json", {})
    qbt_jobs = document("user-data/qbittorrent/jobs.json", {})
    list_rows = lists.get("lists", []) if isinstance(lists.get("lists", []), list) else []
    counts = {
        "file_records": _count_mapping(files, "files"),
        "tmdb_movies": _count_mapping(tmdb, "movies"),
        "plex_files": _count_mapping(plex, "files"),
        "manual_matches": _count_mapping(manual, "matches"),
        "user_lists": len(list_rows),
        "list_movies": sum(
            len(item.get("movies", []))
            for item in list_rows
            if isinstance(item, dict) and isinstance(item.get("movies", []), list)
        ),
        "collection_overrides": _count_mapping(collections, "overrides"),
        "followed_releases": _count_list(followed, "movies"),
        "qbittorrent_jobs": _count_mapping(qbt_jobs, "jobs"),
        "metadata_asset_files": sum(1 for name in payloads if name.startswith("metadata/assets/")),
        "metadata_asset_bytes": sum(len(payload) for name, payload in payloads.items() if name.startswith("metadata/assets/")),
    }
    catalog_payload = payloads.get("catalog/catalog.sqlite")
    if catalog_payload:
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as handle:
                handle.write(catalog_payload)
                temporary_name = handle.name
            connection = sqlite3.connect(temporary_name)
            try:
                table_counts = {
                    "file_records": "media_files",
                    "tmdb_movies": "tmdb_movies",
                    "plex_files": "plex_files",
                    "manual_matches": "manual_matches",
                    "user_lists": "user_lists",
                    "list_movies": "list_items",
                    "collection_overrides": "collection_overrides",
                    "followed_releases": "followed_releases",
                }
                for key, table in table_counts.items():
                    counts[key] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            finally:
                connection.close()
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
    return counts


def _catalog_snapshot(path):
    path = Path(path)
    if not path.is_file():
        return None
    temporary_name = ""
    source = None
    target = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as handle:
            temporary_name = handle.name
        source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(temporary_name)
        source.backup(target)
        target.commit()
        target.close()
        target = None
        source.close()
        source = None
        return Path(temporary_name).read_bytes()
    finally:
        if target is not None:
            target.close()
        if source is not None:
            source.close()
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _catalog_rollback_payloads(path):
    path = Path(path)
    if not path.is_file():
        return {}
    connection = None
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        payloads = {}
        for name, fallback in CATALOG_ROLLBACK_DOCUMENTS.items():
            document = CatalogRepository._read_document(connection, name, fallback)
            payloads[f"user-data/{name}"] = json.dumps(document, indent=2).encode("utf-8")
        return payloads
    finally:
        if connection is not None:
            connection.close()


def _verify_rollback_shadow(archive_path):
    from tools.build_shadow_catalog import build_shadow_catalog

    with tempfile.TemporaryDirectory(prefix="cp-shadow-audit-") as root:
        _, report = build_shadow_catalog(archive_path, Path(root) / "catalog-shadow.sqlite")
    if not report.get("passed"):
        raise BackupError(f"Rollback shadow verification failed: {json.dumps(report, sort_keys=True)}")
    return report


def _app_version(project_root):
    package = _read_json(Path(project_root) / "package.json", {})
    return str(package.get("version") or "unknown")


def create_backup(project_root, output_dir=None, now=None):
    sources, entries = _backup_entries(project_root)
    if not entries:
        raise BackupError("No Cinema Paradiso user data was found to back up")
    created_at = now or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    timestamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    default_output = Path(os.environ.get("LOCALAPPDATA") or sources["project_root"])
    output_dir = Path(output_dir or (default_output / "Cinema Paradiso" / "Backups")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"cp-catalog-migration-{timestamp}.zip"
    if archive_path.exists():
        archive_path = output_dir / f"cp-catalog-migration-{timestamp}-{uuid.uuid4().hex[:8]}.zip"

    payloads = {}
    file_manifest = []
    for source, archive_name, source_kind in entries:
        payload = source.read_bytes()
        name = archive_name.as_posix()
        payloads[name] = payload
        file_manifest.append({
            "archive_path": name,
            "source_kind": source_kind,
            "size": len(payload),
            "sha256": _sha256_bytes(payload),
        })
    rollback_payloads = _catalog_rollback_payloads(sources["catalog_path"])
    if rollback_payloads:
        manifest_by_name = {item["archive_path"]: item for item in file_manifest}
        for name, payload in rollback_payloads.items():
            payloads[name] = payload
            entry = manifest_by_name.get(name)
            if entry is None:
                entry = {"archive_path": name}
                file_manifest.append(entry)
                manifest_by_name[name] = entry
            entry.update({
                "source_kind": "catalog_rollback_export",
                "size": len(payload),
                "sha256": _sha256_bytes(payload),
            })
    catalog_payload = _catalog_snapshot(sources["catalog_path"])
    if catalog_payload is not None:
        name = "catalog/catalog.sqlite"
        payloads[name] = catalog_payload
        file_manifest.append({
            "archive_path": name,
            "source_kind": "catalog",
            "size": len(catalog_payload),
            "sha256": _sha256_bytes(catalog_payload),
        })

    manifest = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "created_at": created_at.astimezone(timezone.utc).isoformat(),
        "app_version": _app_version(sources["project_root"]),
        "source": {
            "project_root": str(sources["project_root"]),
            "user_data_dir": str(sources["user_data_dir"]),
            "metadata_dir": str(sources["metadata_dir"]),
        },
        "files": file_manifest,
        "totals": {
            "files": len(file_manifest),
            "bytes": sum(item["size"] for item in file_manifest),
        },
        "semantic_counts": _semantic_counts(payloads),
    }
    temporary = archive_path.with_name(f".{archive_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for name, payload in payloads.items():
                archive.writestr(name, payload)
            archive.writestr("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)
    try:
        verify_backup(archive_path)
        _verify_rollback_shadow(archive_path)
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise
    return archive_path, manifest


def verify_backup(archive_path):
    archive_path = Path(archive_path).resolve()
    if not archive_path.is_file():
        raise BackupError(f"Backup not found: {archive_path}")
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            if archive.testzip() is not None:
                raise BackupError("Backup ZIP integrity check failed")
            try:
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
            except (KeyError, UnicodeDecodeError, ValueError) as error:
                raise BackupError("Backup manifest is missing or invalid") from error
            if manifest.get("format") != BACKUP_FORMAT or manifest.get("version") not in {1, 2, BACKUP_VERSION}:
                raise BackupError("Unsupported backup format or version")
            payloads = {}
            for item in manifest.get("files", []):
                name = str(item.get("archive_path") or "")
                try:
                    payload = archive.read(name)
                except KeyError as error:
                    raise BackupError(f"Backup entry is missing: {name}") from error
                if len(payload) != int(item.get("size", -1)):
                    raise BackupError(f"Backup entry size mismatch: {name}")
                if _sha256_bytes(payload) != item.get("sha256"):
                    raise BackupError(f"Backup entry hash mismatch: {name}")
                payloads[name] = payload
            if manifest.get("semantic_counts") != _semantic_counts(payloads):
                raise BackupError("Backup semantic record counts do not match the archived data")
            return manifest
    except zipfile.BadZipFile as error:
        raise BackupError("Backup is not a valid ZIP archive") from error


def _safe_restore_target(destination, archive_name):
    destination = Path(destination).resolve()
    relative = PurePosixPath(archive_name)
    if relative.is_absolute() or ".." in relative.parts:
        raise BackupError(f"Unsafe backup path: {archive_name}")
    target = destination.joinpath(*relative.parts).resolve()
    if target != destination and destination not in target.parents:
        raise BackupError(f"Backup path escapes restore directory: {archive_name}")
    return target


def restore_backup(archive_path, destination):
    manifest = verify_backup(archive_path)
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise BackupError(f"Restore destination is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="cp-restore-", dir=str(destination.parent)))
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for item in manifest.get("files", []):
                name = item["archive_path"]
                target = _safe_restore_target(staging, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if destination.exists():
            destination.rmdir()
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination, manifest


def main():
    parser = argparse.ArgumentParser(description="Back up and verify Cinema Paradiso state before catalog migration.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--project-root", default=Path(__file__).resolve().parents[1])
    backup.add_argument("--output-dir", default=None)
    verify = subparsers.add_parser("verify")
    verify.add_argument("archive")
    restore = subparsers.add_parser("restore")
    restore.add_argument("archive")
    restore.add_argument("destination")
    args = parser.parse_args()

    if args.command == "backup":
        archive, manifest = create_backup(args.project_root, args.output_dir)
        print(json.dumps({"archive": str(archive), **manifest["totals"], "semantic_counts": manifest["semantic_counts"]}, indent=2))
    elif args.command == "verify":
        manifest = verify_backup(args.archive)
        print(json.dumps({"verified": str(Path(args.archive).resolve()), **manifest["totals"], "semantic_counts": manifest["semantic_counts"]}, indent=2))
    else:
        destination, manifest = restore_backup(args.archive, args.destination)
        print(json.dumps({"restored": str(destination), **manifest["totals"], "semantic_counts": manifest["semantic_counts"]}, indent=2))


if __name__ == "__main__":
    main()
