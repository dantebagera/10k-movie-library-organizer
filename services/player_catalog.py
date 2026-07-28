import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class PlayerMediaError(ValueError):
    pass


def _is_within(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def _safe_poster_reference(value):
    text = str(value or "").strip()
    if not text or len(text) > 2048:
        return ""
    if text.startswith("/api/"):
        return text
    try:
        parsed = urlsplit(text)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def resolve_library_media(repository, path_key, library_roots):
    if not isinstance(path_key, str):
        raise PlayerMediaError("A library file identity is required")
    raw_key = path_key.strip()
    if not raw_key:
        raise PlayerMediaError("The library file identity is invalid")
    requested_key = os.path.normcase(os.path.normpath(raw_key))
    if (
        not requested_key
        or len(requested_key) > 32768
        or "\x00" in requested_key
        or "://" in raw_key
    ):
        raise PlayerMediaError("The library file identity is invalid")

    candidate = repository.store.owned_movie_candidate(path_key=requested_key)
    if not candidate:
        raise PlayerMediaError("The selected file is not in the Cinema Paradiso library")
    resolved_key = os.path.normcase(os.path.normpath(str(candidate.get("path_key") or "")))
    if resolved_key != requested_key:
        raise PlayerMediaError("The selected library identity does not match its catalog record")

    path = os.path.abspath(str(candidate.get("path") or ""))
    normalized_path = os.path.normcase(os.path.realpath(path))
    roots = [
        os.path.normcase(os.path.realpath(os.path.abspath(str(root))))
        for root in library_roots or []
        if str(root or "").strip()
    ]
    if not roots or not any(_is_within(normalized_path, root) for root in roots):
        raise PlayerMediaError("The selected file is outside configured library roots")
    if not os.path.isfile(path):
        raise PlayerMediaError("The selected library file is missing")

    canonical = candidate.get("relational_canonical") or {}
    title = str(
        canonical.get("title")
        or candidate.get("identity_title")
        or candidate.get("parsed_title")
        or Path(path).stem
    ).strip()
    year = str(
        canonical.get("year")
        or candidate.get("identity_year")
        or candidate.get("parsed_year")
        or ""
    ).strip()
    movie_key = str(canonical.get("movie_key") or "").strip()
    poster_reference = _safe_poster_reference(
        canonical.get("poster_url")
        or canonical.get("poster_path")
        or ""
    )
    return {
        "path_key": requested_key,
        "movie_key": movie_key,
        "path": path,
        "filename": str(candidate.get("filename") or Path(path).name)[:512],
        "file_size": int(candidate.get("size") or os.path.getsize(path)),
        "frame_rate": float(candidate.get("video_frame_rate") or 0),
        "title": title[:512] or Path(path).stem[:512],
        "year": year[:16],
        "tmdb_id": str(canonical.get("tmdb_id") or candidate.get("tmdb_id") or "")[:64],
        "imdb_id": str(canonical.get("imdb_id") or candidate.get("imdb_id") or "")[:64],
        "release_date": str(canonical.get("release_date") or "")[:32],
        "poster_reference": poster_reference,
    }
