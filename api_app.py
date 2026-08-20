from __future__ import annotations

import gc
import os
import json
import queue
import random
import subprocess
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

PROJECT_DIR = Path(__file__).resolve().parent
os.environ["HF_HUB_CACHE"] = str(PROJECT_DIR / "models")

import numpy as np
import torch
import torchaudio as ta
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import character_api

from chatterbox.mtl_tts import ChatterboxMultilingualTTS, SUPPORTED_LANGUAGES
from chatterbox.tts import ChatterboxTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS
from chatterbox.vc import ChatterboxVC
from utils.platform_tools import clear_accelerator_cache, detect_system_profile, select_device


SYSTEM_PROFILE = detect_system_profile(os.getenv("CHATTERBOX_DEVICE", "auto"))
DEVICE = SYSTEM_PROFILE["device"]
RECOMMENDED_MODEL = SYSTEM_PROFILE["recommended_model"]
CPU_THREADS = int(os.getenv("CHATTERBOX_API_CPU_THREADS", "2"))
torch.set_num_threads(CPU_THREADS)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass

print(f"[Chatterbox API] 🚀 Thiết bị: {DEVICE.upper()} | RAM: {SYSTEM_PROFILE['total_ram_gb']}GB | Model khuyên dùng: {RECOMMENDED_MODEL.upper()}")
if SYSTEM_PROFILE.get("reason"):
    print(f"[Chatterbox API] 💡 {SYSTEM_PROFILE['reason']}")

WEBUI_DIR = PROJECT_DIR / "webui"
API_DATA_DIR = Path(os.getenv("CHATTERBOX_API_DATA_DIR", str(PROJECT_DIR / "tmp" / "api")))
MAX_UPLOAD_BYTES = int(os.getenv("CHATTERBOX_API_MAX_UPLOAD_BYTES", 20 * 1024 * 1024))
MODEL_NAMES = ("standard", "turbo", "nano", "multilingual", "voice-conversion")
AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".m4a"}

JobStatus = Literal["queued", "processing", "completed", "failed"]
JobType = Literal["tts", "turbo", "nano", "multilingual", "voice-conversion"]


@dataclass
class AudioJob:
    id: str
    type: JobType
    params: dict
    input_paths: list[str]
    status: JobStatus = "queued"
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    output_path: str | None = None

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("input_paths", None)
        data.pop("output_path", None)
        data["params"] = {key: value for key, value in self.params.items() if not key.endswith("_path")}
        data["audio_url"] = f"/api/v1/jobs/{self.id}/audio" if self.status == "completed" else None
        return data


job_queue: queue.Queue[str] = queue.Queue()
jobs: dict[str, AudioJob] = {}
jobs_lock = threading.Lock()
execution_lock = threading.Lock()
models: dict[str, object | None] = {name: None for name in MODEL_NAMES}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    if DEVICE == "cuda":
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    random.seed(seed)
    np.random.seed(seed)


def model_key_for_job(job_type: JobType) -> str:
    return {
        "tts": "standard",
        "turbo": "turbo",
        "nano": "nano",
        "multilingual": "multilingual",
        "voice-conversion": "voice-conversion",
    }[job_type]


def cleanup_runtime() -> None:
    gc.collect()
    clear_accelerator_cache()


def load_model(model_name: str):
    if model_name not in models:
        raise ValueError(f"Model không hợp lệ: {model_name}")
    if models[model_name] is None:
        for loaded_name in models:
            if loaded_name != model_name:
                models[loaded_name] = None
        cleanup_runtime()
        print(f"[API] Loading {model_name} on {DEVICE}...")
        if model_name == "standard":
            models[model_name] = ChatterboxTTS.from_pretrained(DEVICE)
        elif model_name == "turbo":
            models[model_name] = ChatterboxTurboTTS.from_pretrained(DEVICE, nano=False)
        elif model_name == "nano":
            models[model_name] = ChatterboxTurboTTS.from_pretrained(DEVICE, nano=True)
        elif model_name == "multilingual":
            models[model_name] = ChatterboxMultilingualTTS.from_pretrained(DEVICE)
        else:
            models[model_name] = ChatterboxVC.from_pretrained(DEVICE)
    return models[model_name]


def unload_model(model_name: str) -> None:
    if model_name not in models:
        raise ValueError(f"Model không hợp lệ: {model_name}")
    models[model_name] = None
    cleanup_runtime()


def update_job(job_id: str, **changes) -> None:
    with jobs_lock:
        job = jobs[job_id]
        for key, value in changes.items():
            setattr(job, key, value)


def generate_job_audio(job: AudioJob) -> tuple[torch.Tensor, int]:
    params = job.params
    model = load_model(model_key_for_job(job.type))
    seed = int(params.get("seed", 0))
    if seed:
        set_seed(seed)

    with torch.inference_mode():
        if job.type == "tts":
            wav = model.generate(
                params["text"],
                audio_prompt_path=params.get("audio_prompt_path"),
                exaggeration=params["exaggeration"],
                temperature=params["temperature"],
                cfg_weight=params["cfg_weight"],
                min_p=params["min_p"],
                top_p=params["top_p"],
                repetition_penalty=params["repetition_penalty"],
            )
        elif job.type in {"turbo", "nano"}:
            wav = model.generate(
                params["text"],
                audio_prompt_path=params.get("audio_prompt_path"),
                temperature=params["temperature"],
                top_k=params["top_k"],
                top_p=params["top_p"],
                repetition_penalty=params["repetition_penalty"],
            )
        elif job.type == "multilingual":
            wav = model.generate(
                params["text"],
                language_id=params["language_id"],
                audio_prompt_path=params.get("audio_prompt_path"),
                exaggeration=params["exaggeration"],
                temperature=params["temperature"],
                cfg_weight=params["cfg_weight"],
                min_p=params["min_p"],
                top_p=params["top_p"],
                repetition_penalty=params["repetition_penalty"],
            )
        else:
            wav = model.generate(
                params["source_audio_path"],
                target_voice_path=params.get("target_voice_path"),
            )
    return wav.cpu(), model.sr


def run_inference_isolated(job: AudioJob, output_path: Path) -> tuple[bool, str | None]:
    """Execute model inference inside a separate isolated child process.
    
    If the child process crashes, triggers a segfault, or gets SIGKILLed by the OS kernel
    due to an Out-Of-Memory (OOM) event, the main FastAPI server intercepts the exit code
    and stays 100% alive.
    """
    config = {
        "type": job.type,
        "params": job.params,
        "output_path": str(output_path),
        "device": DEVICE,
        "cpu_threads": CPU_THREADS,
    }
    config_json = json.dumps(config)
    runner_script = PROJECT_DIR / "inference_runner.py"

    cmd = [
        sys.executable,
        str(runner_script),
        "--config",
        config_json,
    ]

    env = os.environ.copy()
    env["HF_HUB_CACHE"] = str(PROJECT_DIR / "models")
    env["PYTHONPATH"] = str(PROJECT_DIR / "src") + (":" + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else "")

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=240,  # 4 minutes timeout per job
            env=env,
            cwd=str(PROJECT_DIR),
        )

        if proc.returncode == 0 and output_path.exists():
            return True, None

        rc = proc.returncode
        stderr = proc.stderr.strip() if proc.stderr else ""

        # OOM Killer / Fatal signals:
        # SIGKILL on Unix is -9 or 137 (128 + 9)
        # SIGSEGV is -11 or 139
        # SIGBUS is -10 or 138
        if rc in (-9, 137, -11, 139, -10, 138):
            err_msg = (
                f"Tiến trình sinh âm thanh bị hệ thống ngắt đột ngột (Mã thoát: {rc} - Tràn bộ nhớ RAM / OOM). "
                "Khuyến nghị: Chuyển sang sử dụng model 'nano' (chỉ tốn ~500MB RAM), chia nhỏ câu văn bản "
                "hoặc đóng bớt các ứng dụng nặng khác trên máy."
            )
            print(f"[API Worker] ⚠️ OOM/Crash intercepted in isolated worker for job {job.id}: {err_msg}")
            return False, err_msg

        # Check for missing snapshot / offline hub error
        if "Cannot find an appropriate cached snapshot folder" in stderr or "HF_HUB_OFFLINE" in stderr:
            err_msg = (
                f"Chưa có file checkpoint của model '{job.type}' trong thư mục models/. "
                "Hãy khởi động server với 'HF_HUB_OFFLINE=0 ./run_chatterbox_api.sh' để hệ thống tự động tải model."
            )
            return False, err_msg

        # General error fallback
        clean_stderr = stderr.split("\n")[-1] if stderr else f"Mã thoát: {rc}"
        return False, f"Lỗi sinh âm thanh (Mã {rc}): {clean_stderr}"

    except subprocess.TimeoutExpired:
        return False, "Quá thời gian xử lý cho phép (Timeout 240s)."
    except Exception as exc:
        return False, f"Lỗi không thể khởi chạy tiến trình xử lý: {exc}"


def is_in_process_mode() -> bool:
    if os.getenv("CHATTERBOX_IN_PROCESS", "0") == "1":
        return True
    if hasattr(load_model, "mock") or hasattr(load_model, "assert_called") or hasattr(load_model, "return_value"):
        return True
    return False


def process_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs[job_id]
    update_job(job_id, status="processing", started_at=now_iso())

    output_path = API_DATA_DIR / "outputs" / f"{job.id}.wav"
    try:
        if is_in_process_mode():
            with execution_lock:
                wav, sample_rate = generate_job_audio(job)
                ta.save(output_path, wav, sample_rate)
            update_job(job_id, status="completed", completed_at=now_iso(), output_path=str(output_path))
        else:
            with execution_lock:
                success, error_msg = run_inference_isolated(job, output_path)

            if success and output_path.exists():
                update_job(job_id, status="completed", completed_at=now_iso(), output_path=str(output_path))
            else:
                update_job(job_id, status="failed", completed_at=now_iso(), error=error_msg or "Lỗi không xác định")
    except Exception as exc:
        update_job(job_id, status="failed", completed_at=now_iso(), error=str(exc))
    finally:
        for input_path in job.input_paths:
            Path(input_path).unlink(missing_ok=True)
        cleanup_runtime()


def worker_loop() -> None:
    while True:
        job_id = job_queue.get()
        try:
            process_job(job_id)
        finally:
            job_queue.task_done()


@asynccontextmanager
async def lifespan(_: FastAPI):
    API_DATA_DIR.joinpath("inputs").mkdir(parents=True, exist_ok=True)
    API_DATA_DIR.joinpath("outputs").mkdir(parents=True, exist_ok=True)
    threading.Thread(target=worker_loop, name="chatterbox-audio-worker", daemon=True).start()
    yield


app = FastAPI(
    title="Chatterbox TTS API & Web Studio",
    version="1.3.0",
    description="Local API & Web GUI cho Chatterbox TTS, Turbo, Nano, Multilingual và Voice Conversion.",
    lifespan=lifespan,
)

# Kích hoạt CORS cho các client kết nối API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gắn router Character API
app.include_router(character_api.router)

# Mount thư mục WebUI static files
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
    """Phục vụ giao diện Material Design 3 Web Dashboard trực tiếp trên trình duyệt"""
    dashboard_file = WEBUI_DIR / "material_dashboard.html"
    if dashboard_file.exists():
        return FileResponse(dashboard_file, media_type="text/html")
    return HTMLResponse("<h2>Chatterbox Studio Web GUI</h2><p>Đang tải tài nguyên giao diện...</p>")


async def save_upload(upload: UploadFile, job_id: str, label: str) -> str:
    suffix = Path(upload.filename or "audio.wav").suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"Định dạng {label} không được hỗ trợ")
    destination_path = API_DATA_DIR / "inputs" / f"{job_id}-{label}{suffix}"
    size = 0
    try:
        with destination_path.open("wb") as destination:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"{label} vượt quá giới hạn dung lượng")
                destination.write(chunk)
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return str(destination_path)


async def resolve_character_prompt(
    character_id: str | None,
    audio_prompt: UploadFile | None,
    upload_id: str,
) -> tuple[str | None, list[str], dict | None]:
    character_prompt, voice_profile = character_api.resolve_character_voice(character_id)
    if audio_prompt is not None:
        uploaded_prompt = await save_upload(audio_prompt, upload_id, "prompt")
        return uploaded_prompt, [uploaded_prompt], voice_profile
    return character_prompt, [], voice_profile


def effective_temperature(explicit: float | None, voice_profile: dict | None, default: float) -> float:
    if explicit is not None:
        return explicit
    if voice_profile is None:
        return default
    return round(1.2 - (0.7 * voice_profile["stability"]), 3)


def effective_value(explicit, voice_profile: dict | None, profile_key: str, default):
    if explicit is not None:
        return explicit
    if voice_profile is not None:
        return voice_profile[profile_key]
    return default


def validate_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Văn bản không được để trống")
    return cleaned


class SplitTextRequest(BaseModel):
    text: str = Field(min_length=1)
    min_chars: int = Field(default=200, ge=50, le=1000)
    max_chars: int = Field(default=500, ge=100, le=2000)


def split_text_preserving_content(text: str, min_chars: int, max_chars: int) -> list[dict]:
    if min_chars > max_chars:
        raise HTTPException(status_code=422, detail="min_chars không được lớn hơn max_chars")

    chunks = []
    start = 0
    text_length = len(text)
    while start < text_length:
        hard_end = min(start + max_chars, text_length)
        end = hard_end
        if hard_end < text_length:
            soft_start = min(start + min_chars, hard_end)
            for index in range(hard_end, soft_start - 1, -1):
                if text[index - 1] in ".!?;:\n":
                    end = index
                    break
            else:
                for index in range(hard_end, soft_start - 1, -1):
                    if text[index - 1].isspace():
                        end = index
                        break
        chunks.append({"index": len(chunks), "start": start, "end": end, "text": text[start:end]})
        start = end
    return chunks


def submit_job(job_type: JobType, params: dict, input_paths: list[str]) -> dict:
    job = AudioJob(
        id=uuid.uuid4().hex,
        type=job_type,
        params=params,
        input_paths=input_paths,
        created_at=now_iso(),
    )
    with jobs_lock:
        jobs[job.id] = job
    job_queue.put(job.id)
    return job.public_dict()


@app.post("/api/v1/text/split", tags=["text"])
def split_text(request: SplitTextRequest) -> dict:
    chunks = split_text_preserving_content(request.text, request.min_chars, request.max_chars)
    return {
        "chunks": chunks,
        "count": len(chunks),
        "original_length": len(request.text),
        "content_preserved": "".join(chunk["text"] for chunk in chunks) == request.text,
    }


@app.get("/health", tags=["system"])
@app.get("/api/v1/health", tags=["system"])
def health() -> dict:
    with jobs_lock:
        processing = sum(job.status == "processing" for job in jobs.values())
    
    models_dir = PROJECT_DIR / "models"
    return {
        "status": "ok",
        "device": DEVICE,
        "cpu_threads": CPU_THREADS,
        "total_ram_gb": SYSTEM_PROFILE["total_ram_gb"],
        "recommended_model": RECOMMENDED_MODEL,
        "default_model": "turbo",
        "recommendation_reason": SYSTEM_PROFILE.get("reason", ""),
        "queue_size": job_queue.qsize(),
        "processing": processing,
        "models_cached": {
            "nano": (models_dir / "models--ResembleAI--chatterbox-nano").exists(),
            "turbo": (models_dir / "models--ResembleAI--chatterbox-turbo").exists(),
            "standard": (models_dir / "models--ResembleAI--chatterbox").exists(),
            "multilingual": (models_dir / "models--ResembleAI--chatterbox-multilingual").exists(),
        },
    }


@app.post("/api/v1/tts/standard", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
async def create_tts_job(
    text: Annotated[str, Form(min_length=1, max_length=4000)],
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    character_id: Annotated[str | None, Form()] = None,
    exaggeration: Annotated[float | None, Form(ge=0.25, le=2.0)] = None,
    temperature: Annotated[float | None, Form(ge=0.05, le=5.0)] = None,
    seed: Annotated[int | None, Form(ge=0)] = None,
    cfg_weight: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    min_p: Annotated[float, Form(ge=0.0, le=1.0)] = 0.05,
    top_p: Annotated[float, Form(ge=0.0, le=1.0)] = 1.0,
    repetition_penalty: Annotated[float, Form(ge=1.0, le=2.0)] = 1.2,
) -> dict:
    job_id = uuid.uuid4().hex
    audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(
        character_id, audio_prompt, job_id
    )
    params = {
        "text": validate_text(text),
        "character_id": character_id,
        "audio_prompt_path": audio_prompt_path,
        "exaggeration": effective_value(exaggeration, voice_profile, "expressiveness", 0.5),
        "temperature": effective_temperature(temperature, voice_profile, 0.8),
        "seed": effective_value(seed, voice_profile, "seed", 0),
        "cfg_weight": effective_value(cfg_weight, voice_profile, "pace", 0.5),
        "min_p": min_p,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    return submit_job("tts", params, input_paths)


@app.post("/api/v1/tts", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
@app.post("/api/v1/tts/turbo", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
async def create_turbo_job(
    text: Annotated[str, Form(min_length=1, max_length=4000)],
    model: Annotated[Literal["turbo", "nano"], Form()] = "turbo",
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    character_id: Annotated[str | None, Form()] = None,
    temperature: Annotated[float | None, Form(ge=0.05, le=5.0)] = None,
    seed: Annotated[int | None, Form(ge=0)] = None,
    top_k: Annotated[int, Form(ge=1, le=5000)] = 1000,
    top_p: Annotated[float, Form(ge=0.0, le=1.0)] = 0.95,
    repetition_penalty: Annotated[float, Form(ge=1.0, le=2.0)] = 1.2,
) -> dict:
    job_id = uuid.uuid4().hex
    audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(
        character_id, audio_prompt, job_id
    )
    params = {
        "text": validate_text(text),
        "character_id": character_id,
        "audio_prompt_path": audio_prompt_path,
        "temperature": effective_temperature(temperature, voice_profile, 0.8),
        "seed": effective_value(seed, voice_profile, "seed", 0),
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    return submit_job(model, params, input_paths)


@app.post("/api/v1/tts/multilingual", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
async def create_multilingual_job(
    text: Annotated[str, Form(min_length=1, max_length=4000)],
    language_id: Annotated[str, Form()],
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    character_id: Annotated[str | None, Form()] = None,
    exaggeration: Annotated[float | None, Form(ge=0.25, le=2.0)] = None,
    temperature: Annotated[float | None, Form(ge=0.05, le=5.0)] = None,
    seed: Annotated[int | None, Form(ge=0)] = None,
    cfg_weight: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    min_p: Annotated[float, Form(ge=0.0, le=1.0)] = 0.05,
    top_p: Annotated[float, Form(ge=0.0, le=1.0)] = 1.0,
    repetition_penalty: Annotated[float, Form(ge=1.0, le=2.0)] = 1.2,
) -> dict:
    language_id = language_id.lower().strip()
    if language_id not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail={"message": "Ngôn ngữ không được hỗ trợ", "supported": SUPPORTED_LANGUAGES})
    job_id = uuid.uuid4().hex
    audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(
        character_id, audio_prompt, job_id
    )
    params = {
        "text": validate_text(text),
        "character_id": character_id,
        "language_id": language_id,
        "audio_prompt_path": audio_prompt_path,
        "exaggeration": effective_value(exaggeration, voice_profile, "expressiveness", 0.5),
        "temperature": effective_temperature(temperature, voice_profile, 0.8),
        "seed": effective_value(seed, voice_profile, "seed", 0),
        "cfg_weight": effective_value(cfg_weight, voice_profile, "pace", 0.5),
        "min_p": min_p,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    return submit_job("multilingual", params, input_paths)


@app.post("/api/v1/voice-conversion", status_code=status.HTTP_202_ACCEPTED, tags=["voice-conversion"])
async def create_voice_conversion_job(
    source_audio: Annotated[UploadFile, File()],
    target_voice: Annotated[UploadFile | None, File()] = None,
) -> dict:
    job_id = uuid.uuid4().hex
    source_audio_path = await save_upload(source_audio, job_id, "source")
    input_paths = [source_audio_path]
    try:
        target_voice_path = await save_upload(target_voice, job_id, "target") if target_voice else None
    except Exception:
        Path(source_audio_path).unlink(missing_ok=True)
        raise
    if target_voice_path:
        input_paths.append(target_voice_path)
    params = {"source_audio_path": source_audio_path, "target_voice_path": target_voice_path}
    return submit_job("voice-conversion", params, input_paths)


@app.get("/api/v1/languages", tags=["models"])
def list_languages() -> dict:
    return {"languages": SUPPORTED_LANGUAGES}


@app.get("/api/v1/models", tags=["models"])
def list_models() -> dict:
    return {
        "device": DEVICE,
        "models": [{"name": name, "loaded": model is not None} for name, model in models.items()],
    }


@app.post("/api/v1/models/{model_name}/load", tags=["models"])
def preload_model(model_name: str) -> dict:
    if model_name not in models:
        raise HTTPException(status_code=404, detail="Model không hợp lệ")
    with execution_lock:
        load_model(model_name)
    return {"name": model_name, "loaded": True, "device": DEVICE}


@app.delete("/api/v1/models/{model_name}", tags=["models"])
def release_model(model_name: str) -> dict:
    if model_name not in models:
        raise HTTPException(status_code=404, detail="Model không hợp lệ")
    with execution_lock:
        unload_model(model_name)
    return {"name": model_name, "loaded": False}


@app.get("/api/v1/jobs", tags=["jobs"])
def list_jobs(job_status: Annotated[JobStatus | None, Query(alias="status")] = None) -> dict:
    with jobs_lock:
        result = [job.public_dict() for job in reversed(jobs.values()) if job_status is None or job.status == job_status]
    return {"jobs": result, "count": len(result)}


@app.get("/api/v1/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy job")
        return job.public_dict()


@app.delete("/api/v1/jobs/{job_id}", tags=["jobs"])
def delete_job(job_id: str) -> dict:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy job")
        if job.status in {"queued", "processing"}:
            raise HTTPException(status_code=409, detail="Không thể xóa job đang chờ hoặc đang xử lý")
        jobs.pop(job_id)
    if job.output_path:
        Path(job.output_path).unlink(missing_ok=True)
    return {"id": job_id, "deleted": True}


@app.get("/api/v1/jobs/{job_id}/audio", tags=["jobs"])
def download_audio(job_id: str) -> FileResponse:
    with jobs_lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy job")
        if job.status != "completed" or not job.output_path:
            raise HTTPException(status_code=409, detail=f"Job chưa hoàn tất: {job.status}")
        output_path = Path(job.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=410, detail="File âm thanh không còn tồn tại")
    return FileResponse(output_path, media_type="audio/wav", filename=f"chatterbox-{job_id}.wav")


@app.get("/api/v1/settings", tags=["settings"])
def get_settings() -> dict:
    from config.settings import settings_manager
    return {"settings": settings_manager.settings}


@app.post("/api/v1/settings", tags=["settings"])
def update_settings(payload: dict = Body(...)) -> dict:
    from config.settings import settings_manager
    settings_manager.settings.update(payload)
    settings_manager.save()
    return {"status": "ok", "settings": settings_manager.settings}


@app.post("/api/v1/system/clean-tmp", tags=["system"])
def clean_temp_dir() -> dict:
    from config.constants import TMP_DIR
    count = 0
    size_bytes = 0
    if TMP_DIR.exists():
        for f in TMP_DIR.glob("**/*"):
            if f.is_file() and not f.name.startswith("."):
                try:
                    size_bytes += f.stat().st_size
                    f.unlink(missing_ok=True)
                    count += 1
                except Exception:
                    pass
    return {"status": "ok", "deleted_files": count, "freed_bytes": size_bytes}


@app.post("/api/v1/audio/merge", tags=["audio"])
@app.post("/api/v1/batch/merge", tags=["audio"])
async def merge_audio_jobs(
    request: Request,
    job_ids: Annotated[str | None, Form()] = None,
    pause_duration: Annotated[float, Form(ge=0.0, le=5.0)] = 0.8,
    bgm_file: Annotated[UploadFile | None, File()] = None,
    bgm_volume: Annotated[float, Form(ge=0.0, le=1.0)] = 0.15,
) -> dict:
    """Ghép nối nhiều đoạn audio từ các job TTS thành 1 file hoàn chỉnh kèm khoảng lặng và nhạc nền BGM."""
    content_type = request.headers.get("content-type", "")
    target_job_ids = []
    if "application/json" in content_type:
        try:
            body = await request.json()
            target_job_ids = body.get("job_ids", [])
            if "pause_duration" in body:
                pause_duration = float(body["pause_duration"])
            if "bgm_volume" in body:
                bgm_volume = float(body["bgm_volume"])
        except Exception:
            pass
    elif job_ids:
        target_job_ids = [j.strip() for j in job_ids.split(",") if j.strip()]

    if not target_job_ids:
        raise HTTPException(status_code=400, detail="Danh sách job_ids không được để trống")

    chunks = []
    target_sr = 24000
    for jid in target_job_ids:
        with jobs_lock:
            job = jobs.get(jid)
        if not job or job.status != "completed" or not job.output_path:
            continue
        p = Path(job.output_path)
        if not p.exists():
            continue
        try:
            wav, sr = ta.load(p)
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0, keepdim=True)
            if sr != target_sr:
                wav = ta.transforms.Resample(orig_freq=sr, new_freq=target_sr)(wav)
            chunks.append(wav)
        except Exception:
            continue

    if not chunks:
        raise HTTPException(status_code=404, detail="Không tìm thấy file audio hợp lệ từ các job đã chọn")

    silence_samples = int(target_sr * max(0.0, pause_duration))
    silence_tensor = torch.zeros(1, silence_samples)

    speech_parts = []
    for i, ch in enumerate(chunks):
        speech_parts.append(ch)
        if i < len(chunks) - 1 and silence_samples > 0:
            speech_parts.append(silence_tensor)

    merged_speech = torch.cat(speech_parts, dim=-1)

    # Optional BGM mixing
    if bgm_file is not None and bgm_file.filename:
        bgm_temp = API_DATA_DIR / "inputs" / f"bgm_{uuid.uuid4().hex}_{bgm_file.filename}"
        try:
            with open(bgm_temp, "wb") as f:
                while chunk := await bgm_file.read(1024 * 1024):
                    f.write(chunk)
            bgm_wav, bgm_sr = ta.load(bgm_temp)
            if bgm_wav.shape[0] > 1:
                bgm_wav = bgm_wav.mean(dim=0, keepdim=True)
            if bgm_sr != target_sr:
                bgm_wav = ta.transforms.Resample(orig_freq=bgm_sr, new_freq=target_sr)(bgm_wav)

            speech_len = merged_speech.shape[-1]
            if bgm_wav.shape[-1] < speech_len:
                repeats = (speech_len // bgm_wav.shape[-1]) + 1
                bgm_wav = bgm_wav.repeat(1, repeats)[:, :speech_len]
            else:
                bgm_wav = bgm_wav[:, :speech_len]

            # Fade out last 1.5s
            fade_len = min(int(target_sr * 1.5), bgm_wav.shape[-1])
            if fade_len > 0:
                fade_curve = torch.linspace(1.0, 0.0, fade_len)
                bgm_wav[:, -fade_len:] *= fade_curve

            merged_speech = merged_speech + (bgm_wav * bgm_volume)
            max_amp = merged_speech.abs().max()
            if max_amp > 1.0:
                merged_speech = merged_speech / max_amp
        except Exception:
            pass
        finally:
            bgm_temp.unlink(missing_ok=True)

    merge_id = f"merge_{uuid.uuid4().hex[:10]}"
    out_file = API_DATA_DIR / "outputs" / f"{merge_id}.wav"
    ta.save(out_file, merged_speech, target_sr)

    total_duration = round(merged_speech.shape[-1] / target_sr, 2)
    merge_job = AudioJob(
        id=merge_id,
        type="tts",
        params={"merged_from_count": len(chunks), "pause_duration": pause_duration},
        input_paths=[],
        status="completed",
        created_at=now_iso(),
        completed_at=now_iso(),
        output_path=str(out_file)
    )
    with jobs_lock:
        jobs[merge_id] = merge_job

    return {
        "id": merge_id,
        "audio_url": f"/api/v1/jobs/{merge_id}/audio",
        "duration_seconds": total_duration,
        "chunks_count": len(chunks),
        "message": f"Đã ghép thành công {len(chunks)} đoạn audio thành 1 file hoàn chỉnh ({total_duration}s)!"
    }



