"""Voice Project Preflight Request Validation (Phase 12-13 Hardening).

Performs synchronous application-level preflight validation before enqueuing
background operations to guarantee that malformed, stale, or blocked requests
fail immediately with stable HTTP error codes (404/409/503/422) instead of
returning 202 Accepted and failing in the background.
"""

from __future__ import annotations

import logging
from typing import Any

from services.render_models import ProjectStatus
from services.voice_project_models import (
    BeatNotFoundError,
    InvalidProjectStateError,
    ResourceBlockedError,
    StaleArtifactError,
    VoiceProjectNotFound,
)
from services.voice_project_store import VoiceProjectStore

logger = logging.getLogger(__name__)


class VoiceProjectPreflight:
    """Synchronous preflight validator for Voice Project operations."""

    def __init__(self, store: VoiceProjectStore | None = None) -> None:
        self.store = store or VoiceProjectStore()

    def validate_project_exists(self, project_id: str) -> None:
        """Ensure the target project exists on disk."""
        if not self.store.project_exists(project_id):
            raise VoiceProjectNotFound(f"Voice project '{project_id}' not found.")

    def validate_plan_request(self, project_id: str) -> None:
        """Validate pre-conditions for planning a voice project."""
        self.validate_project_exists(project_id)
        state = self.store.get_project_state(project_id)
        allowed_from = (
            ProjectStatus.NEW,
            ProjectStatus.PLANNED,
            ProjectStatus.FAILED,
            ProjectStatus.RESOURCE_BLOCKED,
            ProjectStatus.READY_TO_RENDER,
            ProjectStatus.NARRATION_READY,
            ProjectStatus.REVIEW_REQUIRED,
        )
        if state.stage not in allowed_from:
            raise InvalidProjectStateError(
                f"Cannot plan project '{project_id}' from current stage '{state.stage.value}'."
            )

    def validate_resource_check_request(self, project_id: str) -> None:
        """Validate pre-conditions for resource check."""
        self.validate_project_exists(project_id)
        state = self.store.get_project_state(project_id)
        allowed_from = (
            ProjectStatus.PLANNED,
            ProjectStatus.RESOURCE_CHECKING,
            ProjectStatus.RESOURCE_BLOCKED,
            ProjectStatus.READY_TO_RENDER,
            ProjectStatus.REVIEW_REQUIRED,
            ProjectStatus.NARRATION_READY,
            ProjectStatus.FAILED,
        )
        if state.stage not in allowed_from:
            raise InvalidProjectStateError(
                f"Cannot check resources for project '{project_id}' from state '{state.stage.value}'. Must run plan() first."
            )

        # Ensure VoicePlan exists and is not stale
        is_stale, reason = self.store.check_staleness(project_id)
        if is_stale:
            raise StaleArtifactError(f"Cannot check resources: {reason}. Please re-run plan() first.")

    def validate_render_request(
        self,
        project_id: str,
        provider_name: str = "local",
        beats: list[str] | None = None,
    ) -> None:
        """Validate pre-conditions for rendering narration beats."""
        self.validate_project_exists(project_id)
        state = self.store.get_project_state(project_id)

        # 1. Staleness check
        is_stale, reason = self.store.check_staleness(project_id, for_render=True)
        if is_stale:
            raise StaleArtifactError(f"Cannot render: {reason}. Please re-plan and check resources first.")

        # 2. Resource Gate check (STRICT: no public bypass)
        report = self.store.load_resource_report(project_id)
        if report is None:
            raise ResourceBlockedError(
                f"Resource report missing for project '{project_id}'. Run check_resources() first."
            )
        if report.readiness.render_blocked:
            missing_terms = [
                g.term or g.intent or g.id
                for g in report.missing
                if g.priority.value == "required"
            ]
            raise ResourceBlockedError(
                f"Rendering blocked by required resource gaps: {', '.join(missing_terms[:5])}"
            )

        # 3. Stage check
        allowed_from = (
            ProjectStatus.READY_TO_RENDER,
            ProjectStatus.RENDERING,
            ProjectStatus.QC_PENDING,
            ProjectStatus.REVIEW_REQUIRED,
            ProjectStatus.NARRATION_READY,
            ProjectStatus.FAILED,
        )
        if state.stage not in allowed_from:
            raise InvalidProjectStateError(
                f"Cannot render project '{project_id}' from state '{state.stage.value}'."
            )

        # 3. Beat validation if subset requested
        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan() first.")
        if beats:
            valid_ids = {b.id for b in plan.beats}
            unknown_ids = set(beats) - valid_ids
            if unknown_ids:
                raise BeatNotFoundError(
                    f"Beat ID(s) not found in project '{project_id}': {', '.join(sorted(unknown_ids))}"
                )

    def validate_beat_render_request(
        self,
        project_id: str,
        beat_id: str,
        provider_name: str = "local",
    ) -> None:
        """Validate pre-conditions for selective single-beat render."""
        self.validate_render_request(project_id=project_id, provider_name=provider_name, beats=[beat_id])

    def validate_evaluate_request(
        self,
        project_id: str,
        beats: list[str] | None = None,
    ) -> None:
        """Validate pre-conditions for Voice QC re-evaluation."""
        self.validate_project_exists(project_id)
        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan() first.")
        if beats:
            valid_ids = {b.id for b in plan.beats}
            unknown_ids = set(beats) - valid_ids
            if unknown_ids:
                raise BeatNotFoundError(
                    f"Beat ID(s) not found in project '{project_id}': {', '.join(sorted(unknown_ids))}"
                )
