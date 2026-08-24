"""Per-Beat TTS Renderer Service (Phase 8).

Renders narration story beats one-by-one into WAV attempts, manages
render manifests, enforces resource readiness gates, and supports selective
rerendering, auto-QC loops, and idempotent resumption.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import yaml

from services.voice_plan import VoicePlan, Beat
from services.resource_models import ResourceReport
from services.render_models import (
    BeatQCResult,
    BeatRenderState,
    ProjectState,
    ProjectStatus,
    QCVerdict,
    RenderAttempt,
    RenderManifest,
    RenderStatus,
    TTSRenderRequest,
)
from services.tts.base import CancellationToken, ProgressCallback, TTSExecutionPort, TTSProvider
from services.tts.provider_factory import create_tts_provider
from services.voice_qc import evaluate_beat_qc, select_best_candidate


class ResourceBlockedError(Exception):
    """Raised when rendering is attempted while ResourceReport is blocked."""
    pass


class ProviderUnavailableError(Exception):
    """Raised when TTS provider fails healthcheck or configuration."""
    pass


def load_render_manifest(project_dir: Path) -> RenderManifest:
    """Load or initialize render-manifest.yaml for a project directory."""
    manifest_path = project_dir / "render-manifest.yaml"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return RenderManifest.from_dict(data)
    
    project_id = project_dir.name
    return RenderManifest(version=1, project_id=project_id, beats={})


def save_render_manifest(manifest: RenderManifest, project_dir: Path) -> None:
    """Save render manifest to project_dir/render-manifest.yaml."""
    manifest_path = project_dir / "render-manifest.yaml"
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest.to_dict(), f, sort_keys=False, allow_unicode=True)


def build_render_request(
    project_id: str,
    beat: Beat,
    attempt_id: int = 1,
    voice_profile: str = "mythology_narrator_male",
    pronunciation_overrides: dict[str, str] | None = None,
    retry_adjustment: dict[str, Any] | None = None,
) -> TTSRenderRequest:
    """Construct a TTSRenderRequest from Beat data, preserving original script text."""
    v_dir = beat.voice
    
    emotion = v_dir.emotion if v_dir else None
    energy = v_dir.energy if v_dir else None
    pace = v_dir.pace if v_dir else 1.0
    target_wpm = v_dir.target_wpm if v_dir else 138
    director_note = v_dir.director_note if v_dir else None
    pause_before = v_dir.pause.before if v_dir and v_dir.pause else 0.0
    pause_after = v_dir.pause.after if v_dir and v_dir.pause else 0.0

    # Apply deterministic retry adjustment if present
    if retry_adjustment:
        if "director_note" in retry_adjustment:
            director_note = f"{director_note or ''} | {retry_adjustment['director_note']}".strip(" |")
        if "energy_adjustment" in retry_adjustment and energy is not None:
            energy = max(1.0, min(5.0, energy + retry_adjustment["energy_adjustment"]))
        if "pace_multiplier" in retry_adjustment and pace is not None:
            pace = round(pace * retry_adjustment["pace_multiplier"], 2)

    # Collect pronunciation overrides
    pron_dict = dict(pronunciation_overrides or {})
    if v_dir and v_dir.pronunciation:
        pron_dict.update(v_dir.pronunciation)

    # Collect emphasis
    emphasis_list = [e.text for e in v_dir.emphasis] if v_dir and v_dir.emphasis else []

    return TTSRenderRequest(
        project_id=project_id,
        beat_id=beat.id,
        attempt_id=attempt_id,
        text=beat.script.text,  # MUST PRESERVE SCRIPT TEXT EXACTLY
        voice_profile=voice_profile,
        emotion=emotion,
        energy=energy,
        pace=pace,
        target_wpm=target_wpm,
        director_note=director_note,
        pronunciation=pron_dict,
        emphasis=emphasis_list,
        pause_before=pause_before,
        pause_after=pause_after,
        output_format="wav",
    )


def render_single_beat_attempt(
    project_dir: Path,
    project_id: str,
    beat: Beat,
    provider: TTSExecutionPort | TTSProvider,
    attempt_id: int,
    voice_profile: str = "mythology_narrator_male",
    pronunciation_overrides: dict[str, str] | None = None,
    retry_adjustment: dict[str, Any] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancellation_token: CancellationToken | None = None,
) -> RenderAttempt:
    """Render a single attempt for a beat using the chosen TTS provider."""
    beat_render_dir = project_dir / "renders" / beat.id
    beat_render_dir.mkdir(parents=True, exist_ok=True)

    request = build_render_request(
        project_id=project_id,
        beat=beat,
        attempt_id=attempt_id,
        voice_profile=voice_profile,
        pronunciation_overrides=pronunciation_overrides,
        retry_adjustment=retry_adjustment,
    )

    result = provider.render(
        request,
        beat_render_dir,
        progress_callback=progress_callback,
        cancellation_token=cancellation_token,
    )

    status = RenderStatus.RENDERED if result.success else RenderStatus.FAILED

    attempt = RenderAttempt(
        attempt=attempt_id,
        provider=result.provider,
        model=result.model,
        status=status,
        audio_path=result.audio_path or "",
        duration=result.duration,
        sample_rate=result.sample_rate,
        channels=result.channels,
        direction_summary={
            "emotion": request.emotion,
            "energy": request.energy,
            "pace": request.pace,
            "target_wpm": request.target_wpm,
            "director_note": request.director_note,
        },
        error=result.error,
        error_type=result.error_type,
        retryable=result.retryable,
        retry_after_seconds=result.retry_after_seconds,
    )

    # Save attempt metadata json
    meta_path = beat_render_dir / f"attempt_{attempt_id:02d}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(attempt.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

    return attempt


def render_project_narration(
    project_dir: Path,
    plan: VoicePlan,
    provider: TTSExecutionPort | TTSProvider | None = None,
    resource_report: ResourceReport | None = None,
    beats_filter: list[str] | None = None,
    auto_qc: bool = True,
    max_retries: int = 3,
    force_rerender: bool = False,
    allow_resource_blocked: bool = False,
    force: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancellation_token: CancellationToken | None = None,
) -> tuple[RenderManifest, ProjectState | None]:
    """Render project narration beats with resource gating, auto-QC, and resumption."""
    provider = provider or create_tts_provider()
    force_rerender = force_rerender or force
    project_dir = Path(project_dir)
    project_id = plan.project.id or project_dir.name

    # 1. Resource Readiness Gate Check
    if resource_report and resource_report.readiness.render_blocked and not allow_resource_blocked:
        reasons = "; ".join(resource_report.readiness.block_reasons)
        raise ResourceBlockedError(
            f"Cannot render project '{project_id}': Resource report is BLOCKED. Reasons: {reasons}"
        )

    # 2. Check Provider Health
    health = provider.healthcheck()
    if not health.available:
        raise ProviderUnavailableError(f"TTS Provider '{health.provider_name}' is unavailable: {health.message}")

    # 3. Load Manifest
    manifest = load_render_manifest(project_dir)
    voice_profile = plan.voice.profile if plan.voice else "mythology_narrator_male"
    pronunciation_overrides = resource_report.pronunciation_overrides if resource_report else {}

    target_beats = plan.beats
    if beats_filter:
        filter_set = set(beats_filter)
        target_beats = [b for b in plan.beats if b.id in filter_set]

    qc_dir = project_dir / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)

    for beat in target_beats:
        beat_state = manifest.get_or_create_beat(beat.id)

        # Idempotency: Skip if already passed and not forcing rerender
        if not force_rerender and beat_state.status == RenderStatus.PASSED and beat_state.selected_attempt is not None:
            continue

        # Render and QC loop (up to max_retries attempts)
        current_attempt_id = len(beat_state.attempts) + 1
        retry_adjustment: dict[str, Any] | None = None

        while current_attempt_id <= max_retries:
            if cancellation_token and cancellation_token.is_cancelled():
                break

            attempt = render_single_beat_attempt(
                project_dir=project_dir,
                project_id=project_id,
                beat=beat,
                provider=provider,
                attempt_id=current_attempt_id,
                voice_profile=voice_profile,
                pronunciation_overrides=pronunciation_overrides,
                retry_adjustment=retry_adjustment,
                progress_callback=progress_callback,
                cancellation_token=cancellation_token,
            )

            if attempt.status == RenderStatus.FAILED:
                beat_state.attempts.append(attempt)
                if attempt.retryable and current_attempt_id < max_retries:
                    retry_adjustment = {"director_note": f"Retry after transient provider error: {attempt.error}"}
                    current_attempt_id += 1
                    continue
                else:
                    beat_state.status = RenderStatus.FAILED
                    break

            if auto_qc and attempt.audio_path:
                # Run Voice QC
                qc_res = evaluate_beat_qc(
                    beat=beat,
                    audio_path=attempt.audio_path,
                    attempt_id=current_attempt_id,
                    max_retries=max_retries,
                    pronunciation_overrides=pronunciation_overrides,
                )
                attempt.qc_result = qc_res

                # Save QC Artifact
                beat_qc_dir = qc_dir / beat.id
                beat_qc_dir.mkdir(parents=True, exist_ok=True)
                qc_meta_path = beat_qc_dir / f"attempt_{current_attempt_id:02d}.json"
                with open(qc_meta_path, "w", encoding="utf-8") as f:
                    json.dump(qc_res.to_dict(), f, indent=2, ensure_ascii=False)

                if qc_res.verdict == QCVerdict.PASS:
                    attempt.status = RenderStatus.PASSED
                    beat_state.attempts.append(attempt)
                    beat_state.selected_attempt = current_attempt_id
                    beat_state.status = RenderStatus.PASSED
                    break
                elif qc_res.verdict == QCVerdict.RETRY:
                    attempt.status = RenderStatus.QC_FAILED
                    beat_state.attempts.append(attempt)
                    retry_adjustment = qc_res.retry_adjustment
                    current_attempt_id += 1
                    continue
                elif qc_res.verdict == QCVerdict.NEEDS_REVIEW:
                    attempt.status = RenderStatus.NEEDS_REVIEW
                    beat_state.attempts.append(attempt)
                    beat_state.selected_attempt = current_attempt_id
                    beat_state.status = RenderStatus.NEEDS_REVIEW
                    break
                else:
                    attempt.status = RenderStatus.FAILED
                    beat_state.attempts.append(attempt)
                    beat_state.status = RenderStatus.FAILED
                    break
            else:
                beat_state.attempts.append(attempt)
                if attempt.status == RenderStatus.RENDERED:
                    beat_state.status = RenderStatus.RENDERED
                    beat_state.selected_attempt = current_attempt_id
                else:
                    beat_state.status = RenderStatus.FAILED
                break

    # Save updated manifest
    save_render_manifest(manifest, project_dir)

    # Update project state if project.yaml exists
    state_path = project_dir / "project.yaml"
    proj_state = None
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            proj_state = ProjectState.from_dict(data)

        # Evaluate overall narration readiness
        all_passed = all(b.status == RenderStatus.PASSED for b in manifest.beats.values())
        any_needs_review = any(b.status == RenderStatus.NEEDS_REVIEW for b in manifest.beats.values())
        any_failed = any(b.status == RenderStatus.FAILED for b in manifest.beats.values())

        if all_passed and len(manifest.beats) == len(plan.beats):
            proj_state.stage = ProjectStatus.NARRATION_READY
            proj_state.status.narration_ready = True
            proj_state.status.render_ready = True
        elif any_needs_review:
            proj_state.stage = ProjectStatus.REVIEW_REQUIRED
            proj_state.status.narration_ready = False
        elif any_failed:
            proj_state.stage = ProjectStatus.FAILED
            proj_state.status.narration_ready = False
        else:
            proj_state.stage = ProjectStatus.RENDERING

        with open(state_path, "w", encoding="utf-8") as f:
            f.write(proj_state.to_yaml())

    return manifest, proj_state
