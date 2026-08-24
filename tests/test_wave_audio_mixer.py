"""Unit tests for Pure Python Wave Audio Mixer (Phase 14)."""

import math
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from services.audio_mix_models import MixPlan, VoiceClip
from services.tts.base import CancellationToken
from services.wave_audio_mixer import WaveAudioMixer, _read_wav_samples, _write_wav_samples


def _generate_tone_wav(path: Path, freq: float = 440.0, duration_s: float = 0.5, sample_rate: int = 44100):
    """Generate a clean test sine wave WAV fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(duration_s * sample_rate)
    samples = [0.5 * math.sin(2.0 * math.pi * freq * (i / float(sample_rate))) for i in range(num_samples)]
    _write_wav_samples(path, samples, sample_rate=sample_rate)


class TestWaveAudioMixer(unittest.TestCase):
    """Test multi-track timeline wave rendering."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.proj_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_wave_audio_mixer_renders_multi_clip_timeline(self):
        clip1_path = self.proj_dir / "clip1.wav"
        clip2_path = self.proj_dir / "clip2.wav"
        _generate_tone_wav(clip1_path, freq=440.0, duration_s=0.5)
        _generate_tone_wav(clip2_path, freq=880.0, duration_s=0.5)

        plan = MixPlan(
            project_id="test_mixer",
            duration_ms=1200.0,
            sample_rate=44100,
            channels=1,
            voice_clips=[
                VoiceClip(
                    beat_id="B01",
                    selected_attempt=1,
                    source_path="clip1.wav",
                    start_ms=0.0,
                    duration_ms=500.0,
                ),
                VoiceClip(
                    beat_id="B02",
                    selected_attempt=1,
                    source_path="clip2.wav",
                    start_ms=700.0,
                    duration_ms=500.0,
                ),
            ],
        )

        output_path = self.proj_dir / "premaster.wav"
        mixer = WaveAudioMixer()
        res = mixer.mix(plan=plan, proj_dir=self.proj_dir, output_path=output_path)

        self.assertTrue(output_path.exists())
        self.assertEqual(res, output_path)

        # Inspect resulting WAV file header
        with wave.open(str(output_path), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), 44100)
            self.assertGreater(wf.getnframes(), 44100)  # > 1.0s

    def test_wave_mixer_respects_cancellation_token(self):
        clip_path = self.proj_dir / "clip.wav"
        _generate_tone_wav(clip_path, duration_s=0.2)

        plan = MixPlan(
            project_id="cancel_mixer",
            duration_ms=500.0,
            voice_clips=[
                VoiceClip(beat_id="B01", selected_attempt=1, source_path="clip.wav", start_ms=0, duration_ms=200)
            ],
        )
        token = CancellationToken()
        token.cancel()

        mixer = WaveAudioMixer()
        output_path = self.proj_dir / "cancelled.wav"
        mixer.mix(plan=plan, proj_dir=self.proj_dir, output_path=output_path, cancellation_token=token)

        # Should exit without creating output
        self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
