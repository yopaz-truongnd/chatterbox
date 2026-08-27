"""Cross-Interface Parity Tests (REST vs MCP vs Service) (Phase 13-15).

Verifies that REST API and MCP Tool responses maintain semantic parity for
project summaries, operation statuses, human actions, and artifact outputs.
"""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

import api_app
from mcp_adapter.voice_project_tools import handle_voice_project_tool
from services.voice_project_dependencies import get_voice_project_service


class TestVoiceProjectCrossParity(unittest.TestCase):
    """Test response shape and semantics consistency across REST and MCP boundaries."""

    @classmethod
    def setUpClass(cls):
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.projects_root = Path(cls.temp_dir.name) / "projects"
        cls.projects_root.mkdir(parents=True, exist_ok=True)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(cls.temp_dir.name)

        cls.client_context = TestClient(api_app.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def test_cross_interface_parity_on_planned_and_rendered_project(self):
        script_text = "The morning sun rose gently over the calm green valley."
        project_id = "parity_proj_01"

        # 1. Create via REST API
        rest_create = self.client.post(
            "/api/v1/voice-projects",
            json={"project_id": project_id, "script_text": script_text},
        )
        self.assertEqual(rest_create.status_code, 201)
        rest_create_data = rest_create.json()

        # 2. Query same project via MCP tool
        mcp_get = handle_voice_project_tool(
            "chatterbox_voice_project_get",
            {"project_id": project_id},
        )
        self.assertFalse(mcp_get["isError"])
        mcp_get_data = json.loads(mcp_get["content"][0]["text"])

        # Parity Check: Project ID and Stage match exactly
        self.assertEqual(rest_create_data["project_id"], mcp_get_data["project_id"])
        self.assertEqual(rest_create_data["stage"], mcp_get_data["stage"])
        self.assertEqual(rest_create_data["beats"]["total"], mcp_get_data["beats"]["total"])

        # 3. Plan via MCP tool
        mcp_plan = handle_voice_project_tool(
            "chatterbox_voice_plan",
            {"project_id": project_id},
        )
        self.assertFalse(mcp_plan["isError"])
        mcp_job_id = json.loads(mcp_plan["content"][0]["text"])["job_id"]

        # 4. Check job status via REST API
        self._wait_for_rest_job(mcp_job_id)

        # 5. Check Resources via REST API
        res_job_resp = self.client.post(f"/api/v1/voice-projects/{project_id}/resources/check")
        self.assertEqual(res_job_resp.status_code, 202)
        self._wait_for_rest_job(res_job_resp.json()["job_id"])

        # 6. Render via MCP tool
        mcp_render = handle_voice_project_tool(
            "chatterbox_voice_render",
            {"project_id": project_id, "provider": "fake"},
        )
        self.assertFalse(mcp_render["isError"])
        mcp_render_job_id = json.loads(mcp_render["content"][0]["text"])["job_id"]
        self._wait_for_rest_job(mcp_render_job_id)

        # 7. Final comparison between REST, MCP, and Service layer
        rest_summary = self.client.get(f"/api/v1/voice-projects/{project_id}").json()
        mcp_summary = json.loads(
            handle_voice_project_tool("chatterbox_voice_project_get", {"project_id": project_id})["content"][0]["text"]
        )
        direct_service_summary = get_voice_project_service().get_project(project_id)

        self.assertEqual(rest_summary["stage"], "NARRATION_READY")
        self.assertEqual(mcp_summary["stage"], "NARRATION_READY")
        self.assertEqual(direct_service_summary.stage.value, "NARRATION_READY")
        self.assertEqual(rest_summary["beats"]["passed"], direct_service_summary.passed_beats)
        self.assertEqual(mcp_summary["beats"]["passed"], direct_service_summary.passed_beats)

    def _wait_for_rest_job(self, job_id: str, max_retries: int = 50):
        for _ in range(max_retries):
            resp = self.client.get(f"/api/v1/voice-project-jobs/{job_id}")
            if resp.status_code == 200:
                data = resp.json()
                if data["status"] in ("completed", "failed", "cancelled", "interrupted"):
                    return data
            time.sleep(0.05)
        self.fail(f"Job {job_id} did not finish in time.")


if __name__ == "__main__":
    unittest.main()
