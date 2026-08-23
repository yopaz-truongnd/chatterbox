"""Voice Plan domain model, builder, validation, and serialization services.

Acts as the central design contract (VoicePlan) between the Story Analyzer,
Sound Director, and TTS Renderer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
import yaml
from pydantic import BaseModel, Field, field_validator


class BeatRole(str, Enum):
    HOOK = "hook"
    SETUP = "setup"
    REVEAL = "reveal"
    DESCRIPTION = "description"
    LORE = "lore"
    ESCALATION = "escalation"
    SUPERNATURAL_EVENT = "supernatural_event"
    CLIMAX = "climax"
    REFLECTION = "reflection"
    TRANSITION = "transition"
    OUTRO = "outro"


class SFXPlacement(str, Enum):
    PRE = "pre"
    UNDER = "under"
    POST = "post"
    BRIDGE = "bridge"


class EmphasisStrength(str, Enum):
    SUBTLE = "subtle"
    MEDIUM = "medium"
    STRONG = "strong"


class ProjectMetadata(BaseModel):
    id: str
    title: str
    language: str = "en-US"
    source_script: str


class VoiceMetadata(BaseModel):
    profile: str
    provider: str
    model: str


class GlobalDirection(BaseModel):
    tone: str
    base_pace: float
    dramatic_level: int
    max_energy: float
    avoid_overacting: bool


class BeatScript(BaseModel):
    text: str
    preserve_exact_text: bool = True

    @field_validator("text")
    @classmethod
    def validate_non_empty_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Script text cannot be empty.")
        return v.strip()


class Emphasis(BaseModel):
    text: str
    strength: EmphasisStrength = EmphasisStrength.MEDIUM


class PauseModel(BaseModel):
    before: float = 0.0
    after: float = 0.0

    @field_validator("before", "after")
    @classmethod
    def validate_non_negative_pause(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("Pause duration must be non-negative.")
        return v


class VoiceDirection(BaseModel):
    emotion: str
    energy: float
    pace: float | None = None
    target_wpm: int | None = None
    volume: str = "normal"
    emphasis: list[Emphasis] = Field(default_factory=list)
    pause: PauseModel
    director_note: str | None = None
    pronunciation: dict[str, str] = Field(default_factory=dict)

    @field_validator("energy")
    @classmethod
    def validate_energy_range(cls, v: float) -> float:
        if v < 0.0 or v > 5.0:
            raise ValueError("Energy must be between 0.0 and 5.0.")
        return v


class AmbienceIntent(BaseModel):
    intent: str
    intensity: str = "medium"
    volume_db: float = -29.0


class SFXIntent(BaseModel):
    intent: str
    placement: SFXPlacement
    anchor: str | None = None
    offset: float = 0.0
    intensity: str = "medium"
    necessity: float = 0.5
    max_volume_db: float = -24.0

    @field_validator("necessity")
    @classmethod
    def validate_necessity_range(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError("SFX necessity must be between 0.0 and 1.0.")
        return v


class SilenceAfter(BaseModel):
    duration: float
    reason: str | None = None

    @field_validator("duration")
    @classmethod
    def validate_non_negative_duration(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("Silence duration must be non-negative.")
        return v


class SilenceDecision(BaseModel):
    after: SilenceAfter | None = None


class Beat(BaseModel):
    id: str
    role: BeatRole
    script: BeatScript
    voice: VoiceDirection
    ambience: AmbienceIntent | None = None
    sfx: list[SFXIntent] = Field(default_factory=list)
    silence: SilenceDecision | None = None


class VoicePlan(BaseModel):
    version: int = 1
    project: ProjectMetadata
    voice: VoiceMetadata
    global_direction: GlobalDirection
    beats: list[Beat] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert VoicePlan to a nested dictionary using standard serialization."""
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        """Serialize VoicePlan to YAML string."""
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoicePlan:
        """Load VoicePlan from dictionary."""
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> VoicePlan:
        """Load VoicePlan from YAML string."""
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)


def build_voice_plan(
    project_data: dict[str, Any],
    segments: list[dict[str, Any]],
    voice_profile: str | None = None,
    global_direction: dict[str, Any] | None = None,
    default_beat_role: BeatRole = BeatRole.DESCRIPTION,
) -> VoicePlan:
    """Build a complete VoicePlan from existing project metadata and planned segments.

    Acts as a compatibility layer that maps older segment structure (WPM, ms pauses, simple emphasis list,
    scaled energy) to the new domain models.
    """
    proj_id = project_data.get("id", "unknown_project")
    proj_title = project_data.get("topic", "Untitled Project")
    requirements = project_data.get("requirements", {})

    # 1. Project Metadata
    script_text = project_data.get("script", {}).get("full_text", "")
    if not script_text and segments:
        script_text = "\n".join(seg.get("text", "") for seg in segments)

    project_meta = ProjectMetadata(
        id=proj_id,
        title=proj_title,
        language=requirements.get("language_id", "en-US"),
        source_script=script_text
    )

    # 2. Voice Metadata
    voice_meta = VoiceMetadata(
        profile=voice_profile or requirements.get("character_id", "mythology_female_v1"),
        provider="gemini",
        model=project_data.get("voice_plan", {}).get("default_model", "gemini-3.1-flash-tts-preview")
    )

    # 3. Global Direction
    if not global_direction:
        global_direction = {}

    derived_pace = 0.92
    if segments:
        first_seg_plan = segments[0].get("narration_plan", {})
        if first_seg_plan and "target_wpm" in first_seg_plan:
            derived_pace = round(first_seg_plan["target_wpm"] / 138.0, 2)

    global_dir_model = GlobalDirection(
        tone=global_direction.get("tone", "mysterious_cinematic"),
        base_pace=global_direction.get("base_pace", derived_pace),
        dramatic_level=global_direction.get("dramatic_level", 3),
        max_energy=global_direction.get("max_energy", 5.0),
        avoid_overacting=global_direction.get("avoid_overacting", True)
    )

    # 4. Beats
    beats_list = []
    for idx, seg in enumerate(segments, 1):
        seg_id = seg.get("id", f"B{idx:02d}")
        text = seg.get("text", "")
        if not text:
            continue

        # Use segment.beat_role if provided, otherwise default fallback
        role_str = seg.get("beat_role")
        if role_str:
            try:
                role_enum = BeatRole(role_str)
            except ValueError:
                role_enum = default_beat_role
        else:
            role_enum = default_beat_role

        # Ensure BeatScript always uses the raw segment text
        script_seg = BeatScript(
            text=text,
            preserve_exact_text=True
        )

        plan = seg.get("narration_plan", {})

        # Energy Mapping and Scaling (0-1 -> 0-5)
        old_energy = plan.get("energy", 0.5)
        # Apply the scaling logic exactly
        scaled_energy = min(5.0, max(0.0, float(old_energy) * 5.0))

        # Pacing and WPM resolution
        old_wpm = plan.get("target_wpm")
        
        # Determine float pace if supplied as float, else keep None as WPM is populated
        float_pace = None
        legacy_pace = plan.get("pace")
        if isinstance(legacy_pace, (int, float)):
            float_pace = float(legacy_pace)

        pause_before_sec = plan.get("pause_before_ms", 100) / 1000.0
        pause_after_sec = plan.get("pause_after_ms", 700) / 1000.0

        emphasis_list = []
        old_emphasis = plan.get("emphasis", [])
        for emp_item in old_emphasis:
            if isinstance(emp_item, dict):
                emp_text = emp_item.get("text", "")
                emp_str = emp_item.get("strength", "medium")
                emphasis_list.append(Emphasis(text=emp_text, strength=EmphasisStrength(emp_str)))
            else:
                emphasis_list.append(Emphasis(text=str(emp_item), strength=EmphasisStrength.MEDIUM))

        pause_model = PauseModel(before=pause_before_sec, after=pause_after_sec)

        voice_dir = VoiceDirection(
            emotion=plan.get("emotion", seg.get("emotion", "engaging")),
            energy=scaled_energy,
            pace=float_pace,
            target_wpm=old_wpm,
            volume="normal",
            emphasis=emphasis_list,
            pause=pause_model,
            director_note=None,
            pronunciation=plan.get("pronunciation", {})
        )

        silence_decision = None
        if pause_after_sec > 1.0:
            silence_decision = SilenceDecision(
                after=SilenceAfter(duration=pause_after_sec, reason="let_beat_resonate")
            )

        beat_obj = Beat(
            id=seg_id,
            role=role_enum,
            script=script_seg,
            voice=voice_dir,
            ambience=None,
            sfx=[],
            silence=silence_decision
        )
        beats_list.append(beat_obj)

    return VoicePlan(
        version=1,
        project=project_meta,
        voice=voice_meta,
        global_direction=global_dir_model,
        beats=beats_list
    )
