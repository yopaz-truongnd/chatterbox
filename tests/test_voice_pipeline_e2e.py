"""End-to-End Acceptance Tests for Phases 7-9 (CLI Workflow -> TTS Provider -> Voice QC)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import yaml

from services.voice_cli import (
    EXIT_SUCCESS,
    main,
)
from services.render_models import (
    ProjectStatus,
    ProjectState,
    RenderManifest,
    RenderStatus,
)


class TestVoicePipelineE2E(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="voice_e2e_test_"))
        self.script_file = self.temp_dir / "torch_dragon.txt"

        # 4-beat mythology narrative script with verified proper nouns (Zhulong, Taotie, Hundun)
        self.raw_script = (
            "In ancient times before the dawn of human kings.\n\n"
            "When Zhulong opened its eyes, eternal daylight illuminated the cosmic darkness.\n\n"
            "Across the northern peaks, Taotie devoured the shadows of the silent valleys.\n\n"
            "From the primordial depths, Hundun slept as the cosmic balance held firm."
        )

        with open(self.script_file, "w", encoding="utf-8") as f:
            f.write(self.raw_script)

        self.projects_dir = self.temp_dir / "projects"

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_phases_7_to_9_acceptance_scenario(self):
        """Acceptance test:
        1. voice new TorchDragon.txt
        2. voice plan
        3. voice resources
        4. voice render --qc --fake
        5. voice inspect -> NARRATION_READY
        """
        project_id = "torch_dragon"
        project_path = self.projects_dir / project_id

        # 1. voice new
        code_new = main([
            "new",
            str(self.script_file),
            "--project-id", project_id,
            "--output-dir", str(self.projects_dir),
        ])
        self.assertEqual(code_new, EXIT_SUCCESS)
        self.assertTrue(project_path.exists())
        self.assertTrue((project_path / "project.yaml").exists())

        # 2. voice plan
        code_plan = main(["plan", str(project_path)])
        self.assertEqual(code_plan, EXIT_SUCCESS)
        self.assertTrue((project_path / "voice-plan.yaml").exists())

        with open(project_path / "voice-plan.yaml", "r", encoding="utf-8") as f:
            plan_data = yaml.safe_load(f)
            self.assertEqual(len(plan_data["beats"]), 4)

        # 3. voice resources
        code_res = main(["resources", str(project_path)])
        # Zhulong is verified in default knowledge -> readiness is high and not blocked
        self.assertEqual(code_res, EXIT_SUCCESS)
        self.assertTrue((project_path / "resource-report.yaml").exists())

        # 4. voice render --qc --fake
        code_render = main(["render", str(project_path), "--fake", "--qc"])
        self.assertEqual(code_render, EXIT_SUCCESS)

        manifest_path = project_path / "render-manifest.yaml"
        self.assertTrue(manifest_path.exists())

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)
            manifest = RenderManifest.from_dict(manifest_data)

            # Check that every beat was rendered and passed
            self.assertEqual(len(manifest.beats), 4)
            for bid, bstate in manifest.beats.items():
                self.assertEqual(bstate.status, RenderStatus.PASSED)
                self.assertIsNotNone(bstate.selected_attempt)
                wav_path = project_path / "renders" / bid / f"attempt_{bstate.selected_attempt:02d}.wav"
                self.assertTrue(wav_path.exists())
                qc_path = project_path / "qc" / bid / f"attempt_{bstate.selected_attempt:02d}.json"
                self.assertTrue(qc_path.exists())

        # 5. voice inspect check final state
        with open(project_path / "project.yaml", "r", encoding="utf-8") as f:
            state_data = yaml.safe_load(f)
            state = ProjectState.from_dict(state_data)
            self.assertEqual(state.stage, ProjectStatus.NARRATION_READY)
            self.assertTrue(state.status.narration_ready)

        # 6. Verify original script text was untouched
        with open(project_path / "source" / "script.txt", "r", encoding="utf-8") as f:
            saved_script = f.read()
            self.assertEqual(saved_script, self.raw_script)


if __name__ == "__main__":
    unittest.main()
