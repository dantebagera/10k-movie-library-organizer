"""Filesystem hint adapter for the authoritative library ingestion coordinator."""

import ctypes
import hashlib
import os
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
SIDECAR_EXTENSIONS = frozenset({".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".nfo"})


def _path_id(path):
    normalized = os.path.normcase(os.path.normpath(os.path.abspath(str(path or ""))))
    return hashlib.blake2b(normalized.encode("utf-8", errors="surrogatepass"), digest_size=8).hexdigest()


def classify_library_root(path, *, is_directory=os.path.isdir, drive_type=None):
    absolute = os.path.abspath(str(path or ""))
    online = bool(is_directory(absolute))
    if absolute.startswith("\\\\"):
        kind = "network"
    else:
        if drive_type is None and os.name == "nt":
            drive = os.path.splitdrive(absolute)[0] + "\\"
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
        kind = {
            DRIVE_FIXED: "local",
            DRIVE_REMOVABLE: "removable",
            DRIVE_REMOTE: "network",
        }.get(drive_type, "unsupported")
    supported = online and kind in {"local", "removable"}
    return {
        "path": absolute,
        "root_id": _path_id(absolute),
        "kind": kind,
        "online": online,
        "supported": supported,
        "degraded": not supported,
        "reason": "" if supported else ("offline" if not online else "network_or_unsupported"),
    }


class _RootEventHandler(FileSystemEventHandler):
    def __init__(self, adapter, root):
        super().__init__()
        self.adapter = adapter
        self.root = root

    def on_any_event(self, event):
        if getattr(event, "event_type", "") in {"opened", "closed", "closed_no_write"}:
            return
        self.adapter.handle_event(
            self.root,
            getattr(event, "src_path", ""),
            destination=getattr(event, "dest_path", ""),
            is_directory=bool(getattr(event, "is_directory", False)),
            event_type=getattr(event, "event_type", "modified"),
        )


class LibraryObserverAdapter:
    """Own native observers; emit only bounded path hints to the coordinator."""

    def __init__(self, roots, coordinator, *, observer_factory=Observer, clock=time.time):
        self._configured_roots = tuple(os.path.abspath(str(root)) for root in roots if root)
        self._coordinator = coordinator
        self._observer_factory = observer_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._observer = None
        self._roots = {}
        self._started = False

    def start(self):
        with self._lock:
            if self._started:
                return self.status()
            observer = self._observer_factory()
            scheduled = 0
            for root in self._configured_roots:
                state = classify_library_root(root)
                self._roots[root] = state
                if not state["supported"]:
                    continue
                try:
                    observer.schedule(_RootEventHandler(self, root), root, recursive=True)
                    scheduled += 1
                except OSError as error:
                    state.update(degraded=True, supported=False, reason=type(error).__name__)
            if scheduled:
                observer.start()
                self._observer = observer
            self._started = True
            return self.status()

    def _root_online(self, root):
        online = os.path.isdir(root)
        with self._lock:
            state = self._roots.get(root)
            if state is not None:
                state["online"] = online
                if not online:
                    state.update(degraded=True, reason="offline")
        return online

    def _emit(self, root, path, *, is_directory, event_type):
        if not path or not self._root_online(root):
            return
        absolute = os.path.abspath(path)
        try:
            if os.path.commonpath((absolute, root)) != root:
                return
        except ValueError:
            return
        extension = os.path.splitext(absolute)[1].lower()
        reason = f"observer:{event_type}"
        if is_directory:
            # Directory metadata changes are noisy on Windows and do not identify
            # a media candidate. File and sidecar events below carry the bounded
            # path information; only a newly created/moved directory needs a
            # one-time bounded traversal.
            if event_type in {"created", "moved"} and os.path.isdir(absolute):
                self._coordinator.reconcile_directories((absolute,), reason=reason)
        elif extension in self._coordinator.dependencies.video_extensions:
            self._coordinator.reconcile_paths((absolute,), reason=reason)
        elif extension in SIDECAR_EXTENSIONS:
            parent = os.path.dirname(absolute)
            if os.path.isdir(parent):
                self._coordinator.reconcile_directories((parent,), reason=reason)
        with self._lock:
            state = self._roots.get(root)
            if state is not None:
                state["last_observed_at"] = self._clock()

    def handle_event(self, root, source, *, destination="", is_directory=False, event_type="modified"):
        self._emit(root, source, is_directory=is_directory, event_type=event_type)
        if destination and destination != source:
            self._emit(root, destination, is_directory=is_directory, event_type="moved")

    def mark_overflow(self, root):
        absolute = os.path.abspath(str(root or ""))
        if absolute not in self._roots or not self._root_online(absolute):
            return {"accepted": 0, "rejected": 1, "reason": "root_unavailable"}
        with self._lock:
            self._roots[absolute].update(degraded=True, reason="overflow")
        return self._coordinator.reconcile_directories((absolute,), reason="observer:overflow")

    def status(self):
        with self._lock:
            observer = self._observer
            return {
                "implementation": "watchdog-native",
                "version": "6.0.0",
                "started": self._started,
                "alive": bool(observer and observer.is_alive()),
                "roots": [
                    {key: value for key, value in state.items() if key != "path"}
                    for state in self._roots.values()
                ],
            }

    def shutdown(self, timeout_seconds=10):
        with self._lock:
            observer = self._observer
            self._observer = None
            self._started = False
        if observer:
            observer.stop()
            observer.join(timeout=max(0, float(timeout_seconds)))
        return not (observer and observer.is_alive())
