import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.player_runtime import (  # noqa: E402
    PLAYER_RUNTIME_SCHEMA,
    PLAYER_SELECTOR_SCHEMA,
    sha256_file,
    validate_player_manifest,
)


BUILD_METADATA_SCHEMA = "cinema-paradiso-player-build-v1"
FORBIDDEN_NAMES = {
    "config.json",
    "res_cache.json",
    "providers.json",
    "playback-history.db",
    "canonical_catalog.db",
}
FORBIDDEN_ROOTS = {
    "cache",
    "data",
    "downloads",
    "logs",
    "profiles",
    "test-results",
}


def load_build_metadata(path):
    metadata = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if metadata.get("schema") != BUILD_METADATA_SCHEMA:
        raise ValueError("Native player build metadata schema is invalid")
    return metadata


def should_include_player_file(relative_path):
    relative = Path(relative_path)
    lowered_parts = [part.lower() for part in relative.parts]
    if not lowered_parts:
        return False
    if lowered_parts[0] in FORBIDDEN_ROOTS:
        return False
    if relative.name.lower() in FORBIDDEN_NAMES:
        return False
    if relative.suffix.lower() in {".pdb", ".log"}:
        return False
    if relative.name == "cinema-paradiso-player.json":
        return False
    return True


def assemble_player_runtime(staged_runtime, output_root, metadata_path):
    staged_runtime = Path(staged_runtime).resolve()
    output_root = Path(output_root).resolve()
    metadata = load_build_metadata(metadata_path)
    bundle_version = str(metadata.get("bundle_version") or "").strip()
    if not bundle_version or Path(bundle_version).name != bundle_version:
        raise ValueError("Native player bundle version is invalid")
    destination = output_root / "versions" / bundle_version
    if destination.exists():
        raise FileExistsError(f"Native player bundle already exists: {destination}")

    staged_entries = list(staged_runtime.rglob("*"))
    if any(path.is_symlink() for path in staged_entries):
        raise ValueError("Native player staging may not contain symbolic links")
    source_files = [
        path
        for path in staged_entries
        if path.is_file() and should_include_player_file(path.relative_to(staged_runtime))
    ]
    if not source_files:
        raise FileNotFoundError(f"No native player files found under: {staged_runtime}")
    versions_root = output_root / "versions"
    versions_root.mkdir(parents=True, exist_ok=True)
    # Python 3.12's secure temporary-directory helper uses an owner-only ACL
    # on Windows. A
    # renamed runtime would keep that ACL and be unreadable by the normal
    # desktop user when assembly runs under an isolated build identity.
    temporary_parent = versions_root / f".assembling-{uuid.uuid4().hex}"
    temporary_parent.mkdir()
    working_destination = temporary_parent / bundle_version
    working_destination.mkdir()
    try:
        for source in source_files:
            relative = source.relative_to(staged_runtime)
            target = working_destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        required_files = [
            path.relative_to(working_destination).as_posix()
            for path in sorted(working_destination.rglob("*"))
            if path.is_file()
        ]
        hashes = {
            relative: sha256_file(
                working_destination / Path(*relative.split("/"))
            )
            for relative in required_files
        }
        pinned_hashes = metadata.get("pinned_sha256") or {}
        for relative, expected in pinned_hashes.items():
            if hashes.get(relative, "").upper() != str(expected).upper():
                raise ValueError(f"Pinned runtime hash does not match: {relative}")

        manifest_fields = {
            key: metadata[key]
            for key in (
                "bundle_version",
                "player_version",
                "ipc_protocol_version",
                "mpv_version",
                "mpv_commit",
                "mpv_dll",
                "qt_version",
                "architecture",
                "build_flags",
                "sources",
                "licenses",
            )
        }
        manifest = {
            "schema": PLAYER_RUNTIME_SCHEMA,
            **manifest_fields,
            "required_files": required_files,
            "sha256": hashes,
        }
        (working_destination / "cinema-paradiso-player.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        validate_player_manifest(working_destination, verify_hashes=True)
        working_destination.replace(destination)
    finally:
        shutil.rmtree(temporary_parent, ignore_errors=True)

    selector_path = output_root / "current.json"
    temporary_selector = output_root / ".current.json.tmp"
    temporary_selector.write_text(
        json.dumps({
            "schema": PLAYER_SELECTOR_SCHEMA,
            "bundle_version": bundle_version,
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_selector.replace(selector_path)
    return destination


def main():
    parser = argparse.ArgumentParser(
        description="Assemble and verify a pinned Cinema Paradiso Player runtime."
    )
    parser.add_argument("--staged-runtime", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--metadata",
        default=PROJECT_ROOT / "native" / "player" / "runtime-metadata.json",
    )
    args = parser.parse_args()
    print(assemble_player_runtime(args.staged_runtime, args.output_root, args.metadata))


if __name__ == "__main__":
    main()
