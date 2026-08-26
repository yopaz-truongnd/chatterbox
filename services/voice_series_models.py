"""Story Series & Batch Production Domain Models (Phase 19).

Defines typed schemas for multi-episode story series, shared bibles
(Voice, Pronunciation, Sound), batch production summaries, and human review gates.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import yaml
from pydantic import BaseModel, Field, field_validator


class SeriesStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class EpisodeStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PRODUCING = "producing"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def make_safe_slug(text: str) -> str:
    """Generate a filesystem-safe normalized slug without path traversal risks."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    slug = re.sub(r"[\s_-]+", "-", text).strip("-")
    if not slug or ".." in slug:
        return "series"
    return slug


class SeriesVoiceBible(BaseModel):
    """Voice characteristics shared across all episodes in a series."""

    narrator_character: str | None = None
    narrator_reference_voice: str | None = None
    provider: str = "local"
    model: str | None = None
    language: str = "en"
    voice_style: str | None = None


class SeriesPronunciationBible(BaseModel):
    """Mythology proper noun pronunciation dictionary shared across a series."""

    overrides: dict[str, str] = Field(default_factory=dict)
    # mapping of term -> phoneme / IPA / alias override


class SeriesSoundBible(BaseModel):
    """Aesthetic sound design palette and mastering standards across a series."""

    ambience_palette: list[str] = Field(default_factory=list)
    sfx_palette: list[str] = Field(default_factory=list)
    mastering_profile: str = "storytelling"
    loudness_target_lufs: float = -23.0
    output_formats: list[str] = Field(default_factory=lambda: ["wav"])


class SeriesProductionPolicy(BaseModel):
    """Execution rules and concurrency controls for batch series production."""

    max_parallel_episodes: int = Field(default=2, ge=1, le=10)
    stop_on_required_gap: bool = True
    continue_unrelated_on_gap: bool = True
    require_human_approval: bool = False


class VoiceSeries(BaseModel):
    """Top-level multi-episode series record."""

    series_id: str
    title: str
    description: str | None = None
    language: str = "en"
    episode_order: list[str] = Field(default_factory=list)
    voice_bible: SeriesVoiceBible = Field(default_factory=SeriesVoiceBible)
    pronunciation_bible: SeriesPronunciationBible = Field(default_factory=SeriesPronunciationBible)
    sound_bible: SeriesSoundBible = Field(default_factory=SeriesSoundBible)
    production_policy: SeriesProductionPolicy = Field(default_factory=SeriesProductionPolicy)
    status: SeriesStatus = SeriesStatus.DRAFT
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def slug(self) -> str:
        return make_safe_slug(self.title or self.series_id)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceSeries:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> VoiceSeries:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)


class VoiceSeriesEpisode(BaseModel):
    """An individual story episode within a series."""

    episode_id: str
    series_id: str
    project_id: str
    episode_number: int
    title: str
    status: EpisodeStatus = EpisodeStatus.PENDING
    workflow_id: str | None = None
    duration_ms: float | None = None
    final_artifacts: dict[str, str] = Field(default_factory=dict)
    required_gaps: list[str] = Field(default_factory=list)
    review_required: bool = False
    published_at: str | None = None
    error: dict[str, Any] | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceSeriesEpisode:
        return cls.model_validate(data)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> VoiceSeriesEpisode:
        data = yaml.safe_load(yaml_str) or {}
        return cls.from_dict(data)


class SeriesHumanAction(BaseModel):
    """A blocking human review gate for an episode within a series."""

    episode_id: str
    project_id: str
    action_type: str
    reason: str
    items: list[dict[str, Any]] = Field(default_factory=list)
    available_options: list[str] = Field(default_factory=list)
    artifact_id: str | None = None
    artifact_sha256: str | None = None


class SeriesProductionSummary(BaseModel):
    """Batch production outcome aggregated across all episodes in a series."""

    series_id: str
    operation_id: str = ""
    total_episodes: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    waiting_for_human: int = 0
    failed: int = 0
    cancelled: int = 0
    progress_percent: float = 0.0
    episode_results: list[dict[str, Any]] = Field(default_factory=list)
    human_actions: list[SeriesHumanAction] = Field(default_factory=list)
    suggested_action: str = ""
