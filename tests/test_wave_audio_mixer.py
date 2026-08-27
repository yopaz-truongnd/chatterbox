"""Unit tests for Pure Python Wave Audio Mixer (Phase 14)."""

import math
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from services.audio_mix_models import AmbienceClip, DuckingRule, MixPlan, SFXClip, VoiceClip
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

    def test_wave_audio_mixer_mixes_voice_ambience_and_sfx_with_ducking(self):
        # 1. Voice Tone: 440 Hz from 500ms to 1000ms
        voice_path = self.proj_dir / "voice_440.wav"
        _generate_tone_wav(voice_path, freq=440.0, duration_s=0.5)

        # 2. Ambience Tone: 110 Hz spanning entire 2000ms
        amb_path = self.proj_dir / "amb_110.wav"
        _generate_tone_wav(amb_path, freq=110.0, duration_s=1.0)

        # 3. SFX Tone: 880 Hz at 1200ms
        sfx_path = self.proj_dir / "sfx_880.wav"
        _generate_tone_wav(sfx_path, freq=880.0, duration_s=0.3)

        plan = MixPlan(
            project_id="test_full_mix",
            duration_ms=2000.0,
            sample_rate=44100,
            voice_clips=[
                VoiceClip(beat_id="B01", selected_attempt=1, source_path="voice_440.wav", start_ms=500.0, duration_ms=500.0)
            ],
            ambience_clips=[
                AmbienceClip(resource_id="wind", source_path="amb_110.wav", start_ms=0.0, end_ms=2000.0, gain_db=-6.0, loop=True)
            ],
            sfx_clips=[
                SFXClip(resource_id="bell", source_path="sfx_880.wav", beat_id="B01", start_ms=1200.0, duration_ms=300.0, gain_db=-3.0)
            ],
            ducking_rules=[
                DuckingRule(target_track="ambience", duck_gain_db=-18.0, attack_ms=50.0, release_ms=100.0)
            ],
        )

        output_path = self.proj_dir / "full_premaster.wav"
        mixer = WaveAudioMixer()
        mixer.mix(plan=plan, proj_dir=self.proj_dir, output_path=output_path)

        self.assertTrue(output_path.exists())
        samples, sr, ch = _read_wav_samples(output_path)
        self.assertGreater(len(samples), 44100 * 2)

        # Window at 100ms-300ms (only ambience): non-zero energy
        amb_window = [abs(s) for s in samples[int(0.1 * sr):int(0.3 * sr)]]
        self.assertGreater(max(amb_window), 0.05)

        # Window at 600ms-900ms (voice + ducked ambience): voice tone dominant
        voice_window = [abs(s) for s in samples[int(0.6 * sr):int(0.9 * sr)]]
        self.assertGreater(max(voice_window), 0.1)

        # Window at 1250ms-1400ms (sfx + ambience): sfx active
        sfx_window = [abs(s) for s in samples[int(1.25 * sr):int(1.4 * sr)]]
        self.assertGreater(max(sfx_window), 0.05)

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
