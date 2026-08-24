"""Unit tests for VoiceProjectStore filesystem persistence (Phase 11)."""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from services.render_models import ProjectStatus
from services.voice_plan import (
    Beat,
    BeatRole,
    BeatScript,
    GlobalDirection,
    PauseModel,
    ProjectMetadata,
    VoiceDirection,
    VoiceMetadata,
    VoicePlan,
)
from services.voice_project_models import VoiceProjectNotFound
from services.voice_project_store import VoiceProjectStore


class TestVoiceProjectStorePhase11(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="store_test_"))
        self.store = VoiceProjectStore(root_dir=self.temp_dir)
        self.sample_script = "Beyond the northern seas rises Mount Zhong, where no mortal walks."

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_project_id_validation_rejects_path_traversal(self):
        with self.assertRaises(ValueError):
            self.store.validate_project_id("../../etc/passwd")

        with self.assertRaises(ValueError):
            self.store.validate_project_id("invalid/name")

        with self.assertRaises(ValueError):
            self.store.validate_project_id("has space")

        # Valid IDs
        self.store.validate_project_id("torch_dragon_01")
        self.store.validate_project_id("project-123")

    def test_create_workspace_and_atomic_persistence(self):
        state = self.store.create_workspace(
            project_id="torch_dragon",
            script_text=self.sample_script,
            title="Torch Dragon Story",
            language="en",
        )

        self.assertEqual(state.project_id, "torch_dragon")
        self.assertEqual(state.stage, ProjectStatus.NEW)
        self.assertTrue(len(state.artifacts.source_sha256) == 64)

        proj_dir = self.store.get_project_dir("torch_dragon")
        self.assertTrue((proj_dir / "project.yaml").exists())
        self.assertTrue((proj_dir / "source" / "script.txt").exists())
        self.assertTrue((proj_dir / "renders").exists())
        self.assertTrue((proj_dir / "qc").exists())

        # Exact script preservation
        read_script = self.store.read_source_script("torch_dragon")
        self.assertEqual(read_script, self.sample_script)

    def test_nonexistent_project_raises_not_found(self):
        with self.assertRaises(VoiceProjectNotFound):
            self.store.get_project_state("non_existent_project")

    def test_update_script_invalidates_downstream_hashes(self):
        self.store.create_workspace("p1", self.sample_script)

        # Fake plan persistence
        plan = VoicePlan(
            version=1,
            project=ProjectMetadata(id="p1", title="P1", source_script=self.sample_script),
            voice=VoiceMetadata(profile="default", provider="chatterbox-http", model="auto"),
            global_direction=GlobalDirection(tone="epic", base_pace=1.0, dramatic_level=3, max_energy=5.0, avoid_overacting=True),
            beats=[
                Beat(
                    id="B01",
                    role=BeatRole.SETUP,
                    script=BeatScript(text=self.sample_script),
                    voice=VoiceDirection(emotion="mysterious", energy=3.0, pause=PauseModel(before=0.0, after=0.5)),
                )
            ],
        )
        self.store.save_voice_plan("p1", plan)
        state_planned = self.store.get_project_state("p1")
        self.assertEqual(state_planned.stage, ProjectStatus.PLANNED)
        self.assertTrue(len(state_planned.artifacts.voice_plan_sha256) > 0)

        # Update source script
        new_script = "A completely different revised mythic tale."
        state_updated = self.store.update_source_script("p1", new_script)

        self.assertEqual(state_updated.stage, ProjectStatus.NEW)
        self.assertEqual(state_updated.artifacts.voice_plan_sha256, "")
        self.assertEqual(state_updated.artifacts.resource_report_sha256, "")

        # Check staleness
        is_stale, reason = self.store.check_staleness("p1")
        self.assertTrue(is_stale)
        self.assertIn("stale", reason.lower())

    def test_transient_state_crash_recovery(self):
        state = self.store.create_workspace("p1", self.sample_script)
        state.stage = ProjectStatus.PLANNED
        state.last_stable_stage = ProjectStatus.PLANNED
        self.store.save_project_state(state)

        # Simulate crash during PLANNING
        state.stage = ProjectStatus.PLANNING
        # Bypass store.get_project_state to directly write corrupted yaml
        proj_dir = self.store.get_project_dir("p1")
        with open(proj_dir / "project.yaml", "w", encoding="utf-8") as f:
            f.write(state.to_yaml())

        # When recovering, store should automatically roll back to last stable stage
        recovered_state = self.store.recover_transient_state("p1")
        self.assertEqual(recovered_state.stage, ProjectStatus.PLANNED)
        self.assertIsNotNone(recovered_state.error)


if __name__ == "__main__":
    unittest.main()
