"""Unit tests for VoiceProjectService application orchestration (Phase 11)."""

from __future__ import annotations

import io
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import wave
from unittest import mock

from services.render_models import BeatRenderState, ProjectStatus, RenderManifest, RenderStatus
from services.resource_models import RequirementPriority, ResourceGap
from services.tts.fake import FakeTTSProvider
from services.voice_project_models import (
    BeatNotFoundError,
    HumanActionType,
    ResourceBlockedError,
    InvalidProjectStateError,
    StaleArtifactError,
)
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore


class TestVoiceProjectServicePhase11(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="svc_test_"))
        self.store = VoiceProjectStore(root_dir=self.temp_dir)
        self.fake_provider = FakeTTSProvider(sample_rate=24000)
        self.service = VoiceProjectService(
            store=self.store,
            execution_port=self.fake_provider,
            provider_name="fake",
        )
        self.script_content = (
            "In ancient times before the dawn of human kings.\n\n"
            "When Zhulong opened its eyes, eternal daylight illuminated the cosmic darkness."
        )

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lifecycle_e2e_create_plan_resources_render(self):
        # 1. Create Project
        state = self.service.create_project(
            script_text=self.script_content,
            project_id="torch_dragon",
            title="Torch Dragon",
        )
        self.assertEqual(state.project_id, "torch_dragon")
        self.assertEqual(state.stage, ProjectStatus.NEW)

        # 2. Plan
        plan_res = self.service.plan("torch_dragon")
        self.assertEqual(plan_res.stage, ProjectStatus.PLANNED)
        self.assertTrue(plan_res.beat_count >= 1)
        self.assertTrue(Path(plan_res.voice_plan_path).exists())

        # 3. Check Resources
        res_check = self.service.check_resources("torch_dragon")
        self.assertFalse(res_check.render_blocked)
        self.assertEqual(res_check.stage, ProjectStatus.READY_TO_RENDER)
        self.assertTrue(res_check.readiness_score > 0)

        # 4. Render
        render_res = self.service.render("torch_dragon")
        self.assertEqual(render_res.stage, ProjectStatus.NARRATION_READY)
        self.assertEqual(render_res.passed_beats, render_res.total_beats)
        self.assertEqual(render_res.failed_beats, 0)
        self.assertEqual(render_res.review_beats, 0)

        # 5. Project Summary
        summary = self.service.get_project("torch_dragon")
        self.assertEqual(summary.stage, ProjectStatus.NARRATION_READY)
        self.assertEqual(summary.passed_beats, summary.total_beats)
        self.assertIsNone(summary.human_action)

    def test_render_blocked_by_required_resource_gap(self):
        self.service.create_project(self.script_content, "blocked_proj")
        self.service.plan("blocked_proj")

        # Mock resource report with required missing gap
        report = self.store.load_resource_report("blocked_proj")
        if not report:
            self.service.check_resources("blocked_proj")
            report = self.store.load_resource_report("blocked_proj")

        # Inject a required gap
        from services.resource_models import ResourceCategory
        report.missing.append(
            ResourceGap(
                id="gap_custom",
                type=ResourceCategory.KNOWLEDGE,
                priority=RequirementPriority.REQUIRED,
                term="CustomEntity",
                reason="Unverified proper noun",
            )
        )
        report.readiness.render_blocked = True
        report.readiness.block_reasons.append("Missing required proper noun CustomEntity")
        self.store.save_resource_report("blocked_proj", report)

        # Verify summary reports resource blocked and human action
        summary = self.service.get_project("blocked_proj")
        self.assertTrue(summary.resource_blocked)
        self.assertEqual(summary.stage, ProjectStatus.RESOURCE_BLOCKED)
        self.assertIsNotNone(summary.human_action)
        self.assertEqual(summary.human_action.action_type, HumanActionType.RESOURCE_REQUIRED)

        # Render should be rejected
        with self.assertRaises(ResourceBlockedError):
            self.service.render("blocked_proj")

    def test_stale_plan_rejects_render(self):
        self.service.create_project(self.script_content, "stale_proj")
        self.service.plan("stale_proj")
        self.service.check_resources("stale_proj")

        # Update source script without re-planning
        self.service.update_script("stale_proj", "A completely new modified script text.")

        # Render should fail with StaleArtifactError
        with self.assertRaises(StaleArtifactError):
            self.service.render("stale_proj")

    def test_render_requires_resource_check(self):
        self.service.create_project(self.script_content, "unready_proj")
        self.service.plan("unready_proj")

        with self.assertRaises((InvalidProjectStateError, StaleArtifactError)):
            self.service.render("unready_proj")

    def test_plan_rejects_transient_state(self):
        self.service.create_project(self.script_content, "busy_proj")
        state = self.store.get_project_state("busy_proj")
        state.stage = ProjectStatus.RENDERING
        self.store.save_project_state(state)

        with self.assertRaises(InvalidProjectStateError):
            self.service.plan("busy_proj")

    def test_render_beat_selective_and_invalid_beat_id(self):
        self.service.create_project(self.script_content, "beat_proj")
        self.service.plan("beat_proj")
        self.service.check_resources("beat_proj")

        # Nonexistent beat ID
        with self.assertRaises(BeatNotFoundError):
            self.service.render_beat("beat_proj", "B99_INVALID")

        # Valid beat ID
        res = self.service.render_beat("beat_proj", "B01")
        self.assertIn("B01", res.manifest.beats)
        self.assertEqual(res.manifest.beats["B01"].status, RenderStatus.PASSED)

    def test_evaluate_qc_without_synthesizing(self):
        self.service.create_project(self.script_content, "qc_proj")
        self.service.plan("qc_proj")
        self.service.check_resources("qc_proj")
        self.service.render("qc_proj")

        # Run evaluate() to re-assess QC
        eval_res = self.service.evaluate("qc_proj")
        self.assertEqual(eval_res.stage, ProjectStatus.NARRATION_READY)
        self.assertEqual(eval_res.passed_beats, eval_res.total_beats)

    def test_qc_failed_beat_fails_project(self):
        self.service.create_project(self.script_content, "qc_failed_proj")
        self.service.plan("qc_failed_proj")
        self.service.check_resources("qc_failed_proj")
        manifest = RenderManifest(
            project_id="qc_failed_proj",
            beats={"B01": BeatRenderState(beat_id="B01", status=RenderStatus.QC_FAILED)},
        )

        with mock.patch(
            "services.voice_project_service.render_project_narration",
            return_value=(manifest, {}),
        ) as render_mock:
            result = self.service.render("qc_failed_proj", max_retries=1)

        self.assertEqual(result.stage, ProjectStatus.FAILED)
        self.assertEqual(result.failed_beats, 1)
        self.assertEqual(render_mock.call_args.kwargs["max_retries"], 1)

    def test_render_unknown_beat_ids_raises_beat_not_found(self):
        self.service.create_project(self.script_content, "unk_render_proj")
        self.service.plan("unk_render_proj")
        self.service.check_resources("unk_render_proj")

        with self.assertRaises(BeatNotFoundError):
            self.service.render("unk_render_proj", beats=["B999_UNKNOWN"])

    def test_evaluate_unknown_beat_ids_raises_beat_not_found(self):
        self.service.create_project(self.script_content, "unk_eval_proj")
        self.service.plan("unk_eval_proj")
        self.service.check_resources("unk_eval_proj")
        self.service.render("unk_eval_proj")

        with self.assertRaises(BeatNotFoundError):
            self.service.evaluate("unk_eval_proj", beats=["B999_UNKNOWN"])

    def test_render_rejects_when_resource_report_missing_even_if_status_failed(self):
        self.service.create_project(self.script_content, "failed_no_rep_proj")
        self.service.plan("failed_no_rep_proj")
        state = self.store.get_project_state("failed_no_rep_proj")
        state.stage = ProjectStatus.FAILED
        self.store.save_project_state(state)

        with self.assertRaises((InvalidProjectStateError, StaleArtifactError)):
            self.service.render("failed_no_rep_proj")


if __name__ == "__main__":
    unittest.main()
