"""Gate 1: Audio Project Requirements Extraction & Heuristics (English Scope Locked)."""

from __future__ import annotations

import re
from typing import Any


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
