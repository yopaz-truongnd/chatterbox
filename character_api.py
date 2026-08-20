from __future__ import annotations

import json
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field


import os
from utils.platform_tools import get_default_data_dir

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_STORAGE_DIR = Path(os.getenv("CHATTERBOX_API_DATA_DIR") or get_default_data_dir())
CHARACTER_DATA_DIR = DEFAULT_STORAGE_DIR / "characters"
CHARACTERS_FILE = DEFAULT_STORAGE_DIR / "characters.json"
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
    is_default: bool = Field(default=False)
    voice: VoiceProfile = Field(default_factory=VoiceProfile)


class CharacterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    language: str | None = Field(default=None, min_length=2, max_length=20)
    tags: list[str] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    is_default: bool | None = Field(default=None)
    voice: VoiceProfileUpdate | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def migrate_legacy_characters(target_data_dir: Path) -> None:
    """One-time migration of legacy characters from <project>/data to the platform data directory."""
    legacy_dir = PROJECT_DIR / "data"
    legacy_file = legacy_dir / "characters.json"
    legacy_chars_dir = legacy_dir / "characters"
    target_file = target_data_dir / "characters.json"
    target_chars_dir = target_data_dir / "characters"

    if target_file.resolve() == legacy_file.resolve() or target_file.exists() or not legacy_file.exists():
        return

    try:
        target_data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_file, target_file)
        if legacy_chars_dir.exists():
            shutil.copytree(legacy_chars_dir, target_chars_dir, dirs_exist_ok=True)
    except Exception:
        pass


def configure_storage(data_dir: Path) -> None:
    global CHARACTER_DATA_DIR, CHARACTERS_FILE
    migrate_legacy_characters(data_dir)
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
    result["is_default"] = bool(result.get("is_default", False))
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


def get_default_character() -> dict | None:
    with characters_lock:
        for character in characters.values():
            if character.get("is_default"):
                return dict(character)
        return None


def set_default_character(character_id: str | None) -> dict | None:
    with characters_lock:
        if character_id is not None and character_id not in characters:
            raise HTTPException(status_code=404, detail="Không tìm thấy Character")
        target = None
        for cid, character in characters.items():
            if character_id is not None and cid == character_id:
                character["is_default"] = True
                character["updated_at"] = now_iso()
                target = dict(character)
            else:
                character["is_default"] = False
    save_characters()
    return public_character(target) if target else None


def resolve_character_voice(character_id: str | None) -> tuple[str | None, dict | None]:
    if not character_id:
        default_char = get_default_character()
        if default_char:
            character_id = default_char["id"]
        else:
            return None, None
    character = get_character(character_id)
    reference_audio_path = character.get("reference_audio_path")
    if reference_audio_path and not Path(reference_audio_path).exists():
        raise HTTPException(status_code=410, detail="Reference audio của Character không còn tồn tại")
    return reference_audio_path, dict(character["voice"])


def normalized_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


def create_character_from_audio(
    name: str,
    audio_path: str | Path | None = None,
    voice: VoiceProfile | None = None,
    language: str = "en",
) -> dict:
    """Create a persistent Character from a local audio file or without audio (used by the desktop GUI)."""
    payload = CharacterCreate(name=name, language=language, voice=voice or VoiceProfile())
    character_id = f"char_{uuid.uuid4().hex}"
    timestamp = now_iso()
    character_dir = CHARACTER_DATA_DIR / character_id
    character_dir.mkdir(parents=True, exist_ok=False)

    managed_audio_path = None
    if audio_path:
        source_path = Path(audio_path).resolve()
        suffix = source_path.suffix.lower()
        if not source_path.is_file():
            shutil.rmtree(character_dir, ignore_errors=True)
            raise ValueError(f"Reference audio không tồn tại: {source_path}")
        if suffix not in AUDIO_SUFFIXES:
            shutil.rmtree(character_dir, ignore_errors=True)
            raise ValueError(f"Định dạng reference audio không được hỗ trợ: {suffix}")
        managed_audio_path = character_dir / f"reference{suffix}"
        shutil.copy2(source_path, managed_audio_path)

    try:
        character = {
            "id": character_id,
            "name": payload.name.strip(),
            "description": payload.description,
            "language": payload.language.lower().strip(),
            "tags": normalized_tags(payload.tags),
            "notes": payload.notes,
            "voice": payload.voice.model_dump(),
            "is_default": False,
            "reference_audio_path": str(managed_audio_path.resolve()) if managed_audio_path else None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with characters_lock:
            characters[character_id] = character
        save_characters()
    except Exception:
        with characters_lock:
            characters.pop(character_id, None)
        shutil.rmtree(character_dir, ignore_errors=True)
        raise
    return public_character(character)


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


def apply_character_update(character_id: str, changes: dict) -> dict:
    with characters_lock:
        character = characters.get(character_id)
        if character is None:
            raise HTTPException(status_code=404, detail="Không tìm thấy Character")
        
        if "name" in changes and changes["name"] is not None:
            character["name"] = str(changes["name"]).strip()
        if "description" in changes and changes["description"] is not None:
            character["description"] = str(changes["description"])
        if "language" in changes and changes["language"] is not None:
            character["language"] = str(changes["language"]).lower().strip()
        if "tags" in changes and changes["tags"] is not None:
            if isinstance(changes["tags"], str):
                tags_list = [t.strip() for t in changes["tags"].split(",") if t.strip()]
            else:
                tags_list = changes["tags"]
            character["tags"] = normalized_tags(tags_list)
        if "notes" in changes and changes["notes"] is not None:
            character["notes"] = str(changes["notes"])
            
        if "is_default" in changes and changes["is_default"] is not None:
            is_def = bool(changes["is_default"])
            if is_def:
                for cid, c in characters.items():
                    c["is_default"] = (cid == character_id)
            else:
                character["is_default"] = False

        if "voice" in changes and isinstance(changes["voice"], dict):
            for k, v in changes["voice"].items():
                if v is not None and k in character["voice"]:
                    character["voice"][k] = v

        for v_field in ("expressiveness", "pace", "stability", "seed"):
            if v_field in changes and changes[v_field] is not None:
                character["voice"][v_field] = changes[v_field]

        character["updated_at"] = now_iso()
        result = dict(character)
    save_characters()
    return public_character(result)


@router.post("", status_code=201)
async def create_character(
    request: Request,
    reference_audio: Annotated[UploadFile | None, File()] = None,
    name: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    tags: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    is_default: Annotated[bool | None, Form()] = None,
    expressiveness: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    pace: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    stability: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    seed: Annotated[int | None, Form(ge=0)] = None,
) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            payload = CharacterCreate(**body)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))
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
            "is_default": payload.is_default,
            "reference_audio_path": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        with characters_lock:
            if payload.is_default:
                for c in characters.values():
                    c["is_default"] = False
            characters[character_id] = character
        save_characters()
        return public_character(character)

    # Form / Multipart
    if not name or not name.strip():
        raise HTTPException(status_code=422, detail="Tên nhân vật là bắt buộc")
    character_id = f"char_{uuid.uuid4().hex}"
    timestamp = now_iso()

    tags_list = []
    if tags:
        tags_list = [t.strip() for t in tags.split(",") if t.strip()]

    ref_path = None
    if reference_audio is not None and reference_audio.filename:
        ref_path = await save_reference_audio(reference_audio, character_id)

    character = {
        "id": character_id,
        "name": name.strip(),
        "description": description or "",
        "language": (language or "en").lower().strip(),
        "tags": normalized_tags(tags_list),
        "notes": notes or "",
        "voice": {
            "expressiveness": expressiveness if expressiveness is not None else 0.5,
            "pace": pace if pace is not None else 0.5,
            "stability": stability if stability is not None else 0.7,
            "seed": seed if seed is not None else 0,
        },
        "is_default": bool(is_default),
        "reference_audio_path": ref_path,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    with characters_lock:
        if character["is_default"]:
            for c in characters.values():
                c["is_default"] = False
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
async def update_character(
    character_id: str,
    request: Request,
    reference_audio: Annotated[UploadFile | None, File()] = None,
    name: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    tags: Annotated[str | None, Form()] = None,
    notes: Annotated[str | None, Form()] = None,
    is_default: Annotated[bool | None, Form()] = None,
    expressiveness: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    pace: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    stability: Annotated[float | None, Form(ge=0.0, le=1.0)] = None,
    seed: Annotated[int | None, Form(ge=0)] = None,
) -> dict:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            payload = CharacterUpdate(**body)
            changes = payload.model_dump(exclude_none=True)
            return apply_character_update(character_id, changes)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=422, detail=str(e))

    # Form / Multipart request handling
    changes = {}
    if name is not None: changes["name"] = name
    if description is not None: changes["description"] = description
    if language is not None: changes["language"] = language
    if tags is not None: changes["tags"] = tags
    if notes is not None: changes["notes"] = notes
    if is_default is not None: changes["is_default"] = is_default
    if expressiveness is not None: changes["expressiveness"] = expressiveness
    if pace is not None: changes["pace"] = pace
    if stability is not None: changes["stability"] = stability
    if seed is not None: changes["seed"] = seed

    if reference_audio is not None and reference_audio.filename:
        character = get_character(character_id)
        old_path = Path(character["reference_audio_path"]) if character.get("reference_audio_path") else None
        new_path = await save_reference_audio(reference_audio, character_id)
        if old_path and old_path != Path(new_path):
            old_path.unlink(missing_ok=True)
        with characters_lock:
            characters[character_id]["reference_audio_path"] = new_path

    return apply_character_update(character_id, changes)


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


@router.get("/{character_id}/reference-audio", include_in_schema=False)
def download_reference_audio(character_id: str) -> FileResponse:
    character = get_character(character_id)
    reference_audio_path = character.get("reference_audio_path")
    if not reference_audio_path:
        raise HTTPException(status_code=404, detail="Character chưa có reference audio")
    reference_path = Path(reference_audio_path)
    if not reference_path.exists():
        raise HTTPException(status_code=410, detail="Reference audio không còn tồn tại")
    return FileResponse(reference_path, filename=reference_path.name)


load_characters()
