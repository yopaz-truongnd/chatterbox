"""End-to-End Acceptance Tests for VoiceProjectService & Unified Lifecycle (Phase 11)."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from services.render_models import ProjectStatus, RenderStatus
from services.tts.fake import FakeTTSProvider
from services.voice_project_models import (
    HumanActionType,
    ResourceBlockedError,
    StaleArtifactError,
)
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore


class TestVoiceProjectE2E(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="voice_proj_e2e_"))
        self.store = VoiceProjectStore(root_dir=self.temp_dir)
        self.fake_provider = FakeTTSProvider(sample_rate=24000)
        self.service = VoiceProjectService(
            store=self.store,
            execution_port=self.fake_provider,
            provider_name="fake",
        )

        self.initial_script = (
            "In ancient times before the dawn of human kings.\n\n"
            "When Zhulong opened its eyes, eternal daylight illuminated the cosmic darkness.\n\n"
            "Across the northern peaks, Taotie devoured the shadows of the silent valleys."
        )

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_application_lifecycle_and_source_immutability(self):
        project_id = "torch_dragon_e2e"

        # 1. Create project
        state = self.service.create_project(
            script_text=self.initial_script,
            project_id=project_id,
            title="Torch Dragon E2E",
        )
        self.assertEqual(state.stage, ProjectStatus.NEW)
        original_source_bytes = (self.store.get_project_dir(project_id) / "source" / "script.txt").read_bytes()

        # 2. High-level plan()
        plan_result = self.service.plan(project_id)
        self.assertEqual(plan_result.stage, ProjectStatus.PLANNED)
        self.assertEqual(plan_result.beat_count, 3)

        # 3. High-level check_resources()
        res_result = self.service.check_resources(project_id)
        self.assertEqual(res_result.stage, ProjectStatus.READY_TO_RENDER)
        self.assertFalse(res_result.render_blocked)

        # 4. High-level render()
        render_result = self.service.render(project_id)
        self.assertEqual(render_result.stage, ProjectStatus.NARRATION_READY)
        self.assertEqual(render_result.total_beats, 3)
        self.assertEqual(render_result.passed_beats, 3)

        # 5. High-level evaluate() without re-synthesizing
        eval_result = self.service.evaluate(project_id)
        self.assertEqual(eval_result.stage, ProjectStatus.NARRATION_READY)
        self.assertEqual(eval_result.passed_beats, 3)

        # 6. Agent-facing summary
        summary = self.service.get_project(project_id)
        self.assertEqual(summary.stage, ProjectStatus.NARRATION_READY)
        self.assertEqual(summary.total_beats, 3)
        self.assertEqual(summary.passed_beats, 3)
        self.assertIsNone(summary.human_action)

        # 7. Invariant: Source script immutability (byte-for-byte identical)
        final_source_bytes = (self.store.get_project_dir(project_id) / "source" / "script.txt").read_bytes()
        self.assertEqual(original_source_bytes, final_source_bytes)

    def test_idempotent_render_skips_already_passed_beats(self):
        project_id = "idempotent_proj"
        self.service.create_project(self.initial_script, project_id)
        self.service.plan(project_id)
        self.service.check_resources(project_id)

        # First render
        r1 = self.service.render(project_id)
        self.assertEqual(r1.passed_beats, 3)

        # Calling render again should skip passed beats (resumption)
        r2 = self.service.render(project_id)
        self.assertEqual(r2.stage, ProjectStatus.NARRATION_READY)
        self.assertEqual(r2.passed_beats, 3)

    def test_update_script_enforces_replanning(self):
        project_id = "update_script_proj"
        self.service.create_project(self.initial_script, project_id)
        self.service.plan(project_id)
        self.service.check_resources(project_id)

        # Update script
        new_script = "Revised story of ancient gods and dragons."
        self.service.update_script(project_id, new_script)

        # Summary should reflect NEW stage
        summary = self.service.get_project(project_id)
        self.assertEqual(summary.stage, ProjectStatus.NEW)

        # Render should fail with StaleArtifactError
        with self.assertRaises(StaleArtifactError):
            self.service.render(project_id)

        # Re-planning allows proceeding
        self.service.plan(project_id)
        self.service.check_resources(project_id)
        r = self.service.render(project_id)
        self.assertEqual(r.stage, ProjectStatus.NARRATION_READY)


if __name__ == "__main__":
    unittest.main()
