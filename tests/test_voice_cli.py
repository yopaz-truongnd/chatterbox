"""Unit and integration tests for Phase 7 CLI Workflow."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest
import yaml

from services.voice_cli import (
    EXIT_GENERIC_ERROR,
    EXIT_PROVIDER_UNAVAILABLE,
    EXIT_QC_FAILED,
    EXIT_RESOURCE_BLOCKED,
    EXIT_SUCCESS,
    EXIT_VALIDATION_ERROR,
    main,
)
from services.render_models import ProjectStatus, ProjectState


class TestVoiceCLIPhase7(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="voice_cli_test_"))
        self.script_file = self.temp_dir / "torch_dragon.txt"
        self.script_content = (
            "Beyond the northern seas rises Mount Zhong, where no mortal walks.\n"
            "When Zhulong opened its eyes, eternal daylight illuminated the cosmic darkness.\n"
            "When the great Torch Dragon blew its icy breath, howling blizzards covered the mountains."
        )
        with open(self.script_file, "w", encoding="utf-8") as f:
            f.write(self.script_content)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_voice_new_creates_project_layout(self):
        projects_root = self.temp_dir / "projects"
        exit_code = main([
            "new",
            str(self.script_file),
            "--project-id", "test_proj_01",
            "--output-dir", str(projects_root),
        ])
        self.assertEqual(exit_code, EXIT_SUCCESS)

        proj_dir = projects_root / "test_proj_01"
        self.assertTrue(proj_dir.exists())
        self.assertTrue((proj_dir / "source" / "script.txt").exists())
        self.assertTrue((proj_dir / "renders").exists())
        self.assertTrue((proj_dir / "qc").exists())
        self.assertTrue((proj_dir / "logs").exists())
        self.assertTrue((proj_dir / "project.yaml").exists())

        # Check project.yaml contents
        with open(proj_dir / "project.yaml", "r", encoding="utf-8") as f:
            state_data = yaml.safe_load(f)
            state = ProjectState.from_dict(state_data)
            self.assertEqual(state.project_id, "test_proj_01")
            self.assertEqual(state.stage, ProjectStatus.NEW)

    def test_voice_inspect_reads_state(self):
        projects_root = self.temp_dir / "projects"
        main([
            "new",
            str(self.script_file),
            "--project-id", "inspect_proj",
            "--output-dir", str(projects_root),
        ])
        proj_dir = projects_root / "inspect_proj"

        # Plan the project first
        exit_plan = main(["plan", str(proj_dir)])
        self.assertEqual(exit_plan, EXIT_SUCCESS)

        # Inspect project
        exit_inspect = main(["inspect", str(proj_dir)])
        self.assertEqual(exit_inspect, EXIT_SUCCESS)

    def test_voice_plan_generates_voice_plan_artifact(self):
        projects_root = self.temp_dir / "projects"
        main([
            "new",
            str(self.script_file),
            "--project-id", "plan_proj",
            "--output-dir", str(projects_root),
        ])
        proj_dir = projects_root / "plan_proj"

        exit_code = main(["plan", str(proj_dir)])
        self.assertEqual(exit_code, EXIT_SUCCESS)

        plan_file = proj_dir / "voice-plan.yaml"
        self.assertTrue(plan_file.exists())
        with open(plan_file, "r", encoding="utf-8") as f:
            plan_data = yaml.safe_load(f)
            self.assertIn("beats", plan_data)
            self.assertGreater(len(plan_data["beats"]), 0)

    def test_voice_resources_missing_groups_priorities(self):
        projects_root = self.temp_dir / "projects"
        main([
            "new",
            str(self.script_file),
            "--project-id", "res_missing_proj",
            "--output-dir", str(projects_root),
        ])
        proj_dir = projects_root / "res_missing_proj"
        main(["plan", str(proj_dir)])

        # Run resources missing command (should succeed with exit 0)
        exit_code = main(["resources_missing", str(proj_dir)])
        self.assertEqual(exit_code, EXIT_SUCCESS)

    def test_voice_doctor_diagnostics(self):
        exit_code = main(["doctor"])
        self.assertEqual(exit_code, EXIT_SUCCESS)

    def test_json_flag_outputs_valid_json(self):
        projects_root = self.temp_dir / "projects"
        import io
        import sys

        # Redirect stdout to capture JSON
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exit_code = main([
                "new",
                str(self.script_file),
                "--project-id", "json_proj",
                "--output-dir", str(projects_root),
                "--json",
            ])
            output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(exit_code, EXIT_SUCCESS)
        parsed = json.loads(output)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["project_id"], "json_proj")

    def test_read_only_commands_do_not_modify_files(self):
        projects_root = self.temp_dir / "projects"
        main([
            "new",
            str(self.script_file),
            "--project-id", "ro_proj",
            "--output-dir", str(projects_root),
        ])
        proj_dir = projects_root / "ro_proj"
        main(["plan", str(proj_dir)])

        state_file = proj_dir / "project.yaml"
        mtime_before = state_file.stat().st_mtime_ns

        # Run inspect (read-only)
        main(["inspect", str(proj_dir)])
        mtime_after = state_file.stat().st_mtime_ns

        self.assertEqual(mtime_before, mtime_after)

    def test_render_without_fake_flag_fails_provider_unavailable(self):
        projects_root = self.temp_dir / "projects"
        main([
            "new",
            str(self.script_file),
            "--project-id", "unavail_proj",
            "--output-dir", str(projects_root),
        ])
        proj_dir = projects_root / "unavail_proj"
        main(["plan", str(proj_dir)])

        # Temporarily unset GEMINI_API_KEY
        import os
        old_key = os.environ.pop("GEMINI_API_KEY", None)
        try:
            exit_code = main(["render", str(proj_dir)])
            # Must return EXIT_PROVIDER_UNAVAILABLE (4), NOT fall back to fake!
            self.assertEqual(exit_code, EXIT_PROVIDER_UNAVAILABLE)
        finally:
            if old_key is not None:
                os.environ["GEMINI_API_KEY"] = old_key

    def test_standalone_qc_persists_manifest_and_state(self):
        projects_root = self.temp_dir / "projects"
        main([
            "new",
            str(self.script_file),
            "--project-id", "qc_persist_proj",
            "--output-dir", str(projects_root),
        ])
        proj_dir = projects_root / "qc_persist_proj"
        main(["plan", str(proj_dir)])
        # Render with fake provider
        main(["render", str(proj_dir), "--fake"])

        # Now run standalone QC
        exit_code = main(["qc", str(proj_dir)])
        self.assertEqual(exit_code, EXIT_SUCCESS)

        # Verify render-manifest.yaml has persisted QC result and attempt status
        manifest_file = proj_dir / "render-manifest.yaml"
        self.assertTrue(manifest_file.exists())
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)
        for bstate in manifest_data["beats"].values():
            self.assertEqual(bstate["status"], "passed")
            self.assertIsNotNone(bstate["selected_attempt"])

        # Verify project.yaml has been updated to NARRATION_READY
        state_file = proj_dir / "project.yaml"
        with open(state_file, "r", encoding="utf-8") as f:
            proj_data = yaml.safe_load(f)
        self.assertEqual(proj_data["stage"], ProjectStatus.NARRATION_READY.value)
        self.assertTrue(proj_data["status"]["narration_ready"])


if __name__ == "__main__":
    unittest.main()
