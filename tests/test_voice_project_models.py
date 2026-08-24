"""Unit tests for VoiceProject models, DTOs, hashes, and error types (Phase 11)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.render_models import ProjectState, ProjectStatus
from services.voice_project_models import (
    HumanActionRequired,
    HumanActionType,
    InvalidProjectStateError,
    ResourceCheckResult,
    StaleArtifactError,
    VoicePlanningResult,
    VoiceProjectNotFound,
    VoiceProjectSummary,
    VoiceRenderResult,
    compute_file_sha256,
    compute_string_sha256,
)


class TestVoiceProjectModelsPhase11(unittest.TestCase):

    def test_sha256_computations(self):
        text = "Hello World"
        sha = compute_string_sha256(text)
        self.assertEqual(len(sha), 64)

        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(text)
            tmp_path = Path(f.name)

        try:
            file_sha = compute_file_sha256(tmp_path)
            self.assertEqual(sha, file_sha)
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_human_action_model(self):
        action = HumanActionRequired(
            action_type=HumanActionType.RESOURCE_REQUIRED,
            reason="Missing required pronunciation",
            items=["Zhulong"],
        )
        self.assertEqual(action.action_type, HumanActionType.RESOURCE_REQUIRED)
        self.assertEqual(action.items, ["Zhulong"])

    def test_voice_project_summary_serialization(self):
        summary = VoiceProjectSummary(
            project_id="p1",
            title="Project 1",
            stage=ProjectStatus.READY_TO_RENDER,
            total_beats=5,
            passed_beats=5,
            resource_readiness_score=100.0,
            suggested_action="Run render()",
        )
        d = summary.to_dict()
        self.assertEqual(d["project_id"], "p1")
        self.assertEqual(d["stage"], "READY_TO_RENDER")
        self.assertEqual(d["total_beats"], 5)

    def test_project_state_legacy_status_sync(self):
        state = ProjectState(
            project_id="p1",
            stage=ProjectStatus.PLANNED,
        )
        state.sync_legacy_status()
        self.assertTrue(state.status.story_analyzed)
        self.assertTrue(state.status.voice_plan_ready)
        self.assertFalse(state.status.resources_checked)
        self.assertFalse(state.status.narration_ready)

        state.stage = ProjectStatus.NARRATION_READY
        state.sync_legacy_status()
        self.assertTrue(state.status.narration_ready)


if __name__ == "__main__":
    unittest.main()
