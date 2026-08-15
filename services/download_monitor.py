import threading
import time


class DownloadImportMonitor:
    """Runs completed-download imports and retains operational failures."""

    def __init__(self, manager_factory, on_results, *, interval_seconds=5, clock=time.time, sleeper=time.sleep):
        self.manager_factory = manager_factory
        self.on_results = on_results
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.sleeper = sleeper
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._status = {
            'state': 'idle',
            'last_checked_at': 0,
            'last_success_at': 0,
            'last_error_at': 0,
            'last_error': '',
            'consecutive_errors': 0,
            'processed_results': 0,
        }

    def snapshot(self):
        with self._lock:
            return dict(self._status)

    def run_once(self, *, enabled=True):
        checked_at = self.clock()
        if not enabled:
            with self._lock:
                self._status.update({'state': 'disabled', 'last_checked_at': checked_at})
            return False
        try:
            manager = self.manager_factory()
            results = manager.process_completed()
            self.on_results(manager, results)
        except Exception as error:
            with self._lock:
                self._status.update({
                    'state': 'error',
                    'last_checked_at': checked_at,
                    'last_error_at': checked_at,
                    'last_error': str(error),
                    'consecutive_errors': int(self._status.get('consecutive_errors') or 0) + 1,
                })
            return False
        with self._lock:
            self._status.update({
                'state': 'healthy',
                'last_checked_at': checked_at,
                'last_success_at': checked_at,
                'last_error': '',
                'consecutive_errors': 0,
                'processed_results': len(results or []),
            })
        return True

    def run_forever(self, enabled):
        while not self._stop.is_set():
            self.run_once(enabled=bool(enabled()))
            if self.sleeper is time.sleep:
                self._stop.wait(self.interval_seconds)
            else:
                self.sleeper(self.interval_seconds)

    def shutdown(self):
        self._stop.set()
        return True
