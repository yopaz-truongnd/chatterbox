"""Unified Voice Project Application Service (Phase 11).

Single canonical application orchestration layer for VoiceProject lifecycle:
- Serves as the unified facade for CLI, REST API, and MCP Agent interfaces.
- Coordinates domain services (Story Analyzer, Narration Planner, VoicePlan,
  Sound Director, Director Critic, Resource Manager, Voice Renderer, AudioCandidateEvaluator).
- Enforces lifecycle state machine transitions and staleness detection.
- Provides agent-friendly project summaries and explicit human action requests.
- Contains zero framework dependencies (no FastAPI, HTTPException, MCP, or argparse).
"""

from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any
import yaml

from services.audio_export import AudioExportService
from services.audio_mastering import AudioMasteringService, load_mastering_profile
from services.audio_mix_models import (
    ExportManifest,
    ExportProfile,
    MasteringProfile,
    MixArtifact,
    MixPlan,
)
from services.mix_plan_builder import MixPlanBuilder
from services.wave_audio_mixer import WaveAudioMixer
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
    resolve_asset_file_path,
    resolve_project_resources,
)
from services.sound_director import direct_sound
from services.story_analyzer import (
    analyze_story_beats,
    story_beats_to_narration_segments,
)
from services.tts.base import CancellationToken, ProgressCallback, TTSExecutionPort
from services.tts.provider_factory import create_tts_provider
from services.voice_plan import VoicePlan, build_voice_plan
from services.voice_project_models import (
    BeatNotFoundError,
    ExportDependencyUnavailableError,
    HumanActionRequired,
    HumanActionType,
    InvalidProjectStateError,
    MixPlanStaleError,
    ResourceCheckResult,
    StaleArtifactError,
    VoicePlanningResult,
    VoiceProjectNotFound,
    VoiceProjectSummary,
    VoiceRenderResult,
    compute_file_sha256,
)
from services.voice_project_store import VoiceProjectStore
from services.voice_qc import evaluate_beat_qc
from services.voice_renderer import (
    ProviderUnavailableError,
    ResourceBlockedError,
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

        rendered_beats = len([b for b in manifest.beats.values() if b.attempts]) if manifest else 0
        required_gaps_count = len([g for g in report.missing if g.priority.value == "required"]) if report else 0
        recommended_gaps_count = len([g for g in report.missing if g.priority.value == "recommended"]) if report else 0

        return VoiceProjectSummary(
            project_id=project_id,
            title=state.title or project_id,
            stage=state.stage,
            language=getattr(state, "language", "en"),
            total_beats=total_beats,
            rendered_beats=rendered_beats,
            passed_beats=passed_beats,
            review_beats=review_beats,
            failed_beats=failed_beats,
            resource_readiness_score=readiness_score,
            resource_blocked=resource_blocked,
            required_gaps_count=required_gaps_count,
            recommended_gaps_count=recommended_gaps_count,
            provider=self.provider_name,
            suggested_action=suggested_action,
            human_action=human_action,
            last_error=state.error,
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
            raise InvalidProjectStateError(
                f"Cannot plan project '{project_id}' from state '{state.stage.value}'"
            )

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
        allow_substitutions: bool = True,
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
                sub_rules = load_substitution_rules() if allow_substitutions else {}
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
        max_retries: int = 3,
        progress_callback: Any | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> VoiceRenderResult:
        """Render narration beats through injected TTSExecutionPort with Voice QC verification."""
        if max_retries < 1:
            raise ValueError("max_retries must be at least 1")
        state = self.store.get_project_state(project_id)

        # 1. Staleness Check
        is_stale, reason = self.store.check_staleness(project_id, for_render=True)
        if is_stale:
            raise StaleArtifactError(f"Cannot render project '{project_id}': {reason}")

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

        report = self.store.load_resource_report(project_id)
        if report is None:
            raise InvalidProjectStateError(
                f"Cannot render project '{project_id}': Resource report is missing. Run check_resources() first."
            )
        if report.readiness.render_blocked and not allow_resource_blocked:
            missing_terms = [g.term or g.intent or g.id for g in report.missing if g.priority.value == "required"]
            raise ResourceBlockedError(
                f"Cannot render project '{project_id}': Resource check is BLOCKED. "
                f"Missing required resources: {', '.join(missing_terms)}"
            )

        allowed_from = {
            ProjectStatus.READY_TO_RENDER,
            ProjectStatus.REVIEW_REQUIRED,
            ProjectStatus.NARRATION_READY,
            ProjectStatus.FAILED,
        }
        if force_rerender and beats:
            allowed_from.update({
                ProjectStatus.MIX_READY,
                ProjectStatus.MIXED,
                ProjectStatus.MASTERED,
                ProjectStatus.COMPLETED,
            })
        if allow_resource_blocked:
            allowed_from.add(ProjectStatus.RESOURCE_BLOCKED)
        if state.stage not in allowed_from:
            raise InvalidProjectStateError(
                f"Cannot render project '{project_id}' from state '{state.stage.value}'. "
                "Run check_resources() first."
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
                    max_retries=max_retries,
                    allow_resource_blocked=allow_resource_blocked,
                    force_rerender=force_rerender,
                    progress_callback=progress_callback,
                    cancellation_token=cancellation_token,
                )
                self.store.save_manifest(project_id, manifest)

                # Assess final project stage from manifest
                total_beats = len(plan.beats)
                passed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.PASSED)
                review_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.NEEDS_REVIEW)
                failed_statuses = {RenderStatus.FAILED, RenderStatus.QC_FAILED}
                failed_beats = sum(1 for b in manifest.beats.values() if b.status in failed_statuses)
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
        progress_callback: Any | None = None,
        cancellation_token: CancellationToken | None = None,
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
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
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

        if beats:
            valid_ids = {b.id for b in plan.beats}
            unknown_ids = set(beats) - valid_ids
            if unknown_ids:
                raise BeatNotFoundError(
                    f"Beat ID(s) not found in project '{project_id}': {', '.join(sorted(unknown_ids))}"
                )

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
                        elif qc.verdict.value == "retry":
                            attempt.status = RenderStatus.QC_FAILED
                        else:
                            attempt.status = RenderStatus.FAILED

                # Re-select best candidate
                best_attempt = select_best_candidate(b_state.attempts)
                if best_attempt and best_attempt.qc_result and best_attempt.qc_result.verdict.value == "pass":
                    b_state.selected_attempt = best_attempt.attempt
                    b_state.status = RenderStatus.PASSED
                elif any(a.qc_result and a.qc_result.verdict.value == "needs_review" for a in b_state.attempts):
                    b_state.status = RenderStatus.NEEDS_REVIEW
                elif any(a.status == RenderStatus.FAILED for a in b_state.attempts):
                    b_state.status = RenderStatus.FAILED
                else:
                    b_state.status = RenderStatus.QC_FAILED

            self.store.save_manifest(project_id, manifest)

            total_beats = len(plan.beats)
            passed_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.PASSED)
            review_beats = sum(1 for b in manifest.beats.values() if b.status == RenderStatus.NEEDS_REVIEW)
            failed_statuses = {RenderStatus.FAILED, RenderStatus.QC_FAILED}
            failed_beats = sum(1 for b in manifest.beats.values() if b.status in failed_statuses)
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

    # ==========================================
    # Phase 14: Mix, Master & Export Operations
    # ==========================================

    def prepare_for_mix(
        self,
        project_id: str,
        mix_config: dict[str, Any] | None = None,
        mastering_profile: str = "storytelling",
        output_formats: list[str] | None = None,
    ) -> MixPlan:
        """Construct and persist deterministic MixPlan from passed narration renders."""
        state = self.store.get_project_state(project_id)
        allowed_from = (
            ProjectStatus.NARRATION_READY,
            ProjectStatus.MIX_READY,
            ProjectStatus.MIXED,
            ProjectStatus.MASTERED,
            ProjectStatus.COMPLETED,
            ProjectStatus.FAILED,
        )
        if state.stage not in allowed_from:
            raise InvalidProjectStateError(
                f"Cannot prepare mix for project '{project_id}' from state '{state.stage.value}'. "
                "All narration beats must be rendered and passed (NARRATION_READY) first."
            )

        with self.store.get_project_lock(project_id):
            state.stage = ProjectStatus.PREPARING_MIX
            self.store.save_project_state(state)

            try:
                plan = self.store.load_voice_plan(project_id)
                manifest = self.store.load_manifest(project_id)
                report = self.store.load_resource_report(project_id)
                proj_dir = self.store.get_project_dir(project_id)

                if not plan or not manifest:
                    raise InvalidProjectStateError("VoicePlan or RenderManifest missing.")

                builder = MixPlanBuilder()
                m_profile = load_mastering_profile(mastering_profile)
                e_profiles = [ExportProfile(format=fmt) for fmt in (output_formats or ["wav"])]

                mix_plan = builder.build(
                    project_id=project_id,
                    voice_plan=plan,
                    render_manifest=manifest,
                    proj_dir=proj_dir,
                    resource_report=report,
                    mix_config=mix_config,
                    mastering_profile=m_profile,
                    export_profiles=e_profiles,
                )

                # Persist MixPlan
                mix_plan_path = proj_dir / "mix-plan.yaml"
                temp_path = mix_plan_path.with_suffix(".tmp.yaml")
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(mix_plan.to_yaml())
                temp_path.replace(mix_plan_path)

                state.stage = ProjectStatus.MIX_READY
                state.last_stable_stage = ProjectStatus.MIX_READY
                state.error = None
                self.store.save_project_state(state)

                return mix_plan
            except Exception as e:
                state.stage = state.last_stable_stage
                state.error = f"Prepare mix failed: {str(e)}"
                self.store.save_project_state(state)
                raise

    def mix(
        self,
        project_id: str,
        mix_config: dict[str, Any] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """Execute multi-track audio mixing to generate mix/premaster.wav."""
        state = self.store.get_project_state(project_id)
        proj_dir = self.store.get_project_dir(project_id)
        mix_plan_path = proj_dir / "mix-plan.yaml"

        if not mix_plan_path.exists():
            self.prepare_for_mix(project_id, mix_config=mix_config)
        mix_plan, _, mix_plan_path = self._load_valid_mix_plan(project_id)

        with self.store.get_project_lock(project_id):
            state.stage = ProjectStatus.MIXING
            self.store.save_project_state(state)
            pending_path = proj_dir / "mix" / "premaster.pending.wav"

            try:
                mix_dir = proj_dir / "mix"
                mix_dir.mkdir(parents=True, exist_ok=True)
                premaster_path = mix_dir / "premaster.wav"

                mixer = WaveAudioMixer()
                mixer.mix(
                    plan=mix_plan,
                    proj_dir=proj_dir,
                    output_path=pending_path,
                    progress_callback=progress_callback,
                    cancellation_token=cancellation_token,
                )

                if (cancellation_token and cancellation_token.is_cancelled()) or not pending_path.exists():
                    state.stage = state.last_stable_stage
                    self.store.save_project_state(state)
                    return {"status": "cancelled"}

                pending_path.replace(premaster_path)
                self._write_lineage(mix_dir / "premaster.lineage", mix_plan_path, premaster_path)

                state.stage = ProjectStatus.MIXED
                state.last_stable_stage = ProjectStatus.MIXED
                state.error = None
                self.store.save_project_state(state)

                return {
                    "project_id": project_id,
                    "stage": "MIXED",
                    "premaster_path": str(premaster_path),
                    "duration_ms": mix_plan.duration_ms,
                }
            except Exception as e:
                state.stage = state.last_stable_stage
                state.error = f"Mixing failed: {str(e)}"
                self.store.save_project_state(state)
                raise
            finally:
                if pending_path.exists():
                    pending_path.unlink()

    def master(
        self,
        project_id: str,
        profile_name: str = "storytelling",
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> dict[str, Any]:
        """Apply loudness normalization and true peak limiting to create mix/master.wav."""
        state = self.store.get_project_state(project_id)
        proj_dir = self.store.get_project_dir(project_id)
        premaster_path = proj_dir / "mix" / "premaster.wav"
        _, _, mix_plan_path = self._load_valid_mix_plan(project_id)
        if premaster_path.exists():
            self._verify_lineage(
                premaster_path, proj_dir / "mix" / "premaster.lineage", mix_plan_path, "Premaster"
            )
        else:
            self.mix(project_id, cancellation_token=cancellation_token)

        with self.store.get_project_lock(project_id):
            state.stage = ProjectStatus.MASTERING
            self.store.save_project_state(state)
            pending_path = proj_dir / "mix" / "master.pending.wav"

            try:
                master_path = proj_dir / "mix" / "master.wav"
                service = AudioMasteringService()
                prof = load_mastering_profile(profile_name)

                result = service.master(
                    input_wav_path=premaster_path,
                    output_wav_path=pending_path,
                    profile=prof,
                    progress_callback=progress_callback,
                    cancellation_token=cancellation_token,
                )

                if (
                    result.get("cancelled")
                    or (cancellation_token and cancellation_token.is_cancelled())
                    or not pending_path.exists()
                ):
                    state.stage = state.last_stable_stage
                    self.store.save_project_state(state)
                    return {"status": "cancelled"}

                pending_path.replace(master_path)
                self._write_lineage(proj_dir / "mix" / "master.lineage", premaster_path, master_path)

                state.stage = ProjectStatus.MASTERED
                state.last_stable_stage = ProjectStatus.MASTERED
                state.error = None
                self.store.save_project_state(state)

                return {
                    "project_id": project_id,
                    "stage": "MASTERED",
                    "master_path": str(master_path),
                    "metrics": result,
                }
            except Exception as e:
                state.stage = state.last_stable_stage
                state.error = f"Mastering failed: {str(e)}"
                self.store.save_project_state(state)
                raise
            finally:
                if pending_path.exists():
                    pending_path.unlink()

    def export(
        self,
        project_id: str,
        formats: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExportManifest:
        """Package master audio into final deliverable artifacts (exports/FINAL.wav)."""
        state = self.store.get_project_state(project_id)
        proj_dir = self.store.get_project_dir(project_id)
        master_path = proj_dir / "mix" / "master.wav"
        _, _, mix_plan_path = self._load_valid_mix_plan(project_id)
        premaster_path = proj_dir / "mix" / "premaster.wav"
        if premaster_path.exists():
            self._verify_lineage(
                premaster_path, proj_dir / "mix" / "premaster.lineage", mix_plan_path, "Premaster"
            )
        if master_path.exists():
            self._verify_lineage(
                master_path, proj_dir / "mix" / "master.lineage", premaster_path, "Master"
            )
        else:
            self.master(project_id, cancellation_token=cancellation_token)

        with self.store.get_project_lock(project_id):
            state.stage = ProjectStatus.EXPORTING
            self.store.save_project_state(state)

            try:
                export_dir = proj_dir / "exports"
                service = AudioExportService()
                profiles = [ExportProfile(format=fmt) for fmt in (formats or ["wav"])]

                manifest = service.export(
                    project_id=project_id,
                    master_wav_path=master_path,
                    export_profiles=profiles,
                    output_dir=export_dir,
                    progress_callback=progress_callback,
                    cancellation_token=cancellation_token,
                )

                if cancellation_token and cancellation_token.is_cancelled():
                    state.stage = state.last_stable_stage
                    self.store.save_project_state(state)
                    return manifest

                state.stage = ProjectStatus.COMPLETED
                state.last_stable_stage = ProjectStatus.COMPLETED
                state.error = None
                self.store.save_project_state(state)

                return manifest
            except Exception as e:
                state.stage = state.last_stable_stage
                state.error = f"Export failed: {str(e)}"
                self.store.save_project_state(state)
                raise

    def finalize(
        self,
        project_id: str,
        mix_config: dict[str, Any] | None = None,
        mastering_profile: str = "storytelling",
        output_formats: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> ExportManifest:
        """Run complete end-to-end post-production pipeline (prepare_for_mix -> mix -> master -> export)."""
        if progress_callback:
            progress_callback("finalizing_prepare_mix", 10.0, {"step": "prepare_mix"})
        self.prepare_for_mix(
            project_id=project_id,
            mix_config=mix_config,
            mastering_profile=mastering_profile,
            output_formats=output_formats,
        )

        if cancellation_token and cancellation_token.is_cancelled():
            return ExportManifest(project_id=project_id)

        if progress_callback:
            progress_callback("finalizing_mixing", 40.0, {"step": "mix"})
        self.mix(
            project_id=project_id,
            mix_config=mix_config,
            cancellation_token=cancellation_token,
        )

        if cancellation_token and cancellation_token.is_cancelled():
            return ExportManifest(project_id=project_id)

        if progress_callback:
            progress_callback("finalizing_mastering", 70.0, {"step": "master"})
        self.master(
            project_id=project_id,
            profile_name=mastering_profile,
            cancellation_token=cancellation_token,
        )

        if cancellation_token and cancellation_token.is_cancelled():
            return ExportManifest(project_id=project_id)

        if progress_callback:
            progress_callback("finalizing_exporting", 90.0, {"step": "export"})
        manifest = self.export(
            project_id=project_id,
            formats=output_formats or ["wav"],
            progress_callback=progress_callback,
            cancellation_token=cancellation_token,
        )

        return manifest

    def list_artifacts(self, project_id: str) -> list[dict[str, Any]]:
        """List all generated deliverable audio and plan artifacts for a project."""
        self.store.validate_project_id(project_id)
        proj_dir = self.store.get_project_dir(project_id)
        artifacts: list[dict[str, Any]] = []

        # Check exports directory
        export_manifest_path = proj_dir / "exports" / "export-manifest.yaml"
        if export_manifest_path.exists():
            try:
                with open(export_manifest_path, "r", encoding="utf-8") as f:
                    m_data = yaml.safe_load(f) or {}
                manifest = ExportManifest.from_dict(m_data)
                for art in manifest.artifacts:
                    art_file = proj_dir / art.file_path
                    if art_file.exists():
                        artifacts.append({
                            "id": art.artifact_id,
                            "type": art.artifact_type,
                            "filename": art_file.name,
                            "size_bytes": art_file.stat().st_size,
                            "sha256": art.sha256,
                            "created_at": art.created_at,
                            "download_url": f"/api/v1/voice-projects/{project_id}/artifacts/{art.artifact_id}",
                        })
            except Exception as e:
                logger.warning("Failed to parse export manifest for '%s': %s", project_id, e)

        # Check FINAL.wav directly if manifest wasn't present
        final_wav = proj_dir / "exports" / "FINAL.wav"
        if final_wav.exists() and not any(a["id"] == "final_wav" for a in artifacts):
            artifacts.append({
                "id": "final_wav",
                "type": "final_wav",
                "filename": "FINAL.wav",
                "size_bytes": final_wav.stat().st_size,
                "sha256": compute_file_sha256(final_wav),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "download_url": f"/api/v1/voice-projects/{project_id}/artifacts/final_wav",
            })

        # Check mix-plan.yaml
        mix_plan_path = proj_dir / "mix-plan.yaml"
        if mix_plan_path.exists():
            artifacts.append({
                "id": "mix_plan",
                "type": "mix_plan",
                "filename": "mix-plan.yaml",
                "size_bytes": mix_plan_path.stat().st_size,
                "sha256": compute_file_sha256(mix_plan_path),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "download_url": f"/api/v1/voice-projects/{project_id}/artifacts/mix_plan",
            })

        return artifacts

    def _load_valid_mix_plan(self, project_id: str) -> tuple[MixPlan, RenderManifest, Path]:
        """Load a MixPlan and reject it when any upstream input has changed."""
        proj_dir = self.store.get_project_dir(project_id)
        mix_plan_path = proj_dir / "mix-plan.yaml"
        if not mix_plan_path.exists():
            self.prepare_for_mix(project_id)
        with open(mix_plan_path, "r", encoding="utf-8") as f:
            mix_plan = MixPlan.from_yaml(f.read())

        plan = self.store.load_voice_plan(project_id)
        manifest = self.store.load_manifest(project_id)
        if not plan or not manifest:
            raise InvalidProjectStateError("Cannot mix: VoicePlan or RenderManifest missing.")

        paths = {
            "voice_plan_sha256": proj_dir / "voice-plan.yaml",
            "render_manifest_sha256": proj_dir / "render-manifest.yaml",
            "resource_report_sha256": proj_dir / "resource-report.yaml",
        }
        for hash_name, path in paths.items():
            expected = mix_plan.dependency_hashes.get(hash_name)
            if expected and (not path.exists() or compute_file_sha256(path) != expected):
                raise MixPlanStaleError(
                    f"MixPlan for project '{project_id}' is stale: {path.name} has changed "
                    "since MixPlan was generated. Run prepare_for_mix() again."
                )

        for vclip in mix_plan.voice_clips:
            beat = manifest.beats.get(vclip.beat_id)
            if not beat or beat.selected_attempt != vclip.selected_attempt:
                raise MixPlanStaleError(f"MixPlan is stale: selected render changed for beat '{vclip.beat_id}'.")
            clip_file = Path(vclip.source_path)
            if not clip_file.is_absolute():
                clip_file = proj_dir / clip_file
            if not clip_file.exists() or (vclip.source_sha256 and compute_file_sha256(clip_file) != vclip.source_sha256):
                raise MixPlanStaleError(f"MixPlan is stale: audio changed for beat '{vclip.beat_id}'.")

        for clip_type, clips in (("ambience", mix_plan.ambience_clips), ("SFX", mix_plan.sfx_clips)):
            for clip in clips:
                source = resolve_asset_file_path(clip.source_path, project_dir=proj_dir)
                if not source.exists() or (clip.source_sha256 and compute_file_sha256(source) != clip.source_sha256):
                    raise MixPlanStaleError(f"MixPlan is stale: {clip_type} asset '{clip.resource_id}' changed.")
        return mix_plan, manifest, mix_plan_path

    @staticmethod
    def _write_lineage(lineage_path: Path, source: Path, artifact: Path) -> None:
        data = {
            "source_sha256": compute_file_sha256(source),
            "artifact_sha256": compute_file_sha256(artifact),
        }
        pending_path = lineage_path.with_suffix(".pending")
        try:
            pending_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
            pending_path.replace(lineage_path)
        finally:
            if pending_path.exists():
                pending_path.unlink()

    @staticmethod
    def _verify_lineage(artifact: Path, lineage_path: Path, source: Path, label: str) -> None:
        if not artifact.exists():
            return
        lineage = {}
        if lineage_path.exists():
            lineage = yaml.safe_load(lineage_path.read_text(encoding="utf-8")) or {}
        if not source.exists() or lineage != {
            "source_sha256": compute_file_sha256(source),
            "artifact_sha256": compute_file_sha256(artifact),
        }:
            raise MixPlanStaleError(f"{label} is stale relative to {source.name}; rebuild it before continuing.")
