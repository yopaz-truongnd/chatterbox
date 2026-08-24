"""Unit tests for MCP Voice Project Tools Adapter (Phase 13)."""

import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from mcp_adapter.catalog import VOICE_PROJECT_TOOL_SCHEMAS, get_tools_list
from mcp_adapter.voice_project_tools import handle_voice_project_tool
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_service,
    get_voice_project_store,
)


class TestVoiceProjectMCP(unittest.TestCase):
    """Test MCP Voice Project Tools execution and agent contract schemas."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.projects_root = Path(self.temp_dir.name) / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_mcp_catalog_contains_voice_project_tools(self):
        tools = get_tools_list()
        tool_names = [t["name"] for t in tools]

        expected_tools = [
            "chatterbox_voice_project_create",
            "chatterbox_voice_project_get",
            "chatterbox_voice_plan",
            "chatterbox_voice_check_resources",
            "chatterbox_voice_render",
            "chatterbox_voice_render_beat",
            "chatterbox_voice_qc",
            "chatterbox_voice_job_status",
            "chatterbox_voice_job_cancel",
        ]

        for expected in expected_tools:
            self.assertIn(expected, tool_names)

    def test_mcp_full_agent_workflow(self):
        script = "When Zhulong opens his eyes, the world illuminates with brilliant light."

        # 1. Create Project
        create_res = handle_voice_project_tool(
            "chatterbox_voice_project_create",
            {"project_id": "mcp_dragon", "script_text": script},
        )
        self.assertFalse(create_res["isError"])
        create_data = json.loads(create_res["content"][0]["text"])
        self.assertEqual(create_data["project_id"], "mcp_dragon")
        self.assertEqual(create_data["stage"], "NEW")

        # 2. Get Project
        get_res = handle_voice_project_tool(
            "chatterbox_voice_project_get",
            {"project_id": "mcp_dragon"},
        )
        self.assertFalse(get_res["isError"])
        get_data = json.loads(get_res["content"][0]["text"])
        self.assertEqual(get_data["project_id"], "mcp_dragon")
        self.assertIn("suggested_action", get_data)

        # 3. Trigger Plan
        plan_res = handle_voice_project_tool(
            "chatterbox_voice_plan",
            {"project_id": "mcp_dragon"},
        )
        self.assertFalse(plan_res["isError"])
        plan_data = json.loads(plan_res["content"][0]["text"])
        self.assertIn("job_id", plan_data)
        plan_job_id = plan_data["job_id"]

        # 4. Poll Job Status
        status_data = self._wait_for_job(plan_job_id)
        self.assertEqual(status_data["status"], "completed")

        # 5. Check Resources
        res_check_res = handle_voice_project_tool(
            "chatterbox_voice_check_resources",
            {"project_id": "mcp_dragon"},
        )
        self.assertFalse(res_check_res["isError"])
        res_job_id = json.loads(res_check_res["content"][0]["text"])["job_id"]
        self._wait_for_job(res_job_id)

        # 6. Trigger Render with provider=fake
        render_res = handle_voice_project_tool(
            "chatterbox_voice_render",
            {"project_id": "mcp_dragon", "provider": "fake", "allow_blocked": True},
        )
        self.assertFalse(render_res["isError"])
        render_job_id = json.loads(render_res["content"][0]["text"])["job_id"]
        render_final = self._wait_for_job(render_job_id)
        self.assertEqual(render_final["status"], "completed")

    def test_mcp_validation_error_on_empty_script(self):
        res = handle_voice_project_tool(
            "chatterbox_voice_project_create",
            {"script_text": ""},
        )
        self.assertTrue(res["isError"])
        err_data = json.loads(res["content"][0]["text"])
        self.assertEqual(err_data["error"]["code"], "VALIDATION_ERROR")

    def test_mcp_cancel_tool(self):
        create_res = handle_voice_project_tool(
            "chatterbox_voice_project_create",
            {"project_id": "mcp_cancel_proj", "script_text": "Cancellation script test"},
        )
        plan_res = handle_voice_project_tool(
            "chatterbox_voice_plan",
            {"project_id": "mcp_cancel_proj"},
        )
        job_id = json.loads(plan_res["content"][0]["text"])["job_id"]

        cancel_res = handle_voice_project_tool(
            "chatterbox_voice_job_cancel",
            {"job_id": job_id},
        )
        self.assertIn("content", cancel_res)

        # Wait for the background thread to reach a terminal state before tearDown
        # removes the temp directory — prevents OSError 66 (Directory not empty).
        for _ in range(60):
            status_res = handle_voice_project_tool(
                "chatterbox_voice_job_status",
                {"job_id": job_id},
            )
            data = json.loads(status_res["content"][0]["text"])
            if data.get("status") in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.05)

    def _wait_for_job(self, job_id: str, max_retries: int = 50):
        for _ in range(max_retries):
            status_res = handle_voice_project_tool(
                "chatterbox_voice_job_status",
                {"job_id": job_id},
            )
            data = json.loads(status_res["content"][0]["text"])
            if data.get("status") in ("completed", "failed", "cancelled"):
                return data
            time.sleep(0.05)
        self.fail(f"MCP Job {job_id} did not finish in time.")


if __name__ == "__main__":
    unittest.main()
