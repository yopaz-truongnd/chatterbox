"""Beat-level director decisions and minimum-safe incremental reproduction."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Any

from services.director_review_models import (
    BeatDirectionPatch,
    BeatResourcePatch,
    BeatReviewResult,
    BeatTimingPatch,
    DirectorRevisionEvent,
    IncrementalReproductionResult,
    RevisionImpact,
)
from services.director_revision_store import DirectorRevisionStore
from services.render_models import ProjectStatus, RenderStatus
from services.voice_plan import AmbienceIntent, SFXIntent
from services.voice_project_models import BeatNotFoundError, InvalidProjectStateError
from services.voice_project_service import VoiceProjectService, compute_file_sha256


MIX_ARTIFACTS = ["mix_plan", "premaster_wav", "master_wav", "exports", "final_approval"]
MIX_STEPS = ["prepare_mix", "mix", "master", "export"]


class DirectorRevisionService:
    def __init__(self, project_service: VoiceProjectService, revision_store: DirectorRevisionStore | None = None):
        self.project_service = project_service
        self.store = project_service.store
        self.revisions = revision_store or DirectorRevisionStore(self.store)

    def _beat(self, project_id: str, beat_id: str):
        self.store.get_project_state(project_id)
        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan.")
        beat = next((item for item in plan.beats if item.id == beat_id), None)
        if not beat:
            raise BeatNotFoundError(f"Beat '{beat_id}' does not exist in project '{project_id}'.")
        return plan, beat

    def _event(
        self, project_id: str, revision_type: str, beat_id: str | None, before: dict, after: dict,
        artifacts: list[str], steps: list[str], actor_id: str, reason: str | None,
        affected_beats: list[str] | None = None,
    ) -> DirectorRevisionEvent:
        event = DirectorRevisionEvent(
            revision_id=f"rev_{uuid.uuid4().hex[:12]}", project_id=project_id, beat_id=beat_id,
            affected_beats=affected_beats or ([beat_id] if beat_id else []),
            revision_type=revision_type, actor_id=actor_id, reason=reason, before=before, after=after,
            affected_artifacts=artifacts, required_reproduction_steps=steps,
            approval_required="final_approval" in artifacts,
        )
        self.revisions.append(event)
        return event

    def select_attempt(
        self, project_id: str, beat_id: str, attempt_id: int, actor_id: str = "unknown", reason: str | None = None,
        explicit_approval: bool = False,
    ) -> BeatReviewResult:
        self._beat(project_id, beat_id)
        manifest = self.store.load_manifest(project_id)
        beat_state = manifest.beats.get(beat_id)
        if not beat_state:
            raise InvalidProjectStateError(f"Beat '{beat_id}' has no rendered candidates.")
        attempt = next((item for item in beat_state.attempts if item.attempt == attempt_id), None)
        if not attempt:
            raise InvalidProjectStateError(f"Attempt '{attempt_id}' does not exist for beat '{beat_id}'.")
        approved = (attempt.direction_summary or {}).get("director_review", {}).get("action") == "approved"
        rejected = (attempt.direction_summary or {}).get("director_review", {}).get("action") == "rejected"
        if rejected:
            raise InvalidProjectStateError("Rejected candidates cannot be selected unless explicitly approved again.")
        if attempt.status == RenderStatus.NEEDS_REVIEW and not (explicit_approval or approved):
            raise InvalidProjectStateError("NEEDS_REVIEW candidates require explicit human approval.")
        if attempt.status not in (RenderStatus.PASSED, RenderStatus.NEEDS_REVIEW) or attempt.status == RenderStatus.FAILED:
            raise InvalidProjectStateError("Only passing or explicitly approved NEEDS_REVIEW candidates may be selected.")
        before = {"selected_attempt": beat_state.selected_attempt}
        if explicit_approval:
            attempt.direction_summary.setdefault("director_review", {}).update({
                "action": "approved", "actor_id": actor_id,
                "timestamp": datetime.now(timezone.utc).isoformat(), "reason": reason,
            })
            attempt.status = RenderStatus.PASSED
        beat_state.selected_attempt = attempt_id
        beat_state.status = RenderStatus.PASSED
        self.store.save_manifest(project_id, manifest)
        state = self.store.get_project_state(project_id)
        state.stage = ProjectStatus.NARRATION_READY
        state.last_stable_stage = state.stage
        self.store.save_project_state(state)
        self._event(project_id, "attempt_selected", beat_id, before, {"selected_attempt": attempt_id}, MIX_ARTIFACTS, MIX_STEPS, actor_id, reason)
        return BeatReviewResult(
            project_id=project_id, beat_id=beat_id, action="selected", selected_attempt=attempt_id,
            affected_artifacts=MIX_ARTIFACTS, required_reproduction_steps=MIX_STEPS,
            suggested_action="Reproduce mix and downstream artifacts.",
        )

    def approve_attempt(self, project_id: str, beat_id: str, attempt_id: int, actor_id: str, reason: str | None = None):
        return self.select_attempt(project_id, beat_id, attempt_id, actor_id, reason, explicit_approval=True)

    def reject_attempt(self, project_id: str, beat_id: str, attempt_id: int, actor_id: str, reason: str | None = None):
        self._beat(project_id, beat_id)
        manifest = self.store.load_manifest(project_id)
        beat_state = manifest.beats.get(beat_id)
        attempt = next((item for item in beat_state.attempts if item.attempt == attempt_id), None) if beat_state else None
        if not attempt:
            raise InvalidProjectStateError(f"Attempt '{attempt_id}' does not exist for beat '{beat_id}'.")
        selected = beat_state.selected_attempt == attempt_id
        attempt.direction_summary.setdefault("director_review", {}).update({
            "action": "rejected", "actor_id": actor_id,
            "timestamp": datetime.now(timezone.utc).isoformat(), "reason": reason,
        })
        if selected:
            beat_state.selected_attempt = None
            beat_state.status = RenderStatus.NEEDS_REVIEW
        self.store.save_manifest(project_id, manifest)
        artifacts, steps = (MIX_ARTIFACTS, ["render_beat", "evaluate", *MIX_STEPS]) if selected else ([], [])
        self._event(project_id, "candidate_rejected", beat_id, {"selected": selected}, {"selected": False}, artifacts, steps, actor_id, reason)
        return BeatReviewResult(
            project_id=project_id, beat_id=beat_id, action="rejected",
            affected_artifacts=artifacts, required_reproduction_steps=steps,
            suggested_action="Select another passing candidate or rerender the beat." if selected else "Candidate rejected.",
        )

    def update_direction(self, project_id: str, beat_id: str, patch: BeatDirectionPatch, actor_id: str, reason: str | None = None) -> RevisionImpact:
        plan, beat = self._beat(project_id, beat_id)
        before = beat.voice.model_dump(mode="json")
        values = patch.model_dump(exclude_none=True)
        if "voice_style" in values:
            beat.voice.director_note = values.pop("voice_style")
        for key, value in values.items():
            setattr(beat.voice, key, value)
        manifest = self.store.load_manifest(project_id)
        beat_state = manifest.beats.get(beat_id)
        if beat_state:
            beat_state.selected_attempt = None
            beat_state.status = RenderStatus.PENDING
        self.store.save_voice_plan(project_id, plan)
        self.store.save_manifest(project_id, manifest)
        steps = ["check_resources", "render_beat", "evaluate", *MIX_STEPS]
        event = self._event(project_id, "beat_direction_changed", beat_id, before, beat.voice.model_dump(mode="json"), ["selected_attempt", "beat_qc", *MIX_ARTIFACTS], steps, actor_id, reason)
        return RevisionImpact(project_id=project_id, beat_id=beat_id, revision_id=event.revision_id, invalidated_artifacts=event.affected_artifacts, required_reproduction_steps=steps, rerender_beats=[beat_id], final_approval_invalidated=True)

    def update_timing(self, project_id: str, beat_id: str, patch: BeatTimingPatch, actor_id: str, reason: str | None = None) -> RevisionImpact:
        plan, beat = self._beat(project_id, beat_id)
        before = beat.voice.pause.model_dump(mode="json")
        if patch.pause_before_ms is not None:
            beat.voice.pause.before = patch.pause_before_ms / 1000
        if patch.pause_after_ms is not None:
            beat.voice.pause.after = patch.pause_after_ms / 1000
        self.store.save_voice_plan(project_id, plan)
        self._preserve_narration(project_id)
        event = self._event(project_id, "beat_timing_changed", beat_id, before, beat.voice.pause.model_dump(mode="json"), MIX_ARTIFACTS, MIX_STEPS, actor_id, reason)
        return RevisionImpact(project_id=project_id, beat_id=beat_id, revision_id=event.revision_id, invalidated_artifacts=MIX_ARTIFACTS, required_reproduction_steps=MIX_STEPS, final_approval_invalidated=True)

    def update_resources(self, project_id: str, beat_id: str, patch: BeatResourcePatch, actor_id: str, reason: str | None = None) -> RevisionImpact:
        plan, beat = self._beat(project_id, beat_id)
        before = {"ambience": beat.ambience.model_dump(mode="json") if beat.ambience else None, "sfx": [item.model_dump(mode="json") for item in beat.sfx]}
        if patch.ambience_intent is not None:
            beat.ambience = AmbienceIntent(intent=patch.ambience_intent)
        if patch.sfx is not None:
            beat.sfx = [SFXIntent.model_validate(item) for item in patch.sfx]
        self.store.save_voice_plan(project_id, plan)
        self._preserve_narration(project_id)
        after = {"ambience": beat.ambience.model_dump(mode="json") if beat.ambience else None, "sfx": [item.model_dump(mode="json") for item in beat.sfx]}
        steps = ["check_resources", *MIX_STEPS]
        event = self._event(project_id, "beat_resources_changed", beat_id, before, after, MIX_ARTIFACTS, steps, actor_id, reason)
        return RevisionImpact(project_id=project_id, beat_id=beat_id, revision_id=event.revision_id, invalidated_artifacts=MIX_ARTIFACTS, required_reproduction_steps=steps, final_approval_invalidated=True)

    def _preserve_narration(self, project_id: str) -> None:
        resources = self.project_service.check_resources(project_id)
        manifest = self.store.load_manifest(project_id)
        self.store.save_manifest(project_id, manifest)
        if not resources.render_blocked and manifest.beats and all(item.selected_attempt is not None for item in manifest.beats.values()):
            state = self.store.get_project_state(project_id)
            state.stage = ProjectStatus.NARRATION_READY
            state.last_stable_stage = state.stage
            self.store.save_project_state(state)

    def reproduce_project(self, project_id: str, revision_ids: list[str] | None = None, policy: dict[str, Any] | None = None, cancellation_token=None, progress_callback=None) -> IncrementalReproductionResult:
        state = self.revisions.get_state(project_id)
        pending = [event for event in self.revisions.list_events(project_id) if event.status == "pending"]
        selected_ids = list(dict.fromkeys(revision_ids or [event.revision_id for event in pending]))
        selected = [event for event in pending if event.revision_id in selected_ids]
        if len(selected) != len(selected_ids):
            raise InvalidProjectStateError("One or more revision IDs do not exist or are already reproduced.")
        steps = list(dict.fromkeys(step for event in selected for step in event.required_reproduction_steps))
        affected_beats = list(dict.fromkeys(
            beat for event in selected for beat in (event.affected_beats or ([event.beat_id] if event.beat_id else []))
        ))
        final_approval_invalidated = any(event.approval_required for event in selected)

        from services.voice_project_dependencies import get_voice_project_workflow_service
        workflow_service = get_voice_project_workflow_service()
        matches = [item for item in workflow_service.store.list_workflows(limit=200) if item.project_id == project_id]
        workflow = max(matches, key=lambda item: item.created_at, default=None)
        effective = dict(policy or {})
        if workflow:
            effective.update(workflow.policy.model_dump(mode="json"))
        require_final_approval = bool((workflow and workflow.policy.require_final_approval) or effective.get("require_final_approval"))
        ordered = [step for step in ["check_resources", "render_beat", "evaluate", *MIX_STEPS] if step in steps]
        executed = []
        total = max(1, len(ordered))
        for index, step in enumerate(ordered):
            if cancellation_token and cancellation_token.is_cancelled():
                return IncrementalReproductionResult(project_id=project_id, affected_beats=affected_beats, executed_steps=executed, status="cancelled", suggested_action="Resume reproduction when ready.")
            if progress_callback:
                progress_callback(f"reproduce_{step}", index / total * 100, {"beat_id": affected_beats[0] if len(affected_beats) == 1 else None})
            if step == "check_resources":
                result = self.project_service.check_resources(project_id)
                if result.render_blocked:
                    return IncrementalReproductionResult(project_id=project_id, affected_beats=affected_beats, executed_steps=executed + [step], status="resource_blocked", suggested_action="Resolve required resources before resuming.")
            elif step == "render_beat":
                for beat_id in affected_beats:
                    self.project_service.render_beat(project_id, beat_id, cancellation_token=cancellation_token)
            elif step == "evaluate":
                self.project_service.evaluate(project_id, beats=affected_beats)
            elif step == "prepare_mix":
                self.project_service.prepare_for_mix(
                    project_id,
                    mix_config={"profile": effective.get("mixing_profile", "storytelling")},
                    mastering_profile=effective.get("mastering_profile", "storytelling"),
                    output_formats=effective.get("output_formats") or ["wav"],
                )
            elif step == "mix":
                self.project_service.mix(project_id, cancellation_token=cancellation_token)
            elif step == "master":
                self.project_service.master(project_id, profile_name=effective.get("mastering_profile", "storytelling"), cancellation_token=cancellation_token)
            elif step == "export":
                if final_approval_invalidated and require_final_approval:
                    if not workflow or not workflow_service:
                        raise InvalidProjectStateError("Final approval is required but no authoritative workflow exists.")
                    master_path = self.store.get_project_dir(project_id) / "mix" / "master.wav"
                    workflow_service.request_revision_approval(workflow.workflow_id, compute_file_sha256(master_path), selected_ids)
                    return IncrementalReproductionResult(project_id=project_id, affected_beats=affected_beats, executed_steps=executed, status="waiting_for_human", suggested_action=f"Approve master_wav on workflow {workflow.workflow_id} before export.")
                self.project_service.export(project_id, formats=effective.get("output_formats") or ["wav"], cancellation_token=cancellation_token)
            executed.append(step)
        self.revisions.mark_reproduced(project_id, selected_ids)
        return IncrementalReproductionResult(project_id=project_id, affected_beats=affected_beats, executed_steps=executed, status="completed", suggested_action="Review the latest artifacts.")
