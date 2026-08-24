"""Audio Mix, Mastering & Export Domain Models (Phase 14).

Defines strongly-typed contracts for MixPlan, VoiceClip, SFXClip, AmbienceClip,
DuckingRule, MasteringProfile, ExportProfile, and ExportManifest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
import wave
import yaml
from pydantic import BaseModel, Field


def get_wav_duration_ms(wav_path: Path | str) -> float:
    """Calculate exact duration of a WAV file in milliseconds."""
    p = Path(wav_path)
    if not p.exists():
        return 0.0
    try:
        with wave.open(str(p), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                return 0.0
            return (frames / float(rate)) * 1000.0
    except Exception:
        return 0.0


class SFXPlacement(str, Enum):
    PRE = "PRE"
    UNDER = "UNDER"
    POST = "POST"
    BRIDGE = "BRIDGE"


class VoiceClip(BaseModel):
    """Voice narration clip placed along the absolute mix timeline."""

    beat_id: str
    selected_attempt: int
    source_path: str
    source_sha256: str = ""
    start_ms: float
    duration_ms: float
    gain_db: float = 0.0
    fade_in_ms: float = 20.0
    fade_out_ms: float = 20.0


class SFXClip(BaseModel):
    """Sound effect asset clip placed relative to a narration beat."""

    resource_id: str
    source_path: str
    source_sha256: str = ""
    beat_id: str
    placement: SFXPlacement = SFXPlacement.UNDER
    anchor_ms: float = 0.0
    start_ms: float = 0.0
    duration_ms: float = 0.0
    gain_db: float = -6.0
    fade_in_ms: float = 50.0
    fade_out_ms: float = 50.0


class AmbienceClip(BaseModel):
    """Background atmosphere track spanned across scenes/beats."""

    resource_id: str
    source_path: str
    source_sha256: str = ""
    start_ms: float
    end_ms: float
    gain_db: float = -18.0
    loop: bool = True
    fade_in_ms: float = 500.0
    fade_out_ms: float = 500.0
    continuity_group: str = ""


class SilenceRegion(BaseModel):
    """Explicit pause or silence gap between narration beats."""

    start_ms: float
    duration_ms: float
    reason: str = "beat_pause"


class DuckingRule(BaseModel):
    """Voice-priority ducking envelope configuration."""

    target_track: str = "ambience"
    duck_gain_db: float = -12.0
    attack_ms: float = 50.0
    release_ms: float = 200.0


class MasteringProfile(BaseModel):
    """Target loudness and dynamics mastering configuration."""

    name: str = "storytelling"
    target_lufs: float = -16.0
    true_peak_dbtp: float = -1.0
    sample_rate: int = 44100
    channels: int = 1
    limiter_enabled: bool = True


class ExportProfile(BaseModel):
    """Output audio file format specification."""

    format: str = "wav"  # wav | mp3
    sample_rate: int = 44100
    channels: int = 1
    bit_depth: int = 16  # WAV
    bitrate: str = "192k"  # MP3


class MixPlan(BaseModel):
    """Complete, deterministic multi-track timeline plan for audio rendering."""

    project_id: str
    version: str = "1"
    duration_ms: float = 0.0
    sample_rate: int = 44100
    channels: int = 1
    voice_clips: list[VoiceClip] = Field(default_factory=list)
    ambience_clips: list[AmbienceClip] = Field(default_factory=list)
    sfx_clips: list[SFXClip] = Field(default_factory=list)
    silence_regions: list[SilenceRegion] = Field(default_factory=list)
    ducking_rules: list[DuckingRule] = Field(default_factory=list)
    mastering_profile: MasteringProfile = Field(default_factory=MasteringProfile)
    export_profiles: list[ExportProfile] = Field(
        default_factory=lambda: [ExportProfile(format="wav")]
    )
    dependency_hashes: dict[str, str] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MixPlan:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> MixPlan:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)


class MixArtifact(BaseModel):
    """Tracked audio artifact file metadata."""

    project_id: str
    artifact_id: str
    artifact_type: str  # mix_wav | master_wav | final_wav | final_mp3 | mix_plan | export_manifest
    file_path: str
    sha256: str = ""
    duration_ms: float = 0.0
    sample_rate: int = 44100
    channels: int = 1
    file_size_bytes: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class ExportManifest(BaseModel):
    """Manifest of final delivered audio deliverables."""

    project_id: str
    profiles: list[ExportProfile] = Field(default_factory=list)
    artifacts: list[MixArtifact] = Field(default_factory=list)
    source_master_sha256: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    def save_yaml(self, path: Path | str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(self.to_yaml())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExportManifest:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> ExportManifest:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)
