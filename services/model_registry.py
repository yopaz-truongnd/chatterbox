"""Single source of truth for Model Registry, capabilities, and cache metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config.constants import PROJECT_ROOT


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    display_name: str
    param_size: str
    description: str
    hf_repo_id: str
    cache_folders: tuple[str, ...]
    default_sample_rate: int = 24000
    supports_paralinguistic: bool = False
    supports_languages: bool = False
    supports_voice_conversion: bool = False
    supports_exaggeration: bool = False
    supports_cfg: bool = False
    aliases: tuple[str, ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "nano": ModelSpec(
        id="nano",
        name="Chatterbox Nano",
        display_name="Chatterbox Nano (110M - Light/CPU)",
        param_size="110M",
        description="Siêu nhẹ, tối ưu cho CPU và thiết bị RAM thấp. Hỗ trợ paralinguistic tags.",
        hf_repo_id="ResembleAI/chatterbox-nano",
        cache_folders=("models--ResembleAI--chatterbox-nano",),
        supports_paralinguistic=True,
        aliases=("nano", "chatterbox-nano", "nano-tts", "Chatterbox Nano (110M - Light/CPU)"),
        default_params={
            "temperature": 0.6,
            "top_k": 1000,
            "top_p": 0.95,
            "repetition_penalty": 1.2,
        },
    ),
    "turbo": ModelSpec(
        id="turbo",
        name="Chatterbox Turbo",
        display_name="Chatterbox Turbo (350M - Fast)",
        param_size="350M",
        description="Tốc độ nhanh, biểu cảm tự nhiên, hỗ trợ paralinguistic tags [laugh], [sigh]...",
        hf_repo_id="ResembleAI/chatterbox-turbo",
        cache_folders=("models--ResembleAI--chatterbox-turbo",),
        supports_paralinguistic=True,
        aliases=("turbo", "chatterbox-turbo", "turbo-tts", "Chatterbox Turbo (350M - Fast)"),
        default_params={
            "temperature": 0.6,
            "top_k": 1000,
            "top_p": 0.95,
            "repetition_penalty": 1.2,
        },
    ),
    "standard": ModelSpec(
        id="standard",
        name="Chatterbox Standard",
        display_name="Chatterbox Standard (500M)",
        param_size="500M",
        description="Chất lượng âm thanh chuẩn cao cấp, hỗ trợ điều chỉnh Exaggeration và CFG Weight.",
        hf_repo_id="ResembleAI/chatterbox",
        cache_folders=("models--ResembleAI--chatterbox",),
        supports_exaggeration=True,
        supports_cfg=True,
        aliases=("standard", "tts", "chatterbox-tts", "standard-tts", "Chatterbox Standard (500M)"),
        default_params={
            "exaggeration": 0.5,
            "temperature": 0.8,
            "cfg_weight": 0.5,
            "min_p": 0.05,
            "top_p": 1.0,
            "repetition_penalty": 1.2,
        },
    ),
    "multilingual": ModelSpec(
        id="multilingual",
        name="Chatterbox Multilingual",
        display_name="Chatterbox Multilingual (500M+)",
        param_size="500M+",
        description="Hỗ trợ hơn 23 ngôn ngữ quốc tế, giữ nguyên chất giọng cloning.",
        hf_repo_id="ResembleAI/chatterbox-multilingual",
        cache_folders=(
            "models--ResembleAI--chatterbox-multilingual",
            "models--ResembleAI--chatterbox",
        ),
        supports_languages=True,
        supports_exaggeration=True,
        supports_cfg=True,
        aliases=("multilingual", "mtl", "mtl-tts", "Multilingual TTS", "Multilingual (v3)", "Multilingual (v2)"),
        default_params={
            "language_id": "en",
            "exaggeration": 0.5,
            "temperature": 0.8,
            "cfg_weight": 0.5,
            "min_p": 0.05,
            "top_p": 1.0,
            "repetition_penalty": 1.2,
        },
    ),
    "voice-conversion": ModelSpec(
        id="voice-conversion",
        name="Chatterbox Voice Conversion",
        display_name="Chatterbox Voice Conversion (VC)",
        param_size="500M",
        description="Chuyển đổi âm sắc giọng nói từ file audio nguồn sang file giọng đích zero-shot.",
        hf_repo_id="ResembleAI/chatterbox",
        cache_folders=("models--ResembleAI--chatterbox",),
        supports_voice_conversion=True,
        aliases=("voice-conversion", "vc", "Voice Conversion (VC)", "voice_conversion"),
        default_params={},
    ),
}

MODEL_NAMES = tuple(MODEL_REGISTRY.keys())


def resolve_model_id(name_or_alias: str) -> str:
    """Normalize any alias, display name or model string to canonical model ID."""
    if not name_or_alias:
        return "nano"
    key = name_or_alias.strip().lower()
    for model_id, spec in MODEL_REGISTRY.items():
        if key == model_id.lower():
            return model_id
        for alias in spec.aliases:
            if key == alias.lower():
                return model_id
    if "nano" in key:
        return "nano"
    if "turbo" in key:
        return "turbo"
    if "multilingual" in key or "mtl" in key:
        return "multilingual"
    if "voice" in key or "vc" in key:
        return "voice-conversion"
    if "standard" in key or "tts" in key:
        return "standard"
    return key


def get_model_spec(name_or_alias: str) -> ModelSpec | None:
    """Get ModelSpec by model ID or alias."""
    model_id = resolve_model_id(name_or_alias)
    return MODEL_REGISTRY.get(model_id)


def is_multilingual_cached(models_dir: Path | None = None) -> bool:
    """Specialized check for Multilingual checkpoints."""
    if models_dir is None:
        models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        return False
    mtl_dir = models_dir / "models--ResembleAI--chatterbox-multilingual"
    if mtl_dir.exists():
        return True
    chatterbox_dir = models_dir / "models--ResembleAI--chatterbox"
    if chatterbox_dir.exists():
        for p in chatterbox_dir.glob("**/*"):
            if p.is_file() and any(k in p.name for k in ("t3_mtl", "grapheme_mtl", "Cangjie")):
                return True
    return False


def is_model_cached(name_or_alias: str, models_dir: Path | None = None) -> bool:
    """Check if model checkpoint exists in local models cache directory."""
    if models_dir is None:
        models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        return False

    model_id = resolve_model_id(name_or_alias)
    if model_id == "multilingual":
        return is_multilingual_cached(models_dir)

    spec = MODEL_REGISTRY.get(model_id)
    if not spec:
        return False

    for folder in spec.cache_folders:
        if (models_dir / folder).exists():
            return True
    return False


def get_model_disk_size_bytes(name_or_alias: str, models_dir: Path | None = None) -> int:
    """Calculate total disk space in bytes consumed by a model checkpoint."""
    if models_dir is None:
        models_dir = PROJECT_ROOT / "models"
    if not models_dir.exists():
        return 0

    model_id = resolve_model_id(name_or_alias)
    total = 0

    if model_id in {"nano", "turbo"}:
        target_dir = models_dir / f"models--ResembleAI--chatterbox-{model_id}"
        if target_dir.exists():
            for p in target_dir.glob("**/*"):
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
    elif model_id == "multilingual":
        mtl_dir = models_dir / "models--ResembleAI--chatterbox-multilingual"
        if mtl_dir.exists():
            for p in mtl_dir.glob("**/*"):
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size
        chatterbox_dir = models_dir / "models--ResembleAI--chatterbox"
        if chatterbox_dir.exists():
            for p in chatterbox_dir.glob("**/*"):
                if p.is_file() and not p.is_symlink() and any(k in p.name for k in ("t3_mtl", "grapheme_mtl", "Cangjie")):
                    total += p.stat().st_size
    elif model_id in {"standard", "voice-conversion"}:
        target_dir = models_dir / "models--ResembleAI--chatterbox"
        if target_dir.exists():
            for p in target_dir.glob("**/*"):
                if p.is_file() and not p.is_symlink():
                    total += p.stat().st_size

    return total


def list_registered_models(models_dir: Path | None = None, active_model: str | None = None) -> list[dict]:
    """Return list of all registered models with their current cache and memory state."""
    if models_dir is None:
        models_dir = PROJECT_ROOT / "models"

    active_id = resolve_model_id(active_model) if active_model else None
    results = []
    for model_id, spec in MODEL_REGISTRY.items():
        cached = is_model_cached(model_id, models_dir)
        size_bytes = get_model_disk_size_bytes(model_id, models_dir)
        size_mb = round(size_bytes / (1024 * 1024), 1) if size_bytes > 0 else 0
        results.append({
            "name": model_id,
            "display_name": spec.display_name,
            "param_size": spec.param_size,
            "description": spec.description,
            "hf_repo_id": spec.hf_repo_id,
            "cached_on_disk": cached,
            "size_bytes": size_bytes,
            "size_mb": size_mb,
            "loaded_in_memory": (active_id == model_id),
            "supports_paralinguistic": spec.supports_paralinguistic,
            "supports_languages": spec.supports_languages,
            "supports_exaggeration": spec.supports_exaggeration,
            "supports_cfg": spec.supports_cfg,
            "supports_voice_conversion": spec.supports_voice_conversion,
            "default_params": spec.default_params,
        })
    return results


def check_model_preflight(name_or_alias: str, models_dir: Path | None = None) -> dict[str, Any]:
    """Perform preflight health check verifying checkpoint availability and integrity."""
    if models_dir is None:
        models_dir = PROJECT_ROOT / "models"

    model_id = resolve_model_id(name_or_alias)
    spec = MODEL_REGISTRY.get(model_id)
    if not spec:
        return {
            "model": name_or_alias,
            "model_id": model_id,
            "valid": False,
            "cached": False,
            "message": f"Mô hình '{name_or_alias}' không tồn tại trong danh mục.",
            "size_bytes": 0,
        }

    cached = is_model_cached(model_id, models_dir)
    size_bytes = get_model_disk_size_bytes(model_id, models_dir)
    if not cached or size_bytes < 1024 * 1024:
        return {
            "model": spec.name,
            "model_id": model_id,
            "valid": False,
            "cached": cached,
            "message": f"Chưa tải đủ file checkpoint cho model '{spec.name}' trong thư mục models/.",
            "size_bytes": size_bytes,
        }

    return {
        "model": spec.name,
        "model_id": model_id,
        "valid": True,
        "cached": True,
        "message": f"Model '{spec.name}' sẵn sàng cho inference.",
        "size_bytes": size_bytes,
    }
