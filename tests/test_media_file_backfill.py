import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.catalog_repository import CatalogRepository
from services.media_file_backfill import run_file_facts_backfill
from services.media_file_facts import MediaFileFacts, probe_media_file


def successful_facts(path, *, width=1800, height=960, codec="AVC", bit_depth=8):
    stat_result = os.stat(path)
    return MediaFileFacts(
        video_width=width,
        video_height=height,
        video_codec=codec,
        video_bit_depth=bit_depth,
        duration_ms=100_000,
        audio_codec="AAC",
        audio_channels=2,
        filename_quality_claim="1080p",
        quality_class="1080p",
        quality_source="measured",
        quality_nonstandard=(width, height) != (1920, 1080),
        probe_status="ok",
        probed_at=100,
        probe_size=stat_result.st_size,
        probe_modified_time=stat_result.st_mtime,
    )


class MediaFileBackfillTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.movies = self.root / "movies"
        self.movies.mkdir()
        self.repository = CatalogRepository(
            self.root / "user-data",
            database_path=self.root / "catalog.sqlite",
            export_delay=0,
        )

    def tearDown(self):
        self.repository.close(flush=False)
        self.temporary.cleanup()

    def seed(self, count=5):
        records = {}
        paths = []
        for index in range(count):
            path = self.movies / f"Movie.{index}.1080p.mkv"
            path.write_bytes(f"movie-{index}".encode())
            stat_result = path.stat()
            key = os.path.normcase(os.path.normpath(str(path)))
            records[key] = {
                "path": str(path),
                "filename": path.name,
                "library_root": str(self.movies),
                "size": stat_result.st_size,
                "modified_time": stat_result.st_mtime,
                "resolution": "720p",
                "identity_status": "accepted",
                "metadata_status": "accepted",
                "metadata_accepted": True,
                "tmdb_id": str(1000 + index),
            }
            paths.append(path)
        self.repository.store.import_documents({
            "app_metadata/files.json": {"files": records},
            "app_metadata/tmdb_metadata.json": {"movies": {}},
            "app_metadata/plex_metadata.json": {"files": {}},
            "app_metadata/manual_matches.json": {"matches": {}},
            "user_lists.json": {"lists": []},
            "user_collections.json": {"overrides": {}},
            "followed_releases.json": {"movies": []},
        }, {})
        return paths

    def facts_digest(self):
        connection = self.repository.store.connect()
        try:
            return [
                tuple(row) for row in connection.execute("""
                    SELECT path_key, video_width, video_height, video_codec,
                           quality_class, probe_status, file_facts_version,
                           classifier_version, probe_size, probe_modified_time
                    FROM media_files ORDER BY path_key
                """)
            ]
        finally:
            connection.close()

    def test_bounded_batches_resume_and_second_pass_is_idempotent(self):
        self.seed(5)
        generation_start = self.repository.generation("media")
        first = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=successful_facts,
            batch_size=2,
            concurrency=2,
            max_batches=1,
        )
        self.assertEqual(first["status"], "paused")
        self.assertEqual(first["selected"], 2)
        self.assertEqual(first["changed"], 2)
        self.assertEqual(first["remaining"], 3)
        self.assertEqual(first["generation_end"], generation_start + 1)

        resumed = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=successful_facts,
            batch_size=2,
            concurrency=2,
        )
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["batches"], 2)
        self.assertEqual(resumed["changed"], 3)
        self.assertEqual(resumed["remaining"], 0)
        self.assertEqual(resumed["generation_end"], generation_start + 3)
        digest = self.facts_digest()

        second = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=lambda _path: self.fail("unchanged rows must not be probed"),
        )
        self.assertEqual(second["selected"], 0)
        self.assertEqual(second["changed"], 0)
        self.assertEqual(second["generation_end"], generation_start + 3)
        self.assertEqual(self.facts_digest(), digest)

    def test_failure_is_isolated_and_explicit_retry_can_complete_it(self):
        paths = self.seed(2)

        def first_probe(path):
            if Path(path) == paths[0]:
                stat_result = os.stat(path)
                return MediaFileFacts(
                    filename_quality_claim="1080p",
                    quality_class="1080p",
                    quality_source="filename_fallback",
                    probe_status="corrupt",
                    probe_error="parse_failed",
                    probe_size=stat_result.st_size,
                    probe_modified_time=stat_result.st_mtime,
                )
            return successful_facts(path)

        first = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=first_probe,
        )
        self.assertEqual(first["failures"], 1)
        self.assertEqual(first["remaining"], 0)
        connection = self.repository.store.connect()
        try:
            statuses = [
                row[0] for row in connection.execute(
                    "SELECT probe_status FROM media_files ORDER BY path_key"
                )
            ]
        finally:
            connection.close()
        self.assertEqual(statuses, ["corrupt", "ok"])

        retry = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=successful_facts,
            retry_failed=True,
        )
        self.assertEqual(retry["selected"], 1)
        self.assertEqual(retry["changed"], 1)
        self.assertEqual(retry["failures"], 0)

    def test_transient_failure_retains_valid_measurements_for_the_same_file(self):
        path = self.seed(1)[0]
        measured = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=lambda target: successful_facts(
                target,
                width=1800,
                height=960,
                codec="HEVC",
                bit_depth=10,
            ),
        )
        self.assertEqual(measured["changed"], 1)

        with self.repository.store.transaction() as connection:
            connection.execute(
                "UPDATE media_files SET classifier_version=0 WHERE path=?",
                (str(path),),
            )

        def temporary_failure(target):
            stat_result = os.stat(target)
            return MediaFileFacts(
                filename_quality_claim="1080p",
                quality_class="1080p",
                quality_source="filename_fallback",
                probe_status="mediainfo_unavailable",
                probe_error="mediainfo_unavailable",
                probe_size=stat_result.st_size,
                probe_modified_time=stat_result.st_mtime,
            )

        failed = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=temporary_failure,
        )
        self.assertEqual(failed["failures"], 1)
        connection = self.repository.store.connect()
        try:
            row = dict(connection.execute(
                "SELECT * FROM media_files WHERE path=?",
                (str(path),),
            ).fetchone())
        finally:
            connection.close()

        self.assertEqual(row["probe_status"], "mediainfo_unavailable")
        self.assertEqual(row["probe_error"], "mediainfo_unavailable")
        self.assertEqual(row["quality_source"], "last_measured_probe_failed")
        self.assertEqual((row["video_width"], row["video_height"]), (1800, 960))
        self.assertEqual((row["video_codec"], row["video_bit_depth"]), ("HEVC", 10))
        self.assertEqual(row["resolution"], "1080p")
        self.assertEqual(row["classifier_version"], 0)
        self.assertEqual(failed["remaining"], 1)

    def test_changed_file_during_probe_is_rejected_and_not_presented_as_measured(self):
        path = self.seed(1)[0]
        parsed = SimpleNamespace(tracks=[
            SimpleNamespace(
                track_type="Video",
                width=1920,
                height=1080,
                format="AVC",
                format_profile="High",
                bit_depth=8,
                bit_rate=1_000_000,
                frame_rate=24,
                duration=100_000,
                display_aspect_ratio=1.778,
                rotation=0,
                default="Yes",
            ),
        ])

        def parser(changing_path):
            with open(changing_path, "ab") as handle:
                handle.write(b"changed")
            return parsed

        report = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=lambda target: probe_media_file(target, parser=parser),
        )
        self.assertEqual(report["failures"], 1)
        connection = self.repository.store.connect()
        try:
            row = dict(connection.execute("SELECT * FROM media_files").fetchone())
        finally:
            connection.close()
        self.assertEqual(row["probe_status"], "file_changed")
        self.assertEqual(row["video_width"], 0)
        self.assertEqual(row["quality_source"], "filename_fallback")
        self.assertEqual(row["resolution"], "1080p")
        self.assertNotEqual(row["probe_size"], row["size"])

    def test_cancel_stops_after_a_committed_batch(self):
        self.seed(5)
        cancel = threading.Event()

        def progress(_report):
            cancel.set()

        report = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=successful_facts,
            batch_size=2,
            cancel_event=cancel,
            progress=progress,
        )
        self.assertEqual(report["status"], "cancelled")
        self.assertEqual(report["batches"], 1)
        self.assertEqual(report["changed"], 2)
        self.assertEqual(report["remaining"], 3)

    def test_outside_root_is_never_opened(self):
        path = self.seed(1)[0]
        report = run_file_facts_backfill(
            self.repository,
            [self.root / "different-root"],
            probe=lambda _path: self.fail("outside root must not be probed"),
        )
        self.assertEqual(report["failures"], 1)
        self.assertEqual(report["failure_summary"][0]["error"], "outside_library_root")
        self.assertNotIn(str(path), str(report["failure_summary"]))

    def test_requested_concurrency_is_capped_at_four_workers(self):
        self.seed(8)
        lock = threading.Lock()
        active = 0
        maximum = 0

        def bounded_probe(path):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.01)
                return successful_facts(path)
            finally:
                with lock:
                    active -= 1

        report = run_file_facts_backfill(
            self.repository,
            [self.movies],
            probe=bounded_probe,
            batch_size=8,
            concurrency=99,
        )

        self.assertEqual(report["concurrency"], 4)
        self.assertEqual(report["changed"], 8)
        self.assertLessEqual(maximum, 4)


if __name__ == "__main__":
    unittest.main()
