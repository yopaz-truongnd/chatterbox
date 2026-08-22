"""Audio Projects Planning, Requirements Gathering & Multi-Stage Confirmation Service.

Enforces the Two-Gate Lifecycle for English Voice Production:
  Gate 1: Requirements Gathering & Confirmation (collecting_requirements -> awaiting_requirements_confirmation)
  Gate 2: English Script Planning & Confirmation (planning_script -> awaiting_script_confirmation -> approved)
  Orchestration: Semantic Segmentation -> Real Batch Multi-Line Job Submission -> JobManager Synchronization & Signal Auto-Fix -> Completed
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import torch
import torchaudio as ta

from services.audio import (
    load_and_resample_audio,
    merge_speech_segments,
    normalize_loudness,
    save_audio_wav,
)
from services.event_bus import event_bus
from services.exceptions import (
    ProjectNotApprovedError,
    ProjectNotFoundError,
    ProjectStateError,
    ValidationError,
)

logger = logging.getLogger("chatterbox.project_planner")

ProjectStatus = Literal[
    "draft",
    "collecting_requirements",
    "awaiting_answers",
    "awaiting_requirements_confirmation",
    "planning_script",
    "awaiting_script_confirmation",
    "segmenting",
    "rendering_draft",
    "evaluating",
    "revising",
    "rendering_final",
    "completed",
    "completed_partial",
    "needs_revision",
    "failed",
    "cancelled",
    "approved",
    "rendering",
]

PROJECT_FORMATS = {
    "podcast": "Podcast",
    "video_narration": "Video narration / Voiceover",
    "audiobook": "Audiobook / Story",
    "advertisement": "Commercial / Ad",
}

DEFAULT_AUDIENCES = {
    "beginner": "Beginner / Introductory",
    "general": "General Audience",
    "expert": "Expert / In-depth",
    "kids": "Kids / Children",
}

DEFAULT_SFX_LEVELS = {
    "none": "None (Dry Voice only)",
    "light": "Light (Subtle background ambient music & gentle SFX)",
    "cinematic": "Cinematic (Rich sound design & scoring)",
}


def _get_projects_dir() -> Path:
    """Return persistent storage directory for projects."""
    data_dir = Path(os.getenv("CHATTERBOX_API_DATA_DIR", str(Path(__file__).resolve().parent.parent / "tmp" / "api")))
    proj_dir = data_dir / "projects"
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir


def _load_project_file(project_id: str) -> dict[str, Any]:
    """Load project JSON from disk."""
    proj_file = _get_projects_dir() / f"{project_id}.json"
    if not proj_file.exists():
        raise ProjectNotFoundError(f"Project with ID '{project_id}' does not exist.")
    try:
        return json.loads(proj_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"Cannot read project file for '{project_id}': {exc}")


def _save_project_file(project: dict[str, Any]) -> None:
    """Save project JSON to disk with atomic replacement."""
    proj_id = project["id"]
    proj_file = _get_projects_dir() / f"{proj_id}.json"
    part_file = proj_file.with_suffix(".json.part")
    project["updated_at"] = datetime.now(timezone.utc).isoformat()
    part_file.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    part_file.replace(proj_file)


# ==============================================================================
# Gate 1 & 2 Pure Helpers (Delegated to modular services)
# ==============================================================================
from services.project_requirements import (
    analyze_missing_fields,
    apply_sensible_defaults,
    extract_requirements_from_text,
    generate_question_batch,
)
from services.project_script import (
    generate_english_outline_and_script,
    segment_script_text,
)


# ==============================================================================
# Character & Voice Resolution
# ==============================================================================

def resolve_character_and_voice(
    character_id: str | None,
    quality_preset: str | None = None,
) -> tuple[str, str | None, str | None, dict[str, Any]]:
    """Resolve character ID, audio reference file path, and preset model configurations.
    
    Returns (resolved_model, character_id, audio_prompt_path, voice_profile).
    """
    preset = quality_preset or "balanced"
    if preset == "fast":
        model = "nano"
    elif preset == "expressive":
        model = "standard"
    else:
        model = "turbo"

    voice_profile: dict[str, Any] = {
        "expressiveness": 0.5,
        "pace": 0.5,
        "stability": 0.7,
        "temperature": 0.8,
    }
    audio_prompt_path = None
    resolved_char_id = None

    if character_id:
        data_dir = Path(os.getenv("CHATTERBOX_API_DATA_DIR", str(Path(__file__).resolve().parent.parent / "tmp" / "api")))
        char_file = data_dir / "characters.json"
        if char_file.exists():
            try:
                char_data = json.loads(char_file.read_text(encoding="utf-8"))
                for c in char_data:
                    if isinstance(c, dict) and c.get("id") == character_id:
                        resolved_char_id = c.get("id")
                        if c.get("voice"):
                            voice_profile.update(c["voice"])
                        ref_wav = data_dir / "characters" / f"{resolved_char_id}.wav"
                        if ref_wav.exists():
                            audio_prompt_path = str(ref_wav)
                        break
            except Exception as exc:
                logger.warning(f"Could not load character config '{character_id}': {exc}")

    return model, resolved_char_id, audio_prompt_path, voice_profile


# ==============================================================================
# Job & Project Lifecycle Synchronization
# ==============================================================================

def sync_project_with_job(project: dict[str, Any], job_manager: Any) -> bool:
    """Synchronize project rendering status, individual segment audio URLs, evaluation, and SRT with JobManager."""
    if not job_manager or not project.get("final_job_id"):
        return False

    final_job_id = project["final_job_id"]
    job = job_manager.get_job(final_job_id) if hasattr(job_manager, "get_job") else None
    if not job:
        return False

    updated = False
    if job.status in ("completed", "completed_partial") and project.get("status") not in ("completed", "completed_partial"):
        project["status"] = job.status
        project["audio_url"] = f"/api/v1/jobs/{job.id}/audio"
        project["srt_url"] = f"/api/v1/jobs/{job.id}/srt"

        lines_results = job.benchmark.get("lines_results", []) if job.benchmark else []
        idx_map = {r.get("idx", i): r for i, r in enumerate(lines_results)}
        segments = project.get("segments", [])

        # Sync individual segment data from job benchmark
        for idx, seg in enumerate(segments):
            line_data = idx_map.get(idx)
            if line_data:
                line_status = line_data.get("status", "failed")
                seg["status"] = line_status
                seg["duration_seconds"] = line_data.get("duration_seconds")
                seg["start_seconds"] = line_data.get("start_seconds")
                seg["end_seconds"] = line_data.get("end_seconds")
                seg["evaluation"] = line_data.get("quality", {}).get("final", {"passed": (line_status == "completed"), "duration_seconds": seg.get("duration_seconds", 0.0)})
                
                if line_status == "completed":
                    seg_audio_url = f"/api/v1/jobs/{job.id}/lines/{idx}"
                    seg["audio_url"] = seg_audio_url
                    seg["selected_attempt"] = {
                        "attempt_id": 1,
                        "status": "completed",
                        "audio_url": seg_audio_url,
                        "evaluation": seg["evaluation"],
                    }
                else:
                    seg["audio_url"] = None
                    seg["error"] = line_data.get("error")
                    seg["selected_attempt"] = {
                        "attempt_id": 1,
                        "status": "failed",
                        "audio_url": None,
                        "evaluation": seg["evaluation"],
                        "error": line_data.get("error"),
                    }
            else:
                seg["status"] = "failed"
                seg["audio_url"] = None
                seg["evaluation"] = {"passed": False, "duration_seconds": 0.0}
                seg["selected_attempt"] = {
                    "attempt_id": 1,
                    "status": "failed",
                    "audio_url": None,
                    "evaluation": seg["evaluation"],
                }

        # Project quality summary report
        if job.benchmark and job.benchmark.get("quality_report"):
            project["quality_report"] = job.benchmark["quality_report"]
        else:
            total_dur = float(job.duration_seconds) if isinstance(getattr(job, "duration_seconds", None), (int, float)) else sum(float(s.get("duration_seconds", 0.0) or 0.0) for s in segments)
            project["quality_report"] = {
                "total_segments": len(segments),
                "passed_segments": len([s for s in segments if s.get("status") == "completed" and s.get("evaluation", {}).get("passed", True)]),
                "completed_segments": len([s for s in segments if s.get("status") == "completed"]),
                "audio_duration_seconds": round(total_dur, 3),
                "passed": (len([s for s in segments if s.get("status") != "completed"]) == 0),
            }

        updated = True

    elif job.status in ("failed", "cancelled") and project.get("status") not in ("failed", "cancelled"):
        project["status"] = "failed"
        project["error"] = str(job.error or f"Job terminated with status '{job.status}'")
        for seg in project.get("segments", []):
            seg["status"] = "failed"
            seg["audio_url"] = None
        updated = True

    if updated:
        _save_project_file(project)

    return updated


# ==============================================================================
# Summary Formatter
# ==============================================================================

def format_project_summary(project: dict[str, Any]) -> str:
    """Generate structured Markdown summary of the project state across both confirmation gates."""
    topic = project.get("topic", "Untitled")
    reqs = project.get("requirements", {})
    status = project.get("status", "draft")

    fmt_label = PROJECT_FORMATS.get(reqs.get("content_format", ""), reqs.get("content_format") or "Unspecified")
    dur_sec = reqs.get("target_duration_seconds")
    dur_str = f"~{dur_sec // 60} mins ({dur_sec}s)" if dur_sec else "Unspecified"
    aud_label = DEFAULT_AUDIENCES.get(reqs.get("audience", ""), reqs.get("audience") or "Unspecified")
    tone_str = reqs.get("tone") or "Engaging storytelling"
    char_str = reqs.get("character_id") or "Auto-selected optimal English narrator"
    sfx_label = DEFAULT_SFX_LEVELS.get(reqs.get("sfx_level", ""), reqs.get("sfx_level") or "Light BGM")
    out_fmts = ", ".join([f.upper() for f in reqs.get("output_formats", ["WAV", "SRT"])])

    lines = [
        f"### 📋 Audio Project Plan: **{topic}**",
        f"* **Format**: {fmt_label}",
        f"* **Target Duration**: {dur_str}",
        f"* **Audience**: {aud_label}",
        f"* **Language**: English (`en`)",
        f"* **Tone & Style**: {tone_str}",
        f"* **Voice**: `{char_str}`",
        f"* **Audio Production / SFX**: {sfx_label}",
        f"* **Outputs**: {out_fmts}",
    ]

    outline = project.get("outline", [])
    if outline:
        lines.append("\n#### 📑 Scene Outline:")
        for item in outline:
            lines.append(f"- **[{item.get('scene_id', '').upper()}] {item.get('title', '')}** (Mood: `{item.get('emotion', 'engaging')}`)")

    script_obj = project.get("script")
    if script_obj and isinstance(script_obj, dict) and script_obj.get("full_text"):
        lines.append(f"\n#### 📜 English Script (~{script_obj.get('word_count', 0)} words, ~{script_obj.get('estimated_duration_seconds', 0)}s):")
        preview = script_obj["full_text"][:350] + ("..." if len(script_obj["full_text"]) > 350 else "")
        lines.append(f"```text\n{preview}\n```")

    if status == "awaiting_requirements_confirmation":
        lines.extend([
            "\n---",
            "❓ **Gate 1: Confirm Requirements**: Please confirm these requirements to proceed to English outline & script drafting.",
            "*(Call `chatterbox_confirm_requirements` or reply 'Confirm' to proceed)*",
        ])
    elif status == "awaiting_script_confirmation":
        lines.extend([
            "\n---",
            "❓ **Gate 2: Confirm English Script**: Review the generated script and scene outline above.",
            "*(Call `chatterbox_confirm_script` to approve the script, or provide custom script edits)*",
        ])
    elif status in ("approved", "completed"):
        lines.extend([
            "\n---",
            f"✅ **Project Status: `{status.upper()}`** — Ready for full high-level rendering orchestration with `chatterbox_render_project`.",
        ])

    return "\n".join(lines)


# ==============================================================================
# Public Service API Methods
# ==============================================================================

def prepare_project(
    topic: str,
    initial_requirements: dict[str, Any] | None = None,
    auto_defaults: bool = False,
) -> dict[str, Any]:
    """Initialize a structured audio project in English."""
    if not topic or not topic.strip():
        raise ValidationError("Project 'topic' cannot be empty.")

    cleaned_topic = topic.strip()
    proj_id = f"proj_{uuid.uuid4().hex[:12]}"

    extracted = extract_requirements_from_text(cleaned_topic)
    merged_reqs = {**extracted}
    if initial_requirements:
        merged_reqs.update(initial_requirements)

    if auto_defaults:
        merged_reqs = apply_sensible_defaults(merged_reqs, topic=cleaned_topic)

    missing_req, missing_rec = analyze_missing_fields(merged_reqs, auto_defaults=auto_defaults)

    status: ProjectStatus = (
        "awaiting_requirements_confirmation" if (not missing_req and not missing_rec)
        else "awaiting_answers"
    )

    from services.narration_planner import scan_pronunciation_candidates

    questions = generate_question_batch(missing_req, missing_rec)
    pron_candidates = scan_pronunciation_candidates(cleaned_topic)

    project_data = {
        "id": proj_id,
        "topic": cleaned_topic,
        "status": status,
        "requirements": merged_reqs,
        "missing_required": missing_req,
        "missing_recommended": missing_rec,
        "pronunciation_dict": {},
        "pronunciation_candidates": pron_candidates,
        "outline": [],
        "script": {},
        "voice_plan": {
            "default_model": "turbo",
            "quality_preset": "balanced",
            "character_id": merged_reqs.get("character_id"),
        },
        "segments": [],
        "jobs": [],
        "final_job_id": None,
        "audio_url": None,
        "srt_url": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    _save_project_file(project_data)

    if status == "awaiting_answers":
        event_bus.emit(
            event_type="questions_required",
            project_id=proj_id,
            status="awaiting_answers",
            data={"missing_required": missing_req, "question_count": len(questions)},
        )
    else:
        event_bus.emit(
            event_type="requirements_ready",
            project_id=proj_id,
            status="awaiting_requirements_confirmation",
        )

    return {
        "project_id": proj_id,
        "status": status,
        "topic": cleaned_topic,
        "requirements": merged_reqs,
        "questions": questions,
        "summary": format_project_summary(project_data),
    }


def answer_project_questions(
    project_id: str,
    answers: dict[str, Any] | str,
    auto_defaults: bool = False,
) -> dict[str, Any]:
    """Submit answers to missing project requirements."""
    project = _load_project_file(project_id)
    current_status = project.get("status")

    if current_status in ("approved", "completed", "rendering_final", "rendering"):
        raise ProjectStateError(f"Project '{project_id}' is already at '{current_status}'. Cannot modify requirements.")

    new_reqs = dict(project.get("requirements", {}))

    if isinstance(answers, str):
        extracted = extract_requirements_from_text(answers)
        new_reqs.update(extracted)
    elif isinstance(answers, dict):
        for k, v in answers.items():
            if k == "content_format" and v:
                new_reqs["content_format"] = str(v).lower()
            elif k in ("target_duration", "target_duration_seconds", "duration") and v:
                if isinstance(v, (int, float)):
                    new_reqs["target_duration_seconds"] = int(v)
                else:
                    ext = extract_requirements_from_text(str(v))
                    if "target_duration_seconds" in ext:
                        new_reqs["target_duration_seconds"] = ext["target_duration_seconds"]
                    else:
                        try:
                            new_reqs["target_duration_seconds"] = int(str(v).strip().split()[0]) * 60
                        except Exception:
                            new_reqs["target_duration_seconds"] = 300
            elif k == "audience" and v:
                new_reqs["audience"] = str(v).lower()
            elif k == "character_id" and v:
                new_reqs["character_id"] = str(v)
            elif k == "sfx_level" and v:
                new_reqs["sfx_level"] = str(v).lower()
            elif k == "output_formats" and v:
                new_reqs["output_formats"] = v if isinstance(v, list) else [v]
            elif k in ("tone", "pace", "quality_preset"):
                new_reqs[k] = v

    if auto_defaults or "default" in str(answers).lower():
        new_reqs = apply_sensible_defaults(new_reqs, topic=project.get("topic", ""))

    missing_req, missing_rec = analyze_missing_fields(new_reqs, auto_defaults=auto_defaults)

    if not missing_req:
        new_reqs = apply_sensible_defaults(new_reqs, topic=project.get("topic", ""))
        status: ProjectStatus = "awaiting_requirements_confirmation"
        missing_rec = []
    else:
        status = "awaiting_answers"

    project["requirements"] = new_reqs
    project["status"] = status
    project["missing_required"] = missing_req
    project["missing_recommended"] = missing_rec

    _save_project_file(project)
    questions = generate_question_batch(missing_req, missing_rec)

    if status == "awaiting_answers":
        event_bus.emit(
            event_type="questions_required",
            project_id=project_id,
            status="awaiting_answers",
            data={"missing_required": missing_req, "question_count": len(questions)},
        )
    else:
        event_bus.emit(
            event_type="requirements_ready",
            project_id=project_id,
            status="awaiting_requirements_confirmation",
        )

    return {
        "project_id": project_id,
        "status": status,
        "requirements": new_reqs,
        "questions": questions,
        "summary": format_project_summary(project),
    }


def confirm_requirements(project_id: str, confirmed: bool = True) -> dict[str, Any]:
    """Gate 1 Confirmation: Strictly confirm requirements before advancing to script planning."""
    project = _load_project_file(project_id)
    current_status = project.get("status")

    if not confirmed:
        project["status"] = "cancelled"
        _save_project_file(project)
        event_bus.emit(
            event_type="cancelled",
            project_id=project_id,
            status="cancelled",
        )
        return {
            "project_id": project_id,
            "status": "cancelled",
            "message": "❌ Project cancelled by user request.",
            "summary": format_project_summary(project),
        }

    if current_status not in ("awaiting_requirements_confirmation", "awaiting_answers", "collecting_requirements"):
        if current_status in ("awaiting_script_confirmation", "approved", "completed"):
            return {
                "project_id": project_id,
                "status": current_status,
                "message": "Requirements have already been confirmed.",
                "summary": format_project_summary(project),
            }
        raise ProjectStateError(f"Cannot confirm requirements for project at status '{current_status}'.")

    missing_req, _ = analyze_missing_fields(project.get("requirements", {}), auto_defaults=True)
    if missing_req:
        raise ValidationError(f"Cannot confirm requirements: missing required fields: {missing_req}")

    project["requirements"] = apply_sensible_defaults(project.get("requirements", {}), topic=project.get("topic", ""))

    # Auto-generate English script & outline to advance to Gate 2
    outline, script_obj = generate_english_outline_and_script(
        topic=project.get("topic", ""),
        requirements=project["requirements"],
    )
    from services.narration_planner import scan_pronunciation_candidates

    project["outline"] = outline
    project["script"] = script_obj
    project["pronunciation_candidates"] = scan_pronunciation_candidates(script_obj.get("full_text", ""))
    project["status"] = "awaiting_script_confirmation"

    _save_project_file(project)

    event_bus.emit(
        event_type="script_ready",
        project_id=project_id,
        status="awaiting_script_confirmation",
        data={"scene_count": len(outline), "word_count": script_obj.get("word_count", 0)},
    )

    return {
        "project_id": project_id,
        "status": "awaiting_script_confirmation",
        "message": "✅ Requirements confirmed! English outline and script have been drafted for your review (Gate 2).",
        "outline": outline,
        "script": script_obj,
        "pronunciation_candidates": project["pronunciation_candidates"],
        "summary": format_project_summary(project),
    }


def generate_script(
    project_id: str,
    custom_prompt: str | None = None,
    num_scenes: int | None = None,
    script_text: str | None = None,
) -> dict[str, Any]:
    """Generate, edit, or author the English outline and script. Enforces Gate 1 requirement."""
    project = _load_project_file(project_id)
    status = project.get("status")

    # Strict Gate 1 check: block execution if at awaiting_requirements_confirmation or earlier
    if status not in ("awaiting_script_confirmation", "planning_script", "needs_revision"):
        raise ProjectStateError(
            f"Cannot generate or update script when project status is '{status}'. "
            "Gate 1 requirements must be confirmed before planning or editing the script (call 'confirm_requirements' first)."
        )

    outline, script_obj = generate_english_outline_and_script(
        topic=project.get("topic", ""),
        requirements=project.get("requirements", {}),
        custom_prompt=custom_prompt,
        script_text=script_text,
    )
    from services.narration_planner import scan_pronunciation_candidates

    project["outline"] = outline
    project["script"] = script_obj
    project["pronunciation_candidates"] = scan_pronunciation_candidates(script_obj.get("full_text", ""))
    project["status"] = "awaiting_script_confirmation"
    _save_project_file(project)

    event_bus.emit(
        event_type="script_ready",
        project_id=project_id,
        status="awaiting_script_confirmation",
        data={"scene_count": len(outline), "word_count": script_obj.get("word_count", 0)},
    )

    return {
        "project_id": project_id,
        "status": "awaiting_script_confirmation",
        "outline": outline,
        "script": script_obj,
        "pronunciation_candidates": project["pronunciation_candidates"],
        "summary": format_project_summary(project),
    }


def confirm_script(
    project_id: str,
    confirmed: bool = True,
    script_text: str | None = None,
    pronunciation_dict: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Gate 2 Confirmation: Strictly review and approve the English script. Rejects unconfirmed requirements."""
    project = _load_project_file(project_id)
    status = project.get("status")

    if status != "awaiting_script_confirmation":
        raise ProjectStateError(
            f"Cannot confirm script for project at status '{status}'. "
            "Gate 1 requirements must be confirmed before reviewing the script (expected status: 'awaiting_script_confirmation')."
        )

    if not confirmed:
        project["status"] = "needs_revision"
        _save_project_file(project)
        event_bus.emit(
            event_type="needs_revision",
            project_id=project_id,
            status="needs_revision",
        )
        return {
            "project_id": project_id,
            "status": "needs_revision",
            "message": "Script revision requested. Please provide updated script text or instructions.",
            "summary": format_project_summary(project),
        }

    # Update script if user supplied edits
    if script_text and script_text.strip():
        txt = script_text.strip()
        words = len(txt.split())
        project["script"]["full_text"] = txt
        project["script"]["word_count"] = words
        project["script"]["estimated_duration_seconds"] = round((words / 135) * 60, 1)

    if pronunciation_dict:
        curr_dict = project.get("pronunciation_dict", {})
        curr_dict.update(pronunciation_dict)
        project["pronunciation_dict"] = curr_dict

    full_text = project.get("script", {}).get("full_text", "").strip()
    if not full_text:
        raise ValidationError("Cannot approve project without a valid script. Please author or generate a script first.")

    # Segment and pre-compile narration plan
    segments = segment_script_text(
        full_text,
        target_pace=project.get("requirements", {}).get("pace", "medium"),
        default_model=project.get("voice_plan", {}).get("default_model", "turbo"),
        format_type=project.get("requirements", {}).get("content_format", "podcast"),
        pronunciation_dict=project.get("pronunciation_dict", {}),
    )
    project["segments"] = segments
    project["status"] = "approved"
    _save_project_file(project)

    event_bus.emit(
        event_type="approved",
        project_id=project_id,
        status="approved",
        data={"word_count": project["script"].get("word_count", 0), "segment_count": len(segments)},
    )

    return {
        "project_id": project_id,
        "status": "approved",
        "message": "✅ English script and scene outline approved! Ready for high-level rendering orchestration.",
        "segment_count": len(segments),
        "segments": segments,
        "summary": format_project_summary(project),
    }


def update_project_pronunciation(
    project_id: str,
    pronunciation_dict: dict[str, str],
) -> dict[str, Any]:
    """Update project-level pronunciation dictionary (e.g., {'NASA': 'N.A.S.A.'})."""
    project = _load_project_file(project_id)
    curr_dict = project.get("pronunciation_dict", {})
    curr_dict.update(pronunciation_dict)
    project["pronunciation_dict"] = curr_dict

    # If segments exist, re-compile narration plan with updated dictionary
    if project.get("segments") and project.get("script", {}).get("full_text"):
        project["segments"] = segment_script_text(
            project["script"]["full_text"],
            target_pace=project.get("requirements", {}).get("pace", "medium"),
            default_model=project.get("voice_plan", {}).get("default_model", "turbo"),
            format_type=project.get("requirements", {}).get("content_format", "podcast"),
            pronunciation_dict=project["pronunciation_dict"],
        )

    _save_project_file(project)
    return {
        "project_id": project_id,
        "pronunciation_dict": project["pronunciation_dict"],
        "status": project.get("status"),
    }


def confirm_project(project_id: str, confirmed: bool = True) -> dict[str, Any]:
    """Unified confirmation dispatcher supporting both confirmation gates."""
    project = _load_project_file(project_id)
    status = project.get("status")

    if status in ("awaiting_requirements_confirmation", "awaiting_answers", "collecting_requirements"):
        return confirm_requirements(project_id, confirmed=confirmed)
    elif status in ("awaiting_script_confirmation", "planning_script", "needs_revision"):
        return confirm_script(project_id, confirmed=confirmed)
    elif status == "approved":
        return {
            "project_id": project_id,
            "status": "approved",
            "message": "Project is already approved.",
            "summary": format_project_summary(project),
        }
    raise ProjectStateError(f"Cannot confirm project at status '{status}'.")


# ==============================================================================
# High-Level Orchestration: Render Project via Multi-Segment Batch Submission
# ==============================================================================

def render_project(
    project_id: str,
    script_text: str | None = None,
    character_id: str | None = None,
    quality_preset: str | None = None,
    job_manager: Any = None,
) -> dict[str, Any]:
    """Execute speech synthesis and audio rendering for an approved project.
    
    Submits real multi-line batch job to JobManager, preventing duplicate jobs.
    """
    project = _load_project_file(project_id)
    status = project.get("status")
    topic = project.get("topic", "Audio Project")

    # Prevent Duplicate Render Jobs if already running
    if status in ("rendering", "rendering_draft", "rendering_final") and project.get("final_job_id"):
        return {
            "project_id": project_id,
            "status": status,
            "job_id": project["final_job_id"],
            "final_job_id": project["final_job_id"],
            "topic": topic,
            "segment_count": len(project.get("segments", [])),
            "segments": project.get("segments", []),
            "script_text": project.get("script", {}).get("full_text", ""),
            "message": f"Dự án đang trong tiến trình Render với Job ID: `{project['final_job_id']}` (không tạo tác vụ trùng lặp).",
        }

    # Strict Gate Enforcement
    if status != "approved":
        raise ProjectNotApprovedError(
            f"Project '{project_id}' is not approved (current status: '{status}'). "
            "Backend rejects rendering! Please complete both Gate 1 (Requirements) and Gate 2 (Script) confirmation before rendering."
        )

    if job_manager is None or not getattr(job_manager, "_running", False):
        raise ProjectStateError("JobManager is not active or API is offline. Cannot submit audio render job.")

    reqs = project.get("requirements", {})

    # Use approved script or override
    final_script = script_text or project.get("script", {}).get("full_text")
    if not final_script:
        _, script_obj = generate_english_outline_and_script(topic, reqs)
        final_script = script_obj["full_text"]
        project["script"] = script_obj

    selected_char = character_id or reqs.get("character_id")
    selected_preset = quality_preset or reqs.get("quality_preset", "balanced")

    # Resolve model, character reference audio, and voice profile
    resolved_model, resolved_char_id, resolved_audio_path, resolved_voice = resolve_character_and_voice(
        character_id=selected_char,
        quality_preset=selected_preset,
    )

    # Step 1: Semantic Segmentation with Narration Planning
    project["status"] = "segmenting"
    pron_dict = project.get("pronunciation_dict", {})
    segments = segment_script_text(
        final_script,
        target_pace=reqs.get("pace", "medium"),
        default_model=resolved_model,
        format_type=reqs.get("content_format", "podcast"),
        pronunciation_dict=pron_dict,
    )
    project["segments"] = segments

    # Step 2: Build Batch Lines for BatchRunner
    batch_lines = []
    for idx, seg in enumerate(segments):
        line_item = {
            "idx": idx,
            "id": seg["id"],
            "text": seg["text"],
            "speaker": seg.get("speaker", "Narrator"),
            "pause_duration": float(seg.get("pause_after_ms", 500)) / 1000.0,
            "model": resolved_model,
            "character_id": resolved_char_id,
            "audio_prompt_path": resolved_audio_path,
            "narration_plan": seg.get("narration_plan", {}),
            **resolved_voice,
        }
        batch_lines.append(line_item)

    # Step 3: Submit Real Batch Job to JobManager
    batch_params = {
        "lines": batch_lines,
        "model": resolved_model,
        "project_id": project_id,
        "quality_preset": selected_preset,
        "character_id": resolved_char_id,
        "export_srt": True,
        "normalize_loudness": True,
        "crossfade_ms": 30,
        "topic": topic,
    }

    try:
        job = job_manager.submit_job(job_type="batch", params=batch_params, input_paths=[])
        job_id = job.id
    except Exception as exc:
        project["status"] = "failed"
        project["error"] = f"Failed to queue batch render job: {exc}"
        _save_project_file(project)
        raise ProjectStateError(f"Could not submit render job: {exc}")

    project["final_job_id"] = job_id
    project["jobs"].append(job_id)
    project["status"] = "rendering"
    _save_project_file(project)

    event_bus.emit(
        event_type="render_started",
        project_id=project_id,
        job_id=job_id,
        status="rendering",
        progress=0,
        data={"segment_count": len(segments), "model": resolved_model},
    )

    return {
        "project_id": project_id,
        "status": "rendering",
        "job_id": job_id,
        "final_job_id": job_id,
        "topic": topic,
        "segment_count": len(segments),
        "segments": segments,
        "script_text": final_script,
        "message": f"🎙️ Initiated multi-segment audio production for project '{topic}' ({len(segments)} segments) with Job ID: `{job_id}`.",
    }


def get_project(project_id: str, job_manager: Any = None) -> dict[str, Any]:
    """Retrieve full project state, synchronizing with JobManager if active."""
    project = _load_project_file(project_id)
    if job_manager:
        sync_project_with_job(project, job_manager)
    return {
        **project,
        "summary": format_project_summary(project),
    }


def list_projects(job_manager: Any = None) -> list[dict[str, Any]]:
    """List all saved projects with live synchronization."""
    proj_dir = _get_projects_dir()
    projects = []
    for f in sorted(proj_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            pdata = json.loads(f.read_text(encoding="utf-8"))
            if job_manager:
                sync_project_with_job(pdata, job_manager)
            projects.append(pdata)
        except Exception:
            continue
    return projects
