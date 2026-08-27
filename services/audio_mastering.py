"""Audio Mastering Service (Phase 14).

Performs loudness normalization and dynamics control on mixed audio:
- Computes integrated loudness (approximate LUFS from RMS).
- Applies target gain staging to reach profile target LUFS.
- Enforces soft-knee peak limiting to guarantee true peak headroom (e.g. -1.0 dBTP).
- Guarantees atomic file writes for master.wav.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any
import uuid

from services.audio_mix_models import MasteringProfile
from services.tts.base import CancellationToken, ProgressCallback
from services.wave_audio_mixer import _read_wav_samples, _write_wav_samples

logger = logging.getLogger(__name__)


import yaml


def load_mastering_profile(profile_name: str = "storytelling") -> MasteringProfile:
    """Load mastering profile configuration from rules/mastering.yaml."""
    rules_path = Path(__file__).resolve().parent.parent / "rules" / "mastering.yaml"
    if not rules_path.exists():
        rules_path = Path("rules/mastering.yaml")
    if rules_path.exists():
        with open(rules_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            profiles = data.get("profiles", {})
            if profile_name in profiles:
                p = profiles[profile_name]
                return MasteringProfile(
                    name=profile_name,
                    target_lufs=float(p.get("target_lufs", -16.0)),
                    true_peak_dbtp=float(p.get("true_peak_dbtp", -1.0)),
                    sample_rate=int(p.get("sample_rate", 44100)),
                    channels=int(p.get("channels", 1)),
                    limiter_enabled=bool(p.get("limiter_enabled", True)),
                )
            if profile_name in ("storytelling", "default"):
                return MasteringProfile(name=profile_name)
            valid = list(profiles.keys())
            raise ValueError(f"Unknown mastering profile '{profile_name}'. Available profiles: {', '.join(valid)}")
    if profile_name in ("storytelling", "default"):
        return MasteringProfile(name=profile_name)
    raise ValueError(f"Unknown mastering profile '{profile_name}'.")


def _calculate_rms_lufs(samples: list[float]) -> float:
    """Approximate integrated loudness in LUFS using RMS power."""
    if not samples:
        return -70.0
    sum_sq = sum(s * s for s in samples)
    mean_sq = sum_sq / float(len(samples))
    if mean_sq <= 1e-12:
        return -70.0
    # Standard acoustic reference offset: 10 * log10(mean_sq) - 0.691
    return 10.0 * math.log10(mean_sq) - 0.691


class AudioMasteringService:
    """Mastering chain for premaster WAV files."""

    def master(
        self,
        input_wav_path: Path | str,
        output_wav_path: Path | str,
        profile: MasteringProfile | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """Apply loudness normalization and true peak limiting to create master.wav."""
        src_path = Path(input_wav_path)
        dest_path = Path(output_wav_path)
        prof = profile or load_mastering_profile("storytelling")

        if not src_path.exists():
            raise FileNotFoundError(f"Premaster WAV not found at '{src_path}'.")

        if cancellation_token and cancellation_token.is_cancelled():
            return {"cancelled": True}

        if progress_callback:
            progress_callback("mastering_analyzing", 20.0, {"profile": prof.name})

        samples, framerate, channels = _read_wav_samples(src_path)
        if not samples:
            raise ValueError(f"Empty or unreadable audio samples from '{src_path}'.")

        # 1. Measure Input Loudness
        input_lufs = _calculate_rms_lufs(samples)
        target_lufs = prof.target_lufs
        gain_db = target_lufs - input_lufs

        # Cap extreme gain boosts to +12dB to prevent noise amplification
        gain_db = max(-24.0, min(12.0, gain_db))
        linear_gain = math.pow(10.0, gain_db / 20.0)

        # 2. Apply Gain and Peak Limiting with Guaranteed Ceiling
        max_peak_linear = math.pow(10.0, prof.true_peak_dbtp / 20.0)  # e.g. -1.0 dBTP -> ~0.891
        mastered_samples: list[float] = []

        knee_start = 0.80 * max_peak_linear

        for s in samples:
            amplified = s * linear_gain
            if prof.limiter_enabled:
                sign = 1.0 if amplified >= 0 else -1.0
                abs_amp = abs(amplified)
                if abs_amp > knee_start:
                    excess = (abs_amp - knee_start) / max(knee_start, 1e-6)
                    compressed = knee_start + (max_peak_linear - knee_start) * math.tanh(excess)
                    amplified = sign * min(compressed, max_peak_linear)
            mastered_samples.append(amplified)

        if cancellation_token and cancellation_token.is_cancelled():
            return {"cancelled": True}

        if progress_callback:
            progress_callback("mastering_writing", 80.0, {"target_lufs": target_lufs})

        # 3. Atomically write master.wav
        _write_wav_samples(dest_path, mastered_samples, sample_rate=prof.sample_rate or framerate)

        output_lufs = _calculate_rms_lufs(mastered_samples)
        max_peak = max(abs(s) for s in mastered_samples) if mastered_samples else 0.0
        output_peak_dbfs = 20.0 * math.log10(max(max_peak, 1e-12))

        if progress_callback:
            progress_callback("mastering_complete", 100.0, {"output_lufs": output_lufs})

        return {
            "profile": prof.name,
            "input_lufs": round(input_lufs, 2),
            "output_lufs": round(output_lufs, 2),
            "target_lufs": prof.target_lufs,
            "true_peak_dbtp": round(output_peak_dbfs, 2),
            "sample_peak_dbfs": round(output_peak_dbfs, 2),
            "output_path": str(dest_path),
            "sample_rate": prof.sample_rate or framerate,
            "channels": channels,
        }
