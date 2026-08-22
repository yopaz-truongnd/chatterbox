"""Project Planning & Requirements Gathering Service for Chatterbox Audio Productions.

Enforces a two-stage confirmation state machine:
  1. Awaiting Answers (Gather missing requirements in a single batch turn)
  2. Awaiting Confirmation (Review final plan summary before any synthesis is permitted)
  3. Approved (Strict prerequisite for rendering/generation)
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from services.exceptions import (
    ProjectNotApprovedError,
    ProjectNotFoundError,
    ProjectStateError,
    ValidationError,
)

ProjectStatus = Literal[
    "draft",
    "collecting_requirements",
    "awaiting_answers",
    "awaiting_confirmation",
    "approved",
    "scripting",
    "rendering",
    "reviewing",
    "completed",
    "cancelled",
]

PROJECT_FORMATS = {
    "podcast": "Podcast",
    "video_narration": "Video narration / Thuyết minh",
    "audiobook": "Audiobook / Sách nói",
    "advertisement": "Quảng cáo / Commercial",
}

DEFAULT_AUDIENCES = {
    "beginner": "Người mới bắt đầu (Beginner)",
    "general": "Khán giả đại chúng (General Audience)",
    "expert": "Chuyên gia / Học thuật (Expert)",
    "kids": "Trẻ em / Thiếu nhi (Kids)",
}

DEFAULT_SFX_LEVELS = {
    "none": "Không (Chỉ có giọng mộc)",
    "light": "Nhẹ (Nhạc nền êm dịu, ít SFX)",
    "cinematic": "Điện ảnh (Đậm hiệu ứng SFX & nhạc phim)",
}


def _get_projects_dir() -> Path:
    """Return persistent storage directory for projects."""
    data_dir = Path(os.getenv("CHATTERBOX_API_DATA_DIR", str(Path(__file__).resolve().parent.parent / "tmp" / "api")))
    proj_dir = data_dir / "projects"
    proj_dir.mkdir(parents=True, exist_ok=True)
    return proj_dir


def _load_project_file(project_id: str) -> dict:
    """Load project JSON from disk."""
    proj_file = _get_projects_dir() / f"{project_id}.json"
    if not proj_file.exists():
        raise ProjectNotFoundError(f"Dự án với ID '{project_id}' không tồn tại.")
    try:
        return json.loads(proj_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValidationError(f"Không thể đọc dữ liệu dự án '{project_id}': {exc}")


def _save_project_file(project: dict) -> None:
    """Save project JSON to disk with atomic write."""
    proj_id = project["id"]
    proj_file = _get_projects_dir() / f"{proj_id}.json"
    part_file = proj_file.with_suffix(".json.part")
    project["updated_at"] = datetime.now(timezone.utc).isoformat()
    part_file.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")
    part_file.replace(proj_file)


def extract_requirements_from_text(text: str) -> dict[str, Any]:
    """Heuristic extraction of audio project parameters from freeform text."""
    reqs: dict[str, Any] = {}
    lower = text.lower()

    # 1. Format detection
    if "podcast" in lower:
        reqs["content_format"] = "podcast"
    elif any(k in lower for k in ["video", "narration", "thuyết minh", "lồng tiếng", "youtube", "tiktok"]):
        reqs["content_format"] = "video_narration"
    elif any(k in lower for k in ["audiobook", "sách nói", "đọc sách", "truyện", "tiểu thuyết"]):
        reqs["content_format"] = "audiobook"
    elif any(k in lower for k in ["quảng cáo", "commercial", "ads", "promo"]):
        reqs["content_format"] = "advertisement"

    # 2. Duration detection (e.g., "5 phút", "10 mins", "300s")
    dur_match = re.search(r"(\d+)\s*(phút|mins?|m\b|giây|seconds?|s\b)", lower)
    if dur_match:
        val = int(dur_match.group(1))
        unit = dur_match.group(2)
        if unit in ("phút", "min", "mins", "m"):
            reqs["target_duration_seconds"] = val * 60
        else:
            reqs["target_duration_seconds"] = val

    # 3. Audience detection
    if any(k in lower for k in ["người mới", "beginner", "nhập môn", "tìm hiểu", "cơ bản"]):
        reqs["audience"] = "beginner"
    elif any(k in lower for k in ["chuyên gia", "expert", "chuyên sâu", "nâng cao", "học thuật"]):
        reqs["audience"] = "expert"
    elif any(k in lower for k in ["trẻ em", "kids", "thiếu nhi", "bé"]):
        reqs["audience"] = "kids"
    elif any(k in lower for k in ["đại chúng", "mọi người", "general", "phổ thông"]):
        reqs["audience"] = "general"

    # 4. Language detection
    if any(k in lower for k in ["tiếng việt", "vietnamese", "vi"]):
        reqs["language"] = "vi"
    elif any(k in lower for k in ["tiếng anh", "english", "en"]):
        reqs["language"] = "en"

    # 5. Tone / Style detection
    if any(k in lower for k in ["nhẹ nhàng", "truyền cảm", "kể chuyện", "gentle", "storytelling"]):
        reqs["tone"] = "gentle storytelling"
    elif any(k in lower for k in ["chuyên nghiệp", "trang trọng", "tin tức", "formal", "professional"]):
        reqs["tone"] = "professional"
    elif any(k in lower for k in ["năng động", "sôi nổi", "hài hước", "energetic", "fun"]):
        reqs["tone"] = "energetic"
    elif any(k in lower for k in ["kịch tính", "hấp dẫn", "dramatic", "epic", "điện ảnh"]):
        reqs["tone"] = "dramatic"

    # 6. SFX / BGM detection
    if any(k in lower for k in ["không cần nhạc", "giọng mộc", "không nhạc", "no sfx"]):
        reqs["sfx_level"] = "none"
    elif any(k in lower for k in ["nhạc nền nhẹ", "nhẹ", "light sfx", "ít sound effect", "nhạc êm"]):
        reqs["sfx_level"] = "light"
    elif any(k in lower for k in ["điện ảnh", "nhiều sfx", "cinematic", "đậm chất"]):
        reqs["sfx_level"] = "cinematic"

    # 7. Output formats detection
    formats = []
    if "wav" in lower or "audio" in lower:
        formats.append("wav")
    if "srt" in lower or "phụ đề" in lower or "sub" in lower:
        formats.append("srt")
    if "vtt" in lower:
        formats.append("vtt")
    if "json" in lower or "project" in lower:
        formats.append("json")
    if formats:
        reqs["output_formats"] = list(dict.fromkeys(formats))

    return reqs


def apply_sensible_defaults(reqs: dict[str, Any], topic: str = "") -> dict[str, Any]:
    """Populate sensible defaults for recommended/optional parameters."""
    reqs = dict(reqs)
    if not reqs.get("language"):
        # Detect if topic has Vietnamese characters
        has_vi = bool(re.search(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", topic.lower()))
        reqs["language"] = "vi" if has_vi else "en"

    if not reqs.get("tone"):
        fmt = reqs.get("content_format", "podcast")
        reqs["tone"] = "gentle storytelling" if fmt in ("podcast", "audiobook") else "professional"

    if not reqs.get("sfx_level"):
        reqs["sfx_level"] = "light"

    if not reqs.get("output_formats"):
        reqs["output_formats"] = ["wav", "srt"]

    if not reqs.get("pace"):
        reqs["pace"] = "medium"

    if not reqs.get("quality_preset"):
        reqs["quality_preset"] = "balanced"

    if not reqs.get("target_lufs"):
        reqs["target_lufs"] = -18.0

    return reqs


def analyze_missing_fields(reqs: dict[str, Any], auto_defaults: bool = False) -> tuple[list[str], list[str]]:
    """Determine missing required and recommended fields."""
    required_fields = ["content_format", "target_duration_seconds", "audience"]
    recommended_fields = ["character_id", "sfx_level", "output_formats"]

    missing_required = [f for f in required_fields if not reqs.get(f)]

    if auto_defaults:
        missing_recommended: list[str] = []
    else:
        missing_recommended = [f for f in recommended_fields if not reqs.get(f)]

    return missing_required, missing_recommended


def generate_question_batch(missing_required: list[str], missing_recommended: list[str]) -> list[dict[str, Any]]:
    """Generate a clean, single-batch question list for the missing requirements."""
    questions: list[dict[str, Any]] = []

    field_catalog = {
        "content_format": {
            "id": "content_format",
            "question": "Bạn muốn sản phẩm theo định dạng nào?",
            "options": ["Podcast", "Video narration / Thuyết minh", "Audiobook / Sách nói", "Quảng cáo / Commercial"],
            "required": True,
            "category": "content",
        },
        "target_duration_seconds": {
            "id": "target_duration",
            "question": "Thời lượng mục tiêu của sản phẩm là bao nhiêu?",
            "options": ["1 phút (Ngắn gọn)", "3 phút (Tiêu chuẩn)", "5 phút (Chi tiết)", "10 phút (Chuyên sâu)"],
            "required": True,
            "category": "content",
        },
        "audience": {
            "id": "audience",
            "question": "Đối tượng người nghe chính là ai?",
            "options": ["Người mới bắt đầu (Beginner)", "Khán giả đại chúng", "Chuyên gia / Học thuật", "Trẻ em / Thiếu nhi"],
            "required": True,
            "category": "content",
        },
        "character_id": {
            "id": "character_id",
            "question": "Bạn muốn chỉ định nhân vật/giọng đọc cụ thể nào không?",
            "options": ["Tự động chọn giọng đọc tối ưu theo chủ đề", "Giọng nam truyền cảm", "Giọng nữ nhẹ nhàng"],
            "required": False,
            "category": "voice",
        },
        "sfx_level": {
            "id": "sfx_level",
            "question": "Mức độ âm thanh & nhạc nền hậu kỳ mong muốn?",
            "options": ["Nhẹ (Nhạc nền êm dịu, ít SFX)", "Không (Chỉ có giọng nói mộc)", "Điện ảnh (Đậm hiệu ứng SFX)"],
            "required": False,
            "category": "audio",
        },
        "output_formats": {
            "id": "output_formats",
            "question": "Định dạng tệp đầu ra bạn muốn xuất?",
            "options": ["WAV + Phụ đề SRT", "Chỉ xuất file âm thanh WAV", "WAV + SRT + Project JSON"],
            "required": False,
            "category": "export",
        },
    }

    # Add required questions first
    for f in missing_required:
        if f in field_catalog:
            questions.append(field_catalog[f])

    # Add recommended questions
    for f in missing_recommended:
        if f in field_catalog:
            questions.append(field_catalog[f])

    return questions


def format_project_summary(project: dict[str, Any]) -> str:
    """Generate a clean, structured Markdown summary of the project configuration."""
    topic = project.get("topic", "Chưa đặt tên")
    reqs = project.get("requirements", {})

    fmt_label = PROJECT_FORMATS.get(reqs.get("content_format", ""), reqs.get("content_format") or "Chưa chọn")
    dur_sec = reqs.get("target_duration_seconds")
    dur_str = f"Khoảng {dur_sec // 60} phút ({dur_sec}s)" if dur_sec else "Chưa xác định"
    aud_label = DEFAULT_AUDIENCES.get(reqs.get("audience", ""), reqs.get("audience") or "Chưa chọn")
    lang_str = "Tiếng Việt (vi)" if reqs.get("language") == "vi" else (reqs.get("language") or "Tiếng Việt (vi)")
    tone_str = reqs.get("tone") or "Hấp dẫn, dễ hiểu"
    char_str = reqs.get("character_id") or "Tự động chọn theo chủ đề (Default Narrator)"
    sfx_label = DEFAULT_SFX_LEVELS.get(reqs.get("sfx_level", ""), reqs.get("sfx_level") or "Nhạc nền nhẹ, ít sound effect")
    out_fmts = ", ".join([f.upper() for f in reqs.get("output_formats", ["WAV", "SRT"])])

    lines = [
        "### 📋 Tóm tắt cấu hình dự án âm thanh:",
        f"* **Chủ đề**: {topic}",
        f"* **Định dạng**: {fmt_label}",
        f"* **Thời lượng mục tiêu**: {dur_str}",
        f"* **Đối tượng**: {aud_label}",
        f"* **Ngôn ngữ**: {lang_str}",
        f"* **Phong cách / Giọng điệu**: {tone_str}",
        f"* **Giọng đọc**: `{char_str}`",
        f"* **Âm thanh hậu kỳ**: {sfx_label}",
        f"* **Đầu ra**: {out_fmts} + project JSON",
    ]

    status = project.get("status")
    if status == "awaiting_confirmation":
        lines.extend([
            "\n---",
            "❓ **Xác nhận cấu hình**: Đây có phải cấu hình bạn muốn triển khai không?",
            "*(Vui lòng phản hồi 'Đồng ý', 'Xác nhận' hoặc gọi công cụ `chatterbox_confirm_project` để bắt đầu sản xuất)*",
        ])
    elif status == "approved":
        lines.extend([
            "\n---",
            "✅ **Dự án ĐÃ ĐƯỢC PHÊ DUYỆT (Approved)**! Bạn có thể bắt đầu tạo giọng nói với công cụ `chatterbox_render_project`.",
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
    """Initialize a project from topic and initial requirements."""
    if not topic or not topic.strip():
        raise ValidationError("Chủ đề dự án ('topic') không được để trống.")

    cleaned_topic = topic.strip()
    proj_id = f"proj_{uuid.uuid4().hex[:12]}"

    # Extract requirements from topic text and merge with explicit requirements
    extracted = extract_requirements_from_text(cleaned_topic)
    merged_reqs = {**extracted}
    if initial_requirements:
        merged_reqs.update(initial_requirements)

    if auto_defaults:
        merged_reqs = apply_sensible_defaults(merged_reqs, topic=cleaned_topic)

    missing_req, missing_rec = analyze_missing_fields(merged_reqs, auto_defaults=auto_defaults)

    status: ProjectStatus = (
        "awaiting_confirmation" if (not missing_req and not missing_rec)
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
        "confirmed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "approved_at": None,
        "job_id": None,
    }

    _save_project_file(project_data)

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
    """Process user answers for missing fields and update project state."""
    project = _load_project_file(project_id)
    current_status = project.get("status")

    if current_status in ("approved", "scripting", "rendering", "completed"):
        raise ProjectStateError(f"Dự án '{project_id}' đã ở trạng thái '{current_status}', không thể trả lời lại.")

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
            elif k in ("tone", "language", "pace", "quality_preset"):
                new_reqs[k] = v

    if auto_defaults or "tự chọn mặc định" in str(answers).lower():
        new_reqs = apply_sensible_defaults(new_reqs, topic=project.get("topic", ""))

    missing_req, missing_rec = analyze_missing_fields(new_reqs, auto_defaults=auto_defaults)

    if not missing_req:
        if missing_rec and not auto_defaults:
            # Still have recommended fields left
            status: ProjectStatus = "awaiting_answers"
        else:
            # Everything needed is collected -> move to awaiting_confirmation
            new_reqs = apply_sensible_defaults(new_reqs, topic=project.get("topic", ""))
            status = "awaiting_confirmation"
            missing_rec = []
    else:
        status = "awaiting_answers"

    project["requirements"] = new_reqs
    project["status"] = status
    project["missing_required"] = missing_req
    project["missing_recommended"] = missing_rec

    _save_project_file(project)

    questions = generate_question_batch(missing_req, missing_rec)

    return {
        "project_id": project_id,
        "status": status,
        "requirements": new_reqs,
        "questions": questions,
        "summary": format_project_summary(project),
    }


def confirm_project(project_id: str, confirmed: bool = True) -> dict[str, Any]:
    """Explicitly confirm or reject the final project plan."""
    project = _load_project_file(project_id)
    current_status = project.get("status")

    if current_status not in ("awaiting_confirmation", "awaiting_answers"):
        if current_status == "approved":
            return {
                "project_id": project_id,
                "status": "approved",
                "message": "Dự án đã được phê duyệt từ trước đó.",
                "summary": format_project_summary(project),
            }
        raise ProjectStateError(f"Không thể xác nhận dự án ở trạng thái '{current_status}'.")

    if confirmed:
        # Check that there are no remaining missing required fields
        missing_req, _ = analyze_missing_fields(project.get("requirements", {}), auto_defaults=True)
        if missing_req:
            raise ValidationError(f"Dự án chưa thể xác nhận vì còn thiếu thông tin bắt buộc: {missing_req}")

        project["requirements"] = apply_sensible_defaults(project.get("requirements", {}), topic=project.get("topic", ""))
        project["status"] = "approved"
        project["confirmed"] = True
        project["approved_at"] = datetime.now(timezone.utc).isoformat()
        _save_project_file(project)

        return {
            "project_id": project_id,
            "status": "approved",
            "message": "✅ Đã xác nhận phê duyệt dự án thành công!",
            "summary": format_project_summary(project),
        }
    else:
        project["status"] = "cancelled"
        project["confirmed"] = False
        _save_project_file(project)

        return {
            "project_id": project_id,
            "status": "cancelled",
            "message": "❌ Đã hủy dự án theo yêu cầu người dùng.",
            "summary": format_project_summary(project),
        }


def render_project(
    project_id: str,
    script_text: str | None = None,
    character_id: str | None = None,
    quality_preset: str | None = None,
    job_manager: Any = None,
) -> dict[str, Any]:
    """Execute speech synthesis on an approved project. Rejects unapproved projects."""
    project = _load_project_file(project_id)
    status = project.get("status")

    # Strict Backend Enforcement
    if status != "approved":
        raise ProjectNotApprovedError(
            f"Dự án '{project_id}' chưa được phê duyệt (trạng thái hiện tại: '{status}'). "
            "Backend từ chối render! Vui lòng xác nhận cấu hình dự án bằng 'chatterbox_confirm_project' trước khi triển khai."
        )

    reqs = project.get("requirements", {})
    topic = project.get("topic", "Dự án âm thanh")

    # Generate starter script if not provided
    if not script_text:
        script_text = (
            f"Chào mừng bạn đến với chương trình âm thanh về chủ đề: {topic}. "
            f"Hôm nay chúng ta sẽ cùng khám phá những thông tin hấp dẫn, ngắn gọn và hữu ích nhất dành cho bạn."
        )

    selected_char = character_id or reqs.get("character_id")
    selected_preset = quality_preset or reqs.get("quality_preset", "balanced")
    selected_lang = reqs.get("language", "vi")

    # Transition to scripting -> rendering
    project["status"] = "rendering"
    project["script"] = script_text

    job_id = None
    if job_manager and getattr(job_manager, "_running", False):
        try:
            tts_params = {
                "text": script_text,
                "quality_preset": selected_preset,
                "character_id": selected_char,
                "language": selected_lang,
                "project_id": project_id,
            }
            job = job_manager.submit_job(job_type="tts", params=tts_params, input_paths=[])
            job_id = job.id
            project["job_id"] = job_id
        except Exception:
            job_id = f"job_proj_{uuid.uuid4().hex[:8]}"
            project["job_id"] = job_id
    else:
        # Fallback dummy job_id for tests / standalone mode
        job_id = f"job_proj_{uuid.uuid4().hex[:8]}"
        project["job_id"] = job_id

    _save_project_file(project)

    return {
        "project_id": project_id,
        "status": "rendering",
        "job_id": job_id,
        "topic": topic,
        "script_text": script_text,
        "message": f"🎙️ Đã khởi tạo tác vụ tổng hợp giọng nói cho dự án '{topic}' với Job ID: `{job_id}`.",
    }


def get_project(project_id: str) -> dict[str, Any]:
    """Retrieve full project state."""
    project = _load_project_file(project_id)
    return {
        **project,
        "summary": format_project_summary(project),
    }


def list_projects() -> list[dict[str, Any]]:
    """List all saved projects."""
    proj_dir = _get_projects_dir()
    projects = []
    for f in sorted(proj_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            pdata = json.loads(f.read_text(encoding="utf-8"))
            projects.append(pdata)
        except Exception:
            continue
    return projects
