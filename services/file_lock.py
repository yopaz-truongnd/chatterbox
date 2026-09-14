"""Cross-platform advisory file locks for durable local stores."""

from __future__ import annotations

from contextlib import contextmanager
import os
from typing import IO, Iterator


if os.name == "nt":  # pragma: no cover - exercised on Windows hosts.
    import msvcrt
else:  # pragma: no cover - exercised on POSIX hosts.
    import fcntl


@contextmanager
def exclusive_file_lock(handle: IO[str]) -> Iterator[None]:
    """Hold an exclusive, cross-process advisory lock for an open lock file.

    ``fcntl.flock`` is unavailable on Windows.  ``msvcrt.locking`` locks a
    byte range instead, so ensure the lock file has a first byte before
    acquiring the equivalent one-byte exclusive lock.
    """
    if os.name == "nt":
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write("\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
