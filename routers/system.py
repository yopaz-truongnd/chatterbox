"""System health, diagnostics, settings validation, and models status router."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings_manager
from utils.platform_tools import detect_full_diagnostics, detect_system_profile

router = APIRouter(tags=["system"])

MODEL_NAMES = ("standard", "turbo", "nano", "multilingual", "voice-conversion")


class SettingsUpdateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: Literal["auto", "cuda", "mps", "cpu"] | None = None
    device_preference: Literal["auto", "cuda", "mps", "cpu"] | None = None
    default_model: Literal["auto", "nano", "turbo", "standard", "multilingual"] | None = None
    default_startup_model: str | None = None
    retention_days: int | None = Field(default=None, ge=1, le=30)
    cpu_threads: int | None = Field(default=None, ge=1, le=32)
    cpu_threads_limit: int | None = Field(default=None, ge=1, le=32)
    export_dir: str | None = None
    audio_format: Literal["wav", "mp3", "flac", "ogg"] | None = None
    dark_mode: bool | None = None
    auto_open_export_dir: bool | None = None
    desktop_notifications: bool | None = None
    confirm_delete_history: bool | None = None
    custom_accent_color: str | None = Field(default=None, max_length=20)


@router.get("/health")
@router.get("/api/v1/health")
def get_health() -> dict:
    from api_app import CPU_THREADS, DEVICE, PROJECT_DIR, RECOMMENDED_MODEL, SYSTEM_PROFILE, job_manager

    models_dir = PROJECT_DIR / "models"
    return {
        "status": "ok",
        "device": DEVICE,
        "cpu_threads": CPU_THREADS,
        "total_ram_gb": SYSTEM_PROFILE["total_ram_gb"],
        "recommended_model": RECOMMENDED_MODEL,
        "default_model": RECOMMENDED_MODEL,
        "recommendation_reason": SYSTEM_PROFILE.get("reason", ""),
        "queue_size": job_manager._job_queue.qsize() if job_manager else 0,
        "processing": len(job_manager._active_procs) if job_manager else 0,
        "models_cached": {
            "nano": (models_dir / "models--ResembleAI--chatterbox-nano").exists(),
            "turbo": (models_dir / "models--ResembleAI--chatterbox-turbo").exists(),
            "standard": (models_dir / "models--ResembleAI--chatterbox").exists(),
            "multilingual": (models_dir / "models--ResembleAI--chatterbox-multilingual").exists(),
        },
    }


@router.get("/api/v1/diagnostics")
@router.get("/api/v1/system/diagnostics")
def get_diagnostics() -> dict:
    from api_app import PROJECT_DIR
    return detect_full_diagnostics(os.getenv("CHATTERBOX_DEVICE", "auto"), PROJECT_DIR)


@router.get("/api/v1/models", tags=["models"])
def list_models() -> dict:
    from api_app import PROJECT_DIR
    models_dir = PROJECT_DIR / "models"
    return {
        "models": [
            {
                "name": name,
                "cached_on_disk": (
                    (models_dir / f"models--ResembleAI--chatterbox-{name}").exists()
                    if name in {"turbo", "nano", "multilingual"}
                    else (models_dir / "models--ResembleAI--chatterbox").exists()
                ),
            }
            for name in MODEL_NAMES
        ]
    }


@router.get("/api/v1/settings", tags=["settings"])
def get_settings() -> dict:
    return {"settings": settings_manager.settings}


@router.post("/api/v1/settings", tags=["settings"])
def update_settings(payload: SettingsUpdateModel) -> dict:
    clean_data = payload.model_dump(exclude_unset=True)
    restart_required_keys = {
        "device", "device_preference", "default_model", "default_startup_model",
        "retention_days", "cpu_threads", "cpu_threads_limit"
    }
    restart_required = any(k in clean_data for k in restart_required_keys)

    # Apply via settings_manager which handles migration/aliasing
    for k, v in clean_data.items():
        settings_manager.set(k, v)
    settings_manager.save()

    msg = (
        "Cài đặt đã được lưu thành công. Vui lòng khởi động lại server API để áp dụng các thay đổi phần cứng / thiết bị."
        if restart_required
        else "Cài đặt đã được lưu thành công."
    )
    return {
        "status": "ok",
        "restart_required": restart_required,
        "message": msg,
        "settings": settings_manager.settings,
    }


@router.post("/api/v1/system/clean-tmp", tags=["system"])
def clean_temp_dir() -> dict:
    from api_app import API_DATA_DIR, PROJECT_DIR, job_manager
    count = 0
    size_bytes = 0

    # 1. Clean API data inputs and chunks
    target_dirs = [API_DATA_DIR / "inputs", API_DATA_DIR / "chunks", PROJECT_DIR / "tmp"]
    for d in target_dirs:
        if d.exists():
            for f in d.glob("**/*"):
                if f.is_file() and not f.name.startswith("."):
                    try:
                        size_bytes += f.stat().st_size
                        f.unlink(missing_ok=True)
                        count += 1
                    except Exception:
                        pass

    # 2. Trigger SQLite expired jobs TTL cleanup
    if job_manager:
        del_jobs, freed_db_bytes = job_manager.store.cleanup_expired(retention_days=1)
        count += del_jobs
        size_bytes += freed_db_bytes

    return {"status": "ok", "deleted_files": count, "freed_bytes": size_bytes}
