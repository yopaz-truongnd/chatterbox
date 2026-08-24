"""Unit tests for Audio Export Service (Phase 14)."""

from pathlib import Path
import tempfile
import unittest
import wave

from services.audio_export import AudioExportService
from services.audio_mix_models import ExportProfile
from services.wave_audio_mixer import _write_wav_samples


class TestAudioExport(unittest.TestCase):
    """Test packaging master audio to FINAL deliverables."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_audio_export_generates_final_wav_and_manifest(self):
        master_wav = self.dir / "master.wav"
        _write_wav_samples(master_wav, [0.1] * 44100, sample_rate=44100)

        out_dir = self.dir / "exports"
        service = AudioExportService()
        manifest = service.export(
            project_id="test_export",
            master_wav_path=master_wav,
            export_profiles=[ExportProfile(format="wav", sample_rate=44100, channels=1)],
            output_dir=out_dir,
        )

        final_wav = out_dir / "FINAL.wav"
        manifest_file = out_dir / "export-manifest.yaml"

        self.assertTrue(final_wav.exists())
        self.assertTrue(manifest_file.exists())
        self.assertEqual(len(manifest.artifacts), 1)
        self.assertEqual(manifest.artifacts[0].artifact_id, "final_wav")
        self.assertGreater(len(manifest.source_master_sha256), 0)


if __name__ == "__main__":
    unittest.main()
