"""Offline-change catch-up through the authoritative ingestion coordinator."""

import json
import os


class LibraryStartupCatchup:
    META_KEY = "library_directory_revisions_v1"

    def __init__(self, roots, coordinator, repository):
        self.roots = roots
        self.coordinator = coordinator
        self.repository = repository

    @staticmethod
    def _snapshot_root(root):
        absolute = os.path.abspath(str(root or ""))
        if not os.path.isdir(absolute):
            return None
        revisions = {}
        for current, directories, _files in os.walk(absolute):
            try:
                revisions[os.path.normcase(os.path.normpath(current))] = os.stat(current).st_mtime_ns
            except OSError:
                continue
            directories.sort(key=str.casefold)
        return revisions

    def run_once(self):
        raw_previous = self.repository.catalog_meta(self.META_KEY, "")
        try:
            previous = json.loads(raw_previous) if raw_previous else {}
        except ValueError:
            previous = {}
        current = {}
        offline = []
        for root in self.roots():
            snapshot = self._snapshot_root(root)
            normalized_root = os.path.normcase(os.path.normpath(os.path.abspath(str(root))))
            if snapshot is None:
                offline.append(normalized_root)
                for path, revision in previous.items():
                    try:
                        if os.path.commonpath((path, normalized_root)) == normalized_root:
                            current[path] = revision
                    except ValueError:
                        continue
                continue
            current.update(snapshot)

        changed = [path for path, revision in current.items() if previous.get(path) != revision]
        if not previous:
            result = self.coordinator.reconcile_all_now(enrich_accepted=False)
        elif changed:
            result = self.coordinator.reconcile_directories_now(
                changed,
                enrich_accepted=False,
            )
        else:
            result = {"checked": 0, "skipped": True}
        self.repository.set_operational_meta(
            self.META_KEY,
            json.dumps(current, sort_keys=True, separators=(",", ":")),
        )
        return {"changed_directories": len(changed), "offline_roots": len(offline), "result": result}
