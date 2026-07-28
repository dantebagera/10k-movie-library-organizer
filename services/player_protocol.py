import json
import math


PLAYER_PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 256 * 1024
MAX_STRING_LENGTH = 4096
MAX_TRACKS = 128
MAX_DURATION_MS = 30 * 24 * 60 * 60 * 1000

MESSAGE_TYPES = {
    "hello",
    "load",
    "ready",
    "playback.state",
    "progress",
    "resume.choice",
    "playback.settings",
    "tracks.changed",
    "subtitle.search",
    "subtitle.results",
    "subtitle.download",
    "subtitle.loaded",
    "error",
    "closing",
    "closed",
    "close",
}


class PlayerProtocolError(ValueError):
    pass


def _bounded_string(value, field, maximum=MAX_STRING_LENGTH, allow_empty=False):
    if not isinstance(value, str):
        raise PlayerProtocolError(f"{field} must be a string")
    if (not allow_empty and not value) or len(value) > maximum or "\x00" in value:
        raise PlayerProtocolError(f"{field} is invalid")
    return value


def _bounded_number(value, field, minimum=0, maximum=MAX_DURATION_MS):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlayerProtocolError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise PlayerProtocolError(f"{field} is out of range")
    return number


def _validate_tracks(tracks):
    if not isinstance(tracks, list) or len(tracks) > MAX_TRACKS:
        raise PlayerProtocolError("tracks must be a bounded list")
    result = []
    for track in tracks:
        if not isinstance(track, dict):
            raise PlayerProtocolError("track entries must be objects")
        result.append({
            "fingerprint": _bounded_string(
                track.get("fingerprint", ""),
                "track.fingerprint",
                maximum=512,
            ),
            "type": _bounded_string(track.get("type", ""), "track.type", maximum=16),
            "language": _bounded_string(
                track.get("language", "und"),
                "track.language",
                maximum=32,
            ),
            "title": _bounded_string(
                track.get("title", ""),
                "track.title",
                maximum=512,
                allow_empty=True,
            ),
            "codec": _bounded_string(
                track.get("codec", ""),
                "track.codec",
                maximum=64,
                allow_empty=True,
            ),
            "channels": _bounded_string(
                track.get("channels", ""),
                "track.channels",
                maximum=64,
                allow_empty=True,
            ),
            "selected": bool(track.get("selected", False)),
            "default": bool(track.get("default", False)),
            "forced": bool(track.get("forced", False)),
            "hearing_impaired": bool(track.get("hearing_impaired", False)),
        })
    return result


def validate_message(message, *, expected_type=None, session_id=None, token=None):
    if not isinstance(message, dict):
        raise PlayerProtocolError("Player message must be an object")
    message_type = _bounded_string(message.get("type", ""), "type", maximum=64)
    if message_type not in MESSAGE_TYPES:
        raise PlayerProtocolError("Player message type is not supported")
    if expected_type and message_type != expected_type:
        raise PlayerProtocolError(f"Expected {expected_type} message")
    if message.get("protocol") != PLAYER_PROTOCOL_VERSION:
        raise PlayerProtocolError("Player protocol version is incompatible")
    received_session_id = _bounded_string(
        message.get("session_id", ""),
        "session_id",
        maximum=128,
    )
    if session_id is not None and received_session_id != session_id:
        raise PlayerProtocolError("Player session does not match")
    sequence = message.get("sequence", 0)
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise PlayerProtocolError("Player message sequence is invalid")

    if message_type == "hello":
        received_token = _bounded_string(
            message.get("token", ""),
            "token",
            maximum=256,
        )
        if token is not None and received_token != token:
            raise PlayerProtocolError("Player session authentication failed")
    elif message_type == "load":
        media = message.get("media")
        if not isinstance(media, dict):
            raise PlayerProtocolError("Player load media is missing")
        _bounded_string(media.get("path_key", ""), "media.path_key")
        _bounded_string(media.get("path", ""), "media.path", maximum=32768)
        _bounded_string(
            media.get("title", ""),
            "media.title",
            maximum=512,
        )
        _bounded_string(
            media.get("year", ""),
            "media.year",
            maximum=16,
            allow_empty=True,
        )
        _bounded_number(message.get("start_position_ms", 0), "start_position_ms")
        if not isinstance(message.get("preferences", {}), dict):
            raise PlayerProtocolError("Player preferences must be an object")
        playback_state = message.get("playback_state", {})
        if not isinstance(playback_state, dict):
            raise PlayerProtocolError("Player playback state must be an object")
        for field in ("audio_track_fingerprint", "subtitle_track_fingerprint"):
            _bounded_string(
                playback_state.get(field, ""),
                f"playback_state.{field}",
                maximum=512,
                allow_empty=True,
            )
        _bounded_number(
            playback_state.get("subtitle_delay_ms", 0),
            "playback_state.subtitle_delay_ms",
            minimum=-60 * 60 * 1000,
            maximum=60 * 60 * 1000,
        )
    elif message_type == "ready":
        if not isinstance(message.get("accepted", False), bool):
            raise PlayerProtocolError("Player ready state is invalid")
    elif message_type == "playback.state":
        if message.get("state") not in {"loading", "playing", "paused", "ended", "error"}:
            raise PlayerProtocolError("Player playback state is invalid")
    elif message_type == "progress":
        _bounded_number(message.get("position_ms"), "position_ms")
        _bounded_number(message.get("duration_ms"), "duration_ms")
        if not isinstance(message.get("paused"), bool):
            raise PlayerProtocolError("Player paused state is invalid")
    elif message_type == "tracks.changed":
        _validate_tracks(message.get("tracks"))
    elif message_type == "resume.choice":
        if message.get("choice") not in {"resume", "restart"}:
            raise PlayerProtocolError("Player resume choice is invalid")
    elif message_type == "playback.settings":
        _bounded_number(
            message.get("subtitle_delay_ms"),
            "subtitle_delay_ms",
            minimum=-60 * 60 * 1000,
            maximum=60 * 60 * 1000,
        )
    elif message_type == "error":
        _bounded_string(message.get("code", ""), "error.code", maximum=128)
        _bounded_string(message.get("message", ""), "error.message", maximum=1024)

    return message


def encode_message(message):
    validate_message(message)
    encoded = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise PlayerProtocolError("Player message exceeds the size limit")
    return encoded


def decode_message(payload):
    if not isinstance(payload, (bytes, bytearray)) or not payload:
        raise PlayerProtocolError("Player message is empty")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise PlayerProtocolError("Player message exceeds the size limit")
    try:
        message = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PlayerProtocolError("Player message is not valid UTF-8 JSON") from error
    return validate_message(message)


class JsonLineBuffer:
    def __init__(self):
        self._buffer = bytearray()

    def feed(self, payload):
        if not isinstance(payload, (bytes, bytearray)):
            raise PlayerProtocolError("Player transport payload must be bytes")
        self._buffer.extend(payload)
        if len(self._buffer) > MAX_MESSAGE_BYTES and b"\n" not in self._buffer:
            raise PlayerProtocolError("Player message exceeds the size limit")
        messages = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                break
            line = bytes(self._buffer[:newline])
            del self._buffer[:newline + 1]
            if not line:
                continue
            messages.append(decode_message(line))
        return messages
