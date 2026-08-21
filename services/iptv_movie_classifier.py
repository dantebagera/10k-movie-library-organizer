"""Authoritative deterministic classification for provider-local IPTV Movies.

The classifier deals only in credential-free title and playlist evidence.  It
does not know about providers, databases, TMDB, or playback, which keeps the
same rules reusable for every isolated provider store.
"""

import hashlib
import json
import re
import unicodedata


CLASSIFIER_VERSION = 1
CATEGORIES = ("Film", "Sports", "Plays", "Music", "Misc")
UNCLASSIFIED = "unclassified"
MAX_OLLAMA_RESPONSE_BYTES = 16 * 1024
MAX_OLLAMA_SAMPLE_TITLES = 25
MAX_OLLAMA_TITLE_CHARS = 240
MAX_OLLAMA_EVIDENCE_CHARS = 600

_ARABIC_MARKS_RE = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_NON_WORD_RE = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)


def _text(value):
    return str(value or "").strip()


def normalize_classification_text(value):
    """Return stable lookup text without changing the displayed provider text."""

    text = unicodedata.normalize("NFKC", _text(value)).casefold()
    text = text.replace("\u0640", "")
    text = _ARABIC_MARKS_RE.sub("", text)
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    return re.sub(r"\s+", " ", _NON_WORD_RE.sub(" ", text)).strip()


def _contains(text, phrases):
    padded = f" {text} "
    return any(f" {normalize_classification_text(phrase)} " in padded for phrase in phrases)


_SOURCE_RULES = (
    (
        "Sports",
        0.99,
        (
            "wwe", "wrestlemania", "football match", "soccer match", "full match",
            "premier league", "champions league", "world cup", "tournament", "ufc",
            "boxing", "مباراة", "مباريات", "بطولة", "الدوري", "كأس العالم", "مصارعة",
        ),
    ),
    (
        "Plays",
        0.98,
        (
            "stage play", "theatre play", "theater play", "recorded play", "مسرحية",
            "مسرحيات", "المسرح القومي", "عرض مسرحي",
        ),
    ),
    (
        "Music",
        0.97,
        (
            "concert", "live concert", "music concert", "concert film", "music festival", "حفلة موسيقية",
            "حفل موسيقي", "حفل غنائي", "حفلات", "كونسرت",
        ),
    ),
    (
        "Misc",
        0.96,
        (
            "award ceremony", "opening ceremony", "closing ceremony", "lecture", "sermon",
            "conference keynote", "حفل توزيع الجوائز", "مراسم", "محاضرة", "ندوة", "خطبة",
        ),
    ),
    (
        "Film",
        0.94,
        (
            "documentary film", "feature film", "short film", "movie", "movies", "cinema",
            "documentary", "فيلم وثائقي", "فيلم", "افلام", "سينما",
        ),
    ),
)

_PLAYLIST_RULES = {
    "Sports": (
        "sports", "football", "soccer", "wwe", "wrestling", "matches", "رياضة", "رياضي",
        "مباريات", "مصارعة",
    ),
    "Plays": ("plays", "theatre", "theater", "مسرحيات", "مسرح"),
    "Music": ("music", "concerts", "concert", "موسيقى", "حفلات"),
    "Misc": ("lectures", "ceremonies", "محاضرات", "مراسم"),
    "Film": ("movies", "movie", "films", "film", "cinema", "افلام", "سينما"),
}

_INHERENTLY_UNCLEAR_PLAYLISTS = (
    "on demand", "shows", "show", "masspero", "weekend evening", "week end evening",
    "tawaasheeh", "تواشيح", "منوعات", "variety",
)


def _decision(category=UNCLASSIFIED, confidence=0.0, method="deterministic", evidence=None, *, mixed=False, manual_lock=False, review_reason=""):
    return {
        "category": category,
        "status": "classified" if category in CATEGORIES and not mixed else "review",
        "confidence": round(max(0.0, min(1.0, float(confidence or 0))), 4),
        "method": _text(method) or "deterministic",
        "evidence": evidence if isinstance(evidence, dict) else {},
        "mixed": bool(mixed),
        "manual_lock": bool(manual_lock),
        "review_reason": _text(review_reason),
        "classifier_version": CLASSIFIER_VERSION,
    }


def classify_title_evidence(title):
    """Classify only explicit source-title evidence; never guess Film by default."""

    normalized = normalize_classification_text(title)
    if not normalized:
        return _decision(evidence={"normalized_title": ""}, review_reason="missing-title")
    for category, confidence, phrases in _SOURCE_RULES:
        matched = [phrase for phrase in phrases if _contains(normalized, (phrase,))]
        if matched:
            return _decision(
                category,
                confidence,
                "source-rule",
                {"normalized_title": normalized, "matched_terms": matched[:5]},
            )
    return _decision(
        evidence={"normalized_title": normalized},
        review_reason="no-deterministic-source-rule",
    )


def classify_playlist(playlist_name, sample_titles=()):
    """Return a playlist default, or review when the playlist is mixed/unclear."""

    normalized = normalize_classification_text(playlist_name)
    sample_decisions = [classify_title_evidence(title) for title in list(sample_titles or ())[:MAX_OLLAMA_SAMPLE_TITLES]]
    sample_categories = sorted({row["category"] for row in sample_decisions if row["category"] in CATEGORIES})
    named_categories = [category for category, phrases in _PLAYLIST_RULES.items() if _contains(normalized, phrases)]
    inherently_unclear = _contains(normalized, _INHERENTLY_UNCLEAR_PLAYLISTS)
    contradictory = len(sample_categories) > 1 or (
        bool(named_categories) and bool(sample_categories) and any(row not in named_categories for row in sample_categories)
    )
    if inherently_unclear or contradictory or len(named_categories) > 1:
        return _decision(
            evidence={
                "normalized_playlist": normalized,
                "playlist_categories": named_categories,
                "sample_categories": sample_categories,
                "sample_count": len(sample_decisions),
            },
            mixed=True,
            review_reason="mixed-or-unclear-playlist",
        )
    category = named_categories[0] if len(named_categories) == 1 else UNCLASSIFIED
    if category in CATEGORIES:
        return _decision(
            category,
            0.96,
            "playlist-rule",
            {
                "normalized_playlist": normalized,
                "playlist_categories": named_categories,
                "sample_categories": sample_categories,
                "sample_count": len(sample_decisions),
            },
        )
    if len(sample_categories) == 1 and sample_decisions:
        explicit = [row for row in sample_decisions if row["category"] == sample_categories[0]]
        if len(explicit) == len(sample_decisions):
            return _decision(
                sample_categories[0],
                min(row["confidence"] for row in explicit),
                "playlist-sample-rule",
                {"normalized_playlist": normalized, "sample_categories": sample_categories, "sample_count": len(explicit)},
            )
    return _decision(
        evidence={"normalized_playlist": normalized, "sample_categories": sample_categories},
        review_reason="no-high-confidence-playlist-default",
    )


def classify_source(title, playlist_name="", *, playlist_decision=None, manual_category="", manual_lock=False):
    """Apply manual lock, then source evidence, then a clear playlist default."""

    if manual_lock:
        if manual_category not in CATEGORIES:
            raise ValueError("A manual IPTV movie classification must use one of the five categories")
        return _decision(
            manual_category,
            1.0,
            "manual",
            {"manual_category": manual_category},
            manual_lock=True,
        )
    source = classify_title_evidence(title)
    playlist = playlist_decision if isinstance(playlist_decision, dict) else classify_playlist(playlist_name)
    if source["category"] in CATEGORIES:
        evidence = dict(source["evidence"])
        evidence["playlist_default"] = playlist.get("category", UNCLASSIFIED)
        evidence["playlist_mixed"] = bool(playlist.get("mixed"))
        return {**source, "evidence": evidence}
    if (
        playlist.get("category") in CATEGORIES
        and not playlist.get("mixed")
        and float(playlist.get("confidence") or 0) >= 0.9
    ):
        return _decision(
            playlist["category"],
            playlist["confidence"],
            "playlist-default",
            {
                "normalized_title": normalize_classification_text(title),
                "playlist": playlist.get("evidence") or {},
            },
        )
    return _decision(
        evidence={
            "normalized_title": normalize_classification_text(title),
            "playlist": playlist.get("evidence") or {},
        },
        mixed=bool(playlist.get("mixed")),
        review_reason="source-requires-review",
    )


def build_ollama_classification_payload(playlist_name, sample_titles=()):
    """Build the bounded, credential-free evidence package allowed by the plan."""

    playlist = _text(playlist_name)[:MAX_OLLAMA_TITLE_CHARS]
    titles = []
    for value in list(sample_titles or ())[:MAX_OLLAMA_SAMPLE_TITLES]:
        title = _text(value)[:MAX_OLLAMA_TITLE_CHARS]
        if title and title not in titles:
            titles.append(title)
    canonical = json.dumps({"playlist": playlist, "titles": titles}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "playlist_name": playlist,
        "sample_titles": titles,
        "allowed_categories": list(CATEGORIES),
        "input_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "classifier_version": CLASSIFIER_VERSION,
    }


def _bounded_string(value, field, limit):
    if not isinstance(value, str):
        raise ValueError(f"Ollama classification {field} must be text")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"Ollama classification {field} is too long")
    return value


def validate_ollama_classification(payload):
    """Validate strict structured output without authorizing persistence."""

    if isinstance(payload, str):
        if len(payload.encode("utf-8")) > MAX_OLLAMA_RESPONSE_BYTES:
            raise ValueError("Ollama classification response is too large")
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as error:
            raise ValueError("Ollama classification response is invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("Ollama classification response must be an object")
    allowed = {"category", "confidence", "evidence_summary", "mixed", "uncertain", "title_exceptions"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError("Ollama classification response contains unsupported fields")
    category = payload.get("category")
    if category not in (*CATEGORIES, UNCLASSIFIED):
        raise ValueError("Ollama classification category is invalid")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("Ollama classification confidence must be between zero and one")
    evidence_summary = _bounded_string(payload.get("evidence_summary", ""), "evidence_summary", MAX_OLLAMA_EVIDENCE_CHARS)
    mixed = payload.get("mixed", False)
    uncertain = payload.get("uncertain", False)
    if not isinstance(mixed, bool) or not isinstance(uncertain, bool):
        raise ValueError("Ollama classification mixed and uncertain flags must be booleans")
    exceptions = payload.get("title_exceptions", [])
    if not isinstance(exceptions, list) or len(exceptions) > MAX_OLLAMA_SAMPLE_TITLES:
        raise ValueError("Ollama classification title exceptions are invalid or too large")
    normalized_exceptions = []
    for row in exceptions:
        if not isinstance(row, dict) or set(row) - {"title", "category", "confidence", "evidence_summary"}:
            raise ValueError("Ollama title exception is invalid")
        row_category = row.get("category")
        row_confidence = row.get("confidence")
        if row_category not in CATEGORIES:
            raise ValueError("Ollama title exception category is invalid")
        if isinstance(row_confidence, bool) or not isinstance(row_confidence, (int, float)) or not 0 <= float(row_confidence) <= 1:
            raise ValueError("Ollama title exception confidence is invalid")
        normalized_exceptions.append({
            "title": _bounded_string(row.get("title", ""), "title", MAX_OLLAMA_TITLE_CHARS),
            "category": row_category,
            "confidence": float(row_confidence),
            "evidence_summary": _bounded_string(row.get("evidence_summary", ""), "evidence_summary", MAX_OLLAMA_EVIDENCE_CHARS),
        })
        if not normalized_exceptions[-1]["title"]:
            raise ValueError("Ollama title exception title is required")
    return {
        "category": category,
        "confidence": float(confidence),
        "evidence_summary": evidence_summary,
        "mixed": mixed,
        "uncertain": uncertain,
        "title_exceptions": normalized_exceptions,
        "status": "review" if mixed or uncertain or category == UNCLASSIFIED else "classified",
        "method": "ollama",
        "classifier_version": CLASSIFIER_VERSION,
    }
