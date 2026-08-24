"""Canonical Models, DTOs, Error Hierarchy, and Hashes for VoiceProjectService (Phase 11).

Defines typed application contracts for project planning, resource checking,
rendering, human action requests, and staleness detection.
"""

from __future__ import annotations

from enum import Enum
import hashlib
from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field

from services.render_models import ProjectState, ProjectStatus, RenderManifest
from services.voice_renderer import (
    ProviderUnavailableError,
    ResourceBlockedError,
)


# ==========================================
# 1. Error Hierarchy
# ==========================================

class VoiceProjectError(Exception):
    """Base exception for all VoiceProject domain and application errors."""
    pass


class VoiceProjectNotFound(VoiceProjectError):
    """Raised when a requested project workspace is not found on disk."""
    pass


class VoiceProjectAlreadyExists(VoiceProjectError):
    """Raised when project creation would overwrite an existing workspace."""
    pass


class InvalidProjectStateError(VoiceProjectError):
    """Raised when an operation is invalid for the project's current lifecycle stage."""
    pass


class StaleArtifactError(VoiceProjectError):
    """Raised when an artifact (e.g. VoicePlan) is stale relative to its dependency source."""
    pass


class BeatNotFoundError(VoiceProjectError):
    """Raised when a specific beat ID is not found in the project's VoicePlan."""
    pass


# ==========================================
# 2. Hash & Staleness Utilities
# ==========================================

def compute_string_sha256(text: str) -> str:
    """Compute SHA-256 hex digest of a string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_file_sha256(file_path: Path | str) -> str:
    """Compute SHA-256 hex digest of a file on disk."""
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return ""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


# ==========================================
# 3. Human Action Model
# ==========================================

class HumanActionType(str, Enum):
    PRONUNCIATION_REVIEW = "pronunciation_review"
    RESOURCE_REQUIRED = "resource_required"
    AUDIO_QUALITY_REVIEW = "audio_quality_review"
    SCRIPT_CONFIRMATION = "script_confirmation"


class HumanActionRequired(BaseModel):
    """Encapsulates explicit review or missing requirement for Agent/Human loop."""
    action_type: HumanActionType
    reason: str
    items: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


# ==========================================
# 4. Application DTOs
# ==========================================

class VoiceProjectSummary(BaseModel):
    """Agent-facing high-level summary of VoiceProject state and next steps."""
    project_id: str
    title: str = ""
    stage: ProjectStatus
    language: str = "en"
    total_beats: int = 0
    rendered_beats: int = 0
    passed_beats: int = 0
    review_beats: int = 0
    failed_beats: int = 0
    resource_readiness_score: float = 0.0
    resource_blocked: bool = False
    required_gaps_count: int = 0
    recommended_gaps_count: int = 0
    provider: str = "chatterbox-http"
    suggested_action: str = ""
    human_action: HumanActionRequired | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VoicePlanningResult(BaseModel):
    """Result of VoiceProjectService.plan()."""
    model_config = {"arbitrary_types_allowed": True}

    project_id: str
    stage: ProjectStatus
    beat_count: int
    voice_plan_path: str
    critique_path: str
    warnings: list[str] = Field(default_factory=list)
    voice_plan: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        res = self.model_dump(mode="json", exclude={"voice_plan"})
        if self.voice_plan is not None and hasattr(self.voice_plan, "to_dict"):
            res["voice_plan"] = self.voice_plan.to_dict()
        return res


class ResourceCheckResult(BaseModel):
    """Result of VoiceProjectService.check_resources()."""
    model_config = {"arbitrary_types_allowed": True}

    project_id: str
    stage: ProjectStatus
    readiness_score: float
    render_blocked: bool
    required_missing: list[str] = Field(default_factory=list)
    recommended_missing: list[str] = Field(default_factory=list)
    optional_missing: list[str] = Field(default_factory=list)
    pronunciation_overrides: dict[str, str] = Field(default_factory=dict)
    report_path: str = ""
    human_action: HumanActionRequired | None = None
    report: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        res = self.model_dump(mode="json", exclude={"report"})
        if self.report is not None and hasattr(self.report, "to_dict"):
            res["report"] = self.report.to_dict()
        return res


class VoiceRenderResult(BaseModel):
    """Result of VoiceProjectService.render() and render_beat()."""
    model_config = {"arbitrary_types_allowed": True}

    project_id: str
    stage: ProjectStatus
    total_beats: int = 0
    rendered_beats: int = 0
    passed_beats: int = 0
    review_beats: int = 0
    failed_beats: int = 0
    manifest_path: str = ""
    human_action: HumanActionRequired | None = None
    manifest: RenderManifest | None = None

    def to_dict(self) -> dict[str, Any]:
        res = self.model_dump(mode="json", exclude={"manifest"})
        if self.manifest is not None:
            res["manifest"] = self.manifest.to_dict()
        return res
