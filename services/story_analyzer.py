"""Story Analyzer Service for narrative grouping and semantic beat classification (Phase 2)."""

from __future__ import annotations

import re
from typing import Any
from pydantic import BaseModel, Field

from services.voice_plan import BeatRole


class StoryBeat(BaseModel):
    id: str
    role: BeatRole
    text: str
    source_segment_ids: list[str] = Field(default_factory=list)
    source_start: int | None = None
    source_end: int | None = None
    estimated_seconds: float = 0.0
    confidence: float = 1.0


def analyze_story_beats(
    script_text: str,
    segments: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
) -> list[StoryBeat]:
    """Segment raw script text or group existing segments into semantic storytelling beats.

    Applies weighted heuristic scoring to determine the narrative BeatRole.
    """
    if not script_text:
        return []

    # If segments are not provided, we perform basic paragraph/scene splitting with exact offsets
    if not segments:
        segments = []
        start = 0
        p_matches = list(re.finditer(r"\n\s*\n", script_text))
        for p_idx, match in enumerate(p_matches, 1):
            end = match.start()
            p_text = script_text[start:end]
            if p_text:
                segments.append({
                    "id": f"seg_{p_idx:03d}",
                    "text": p_text,
                    "speaker": "Narrator",
                    "estimated_seconds": len(p_text.split()) / 2.3,
                    "source_start": start,
                    "source_end": end,
                })
            start = match.end()
        # last part
        p_text = script_text[start:]
        if p_text:
            segments.append({
                "id": f"seg_{len(p_matches)+1:03d}",
                "text": p_text,
                "speaker": "Narrator",
                "estimated_seconds": len(p_text.split()) / 2.3,
                "source_start": start,
                "source_end": start + len(p_text),
            })
    else:
        # Resolve user-provided segment offsets sequentially to avoid picking up out-of-order duplicates
        search_cursor = 0
        for seg in segments:
            seg_text = seg.get("text", "")
            if not seg_text:
                seg["source_start"] = None
                seg["source_end"] = None
                continue
            pos = script_text.find(seg_text, search_cursor)
            if pos != -1:
                seg["source_start"] = pos
                seg["source_end"] = pos + len(seg_text)
                search_cursor = pos + len(seg_text)
            else:
                seg["source_start"] = None
                seg["source_end"] = None

    story_beats: list[StoryBeat] = []
    current_group: list[dict[str, Any]] = []
    current_duration = 0.0
    beat_idx = 1

    def flush_beat(group: list[dict[str, Any]], idx: int) -> StoryBeat:
        first_seg = group[0]
        last_seg = group[-1]

        source_start = first_seg.get("source_start")
        source_end = last_seg.get("source_end")

        if source_start is not None and source_end is not None:
            beat_text = script_text[source_start:source_end]
        else:
            texts = [seg.get("text", "") for seg in group]
            beat_text = " ".join(texts)

        # Estimate duration
        est_sec = sum(seg.get("estimated_seconds", len(seg.get("text", "").split()) / 2.3) for seg in group)
        seg_ids = [seg.get("id", "") for seg in group]

        # Determine BeatRole via Heuristics
        role, confidence = classify_beat_role(beat_text, group, idx)

        return StoryBeat(
            id=f"B{idx:02d}",
            role=role,
            text=beat_text,
            source_segment_ids=seg_ids,
            source_start=source_start,
            source_end=source_end,
            estimated_seconds=round(est_sec, 2),
            confidence=round(confidence, 2)
        )

    # Group segments into semantic beats targeting 8-25 seconds
    for seg in segments:
        seg_text = seg.get("text", "")
        if not seg_text:
            continue

        seg_dur = seg.get("estimated_seconds", len(seg_text.split()) / 2.3)

        # Flush if speaker, scene, paragraph, or duration limit is reached
        if current_group:
            prev_seg = current_group[-1]
            speaker_changed = seg.get("speaker") != prev_seg.get("speaker")
            scene_changed = seg.get("scene_id") != prev_seg.get("scene_id")
            over_duration = (current_duration + seg_dur > 25.0)

            # Check if there is a newline/paragraph break in source text between segments using offsets
            p_break = False
            prev_end = prev_seg.get("source_end")
            curr_start = seg.get("source_start")
            if prev_end is not None and curr_start is not None:
                gap_text = script_text[prev_end:curr_start]
                if "\n" in gap_text:
                    p_break = True

            if speaker_changed or scene_changed or over_duration or p_break:
                story_beats.append(flush_beat(current_group, beat_idx))
                beat_idx += 1
                current_group = []
                current_duration = 0.0

        current_group.append(seg)
        current_duration += seg_dur

    if current_group:
        story_beats.append(flush_beat(current_group, beat_idx))

    # Adjust Outro role if necessary (last beat defaults to outro unless it's hook)
    if len(story_beats) > 1 and story_beats[-1].role == BeatRole.DESCRIPTION:
        # Re-classify final beat as outro if it fits closing narrative signals
        story_beats[-1].role = BeatRole.OUTRO

    return story_beats


def classify_beat_role(beat_text: str, group: list[dict[str, Any]], beat_idx: int) -> tuple[BeatRole, float]:
    """Analyze semantic markers using weighted scoring rules rather than keyword mapping."""
    text_lower = beat_text.lower()
    
    # 1. Check if beat_role is explicitly supplied by the caller (Fail-Fast)
    for seg in group:
        explicit_role = seg.get("beat_role")
        if explicit_role:
            try:
                return BeatRole(explicit_role), 1.0
            except ValueError:
                # If explicit role was supplied but invalid, fail-fast immediately
                raise ValueError(f"Invalid beat role value supplied: '{explicit_role}'")

    scores: dict[BeatRole, float] = {role: 0.0 for role in BeatRole}

    # Signal 1: Position indicators
    if beat_idx == 1:
        scores[BeatRole.HOOK] += 0.60
    
    # Signal 2: Structural/punctuation signals
    if "?" in beat_text:
        scores[BeatRole.HOOK] += 0.30
        scores[BeatRole.REFLECTION] += 0.30
    if beat_text.rstrip().endswith("?"):
        scores[BeatRole.REFLECTION] += 0.40
    if '"' in beat_text or "'" in beat_text:
        scores[BeatRole.REVEAL] += 0.30
        scores[BeatRole.LORE] += 0.20

    # Signal 3: Lexical indicators (weighted lower to avoid simplistic keyword triggers)
    if any(w in text_lower for w in ["think", "wonder", "ponder", "perhaps", "maybe", "represent"]):
        scores[BeatRole.REFLECTION] += 0.45
    if any(w in text_lower for w in ["ancient", "text", "century", "history", "dynasty", "mythology", "classic", "describe", "legend"]):
        scores[BeatRole.LORE] += 0.45
    if any(w in text_lower for w in ["dragon", "god", "spirit", "supernatural", "magic", "immortal", "myth"]):
        scores[BeatRole.SUPERNATURAL_EVENT] += 0.30
    if any(w in text_lower for w in ["but", "however", "suddenly", "terrifying", "colossal"]):
        scores[BeatRole.ESCALATION] += 0.30
    if any(w in text_lower for w in ["climax", "battle", "clash", "force", "power", "daylight"]):
        scores[BeatRole.CLIMAX] += 0.40

    # Signal 4: Speaker role hints
    speakers = {seg.get("speaker", "Narrator").lower() for seg in group}
    if any("thought" in s or "inner" in s for s in speakers):
        scores[BeatRole.REFLECTION] += 0.50
    elif any(s not in ("narrator", "mc", "host") for s in speakers):
        scores[BeatRole.REVEAL] += 0.35

    # Determine highest score
    best_role = BeatRole.DESCRIPTION
    best_score = 0.0
    for role, score in scores.items():
        if score > best_score:
            best_score = score
            best_role = role

    confidence = 0.5 if best_score == 0.0 else min(1.0, best_score)
    return best_role, confidence


def story_beats_to_narration_segments(
    beats: list[StoryBeat],
    original_segments: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Adapter helper mapping new StoryBeat models back to segment dictionaries.

    Ensures seamless compatibility with the Narration Planner compilation steps.
    """
    mapped_segments: list[dict[str, Any]] = []

    # Map original segments by ID for context lookup
    orig_map = {seg.get("id"): seg for seg in original_segments} if original_segments else {}

    for beat in beats:
        # Determine narrator speaker / emotion matching from source lineage
        first_seg_id = beat.source_segment_ids[0] if beat.source_segment_ids else None
        orig_seg = orig_map.get(first_seg_id) if first_seg_id else None

        speaker = orig_seg.get("speaker", "Narrator") if orig_seg else "Narrator"
        emotion = orig_seg.get("emotion", "engaging") if orig_seg else "engaging"

        # Construct legacy-compatible narration plan segment dict
        seg_dict = {
            "id": beat.id,
            "text": beat.text,
            "speaker": speaker,
            "emotion": emotion,
            "beat_role": beat.role.value,
            "estimated_seconds": beat.estimated_seconds,
            "word_count": len(beat.text.split()),
            "status": "planned",
            "source_segment_ids": beat.source_segment_ids,
        }

        # Preserve any attempts or results if pre-populated
        if orig_seg:
            for k in ("attempts", "selected_attempt", "status"):
                if k in orig_seg:
                    seg_dict[k] = orig_seg[k]

        mapped_segments.append(seg_dict)

    return mapped_segments
