"""Bounded TMDB planning for normalized Discover queries.

This module owns provider parameter compilation only.  It deliberately does not
perform HTTP requests, inspect local curation state, or fetch movie details.
"""

from dataclasses import dataclass
import re

from services.advanced_search import AdvancedSearchValidationError, group_map


LOCAL_CRITERIA = {"viewing_status", "movie_list", "availability"}
SUMMARY_CRITERIA = {"genre", "year", "rating", "minimum_votes", "language", "country"}

FEED_SORTS = {
    "trending_week": "popularity.desc",
    "trending_today": "popularity.desc",
    "catalog": "popularity.desc",
    "now_playing": "popularity.desc",
    "upcoming": "primary_release_date.desc",
    "popular": "popularity.desc",
    "top_rated": "vote_average.desc",
    "best_all_time": "vote_count.desc",
}

FEED_ENDPOINTS = {
    "trending_week": "/trending/movie/week",
    "trending_today": "/trending/movie/day",
    "now_playing": "/movie/now_playing",
    "popular": "/movie/popular",
    "upcoming": "/movie/upcoming",
    "top_rated": "/movie/top_rated",
}


@dataclass(frozen=True)
class DiscoverPlan:
    query: dict
    strategy: str
    endpoint: str
    provider_params: dict
    title: str
    people: tuple
    provider_groups: tuple
    summary_groups: tuple
    local_groups: tuple
    total_scope: str
    total_label: str


def _invalid(message):
    raise AdvancedSearchValidationError(message)


def _controlled_id(value, label, pattern):
    identity = str(value.get("id", "") or "")
    if not re.fullmatch(pattern, identity):
        _invalid(f"{label} must use a controlled TMDB identity")
    return identity


def _joined_ids(group, label):
    values = [_controlled_id(value, label, r"[1-9]\d*") for value in group["values"]]
    return ("," if group.get("join") == "and" else "|").join(values)


def _numeric_bounds(value):
    operator = value["operator"]
    if operator == "exactly":
        return value["value"], value["value"]
    if operator == "at_least":
        return value["value"], None
    if operator == "at_most":
        return None, value["value"]
    return value["from"], value["to"]


def _runtime_bounds(value):
    preset = value["preset"]
    if preset == "short":
        return None, 59
    if preset == "feature":
        return 60, 149
    if preset == "long":
        return 150, None
    return value["from"], value["to"]


def build_discover_plan(query):
    normalized, groups = group_map(query, "discover")
    title_group = groups.get("title")
    title = title_group["values"][0]["text"] if title_group else ""

    if title and "keyword" in groups:
        _invalid("Title cannot be combined with Keyword in Discover because TMDB title results do not expose keyword membership")
    if title and "runtime" in groups:
        _invalid("Title cannot be combined with Runtime in Discover because TMDB title results do not expose runtime")

    for value in groups.get("genre", {}).get("values", []):
        _controlled_id(value, "Genre", r"[1-9]\d*")
    for value in groups.get("keyword", {}).get("values", []):
        _controlled_id(value, "Keyword", r"[1-9]\d*")
    people = []
    for value in groups.get("person", {}).get("values", []):
        people.append({
            **value,
            "id": _controlled_id(value, "Person", r"[1-9]\d*"),
        })
    if "language" in groups:
        _controlled_id(groups["language"]["values"][0], "Language", r"[a-z]{2,3}(?:-[a-z]{2})?")
    if "country" in groups:
        _controlled_id(groups["country"]["values"][0], "Country", r"[A-Z]{2}")

    provider_params = {}
    if "genre" in groups:
        provider_params["with_genres"] = _joined_ids(groups["genre"], "Genre")
    if "keyword" in groups:
        provider_params["with_keywords"] = _joined_ids(groups["keyword"], "Keyword")
    if "language" in groups:
        provider_params["with_original_language"] = groups["language"]["values"][0]["id"]
    if "country" in groups:
        provider_params["with_origin_country"] = groups["country"]["values"][0]["id"]
    if "minimum_votes" in groups:
        provider_params["vote_count.gte"] = groups["minimum_votes"]["values"][0]["value"]
    elif "genre" in groups:
        # Preserve the existing quick-filter noise floor.
        provider_params["vote_count.gte"] = 50
    if "year" in groups:
        lower, upper = _numeric_bounds(groups["year"]["values"][0])
        if lower is not None:
            provider_params["primary_release_date.gte"] = f"{int(lower):04d}-01-01"
        if upper is not None:
            provider_params["primary_release_date.lte"] = f"{int(upper):04d}-12-31"
    if "rating" in groups:
        lower, upper = _numeric_bounds(groups["rating"]["values"][0])
        if lower is not None:
            provider_params["vote_average.gte"] = lower
        if upper is not None:
            provider_params["vote_average.lte"] = upper
    if "runtime" in groups:
        lower, upper = _runtime_bounds(groups["runtime"]["values"][0])
        if lower is not None:
            provider_params["with_runtime.gte"] = lower
        if upper is not None:
            provider_params["with_runtime.lte"] = upper

    feed = normalized["feed"]
    requested_sort = normalized["sort"]["key"]
    provider_params["sort_by"] = (
        "original_title.asc" if requested_sort == "title.asc"
        else requested_sort if requested_sort != "auto"
        else FEED_SORTS[feed]
    )
    if feed == "top_rated" and "rating" not in groups:
        provider_params["vote_average.gte"] = 6.0
    if feed == "best_all_time":
        provider_params.setdefault("vote_average.gte", 7.5)
        provider_params.setdefault("vote_count.gte", 5000)

    local_groups = tuple(group for group in normalized["groups"] if group["type"] in LOCAL_CRITERIA)
    provider_groups = tuple(
        group for group in normalized["groups"]
        if group["type"] not in LOCAL_CRITERIA | {"title", "person"}
    )
    summary_groups = tuple(group for group in normalized["groups"] if group["type"] in SUMMARY_CRITERIA)
    page_scoped = bool(title or people or local_groups)
    limitations = []
    if title:
        limitations.append("filters applied to this TMDB title page")
    if people:
        limitations.append("role criteria applied to this provider page")
    if local_groups:
        limitations.append("local criteria applied to this page")
    total_label = "TMDB results"
    if limitations:
        total_label = "TMDB page matches — " + "; ".join(limitations)

    has_provider_filters = bool(provider_groups) or feed in {"catalog", "best_all_time"} or requested_sort != "auto"
    strategy = "title" if title else "discover"
    endpoint = "/search/movie" if title else (
        "/discover/movie" if has_provider_filters or people or local_groups else FEED_ENDPOINTS.get(feed, "/trending/movie/week")
    )
    if title:
        provider_params = {}

    return DiscoverPlan(
        query=normalized,
        strategy=strategy,
        endpoint=endpoint,
        provider_params=provider_params,
        title=title,
        people=tuple(people),
        provider_groups=provider_groups,
        summary_groups=summary_groups,
        local_groups=local_groups,
        total_scope="page" if page_scoped else "provider",
        total_label=total_label,
    )


def movie_matches_summary(movie, summary_groups, language_country_fallback=None):
    """Apply only facts present in TMDB movie summaries; missing facts fail."""
    language_country_fallback = language_country_fallback or {}
    genre_ids = {str(value) for value in (movie.get("genre_ids") or [])}
    language = str(movie.get("original_language", "") or "").lower()
    countries = {str(value or "").upper() for value in (movie.get("origin_country") or [])}
    fallback = str(language_country_fallback.get(language, "") or "").upper()
    if not countries and fallback:
        countries.add(fallback)
    release_year = str(movie.get("release_date", "") or "")[:4]
    year = int(release_year) if release_year.isdigit() else None
    rating = movie.get("vote_average")
    votes = movie.get("vote_count")

    for group in summary_groups:
        criterion = group["type"]
        value = group["values"][0]
        if criterion == "genre":
            wanted = {entry["id"] for entry in group["values"]}
            matched = wanted & genre_ids
            if group.get("join") == "and" and matched != wanted:
                return False
            if group.get("join") != "and" and not matched:
                return False
        elif criterion == "language" and language != value["id"].lower():
            return False
        elif criterion == "country" and value["id"].upper() not in countries:
            return False
        elif criterion == "minimum_votes" and (votes is None or int(votes or 0) < value["value"]):
            return False
        elif criterion in {"year", "rating"}:
            candidate = year if criterion == "year" else (float(rating) if rating is not None else None)
            if candidate is None:
                return False
            lower, upper = _numeric_bounds(value)
            if lower is not None and candidate < lower:
                return False
            if upper is not None and candidate > upper:
                return False
    return True
