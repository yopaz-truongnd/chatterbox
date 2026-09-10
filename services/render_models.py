"""Domain models for CLI Workflow, Per-Beat TTS Renderer, and Voice QC (Phases 7-9).

Defines strongly-typed contracts for ProjectState, TTSRenderRequest,
TTSRenderResult, RenderManifest, QC Results, and Provider interfaces.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field, field_validator


class ProjectStatus(str, Enum):
    NEW = "NEW"
    PLANNING = "PLANNING"
    PLANNED = "PLANNED"
    RESOURCE_CHECKING = "RESOURCE_CHECKING"
    RESOURCE_BLOCKED = "RESOURCE_BLOCKED"
    READY_TO_RENDER = "READY_TO_RENDER"
    RENDERING = "RENDERING"
    QC_PENDING = "QC_PENDING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NARRATION_READY = "NARRATION_READY"
    PREPARING_MIX = "PREPARING_MIX"
    MIX_READY = "MIX_READY"
    MIXING = "MIXING"
    MIXED = "MIXED"
    MASTERING = "MASTERING"
    MASTERED = "MASTERED"
    EXPORTING = "EXPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RenderStatus(str, Enum):
    PENDING = "pending"
    RENDERING = "rendering"
    RENDERED = "rendered"
    QC_FAILED = "qc_failed"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class QCVerdict(str, Enum):
    PASS = "pass"
    RETRY = "retry"
    NEEDS_REVIEW = "needs_review"
    FAIL = "fail"


# ==========================================
# 1. Project State & Lifecycle (Phase 7 & 11)
# ==========================================

class ProjectArtifacts(BaseModel):
    voice_plan: str = "voice-plan.yaml"
    director_critique: str = "director-critique.yaml"
    resource_report: str = "resource-report.yaml"
    render_manifest: str = "render-manifest.yaml"

    # Dependency & Staleness Tracking Hashes (Phase 11)
    source_sha256: str = ""
    voice_plan_source_sha256: str = ""
    voice_plan_sha256: str = ""
    resource_report_voice_plan_sha256: str = ""
    resource_report_sha256: str = ""
    render_manifest_voice_plan_sha256: str = ""
    render_manifest_resource_report_sha256: str = ""
    render_manifest_sha256: str = ""


class ProjectStateStatus(BaseModel):
    story_analyzed: bool = False
    voice_plan_ready: bool = False
    sound_directed: bool = False
    resources_checked: bool = False
    render_ready: bool = False
    narration_ready: bool = False


class ProjectState(BaseModel):
    version: int = 1
    project_id: str
    title: str = ""
    language: str = "en"
    source_script_path: str = "source/script.txt"
    stage: ProjectStatus = ProjectStatus.NEW
    last_stable_stage: ProjectStatus = ProjectStatus.NEW
    error: str | None = None
    status: ProjectStateStatus = Field(default_factory=ProjectStateStatus)
    artifacts: ProjectArtifacts = Field(default_factory=ProjectArtifacts)
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def sync_legacy_status(self) -> None:
        """Derive legacy boolean flags from canonical stage."""
        stage = self.stage
        all_post_narration = (
            ProjectStatus.NARRATION_READY,
            ProjectStatus.PREPARING_MIX,
            ProjectStatus.MIX_READY,
            ProjectStatus.MIXING,
            ProjectStatus.MIXED,
            ProjectStatus.MASTERING,
            ProjectStatus.MASTERED,
            ProjectStatus.EXPORTING,
            ProjectStatus.COMPLETED,
        )
        self.status.story_analyzed = stage in (
            ProjectStatus.PLANNED, ProjectStatus.RESOURCE_CHECKING, ProjectStatus.RESOURCE_BLOCKED,
            ProjectStatus.READY_TO_RENDER, ProjectStatus.RENDERING, ProjectStatus.QC_PENDING,
            ProjectStatus.REVIEW_REQUIRED, *all_post_narration,
        )
        self.status.voice_plan_ready = self.status.story_analyzed
        self.status.sound_directed = self.status.story_analyzed
        self.status.resources_checked = stage in (
            ProjectStatus.RESOURCE_BLOCKED, ProjectStatus.READY_TO_RENDER, ProjectStatus.RENDERING,
            ProjectStatus.QC_PENDING, ProjectStatus.REVIEW_REQUIRED, *all_post_narration,
        )
        self.status.render_ready = stage in (
            ProjectStatus.READY_TO_RENDER, ProjectStatus.RENDERING, ProjectStatus.QC_PENDING,
            ProjectStatus.REVIEW_REQUIRED, *all_post_narration,
        )
        self.status.narration_ready = stage in all_post_narration

    def to_dict(self) -> dict[str, Any]:
        self.sync_legacy_status()
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectState:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ProjectState:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)


# ==========================================
# 2. TTS Provider Contracts (Phase 8)
# ==========================================

class ProviderErrorType(str, Enum):
    AUTH_ERROR = "AUTH_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    TIMEOUT = "TIMEOUT"
    SERVER_ERROR = "SERVER_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    INVALID_AUDIO_RESPONSE = "INVALID_AUDIO_RESPONSE"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN = "UNKNOWN"


class ProviderCapabilities(BaseModel):
    supports_emotion: bool = True
    supports_pace: bool = True
    supports_pronunciation: bool = True
    supports_director_notes: bool = True
    supports_ssml: bool = False
    supports_seed: bool = True


class ProviderHealth(BaseModel):
    available: bool = True
    configured: bool = True
    connectivity_checked: bool = False
    provider_name: str = "fake"
    message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TTSRenderRequest(BaseModel):
    project_id: str
    beat_id: str
    attempt_id: int = 1
    text: str  # Preserves Beat.script.text exactly
    provider_payload_text: str | None = None  # Transformed pronunciation text if required
    language: str = "en-US"
    voice_profile: str = "mythology_narrator_male"
    emotion: str | None = None
    energy: float | None = None
    pace: float | None = None
    target_wpm: int | None = None
    director_note: str | None = None
    pronunciation: dict[str, str] = Field(default_factory=dict)
    emphasis: list[str] = Field(default_factory=list)
    pause_before: float = 0.0
    pause_after: float = 0.0
    output_format: str = "wav"


class TTSRenderResult(BaseModel):
    success: bool
    provider: str
    model: str
    audio_path: str | None = None
    duration: float = 0.0
    sample_rate: int = 24000
    channels: int = 1
    provider_request_id: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    error_type: ProviderErrorType | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None


# ==========================================
# 3. Voice QC Contracts (Phase 9)
# ==========================================

class SignalQCResult(BaseModel):
    passed: bool = True
    duration: float = 0.0
    peak_dbfs: float = -3.0
    rms_dbfs: float = -20.0
    clipping_detected: bool = False
    silence_ratio: float = 0.0
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContentQCResult(BaseModel):
    passed: bool = True
    wer: float = 0.0
    accuracy_percent: float = 100.0
    transcription: str = ""
    missing_words: list[str] = Field(default_factory=list)
    repeated_words: list[str] = Field(default_factory=list)
    actual_wpm: float = 138.0
    target_wpm: float | None = None
    pronunciation_risk_flags: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class DirectionQCResult(BaseModel):
    passed: bool = True
    expected_duration_range: tuple[float, float] = (0.5, 10.0)
    actual_duration: float = 0.0
    expected_wpm: float | None = None
    actual_wpm: float = 0.0
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BeatQCResult(BaseModel):
    beat_id: str
    attempt_id: int
    signal: SignalQCResult
    content: ContentQCResult
    direction: DirectionQCResult
    verdict: QCVerdict
    qc_score: float = 100.0
    retry_reason: str | None = None
    retry_adjustment: dict[str, Any] | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ==========================================
# 4. Render Manifest & Attempts (Phase 8 & 9)
# ==========================================

class RenderAttempt(BaseModel):
    attempt: int
    provider: str
    model: str
    status: RenderStatus
    audio_path: str
    duration: float = 0.0
    sample_rate: int = 24000
    channels: int = 1
    direction_summary: dict[str, Any] = Field(default_factory=dict)
    qc_result: BeatQCResult | None = None
    error: str | None = None
    error_type: ProviderErrorType | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class BeatRenderState(BaseModel):
    beat_id: str
    status: RenderStatus = RenderStatus.PENDING
    selected_attempt: int | None = None
    attempts: list[RenderAttempt] = Field(default_factory=list)


class RenderManifest(BaseModel):
    version: int = 1
    project_id: str
    beats: dict[str, BeatRenderState] = Field(default_factory=dict)
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RenderManifest:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> RenderManifest:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)

    def get_or_create_beat(self, beat_id: str) -> BeatRenderState:
        if beat_id not in self.beats:
            self.beats[beat_id] = BeatRenderState(beat_id=beat_id)
        return self.beats[beat_id]
