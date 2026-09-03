"""Typed director review, resource resolution, and revision contracts (Phase 16)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field, field_validator


class DirectorAudioCandidate(BaseModel):
    attempt_id: int
    status: str
    provider: str
    model: str
    artifact_id: str
    duration_ms: float = 0.0
    qc_score: float | None = None
    qc_verdict: str | None = None
    created_at: str
    selected: bool = False
    review: dict[str, Any] | None = None


class DirectorResourceGap(BaseModel):
    resource_id: str
    resource_type: str
    priority: str
    description: str
    affected_beats: list[str] = Field(default_factory=list)
    story_context: str | None = None
    desired_characteristics: dict[str, Any] = Field(default_factory=dict)
    duration_hint_ms: float | None = None
    loopable: bool = False
    suggested_search_queries: list[str] = Field(default_factory=list)
    accepted_formats: list[str] = Field(default_factory=list)
    substitution_candidates: list[dict[str, Any]] = Field(default_factory=list)
    resolution_options: list[str] = Field(default_factory=list)


class DirectorArtifactStatus(BaseModel):
    artifact_id: str
    exists: bool
    fresh: bool
    sha256: str | None = None
    download_url: str | None = None


class DirectorRevisionSummary(BaseModel):
    revision_count: int = 0
    latest_revision_id: str | None = None
    affected_beats: list[str] = Field(default_factory=list)
    invalidated_artifacts: list[str] = Field(default_factory=list)
    required_reproduction_steps: list[str] = Field(default_factory=list)
    final_approval_invalidated: bool = False


class DirectorBeatReview(BaseModel):
    beat_id: str
    source_text: str
    source_start: int
    source_end: int
    role: str
    voice_direction: dict[str, Any]
    emotion: str
    energy: float
    pace: float | None = None
    pause_before_ms: float
    pause_after_ms: float
    ambience_intents: list[str] = Field(default_factory=list)
    sfx_intents: list[str] = Field(default_factory=list)
    pronunciation_terms: list[str] = Field(default_factory=list)
    resource_dependencies: list[str] = Field(default_factory=list)
    render_status: str
    selected_attempt: int | None = None
    available_attempts: list[DirectorAudioCandidate] = Field(default_factory=list)
    qc_summary: dict[str, Any] | None = None
    artifact_freshness: str = "missing"
    available_actions: list[str] = Field(default_factory=list)


class DirectorProjectReview(BaseModel):
    project_id: str
    title: str
    language: str
    project_stage: str
    workflow_id: str | None = None
    workflow_status: str | None = None
    source_script_sha256: str
    script_excerpt: str
    beats: list[DirectorBeatReview] = Field(default_factory=list)
    resource_readiness: int | None = None
    required_resource_gaps: list[DirectorResourceGap] = Field(default_factory=list)
    recommended_resource_gaps: list[DirectorResourceGap] = Field(default_factory=list)
    human_action: dict[str, Any] | None = None
    available_actions: list[str] = Field(default_factory=list)
    artifact_status: list[DirectorArtifactStatus] = Field(default_factory=list)
    revision_summary: DirectorRevisionSummary = Field(default_factory=DirectorRevisionSummary)


class DirectorResourceShoppingList(BaseModel):
    project_id: str
    required_items: list[DirectorResourceGap] = Field(default_factory=list)
    recommended_items: list[DirectorResourceGap] = Field(default_factory=list)
    ready_for_render: bool
    estimated_resource_count: int
    suggested_search_queries: list[str] = Field(default_factory=list)


class DirectorRevisionEvent(BaseModel):
    revision_id: str
    project_id: str
    beat_id: str | None = None
    affected_beats: list[str] = Field(default_factory=list)
    revision_type: str
    actor_type: str = "human"
    actor_id: str = "unknown"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str | None = None
    before: dict[str, Any] = Field(default_factory=dict)
    after: dict[str, Any] = Field(default_factory=dict)
    affected_artifacts: list[str] = Field(default_factory=list)
    required_reproduction_steps: list[str] = Field(default_factory=list)
    approval_required: bool = False
    status: str = "pending"
    reproduced_at: str | None = None


class DirectorRevisionState(BaseModel):
    pending_revision_ids: list[str] = Field(default_factory=list)
    affected_beats: list[str] = Field(default_factory=list)
    invalidated_artifacts: list[str] = Field(default_factory=list)
    required_reproduction_steps: list[str] = Field(default_factory=list)
    final_approval_invalidated: bool = False


class ResourceResolutionResult(BaseModel):
    project_id: str
    resource_id: str
    resource_type: str
    resolution_status: str
    updated_resource_report: dict[str, Any]
    remaining_required_gaps: list[str] = Field(default_factory=list)
    remaining_recommended_gaps: list[str] = Field(default_factory=list)
    affected_beats: list[str] = Field(default_factory=list)
    invalidated_artifacts: list[str] = Field(default_factory=list)
    suggested_action: str


class BeatReviewResult(BaseModel):
    project_id: str
    beat_id: str
    action: str
    selected_attempt: int | None = None
    affected_artifacts: list[str] = Field(default_factory=list)
    required_reproduction_steps: list[str] = Field(default_factory=list)
    suggested_action: str


class BeatDirectionPatch(BaseModel):
    emotion: str | None = None
    energy: float | None = None
    pace: float | None = None
    voice_style: str | None = None

    @field_validator("energy")
    @classmethod
    def validate_energy(cls, value: float | None) -> float | None:
        if value is not None and not 0 <= value <= 5:
            raise ValueError("energy must be between 0 and 5")
        return value


class BeatTimingPatch(BaseModel):
    pause_before_ms: float | None = None
    pause_after_ms: float | None = None

    @field_validator("pause_before_ms", "pause_after_ms")
    @classmethod
    def validate_pause(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("pause duration must be non-negative")
        return value


class BeatResourcePatch(BaseModel):
    ambience_intent: str | None = None
    sfx: list[dict[str, Any]] | None = None


class RevisionImpact(BaseModel):
    project_id: str
    beat_id: str | None = None
    revision_id: str
    invalidated_artifacts: list[str]
    required_reproduction_steps: list[str]
    rerender_beats: list[str] = Field(default_factory=list)
    final_approval_invalidated: bool = False


class IncrementalReproductionResult(BaseModel):
    project_id: str
    affected_beats: list[str] = Field(default_factory=list)
    executed_steps: list[str] = Field(default_factory=list)
    status: str
    suggested_action: str
    # Populated when status == "waiting_for_human" (P1-2)
    artifact_id: str | None = None
    artifact_sha256: str | None = None
    human_action: dict[str, Any] | None = None
    approval_endpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
