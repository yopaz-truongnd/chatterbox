from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from services.atomic_io import atomic_write_text


class TestAtomicIO(unittest.TestCase):
    def test_fsyncs_before_replace_and_directory_after(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.yaml"
            calls = []
            real_replace = os.replace

            with patch("services.atomic_io.os.fsync", side_effect=lambda _: calls.append("fsync")), patch(
                "services.atomic_io.os.replace",
                side_effect=lambda source, target: (calls.append("replace"), real_replace(source, target))[1],
            ):
                atomic_write_text(path, "version: 1\n")

            self.assertEqual(calls, ["fsync", "replace", "fsync"])
            self.assertEqual(path.read_text(encoding="utf-8"), "version: 1\n")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
