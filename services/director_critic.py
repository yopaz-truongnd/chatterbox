"""Director Critic Service (Phase 3) for inspecting and auto-fixing sound intents before rendering."""

from __future__ import annotations

import copy
from typing import Any
from pydantic import BaseModel, Field

from services.voice_plan import (
    VoicePlan,
    Beat,
    BeatRole,
    SFXFunction,
    SFXIntent,
)
from services.sound_director import classify_sfx_prominence, load_sound_policy


class DirectorCritiqueResult(BaseModel):
    score: int
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    changed: bool = False


def calculate_sfx_timestamps(plan: VoicePlan) -> list[dict[str, Any]]:
    """Construct an estimated virtual timeline of beats and compute absolute timestamps for all SFX cues."""
    sfx_timeline: list[dict[str, Any]] = []
    current_time = 0.0

    for idx, beat in enumerate(plan.beats):
        beat_dur = beat.script.estimated_seconds if hasattr(beat.script, "estimated_seconds") else 0.0
        if not beat_dur:
            beat_dur = len(beat.script.text.split()) / 2.3

        # Add pause before
        pause_before = beat.voice.pause.before if beat.voice.pause else 0.0
        beat_start = current_time + pause_before
        beat_end = beat_start + beat_dur

        # Parse SFX intents and assign virtual absolute timestamps
        for s_idx, sfx in enumerate(beat.sfx):
            absolute_time = beat_start
            if sfx.placement == "under":
                absolute_time = beat_start + sfx.offset
            elif sfx.placement == "post":
                absolute_time = beat_end + sfx.offset
            elif sfx.placement == "pre":
                absolute_time = beat_start - sfx.offset
            elif sfx.placement == "bridge":
                absolute_time = beat_end

            sfx_timeline.append({
                "beat_idx": idx,
                "beat_id": beat.id,
                "beat_role": beat.role,
                "sfx_idx": s_idx,
                "sfx": sfx,
                "timestamp": absolute_time,
                "prominent": classify_sfx_prominence(sfx.necessity) == "prominent"
            })

        # Advance timeline for next beat
        pause_after = beat.voice.pause.after if beat.voice.pause else 0.0
        current_time = beat_end + pause_after

    return sfx_timeline


def critique_voice_plan(plan: VoicePlan, policy_path: str | None = None) -> DirectorCritiqueResult:
    """Inspect a VoicePlan's sound plan for density, gap conflicts, and forbidden rules."""
    policy = load_sound_policy(policy_path)
    density_rules = policy.get("density", {})
    max_prominent_per_min = density_rules.get("max_prominent_sfx_per_minute", 5)
    min_gap_seconds = density_rules.get("min_gap_prominent_sfx_seconds", 5)

    issues: list[str] = []
    suggestions: list[str] = []
    score = 100

    sfx_timeline = calculate_sfx_timestamps(plan)

    # 1. Inspect Reflection Beat constraints (forbid impact SFX)
    for beat in plan.beats:
        if beat.role == BeatRole.REFLECTION:
            for sfx in beat.sfx:
                if sfx.function == SFXFunction.EMPHASIS:
                    issues.append(f"Beat {beat.id} ({beat.role.value}): Forbidden prominent/emphasis SFX '{sfx.intent}' found during reflection.")
                    score -= 15

    # 2. Inspect Gap conflicts between prominent cues (< 5 seconds)
    prominent_cues = [c for c in sfx_timeline if c["prominent"]]
    for i in range(len(prominent_cues) - 1):
        c1 = prominent_cues[i]
        c2 = prominent_cues[i+1]
        gap = c2["timestamp"] - c1["timestamp"]
        if gap < min_gap_seconds:
            issues.append(
                f"SFX Gap Conflict: Prominent SFX '{c1['sfx'].intent}' (Beat {c1['beat_id']}) and "
                f"'{c2['sfx'].intent}' (Beat {c2['beat_id']}) are too close ({gap:.2f}s < {min_gap_seconds}s)."
            )
            score -= 10

    # 3. Inspect density per minute
    # Let's count prominent cues in sliding 60s windows
    for idx, c in enumerate(prominent_cues):
        t_start = c["timestamp"]
        t_end = t_start + 60.0
        count_min = sum(1 for other in prominent_cues if t_start <= other["timestamp"] < t_end)
        if count_min > max_prominent_per_min:
            issues.append(f"SFX Density Warning: Found {count_min} prominent cues in a 60s window starting at {t_start:.1f}s (Max allowed is {max_prominent_per_min}).")
            score -= 10
            break

    # Make suggestions if score is low
    if score < 100:
        suggestions.append("Run auto-fix to deterministic-prune or relocate overlapping and forbidden cues.")

    return DirectorCritiqueResult(
        score=max(0, score),
        issues=issues,
        suggestions=suggestions,
        changed=False
    )


def apply_director_fixes(plan: VoicePlan, critique: DirectorCritiqueResult | None = None, policy_path: str | None = None) -> VoicePlan:
    """Return a deep-copied, corrected VoicePlan v2 without mutating the original input plan.

    Resolves necessity conflicts, strips forbidden cues, and adjusts gaps according to role importance.
    """
    fixed_plan = copy.deepcopy(plan)
    policy = load_sound_policy(policy_path)
    density_rules = policy.get("density", {})
    min_gap = density_rules.get("min_gap_prominent_sfx_seconds", 5)

    # Step 1: Remove necessity < 0.40 and forbidden reflection impacts
    for beat in fixed_plan.beats:
        valid_sfx = []
        for sfx in beat.sfx:
            if sfx.necessity < 0.40:
                continue
            if beat.role == BeatRole.REFLECTION and sfx.function == SFXFunction.EMPHASIS:
                # Strip emphasis impact from reflection beat
                continue
            valid_sfx.append(sfx)
        beat.sfx = valid_sfx

    # Step 2: Enforce prominent SFX gaps (>= 5s) using role priority weighting
    # We resolve conflicts by prioritizing Climax, Supernatural Event, and Hook roles
    role_priority_bonuses = {
        BeatRole.CLIMAX: 0.50,
        BeatRole.SUPERNATURAL_EVENT: 0.30,
        BeatRole.HOOK: 0.20,
    }

    # Iterate timeline and resolve adjacent conflicts
    has_changed = True
    while has_changed:
        has_changed = False
        timeline = calculate_sfx_timestamps(fixed_plan)
        prominents = [c for c in timeline if c["prominent"]]

        for i in range(len(prominents) - 1):
            c1 = prominents[i]
            c2 = prominents[i+1]
            gap = c2["timestamp"] - c1["timestamp"]
            if gap < min_gap:
                # Compute composite scores
                bonus1 = role_priority_bonuses.get(c1["beat_role"], 0.0)
                score1 = c1["sfx"].necessity + bonus1

                bonus2 = role_priority_bonuses.get(c2["beat_role"], 0.0)
                score2 = c2["sfx"].necessity + bonus2

                # Discard the cue with the lower composite score
                if score1 >= score2:
                    # Remove c2
                    target_beat = fixed_plan.beats[c2["beat_idx"]]
                    target_beat.sfx.pop(c2["sfx_idx"])
                else:
                    # Remove c1
                    target_beat = fixed_plan.beats[c1["beat_idx"]]
                    target_beat.sfx.pop(c1["sfx_idx"])

                has_changed = True
                break  # Re-evaluate timeline since indexes shifted

    return fixed_plan
