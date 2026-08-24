"""Public REST schemas and request/response models for Voice Projects (Phase 12-14).

Defines stable contract models for HTTP requests, asynchronous operation jobs,
agent summaries, resource reports, mix plans, artifacts, and structured domain errors.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------


class CreateVoiceProjectRequest(BaseModel):
    """Payload to create a new narration voice project."""

    project_id: str | None = Field(
        default=None,
        description="Unique project identifier slug (letters, numbers, hyphens, underscores). Auto-generated if omitted.",
        examples=["torch_dragon"],
    )
    title: str | None = Field(
        default=None,
        description="Human-readable project title.",
        examples=["The Torch Dragon of Mount Zhong"],
    )
    language: str = Field(
        default="en",
        description="Source text language code.",
        examples=["en"],
    )
    script_text: str = Field(
        ...,
        description="Source script raw text to narrate.",
        examples=["What if I told you that the sun is not a burning ball of plasma..."],
    )
    config: dict[str, Any] | None = Field(
        default=None,
        description="Optional voice configuration overrides (e.g. voice profile, provider defaults).",
    )


class UpdateVoiceScriptRequest(BaseModel):
    """Payload to update the source script of an existing project."""

    script_text: str = Field(
        ...,
        description="New source script text. Updating invalidates all downstream artifacts and resets stage to NEW.",
    )


class PlanVoiceProjectRequest(BaseModel):
    """Payload to trigger project story analysis and voice planning."""

    config: dict[str, Any] | None = Field(
        default=None,
        description="Optional planning parameter overrides.",
    )


class CheckVoiceResourcesRequest(BaseModel):
    """Payload to trigger resource checking and knowledge resolution."""

    manifest_path: str | None = Field(
        default=None,
        description="Custom asset manifest YAML path. Uses default repository manifest if omitted.",
    )


class RenderVoiceProjectRequest(BaseModel):
    """Payload to trigger narration synthesis and automated voice QC."""

    provider: str = Field(
        default="local",
        description="Semantic TTS provider name: 'local' (in-process Chatterbox runtime), 'gemini' (cloud), or 'fake' (testing only).",
        examples=["local"],
    )
    beats: list[str] | None = Field(
        default=None,
        description="Optional subset of beat IDs to render (e.g. ['B01', 'B02']). Renders all beats if omitted.",
    )
    auto_qc: bool = Field(
        default=True,
        description="Whether to perform automated Signal QC and Speech Critic evaluation on rendered audio.",
    )
    force_rerender: bool = Field(
        default=False,
        description="Whether to re-synthesize beats even if already in PASSED status.",
    )


class RenderBeatRequest(BaseModel):
    """Payload to render/rerender a single specific beat."""

    provider: str = Field(
        default="local",
        description="Semantic TTS provider: 'local', 'gemini', or 'fake'.",
    )


class EvaluateVoiceProjectRequest(BaseModel):
    """Payload to re-evaluate Voice QC without synthesizing audio."""

    beats: list[str] | None = Field(
        default=None,
        description="Optional subset of beat IDs to re-evaluate.",
    )


class PrepareMixRequest(BaseModel):
    """Payload to prepare deterministic MixPlan."""

    mastering_profile: str = Field(
        default="storytelling",
        description="Target audio mastering profile (e.g. 'storytelling', 'podcast').",
    )
    output_formats: list[str] = Field(
        default=["wav"],
        description="List of target export formats ('wav', 'mp3').",
    )
    mix_config: dict[str, Any] | None = Field(
        default=None,
        description="Optional mix parameter overrides.",
    )


class MixVoiceProjectRequest(BaseModel):
    """Payload to execute multi-track audio mixing."""

    mix_config: dict[str, Any] | None = Field(
        default=None,
        description="Optional mix parameter overrides.",
    )


class MasterVoiceProjectRequest(BaseModel):
    """Payload to execute mastering on mixed audio."""

    profile: str = Field(
        default="storytelling",
        description="Target mastering profile.",
    )


class ExportVoiceProjectRequest(BaseModel):
    """Payload to export final master audio files."""

    formats: list[str] = Field(
        default=["wav"],
        description="Target formats to export (e.g. ['wav']).",
    )


class FinalizeVoiceProjectRequest(BaseModel):
    """Payload to execute end-to-end post-production (prepare_mix -> mix -> master -> export)."""

    mastering_profile: str = Field(
        default="storytelling",
        description="Target mastering profile.",
    )
    output_formats: list[str] = Field(
        default=["wav"],
        description="Target output formats.",
    )
    mix_config: dict[str, Any] | None = Field(
        default=None,
        description="Optional mix parameter overrides.",
    )


# ---------------------------------------------------------
# Sub-models & Summary DTOs
# ---------------------------------------------------------


class HumanActionSchema(BaseModel):
    """Structured request for human or AI supervisor action."""

    action_type: str = Field(
        description="Action type code: pronunciation_review, resource_required, audio_quality_review, script_confirmation"
    )
    reason: str = Field(description="Explanatory reason why action is requested.")
    items: list[str] = Field(
        default_factory=list, description="Target entities, terms, or beat IDs requiring attention."
    )
    available_options: list[str] = Field(
        default_factory=list, description="List of valid resume options for the agent/user."
    )
    resume_action: str | None = Field(
        default=None, description="Suggested method or endpoint to invoke once human action is resolved."
    )


class VoiceProjectBeatsSummary(BaseModel):
    """Aggregated narration beat status statistics."""

    total: int = 0
    rendered: int = 0
    passed: int = 0
    review: int = 0
    failed: int = 0


class VoiceProjectResourcesSummary(BaseModel):
    """Aggregated resource readiness statistics."""

    readiness_score: int | None = None
    blocked: bool | None = None
    required_gaps_count: int = 0
    recommended_gaps_count: int = 0


class ArtifactInfo(BaseModel):
    """Metadata for an exported audio or YAML artifact."""

    id: str = Field(description="Artifact identifier slug.")
    type: str = Field(description="Artifact type (e.g. 'final_wav', 'final_mp3', 'mix_wav', 'master_wav', 'manifest').")
    filename: str = Field(description="File name.")
    size_bytes: int = Field(default=0, description="File size in bytes.")
    sha256: str = Field(default="", description="SHA-256 content checksum.")
    created_at: str = Field(description="ISO 8601 creation timestamp.")
    download_url: str = Field(description="Safe relative API download URL.")


# ---------------------------------------------------------
# Response Models
# ---------------------------------------------------------


class VoiceProjectResponse(BaseModel):
    """Agent-friendly comprehensive project summary."""

    project_id: str
    title: str
    stage: str
    language: str = "en"
    beats: VoiceProjectBeatsSummary = Field(default_factory=VoiceProjectBeatsSummary)
    resources: VoiceProjectResourcesSummary = Field(default_factory=VoiceProjectResourcesSummary)
    suggested_action: str
    human_action: HumanActionSchema | None = None
    last_error: str | None = None


class VoiceProjectOperationResponse(BaseModel):
    """Accepted response (HTTP 202) for background project operations."""

    job_id: str
    project_id: str
    operation: str
    status: str
    message: str | None = None


class VoiceProjectJobResponse(BaseModel):
    """Status details for an asynchronous Voice Project operation."""

    id: str
    project_id: str
    operation: str
    status: str
    stage: str | None = None
    beat_id: str | None = None
    child_job_id: str | None = None
    progress_percent: float = 0.0
    message: str | None = None
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class VoiceProjectArtifactsListResponse(BaseModel):
    """Listing of downloadable artifacts generated for a project."""

    project_id: str
    artifacts: list[ArtifactInfo] = Field(default_factory=list)


class VoiceProjectErrorDetail(BaseModel):
    """Structured error payload for application errors."""

    code: str
    message: str
    project_id: str | None = None
    human_action: HumanActionSchema | None = None
    details: dict[str, Any] | None = None


class VoiceProjectErrorResponse(BaseModel):
    """Outer error envelope."""

    error: VoiceProjectErrorDetail
