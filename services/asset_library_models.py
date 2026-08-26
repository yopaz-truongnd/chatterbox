"""Domain models for the Intelligent Asset Library (Phase 18).

Provides strongly-typed contracts for library assets, match results,
ingest results, and scan results.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class AssetCategory(str, Enum):
    AMBIENCE = "ambience"
    SFX = "sfx"
    VOICE_REFERENCE = "voice_reference"
    PRONUNCIATION_REFERENCE = "pronunciation_reference"


class LibraryAsset(BaseModel):
    asset_id: str
    category: AssetCategory
    file_path: str  # relative path from permitted root
    sha256: str
    format: str  # "wav" | "mp3" | "flac"
    duration_ms: float
    sample_rate: int
    channels: int
    intents: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    mood: str | None = None
    environment: str | None = None
    energy: float | None = None  # 0.0-5.0
    loopable: bool = False
    license: str | None = None
    source_url: str | None = None
    attribution: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    usage_count: int = 0
    last_used_at: str | None = None
    usage_references: list[dict[str, str]] = Field(default_factory=list)
    enabled: bool = True


class AssetMatchResult(BaseModel):
    asset_id: str
    match_score: float  # 0.0-1.0
    match_reasons: list[str]
    exact_or_substitute: str  # "exact" | "substitute"
    license: str | None = None
    preview_artifact: str | None = None


class AssetIngestResult(BaseModel):
    asset_id: str
    status: str  # "registered" | "duplicate" | "rejected"
    existing_asset_id: str | None = None  # when duplicate
    reason: str | None = None


class AssetScanResult(BaseModel):
    scanned_path: str
    registered: int
    duplicates: int
    rejected: int
    assets: list[AssetIngestResult]
