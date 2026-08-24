"""Voice CLI Service and Command Orchestrator (Phase 7).

Orchestrates project initialization, planning, resource resolution, asset ingestion,
diagnostics, per-beat rendering, and quality control.

Strictly acts as an orchestration layer without embedding low-level business logic.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
import yaml

from services.render_models import (
    ProjectArtifacts,
    ProjectState,
    ProjectStateStatus,
    ProjectStatus,
    QCVerdict,
    RenderStatus,
)
from services.voice_plan import VoicePlan, build_voice_plan
from services.story_analyzer import analyze_story_beats, story_beats_to_narration_segments
from services.narration_planner import compile_narration_plan
from services.sound_director import direct_sound
from services.director_critic import critique_voice_plan, apply_director_fixes
from services.resource_models import (
    IngestMetadata,
    RequirementPriority,
    ResourceCategory,
    ResourceReport,
)
from services.resource_manager import (
    load_manifest,
    load_selection_rules,
    load_substitution_rules,
    resolve_project_resources,
    save_manifest,
)
from services.pronunciation_knowledge import load_pronunciation_knowledge
from services.asset_ingest import ingest_asset
from services.resource_doctor import diagnose_resources
from services.tts.fake import FakeTTSProvider
from services.tts.gemini import GeminiTTSProvider
from services.tts.provider_factory import create_tts_provider
from services.voice_renderer import (
    ResourceBlockedError,
    ProviderUnavailableError,
    load_render_manifest,
    render_project_narration,
)
from services.voice_qc import evaluate_beat_qc


# Standard CLI Exit Codes
EXIT_SUCCESS = 0
EXIT_GENERIC_ERROR = 1
EXIT_VALIDATION_ERROR = 2
EXIT_RESOURCE_BLOCKED = 3
EXIT_PROVIDER_UNAVAILABLE = 4
EXIT_RENDER_FAILED = 5
EXIT_QC_FAILED = 6


def _slugify(text: str) -> str:
    """Helper to convert string to a valid directory / project id slug."""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"[-\s]+", "_", s)


from services.voice_project_models import (
    HumanActionType,
    InvalidProjectStateError,
    StaleArtifactError,
    VoiceProjectNotFound,
)
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore


def cmd_new(args: argparse.Namespace) -> int:
    """Initialize a new narration project workspace using VoiceProjectService."""
    script_path = Path(args.script_path)
    if not script_path.exists():
        if args.json:
            print(json.dumps({"error": f"Source script '{args.script_path}' not found", "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: Source script '{args.script_path}' not found", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    with open(script_path, "r", encoding="utf-8") as f:
        script_text = f.read()

    if not script_text.strip():
        if args.json:
            print(json.dumps({"error": "Source script is empty", "exit_code": EXIT_VALIDATION_ERROR}))
        else:
            print("Error: Source script cannot be empty", file=sys.stderr)
        return EXIT_VALIDATION_ERROR

    project_id = args.project_id or _slugify(script_path.stem)
    base_dir = Path(args.output_dir) if args.output_dir else Path("projects")
    project_dir = base_dir / project_id

    store = VoiceProjectStore(root_dir=base_dir)
    service = VoiceProjectService(store=store)

    try:
        state = service.create_project(
            script_text=script_text,
            project_id=project_id,
            title=project_id,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error creating project: {exc}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    if args.auto:
        # Run planning and resources automatically
        try:
            service.plan(project_id)
            res_check = service.check_resources(project_id)
            if res_check.render_blocked:
                if not args.json:
                    print(f"Created new project '{project_id}' at {project_dir}")
                return EXIT_RESOURCE_BLOCKED
        except Exception as exc:
            if args.json:
                print(json.dumps({"error": str(exc), "exit_code": EXIT_GENERIC_ERROR}))
            else:
                print(f"Error during auto plan/resource check: {exc}", file=sys.stderr)
            return EXIT_GENERIC_ERROR

    if args.json:
        print(json.dumps({
            "status": "success",
            "project_id": project_id,
            "project_dir": str(project_dir),
            "state": state.to_dict(),
        }, indent=2))
    else:
        print(f"Created new project '{project_id}' at {project_dir}")

    return EXIT_SUCCESS


def execute_plan(project_dir: Path) -> int:
    """Execute full planning pipeline for a project directory via VoiceProjectService."""
    project_dir = Path(project_dir)
    store = VoiceProjectStore(root_dir=project_dir.parent)
    service = VoiceProjectService(store=store)

    try:
        service.plan(project_dir.name)
        return EXIT_SUCCESS
    except Exception as exc:
        return EXIT_GENERIC_ERROR


def cmd_plan(args: argparse.Namespace) -> int:
    """CLI handler for voice plan."""
    target_path = Path(args.target)
    if target_path.is_file():
        # Standalone script file target
        with open(target_path, "r", encoding="utf-8") as f:
            raw_script = f.read()

        story_beats = analyze_story_beats(raw_script)
        segments = story_beats_to_narration_segments(story_beats)
        planned_segments = compile_narration_plan(segments)
        project_data = {
            "project": {"id": target_path.stem, "title": target_path.stem, "source_script": raw_script},
            "voice": {"profile": "mythology_narrator_male", "provider": "chatterbox-http", "model": "auto"},
            "global_direction": {"tone": "mysterious", "base_pace": 0.92, "dramatic_level": 3, "max_energy": 5.0, "avoid_overacting": True},
        }
        voice_plan = build_voice_plan(project_data, planned_segments)
        directed_plan = direct_sound(voice_plan)
        critique = critique_voice_plan(directed_plan)
        final_plan = apply_director_fixes(directed_plan, critique)

        out_file = Path(args.output) if args.output else target_path.parent / "voice-plan.yaml"
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(final_plan.to_yaml())

        if args.json:
            print(json.dumps({"status": "success", "plan_path": str(out_file), "beats_count": len(final_plan.beats)}, indent=2))
        else:
            print(f"Generated VoicePlan with {len(final_plan.beats)} beats at {out_file}")
        return EXIT_SUCCESS

    # Target is a project directory
    if not target_path.exists():
        if args.json:
            print(json.dumps({"error": f"Project directory '{target_path}' not found", "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: Project directory '{target_path}' not found", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    store = VoiceProjectStore(root_dir=target_path.parent)
    service = VoiceProjectService(store=store)

    try:
        plan_res = service.plan(target_path.name)
        if args.json:
            print(json.dumps({"status": "success", "project_dir": str(target_path), "plan": "voice-plan.yaml"}, indent=2))
        else:
            print(f"Successfully planned project at {target_path}")
        return EXIT_SUCCESS
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return EXIT_GENERIC_ERROR


def execute_resources(project_dir: Path) -> tuple[int, ResourceReport | None]:
    """Resolve resources for a project directory via VoiceProjectService."""
    project_dir = Path(project_dir)
    store = VoiceProjectStore(root_dir=project_dir.parent)
    service = VoiceProjectService(store=store)

    try:
        res_check = service.check_resources(project_dir.name)
        exit_code = EXIT_RESOURCE_BLOCKED if res_check.render_blocked else EXIT_SUCCESS
        return exit_code, res_check.report
    except Exception as exc:
        return EXIT_GENERIC_ERROR, None


def cmd_resources(args: argparse.Namespace) -> int:
    """CLI handler for voice resources."""
    project_dir = Path(args.project_dir)
    if not project_dir.exists():
        if args.json:
            print(json.dumps({"error": f"Project directory '{project_dir}' not found", "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: Project directory '{project_dir}' not found", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    store = VoiceProjectStore(root_dir=project_dir.parent)
    service = VoiceProjectService(store=store)

    try:
        res_check = service.check_resources(project_dir.name)
        report = res_check.report
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error checking resources: {exc}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    code = EXIT_RESOURCE_BLOCKED if res_check.render_blocked else EXIT_SUCCESS

    if args.json:
        print(json.dumps({
            "status": "blocked" if report.readiness.render_blocked else "ready",
            "readiness_score": report.readiness.score,
            "render_blocked": report.readiness.render_blocked,
            "block_reasons": report.readiness.block_reasons,
            "resolved_count": len(report.resolved),
            "substituted_count": len(report.substituted),
            "missing_count": len(report.missing),
            "pronunciation_overrides": report.pronunciation_overrides,
        }, indent=2))
    else:
        print(f"Resource Readiness: {report.readiness.score}%")
        print(f"Render Blocked: {'YES' if report.readiness.render_blocked else 'NO'}")
        if report.readiness.block_reasons:
            print("\nBlock Reasons:")
            for reason in report.readiness.block_reasons:
                print(f"  • {reason}")

    return code


def cmd_resources_missing(args: argparse.Namespace) -> int:
    """CLI handler for voice resources missing (read-only)."""
    project_dir = Path(args.project_dir)
    report_path = project_dir / "resource-report.yaml"
    if not report_path.exists():
        # Try resolving dynamically
        code, report = execute_resources(project_dir)
        if report is None:
            if args.json:
                print(json.dumps({"error": "No resource report found", "exit_code": EXIT_GENERIC_ERROR}))
            else:
                print("Error: No resource report found", file=sys.stderr)
            return EXIT_GENERIC_ERROR
    else:
        with open(report_path, "r", encoding="utf-8") as f:
            report = ResourceReport.from_dict(yaml.safe_load(f) or {})

    req_gaps = [g for g in report.missing if g.priority == RequirementPriority.REQUIRED]
    rec_gaps = [g for g in report.missing if g.priority == RequirementPriority.RECOMMENDED]
    opt_gaps = [g for g in report.missing if g.priority == RequirementPriority.OPTIONAL]

    if args.json:
        print(json.dumps({
            "required": [g.model_dump(mode="json") for g in req_gaps],
            "recommended": [g.model_dump(mode="json") for g in rec_gaps],
            "optional": [g.model_dump(mode="json") for g in opt_gaps],
        }, indent=2))
    else:
        print("=== REQUIRED GAPS ===")
        if not req_gaps:
            print("  (None)")
        for g in req_gaps:
            label = g.term if g.term else g.intent
            used_str = ", ".join(g.used_at) if g.used_at else "global"
            print(f"  • [{g.type.value.upper()}] {label} (Beats: {used_str})")

        print("\n=== RECOMMENDED GAPS ===")
        if not rec_gaps:
            print("  (None)")
        for g in rec_gaps:
            label = g.term if g.term else g.intent
            used_str = ", ".join(g.used_at) if g.used_at else "global"
            print(f"  • [{g.type.value.upper()}] {label} (Beats: {used_str})")

        print("\n=== OPTIONAL GAPS ===")
        if not opt_gaps:
            print("  (None)")
        for g in opt_gaps:
            label = g.term if g.term else g.intent
            used_str = ", ".join(g.used_at) if g.used_at else "global"
            print(f"  • [{g.type.value.upper()}] {label} (Beats: {used_str})")

    return EXIT_SUCCESS


def cmd_inspect(args: argparse.Namespace) -> int:
    """CLI handler for voice inspect (read-only)."""
    project_dir = Path(args.project_dir)
    if not project_dir.exists():
        if args.json:
            print(json.dumps({"error": f"Project directory '{project_dir}' not found", "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: Project directory '{project_dir}' not found", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    state_path = project_dir / "project.yaml"
    plan_path = project_dir / "voice-plan.yaml"
    report_path = project_dir / "resource-report.yaml"
    manifest_path = project_dir / "render-manifest.yaml"

    state = None
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            state = ProjectState.from_dict(yaml.safe_load(f) or {})

    plan = None
    if plan_path.exists():
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = VoicePlan.from_yaml(f.read())

    report = None
    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            report = ResourceReport.from_dict(yaml.safe_load(f) or {})

    render_manifest = None
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            render_manifest = yaml.safe_load(f) or {}

    summary = {
        "project_id": state.project_id if state else project_dir.name,
        "stage": state.stage.value if state else "UNKNOWN",
        "beats_count": len(plan.beats) if plan else 0,
        "readiness_score": report.readiness.score if report else None,
        "render_blocked": report.readiness.render_blocked if report else None,
        "required_gaps_count": len([g for g in report.missing if g.priority == RequirementPriority.REQUIRED]) if report else 0,
        "recommended_gaps_count": len([g for g in report.missing if g.priority == RequirementPriority.RECOMMENDED]) if report else 0,
        "renders_summary": {
            b_id: b_info.get("status") for b_id, b_info in render_manifest.get("beats", {}).items()
        } if render_manifest else {},
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"PROJECT: {summary['project_id']}")
        print(f"STAGE: {summary['stage']}")
        print(f"BEATS: {summary['beats_count']}")
        if summary['readiness_score'] is not None:
            print(f"RESOURCE READINESS: {summary['readiness_score']}%")
            print(f"BLOCKED: {'Yes' if summary['render_blocked'] else 'No'}")
            print(f"REQUIRED GAPS: {summary['required_gaps_count']}")
            print(f"RECOMMENDED GAPS: {summary['recommended_gaps_count']}")
        if summary['renders_summary']:
            print("\nRENDERS:")
            for bid, bstatus in summary['renders_summary'].items():
                print(f"  • {bid}: {bstatus}")

    return EXIT_SUCCESS


def cmd_assets_ingest(args: argparse.Namespace) -> int:
    """CLI handler for voice assets ingest."""
    file_path = Path(args.file_path)
    if not file_path.exists():
        if args.json:
            print(json.dumps({"error": f"File '{file_path}' not found", "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: File '{file_path}' not found", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    manifest = load_manifest()

    cat_map = {
        "ambience": ResourceCategory.AMBIENCE,
        "sfx": ResourceCategory.SFX,
        "voice": ResourceCategory.VOICE,
    }
    category = cat_map.get(args.category.lower(), ResourceCategory.SFX)

    intents = [args.intent] if args.intent else [file_path.stem]
    tags = args.tag if args.tag else []
    res_id = f"{category.value}_{_slugify(file_path.stem)}"

    metadata = IngestMetadata(
        resource_id=res_id,
        category=category,
        intents=intents,
        tags=tags,
        intensity=int(getattr(args, "intensity", 3) or 3),
        loopable=bool(getattr(args, "loopable", False)),
    )

    try:
        entry, updated_manifest = ingest_asset(
            file_path=file_path,
            metadata=metadata,
            manifest=manifest,
        )
        save_manifest(updated_manifest)
        if args.json:
            print(json.dumps({"status": "success", "entry": entry.model_dump(mode="json")}, indent=2))
        else:
            print(f"Successfully ingested asset '{entry.id}' ({category.value})")
        return EXIT_SUCCESS
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": EXIT_VALIDATION_ERROR}))
        else:
            print(f"Error ingesting asset: {exc}", file=sys.stderr)
        return EXIT_VALIDATION_ERROR


def cmd_doctor(args: argparse.Namespace) -> int:
    """CLI handler for voice doctor (read-only diagnostics)."""
    manifest = load_manifest()
    knowledge = load_pronunciation_knowledge()

    report = diagnose_resources(manifest=manifest, knowledge=knowledge)

    if args.json:
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print(f"Doctor Status: {'HEALTHY' if report.healthy else 'UNHEALTHY'}")
        if report.issues:
            print("\nIssues:")
            for iss in report.issues:
                print(f"  ❌ [{iss.component.upper()}] {iss.message}")
        if report.warnings:
            print("\nWarnings:")
            for w in report.warnings:
                print(f"  ⚠️ [{w.component.upper()}] {w.message}")

    return EXIT_SUCCESS if report.healthy else EXIT_VALIDATION_ERROR


def cmd_render(args: argparse.Namespace) -> int:
    """CLI handler for voice render."""
    project_dir = Path(args.project_dir)
    if not project_dir.exists():
        if args.json:
            print(json.dumps({"error": f"Project directory '{project_dir}' not found", "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: Project directory '{project_dir}' not found", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    store = VoiceProjectStore(root_dir=project_dir.parent)

    # Provider selection: canonical priority (chatterbox-http default, or explicit --provider / --fake)
    provider_name = getattr(args, "provider", None)
    if args.fake:
        provider_name = "fake"
    elif not provider_name:
        provider_name = "chatterbox-http"

    model_override = getattr(args, "model", None)
    voice_override = getattr(args, "voice", None)
    provider = create_tts_provider(provider_name=provider_name, model=model_override, voice=voice_override)

    service = VoiceProjectService(
        store=store,
        execution_port=provider,
        provider_name=provider_name,
    )

    try:
        # Preserve the legacy one-command render UX while keeping the service
        # lifecycle strict: PLANNED projects pass through resource checking.
        if store.get_project_state(project_dir.name).stage == ProjectStatus.PLANNED:
            service.check_resources(project_dir.name)
        render_res = service.render(
            project_id=project_dir.name,
            beats=args.beats,
            auto_qc=args.qc,
            force_rerender=getattr(args, "force_rerender", False) or getattr(args, "force", False),
            allow_resource_blocked=getattr(args, "force", False),
        )
    except ResourceBlockedError as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": EXIT_RESOURCE_BLOCKED}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return EXIT_RESOURCE_BLOCKED
    except ProviderUnavailableError as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": EXIT_PROVIDER_UNAVAILABLE}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return EXIT_PROVIDER_UNAVAILABLE
    except Exception as exc:
        if args.json:
            print(json.dumps({"error": str(exc), "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    manifest = render_res.manifest
    all_passed = manifest is not None and all(b.status == RenderStatus.PASSED for b in manifest.beats.values())
    if args.json:
        print(json.dumps({
            "status": "success" if all_passed else "completed_with_review",
            "manifest": manifest.to_dict() if manifest else {},
        }, indent=2))
    else:
        print(f"Render completed. Manifest updated with {len(manifest.beats) if manifest else 0} beats.")
        if manifest:
            for bid, bstate in manifest.beats.items():
                print(f"  • {bid}: {bstate.status.value} (selected attempt: {bstate.selected_attempt})")

    return EXIT_SUCCESS if all_passed else EXIT_QC_FAILED


def cmd_rerender(args: argparse.Namespace) -> int:
    """CLI handler for voice rerender."""
    args.force_rerender = True
    args.beats = args.beat_ids
    return cmd_render(args)


def cmd_qc(args: argparse.Namespace) -> int:
    """CLI handler for voice qc with persistence to manifest and project state."""
    project_dir = Path(args.project_dir)
    plan_path = project_dir / "voice-plan.yaml"
    manifest_path = project_dir / "render-manifest.yaml"
    report_path = project_dir / "resource-report.yaml"

    if not plan_path.exists() or not manifest_path.exists():
        if args.json:
            print(json.dumps({"error": "Plan or render manifest missing", "exit_code": EXIT_GENERIC_ERROR}))
        else:
            print("Error: Plan or render manifest missing. Run render first.", file=sys.stderr)
        return EXIT_GENERIC_ERROR

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = VoicePlan.from_yaml(f.read())

    manifest = load_render_manifest(project_dir)

    pron_overrides = {}
    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            report = ResourceReport.from_dict(yaml.safe_load(f) or {})
            pron_overrides = report.pronunciation_overrides

    target_beats = [b for b in plan.beats if not args.beat_ids or b.id in args.beat_ids]
    qc_results = {}

    qc_dir = project_dir / "qc"
    qc_dir.mkdir(parents=True, exist_ok=True)

    for beat in target_beats:
        bstate = manifest.get_or_create_beat(beat.id)
        if not bstate.attempts:
            continue
        latest_attempt = bstate.attempts[-1]
        if not latest_attempt.audio_path or not Path(latest_attempt.audio_path).exists():
            continue

        qc_res = evaluate_beat_qc(
            beat=beat,
            audio_path=latest_attempt.audio_path,
            attempt_id=latest_attempt.attempt,
            pronunciation_overrides=pron_overrides,
        )
        latest_attempt.qc_result = qc_res
        qc_results[beat.id] = qc_res.to_dict()

        # Update attempt & beat status
        if qc_res.verdict == QCVerdict.PASS:
            latest_attempt.status = RenderStatus.PASSED
            bstate.status = RenderStatus.PASSED
            bstate.selected_attempt = latest_attempt.attempt
        elif qc_res.verdict == QCVerdict.NEEDS_REVIEW:
            latest_attempt.status = RenderStatus.NEEDS_REVIEW
            bstate.status = RenderStatus.NEEDS_REVIEW
            bstate.selected_attempt = latest_attempt.attempt
        elif qc_res.verdict == QCVerdict.RETRY:
            latest_attempt.status = RenderStatus.QC_FAILED
            bstate.status = RenderStatus.QC_FAILED
        else:
            latest_attempt.status = RenderStatus.FAILED
            bstate.status = RenderStatus.FAILED

        # Persist attempt JSON
        beat_render_dir = project_dir / "renders" / beat.id
        if beat_render_dir.exists():
            meta_path = beat_render_dir / f"attempt_{latest_attempt.attempt:02d}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(latest_attempt.model_dump(mode="json"), f, indent=2, ensure_ascii=False)

        # Persist QC artifact JSON
        beat_qc_dir = qc_dir / beat.id
        beat_qc_dir.mkdir(parents=True, exist_ok=True)
        qc_meta_path = beat_qc_dir / f"attempt_{latest_attempt.attempt:02d}.json"
        with open(qc_meta_path, "w", encoding="utf-8") as f:
            json.dump(qc_res.to_dict(), f, indent=2, ensure_ascii=False)

    # Persist updated render manifest to disk
    from services.voice_renderer import save_render_manifest
    save_render_manifest(manifest, project_dir)

    # Persist updated project.yaml state
    state_path = project_dir / "project.yaml"
    all_passed = all(b.status == RenderStatus.PASSED for b in manifest.beats.values())
    any_needs_review = any(b.status == RenderStatus.NEEDS_REVIEW for b in manifest.beats.values())
    any_failed = any(b.status == RenderStatus.FAILED for b in manifest.beats.values())

    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            state = ProjectState.from_dict(yaml.safe_load(f) or {})
        if all_passed and len(manifest.beats) == len(plan.beats):
            state.stage = ProjectStatus.NARRATION_READY
            state.status.narration_ready = True
        elif any_needs_review:
            state.stage = ProjectStatus.REVIEW_REQUIRED
            state.status.narration_ready = False
        elif any_failed:
            state.stage = ProjectStatus.FAILED
            state.status.narration_ready = False
        with open(state_path, "w", encoding="utf-8") as f:
            f.write(state.to_yaml())

    if args.json:
        print(json.dumps({"status": "passed" if all_passed else "review_required", "qc_results": qc_results}, indent=2))
    else:
        for bid, q in qc_results.items():
            print(f"Beat {bid} -> Verdict: {q['verdict'].upper()} (Score: {q['qc_score']})")

    return EXIT_SUCCESS if all_passed else EXIT_QC_FAILED


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI command parser."""
    parser = argparse.ArgumentParser(
        prog="voice",
        description="Chatterbox Voice Director CLI Orchestrator (Phases 7-9)",
    )
    subparsers = parser.add_subparsers(dest="command", help="Voice Director commands")

    # voice new
    p_new = subparsers.add_parser("new", help="Create new project workspace from script")
    p_new.add_argument("script_path", help="Path to input text script")
    p_new.add_argument("--project-id", help="Optional custom project ID")
    p_new.add_argument("--auto", action="store_true", help="Auto-run planning and resource resolution")
    p_new.add_argument("--output-dir", help="Base directory for project workspaces (default: projects/)")
    p_new.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect project state and artifacts (read-only)")
    p_inspect.add_argument("project_dir", help="Path to project directory")
    p_inspect.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice plan
    p_plan = subparsers.add_parser("plan", help="Execute planning pipeline to build VoicePlan")
    p_plan.add_argument("target", help="Project directory or standalone script file")
    p_plan.add_argument("--output", help="Custom output path for voice-plan.yaml")
    p_plan.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice resources
    p_res = subparsers.add_parser("resources", help="Check and resolve project resources")
    p_res.add_argument("project_dir", help="Path to project directory")
    p_res.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice resources missing
    p_res_missing = subparsers.add_parser("resources_missing", help="List missing resource gaps (read-only)")
    p_res_missing.add_argument("project_dir", help="Path to project directory")
    p_res_missing.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice assets ingest
    p_ingest = subparsers.add_parser("assets_ingest", help="Ingest audio asset into library manifest")
    p_ingest.add_argument("file_path", help="Path to raw audio file")
    p_ingest.add_argument("--category", default="sfx", choices=["ambience", "sfx", "voice"], help="Asset category")
    p_ingest.add_argument("--intent", help="Primary sound intent")
    p_ingest.add_argument("--tag", action="append", help="Descriptive tag (repeatable)")
    p_ingest.add_argument("--intensity", type=int, default=3, help="Intensity rating 1-5")
    p_ingest.add_argument("--loopable", action="store_true", help="Whether audio is loopable")
    p_ingest.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice doctor
    p_doc = subparsers.add_parser("doctor", help="Run system and asset library diagnostics (read-only)")
    p_doc.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice render
    p_render = subparsers.add_parser("render", help="Render narration beats using TTS provider")
    p_render.add_argument("project_dir", help="Path to project directory")
    p_render.add_argument("--provider", choices=["chatterbox-http", "gemini", "fake"], help="TTS execution provider (default: chatterbox-http)")
    p_render.add_argument("--qc", action="store_true", default=True, help="Auto-run Voice QC after rendering")
    p_render.add_argument("--beats", nargs="+", help="Render only specific beat IDs")
    p_render.add_argument("--fake", action="store_true", help="Force use of FakeTTSProvider")
    p_render.add_argument("--model", help="Override TTS model name (e.g., nano, turbo, gemini-3.1-flash-tts-preview)")
    p_render.add_argument("--voice", help="Override TTS voice name (e.g., Kore, Aoede)")
    p_render.add_argument("--force", action="store_true", help="Force render even if resource report is blocked")
    p_render.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice rerender
    p_rerender = subparsers.add_parser("rerender", help="Selectively rerender specific story beats")
    p_rerender.add_argument("project_dir", help="Path to project directory")
    p_rerender.add_argument("beat_ids", nargs="+", help="One or more beat IDs to rerender")
    p_rerender.add_argument("--provider", choices=["chatterbox-http", "gemini", "fake"], help="TTS execution provider (default: chatterbox-http)")
    p_rerender.add_argument("--qc", action="store_true", default=True, help="Auto-run Voice QC after rendering")
    p_rerender.add_argument("--fake", action="store_true", help="Force use of FakeTTSProvider")
    p_rerender.add_argument("--model", help="Override TTS model name (e.g., nano, turbo, gemini-3.1-flash-tts-preview)")
    p_rerender.add_argument("--voice", help="Override TTS voice name (e.g., Kore, Aoede)")
    p_rerender.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # voice qc
    p_qc = subparsers.add_parser("qc", help="Run Voice Quality Control on rendered audio")
    p_qc.add_argument("project_dir", help="Path to project directory")
    p_qc.add_argument("beat_ids", nargs="*", help="Optional specific beat IDs to evaluate")
    p_qc.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    return parser


def main(args_list: list[str] | None = None) -> int:
    """Main CLI entrypoint function."""
    parser = build_parser()

    # Handle multi-word commands like `voice resources missing` or `voice assets ingest`
    if args_list is None:
        args_list = sys.argv[1:]

    normalized_args = list(args_list)
    if len(normalized_args) >= 2:
        if normalized_args[0] == "resources" and normalized_args[1] == "missing":
            normalized_args = ["resources_missing"] + normalized_args[2:]
        elif normalized_args[0] == "assets" and normalized_args[1] == "ingest":
            normalized_args = ["assets_ingest"] + normalized_args[2:]

    if not normalized_args:
        parser.print_help()
        return EXIT_GENERIC_ERROR

    args = parser.parse_args(normalized_args)

    if args.command == "new":
        return cmd_new(args)
    elif args.command == "inspect":
        return cmd_inspect(args)
    elif args.command == "plan":
        return cmd_plan(args)
    elif args.command == "resources":
        return cmd_resources(args)
    elif args.command == "resources_missing":
        return cmd_resources_missing(args)
    elif args.command == "assets_ingest":
        return cmd_assets_ingest(args)
    elif args.command == "doctor":
        return cmd_doctor(args)
    elif args.command == "render":
        return cmd_render(args)
    elif args.command == "rerender":
        return cmd_rerender(args)
    elif args.command == "qc":
        return cmd_qc(args)
    else:
        parser.print_help()
        return EXIT_GENERIC_ERROR


if __name__ == "__main__":
    sys.exit(main())
