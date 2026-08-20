"""Small cross-platform helpers shared by desktop, API, and demos."""

import os
import subprocess
import sys
from pathlib import Path

import torch


def select_device(preference="auto"):
    """Return the requested available accelerator, or the best fallback."""
    if preference == "cpu":
        return "cpu"
    if preference in ("auto", "cuda") and torch.cuda.is_available():
        return "cuda"
    if preference in ("auto", "cuda", "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def clear_accelerator_cache():
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    elif torch.backends.mps.is_available():
        torch.mps.empty_cache()


def open_folder(path):
    """Open a directory with the operating system's file manager."""
    folder = str(Path(path))
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])


def primary_shortcut():
    """Return Tk's primary modifier and its user-facing label."""
    return ("Command", "⌘") if sys.platform == "darwin" else ("Control", "Ctrl")


def get_system_ram_gb() -> float:
    """Return total system RAM in gigabytes."""
    try:
        if sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=2)
            return round(int(out.decode().strip()) / (1024 ** 3), 1)
        elif sys.platform == "linux":
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 ** 2), 1)
    except Exception:
        pass
    return 16.0


def detect_system_profile(preference: str = "auto") -> dict:
    """Analyze system hardware and provide optimal model & device recommendations."""
    device = select_device(preference)
    ram_gb = get_system_ram_gb()
    
    # Recommend nano for CPU or <= 16GB RAM devices to avoid OOM
    if device == "cpu" or ram_gb <= 16.0:
        recommended_model = "nano"
        reason = "Hệ thống có RAM ≤ 16GB hoặc chạy CPU: Khuyên dùng model Nano để đảm bảo tốc độ và tránh tràn RAM (OOM)."
    elif device == "cuda":
        recommended_model = "turbo"
        reason = "Phát hiện GPU NVIDIA CUDA: Model Turbo hoạt động với hiệu năng tối đa."
    else:
        recommended_model = "turbo"
        reason = "Hệ thống Apple Silicon MPS: Model Turbo/Nano được hỗ trợ tốt."

    return {
        "device": device,
        "total_ram_gb": ram_gb,
        "recommended_model": recommended_model,
        "reason": reason,
    }

