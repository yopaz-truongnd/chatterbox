"""Central Model Runtime service managing lifecycle, loading, caching, and VRAM memory."""

from __future__ import annotations

import copy
import gc
import logging
import os
import threading
from typing import Any

import torch

from services.exceptions import CheckpointMissingError, InferenceError, ModelNotFoundError
from services.model_registry import (
    MODEL_REGISTRY,
    is_model_cached,
    resolve_model_id,
)
from utils.platform_tools import clear_accelerator_cache, select_device

logger = logging.getLogger("chatterbox.model_runtime")


class ModelRuntime:
    """Thread-safe model cache and runtime manager with device and variant-aware caching."""

    def __init__(self, default_device: str = "auto") -> None:
        self.device = select_device(default_device)
        self._lock = threading.RLock()
        self._active_cache_key: str | None = None
        self._active_model_id: str | None = None
        self._active_device: str | None = None
        self._active_variant: str | None = None
        self._active_instance: Any | None = None
        self._active_sample_rate: int = 24000
        self._loaded_models: dict[str, tuple[Any, int]] = {}

    @staticmethod
    def build_cache_key(model_id: str, device: str, variant: str | None = None) -> str:
        """Construct canonical cache key incorporating model ID, optional variant, and target device."""
        norm_device = device.lower().strip() if device in {"cpu", "cuda", "mps"} else select_device(device)
        norm_id = resolve_model_id(model_id)
        if variant:
            return f"{norm_id}:{variant.lower().strip()}@{norm_device}"
        return f"{norm_id}@{norm_device}"

    def get_device(self) -> str:
        return self.device

    def set_device(self, device: str) -> None:
        with self._lock:
            if device != self.device:
                self.unload_all()
                self.device = select_device(device)

    def load_model(
        self,
        model_name_or_id: str,
        device: str | None = None,
        extra_args: dict | None = None,
        keep_in_cache: bool = True,
    ) -> tuple[Any, int]:
        """Load requested model, verifying device and variant with cache retention."""
        target_device = select_device(device) if device else self.device
        model_id = resolve_model_id(model_name_or_id)
        variant = (extra_args or {}).get("ver") if model_id == "multilingual" else None
        cache_key = self.build_cache_key(model_id, target_device, variant)

        # Mock for dummy inference in unit tests
        if os.environ.get("CHATTERBOX_TEST_DUMMY_INFERENCE") == "1":
            class DummyModel:
                def __init__(self):
                    self.sr = 24000
                    self.conds = {"voice": "default"}
                    self.default_conds = {"voice": "default"}

                def generate(self, *args, **kwargs):
                    return torch.zeros(1, 24000)

            return DummyModel(), 24000

        with self._lock:
            # 1. Exact active cache key match (same model, device, and variant)
            if self._active_cache_key == cache_key and self._active_instance is not None:
                return self._active_instance, self._active_sample_rate

            # 2. Check if already loaded in cached pool
            if cache_key in self._loaded_models:
                inst, sr = self._loaded_models[cache_key]
                self._active_cache_key = cache_key
                self._active_model_id = model_id
                self._active_device = target_device
                self._active_variant = variant
                self._active_instance = inst
                self._active_sample_rate = sr
                return inst, sr

            logger.info("Đang nạp mô hình '%s' (%s) trên thiết bị %s...", model_id, variant or "default", target_device.upper())

            try:
                if model_id == "standard":
                    from chatterbox.tts import ChatterboxTTS
                    model = ChatterboxTTS.from_pretrained(target_device)
                elif model_id in {"turbo", "nano"}:
                    from chatterbox.tts_turbo import ChatterboxTurboTTS
                    is_nano = (model_id == "nano")
                    model = ChatterboxTurboTTS.from_pretrained(target_device, nano=is_nano)
                elif model_id == "multilingual":
                    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
                    t3_ver = variant or "v3"
                    model = ChatterboxMultilingualTTS.from_pretrained(target_device, t3_model=t3_ver)
                elif model_id == "voice-conversion":
                    from chatterbox.vc import ChatterboxVC
                    model = ChatterboxVC.from_pretrained(target_device)
                else:
                    raise ModelNotFoundError(f"Không hỗ trợ mô hình: '{model_name_or_id}'")

                sr = getattr(model, "sr", 24000)

                # Store default conditionals for zero-shot speaker state resetting
                if hasattr(model, "conds") and getattr(model, "conds", None) is not None:
                    try:
                        model.default_conds = copy.deepcopy(model.conds)
                    except Exception:
                        model.default_conds = model.conds

                if keep_in_cache:
                    self._loaded_models[cache_key] = (model, sr)

                self._active_cache_key = cache_key
                self._active_model_id = model_id
                self._active_device = target_device
                self._active_variant = variant
                self._active_instance = model
                self._active_sample_rate = sr
                logger.info("Đã nạp thành công mô hình '%s'!", cache_key)
                return model, sr

            except Exception as exc:
                self._active_cache_key = None
                self._active_model_id = None
                self._active_device = None
                self._active_variant = None
                self._active_instance = None
                gc.collect()
                clear_accelerator_cache()
                err_str = str(exc)
                if "Cannot find an appropriate cached snapshot" in err_str or "HF_HUB_OFFLINE" in err_str:
                    raise CheckpointMissingError(
                        f"Chưa có checkpoint cho model '{model_id}' trong thư mục models/. "
                        "Vui lòng khởi động lại server khi có kết nối mạng để tải checkpoint."
                    ) from exc
                raise InferenceError(f"Không thể nạp mô hình '{model_id}': {exc}") from exc

    def unload_model(self, model_name_or_id: str | None = None) -> None:
        """Unload specific model or currently active model across all devices/variants."""
        with self._lock:
            if model_name_or_id:
                target_id = resolve_model_id(model_name_or_id)
                keys_to_del = [
                    k for k in self._loaded_models
                    if k.startswith(f"{target_id}@") or k.startswith(f"{target_id}:")
                ]
                for k in keys_to_del:
                    del self._loaded_models[k]
                if self._active_model_id == target_id:
                    self._active_cache_key = None
                    self._active_model_id = None
                    self._active_device = None
                    self._active_variant = None
                    self._active_instance = None
            else:
                self._active_cache_key = None
                self._active_model_id = None
                self._active_device = None
                self._active_variant = None
                self._active_instance = None

            gc.collect()
            clear_accelerator_cache()

    def unload_all(self) -> None:
        """Unload all cached models and free RAM/VRAM."""
        with self._lock:
            self._loaded_models.clear()
            self._active_cache_key = None
            self._active_model_id = None
            self._active_device = None
            self._active_variant = None
            self._active_instance = None
            gc.collect()
            clear_accelerator_cache()

    @property
    def active_model_name(self) -> str | None:
        return self._active_model_id

    @property
    def active_device(self) -> str | None:
        return self._active_device

    @property
    def active_variant(self) -> str | None:
        return self._active_variant

    @property
    def active_cache_key(self) -> str | None:
        return self._active_cache_key

    @property
    def active_instance(self) -> Any | None:
        return self._active_instance

    @property
    def active_sample_rate(self) -> int:
        return self._active_sample_rate


# Global singleton instance
model_runtime = ModelRuntime()
