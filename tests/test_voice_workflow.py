"""Unit tests for Unified Autonomous Voice Workflow (Phase 15)."""

import os
from pathlib import Path
import tempfile
import time
import unittest

from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_models import WorkflowPolicy, WorkflowStatus
from services.voice_project_workflow_store import VoiceProjectWorkflowStore


class TestVoiceWorkflow(unittest.TestCase):
    """Test full produce(), human action pauses, resume, and crash recovery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        os.environ["CHATTERBOX_API_DATA_DIR"] = str(self.temp_dir.name)
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"
        self.wf_store = VoiceProjectWorkflowStore(root_dir=Path(self.temp_dir.name) / "workflows")
        self.service = VoiceProjectWorkflowService(store=self.wf_store)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_workflow_happy_path_produces_final_deliverables(self):
        script = "The morning sun rose gently over the calm green valley."
        policy = WorkflowPolicy(provider="fake")

        state = self.service.start_workflow(
            script_text=script,
            project_id="wf_happy_01",
            title="Happy Valley",
            policy=policy,
        )
        self.assertEqual(state.status, WorkflowStatus.RUNNING)

        # Wait for background orchestration thread to complete all steps
        final_state = self._wait_for_workflow(state.workflow_id)
        self.assertEqual(final_state.status, WorkflowStatus.COMPLETED)
        self.assertIsNotNone(final_state.result)
        self.assertIn("artifacts", final_state.result)
        self.assertTrue(any(a["id"] == "final_wav" for a in final_state.result["artifacts"]))

    def test_workflow_pauses_at_required_resource_human_gate(self):
        script = "Long ago the mysterious beast Qiongqi walked Mount Zhong."
        policy = WorkflowPolicy(provider="fake")

        state = self.service.start_workflow(
            script_text=script,
            project_id="wf_blocked_01",
            policy=policy,
        )

        final_state = self._wait_for_workflow(state.workflow_id, target_statuses=(WorkflowStatus.WAITING_FOR_HUMAN,))
        self.assertEqual(final_state.status, WorkflowStatus.WAITING_FOR_HUMAN)
        self.assertIsNotNone(final_state.human_action)
        self.assertEqual(final_state.human_action["action_type"], "resource_required")
        self.assertIn("Qiongqi", final_state.human_action["items"])

    def test_workflow_cancellation(self):
        script = "The morning sun rose gently over the calm green valley."
        policy = WorkflowPolicy(provider="fake")

        state = self.service.start_workflow(
            script_text=script,
            project_id="wf_cancel_01",
            policy=policy,
        )

        success, msg = self.service.cancel_workflow(state.workflow_id)
        self.assertTrue(success)

        curr = self.service.get_workflow(state.workflow_id)
        self.assertEqual(curr.status, WorkflowStatus.CANCELLED)
        time.sleep(0.1)

    def _wait_for_workflow(self, wf_id: str, target_statuses=(WorkflowStatus.COMPLETED, WorkflowStatus.FAILED), max_retries=60):
        for _ in range(max_retries):
            st = self.service.get_workflow(wf_id)
            if st and st.status in target_statuses:
                return st
            time.sleep(0.05)
        st = self.service.get_workflow(wf_id)
        self.fail(f"Workflow {wf_id} timed out; final status: {st.status.value if st else 'None'}")


if __name__ == "__main__":
    unittest.main()
