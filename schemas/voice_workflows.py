"""Public REST Schemas for Voice Workflows (Phase 15).

Defines stable contract models for autonomous multi-step workflow requests,
execution status, human gates, and deliverable manifests.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class WorkflowPolicySchema(BaseModel):
    """Execution policy parameters for autonomous production."""

    provider: str = Field(
        default="local",
        description="Target TTS provider ('local', 'gemini', 'fake').",
    )
    retry_budget: int = Field(
        default=2,
        description="Maximum automated QC retry budget per narration beat.",
    )
    auto_accept_qc_pass: bool = Field(
        default=True,
        description="Automatically accept and select audio attempts that achieve a passing QC verdict.",
    )
    allow_resource_substitute: bool = Field(
        default=True,
        description="Allow automatic semantic substitution of missing SFX and ambience assets.",
    )
    mixing_profile: str = Field(
        default="storytelling",
        description="Mixing profile name for timeline timing and ducking rules.",
    )
    mastering_profile: str = Field(
        default="storytelling",
        description="Mastering dynamics and loudness profile name.",
    )
    output_formats: list[str] = Field(
        default_factory=lambda: ["wav"],
        description="Target deliverables audio formats (e.g. ['wav', 'mp3']).",
    )
    require_final_approval: bool = Field(
        default=False,
        description="Pause workflow for human director approval after mastering before final deliverable export.",
    )


class CreateVoiceWorkflowRequest(BaseModel):
    """Payload to launch an autonomous end-to-end voice production workflow."""

    project_id: str | None = Field(
        default=None,
        description="Optional custom project ID slug. Auto-generated if omitted.",
        examples=["torch_dragon_wf"],
    )
    title: str | None = Field(
        default=None,
        description="Optional human-readable story title.",
    )
    language: str = Field(
        default="en",
        description="Source script language code.",
    )
    script_text: str = Field(
        ...,
        description="Full raw story script text to produce into complete master audio.",
    )
    policy: WorkflowPolicySchema = Field(
        default_factory=WorkflowPolicySchema,
        description="Autonomous execution policy rules.",
    )


class WorkflowStepSchema(BaseModel):
    """Status record of an individual workflow step."""

    name: str
    status: str
    operation_id: str | None = None
    progress_percent: float | None = None
    started_at: str | None = None
    completed_at: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class VoiceWorkflowResponse(BaseModel):
    """Comprehensive state response for an autonomous workflow."""

    workflow_id: str
    project_id: str
    status: str
    policy: WorkflowPolicySchema = Field(default_factory=WorkflowPolicySchema)
    steps: list[WorkflowStepSchema] = Field(default_factory=list)
    current_step: str | None = None
    human_action: dict[str, Any] | None = None
    suggested_action: str = ""
    created_at: str
    updated_at: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
