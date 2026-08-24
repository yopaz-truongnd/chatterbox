"""Unit tests for Deterministic Mix Plan Builder (Phase 14)."""

import os
from pathlib import Path
import tempfile
import unittest
import wave

from services.audio_mix_models import MasteringProfile, MixPlan
from services.mix_plan_builder import MixPlanBuilder
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
