import argparse
import json
import sys
import time
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.player_config import PlayerConfig
from services.player_manager import PlayerManager


class ResolvedRuntime:
    def __init__(self, bundle_root):
        self.bundle_root = bundle_root

    def resolve_bundle(self, verify_hashes=True):
        if verify_hashes:
            raise AssertionError("PlayerManager launch must use quick runtime validation.")
        return {
            "bundle_root": self.bundle_root,
            "manifest": {"player_version": "smoke"},
        }


def main():
    parser = argparse.ArgumentParser(
        description="Exercise PlayerManager with the production cp-player runtime."
    )
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--simulate-crash", action="store_true")
    args = parser.parse_args()

    runtime = args.runtime.resolve()
    media = args.media.resolve()
    os_fallback_calls = []
    config = PlayerConfig({"mode": "built_in"})
    manager = PlayerManager(
        config,
        ResolvedRuntime(runtime),
        lambda path_key: {
            "path_key": path_key,
            "path": str(media),
            "title": "PlayerManager Real Runtime Fixture",
            "year": "2026",
            "movie_key": "fixture:manager",
            "poster_reference": "",
        },
        os_opener=os_fallback_calls.append,
    )
    result = manager.play(str(media).casefold())
    if result.get("mode") != "built_in" or result.get("fallback"):
        raise RuntimeError(f"PlayerManager unexpectedly fell back: {result}")

    deadline = time.monotonic() + 6
    status = manager.active_status()
    while time.monotonic() < deadline:
        status = manager.active_status()
        if (
            status.get("last_event", {}).get("type") == "progress"
            and status["last_event"].get("duration_ms", 0) > 0
        ):
            break
        time.sleep(0.1)
    if (
        status.get("last_event", {}).get("type") != "progress"
        or status["last_event"].get("duration_ms", 0) <= 0
    ):
        raise RuntimeError(f"PlayerManager did not receive progress: {status}")
    crash_event = {}
    if args.simulate_crash:
        with manager._lock:
            session = manager._active
        if not session or session.process.poll() is not None:
            raise RuntimeError("The native helper was not active before crash simulation.")
        session.process.terminate()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            crash_status = manager.active_status()
            if (
                not crash_status.get("active")
                and crash_status.get("last_event", {}).get("type") == "closed"
            ):
                crash_event = crash_status["last_event"]
                break
            time.sleep(0.1)
        if not crash_event:
            raise RuntimeError(
                f"PlayerManager did not close the crashed session: {manager.active_status()}"
            )
    else:
        manager.close_active()
    if os_fallback_calls:
        raise RuntimeError("PlayerManager invoked the OS fallback during a healthy native session.")

    print(
        json.dumps(
            {
                "schema": "cp-player-manager-smoke-v1",
                "ok": True,
                "launch": result,
                "last_event": status["last_event"],
                "simulated_crash": bool(args.simulate_crash),
                "crash_event": crash_event,
                "os_fallback_calls": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
