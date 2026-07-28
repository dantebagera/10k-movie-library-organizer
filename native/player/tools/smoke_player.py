import argparse
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
    user32.SetCursorPos(x, y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


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
    parser.add_argument("--allow-no-audio", action="store_true")
    parser.add_argument("--require-subtitle", action="store_true")
    parser.add_argument("--exercise-controls", action="store_true")
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
    environment.update(
        {
            "CP_PLAYER_PIPE": pipe_name,
            "CP_PLAYER_SESSION_ID": session_id,
            "CP_PLAYER_SESSION_TOKEN": token,
            "CP_PLAYER_PROTOCOL": str(PLAYER_PROTOCOL_VERSION),
        }
    )

    process = None
    events = []
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
                    start_position_ms=500,
                    preferences={
                        "preferred_audio_languages": ["eng", "fra"],
                        "preferred_subtitle_languages": ["eng", "spa"],
                        "hardware_decoding": "auto_safe",
                    },
                )
            )
            ready = transport.receive(10)
            validate_message(ready, expected_type="ready", session_id=session_id)
            if not ready.get("accepted"):
                raise RuntimeError("The production player rejected the fixture.")
            events.append(ready)

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

            transport.send(message(session_id, 2, "close"))
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
    if process.returncode != 0:
        raise RuntimeError(f"Production helper exited with code {process.returncode}.")

    report = {
        "schema": "cp-player-production-smoke-v1",
        "ok": True,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "executable": str(executable),
        "media_fixture": str(media),
        "process_arguments": [executable.name],
        "media_path_in_process_arguments": False,
        "event_types": event_types,
        "track_count": len(tracks),
        "audio_tracks": sum(track.get("type") == "audio" for track in tracks),
        "subtitle_tracks": sum(track.get("type") == "sub" for track in tracks),
        "progress_samples": len(progress),
        "last_position_ms": int(progress[-1]["position_ms"]) if progress else 0,
        "process_exit_code": process.returncode if process else None,
        "controls_exercised": bool(args.exercise_controls),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
