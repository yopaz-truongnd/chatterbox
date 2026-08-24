"""Voice Project Workflow Models (Phase 15).

Defines state machines, execution steps, policy configurations, and human action
contracts for end-to-end autonomous voice project orchestration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
import yaml
from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class WorkflowStepName(str, Enum):
    CREATE_PROJECT = "create_project"
    PLAN = "plan"
    CHECK_RESOURCES = "check_resources"
    RENDER = "render"
    EVALUATE = "evaluate"
    PREPARE_MIX = "prepare_mix"
    MIX = "mix"
    MASTER = "master"
    EXPORT = "export"
    COMPLETE = "complete"


class WorkflowStep(BaseModel):
    """Execution step record within a workflow."""

    name: str
    status: str = "pending"  # pending | running | completed | failed | skipped
    operation_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None
    retry_count: int = 0
    dependency_hashes: dict[str, str] = Field(default_factory=dict)


class WorkflowPolicy(BaseModel):
    """Guiding execution rules and constraints for the autonomous agent."""

    provider: str = "local"
    retry_budget: int = 2
    auto_accept_qc_pass: bool = True
    allow_resource_substitute: bool = True
    require_final_approval: bool = False
    output_formats: list[str] = Field(default_factory=lambda: ["wav"])
    mixing_profile: str = "storytelling"
    mastering_profile: str = "storytelling"


class VoiceWorkflowState(BaseModel):
    """Complete persistent state record for an orchestrated workflow."""

    workflow_id: str
    project_id: str
    status: WorkflowStatus = WorkflowStatus.QUEUED
    policy: WorkflowPolicy = Field(default_factory=WorkflowPolicy)
    steps: list[WorkflowStep] = Field(default_factory=list)
    current_step: str | None = None
    human_action: dict[str, Any] | None = None
    suggested_action: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceWorkflowState:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> VoiceWorkflowState:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)
