"""Isolated inference runner for Chatterbox API with telemetry and benchmarking.

This script runs in a separate process. If an Out-Of-Memory (OOM) or SIGKILL event occurs,
only this process will be terminated by the OS, leaving the main FastAPI server healthy and alive.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import random
import sys
import time
from pathlib import Path

# Set HF cache relative to project root
PROJECT_DIR = Path(__file__).resolve().parent
os.environ["HF_HUB_CACHE"] = str(PROJECT_DIR / "models")

import numpy as np
import torch
import torchaudio as ta

from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from chatterbox.tts import ChatterboxTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS
from chatterbox.vc import ChatterboxVC
from utils.platform_tools import clear_accelerator_cache, select_device


def report_progress(phase: str, percent: int, message: str) -> None:
    """Print structured progress marker for parent process consumption."""
    payload = json.dumps({"phase": phase, "percent": percent, "message": message})
    print(f"PROGRESS:{payload}", flush=True)


def set_seed(seed: int, device: str) -> None:
    torch.manual_seed(seed)
    if device == "cuda":
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)


def run_inference(config: dict) -> None:
    job_type = config.get("type", "turbo")
    params = config.get("params", {})
    output_path = Path(config["output_path"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = Path(config["meta_path"]) if config.get("meta_path") else None
    
    device_pref = config.get("device", "auto")
    device = select_device(device_pref)
    
    cpu_threads = int(config.get("cpu_threads", 2))
    torch.set_num_threads(cpu_threads)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        pass

    seed = int(params.get("seed", 0))
    if seed:
        set_seed(seed, device)

    # 1. Load model with progress telemetry
    report_progress("loading_model", 10, f"Đang nạp mô hình {job_type.upper()} ({device.upper()})...")
    t0_load = time.time()

    if job_type == "tts":
        model = ChatterboxTTS.from_pretrained(device)
    elif job_type == "turbo":
        model = ChatterboxTurboTTS.from_pretrained(device, nano=False)
    elif job_type == "nano":
        model = ChatterboxTurboTTS.from_pretrained(device, nano=True)
    elif job_type == "multilingual":
        model = ChatterboxMultilingualTTS.from_pretrained(device)
    elif job_type == "voice-conversion":
        model = ChatterboxVC.from_pretrained(device)
    else:
        raise ValueError(f"Loại job không hợp lệ: {job_type}")

    load_time = round(time.time() - t0_load, 3)

    # 2. Run inference with progress telemetry
    report_progress("generating_tokens", 40, "Đang sinh chuỗi ngữ điệu & mã âm thanh (Tokens)...")
    t0_infer = time.time()

    with torch.inference_mode():
        if job_type == "tts":
            wav = model.generate(
                params["text"],
                audio_prompt_path=params.get("audio_prompt_path"),
                exaggeration=float(params.get("exaggeration", 0.5)),
                temperature=float(params.get("temperature", 0.8)),
                cfg_weight=float(params.get("cfg_weight", 0.5)),
                min_p=float(params.get("min_p", 0.05)),
                top_p=float(params.get("top_p", 1.0)),
                repetition_penalty=float(params.get("repetition_penalty", 1.2)),
            )
        elif job_type in {"turbo", "nano"}:
            wav = model.generate(
                params["text"],
                audio_prompt_path=params.get("audio_prompt_path"),
                temperature=float(params.get("temperature", 0.6)),
                top_k=int(params.get("top_k", 1000)),
                top_p=float(params.get("top_p", 0.95)),
                repetition_penalty=float(params.get("repetition_penalty", 1.2)),
            )
        elif job_type == "multilingual":
            wav = model.generate(
                params["text"],
                language_id=params.get("language_id", "vi"),
                audio_prompt_path=params.get("audio_prompt_path"),
                exaggeration=float(params.get("exaggeration", 0.5)),
                temperature=float(params.get("temperature", 0.8)),
                cfg_weight=float(params.get("cfg_weight", 0.5)),
                min_p=float(params.get("min_p", 0.05)),
                top_p=float(params.get("top_p", 1.0)),
                repetition_penalty=float(params.get("repetition_penalty", 1.2)),
            )
        else:
            wav = model.generate(
                params["source_audio_path"],
                target_voice_path=params.get("target_voice_path"),
            )

    infer_time = round(time.time() - t0_infer, 3)

    # 3. Save output WAV file & compute benchmarks
    report_progress("generating_audio", 85, "Đang xử lý hậu kỳ & giải mã sóng âm thanh (WAV)...")
    t0_save = time.time()
    ta.save(output_path, wav.cpu(), model.sr)
    save_time = round(time.time() - t0_save, 3)

    audio_samples = wav.shape[-1]
    audio_duration = round(audio_samples / model.sr, 3)
    rtf = round(infer_time / max(0.01, audio_duration), 3)

    benchmark_data = {
        "device": device,
        "model_type": job_type,
        "model_load_seconds": load_time,
        "inference_seconds": infer_time,
        "save_seconds": save_time,
        "audio_duration_seconds": audio_duration,
        "realtime_factor": rtf,
        "faster_than_realtime": round(audio_duration / max(0.01, infer_time), 2),
    }

    # Print benchmark marker
    print(f"BENCHMARK:{json.dumps(benchmark_data, ensure_ascii=False)}", flush=True)

    if meta_path:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(benchmark_data, f, ensure_ascii=False, indent=2)

    report_progress("completed", 100, "Hoàn tất sinh âm thanh thành công!")

    # Cleanup memory
    del model, wav
    gc.collect()
    clear_accelerator_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chatterbox Isolated Inference Worker")
    parser.add_argument("--config", required=True, help="JSON configuration string or path to JSON file")
    args = parser.parse_args()

    config_str = args.config
    if Path(config_str).is_file():
        with open(config_str, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = json.loads(config_str)

    run_inference(config)


if __name__ == "__main__":
    main()
