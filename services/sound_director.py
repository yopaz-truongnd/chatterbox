"""Sound Director Service (Phase 3) for mapping storytelling beats to sound intents (ambience, SFX, silence)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml

from services.voice_plan import (
    VoicePlan,
    Beat,
    BeatRole,
    AmbienceIntent,
    SFXIntent,
    SFXFunction,
    SFXPlacement,
    SilenceDecision,
    SilenceAfter,
)

# Built-in Default Sound Policy to guarantee single source of truth fallback
DEFAULT_SOUND_POLICY = {
    "version": 1,
    "general": {
        "voice_priority": 100,
        "ambience_priority": 50,
        "sfx_priority": 30,
        "never_mask_voice": True,
    },
    "density": {
        "max_prominent_sfx_per_minute": 5,
        "min_gap_prominent_sfx_seconds": 5,
        "max_simultaneous_sfx": 2,
    },
    "roles": {
        "hook": {"ambience": "preferred", "riser": "allowed", "whoosh": "allowed"},
        "setup": {"ambience": "allowed", "sfx": "allowed"},
        "reveal": {"riser": "preferred", "impact": "allowed"},
        "description": {"ambience": "allowed", "sfx": "discouraged"},
        "lore": {"ambience": "preferred", "sfx": "minimal"},
        "escalation": {"sfx": "preferred", "riser": "preferred"},
        "supernatural_event": {"sfx": "preferred", "impact": "allowed"},
        "climax": {"impact": "preferred", "silence_after": "preferred"},
        "reflection": {"ambience": "subtle", "impact": "forbidden", "silence": "preferred"},
        "transition": {"riser": "allowed", "whoosh": "preferred"},
        "outro": {"riser": "allowed", "final_hit": "allowed"},
    }
}


def load_sound_policy(policy_path: str | None = None) -> dict[str, Any]:
    """Load sound policy from rules/sound-director.yaml if present, else fallback to defaults."""
    import copy
    if not policy_path:
        # Resolve standard path rules/sound-director.yaml relative to project root
        policy_path = str(Path(__file__).resolve().parent.parent / "rules" / "sound-director.yaml")

    policy = copy.deepcopy(DEFAULT_SOUND_POLICY)
    if os.path.exists(policy_path):
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if loaded and isinstance(loaded, dict):
                    # Merge keys
                    if "general" in loaded and isinstance(loaded["general"], dict):
                        policy["general"].update(loaded["general"])
                    if "density" in loaded and isinstance(loaded["density"], dict):
                        policy["density"].update(loaded["density"])
                    if "roles" in loaded and isinstance(loaded["roles"], dict):
                        policy["roles"].update(loaded["roles"])
        except Exception as e:
            raise ValueError(f"Malformed sound policy YAML at {policy_path}: {e}") from e
    return policy


def classify_sfx_prominence(necessity: float) -> str:
    """Classify the prominence of an SFX cue based on its necessity score range."""
    if necessity > 0.80:
        return "prominent"
    elif necessity >= 0.65:
        return "light"
    elif necessity >= 0.40:
        return "subtle"
    else:
        return "removed"


def direct_sound(
    voice_plan: VoicePlan,
    beat_context: dict[str, Any] | None = None,
    policy_path: str | None = None,
) -> VoicePlan:
    """Analyze BeatRoles and narrative context in VoicePlan to suggest Ambience, SFX, and Silence intents.

    Operates purely on plan intents, leaving asset resolution to the Resource Manager.
    """
    import copy
    directed_plan = copy.deepcopy(voice_plan)

    # Load consolidated policy rules
    policy = load_sound_policy(policy_path)
    role_rules = policy.get("roles", {})

    active_ambience: AmbienceIntent | None = None

    for idx, beat in enumerate(directed_plan.beats):
        role = beat.role
        rule = role_rules.get(role.value, {})

        # 1. Ambience Decision (preserves continuity if tone matches)
        beat_ambience = None
        amb_rule = rule.get("ambience", "none")
        if amb_rule == "preferred" or (amb_rule == "allowed" and active_ambience is None):
            # Formulate ambience intent depending on role
            intent_name = "ancient_dark_atmosphere" if role in (BeatRole.HOOK, BeatRole.LORE, BeatRole.SUPERNATURAL_EVENT) else "subtle_narrative_drone"
            intensity = "medium" if amb_rule == "preferred" else "low"
            active_ambience = AmbienceIntent(
                intent=intent_name,
                intensity=intensity,
                volume_db=-29.0 if amb_rule == "preferred" else -35.0
            )
            beat_ambience = active_ambience
        elif amb_rule == "subtle":
            # Subtle reflection/emotional drones
            active_ambience = AmbienceIntent(
                intent="ethereal_silence_pad",
                intensity="low",
                volume_db=-38.0
            )
            beat_ambience = active_ambience
        elif amb_rule == "allowed" and active_ambience is not None:
            # Continue active ambience
            beat_ambience = active_ambience
        else:
            # Silence/stop active ambience for this beat
            active_ambience = None

        beat.ambience = beat_ambience

        # 2. SFX Intent generation
        # We go: BeatRole + context -> Narrative sound function -> Necessity -> SFX Intent
        sfx_intents: list[SFXIntent] = []
        text_lower = beat.script.text.lower()

        # Check narrative cues in text for emphasis and transition functions
        has_climax = role == BeatRole.CLIMAX
        has_supernatural = role == BeatRole.SUPERNATURAL_EVENT
        has_escalation = role == BeatRole.ESCALATION
        has_reveal = role == BeatRole.REVEAL

        # Reveal/Hook Transition
        if has_reveal or (role == BeatRole.HOOK and any(w in text_lower for w in ["what if", "legend"])):
            # Transition function -> Riser intent
            riser_rule = rule.get("riser", "discouraged")
            if riser_rule != "discouraged":
                necessity = 0.72 if riser_rule == "preferred" else 0.55
                sfx_intents.append(
                    SFXIntent(
                        intent="supernatural_reveal_riser",
                        function=SFXFunction.TRANSITION,
                        placement=SFXPlacement.PRE,
                        necessity=necessity,
                        max_volume_db=-22.0,
                        reason="marks transition into a major reveal or hook"
                    )
                )

        # Supernatural / Climax Impacts
        if has_climax or has_supernatural:
            # Emphasis function -> Impact intent
            impact_rule = rule.get("impact", "discouraged")
            if impact_rule != "discouraged" and impact_rule != "forbidden":
                necessity = 0.85 if has_climax else 0.70
                sfx_intents.append(
                    SFXIntent(
                        intent="cinematic_sub_boom",
                        function=SFXFunction.EMPHASIS,
                        placement=SFXPlacement.POST,
                        necessity=necessity,
                        offset=0.15,
                        max_volume_db=-18.0 if has_climax else -24.0,
                        reason="marks the cosmic/physical climax of the beat"
                    )
                )

        # Reflection beat checks: absolutely block impacts
        if role == BeatRole.REFLECTION:
            # Reflection beat should NOT have any physical impacts. Enforce this inside director
            sfx_intents = [s for s in sfx_intents if s.function != SFXFunction.EMPHASIS]

        # Filter out anything with necessity < 0.40 immediately in director stage
        beat.sfx = [s for s in sfx_intents if s.necessity >= 0.40]

        # 3. Silence Decision (first-class decision)
        silence_decision = None
        silence_rule = rule.get("silence", "discouraged")
        silence_after_rule = rule.get("silence_after", "discouraged")

        if silence_rule == "preferred" or role == BeatRole.REFLECTION:
            silence_decision = SilenceDecision(
                after=SilenceAfter(duration=1.2, reason="give the reflection beat breathing room")
            )
        elif silence_after_rule == "preferred" or has_climax:
            silence_decision = SilenceDecision(
                after=SilenceAfter(duration=1.5, reason="let the climax impact resonate")
            )

        beat.silence = silence_decision

    return directed_plan
