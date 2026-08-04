import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from services.catalog_repository import CatalogRepository
from services.catalog_writer_lease import (
    CatalogWriterLease,
    CatalogWriterLeaseError,
    catalog_lease_path,
)


def _declared_test_root():
    if os.environ.get("CP_TEST_MODE") != "1":
        raise RuntimeError("Gate 2 tests require CP_TEST_MODE=1")
    root = Path(os.environ["CP_TEST_ROOT"]).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if root != temporary and temporary not in root.parents:
        raise RuntimeError("CP_TEST_ROOT must resolve inside the system temporary directory")
    return root


class CatalogWriterLeaseTest(unittest.TestCase):
    def setUp(self):
        self.test_root = _declared_test_root()
        self.workspace = tempfile.TemporaryDirectory(dir=self.test_root)
        self.root = Path(self.workspace.name)

    def tearDown(self):
        self.workspace.cleanup()

    def test_catalog_path_hashes_to_stable_distinct_lease_names(self):
        first = catalog_lease_path(self.root / "first.sqlite", self.root / "leases")
        repeated = catalog_lease_path(self.root / "first.sqlite", self.root / "leases")
        second = catalog_lease_path(self.root / "second.sqlite", self.root / "leases")
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, second)
        self.assertEqual(first.parent, self.root / "leases")

    def test_second_writer_fails_closed_and_release_allows_reacquire(self):
        database = self.root / "catalog.sqlite"
        lease_root = self.root / "leases"
        first = CatalogWriterLease(database, lease_root).acquire()
        second = CatalogWriterLease(database, lease_root)
        try:
            with self.assertRaises(CatalogWriterLeaseError):
                second.acquire()
        finally:
            first.close()
        second.acquire()
        self.assertTrue(second.acquired)
        second.close()

    def test_other_process_cannot_acquire_owned_catalog(self):
        database = self.root / "catalog.sqlite"
        lease_root = self.root / "leases"
        lease = CatalogWriterLease(database, lease_root).acquire()
        script = (
            "import sys;"
            "from services.catalog_writer_lease import CatalogWriterLease,CatalogWriterLeaseError;"
            "lease=CatalogWriterLease(sys.argv[1],sys.argv[2]);"
            "\ntry: lease.acquire()"
            "\nexcept CatalogWriterLeaseError: raise SystemExit(23)"
            "\nraise SystemExit(0)"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", script, str(database), str(lease_root)],
                cwd=Path(__file__).resolve().parents[1],
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        finally:
            lease.close()
        self.assertEqual(result.returncode, 23, result.stderr)

    def test_process_crash_releases_operating_system_handle(self):
        database = self.root / "catalog.sqlite"
        lease_root = self.root / "leases"
        script = (
            "import os,sys;"
            "from services.catalog_writer_lease import CatalogWriterLease;"
            "CatalogWriterLease(sys.argv[1],sys.argv[2]).acquire();"
            "os._exit(0)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(database), str(lease_root)],
            cwd=Path(__file__).resolve().parents[1],
            env=os.environ.copy(),
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        lease = CatalogWriterLease(database, lease_root).acquire()
        self.assertTrue(lease.acquired)
        lease.close()

    def test_repository_transaction_commits_and_rolls_back_atomically(self):
        repository = CatalogRepository(
            self.root / "user-data",
            database_path=self.root / "catalog.sqlite",
            export_delay=0,
        )
        with repository.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO catalog_meta(key,value) VALUES('gate2_probe','committed')"
            )
        self.assertEqual(repository.catalog_meta("gate2_probe"), "committed")
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with repository.transaction() as connection:
                connection.execute(
                    "UPDATE catalog_meta SET value='mutated' WHERE key='gate2_probe'"
                )
                raise RuntimeError("rollback")
        self.assertEqual(repository.catalog_meta("gate2_probe"), "committed")
        repository.close(flush=False)


if __name__ == "__main__":
    unittest.main()

