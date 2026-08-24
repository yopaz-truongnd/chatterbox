"""Deterministic Mix Plan Builder (Phase 14).

Constructs an immutable, fully deterministic multi-track MixPlan from:
- VoicePlan (sequence, direction, scene structure, pauses)
- RenderManifest (selected attempt per beat, audio paths)
- ResourceReport (resolved audio assets, ambience, SFX)
- Mixing and mastering configuration profiles
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
from typing import Any
import wave
import yaml

from services.audio_mix_models import (
    AmbienceClip,
    DuckingRule,
    ExportProfile,
    MasteringProfile,
    MixPlan,
    SFXClip,
    SFXPlacement,
    SilenceRegion,
    VoiceClip,
)
from services.render_models import RenderManifest, RenderStatus
from services.resource_models import ResourceReport
from services.voice_plan import VoicePlan
from services.voice_project_models import InvalidProjectStateError, compute_file_sha256

logger = logging.getLogger(__name__)

DEFAULT_MIXING_RULES_PATH = Path("rules/mixing.yaml")
DEFAULT_MASTERING_RULES_PATH = Path("rules/mastering.yaml")


def load_mixing_rules(rules_path: Path | str | None = None) -> dict[str, Any]:
    """Load mixing rules from YAML."""
    path = Path(rules_path or DEFAULT_MIXING_RULES_PATH)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def load_mastering_rules(rules_path: Path | str | None = None) -> dict[str, Any]:
    """Load mastering profiles from YAML."""
    path = Path(rules_path or DEFAULT_MASTERING_RULES_PATH)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def get_wav_duration_ms(wav_path: Path | str) -> float:
    """Read precise audio duration in milliseconds from standard WAV header."""
    path = Path(wav_path)
    if not path.exists():
        return 0.0
    try:
        with wave.open(str(path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            if rate <= 0:
                return 0.0
            return (frames / float(rate)) * 1000.0
    except Exception as exc:
        logger.warning("Failed to read WAV duration from '%s': %s", wav_path, exc)
        return 0.0


class MixPlanBuilder:
    """Constructs deterministic multi-track MixPlan."""

    def __init__(self, rules_path: Path | str | None = None) -> None:
        self.mixing_rules = load_mixing_rules(rules_path)
        self.mastering_rules = load_mastering_rules()

    def build(
        self,
        project_id: str,
        voice_plan: VoicePlan,
        render_manifest: RenderManifest,
        proj_dir: Path | str,
        resource_report: ResourceReport | None = None,
        mix_config: dict[str, Any] | None = None,
        mastering_profile: MasteringProfile | None = None,
        export_profiles: list[ExportProfile] | None = None,
    ) -> MixPlan:
        """Build deterministic MixPlan from validated project narration and sound design."""
        project_root = Path(proj_dir)
        cfg = mix_config or {}

        # Resolve rules
        def_rules = self.mixing_rules.get("default_profile", {})
        prof_name = cfg.get("profile", "storytelling")
        prof_rules = self.mixing_rules.get("profiles", {}).get(prof_name, {})

        pause_between_beats_ms = float(
            cfg.get(
                "pause_between_beats_ms",
                prof_rules.get("pause_between_beats_ms", def_rules.get("pause_between_beats_ms", 600)),
            )
        )
        fade_in_ms = float(cfg.get("fade_in_ms", def_rules.get("fade_in_ms", 20.0)))
        fade_out_ms = float(cfg.get("fade_out_ms", def_rules.get("fade_out_ms", 20.0)))
        ambience_gain_db = float(
            prof_rules.get("ambience_default_gain_db", def_rules.get("ambience_default_gain_db", -18.0))
        )
        sfx_gain_db = float(prof_rules.get("sfx_default_gain_db", def_rules.get("sfx_default_gain_db", -6.0)))

        # Resolve mastering profile
        if mastering_profile is None:
            m_profiles = self.mastering_rules.get("profiles", {})
            m_data = m_profiles.get("storytelling", {})
            mastering_profile = MasteringProfile(
                name="storytelling",
                target_lufs=float(m_data.get("target_lufs", -16.0)),
                true_peak_dbtp=float(m_data.get("true_peak_dbtp", -1.0)),
                sample_rate=int(m_data.get("sample_rate", 44100)),
                channels=int(m_data.get("channels", 1)),
                limiter_enabled=bool(m_data.get("limiter_enabled", True)),
            )

        if export_profiles is None:
            export_profiles = [
                ExportProfile(
                    format="wav",
                    sample_rate=mastering_profile.sample_rate,
                    channels=mastering_profile.channels,
                )
            ]

        # 1. Validate all beats in voice_plan have selected passing attempt
        voice_clips: list[VoiceClip] = []
        silence_regions: list[SilenceRegion] = []
        current_time_ms = 0.0

        for idx, beat in enumerate(voice_plan.beats):
            b_manifest = render_manifest.beats.get(beat.id)
            if not b_manifest or b_manifest.selected_attempt is None:
                raise InvalidProjectStateError(
                    f"Beat '{beat.id}' does not have a selected passing render attempt. "
                    "All beats must be rendered and passed before mixing."
                )

            selected_attempt_id = b_manifest.selected_attempt
            attempt = next((a for a in b_manifest.attempts if a.attempt == selected_attempt_id), None)
            if not attempt:
                raise InvalidProjectStateError(
                    f"Selected attempt {selected_attempt_id} for beat '{beat.id}' was not found in manifest."
                )

            audio_path = Path(attempt.audio_path)
            if not audio_path.is_absolute():
                audio_path = project_root / audio_path

            if not audio_path.exists():
                raise InvalidProjectStateError(
                    f"Audio file for beat '{beat.id}' (attempt {selected_attempt_id}) not found at '{audio_path}'."
                )

            duration_ms = get_wav_duration_ms(audio_path)
            if duration_ms <= 0:
                duration_ms = 1000.0  # Fallback duration if unreadable

            sha256 = compute_file_sha256(audio_path) if audio_path.exists() else ""

            # Check for per-beat custom pause
            beat_pause = pause_between_beats_ms
            if hasattr(beat, "direction") and getattr(beat.direction, "pause_after", None):
                beat_pause = float(beat.direction.pause_after) * 1000.0

            clip = VoiceClip(
                beat_id=beat.id,
                selected_attempt=selected_attempt_id,
                source_path=str(audio_path.relative_to(project_root) if audio_path.is_relative_to(project_root) else audio_path),
                source_sha256=sha256,
                start_ms=current_time_ms,
                duration_ms=duration_ms,
                gain_db=0.0,
                fade_in_ms=fade_in_ms,
                fade_out_ms=fade_out_ms,
            )
            voice_clips.append(clip)

            current_time_ms += duration_ms

            # Append silence region after beat if not last beat
            if idx < len(voice_plan.beats) - 1:
                silence_regions.append(
                    SilenceRegion(
                        start_ms=current_time_ms,
                        duration_ms=beat_pause,
                        reason="beat_pause",
                    )
                )
                current_time_ms += beat_pause

        # 2. Place Ambience Clips
        ambience_clips: list[AmbienceClip] = []
        if resource_report:
            resolutions = getattr(resource_report, "resolved", []) + getattr(resource_report, "substituted", [])
            for res in resolutions:
                res_type = getattr(res, "type", "")
                type_val = res_type.value if hasattr(res_type, "value") else str(res_type)
                if type_val == "ambience" and getattr(res, "selected", None):
                    entry = res.selected
                    f_obj = getattr(entry, "file", None)
                    if f_obj and getattr(f_obj, "path", None):
                        asset_path = Path(f_obj.path)
                        if not asset_path.is_absolute():
                            asset_path = project_root / asset_path
                        if asset_path.exists():
                            ambience_clips.append(
                                AmbienceClip(
                                    resource_id=getattr(entry, "id", "ambience"),
                                    source_path=str(asset_path),
                                    source_sha256=compute_file_sha256(asset_path),
                                    start_ms=0.0,
                                    end_ms=current_time_ms,
                                    gain_db=ambience_gain_db,
                                    loop=True,
                                )
                            )

        # 3. Place SFX Clips
        sfx_clips: list[SFXClip] = []
        offset_rules = def_rules.get("sfx_placement_offsets_ms", {"PRE": -400, "UNDER": 0, "POST": 200, "BRIDGE": 0})
        # Check sound direction cues from voice_plan
        for beat in voice_plan.beats:
            sound_dir = getattr(beat, "sound_direction", None)
            if sound_dir and hasattr(sound_dir, "sfx_cues") and sound_dir.sfx_cues:
                for cue in sound_dir.sfx_cues:
                    # Find matching clip
                    matching_vclip = next((v for v in voice_clips if v.beat_id == beat.id), None)
                    if matching_vclip:
                        placement_str = str(getattr(cue, "placement", "UNDER")).upper()
                        placement = SFXPlacement.UNDER
                        try:
                            placement = SFXPlacement(placement_str)
                        except ValueError:
                            placement = SFXPlacement.UNDER

                        offset_ms = float(offset_rules.get(placement.value, 0))
                        if placement == SFXPlacement.PRE:
                            start_ms = max(0.0, matching_vclip.start_ms + offset_ms)
                        elif placement == SFXPlacement.POST:
                            start_ms = matching_vclip.start_ms + matching_vclip.duration_ms + offset_ms
                        else:  # UNDER / BRIDGE
                            start_ms = matching_vclip.start_ms

                        sfx_clips.append(
                            SFXClip(
                                resource_id=getattr(cue, "cue_id", "sfx_cue"),
                                source_path=getattr(cue, "source_path", ""),
                                beat_id=beat.id,
                                placement=placement,
                                start_ms=start_ms,
                                duration_ms=float(getattr(cue, "duration_ms", 1500.0)),
                                gain_db=sfx_gain_db,
                            )
                        )

        # 4. Ducking rules
        ducking_rules = [
            DuckingRule(
                target_track="ambience",
                duck_gain_db=float(def_rules.get("ducking", {}).get("duck_gain_db", -12.0)),
                attack_ms=float(def_rules.get("ducking", {}).get("attack_ms", 50.0)),
                release_ms=float(def_rules.get("ducking", {}).get("release_ms", 200.0)),
            )
        ]

        # 5. Dependency hashes
        dep_hashes = {
            "voice_plan_sha256": compute_file_sha256(project_root / "voice-plan.yaml") if (project_root / "voice-plan.yaml").exists() else "",
            "render_manifest_sha256": compute_file_sha256(project_root / "render-manifest.yaml") if (project_root / "render-manifest.yaml").exists() else "",
            "resource_report_sha256": compute_file_sha256(project_root / "resource-report.yaml") if (project_root / "resource-report.yaml").exists() else "",
        }

        total_duration_ms = current_time_ms

        return MixPlan(
            project_id=project_id,
            duration_ms=round(total_duration_ms, 2),
            sample_rate=mastering_profile.sample_rate,
            channels=mastering_profile.channels,
            voice_clips=voice_clips,
            ambience_clips=ambience_clips,
            sfx_clips=sfx_clips,
            silence_regions=silence_regions,
            ducking_rules=ducking_rules,
            mastering_profile=mastering_profile,
            export_profiles=export_profiles,
            dependency_hashes=dep_hashes,
        )
