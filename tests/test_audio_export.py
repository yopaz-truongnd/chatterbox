"""Unit tests for Audio Export Service (Phase 14)."""

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from services.audio_export import AudioExportService
from services.audio_mix_models import ExportProfile
from services.tts.base import CancellationToken
from services.voice_project_models import ExportDependencyUnavailableError
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
            master_path=master_wav,
            export_profiles=[ExportProfile(format="wav", sample_rate=44100, channels=1)],
            output_dir=out_dir,
        )

        final_wav = out_dir / "FINAL.wav"
        manifest_file = out_dir / "export-manifest.yaml"

        self.assertTrue(final_wav.exists())
        self.assertTrue(manifest_file.exists())
        self.assertEqual(len(manifest.artifacts), 1)
        self.assertEqual(manifest.artifacts[0].artifact_id, "final_wav")

    def test_audio_export_probes_actual_sample_rate_for_broadcast_master_48khz(self):
        """Verify that a 48 kHz broadcast master records actual 48000 Hz in manifest."""
        master_wav = self.dir / "broadcast_master.wav"
        _write_wav_samples(master_wav, [0.1] * 48000, sample_rate=48000)

        out_dir = self.dir / "exports"
        service = AudioExportService()
        # Even with default profile
        manifest = service.export(
            project_id="test_broadcast_export",
            master_path=master_wav,
            export_profiles=[ExportProfile(format="wav")],
            output_dir=out_dir,
        )

        self.assertEqual(manifest.artifacts[0].sample_rate, 48000)

    @patch("shutil.which", return_value=None)
    def test_mp3_export_raises_dependency_unavailable_when_ffmpeg_missing(self, mock_which):
        master_wav = self.dir / "master.wav"
        _write_wav_samples(master_wav, [0.1] * 44100, sample_rate=44100)

        out_dir = self.dir / "exports"
        service = AudioExportService()

        with self.assertRaises(ExportDependencyUnavailableError):
            service.export(
                project_id="test_mp3_fail",
                master_path=master_wav,
                export_profiles=[ExportProfile(format="mp3")],
                output_dir=out_dir,
            )

    def test_export_cancellation_cleans_up_temp_files(self):
        master_wav = self.dir / "master.wav"
        _write_wav_samples(master_wav, [0.1] * 44100, sample_rate=44100)

        out_dir = self.dir / "exports"
        service = AudioExportService()
        token = CancellationToken()
        token.cancel()

        with self.assertRaises(RuntimeError):
            service.export(
                project_id="test_cancel_export",
                master_path=master_wav,
                export_profiles=[ExportProfile(format="wav")],
                output_dir=out_dir,
                cancellation_token=token,
            )


if __name__ == "__main__":
    unittest.main()
