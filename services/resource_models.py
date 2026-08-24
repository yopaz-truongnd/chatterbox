"""Domain models for the Chatterbox Resource System (Phases 4-6).

Provides strongly-typed contracts for Asset Manifest, Requirements,
Resolutions, Gaps, Pronunciation Knowledge, and Readiness Reporting.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field, field_validator


class ResourceCategory(str, Enum):
    AMBIENCE = "ambience"
    SFX = "sfx"
    MUSIC = "music"
    VOICE = "voice"
    KNOWLEDGE = "knowledge"


class RequirementPriority(str, Enum):
    REQUIRED = "required"
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"


class ResolutionStatus(str, Enum):
    EXACT = "exact"
    SUBSTITUTE = "substitute"
    MISSING = "missing"


class PronunciationStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


# ==========================================
# 1. Asset Manifest Models
# ==========================================

class ResourceFile(BaseModel):
    path: str
    format: str = "wav"
    size_bytes: int | None = None
    hash: str | None = None


class ResourceProperties(BaseModel):
    duration: float = 0.0
    loopable: bool = False
    intensity: int = 3
    sample_rate: int | None = None
    channels: int | None = None

    @field_validator("intensity")
    @classmethod
    def validate_intensity_range(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Intensity must be an integer between 1 and 5.")
        return v

    @field_validator("duration")
    @classmethod
    def validate_duration_non_negative(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("Duration must be non-negative.")
        return v


class ResourceMixSettings(BaseModel):
    recommended_db: float = -29.0
    max_db: float = -24.0


class ResourceUsage(BaseModel):
    total: int = 0
    last_used: dict[str, Any] | None = None
    recent_projects: list[str] = Field(default_factory=list)


class ResourceEntry(BaseModel):
    id: str
    file: ResourceFile
    category: ResourceCategory
    intents: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    properties: ResourceProperties = Field(default_factory=ResourceProperties)
    mix: ResourceMixSettings = Field(default_factory=ResourceMixSettings)
    usage: ResourceUsage = Field(default_factory=ResourceUsage)

    @field_validator("id")
    @classmethod
    def validate_id_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Resource ID cannot be empty.")
        return v.strip()


class ResourceManifest(BaseModel):
    version: int = 1
    resources: list[ResourceEntry] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceManifest:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ResourceManifest:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)

    def find_by_id(self, resource_id: str) -> ResourceEntry | None:
        for r in self.resources:
            if r.id == resource_id:
                return r
        return None

    def find_by_category(self, category: ResourceCategory) -> list[ResourceEntry]:
        return [r for r in self.resources if r.category == category]


# ==========================================
# 2. Requirements Models
# ==========================================

class NarrativeContext(BaseModel):
    role: str | None = None
    text: str | None = None
    beat_id: str | None = None
    scene_id: str | None = None


class DesiredProperties(BaseModel):
    intensity: int = 3
    duration_min: float = 0.0
    duration_max: float = 0.0
    tags: list[str] = Field(default_factory=list)
    volume_db: float | None = None


class ResourceRequirement(BaseModel):
    id: str
    type: ResourceCategory
    intent: str
    priority: RequirementPriority = RequirementPriority.RECOMMENDED
    beat_id: str | None = None
    narrative_context: NarrativeContext | None = None
    desired: DesiredProperties = Field(default_factory=DesiredProperties)
    term: str | None = None
    raw_candidate: dict[str, Any] | None = None


# ==========================================
# 3. Candidate Scoring & Resolution Models
# ==========================================

class ScoreBreakdown(BaseModel):
    intent_score: float = 0.0
    intensity_score: float = 0.0
    duration_score: float = 0.0
    tag_score: float = 0.0
    usage_score: float = 0.0
    total_score: float = 0.0


class ResourceCandidate(BaseModel):
    resource: ResourceEntry
    score: float
    match_type: str = "exact"
    breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)


class ResourceResolution(BaseModel):
    beat_id: str | None = None
    type: ResourceCategory
    requested_intent: str
    status: ResolutionStatus
    selected: ResourceEntry | None = None
    score: float | None = None
    match_type: str | None = None
    recommendation: dict[str, Any] | None = None
    acquisition_priority: RequirementPriority = RequirementPriority.OPTIONAL


# ==========================================
# 4. Gaps & Reports
# ==========================================

class ResourceGap(BaseModel):
    id: str
    type: ResourceCategory
    intent: str | None = None
    term: str | None = None
    priority: RequirementPriority = RequirementPriority.RECOMMENDED
    used_at: list[str] = Field(default_factory=list)
    narrative_context: NarrativeContext | None = None
    wanted: dict[str, Any] = Field(default_factory=dict)
    suggested_search: list[str] = Field(default_factory=list)
    accepted_formats: list[str] = Field(default_factory=lambda: ["WAV", "MP3"])
    reason: str | None = None
    risk: str | None = None


class ReadinessReport(BaseModel):
    score: int = 100
    render_blocked: bool = False
    required_missing_count: int = 0
    recommended_missing_count: int = 0
    optional_missing_count: int = 0
    block_reasons: list[str] = Field(default_factory=list)


class ResourceReport(BaseModel):
    project_id: str
    readiness: ReadinessReport
    resolved: list[ResourceResolution] = Field(default_factory=list)
    substituted: list[ResourceResolution] = Field(default_factory=list)
    missing: list[ResourceGap] = Field(default_factory=list)
    pronunciation_overrides: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResourceReport:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ResourceReport:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)


class ResolutionContext(BaseModel):
    project_id: str | None = None
    recent_project_ids: list[str] = Field(default_factory=list)
    min_substitute_score: float = 0.70


# ==========================================
# 5. Pronunciation Models (Phase 5)
# ==========================================

class PronunciationHint(BaseModel):
    tts_hint: str | None = None
    ipa: str | None = None


class PronunciationEntry(BaseModel):
    display: str
    aliases: list[str] = Field(default_factory=list)
    language: str = "zh"
    pronunciation: PronunciationHint = Field(default_factory=PronunciationHint)
    status: PronunciationStatus = PronunciationStatus.UNVERIFIED
    source: str = "manual"
    notes: str | None = None


class PronunciationKnowledge(BaseModel):
    version: int = 1
    terms: dict[str, PronunciationEntry] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PronunciationKnowledge:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> PronunciationKnowledge:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)


# ==========================================
# 6. Ingest & Doctor Models (Phase 6)
# ==========================================

class AssetInspection(BaseModel):
    file_path: str
    filename: str
    extension: str
    duration: float
    sample_rate: int
    channels: int
    size_bytes: int
    hash_sha256: str
    suggested_category: ResourceCategory
    suggested_intents: list[str] = Field(default_factory=list)
    suggested_tags: list[str] = Field(default_factory=list)
    suggested_intensity: int = 3
    suggested_loopable: bool = False


class IngestMetadata(BaseModel):
    resource_id: str
    category: ResourceCategory
    intents: list[str]
    tags: list[str] = Field(default_factory=list)
    intensity: int = 3
    loopable: bool = False
    recommended_db: float = -29.0
    max_db: float = -24.0


class ShoppingListItem(BaseModel):
    item_key: str
    type: ResourceCategory
    intent_or_term: str
    priority: RequirementPriority
    needed_by_projects_count: int
    project_ids: list[str] = Field(default_factory=list)
    suggested_search: list[str] = Field(default_factory=list)
    reason: str | None = None


class ResourceShoppingList(BaseModel):
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    items: list[ShoppingListItem] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


class DoctorIssue(BaseModel):
    severity: str  # "error" or "warning"
    component: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DoctorReport(BaseModel):
    healthy: bool
    issues: list[DoctorIssue] = Field(default_factory=list)
    warnings: list[DoctorIssue] = Field(default_factory=list)
