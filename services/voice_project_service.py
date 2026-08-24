"""Unified Voice Project Application Service (Phase 11).

Single canonical application orchestration layer for VoiceProject lifecycle:
- Serves as the unified facade for CLI, REST API, and MCP Agent interfaces.
- Coordinates domain services (Story Analyzer, Narration Planner, VoicePlan,
  Sound Director, Director Critic, Resource Manager, Voice Renderer, AudioCandidateEvaluator).
- Enforces lifecycle state machine transitions and staleness detection.
- Provides agent-friendly project summaries and explicit human action requests.
- Contains zero framework dependencies (no FastAPI, HTTPException, MCP, or argparse).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from services.director_critic import apply_director_fixes, critique_voice_plan
from services.narration_planner import compile_narration_plan
from services.pronunciation_knowledge import load_pronunciation_knowledge
from services.render_models import (
    ProjectState,
    ProjectStatus,
    RenderManifest,
    RenderStatus,
)
from services.resource_manager import (
    load_manifest,
    load_selection_rules,
    load_substitution_rules,
    resolve_project_resources,
)
from services.sound_director import direct_sound
from services.story_analyzer import (
    analyze_story_beats,
    story_beats_to_narration_segments,
)
from services.tts.base import TTSExecutionPort
from services.tts.provider_factory import create_tts_provider
from services.voice_plan import VoicePlan, build_voice_plan
from services.voice_project_models import (
    BeatNotFoundError,
    HumanActionRequired,
    HumanActionType,
    InvalidProjectStateError,
    ResourceCheckResult,
    StaleArtifactError,
    VoicePlanningResult,
    VoiceProjectNotFound,
    VoiceProjectSummary,
    VoiceRenderResult,
)
from services.voice_project_store import VoiceProjectStore
from services.voice_renderer import (
    ProviderUnavailableError,
    ResourceBlockedError,
    evaluate_beat_qc,
    render_project_narration,
    select_best_candidate,
)

logger = logging.getLogger(__name__)


class VoiceProjectService:
    """Canonical application service orchestrating the full VoiceProject lifecycle."""

    def __init__(
        self,
        store: VoiceProjectStore | None = None,
        execution_port: TTSExecutionPort | None = None,
        provider_name: str = "chatterbox-http",
    ):
        self.store = store or VoiceProjectStore()
        self.execution_port = execution_port
        self.provider_name = provider_name

    # ==========================================
    # Project Creation & Overview
    # ==========================================

    def create_project(
        self,
        script_text: str,
        project_id: str | None = None,
        title: str | None = None,
        language: str = "en",
        config: dict[str, Any] | None = None,
    ) -> ProjectState:
        """Create a new VoiceProject workspace with immutable source script."""
        if not project_id:
            import uuid
            project_id = f"voice_proj_{uuid.uuid4().hex[:8]}"

        self.store.validate_project_id(project_id)
        return self.store.create_workspace(
            project_id=project_id,
            script_text=script_text,
            title=title,
            language=language,
            config=config,
        )

    def get_project(self, project_id: str) -> VoiceProjectSummary:
        """Retrieve concise, structured, agent-friendly project overview."""
        state = self.store.get_project_state(project_id)
        proj_dir = self.store.get_project_dir(project_id)

        plan = self.store.load_voice_plan(project_id)
        report = self.store.load_resource_report(project_id)
        manifest = self.store.load_manifest(project_id)

        total_beats = len(plan.beats) if plan else len(manifest.beats)
        passed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.PASSED)
        review_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.NEEDS_REVIEW)
        failed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.FAILED)

        readiness_score = float(report.readiness.score) if report else 0.0
        resource_blocked = report.readiness.render_blocked if report else False

        # Determine suggested action & explicit human action
        suggested_action = "Run plan() to analyze script and build voice direction"
        human_action: HumanActionRequired | None = None

        if state.stage == ProjectStatus.NEW:
            suggested_action = "Run plan() to generate VoicePlan and sound direction"
        elif state.stage == ProjectStatus.PLANNED:
            suggested_action = "Run check_resources() to evaluate asset availability and pronunciation"
        elif state.stage == ProjectStatus.RESOURCE_BLOCKED:
            missing_terms = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "required"] if report else []
            suggested_action = f"Ingest or verify required missing resources: {', '.join(missing_terms[:3])}"
            human_action = HumanActionRequired(
                action_type=HumanActionType.RESOURCE_REQUIRED,
                reason="Required audio assets or proper noun pronunciations are unverified",
                items=missing_terms,
            )
        elif state.stage == ProjectStatus.READY_TO_RENDER:
            suggested_action = "Run render() to synthesize voice narration beats"
        elif state.stage == ProjectStatus.REVIEW_REQUIRED:
            review_beat_ids = [bid for bid, b in manifest.beats.items() if b.status == RenderStatus.NEEDS_REVIEW]
            suggested_action = f"Review or rerender beats needing human attention: {', '.join(review_beat_ids)}"
            human_action = HumanActionRequired(
                action_type=HumanActionType.AUDIO_QUALITY_REVIEW,
                reason="One or more rendered beats did not achieve passing QC score after retries",
                items=review_beat_ids,
            )
        elif state.stage == ProjectStatus.NARRATION_READY:
            suggested_action = "Narration audio passed all QC gates and is ready for sound mixing (Phase 14)"
        elif state.stage == ProjectStatus.MIX_READY:
            suggested_action = "Project mix is fully prepared"
        elif state.stage == ProjectStatus.FAILED:
            suggested_action = f"Project failed: {state.error or 'Check error logs and retry'}"

        return VoiceProjectSummary(
            project_id=project_id,
            title=state.title or project_id,
            stage=state.stage,
            total_beats=total_beats,
            passed_beats=passed_beats,
            review_beats=review_beats,
            failed_beats=failed_beats,
            resource_readiness_score=readiness_score,
            resource_blocked=resource_blocked,
            provider=self.provider_name,
            suggested_action=suggested_action,
            human_action=human_action,
        )

    def update_script(self, project_id: str, new_script_text: str) -> ProjectState:
        """Explicitly update source script and invalidate downstream planning artifacts."""
        state = self.store.get_project_state(project_id)
        if state.stage in (ProjectStatus.PLANNING, ProjectStatus.RESOURCE_CHECKING, ProjectStatus.RENDERING):
            raise InvalidProjectStateError(
                f"Cannot update script while project '{project_id}' is in active state '{state.stage}'."
            )
        return self.store.update_source_script(project_id, new_script_text)

    # ==========================================
    # Planning Operation
    # ==========================================

    def plan(
        self,
        project_id: str,
        config: dict[str, Any] | None = None,
        skip_director_critic: bool = False,
    ) -> VoicePlanningResult:
        """Run single high-level planning operation from Source Script to Directed VoicePlan."""
        state = self.store.get_project_state(project_id)

        # 1. State check
        allowed_from = (ProjectStatus.NEW, ProjectStatus.PLANNED, ProjectStatus.FAILED, ProjectStatus.RESOURCE_BLOCKED)
        if state.stage not in allowed_from:
            logger.info("Re-planning project '%s' currently in state '%s'", project_id, state.stage)

        with self.store.get_project_lock(project_id):
            state.stage = ProjectStatus.PLANNING
            self.store.save_project_state(state)

            try:
                raw_script = self.store.read_source_script(project_id)
                proj_dir = self.store.get_project_dir(project_id)

                # Domain Steps: Story Analysis -> Narration Plan -> VoicePlan -> Sound Director -> Critic
                story_beats = analyze_story_beats(raw_script)
                segments = story_beats_to_narration_segments(story_beats)
                planned_segments = compile_narration_plan(segments)

                proj_cfg = config or {}
                voice_cfg = proj_cfg.get("voice", {})
                global_dir_cfg = proj_cfg.get("global_direction", {})

                project_data = {
                    "project": {"id": project_id, "title": state.title or project_id, "source_script": raw_script},
                    "voice": {
                        "profile": voice_cfg.get("profile", "mythology_narrator_male"),
                        "provider": voice_cfg.get("provider", self.provider_name or "chatterbox-http"),
                        "model": voice_cfg.get("model", "auto"),
                    },
                    "global_direction": {
                        "tone": global_dir_cfg.get("tone", "mysterious"),
                        "base_pace": float(global_dir_cfg.get("base_pace", 0.92)),
                        "dramatic_level": int(global_dir_cfg.get("dramatic_level", 3)),
                        "max_energy": float(global_dir_cfg.get("max_energy", 5.0)),
                        "avoid_overacting": bool(global_dir_cfg.get("avoid_overacting", True)),
                    },
                }

                voice_plan = build_voice_plan(project_data, planned_segments)
                directed_plan = direct_sound(voice_plan)

                critique = None
                warnings: list[str] = []
                if not skip_director_critic:
                    critique = critique_voice_plan(directed_plan)
                    final_plan = apply_director_fixes(directed_plan, critique)
                    warnings.extend(critique.warnings if hasattr(critique, "warnings") else [])
                else:
                    final_plan = directed_plan

                # Save plan and critique artifacts
                self.store.save_voice_plan(project_id, final_plan, critique)

                return VoicePlanningResult(
                    project_id=project_id,
                    stage=ProjectStatus.PLANNED,
                    beat_count=len(final_plan.beats),
                    voice_plan_path=str(proj_dir / "voice-plan.yaml"),
                    critique_path=str(proj_dir / "director-critique.yaml") if critique else "",
                    warnings=warnings,
                    voice_plan=final_plan,
                )
            except Exception as exc:
                state.stage = ProjectStatus.FAILED
                state.error = f"Planning failed: {exc}"
                self.store.save_project_state(state)
                raise

    # ==========================================
    # Resource Checking Operation
    # ==========================================

    def check_resources(
        self,
        project_id: str,
        manifest_path: Path | str | None = None,
    ) -> ResourceCheckResult:
        """Resolve requirements from Directed VoicePlan against Asset Library & Pronunciation Knowledge."""
        state = self.store.get_project_state(project_id)

        # 1. Staleness Check
        is_stale, reason = self.store.check_staleness(project_id, for_render=False)
        if is_stale:
            raise StaleArtifactError(f"Cannot check resources for '{project_id}': {reason}")

        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan() first.")

        with self.store.get_project_lock(project_id):
            state.stage = ProjectStatus.RESOURCE_CHECKING
            self.store.save_project_state(state)

            try:
                proj_dir = self.store.get_project_dir(project_id)
                resource_manifest = load_manifest(manifest_path)
                pron_knowledge = load_pronunciation_knowledge()
                sub_rules = load_substitution_rules()
                sel_rules = load_selection_rules()

                report = resolve_project_resources(
                    plan=plan,
                    manifest=resource_manifest,
                    knowledge=pron_knowledge,
                    substitution_rules=sub_rules,
                    selection_rules=sel_rules,
                )

                self.store.save_resource_report(project_id, report)

                required_missing = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "required"]
                recommended_missing = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "recommended"]
                optional_missing = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "optional"]

                human_action = None
                if report.readiness.render_blocked:
                    human_action = HumanActionRequired(
                        action_type=HumanActionType.RESOURCE_REQUIRED,
                        reason="Required audio assets or proper noun pronunciations must be resolved",
                        items=required_missing,
                    )

                return ResourceCheckResult(
                    project_id=project_id,
                    stage=ProjectStatus.RESOURCE_BLOCKED if report.readiness.render_blocked else ProjectStatus.READY_TO_RENDER,
                    readiness_score=float(report.readiness.score),
                    render_blocked=report.readiness.render_blocked,
                    required_missing=required_missing,
                    recommended_missing=recommended_missing,
                    optional_missing=optional_missing,
                    pronunciation_overrides=report.pronunciation_overrides,
                    report_path=str(proj_dir / "resource-report.yaml"),
                    human_action=human_action,
                    report=report,
                )
            except Exception as exc:
                state.stage = ProjectStatus.FAILED
                state.error = f"Resource check failed: {exc}"
                self.store.save_project_state(state)
                raise

    # ==========================================
    # Render & Evaluation Operations
    # ==========================================

    def render(
        self,
        project_id: str,
        beats: list[str] | None = None,
        execution_port: TTSExecutionPort | None = None,
        allow_resource_blocked: bool = False,
        force_rerender: bool = False,
        auto_qc: bool = True,
    ) -> VoiceRenderResult:
        """Render narration beats through injected TTSExecutionPort with Voice QC verification."""
        state = self.store.get_project_state(project_id)

        # 1. Staleness Check
        is_stale, reason = self.store.check_staleness(project_id, for_render=True)
        if is_stale:
            raise StaleArtifactError(f"Cannot render project '{project_id}': {reason}")

        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan() first.")

        report = self.store.load_resource_report(project_id)
        if report and report.readiness.render_blocked and not allow_resource_blocked:
            missing_terms = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "required"]
            raise ResourceBlockedError(
                f"Cannot render project '{project_id}': Resource check is BLOCKED. "
                f"Missing required resources: {', '.join(missing_terms)}"
            )

        with self.store.get_project_lock(project_id):
            state.stage = ProjectStatus.RENDERING
            self.store.save_project_state(state)

            try:
                proj_dir = self.store.get_project_dir(project_id)
                port = execution_port or self.execution_port or create_tts_provider(self.provider_name)

                # Delegate per-beat rendering and QC attempts to domain renderer
                manifest, _ = render_project_narration(
                    project_dir=proj_dir,
                    plan=plan,
                    provider=port,
                    resource_report=report,
                    beats_filter=beats,
                    auto_qc=auto_qc,
                    allow_resource_blocked=allow_resource_blocked,
                    force_rerender=force_rerender,
                )

                # Assess final project stage from manifest
                total_beats = len(plan.beats)
                passed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.PASSED)
                review_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.NEEDS_REVIEW)
                failed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.FAILED)
                rendered_beats = len([b for b in manifest.beats.values() if b.attempts])

                human_action = None
                if review_beats > 0:
                    final_stage = ProjectStatus.REVIEW_REQUIRED
                    review_ids = [bid for bid, b in manifest.beats.items() if b.status == RenderStatus.NEEDS_REVIEW]
                    human_action = HumanActionRequired(
                        action_type=HumanActionType.AUDIO_QUALITY_REVIEW,
                        reason="One or more beats require human review or manual direction adjustment",
                        items=review_ids,
                    )
                elif failed_beats > 0:
                    final_stage = ProjectStatus.FAILED
                elif passed_beats == total_beats and total_beats > 0:
                    final_stage = ProjectStatus.NARRATION_READY
                else:
                    final_stage = ProjectStatus.READY_TO_RENDER

                state.stage = final_stage
                state.last_stable_stage = final_stage
                state.error = None
                self.store.save_project_state(state)

                return VoiceRenderResult(
                    project_id=project_id,
                    stage=final_stage,
                    total_beats=total_beats,
                    rendered_beats=rendered_beats,
                    passed_beats=passed_beats,
                    review_beats=review_beats,
                    failed_beats=failed_beats,
                    manifest_path=str(proj_dir / "render-manifest.yaml"),
                    human_action=human_action,
                    manifest=manifest,
                )
            except Exception as exc:
                state.stage = ProjectStatus.FAILED
                state.error = f"Render failed: {exc}"
                self.store.save_project_state(state)
                raise

    def render_beat(
        self,
        project_id: str,
        beat_id: str,
        execution_port: TTSExecutionPort | None = None,
        allow_resource_blocked: bool = False,
    ) -> VoiceRenderResult:
        """Selectively render/rerender a single beat with strict beat existence validation."""
        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan() first.")

        matching_beat = next((b for b in plan.beats if b.id == beat_id), None)
        if not matching_beat:
            raise BeatNotFoundError(f"Beat '{beat_id}' does not exist in project '{project_id}'.")

        return self.render(
            project_id=project_id,
            beats=[beat_id],
            execution_port=execution_port,
            allow_resource_blocked=allow_resource_blocked,
            force_rerender=True,
            auto_qc=True,
        )

    def evaluate(
        self,
        project_id: str,
        beats: list[str] | None = None,
    ) -> VoiceRenderResult:
        """Rerun Voice QC on existing rendered audio attempts without re-synthesizing."""
        state = self.store.get_project_state(project_id)
        plan = self.store.load_voice_plan(project_id)
        if not plan:
            raise InvalidProjectStateError(f"Project '{project_id}' has no VoicePlan. Run plan() first.")

        report = self.store.load_resource_report(project_id)
        pron_overrides = report.pronunciation_overrides if report else {}

        with self.store.get_project_lock(project_id):
            proj_dir = self.store.get_project_dir(project_id)
            manifest = self.store.load_manifest(project_id)

            target_beats = beats or [b.id for b in plan.beats]

            for beat in plan.beats:
                if beat.id not in target_beats:
                    continue

                b_state = manifest.beats.get(beat.id)
                if not b_state or not b_state.attempts:
                    continue

                for attempt in b_state.attempts:
                    audio_path = Path(attempt.audio_path)
                    if not audio_path.is_absolute():
                        audio_path = proj_dir / audio_path

                    if audio_path.exists():
                        qc = evaluate_beat_qc(
                            beat=beat,
                            audio_path=audio_path,
                            attempt_id=attempt.attempt,
                            pronunciation_overrides=pron_overrides,
                        )
                        attempt.qc_result = qc
                        if qc.verdict.value == "pass":
                            attempt.status = RenderStatus.PASSED
                        elif qc.verdict.value == "needs_review":
                            attempt.status = RenderStatus.NEEDS_REVIEW
                        else:
                            attempt.status = RenderStatus.QC_FAILED

                # Re-select best candidate
                best_attempt = select_best_candidate(b_state.attempts)
                if best_attempt and best_attempt.qc_result and best_attempt.qc_result.verdict.value == "pass":
                    b_state.selected_attempt = best_attempt.attempt
                    b_state.status = RenderStatus.PASSED
                elif any(a.qc_result and a.qc_result.verdict.value == "needs_review" for a in b_state.attempts):
                    b_state.status = RenderStatus.NEEDS_REVIEW
                else:
                    b_state.status = RenderStatus.QC_FAILED

            self.store.save_manifest(project_id, manifest)

            total_beats = len(plan.beats)
            passed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.PASSED)
            review_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.NEEDS_REVIEW)
            failed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.FAILED)
            rendered_beats = len([b for b in manifest.beats.values() if b.attempts])

            human_action = None
            if review_beats > 0:
                final_stage = ProjectStatus.REVIEW_REQUIRED
                review_ids = [bid for bid, b in manifest.beats.items() if b.status == RenderStatus.NEEDS_REVIEW]
                human_action = HumanActionRequired(
                    action_type=HumanActionType.AUDIO_QUALITY_REVIEW,
                    reason="One or more beats require manual review after QC re-evaluation",
                    items=review_ids,
                )
            elif failed_beats > 0:
                final_stage = ProjectStatus.FAILED
            elif passed_beats == total_beats and total_beats > 0:
                final_stage = ProjectStatus.NARRATION_READY
            else:
                final_stage = ProjectStatus.READY_TO_RENDER

            state.stage = final_stage
            state.last_stable_stage = final_stage
            self.store.save_project_state(state)

            return VoiceRenderResult(
                project_id=project_id,
                stage=final_stage,
                total_beats=total_beats,
                rendered_beats=rendered_beats,
                passed_beats=passed_beats,
                review_beats=review_beats,
                failed_beats=failed_beats,
                manifest_path=str(proj_dir / "render-manifest.yaml"),
                human_action=human_action,
                manifest=manifest,
            )
