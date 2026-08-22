"""Narration Planning & Pronunciation Engine for Storytelling and Voice Production.

Analyzes English scripts to generate rich segment-level narration plans (roles, emotions,
energy, pacing, pauses, emphasis, model-aware parameters) and scans pronunciation candidates.
"""

from __future__ import annotations

import re
from typing import Any


def scan_pronunciation_candidates(script_text: str) -> list[dict[str, Any]]:
    """Scan script text for words that likely need pronunciation verification.
    
    Detects:
    - Acronyms / ALL_CAPS words (e.g., 'NASA', 'AI', 'GPT', 'TTS')
    - Proper nouns / Capitalized words mid-sentence (e.g., 'Elan', 'Turing', 'Krypton')
    - Numbers, dates, and measurements (e.g., '1984', '$50', '3.14', '100km/h')
    - Unusual hyphenated words or compounds
    """
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Acronyms / All-caps (2+ uppercase letters)
    acronym_matches = re.findall(r"\b([A-Z]{2,6})\b", script_text)
    for acr in acronym_matches:
        if acr not in seen and acr not in ("AI", "OK"):
            seen.add(acr)
            candidates.append({
                "word": acr,
                "category": "acronym",
                "reason": "All-caps acronym may need hyphenation or letter-by-letter expansion (e.g., 'N.A.S.A.')",
                "suggested_reading": ". ".join(list(acr)) + ".",
            })

    # 2. Numbers and units (e.g. 1990s, 300km, 25%, $50M)
    num_matches = re.findall(r"(?:[\$€£]?\d+(?:[.,]\d+)*(?:%|st|nd|rd|th|km|m|kg|s|s|M|B|k)?)\b", script_text)
    for num in num_matches:
        clean_num = num.strip()
        if clean_num and clean_num not in seen and len(clean_num) > 1:
            seen.add(clean_num)
            candidates.append({
                "word": clean_num,
                "category": "number_or_unit",
                "reason": "Numbers or formatted units may sound better expanded into written English words",
                "suggested_reading": clean_num,
            })

    # 3. Capitalized words occurring mid-sentence (potential proper nouns / character names)
    sentences = re.split(r"(?<=[.?!])\s+", script_text)
    for sent in sentences:
        words = sent.strip().split()
        if len(words) > 1:
            for w in words[1:]:
                clean_w = re.sub(r"[^\w]", "", w)
                if clean_w.istitle() and len(clean_w) > 2 and clean_w not in seen:
                    # Filter common English words that might be capitalized after quotes
                    if clean_w.lower() not in ("the", "this", "that", "there", "then", "when", "what", "where", "how", "and", "but", "so"):
                        seen.add(clean_w)
                        candidates.append({
                            "word": clean_w,
                            "category": "proper_noun",
                            "reason": "Character name or proper noun may require phonetic spelling for natural inflection",
                            "suggested_reading": clean_w,
                        })

    return candidates


def apply_pronunciation_dict(text: str, pronunciation_dict: dict[str, str] | None) -> str:
    """Apply dictionary substitutions to text with word-boundary awareness."""
    if not pronunciation_dict:
        return text

    processed = text
    for word, reading in pronunciation_dict.items():
        if not word.strip() or not reading.strip():
            continue
        # Use regex word boundary replacement
        pattern = r"\b" + re.escape(word.strip()) + r"\b"
        processed = re.sub(pattern, reading.strip(), processed)

    return processed


def extract_emphasis_words(sentence: str) -> list[str]:
    """Extract candidate key words to emphasize in the spoken phrase."""
    # Look for quoted words, asterisks, or expressive adverbs/adjectives
    expressive_keywords = re.findall(
        r"\b(never|always|suddenly|slowly|instantly|crucial|vital|profound|remarkable|extraordinary|shocking|secret|unbelievable|truly)\b",
        sentence,
        flags=re.IGNORECASE,
    )
    # Also capture words in quotes or between *asterisks*
    marked = re.findall(r"[\"']([^\"']+)[\"']|\*([^*]+)\*", sentence)
    flattened_marked = [item for sub in marked for item in sub if item]

    combined = list(dict.fromkeys([w.lower() for w in expressive_keywords + flattened_marked]))
    return combined[:3]


def determine_segment_role_and_emotion(
    speaker: str,
    text: str,
    scene_emotion: str = "engaging",
) -> tuple[str, str, float]:
    """Determine speaker role, emotional inflection, and baseline energy level."""
    speaker_lower = speaker.strip().lower()
    text_lower = text.lower()

    # 1. Role determination
    if speaker_lower in ("narrator", "mc", "host", "voiceover", "voice"):
        role = "narrator"
    elif any(s in speaker_lower for s in ("monologue", "inner", "thought")):
        role = "monologue"
    else:
        role = "dialogue"

    # 2. Emotion & Energy detection
    if any(w in text_lower for w in ("whisper", "secret", "shadow", "quiet", "danger", "dark", "suddenly")):
        emotion = "suspense"
        energy = 0.35
    elif any(w in text_lower for w in ("think", "reflect", "wonder", "ponder", "perhaps", "history", "origins")):
        emotion = "thoughtful"
        energy = 0.45
    elif any(w in text_lower for w in ("amazing", "breakthrough", "accelerat", "fast", "powerful", "revolution", "incredible")):
        emotion = "energetic"
        energy = 0.85
    elif any(w in text_lower for w in ("warning", "urgent", "critical", "epic", "battle", "clash", "storm")):
        emotion = "dramatic"
        energy = 0.80
    elif any(w in text_lower for w in ("relax", "peace", "calm", "gentle", "breath", "meditation")):
        emotion = "calm"
        energy = 0.30
    else:
        emotion = scene_emotion or "engaging"
        energy = 0.60

    return role, emotion, energy


def compile_narration_plan(
    segments: list[dict[str, Any]],
    format_type: str = "podcast",
    default_pace: str = "medium",
    default_model: str = "turbo",
    pronunciation_dict: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Compile an explicit, model-aware narration plan for each script segment.
    
    Generates pacing, target WPM, pauses, emphasis, pronunciation, and candidate strategies.
    """
    pacing_map = {
        "slow": 110,
        "medium": 138,
        "fast": 165,
    }
    target_wpm = pacing_map.get(default_pace, 138)

    planned_segments: list[dict[str, Any]] = []

    for seg in segments:
        seg_copy = dict(seg)
        text = seg_copy.get("text", "")
        speaker = seg_copy.get("speaker", "Narrator")
        scene_emotion = seg_copy.get("emotion", "engaging")

        role, emotion, energy = determine_segment_role_and_emotion(speaker, text, scene_emotion)

        # Dynamic pace based on emotion & energy
        if emotion in ("suspense", "calm") or energy < 0.4:
            pace = "slow"
            wpm = 112
        elif emotion in ("energetic", "dramatic") or energy > 0.75:
            pace = "fast"
            wpm = 160
        else:
            pace = default_pace or "medium"
            wpm = target_wpm

        # Pauses
        pause_before_ms = 250 if role == "dialogue" else 100
        pause_after_ms = seg_copy.get("pause_after_ms", 700 if text.endswith((".", "!", "?")) else 400)

        # Emphasis & Pronunciation
        emphasis = extract_emphasis_words(text)
        pron_overrides = {}
        if pronunciation_dict:
            for k, v in pronunciation_dict.items():
                if re.search(r"\b" + re.escape(k) + r"\b", text, flags=re.IGNORECASE):
                    pron_overrides[k] = v

        # Candidate Strategy: selective 2-candidate for dialogue, climax, complex words, or high emotion
        is_dialogue = role == "dialogue"
        is_climax = emotion in ("dramatic", "suspense") and energy >= 0.7
        has_pron = len(pron_overrides) > 0
        is_long = len(text.split()) > 24

        if is_dialogue or is_climax or has_pron or is_long:
            candidate_strategy = "multi_selective"
        else:
            candidate_strategy = "single"

        # Model resolution
        assigned_model = default_model or "turbo"

        narration_plan = {
            "role": role,
            "emotion": emotion,
            "energy": energy,
            "pace": pace,
            "target_wpm": wpm,
            "pause_before_ms": pause_before_ms,
            "pause_after_ms": pause_after_ms,
            "emphasis": emphasis,
            "pronunciation": pron_overrides,
            "model": assigned_model,
            "candidate_strategy": candidate_strategy,
        }

        seg_copy["narration_plan"] = narration_plan
        # Ensure top-level segment metadata matches
        seg_copy["role"] = role
        seg_copy["emotion"] = emotion
        seg_copy["pace"] = pace
        seg_copy["model"] = assigned_model
        planned_segments.append(seg_copy)

    return planned_segments
