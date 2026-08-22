"""Canonical Speech Synthesis and Voice Conversion Application Service.

Provides unified parameter normalization, text chunking, seed handling, and inference dispatch.
"""

from __future__ import annotations

import copy
import logging
import random
import re
from typing import Any, Callable

import numpy as np
import torch

from config.constants import MAX_CHUNK_CHARS
from services.exceptions import InferenceError, ValidationError
from services.model_registry import get_model_spec, resolve_model_id
from services.model_runtime import model_runtime
from utils.logger import set_active_progress_callback

logger = logging.getLogger("chatterbox.synthesis")


def set_synthesis_seed(seed: int, device: str = "cpu") -> None:
    """Set random seed for reproducibility across PyTorch and NumPy."""
    if not seed:
        return
    torch.manual_seed(seed)
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)


def split_text(text: str, max_len: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split long text into sentence chunks <= max_len characters to avoid VRAM OOM."""
    cleaned = text.strip()
    if not cleaned:
        return []
    sentences = re.split(r"(?<=[.!?\n])\s+", cleaned)
    chunks, current = [], ""
    for s in sentences:
        if not s:
            continue
        if len(current) + len(s) + 1 <= max_len:
            current = f"{current} {s}".strip()
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks if chunks else [cleaned]


def normalize_synthesis_params(model_id: str, raw_params: dict) -> dict[str, Any]:
    """Validate and fill defaults according to model specification."""
    canonical_id = resolve_model_id(model_id)
    spec = get_model_spec(canonical_id)
    params = dict(raw_params or {})

    # Copy defaults from registry
    if spec:
        for k, v in spec.default_params.items():
            if k not in params or params[k] is None:
                params[k] = v

    # Common parameters
    params["seed"] = int(params.get("seed", 0) or 0)

    # Sanitize float bounds
    if "temperature" in params:
        params["temperature"] = float(np.clip(float(params["temperature"]), 0.05, 2.0))
    if "exaggeration" in params:
        params["exaggeration"] = float(np.clip(float(params["exaggeration"]), 0.0, 2.0))
    if "cfg_weight" in params:
        params["cfg_weight"] = float(np.clip(float(params["cfg_weight"]), 0.0, 2.0))
    if "top_p" in params:
        params["top_p"] = float(np.clip(float(params["top_p"]), 0.01, 1.0))
    if "repetition_penalty" in params:
        params["repetition_penalty"] = float(np.clip(float(params["repetition_penalty"]), 0.5, 3.0))

    return params


def synthesize_chunk_tensor(
    model: Any,
    model_id: str,
    text: str,
    params: dict[str, Any],
    device: str,
) -> torch.Tensor:
    """Run forward generation on a single text chunk with an already-loaded model."""
    canonical_id = resolve_model_id(model_id)

    # Reset conditional voice state if no audio prompt path is passed
    audio_prompt_path = params.get("audio_prompt_path")
    if not audio_prompt_path and hasattr(model, "default_conds") and getattr(model, "default_conds", None) is not None:
        try:
            model.conds = copy.deepcopy(model.default_conds)
        except Exception:
            model.conds = model.default_conds

    with torch.inference_mode():
        if canonical_id == "standard":
            wav = model.generate(
                text,
                audio_prompt_path=audio_prompt_path,
                exaggeration=float(params.get("exaggeration", 0.5)),
                temperature=float(params.get("temperature", 0.8)),
                cfg_weight=float(params.get("cfg_weight", 0.5)),
                min_p=float(params.get("min_p", 0.05)),
                top_p=float(params.get("top_p", 1.0)),
                repetition_penalty=float(params.get("repetition_penalty", 1.2)),
            )
        elif canonical_id in {"turbo", "nano"}:
            wav = model.generate(
                text,
                audio_prompt_path=audio_prompt_path,
                temperature=float(params.get("temperature", 0.6)),
                top_k=int(params.get("top_k", 1000)),
                top_p=float(params.get("top_p", 0.95)),
                repetition_penalty=float(params.get("repetition_penalty", 1.2)),
            )
        elif canonical_id == "multilingual":
            wav = model.generate(
                text,
                language_id=params.get("language_id", "en"),
                audio_prompt_path=audio_prompt_path,
                exaggeration=float(params.get("exaggeration", 0.5)),
                temperature=float(params.get("temperature", 0.8)),
                cfg_weight=float(params.get("cfg_weight", 0.5)),
                min_p=float(params.get("min_p", 0.05)),
                top_p=float(params.get("top_p", 1.0)),
                repetition_penalty=float(params.get("repetition_penalty", 1.2)),
            )
        elif canonical_id == "voice-conversion":
            wav = model.generate(
                params.get("source_audio_path", text),
                target_voice_path=params.get("target_voice_path"),
            )
        else:
            raise ValidationError(f"Mô hình không được hỗ trợ: {model_id}")

    return wav.cpu()


def generate_audio(
    model_name_or_id: str,
    params: dict[str, Any],
    device: str | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[torch.Tensor, int]:
    """Complete high-level synthesis flow: load/reuse model, seed, split text, generate, concat."""
    model_id = resolve_model_id(model_name_or_id)
    norm_params = normalize_synthesis_params(model_id, params)

    target_device = device or model_runtime.get_device()
    seed = norm_params.get("seed", 0)
    set_synthesis_seed(seed, target_device)

    model, sr = model_runtime.load_model(model_id, device=target_device)

    if model_id == "voice-conversion":
        source_audio = norm_params.get("source_audio_path", "")
        if not source_audio:
            raise ValidationError("Thiếu file audio nguồn ('source_audio_path') cho Voice Conversion")
        wav = synthesize_chunk_tensor(model, model_id, source_audio, norm_params, target_device)
        return wav, sr

    text = norm_params.get("text", "")
    if not text:
        raise ValidationError("Văn bản phát âm không được để trống")

    chunks = split_text(text)
    if not chunks:
        chunks = [text]

    wav_chunks = []
    total_chunks = len(chunks)

    for idx, chunk in enumerate(chunks, 1):
        if progress_callback:
            progress_callback(idx, total_chunks, f"Đang xử lý đoạn {idx}/{total_chunks}...")

        wav = synthesize_chunk_tensor(model, model_id, chunk, norm_params, target_device)
        wav_chunks.append(wav)

    if len(wav_chunks) == 1:
        merged = wav_chunks[0]
    else:
        merged = torch.cat(wav_chunks, dim=-1)

    return merged, sr
