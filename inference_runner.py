"""Isolated inference runner for Chatterbox API.

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

    # Load appropriate model
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

    # Save output WAV file
    ta.save(output_path, wav.cpu(), model.sr)
    
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
