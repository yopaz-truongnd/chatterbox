"""Unified Autonomous Voice Project Production Workflow (Phase 15).

Coordinates the end-to-end voice story production lifecycle through VoiceProjectService:
1. Script intake & project initialization
2. Story analysis, voice planning & sound direction
3. Pronunciation & audio resource resolution
4. Per-beat TTS synthesis and 3-layer Voice QC
5. Multi-track mix timeline preparation & crossfade rendering
6. Dynamics mastering (loudness normalization & true-peak limiter)
7. Deliverables packaging (FINAL.wav, FINAL.mp3, export-manifest.yaml)

Coordinates every step cleanly through VoiceProjectOperationManager to guarantee
project serialization, progress reporting, and immediate cancellation propagation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from pathlib import Path
import threading
import time
from typing import Any, Callable
import uuid

from services.audio_mix_models import ExportManifest
from services.render_models import ProjectStatus, RenderStatus
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_service,
    get_voice_project_store,
)
from services.voice_project_models import (
    HumanActionType,
    InvalidProjectStateError,
    ProviderUnavailableError,
)
from services.voice_project_operations import OperationStatus, VoiceProjectOperationManager
from services.voice_project_store import VoiceProjectStore
from services.voice_project_workflow_models import (
    VoiceWorkflowState,
    WorkflowPolicy,
    WorkflowStatus,
    WorkflowStep,
    WorkflowStepName,
)
from services.voice_project_workflow_store import VoiceProjectWorkflowStore

logger = logging.getLogger(__name__)


class VoiceProjectWorkflowService:
    """Autonomous orchestrator for end-to-end Voice Projects."""

    def __init__(
        self,
        store: VoiceProjectWorkflowStore | None = None,
        project_store: VoiceProjectStore | None = None,
        op_manager: VoiceProjectOperationManager | None = None,
    ) -> None:
        self.store = store or VoiceProjectWorkflowStore()
        self.project_store = project_store or get_voice_project_store()
        self.op_manager = op_manager or get_voice_project_operation_manager()

    def start_workflow(
        self,
        script_text: str,
        project_id: str | None = None,
        title: str | None = None,
        language: str = "en",
        policy: WorkflowPolicy | None = None,
    ) -> VoiceWorkflowState:
        """Initialize and launch an autonomous voice story production workflow."""
        proj_id = project_id or f"voice_proj_{uuid.uuid4().hex[:8]}"
        wf_id = f"vwf_{uuid.uuid4().hex[:12]}"
        pol = policy or WorkflowPolicy()

        state = VoiceWorkflowState(
            workflow_id=wf_id,
            project_id=proj_id,
            status=WorkflowStatus.RUNNING,
            policy=pol,
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
        if not fresh_state:
            return
        if fresh_state.status == WorkflowStatus.CANCELLED:
            state.status = WorkflowStatus.CANCELLED
            return

        for step in fresh_state.steps:
            if step.name == step_name:
                step.status = status
                if status == "running":
                    step.started_at = datetime.now(timezone.utc).isoformat()
                    fresh_state.current_step = step_name
                elif status in ("completed", "failed", "skipped"):
                    step.completed_at = datetime.now(timezone.utc).isoformat()
                if result_summary:
                    step.result_summary = result_summary
                if error:
                    step.error = error
                break
        fresh_state.updated_at = datetime.now(timezone.utc).isoformat()
        self.store.save_workflow(fresh_state)

    def _run_workflow_op(
        self,
        workflow_id: str,
        step_name: str,
        op_name: str,
        fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Submit operation through operation manager and wait synchronously for completion with cancellation polling."""
        state = self.store.get_workflow(workflow_id)
        if not state or state.status == WorkflowStatus.CANCELLED:
            return None

        self._mark_step(state, step_name, "running")
        op = self.op_manager.submit(state.project_id, op_name, fn, *args, **kwargs)

        for s in state.steps:
            if s.name == step_name:
                s.operation_id = op.id
        self.store.save_workflow(state)

        while True:
            fresh_state = self.store.get_workflow(workflow_id)
            if not fresh_state or fresh_state.status == WorkflowStatus.CANCELLED:
                self.op_manager.cancel_operation(op.id)
                return None

            curr_op = self.op_manager.get_operation(op.id)
            if not curr_op:
                break

            if curr_op.progress_percent > 0:
                for s in fresh_state.steps:
                    if s.name == step_name:
                        s.progress_percent = curr_op.progress_percent
                self.store.save_workflow(fresh_state)

            if curr_op.status == OperationStatus.COMPLETED:
                self._mark_step(fresh_state, step_name, "completed", result_summary={"operation_id": op.id})
                return curr_op.result
            elif curr_op.status in (OperationStatus.FAILED, OperationStatus.INTERRUPTED):
                err = curr_op.error or {"code": "OPERATION_FAILED", "message": "Operation failed"}
                self._mark_step(fresh_state, step_name, "failed", error=err)
                raise RuntimeError(f"Workflow step '{step_name}' failed: {err.get('message')}")
            elif curr_op.status == OperationStatus.CANCELLED:
                self._mark_step(fresh_state, step_name, "failed", error={"code": "CANCELLED", "message": "Operation cancelled"})
                return None

            time.sleep(0.03)

    def _execute_workflow_loop(
        self,
        workflow_id: str,
        script_text: str | None,
        title: str | None,
        language: str | None,
    ) -> None:
        """Main autonomous execution loop coordinating VoiceProjectService via OperationManager."""
        state = self.store.get_workflow(workflow_id)
        if not state:
            return

        try:
            service = get_voice_project_service(provider_name=state.policy.provider)
            project_id = state.project_id

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

            # 2. Step: PLAN (via OperationManager)
            p_state = self.project_store.get_project_state(project_id)
            if p_state.stage == ProjectStatus.NEW or not self.project_store.load_voice_plan(project_id):
                plan_res = self._run_workflow_op(
                    workflow_id,
                    WorkflowStepName.PLAN.value,
                    "plan",
                    service.plan,
                    project_id,
                )
                if plan_res is None:
                    return

            # Check for cancellation
            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 3. Step: CHECK_RESOURCES (via OperationManager)
            res_report = self._run_workflow_op(
                workflow_id,
                WorkflowStepName.CHECK_RESOURCES.value,
                "check_resources",
                service.check_resources,
                project_id,
            )
            if res_report is None:
                return

            render_blocked = res_report.get("render_blocked", False) if isinstance(res_report, dict) else getattr(res_report, "render_blocked", False)
            required_missing = res_report.get("required_missing", []) if isinstance(res_report, dict) else getattr(res_report, "required_missing", [])
            recommended_missing = res_report.get("recommended_missing", []) if isinstance(res_report, dict) else getattr(res_report, "recommended_missing", [])
            readiness_score = res_report.get("readiness_score", 100.0) if isinstance(res_report, dict) else getattr(res_report, "readiness_score", 100.0)

            # Human Gate: Resource Blocked
            if render_blocked:
                missing_terms = required_missing or ["Unverified pronunciation/audio asset"]
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
                {"readiness_score": readiness_score, "gaps_count": len(required_missing) + len(recommended_missing)},
            )

            # Check for cancellation
            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 4. Step: RENDER (via OperationManager)
            render_res = self._run_workflow_op(
                workflow_id,
                WorkflowStepName.RENDER.value,
                "render",
                service.render,
                project_id,
                auto_qc=True,
            )
            if render_res is None:
                return

            stage_val = render_res.get("stage") if isinstance(render_res, dict) else getattr(render_res, "stage", None)
            stage_str = stage_val.value if hasattr(stage_val, "value") else str(stage_val)

            # Human Gate: Quality Review Required
            if stage_str == ProjectStatus.REVIEW_REQUIRED.value:
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

            if stage_str not in (ProjectStatus.NARRATION_READY.value, ProjectStatus.COMPLETED.value):
                raise RuntimeError(f"Rendering did not achieve NARRATION_READY; ended in '{stage_str}'.")

            # Check for cancellation
            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 5. Step: PREPARE_MIX (via OperationManager)
            self._run_workflow_op(
                workflow_id,
                WorkflowStepName.PREPARE_MIX.value,
                "prepare_mix",
                service.prepare_for_mix,
                project_id,
                mastering_profile=state.policy.mastering_profile,
                output_formats=state.policy.output_formats,
            )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 6. Step: MIX (via OperationManager)
            self._run_workflow_op(
                workflow_id,
                WorkflowStepName.MIX.value,
                "mix",
                service.mix,
                project_id,
            )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 7. Step: MASTER (via OperationManager)
            self._run_workflow_op(
                workflow_id,
                WorkflowStepName.MASTER.value,
                "master",
                service.master,
                project_id,
                profile_name=state.policy.mastering_profile,
            )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # 8. Step: EXPORT (via OperationManager)
            export_manifest = self._run_workflow_op(
                workflow_id,
                WorkflowStepName.EXPORT.value,
                "export",
                service.export,
                project_id,
                formats=state.policy.output_formats,
            )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status == WorkflowStatus.CANCELLED:
                return

            # Complete Workflow
            artifacts = service.list_artifacts(project_id)
            state.status = WorkflowStatus.COMPLETED
            state.current_step = WorkflowStepName.COMPLETE.value
            state.suggested_action = "Production completed successfully. Audio deliverables ready."
            state.result = {
                "project_id": project_id,
                "artifacts": artifacts,
                "manifest": export_manifest.to_dict() if hasattr(export_manifest, "to_dict") else export_manifest,
            }
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_workflow(state)

        except Exception as exc:
            fresh_state = self.store.get_workflow(workflow_id)
            if fresh_state and fresh_state.status == WorkflowStatus.CANCELLED:
                logger.info("Workflow '%s' was cancelled, skipping failure marking.", workflow_id)
                return
            logger.exception("Workflow '%s' execution failed: %s", workflow_id, exc)
            state = fresh_state or state
            state.status = WorkflowStatus.FAILED
            state.error = {"code": type(exc).__name__, "message": str(exc)}
            state.suggested_action = f"Workflow failed: {str(exc)}"
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_workflow(state)
