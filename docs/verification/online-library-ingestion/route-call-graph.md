# Gate 0 route, trigger, and ownership graph

## Reconciliation triggers

| Trigger | Entry point | Current path | Scope |
| --- | --- | --- | --- |
| CP startup | `app.py:11634-11646` | `_start_library_reconcile()` -> `_startup_reconcile_decision()` -> optional `_run_library_reconcile_loop()` | Skip or global inventory/backfill |
| Manual background reconcile | `POST /api/library/reconcile`, `app.py:4682-4686` | `_start_library_reconcile(force=True)` | Global inventory plus all backfills |
| Manual Library rescan | `GET /api/library?force_scan=1`, `app.py:5050-5086` | synchronous `_reconcile_library_files(force_unresolved=True)` | Global recursive inventory |
| External file while CP is online | none | none | Missing |
| qBittorrent completion | monitor -> manager -> callback | exact imported paths are identity-handoff inputs, then `_start_library_reconcile(force=True)` | Exact pre-handoff plus global inventory |

## Current filesystem and publication graph

```text
startup/manual/qBittorrent force
              |
              v
_start_library_reconcile
              |
              v
_run_library_reconcile_loop
              |
              v
_reconcile_library_files
              |
              +--> _iter_video_files --> os.walk(all configured roots)
              |
              +--> stat inventory / prune missing paths / save inventory
              |
              +--> _reconcile_library_path(each candidate)
                        |
                        +--> stat-only observation
                        +--> 15-second stability predicate
                        +--> probe_media_file
                        +--> provider identity/metadata migration
                        +--> separate CatalogRepository writes
                                   |
                                   v
                         canonical sync + generation bump
```

Pending files cause the loop to sleep 15 seconds and run the global reconciliation owner again.

## qBittorrent ownership and restart recovery

```text
DownloadImportMonitor.run_forever (5-second interval)
    |
    v
QBittorrentManager.process_completed
    |
    +--> recover payload_imported / cleanup_failed / moving / conflict states
    +--> QBittorrentJobStore.move_completed_payload
    |       |
    |       +--> validate staging containment
    |       +--> fingerprint destination collisions
    |       +--> journal state=moving before each move
    |       +--> shutil.move / duplicate cleanup
    |       +--> journal state=payload_imported
    |       +--> imported_paths + library_scan_pending=true
    |
    +--> cleanup torrent, finish imported or cleanup_failed
    |
    v
app._handle_completed_qbittorrent_imports
    |
    +--> accept_tmdb_identity(imported path, probe=False)
    +--> _start_library_reconcile(force=True)
    +--> update identity_handoff/library_scan_pending in job journal
```

Evidence:

- atomic job JSON write and in-process lock: `services/qbittorrent.py:289-317`;
- collision, transfer journal, move, and `payload_imported`: `services/qbittorrent.py:319-417`;
- cleanup completion/failure: `services/qbittorrent.py:919-928`;
- missing-job grace and recovery paths: `services/qbittorrent.py:931-1060`;
- polling/callback owner: `services/download_monitor.py:5-63`;
- application callback and forced reconciliation: `app.py:2401-2459`.

The existing qBittorrent manager remains the authoritative owner of runtime, job journal, move/import, cleanup, and restart recovery. It must not be replaced by an ingestion coordinator.

## SQL Movie View graph

```text
GET /api/library?view=cards
    |
    v
app._paged_library_cards                    app.py:5018-5047
    |
    v
CatalogRepository.library_page              catalog_repository.py:232-237
    |
    v
CatalogStore.library_page                   catalog_store.py:1626-1702
    |
    +--> _library_effective_cte
    |       publication predicate:
    |       identity_status=accepted OR metadata_accepted=1
    |
    +--> count/page/facets/stats/generation
    |
    v
CanonicalCatalog.project_paths              canonical_catalog.py:1079-1313
    |
    v
canonical_card_projection                   canonical_catalog.py:84
    |
    v
JSON cards -> LibraryWorkspace
```

SQL is authoritative, but the current predicate is not a final-form readiness predicate.

## File View graph

`GET /api/library?view=files` takes the full SQL-backed `library_projection`, filters paths with `os.path.isfile`, and maps physical facts into File View response rows (`app.py:5087-5112`). `LibraryFileRow` renders those file/probe/identity facts in `LibraryWorkspace`.

This is the correct owner boundary to preserve: File View exposes physical and incomplete facts; Movie View exposes accepted cards.

## Browser update graph

```text
App mounts
   |
   +--> GET /api/library/reconcile once
           |
           +--> if already running: poll every 2 seconds
           +--> if idle/completed: stop polling
           +--> if a new completion is observed:
                   announceLibraryReconciled()
                       |
                       +--> cp-library-reconciled CustomEvent
                       +--> cp-library-changed CustomEvent
                                   |
                                   v
                         LibraryWorkspace.loadLibrary(quiet=true)
                                   |
                                   +--> setLoading(true)
                                   +--> grid unmounts until response
```

There is no server event stream. Catalog-generation notifications in `src/api/library.js` are also browser-local events created when some request happens to observe a changed generation.

## Single-writer proof

Observed:

- one CP listener at capture time;
- one qBittorrent process parented by that CP process;
- `CatalogRepository._lock`, `_library_reconcile_run_lock`, `QBittorrentJobStore._lock`, and qBittorrent completion/update locks serialize threads within one Python process.

Not enforced:

- no system mutex;
- no catalog-writer lock file;
- no process lease;
- no rejection path for a second CP writer.

Gate 1 must freeze this process boundary before adding observer or queue workers.
