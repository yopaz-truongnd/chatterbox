"""Single canonical inference service and isolated process execution for Chatterbox."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np
import torch
import torchaudio as ta

from chatterbox.mtl_tts import ChatterboxMultilingualTTS
from chatterbox.tts import ChatterboxTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS
from chatterbox.vc import ChatterboxVC
from utils.platform_tools import clear_accelerator_cache, select_device


def set_inference_seed(seed: int, device: str) -> None:
    if not seed:
        return
    torch.manual_seed(seed)
    if device == "cuda":
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)


def execute_model_inference(job_type: str, params: dict, device: str) -> tuple[torch.Tensor, int]:
    """Single canonical model inference implementation used by both isolated runner and test harnesses.
    
    Guarantees that default parameter values and generation logic never drift.
    """
    seed = int(params.get("seed", 0))
    set_inference_seed(seed, device)

    with torch.inference_mode():
        if job_type == "tts":
            model = ChatterboxTTS.from_pretrained(device)
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
            sr = model.sr
        elif job_type in {"turbo", "nano"}:
            is_nano = (job_type == "nano")
            model = ChatterboxTurboTTS.from_pretrained(device, nano=is_nano)
            wav = model.generate(
                params["text"],
                audio_prompt_path=params.get("audio_prompt_path"),
                temperature=float(params.get("temperature", 0.6)),
                top_k=int(params.get("top_k", 1000)),
                top_p=float(params.get("top_p", 0.95)),
                repetition_penalty=float(params.get("repetition_penalty", 1.2)),
            )
            sr = model.sr
        elif job_type == "multilingual":
            model = ChatterboxMultilingualTTS.from_pretrained(device)
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
            sr = model.sr
        elif job_type == "voice-conversion":
            model = ChatterboxVC.from_pretrained(device)
            wav = model.generate(
                params["source_audio_path"],
                target_voice_path=params.get("target_voice_path"),
            )
            sr = model.sr
        else:
            raise ValueError(f"Loại mô hình không hợp lệ: {job_type}")

    return wav.cpu(), sr


def run_isolated_subprocess(
    job_id: str,
    job_type: str,
    params: dict,
    output_path: Path,
    device: str,
    cpu_threads: int,
    project_dir: Path,
    data_dir: Path,
    timeout_seconds: int = 240,
    progress_callback: Callable[[str, int, str], None] | None = None,
    benchmark_callback: Callable[[dict], None] | None = None,
    register_proc_callback: Callable[[str, subprocess.Popen], None] | None = None,
    unregister_proc_callback: Callable[[str], None] | None = None,
) -> tuple[bool, str | None, dict | None]:
    """Execute inference inside an isolated subprocess with deadline enforcement and non-blocking stream reading.
    
    Guarantees:
      - Main process cannot freeze if child process hangs without closing stdout.
      - Uses os.pathsep for cross-platform PYTHONPATH on Windows and macOS.
      - Cleanly intercepts OOM, crashes, and timeouts.
    """
    meta_path = data_dir / "outputs" / f"{job_id}.json"
    config = {
        "type": job_type,
        "params": params,
        "output_path": str(output_path),
        "meta_path": str(meta_path),
        "device": device,
        "cpu_threads": cpu_threads,
    }
    config_json = json.dumps(config)
    runner_script = project_dir / "inference_runner.py"

    cmd = [
        sys.executable,
        str(runner_script),
        "--config",
        config_json,
    ]

    # Cross-platform environment with os.pathsep
    env = os.environ.copy()
    env["HF_HUB_CACHE"] = str(project_dir / "models")
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_dir = str(project_dir / "src")
    env["PYTHONPATH"] = (src_dir + os.pathsep + existing_pythonpath) if existing_pythonpath else src_dir

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
            cwd=str(project_dir),
        )
    except Exception as exc:
        return False, f"Không thể khởi chạy tiến trình con: {exc}", None

    if register_proc_callback:
        register_proc_callback(job_id, proc)

    stdout_queue: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []

    def reader_thread_stdout():
        try:
            for line in iter(proc.stdout.readline, ""):
                stdout_queue.put(line)
        finally:
            stdout_queue.put(None)

    def reader_thread_stderr():
        try:
            for line in iter(proc.stderr.readline, ""):
                stderr_lines.append(line)
        finally:
            pass

    t_out = threading.Thread(target=reader_thread_stdout, daemon=True)
    t_err = threading.Thread(target=reader_thread_stderr, daemon=True)
    t_out.start()
    t_err.start()

    benchmark_data = None
    deadline = time.monotonic() + timeout_seconds
    timed_out = False

    try:
        while True:
            # Check timeout deadline
            if time.monotonic() > deadline:
                timed_out = True
                try:
                    proc.terminate()
                    time.sleep(1.0)
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                break

            # Read available stdout lines without blocking forever
            try:
                line = stdout_queue.get(timeout=0.1)
                if line is None:
                    break
                line_str = line.strip()
                if line_str.startswith("PROGRESS:"):
                    try:
                        pdata = json.loads(line_str[9:])
                        if progress_callback:
                            progress_callback(
                                pdata.get("phase", "processing"),
                                int(pdata.get("percent", 0)),
                                pdata.get("message", ""),
                            )
                    except Exception:
                        pass
                elif line_str.startswith("BENCHMARK:"):
                    try:
                        bdata = json.loads(line_str[10:])
                        benchmark_data = bdata
                        if benchmark_callback:
                            benchmark_callback(bdata)
                    except Exception:
                        pass
            except queue.Empty:
                # Check if process exited
                if proc.poll() is not None and stdout_queue.empty():
                    break

        proc.wait(timeout=2.0)
    except Exception:
        pass
    finally:
        if unregister_proc_callback:
            unregister_proc_callback(job_id)

    if timed_out:
        return False, f"Quá thời gian xử lý cho phép (Timeout {timeout_seconds}s).", None

    rc = proc.returncode
    if rc == 0 and output_path.exists():
        return True, None, benchmark_data

    # Inspect failure reason
    stderr_full = "".join(stderr_lines).strip()
    if rc in (-9, 137, -11, 139, -10, 138):
        err_msg = (
            f"Tiến trình sinh âm thanh bị hệ thống ngắt đột ngột (Mã thoát: {rc} - Tràn bộ nhớ RAM / OOM). "
            "Khuyến nghị: Chuyển sang model 'nano' (chỉ tốn ~500MB RAM), chia nhỏ câu văn bản "
            "hoặc đóng bớt các ứng dụng nặng khác."
        )
        return False, err_msg, None

    if "Cannot find an appropriate cached snapshot folder" in stderr_full or "HF_HUB_OFFLINE" in stderr_full:
        err_msg = (
            f"Chưa có file checkpoint của model '{job_type}' trong thư mục models/. "
            "Hãy khởi động server với 'HF_HUB_OFFLINE=0 ./run_chatterbox_api.sh' để hệ thống tự động tải model."
        )
        return False, err_msg, None

    clean_err = stderr_full.split("\n")[-1] if stderr_full else f"Mã thoát {rc}"
    return False, f"Lỗi sinh âm thanh (Mã {rc}): {clean_err}", None
