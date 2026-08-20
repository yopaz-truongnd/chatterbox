"""Audio processing, resampling, silence concatenation, and BGM mixing services."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import torch
import torchaudio as ta

logger = logging.getLogger("chatterbox.audio")


def load_and_resample_audio(file_path: str | Path, target_sr: int = 24000) -> tuple[torch.Tensor | None, str | None]:
    """Load an audio file, convert to mono if needed, and resample to target_sr.
    
    Returns (audio_tensor, error_message).
    """
    path = Path(file_path)
    if not path.exists():
        return None, f"File âm thanh không tồn tại: {path.name}"

    try:
        wav, sr = ta.load(str(path))
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        if sr != target_sr:
            resampler = ta.transforms.Resample(orig_freq=sr, new_freq=target_sr)
            wav = resampler(wav)
        return wav, None
    except Exception as exc:
        err_msg = f"Không thể đọc file audio '{path.name}': {exc}"
        logger.warning(err_msg)
        return None, err_msg


def normalize_loudness(tensor: torch.Tensor, target_db: float = -20.0, peak_limit: float = 0.95) -> torch.Tensor:
    """Normalize audio tensor RMS loudness to a target dB level with a strict peak ceiling."""
    if tensor.numel() == 0:
        return tensor

    # Calculate RMS
    rms = torch.sqrt(torch.mean(tensor ** 2) + 1e-9)
    if rms < 1e-6:
        return tensor

    target_linear = 10.0 ** (target_db / 20.0)
    gain = target_linear / rms
    normalized = tensor * gain

    # Apply peak ceiling to prevent digital clipping
    max_peak = normalized.abs().max()
    if max_peak > peak_limit:
        normalized = normalized * (peak_limit / max_peak)

    return normalized


def apply_edge_fades(tensor: torch.Tensor, fade_samples: int = 480) -> torch.Tensor:
    """Apply short linear fade-in and fade-out at audio boundaries to prevent clicks."""
    if tensor.numel() == 0 or fade_samples <= 0:
        return tensor

    length = tensor.shape[-1]
    actual_fade = min(fade_samples, length // 2)
    if actual_fade <= 0:
        return tensor

    faded = tensor.clone()
    fade_in = torch.linspace(0.0, 1.0, actual_fade, dtype=tensor.dtype, device=tensor.device)
    fade_out = torch.linspace(1.0, 0.0, actual_fade, dtype=tensor.dtype, device=tensor.device)

    faded[..., :actual_fade] *= fade_in
    faded[..., -actual_fade:] *= fade_out
    return faded


def merge_speech_segments(
    segments: Sequence[torch.Tensor],
    pause_duration: float = 0.6,
    pause_durations: Sequence[float] | None = None,
    target_sr: int = 24000,
    normalize: bool = True,
    crossfade_ms: int = 30,
) -> torch.Tensor:
    """Concatenate speech segments with per-segment normalization, edge crossfades, and customizable pauses."""
    if not segments:
        return torch.zeros(1, 0)

    fade_samples = int(target_sr * (crossfade_ms / 1000.0)) if crossfade_ms > 0 else 0

    parts: list[torch.Tensor] = []
    total_segments = len(segments)

    for idx, raw_tensor in enumerate(segments):
        tensor = raw_tensor
        if normalize:
            tensor = normalize_loudness(tensor, target_db=-20.0, peak_limit=0.95)
        if fade_samples > 0:
            tensor = apply_edge_fades(tensor, fade_samples=fade_samples)

        parts.append(tensor)

        if idx < total_segments - 1:
            p_dur = pause_durations[idx] if (pause_durations is not None and idx < len(pause_durations)) else pause_duration
            silence_samples = int(target_sr * max(0.0, float(p_dur)))
            if silence_samples > 0:
                parts.append(torch.zeros(1, silence_samples, dtype=tensor.dtype, device=tensor.device))

    return torch.cat(parts, dim=-1)


def mix_background_music(
    speech_tensor: torch.Tensor,
    bgm_path: str | Path,
    bgm_volume: float = 0.15,
    target_sr: int = 24000,
    fade_duration: float = 1.5,
    ducking: bool = True,
    duck_ratio: float = 0.35,
) -> tuple[torch.Tensor, str | None]:
    """Mix background music under speech with smooth volume attenuation, fade-out, and auto-ducking during speech."""
    bgm_wav, err = load_and_resample_audio(bgm_path, target_sr)
    if bgm_wav is None:
        return speech_tensor, f"Bỏ qua nhạc nền: {err}"

    try:
        speech_len = speech_tensor.shape[-1]
        bgm_len = bgm_wav.shape[-1]

        if bgm_len == 0 or speech_len == 0:
            return speech_tensor, "Bỏ qua nhạc nền: File âm thanh rỗng (0 samples)"

        # Loop BGM if shorter than speech
        if bgm_len < speech_len:
            repeats = (speech_len // bgm_len) + 1
            bgm_wav = bgm_wav.repeat(1, repeats)[:, :speech_len]
        else:
            bgm_wav = bgm_wav[:, :speech_len]

        # Apply end fade-out
        fade_samples = min(int(target_sr * fade_duration), bgm_wav.shape[-1])
        if fade_samples > 0:
            fade_curve = torch.linspace(1.0, 0.0, fade_samples, dtype=bgm_wav.dtype)
            bgm_wav[:, -fade_samples:] *= fade_curve

        base_vol = max(0.0, min(1.0, bgm_volume))

        if ducking and speech_len > target_sr * 0.1:
            # Calculate speech energy envelope
            window_size = int(target_sr * 0.05)  # 50ms window
            speech_sq = speech_tensor[0] ** 2

            # Smooth using 1D moving average
            pad_size = window_size // 2
            padded = torch.nn.functional.pad(speech_sq.unsqueeze(0).unsqueeze(0), (pad_size, pad_size), mode="reflect")
            kernel = torch.ones(1, 1, window_size, dtype=speech_tensor.dtype) / window_size
            env = torch.nn.functional.conv1d(padded, kernel).squeeze(0).squeeze(0)[:speech_len]
            env_rms = torch.sqrt(env + 1e-9)

            # Threshold for speech activity
            speech_thresh = 0.015
            duck_factor = torch.clamp((env_rms / speech_thresh), 0.0, 1.0)
            # When speech is loud, volume is base_vol * duck_ratio; when quiet, base_vol
            gain_envelope = base_vol * (1.0 - (1.0 - duck_ratio) * duck_factor)

            # Smooth gain transitions with a 200ms smoothing filter
            smooth_win = int(target_sr * 0.20)
            pad_smooth = smooth_win // 2
            padded_gain = torch.nn.functional.pad(gain_envelope.unsqueeze(0).unsqueeze(0), (pad_smooth, pad_smooth), mode="replicate")
            smooth_kernel = torch.ones(1, 1, smooth_win, dtype=speech_tensor.dtype) / smooth_win
            smooth_gain = torch.nn.functional.conv1d(padded_gain, smooth_kernel).squeeze(0).squeeze(0)[:speech_len]

            bgm_processed = bgm_wav * smooth_gain.unsqueeze(0)
        else:
            bgm_processed = bgm_wav * base_vol

        mixed = speech_tensor + bgm_processed

        # Prevent clipping / distortion
        max_amp = mixed.abs().max()
        if max_amp > 0.98:
            mixed = mixed * (0.98 / max_amp)

        return mixed, None
    except Exception as exc:
        err_msg = f"Lỗi trong quá trình hòa âm nhạc nền BGM: {exc}"
        logger.warning(err_msg)
        return speech_tensor, err_msg


def save_audio_wav(output_path: str | Path, tensor: torch.Tensor, sample_rate: int = 24000) -> None:
    """Save audio tensor as standard WAV file ensuring directory exists."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ta.save(str(path), tensor.cpu(), sample_rate)
