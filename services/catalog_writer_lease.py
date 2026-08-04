"""Process-wide ownership guard for a Cinema Paradiso catalog.

The zero-byte lease file is only a stable rendezvous name. Ownership is the
exclusive operating-system handle, so a crash releases ownership without a
stale-lock cleanup protocol.
"""

import atexit
import hashlib
import os
from pathlib import Path


class CatalogWriterLeaseError(RuntimeError):
    """Raised when another backend already owns the catalog writer lease."""


def catalog_lease_path(database_path, lease_root=None):
    database_path = Path(database_path).resolve()
    digest = hashlib.blake2b(
        str(database_path).encode("utf-8", errors="surrogatepass"),
        digest_size=12,
    ).hexdigest()
    root = Path(lease_root).resolve() if lease_root else database_path.parent
    return root / f"catalog-writer-{digest}.lock"


class CatalogWriterLease:
    """Hold one exclusive, crash-released handle for a resolved catalog path."""

    def __init__(self, database_path, lease_root=None):
        self.database_path = Path(database_path).resolve()
        self.path = catalog_lease_path(self.database_path, lease_root=lease_root)
        self._handle = None
        self._fd = None
        self._closed = False

    @property
    def acquired(self):
        return self._handle is not None or self._fd is not None

    def acquire(self):
        if self.acquired:
            return self
        if self._closed:
            raise CatalogWriterLeaseError("A closed catalog writer lease cannot be reacquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            self._acquire_windows()
        else:
            self._acquire_posix()
        atexit.register(self.close)
        return self

    def _acquire_windows(self):
        import ctypes
        from ctypes import wintypes

        create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
        create_file.argtypes = (
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        )
        create_file.restype = wintypes.HANDLE
        handle = create_file(
            str(self.path),
            0x80000000 | 0x40000000,  # GENERIC_READ | GENERIC_WRITE
            0,  # no sharing
            None,
            4,  # OPEN_ALWAYS
            0x80,  # FILE_ATTRIBUTE_NORMAL
            None,
        )
        invalid_handle = ctypes.c_void_p(-1).value
        if handle == invalid_handle:
            error_code = ctypes.get_last_error()
            raise CatalogWriterLeaseError(
                f"Catalog writer already owned or unavailable: {self.database_path} "
                f"(Windows error {error_code})"
            )
        self._handle = handle

    def _acquire_posix(self):
        import fcntl

        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            raise CatalogWriterLeaseError(
                f"Catalog writer already owned or unavailable: {self.database_path}"
            ) from error
        self._fd = fd

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._handle is not None:
            import ctypes
            from ctypes import wintypes

            close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle.restype = wintypes.BOOL
            close_handle(self._handle)
            self._handle = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, _exc_type, _exc_value, _traceback):
        self.close()

