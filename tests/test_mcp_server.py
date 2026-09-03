"""Unit tests for Chatterbox Model Context Protocol (MCP) Server.

Tests JSON-RPC protocol handling, tool execution, character parsing, safe download handling,
and structured Critic evaluation.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import mcp_server


class MCPServerTestCase(unittest.TestCase):
    """Test suite for stdio MCP JSON-RPC server and tools."""

    def test_mcp_tools_list_contains_all_tools(self):
        tools = mcp_server.get_tools_list()
        tool_names = {t["name"] for t in tools}
        expected_tools = {
            "chatterbox_list_characters",
            "chatterbox_generate_tts",
            "chatterbox_get_job_status",
            "chatterbox_download_audio",
            "chatterbox_voice_conversion",
            "chatterbox_evaluate_voice",
            "chatterbox_prepare_project",
            "chatterbox_answer_project_questions",
            "chatterbox_confirm_requirements",
            "chatterbox_generate_script",
            "chatterbox_confirm_script",
            "chatterbox_confirm_project",
            "chatterbox_render_project",
            "chatterbox_get_project",
            "chatterbox_list_projects",
            "chatterbox_get_events",
        }
        self.assertTrue(expected_tools.issubset(tool_names), f"Missing tools: {expected_tools - tool_names}")
        # 49 prior tools + 19 new tools from Phase 17-20 (2 runtime + 5 asset + 7 series + 5 health)
        self.assertEqual(len(tools), 68)

    def test_list_characters_handles_dict_and_list_responses(self):
        # 1. Dict response format (standard from /api/v1/characters)
        dict_payload = {
            "characters": [
                {
                    "id": "char_1",
                    "name": "Hero Narrator",
                    "language": "en",
                    "description": "Deep epic voice",
                    "has_reference_audio": True,
                    "is_default": True,
                }
            ],
            "count": 1,
        }

        with patch("mcp_server.make_api_request", return_value=dict_payload):
            res = mcp_server.execute_tool("chatterbox_list_characters", {})
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("Hero Narrator", text)
            self.assertIn("Default", text)
            self.assertIn("char_1", text)

        # 2. Raw list response format (fallback)
        list_payload = [
            {
                "id": "char_2",
                "name": "Sidekick",
                "language": "vi",
                "has_reference_audio": False,
            }
        ]
        with patch("mcp_server.make_api_request", return_value=list_payload):
            res = mcp_server.execute_tool("chatterbox_list_characters", {})
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("Sidekick", text)
            self.assertIn("char_2", text)

    def test_generate_tts_routes_parameters(self):
        with patch("mcp_server.make_api_request") as mock_api:
            mock_api.return_value = {"id": "job_123", "status": "queued"}
            res = mcp_server.execute_tool(
                "chatterbox_generate_tts",
                {"text": "Hello world", "model": "nano", "preset": "fast"},
            )
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("job_123", text)

            mock_api.assert_called_once()
            args, kwargs = mock_api.call_args
            self.assertEqual(args[0], "/api/v1/tts/nano")

    def test_download_audio_overwrite_protection_and_atomic_write(self):
        with tempfile.TemporaryDirectory() as temp_d:
            temp_dir_path = Path(temp_d)
            dest_file = temp_dir_path / "output.wav"

            # Create dummy 44-byte WAV header
            dummy_wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + b"\x00" * 28 + b"data\x00\x00\x00\x00"

            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = dummy_wav
            mock_resp.__enter__.return_value = mock_resp

            with patch("mcp_server.DEFAULT_MCP_OUTPUT_DIR", temp_dir_path), patch("urllib.request.urlopen", return_value=mock_resp):
                # 1. First download succeeds
                res = mcp_server.execute_tool(
                    "chatterbox_download_audio",
                    {"job_id": "job_test", "destination_path": "output.wav", "overwrite": False},
                )
                self.assertFalse(res.get("isError", False))
                self.assertTrue(dest_file.exists())
                self.assertEqual(dest_file.read_bytes(), dummy_wav)

                # 2. Second download without overwrite fails
                res_exists = mcp_server.execute_tool(
                    "chatterbox_download_audio",
                    {"job_id": "job_test", "destination_path": "output.wav", "overwrite": False},
                )
                self.assertTrue(res_exists.get("isError", False))
                self.assertIn("already exists", res_exists["content"][0]["text"])

                # 3. Download with overwrite=True succeeds
                res_overwrite = mcp_server.execute_tool(
                    "chatterbox_download_audio",
                    {"job_id": "job_test", "destination_path": "output.wav", "overwrite": True},
                )
                self.assertFalse(res_overwrite.get("isError", False))

    def test_download_audio_path_traversal_prevention(self):
        with tempfile.TemporaryDirectory() as temp_d:
            temp_dir_path = Path(temp_d)
            with patch("mcp_server.DEFAULT_MCP_OUTPUT_DIR", temp_dir_path):
                # Attempt relative path traversal
                res_relative = mcp_server.execute_tool(
                    "chatterbox_download_audio",
                    {"job_id": "job_test", "destination_path": "../../../etc/passwd.wav"},
                )
                self.assertTrue(res_relative.get("isError", False))
                self.assertIn("Security restriction", res_relative["content"][0]["text"])

                # Attempt absolute path escape
                res_absolute = mcp_server.execute_tool(
                    "chatterbox_download_audio",
                    {"job_id": "job_test", "destination_path": "/tmp/unauthorized_audio.wav"},
                )
                self.assertTrue(res_absolute.get("isError", False))
                self.assertIn("Security restriction", res_absolute["content"][0]["text"])

    def test_evaluate_voice_returns_structured_summary(self):
        eval_payload = {
            "status": "completed",
            "markdown_report": "### Evaluation Report\nGood audio.",
            "evaluation": {
                "passed": True,
                "overall_score": 90,
                "issues": [],
                "metrics": {
                    "duration_seconds": 2.5,
                    "loudness_lufs": -20.0,
                    "pitch_std_hz": 45.0,
                    "pace_wpm": 130,
                },
                "recommended_changes": {},
            },
            "feedback_job_id": "coach_job_99",
            "feedback_audio_url": "/api/v1/jobs/coach_job_99/audio",
        }

        with patch("mcp_server.make_api_request", return_value=eval_payload):
            res = mcp_server.execute_tool(
                "chatterbox_evaluate_voice",
                {"job_id": "job_test_eval"},
            )
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("Structured Evaluation Summary", text)
            self.assertIn('"overall_score": 90', text)
            self.assertIn('"passed": true', text)

    def test_api_offline_helpful_error_message(self):
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            res = mcp_server.make_api_request("/api/v1/health")
            self.assertIn("detail", res)
            self.assertIn("Không thể kết nối tới Chatterbox API", res["detail"])
            self.assertIn("./run_chatterbox_api.sh", res["detail"])

    def test_project_planning_tools_execution(self):
        # 1. Prepare Project
        mock_prepare = {
            "project_id": "proj_abc123",
            "status": "awaiting_answers",
            "summary": "### Tóm tắt dự án test",
            "questions": [
                {"id": "content_format", "question": "Định dạng gì?", "required": True, "options": ["Podcast"]}
            ],
        }
        with patch("mcp_server.make_api_request", return_value=mock_prepare):
            res = mcp_server.execute_tool("chatterbox_prepare_project", {"topic": "Podcast AI"})
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("proj_abc123", text)
            self.assertIn("AWAITING_ANSWERS", text)
            self.assertIn("Định dạng gì?", text)

        # 2. Answer Project Questions
        mock_answer = {
            "project_id": "proj_abc123",
            "status": "awaiting_confirmation",
            "summary": "### Tóm tắt dự án đầy đủ\nFormat: Podcast",
            "questions": [],
        }
        with patch("mcp_server.make_api_request", return_value=mock_answer):
            res = mcp_server.execute_tool(
                "chatterbox_answer_project_questions",
                {"project_id": "proj_abc123", "answers": "Podcast 5 phút"},
            )
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("AWAITING_CONFIRMATION", text)

        # 3. Confirm Project
        mock_confirm = {
            "project_id": "proj_abc123",
            "status": "approved",
            "message": "Đã phê duyệt thành công",
            "summary": "Full summary",
        }
        with patch("mcp_server.make_api_request", return_value=mock_confirm):
            res = mcp_server.execute_tool(
                "chatterbox_confirm_project",
                {"project_id": "proj_abc123", "confirmed": True},
            )
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("APPROVED", text)
            self.assertIn("Đã phê duyệt", text)

        # 4. Render Project
        mock_render = {
            "project_id": "proj_abc123",
            "job_id": "job_render_999",
            "status": "rendering",
            "message": "Đã khởi tạo tác vụ tổng hợp",
            "script_text": "Script narration",
        }
        with patch("mcp_server.make_api_request", return_value=mock_render):
            res = mcp_server.execute_tool(
                "chatterbox_render_project",
                {"project_id": "proj_abc123"},
            )
            self.assertFalse(res.get("isError", False))
            text = res["content"][0]["text"]
            self.assertIn("job_render_999", text)
            self.assertIn("RENDERING", text)

    def test_jsonrpc_stdio_subprocess_protocol(self):
        """Integration test verifying end-to-end JSON-RPC protocol over real stdio process."""
        server_script = Path(mcp_server.__file__).resolve()
        proc = subprocess.Popen(
            [sys.executable, str(server_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        def send_and_recv(req: dict) -> dict:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            line = proc.stdout.readline()
            self.assertTrue(line, "Server returned empty response on stdout")
            return json.loads(line)

        try:
            # 1. Initialize RPC
            init_res = send_and_recv({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertEqual(init_res.get("jsonrpc"), "2.0")
            self.assertEqual(init_res.get("id"), 1)
            self.assertEqual(init_res.get("result", {}).get("serverInfo", {}).get("name"), "chatterbox-mcp")

            # 2. Tools list RPC
            tools_res = send_and_recv({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            tools = tools_res.get("result", {}).get("tools", [])
            # 49 prior tools + 19 new tools from Phase 17-20 (2 runtime + 5 asset + 7 series + 5 health)
            self.assertEqual(len(tools), 68)
            tool_names = {t["name"] for t in tools}
            self.assertIn("chatterbox_list_characters", tool_names)
            self.assertIn("chatterbox_generate_tts", tool_names)
            self.assertIn("chatterbox_download_audio", tool_names)
            self.assertIn("chatterbox_prepare_project", tool_names)
            self.assertIn("chatterbox_confirm_requirements", tool_names)
            self.assertIn("chatterbox_generate_script", tool_names)
            self.assertIn("chatterbox_confirm_script", tool_names)
            self.assertIn("chatterbox_confirm_project", tool_names)
            self.assertIn("chatterbox_render_project", tool_names)
            self.assertIn("chatterbox_get_events", tool_names)

            # 3. Unknown method returns standard JSON-RPC error
            err_res = send_and_recv({"jsonrpc": "2.0", "id": 3, "method": "unsupported_method", "params": {}})
            self.assertEqual(err_res.get("error", {}).get("code"), -32601)

        finally:
            proc.terminate()
            stdout_remainder, stderr_output = proc.communicate(timeout=5)

        # Confirm debug logs went to stderr and didn't corrupt stdout
        self.assertIn("[Chatterbox MCP]", stderr_output)
        self.assertEqual(stdout_remainder.strip(), "")


if __name__ == "__main__":
    unittest.main()
