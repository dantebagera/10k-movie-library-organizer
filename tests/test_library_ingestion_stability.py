import os
import tempfile
import unittest
from pathlib import Path

from services.library_ingestion import file_copy_is_stable, file_is_readable


class LibraryIngestionStabilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("CP_TEST_MODE") != "1":
            raise RuntimeError("Gate 2 tests require CP_TEST_MODE=1")
        root = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if root != temporary and temporary not in root.parents:
            raise RuntimeError("CP_TEST_ROOT must be inside system temporary storage")

    def test_last_write_must_be_at_least_exactly_fifteen_seconds_old(self):
        facts = {"size": 10, "modified_time": 100}
        self.assertFalse(file_copy_is_stable(facts, now=114.999, stability_seconds=15))
        self.assertTrue(file_copy_is_stable(facts, now=115, stability_seconds=15))

    def test_unchanged_observation_must_span_exactly_fifteen_seconds(self):
        facts = {"size": 10, "modified_time": 210}
        previous = {
            "observed_size": 10,
            "observed_modified_time": 210,
            "observed_at": 200,
        }
        self.assertFalse(
            file_copy_is_stable(facts, previous, now=214.999, stability_seconds=15)
        )
        self.assertTrue(
            file_copy_is_stable(facts, previous, now=215, stability_seconds=15)
        )

    def test_size_or_modified_time_change_resets_stability(self):
        previous = {
            "observed_size": 9,
            "observed_modified_time": 100,
            "observed_at": 200,
        }
        self.assertFalse(
            file_copy_is_stable(
                {"size": 10, "modified_time": 201},
                previous,
                now=214,
                stability_seconds=15,
            )
        )

    def test_readable_check_rejects_a_share_violation(self):
        from unittest.mock import mock_open, patch

        with patch("builtins.open", side_effect=PermissionError("shared")):
            self.assertFalse(file_is_readable("locked.mkv"))
        with patch("builtins.open", mock_open(read_data=b"x")):
            self.assertTrue(file_is_readable("ready.mkv"))


if __name__ == "__main__":
    unittest.main()
