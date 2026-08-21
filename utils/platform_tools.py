"""Cross-platform hardware profiler, path manager, and device selector for Chatterbox.

Supports Windows 10/11, macOS (Apple Silicon MPS / Intel), and Linux (CUDA / CPU).
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import torch


def select_device(preference: str = "auto") -> str:
    """Return the requested available accelerator, or the best platform-appropriate fallback.
    
    Priority order:
      - Explicit preference (cpu, cuda, mps) if available.
      - Windows / Linux: 'cuda' if NVIDIA GPU available, else 'cpu'.
      - macOS: 'mps' if Apple Silicon Metal available, else 'cpu'.
    """
    pref = preference.lower().strip()
    
    if pref == "cpu":
        return "cpu"
    if pref == "cuda" and torch.cuda.is_available():
        return "cuda"
    if pref == "mps" and hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"

    # Auto-detection
    if sys.platform == "darwin":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    
    # Windows & Linux
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def clear_accelerator_cache() -> None:
    """Safely release GPU/MPS memory back to the OS."""
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        try:
            torch.mps.empty_cache()
        except Exception:
            pass


def get_default_data_dir() -> Path:
    """Return platform-standard persistent data directory for Chatterbox.
    
    - Windows: %LOCALAPPDATA%\\Chatterbox\\data (e.g. C:\\Users\\<user>\\AppData\\Local\\Chatterbox\\data)
    - macOS: ~/Library/Application Support/Chatterbox
    - Linux: ~/.local/share/chatterbox
    - Fallback/Override: CHATTERBOX_API_DATA_DIR or <project>/tmp/api
    """
    env_dir = os.getenv("CHATTERBOX_API_DATA_DIR") or os.getenv("CHATTERBOX_DATA_DIR")
    if env_dir:
        return Path(env_dir).resolve()

    home = Path.home()
    if sys.platform == "win32":
        local_app_data = os.getenv("LOCALAPPDATA", str(home / "AppData" / "Local"))
        return Path(local_app_data) / "Chatterbox" / "data"
    elif sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Chatterbox"
    else:
        xdg_data = os.getenv("XDG_DATA_HOME", str(home / ".local" / "share"))
        return Path(xdg_data) / "chatterbox"


def open_folder(path: str | Path) -> None:
    """Open a directory with the operating system's native file manager."""
    folder = str(Path(path).resolve())
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])


def primary_shortcut() -> tuple[str, str]:
    """Return platform's primary keyboard modifier and its display symbol."""
    return ("Command", "⌘") if sys.platform == "darwin" else ("Control", "Ctrl")


def get_system_ram_gb() -> tuple[float, float | None]:
    """Return (total_ram_gb, available_ram_gb) across Windows, macOS, and Linux."""
    total_gb = 16.0
    avail_gb = None

    try:
        if sys.platform == "win32":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                total_gb = round(stat.ullTotalPhys / (1024 ** 3), 1)
                avail_gb = round(stat.ullAvailPhys / (1024 ** 3), 1)
                return total_gb, avail_gb

        elif sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=2)
            total_gb = round(int(out.decode().strip()) / (1024 ** 3), 1)
            return total_gb, None

        elif sys.platform == "linux":
            with open("/proc/meminfo", "r") as f:
                mem_info = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        mem_info[parts[0].rstrip(":")] = int(parts[1])
                if "MemTotal" in mem_info:
                    total_gb = round(mem_info["MemTotal"] / (1024 ** 2), 1)
                if "MemAvailable" in mem_info:
                    avail_gb = round(mem_info["MemAvailable"] / (1024 ** 2), 1)
                return total_gb, avail_gb
    except Exception:
        pass

    return total_gb, avail_gb


def check_ffmpeg_available() -> tuple[bool, str | None]:
    """Check if FFmpeg binary is available on the system PATH."""
    path = shutil.which("ffmpeg")
    if path:
        return True, None

    if sys.platform == "win32":
        instruction = "Cài đặt FFmpeg trên Windows bằng lệnh: winget install Gyan.FFmpeg hoặc tải từ https://www.gyan.dev/ffmpeg/builds/"
    elif sys.platform == "darwin":
        instruction = "Cài đặt FFmpeg trên macOS bằng lệnh: brew install ffmpeg"
    else:
        instruction = "Cài đặt FFmpeg trên Linux bằng lệnh: sudo apt install ffmpeg"
    return False, instruction


def is_port_available(host: str = "127.0.0.1", port: int = 8000) -> bool:
    """Check if TCP port is available without relying on external shell commands."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            s.bind((host, port))
            return True
    except OSError:
        return False


def get_gpu_info() -> dict:
    """Return GPU and VRAM details if CUDA is available."""
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_bytes = torch.cuda.get_device_properties(0).total_memory
        vram_gb = round(vram_bytes / (1024 ** 3), 1)
        cuda_ver = torch.version.cuda or "N/A"
        return {
            "cuda_available": True,
            "gpu_name": gpu_name,
            "vram_gb": vram_gb,
            "cuda_version": cuda_ver,
            "device_count": torch.cuda.device_count(),
        }
    return {
        "cuda_available": False,
        "gpu_name": None,
        "vram_gb": None,
        "cuda_version": None,
        "device_count": 0,
    }


def detect_system_profile(preference: str = "auto") -> dict:
    """Analyze system hardware, OS, accelerator, and select optimal default model."""
    device = select_device(preference)
    total_ram_gb, avail_ram_gb = get_system_ram_gb()
    gpu_info = get_gpu_info()

    warnings = []

    # Check for NVIDIA card with CPU-only torch build
    if sys.platform in ("win32", "linux") and not gpu_info["cuda_available"]:
        if "+cpu" in torch.__version__:
            nvidia_smi = shutil.which("nvidia-smi")
            if nvidia_smi:
                warnings.append(
                    "Máy có card NVIDIA nhưng PyTorch đang cài là bản CPU-only. "
                    "Hãy cài lại bản CUDA để tăng tốc: pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124"
                )

    # Resource-aware model recommendation
    if device == "cuda" and gpu_info.get("vram_gb", 0) >= 6.0:
        recommended_model = "turbo"
        reason = f"Phát hiện NVIDIA GPU ({gpu_info['gpu_name']} • {gpu_info['vram_gb']}GB VRAM): Đủ tài nguyên để chạy Turbo & Standard mượt mà."
    elif device == "cuda":
        recommended_model = "nano"
        reason = f"NVIDIA GPU có VRAM < 6GB ({gpu_info.get('vram_gb', 0)}GB): Khuyên dùng model Nano để đảm bảo ổn định."
    elif total_ram_gb <= 16.0 or device == "cpu":
        recommended_model = "nano"
        reason = "Hệ thống có RAM ≤ 16GB hoặc chạy CPU: Khuyên dùng model Nano (110M) để đảm bảo tốc độ và tránh tràn RAM (OOM)."
    else:
        recommended_model = "turbo"
        reason = f"Hệ thống có {total_ram_gb}GB RAM: Đủ tài nguyên chạy model Turbo."

    return {
        "device": device,
        "total_ram_gb": total_ram_gb,
        "available_ram_gb": avail_ram_gb,
        "recommended_model": recommended_model,
        "reason": reason,
        "gpu_info": gpu_info,
        "warnings": warnings,
    }


def is_multilingual_cached(models_dir: Path) -> bool:
    if (models_dir / "models--ResembleAI--chatterbox-multilingual").exists():
        return True
    chatterbox_dir = models_dir / "models--ResembleAI--chatterbox"
    if chatterbox_dir.exists():
        for ext in ("*.safetensors", "*.pt"):
            for f in chatterbox_dir.glob(f"**/{ext}"):
                if "t3_mtl" in f.name:
                    return True
    return False


def detect_full_diagnostics(preference: str = "auto", project_dir: Path | None = None) -> dict:
    """Generate comprehensive cross-platform diagnostic report for debugging & health checks."""
    profile = detect_system_profile(preference)
    ffmpeg_ok, ffmpeg_hint = check_ffmpeg_available()
    data_dir = get_default_data_dir()

    if project_dir is None:
        project_dir = Path(__file__).resolve().parent.parent

    models_dir = project_dir / "models"
    checkpoints = {
        "nano": (models_dir / "models--ResembleAI--chatterbox-nano").exists(),
        "turbo": (models_dir / "models--ResembleAI--chatterbox-turbo").exists(),
        "standard": (models_dir / "models--ResembleAI--chatterbox").exists(),
        "multilingual": is_multilingual_cached(models_dir),
    }

    os_name = f"{platform.system()} {platform.release()}"
    if sys.platform == "win32":
        os_name = f"Windows {platform.release()}"
    elif sys.platform == "darwin":
        os_name = f"macOS {platform.mac_ver()[0]}"

    return {
        "os": os_name,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "torch": torch.__version__,
        "device": profile["device"],
        "gpu_name": profile["gpu_info"]["gpu_name"],
        "vram_gb": profile["gpu_info"]["vram_gb"],
        "cuda_version": profile["gpu_info"]["cuda_version"],
        "ram_total_gb": profile["total_ram_gb"],
        "ram_available_gb": profile["available_ram_gb"],
        "recommended_model": profile["recommended_model"],
        "recommendation_reason": profile["reason"],
        "ffmpeg_available": ffmpeg_ok,
        "ffmpeg_hint": ffmpeg_hint,
        "data_dir": str(data_dir),
        "checkpoints": checkpoints,
        "warnings": profile["warnings"],
    }
