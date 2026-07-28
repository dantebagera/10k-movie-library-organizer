import argparse
from collections import Counter
import ctypes
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from ctypes import wintypes


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.player_protocol import PLAYER_PROTOCOL_VERSION, validate_message
from services.player_config import default_player_config
from services.player_manager import safe_player_preferences
from services.player_windows_pipe import WindowsNamedPipeServer


def message(session_id, sequence, message_type, **payload):
    return {
        "type": message_type,
        "protocol": PLAYER_PROTOCOL_VERSION,
        "session_id": session_id,
        "sequence": sequence,
        **payload,
    }


def find_visible_window(process_id):
    matches = []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(handle, _parameter):
        window_process = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(window_process))
        if window_process.value == process_id and user32.IsWindowVisible(handle):
            matches.append(handle)
            return False
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if matches else None


def send_window_key(window, virtual_key):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow(window, 5)
    user32.SetForegroundWindow(window)
    time.sleep(0.1)
    user32.keybd_event(virtual_key, 0, 0, 0)
    user32.keybd_event(virtual_key, 0, 0x0002, 0)


def click_window_fraction(window, x_fraction, y_fraction):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    rectangle = wintypes.RECT()
    user32.GetWindowRect(window, ctypes.byref(rectangle))
    x = round(rectangle.left + (rectangle.right - rectangle.left) * x_fraction)
    y = round(rectangle.top + (rectangle.bottom - rectangle.top) * y_fraction)
    user32.SetForegroundWindow(window)
    time.sleep(0.15)
    user32.SetCursorPos(x, y)
    point = wintypes.POINT(x, y)
    user32.ScreenToClient(window, ctypes.byref(point))
    packed = (point.x & 0xFFFF) | ((point.y & 0xFFFF) << 16)
    user32.PostMessageW(window, 0x0200, 0, packed)
    user32.PostMessageW(window, 0x0201, 1, packed)
    user32.PostMessageW(window, 0x0202, 0, packed)


def receive_until(transport, process, events, predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            event = transport.receive(0.5)
        except TimeoutError:
            if process.poll() is not None:
                break
            continue
        events.append(event)
        if event["type"] == "error":
            raise RuntimeError(
                f"Native helper error {event.get('code')}: {event.get('message')}"
            )
        if predicate(event):
            return event
    raise RuntimeError(
        "The native player did not report the expected control state. Recent events: "
        + json.dumps(events[-10:], ensure_ascii=False)
    )


def main():
    try:
        ctypes.WinDLL("user32").SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)
        )
    except (AttributeError, OSError):
        ctypes.WinDLL("user32").SetProcessDPIAware()

    parser = argparse.ArgumentParser(
        description="Exercise the production cp-player executable over its real named-pipe protocol."
    )
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--media", required=True, type=Path)
    parser.add_argument("--observe-seconds", type=float, default=4.0)
    parser.add_argument("--require-min-position-ms", type=int, default=0)
    parser.add_argument("--allow-no-audio", action="store_true")
    parser.add_argument("--require-subtitle", action="store_true")
    parser.add_argument("--exercise-controls", action="store_true")
    parser.add_argument("--exercise-subtitle-provider-flow", action="store_true")
    parser.add_argument("--external-subtitle", type=Path)
    parser.add_argument("--exercise-resume", action="store_true")
    parser.add_argument("--resume-position-ms", type=int, default=4000)
    parser.add_argument("--restore-audio-fingerprint", default="")
    parser.add_argument("--restore-subtitle-fingerprint", default="")
    parser.add_argument("--restore-subtitle-delay-ms", type=int, default=0)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()

    executable = (args.runtime / "cp-player.exe").resolve()
    media = args.media.resolve()
    if not executable.is_file() or not media.is_file():
        raise SystemExit("The runtime executable and media fixture must exist.")

    session_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    pipe_name = f"cp-player-smoke-{session_id}"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "LOCALAPPDATA",
            "APPDATA",
        }
    }
    isolated_user_data = (
        Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
        / "cp-player-smoke-userdata"
        / session_id
    ).resolve()
    isolated_local = isolated_user_data / "Local"
    isolated_roaming = isolated_user_data / "Roaming"
    isolated_local.mkdir(parents=True, exist_ok=True)
    isolated_roaming.mkdir(parents=True, exist_ok=True)
    environment.update(
        {
            "LOCALAPPDATA": str(isolated_local),
            "APPDATA": str(isolated_roaming),
            "CP_PLAYER_PIPE": pipe_name,
            "CP_PLAYER_SESSION_ID": session_id,
            "CP_PLAYER_SESSION_TOKEN": token,
            "CP_PLAYER_PROTOCOL": str(PLAYER_PROTOCOL_VERSION),
        }
    )

    process = None
    events = []
    backend_sequence = 1
    started = time.monotonic()
    with WindowsNamedPipeServer(pipe_name) as transport:
        try:
            command = [str(executable)]
            process = subprocess.Popen(
                command,
                cwd=str(args.runtime.resolve()),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                shell=False,
            )
            transport.accept(10)
            hello = transport.receive(10)
            validate_message(
                hello,
                expected_type="hello",
                session_id=session_id,
                token=token,
            )
            events.append(hello)
            transport.send(
                message(
                    session_id,
                    1,
                    "load",
                    media={
                        "path_key": str(media).casefold(),
                        "path": str(media),
                        "title": "Cinema Paradiso Player Smoke Fixture",
                        "year": "2026",
                        "movie_key": "fixture:phase2",
                        "poster_reference": "",
                    },
                    start_position_ms=(
                        max(0, args.resume_position_ms)
                        if args.exercise_resume else 0
                    ),
                    playback_state={
                        "audio_track_fingerprint": args.restore_audio_fingerprint,
                        "subtitle_track_fingerprint": args.restore_subtitle_fingerprint,
                        "subtitle_delay_ms": args.restore_subtitle_delay_ms,
                    },
                    preferences={
                        **safe_player_preferences(default_player_config()),
                        "preferred_audio_languages": ["eng", "fra"],
                        "preferred_subtitle_languages": ["eng", "spa"],
                    },
                )
            )
            ready = transport.receive(10)
            if ready.get("type") == "error":
                raise RuntimeError(
                    f"Native helper rejected load {ready.get('code')}: "
                    f"{ready.get('message')}"
                )
            validate_message(ready, expected_type="ready", session_id=session_id)
            if not ready.get("accepted"):
                raise RuntimeError("The production player rejected the fixture.")
            events.append(ready)

            if args.exercise_resume:
                window = None
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not window:
                    window = find_visible_window(process.pid)
                    if not window:
                        time.sleep(0.1)
                if not window:
                    raise RuntimeError("The resume prompt window was not visible.")
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "playback.state"
                    and event.get("state") == "paused",
                    5,
                )
                if args.screenshot:
                    from PIL import ImageGrab

                    time.sleep(0.3)
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    resume_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-resume-prompt{args.screenshot.suffix}"
                    )
                    rectangle = wintypes.RECT()
                    ctypes.WinDLL("user32").GetWindowRect(window, ctypes.byref(rectangle))
                    ImageGrab.grab(
                        bbox=(
                            rectangle.left,
                            rectangle.top,
                            rectangle.right,
                            rectangle.bottom,
                        ),
                        all_screens=True,
                    ).save(resume_path)
                send_window_key(window, 0x0D)
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "resume.choice"
                    and event.get("choice") == "resume",
                    3,
                )
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "progress"
                    and event.get("position_ms", 0)
                        >= max(0, args.resume_position_ms - 500),
                    3,
                )

            deadline = time.monotonic() + max(1.0, args.observe_seconds)
            while time.monotonic() < deadline:
                try:
                    event = transport.receive(0.5)
                except TimeoutError:
                    if process.poll() is not None:
                        break
                    continue
                validate_message(event, session_id=session_id)
                events.append(event)
                if event["type"] == "error":
                    raise RuntimeError(
                        f"Native helper error {event.get('code')}: {event.get('message')}"
                    )

            if args.exercise_controls:
                window = find_visible_window(process.pid)
                if not window:
                    raise RuntimeError("The production player window was not visible.")
                if args.screenshot:
                    from PIL import ImageGrab

                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    pre_controls_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-pre-controls{args.screenshot.suffix}"
                    )
                    rectangle = wintypes.RECT()
                    ctypes.WinDLL("user32").GetWindowRect(window, ctypes.byref(rectangle))
                    ImageGrab.grab(
                        bbox=(
                            rectangle.left,
                            rectangle.top,
                            rectangle.right,
                            rectangle.bottom,
                        ),
                        all_screens=True,
                    ).save(pre_controls_path)
                send_window_key(window, 0x20)
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "playback.state"
                    and event.get("state") == "paused",
                    3,
                )
                if args.screenshot:
                    from PIL import ImageGrab

                    time.sleep(0.3)
                    args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                    rectangle = wintypes.RECT()
                    ctypes.WinDLL("user32").GetWindowRect(window, ctypes.byref(rectangle))
                    ImageGrab.grab(
                        bbox=(
                            rectangle.left,
                            rectangle.top,
                            rectangle.right,
                            rectangle.bottom,
                        ),
                        all_screens=True,
                    ).save(args.screenshot)
                    send_window_key(window, 0x41)
                    time.sleep(0.3)
                    audio_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-audio-tracks{args.screenshot.suffix}"
                    )
                    rectangle = wintypes.RECT()
                    ctypes.WinDLL("user32").GetWindowRect(window, ctypes.byref(rectangle))
                    ImageGrab.grab(
                        bbox=(
                            rectangle.left,
                            rectangle.top,
                            rectangle.right,
                            rectangle.bottom,
                        ),
                        all_screens=True,
                    ).save(audio_path)
                    click_window_fraction(window, 0.81, 0.47)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "tracks.changed"
                        and any(
                            track.get("selected")
                            and track.get("type") == "audio"
                            and track.get("language") == "fra"
                            for track in event.get("tracks", [])
                        ),
                        3,
                    )
                    time.sleep(0.8)
                    click_window_fraction(window, 0.92, 0.945)
                    time.sleep(0.5)
                    subtitle_tracks_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-subtitle-tracks{args.screenshot.suffix}"
                    )
                    rectangle = wintypes.RECT()
                    ctypes.WinDLL("user32").GetWindowRect(window, ctypes.byref(rectangle))
                    ImageGrab.grab(
                        bbox=(
                            rectangle.left,
                            rectangle.top,
                            rectangle.right,
                            rectangle.bottom,
                        ),
                        all_screens=True,
                    ).save(subtitle_tracks_path)
                    click_window_fraction(window, 0.81, 0.50)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "tracks.changed"
                        and any(
                            track.get("selected")
                            and track.get("type") == "sub"
                            and track.get("language") == "spa"
                            for track in event.get("tracks", [])
                        ),
                        3,
                    )
                send_window_key(window, 0x20)
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "playback.state"
                    and event.get("state") == "playing",
                    3,
                )
                send_window_key(window, 0x27)
                send_window_key(window, 0x46)
                time.sleep(0.2)
                send_window_key(window, 0x1B)
                send_window_key(window, 0x44)
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "subtitle.search",
                    3,
                )
                if args.exercise_subtitle_provider_flow:
                    if not args.external_subtitle or not args.external_subtitle.resolve().is_file():
                        raise RuntimeError(
                            "--external-subtitle is required for subtitle-provider flow."
                        )
                    backend_sequence += 1
                    transport.send(message(
                        session_id,
                        backend_sequence,
                        "subtitle.results",
                        status="complete",
                        results=[{
                            "result_id": "fixture-result",
                            "provider": "fixture-provider",
                            "language": "en",
                            "release_name": "Cinema.Paradiso.Phase4.1080p",
                            "file_name": args.external_subtitle.name,
                            "frame_rate": 23.976,
                            "rating": 9.0,
                            "download_count": 1000,
                            "hearing_impaired": False,
                            "forced": False,
                            "match_reason": "Exact file hash",
                        }],
                        diagnostics={},
                    ))
                    time.sleep(0.5)
                if args.screenshot:
                    time.sleep(0.3)
                    overlay_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-subtitle-search{args.screenshot.suffix}"
                    )
                    rectangle = wintypes.RECT()
                    ctypes.WinDLL("user32").GetWindowRect(window, ctypes.byref(rectangle))
                    ImageGrab.grab(
                        bbox=(
                            rectangle.left,
                            rectangle.top,
                            rectangle.right,
                            rectangle.bottom,
                        ),
                        all_screens=True,
                    ).save(overlay_path)
                if args.exercise_subtitle_provider_flow:
                    send_window_key(window, 0x0D)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "subtitle.download"
                        and event.get("result_id") == "fixture-result",
                        3,
                    )
                    backend_sequence += 1
                    transport.send(message(
                        session_id,
                        backend_sequence,
                        "subtitle.loaded",
                        path=str(args.external_subtitle.resolve()),
                        provider="fixture-provider",
                        language="en",
                        release_name="Cinema.Paradiso.Phase4.1080p",
                    ))
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "subtitle.loaded"
                        and event.get("provider") == "fixture-provider",
                        3,
                    )
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "tracks.changed"
                        and any(
                            track.get("selected")
                            and track.get("type") == "sub"
                            and track.get("external")
                            for track in event.get("tracks", [])
                        ),
                        4,
                    )

            backend_sequence += 1
            transport.send(message(session_id, backend_sequence, "close"))
            close_deadline = time.monotonic() + 5.0
            while time.monotonic() < close_deadline:
                try:
                    event = transport.receive(0.5)
                except (TimeoutError, OSError, RuntimeError):
                    if process.poll() is not None:
                        break
                    continue
                validate_message(event, session_id=session_id)
                events.append(event)
                if event["type"] == "closed":
                    break
        finally:
            if process and process.poll() is None:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()

    event_types = [event["type"] for event in events]
    tracks = [
        track
        for event in events
        if event["type"] == "tracks.changed"
        for track in event.get("tracks", [])
    ]
    progress = [event for event in events if event["type"] == "progress"]
    progress_positions = [
        int(event.get("position_ms", 0))
        for event in progress
    ]
    required = {"hello", "ready", "playback.state", "progress", "tracks.changed", "closed"}
    missing = sorted(required.difference(event_types))
    if missing:
        raise RuntimeError(
            f"Production helper omitted required events: {missing}; received {event_types}"
        )
    if not args.allow_no_audio and not any(track.get("type") == "audio" for track in tracks):
        raise RuntimeError("Production helper did not report an audio track.")
    if args.require_subtitle and not any(track.get("type") == "sub" for track in tracks):
        raise RuntimeError("Production helper did not report a subtitle track.")
    if not all(track.get("fingerprint") for track in tracks):
        raise RuntimeError("Production helper returned a track without a fingerprint.")
    if args.restore_audio_fingerprint and not any(
        track.get("selected")
        and track.get("fingerprint") == args.restore_audio_fingerprint
        for track in tracks
    ):
        raise RuntimeError("Production helper did not restore the requested audio track.")
    if args.restore_subtitle_fingerprint and not any(
        track.get("selected")
        and track.get("fingerprint") == args.restore_subtitle_fingerprint
        for track in tracks
    ):
        raise RuntimeError("Production helper did not restore the requested subtitle track.")
    settings = [
        event for event in events if event["type"] == "playback.settings"
    ]
    if args.restore_subtitle_delay_ms and not any(
        abs(int(event.get("subtitle_delay_ms", 0)) - args.restore_subtitle_delay_ms) <= 1
        for event in settings
    ):
        raise RuntimeError("Production helper did not restore the requested subtitle delay.")
    if process.returncode != 0:
        raise RuntimeError(f"Production helper exited with code {process.returncode}.")
    max_position_ms = max(progress_positions, default=0)
    if max_position_ms < max(0, args.require_min_position_ms):
        raise RuntimeError(
            "Production helper did not reach the required playback position: "
            f"{max_position_ms} ms < {args.require_min_position_ms} ms."
        )

    report = {
        "schema": "cp-player-production-smoke-v1",
        "ok": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "executable": str(executable),
        "media_fixture": str(media),
        "process_arguments": [executable.name],
        "media_path_in_process_arguments": False,
        "event_types": sorted(set(event_types)),
        "event_type_counts": dict(sorted(Counter(event_types).items())),
        "track_count": len(tracks),
        "audio_tracks": sum(track.get("type") == "audio" for track in tracks),
        "subtitle_tracks": sum(track.get("type") == "sub" for track in tracks),
        "progress_samples": len(progress),
        "max_duration_ms": max(
            (int(event.get("duration_ms", 0)) for event in progress),
            default=0,
        ),
        "first_position_ms": progress_positions[0] if progress_positions else 0,
        "max_position_ms": max_position_ms,
        "last_position_ms": int(progress[-1]["position_ms"]) if progress else 0,
        "process_exit_code": process.returncode if process else None,
        "controls_exercised": bool(args.exercise_controls),
        "resume_exercised": bool(args.exercise_resume),
        "track_restore_exercised": bool(
            args.restore_audio_fingerprint or args.restore_subtitle_fingerprint
        ),
        "subtitle_delay_restore_ms": args.restore_subtitle_delay_ms,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
