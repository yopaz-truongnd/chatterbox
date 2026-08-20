"""Isolated inference runner for Chatterbox API with telemetry and benchmarking."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

# Set HF cache relative to project root
PROJECT_DIR = Path(__file__).resolve().parent
os.environ["HF_HUB_CACHE"] = str(PROJECT_DIR / "models")

import torch
import torchaudio as ta

from services.inference import execute_model_inference
from utils.platform_tools import clear_accelerator_cache, select_device


def report_progress(phase: str, percent: int, message: str) -> None:
    payload = json.dumps({"phase": phase, "percent": percent, "message": message})
    print(f"PROGRESS:{payload}", flush=True)


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

    # 1. Report loading
    report_progress("loading_model", 10, f"Đang nạp mô hình {job_type.upper()} ({device.upper()})...")
    t0_start = time.time()

    # 2. Execute inference using single canonical function
    report_progress("generating_tokens", 40, "Đang sinh chuỗi ngữ điệu & mã âm thanh (Tokens)...")
    t0_infer = time.time()
    wav, sr = execute_model_inference(job_type, params, device)
    infer_time = round(time.time() - t0_infer, 3)

    # 3. Postprocess & save audio
    report_progress("generating_audio", 85, "Đang xử lý hậu kỳ & giải mã sóng âm thanh (WAV)...")
    t0_save = time.time()
    ta.save(output_path, wav, sr)
    save_time = round(time.time() - t0_save, 3)

    audio_samples = wav.shape[-1]
    audio_duration = round(audio_samples / sr, 3)
    rtf = round(infer_time / max(0.01, audio_duration), 3)
    total_time = round(time.time() - t0_start, 3)

    benchmark_data = {
        "device": device,
        "model_type": job_type,
        "inference_seconds": infer_time,
        "save_seconds": save_time,
        "total_seconds": total_time,
        "audio_duration_seconds": audio_duration,
        "realtime_factor": rtf,
        "faster_than_realtime": round(audio_duration / max(0.01, infer_time), 2),
    }

    print(f"BENCHMARK:{json.dumps(benchmark_data, ensure_ascii=False)}", flush=True)

    if meta_path:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(benchmark_data, f, ensure_ascii=False, indent=2)

    report_progress("completed", 100, "Hoàn tất sinh âm thanh thành công!")

    # Cleanup memory
    del wav
    gc.collect()
    clear_accelerator_cache()


def main() -> None:
    parser = argparse.ArgumentParser(description="Chatterbox Isolated Inference Worker")
    parser.add_argument("--config", required=True, help="JSON configuration string or path to JSON file")
    args = parser.parse_args()

    config_str = args.config.strip()
    if config_str.startswith("{") and config_str.endswith("}"):
        config = json.loads(config_str)
    elif os.path.isfile(config_str):
        with open(config_str, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = json.loads(config_str)

    run_inference(config)


if __name__ == "__main__":
    main()
