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


def merge_speech_segments(
    segments: Sequence[torch.Tensor],
    pause_duration: float = 0.6,
    target_sr: int = 24000,
) -> torch.Tensor:
    """Concatenate a sequence of audio tensors with configurable silence padding."""
    if not segments:
        return torch.zeros(1, 0)

    silence_samples = int(target_sr * max(0.0, pause_duration))
    silence_tensor = torch.zeros(1, silence_samples)

    parts: list[torch.Tensor] = []
    for idx, tensor in enumerate(segments):
        parts.append(tensor)
        if idx < len(segments) - 1 and silence_samples > 0:
            parts.append(silence_tensor)

    return torch.cat(parts, dim=-1)


def mix_background_music(
    speech_tensor: torch.Tensor,
    bgm_path: str | Path,
    bgm_volume: float = 0.15,
    target_sr: int = 24000,
    fade_duration: float = 1.5,
) -> tuple[torch.Tensor, str | None]:
    """Mix background music under speech tensor with volume attenuation and fade-out.
    
    Returns (mixed_tensor, warning_message). If BGM loading fails, returns original speech with warning.
    """
    bgm_wav, err = load_and_resample_audio(bgm_path, target_sr)
    if bgm_wav is None:
        return speech_tensor, f"Bỏ qua nhạc nền: {err}"

    try:
        speech_len = speech_tensor.shape[-1]
        bgm_len = bgm_wav.shape[-1]

        if bgm_len == 0:
            return speech_tensor, "Bỏ qua nhạc nền: File BGM rỗng (0 samples)"

        # Loop BGM if shorter than speech
        if bgm_len < speech_len:
            repeats = (speech_len // bgm_len) + 1
            bgm_wav = bgm_wav.repeat(1, repeats)[:, :speech_len]
        else:
            bgm_wav = bgm_wav[:, :speech_len]

        # Apply smooth fade-out at the end
        fade_samples = min(int(target_sr * fade_duration), bgm_wav.shape[-1])
        if fade_samples > 0:
            fade_curve = torch.linspace(1.0, 0.0, fade_samples)
            bgm_wav[:, -fade_samples:] *= fade_curve

        mixed = speech_tensor + (bgm_wav * max(0.0, min(1.0, bgm_volume)))
        
        # Prevent clipping / distortion
        max_amp = mixed.abs().max()
        if max_amp > 1.0:
            mixed = mixed / max_amp

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
