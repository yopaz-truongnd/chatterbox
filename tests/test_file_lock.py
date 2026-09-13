from pathlib import Path
import tempfile
import unittest

from services.file_lock import exclusive_file_lock


class TestExclusiveFileLock(unittest.TestCase):
    def test_creates_and_releases_a_cross_platform_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "store.lock"
            with open(lock_path, "a+", encoding="utf-8") as handle:
                with exclusive_file_lock(handle):
                    handle.seek(0)
                    self.assertEqual(handle.read(1), "\0")

            with open(lock_path, "a+", encoding="utf-8") as handle:
                with exclusive_file_lock(handle):
                    self.assertTrue(lock_path.exists())
