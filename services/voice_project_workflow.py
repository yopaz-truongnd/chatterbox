"""Unified Voice Project Autonomous Workflow Orchestrator (Phase 15).

Coordinates end-to-end multi-step voice project execution (Script -> Planning ->
Resources -> Render -> QC -> Mix -> Master -> Export -> Final Deliverables).
Enforces human gates at required resource gaps or quality review requests without
silent bypasses or framework coupling.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Callable
import uuid

from services.render_models import ProjectStatus, RenderStatus
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_service,
    get_voice_project_store,
    resolve_server_tts_provider,
)
from services.voice_project_models import (
    HumanActionRequired,
    HumanActionType,
    InvalidProjectStateError,
    ResourceBlockedError,
)
from services.voice_project_workflow_models import (
    VoiceWorkflowState,
    WorkflowPolicy,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepName,
)
from services.voice_project_workflow_store import VoiceProjectWorkflowStore

logger = logging.getLogger(__name__)

_GLOBAL_WORKFLOW_STORE: VoiceProjectWorkflowStore | None = None


def get_workflow_store() -> VoiceProjectWorkflowStore:
    """Retrieve shared workflow store singleton."""
    global _GLOBAL_WORKFLOW_STORE
    if _GLOBAL_WORKFLOW_STORE is None:
        _GLOBAL_WORKFLOW_STORE = VoiceProjectWorkflowStore()
    return _GLOBAL_WORKFLOW_STORE


class VoiceProjectWorkflowService:
    """Autonomous orchestration service for voice projects."""

    def __init__(self, store: VoiceProjectWorkflowStore | None = None):
        self.store = store or get_workflow_store()
        self.project_store = get_voice_project_store()
        self.op_manager = get_voice_project_operation_manager()

    def start_workflow(
        self,
        script_text: str,
        project_id: str | None = None,
        title: str | None = None,
        language: str = "en",
        policy: WorkflowPolicy | None = None,
    ) -> VoiceWorkflowState:
        """Initialize and begin execution of an autonomous voice production workflow."""
        wf_policy = policy or WorkflowPolicy()
        target_pid = project_id or f"proj_{uuid.uuid4().hex[:8]}"
        wf_id = f"vwf_{uuid.uuid4().hex[:12]}"

        state = VoiceWorkflowState(
            workflow_id=wf_id,
            project_id=target_pid,
            status=WorkflowStatus.RUNNING,
            policy=wf_policy,
            steps=[
                WorkflowStep(name=WorkflowStepName.CREATE_PROJECT.value, status="pending"),
                WorkflowStep(name=WorkflowStepName.PLAN.value, status="pending"),
                WorkflowStep(name=WorkflowStepName.CHECK_RESOURCES.value, status="pending"),
                WorkflowStep(name=WorkflowStepName.RENDER.value, status="pending"),
                WorkflowStep(name=WorkflowStepName.PREPARE_MIX.value, status="pending"),
                WorkflowStep(name=WorkflowStepName.MIX.value, status="pending"),
                WorkflowStep(name=WorkflowStepName.MASTER.value, status="pending"),
                WorkflowStep(name=WorkflowStepName.EXPORT.value, status="pending"),
            ],
            current_step=WorkflowStepName.CREATE_PROJECT.value,
            suggested_action="Executing workflow...",
        )
        self.store.save_workflow(state)

        # Run execution loop asynchronously in background thread
        threading.Thread(
            target=self._execute_workflow_loop,
            args=(state.workflow_id, script_text, title, language),
            daemon=True,
            name=f"Workflow-{wf_id}",
        ).start()

        return state

    def get_workflow(self, workflow_id: str) -> VoiceWorkflowState | None:
        """Retrieve live workflow status and human action gates."""
        return self.store.get_workflow(workflow_id)

    def cancel_workflow(self, workflow_id: str) -> tuple[bool, str]:
        """Cancel an in-flight workflow and terminate active operations."""
        state = self.store.get_workflow(workflow_id)
        if not state:
            return False, f"Workflow '{workflow_id}' not found."

        if state.status in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED, WorkflowStatus.FAILED):
            return False, f"Workflow '{workflow_id}' is already in terminal state '{state.status.value}'."

        state.status = WorkflowStatus.CANCELLED
        state.updated_at = datetime.now(timezone.utc).isoformat()
        state.error = {"code": "WORKFLOW_CANCELLED", "message": "Workflow was cancelled by user."}
        self.store.save_workflow(state)

        # Cancel active project operations if running
        active_job = self.op_manager._project_active_op.get(state.project_id)
        if active_job:
            self.op_manager.cancel_operation(active_job)

        return True, f"Workflow '{workflow_id}' cancelled."

    def resume_workflow(self, workflow_id: str) -> VoiceWorkflowState:
        """Resume workflow execution after a human gate (e.g. pronunciation provided) has been resolved."""
        state = self.store.get_workflow(workflow_id)
        if not state:
            raise ValueError(f"Workflow '{workflow_id}' not found.")

        if state.status != WorkflowStatus.WAITING_FOR_HUMAN:
            raise InvalidProjectStateError(
                f"Workflow '{workflow_id}' is in status '{state.status.value}'; only workflows in 'waiting_for_human' can be resumed."
            )

        state.status = WorkflowStatus.RUNNING
        state.human_action = None
        state.suggested_action = "Resuming workflow execution..."
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_workflow(state)

        # Launch background resume loop
        threading.Thread(
            target=self._execute_workflow_loop,
            args=(state.workflow_id, None, None, None),
            daemon=True,
            name=f"WorkflowResume-{workflow_id}",
        ).start()

        return state

    def _mark_step(
        self,
        state: VoiceWorkflowState,
        step_name: str,
        status: str,
        result_summary: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Update individual step record within workflow state."""
        fresh_state = self.store.get_workflow(state.workflow_id)
        if fresh_state and fresh_state.status == WorkflowStatus.CANCELLED:
            state.status = WorkflowStatus.CANCELLED
            return

        for step in state.steps:
            if step.name == step_name:
                step.status = status
                if status == "running":
                    step.started_at = datetime.now(timezone.utc).isoformat()
                    state.current_step = step_name
                elif status in ("completed", "failed", "skipped"):
                    step.completed_at = datetime.now(timezone.utc).isoformat()
                if result_summary:
                    step.result_summary = result_summary
                if error:
                    step.error = error
                break
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_workflow(state)

    def _execute_workflow_loop(
        self,
        workflow_id: str,
        script_text: str | None,
        title: str | None,
        language: str | None,
    ) -> None:
        """Main autonomous execution loop coordinating VoiceProjectService."""
        state = self.store.get_workflow(workflow_id)
        if not state:
            return

        service = get_voice_project_service(provider_name=state.policy.provider)
        project_id = state.project_id

        try:
            # 1. Step: CREATE_PROJECT
            if script_text:
                self._mark_step(state, WorkflowStepName.CREATE_PROJECT.value, "running")
                if not self.project_store.project_exists(project_id):
                    service.create_project(
                        script_text=script_text,
                        project_id=project_id,
                        title=title,
                        language=language or "en",
                    )
                self._mark_step(state, WorkflowStepName.CREATE_PROJECT.value, "completed", {"project_id": project_id})

            # Check for cancellation
            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 2. Step: PLAN
            p_state = self.project_store.get_project_state(project_id)
            if p_state.stage == ProjectStatus.NEW or not self.project_store.load_voice_plan(project_id):
                self._mark_step(state, WorkflowStepName.PLAN.value, "running")
                plan_res = service.plan(project_id)
                self._mark_step(
                    state,
                    WorkflowStepName.PLAN.value,
                    "completed",
                    {"beat_count": plan_res.beat_count},
                )

            # Check for cancellation
            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 3. Step: CHECK_RESOURCES
            self._mark_step(state, WorkflowStepName.CHECK_RESOURCES.value, "running")
            res_report = service.check_resources(project_id)

            # Human Gate: Resource Blocked
            if res_report.render_blocked:
                missing_terms = res_report.required_missing or ["Unverified pronunciation/audio asset"]
                state.status = WorkflowStatus.WAITING_FOR_HUMAN
                state.human_action = {
                    "action_type": "resource_required",
                    "reason": "Required audio assets or proper noun pronunciations are unverified",
                    "items": missing_terms,
                    "available_options": ["add_pronunciation", "cancel_workflow"],
                    "resume_action": "check_resources",
                }
                state.suggested_action = f"Add pronunciations or resources for: {', '.join(missing_terms[:3])}"
                self._mark_step(
                    state,
                    WorkflowStepName.CHECK_RESOURCES.value,
                    "failed",
                    error={"code": "RESOURCE_BLOCKED", "message": "Required resources missing"},
                )
                self.store.save_workflow(state)
                return  # Pause workflow until user/agent resumes

            self._mark_step(
                state,
                WorkflowStepName.CHECK_RESOURCES.value,
                "completed",
                {"readiness_score": res_report.readiness_score, "gaps_count": len(res_report.required_missing) + len(res_report.recommended_missing)},
            )

            # 4. Step: RENDER
            self._mark_step(state, WorkflowStepName.RENDER.value, "running")
            render_res = service.render(project_id, auto_qc=True)

            # Human Gate: Quality Review Required
            if render_res.stage == ProjectStatus.REVIEW_REQUIRED:
                manifest = self.project_store.load_manifest(project_id)
                review_ids = [
                    bid for bid, b in manifest.beats.items() if b.status == RenderStatus.NEEDS_REVIEW
                ]
                state.status = WorkflowStatus.WAITING_FOR_HUMAN
                state.human_action = {
                    "action_type": "audio_quality_review",
                    "reason": "One or more rendered beats did not achieve passing QC score",
                    "items": review_ids,
                    "available_options": ["accept_beat", "rerender_beat", "cancel_workflow"],
                    "resume_action": "evaluate",
                }
                state.suggested_action = f"Review quality for beats: {', '.join(review_ids)}"
                self._mark_step(state, WorkflowStepName.RENDER.value, "failed", error={"code": "REVIEW_REQUIRED"})
                self.store.save_workflow(state)
                return

            if render_res.stage not in (ProjectStatus.NARRATION_READY, ProjectStatus.COMPLETED):
                raise RuntimeError(f"Rendering did not achieve NARRATION_READY; ended in '{render_res.stage.value}'.")

            self._mark_step(
                state,
                WorkflowStepName.RENDER.value,
                "completed",
                {"passed_beats": render_res.passed_beats, "total_beats": render_res.total_beats},
            )

            # 5. Step: FINALIZE (Prepare Mix -> Mix -> Master -> Export)
            self._mark_step(state, WorkflowStepName.PREPARE_MIX.value, "running")
            service.prepare_for_mix(
                project_id,
                mastering_profile=state.policy.mastering_profile,
                output_formats=state.policy.output_formats,
            )
            self._mark_step(state, WorkflowStepName.PREPARE_MIX.value, "completed")

            self._mark_step(state, WorkflowStepName.MIX.value, "running")
            service.mix(project_id)
            self._mark_step(state, WorkflowStepName.MIX.value, "completed")

            self._mark_step(state, WorkflowStepName.MASTER.value, "running")
            service.master(project_id, profile_name=state.policy.mastering_profile)
            self._mark_step(state, WorkflowStepName.MASTER.value, "completed")

            self._mark_step(state, WorkflowStepName.EXPORT.value, "running")
            export_manifest = service.export(project_id, formats=state.policy.output_formats)
            self._mark_step(state, WorkflowStepName.EXPORT.value, "completed")

            # Complete Workflow
            artifacts = service.list_artifacts(project_id)
            state.status = WorkflowStatus.COMPLETED
            state.current_step = WorkflowStepName.COMPLETE.value
            state.suggested_action = "Production completed successfully. Audio deliverables ready."
            state.result = {
                "project_id": project_id,
                "artifacts": artifacts,
                "manifest": export_manifest.to_dict(),
            }
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_workflow(state)

        except Exception as exc:
            fresh_state = self.store.get_workflow(workflow_id)
            if fresh_state and fresh_state.status == WorkflowStatus.CANCELLED:
                logger.info("Workflow '%s' was cancelled, skipping failure marking.", workflow_id)
                return
            logger.exception("Workflow '%s' execution failed: %s", workflow_id, exc)
            state.status = WorkflowStatus.FAILED
            state.error = {"code": type(exc).__name__, "message": str(exc)}
            state.suggested_action = f"Workflow failed: {str(exc)}"
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_workflow(state)
