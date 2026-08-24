"""Unit tests for Unified Autonomous Voice Workflow (Phase 15)."""

import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowPolicy, WorkflowStatus
from services.voice_project_models import InvalidProjectStateError
from services.voice_project_models import MixPlanStaleError
from services.tts.fake import FakeTTSProvider
from services.voice_project_service import VoiceProjectService
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
        resource_step = next(step for step in final_state.steps if step.name == "check_resources")
        self.assertEqual(resource_step.status, "failed")
        self.assertIsNotNone(resource_step.operation_id)

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

        approval_item = final_state.human_action["items"][0]
        self.assertEqual(approval_item["artifact_id"], "master_wav")
        self.assertTrue(approval_item["sha256"])
        master_path = self.service.project_store.get_project_dir("wf_approval_01") / "mix" / "master.wav"
        self.assertTrue(master_path.exists())

        # 2. Generic resume cannot bypass the approval gate.
        with self.assertRaises(InvalidProjectStateError):
            self.service.resume_workflow(state.workflow_id)

        # 3. Explicit approval executes export and transitions to COMPLETED.
        resumed_state = self.service.approve_workflow(
            state.workflow_id,
            action="approve_final_audio",
            approved=True,
            artifact_id="master_wav",
            artifact_sha256=approval_item["sha256"],
        )
        self.assertEqual(resumed_state.status, WorkflowStatus.RUNNING)

        completed_state = self._wait_for_workflow(state.workflow_id, target_statuses=(WorkflowStatus.COMPLETED,))
        self.assertEqual(completed_state.status, WorkflowStatus.COMPLETED)
        self.assertTrue(any(a["id"] == "final_wav" for a in completed_state.result["artifacts"]))

    def test_qc_always_runs_when_narration_requires_manual_acceptance(self):
        state = self.service.start_workflow(
            script_text="The morning sun rose gently over the calm green valley.",
            project_id="wf_narration_approval",
            policy=WorkflowPolicy(provider="fake", auto_accept_qc_pass=False),
        )

        waiting = self._wait_for_workflow(
            state.workflow_id,
            target_statuses=(WorkflowStatus.WAITING_FOR_HUMAN,),
        )
        self.assertEqual(waiting.human_action["action_type"], "narration_acceptance")
        manifest = self.service.project_store.load_manifest("wf_narration_approval")
        self.assertTrue(manifest.beats)
        self.assertTrue(all(beat.status.value == "passed" for beat in manifest.beats.values()))

        with self.assertRaises(InvalidProjectStateError):
            self.service.resume_workflow(state.workflow_id)

        self.service.approve_workflow(
            state.workflow_id,
            action="approve_narration",
            approved=True,
        )
        completed = self._wait_for_workflow(state.workflow_id)
        self.assertEqual(completed.status, WorkflowStatus.COMPLETED)

    def test_final_approval_rejects_changed_master(self):
        state = self.service.start_workflow(
            script_text="The morning sun rose gently over the calm green valley.",
            project_id="wf_changed_master",
            policy=WorkflowPolicy(provider="fake", require_final_approval=True),
        )
        waiting = self._wait_for_workflow(
            state.workflow_id,
            target_statuses=(WorkflowStatus.WAITING_FOR_HUMAN,),
        )
        item = waiting.human_action["items"][0]
        master_path = self.service.project_store.get_project_dir("wf_changed_master") / "mix" / "master.wav"
        master_path.write_bytes(master_path.read_bytes() + b"changed")

        with self.assertRaises(InvalidProjectStateError):
            self.service.approve_workflow(
                state.workflow_id,
                action="approve_final_audio",
                approved=True,
                artifact_id="master_wav",
                artifact_sha256=item["sha256"],
            )

        self.assertEqual(self.service.get_workflow(state.workflow_id).status, WorkflowStatus.WAITING_FOR_HUMAN)

    def test_terminal_state_cannot_be_overwritten(self):
        state = self.service.start_workflow(
            script_text="The morning sun rose gently over the calm green valley.",
            project_id="wf_terminal_guard",
            policy=WorkflowPolicy(provider="fake"),
        )
        completed = self._wait_for_workflow(state.workflow_id)
        self.assertEqual(completed.status, WorkflowStatus.COMPLETED)

        stale = completed.model_copy(deep=True)
        stale.status = WorkflowStatus.FAILED
        self.assertFalse(self.wf_store.save_workflow(stale))
        self.assertEqual(self.service.get_workflow(state.workflow_id).status, WorkflowStatus.COMPLETED)

    def test_transition_is_atomic_across_store_instances(self):
        state = VoiceWorkflowState(
            workflow_id="vwf_atomic_claim",
            project_id="atomic_claim",
            status=WorkflowStatus.WAITING_FOR_HUMAN,
        )
        self.wf_store.save_workflow(state)
        second_store = VoiceProjectWorkflowStore(root_dir=self.wf_store.root_dir)
        barrier = threading.Barrier(2)
        outcomes = []

        def claim(store):
            barrier.wait()
            try:
                store.transition_workflow(
                    state.workflow_id,
                    WorkflowStatus.WAITING_FOR_HUMAN,
                    lambda current: setattr(current, "status", WorkflowStatus.RUNNING),
                )
                outcomes.append("claimed")
            except InvalidProjectStateError:
                outcomes.append("rejected")

        threads = [threading.Thread(target=claim, args=(store,)) for store in (self.wf_store, second_store)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual(outcomes, ["claimed", "rejected"])

    def test_store_recovery_runs_only_when_explicitly_requested_at_startup(self):
        running = VoiceWorkflowState(
            workflow_id="vwf_running_poll",
            project_id="running_poll",
            status=WorkflowStatus.RUNNING,
        )
        self.wf_store.save_workflow(running)

        second_store = VoiceProjectWorkflowStore(root_dir=self.wf_store.root_dir)
        self.assertEqual(second_store.get_workflow(running.workflow_id).status, WorkflowStatus.RUNNING)

        second_store.recover_interrupted_workflows()
        self.assertEqual(second_store.get_workflow(running.workflow_id).status, WorkflowStatus.INTERRUPTED)

    def test_rerender_makes_existing_premaster_and_master_stale(self):
        state = self.service.start_workflow(
            script_text="The morning sun rose gently over the calm green valley.",
            project_id="wf_stale_downstream",
            policy=WorkflowPolicy(provider="fake"),
        )
        completed = self._wait_for_workflow(state.workflow_id)
        self.assertEqual(completed.status, WorkflowStatus.COMPLETED)

        project_service = VoiceProjectService(
            store=self.service.project_store,
            execution_port=FakeTTSProvider(),
            provider_name="fake",
        )
        beat_id = next(iter(project_service.store.load_manifest("wf_stale_downstream").beats))
        project_service.render_beat("wf_stale_downstream", beat_id)

        with self.assertRaises(MixPlanStaleError):
            project_service.master("wf_stale_downstream")
        with self.assertRaises(MixPlanStaleError):
            project_service.export("wf_stale_downstream")

    def test_workflow_persistence_failure_is_not_silenced(self):
        state = VoiceWorkflowState(
            workflow_id="vwf_write_failure",
            project_id="write_failure",
        )
        with mock.patch("pathlib.Path.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.wf_store.save_workflow(state)

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
