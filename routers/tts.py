"""TTS generation, long-text, multilingual, quality presets, and voice conversion router."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

import character_api
from chatterbox.mtl_tts import SUPPORTED_LANGUAGES
from utils.text_cleaner import split_text_preserving_content

router = APIRouter(tags=["tts"])

AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".m4a"}

QUALITY_PRESETS = {
    "fast": {
        "name": "⚡ Siêu Nhanh (Fast / Low Latency)",
        "model": "nano",
        "temperature": 0.50,
        "top_p": 0.90,
        "repetition_penalty": 1.15,
        "description": "Tốc độ nhanh nhất, tối ưu CPU/RAM thấp, giọng nói chuẩn xác, mượt mà.",
    },
    "balanced": {
        "name": "⚖️ Cân Bằng (Balanced / Natural)",
        "model": "nano",
        "temperature": 0.65,
        "top_p": 0.95,
        "repetition_penalty": 1.20,
        "description": "Cân bằng hoàn hảo giữa độ tự nhiên, độ biểu cảm và tốc độ xử lý.",
    },
    "expressive": {
        "name": "🎭 Biểu Cảm Cao (Expressive / Dynamic)",
        "model": "turbo",
        "temperature": 0.85,
        "top_p": 0.98,
        "repetition_penalty": 1.25,
        "description": "Biểu cảm giọng đọc phong phú, nhấn nhá ngữ điệu sâu sắc và chân thực.",
    },
}


class SplitTextRequest(BaseModel):
    text: str = Field(min_length=1)
    min_chars: int = Field(default=200, ge=50, le=1000)
    max_chars: int = Field(default=500, ge=100, le=2000)


def validate_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Văn bản không được để trống")
    return cleaned


async def save_upload(upload: UploadFile, job_id: str, label: str) -> str:
    from api_app import API_DATA_DIR, MAX_UPLOAD_BYTES
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
                    raise HTTPException(status_code=413, detail=f"File {label} vượt quá dung lượng tối đa cho phép")
                destination.write(chunk)
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return str(destination_path)


async def resolve_character_prompt(
    character_id: str | None, audio_prompt: UploadFile | None, upload_id: str
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
    return round(1.2 - (0.7 * voice_profile.get("stability", 0.5)), 3)


def effective_value(explicit, voice_profile: dict | None, profile_key: str, default):
    if explicit is not None:
        return explicit
    if voice_profile is not None:
        return voice_profile.get(profile_key, default)
    return default


@router.get("/api/v1/presets/quality", tags=["presets"])
def get_quality_presets() -> dict:
    return {"presets": QUALITY_PRESETS}


@router.get("/api/v1/languages", tags=["multilingual"])
def list_languages() -> dict:
    return {"languages": SUPPORTED_LANGUAGES, "count": len(SUPPORTED_LANGUAGES)}


@router.post("/api/v1/text/split", tags=["text"])
def split_text(request: SplitTextRequest) -> dict:
    try:
        chunks = split_text_preserving_content(request.text, request.min_chars, request.max_chars)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "chunks": chunks,
        "count": len(chunks),
        "original_length": len(request.text),
        "content_preserved": "".join(chunk["text"] for chunk in chunks) == request.text,
    }


@router.post("/api/v1/tts", status_code=status.HTTP_202_ACCEPTED)
@router.post("/api/v1/tts/turbo", status_code=status.HTTP_202_ACCEPTED)
async def create_turbo_job(
    text: Annotated[str, Form(min_length=1, max_length=4000)],
    model: Annotated[Literal["turbo", "nano"] | None, Form()] = None,
    quality_preset: Annotated[Literal["fast", "balanced", "expressive"] | None, Form()] = None,
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    character_id: Annotated[str | None, Form()] = None,
    temperature: Annotated[float | None, Form(ge=0.05, le=5.0)] = None,
    seed: Annotated[int | None, Form(ge=0)] = None,
    top_k: Annotated[int, Form(ge=1, le=5000)] = 1000,
    top_p: Annotated[float, Form(ge=0.0, le=1.0)] = 0.95,
    repetition_penalty: Annotated[float, Form(ge=1.0, le=2.0)] = 1.2,
) -> dict:
    from api_app import RECOMMENDED_MODEL, job_manager

    selected_model = model or (QUALITY_PRESETS[quality_preset]["model"] if quality_preset else RECOMMENDED_MODEL)
    if quality_preset and quality_preset in QUALITY_PRESETS:
        preset_cfg = QUALITY_PRESETS[quality_preset]
        temperature = temperature or preset_cfg["temperature"]
        top_p = top_p if top_p != 0.95 else preset_cfg["top_p"]
        repetition_penalty = repetition_penalty if repetition_penalty != 1.2 else preset_cfg["repetition_penalty"]

    job_id = uuid.uuid4().hex
    audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(character_id, audio_prompt, job_id)
    params = {
        "text": validate_text(text),
        "character_id": character_id,
        "audio_prompt_path": audio_prompt_path,
        "temperature": effective_temperature(temperature, voice_profile, 0.6),
        "seed": effective_value(seed, voice_profile, "seed", 0),
        "top_k": top_k,
        "top_p": top_p,
        "repetition_penalty": repetition_penalty,
    }
    job = job_manager.submit_job(selected_model, params, input_paths)
    return job.public_dict()


@router.post("/api/v1/tts/standard", status_code=status.HTTP_202_ACCEPTED)
async def create_standard_tts_job(
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
    from api_app import job_manager

    job_id = uuid.uuid4().hex
    audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(character_id, audio_prompt, job_id)
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
    job = job_manager.submit_job("tts", params, input_paths)
    return job.public_dict()


@router.post("/api/v1/tts/multilingual", status_code=status.HTTP_202_ACCEPTED)
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
    from api_app import job_manager

    if language_id not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Ngôn ngữ không được hỗ trợ: {language_id}. Xem danh sách tại /api/v1/languages",
        )
    job_id = uuid.uuid4().hex
    audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(character_id, audio_prompt, job_id)
    params = {
        "text": validate_text(text),
        "language_id": language_id,
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
    job = job_manager.submit_job("multilingual", params, input_paths)
    return job.public_dict()


@router.post("/api/v1/tts/long-text", status_code=status.HTTP_202_ACCEPTED)
async def create_long_text_job(
    text: Annotated[str, Form(min_length=1)],
    model: Annotated[Literal["turbo", "nano", "standard"] | None, Form()] = None,
    quality_preset: Annotated[Literal["fast", "balanced", "expressive"] | None, Form()] = None,
    audio_prompt: Annotated[UploadFile | None, File()] = None,
    character_id: Annotated[str | None, Form()] = None,
    pause_duration: Annotated[float, Form(ge=0.0, le=5.0)] = 0.6,
    bgm_file: Annotated[UploadFile | None, File()] = None,
    bgm_volume: Annotated[float, Form(ge=0.0, le=1.0)] = 0.15,
    min_chars: Annotated[int, Form(ge=50, le=1000)] = 200,
    max_chars: Annotated[int, Form(ge=100, le=2000)] = 500,
    temperature: Annotated[float | None, Form(ge=0.05, le=5.0)] = None,
    seed: Annotated[int | None, Form(ge=0)] = None,
) -> dict:
    from api_app import RECOMMENDED_MODEL, job_manager

    selected_model = model or (QUALITY_PRESETS[quality_preset]["model"] if quality_preset else RECOMMENDED_MODEL)
    job_id = uuid.uuid4().hex
    audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(character_id, audio_prompt, job_id)

    bgm_path = None
    if bgm_file is not None and bgm_file.filename:
        bgm_path = await save_upload(bgm_file, job_id, "bgm")
        input_paths.append(bgm_path)

    params = {
        "text": validate_text(text),
        "model": selected_model,
        "character_id": character_id,
        "audio_prompt_path": audio_prompt_path,
        "bgm_audio_path": bgm_path,
        "bgm_volume": bgm_volume,
        "pause_duration": pause_duration,
        "min_chars": min_chars,
        "max_chars": max_chars,
        "temperature": effective_temperature(temperature, voice_profile, 0.6),
        "seed": effective_value(seed, voice_profile, "seed", 0),
        "top_k": 1000,
        "top_p": 0.95,
        "repetition_penalty": 1.2,
    }
    job = job_manager.submit_job("long-text", params, input_paths)
    return job.public_dict()


@router.post("/api/v1/voice-conversion", status_code=status.HTTP_202_ACCEPTED, tags=["vc"])
async def create_voice_conversion_job(
    source_audio: Annotated[UploadFile, File()],
    target_voice: Annotated[UploadFile | None, File()] = None,
) -> dict:
    from api_app import job_manager

    job_id = uuid.uuid4().hex
    source_path = await save_upload(source_audio, job_id, "source")
    input_paths = [source_path]
    target_path = None
    if target_voice is not None:
        target_path = await save_upload(target_voice, job_id, "target")
        input_paths.append(target_path)
    params = {
        "source_audio_path": source_path,
        "target_voice_path": target_path,
    }
    job = job_manager.submit_job("voice-conversion", params, input_paths)
    return job.public_dict()
