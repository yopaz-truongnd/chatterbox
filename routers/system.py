"""System health, diagnostics, settings validation, benchmarks, and models status router."""

from __future__ import annotations

import gc
import os
import shutil
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from config.settings import settings_manager
from services.model_registry import (
    MODEL_NAMES,
    MODEL_REGISTRY,
    check_model_preflight,
    get_model_disk_size_bytes,
    is_model_cached,
    is_multilingual_cached,
    list_registered_models,
    resolve_model_id,
)
from services.model_runtime import model_runtime
from utils.platform_tools import clear_accelerator_cache, detect_full_diagnostics, detect_system_profile

router = APIRouter(tags=["system"])


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
    active_loaded = model_runtime.active_model_name
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
            "nano": is_model_cached("nano", models_dir),
            "turbo": is_model_cached("turbo", models_dir),
            "standard": is_model_cached("standard", models_dir),
            "multilingual": is_multilingual_cached(models_dir),
        },
        "loaded_model": active_loaded,
        "active_cache_key": model_runtime.active_cache_key,
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
    active_loaded = model_runtime.active_model_name
    result = list_registered_models(models_dir=models_dir, active_model=active_loaded)
    return {
        "models": result,
        "active_model": active_loaded,
        "active_cache_key": model_runtime.active_cache_key,
    }


@router.get("/api/v1/models/preflight", tags=["models"])
def preflight_all_models() -> dict:
    """Preflight integrity check for all registered models."""
    from api_app import PROJECT_DIR
    models_dir = PROJECT_DIR / "models"
    reports = [check_model_preflight(name, models_dir) for name in MODEL_NAMES]
    all_ready = all(r["valid"] for r in reports if r["cached"])
    return {
        "status": "ok",
        "all_ready": all_ready,
        "models": reports,
    }


@router.get("/api/v1/models/{name}/preflight", tags=["models"])
def preflight_single_model(name: str) -> dict:
    """Preflight integrity check for a specific model before launching inference."""
    from api_app import PROJECT_DIR
    models_dir = PROJECT_DIR / "models"
    report = check_model_preflight(name, models_dir)
    return report


@router.delete("/api/v1/models/{name}/disk", tags=["models"])
def delete_model_from_disk_endpoint(name: str) -> dict:
    from api_app import PROJECT_DIR

    model_name = resolve_model_id(name)
    if model_name not in MODEL_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Tên mô hình không hợp lệ: '{name}'. Danh sách mô hình hỗ trợ: {', '.join(MODEL_NAMES)}",
        )

    models_dir = PROJECT_DIR / "models"
    freed_bytes = get_model_disk_size_bytes(model_name, models_dir)

    # 1. Unload from RAM/VRAM if currently loaded
    model_runtime.unload_model(model_name)

    # 2. Remove files from models_dir
    deleted_items = 0
    if model_name in {"nano", "turbo"}:
        target_dir = models_dir / f"models--ResembleAI--chatterbox-{model_name}"
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
            deleted_items += 1
    elif model_name == "multilingual":
        target_dir = models_dir / "models--ResembleAI--chatterbox-multilingual"
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
            deleted_items += 1
        chatterbox_dir = models_dir / "models--ResembleAI--chatterbox"
        if chatterbox_dir.exists():
            for p in list(chatterbox_dir.glob("**/*")):
                if p.is_file() and any(k in p.name for k in ("t3_mtl", "grapheme_mtl", "Cangjie")):
                    try:
                        p.unlink(missing_ok=True)
                        deleted_items += 1
                    except Exception:
                        pass
    elif model_name in {"standard", "voice-conversion"}:
        target_dir = models_dir / "models--ResembleAI--chatterbox"
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
            deleted_items += 1

    freed_mb = round(freed_bytes / (1024 * 1024), 2)
    return {
        "status": "ok",
        "message": f"Đã xóa toàn bộ checkpoint của mô hình {model_name.upper()} khỏi ổ đĩa (đã giải phóng {freed_mb} MB).",
        "model": model_name,
        "freed_bytes": freed_bytes,
        "freed_mb": freed_mb,
    }


@router.post("/api/v1/models/{name}/load", tags=["models"])
def preload_model_endpoint(name: str) -> dict:
    from api_app import DEVICE, PROJECT_DIR

    model_name = resolve_model_id(name)
    if model_name not in MODEL_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Tên mô hình không hợp lệ: '{name}'. Danh sách mô hình hỗ trợ: {', '.join(MODEL_NAMES)}",
        )

    models_dir = PROJECT_DIR / "models"
    is_offline = os.getenv("HF_HUB_OFFLINE", "1") == "1"

    # Check disk cache availability
    if not is_model_cached(model_name, models_dir) and is_offline:
        if model_name == "multilingual":
            raise HTTPException(
                status_code=404,
                detail=(
                    "Mô hình Multilingual chưa được tải về máy. "
                    "Vui lòng khởi động server với kết nối mạng bằng lệnh 'HF_HUB_OFFLINE=0 ./run_chatterbox_api.sh' để tự động tải mô hình từ Hugging Face."
                ),
            )
        raise HTTPException(
            status_code=404,
            detail=f"Mô hình {model_name.upper()} chưa có trong thư mục models/.",
        )

    try:
        model_runtime.load_model(model_name, device=DEVICE, keep_in_cache=True)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Lỗi khi nạp mô hình '{model_name}': {str(e)}",
        )

    return {
        "status": "ok",
        "message": f"Mô hình '{model_name.upper()}' đã được nạp sẵn sàng vào bộ nhớ ({DEVICE.upper()}).",
        "model": model_name,
        "device": DEVICE,
        "cache_key": model_runtime.active_cache_key,
    }


@router.delete("/api/v1/models/{name}", tags=["models"])
def unload_model_endpoint(name: str) -> dict:
    model_name = resolve_model_id(name)
    if model_name not in MODEL_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Tên mô hình không hợp lệ: '{name}'. Danh sách mô hình hỗ trợ: {', '.join(MODEL_NAMES)}",
        )

    model_runtime.unload_model(model_name)

    return {
        "status": "ok",
        "message": f"Đã giải phóng mô hình '{model_name.upper()}' khỏi bộ nhớ RAM/VRAM.",
        "model": model_name,
    }


@router.get("/api/v1/benchmarks", tags=["benchmarks"])
def list_benchmarks_endpoint(
    model: Annotated[str | None, Query(description="Filter by model ID")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """Retrieve historical inference benchmark performance metrics."""
    from api_app import job_manager
    if not job_manager or not job_manager.store:
        return {"benchmarks": [], "count": 0}

    results = job_manager.store.list_benchmarks(model=model, limit=limit)
    return {"benchmarks": results, "count": len(results)}


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

    if job_manager:
        active_count = len(job_manager._active_procs) + job_manager._job_queue.qsize()
        if active_count > 0:
            raise HTTPException(
                status_code=409,
                detail=f"Không thể dọn dẹp thư mục tạm vì đang có {active_count} tác vụ đang xử lý hoặc trong hàng đợi.",
            )

    count = 0
    size_bytes = 0

    target_dirs = [API_DATA_DIR / "inputs", API_DATA_DIR / "chunks", PROJECT_DIR / "tmp"]
    for d in target_dirs:
        if d.exists():
            for f in d.glob("**/*"):
                if f.is_file() and not f.name.startswith(".") and not f.name.endswith(".db") and f.name != "jobs.db":
                    try:
                        size_bytes += f.stat().st_size
                        f.unlink(missing_ok=True)
                        count += 1
                    except Exception:
                        pass

    if job_manager:
        del_jobs, freed_db_bytes = job_manager.store.cleanup_expired(retention_days=1)
        count += del_jobs
        size_bytes += freed_db_bytes

    return {"status": "ok", "deleted_files": count, "freed_bytes": size_bytes}
