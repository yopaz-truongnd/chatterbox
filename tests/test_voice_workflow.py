"""Unit tests for Unified Autonomous Voice Workflow (Phase 15)."""

import os
from pathlib import Path
import tempfile
import threading
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

    def test_workflow_happy_path_produces_final_deliverables_and_tracks_operations(self):
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

        # Verify operations were tracked on steps
        plan_step = next((s for s in final_state.steps if s.name == "plan"), None)
        self.assertIsNotNone(plan_step)
        self.assertEqual(plan_step.status, "completed")
        self.assertIsNotNone(plan_step.operation_id)

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

    def test_workflow_require_final_approval_human_gate_and_resume(self):
        script = "The morning sun rose gently over the calm green valley."
        policy = WorkflowPolicy(provider="fake", require_final_approval=True)

        state = self.service.start_workflow(
            script_text=script,
            project_id="wf_approval_01",
            policy=policy,
        )

        # 1. Workflow must pause before export at WAITING_FOR_HUMAN
        final_state = self._wait_for_workflow(state.workflow_id, target_statuses=(WorkflowStatus.WAITING_FOR_HUMAN,))
        self.assertEqual(final_state.status, WorkflowStatus.WAITING_FOR_HUMAN)
        self.assertIsNotNone(final_state.human_action)
        self.assertEqual(final_state.human_action["action_type"], "final_audio_approval")
        self.assertEqual(final_state.human_action["resume_action"], "export")

        # 2. Resume workflow: should execute export and transition to COMPLETED
        resumed_state = self.service.resume_workflow(state.workflow_id)
        self.assertEqual(resumed_state.status, WorkflowStatus.RUNNING)

        completed_state = self._wait_for_workflow(state.workflow_id, target_statuses=(WorkflowStatus.COMPLETED,))
        self.assertEqual(completed_state.status, WorkflowStatus.COMPLETED)
        self.assertTrue(any(a["id"] == "final_wav" for a in completed_state.result["artifacts"]))

    def test_workflow_cancellation_propagates(self):
        script = "The morning sun rose gently over the calm green valley."
        policy = WorkflowPolicy(provider="fake")

        state = self.service.start_workflow(
            script_text=script,
            project_id="wf_cancel_01",
            policy=policy,
        )

        success, msg = self.service.cancel_workflow(state.workflow_id)
        self.assertTrue(success)

        # Wait for workflow to settle to CANCELLED
        settled_state = self._wait_for_workflow(state.workflow_id, target_statuses=(WorkflowStatus.CANCELLED,))
        self.assertEqual(settled_state.status, WorkflowStatus.CANCELLED)

    def test_workflow_cancellation_race_condition_never_regresses_status(self):
        """Stress test: rapid cancel during concurrent background worker execution."""
        script = "The morning sun rose gently over the calm green valley."
        policy = WorkflowPolicy(provider="fake")

        for i in range(5):
            state = self.service.start_workflow(
                script_text=script,
                project_id=f"wf_race_{i}",
                policy=policy,
            )
            time.sleep(0.01)  # allow thread to spin up
            self.service.cancel_workflow(state.workflow_id)

            settled = self._wait_for_workflow(state.workflow_id, target_statuses=(WorkflowStatus.CANCELLED,))
            self.assertEqual(settled.status, WorkflowStatus.CANCELLED)

    def test_workflow_fails_safely_on_invalid_provider(self):
        script = "The morning sun rose gently over the calm green valley."
        policy = WorkflowPolicy(provider="nonexistent_provider_xyz")

        state = self.service.start_workflow(
            script_text=script,
            project_id="wf_bad_prov",
            policy=policy,
        )

        final_state = self._wait_for_workflow(state.workflow_id, target_statuses=(WorkflowStatus.FAILED,))
        self.assertEqual(final_state.status, WorkflowStatus.FAILED)
        self.assertIsNotNone(final_state.error)

    def _wait_for_workflow(self, wf_id: str, target_statuses=(WorkflowStatus.COMPLETED, WorkflowStatus.FAILED), max_retries=100):
        for _ in range(max_retries):
            st = self.service.get_workflow(wf_id)
            if st and st.status in target_statuses:
                return st
            time.sleep(0.05)
        st = self.service.get_workflow(wf_id)
        self.fail(f"Workflow {wf_id} timed out; final status: {st.status.value if st else 'None'}")


if __name__ == "__main__":
    unittest.main()
