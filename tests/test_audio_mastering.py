"""Unit tests for Audio Mastering Service (Phase 14)."""

import math
from pathlib import Path
import tempfile
import unittest
import wave

from services.audio_mastering import AudioMasteringService, load_mastering_profile
from services.audio_mix_models import MasteringProfile
from services.wave_audio_mixer import _write_wav_samples, _read_wav_samples


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

    def test_load_mastering_profiles_from_yaml(self):
        p_story = load_mastering_profile("storytelling")
        self.assertEqual(p_story.target_lufs, -16.0)
        self.assertEqual(p_story.true_peak_dbtp, -1.0)

        p_pod = load_mastering_profile("podcast")
        self.assertEqual(p_pod.target_lufs, -19.0)
        self.assertEqual(p_pod.true_peak_dbtp, -1.5)

        p_broad = load_mastering_profile("broadcast")
        self.assertEqual(p_broad.target_lufs, -23.0)
        self.assertEqual(p_broad.sample_rate, 48000)

        with self.assertRaises(ValueError):
            load_mastering_profile("unknown_random_profile")

    def test_audio_mastering_applies_loudness_gain_and_limiting(self):
        input_wav = self.dir / "premaster.wav"
        output_wav = self.dir / "master.wav"
        _generate_quiet_wav(input_wav)

        service = AudioMasteringService()
        prof = load_mastering_profile("storytelling")
        res = service.master(input_wav_path=input_wav, output_wav_path=output_wav, profile=prof)

        self.assertTrue(output_wav.exists())
        self.assertGreater(res["output_lufs"], res["input_lufs"])
        self.assertLessEqual(res["true_peak_dbtp"], -1.0 + 0.01)

        # Verify output WAV is readable
        with wave.open(str(output_wav), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)

    def test_limiter_strictly_enforces_ceiling_on_hot_signal(self):
        input_wav = self.dir / "hot_premaster.wav"
        output_wav = self.dir / "limited_master.wav"
        # Generate loud full-scale audio
        path = Path(input_wav)
        path.parent.mkdir(parents=True, exist_ok=True)
        samples = [0.99 * math.sin(2.0 * math.pi * 1000.0 * (i / 44100.0)) for i in range(4410)]
        _write_wav_samples(path, samples, sample_rate=44100)

        service = AudioMasteringService()
        prof = MasteringProfile(name="test_limiter", target_lufs=-10.0, true_peak_dbtp=-2.0)
        max_allowed_linear = math.pow(10.0, -2.0 / 20.0)  # ~0.7943

        res = service.master(input_wav_path=input_wav, output_wav_path=output_wav, profile=prof)

        mastered_samples, _, _ = _read_wav_samples(output_wav)
        max_sample = max(abs(s) for s in mastered_samples)
        self.assertLessEqual(max_sample, max_allowed_linear + 1e-4)


if __name__ == "__main__":
    unittest.main()
