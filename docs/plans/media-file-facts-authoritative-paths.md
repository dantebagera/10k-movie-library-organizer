# Media File Facts: Authoritative Paths

This note freezes ownership for the version 9 media-file-facts implementation.
It does not authorize or record a live catalogue rollout.

## Authority

| Responsibility | Authoritative owner |
| --- | --- |
| SQLite schema, migration, stale-row selection, atomic fact writes, Library/file projections | `services/catalog_store.py` |
| Generation changes and deferred rollback export | `services/catalog_repository.py` |
| MediaInfo invocation, stream selection, normalization, filename claim, dimension classification, display wording | `services/media_file_facts.py` |
| Bounded concurrency, root validation, retry, cancellation, resume, and progress | `services/media_file_backfill.py` |
| New-file, changed-file, and rename initiation | Existing reconciliation and mutation paths in `app.py` |
| Duplicate and upgrade decisions | `services/maintenance_audit.py` |
| Canonical movie identity and relationships | `services/canonical_catalog.py` |
| Shared quality presentation | `src/utils/libraryUtils.js` and the existing shared cards |

## Write path

1. New and changed files are detected by existing reconciliation.
2. A stable file is passed once to `probe_media_file`.
3. The probe returns one complete immutable facts record. It never writes SQL
   and never calls a metadata provider.
4. Reconciliation or the backfill coordinator passes that complete record to
   the repository.
5. The store verifies the persisted size and modified-time fingerprint and
   updates all fact columns atomically.
6. The repository advances the existing media generation once for a changed
   batch and does not advance it for an unchanged pass.

Legacy rows are marked `unprobed` by the filesystem-free version 8 to version 9
migration. The background backfill later processes them in bounded batches.

## Read path

Library, Home, Lists, Discover-owned cards, AI Control, File View, filters,
statistics, Maintenance, upgrades, and duplicate policy receive the same
normalized SQL columns. `resolution` remains a compatibility projection of
`quality_class`; it is not independently classified.

Measured dimensions, filename claims, and the derived quality class remain
separate:

- `video_width` and `video_height` are measured coded dimensions;
- `filename_quality_claim` is release-name evidence only;
- `quality_class` is the classifier result;
- `quality_source`, `quality_conflict`, and `probe_status` explain confidence
  and fallback;
- `quality_display` is derived at the projection boundary.

Maintenance reads normalized columns. Raw provider documents remain available
only to explicit identity/parity audit paths.

## Duplicate comparison

`services/maintenance_audit.py` owns three independent duplicate verdicts:

1. content equivalence from accepted public identity, edition tokens, measured
   runtime, optional 23.976/24-to-25 frame-count equivalence, and relative
   framing difference;
2. technical quality from pairwise measured resolution/pixel dominance, with
   source, bit-depth, and primary-audio regressions preserved as tradeoffs;
3. storage efficiency from file-size difference, which is displayed but never
   treated as proof of visual quality across codecs.

Automatic removal requires safe identity, equivalent content, at least a
1.5-times pixel advantage in a higher measured resolution class, no meaningful
source/bit-depth/primary-audio regression, and no quality conflict. Frame rate
can explain a speed conversion but never contributes to the quality rank.
Framing differences of at most two percent are treated as minor encoding crops
and remain visible in the explanation.

Groups are compared pairwise. There is no filename-selected reference copy and
no weighted score that can cancel a protected tradeoff. `reclaimable_bytes`
contains recommended removals only; possible manual savings are reported
separately.

The current schema stores measured video and the selected primary audio track.
Full audio-language, subtitle, commentary, HDR, and Dolby Vision inventories
are not yet normalized catalogue facts. Maintenance states that evidence scope
in the UI; adding those facts requires a separately reviewed schema/probe
extension rather than an on-demand disk scan.

## Retired path

`res_cache.json` is not read, written, migrated, or deleted. Existing physical
files are retained for rollback history only and never seed measured facts.

## Safety boundary

Schema migration performs no file access or provider call. Backfill opens only
explicit files inside configured library roots, checks their fingerprint before
and after probing, records bounded error codes, and never modifies media files.
Uncertain duplicate comparisons remain review-only.
