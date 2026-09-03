"""Production Event Models (Phase 20).

Defines typed contracts for production observability events, health aggregates,
and stable error codes emitted by the Chatterbox voice production system.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ==========================================
# 1. Stable Production Error Codes
# ==========================================


class ProductionErrorCode(str, Enum):
    """Stable, serializable error codes for the voice production system."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    SERIES_NOT_FOUND = "SERIES_NOT_FOUND"
    RESOURCE_BLOCKED = "RESOURCE_BLOCKED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    QC_REVIEW_REQUIRED = "QC_REVIEW_REQUIRED"
    STALE_ARTIFACT = "STALE_ARTIFACT"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    EXPORT_DEPENDENCY_UNAVAILABLE = "EXPORT_DEPENDENCY_UNAVAILABLE"
    OPERATION_CONFLICT = "OPERATION_CONFLICT"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# ==========================================
# 2. Production Event Types
# ==========================================


class ProductionEventType(str, Enum):
    """Enumeration of all observable production lifecycle events."""

    WORKFLOW_STARTED = "workflow_started"
    STEP_STARTED = "step_started"
    STEP_PROGRESS = "step_progress"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    RESOURCE_BLOCKED = "resource_blocked"
    HUMAN_ACTION_REQUIRED = "human_action_required"
    CANDIDATE_SELECTED = "candidate_selected"
    RETRY_STARTED = "retry_started"
    RETRY_EXHAUSTED = "retry_exhausted"
    MIX_STARTED = "mix_started"
    MASTER_STARTED = "master_started"
    APPROVAL_REQUIRED = "approval_required"
    EXPORT_COMPLETED = "export_completed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    WORKFLOW_RECOVERED = "workflow_recovered"


# ==========================================
# 3. Production Event
# ==========================================


class ProductionEvent(BaseModel):
    """Immutable audit record for a single production lifecycle event."""

    event_id: str = Field(
        default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    project_id: str | None = None
    series_id: str | None = None
    episode_id: str | None = None
    workflow_id: str | None = None
    operation_id: str | None = None
    event_type: ProductionEventType
    step: str | None = None
    progress_percent: float | None = None
    status: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


# ==========================================
# 4. Health Aggregates
# ==========================================


class ProjectProductionHealth(BaseModel):
    """Aggregated health snapshot for a single voice project."""

    project_id: str
    status: str
    current_step: str | None = None
    progress_percent: float | None = None
    active_operation: str | None = None
    last_successful_step: str | None = None
    last_error: dict[str, Any] | None = None
    human_actions: list[dict[str, Any]] = Field(default_factory=list)
    artifact_freshness: dict[str, str] = Field(default_factory=dict)
    runtime_health: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SeriesProductionHealth(BaseModel):
    """Aggregated health snapshot across all episodes in a series."""

    series_id: str
    status: str
    episode_count: int
    completed_count: int
    failed_count: int
    waiting_for_human: int
    progress_percent: float
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
