"""Unit tests for Phase 17-20 MCP tool adapters and dispatching."""

import json
import os
from pathlib import Path
import tempfile
import unittest

from unittest import mock
from fastapi.testclient import TestClient
import api_app
from mcp_server import execute_tool
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.tts.fake import FakeTTSProvider


class TestPhase17to20MCP(unittest.TestCase):
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

    def _extract_content(self, res: dict):
        self.assertFalse(res.get("isError", False), f"Tool returned error: {res}")
        text = res["content"][0]["text"]
        return json.loads(text)

    # ---------------- Phase 17 MCP ----------------
    def test_mcp_runtime_capabilities(self):
        res = execute_tool("chatterbox_voice_runtime_capabilities", {})
        data = self._extract_content(res)
        self.assertIn("available", data)
        self.assertIn("supported_output_formats", data)

    def test_mcp_runtime_preflight(self):
        pid = "mcp_preflight_proj"
        self.proj_service.create_project("The ancient realm awakened.", project_id=pid)
        res = execute_tool(
            "chatterbox_voice_runtime_preflight",
            {"project_id": pid, "provider": "fake", "requested_formats": ["wav"]},
        )
        data = self._extract_content(res)
        self.assertEqual(data["project_id"], pid)
        self.assertTrue(data["passed"])

    # ---------------- Phase 18 MCP ----------------
    def test_mcp_asset_tools(self):
        # List assets
        res = execute_tool("chatterbox_voice_assets", {})
        data = self._extract_content(res)
        self.assertIsInstance(data, list)

        # Match assets
        res_match = execute_tool(
            "chatterbox_voice_asset_match",
            {"intents": ["thunder"], "category": "sfx"},
        )
        data_match = self._extract_content(res_match)
        self.assertIsInstance(data_match, list)

    # ---------------- Phase 19 MCP ----------------
    def test_mcp_series_tools(self):
        # Create
        res_create = execute_tool(
            "chatterbox_voice_series_create",
            {"title": "MCP Series Saga", "language": "en"},
        )
        series_data = self._extract_content(res_create)
        sid = series_data["series_id"]

        # Get
        res_get = execute_tool("chatterbox_voice_series_get", {"series_id": sid})
        get_data = self._extract_content(res_get)
        self.assertEqual(get_data["title"], "MCP Series Saga")

        # Add episode
        self.proj_service.create_project("Episode 1 script text", project_id="proj_mcp_ep1")
        res_ep = execute_tool(
            "chatterbox_voice_series_add_episode",
            {"series_id": sid, "project_id": "proj_mcp_ep1", "title": "Ep 1", "episode_number": 1},
        )
        ep_data = self._extract_content(res_ep)
        self.assertEqual(ep_data["title"], "Ep 1")

    # ---------------- Phase 20 MCP ----------------
    def test_mcp_health_events_diagnostics(self):
        pid = "proj_mcp_health"
        self.proj_service.create_project("Some text", project_id=pid)

        # Health
        res_h = execute_tool("chatterbox_voice_health", {"project_id": pid})
        data_h = self._extract_content(res_h)
        self.assertEqual(data_h["project_id"], pid)

        # Events
        res_e = execute_tool("chatterbox_voice_events", {"project_id": pid})
        data_e = self._extract_content(res_e)
        self.assertIsInstance(data_e, list)

        # Diagnostics
        res_d = execute_tool("chatterbox_voice_diagnostics", {"project_id": pid})
        data_d = self._extract_content(res_d)
        self.assertIn("health", data_d)
