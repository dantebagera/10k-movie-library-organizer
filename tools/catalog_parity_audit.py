import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import app
from tools.catalog_migration_backup import resolve_backup_sources


SHADOW_FIELDS = (
    "title", "year", "tmdb_id", "imdb_id", "plex_guid", "poster_url", "backdrop_url",
    "genres", "plot", "summary", "rating", "tmdb_rating", "tmdb_vote_count",
    "language", "country", "country_flag", "release_date", "runtime", "tagline",
    "trailer_url", "collection", "cast", "directors", "writers", "keywords",
)


def _normalized_shadow_value(field, value):
    if value in (None, "", [], {}):
        return None
    if field in {"cast", "directors", "writers"}:
        return [
            {
                "id": str(person.get("id", "") or "").strip(),
                "name": str(person.get("name", "") or "").strip(),
                "profile_url": str(
                    person.get("remote_profile_url")
                    if str(person.get("profile_url", "") or "").startswith("/api/assets/")
                    else person.get("profile_url", "")
                ).strip(),
                **({"character": str(person.get("character", "") or "").strip()} if field == "cast" else {}),
                **({"job": str(person.get("job", "") or "").strip()} if field == "writers" else {}),
            }
            for person in (value or [])
            if isinstance(person, dict)
        ]
    return value


def _violation(bucket, candidate, message, limit):
    if len(bucket) >= limit:
        return
    bucket.append({
        "path": str(candidate.get("path") or ""),
        "path_key": str(candidate.get("path_key") or ""),
        "message": message,
    })


def _legacy_canonical(candidate, store, snapshot):
    """Rebuild the pre-relational JSON contract for one shadow comparison."""
    record = app._catalog_file_record(candidate)
    plex = candidate.get("plex_json") or {}
    canonical = app._build_canonical_metadata(
        record,
        plex_data=plex,
        tmdb_data=candidate.get("tmdb_json") or {},
        manual_match=candidate.get("manual_json") or {},
        display_provider=record.get("display_provider", ""),
        file_record=record,
    )
    identity = app._poster_identity_for_movie(record, canonical, plex)
    canonical = app._apply_metadata_override(canonical, identity, store=store, snapshot=snapshot)
    return app._apply_poster_override(canonical, identity, store=store, snapshot=snapshot)


def audit_catalog(user_data_dir, max_errors=100):
    """Read the active SQL catalog through the same canonical projections as the app."""
    store = app.AppMetadataStore(Path(user_data_dir))
    snapshot = store.snapshot()
    candidates = store.catalog.store.audit_library_candidates()
    connection = store.catalog.store.connect()
    try:
        relational_by_path = store.catalog.store.canonical.project_paths(
            connection,
            [candidate["path_key"] for candidate in candidates],
            include_details=True,
        )
    finally:
        connection.close()
    for candidate in candidates:
        candidate["relational_canonical"] = relational_by_path.get(candidate["path_key"], {})
    violations = {
        "sql_rows": [],
        "canonical": [],
        "deferred_details": [],
        "projections": [],
        "relational_shadow": [],
    }
    accepted = 0
    active_detail_providers = {}

    with patch("app.urllib.request.urlopen", side_effect=AssertionError("Catalog parity audit must not call providers")):
        for candidate in candidates:
            record = app._catalog_file_record(candidate)
            if not candidate.get("path_key") or not candidate.get("path") or not record.get("filename"):
                _violation(violations["sql_rows"], candidate, "Missing required SQL path or filename fields", max_errors)
                continue
            if str(record.get("path") or "") != str(candidate.get("path") or ""):
                _violation(violations["sql_rows"], candidate, "Raw file record path disagrees with normalized SQL row", max_errors)

            item = app._catalog_library_item(candidate, store, snapshot)
            canonical = item.get("canonical_metadata") or {}
            legacy_canonical = _legacy_canonical(candidate, store, snapshot)
            relational_canonical = candidate.get("relational_canonical") or {}
            card = app._library_card_item(item)
            list_item = app._movie_list_library_item(item)
            people = app._library_people_item(item)

            if canonical.get("accepted"):
                accepted += 1
                if not canonical.get("title") or not canonical.get("year"):
                    _violation(violations["canonical"], candidate, "Accepted canonical identity is missing title or year", max_errors)
                if not any(canonical.get(field) for field in ("tmdb_id", "imdb_id", "plex_guid")):
                    _violation(violations["canonical"], candidate, "Accepted canonical identity has no stable provider ID", max_errors)

            tmdb = candidate.get("tmdb_json") or {}
            plex = candidate.get("plex_json") or {}
            detail_provider = canonical.get("detail_provider", "")
            if detail_provider:
                active_detail_providers[detail_provider] = active_detail_providers.get(detail_provider, 0) + 1
            if record.get("display_provider") == "tmdb" and record.get("tmdb_id") and not tmdb:
                _violation(
                    violations["deferred_details"],
                    candidate,
                    "TMDB-selected identity has no persisted SQL TMDB snapshot; fallback data is not completion",
                    max_errors,
                )
            if detail_provider == "tmdb_snapshot" and not tmdb:
                _violation(violations["deferred_details"], candidate, "Canonical TMDB detail provider has no SQL snapshot", max_errors)
            if detail_provider == "plex_snapshot" and not plex:
                _violation(violations["deferred_details"], candidate, "Canonical Plex detail provider has no SQL snapshot", max_errors)
            if tmdb.get("plot") and canonical.get("source", "").startswith("tmdb"):
                if canonical.get("plot") != tmdb.get("plot") or canonical.get("summary") != tmdb.get("plot"):
                    _violation(violations["deferred_details"], candidate, "TMDB plot is not preserved by the canonical detail read", max_errors)
            if plex.get("plex_summary") and item.get("plex_summary") != plex.get("plex_summary"):
                _violation(violations["deferred_details"], candidate, "Plex summary is not preserved by the canonical detail read", max_errors)

            for projection in (card, list_item):
                projected = projection.get("canonical_metadata") or {}
                for field in (
                    "tmdb_id", "imdb_id", "plex_guid", "title", "year",
                    "poster_url", "genres", "plot", "summary", "rating",
                    "language", "country", "country_flag", "release_date",
                    "runtime", "tagline", "trailer_url", "collection", "detail_provider",
                ):
                    if projected.get(field) and projected.get(field) != canonical.get(field):
                        _violation(violations["projections"], candidate, f"Projection disagrees on canonical {field}", max_errors)
                for field in ("plot", "summary", "detail_provider"):
                    if canonical.get(field) and projected.get(field) != canonical.get(field):
                        _violation(violations["projections"], candidate, f"Projection lost canonical {field}", max_errors)
            if any(canonical.get(field) for field in ("cast", "directors", "writers", "keywords")):
                if any((card.get("canonical_metadata") or {}).get(field) for field in ("cast", "directors", "writers", "keywords")):
                    _violation(violations["projections"], candidate, "Card projection includes deferred people fields", max_errors)
            if canonical.get("cast") and not (people.get("canonical_metadata") or {}).get("cast"):
                _violation(violations["projections"], candidate, "People projection lost canonical cast", max_errors)
            if relational_canonical:
                for field in SHADOW_FIELDS:
                    legacy_value = _normalized_shadow_value(field, legacy_canonical.get(field))
                    relational_source = relational_canonical.get(field)
                    if field == "poster_url" and str(relational_source or "").startswith("/api/assets/"):
                        relational_source = relational_canonical.get("remote_poster_url")
                    relational_value = _normalized_shadow_value(field, relational_source)
                    if legacy_value != relational_value:
                        _violation(
                            violations["relational_shadow"],
                            candidate,
                            f"Relational canonical projection disagrees on {field}",
                            max_errors,
                        )
                        break

    relational = store.catalog.store.canonical_report(max_errors=max_errors)
    error_count = sum(len(rows) for rows in violations.values())
    return {
        "source": "catalog",
        "database": str(store.catalog.database_path),
        "catalog_generation": store.catalog.generation("media"),
        "checked_records": len(candidates),
        "accepted_records": accepted,
        "provider_calls": 0,
        "active_detail_providers": dict(sorted(active_detail_providers.items())),
        "relational": relational,
        "passed": error_count == 0 and relational["passed"],
        "violations": violations,
    }


def main():
    parser = argparse.ArgumentParser(description="Audit active SQL catalog rows and app projections without provider calls.")
    parser.add_argument("--project-root", default=PROJECT_ROOT)
    parser.add_argument("--max-errors", type=int, default=100)
    args = parser.parse_args()
    sources = resolve_backup_sources(args.project_root)
    report = audit_catalog(sources["user_data_dir"], max_errors=max(1, args.max_errors))
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
