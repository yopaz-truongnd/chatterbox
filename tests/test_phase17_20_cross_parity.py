"""Cross-parity tests verifying REST and MCP interfaces produce equivalent outcomes (Phases 17-20)."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient

from unittest import mock
import api_app
from mcp_server import execute_tool
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.tts.fake import FakeTTSProvider


class TestPhase17to20CrossParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(self.tmp.name)
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"

        self.client = TestClient(api_app.app)
        self.store = VoiceProjectStore(root_dir=Path(self.tmp.name) / "projects")
        self.provider = FakeTTSProvider()
        self.proj_service = VoiceProjectService(
            store=self.store, execution_port=self.provider, provider_name="fake"
        )

        def _client_request(path, method="GET", data=None, headers=None, timeout=None):
            if method == "GET":
                resp = self.client.get(path)
            else:
                resp = self.client.post(path, json=data if isinstance(data, dict) else (data or {}))
            try:
                return resp.json()
            except Exception:
                return {"status_code": resp.status_code, "detail": resp.text}

        self.patcher = mock.patch("mcp_server.make_api_request", side_effect=_client_request)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def _mcp_call(self, name: str, args: dict) -> dict:
        res = execute_tool(name, args)
        self.assertFalse(res.get("isError", False))
        return json.loads(res["content"][0]["text"])

    def test_runtime_capabilities_parity(self):
        rest_res = self.client.get("/api/v1/voice-runtime/capabilities").json()
        mcp_res = self._mcp_call("chatterbox_voice_runtime_capabilities", {})

        self.assertEqual(rest_res["available"], mcp_res["available"])
        self.assertEqual(rest_res["supported_output_formats"], mcp_res["supported_output_formats"])

    def test_series_create_and_get_parity(self):
        title = "Parity Test Series"

        # Create via MCP
        mcp_create = self._mcp_call(
            "chatterbox_voice_series_create",
            {"title": title, "language": "en"},
        )
        sid = mcp_create["series_id"]

        # Read via REST
        rest_get = self.client.get(f"/api/v1/voice-series/{sid}").json()

        self.assertEqual(mcp_create["title"], rest_get["title"])
        self.assertEqual(mcp_create["language"], rest_get["language"])

    def test_project_health_parity(self):
        pid = "parity_health_proj"
        self.proj_service.create_project("Testing parity of health endpoint.", project_id=pid)

        rest_h = self.client.get(f"/api/v1/voice-projects/{pid}/health").json()
        mcp_h = self._mcp_call("chatterbox_voice_health", {"project_id": pid})

        self.assertEqual(rest_h["project_id"], mcp_h["project_id"])
        self.assertEqual(rest_h["status"], mcp_h["status"])
