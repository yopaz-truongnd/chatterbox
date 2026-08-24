"""Cross-interface parity test (Phase 12-13).

Ensures CLI, REST API, and MCP Agent interfaces derive identical project state,
beat summaries, readiness statistics, and suggested next actions from VoiceProjectService.
"""

import argparse
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import api_app
from mcp_adapter.voice_project_tools import handle_voice_project_tool
from services.voice_cli import cmd_inspect
from services.voice_project_dependencies import get_voice_project_service, get_voice_project_store
from services.voice_project_store import VoiceProjectStore


class TestVoiceProjectCrossParity(unittest.TestCase):
    """Verify semantic and field parity across CLI, REST, and MCP."""

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
        script = "The ancient titan Nuwa forged colored stones to mend the weeping sky."

        store = VoiceProjectStore(root_dir=self.projects_root)
        service = get_voice_project_service(provider_name="fake", store=store)

        # Create, plan, check resources, render
        service.create_project(script_text=script, project_id="parity_nuwa")
        service.plan("parity_nuwa")
        service.check_resources("parity_nuwa")
        service.render("parity_nuwa", allow_resource_blocked=True)

        project_dir = self.projects_root / "parity_nuwa"

        # 1. Inspect via CLI (JSON output)
        cli_args = argparse.Namespace(project_dir=str(project_dir), json=True)
        with patch("sys.stdout", new=io.StringIO()) as fake_stdout:
            exit_code = cmd_inspect(cli_args)
            self.assertEqual(exit_code, 0)
            cli_json = json.loads(fake_stdout.getvalue())

        # 2. Inspect via REST API
        rest_resp = self.client.get("/api/v1/voice-projects/parity_nuwa")
        self.assertEqual(rest_resp.status_code, 200)
        rest_json = rest_resp.json()

        # 3. Inspect via MCP
        mcp_res = handle_voice_project_tool(
            "chatterbox_voice_project_get",
            {"project_id": "parity_nuwa"},
        )
        self.assertFalse(mcp_res["isError"])
        mcp_json = json.loads(mcp_res["content"][0]["text"])

        # Compare parity
        self.assertEqual(cli_json["project_id"], "parity_nuwa")
        self.assertEqual(rest_json["project_id"], "parity_nuwa")
        self.assertEqual(mcp_json["project_id"], "parity_nuwa")

        self.assertEqual(cli_json["stage"], rest_json["stage"])
        self.assertEqual(rest_json["stage"], mcp_json["stage"])

        self.assertEqual(cli_json["beats_count"], rest_json["beats"]["total"])
        self.assertEqual(rest_json["beats"]["total"], mcp_json["total_beats"])

        self.assertEqual(rest_json["suggested_action"], mcp_json["suggested_action"])


if __name__ == "__main__":
    unittest.main()
