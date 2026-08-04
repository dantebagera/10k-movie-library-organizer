# Gate 6 verification — passed

## Outcome

qBittorrent completion keeps `QBittorrentManager`, the existing jobs journal, importer, recovery, cleanup, and seeding ownership. After the existing import/move step, the exact accepted destination path is passed to the shared coordinator with the existing identity hint.

The synchronous handoff performs stability and a current probe before identity can be applied. If it is not final, only that path is queued. The normal known-path case never calls `_start_library_reconcile` and never walks a root. `library_scan_pending` remains true until final-card publication commits; failed handoff state remains recoverable instead of being marked applied.

## Proof

- qBittorrent API/service/monitor coverage is included in the 1,053-test backend pass.
- `test_completed_video_uses_exact_path_coordinator_and_keeps_journal_pending_until_commit` proves exact-path use and no full scan.
- ownership/source tests prohibit the old forced full-reconcile call.
- exact-path reconciliation has an `os.walk` trap and produces zero walks.

No category, seeding, hardlink, download directory, collision, cleanup, or source-search policy changed.
