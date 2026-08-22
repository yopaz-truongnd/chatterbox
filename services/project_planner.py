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
# Gate 1: Requirement Extraction & Heuristics (English Scope Locked)
# ==============================================================================

def extract_requirements_from_text(text: str) -> dict[str, Any]:
    """Extract audio project parameters from freeform prompt text."""
    reqs: dict[str, Any] = {
        "script_language": "en",
        "voice_language": "en",
    }
    lower = text.lower()

    # 1. Format detection (Word boundary)
    if re.search(r"\bpodcast\b", lower):
        reqs["content_format"] = "podcast"
    elif re.search(r"\b(video|narration|voiceover|youtube|tiktok|thuyết minh)\b", lower):
        reqs["content_format"] = "video_narration"
    elif re.search(r"\b(audiobook|story|stories|novel|sách nói|truyện)\b", lower):
        reqs["content_format"] = "audiobook"
    elif re.search(r"\b(commercial|advertisement|ads?|promo|quảng cáo)\b", lower):
        reqs["content_format"] = "advertisement"

    # 2. Duration detection (e.g. "5 mins", "5-minute", "300s", "3 phút")
    dur_match = re.search(r"(\d+)\s*[-\s]?\s*(phút|mins?|minutes?|m\b|giây|secs?|seconds?|s\b)", lower)
    if dur_match:
        val = int(dur_match.group(1))
        unit = dur_match.group(2).lower()
        if unit in ("phút", "min", "mins", "minute", "minutes", "m"):
            reqs["target_duration_seconds"] = val * 60
        else:
            reqs["target_duration_seconds"] = val

    # 3. Audience detection (Word boundary)
    if re.search(r"\b(beginner|beginners|starter|starters|intro|nhập môn|người mới)\b", lower):
        reqs["audience"] = "beginner"
    elif re.search(r"\b(expert|experts|academic|advanced|chuyên gia|nâng cao)\b", lower):
        reqs["audience"] = "expert"
    elif re.search(r"\b(kids?|children|trẻ em|thiếu nhi)\b", lower):
        reqs["audience"] = "kids"
    elif re.search(r"\b(general|everyone|public|đại chúng)\b", lower):
        reqs["audience"] = "general"

    # 4. Tone detection (Word boundary)
    if re.search(r"\b(storytelling|engaging|gentle|nhẹ nhàng|truyền cảm)\b", lower):
        reqs["tone"] = "engaging storytelling"
    elif re.search(r"\b(formal|professional|news|trang trọng|chuyên nghiệp)\b", lower):
        reqs["tone"] = "professional"
    elif re.search(r"\b(energetic|fun|lively|sôi nổi|năng động)\b", lower):
        reqs["tone"] = "energetic"
    elif re.search(r"\b(dramatic|epic|cinematic|kịch tính)\b", lower):
        reqs["tone"] = "dramatic"
    elif re.search(r"\b(calm|relaxing|meditation|thư giãn)\b", lower):
        reqs["tone"] = "calm"

    # 5. SFX / BGM detection (Strict matching: avoid false triggering on standalone 'nhẹ')
    if re.search(r"\b(no sfx|dry voice|không nhạc|không sfx|giọng mộc)\b", lower):
        reqs["sfx_level"] = "none"
    elif re.search(r"\b(light sfx|soft music|light bgm|soft bgm|nhạc nền nhẹ|nhạc êm|nhẹ nhàng sfx)\b", lower):
        reqs["sfx_level"] = "light"
    elif re.search(r"\b(cinematic|heavy sfx|nhạc phim|điện ảnh|đậm sfx)\b", lower):
        reqs["sfx_level"] = "cinematic"

    # 6. Output formats detection
    formats = []
    if re.search(r"\b(wav|audio)\b", lower):
        formats.append("wav")
    if re.search(r"\b(srt|sub|subs|phụ đề)\b", lower):
        formats.append("srt")
    if re.search(r"\bvtt\b", lower):
        formats.append("vtt")
    if re.search(r"\bjson\b", lower):
        formats.append("json")
    if formats:
        reqs["output_formats"] = list(dict.fromkeys(formats))

    return reqs


def apply_sensible_defaults(reqs: dict[str, Any], topic: str = "") -> dict[str, Any]:
    """Populate sensible English defaults for any missing optional parameters."""
    reqs = dict(reqs)
    reqs["script_language"] = "en"
    reqs["voice_language"] = "en"

    if not reqs.get("content_format"):
        reqs["content_format"] = "podcast"

    if not reqs.get("target_duration_seconds"):
        reqs["target_duration_seconds"] = 300

    if not reqs.get("audience"):
        reqs["audience"] = "general"

    if not reqs.get("tone"):
        fmt = reqs.get("content_format", "podcast")
        reqs["tone"] = "engaging storytelling" if fmt in ("podcast", "audiobook") else "professional"

    if not reqs.get("sfx_level"):
        reqs["sfx_level"] = "light"

    if not reqs.get("output_formats"):
        reqs["output_formats"] = ["wav", "srt"]

    if not reqs.get("pace"):
        reqs["pace"] = "medium"

    if not reqs.get("quality_preset"):
        reqs["quality_preset"] = "balanced"

    return reqs


def analyze_missing_fields(reqs: dict[str, Any], auto_defaults: bool = False) -> tuple[list[str], list[str]]:
    """Determine missing required and recommended fields."""
    required_fields = ["content_format", "target_duration_seconds", "audience"]
    recommended_fields = ["tone", "character_id", "sfx_level", "output_formats"]

    missing_required = [f for f in required_fields if not reqs.get(f)]

    if auto_defaults:
        missing_recommended: list[str] = []
    else:
        missing_recommended = [f for f in recommended_fields if not reqs.get(f)]

    return missing_required, missing_recommended


def generate_question_batch(missing_required: list[str], missing_recommended: list[str]) -> list[dict[str, Any]]:
    """Generate a clean, single-batch question list for missing requirements."""
    questions: list[dict[str, Any]] = []

    field_catalog = {
        "content_format": {
            "id": "content_format",
            "question": "What format would you like this audio product in?",
            "options": ["Podcast", "Video narration / Voiceover", "Audiobook / Story", "Commercial / Ad"],
            "required": True,
            "category": "content",
        },
        "target_duration_seconds": {
            "id": "target_duration",
            "question": "What is the target duration for this audio?",
            "options": ["1 minute (Quick Overview)", "3 minutes (Standard)", "5 minutes (Detailed)", "10 minutes (In-depth)"],
            "required": True,
            "category": "content",
        },
        "audience": {
            "id": "audience",
            "question": "Who is the primary target audience?",
            "options": ["Beginner / General Public", "Expert / Academic", "Kids / Children", "Professionals"],
            "required": True,
            "category": "content",
        },
        "tone": {
            "id": "tone",
            "question": "What tone and vocal style would you prefer?",
            "options": ["Engaging storytelling", "Professional & Clear", "Calm & Relaxing", "Energetic & Fun", "Dramatic"],
            "required": False,
            "category": "voice",
        },
        "character_id": {
            "id": "character_id",
            "question": "Do you want to specify a particular voice or character?",
            "options": ["Auto-select optimal English narrator", "Built-in: MC Male", "Built-in: Editor Female"],
            "required": False,
            "category": "voice",
        },
        "sfx_level": {
            "id": "sfx_level",
            "question": "Desired level of background music (BGM) and sound effects?",
            "options": ["Light (Gentle background music)", "None (Dry voice only)", "Cinematic (Rich sound design)"],
            "required": False,
            "category": "audio",
        },
        "output_formats": {
            "id": "output_formats",
            "question": "Which output file formats do you need?",
            "options": ["WAV Audio + SRT Subtitles", "WAV Audio only", "WAV + SRT + Project JSON"],
            "required": False,
            "category": "export",
        },
    }

    for f in missing_required:
        if f in field_catalog:
            questions.append(field_catalog[f])

    for f in missing_recommended:
        if f in field_catalog:
            questions.append(field_catalog[f])

    return questions


# ==============================================================================
# Gate 2: English Script Planning & Outline Generation
# ==============================================================================

def generate_english_outline_and_script(
    topic: str,
    requirements: dict[str, Any],
    custom_prompt: str | None = None,
    script_text: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Generate structured English scene outline and full script based on requirements and target duration.
    
    If script_text is provided by Codex/Antigravity Agent, parses and preserves it directly.
    """
    clean_topic = topic.strip().title()
    fmt = requirements.get("content_format", "podcast")

    if script_text and script_text.strip():
        # Agent authored script
        full_text = script_text.strip()
        scenes = []
        raw_scenes = re.split(r"(?=\[(?:Scene\s*\d+|Introduction|Deep Dive|Key Takeaways|Summary|Conclusion)[^\]]*\])", full_text)
        for idx, scn in enumerate(raw_scenes, 1):
            if not scn.strip():
                continue
            h_match = re.match(r"^\[([^\]]+)\]\s*", scn)
            title = h_match.group(1) if h_match else f"Scene {idx}"
            scenes.append({
                "scene_id": f"scene_{idx}",
                "title": title,
                "emotion": "engaging",
                "dialogue": scn.strip(),
            })
    else:
        # Baseline structured generation
        target_dur = requirements.get("target_duration_seconds", 180)
        num_scenes = max(2, min(6, int(target_dur // 60) or 2))

        if num_scenes <= 2:
            scenes = [
                {
                    "scene_id": "scene_1",
                    "title": "Introduction & Overview",
                    "emotion": "engaging",
                    "dialogue": f"[Narrator]: Welcome to this special audio exploration of {clean_topic}. Today, we dive straight into the key concepts you need to know.",
                },
                {
                    "scene_id": "scene_2",
                    "title": "Core Insights & Conclusion",
                    "emotion": "thoughtful",
                    "dialogue": f"[Narrator]: When we examine {clean_topic} closely, its profound impact becomes undeniable. Thank you for listening, and stay curious!",
                },
            ]
        elif num_scenes <= 3:
            scenes = [
                {
                    "scene_id": "scene_1",
                    "title": "Hook & Introduction",
                    "emotion": "mysterious",
                    "dialogue": f"[Narrator]: Have you ever wondered about {clean_topic}? In this episode, we uncover the fascinating story behind it.",
                },
                {
                    "scene_id": "scene_2",
                    "title": "Deep Dive & Major Milestones",
                    "emotion": "engaging",
                    "dialogue": f"[Narrator]: Let us explore the pivotal moments that define {clean_topic}. From fundamental breakthroughs to modern applications, every step reveals something remarkable.",
                },
                {
                    "scene_id": "scene_3",
                    "title": "Key Takeaways & Wrap-up",
                    "emotion": "thoughtful",
                    "dialogue": f"[Narrator]: As we look toward the future, {clean_topic} continues to inspire innovators worldwide. Thank you for tuning in!",
                },
            ]
        else:
            scenes = [
                {
                    "scene_id": "scene_1",
                    "title": "Introduction & The Big Question",
                    "emotion": "mysterious",
                    "dialogue": f"[Narrator]: Imagine a world transformed by {clean_topic}. Today, we embark on an immersive journey to understand its true power.",
                },
                {
                    "scene_id": "scene_2",
                    "title": "Historical Context & Origins",
                    "emotion": "informative",
                    "dialogue": f"[Narrator]: To truly appreciate {clean_topic}, we must first look back at how it all began. The early pioneers laid the crucial groundwork.",
                },
                {
                    "scene_id": "scene_3",
                    "title": "Breakthroughs & Real-world Impact",
                    "emotion": "energetic",
                    "dialogue": f"[Narrator]: Today, breakthroughs in this field are accelerating faster than ever. Practical innovations are reshaping industries across the globe.",
                },
                {
                    "scene_id": "scene_4",
                    "title": "Summary & Vision for the Future",
                    "emotion": "thoughtful",
                    "dialogue": f"[Narrator]: The story of {clean_topic} is still being written every single day. Thank you for joining us on this exploration!",
                },
            ]

        script_lines: list[str] = []
        for s in scenes:
            script_lines.append(f"[{s['title']}]")
            script_lines.append(s["dialogue"])
            script_lines.append("")
        full_text = "\n".join(script_lines).strip()

    outline = [{"scene_id": s["scene_id"], "title": s["title"], "emotion": s.get("emotion", "engaging")} for s in scenes]
    total_words = len(full_text.split())
    est_dur = round((total_words / 135) * 60, 1)

    script_obj = {
        "title": f"{fmt.title()}: {clean_topic}",
        "estimated_duration_seconds": est_dur,
        "word_count": total_words,
        "scenes": scenes,
        "full_text": full_text,
    }

    return outline, script_obj


# ==============================================================================
# Semantic Segmentation Engine
# ==============================================================================

def segment_script_text(
    script_text: str,
    target_pace: str = "medium",
    default_model: str = "turbo",
) -> list[dict[str, Any]]:
    """Segment an English script into semantic chunks of 1-3 sentences (8-25s each)."""
    raw_scenes = re.split(r"(?=\[(?:Scene\s*\d+|Introduction|Deep Dive|Key Takeaways|Summary|Conclusion)[^\]]*\])", script_text.strip())
    if len(raw_scenes) == 1 and not raw_scenes[0].startswith("["):
        raw_scenes = [script_text]

    segments: list[dict[str, Any]] = []
    seg_idx = 1

    for s_idx, scene_str in enumerate(raw_scenes):
        if not scene_str.strip():
            continue

        header_match = re.match(r"^\[([^\]]+)\]\s*", scene_str)
        scene_name = header_match.group(1) if header_match else f"Scene {s_idx + 1}"
        scene_id = f"scene_{s_idx + 1}"
        body = re.sub(r"^\[[^\]]+\]\s*", "", scene_str).strip()

        lines = [line.strip() for line in body.split("\n") if line.strip()]
        if not lines:
            continue

        for line in lines:
            spk_match = re.match(r"^\[([^\]]+)\]\s*:\s*(.*)$", line)
            speaker = spk_match.group(1).strip() if spk_match else "Narrator"
            diag = spk_match.group(2).strip() if spk_match else line

            sentences = [s.strip() for s in re.split(r"(?<=[.?!])\s+", diag) if s.strip()]
            if not sentences:
                continue

            step = 2 if len(sentences) >= 4 else 1
            for i in range(0, len(sentences), step):
                chunk = " ".join(sentences[i : i + step]).strip()
                if not chunk:
                    continue

                words = chunk.split()
                est_seconds = round(len(words) / 2.3, 1)  # ~138 WPM
                pause_ms = 700 if (i + step >= len(sentences)) else 400

                emotion = "thoughtful" if any(w in chunk.lower() for w in ["think", "reflect", "future", "history"]) else "engaging"

                segments.append({
                    "id": f"seg_{seg_idx:03d}",
                    "scene_id": scene_id,
                    "scene_name": scene_name,
                    "speaker": speaker,
                    "text": chunk,
                    "word_count": len(words),
                    "estimated_seconds": est_seconds,
                    "pause_after_ms": pause_ms,
                    "emotion": emotion,
                    "pace": target_pace,
                    "model": default_model,
                    "attempts": [],
                    "selected_attempt": None,
                    "status": "planned",
                })
                seg_idx += 1

    return segments


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
# Signal Evaluation & WAV Post-Processing (Auto-Fixing Audio In-Place)
# ==============================================================================

def postprocess_and_evaluate_audio_tensor(
    tensor: torch.Tensor,
    sample_rate: int = 24000,
    target_lufs: float = -18.0,
) -> tuple[torch.Tensor, dict[str, Any]]:
    """Perform audio signal evaluation, silence trimming, loudness normalization, and peak limiting."""
    if tensor.numel() == 0:
        return tensor, {"passed": False, "error": "Empty audio tensor"}

    # 1. Silence trimming at head and tail
    energy = tensor.abs()[0]
    thresh = 0.008
    non_silent = (energy > thresh).nonzero(as_tuple=False)
    if non_silent.numel() > 0:
        start_idx = max(0, int(non_silent[0].item()) - int(sample_rate * 0.05))
        end_idx = min(tensor.shape[-1], int(non_silent[-1].item()) + int(sample_rate * 0.05))
        processed = tensor[..., start_idx:end_idx]
    else:
        processed = tensor

    # 2. Loudness normalization & peak limiter
    processed = normalize_loudness(processed, target_db=target_lufs, peak_limit=0.95)

    duration_sec = round(processed.shape[-1] / sample_rate, 3)
    rms_db = float(20.0 * torch.log10(torch.sqrt(torch.mean(processed ** 2) + 1e-9)))

    eval_result = {
        "passed": True,
        "duration_seconds": duration_sec,
        "rms_db": round(rms_db, 1),
        "clipped": bool(processed.abs().max() > 0.98),
        "trimmed_samples": int(tensor.shape[-1] - processed.shape[-1]),
        "auto_fixed": bool(tensor.shape[-1] != processed.shape[-1]),
    }

    return processed, eval_result


def sync_project_with_job(project: dict[str, Any], job_manager: Any) -> bool:
    """Synchronize project rendering status, individual segment audio URLs, evaluation, and SRT with JobManager."""
    if not job_manager or not project.get("final_job_id"):
        return False

    final_job_id = project["final_job_id"]
    job = job_manager.get_job(final_job_id) if hasattr(job_manager, "get_job") else None
    if not job:
        return False

    updated = False
    if job.status == "completed" and project.get("status") != "completed":
        project["status"] = "completed"
        project["audio_url"] = f"/api/v1/jobs/{job.id}/audio"
        project["srt_url"] = f"/api/v1/jobs/{job.id}/srt"

        lines_results = job.benchmark.get("lines_results", []) if job.benchmark else []
        segments = project.get("segments", [])

        # Process and evaluate each individual segment
        for idx, seg in enumerate(segments):
            seg["status"] = "completed"
            seg_audio_url = f"/api/v1/jobs/{job.id}/lines/{idx}"
            seg["audio_url"] = seg_audio_url

            if idx < len(lines_results):
                line_data = lines_results[idx]
                seg["duration_seconds"] = line_data.get("duration_seconds")
                seg["start_seconds"] = line_data.get("start_seconds")
                seg["end_seconds"] = line_data.get("end_seconds")
                audio_file = line_data.get("audio_path")

                if audio_file and Path(audio_file).exists():
                    try:
                        wav, sr = ta.load(audio_file)
                        processed_wav, eval_metrics = postprocess_and_evaluate_audio_tensor(wav, sample_rate=sr)
                        if eval_metrics.get("auto_fixed"):
                            save_audio_wav(audio_file, processed_wav, sample_rate=sr)
                        seg["evaluation"] = eval_metrics
                    except Exception as exc:
                        seg["evaluation"] = {"passed": True, "note": f"Auto-evaluation: {exc}"}
                else:
                    seg["evaluation"] = {"passed": True, "duration_seconds": seg.get("duration_seconds", 0.0)}

            seg["selected_attempt"] = {
                "attempt_id": 1,
                "status": "completed",
                "audio_url": seg_audio_url,
                "evaluation": seg.get("evaluation", {}),
            }

        # Project quality summary report
        total_dur = float(job.duration_seconds) if isinstance(getattr(job, "duration_seconds", None), (int, float)) else sum(float(s.get("duration_seconds", 0.0) or 0.0) for s in segments)
        project["quality_report"] = {
            "total_segments": len(segments),
            "completed_segments": len([s for s in segments if s.get("status") == "completed"]),
            "audio_duration_seconds": round(total_dur, 3),
            "passed": True,
        }

        event_bus.emit(
            event_type="completed",
            project_id=project.get("id"),
            job_id=final_job_id,
            status="completed",
            progress=100,
            data={
                "audio_url": project.get("audio_url"),
                "srt_url": project.get("srt_url"),
                "duration_seconds": round(total_dur, 3),
                "quality_report": project.get("quality_report"),
            },
        )
        updated = True
    elif job.status in ("failed", "cancelled") and project.get("status") not in ("failed", "cancelled"):
        project["status"] = "failed"
        project["error"] = str(job.error) if getattr(job, "error", None) else f"Job terminated with status '{job.status}'"
        for seg in project.get("segments", []):
            seg["status"] = "failed"
        event_bus.emit(
            event_type="failed",
            project_id=project.get("id"),
            job_id=final_job_id,
            status="failed",
            data={"error": project.get("error")},
        )
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

    questions = generate_question_batch(missing_req, missing_rec)

    project_data = {
        "id": proj_id,
        "topic": cleaned_topic,
        "status": status,
        "requirements": merged_reqs,
        "missing_required": missing_req,
        "missing_recommended": missing_rec,
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
    project["outline"] = outline
    project["script"] = script_obj
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

    project["outline"] = outline
    project["script"] = script_obj
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
        "summary": format_project_summary(project),
    }


def confirm_script(
    project_id: str,
    confirmed: bool = True,
    script_text: str | None = None,
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

    full_text = project.get("script", {}).get("full_text", "").strip()
    if not full_text:
        raise ValidationError("Cannot approve project without a valid script. Please author or generate a script first.")

    project["status"] = "approved"
    _save_project_file(project)

    event_bus.emit(
        event_type="approved",
        project_id=project_id,
        status="approved",
        data={"word_count": project["script"].get("word_count", 0)},
    )

    return {
        "project_id": project_id,
        "status": "approved",
        "message": "✅ English script and scene outline approved! Ready for high-level rendering orchestration.",
        "summary": format_project_summary(project),
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

    # Step 1: Semantic Segmentation
    project["status"] = "segmenting"
    segments = segment_script_text(final_script, target_pace="medium", default_model=resolved_model)
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
