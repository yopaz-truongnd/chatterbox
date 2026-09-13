"""Technical metrics used by production validation reports."""

from __future__ import annotations

from datetime import datetime
import math
import os
from pathlib import Path
import platform
import resource
import struct
from typing import Any
import wave


def _sanitize_path(path_str: str | Path, base_dir: Path | None = None) -> str:
    """Sanitize absolute filesystem path into clean relative path for reports."""
    path = Path(path_str)
    if base_dir:
        try:
            return str(path.relative_to(base_dir))
        except ValueError:
            pass
    if "projects" in path.parts:
        return "/".join(path.parts[path.parts.index("projects"):])
    return path.name


def _get_machine_summary() -> dict[str, Any]:
    """Capture sanitized host machine details without private credentials."""
    summary: dict[str, Any] = {
        "os": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "machine": platform.machine(),
    }
    try:
        import torch
        summary["cuda_available"] = torch.cuda.is_available()
        summary["mps_available"] = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        if torch.cuda.is_available():
            summary["gpu_name"] = torch.cuda.get_device_name(0)
            summary["gpu_count"] = torch.cuda.device_count()
    except Exception:
        summary["cuda_available"] = False
        summary["mps_available"] = False
    return summary


def _get_peak_memory_mb() -> float:
    """Measure peak process memory in megabytes."""
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
        return round(usage / divisor, 2)
    except Exception:
        return 0.0


def _workflow_step_duration_ms(step: Any) -> float:
    """Return persisted wall-clock duration for a completed workflow step."""
    if not step or not step.started_at or not step.completed_at:
        return 0.0
    try:
        started = datetime.fromisoformat(step.started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(step.completed_at.replace("Z", "+00:00"))
        return round(max(0.0, (completed - started).total_seconds() * 1000.0), 1)
    except (TypeError, ValueError):
        return 0.0


def _project_artifact_path(project_dir: Path, stored_path: str | Path) -> Path:
    """Resolve manifest paths that may be absolute, cwd-relative, or project-relative."""
    path = Path(stored_path)
    return path if path.is_absolute() or path.exists() else project_dir / path


def _inspect_audio_wave(wav_path: Path) -> dict[str, Any]:
    """Inspect and measure technical properties of a WAV file."""
    if not wav_path.exists() or wav_path.stat().st_size == 0:
        return {"valid": False, "error": "File missing or empty"}
    try:
        with wave.open(str(wav_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            framerate = wav_file.getframerate()
            frames = wav_file.getnframes()
            if frames == 0:
                return {"valid": False, "error": "Zero frames in audio"}
            raw_bytes = wav_file.readframes(frames)

        peak = sum_sq = 0.0
        clipping = max_silent_run = silent_run = 0
        samples = ()
        if sample_width == 2:
            count = len(raw_bytes) // 2
            samples = struct.unpack(f"<{count}h", raw_bytes[:count * 2])
            for sample in samples:
                normalized = abs(sample) / 32768.0
                peak = max(peak, normalized)
                clipping += normalized >= 0.999
                sum_sq += normalized * normalized
                silent_run = silent_run + 1 if normalized < 0.005 else 0
                max_silent_run = max(max_silent_run, silent_run)

        rms = (sum_sq / len(samples)) ** 0.5 if samples else 0.0
        return {
            "valid": True,
            "duration_ms": round(frames / framerate * 1000.0, 1) if framerate else 0.0,
            "sample_rate": framerate,
            "channels": channels,
            "sample_width": sample_width,
            "peak_amplitude": round(peak, 4),
            "clipping_count": clipping,
            "approx_lufs": round(20 * math.log10(max(rms, 1e-6)) - 0.5, 2),
            "max_silence_s": round(max_silent_run / (framerate * channels), 2) if framerate else 0.0,
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc)}
