"""Production Health Service (Phase 20).

Aggregates project/series health from project state, workflow state, operation
state, and artifact freshness into typed health snapshots. Also provides
startup recovery logic for interrupted operations and stale artifacts.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from services.production_event_models import (
    ProjectProductionHealth,
    SeriesProductionHealth,
)

logger = logging.getLogger(__name__)


# ==========================================
# Health Aggregation
# ==========================================


def get_project_health(
    project_id: str,
    project_store: Any | None = None,
    operation_manager: Any | None = None,
    workflow_service: Any | None = None,
) -> ProjectProductionHealth:
    """Build a ProjectProductionHealth snapshot by aggregating available state sources.

    Gracefully degrades if individual sources are unavailable (e.g., no workflow yet).
    """
    from services.voice_project_dependencies import (
        get_voice_project_store,
        get_voice_project_operation_manager,
    )

    store = project_store or get_voice_project_store()
    op_manager = operation_manager or get_voice_project_operation_manager()

    # --- Project state ---
    project_status = "unknown"
    last_error: dict[str, Any] | None = None
    human_actions: list[dict[str, Any]] = []
    artifact_freshness: dict[str, str] = {}
    suggested_action = ""
    current_step: str | None = None
    progress_percent: float | None = None
    last_successful_step: str | None = None

    try:
        state = store.get_project_state(project_id)
        project_status = state.stage.value
        if state.error:
            last_error = {"message": state.error, "code": "INTERNAL_ERROR"}

        # Artifact freshness: compare stored sha256 against disk reality
        from services.voice_project_models import compute_file_sha256
        proj_dir = store.get_project_dir(project_id)

        artifacts_map = {
            "voice_plan": state.artifacts.voice_plan,
            "resource_report": state.artifacts.resource_report,
            "render_manifest": state.artifacts.render_manifest,
        }
        stored_hashes = {
            "voice_plan": state.artifacts.voice_plan_sha256,
            "resource_report": state.artifacts.resource_report_sha256,
            "render_manifest": state.artifacts.render_manifest_sha256,
        }
        for artifact_key, rel_path in artifacts_map.items():
            full_path = proj_dir / rel_path
            if not full_path.exists():
                artifact_freshness[artifact_key] = "missing"
            else:
                disk_hash = compute_file_sha256(full_path)
                stored_hash = stored_hashes.get(artifact_key, "")
                if not stored_hash:
                    artifact_freshness[artifact_key] = "untracked"
                elif disk_hash == stored_hash:
                    artifact_freshness[artifact_key] = "fresh"
                else:
                    artifact_freshness[artifact_key] = "stale"

    except Exception as exc:
        logger.warning("Could not load project state for '%s': %s", project_id, exc)
        project_status = "not_found"
        suggested_action = f"Project '{project_id}' not found or state unreadable."

    # --- Active operation ---
    active_operation: str | None = None
    try:
        ops = op_manager.list_operations(project_id=project_id, limit=10)
        if ops:
            latest = ops[0]
            from services.voice_project_operations import OperationStatus
            if latest.status in (
                OperationStatus.QUEUED,
                OperationStatus.RUNNING,
                OperationStatus.CANCELLING,
            ):
                active_operation = latest.id
                current_step = latest.stage or latest.operation
                progress_percent = latest.progress_percent

            # Find last successful step
            for op in ops:
                if op.status == OperationStatus.COMPLETED:
                    last_successful_step = op.operation
                    break

            # Expose last error from most recent failed op
            if last_error is None:
                for op in ops:
                    if op.status == OperationStatus.FAILED and op.error:
                        last_error = op.error
                        break
    except Exception as exc:
        logger.debug("Could not load operations for project '%s': %s", project_id, exc)

    # --- Workflow state ---
    try:
        if workflow_service is None:
            from services.voice_project_dependencies import get_voice_project_workflow_service
            workflow_service = get_voice_project_workflow_service()

        from services.voice_project_workflow_models import WorkflowStatus
        wf_list = workflow_service.list_workflows(project_id=project_id)
        if wf_list:
            # Most recent workflow first
            wf = wf_list[0]
            if current_step is None:
                current_step = wf.current_step
            if wf.human_action:
                human_actions.append(wf.human_action)
            if not suggested_action:
                suggested_action = wf.suggested_action or ""
    except Exception as exc:
        logger.debug("Could not load workflow state for project '%s': %s", project_id, exc)

    # --- Runtime health ---
    runtime_health: dict[str, Any] = _collect_runtime_health()

    # --- Suggested action fallback ---
    if not suggested_action:
        suggested_action = _suggest_action_for_project(project_status, last_error, human_actions)

    return ProjectProductionHealth(
        project_id=project_id,
        status=project_status,
        current_step=current_step,
        progress_percent=progress_percent,
        active_operation=active_operation,
        last_successful_step=last_successful_step,
        last_error=last_error,
        human_actions=human_actions,
        artifact_freshness=artifact_freshness,
        runtime_health=runtime_health,
        suggested_action=suggested_action,
    )


def get_series_health(
    series_id: str,
    project_store: Any | None = None,
    series_store: Any | None = None,
) -> SeriesProductionHealth:
    """Build a SeriesProductionHealth by aggregating health across all member episodes."""
    from services.voice_project_dependencies import get_voice_project_store
    from services.voice_series_store import get_voice_series_store
    from services.render_models import ProjectStatus

    p_store = project_store or get_voice_project_store()
    s_store = series_store or get_voice_series_store()

    # Discover member episodes from series store if available
    episodes = []
    try:
        episodes = s_store.list_episodes(series_id)
    except Exception:
        pass

    members = [ep.project_id for ep in episodes if getattr(ep, "project_id", None)]

    if not members:
        # Fallback to discovering member projects by prefix
        all_projects = p_store.list_projects()
        prefix = f"{series_id}_"
        members = [pid for pid in all_projects if pid.startswith(prefix)]

    episode_count = len(members)
    completed_count = 0
    failed_count = 0
    waiting_for_human = 0
    total_progress = 0.0

    terminal_completed = {ProjectStatus.COMPLETED}
    terminal_failed = {ProjectStatus.FAILED}
    human_wait_stages = {
        ProjectStatus.REVIEW_REQUIRED,
        ProjectStatus.RESOURCE_BLOCKED,
    }

    for pid in members:
        try:
            state = p_store.get_project_state(pid)
            stage = state.stage
            if stage in terminal_completed:
                completed_count += 1
                total_progress += 100.0
            elif stage in terminal_failed:
                failed_count += 1
            elif stage in human_wait_stages:
                waiting_for_human += 1
                total_progress += _stage_to_progress(stage)
            else:
                total_progress += _stage_to_progress(stage)
        except Exception:
            failed_count += 1

    progress_percent = (total_progress / episode_count) if episode_count > 0 else 0.0

    # Determine overall series status
    if episode_count == 0:
        status = "empty"
        suggested_action = "No episodes found for this series."
    elif completed_count == episode_count:
        status = "completed"
        suggested_action = "All episodes completed."
    elif failed_count > 0 and failed_count == episode_count - completed_count:
        status = "failed"
        suggested_action = f"{failed_count} episode(s) failed. Review logs and retry."
    elif waiting_for_human > 0:
        status = "waiting_for_human"
        suggested_action = f"{waiting_for_human} episode(s) require human action."
    else:
        status = "in_progress"
        suggested_action = f"{completed_count}/{episode_count} episodes completed."

    return SeriesProductionHealth(
        series_id=series_id,
        status=status,
        episode_count=episode_count,
        completed_count=completed_count,
        failed_count=failed_count,
        waiting_for_human=waiting_for_human,
        progress_percent=round(progress_percent, 1),
        suggested_action=suggested_action,
    )


# ==========================================
# Startup Recovery
# ==========================================


def recover_on_startup(
    project_store: Any,
    series_store: Any | None = None,
) -> dict[str, Any]:
    """Scan all projects at startup and recover inconsistent state.

    Recovery actions:
    1. Mark stale running/queued operations as INTERRUPTED.
    2. Clean orphaned pending audio files without manifest entries.
    3. Validate lineage hashes (sha256) and mark inconsistent artifacts as stale.

    NEVER silently continues a human approval gate.
    NEVER silently approves NEEDS_REVIEW beats.

    Returns a structured recovery report.
    """
    report: dict[str, Any] = {
        "projects_scanned": 0,
        "operations_interrupted": [],
        "orphaned_files_removed": [],
        "stale_artifacts_flagged": [],
        "lineage_failures": [],
        "errors": [],
    }

    all_projects: list[str] = []
    try:
        all_projects = project_store.list_projects()
    except Exception as exc:
        logger.warning("recover_on_startup: could not list projects: %s", exc)
        report["errors"].append(str(exc))
        return report

    report["projects_scanned"] = len(all_projects)

    from services.voice_project_models import compute_file_sha256
    from services.render_models import ProjectStatus

    for project_id in all_projects:
        try:
            proj_dir = project_store.get_project_dir(project_id)
            state = project_store.get_project_state(project_id)

            # 1. Validate artifact sha256 hashes
            artifacts_to_check = [
                ("voice_plan", state.artifacts.voice_plan, state.artifacts.voice_plan_sha256),
                (
                    "resource_report",
                    state.artifacts.resource_report,
                    state.artifacts.resource_report_sha256,
                ),
                (
                    "render_manifest",
                    state.artifacts.render_manifest,
                    state.artifacts.render_manifest_sha256,
                ),
            ]
            for artifact_key, rel_path, stored_hash in artifacts_to_check:
                if not stored_hash:
                    continue
                full_path = proj_dir / rel_path
                if not full_path.exists():
                    continue
                disk_hash = compute_file_sha256(full_path)
                if disk_hash != stored_hash:
                    logger.warning(
                        "Project '%s' artifact '%s' hash mismatch — flagging stale and persisting error state.",
                        project_id,
                        artifact_key,
                    )
                    report["stale_artifacts_flagged"].append(
                        {"project_id": project_id, "artifact": artifact_key}
                    )
                    report["lineage_failures"].append(
                        {
                            "project_id": project_id,
                            "artifact": artifact_key,
                            "reason": "sha256_mismatch",
                        }
                    )
                    # Persist stale artifact detection into project state
                    try:
                        state.error = f"Stale artifact detected: '{artifact_key}' disk hash mismatch. Re-run planning/rendering."
                        state.stage = ProjectStatus.NEW
                        state.last_stable_stage = ProjectStatus.NEW
                        state.artifacts.voice_plan_sha256 = ""
                        state.artifacts.resource_report_sha256 = ""
                        state.artifacts.render_manifest_sha256 = ""
                        project_store.save_project_state(state)
                    except Exception as save_exc:
                        logger.warning("Failed to save project state for '%s': %s", project_id, save_exc)

            # 2. Clean orphaned pending audio files
            pending_dir = proj_dir / "audio" / "pending"
            if pending_dir.exists():
                manifest_path = proj_dir / state.artifacts.render_manifest
                manifest_entries: set[str] = set()
                if manifest_path.exists():
                    try:
                        import yaml
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            manifest_data = yaml.safe_load(f) or {}
                        beats = manifest_data.get("beats", {})
                        for beat_data in beats.values():
                            if isinstance(beat_data, dict):
                                af = beat_data.get("audio_file", "")
                                if af:
                                    manifest_entries.add(Path(af).name)
                    except Exception as exc:
                        logger.debug(
                            "Could not read render manifest for '%s': %s", project_id, exc
                        )

                for pending_file in pending_dir.iterdir():
                    if pending_file.is_file() and pending_file.name not in manifest_entries:
                        try:
                            pending_file.unlink()
                            report["orphaned_files_removed"].append(
                                {"project_id": project_id, "file": pending_file.name}
                            )
                            logger.info(
                                "Removed orphaned pending file '%s' in project '%s'.",
                                pending_file.name,
                                project_id,
                            )
                        except OSError as exc:
                            logger.warning(
                                "Could not remove orphaned file '%s': %s", pending_file, exc
                            )

        except Exception as exc:
            logger.warning("recover_on_startup: error processing project '%s': %s", project_id, exc)
            report["errors"].append({"project_id": project_id, "error": str(exc)})

    # 3. Mark stale running operations — handled by VoiceProjectOperationManager on init
    #    We log the report entries that were already marked INTERRUPTED.
    try:
        from services.voice_project_dependencies import get_voice_project_operation_manager
        op_manager = get_voice_project_operation_manager()
        from services.voice_project_operations import OperationStatus
        for op in op_manager.list_operations(limit=500):
            if op.status == OperationStatus.INTERRUPTED:
                report["operations_interrupted"].append(
                    {"operation_id": op.id, "project_id": op.project_id, "operation": op.operation}
                )
    except Exception as exc:
        logger.debug("recover_on_startup: could not enumerate interrupted ops: %s", exc)

    logger.info(
        "Startup recovery complete. Projects scanned: %d, ops interrupted: %d, "
        "orphaned files removed: %d, stale artifacts: %d",
        report["projects_scanned"],
        len(report["operations_interrupted"]),
        len(report["orphaned_files_removed"]),
        len(report["stale_artifacts_flagged"]),
    )
    return report


# ==========================================
# Internal helpers
# ==========================================


def _stage_to_progress(stage: Any) -> float:
    """Map a ProjectStatus stage to an approximate progress percentage."""
    from services.render_models import ProjectStatus
    _STAGE_PROGRESS: dict[str, float] = {
        ProjectStatus.NEW.value: 0.0,
        ProjectStatus.PLANNING.value: 10.0,
        ProjectStatus.PLANNED.value: 20.0,
        ProjectStatus.RESOURCE_CHECKING.value: 25.0,
        ProjectStatus.RESOURCE_BLOCKED.value: 25.0,
        ProjectStatus.READY_TO_RENDER.value: 30.0,
        ProjectStatus.RENDERING.value: 50.0,
        ProjectStatus.QC_PENDING.value: 55.0,
        ProjectStatus.REVIEW_REQUIRED.value: 60.0,
        ProjectStatus.NARRATION_READY.value: 65.0,
        ProjectStatus.PREPARING_MIX.value: 70.0,
        ProjectStatus.MIX_READY.value: 75.0,
        ProjectStatus.MIXING.value: 80.0,
        ProjectStatus.MIXED.value: 83.0,
        ProjectStatus.MASTERING.value: 86.0,
        ProjectStatus.MASTERED.value: 90.0,
        ProjectStatus.EXPORTING.value: 95.0,
        ProjectStatus.COMPLETED.value: 100.0,
        ProjectStatus.FAILED.value: 0.0,
    }
    stage_val = stage.value if hasattr(stage, "value") else str(stage)
    return _STAGE_PROGRESS.get(stage_val, 0.0)


def _collect_runtime_health() -> dict[str, Any]:
    """Collect non-sensitive runtime capability flags."""
    health: dict[str, Any] = {}
    try:
        import shutil
        health["ffmpeg_available"] = shutil.which("ffmpeg") is not None
        health["whisper_available"] = _check_import("whisper")
        health["torch_available"] = _check_import("torch")
    except Exception:
        pass
    return health


def _check_import(module_name: str) -> bool:
    """Check whether a Python module can be imported without loading it fully."""
    import importlib.util
    return importlib.util.find_spec(module_name) is not None


def _suggest_action_for_project(
    status: str,
    last_error: dict[str, Any] | None,
    human_actions: list[dict[str, Any]],
) -> str:
    """Generate a suggested next action string based on project status."""
    if human_actions:
        return "Human action required — review pending items."
    if status in ("RESOURCE_BLOCKED",):
        return "Resolve missing resources then retry check_resources."
    if status in ("REVIEW_REQUIRED",):
        return "Audio QC requires human review. Use director review tools."
    if status in ("FAILED",):
        return "Project encountered a failure. Check last_error for details."
    if status in ("COMPLETED",):
        return "Project is complete. Export artifacts are available."
    if status == "not_found":
        return "Project not found."
    return ""
