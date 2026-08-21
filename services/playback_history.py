import math
import time
from pathlib import Path

from services.player_catalog import _safe_poster_reference


MAX_PLAYBACK_MS = 30 * 24 * 60 * 60 * 1000
MAX_FINGERPRINT_LENGTH = 512
PROGRESS_SAVE_INTERVAL_SECONDS = 15
SEEK_JUMP_THRESHOLD_MS = 5000
_UNSET = object()


class PlaybackHistoryError(ValueError):
    pass


def _bounded_ms(value, field):
    if isinstance(value, bool):
        raise PlaybackHistoryError(f"{field} must be a number")
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError, OverflowError) as error:
        raise PlaybackHistoryError(f"{field} must be a number") from error
    if number < 0 or number > MAX_PLAYBACK_MS:
        raise PlaybackHistoryError(f"{field} is out of range")
    return number


def _fingerprint(value):
    text = str(value or "").strip()
    return text[:MAX_FINGERPRINT_LENGTH] or None


def _row_payload(row):
    if not row:
        return None
    payload = dict(row)
    payload["position_ms"] = int(payload.get("position_ms") or 0)
    payload["duration_ms"] = int(payload.get("duration_ms") or 0)
    payload["revision"] = int(payload.get("revision") or 0)
    return payload


class PlaybackHistoryStore:
    """Authoritative persistence owner for the catalog playback_history table."""

    def __init__(self, catalog_store, clock=None):
        self._catalog_store_provider = (
            catalog_store if callable(catalog_store) else lambda: catalog_store
        )
        self.clock = clock or time.time

    @property
    def catalog_store(self):
        return self._catalog_store_provider()

    def get(self, path_key):
        connection = self.catalog_store.connect()
        try:
            return _row_payload(connection.execute(
                "SELECT * FROM playback_history WHERE path_key=?",
                (str(path_key),),
            ).fetchone())
        finally:
            connection.close()

    def begin_session(self, path_key, movie_key, *, restart=False):
        path_key = str(path_key or "").strip()
        if not path_key:
            raise PlaybackHistoryError("A playback file identity is required")
        now = max(0.0, float(self.clock()))
        with self.catalog_store.transaction() as connection:
            if not connection.execute(
                "SELECT 1 FROM media_files WHERE path_key=?",
                (path_key,),
            ).fetchone():
                raise PlaybackHistoryError("The playback file is no longer in the catalog")
            row = connection.execute(
                "SELECT * FROM playback_history WHERE path_key=?",
                (path_key,),
            ).fetchone()
            revision = int(row["revision"] if row else 0) + 1
            # A completed row belongs to the previous viewing. Opening it again is
            # a rewatch, so it must start a new unfinished session. Watched is
            # owned separately by curation and is intentionally not affected.
            rewatch = bool(row and row["completed_at"] is not None)
            position_ms = 0 if restart or rewatch else int(row["position_ms"] if row else 0)
            duration_ms = int(row["duration_ms"] if row else 0)
            completed_at = None if restart or rewatch else (row["completed_at"] if row else None)
            connection.execute("""
                INSERT INTO playback_history(
                    path_key, movie_key, position_ms, duration_ms, last_played_at,
                    completed_at, audio_track_fingerprint,
                    subtitle_track_fingerprint, subtitle_delay_ms, revision
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path_key) DO UPDATE SET
                    movie_key=excluded.movie_key,
                    position_ms=excluded.position_ms,
                    duration_ms=excluded.duration_ms,
                    last_played_at=excluded.last_played_at,
                    completed_at=excluded.completed_at,
                    revision=excluded.revision
            """, (
                path_key,
                str(movie_key or "").strip() or None,
                position_ms,
                duration_ms,
                now,
                completed_at,
                row["audio_track_fingerprint"] if row else None,
                row["subtitle_track_fingerprint"] if row else None,
                int(row["subtitle_delay_ms"] if row else 0),
                revision,
            ))
            return _row_payload(connection.execute(
                "SELECT * FROM playback_history WHERE path_key=?",
                (path_key,),
            ).fetchone())

    def restart_session(self, path_key, revision):
        with self.catalog_store.transaction() as connection:
            changed = connection.execute("""
                UPDATE playback_history
                SET position_ms=0, completed_at=NULL, last_played_at=?
                WHERE path_key=? AND revision=?
            """, (
                max(0.0, float(self.clock())),
                str(path_key),
                int(revision),
            )).rowcount
        return bool(changed)

    def save(
        self,
        path_key,
        revision,
        *,
        position_ms,
        duration_ms,
        completion_threshold,
        force_complete=False,
        audio_track_fingerprint=_UNSET,
        subtitle_track_fingerprint=_UNSET,
        subtitle_delay_ms=_UNSET,
    ):
        position_ms = _bounded_ms(position_ms, "position_ms")
        duration_ms = _bounded_ms(duration_ms, "duration_ms")
        threshold = float(completion_threshold)
        if not math.isfinite(threshold) or not 0.5 <= threshold <= 1.0:
            raise PlaybackHistoryError("completion_threshold is out of range")
        with self.catalog_store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM playback_history WHERE path_key=?",
                (str(path_key),),
            ).fetchone()
            if not row or int(row["revision"]) != int(revision):
                return {"accepted": False, "became_completed": False, "row": None}
            effective_duration = duration_ms or int(row["duration_ms"] or 0)
            effective_position = min(position_ms, effective_duration) if effective_duration else position_ms
            completed = bool(
                effective_duration > 0
                and (
                    force_complete
                    or effective_position / effective_duration >= threshold
                )
            )
            previous_completed = row["completed_at"] is not None
            completed_at = (
                row["completed_at"]
                if previous_completed
                else (max(0.0, float(self.clock())) if completed else None)
            )
            audio = (
                _fingerprint(audio_track_fingerprint)
                if audio_track_fingerprint is not _UNSET
                else row["audio_track_fingerprint"]
            )
            subtitle = (
                _fingerprint(subtitle_track_fingerprint)
                if subtitle_track_fingerprint is not _UNSET
                else row["subtitle_track_fingerprint"]
            )
            delay = (
                int(subtitle_delay_ms)
                if subtitle_delay_ms is not _UNSET
                else int(row["subtitle_delay_ms"] or 0)
            )
            if not -60 * 60 * 1000 <= delay <= 60 * 60 * 1000:
                raise PlaybackHistoryError("subtitle_delay_ms is out of range")
            connection.execute("""
                UPDATE playback_history
                SET position_ms=?, duration_ms=?, last_played_at=?, completed_at=?,
                    audio_track_fingerprint=?, subtitle_track_fingerprint=?,
                    subtitle_delay_ms=?
                WHERE path_key=? AND revision=?
            """, (
                effective_position,
                effective_duration,
                max(0.0, float(self.clock())),
                completed_at,
                audio,
                subtitle,
                delay,
                str(path_key),
                int(revision),
            ))
            updated = connection.execute(
                "SELECT * FROM playback_history WHERE path_key=?",
                (str(path_key),),
            ).fetchone()
            return {
                "accepted": True,
                "became_completed": bool(completed and not previous_completed),
                "row": _row_payload(updated),
            }

    def clear(self, path_key):
        with self.catalog_store.transaction() as connection:
            return bool(connection.execute(
                "DELETE FROM playback_history WHERE path_key=?",
                (str(path_key),),
            ).rowcount)

    def bind_movie_key(self, path_key, movie_key):
        with self.catalog_store.transaction() as connection:
            return bool(connection.execute(
                "UPDATE playback_history SET movie_key=? WHERE path_key=?",
                (str(movie_key or "").strip() or None, str(path_key)),
            ).rowcount)

    def rows_for_presentation(self, limit=200):
        connection = self.catalog_store.connect()
        try:
            rows = connection.execute("""
                SELECT history.*
                FROM playback_history AS history
                JOIN media_files AS media ON media.path_key=history.path_key
                ORDER BY history.last_played_at DESC, history.path_key
                LIMIT ?
            """, (max(1, min(int(limit), 500)),)).fetchall()
            return [_row_payload(row) for row in rows]
        finally:
            connection.close()


class PlaybackHistoryService:
    """Owns resume policy, event throttling, completion, and watched integration."""

    def __init__(
        self,
        history_store,
        player_config,
        curation_store_provider,
        *,
        monotonic_clock=None,
    ):
        self.history_store = history_store
        self.player_config = player_config
        self.curation_store_provider = curation_store_provider
        self.monotonic_clock = monotonic_clock or time.monotonic

    def begin_session(self, media, *, restart=False):
        config = self.player_config.storage_payload()
        row = self.history_store.begin_session(
            media["path_key"],
            media.get("movie_key"),
            restart=restart,
        )
        threshold = float(config["completion_threshold"])
        minimum_ms = int(config["minimum_resume_seconds"]) * 1000
        resumable = bool(
            config["resume_enabled"]
            and not restart
            and row["completed_at"] is None
            and row["position_ms"] >= minimum_ms
            and row["duration_ms"] > 0
            and row["position_ms"] / row["duration_ms"] < threshold
        )
        now = self.monotonic_clock()
        return {
            "media": dict(media),
            "revision": row["revision"],
            "start_position_ms": row["position_ms"] if resumable else 0,
            "latest_position_ms": row["position_ms"] if resumable else 0,
            "latest_duration_ms": row["duration_ms"],
            "last_event_position_ms": row["position_ms"] if resumable else 0,
            "last_event_at": now,
            "last_saved_at": now,
            "resume_choice_pending": resumable,
            "audio_track_fingerprint": row.get("audio_track_fingerprint"),
            "subtitle_track_fingerprint": row.get("subtitle_track_fingerprint"),
            "subtitle_delay_ms": row.get("subtitle_delay_ms", 0),
        }

    def handle_event(self, session, message):
        context = getattr(session, "playback_context", None)
        if not context:
            return
        message_type = message["type"]
        now = self.monotonic_clock()
        if message_type == "resume.choice":
            choice = message.get("choice")
            if choice == "restart":
                self.history_store.restart_session(
                    context["media"]["path_key"],
                    context["revision"],
                )
                context["latest_position_ms"] = 0
                context["last_event_position_ms"] = 0
            context["resume_choice_pending"] = False
            context["last_event_at"] = now
            context["last_saved_at"] = now
            return

        if message_type == "progress":
            position = int(message["position_ms"])
            duration = int(message["duration_ms"])
            elapsed_ms = max(0, int((now - context["last_event_at"]) * 1000))
            expected_delta = elapsed_ms + SEEK_JUMP_THRESHOLD_MS
            jumped = abs(position - context["last_event_position_ms"]) > expected_delta
            context["latest_position_ms"] = position
            context["latest_duration_ms"] = duration
            context["last_event_position_ms"] = position
            context["last_event_at"] = now
            if context["resume_choice_pending"]:
                return
            if (
                message["paused"]
                or jumped
                or now - context["last_saved_at"] >= PROGRESS_SAVE_INTERVAL_SECONDS
            ):
                self._persist(context)
            return

        if message_type == "tracks.changed":
            selected = {
                track.get("type"): track.get("fingerprint")
                for track in message.get("tracks", [])
                if track.get("selected")
            }
            context["audio_track_fingerprint"] = selected.get("audio")
            context["subtitle_track_fingerprint"] = (
                selected.get("sub") or "disabled"
            )
            if not context["resume_choice_pending"]:
                self._persist(context)
            return

        if message_type == "playback.settings":
            context["subtitle_delay_ms"] = int(message["subtitle_delay_ms"])
            if not context["resume_choice_pending"]:
                self._persist(context)
            return

        if message_type == "playback.state" and message.get("state") == "ended":
            if not context["resume_choice_pending"]:
                self._persist(context, force_complete=True)
            return

        if message_type in {"closing", "closed", "error"}:
            if not context["resume_choice_pending"]:
                self._persist(context)

    def _persist(self, context, *, force_complete=False):
        config = self.player_config.storage_payload()
        result = self.history_store.save(
            context["media"]["path_key"],
            context["revision"],
            position_ms=context["latest_position_ms"],
            duration_ms=context["latest_duration_ms"],
            completion_threshold=config["completion_threshold"],
            force_complete=force_complete,
            audio_track_fingerprint=context.get("audio_track_fingerprint"),
            subtitle_track_fingerprint=context.get("subtitle_track_fingerprint"),
            subtitle_delay_ms=context.get("subtitle_delay_ms"),
        )
        context["last_saved_at"] = self.monotonic_clock()
        if (
            result["accepted"]
            and result["row"].get("completed_at") is not None
            and config["auto_mark_completed_watched"]
        ):
            curation = self.curation_store_provider()
            movie = self._curation_movie(context["media"])
            if not curation.system_states_for_movie(movie)["watched"]:
                curation.set_system_list_state("watched", movie, True)
        return result

    @staticmethod
    def _curation_movie(media):
        return {
            "tmdb_id": str(media.get("tmdb_id") or ""),
            "imdb_id": str(media.get("imdb_id") or ""),
            "title": str(media.get("title") or ""),
            "year": str(media.get("year") or ""),
            "path": str(media.get("path") or ""),
            "poster_url": str(media.get("poster_reference") or ""),
            "release_date": str(media.get("release_date") or ""),
        }

    def clear(self, path_key):
        return self.history_store.clear(path_key)

    def continue_watching(self, limit=50):
        config = self.player_config.storage_payload()
        if not config["resume_enabled"]:
            return []
        minimum_ms = int(config["minimum_resume_seconds"]) * 1000
        threshold = float(config["completion_threshold"])
        grouped = {}
        for row in self.history_store.rows_for_presentation(limit=200):
            duration = row["duration_ms"]
            position = row["position_ms"]
            if (
                row.get("completed_at") is not None
                or duration <= 0
                or position < minimum_ms
                or position / duration >= threshold
            ):
                continue
            candidate = self.history_store.catalog_store.owned_movie_candidate(
                path_key=row["path_key"]
            )
            if not candidate or not Path(str(candidate.get("path") or "")).is_file():
                continue
            canonical = candidate.get("relational_canonical") or {}
            movie_key = str(canonical.get("movie_key") or row.get("movie_key") or "").strip()
            if movie_key != str(row.get("movie_key") or ""):
                self.history_store.bind_movie_key(row["path_key"], movie_key)
            movie = {
                "tmdb_id": str(canonical.get("tmdb_id") or candidate.get("tmdb_id") or ""),
                "imdb_id": str(canonical.get("imdb_id") or candidate.get("imdb_id") or ""),
                "title": str(
                    canonical.get("title")
                    or candidate.get("identity_title")
                    or candidate.get("parsed_title")
                    or Path(candidate["path"]).stem
                ),
                "year": str(
                    canonical.get("year")
                    or candidate.get("identity_year")
                    or candidate.get("parsed_year")
                    or ""
                ),
                "path": str(candidate["path"]),
                "poster_url": _safe_poster_reference(
                    canonical.get("poster_url") or canonical.get("poster_path") or ""
                ),
            }
            identity = movie_key or f"path:{row['path_key']}"
            if identity in grouped:
                continue
            grouped[identity] = {
                "path_key": row["path_key"],
                "movie_key": movie_key,
                "title": movie["title"][:512],
                "year": movie["year"][:16],
                "poster_url": movie["poster_url"],
                "position_ms": position,
                "duration_ms": duration,
                "progress": round(position / duration, 6),
                "remaining_seconds": max(0, int(math.ceil((duration - position) / 1000))),
                "last_played_at": float(row["last_played_at"]),
            }
            if len(grouped) >= max(1, min(int(limit), 100)):
                break
        return list(grouped.values())
