from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field


PROJECT_DIR = Path(__file__).resolve().parent
CHARACTER_DATA_DIR = PROJECT_DIR / "data" / "characters"
CHARACTERS_FILE = PROJECT_DIR / "data" / "characters.json"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".ogg", ".m4a"}

characters: dict[str, dict] = {}
characters_lock = threading.RLock()
router = APIRouter(prefix="/api/v1/characters", tags=["characters"])


class VoiceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expressiveness: float = Field(default=0.5, ge=0.0, le=1.0)
    pace: float = Field(default=0.5, ge=0.0, le=1.0)
    stability: float = Field(default=0.7, ge=0.0, le=1.0)
    seed: int = Field(default=0, ge=0)


class VoiceProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expressiveness: float | None = Field(default=None, ge=0.0, le=1.0)
    pace: float | None = Field(default=None, ge=0.0, le=1.0)
    stability: float | None = Field(default=None, ge=0.0, le=1.0)
    seed: int | None = Field(default=None, ge=0)


class CharacterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    language: str = Field(default="en", min_length=2, max_length=20)
    tags: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)
    voice: VoiceProfile = Field(default_factory=VoiceProfile)


class CharacterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    language: str | None = Field(default=None, min_length=2, max_length=20)
    tags: list[str] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    voice: VoiceProfileUpdate | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def configure_storage(data_dir: Path) -> None:
    global CHARACTER_DATA_DIR, CHARACTERS_FILE
    CHARACTER_DATA_DIR = data_dir / "characters"
    CHARACTERS_FILE = data_dir / "characters.json"
    load_characters()


def load_characters() -> None:
    CHARACTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    loaded = {}
    if CHARACTERS_FILE.exists():
        try:
            raw = json.loads(CHARACTERS_FILE.read_text(encoding="utf-8"))
            loaded = {item["id"]: item for item in raw if isinstance(item, dict) and item.get("id")}
        except (OSError, json.JSONDecodeError):
            loaded = {}
    with characters_lock:
        characters.clear()
        characters.update(loaded)


def save_characters() -> None:
    CHARACTERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = CHARACTERS_FILE.with_suffix(".json.tmp")
    with characters_lock:
        payload = sorted(characters.values(), key=lambda item: item["created_at"])
        temporary_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_file.replace(CHARACTERS_FILE)


def public_character(character: dict) -> dict:
    result = dict(character)
    reference_audio_path = result.pop("reference_audio_path", None)
    result["has_reference_audio"] = bool(reference_audio_path)
    result["reference_audio_url"] = (
        f"/api/v1/characters/{character['id']}/reference-audio" if reference_audio_path else None
    )
    return result


def get_character(character_id: str) -> dict:
    with characters_lock:
        character = characters.get(character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy Character")
        return dict(character)


def resolve_character_voice(character_id: str | None) -> tuple[str | None, dict | None]:
    if not character_id:
        return None, None
    character = get_character(character_id)
    reference_audio_path = character.get("reference_audio_path")
    if reference_audio_path and not Path(reference_audio_path).exists():
        raise HTTPException(status_code=410, detail="Reference audio của Character không còn tồn tại")
    return reference_audio_path, dict(character["voice"])


def normalized_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


async def save_reference_audio(upload: UploadFile, character_id: str) -> str:
    suffix = Path(upload.filename or "reference.wav").suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise HTTPException(status_code=415, detail="Định dạng reference audio không được hỗ trợ")
    character_dir = CHARACTER_DATA_DIR / character_id
    character_dir.mkdir(parents=True, exist_ok=True)
    destination_path = character_dir / f"reference{suffix}"
    size = 0
    try:
        with destination_path.open("wb") as destination:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Reference audio vượt quá giới hạn dung lượng")
                destination.write(chunk)
    except Exception:
        destination_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return str(destination_path)


@router.post("", status_code=201)
def create_character(payload: CharacterCreate) -> dict:
    character_id = f"char_{uuid.uuid4().hex}"
    timestamp = now_iso()
    character = {
        "id": character_id,
        "name": payload.name.strip(),
        "description": payload.description,
        "language": payload.language.lower().strip(),
        "tags": normalized_tags(payload.tags),
        "notes": payload.notes,
        "voice": payload.voice.model_dump(),
        "reference_audio_path": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with characters_lock:
        characters[character_id] = character
    save_characters()
    return public_character(character)


@router.get("")
def list_characters() -> dict:
    with characters_lock:
        result = [public_character(item) for item in characters.values()]
    result.sort(key=lambda item: item["created_at"])
    return {"characters": result, "count": len(result)}


@router.get("/{character_id}")
def read_character(character_id: str) -> dict:
    return public_character(get_character(character_id))


@router.patch("/{character_id}")
def update_character(character_id: str, payload: CharacterUpdate) -> dict:
    changes = payload.model_dump(exclude_none=True)
    with characters_lock:
        character = characters.get(character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy Character")
        for field in ("name", "description", "language", "tags", "notes"):
            if field in changes:
                character[field] = normalized_tags(changes[field]) if field == "tags" else changes[field]
        if "voice" in changes:
            character["voice"].update(changes["voice"])
        character["updated_at"] = now_iso()
        result = dict(character)
    save_characters()
    return public_character(result)


@router.put("/{character_id}/reference-audio")
async def replace_reference_audio(
    character_id: str,
    reference_audio: Annotated[UploadFile, File()],
) -> dict:
    character = get_character(character_id)
    old_path = Path(character["reference_audio_path"]) if character.get("reference_audio_path") else None
    new_path = await save_reference_audio(reference_audio, character_id)
    if old_path and old_path != Path(new_path):
        old_path.unlink(missing_ok=True)
    with characters_lock:
        characters[character_id]["reference_audio_path"] = new_path
        characters[character_id]["updated_at"] = now_iso()
        result = dict(characters[character_id])
    save_characters()
    return public_character(result)


@router.get("/{character_id}/reference-audio")
def download_reference_audio(character_id: str) -> FileResponse:
    character = get_character(character_id)
    reference_audio_path = character.get("reference_audio_path")
    if not reference_audio_path:
        raise HTTPException(status_code=404, detail="Character chưa có reference audio")
    reference_path = Path(reference_audio_path)
    if not reference_path.exists():
        raise HTTPException(status_code=410, detail="Reference audio không còn tồn tại")
    return FileResponse(reference_path, filename=reference_path.name)


@router.delete("/{character_id}/reference-audio")
def delete_reference_audio(character_id: str) -> dict:
    character = get_character(character_id)
    reference_audio_path = character.get("reference_audio_path")
    if reference_audio_path:
        Path(reference_audio_path).unlink(missing_ok=True)
    with characters_lock:
        characters[character_id]["reference_audio_path"] = None
        characters[character_id]["updated_at"] = now_iso()
        result = dict(characters[character_id])
    save_characters()
    return public_character(result)


@router.delete("/{character_id}")
def delete_character(character_id: str) -> dict:
    character = get_character(character_id)
    with characters_lock:
        characters.pop(character_id)
    save_characters()
    reference_audio_path = character.get("reference_audio_path")
    if reference_audio_path:
        shutil.rmtree(Path(reference_audio_path).parent, ignore_errors=True)
    return {"id": character_id, "deleted": True}


load_characters()
