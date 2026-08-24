"""Director-facing read model assembled from canonical Phase 11-15 artifacts."""

from __future__ import annotations

from services.director_review_models import (
    DirectorArtifactStatus,
    DirectorAudioCandidate,
    DirectorBeatReview,
    DirectorProjectReview,
    DirectorResourceGap,
    DirectorResourceShoppingList,
    DirectorRevisionSummary,
)
from services.render_models import RenderStatus
from services.resource_models import RequirementPriority, ResourceGap
from services.voice_project_models import InvalidProjectStateError, compute_file_sha256
from services.voice_project_store import VoiceProjectStore
from services.director_revision_store import DirectorRevisionStore


class DirectorReviewService:
    def __init__(self, store: VoiceProjectStore, revision_store: DirectorRevisionStore | None = None):
        self.store = store
        self.revisions = revision_store or DirectorRevisionStore(store)

    @staticmethod
    def _gap(gap: ResourceGap) -> DirectorResourceGap:
        context = gap.narrative_context
        wanted = gap.wanted or {}
        duration = wanted.get("duration_max") or wanted.get("duration_min")
        return DirectorResourceGap(
            resource_id=gap.id,
            resource_type=gap.type.value,
            priority=gap.priority.value,
            description=gap.reason or gap.term or gap.intent or gap.id,
            affected_beats=gap.used_at or ([context.beat_id] if context and context.beat_id else []),
            story_context=context.text if context else None,
            desired_characteristics=wanted,
            duration_hint_ms=float(duration) * 1000 if duration else None,
            loopable=bool(wanted.get("loopable", gap.type.value == "ambience")),
            suggested_search_queries=gap.suggested_search,
            accepted_formats=[item.lower() for item in gap.accepted_formats],
            resolution_options=["bind_existing", "register_asset", "approve_substitution"]
            + (["omit"] if gap.priority != RequirementPriority.REQUIRED else []),
        )

    def get_review(self, project_id: str) -> DirectorProjectReview:
        state = self.store.get_project_state(project_id)
        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan() first.")
        report = self.store.load_resource_report(project_id)
        manifest = self.store.load_manifest(project_id)
        project_dir = self.store.get_project_dir(project_id)
        source_path = project_dir / "source" / "script.txt"
        source = source_path.read_text(encoding="utf-8")
        revision_state = self.revisions.get_state(project_id)
        events = self.revisions.list_events(project_id)

        cursor = 0
        beats: list[DirectorBeatReview] = []
        invalidated = set(revision_state.invalidated_artifacts)
        for beat in plan.beats:
            start = source.find(beat.script.text, cursor)
            if start < 0:
                raise InvalidProjectStateError(
                    f"Beat '{beat.id}' text no longer maps exactly to immutable source script. Re-plan required."
                )
            end = start + len(beat.script.text)
            cursor = end
            render = manifest.beats.get(beat.id)
            attempts = []
            if render:
                for attempt in render.attempts:
                    qc = attempt.qc_result
                    review = attempt.direction_summary.get("director_review") if attempt.direction_summary else None
                    attempts.append(DirectorAudioCandidate(
                        attempt_id=attempt.attempt,
                        status=attempt.status.value,
                        provider=attempt.provider,
                        model=attempt.model,
                        artifact_id=f"beat_{beat.id.lower()}_attempt_{attempt.attempt}",
                        duration_ms=attempt.duration * 1000,
                        qc_score=qc.qc_score if qc else None,
                        qc_verdict=qc.verdict.value if qc else None,
                        created_at=attempt.created_at,
                        selected=render.selected_attempt == attempt.attempt,
                        review=review,
                    ))
            selected = next((item for item in attempts if item.selected), None)
            resource_ids = []
            if report:
                resource_ids = [
                    item.selected.id for item in report.resolved + report.substituted
                    if item.beat_id == beat.id and item.selected
                ]
            freshness = "invalidated" if beat.id in revision_state.affected_beats else (
                "fresh" if selected else "missing"
            )
            beats.append(DirectorBeatReview(
                beat_id=beat.id,
                source_text=source[start:end],
                source_start=start,
                source_end=end,
                role=beat.role.value,
                voice_direction=beat.voice.model_dump(mode="json"),
                emotion=beat.voice.emotion,
                energy=beat.voice.energy,
                pace=beat.voice.pace,
                pause_before_ms=beat.voice.pause.before * 1000,
                pause_after_ms=beat.voice.pause.after * 1000,
                ambience_intents=[beat.ambience.intent] if beat.ambience else [],
                sfx_intents=[item.intent for item in beat.sfx],
                pronunciation_terms=list(beat.voice.pronunciation),
                resource_dependencies=resource_ids,
                render_status=render.status.value if render else RenderStatus.PENDING.value,
                selected_attempt=render.selected_attempt if render else None,
                available_attempts=attempts,
                qc_summary=selected.model_dump(mode="json") if selected else None,
                artifact_freshness=freshness,
                available_actions=["review", "rerender", "reevaluate", "update_direction", "update_timing"]
                + (["select_attempt"] if attempts else []),
            ))

        workflow_id = workflow_status = None
        try:
            from services.voice_project_dependencies import get_voice_project_workflow_service
            workflows = get_voice_project_workflow_service().store.list_workflows(limit=200)
            workflow = next((item for item in workflows if item.project_id == project_id), None)
            if workflow:
                workflow_id = workflow.workflow_id
                workflow_status = workflow.status.value
        except Exception:
            pass

        required = [self._gap(g) for g in (report.missing if report else []) if g.priority == RequirementPriority.REQUIRED]
        recommended = [self._gap(g) for g in (report.missing if report else []) if g.priority == RequirementPriority.RECOMMENDED]
        artifacts = []
        for artifact_id, relative, url in (
            ("mix_plan", "mix-plan.yaml", f"/api/v1/voice-projects/{project_id}/artifacts/mix_plan"),
            ("premaster_wav", "mix/premaster.wav", f"/api/v1/voice-projects/{project_id}/artifacts/premaster_wav"),
            ("master_wav", "mix/master.wav", f"/api/v1/voice-projects/{project_id}/artifacts/master_wav"),
            ("final_wav", "exports/FINAL.wav", f"/api/v1/voice-projects/{project_id}/artifacts/final_wav"),
        ):
            path = project_dir / relative
            artifacts.append(DirectorArtifactStatus(
                artifact_id=artifact_id,
                exists=path.exists(),
                fresh=path.exists() and artifact_id not in invalidated,
                sha256=compute_file_sha256(path) if path.exists() else None,
                download_url=url if path.exists() else None,
            ))

        return DirectorProjectReview(
            project_id=project_id,
            title=state.title,
            language=state.language,
            project_stage=state.stage.value,
            workflow_id=workflow_id,
            workflow_status=workflow_status,
            source_script_sha256=compute_file_sha256(source_path),
            script_excerpt=source[:500],
            beats=beats,
            resource_readiness=report.readiness.score if report else None,
            required_resource_gaps=required,
            recommended_resource_gaps=recommended,
            human_action={
                "action_type": "resource_required",
                "items": [item.resource_id for item in required],
            } if required else None,
            available_actions=["review_resources", "review_beats", "update_direction", "reproduce"],
            artifact_status=artifacts,
            revision_summary=DirectorRevisionSummary(
                revision_count=len(events),
                latest_revision_id=events[-1].revision_id if events else None,
                affected_beats=revision_state.affected_beats,
                invalidated_artifacts=revision_state.invalidated_artifacts,
                required_reproduction_steps=revision_state.required_reproduction_steps,
                final_approval_invalidated=revision_state.final_approval_invalidated,
            ),
        )

    def get_beat_review(self, project_id: str, beat_id: str) -> DirectorBeatReview:
        review = self.get_review(project_id)
        for beat in review.beats:
            if beat.beat_id == beat_id:
                return beat
        from services.voice_project_models import BeatNotFoundError
        raise BeatNotFoundError(f"Beat '{beat_id}' does not exist in project '{project_id}'.")

    def shopping_list(self, project_id: str) -> DirectorResourceShoppingList:
        review = self.get_review(project_id)
        queries = list(dict.fromkeys(
            query for item in review.required_resource_gaps + review.recommended_resource_gaps
            for query in item.suggested_search_queries
        ))
        return DirectorResourceShoppingList(
            project_id=project_id,
            required_items=review.required_resource_gaps,
            recommended_items=review.recommended_resource_gaps,
            ready_for_render=not review.required_resource_gaps,
            estimated_resource_count=len(review.required_resource_gaps) + len(review.recommended_resource_gaps),
            suggested_search_queries=queries,
        )
