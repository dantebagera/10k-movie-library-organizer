import json
import re
import socket
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher


TMDB_API_ROOT = "https://api.themoviedb.org/3"
TMDB_IMAGE_ROOT = "https://image.tmdb.org/t/p"
PARSER_VERSION = 2
MATCHER_VERSION = 2
MAX_QUERY_VARIANTS = 6
MAX_MERGED_CANDIDATES = 20


class IPTVTMDBError(RuntimeError):
    def __init__(self, message, *, status=0, retryable=False, retry_after=0):
        super().__init__(message)
        self.status = int(status or 0)
        self.retryable = bool(retryable)
        self.retry_after = max(0, int(retry_after or 0))


def _text(value):
    return str(value or "").strip()


def extract_year(value):
    match = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", _text(value))
    return int(match.group(1)) if match else 0


_year = extract_year


_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2}|21\d{2})\b")
_ARABIC_RE = re.compile(r"[\u0600-\u06ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_NOISE_RE = re.compile(
    r"(?i)(?:\b(?:2160p|1080p|720p|4k|uhd|fhd|hdcam|camrip|cam|web[- .]?dl|webrip|"
    r"bluray|brrip|hdrip|x26[45]|hevc|multi|dubbed|subbed|subtitle(?:d|s)?|translated|"
    r"eng(?:lish)?\s+audio|arabic\s+audio|dual\s+audio)\b|"
    r"(?:مدبلج|مترجم|ترجمة|دبلجة\s*(?:إنجليزي(?:ة)?|انجليزي(?:ة)?)?|صوت\s*(?:إنجليزي|انجليزي|عربي)))"
)


def _clean_alias(value):
    text = unicodedata.normalize("NFKC", _text(value))
    text = _NOISE_RE.sub(" ", text)
    text = "".join(character if character.isalnum() else " " for character in text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def parse_provider_title(value, explicit_year=0):
    raw = unicodedata.normalize("NFKC", _text(value))
    year = extract_year(explicit_year)
    parenthesized = re.findall(r"\(\s*(19\d{2}|20\d{2}|21\d{2})\s*\)", raw)
    if not year and parenthesized:
        year = int(parenthesized[-1])
    if not year:
        year = extract_year(raw)
    text = re.sub(r"\[[^\]]*\]", " ", raw)
    text = re.sub(r"\(\s*(?:19\d{2}|20\d{2}|21\d{2})\s*\)", " ", text)
    text = re.sub(r"\(\s*(?:مدبلج|مترجم|dubbed|subbed|translated)\s*\)", " ", text, flags=re.I)
    if year:
        text = re.sub(rf"(?:[-–—|:]\s*)?\b{year}\b\s*$", " ", text)
    text = _NOISE_RE.sub(" ", text)
    text = re.sub(r"\s+[-–—|]\s*$", " ", text)

    latin_aliases = []
    arabic_aliases = []
    # Script transitions are identity evidence. Keep punctuation and digits with
    # the surrounding run, but never flatten two languages into one TMDB query.
    runs = re.findall(r"[A-Za-z0-9][A-Za-z0-9\s'&:.,!?\-]*|[\u0600-\u06ff0-9][\u0600-\u06ff0-9\s'&:.,!?\-]*", text)
    for run in runs:
        alias = _clean_alias(run)
        if len(alias) < 2:
            continue
        if _ARABIC_RE.search(run):
            arabic_aliases.append(alias)
        elif _LATIN_RE.search(run):
            latin_aliases.append(alias)
        elif alias.isdigit():
            latin_aliases.append(alias)
    if not runs:
        alias = _clean_alias(text)
        if alias:
            (arabic_aliases if _ARABIC_RE.search(text) else latin_aliases).append(alias)
    latin_aliases = list(dict.fromkeys(latin_aliases))
    arabic_aliases = list(dict.fromkeys(arabic_aliases))
    aliases = list(dict.fromkeys([*latin_aliases, *arabic_aliases]))
    return {
        "raw_title": raw,
        "year": int(year or 0),
        "latin_aliases": latin_aliases,
        "arabic_aliases": arabic_aliases,
        "aliases": aliases,
        "primary_alias": (latin_aliases or arabic_aliases or [""])[0],
        "parser_version": PARSER_VERSION,
    }


def clean_provider_title(value, explicit_year=0):
    return parse_provider_title(value, explicit_year).get("primary_alias", "")


def _candidate_names(candidate):
    alternative_titles = candidate.get("alternative_titles")
    alternative_rows = (
        alternative_titles.get("titles", [])
        if isinstance(alternative_titles, dict)
        else []
    )
    values = [candidate.get("title"), candidate.get("original_title")]
    values.extend(
        row.get("title")
        for row in alternative_rows
        if isinstance(row, dict)
    )
    return list(dict.fromkeys(
        name for name in (clean_provider_title(value) for value in values) if name
    ))


def score_candidate(provider_title, provider_year, candidate):
    parsed = provider_title if isinstance(provider_title, dict) else parse_provider_title(provider_title, provider_year)
    targets = parsed.get("aliases") or [parsed.get("primary_alias")]
    targets = [target for target in targets if target]
    names = _candidate_names(candidate)
    if not targets or not names:
        return 0.0
    similarity = max(SequenceMatcher(None, target, name).ratio() for target in targets for name in names)
    score = similarity * 80.0
    if any(target in names for target in targets):
        score = 85.0
    expected_year = _year(provider_year) or int(parsed.get("year") or 0)
    candidate_year = _year(candidate.get("release_date") or candidate.get("year"))
    if expected_year and candidate_year:
        difference = abs(expected_year - candidate_year)
        if difference == 0:
            score += 15.0
        elif difference == 1:
            score += 5.0
        else:
            score -= min(20.0, difference * 4.0)
    elif not expected_year:
        score += 5.0
    # Shared franchise prefixes are weak evidence; missing distinctive sequel
    # tokens are a strong negative signal.
    stop = {"the", "and", "movie", "film", "part", "episode", "a", "an", "of", "to", "in"}
    target_tokens = set(max(targets, key=len).split()) - stop
    candidate_tokens = set(max(names, key=len).split()) - stop
    missing = {token for token in target_tokens - candidate_tokens if len(token) >= 5}
    conflicting = {token for token in candidate_tokens - target_tokens if len(token) >= 6}
    if missing and candidate_tokens:
        score -= min(24.0, len(missing) * 8.0)
    if missing and conflicting:
        score -= min(12.0, len(conflicting) * 4.0)
    return round(max(0.0, min(100.0, score)), 3)


def choose_automatic_match(provider_title, provider_year, candidates):
    parsed = provider_title if isinstance(provider_title, dict) else parse_provider_title(provider_title, provider_year)
    scored = sorted(
        [
            {**candidate, "match_score": score_candidate(parsed, provider_year, candidate)}
            for candidate in candidates or []
            if isinstance(candidate, dict) and candidate.get("id")
        ],
        key=lambda row: (-row["match_score"], int(row.get("id") or 0)),
    )
    if not scored:
        return {"state": "unmatched", "accepted": None, "candidates": []}
    best = scored[0]
    second = scored[1] if len(scored) > 1 else None
    credible_rival = bool(
        second
        and second["match_score"] >= 84.0
        and best["match_score"] - second["match_score"] < 8.0
    )
    if best["match_score"] >= 94.0 and not credible_rival:
        return {"state": "matched-auto", "accepted": best, "candidates": scored[:8]}
    if best["match_score"] >= 78.0:
        return {"state": "ambiguous", "accepted": None, "candidates": scored[:8]}
    return {"state": "unmatched", "accepted": None, "candidates": scored[:8]}


def provider_id_matches(provider_title, provider_year, movie):
    parsed = provider_title if isinstance(provider_title, dict) else parse_provider_title(provider_title, provider_year)
    score = score_candidate(parsed, provider_year, movie)
    expected_year = _year(provider_year) or int(parsed.get("year") or 0)
    actual_year = _year(movie.get("release_date") or movie.get("year"))
    year_ok = not expected_year or not actual_year or abs(expected_year - actual_year) <= 1
    return score >= 90.0 and year_ok, score


def bounded_search_candidates(client, parsed):
    parsed = parsed if isinstance(parsed, dict) else parse_provider_title(parsed)
    aliases = (parsed.get("latin_aliases") or []) + (parsed.get("arabic_aliases") or [])
    aliases = list(dict.fromkeys(alias for alias in aliases if alias))[:MAX_QUERY_VARIANTS]
    year = int(parsed.get("year") or 0)
    merged = {}
    attempts = []
    for phase, use_year in (("year", year), ("no-year", 0)):
        phase_found = False
        for alias in aliases:
            rows = client.search_movies(alias, use_year)
            attempts.append({"phase": phase, "alias": alias, "year": int(use_year or 0), "results": len(rows)})
            for row in rows:
                if not isinstance(row, dict) or not row.get("id"):
                    continue
                tmdb_id = int(row["id"])
                current = merged.get(tmdb_id, {})
                merged[tmdb_id] = {**current, **row, "search_alias": alias, "search_phase": phase}
                phase_found = True
                if len(merged) >= MAX_MERGED_CANDIDATES:
                    break
            if len(merged) >= MAX_MERGED_CANDIDATES:
                break
        if phase_found or not year or len(merged) >= MAX_MERGED_CANDIDATES:
            break
    return list(merged.values()), attempts


def _image(path, size):
    path = _text(path)
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{TMDB_IMAGE_ROOT}/{size}/{path.lstrip('/')}"


def normalize_tmdb_movie(payload):
    payload = payload if isinstance(payload, dict) else {}
    credits = payload.get("credits") if isinstance(payload.get("credits"), dict) else {}
    keywords_payload = payload.get("keywords") if isinstance(payload.get("keywords"), dict) else {}
    release_payload = payload.get("release_dates") if isinstance(payload.get("release_dates"), dict) else {}
    crew = credits.get("crew") if isinstance(credits.get("crew"), list) else []
    cast = credits.get("cast") if isinstance(credits.get("cast"), list) else []
    directors = [row for row in crew if isinstance(row, dict) and row.get("job") == "Director"]
    writers = [
        row for row in crew
        if isinstance(row, dict) and row.get("job") in {"Writer", "Screenplay", "Story"}
    ]
    certification = ""
    release_groups = release_payload.get("results") if isinstance(release_payload.get("results"), list) else []
    ordered_groups = sorted(
        [row for row in release_groups if isinstance(row, dict)],
        key=lambda row: (0 if row.get("iso_3166_1") == "US" else 1, _text(row.get("iso_3166_1"))),
    )
    for group in ordered_groups:
        releases = group.get("release_dates") if isinstance(group.get("release_dates"), list) else []
        certification = next((_text(row.get("certification")) for row in releases if isinstance(row, dict) and _text(row.get("certification"))), "")
        if certification:
            break
    collection = payload.get("belongs_to_collection") if isinstance(payload.get("belongs_to_collection"), dict) else {}
    return {
        "tmdb_id": int(payload.get("id") or 0),
        "title": _text(payload.get("title")) or _text(payload.get("original_title")) or "Untitled",
        "original_title": _text(payload.get("original_title")),
        "plot": _text(payload.get("overview")),
        "poster_url": _image(payload.get("poster_path"), "w500"),
        "backdrop_url": _image(payload.get("backdrop_path"), "w1280"),
        "genres": [
            {"id": int(row.get("id") or 0), "name": _text(row.get("name"))}
            for row in payload.get("genres", []) if isinstance(row, dict) and row.get("id") and _text(row.get("name"))
        ],
        "rating": float(payload.get("vote_average") or 0),
        "vote_count": int(payload.get("vote_count") or 0),
        "release_date": _text(payload.get("release_date")),
        "year": _year(payload.get("release_date")),
        "runtime": int(payload.get("runtime") or 0),
        "original_language": _text(payload.get("original_language")),
        "imdb_id": _text(payload.get("imdb_id")) if re.fullmatch(r"tt[0-9]{5,12}", _text(payload.get("imdb_id"))) else "",
        "languages": [
            {"code": _text(row.get("iso_639_1")), "name": _text(row.get("english_name") or row.get("name"))}
            for row in payload.get("spoken_languages", []) if isinstance(row, dict) and _text(row.get("iso_639_1"))
        ],
        "countries": [
            {"code": _text(row.get("iso_3166_1")), "name": _text(row.get("name"))}
            for row in payload.get("production_countries", []) if isinstance(row, dict) and _text(row.get("iso_3166_1"))
        ],
        "certification": certification,
        "directors": directors,
        "writers": writers,
        "cast": cast[:40],
        "collection": {
            "id": int(collection.get("id") or 0),
            "name": _text(collection.get("name")),
        } if collection.get("id") else {},
        "keywords": [
            {"id": int(row.get("id") or 0), "name": _text(row.get("name"))}
            for row in keywords_payload.get("keywords", []) if isinstance(row, dict) and row.get("id") and _text(row.get("name"))
        ],
        "raw": payload,
    }


class IPTVTMDBClient:
    def __init__(self, settings, *, timeout=15, open_url=None, api_root=TMDB_API_ROOT, min_request_interval=0.25):
        self.settings = settings
        self.timeout = max(1, int(timeout or 15))
        self.open_url = open_url or urllib.request.urlopen
        self.api_root = str(api_root).rstrip("/")
        self.min_request_interval = max(0.0, float(min_request_interval or 0))
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0

    def _pace_request(self):
        with self._request_lock:
            wait_for = self.min_request_interval - (time.monotonic() - self._last_request_at)
            if wait_for > 0:
                time.sleep(wait_for)
            self._last_request_at = time.monotonic()

    def _request(self, path, params=None):
        credential_type, credential = self.settings.credential()
        query = dict(params or {})
        headers = {"Accept": "application/json", "User-Agent": "Cinema-Paradiso-IPTV/1"}
        if credential_type == "bearer":
            headers["Authorization"] = f"Bearer {credential}"
        else:
            query["api_key"] = credential
        encoded = urllib.parse.urlencode(query)
        url = f"{self.api_root}/{str(path).lstrip('/')}"
        if encoded:
            url = f"{url}?{encoded}"
        request = urllib.request.Request(url, headers=headers)
        try:
            self._pace_request()
            response = self.open_url(request, timeout=self.timeout)
            with response:
                body = response.read(8 * 1024 * 1024)
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise IPTVTMDBError("IPTV TMDB returned an invalid response", retryable=True)
            return payload
        except urllib.error.HTTPError as error:
            status = int(error.code or 0)
            retry_after = error.headers.get("Retry-After", "0") if error.headers else "0"
            try:
                retry_after = int(float(retry_after or 0))
            except (TypeError, ValueError):
                retry_after = 0
            if status == 401:
                raise IPTVTMDBError("IPTV TMDB authentication failed", status=401) from None
            if status == 429:
                raise IPTVTMDBError(
                    "IPTV TMDB rate limit reached",
                    status=429,
                    retryable=True,
                    retry_after=max(1, retry_after),
                ) from None
            raise IPTVTMDBError(
                f"IPTV TMDB request failed with HTTP {status}",
                status=status,
                retryable=status >= 500,
            ) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
            reason = getattr(error, "reason", error)
            label = "timed out" if isinstance(reason, (socket.timeout, TimeoutError)) else "could not connect"
            raise IPTVTMDBError(f"IPTV TMDB {label}", retryable=True) from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise IPTVTMDBError("IPTV TMDB returned invalid JSON", retryable=True) from None

    def validate(self):
        payload = self._request("configuration")
        return bool(payload.get("images"))

    def search_movies(self, title, year=0, page=1):
        params = {"query": _text(title), "page": max(1, int(page or 1)), "include_adult": "false"}
        if _year(year):
            params["year"] = _year(year)
        payload = self._request("search/movie", params)
        return [row for row in payload.get("results", []) if isinstance(row, dict)]

    def movie(self, tmdb_id, language=""):
        tmdb_id = int(tmdb_id or 0)
        if tmdb_id <= 0:
            raise ValueError("A valid TMDB movie ID is required")
        params = {"append_to_response": "credits,keywords,release_dates,alternative_titles"}
        if _text(language):
            params["language"] = _text(language)
        return self._request(f"movie/{tmdb_id}", params)

    def normalized_movie(self, tmdb_id, language=""):
        return normalize_tmdb_movie(self.movie(tmdb_id, language=language))
