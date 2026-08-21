import tempfile
import unittest
from pathlib import Path

from services.catalog_store import CatalogStore
from services.playback_history import PlaybackHistoryService, PlaybackHistoryStore
from services.player_config import PlayerConfig


class FakeCuration:
    def __init__(self):
        self.watched = False
        self.calls = []

    def system_states_for_movie(self, movie):
        return {"watched": self.watched, "watchlist": False}

    def set_system_list_state(self, system_type, movie, active):
        self.calls.append((system_type, dict(movie), active))
        self.watched = bool(active)


class Session:
    def __init__(self, context):
        self.playback_context = context


class PlaybackHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.media = self.root / "Alien.mkv"
        self.media.write_bytes(b"fixture")
        self.path_key = str(self.media).lower()
        self.store = CatalogStore(self.root / "catalog.sqlite")
        self.store.import_documents({
            "app_metadata/files.json": {"files": {
                self.path_key: {
                    "path": str(self.media),
                    "filename": self.media.name,
                    "identity_status": "accepted",
                    "metadata_status": "accepted",
                    "metadata_accepted": True,
                    "tmdb_id": "348",
                },
            }},
            "app_metadata/tmdb_metadata.json": {"movies": {
                "348": {
                    "tmdb_id": "348",
                    "title": "Alien",
                    "year": "1979",
                    "poster_url": "https://image.tmdb.org/alien.jpg?unsafe=1",
                },
            }},
        }, {})
        self.clock_value = 1000.0
        self.history = PlaybackHistoryStore(
            self.store,
            clock=lambda: self.clock_value,
        )
        self.config = PlayerConfig({
            "resume_enabled": True,
            "minimum_resume_seconds": 2,
            "completion_threshold": 0.9,
            "auto_mark_completed_watched": True,
        })
        self.curation = FakeCuration()
        self.monotonic = 10.0
        self.service = PlaybackHistoryService(
            self.history,
            self.config,
            lambda: self.curation,
            monotonic_clock=lambda: self.monotonic,
        )
        self.media_payload = {
            "path_key": self.path_key,
            "movie_key": "tmdb:348",
            "path": str(self.media),
            "title": "Alien",
            "year": "1979",
            "tmdb_id": "348",
            "imdb_id": "tt0078748",
            "poster_reference": "https://image.tmdb.org/alien.jpg",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_resume_threshold_and_revision_reject_late_sessions(self):
        first = self.history.begin_session(self.path_key, "tmdb:348")
        saved = self.history.save(
            self.path_key,
            first["revision"],
            position_ms=5000,
            duration_ms=10000,
            completion_threshold=0.9,
        )
        self.assertTrue(saved["accepted"])

        context = self.service.begin_session(self.media_payload)
        self.assertEqual(context["start_position_ms"], 5000)
        late = self.history.save(
            self.path_key,
            first["revision"],
            position_ms=8000,
            duration_ms=10000,
            completion_threshold=0.9,
        )
        self.assertFalse(late["accepted"])
        self.assertEqual(self.history.get(self.path_key)["position_ms"], 5000)

    def test_progress_is_throttled_but_pause_seek_and_close_are_persisted(self):
        context = self.service.begin_session(self.media_payload)
        session = Session(context)
        self.service.handle_event(session, {
            "type": "progress",
            "position_ms": 1000,
            "duration_ms": 10000,
            "paused": False,
        })
        self.assertEqual(self.history.get(self.path_key)["position_ms"], 0)

        self.monotonic += 1
        self.service.handle_event(session, {
            "type": "progress",
            "position_ms": 8000,
            "duration_ms": 10000,
            "paused": False,
        })
        self.assertEqual(self.history.get(self.path_key)["position_ms"], 8000)

        self.monotonic += 1
        self.service.handle_event(session, {
            "type": "progress",
            "position_ms": 6500,
            "duration_ms": 10000,
            "paused": True,
        })
        self.assertEqual(self.history.get(self.path_key)["position_ms"], 6500)

        self.service.handle_event(session, {"type": "closed"})
        self.assertEqual(self.history.get(self.path_key)["position_ms"], 6500)

    def test_completion_uses_existing_watched_owner_once(self):
        context = self.service.begin_session(self.media_payload)
        session = Session(context)
        self.service.handle_event(session, {
            "type": "progress",
            "position_ms": 9500,
            "duration_ms": 10000,
            "paused": True,
        })
        self.assertIsNotNone(self.history.get(self.path_key)["completed_at"])
        self.assertEqual(len(self.curation.calls), 1)
        self.assertEqual(self.curation.calls[0][0], "watched")

        self.service.handle_event(session, {"type": "playback.state", "state": "ended"})
        self.assertEqual(len(self.curation.calls), 1)

    def test_completed_movie_rewatch_starts_fresh_then_resumes_without_unwatching(self):
        completed_context = self.service.begin_session(self.media_payload)
        completed_session = Session(completed_context)
        self.service.handle_event(completed_session, {
            "type": "tracks.changed",
            "tracks": [{
                "type": "audio",
                "fingerprint": "audio|eng|eac3|6|English",
                "selected": True,
            }],
        })
        self.service.handle_event(completed_session, {
            "type": "progress",
            "position_ms": 9500,
            "duration_ms": 10000,
            "paused": True,
        })
        self.assertIsNotNone(self.history.get(self.path_key)["completed_at"])
        self.assertTrue(self.curation.watched)

        rewatch_context = self.service.begin_session(self.media_payload)
        self.assertEqual(rewatch_context["start_position_ms"], 0)
        self.assertFalse(rewatch_context["resume_choice_pending"])
        self.assertIsNone(self.history.get(self.path_key)["completed_at"])
        self.assertTrue(self.curation.watched)
        self.assertEqual(
            rewatch_context["audio_track_fingerprint"],
            "audio|eng|eac3|6|English",
        )

        rewatch_session = Session(rewatch_context)
        self.service.handle_event(rewatch_session, {
            "type": "progress",
            "position_ms": 3500,
            "duration_ms": 10000,
            "paused": True,
        })
        resumed_context = self.service.begin_session(self.media_payload)
        self.assertTrue(resumed_context["resume_choice_pending"])
        self.assertEqual(resumed_context["start_position_ms"], 3500)
        self.assertTrue(self.curation.watched)
        self.assertEqual(len(self.service.continue_watching()), 1)

    def test_resume_prompt_restart_choice_clears_only_progress(self):
        row = self.history.begin_session(self.path_key, "tmdb:348")
        self.history.save(
            self.path_key,
            row["revision"],
            position_ms=5000,
            duration_ms=10000,
            completion_threshold=0.9,
            audio_track_fingerprint="audio:eng",
        )
        context = self.service.begin_session(self.media_payload)
        self.assertTrue(context["resume_choice_pending"])
        session = Session(context)
        self.service.handle_event(session, {
            "type": "resume.choice",
            "choice": "restart",
        })
        restarted = self.history.get(self.path_key)
        self.assertEqual(restarted["position_ms"], 0)
        self.assertEqual(restarted["audio_track_fingerprint"], "audio:eng")

    def test_track_and_subtitle_delay_changes_persist_for_the_next_session(self):
        context = self.service.begin_session(self.media_payload)
        session = Session(context)
        self.service.handle_event(session, {
            "type": "tracks.changed",
            "tracks": [
                {
                    "type": "audio",
                    "fingerprint": "audio|fra|ac3|6|French",
                    "selected": True,
                },
                {
                    "type": "sub",
                    "fingerprint": "sub|spa|ass||Spanish",
                    "selected": True,
                },
            ],
        })
        self.service.handle_event(session, {
            "type": "playback.settings",
            "subtitle_delay_ms": -250,
        })
        stored = self.history.get(self.path_key)
        self.assertEqual(stored["audio_track_fingerprint"], "audio|fra|ac3|6|French")
        self.assertEqual(stored["subtitle_track_fingerprint"], "sub|spa|ass||Spanish")
        self.assertEqual(stored["subtitle_delay_ms"], -250)

        restored = self.service.begin_session(self.media_payload)
        self.assertEqual(restored["audio_track_fingerprint"], "audio|fra|ac3|6|French")
        self.assertEqual(restored["subtitle_track_fingerprint"], "sub|spa|ass||Spanish")
        self.assertEqual(restored["subtitle_delay_ms"], -250)

    def test_continue_watching_uses_canonical_presentation_for_watched_replays(self):
        row = self.history.begin_session(self.path_key, "stale:key")
        self.history.save(
            self.path_key,
            row["revision"],
            position_ms=4000,
            duration_ms=10000,
            completion_threshold=0.9,
        )
        items = self.service.continue_watching()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["movie_key"], "tmdb:348")
        self.assertEqual(items[0]["title"], "Alien")
        self.assertEqual(items[0]["poster_url"], "https://image.tmdb.org/alien.jpg")
        self.assertEqual(items[0]["path_key"], self.path_key)

        self.curation.watched = True
        watched_replay_items = self.service.continue_watching()
        self.assertEqual(len(watched_replay_items), 1)
        self.assertEqual(watched_replay_items[0]["movie_key"], "tmdb:348")


if __name__ == "__main__":
    unittest.main()
