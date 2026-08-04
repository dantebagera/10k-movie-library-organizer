import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class LibraryIngestionApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("CP_TEST_MODE") != "1":
            raise RuntimeError("Gate 2 tests require CP_TEST_MODE=1")
        root = Path(os.environ["CP_TEST_ROOT"]).resolve()
        temporary = Path(tempfile.gettempdir()).resolve()
        if root != temporary and temporary not in root.parents:
            raise RuntimeError("CP_TEST_ROOT must resolve inside system temp")

    def test_existing_reconcile_get_contract_remains_status_only(self):
        expected = {"status": "idle", "catalog_generation": 3}
        with patch("app._library_reconcile_status", return_value=expected), patch(
            "app._start_library_reconcile"
        ) as start:
            response = app.app.test_client().get("/api/library/reconcile")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        start.assert_not_called()

    def test_existing_reconcile_post_still_uses_explicit_full_caller(self):
        expected = {"status": "running", "reason": "explicit"}
        with patch("app._start_library_reconcile", return_value=expected) as start:
            response = app.app.test_client().post("/api/library/reconcile")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), expected)
        start.assert_called_once_with(force=True)


if __name__ == "__main__":
    unittest.main()

