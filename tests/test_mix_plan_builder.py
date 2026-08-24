"""Unit tests for Deterministic Mix Plan Builder (Phase 14)."""

import os
from pathlib import Path
import tempfile
import unittest
import wave

from services.audio_mix_models import MasteringProfile, MixPlan, SFXPlacement
from services.mix_plan_builder import MixPlanBuilder
from services.resource_models import (
    ReadinessReport,
    ResolutionStatus,
    ResourceCategory,
    ResourceEntry,
    ResourceFile,
    ResourceProperties,
    ResourceReport,
    ResourceResolution,
)
from services.voice_plan import (
    SFXIntent,
    SFXPlacement as PlanSFXPlacement,
    SilenceAfter,
    SilenceDecision,
)
from services.voice_project_models import InvalidProjectStateError
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore


def _create_mock_wav(path: Path, duration_s: float = 1.0, sample_rate: int = 44100):
    """Helper to generate a clean silent WAV fixture for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        nframes = int(duration_s * sample_rate)
        wf.writeframes(b"\x00\x00" * nframes)


class TestMixPlanBuilder(unittest.TestCase):
    """Test deterministic MixPlan generation and validation."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceProjectStore(root_dir=Path(self.temp_dir.name) / "projects")
        self.service = VoiceProjectService(store=self.store, provider_name="fake")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mix_plan_builder_constructs_deterministic_timeline(self):
        script = "The morning sun rose gently over the calm green valley."
        self.service.create_project(project_id="mix_proj_01", script_text=script)
        self.service.plan("mix_proj_01")
        self.service.check_resources("mix_proj_01")
        self.service.render("mix_proj_01")

        builder = MixPlanBuilder()
        plan = self.store.load_voice_plan("mix_proj_01")
        manifest = self.store.load_manifest("mix_proj_01")
        proj_dir = self.store.get_project_dir("mix_proj_01")

        mix_plan1 = builder.build(
            project_id="mix_proj_01",
            voice_plan=plan,
            render_manifest=manifest,
            proj_dir=proj_dir,
        )

        mix_plan2 = builder.build(
            project_id="mix_proj_01",
            voice_plan=plan,
            render_manifest=manifest,
            proj_dir=proj_dir,
        )

        # Determinism check: multiple builds from same input produce identical timeline & hashes
        self.assertEqual(mix_plan1.duration_ms, mix_plan2.duration_ms)
        self.assertEqual(len(mix_plan1.voice_clips), len(mix_plan2.voice_clips))
        self.assertEqual(mix_plan1.voice_clips[0].start_ms, mix_plan2.voice_clips[0].start_ms)
        self.assertEqual(mix_plan1.dependency_hashes, mix_plan2.dependency_hashes)

    def test_mix_plan_resolves_sfx_from_beat_and_resource_report(self):
        script = "The morning sun rose gently over the calm green valley."
        self.service.create_project(project_id="sfx_proj", script_text=script)
        self.service.plan("sfx_proj")
        self.service.check_resources("sfx_proj")
        self.service.render("sfx_proj")

        proj_dir = self.store.get_project_dir("sfx_proj")
        plan = self.store.load_voice_plan("sfx_proj")
        manifest = self.store.load_manifest("sfx_proj")

        # Create dummy thunder WAV
        thunder_wav = proj_dir / "assets" / "thunder.wav"
        _create_mock_wav(thunder_wav, duration_s=1.5)

        # Add SFX intent to beat 0
        b0 = plan.beats[0]
        b0.sfx = [
            SFXIntent(
                intent="thunder",
                placement=PlanSFXPlacement.PRE,
                offset=-0.2,
                max_volume_db=-18.0,
            )
        ]
        # Add custom silence after
        b0.silence = SilenceDecision(after=SilenceAfter(duration=2.5, reason="dramatic_pause"))

        # Construct ResourceReport with resolved thunder asset
        res_report = ResourceReport(
            project_id="sfx_proj",
            readiness=ReadinessReport(score=100),
            resolved=[
                ResourceResolution(
                    type=ResourceCategory.SFX,
                    requested_intent="thunder",
                    beat_id=b0.id,
                    status=ResolutionStatus.EXACT,
                    selected=ResourceEntry(
                        id="sfx_thunder_01",
                        category=ResourceCategory.SFX,
                        intents=["thunder"],
                        file=ResourceFile(path=str(thunder_wav), format="wav"),
                        properties=ResourceProperties(duration=1.5),
                    ),
                )
            ],
        )

        builder = MixPlanBuilder()
        mix_plan = builder.build(
            project_id="sfx_proj",
            voice_plan=plan,
            render_manifest=manifest,
            proj_dir=proj_dir,
            resource_report=res_report,
        )

        # Verify SFX clip exists with PRE placement
        self.assertEqual(len(mix_plan.sfx_clips), 1)
        sfx_clip = mix_plan.sfx_clips[0]
        self.assertEqual(sfx_clip.resource_id, "sfx_thunder_01")
        self.assertEqual(sfx_clip.placement, SFXPlacement.PRE)
        self.assertEqual(sfx_clip.gain_db, -18.0)

        # Verify silence regions respects explicit silence decision (2500 ms)
        if len(plan.beats) > 1:
            self.assertTrue(any(sr.duration_ms == 2500.0 for sr in mix_plan.silence_regions))

    def test_mix_plan_fails_if_beats_unrendered(self):
        script = "The morning sun rose gently over the calm green valley."
        self.service.create_project(project_id="unrendered_proj", script_text=script)
        self.service.plan("unrendered_proj")

        plan = self.store.load_voice_plan("unrendered_proj")
        manifest = self.store.load_manifest("unrendered_proj")
        proj_dir = self.store.get_project_dir("unrendered_proj")
        builder = MixPlanBuilder()

        with self.assertRaises(InvalidProjectStateError):
            builder.build(
                project_id="unrendered_proj",
                voice_plan=plan,
                render_manifest=manifest,
                proj_dir=proj_dir,
            )


if __name__ == "__main__":
    unittest.main()
