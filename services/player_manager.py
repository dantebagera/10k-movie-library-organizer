import os
import secrets
import subprocess
import threading
import time
import uuid
from pathlib import Path

from services.player_protocol import (
    PLAYER_PROTOCOL_VERSION,
    PlayerProtocolError,
    validate_message,
)
from services.player_runtime import PlayerRuntimeError
from services.player_windows_pipe import WindowsNamedPipeServer


PLAYER_STARTUP_TIMEOUT_SECONDS = 10
PLAYER_EVENT_TIMEOUT_SECONDS = 1
PLAYER_SHUTDOWN_TIMEOUT_SECONDS = 5


class PlayerLaunchError(RuntimeError):
    pass


def safe_player_preferences(payload):
    allowed = {
        "preferred_audio_languages",
        "preferred_subtitle_languages",
        "prefer_forced_subtitles",
        "prefer_hearing_impaired_subtitles",
        "hardware_decoding",
        "hdr_handling",
        "audio_output",
        "audio_passthrough",
        "keyboard_shortcuts",
    }
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if key in allowed
    }


def launch_player_process(executable, environment):
    return subprocess.Popen(
        [str(executable)],
        cwd=str(Path(executable).parent),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        shell=False,
    )


class PlayerSession:
    def __init__(self, session_id, process, transport, on_event):
        self.session_id = session_id
        self.process = process
        self.transport = transport
        self.on_event = on_event
        self.last_sequence = 0
        self.closed = threading.Event()
        self._send_sequence = 1
        self._reader = None

    def send(self, message_type, **payload):
        message = {
            "type": message_type,
            "protocol": PLAYER_PROTOCOL_VERSION,
            "session_id": self.session_id,
            "sequence": self._send_sequence,
            **payload,
        }
        self._send_sequence += 1
        self.transport.send(message)

    def start_reader(self):
        self._reader = threading.Thread(
            target=self._read_events,
            name=f"cp-player-{self.session_id[:8]}",
            daemon=True,
        )
        self._reader.start()

    def _read_events(self):
        try:
            while not self.closed.is_set():
                if self.process.poll() is not None:
                    break
                try:
                    message = self.transport.receive(PLAYER_EVENT_TIMEOUT_SECONDS)
                except TimeoutError:
                    continue
                validated = validate_message(message, session_id=self.session_id)
                sequence = validated.get("sequence", 0)
                if sequence <= self.last_sequence:
                    continue
                self.last_sequence = sequence
                self.on_event(self, validated)
                if validated["type"] == "closed":
                    break
        except (PlayerProtocolError, OSError, RuntimeError):
            pass
        finally:
            self.closed.set()
            self.transport.close()

    def close(self):
        if self.closed.is_set():
            return
        try:
            self.send("close")
        except (OSError, RuntimeError):
            pass
        if not self.closed.wait(PLAYER_SHUTDOWN_TIMEOUT_SECONDS):
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.closed.set()
            self.transport.close()


class PlayerManager:
    """Single authority for local-library playback mode, launch, IPC, and fallback."""

    def __init__(
        self,
        player_config,
        player_runtime,
        media_resolver,
        *,
        os_opener=None,
        transport_factory=None,
        process_launcher=None,
        startup_timeout=PLAYER_STARTUP_TIMEOUT_SECONDS,
    ):
        self.player_config = player_config
        self.player_runtime = player_runtime
        self.media_resolver = media_resolver
        self.os_opener = os_opener or getattr(os, "startfile", None)
        self.transport_factory = transport_factory or WindowsNamedPipeServer
        self.process_launcher = process_launcher or launch_player_process
        self.startup_timeout = float(startup_timeout)
        self._lock = threading.RLock()
        self._active = None
        self._last_event = {}

    def active_status(self):
        with self._lock:
            session = self._active
            return {
                "active": bool(session and not session.closed.is_set()),
                "session_id": session.session_id if session and not session.closed.is_set() else "",
                "last_event": dict(self._last_event),
            }

    def play(self, path_key):
        media = self.media_resolver(path_key)
        mode = self.player_config.public_payload()["mode"]
        if mode == "os_default":
            self._open_with_os(media["path"])
            return {"ok": True, "mode": "os_default", "fallback": False}
        try:
            return self._launch_built_in(media)
        except (PlayerRuntimeError, PlayerProtocolError, PlayerLaunchError, OSError, RuntimeError, TimeoutError):
            self._open_with_os(media["path"])
            return {
                "ok": True,
                "mode": "os_default",
                "fallback": True,
                "reason": "Cinema Paradiso Player could not start; the OS player was opened.",
            }

    def close_active(self):
        with self._lock:
            session = self._active
            self._active = None
        if session:
            session.close()

    def _open_with_os(self, path):
        if not self.os_opener:
            raise PlayerLaunchError("Operating-system playback is unavailable")
        try:
            self.os_opener(path)
        except OSError as error:
            raise PlayerLaunchError("The operating-system player could not open the file") from error

    def _launch_built_in(self, media):
        runtime = self.player_runtime.resolve_bundle(verify_hashes=True)
        executable = runtime["bundle_root"] / "cp-player.exe"
        self.close_active()

        session_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(32)
        pipe_name = f"cp-player-{session_id}"
        transport = self.transport_factory(pipe_name)
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
        environment.update({
            "CP_PLAYER_PIPE": pipe_name,
            "CP_PLAYER_SESSION_ID": session_id,
            "CP_PLAYER_SESSION_TOKEN": token,
            "CP_PLAYER_PROTOCOL": str(PLAYER_PROTOCOL_VERSION),
        })
        process = None
        try:
            process = self.process_launcher(executable, environment)
            transport.accept(self.startup_timeout)
            hello = transport.receive(self.startup_timeout)
            validate_message(
                hello,
                expected_type="hello",
                session_id=session_id,
                token=token,
            )
            session = PlayerSession(session_id, process, transport, self._handle_event)
            session.send(
                "load",
                media=media,
                start_position_ms=0,
                preferences=safe_player_preferences(
                    self.player_config.storage_payload()
                ),
            )
            ready = transport.receive(self.startup_timeout)
            validate_message(ready, session_id=session_id)
            if ready["type"] == "error" or not (
                ready["type"] == "ready" and ready.get("accepted") is True
            ):
                raise PlayerLaunchError("The native player rejected the playback session")
            session.last_sequence = ready.get("sequence", 0)
            with self._lock:
                self._active = session
                self._last_event = {
                    "type": "ready",
                    "received_at": time.time(),
                }
            session.start_reader()
            return {
                "ok": True,
                "mode": "built_in",
                "fallback": False,
                "session_id": session_id,
            }
        except Exception:
            transport.close()
            if process and process.poll() is None:
                process.terminate()
            raise

    def _handle_event(self, session, message):
        safe_event = {
            "type": message["type"],
            "sequence": message.get("sequence", 0),
            "received_at": time.time(),
        }
        if message["type"] == "playback.state":
            safe_event["state"] = message["state"]
        elif message["type"] == "progress":
            safe_event.update({
                "position_ms": int(message["position_ms"]),
                "duration_ms": int(message["duration_ms"]),
                "paused": message["paused"],
            })
        elif message["type"] == "error":
            safe_event.update({
                "code": message["code"],
                "message": message["message"],
            })
        with self._lock:
            if self._active is session:
                self._last_event = safe_event
                if message["type"] == "closed":
                    self._active = None
