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
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int

    @callback_type
    def callback(handle, _parameter):
        window_process = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(window_process))
        if window_process.value == process_id and user32.IsWindowVisible(handle):
            title_length = user32.GetWindowTextLengthW(handle)
            title_buffer = ctypes.create_unicode_buffer(title_length + 1)
            user32.GetWindowTextW(handle, title_buffer, title_length + 1)
            matches.append((handle, title_buffer.value))
        return True

    user32.EnumWindows(callback, 0)
    for handle, title in matches:
        if "Cinema Paradiso" in title:
            return handle
    return matches[0][0] if matches else None


def show_test_window(window):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.ShowWindow(window, 5)
    user32.SetWindowPos(
        window,
        wintypes.HWND(-1),
        0,
        0,
        0,
        0,
        0x0001 | 0x0002 | 0x0010,
    )
    user32.BringWindowToTop(window)
    user32.SetForegroundWindow(window)
    user32.SwitchToThisWindow(window, True)
    time.sleep(0.1)


def send_window_key(window, virtual_key):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    show_test_window(window)
    if user32.GetForegroundWindow() == window:
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, 0x0002, 0)
    else:
        user32.PostMessageW(window, 0x0100, virtual_key, 0)
        user32.PostMessageW(window, 0x0101, virtual_key, 0xC0000001)


def window_client_fraction_point(window, x_fraction, y_fraction):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.POINT),
    ]
    user32.ClientToScreen.restype = wintypes.BOOL
    rectangle = wintypes.RECT()
    if not user32.GetClientRect(window, ctypes.byref(rectangle)):
        raise RuntimeError("The native player client bounds were unavailable.")
    client = wintypes.POINT(
        round((rectangle.right - rectangle.left) * x_fraction),
        round((rectangle.bottom - rectangle.top) * y_fraction),
    )
    screen = wintypes.POINT(client.x, client.y)
    if not user32.ClientToScreen(window, ctypes.byref(screen)):
        raise RuntimeError("The native player client coordinates were unavailable.")
    packed = (client.x & 0xFFFF) | ((client.y & 0xFFFF) << 16)
    return user32, screen, packed


def click_window_fraction(window, x_fraction, y_fraction):
    user32, screen, packed = window_client_fraction_point(
        window,
        x_fraction,
        y_fraction,
    )
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    show_test_window(window)
    user32.SetCursorPos(screen.x, screen.y)
    time.sleep(0.05)
    if user32.GetForegroundWindow() == window:
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    else:
        user32.SendMessageW(window, 0x0201, 1, packed)
        user32.SendMessageW(window, 0x0202, 0, packed)


def send_media_play_pause(window):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    # APPCOMMAND_MEDIA_PLAY_PAUSE (14) occupies the high word of lParam.
    user32.SendMessageW(window, 0x0319, 0, 14 << 16)


def move_window_fraction(window, x_fraction, y_fraction):
    user32, screen, _ = window_client_fraction_point(
        window,
        x_fraction,
        y_fraction,
    )
    show_test_window(window)
    user32.SetCursorPos(screen.x - 2, screen.y)
    time.sleep(0.05)
    user32.SetCursorPos(screen.x, screen.y)
    user32.mouse_event(0x0001, 1, 0, 0, 0)
    time.sleep(0.1)


def drag_window_fraction(
    window,
    start_x_fraction,
    end_x_fraction,
    y_fraction,
    steps=12,
):
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    def client_point(x_fraction):
        _, screen, packed = window_client_fraction_point(
            window,
            x_fraction,
            y_fraction,
        )
        user32.SetCursorPos(screen.x, screen.y)
        return packed

    show_test_window(window)
    start = client_point(start_x_fraction)
    user32.SendMessageW(window, 0x0201, 1, start)
    for step in range(1, steps + 1):
        fraction = start_x_fraction + (
            end_x_fraction - start_x_fraction
        ) * step / steps
        packed = client_point(fraction)
        user32.SendMessageW(window, 0x0200, 1, packed)
        time.sleep(0.025)
    user32.SendMessageW(window, 0x0202, 0, packed)


def capture_window(window, destination):
    from PIL import ImageGrab

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        image = ImageGrab.grab(window=window)
    except TypeError:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        user32.GetWindowRect.restype = wintypes.BOOL
        rectangle = wintypes.RECT()
        if not user32.GetWindowRect(window, ctypes.byref(rectangle)):
            raise RuntimeError("The native player window bounds were unavailable.")
        image = ImageGrab.grab(
            bbox=(
                rectangle.left,
                rectangle.top,
                rectangle.right,
                rectangle.bottom,
            )
        )
    image.save(destination)


def read_windows_window_chrome(window):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    get_window_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    get_window_long.argtypes = [wintypes.HWND, ctypes.c_int]
    get_window_long.restype = ctypes.c_ssize_t
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    user32.GetWindowRect.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.RECT),
    ]
    user32.GetWindowRect.restype = wintypes.BOOL
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]

    def read_dword(attribute):
        value = wintypes.DWORD()
        result = dwmapi.DwmGetWindowAttribute(
            window,
            attribute,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
        return value.value if result >= 0 else None

    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(window, ctypes.byref(rectangle)):
        raise RuntimeError("The native player window bounds were unavailable.")

    def hit_test(client_x, client_y):
        screen = wintypes.POINT(
            rectangle.left + client_x,
            rectangle.top + client_y,
        )
        packed = (screen.x & 0xFFFF) | ((screen.y & 0xFFFF) << 16)
        return int(user32.SendMessageW(window, 0x0084, 0, packed))

    width = rectangle.right - rectangle.left
    height = rectangle.bottom - rectangle.top
    dpi = int(user32.GetDpiForWindow(window) or 96)
    scaled = lambda logical: round(logical * dpi / 96)
    style = int(get_window_long(window, -16))

    return {
        "style_hex": f"0x{style & 0xFFFFFFFF:08x}",
        "has_caption": bool(style & 0x00C00000),
        "has_thick_frame": bool(style & 0x00040000),
        "has_minimize_box": bool(style & 0x00020000),
        "has_maximize_box": bool(style & 0x00010000),
        "has_system_menu": bool(style & 0x00080000),
        "dpi": dpi,
        "dark_mode": bool(read_dword(20)),
        "hit_tests": {
            "top_drag": hit_test(width // 2, scaled(20)),
            "top_left_resize": hit_test(2, 2),
            "bottom_right_resize": hit_test(width - 2, height - 2),
            "window_controls": hit_test(
                width - scaled(29),
                scaled(27),
            ),
            "video_client": hit_test(
                width // 2,
                min(height - 10, scaled(100)),
            ),
        },
    }


def logical_pixels(window, value):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    dpi = int(user32.GetDpiForWindow(window) or 96)
    return round(value * dpi / 96)


def get_window_rectangle(window):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.RECT),
    ]
    user32.GetWindowRect.restype = wintypes.BOOL
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(window, ctypes.byref(rectangle)):
        raise RuntimeError("The native player window bounds were unavailable.")
    return (
        rectangle.left,
        rectangle.top,
        rectangle.right,
        rectangle.bottom,
    )


def set_window_rectangle(window, rectangle):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    left, top, right, bottom = rectangle
    if not user32.SetWindowPos(
        window,
        0,
        left,
        top,
        right - left,
        bottom - top,
        0x0004 | 0x0010,
    ):
        raise RuntimeError("The native player window bounds could not be restored.")


def wait_for_window_state(predicate, description, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError(f"The native player did not {description}.")


def click_window_client_point(window, client_x, client_y):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ClientToScreen.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.POINT),
    ]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    client = wintypes.POINT(round(client_x), round(client_y))
    screen = wintypes.POINT(client.x, client.y)
    if not user32.ClientToScreen(window, ctypes.byref(screen)):
        raise RuntimeError("The native player client coordinates were unavailable.")
    show_test_window(window)
    user32.SetCursorPos(screen.x, screen.y)
    time.sleep(0.05)
    packed = (client.x & 0xFFFF) | ((client.y & 0xFFFF) << 16)
    user32.SendMessageW(window, 0x0200, 0, packed)
    user32.SendMessageW(window, 0x0201, 1, packed)
    time.sleep(0.08)
    user32.SendMessageW(window, 0x0202, 0, packed)
    time.sleep(0.08)
    return {
        "client": (client.x, client.y),
        "screen": (screen.x, screen.y),
    }


def exercise_window_drag(window):
    before = get_window_rectangle(window)
    left, top, right, _bottom = before
    start_x = left + (right - left) // 2
    start_y = top + logical_pixels(window, 22)
    movement_x = logical_pixels(window, 7)
    movement_y = logical_pixels(window, 4)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    show_test_window(window)
    user32.SetCursorPos(start_x, start_y)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    for step in range(1, 9):
        user32.SetCursorPos(
            start_x + step * movement_x,
            start_y + step * movement_y,
        )
        time.sleep(0.025)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    wait_for_window_state(
        lambda: get_window_rectangle(window)[:2] != before[:2],
        "move through the CP drag region",
    )
    after = get_window_rectangle(window)
    set_window_rectangle(window, before)
    return {"before": before, "after": after}


def exercise_window_resize(window):
    before = get_window_rectangle(window)
    _left, _top, right, bottom = before
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    show_test_window(window)
    user32.SetCursorPos(right - 2, bottom - 2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    movement_x = logical_pixels(window, 8)
    movement_y = logical_pixels(window, 5)
    for step in range(1, 9):
        user32.SetCursorPos(
            right - 2 + step * movement_x,
            bottom - 2 + step * movement_y,
        )
        time.sleep(0.025)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    wait_for_window_state(
        lambda: get_window_rectangle(window)[2:] != before[2:],
        "resize through the CP bottom-right edge",
    )
    after = get_window_rectangle(window)
    set_window_rectangle(window, before)
    return {"before": before, "after": after}


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
    parser.add_argument("--poster-reference", type=Path)
    parser.add_argument("--observe-seconds", type=float, default=4.0)
    parser.add_argument("--require-min-position-ms", type=int, default=0)
    parser.add_argument("--allow-no-audio", action="store_true")
    parser.add_argument("--require-subtitle", action="store_true")
    parser.add_argument("--exercise-controls", action="store_true")
    parser.add_argument("--exercise-media-play-pause", action="store_true")
    parser.add_argument("--exercise-timeline", action="store_true")
    parser.add_argument("--exercise-speed-control", action="store_true")
    parser.add_argument("--exercise-window-chrome", action="store_true")
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
    poster_reference = ""
    if args.poster_reference:
        poster_path = args.poster_reference.resolve()
        if not poster_path.is_file():
            raise SystemExit("The poster fixture must exist.")
        poster_reference = poster_path.as_uri()

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
            "CP_PLAYER_CACHE_ROOT": str(isolated_local / "Cache"),
        }
    )

    process = None
    events = []
    window_chrome = {}
    window_chrome_actions = {}
    speed_control = {}
    timeline_click_position_ms = 0
    timeline_drag_position_ms = 0
    timeline_preview_thumbnail = ""
    timeline_y_fraction = 0.0
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
                        "poster_reference": poster_reference,
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
                    time.sleep(0.3)
                    resume_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-resume-prompt{args.screenshot.suffix}"
                    )
                    capture_window(window, resume_path)
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

            exercise_ui = (
                args.exercise_controls
                or args.exercise_media_play_pause
                or args.exercise_timeline
                or args.exercise_speed_control
                or args.exercise_window_chrome
            )
            if exercise_ui:
                window = find_visible_window(process.pid)
                if not window:
                    raise RuntimeError("The production player window was not visible.")
                show_test_window(window)
                window_chrome = read_windows_window_chrome(window)
                expected_hit_tests = {
                    "top_drag": 2,
                    "top_left_resize": 13,
                    "bottom_right_resize": 17,
                    "window_controls": 1,
                    "video_client": 1,
                }
                if window_chrome["has_caption"]:
                    raise RuntimeError("The CP player still has a Windows caption style.")
                for required_style in (
                    "has_thick_frame",
                    "has_minimize_box",
                    "has_maximize_box",
                    "has_system_menu",
                ):
                    if not window_chrome[required_style]:
                        raise RuntimeError(
                            f"The frameless player omitted {required_style}."
                        )
                if window_chrome["hit_tests"] != expected_hit_tests:
                    raise RuntimeError(
                        "The frameless hit-test contract is incorrect: "
                        + json.dumps(window_chrome["hit_tests"], sort_keys=True)
                    )
                if args.screenshot:
                    pre_controls_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-pre-controls{args.screenshot.suffix}"
                    )
                    capture_window(window, pre_controls_path)
                send_window_key(window, 0x20)
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "playback.state"
                    and event.get("state") == "paused",
                    3,
                )
                click_window_fraction(window, 0.50, 0.50)
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "playback.state"
                    and event.get("state") == "playing",
                    3,
                )
                click_window_fraction(window, 0.50, 0.50)
                receive_until(
                    transport,
                    process,
                    events,
                    lambda event: event["type"] == "playback.state"
                    and event.get("state") == "paused",
                    3,
                )
                if args.exercise_media_play_pause:
                    send_media_play_pause(window)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "playback.state"
                        and event.get("state") == "playing",
                        3,
                    )
                    send_media_play_pause(window)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "playback.state"
                        and event.get("state") == "paused",
                        3,
                    )
                if args.exercise_window_chrome:
                    user32 = ctypes.WinDLL("user32", use_last_error=True)
                    user32.IsIconic.argtypes = [wintypes.HWND]
                    user32.IsIconic.restype = wintypes.BOOL
                    user32.IsZoomed.argtypes = [wintypes.HWND]
                    user32.IsZoomed.restype = wintypes.BOOL
                    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

                    normal_rectangle = get_window_rectangle(window)
                    normal_width = normal_rectangle[2] - normal_rectangle[0]
                    maximize_click = click_window_client_point(
                        window,
                        normal_width - logical_pixels(window, 75),
                        logical_pixels(window, 27),
                    )
                    time.sleep(0.4)
                    maximize_result_rectangle = get_window_rectangle(window)
                    wait_for_window_state(
                        lambda: bool(user32.IsZoomed(window))
                        or get_window_rectangle(window) != normal_rectangle,
                        "maximize through the CP overlay control at "
                        f"{maximize_click}, rect={normal_rectangle}, "
                        f"result={maximize_result_rectangle}, "
                        f"is_zoomed={bool(user32.IsZoomed(window))}, "
                        f"dpi={window_chrome['dpi']}",
                    )
                    maximized_rectangle = get_window_rectangle(window)
                    if args.screenshot:
                        maximized_path = args.screenshot.with_name(
                            f"{args.screenshot.stem}-maximized{args.screenshot.suffix}"
                        )
                        capture_window(window, maximized_path)
                    maximized_width = (
                        maximized_rectangle[2] - maximized_rectangle[0]
                    )
                    click_window_client_point(
                        window,
                        maximized_width - logical_pixels(window, 75),
                        logical_pixels(window, 27),
                    )
                    wait_for_window_state(
                        lambda: not bool(user32.IsZoomed(window)),
                        "restore through the CP overlay control",
                    )
                    show_test_window(window)

                    restored_rectangle = get_window_rectangle(window)
                    restored_width = restored_rectangle[2] - restored_rectangle[0]
                    click_window_client_point(
                        window,
                        restored_width - logical_pixels(window, 121),
                        logical_pixels(window, 27),
                    )
                    wait_for_window_state(
                        lambda: bool(user32.IsIconic(window)),
                        "minimize through the CP overlay control",
                    )
                    user32.ShowWindow(window, 9)
                    wait_for_window_state(
                        lambda: not bool(user32.IsIconic(window)),
                        "restore after CP minimize",
                    )
                    show_test_window(window)

                    drag_evidence = exercise_window_drag(window)
                    resize_evidence = exercise_window_resize(window)
                    before_fullscreen = get_window_rectangle(window)
                    send_window_key(window, 0x46)
                    wait_for_window_state(
                        lambda: get_window_rectangle(window) != before_fullscreen,
                        "enter fullscreen",
                    )
                    fullscreen_rectangle = get_window_rectangle(window)
                    if args.screenshot:
                        fullscreen_path = args.screenshot.with_name(
                            f"{args.screenshot.stem}-fullscreen{args.screenshot.suffix}"
                        )
                        capture_window(window, fullscreen_path)
                    send_window_key(window, 0x46)
                    wait_for_window_state(
                        lambda: get_window_rectangle(window) != fullscreen_rectangle,
                        "exit fullscreen",
                    )
                    show_test_window(window)
                    window_chrome_actions = {
                        "minimize_restore": True,
                        "maximize_restore": True,
                        "normal_rectangle": normal_rectangle,
                        "maximized_rectangle": maximized_rectangle,
                        "drag": drag_evidence,
                        "resize": resize_evidence,
                        "fullscreen_rectangle": fullscreen_rectangle,
                        "fullscreen_exit_rectangle": get_window_rectangle(window),
                    }

                if args.exercise_speed_control:
                    speed_rectangle = get_window_rectangle(window)
                    speed_width = speed_rectangle[2] - speed_rectangle[0]
                    speed_height = speed_rectangle[3] - speed_rectangle[1]
                    click_window_client_point(
                        window,
                        speed_width - logical_pixels(window, 225),
                        speed_height - logical_pixels(window, 41),
                    )
                    time.sleep(0.35)
                    if args.screenshot:
                        speed_path = args.screenshot.with_name(
                            f"{args.screenshot.stem}-speed-panel{args.screenshot.suffix}"
                        )
                        capture_window(window, speed_path)
                    click_window_client_point(
                        window,
                        speed_width - logical_pixels(window, 176),
                        speed_height - logical_pixels(window, 217),
                    )
                    time.sleep(0.25)
                    send_window_key(window, 0x1B)
                    send_window_key(window, 0x20)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "playback.state"
                        and event.get("state") == "playing",
                        3,
                    )
                    speed_start = receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "progress",
                        2,
                    )
                    speed_started = time.monotonic()
                    speed_start_position = int(speed_start.get("position_ms", 0))
                    speed_end = receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "progress"
                        and int(event.get("position_ms", 0))
                            >= speed_start_position + 300,
                        1.1,
                    )
                    speed_elapsed = time.monotonic() - speed_started
                    speed_delta = (
                        int(speed_end.get("position_ms", 0)) - speed_start_position
                    )
                    measured_rate = speed_delta / max(1.0, speed_elapsed * 1000.0)
                    if measured_rate < 1.45:
                        raise RuntimeError(
                            "The clicked 2.00x speed preset did not accelerate playback."
                        )
                    send_window_key(window, 0x20)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "playback.state"
                        and event.get("state") == "paused",
                        3,
                    )
                    speed_control = {
                        "preset_clicked": "2.00x",
                        "position_delta_ms": speed_delta,
                        "observation_seconds": round(speed_elapsed, 3),
                        "measured_rate": round(measured_rate, 3),
                    }
                if args.exercise_timeline:
                    duration_ms = max(
                        (
                            int(event.get("duration_ms", 0))
                            for event in events
                            if event["type"] == "progress"
                        ),
                        default=0,
                    )
                    if duration_ms < 5000:
                        raise RuntimeError(
                            "Timeline smoke requires a media fixture of at least five seconds."
                        )
                    clicked = None
                    for timeline_y in (
                        0.890,
                        0.895,
                        0.900,
                        0.905,
                        0.910,
                        0.915,
                        0.920,
                    ):
                        click_window_fraction(window, 0.66, timeline_y)
                        try:
                            clicked = receive_until(
                                transport,
                                process,
                                events,
                                lambda event: event["type"] == "progress"
                                and event.get("position_ms", 0)
                                    >= int(duration_ms * 0.55),
                                1.25,
                            )
                            timeline_y_fraction = timeline_y
                            break
                        except RuntimeError:
                            continue
                    if clicked is None:
                        raise RuntimeError(
                            "Real mouse input did not activate the visible timeline."
                        )
                    if args.screenshot:
                        time.sleep(0.3)
                        pointer_path = args.screenshot.with_name(
                            f"{args.screenshot.stem}-timeline-pointer"
                            f"{args.screenshot.suffix}"
                        )
                        capture_window(window, pointer_path)
                    timeline_click_position_ms = int(
                        clicked.get("position_ms", 0)
                    )

                    move_window_fraction(window, 0.62, timeline_y_fraction)
                    preview_deadline = time.monotonic() + 8
                    preview_files = []
                    while time.monotonic() < preview_deadline:
                        preview_files = list(
                            isolated_local.rglob("seek-thumbnails/**/*.jpg")
                        )
                        if preview_files:
                            break
                        if process.poll() is not None:
                            break
                        time.sleep(0.1)
                    if not preview_files:
                        raise RuntimeError(
                            "Click seeking worked at "
                            f"{timeline_click_position_ms} ms, but hovering "
                            "did not produce an on-demand thumbnail."
                        )
                    timeline_preview_thumbnail = str(preview_files[0])
                    if args.screenshot:
                        time.sleep(0.4)
                        preview_path = args.screenshot.with_name(
                            f"{args.screenshot.stem}-timeline-preview"
                            f"{args.screenshot.suffix}"
                        )
                        capture_window(window, preview_path)

                    drag_window_fraction(
                        window,
                        0.30,
                        0.78,
                        timeline_y_fraction,
                    )
                    dragged = receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "progress"
                        and event.get("position_ms", 0)
                            >= int(duration_ms * 0.68),
                        4,
                    )
                    timeline_drag_position_ms = int(
                        dragged.get("position_ms", 0)
                    )
                if args.screenshot and args.exercise_controls:
                    time.sleep(0.3)
                    capture_window(window, args.screenshot)
                    send_window_key(window, 0x41)
                    time.sleep(0.3)
                    audio_path = args.screenshot.with_name(
                        f"{args.screenshot.stem}-audio-tracks{args.screenshot.suffix}"
                    )
                    capture_window(window, audio_path)
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
                    capture_window(window, subtitle_tracks_path)
                    spanish_selected = None
                    for subtitle_y in (0.55, 0.57, 0.59):
                        click_window_fraction(window, 0.81, subtitle_y)
                        try:
                            spanish_selected = receive_until(
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
                                1.25,
                            )
                            break
                        except RuntimeError:
                            send_window_key(window, 0x53)
                            time.sleep(0.2)
                    if spanish_selected is None:
                        raise RuntimeError(
                            "Real mouse input did not select the Spanish subtitle track."
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
                    capture_window(window, overlay_path)
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
                        result_id="fixture-result",
                        save_available=True,
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
                    send_window_key(window, 0x1B)
                    send_window_key(window, 0x53)
                    time.sleep(0.4)
                    if args.screenshot:
                        hub_path = args.screenshot.with_name(
                            f"{args.screenshot.stem}-subtitle-hub"
                            f"{args.screenshot.suffix}"
                        )
                        capture_window(window, hub_path)
                    click_window_fraction(window, 0.81, 0.45)
                    receive_until(
                        transport,
                        process,
                        events,
                        lambda event: event["type"] == "subtitle.save"
                        and event.get("result_id") == "fixture-result",
                        3,
                    )
                    backend_sequence += 1
                    transport.send(message(
                        session_id,
                        backend_sequence,
                        "subtitle.saved",
                        result_id="fixture-result",
                        path=str(
                            args.external_subtitle.with_name(
                                "Cinema.Paradiso.cp.en.fixture.srt"
                            ).resolve()
                        ),
                    ))
                    time.sleep(0.2)

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
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
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
        "controls_exercised": bool(
            args.exercise_controls
            or args.exercise_timeline
            or args.exercise_speed_control
            or args.exercise_window_chrome
        ),
        "screen_click_play_pause_exercised": bool(
            args.exercise_controls
            or args.exercise_timeline
            or args.exercise_speed_control
            or args.exercise_window_chrome
        ),
        "media_play_pause_exercised": bool(args.exercise_media_play_pause),
        "timeline_exercised": bool(args.exercise_timeline),
        "timeline_click_position_ms": timeline_click_position_ms,
        "timeline_drag_position_ms": timeline_drag_position_ms,
        "timeline_preview_thumbnail": timeline_preview_thumbnail,
        "timeline_y_fraction": timeline_y_fraction,
        "speed_control_exercised": bool(args.exercise_speed_control),
        "speed_control": speed_control,
        "window_chrome_exercised": bool(args.exercise_window_chrome),
        "windows_window_chrome": window_chrome,
        "window_chrome_actions": window_chrome_actions,
        "resume_exercised": bool(args.exercise_resume),
        "track_restore_exercised": bool(
            args.restore_audio_fingerprint or args.restore_subtitle_fingerprint
        ),
        "subtitle_delay_restore_ms": args.restore_subtitle_delay_ms,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
