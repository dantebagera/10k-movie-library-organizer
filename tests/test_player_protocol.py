import unittest

from services.player_protocol import (
    JsonLineBuffer,
    PLAYER_PROTOCOL_VERSION,
    PlayerProtocolError,
    encode_message,
    validate_message,
)


def message(message_type, **payload):
    return {
        "type": message_type,
        "protocol": PLAYER_PROTOCOL_VERSION,
        "session_id": "session-1",
        "sequence": 1,
        **payload,
    }


class PlayerProtocolTests(unittest.TestCase):
    def test_fragmented_newline_json_round_trip(self):
        payload = encode_message(message(
            "hello",
            token="private-token",
            player_version="0.1.0",
        ))
        buffer = JsonLineBuffer()

        self.assertEqual(buffer.feed(payload[:7]), [])
        decoded = buffer.feed(payload[7:])

        self.assertEqual(decoded[0]["type"], "hello")
        self.assertEqual(decoded[0]["token"], "private-token")

    def test_handshake_rejects_wrong_version_session_and_token(self):
        hello = message("hello", token="wrong")

        with self.assertRaisesRegex(PlayerProtocolError, "authentication"):
            validate_message(
                hello,
                expected_type="hello",
                session_id="session-1",
                token="expected",
            )
        with self.assertRaisesRegex(PlayerProtocolError, "session"):
            validate_message(
                {**hello, "session_id": "other"},
                session_id="session-1",
            )
        with self.assertRaisesRegex(PlayerProtocolError, "incompatible"):
            validate_message({**hello, "protocol": 99})

    def test_progress_rejects_invalid_shapes_and_bounds(self):
        with self.assertRaises(PlayerProtocolError):
            validate_message(message(
                "progress",
                position_ms=-1,
                duration_ms=1000,
                paused=False,
            ))
        with self.assertRaises(PlayerProtocolError):
            validate_message(message(
                "progress",
                position_ms=100,
                duration_ms=1000,
                paused="false",
            ))

    def test_track_events_are_bounded_and_descriptive(self):
        track = {
            "fingerprint": "audio|ar|eac3|5.1|main",
            "type": "audio",
            "language": "ar",
            "title": "Arabic",
            "codec": "eac3",
            "channels": "5.1",
            "selected": True,
            "default": True,
            "forced": False,
            "hearing_impaired": False,
        }

        validated = validate_message(message("tracks.changed", tracks=[track]))

        self.assertEqual(validated["tracks"][0]["fingerprint"], track["fingerprint"])
        with self.assertRaises(PlayerProtocolError):
            validate_message(message("tracks.changed", tracks=[track] * 129))

    def test_load_requires_catalog_identity_and_local_path(self):
        load = message(
            "load",
            media={
                "path_key": "e:\\movies\\movie.mkv",
                "path": "E:\\Movies\\Movie.mkv",
                "title": "Movie",
                "year": "2024",
            },
            start_position_ms=0,
            preferences={},
        )

        self.assertEqual(validate_message(load)["type"], "load")
        with self.assertRaises(PlayerProtocolError):
            validate_message({**load, "media": {"path": "E:\\Movies\\Movie.mkv"}})

    def test_resume_choice_is_bounded_to_resume_or_restart(self):
        self.assertEqual(
            validate_message(message("resume.choice", choice="resume"))["choice"],
            "resume",
        )
        self.assertEqual(
            validate_message(message("resume.choice", choice="restart"))["choice"],
            "restart",
        )
        with self.assertRaises(PlayerProtocolError):
            validate_message(message("resume.choice", choice="skip"))

    def test_playback_settings_bounds_subtitle_delay(self):
        self.assertEqual(
            validate_message(
                message("playback.settings", subtitle_delay_ms=-250)
            )["subtitle_delay_ms"],
            -250,
        )
        with self.assertRaises(PlayerProtocolError):
            validate_message(
                message("playback.settings", subtitle_delay_ms=4_000_000)
            )

    def test_subtitle_results_and_download_commands_are_bounded(self):
        result = {
            "result_id": "opaque-result",
            "provider": "subdl",
            "language": "en",
            "release_name": "Movie.2024.1080p",
            "file_name": "movie.srt",
            "frame_rate": 23.976,
            "rating": 8.5,
            "download_count": 100,
            "hearing_impaired": False,
            "forced": False,
            "match_reason": "Release-name match",
        }
        self.assertEqual(
            validate_message(message(
                "subtitle.results",
                status="complete",
                results=[result],
                diagnostics={},
            ))["results"][0]["result_id"],
            "opaque-result",
        )
        self.assertEqual(
            validate_message(
                message("subtitle.download", result_id="opaque-result")
            )["result_id"],
            "opaque-result",
        )
        with self.assertRaises(PlayerProtocolError):
            validate_message(message(
                "subtitle.results",
                status="complete",
                results=[result] * 41,
                diagnostics={},
            ))


if __name__ == "__main__":
    unittest.main()
