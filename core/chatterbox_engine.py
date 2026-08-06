"""
Chatterbox TTS / VC Engine Core - Tách biệt logic ML ra khỏi GUI
"""

import os
import random
import torch
import torchaudio as ta
import numpy as np
import pygame
import re
import threading
import time
from utils.logger import logger, set_active_progress_callback
from config.constants import MAX_CHUNK_CHARS

def set_seed(seed: int):
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)

def split_text(text, max_len=MAX_CHUNK_CHARS):
    """Chia văn bản dài thành các câu nhỏ <= max_len ký tự để tránh VRAM OOM."""
    sentences = re.split(r"(?<=[.!?\n])\s+", text.strip())
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
    return chunks if chunks else [text]

# Khởi tạo pygame mixer cho phát âm thanh
try:
    pygame.mixer.init(frequency=24000)
except Exception:
    pygame.mixer.init()

class ChatterboxEngine:
    def __init__(self, device="cpu"):
        self.device = device
        self.loaded_models = {}
        self.current_model = None
        self.active_model_name = None
        self.current_playing_file = None
        self._lock = threading.RLock()

    def get_device(self):
        return self.device

    def load_model(self, model_name, extra_args=None):
        """Tải mô hình Chatterbox và lưu vào cache cache."""
        with self._lock:
            if model_name in self.loaded_models:
                self.current_model = self.loaded_models[model_name]
                self.active_model_name = model_name
                logger.info("Model '%s' đã có sẵn trong Cache.", model_name)
                return self.current_model

            logger.info("Đang tải model '%s' lên %s...", model_name, self.device.upper())
            if model_name == "Chatterbox Standard (500M)":
                from chatterbox.tts import ChatterboxTTS
                m = ChatterboxTTS.from_pretrained(device=self.device)
            elif model_name == "Chatterbox Turbo (350M - Fast)":
                from chatterbox.tts_turbo import ChatterboxTurboTTS
                m = ChatterboxTurboTTS.from_pretrained(device=self.device, nano=False)
            elif model_name == "Chatterbox Nano (110M - Light/CPU)":
                from chatterbox.tts_turbo import ChatterboxTurboTTS
                m = ChatterboxTurboTTS.from_pretrained(device="cpu", nano=True)
            elif model_name.startswith("Multilingual"):
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS
                ver = extra_args.get("ver", "v3") if extra_args else "v3"
                m = ChatterboxMultilingualTTS.from_pretrained(device=self.device, t3_model=ver)
            elif model_name == "Voice Conversion (VC)":
                from chatterbox.vc import ChatterboxVC
                m = ChatterboxVC.from_pretrained(device=self.device)
            else:
                raise ValueError(f"Unknown model name: {model_name}")

            self.loaded_models[model_name] = m
            self.current_model = m
            self.active_model_name = model_name
            logger.info("Tải thành công model '%s'!", model_name)
            return m

    def generate_tts(self, text, ref_path, model_name, exag, cfg, temp, seed, is_random_seed, out_path, progress_callback=None):
        """Sinh giọng nói Tiếng Anh (Standard / Turbo / Nano)."""
        if is_random_seed:
            seed = random.randint(1, 999999)
        set_seed(seed)

        logger.info("Bắt đầu sinh TTS model '%s' (Seed: %d)", model_name, seed)
        model = self.load_model(model_name)

        chunks = split_text(text)
        logger.info("Đã chia văn bản thành %d đoạn", len(chunks))
        wavs = []
        gen_start_time = time.time()

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
            kwargs = {}

            try:
                if "Turbo" in model_name or "Nano" in model_name:
                    kwargs["temperature"] = temp
                    if ref_path:
                        kwargs["audio_prompt_path"] = ref_path
                    wav = model.generate(chunk, **kwargs)
                else:
                    kwargs["exaggeration"] = exag
                    kwargs["cfg_weight"] = cfg
                    if ref_path:
                        kwargs["audio_prompt_path"] = ref_path
                    wav = model.generate(chunk, **kwargs)
            finally:
                set_active_progress_callback(None)

            wavs.append(wav)

        if progress_callback:
            progress_callback(len(chunks), len(chunks), 100, 100, 0)

        full_wav = torch.cat(wavs, dim=-1) if len(wavs) > 1 else wavs[0]
        sr = getattr(model, "sr", 24000)
        ta.save(out_path, full_wav.cpu(), sr)
        
        logger.info("Sinh thành công! File lưu tại: %s", out_path)
        return out_path, seed

    def generate_multilingual(self, text, lang_code, ref_path, exag, cfg, model_ver, out_path, progress_callback=None):
        """Sinh giọng nói đa ngôn ngữ (V3 / V2)."""
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

        try:
            kwargs = {
                "language_id": lang_code,
                "exaggeration": exag,
                "cfg_weight": cfg
            }
            if ref_path:
                kwargs["audio_prompt_path"] = ref_path

            wav = model.generate(text, **kwargs)
        finally:
            set_active_progress_callback(None)

        if progress_callback:
            progress_callback(1, 1, 100, 100, 0)

        ta.save(out_path, wav.cpu(), model.sr)
        logger.info("Sinh đa ngôn ngữ thành công: %s", out_path)
        return out_path

    def convert_voice(self, src_path, tgt_path, out_path, progress_callback=None):
        """Chuyển đổi giọng nói từ audio sang audio (VC)."""
        m_name = "Voice Conversion (VC)"
        model = self.load_model(m_name)
        
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

        try:
            wav = model.generate(src_path, target_voice_path=tgt_path)
        finally:
            set_active_progress_callback(None)

        if progress_callback:
            progress_callback(1, 1, 100, 100, 0)

        ta.save(out_path, wav.cpu(), model.sr)
        logger.info("Chuyển đổi giọng hoàn tất: %s", out_path)
        return out_path

    def play_audio(self, file_path):
        """Phát file âm thanh sử dụng pygame mixer."""
        try:
            logger.info("Phát file âm thanh: %s", file_path)
            pygame.mixer.music.stop()
            pygame.mixer.music.load(file_path)
            pygame.mixer.music.play()
            self.current_playing_file = file_path
        except Exception as e:
            logger.error("Lỗi phát nhạc: %s", e, exc_info=True)
            raise

    def stop_audio(self):
        """Dừng nhạc đang phát."""
        logger.info("Dừng âm thanh.")
        pygame.mixer.music.stop()
