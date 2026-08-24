"""Unit tests for Audio Mastering Service (Phase 14)."""

import math
from pathlib import Path
import tempfile
import unittest
import wave

from services.audio_mastering import AudioMasteringService
from services.audio_mix_models import MasteringProfile
from services.wave_audio_mixer import _write_wav_samples


def _generate_quiet_wav(path: Path, duration_s: float = 0.5, sample_rate: int = 44100):
    """Generate quiet audio fixture to verify loudness gain staging."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_s * sample_rate)
    samples = [0.05 * math.sin(2.0 * math.pi * 440.0 * (i / float(sample_rate))) for i in range(num_samples)]
    _write_wav_samples(path, samples, sample_rate=sample_rate)


class TestAudioMastering(unittest.TestCase):
    """Test loudness normalization and true peak limiting."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_audio_mastering_applies_loudness_gain_and_limiting(self):
        input_wav = self.dir / "premaster.wav"
        output_wav = self.dir / "master.wav"
        _generate_quiet_wav(input_wav)

        service = AudioMasteringService()
        prof = MasteringProfile(name="storytelling", target_lufs=-16.0, true_peak_dbtp=-1.0)
        res = service.master(input_wav_path=input_wav, output_wav_path=output_wav, profile=prof)

        self.assertTrue(output_wav.exists())
        self.assertGreater(res["output_lufs"], res["input_lufs"])
        self.assertLessEqual(res["true_peak_dbtp"], -0.9)  # Limiter kept below target peak

        # Verify output WAV is readable
        with wave.open(str(output_wav), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)


if __name__ == "__main__":
    unittest.main()
