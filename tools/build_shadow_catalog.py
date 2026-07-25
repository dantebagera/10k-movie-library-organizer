import argparse
import json
import os
import sys
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.catalog_store import CatalogStore
from tools.catalog_migration_backup import BackupError, verify_backup


CATALOG_TOP_LEVEL_DOCUMENTS = frozenset({
    "user_lists.json",
    "user_collections.json",
    "followed_releases.json",
})


def _is_catalog_source_document(name):
    name = str(name or "")
    if name in CATALOG_TOP_LEVEL_DOCUMENTS:
        return True
    parts = PurePosixPath(name).parts
    return (
        len(parts) == 2
        and parts[0] == "app_metadata"
        and parts[1].lower().endswith(".json")
    )


def _load_documents(archive_path, manifest):
    documents = {}
    with zipfile.ZipFile(archive_path, "r") as archive:
        for item in manifest.get("files", []):
            archive_name = str(item.get("archive_path") or "")
            if not archive_name.startswith("user-data/") or not archive_name.endswith(".json"):
                continue
            relative_name = archive_name.removeprefix("user-data/")
            if not _is_catalog_source_document(relative_name):
                continue
            try:
                document = json.loads(archive.read(archive_name).decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise BackupError(f"Cannot import invalid JSON document: {archive_name}") from error
            documents[relative_name] = document
    return documents


def build_shadow_catalog(archive_path, database_path):
    archive_path = Path(archive_path).resolve()
    database_path = Path(database_path).resolve()
    manifest = verify_backup(archive_path)
    documents = _load_documents(archive_path, manifest)
    temporary = database_path.with_name(f".{database_path.name}.building")
    for candidate in (temporary, Path(f"{temporary}-wal"), Path(f"{temporary}-shm")):
        candidate.unlink(missing_ok=True)
    store = CatalogStore(temporary)
    store.import_documents(documents, manifest)
    report = store.parity_report(manifest.get("semantic_counts", {}))
    if not report.get("passed"):
        raise BackupError(f"Shadow catalog parity failed: {json.dumps(report, sort_keys=True)}")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    os.replace(temporary, database_path)
    for suffix in ("-wal", "-shm"):
        Path(f"{temporary}{suffix}").unlink(missing_ok=True)
    final_store = CatalogStore(database_path)
    final_report = final_store.parity_report(manifest.get("semantic_counts", {}))
    if not final_report.get("passed"):
        database_path.unlink(missing_ok=True)
        raise BackupError("Final shadow catalog failed parity after activation")
    return database_path, final_report


def main():
    parser = argparse.ArgumentParser(description="Build a read-only Cinema Paradiso shadow catalog from a verified backup.")
    parser.add_argument("archive")
    parser.add_argument("--database", default=None)
    args = parser.parse_args()
    default_root = Path(os.environ.get("LOCALAPPDATA") or Path.cwd()) / "Cinema Paradiso" / "Shadow"
    database = Path(args.database or (default_root / "catalog-shadow-v1.sqlite"))
    path, report = build_shadow_catalog(args.archive, database)
    print(json.dumps({"database": str(path), **report}, indent=2))


if __name__ == "__main__":
    main()
