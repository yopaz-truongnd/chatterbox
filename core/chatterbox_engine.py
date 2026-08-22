"""Chatterbox TTS / VC Desktop Engine Core - delegates to central application services."""

from __future__ import annotations

import gc
import logging
import os
import random
import threading
import time
from typing import Any

import numpy as np
import pygame
import torch
import torchaudio as ta

from config.constants import MAX_CHUNK_CHARS
from config.settings import settings_manager
from services.model_registry import get_model_spec, resolve_model_id
from services.model_runtime import model_runtime
from services.synthesis import set_synthesis_seed, split_text, synthesize_chunk_tensor
from utils.logger import logger, set_active_progress_callback
from utils.platform_tools import clear_accelerator_cache, select_device


def set_seed(seed: int) -> None:
    set_synthesis_seed(seed, "cpu")


def apply_hardware_limits() -> None:
    """Apply CPU thread limits, GPU memory fraction, and process niceness."""
    try:
        threads = settings_manager.get("cpu_threads_limit", 4)
        if isinstance(threads, int) and threads > 0:
            torch.set_num_threads(threads)
            os.environ["OMP_NUM_THREADS"] = str(threads)
            os.environ["MKL_NUM_THREADS"] = str(threads)

        if torch.cuda.is_available():
            vram_pct = settings_manager.get("max_vram_fraction", 80)
            if isinstance(vram_pct, (int, float)) and 10 <= vram_pct <= 100:
                fraction = float(vram_pct) / 100.0
                try:
                    torch.cuda.set_per_process_memory_fraction(fraction)
                except Exception:
                    pass

        prio = settings_manager.get("process_priority", "low")
        if prio == "low" and hasattr(os, "nice"):
            try:
                os.nice(5)
            except Exception:
                pass
    except Exception as e:
        logger.warning("Lỗi khi áp dụng giới hạn phần cứng: %s", e)


def cleanup_memory() -> None:
    """Free RAM and GPU cache after generation."""
    if settings_manager.get("force_gc_after_gen", True):
        gc.collect()
        clear_accelerator_cache()


# Initialize pygame mixer for audio playback
try:
    pygame.mixer.init(frequency=24000)
except Exception:
    try:
        pygame.mixer.init()
    except Exception:
        pass


def get_effective_default_model() -> str:
    """Resolve effective startup model for Desktop GUI based on settings and system hardware."""
    from utils.platform_tools import detect_system_profile
    cfg = settings_manager.get("default_model", "auto")
    if cfg == "auto":
        profile = detect_system_profile()
        rec = profile.get("recommended_model", "nano")
        return "Chatterbox Nano (110M - Light/CPU)" if rec == "nano" else "Chatterbox Turbo (350M - Fast)"
    if cfg in ("nano", "Chatterbox Nano (110M - Light/CPU)"):
        return "Chatterbox Nano (110M - Light/CPU)"
    if cfg in ("turbo", "Chatterbox Turbo (350M - Fast)"):
        return "Chatterbox Turbo (350M - Fast)"
    if cfg in ("multilingual", "Multilingual TTS"):
        return "Multilingual TTS"
    return "Chatterbox Standard (500M)"


class ChatterboxEngine:
    """Desktop Application Engine coordinating ModelRuntime and Synthesis services."""

    def __init__(self, device: str = "auto") -> None:
        saved_device = settings_manager.get("device", "auto")
        preference = saved_device if saved_device != "auto" else device
        self.device = select_device(preference)

        apply_hardware_limits()
        model_runtime.set_device(self.device)

        self.loaded_models: dict[str, Any] = {}
        self.current_model: Any | None = None
        self.active_model_name: str | None = None
        self.current_playing_file: str | None = None
        self._lock = threading.RLock()

    def get_device(self) -> str:
        return self.device

    def load_model(self, model_name: str, extra_args: dict | None = None) -> Any:
        """Load Chatterbox model and cache it."""
        with self._lock:
            if settings_manager.get("auto_unload_models", False) and self.active_model_name != model_name:
                logger.info("Giải phóng các model cũ khỏi VRAM...")
                model_runtime.unload_all()
                self.loaded_models.clear()

            model, sr = model_runtime.load_model(
                model_name,
                device=self.device,
                extra_args=extra_args,
                keep_in_cache=True,
            )
            self.loaded_models[model_name] = model
            self.current_model = model
            self.active_model_name = model_name
            return model

    def generate_tts(
        self,
        text: str,
        ref_path: str | None,
        model_name: str,
        exag: float,
        cfg: float,
        temp: float,
        seed: int,
        is_random_seed: bool,
        out_path: str,
        progress_callback: Any = None,
    ) -> tuple[str, int]:
        """Synthesize English TTS with Standard, Turbo, or Nano models."""
        if is_random_seed:
            seed = random.randint(1, 999999)
        set_seed(seed)

        logger.info("Bắt đầu sinh TTS model '%s' (Seed: %d)", model_name, seed)
        model = self.load_model(model_name)
        canonical_id = resolve_model_id(model_name)

        chunks = split_text(text)
        logger.info("Đã chia văn bản thành %d đoạn", len(chunks))
        wavs = []
        gen_start_time = time.time()

        params = {
            "exaggeration": exag,
            "cfg_weight": cfg,
            "temperature": temp,
            "seed": seed,
            "audio_prompt_path": ref_path,
        }

        for i, chunk in enumerate(chunks, 1):
            def on_sampling_step(step_pct):
                if progress_callback:
                    overall_pct = min(99, int(((i - 1) + (step_pct / 100.0)) / len(chunks) * 100))
                    elapsed = time.time() - gen_start_time
                    if overall_pct > 0:
                        total_est = elapsed / (overall_pct / 100.0)
                        eta = max(0, int(total_est - elapsed))
                    else:
                        eta = 0
                    progress_callback(i, len(chunks), overall_pct, step_pct, eta)

            set_active_progress_callback(on_sampling_step)
            logger.info("Đang xử lý đoạn %d/%d: '%s...'", i, len(chunks), chunk[:40])

            try:
                wav = synthesize_chunk_tensor(model, canonical_id, chunk, params, self.device)
            finally:
                set_active_progress_callback(None)

            wavs.append(wav)

        if progress_callback:
            progress_callback(len(chunks), len(chunks), 100, 100, 0)

        full_wav = torch.cat(wavs, dim=-1) if len(wavs) > 1 else wavs[0]
        sr = getattr(model, "sr", 24000)
        ta.save(out_path, full_wav.cpu(), sr)

        cleanup_memory()
        logger.info("Sinh thành công! File lưu tại: %s", out_path)
        return out_path, seed

    def generate_multilingual(
        self,
        text: str,
        lang_code: str,
        ref_path: str | None,
        exag: float,
        cfg: float,
        model_ver: str,
        out_path: str,
        progress_callback: Any = None,
    ) -> str:
        """Synthesize multilingual speech."""
        m_name = f"Multilingual ({model_ver})"
        model = self.load_model(m_name, extra_args={"ver": model_ver})

        logger.info("Bắt đầu sinh đa ngôn ngữ [Lang: %s, Ver: %s]", lang_code, model_ver)
        gen_start_time = time.time()

        def on_sampling_step(step_pct):
            if progress_callback:
                elapsed = time.time() - gen_start_time
                if step_pct > 0:
                    total_est = elapsed / (step_pct / 100.0)
                    eta = max(0, int(total_est - elapsed))
                else:
                    eta = 0
                progress_callback(1, 1, step_pct, step_pct, eta)

        set_active_progress_callback(on_sampling_step)

        params = {
            "language_id": lang_code,
            "exaggeration": exag,
            "cfg_weight": cfg,
            "audio_prompt_path": ref_path,
        }

        try:
            wav = synthesize_chunk_tensor(model, "multilingual", text, params, self.device)
        finally:
            set_active_progress_callback(None)

        if progress_callback:
            progress_callback(1, 1, 100, 100, 0)

        ta.save(out_path, wav.cpu(), getattr(model, "sr", 24000))
        cleanup_memory()
        logger.info("Sinh đa ngôn ngữ thành công: %s", out_path)
        return out_path

    def convert_voice(
        self,
        src_path: str,
        tgt_path: str | None,
        out_path: str,
        progress_callback: Any = None,
    ) -> str:
        """Voice conversion from source audio to target audio voice."""
        model = self.load_model("voice-conversion")
        logger.info("Bắt đầu thực hiện chuyển đổi giọng nói (VC)")
        gen_start_time = time.time()

        def on_sampling_step(step_pct):
            if progress_callback:
                elapsed = time.time() - gen_start_time
                if step_pct > 0:
                    total_est = elapsed / (step_pct / 100.0)
                    eta = max(0, int(total_est - elapsed))
                else:
                    eta = 0
                progress_callback(1, 1, step_pct, step_pct, eta)

        set_active_progress_callback(on_sampling_step)

        params = {
            "source_audio_path": src_path,
            "target_voice_path": tgt_path,
        }

        try:
            wav = synthesize_chunk_tensor(model, "voice-conversion", src_path, params, self.device)
        finally:
            set_active_progress_callback(None)

        if progress_callback:
            progress_callback(1, 1, 100, 100, 0)

        ta.save(out_path, wav.cpu(), getattr(model, "sr", 24000))
        cleanup_memory()
        logger.info("Chuyển đổi giọng hoàn tất: %s", out_path)
        return out_path

    def play_audio(self, file_path: str) -> None:
        """Play audio file with pygame mixer."""
        try:
            logger.info("Phát file âm thanh: %s", file_path)
            pygame.mixer.music.stop()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            self.current_playing_file = file_path
        except Exception as e:
            logger.error("Lỗi phát nhạc: %s", e, exc_info=True)
            raise

    def stop_audio(self) -> None:
        """Stop currently playing audio."""
        logger.info("Dừng âm thanh.")
        pygame.mixer.music.stop()
