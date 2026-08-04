# Gate 10 final live acceptance - passed and rolled back exactly

## Outcome

Gate 10 passes. While CP remained online, the approved external Rao Bahadur
fixture entered the existing Watchdog adapter and authoritative ingestion
coordinator, completed stability and probe work, received accepted TMDB
identity and metadata, obtained a checksum-ready local poster, became visible
through the canonical SQL projection, committed its ready publication, emitted
one post-commit event, and appeared as one final Movie View card.

The desktop grid stayed visible with no loading spinner or placeholder. The
1080p filter, newly-added sort, page 1, selected movie, expanded movie, search
focus, and visually anchored scroll position survived the background update.
No duplicate, partial card, root walk signal, queue pressure, process ownership
ambiguity, or browser console error occurred.

The accepted catalog is preserved in the fresh rollback backup. The copied
fixture and its one generated poster were then removed, and production SQL was
restored byte-for-byte. CP is stopped; qBittorrent and the original G: source
were not changed.

## Required deployment preflight correction

The first preflight start was stopped before media copy because CP served the
July 30 `dist` entry `/assets/index-CKG_Outm.js`. That bundle contained no
`/api/catalog/events` subscriber, so the backend correctly reported zero
browser subscribers. Continuing would have invalidated the notification and
no-flicker proof.

CP was stopped and SQL restored exactly. The stale 35-file bundle was preserved
under the Gate 10 backup. The already-qualified source was then built without
source, configuration, or dependency changes:

- 1,652 modules transformed;
- new entry `/assets/index-tzQbeasi.js`;
- index SHA-256
  `980CE500BDA6B8A12C77CE67B34C03BD7194EFD2C2ED1242E013C9BB8E99A37C`;
- entry SHA-256
  `D8DB8CA25CC7E5942309F70BD71ED8026334D99731178E73446A2527788574D8`;
- the served entry contains the single catalog-event subscriber.

On the corrected start, the backend reported exactly one event client. This
was a deployment correction, not a second frontend implementation.

## Backup and startup proof

Fresh backup:

`C:\Users\dante\AppData\Local\Temp\cp-gate10-retry2-backup-ad893b6a4320401c80bf9066219b62b8`

Before runtime logs and the preserved bundles/catalogs were added, it contained
60 files and 249,992,608 bytes, including 55 app-metadata files. The catalog
copy matched production at SHA-256
`C8E0F52C65C9A61D8CEF45A522EA897876C73B889783999E3A17EBB90FA47961`.

Corrected CP PID 52532 acquired the writer lease. The native Watchdog observer
was alive on the online, non-degraded local `E:\Movies` root. The coordinator
was idle at 0/4,096 with no dirty root or error. First-upgrade recovery created
`library_directory_revisions_v1` while global, media, canonical-media, and
asset generations remained exactly unchanged. This is the live proof for the
Gate 10B transition correction.

## Approved fixture and targeted ingestion

The exact approved source contained four files totaling 2,989,992,644 bytes.
The 2,989,813,923-byte video SHA-256 was
`3DFCF693F87A50822BCFF340D4308BB0039749C7EF6EF5A21176DC623BF90587`.
All four destination hashes matched their source hashes.

An initial PowerShell command created only the approved empty destination
because square brackets in the source were interpreted as wildcard syntax.
The observer processed that directory hint with zero checked files and zero
generation change. The command was diagnosed and corrected to enumerate the
literal source directory; this was not a product retry.

Authoritative timestamps from the accepted catalog and server log:

| Stage | UTC |
| --- | --- |
| SQL file observation | 2026-08-01 22:24:58.642 |
| Probe completed | 2026-08-01 22:25:07.093 |
| Accepted file facts updated | 2026-08-01 22:25:15.203 |
| Poster record created | 2026-08-01 22:25:15.461 |
| Poster checksum ready | 2026-08-01 22:25:18.276 |
| One authoritative Library refetch | 2026-08-01 22:25:21 server-log second |

The known external addition produced no dirty-root marker and no queue
pressure. The final status was queue 0/4,096, no active work, no error, one
browser subscriber, and one retained post-commit event.

## Final-card and SQL proof

The accepted catalog has `PRAGMA quick_check=ok` and zero foreign-key errors.
Relative to the pre-state it contains exactly:

- one new `media_files` row;
- one new `canonical_movies` row;
- one new `canonical_movie_files` mapping;
- one new provider snapshot;
- one new ready poster asset;
- zero duplicate Rao Bahadur rows.

The file record has `movie_view_publication=ready`, `probe_status=ok`, accepted
identity `Rao Bahadur`/2026, TMDB ID 1443961, accepted metadata, measured
1920x806 HEVC Main 10 facts, and stable ingest status. The canonical projection
is `canonical_movie_card`, selected provider TMDB. The ready local poster is
67,082 bytes with checksum
`E4B95FDAC031F11A0ABF9727D6E041CBF17EB2ECE96251CA98805E44C4069C17`.

The bounded `/api/library` search returned one card from source `catalog` at
generation 7,634. The browser showed exactly one Rao Bahadur card with title,
year, Fantasy/Drama metadata, Telugu/India facts, 1080p WEBRip quality, rating,
and the checksum-owned poster.

Staged pending facts caused no browser event. The ready transition resulted in
one retained event and one bounded Library page refetch after the catalog and
poster were ready.

## Desktop no-regression proof

The live viewport was 1600x1000. Before publication:

- resolution filter `1080p`;
- sort `added`;
- page 1 of 77, 2,986 filtered movies;
- one selected card;
- `Nirvanna the Band the Show the Movie` expanded;
- search input focused;
- main scroll position 600;
- 39 connected cards, no spinner, no skeleton or placeholder.

After publication, the filtered total was 2,987 and Rao Bahadur was the first
card. Selection, expansion, focus, filter, sort, page, and visible content were
preserved. Browser scroll anchoring adjusted the numeric scroll offset to
892.8 because a new card was inserted above the viewport; the same expanded
content remained visually fixed instead of jumping. The grid remained
connected in every captured state, with no spinner, placeholder, blank frame,
reload, or browser console warning/error.

Evidence:

- [corrected live pre-state](after/gate-10-retry2-live-before.png)
- [copy pre-publication state](after/gate-10-retry2-during-copy.png)
- [background-ingestion state](after/gate-10-retry2-during-ingestion.png)
- [published final card](after/gate-10-retry2-final-card.png)

The pre-state and copy-state screenshots are byte-identical, directly proving
that creating the watched destination did not unmount or repaint the grid.

## Cleanup and final parity

After visual and SQL acceptance, CP PID 52532 was stopped. The accepted catalog
was preserved as `accepted-final-catalog.sqlite` with SHA-256
`017A4411D2C24EA20C97C3244EC0FEEBE35AFD14EAB4B4FFB6C430D0320CE8A4`.
It remains healthy and contains exactly one Rao Bahadur media row, canonical
movie, and mapping.

The four destination files were re-hashed against the unchanged G: source,
then the exact approved destination was removed. The single new poster was
checksum-verified and removed. Production SQL was restored from the fresh
backup and again has:

- catalog SHA-256
  `C8E0F52C65C9A61D8CEF45A522EA897876C73B889783999E3A17EBB90FA47961`;
- `quick_check=ok` and zero foreign-key errors;
- generations 30,626 global, 7,629 media/canonical-media, and 23,658 asset;
- zero Rao Bahadur rows;
- no WAL or SHM;
- zero active asset changes since the backup;
- zero configuration, app-metadata, or curation mismatches.

CP and port 5000 are stopped. qBittorrent remains the original PID 42792 on
port 8686 and was not restarted. Nothing was staged, committed, pushed, tagged,
released, or submitted as a pull request.

## Completion

All required gates now pass. Gate 9 remained intentionally unused because no
schema migration or durable Windows file identifier was needed. The plan's
definition of complete is satisfied without a second importer, scanner,
reconciliation pipeline, publication rule, catalog source, metadata pipeline,
frontend card source, or writer.
