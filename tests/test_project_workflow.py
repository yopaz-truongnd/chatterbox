"""Unit and Integration Tests for Project Planning, Two-Gate Confirmation & English Audio Production."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import torch
from fastapi.testclient import TestClient

from api_app import app
from services import project_planner
from services.exceptions import (
    ProjectNotApprovedError,
    ProjectNotFoundError,
    ProjectStateError,
    ValidationError,
)


class ProjectWorkflowTestCase(unittest.TestCase):
    """Test suite for the Two-Gate Confirmation audio project planning & orchestration workflow."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir_patch = patch.dict("os.environ", {"CHATTERBOX_API_DATA_DIR": self.temp_dir.name})
        self.data_dir_patch.start()
        self.client = TestClient(app)

        # Setup dummy mock job manager for render tests
        self.mock_job = MagicMock()
        self.mock_job.id = "job_test_batch_123"
        self.mock_job.status = "queued"
        self.mock_job.duration_seconds = 18.5
        self.mock_job.error = None
        self.mock_job.benchmark = {
            "lines_results": [
                {"idx": 0, "status": "completed", "duration_seconds": 9.0, "start_seconds": 0.0, "end_seconds": 9.0},
                {"idx": 1, "status": "completed", "duration_seconds": 9.5, "start_seconds": 9.5, "end_seconds": 19.0},
            ]
        }

        self.mock_jm = MagicMock()
        self.mock_jm._running = True
        self.mock_jm.submit_job.return_value = self.mock_job
        self.mock_jm.get_job.return_value = self.mock_job

    def tearDown(self):
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_text_heuristic_extraction_english_locked_and_strict_sfx(self):
        # Test 1: Full specification
        sample_prompt = "Create a 5-minute podcast about the History of AI for beginners, engaging storytelling tone, light BGM, output wav and srt"
        reqs = project_planner.extract_requirements_from_text(sample_prompt)

        self.assertEqual(reqs.get("content_format"), "podcast")
        self.assertEqual(reqs.get("target_duration_seconds"), 300)
        self.assertEqual(reqs.get("script_language"), "en")
        self.assertEqual(reqs.get("voice_language"), "en")
        self.assertEqual(reqs.get("audience"), "beginner")
        self.assertEqual(reqs.get("tone"), "engaging storytelling")
        self.assertEqual(reqs.get("sfx_level"), "light")
        self.assertIn("wav", reqs.get("output_formats", []))
        self.assertIn("srt", reqs.get("output_formats", []))

        # Test 2: 'nhẹ nhàng' in tone must NOT trigger SFX
        subtle_prompt = "Giọng nam nhẹ nhàng, không đề cập nhạc nền"
        reqs2 = project_planner.extract_requirements_from_text(subtle_prompt)
        self.assertEqual(reqs2.get("tone"), "engaging storytelling")
        self.assertNotIn("sfx_level", reqs2)

    def test_gate1_cannot_be_bypassed_by_confirm_script(self):
        # Prepare raw project (status = awaiting_answers)
        prep = project_planner.prepare_project(topic="Quantum Mechanics Intro")
        proj_id = prep["project_id"]
        self.assertEqual(prep["status"], "awaiting_answers")

        # Attempting to call confirm_script directly without Gate 1 must raise ProjectStateError
        with self.assertRaises(ProjectStateError) as ctx:
            project_planner.confirm_script(project_id=proj_id, confirmed=True)
        self.assertIn("Gate 1 requirements must be confirmed", str(ctx.exception))

    def test_full_two_gate_confirmation_lifecycle_with_real_batch_render(self):
        # 1. Prepare: raw topic
        prep = project_planner.prepare_project(topic="The Exploration of Mars")
        proj_id = prep["project_id"]
        self.assertEqual(prep["status"], "awaiting_answers")

        # 2. Answer: fill missing requirements
        answers = {
            "content_format": "video_narration",
            "target_duration": "3 mins",
            "audience": "general",
            "sfx_level": "cinematic",
        }
        ans_res = project_planner.answer_project_questions(
            project_id=proj_id,
            answers=answers,
            auto_defaults=True,
        )
        self.assertEqual(ans_res["status"], "awaiting_requirements_confirmation")
        self.assertEqual(ans_res["requirements"]["content_format"], "video_narration")
        self.assertEqual(ans_res["requirements"]["target_duration_seconds"], 180)

        # 3. Premature render before Gate 1 -> REJECTED
        with self.assertRaises(ProjectNotApprovedError):
            project_planner.render_project(project_id=proj_id, job_manager=self.mock_jm)

        # 4. Gate 1 Confirmation (Requirements) -> Generates Outline & Script, transitions to awaiting_script_confirmation
        gate1_res = project_planner.confirm_requirements(project_id=proj_id, confirmed=True)
        self.assertEqual(gate1_res["status"], "awaiting_script_confirmation")
        self.assertTrue(len(gate1_res["outline"]) >= 2)
        self.assertIn("full_text", gate1_res["script"])

        # 5. Premature render before Gate 2 -> REJECTED
        with self.assertRaises(ProjectNotApprovedError):
            project_planner.render_project(project_id=proj_id, job_manager=self.mock_jm)

        # 6. Gate 2 Confirmation (Script) -> Transitions to approved
        gate2_res = project_planner.confirm_script(project_id=proj_id, confirmed=True)
        self.assertEqual(gate2_res["status"], "approved")

        # 7. Render after full Two-Gate approval -> Submits REAL batch job
        render_res = project_planner.render_project(project_id=proj_id, job_manager=self.mock_jm)
        self.assertEqual(render_res["status"], "rendering")
        self.assertEqual(render_res["job_id"], "job_test_batch_123")
        self.assertTrue(render_res["segment_count"] > 0)
        self.assertTrue(len(render_res["segments"]) > 0)

        # Verify JobManager submission arguments
        self.mock_jm.submit_job.assert_called_once()
        call_args = self.mock_jm.submit_job.call_args
        self.assertEqual(call_args.kwargs.get("job_type") or call_args.args[0], "batch")
        params = call_args.kwargs.get("params") or call_args.args[1]
        self.assertIn("lines", params)
        self.assertTrue(len(params["lines"]) > 0)
        self.assertEqual(params["model"], "turbo")

    def test_lifecycle_synchronization_with_job(self):
        # 1. Prepare, confirm G1 and G2
        prep = project_planner.prepare_project(topic="Deep Learning Overview", auto_defaults=True)
        proj_id = prep["project_id"]
        project_planner.confirm_requirements(proj_id, confirmed=True)
        project_planner.confirm_script(proj_id, confirmed=True)

        # 2. Render
        project_planner.render_project(proj_id, job_manager=self.mock_jm)

        # 3. Simulate job completion in JobManager
        self.mock_job.status = "completed"
        self.mock_jm.get_job.return_value = self.mock_job

        # 4. Fetch project via get_project with job_manager -> must auto-sync to 'completed'
        proj_state = project_planner.get_project(proj_id, job_manager=self.mock_jm)
        self.assertEqual(proj_state["status"], "completed")
        self.assertIn("/api/v1/jobs/job_test_batch_123/audio", proj_state["audio_url"])

    def test_generate_script_blocked_before_gate1(self):
        # Prepare project with auto defaults -> lands in awaiting_requirements_confirmation
        prep = project_planner.prepare_project(topic="Robotics Evolution", auto_defaults=True)
        proj_id = prep["project_id"]
        self.assertEqual(prep["status"], "awaiting_requirements_confirmation")

        # Calling generate_script before Gate 1 must raise ProjectStateError
        with self.assertRaises(ProjectStateError) as ctx:
            project_planner.generate_script(project_id=proj_id)
        self.assertIn("Gate 1 requirements must be confirmed", str(ctx.exception))

    def test_duplicate_render_returns_existing_job(self):
        # Prepare and approve project
        prep = project_planner.prepare_project(topic="Space Telescopes", auto_defaults=True)
        proj_id = prep["project_id"]
        project_planner.confirm_requirements(proj_id, confirmed=True)
        project_planner.confirm_script(proj_id, confirmed=True)

        # First render
        render1 = project_planner.render_project(proj_id, job_manager=self.mock_jm)
        self.assertEqual(render1["status"], "rendering")
        self.assertEqual(render1["job_id"], "job_test_batch_123")
        self.assertEqual(self.mock_jm.submit_job.call_count, 1)

        # Second render while still rendering -> returns existing job without calling submit_job again
        render2 = project_planner.render_project(proj_id, job_manager=self.mock_jm)
        self.assertEqual(render2["status"], "rendering")
        self.assertEqual(render2["job_id"], "job_test_batch_123")
        self.assertEqual(self.mock_jm.submit_job.call_count, 1)  # Still 1, no duplicate job created!

    def test_rejection_and_cancellation(self):
        prep = project_planner.prepare_project(topic="Quantum Physics Audiobook", auto_defaults=True)
        proj_id = prep["project_id"]

        cancel_res = project_planner.confirm_requirements(project_id=proj_id, confirmed=False)
        self.assertEqual(cancel_res["status"], "cancelled")

        with self.assertRaises(ProjectNotApprovedError):
            project_planner.render_project(project_id=proj_id, job_manager=self.mock_jm)

    def test_fastapi_rest_endpoints(self):
        # 1. Prepare
        resp1 = self.client.post("/api/v1/projects/prepare", json={"topic": "Podcast AI 5 minutes", "auto_defaults": True})
        self.assertEqual(resp1.status_code, 201)
        data1 = resp1.json()
        proj_id = data1["project_id"]
        self.assertEqual(data1["status"], "awaiting_requirements_confirmation")

        # 2. Render before Gate 1 -> Fail 400
        resp_unapproved = self.client.post(f"/api/v1/projects/{proj_id}/render", json={})
        self.assertEqual(resp_unapproved.status_code, 400)

        # 3. Confirm Requirements (Gate 1)
        resp_g1 = self.client.post(f"/api/v1/projects/{proj_id}/confirm-requirements", json={"confirmed": True})
        self.assertEqual(resp_g1.status_code, 200)
        self.assertEqual(resp_g1.json()["status"], "awaiting_script_confirmation")

        # 4. Confirm Script (Gate 2)
        resp_g2 = self.client.post(f"/api/v1/projects/{proj_id}/confirm-script", json={"confirmed": True})
        self.assertEqual(resp_g2.status_code, 200)
        self.assertEqual(resp_g2.json()["status"], "approved")

        # 5. Render after full approval
        with patch("api_app.job_manager", self.mock_jm):
            resp_render = self.client.post(f"/api/v1/projects/{proj_id}/render", json={})
            self.assertEqual(resp_render.status_code, 200)
            self.assertEqual(resp_render.json()["status"], "rendering")
            self.assertTrue(resp_render.json()["segment_count"] > 0)


    def test_event_bus_ring_buffer_and_condition_wait(self):
        from services.event_bus import LocalEventBus
        bus = LocalEventBus(maxlen=3)

        # 1. Test ring buffer maxlen 3
        e1 = bus.emit("render_progress", project_id="p1", progress=10)
        e2 = bus.emit("render_progress", project_id="p1", progress=20)
        e3 = bus.emit("render_progress", project_id="p2", progress=30)
        e4 = bus.emit("completed", project_id="p1", progress=100)

        # e1 dropped, e2, e3, e4 remain
        all_events = bus.get_events(after_id=0, wait_seconds=0)
        self.assertEqual(len(all_events), 3)
        self.assertEqual(all_events[0]["id"], e2["id"])
        self.assertEqual(all_events[2]["id"], e4["id"])

        # 2. Filter by project_id
        p2_events = bus.get_events(after_id=0, project_id="p2", wait_seconds=0)
        self.assertEqual(len(p2_events), 1)
        self.assertEqual(p2_events[0]["id"], e3["id"])

        # 3. Test condition wait timeout
        t0 = time.time()
        timeout_events = bus.get_events(after_id=999, wait_seconds=0.05)
        self.assertEqual(len(timeout_events), 0)
        self.assertTrue(time.time() - t0 >= 0.04)

    def test_event_bus_long_polling_endpoints(self):
        from services.event_bus import event_bus
        event_bus.clear()

        # Emit an event
        ev = event_bus.emit(
            event_type="questions_required",
            project_id="proj_xyz",
            status="awaiting_answers",
            data={"question_count": 3},
        )

        # 1. GET /api/v1/events
        resp = self.client.get(f"/api/v1/events?after_id=0&wait=0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["events"][0]["id"], ev["id"])
        self.assertEqual(data["last_event_id"], ev["id"])

        # 2. GET /api/v1/projects/{project_id}/events
        resp_proj = self.client.get(f"/api/v1/projects/proj_xyz/events?after_id=0&wait=0")
        self.assertEqual(resp_proj.status_code, 200)
        self.assertEqual(resp_proj.json()["count"], 1)

        # 3. Filter other project -> 0 events
        resp_other = self.client.get(f"/api/v1/projects/proj_other/events?after_id=0&wait=0")
        self.assertEqual(resp_other.status_code, 200)
        self.assertEqual(resp_other.json()["count"], 0)

    def test_mcp_get_events_tool(self):
        import mcp_server
        from services.event_bus import event_bus
        event_bus.clear()

        event_bus.emit("approved", project_id="proj_mcp_1", status="approved")

        with patch("mcp_server.make_api_request") as mock_req:
            mock_req.return_value = {
                "events": [{"id": 1, "type": "approved", "project_id": "proj_mcp_1", "status": "approved"}],
                "count": 1,
                "last_event_id": 1,
            }
            res = mcp_server.execute_tool("chatterbox_get_events", {"after_event_id": 0, "wait_seconds": 0})
            self.assertFalse(res.get("isError", False))
            self.assertIn("Chatterbox Event Stream", res["content"][0]["text"])
            self.assertIn("approved", res["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
