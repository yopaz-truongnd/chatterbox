"""Security regression tests for Asset Library (Phase 18).

Tests:
  1. Path traversal (..) is rejected.
  2. Absolute path outside permitted roots is rejected.
  3. Symlink pointing outside permitted roots is rejected.
  4. Duplicate asset by SHA-256 is detected and not re-registered.
  5. Extension spoofing (e.g. .wav file containing text) is rejected.
"""

from pathlib import Path
import tempfile
import unittest
import wave

from services.asset_library_models import AssetCategory
from services.asset_library_service import AssetLibraryService
from services.asset_library_store import AssetLibraryStore


def _make_dummy_wav(path: Path, duration_s: float = 0.5, sample_rate: int = 22050):
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * n_frames)


class TestAssetSecurity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.tmp.name)
        self.permitted_root = self.root / "assets"
        self.permitted_root.mkdir(parents=True, exist_ok=True)
        self.outside_root = self.root / "outside"
        self.outside_root.mkdir(parents=True, exist_ok=True)

        self.store = AssetLibraryStore(index_path=self.permitted_root / "library-index.yaml")
        self.service = AssetLibraryService(
            store=self.store,
            permitted_roots=[self.permitted_root],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_path_traversal_dotdot_rejected(self):
        res = self.service.ingest_file(
            "assets/../outside/evil.wav",
            category=AssetCategory.SFX,
        )
        self.assertEqual(res.status, "rejected")
        self.assertIn("Path traversal", res.reason or "")

    def test_path_outside_permitted_root_rejected(self):
        evil_file = self.outside_root / "secret.wav"
        _make_dummy_wav(evil_file)
        res = self.service.ingest_file(
            evil_file,
            category=AssetCategory.AMBIENCE,
        )
        self.assertEqual(res.status, "rejected")
        self.assertIn("outside all permitted roots", res.reason or "")

    def test_symlink_escape_rejected(self):
        evil_file = self.outside_root / "target.wav"
        _make_dummy_wav(evil_file)

        symlink_file = self.permitted_root / "link_to_evil.wav"
        try:
            symlink_file.symlink_to(evil_file)
        except OSError:
            self.skipTest("Symlinks not supported on this filesystem")

        res = self.service.ingest_file(
            symlink_file,
            category=AssetCategory.SFX,
        )
        self.assertEqual(res.status, "rejected")
        self.assertIn("outside", res.reason or "")

    def test_duplicate_sha256_returns_existing_asset(self):
        wav_file = self.permitted_root / "sample.wav"
        _make_dummy_wav(wav_file)

        res1 = self.service.ingest_file(wav_file, category=AssetCategory.SFX, metadata={"intents": ["thunder"]})
        self.assertEqual(res1.status, "registered")

        # Ingest identical file again
        res2 = self.service.ingest_file(wav_file, category=AssetCategory.SFX, metadata={"intents": ["thunder"]})
        self.assertEqual(res2.status, "duplicate")
        self.assertEqual(res2.existing_asset_id, res1.asset_id)

        # Confirm store only has 1 asset
        assets = self.store.list_assets()
        self.assertEqual(len(assets), 1)

    def test_extension_spoofing_rejected_by_magic_bytes(self):
        fake_wav = self.permitted_root / "fake.wav"
        fake_wav.write_text("This is plain text, not real audio content!")

        res = self.service.ingest_file(fake_wav, category=AssetCategory.SFX)
        self.assertEqual(res.status, "rejected")
        self.assertIn("format", res.reason or "")
