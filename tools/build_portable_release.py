import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.player_runtime import (
    PLAYER_SELECTOR_SCHEMA,
    validate_player_manifest,
)


QBT_VERSION = "5.2.2"
FFMPEG_VERSION = "8.1.1"
EXCLUDED_QBT_NAMES = {
    "profile",
    "BT_backup",
    "logs",
    "incomplete",
    "downloads",
}


def read_project_version(project_root=PROJECT_ROOT):
    package_path = Path(project_root) / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    version = str(package.get("version") or "").strip()
    if not version:
        raise ValueError(f"Package version is missing: {package_path}")
    return version


def should_include_qbt_file(path):
    candidate = Path(path)
    parts = {part.lower() for part in candidate.parts}
    if any(name.lower() in parts for name in EXCLUDED_QBT_NAMES):
        return False
    if candidate.suffix.lower() == ".pdb":
        return False
    return True


def build_qbt_manifest(version=QBT_VERSION, app_version=None):
    app_version = app_version or read_project_version()
    return {
        "name": "qBittorrent",
        "version": version,
        "source": "official qBittorrent Windows x64 release",
        "website": "https://www.qbittorrent.org/",
        "license": "GPL",
        "bundled_for": f"Cinema Paradiso {app_version}",
    }


def copy_qbt_runtime(source, destination, version=QBT_VERSION, app_version=None):
    source = Path(source)
    destination = Path(destination)
    executable = source / "qbittorrent.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"qBittorrent executable not found: {executable}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if not should_include_qbt_file(relative):
            continue
        target = destination / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
    manifest = build_qbt_manifest(version, app_version=app_version)
    (destination / "cinema-paradiso-qbittorrent.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def build_ffmpeg_manifest(version=FFMPEG_VERSION, app_version=None):
    app_version = app_version or read_project_version()
    return {
        "name": "FFmpeg",
        "version": version,
        "source": "Gyan.dev Windows full build",
        "website": "https://www.gyan.dev/ffmpeg/builds/",
        "license": "GPLv3",
        "purpose": "Local IPTV remuxing to browser-compatible HLS",
        "bundled_for": f"Cinema Paradiso {app_version}",
    }


def copy_ffmpeg_runtime(source, destination, version=FFMPEG_VERSION, app_version=None):
    source = Path(source)
    destination = Path(destination)
    candidates = [source, source / "bin" / "ffmpeg.exe", source / "ffmpeg.exe"]
    executable = next((candidate for candidate in candidates if candidate.is_file() and candidate.name.lower() == "ffmpeg.exe"), None)
    if executable is None:
        raise FileNotFoundError(f"FFmpeg executable not found under: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    bin_dir = destination / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(executable, bin_dir / "ffmpeg.exe")
    ffprobe = executable.with_name("ffprobe.exe")
    if ffprobe.is_file():
        shutil.copy2(ffprobe, bin_dir / "ffprobe.exe")
    manifest = build_ffmpeg_manifest(version, app_version=app_version)
    (destination / "cinema-paradiso-ffmpeg.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def resolve_player_bundle_source(project_root, player_source=None):
    if player_source:
        return Path(player_source).resolve()
    runtime_root = Path(project_root).resolve() / "runtime" / "player"
    selector_path = runtime_root / "current.json"
    try:
        selector = json.loads(selector_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "The pinned native player runtime is missing. "
            "Provide --player-source or assemble runtime/player/current.json."
        ) from error
    if selector.get("schema") != PLAYER_SELECTOR_SCHEMA:
        raise ValueError(f"Invalid native player selector: {selector_path}")
    bundle_version = str(selector.get("bundle_version") or "").strip()
    if not bundle_version or Path(bundle_version).name != bundle_version:
        raise ValueError(f"Invalid native player bundle version: {selector_path}")
    return (runtime_root / "versions" / bundle_version).resolve()


def copy_player_runtime(source, destination, app_version=None):
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    manifest = validate_player_manifest(
        source,
        app_version=app_version or read_project_version(),
        verify_hashes=True,
    )
    bundle_version = manifest["bundle_version"]
    version_destination = destination / "versions" / bundle_version
    if version_destination.exists():
        shutil.rmtree(version_destination)
    version_destination.mkdir(parents=True, exist_ok=True)
    for relative_text in manifest["required_files"]:
        relative = Path(*relative_text.replace("\\", "/").split("/"))
        source_file = source / relative
        destination_file = version_destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, destination_file)
    shutil.copy2(
        source / "cinema-paradiso-player.json",
        version_destination / "cinema-paradiso-player.json",
    )
    selector = {
        "schema": PLAYER_SELECTOR_SCHEMA,
        "bundle_version": bundle_version,
    }
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "current.json").write_text(
        json.dumps(selector, indent=2) + "\n",
        encoding="utf-8",
    )
    validate_player_manifest(
        version_destination,
        app_version=app_version or read_project_version(),
        verify_hashes=True,
    )
    return manifest


def build_release_zip(project_root, qbt_source=None, ffmpeg_source=None, output_dir=None, player_source=None):
    project_root = Path(project_root).resolve()
    app_version = read_project_version(project_root)
    qbt_source = Path(qbt_source or (project_root / "data" / "qbittorrent" / "versions" / QBT_VERSION)).resolve()
    player_source = resolve_player_bundle_source(project_root, player_source)
    default_ffmpeg_source = project_root / "runtime" / "ffmpeg"
    ffmpeg_source = Path(ffmpeg_source).resolve() if ffmpeg_source else (default_ffmpeg_source.resolve() if default_ffmpeg_source.exists() else None)
    output_dir = Path(output_dir or (project_root / "release")).resolve()
    staging = output_dir / f"Cinema-Paradiso-{app_version}-Portable"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    ignored_roots = {
        ".git",
        ".venv",
        "node_modules",
        "data",
        "cache",
        "release",
        "runtime",
        "winapp",
        "_cf_profile",
        "test-results",
        "__pycache__",
        "config.json",
        "res_cache.json",
    }
    for item in project_root.iterdir():
        if item.name in ignored_roots or item.suffix.lower() == ".log":
            continue
        target = staging / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)
    copy_qbt_runtime(
        qbt_source,
        staging / "runtime" / "qbittorrent" / "versions" / QBT_VERSION,
        QBT_VERSION,
        app_version=app_version,
    )
    copy_player_runtime(
        player_source,
        staging / "runtime" / "player",
        app_version=app_version,
    )
    if ffmpeg_source:
        copy_ffmpeg_runtime(
            ffmpeg_source,
            staging / "runtime" / "ffmpeg",
            FFMPEG_VERSION,
            app_version=app_version,
        )
    zip_path = output_dir / f"Cinema-Paradiso-{app_version}-Portable.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for file_path in staging.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(staging.parent))
    return zip_path


def main():
    parser = argparse.ArgumentParser(description="Build the Cinema Paradiso portable release ZIP.")
    parser.add_argument("--project-root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--qbt-source", default=None)
    parser.add_argument("--ffmpeg-source", default=None)
    parser.add_argument("--player-source", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()
    print(
        build_release_zip(
            args.project_root,
            qbt_source=args.qbt_source,
            ffmpeg_source=args.ffmpeg_source,
            player_source=args.player_source,
            output_dir=args.output_dir,
        )
    )


if __name__ == "__main__":
    main()
