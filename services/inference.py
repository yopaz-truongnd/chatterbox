"""Single canonical inference service and isolated process execution for Chatterbox."""

from __future__ import annotations

import copy
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch
import torchaudio as ta

from services.model_registry import resolve_model_id
from services.model_runtime import model_runtime
from services.synthesis import set_synthesis_seed, synthesize_chunk_tensor
from utils.platform_tools import clear_accelerator_cache, select_device

logger = logging.getLogger("chatterbox.inference")


def set_inference_seed(seed: int, device: str) -> None:
    set_synthesis_seed(seed, device)


def load_model(job_type: str, device: str) -> tuple[Any, int]:
    """Load model once and return (model_instance, sample_rate)."""
    return model_runtime.load_model(job_type, device=device)


def generate_with_model(model: Any, job_type: str, params: dict, device: str) -> torch.Tensor:
    """Generate audio waveform tensor using an already-loaded model instance."""
    if os.environ.get("CHATTERBOX_TEST_DUMMY_INFERENCE") == "1":
        if hasattr(model, "generate"):
            try:
                model_id = resolve_model_id(job_type)
                return synthesize_chunk_tensor(model, model_id, params.get("text", ""), params, device)
            except Exception:
                t = torch.linspace(0, 1.0, 24000)
                return (0.177 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)
        t = torch.linspace(0, 1.0, 24000)
        return (0.177 * torch.sin(2 * 3.14159 * 440 * t)).unsqueeze(0)

    seed = int(params.get("seed", 0) or 0)
    set_inference_seed(seed, device)

    # Convert legacy "tts" to "standard" if needed
    model_id = resolve_model_id(job_type)
    return synthesize_chunk_tensor(model, model_id, params.get("text", ""), params, device)


def execute_model_inference(job_type: str, params: dict, device: str) -> tuple[torch.Tensor, int]:
    """Single canonical model inference implementation used by both isolated runner and test harnesses."""
    model, sr = load_model(job_type, device)
    wav = generate_with_model(model, job_type, params, device)
    return wav, sr


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
    line_progress_callback: Callable[[dict], None] | None = None,
    benchmark_callback: Callable[[dict], None] | None = None,
    register_proc_callback: Callable[[str, subprocess.Popen], None] | None = None,
    unregister_proc_callback: Callable[[str], None] | None = None,
) -> tuple[bool, str | None, dict | None]:
    """Execute inference inside an isolated subprocess with inactivity deadline enforcement and non-blocking stream reading."""
    configs_dir = data_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)
    config_file = configs_dir / f"{job_id}.json"

    meta_path = data_dir / "outputs" / f"{job_id}.json"
    config: dict[str, Any] = {
        "type": job_type,
        "params": params,
        "output_path": str(output_path),
        "meta_path": str(meta_path),
        "device": device,
        "cpu_threads": cpu_threads,
    }

    # Pass all batch & post-processing settings to config top-level
    for key in (
        "lines",
        "model",
        "chunks_dir",
        "merge",
        "pause_duration",
        "pause_durations",
        "bgm_audio_path",
        "bgm_volume",
        "export_srt",
        "normalize_loudness",
        "crossfade_ms",
        "bgm_ducking",
        "stop_on_error",
        "keep_original_timeline",
        "resume",
    ):
        if key in params:
            config[key] = params[key]

    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    runner_script = project_dir / "inference_runner.py"

    cmd = [
        sys.executable,
        str(runner_script),
        "--config",
        str(config_file),
    ]

    # Cross-platform environment with os.pathsep
    env = os.environ.copy()
    env["HF_HUB_CACHE"] = str(project_dir / "models")
    env["PYTHONIOENCODING"] = "utf-8"
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_dir = str(project_dir / "src")
    env["PYTHONPATH"] = (src_dir + os.pathsep + existing_pythonpath) if existing_pythonpath else src_dir

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
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
    inactivity_timeout = float(timeout_seconds)
    hard_timeout = float(os.getenv("CHATTERBOX_MAX_JOB_TIMEOUT", "21600"))  # 6 hours
    start_time = time.monotonic()
    last_activity = time.monotonic()
    timed_out = False
    timeout_reason = ""

    try:
        while True:
            now = time.monotonic()
            # Check hard maximum job timeout
            if (now - start_time) > hard_timeout:
                timed_out = True
                timeout_reason = f"Vượt quá tổng thời gian xử lý tối đa cho phép ({int(hard_timeout)}s)."
                try:
                    proc.terminate()
                    time.sleep(1.0)
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                break

            # Check inactivity timeout (no new progress for inactivity_timeout seconds)
            if (now - last_activity) > inactivity_timeout:
                timed_out = True
                timeout_reason = f"Quá thời gian chờ phản hồi (Inactivity timeout {int(inactivity_timeout)}s không có tiến trình mới)."
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
                # Progress or output arrived - reset inactivity timer
                last_activity = time.monotonic()
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
                elif line_str.startswith("LINE_PROGRESS:"):
                    try:
                        lpdata = json.loads(line_str[14:])
                        if line_progress_callback:
                            line_progress_callback(lpdata)
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
        try:
            config_file.unlink(missing_ok=True)
        except Exception:
            pass

    if timed_out:
        return False, timeout_reason or f"Quá thời gian xử lý cho phép (Timeout {timeout_seconds}s).", None

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
