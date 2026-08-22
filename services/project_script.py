"""Gate 2: English Script Planning, Outline Generation & Semantic Segmentation."""

from __future__ import annotations

import re
from typing import Any


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


def segment_script_text(
    script_text: str,
    target_pace: str = "medium",
    default_model: str = "turbo",
    format_type: str = "podcast",
    pronunciation_dict: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Segment an English script into semantic chunks of 1-3 sentences (8-25s each) and attach Narration Plans."""
    from services.narration_planner import compile_narration_plan

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

    return compile_narration_plan(
        segments,
        format_type=format_type,
        default_pace=target_pace,
        default_model=default_model,
        pronunciation_dict=pronunciation_dict,
    )
