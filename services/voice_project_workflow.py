"""Unified Autonomous Voice Project Production Workflow (Phase 15).

Coordinates the end-to-end voice story production lifecycle through VoiceProjectService:
1. Script intake & project initialization
2. Story analysis, voice planning & sound direction
3. Pronunciation & audio resource resolution
4. Per-beat TTS synthesis and 3-layer Voice QC
5. Multi-track mix timeline preparation & crossfade rendering
6. Dynamics mastering (loudness normalization & true-peak limiter)
7. Final Director Approval Human Gate (optional policy)
8. Deliverables packaging (FINAL.wav, FINAL.mp3, export-manifest.yaml)

Coordinates every step cleanly through VoiceProjectOperationManager to guarantee
project serialization, progress reporting, and immediate cancellation propagation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
import time
from typing import Any, Callable
import uuid

from services.render_models import ProjectStatus, RenderStatus
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_service,
    get_voice_project_store,
)
from services.voice_project_models import (
    InvalidProjectStateError,
    compute_file_sha256,
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


def _is_step_completed(state: VoiceWorkflowState, step_name: str) -> bool:
    """Check if a specific workflow step has completed."""
    for s in state.steps:
        if s.name == step_name and s.status == "completed":
            return True
    return False


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
        """Cancel an in-flight workflow: transition to CANCELLING, cancel active op, wait for terminal, then mark CANCELLED."""
        state = self.store.get_workflow(workflow_id)
        if not state:
            return False, f"Workflow '{workflow_id}' not found."

        if state.status in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED, WorkflowStatus.FAILED):
            return False, f"Workflow '{workflow_id}' is already in terminal state '{state.status.value}'."

        if state.status == WorkflowStatus.CANCELLING:
            return True, f"Workflow '{workflow_id}' is already cancelling."

        state.status = WorkflowStatus.CANCELLING
        state.updated_at = datetime.now(timezone.utc).isoformat()
        state.error = {"code": "WORKFLOW_CANCELLED", "message": "Workflow cancellation requested by user."}
        self.store.save_workflow(state)

        # Signal cancellation to active child operation if running
        active_job = self.op_manager._project_active_op.get(state.project_id)
        if active_job:
            self.op_manager.cancel_operation(active_job)

        # If workflow was in WAITING_FOR_HUMAN (no active background op running), mark CANCELLED immediately
        if not active_job:
            state.status = WorkflowStatus.CANCELLED
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_workflow(state)
            self._emit_production_event(
                state, "workflow_cancelled", "Workflow cancelled.", status=state.status.value
            )

        return True, f"Workflow '{workflow_id}' cancelling."

    def resume_workflow(self, workflow_id: str) -> VoiceWorkflowState:
        """Resume workflow execution after a human gate (e.g. pronunciation provided, final approval) has been resolved."""
        def resume(state: VoiceWorkflowState) -> None:
            action_type = state.human_action.get("action_type") if state.human_action else None
            if action_type in ("final_audio_approval", "narration_acceptance"):
                raise InvalidProjectStateError(
                    f"Workflow '{workflow_id}' requires an explicit approval decision before resume."
                )
            resume_action = state.human_action.get("resume_action") if state.human_action else None
            state.status = WorkflowStatus.RUNNING
            state.human_action = None
            state.suggested_action = f"Resuming workflow execution from {resume_action or 'next step'}..."
            state.updated_at = datetime.now(timezone.utc).isoformat()

        state = self.store.transition_workflow(workflow_id, WorkflowStatus.WAITING_FOR_HUMAN, resume)

        # Launch background resume loop
        threading.Thread(
            target=self._execute_workflow_loop,
            args=(state.workflow_id, None, None, None),
            daemon=True,
            name=f"WorkflowResume-{workflow_id}",
        ).start()

        return state

    def approve_workflow(
        self,
        workflow_id: str,
        action: str,
        approved: bool,
        artifact_id: str | None = None,
        artifact_sha256: str | None = None,
    ) -> VoiceWorkflowState:
        """Persist an explicit approval decision and resume the workflow."""
        def approve(state: VoiceWorkflowState) -> None:
            if not state.human_action:
                raise InvalidProjectStateError(f"Workflow '{workflow_id}' is not waiting for approval.")
            action_type = state.human_action.get("action_type")
            expected_action = {
                "final_audio_approval": "approve_final_audio",
                "narration_acceptance": "approve_narration",
            }.get(action_type)
            if not expected_action or action != expected_action:
                raise InvalidProjectStateError(
                    f"Approval action '{action}' does not match pending gate '{action_type}'."
                )
            if not approved:
                state.suggested_action = "Approval was declined; rerender or cancel the workflow."
                return

            if action_type == "final_audio_approval":
                item = (state.human_action.get("items") or [{}])[0]
                expected_sha = item.get("sha256")
                master_path = self.project_store.get_project_dir(state.project_id) / "mix" / "master.wav"
                current_sha = compute_file_sha256(master_path)
                if artifact_id != "master_wav" or not artifact_sha256:
                    raise InvalidProjectStateError(
                        "Final audio approval requires artifact_id='master_wav' and artifact_sha256."
                    )
                if artifact_sha256 != expected_sha or current_sha != expected_sha:
                    raise InvalidProjectStateError("Master audio changed after review; review the current artifact again.")

            step_name = WorkflowStepName.MASTER.value if action_type == "final_audio_approval" else WorkflowStepName.RENDER.value
            for step in state.steps:
                if step.name == step_name:
                    step.result_summary["approved"] = True
                    break
            state.status = WorkflowStatus.RUNNING
            state.human_action = None
            state.suggested_action = "Approval recorded; resuming workflow execution."
            state.updated_at = datetime.now(timezone.utc).isoformat()

        state = self.store.transition_workflow(workflow_id, WorkflowStatus.WAITING_FOR_HUMAN, approve)
        if not approved:
            return state
        threading.Thread(
            target=self._execute_workflow_loop,
            args=(workflow_id, None, None, None),
            daemon=True,
            name=f"WorkflowApproval-{workflow_id}",
        ).start()
        return state

    def request_revision_approval(
        self, workflow_id: str, artifact_sha256: str, revision_ids: list[str]
    ) -> VoiceWorkflowState:
        """Reopen a completed workflow at its existing final-audio approval gate."""
        if not artifact_sha256:
            raise InvalidProjectStateError("Rebuilt master audio is missing before final approval.")

        def reopen(state: VoiceWorkflowState) -> None:
            if not state.policy.require_final_approval:
                raise InvalidProjectStateError("Workflow policy does not require final approval.")
            for step in state.steps:
                if step.name == WorkflowStepName.MASTER.value:
                    step.status = "completed"
                    step.result_summary.pop("approved", None)
                    step.result_summary["revision_ids"] = revision_ids
                elif step.name in (WorkflowStepName.EXPORT.value, WorkflowStepName.COMPLETE.value):
                    step.status = "pending"
                    step.completed_at = None
                    step.result_summary = {}
            state.status = WorkflowStatus.WAITING_FOR_HUMAN
            state.current_step = WorkflowStepName.MASTER.value
            state.human_action = {
                "action_type": "final_audio_approval",
                "reason": "Rebuilt master audio requires renewed final approval before export.",
                "items": [{
                    "artifact_id": "master_wav",
                    "sha256": artifact_sha256,
                    "download_url": f"/api/v1/voice-projects/{state.project_id}/artifacts/master_wav",
                }],
                "revision_ids": revision_ids,
                "available_options": ["approve", "rerender", "cancel_workflow"],
                "resume_action": "export",
            }
            state.result = None
            state.suggested_action = "Listen to and explicitly approve the rebuilt master audio."
            state.updated_at = datetime.now(timezone.utc).isoformat()

        return self.store.reopen_for_revision_approval(workflow_id, reopen)

    def _mark_step(
        self,
        workflow_id: str,
        step_name: str,
        status: str,
        result_summary: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        """Update individual step record within fresh workflow state."""
        fresh_state = self.store.get_workflow(workflow_id)
        if not fresh_state:
            return
        if fresh_state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
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
        event_type = {
            "running": "step_started",
            "completed": "step_completed",
            "failed": "step_failed",
        }.get(status)
        if event_type:
            self._emit_production_event(
                fresh_state,
                event_type,
                f"Workflow step '{step_name}' {status}.",
                step=step_name,
                status=status,
                error=error,
            )

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
        if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
            return None

        self._mark_step(workflow_id, step_name, "running")
        op = self.op_manager.submit(state.project_id, op_name, fn, *args, **kwargs)

        fresh_state = self.store.get_workflow(workflow_id)
        if not fresh_state or fresh_state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
            self.op_manager.cancel_operation(op.id)
            self._wait_for_op_terminal_and_cancel_wf(workflow_id, op.id)
            return None

        for s in fresh_state.steps:
            if s.name == step_name:
                s.operation_id = op.id
        self.store.save_workflow(fresh_state)

        while True:
            fresh_state = self.store.get_workflow(workflow_id)
            if not fresh_state or fresh_state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                self.op_manager.cancel_operation(op.id)
                self._wait_for_op_terminal_and_cancel_wf(workflow_id, op.id)
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
                self._mark_step(workflow_id, step_name, "completed", result_summary={"operation_id": op.id})
                return curr_op.result
            elif curr_op.status in (OperationStatus.FAILED, OperationStatus.INTERRUPTED):
                err = curr_op.error or {"code": "OPERATION_FAILED", "message": "Operation failed"}
                self._mark_step(workflow_id, step_name, "failed", error=err)
                raise RuntimeError(f"Workflow step '{step_name}' failed: {err.get('message')}")
            elif curr_op.status == OperationStatus.CANCELLED:
                self._mark_step(workflow_id, step_name, "failed", error={"code": "CANCELLED", "message": "Operation cancelled"})
                self._wait_for_op_terminal_and_cancel_wf(workflow_id, op.id)
                return None

            time.sleep(0.03)

    def _wait_for_op_terminal_and_cancel_wf(self, workflow_id: str, op_id: str, max_wait_s: float = 10.0) -> None:
        """Wait for active operation to reach terminal state before transitioning workflow to CANCELLED."""
        start_t = time.time()
        while time.time() - start_t < max_wait_s:
            curr_op = self.op_manager.get_operation(op_id)
            if not curr_op or curr_op.status in (
                OperationStatus.CANCELLED,
                OperationStatus.FAILED,
                OperationStatus.COMPLETED,
                OperationStatus.INTERRUPTED,
            ):
                break
            time.sleep(0.05)

        fresh_state = self.store.get_workflow(workflow_id)
        if fresh_state and fresh_state.status != WorkflowStatus.CANCELLED:
            fresh_state.status = WorkflowStatus.CANCELLED
            fresh_state.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_workflow(fresh_state)
            self._emit_production_event(
                fresh_state, "workflow_cancelled", "Workflow cancelled.", status=fresh_state.status.value
            )

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
            service = get_voice_project_service(
                provider_name=state.policy.provider,
                model=state.policy.model,
                voice=state.policy.narrator_reference_voice,
            )
            project_id = state.project_id

            # 1. Step: CREATE_PROJECT
            if script_text and not _is_step_completed(state, WorkflowStepName.CREATE_PROJECT.value):
                if not self.project_store.project_exists(project_id):
                    service.create_project(
                        script_text=script_text,
                        project_id=project_id,
                        title=title,
                        language=language or "en",
                    )
                self._emit_production_event(
                    state, "workflow_started", "Voice production workflow started.", status=state.status.value
                )
                self._mark_step(workflow_id, WorkflowStepName.CREATE_PROJECT.value, "running")
                self._mark_step(workflow_id, WorkflowStepName.CREATE_PROJECT.value, "completed", {"project_id": project_id})

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                return

            # 2. Step: PLAN (via OperationManager)
            if not _is_step_completed(state, WorkflowStepName.PLAN.value):
                p_state = self.project_store.get_project_state(project_id)
                if p_state.stage == ProjectStatus.NEW or not self.project_store.load_voice_plan(project_id):
                    plan_res = self._run_workflow_op(
                        workflow_id,
                        WorkflowStepName.PLAN.value,
                        "plan",
                        service.plan,
                        project_id,
                        config={
                            "voice": {
                                "profile": state.policy.narrator_character or "mythology_narrator_male",
                                "provider": state.policy.provider,
                                "model": state.policy.model or "auto",
                            },
                            "global_direction": {
                                "tone": state.policy.voice_style or "mysterious",
                            },
                        },
                    )
                    if plan_res is None:
                        return

                if state.policy.pronunciation_overrides:
                    source_text = self.project_store.read_source_script(project_id).casefold()
                    current_plan = self.project_store.load_voice_plan(project_id)
                    from services.director_resource_service import DirectorResourceService
                    resources = DirectorResourceService(service)
                    for term, phonetic in state.policy.pronunciation_overrides.items():
                        affected = [
                            beat for beat in current_plan.beats
                            if term.casefold() in beat.script.text.casefold()
                        ] if current_plan else []
                        if term.casefold() in source_text and any(
                            beat.voice.pronunciation.get(term) != phonetic for beat in affected
                        ):
                            resources.add_pronunciation(
                                project_id, term, phonetic, actor_id="series_bible"
                            )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                return

            # 3. Step: CHECK_RESOURCES (via OperationManager)
            if not _is_step_completed(state, WorkflowStepName.CHECK_RESOURCES.value):
                res_report = self._run_workflow_op(
                    workflow_id,
                    WorkflowStepName.CHECK_RESOURCES.value,
                    "check_resources",
                    service.check_resources,
                    project_id,
                    allow_substitutions=state.policy.allow_resource_substitute,
                    ambience_palette=state.policy.ambience_palette,
                    sfx_palette=state.policy.sfx_palette,
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
                    state = self.store.get_workflow(workflow_id) or state
                    state.status = WorkflowStatus.WAITING_FOR_HUMAN
                    state.human_action = {
                        "action_type": "resource_required",
                        "reason": "Required audio assets or proper noun pronunciations are unverified",
                        "items": missing_terms,
                        "available_options": ["add_pronunciation", "cancel_workflow"],
                        "resume_action": "check_resources",
                    }
                    state.suggested_action = f"Add pronunciations or resources for: {', '.join(missing_terms[:3])}"
                    for step in state.steps:
                        if step.name == WorkflowStepName.CHECK_RESOURCES.value:
                            step.status = "failed"
                            step.completed_at = datetime.now(timezone.utc).isoformat()
                            step.error = {"code": "RESOURCE_BLOCKED", "message": "Required resources missing"}
                            break
                    self.store.save_workflow(state)
                    self._emit_production_event(
                        state, "human_action_required", "Required resources need human action.",
                        step=WorkflowStepName.CHECK_RESOURCES.value,
                    )
                    return  # Pause workflow until user/agent resumes

                self._mark_step(
                    workflow_id,
                    WorkflowStepName.CHECK_RESOURCES.value,
                    "completed",
                    {"readiness_score": readiness_score, "gaps_count": len(required_missing) + len(recommended_missing)},
                )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                return

            # 4. Step: RENDER (via OperationManager)
            if not _is_step_completed(state, WorkflowStepName.RENDER.value):
                render_res = self._run_workflow_op(
                    workflow_id,
                    WorkflowStepName.RENDER.value,
                    "render",
                    service.render,
                    project_id,
                    auto_qc=True,
                    max_retries=state.policy.retry_budget,
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
                    state = self.store.get_workflow(workflow_id) or state
                    state.status = WorkflowStatus.WAITING_FOR_HUMAN
                    state.human_action = {
                        "action_type": "audio_quality_review",
                        "reason": "One or more rendered beats did not achieve passing QC score",
                        "items": review_ids,
                        "available_options": ["accept_beat", "rerender_beat", "cancel_workflow"],
                        "resume_action": "evaluate",
                    }
                    state.suggested_action = f"Review quality for beats: {', '.join(review_ids)}"
                    for step in state.steps:
                        if step.name == WorkflowStepName.RENDER.value:
                            step.status = "failed"
                            step.completed_at = datetime.now(timezone.utc).isoformat()
                            step.error = {"code": "REVIEW_REQUIRED"}
                            break
                    self.store.save_workflow(state)
                    self._emit_production_event(
                        state, "human_action_required", "Narration requires human acceptance.",
                        step=WorkflowStepName.RENDER.value,
                    )
                    return

                if stage_str not in (ProjectStatus.NARRATION_READY.value, ProjectStatus.COMPLETED.value):
                    raise RuntimeError(f"Rendering did not achieve NARRATION_READY; ended in '{stage_str}'.")

                if not state.policy.auto_accept_qc_pass:
                    manifest = self.project_store.load_manifest(project_id)
                    passed_beats = [bid for bid, beat in manifest.beats.items() if beat.status == RenderStatus.PASSED]
                    state = self.store.get_workflow(workflow_id) or state
                    state.status = WorkflowStatus.WAITING_FOR_HUMAN
                    state.human_action = {
                        "action_type": "narration_acceptance",
                        "reason": "Narration passed QC and requires explicit acceptance before mixing.",
                        "items": passed_beats,
                        "available_options": ["approve", "rerender", "cancel_workflow"],
                        "resume_action": "prepare_mix",
                    }
                    state.suggested_action = "Review and approve the QC-passed narration beats."
                    self.store.save_workflow(state)
                    return

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                return

            # 5. Step: PREPARE_MIX (via OperationManager)
            if not _is_step_completed(state, WorkflowStepName.PREPARE_MIX.value):
                self._run_workflow_op(
                    workflow_id,
                    WorkflowStepName.PREPARE_MIX.value,
                    "prepare_mix",
                    service.prepare_for_mix,
                    project_id,
                    mastering_profile=state.policy.mastering_profile,
                    output_formats=state.policy.output_formats,
                    mix_config={
                        "profile": state.policy.mixing_profile,
                        "ambience_palette": state.policy.ambience_palette,
                        "sfx_palette": state.policy.sfx_palette,
                    },
                    target_lufs=state.policy.loudness_target_lufs,
                )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                return

            # 6. Step: MIX (via OperationManager)
            if not _is_step_completed(state, WorkflowStepName.MIX.value):
                self._run_workflow_op(
                    workflow_id,
                    WorkflowStepName.MIX.value,
                    "mix",
                    service.mix,
                    project_id,
                )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                return

            # 7. Step: MASTER (via OperationManager)
            if not _is_step_completed(state, WorkflowStepName.MASTER.value):
                self._run_workflow_op(
                    workflow_id,
                    WorkflowStepName.MASTER.value,
                    "master",
                    service.master,
                    project_id,
                    profile_name=state.policy.mastering_profile,
                    target_lufs=state.policy.loudness_target_lufs,
                )

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                return

            # Human Gate: Final Director Approval (if policy enabled and not yet approved)
            master_step = next((s for s in state.steps if s.name == WorkflowStepName.MASTER.value), None)
            is_approved = master_step and master_step.result_summary.get("approved")

            if state.policy.require_final_approval and not is_approved:
                master_path = self.project_store.get_project_dir(project_id) / "mix" / "master.wav"
                master_sha256 = compute_file_sha256(master_path)
                if not master_sha256:
                    raise RuntimeError("Master audio is missing before final approval.")
                state.status = WorkflowStatus.WAITING_FOR_HUMAN
                state.human_action = {
                    "action_type": "final_audio_approval",
                    "reason": "Master audio rendered and awaiting final director approval before export.",
                    "items": [{
                        "artifact_id": "master_wav",
                        "sha256": master_sha256,
                        "download_url": f"/api/v1/voice-projects/{project_id}/artifacts/master_wav",
                    }],
                    "available_options": ["approve", "rerender", "cancel_workflow"],
                    "resume_action": "export",
                }
                state.suggested_action = "Listen to and explicitly approve the master audio."
                self.store.save_workflow(state)
                self._emit_production_event(
                    state, "approval_required", "Master audio requires final approval.",
                    step=WorkflowStepName.MASTER.value,
                )
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

            master_step = next((s for s in state.steps if s.name == WorkflowStepName.MASTER.value), None)
            revision_ids = (master_step.result_summary.get("revision_ids", []) if master_step else [])
            if revision_ids:
                from services.director_revision_store import DirectorRevisionStore
                DirectorRevisionStore(self.project_store).mark_reproduced(project_id, revision_ids)

            state = self.store.get_workflow(workflow_id)
            if not state or state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
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
            self._emit_production_event(
                state, "export_completed", "Production export completed.",
                step=WorkflowStepName.EXPORT.value, status=state.status.value,
            )

        except Exception as exc:
            fresh_state = self.store.get_workflow(workflow_id)
            if fresh_state and fresh_state.status in (WorkflowStatus.CANCELLING, WorkflowStatus.CANCELLED):
                logger.info("Workflow '%s' was cancelled, skipping failure marking.", workflow_id)
                return
            logger.exception("Workflow '%s' execution failed: %s", workflow_id, exc)
            state = fresh_state or state
            state.status = WorkflowStatus.FAILED
            state.error = {"code": type(exc).__name__, "message": str(exc)}
            state.suggested_action = f"Workflow failed: {str(exc)}"
            state.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save_workflow(state)

            self._emit_production_event(
                state, "step_failed", "Production workflow failed.",
                step=state.current_step, status=state.status.value, error=state.error,
            )

    def _emit_production_event(
        self, state: VoiceWorkflowState, event_type: str, message: str, **details: Any
    ) -> None:
        try:
            from services.production_event_models import ProductionEvent, ProductionEventType
            from services.production_event_store import get_production_event_store
            get_production_event_store().append_project_event(ProductionEvent(
                project_id=state.project_id,
                workflow_id=state.workflow_id,
                event_type=ProductionEventType(event_type),
                step=details.pop("step", None),
                status=details.pop("status", None),
                message=message,
                details=details,
            ))
        except Exception as exc:
            logger.warning("Could not persist workflow event '%s': %s", event_type, exc)
