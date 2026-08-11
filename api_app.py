from __future__ import annotations

import gc
import os
import queue
import random
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
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from chatterbox.mtl_tts import ChatterboxMultilingualTTS, SUPPORTED_LANGUAGES
from chatterbox.tts import ChatterboxTTS
from chatterbox.tts_turbo import ChatterboxTurboTTS
from chatterbox.vc import ChatterboxVC


DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
CPU_THREADS = int(os.getenv("CHATTERBOX_API_CPU_THREADS", "2"))
torch.set_num_threads(CPU_THREADS)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass
API_DATA_DIR = Path(os.getenv("CHATTERBOX_API_DATA_DIR", "/tmp/chatterbox-api"))
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
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


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


def process_job(job_id: str) -> None:
    with jobs_lock:
        job = jobs[job_id]
    update_job(job_id, status="processing", started_at=now_iso())

    try:
        with execution_lock:
            wav, sample_rate = generate_job_audio(job)
            output_path = API_DATA_DIR / "outputs" / f"{job.id}.wav"
            ta.save(output_path, wav, sample_rate)
        update_job(job_id, status="completed", completed_at=now_iso(), output_path=str(output_path))
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
    title="Chatterbox TTS API",
    version="1.2.0",
    description="Local API cho Chatterbox TTS, Turbo, Nano, Multilingual và Voice Conversion.",
    lifespan=lifespan,
)


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
def health() -> dict:
    with jobs_lock:
        processing = sum(job.status == "processing" for job in jobs.values())
    return {
        "status": "ok",
        "device": DEVICE,
        "cpu_threads": CPU_THREADS,
        "default_model": "turbo",
        "queue_size": job_queue.qsize(),
        "processing": processing,
        "models_loaded": [name for name, model in models.items() if model is not None],
    }


@app.post("/api/v1/tts/standard", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
async def create_tts_job(
    text: Annotated[str, Form(min_length=1, max_length=4000)],
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    exaggeration: Annotated[float, Form(ge=0.25, le=2.0)] = 0.5,
    temperature: Annotated[float, Form(ge=0.05, le=5.0)] = 0.8,
    seed: Annotated[int, Form(ge=0)] = 0,
    cfg_weight: Annotated[float, Form(ge=0.0, le=1.0)] = 0.5,
    min_p: Annotated[float, Form(ge=0.0, le=1.0)] = 0.05,
    top_p: Annotated[float, Form(ge=0.0, le=1.0)] = 1.0,
    repetition_penalty: Annotated[float, Form(ge=1.0, le=2.0)] = 1.2,
) -> dict:
    job_id = uuid.uuid4().hex
    audio_prompt_path = await save_upload(audio_prompt, job_id, "prompt") if audio_prompt else None
    params = {
        "text": validate_text(text),
        "audio_prompt_path": audio_prompt_path,
        "exaggeration": exaggeration,
        "temperature": temperature,
        "seed": seed,
        "cfg_weight": cfg_weight,
        "min_p": min_p,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    return submit_job("tts", params, [audio_prompt_path] if audio_prompt_path else [])


@app.post("/api/v1/tts", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
@app.post("/api/v1/tts/turbo", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
async def create_turbo_job(
    text: Annotated[str, Form(min_length=1, max_length=4000)],
    model: Annotated[Literal["turbo", "nano"], Form()] = "turbo",
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    temperature: Annotated[float, Form(ge=0.05, le=5.0)] = 0.8,
    seed: Annotated[int, Form(ge=0)] = 0,
    top_k: Annotated[int, Form(ge=1, le=5000)] = 1000,
    top_p: Annotated[float, Form(ge=0.0, le=1.0)] = 0.95,
    repetition_penalty: Annotated[float, Form(ge=1.0, le=2.0)] = 1.2,
) -> dict:
    job_id = uuid.uuid4().hex
    audio_prompt_path = await save_upload(audio_prompt, job_id, "prompt") if audio_prompt else None
    params = {
        "text": validate_text(text),
        "audio_prompt_path": audio_prompt_path,
        "temperature": temperature,
        "seed": seed,
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    return submit_job(model, params, [audio_prompt_path] if audio_prompt_path else [])


@app.post("/api/v1/tts/multilingual", status_code=status.HTTP_202_ACCEPTED, tags=["tts"])
async def create_multilingual_job(
    text: Annotated[str, Form(min_length=1, max_length=4000)],
    language_id: Annotated[str, Form()],
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    exaggeration: Annotated[float, Form(ge=0.25, le=2.0)] = 0.5,
    temperature: Annotated[float, Form(ge=0.05, le=5.0)] = 0.8,
    seed: Annotated[int, Form(ge=0)] = 0,
    cfg_weight: Annotated[float, Form(ge=0.0, le=1.0)] = 0.5,
    min_p: Annotated[float, Form(ge=0.0, le=1.0)] = 0.05,
    top_p: Annotated[float, Form(ge=0.0, le=1.0)] = 1.0,
    repetition_penalty: Annotated[float, Form(ge=1.0, le=2.0)] = 1.2,
) -> dict:
    language_id = language_id.lower().strip()
    if language_id not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=422, detail={"message": "Ngôn ngữ không được hỗ trợ", "supported": SUPPORTED_LANGUAGES})
    job_id = uuid.uuid4().hex
    audio_prompt_path = await save_upload(audio_prompt, job_id, "prompt") if audio_prompt else None
    params = {
        "text": validate_text(text),
        "language_id": language_id,
        "audio_prompt_path": audio_prompt_path,
        "exaggeration": exaggeration,
        "temperature": temperature,
        "seed": seed,
        "cfg_weight": cfg_weight,
        "min_p": min_p,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    return submit_job("multilingual", params, [audio_prompt_path] if audio_prompt_path else [])


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
