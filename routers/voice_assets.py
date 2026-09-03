"""Voice Assets REST Router (Phase 18).

Thin HTTP adapter — validates inputs, delegates to business services,
returns JSON responses. No business logic lives here.
"""

from __future__ import annotations

import io
import struct
import wave
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path as FPath
from fastapi.responses import Response
from pydantic import BaseModel, Field

from services.asset_library_models import (
    AssetCategory,
    AssetIngestResult,
    AssetMatchResult,
    AssetScanResult,
    LibraryAsset,
)
from services.asset_library_service import get_asset_library_service
from services.asset_library_store import get_asset_library_store
from services.asset_matching_service import get_asset_matching_service

router = APIRouter(prefix="/api/v1/voice-assets", tags=["voice-assets"])


# ---------------------------------------------------------------------------
# Request/response schemas (thin, router-only)
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    file_path: str = Field(..., description="Absolute or permitted-root-relative path to the audio file.")
    category: AssetCategory
    intents: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    mood: str | None = None
    environment: str | None = None
    energy: float | None = Field(None, ge=0.0, le=5.0)
    loopable: bool = False
    license: str | None = None
    source_url: str | None = None
    attribution: str | None = None


class ScanRequest(BaseModel):
    directory_path: str = Field(..., description="Directory path to scan for audio files.")
    category: AssetCategory


class MatchRequest(BaseModel):
    intents: list[str] = Field(..., min_length=1)
    category: AssetCategory
    mood: str | None = None
    environment: str | None = None
    duration_ms: float | None = Field(None, gt=0)
    loopable: bool | None = None
    story_context: str | None = None
    top_k: int = Field(5, ge=1, le=50)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[LibraryAsset], summary="List library assets")
def list_assets(category: AssetCategory | None = None):
    """List all assets in the library, optionally filtered by category."""
    svc = get_asset_library_service()
    return svc.list_assets(category=category)


@router.get("/{asset_id}", response_model=LibraryAsset, summary="Get a single asset")
def get_asset(asset_id: str = FPath(..., description="Asset ID")):
    """Retrieve a single asset by ID."""
    svc = get_asset_library_service()
    asset = svc.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found.")
    return asset


@router.post("/register", response_model=AssetIngestResult, summary="Register a single audio file")
def register_asset(req: RegisterRequest):
    """Ingest a single audio file into the library with security validation."""
    svc = get_asset_library_service()
    meta: dict[str, Any] = {
        "intents": req.intents,
        "keywords": req.keywords,
        "mood": req.mood,
        "environment": req.environment,
        "energy": req.energy,
        "loopable": req.loopable,
        "license": req.license,
        "source_url": req.source_url,
        "attribution": req.attribution,
    }
    result = svc.ingest_file(req.file_path, req.category, metadata=meta)
    if result.status == "rejected":
        raise HTTPException(status_code=422, detail=result.reason)
    return result


@router.post("/scan", response_model=AssetScanResult, summary="Batch scan a directory")
def scan_directory(req: ScanRequest):
    """Scan a directory and ingest all supported audio files."""
    svc = get_asset_library_service()
    return svc.scan_directory(req.directory_path, req.category)


@router.post("/match", response_model=list[AssetMatchResult], summary="Match assets by intent")
def match_assets(req: MatchRequest):
    """Find and rank library assets matching the given semantic request."""
    matching_svc = get_asset_matching_service()
    results = matching_svc.match_assets(
        request_intents=req.intents,
        category=req.category,
        mood=req.mood,
        environment=req.environment,
        duration_ms=req.duration_ms,
        loopable=req.loopable,
        story_context=req.story_context,
        top_k=req.top_k,
    )
    store = get_asset_library_store()
    for r in results:
        store.update_usage(r.asset_id)
    return results


@router.post("/{asset_id}/disable", response_model=LibraryAsset, summary="Disable an asset")
def disable_asset(asset_id: str = FPath(..., description="Asset ID")):
    """Mark an asset as disabled so it is excluded from future matches."""
    svc = get_asset_library_service()
    updated = svc.disable_asset(asset_id)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found.")
    return updated


@router.get("/{asset_id}/preview", summary="200 ms WAV preview of asset")
def preview_asset(asset_id: str = FPath(..., description="Asset ID")):
    """Return a 200 ms WAV preview snippet of the asset audio.

    Generates a minimal silent WAV if the actual file is not accessible,
    ensuring the endpoint always returns a valid WAV for UI preview purposes.
    """
    svc = get_asset_library_service()
    asset = svc.get_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Asset '{asset_id}' not found.")

    # Try to read actual first 200 ms from file
    sample_rate = asset.sample_rate or 44100
    channels = asset.channels or 1
    num_frames = int(sample_rate * 0.2)  # 200 ms

    wav_bytes = _extract_preview_wav(asset, sample_rate, channels, num_frames, svc)
    return Response(content=wav_bytes, media_type="audio/wav")


def _extract_preview_wav(
    asset: LibraryAsset,
    sample_rate: int,
    channels: int,
    num_frames: int,
    asset_service: Any,
) -> bytes:
    """Extract first ~200 ms from WAV asset or generate silent WAV preview."""
    if asset.format == "wav":
        try:
            candidate = asset_service.resolve_asset_file(asset)
            with wave.open(str(candidate), "rb") as wf:
                actual_frames = min(num_frames, wf.getnframes())
                raw = wf.readframes(actual_frames)
                buf = io.BytesIO()
                with wave.open(buf, "wb") as out:
                    out.setnchannels(wf.getnchannels())
                    out.setsampwidth(wf.getsampwidth())
                    out.setframerate(wf.getframerate())
                    out.writeframes(raw)
                return buf.getvalue()
        except (OSError, ValueError, wave.Error):
            pass

    # Fallback: generate silent WAV
    return _silent_wav(sample_rate=sample_rate, channels=channels, num_frames=num_frames)


def _silent_wav(sample_rate: int = 44100, channels: int = 1, num_frames: int = 8820) -> bytes:
    """Create a minimal silent 16-bit PCM WAV."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * num_frames * channels * 2)
    return buf.getvalue()
