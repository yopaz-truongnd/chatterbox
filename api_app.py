"""Chatterbox TTS Studio - FastAPI Server & Modular REST API v1.4.0."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
os.environ["HF_HUB_CACHE"] = str(PROJECT_DIR / "models")

import torch
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import character_api
from routers import jobs, system, tts
from services.job_manager import JobManager
from utils.platform_tools import detect_system_profile, get_default_data_dir, is_multilingual_cached

# 1. System & Hardware Profiling
SYSTEM_PROFILE = detect_system_profile(os.getenv("CHATTERBOX_DEVICE", "auto"))
DEVICE = SYSTEM_PROFILE["device"]
RECOMMENDED_MODEL = SYSTEM_PROFILE["recommended_model"]
CPU_THREADS = int(os.getenv("CHATTERBOX_API_CPU_THREADS", "2"))
torch.set_num_threads(CPU_THREADS)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass

WEBUI_DIR = PROJECT_DIR / "webui"
API_DATA_DIR = Path(os.getenv("CHATTERBOX_API_DATA_DIR", str(get_default_data_dir())))
MAX_UPLOAD_BYTES = int(os.getenv("CHATTERBOX_API_MAX_UPLOAD_BYTES", 20 * 1024 * 1024))
JOB_TIMEOUT_SECONDS = int(os.getenv("CHATTERBOX_JOB_TIMEOUT", "240"))
RETENTION_DAYS = int(os.getenv("CHATTERBOX_JOB_RETENTION_DAYS", "3"))

# 2. Central Job Manager
job_manager: JobManager | None = None


def print_startup_banner() -> None:
    models_dir = PROJECT_DIR / "models"
    nano_cached = (models_dir / "models--ResembleAI--chatterbox-nano").exists()
    turbo_cached = (models_dir / "models--ResembleAI--chatterbox-turbo").exists()
    std_cached = (models_dir / "models--ResembleAI--chatterbox").exists()
    mtl_cached = is_multilingual_cached(models_dir)

    dev_label = (
        "Apple Metal (MPS)" if DEVICE == "mps"
        else f"NVIDIA CUDA ({SYSTEM_PROFILE['gpu_info']['gpu_name']})" if DEVICE == "cuda"
        else f"CPU ({CPU_THREADS} Threads)"
    )

    print("\n" + "=" * 72)
    print("  🎙️  CHATTERBOX TTS STUDIO & REST API v1.4.0")
    print("=" * 72)
    print(f"  🔍 Hệ thống:          {sys.platform} ({torch.__version__}) | RAM: {SYSTEM_PROFILE['total_ram_gb']} GB")
    print(f"  🎮 Bộ tăng tốc:       {dev_label}")
    print(f"  ⚡ Model mặc định:    {RECOMMENDED_MODEL.upper()} (Tự động tối ưu theo phần cứng)")
    print(f"  📦 Tình trạng Checkpoints trong models/:")
    print(f"     • Nano (110M):       {'✅ Sẵn sàng (Siêu nhẹ, an toàn RAM)' if nano_cached else '❌ Chưa tải'}")
    print(f"     • Turbo (350M):      {'✅ Sẵn sàng (Hỗ trợ Paralinguistic tags)' if turbo_cached else '❌ Chưa tải'}")
    print(f"     • Standard (500M):   {'✅ Sẵn sàng (Chất lượng cao)' if std_cached else '❌ Chưa tải'}")
    print(f"     • Multilingual:      {'✅ Sẵn sàng (23+ thứ tiếng)' if mtl_cached else '❌ Chưa tải'}")
    print(f"  📁 Thư mục xuất Audio: {API_DATA_DIR / 'outputs'}")
    print(f"  💾 Cơ sở dữ liệu:     {API_DATA_DIR / 'jobs.db'} (Tự động dọn dẹp TTL: {RETENTION_DAYS} ngày)")
    print(f"  🌐 Web GUI Studio:    http://127.0.0.1:8000/")
    print(f"  📖 Swagger API Docs:  http://127.0.0.1:8000/docs")
    print("=" * 72 + "\n")


@asynccontextmanager
async def lifespan(_: FastAPI):
    global job_manager
    job_manager = JobManager(
        data_dir=API_DATA_DIR,
        project_dir=PROJECT_DIR,
        device=DEVICE,
        cpu_threads=CPU_THREADS,
        timeout_seconds=JOB_TIMEOUT_SECONDS,
    )
    job_manager.startup()
    character_api.configure_storage(API_DATA_DIR)

    # Clean expired records and orphaned files (TTL)
    deleted, freed = job_manager.store.cleanup_expired(retention_days=RETENTION_DAYS)
    if deleted > 0:
        print(f"[JobStore] 🧹 Đã dọn dẹp {deleted} job cũ quá {RETENTION_DAYS} ngày (Giải phóng {round(freed / (1024*1024), 2)} MB).")

    print_startup_banner()
    try:
        yield
    finally:
        if job_manager:
            job_manager.shutdown()


# 3. FastAPI App Initialization
app = FastAPI(
    title="Chatterbox TTS API & Web Studio",
    version="1.4.0",
    description="Local API & Web GUI cho Chatterbox TTS, Turbo, Nano, Multilingual, Long-Text và Voice Conversion.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Mount Modular Routers
app.include_router(character_api.router)
app.include_router(system.router)
app.include_router(tts.router)
app.include_router(jobs.router)

if WEBUI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEBUI_DIR)), name="static")


@app.get("/", response_class=FileResponse, tags=["gui"])
@app.get("/gui", response_class=FileResponse, tags=["gui"])
@app.get("/tts-studio", response_class=FileResponse, tags=["gui"])
@app.get("/batch-studio", response_class=FileResponse, tags=["gui"])
@app.get("/multilingual-tts", response_class=FileResponse, tags=["gui"])
@app.get("/voice-clone", response_class=FileResponse, tags=["gui"])
@app.get("/characters-studio", response_class=FileResponse, tags=["gui"])
@app.get("/history-studio", response_class=FileResponse, tags=["gui"])
@app.get("/settings-studio", response_class=FileResponse, tags=["gui"])
def get_web_gui():
    """Phục vụ giao diện Material Design 3 Web Dashboard trực tiếp trên trình duyệt."""
    dashboard_file = WEBUI_DIR / "material_dashboard.html"
    if dashboard_file.exists():
        return FileResponse(dashboard_file, media_type="text/html")
    return HTMLResponse("<h2>Chatterbox Studio Web GUI</h2><p>Đang tải tài nguyên giao diện...</p>")
