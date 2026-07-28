import os
import tempfile
import threading
import unittest
from pathlib import Path

from services.player_config import PlayerConfig
from services.player_manager import PlayerManager, PlayerSession, safe_player_preferences
from services.player_protocol import PLAYER_PROTOCOL_VERSION
from services.player_runtime import PlayerRuntimeError


class FakeRuntime:
    def __init__(self, root=None, error=None):
        self.root = Path(root) if root else None
        self.error = error

    def resolve_bundle(self, verify_hashes=True):
        if self.error:
            raise self.error
        return {
            "bundle_root": self.root,
            "manifest": {"player_version": "0.1.0"},
        }


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self.terminated or self.killed else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.terminated = True
        return 0


class HandshakeTransport:
    def __init__(self, pipe_name, launch_state, authenticated=True):
        self.pipe_name = pipe_name
        self.launch_state = launch_state
        self.authenticated = authenticated
        self.sent = []
        self.receive_count = 0
        self.closed = False

    def accept(self, timeout):
        self.launch_state["accepted_timeout"] = timeout

    def receive(self, timeout):
        self.receive_count += 1
        environment = self.launch_state["environment"]
        if self.receive_count == 1:
            return {
                "type": "hello",
                "protocol": PLAYER_PROTOCOL_VERSION,
                "session_id": environment["CP_PLAYER_SESSION_ID"],
                "sequence": 0,
                "token": (
                    environment["CP_PLAYER_SESSION_TOKEN"]
                    if self.authenticated
                    else "wrong"
                ),
            }
        if self.receive_count == 2:
            return {
                "type": "ready",
                "protocol": PLAYER_PROTOCOL_VERSION,
                "session_id": environment["CP_PLAYER_SESSION_ID"],
                "sequence": 1,
                "accepted": True,
            }
        if self.receive_count == 3:
            return {
                "type": "closed",
                "protocol": PLAYER_PROTOCOL_VERSION,
                "session_id": environment["CP_PLAYER_SESSION_ID"],
                "sequence": 2,
            }
        raise TimeoutError()

    def send(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True


class EventTransport:
    def __init__(self, messages):
        self.messages = list(messages)
        self.sent = []
        self.closed = False

    def receive(self, timeout):
        if self.messages:
            return self.messages.pop(0)
        raise TimeoutError()

    def send(self, message):
        self.sent.append(message)

    def close(self):
        self.closed = True


class FakePlaybackHistory:
    def __init__(self, start_position_ms=0):
        self.start_position_ms = start_position_ms
        self.started = []
        self.events = []
        self.received = threading.Event()

    def begin_session(self, media, restart=False):
        self.started.append((dict(media), restart))
        return {
            "media": dict(media),
            "revision": 7,
            "start_position_ms": self.start_position_ms,
        }

    def handle_event(self, session, message):
        self.events.append((session.playback_context, dict(message)))
        self.received.set()


class FakeSubtitleService:
    def __init__(self):
        self.searches = []
        self.downloads = []
        self.downloaded = threading.Event()

    def search_async(self, session_id, media, callback):
        self.searches.append((session_id, dict(media)))
        callback({"status": "complete", "results": [], "diagnostics": {}})

    def download(self, session_id, result_id, media):
        self.downloads.append((session_id, result_id, dict(media)))
        self.downloaded.set()
        return {
            "path": "C:\\cache\\subtitle.srt",
            "provider": "subdl",
            "language": "en",
            "release_name": "Movie",
        }


class PlayerManagerTests(unittest.TestCase):
    @staticmethod
    def media(path):
        return {
            "path_key": os.path.normcase(os.path.normpath(str(path))),
            "movie_key": "tmdb:42",
            "path": str(path),
            "title": "Movie",
            "year": "2024",
            "poster_reference": "",
        }

    def test_os_default_opens_resolved_catalog_path(self):
        with tempfile.TemporaryDirectory() as root:
            media_path = Path(root) / "Movie.mkv"
            media_path.write_bytes(b"fixture")
            opened = []
            manager = PlayerManager(
                PlayerConfig(),
                FakeRuntime(error=AssertionError("runtime must not be read")),
                lambda path_key: self.media(media_path),
                os_opener=opened.append,
            )

            result = manager.play("catalog-key")

        self.assertEqual(opened, [str(media_path)])
        self.assertEqual(result["mode"], "os_default")
        self.assertFalse(result["fallback"])

    def test_built_in_launch_uses_private_environment_and_pipe_load(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "bundle"
            bundle.mkdir()
            executable = bundle / "cp-player.exe"
            executable.write_bytes(b"exe")
            media_path = Path(root) / "Movie.mkv"
            media_path.write_bytes(b"fixture")
            config = PlayerConfig()
            config.update({
                "mode": "built_in",
                "providers": {"subdl": {"api_key": "provider-secret"}},
            })
            launch_state = {}
            process = FakeProcess()

            def launcher(executable_path, environment):
                launch_state["executable"] = executable_path
                launch_state["environment"] = environment
                return process

            transports = []

            def transport_factory(pipe_name):
                transport = HandshakeTransport(pipe_name, launch_state)
                transports.append(transport)
                return transport

            manager = PlayerManager(
                config,
                FakeRuntime(bundle),
                lambda path_key: self.media(media_path),
                os_opener=lambda path: self.fail("OS fallback was not expected"),
                transport_factory=transport_factory,
                process_launcher=launcher,
            )

            result = manager.play("catalog-key")

        self.assertEqual(result["mode"], "built_in")
        self.assertEqual(launch_state["executable"], executable)
        environment = launch_state["environment"]
        self.assertNotIn("provider-secret", str(environment))
        self.assertNotIn(str(media_path), str(environment))
        self.assertEqual(transports[0].pipe_name, environment["CP_PLAYER_PIPE"])
        load = transports[0].sent[0]
        self.assertEqual(load["type"], "load")
        self.assertEqual(load["media"]["path"], str(media_path))
        self.assertNotIn("providers", load["preferences"])

    def test_runtime_or_authentication_failure_falls_back_to_os_player(self):
        with tempfile.TemporaryDirectory() as root:
            media_path = Path(root) / "Movie.mkv"
            media_path.write_bytes(b"fixture")
            config = PlayerConfig()
            config.update({"mode": "built_in"})
            opened = []
            manager = PlayerManager(
                config,
                FakeRuntime(error=PlayerRuntimeError("runtime missing")),
                lambda path_key: self.media(media_path),
                os_opener=opened.append,
            )

            result = manager.play("catalog-key")

            self.assertTrue(result["fallback"])
            self.assertEqual(opened, [str(media_path)])

            bundle = Path(root) / "bundle"
            bundle.mkdir()
            (bundle / "cp-player.exe").write_bytes(b"exe")
            launch_state = {}
            process = FakeProcess()

            def launcher(executable, environment):
                launch_state["environment"] = environment
                return process

            manager = PlayerManager(
                config,
                FakeRuntime(bundle),
                lambda path_key: self.media(media_path),
                os_opener=opened.append,
                transport_factory=lambda name: HandshakeTransport(
                    name,
                    launch_state,
                    authenticated=False,
                ),
                process_launcher=launcher,
            )

            result = manager.play("catalog-key")

        self.assertTrue(result["fallback"])
        self.assertTrue(process.terminated)
        self.assertEqual(opened, [str(media_path), str(media_path)])

    def test_history_owner_supplies_resume_position_and_receives_session_events(self):
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "bundle"
            bundle.mkdir()
            (bundle / "cp-player.exe").write_bytes(b"exe")
            media_path = Path(root) / "Movie.mkv"
            media_path.write_bytes(b"fixture")
            config = PlayerConfig({"mode": "built_in"})
            launch_state = {}
            process = FakeProcess()
            history = FakePlaybackHistory(start_position_ms=4200)

            def launcher(executable, environment):
                launch_state["environment"] = environment
                return process

            transport = HandshakeTransport("pipe", launch_state)
            manager = PlayerManager(
                config,
                FakeRuntime(bundle),
                lambda path_key: self.media(media_path),
                os_opener=lambda path: self.fail("OS fallback was not expected"),
                transport_factory=lambda name: transport,
                process_launcher=launcher,
                playback_history=history,
            )

            result = manager.play("catalog-key")
            self.assertTrue(history.received.wait(2))

        self.assertEqual(result["start_position_ms"], 4200)
        self.assertEqual(transport.sent[0]["start_position_ms"], 4200)
        self.assertFalse(history.started[0][1])
        self.assertEqual(history.events[-1][1]["type"], "closed")

    def test_session_ignores_duplicate_and_out_of_order_events(self):
        session_id = "session-1"
        events = []
        process = FakeProcess()
        transport = EventTransport([
            {
                "type": "progress",
                "protocol": PLAYER_PROTOCOL_VERSION,
                "session_id": session_id,
                "sequence": 3,
                "position_ms": 3000,
                "duration_ms": 10000,
                "paused": False,
            },
            {
                "type": "progress",
                "protocol": PLAYER_PROTOCOL_VERSION,
                "session_id": session_id,
                "sequence": 2,
                "position_ms": 2000,
                "duration_ms": 10000,
                "paused": False,
            },
            {
                "type": "closed",
                "protocol": PLAYER_PROTOCOL_VERSION,
                "session_id": session_id,
                "sequence": 4,
            },
        ])
        session = PlayerSession(
            session_id,
            process,
            transport,
            lambda _session, message: events.append(message),
        )

        session.start_reader()
        self.assertTrue(session.closed.wait(2))

        self.assertEqual([event["sequence"] for event in events], [3, 4])

    def test_unexpected_process_exit_emits_one_synthetic_closed_event(self):
        session_id = "session-crash"
        events = []
        process = FakeProcess()
        process.terminated = True
        session = PlayerSession(
            session_id,
            process,
            EventTransport([]),
            lambda _session, message: events.append(message),
        )

        session.start_reader()
        self.assertTrue(session.closed.wait(2))

        self.assertEqual([event["type"] for event in events], ["closed"])
        self.assertEqual(events[0]["reason"], "transport_closed")

    def test_safe_preferences_never_include_provider_credentials(self):
        payload = PlayerConfig({
            "providers": {"opensubtitles": {"api_key": "secret"}},
        }).storage_payload()

        safe = safe_player_preferences(payload)

        self.assertNotIn("providers", safe)
        self.assertNotIn("secret", str(safe))

    def test_subtitle_search_and_download_stay_on_authenticated_session(self):
        subtitle_service = FakeSubtitleService()
        manager = PlayerManager(
            PlayerConfig(),
            FakeRuntime(error=AssertionError("not used")),
            lambda _path_key: {},
            subtitle_service=subtitle_service,
        )
        transport = EventTransport([])
        session = PlayerSession(
            "subtitle-session",
            FakeProcess(),
            transport,
            lambda _session, _message: None,
            media={"path_key": "e:\\movie.mkv", "path": "E:\\Movie.mkv"},
        )
        manager._active = session

        manager._handle_event(session, {
            "type": "subtitle.search",
            "sequence": 2,
        })
        manager._handle_event(session, {
            "type": "subtitle.download",
            "sequence": 3,
            "result_id": "opaque-result",
        })
        self.assertTrue(subtitle_service.downloaded.wait(2))

        self.assertEqual(subtitle_service.searches[0][0], "subtitle-session")
        self.assertEqual(subtitle_service.downloads[0][1], "opaque-result")
        self.assertEqual(
            [message["type"] for message in transport.sent],
            ["subtitle.results", "subtitle.loaded"],
        )

    def test_window_state_is_persisted_by_the_authoritative_player_config(self):
        config = PlayerConfig()
        persisted = []
        manager = PlayerManager(
            config,
            FakeRuntime(error=AssertionError("not used")),
            lambda _path_key: {},
            persist_config=lambda: persisted.append(config.storage_payload()),
        )
        session = PlayerSession(
            "window-session",
            FakeProcess(),
            EventTransport([]),
            manager._handle_event,
        )

        manager._handle_event(session, {
            "type": "window.state",
            "sequence": 4,
            "window_state": {
                "x": -1280,
                "y": 40,
                "width": 1000,
                "height": 640,
                "screen": "DISPLAY2",
                "maximized": False,
                "always_on_top": True,
                "positioned": True,
            },
        })

        self.assertEqual(config.storage_payload()["window_state"]["x"], -1280)
        self.assertTrue(persisted[-1]["window_state"]["always_on_top"])


if __name__ == "__main__":
    unittest.main()
