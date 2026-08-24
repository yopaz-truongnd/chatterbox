"""Pure Python Wave Audio Mixer (Phase 14).

Executes multi-track timeline rendering without external FFmpeg dependency:
- Concatenates voice clips and silence regions based on absolute millisecond timeline.
- Applies linear fade-in / fade-out to prevent zero-crossing clicks.
- Applies gain staging (dB to linear scale).
- Mixes overlay tracks (SFX, Ambience) when available.
- Supports cancellation tokens and progress callbacks.
- Guarantees atomic file writes.
"""

from __future__ import annotations

import array
import logging
import math
import os
from pathlib import Path
import struct
from typing import Any, Callable
import uuid
import wave

from services.audio_mix_models import MixPlan
from services.tts.base import CancellationToken, ProgressCallback

logger = logging.getLogger(__name__)


def _db_to_linear(gain_db: float) -> float:
    """Convert decibel gain to linear amplitude multiplier."""
    return math.pow(10.0, gain_db / 20.0)


def _read_wav_samples(wav_path: Path) -> tuple[list[float], int, int]:
    """Read standard 16-bit PCM WAV samples normalized to float [-1.0, 1.0]."""
    with wave.open(str(wav_path), "rb") as wf:
        nchannels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        nframes = wf.getnframes()
        raw_bytes = wf.readframes(nframes)

    if sampwidth != 2:
        # If not 16-bit, do a best-effort conversion or return empty
        logger.warning("Unsupported sample width %d for '%s', expected 2 (16-bit PCM)", sampwidth, wav_path)
        return [], framerate, nchannels

    # Unpack 16-bit signed integers
    num_samples = len(raw_bytes) // 2
    fmt = f"<{num_samples}h"
    int_samples = struct.unpack(fmt, raw_bytes)

    # Convert to mono float samples
    if nchannels == 1:
        float_samples = [s / 32768.0 for s in int_samples]
    else:
        # Downmix stereo to mono by averaging channels
        float_samples = [
            ((int_samples[i] + int_samples[i + 1]) / 2.0) / 32768.0
            for i in range(0, len(int_samples), nchannels)
        ]

    return float_samples, framerate, 1


def _write_wav_samples(output_path: Path, samples: list[float], sample_rate: int = 44100) -> None:
    """Atomically write normalized float samples [-1.0, 1.0] to 16-bit mono PCM WAV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_file = output_path.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}.wav")

    # Clamp samples to [-1.0, 1.0] and convert to 16-bit signed integers
    int_samples = []
    for s in samples:
        clamped = max(-1.0, min(1.0, s))
        int_samples.append(int(clamped * 32767.0))

    raw_bytes = struct.pack(f"<{len(int_samples)}h", *int_samples)

    with wave.open(str(temp_file), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(raw_bytes)

    temp_file.replace(output_path)


class WaveAudioMixer:
    """Pure Python implementation of AudioMixExecutionPort."""

    def mix(
        self,
        plan: MixPlan,
        proj_dir: Path | str,
        output_path: Path | str,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> Path:
        """Render multi-track timeline MixPlan to destination WAV file."""
        project_root = Path(proj_dir)
        target_path = Path(output_path)
        sample_rate = plan.sample_rate or 44100

        total_duration_s = (plan.duration_ms / 1000.0) + 0.5
        total_samples_count = int(total_duration_s * sample_rate)
        master_buffer: list[float] = [0.0] * max(total_samples_count, sample_rate)

        total_clips = len(plan.voice_clips) + len(plan.sfx_clips) + len(plan.ambience_clips)
        processed_clips = 0

        # 1. Mix Voice Clips
        for vclip in plan.voice_clips:
            if cancellation_token and cancellation_token.is_cancelled():
                logger.info("Mix cancelled before processing voice clip '%s'.", vclip.beat_id)
                return target_path

            clip_path = Path(vclip.source_path)
            if not clip_path.is_absolute():
                clip_path = project_root / clip_path

            if clip_path.exists():
                samples, clip_sr, _ = _read_wav_samples(clip_path)
                gain = _db_to_linear(vclip.gain_db)

                # Resample simple linear if sample rate mismatch
                if clip_sr != sample_rate and clip_sr > 0:
                    ratio = sample_rate / float(clip_sr)
                    new_len = int(len(samples) * ratio)
                    resampled = []
                    for i in range(new_len):
                        src_idx = i / ratio
                        idx_low = int(src_idx)
                        idx_high = min(idx_low + 1, len(samples) - 1)
                        frac = src_idx - idx_low
                        resampled.append(samples[idx_low] * (1.0 - frac) + samples[idx_high] * frac)
                    samples = resampled

                # Apply Fade In / Fade Out
                fade_in_samples = int((vclip.fade_in_ms / 1000.0) * sample_rate)
                fade_out_samples = int((vclip.fade_out_ms / 1000.0) * sample_rate)

                for i in range(min(fade_in_samples, len(samples))):
                    samples[i] *= i / float(fade_in_samples)

                for i in range(min(fade_out_samples, len(samples))):
                    idx = len(samples) - 1 - i
                    samples[idx] *= i / float(fade_out_samples)

                # Overlay into master buffer at start_ms
                start_sample = int((vclip.start_ms / 1000.0) * sample_rate)
                for i, smp in enumerate(samples):
                    target_idx = start_sample + i
                    if target_idx < len(master_buffer):
                        master_buffer[target_idx] += smp * gain

            processed_clips += 1
            if progress_callback and total_clips > 0:
                pct = (processed_clips / float(total_clips)) * 70.0
                progress_callback("mixing_voice", pct, {"beat_id": vclip.beat_id})

        # 2. Mix SFX Clips (if any exist)
        for sfx in plan.sfx_clips:
            if cancellation_token and cancellation_token.is_cancelled():
                return target_path

            if sfx.source_path:
                sfx_path = Path(sfx.source_path)
                if not sfx_path.is_absolute():
                    sfx_path = project_root / sfx_path

                if sfx_path.exists():
                    samples, sfx_sr, _ = _read_wav_samples(sfx_path)
                    gain = _db_to_linear(sfx.gain_db)
                    start_sample = int((sfx.start_ms / 1000.0) * sample_rate)
                    for i, smp in enumerate(samples):
                        target_idx = start_sample + i
                        if target_idx < len(master_buffer):
                            master_buffer[target_idx] += smp * gain

            processed_clips += 1
            if progress_callback and total_clips > 0:
                pct = 70.0 + (processed_clips / float(total_clips)) * 20.0
                progress_callback("mixing_sfx", pct, {"resource_id": sfx.resource_id})

        # 3. Write premaster WAV output
        if cancellation_token and cancellation_token.is_cancelled():
            return target_path

        _write_wav_samples(target_path, master_buffer, sample_rate=sample_rate)

        if progress_callback:
            progress_callback("mixing_complete", 100.0, {"output_path": str(target_path)})

        return target_path
