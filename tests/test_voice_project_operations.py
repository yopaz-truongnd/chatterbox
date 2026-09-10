"""Unit tests for Voice Project Async Operation Manager (Phase 12)."""

import time
import unittest

from services.tts.base import CancellationToken
from services.voice_project_operations import (
    OperationAlreadyRunningError,
    OperationStatus,
    VoiceProjectOperationManager,
)


class TestVoiceProjectOperations(unittest.TestCase):
    """Test background operation scheduling, tracking, concurrency locks, and cancellation."""

    def setUp(self):
        self.manager = VoiceProjectOperationManager(max_workers=2)

    def test_submit_and_complete_operation(self):
        def sample_task(*args, cancellation_token=None, progress_callback=None, **kwargs):
            if progress_callback:
                progress_callback("processing", 50.0, beat_id="B01")
            return {"status": "success", "result_val": 42}

        op = self.manager.submit("p1", "test_op", sample_task)
        self.assertEqual(op.status, OperationStatus.QUEUED)
        self.assertEqual(op.project_id, "p1")

        # Wait for worker thread to finish
        for _ in range(50):
            time.sleep(0.05)
            curr = self.manager.get_operation(op.id)
            if curr and curr.status == OperationStatus.COMPLETED:
                break

        final_op = self.manager.get_operation(op.id)
        self.assertIsNotNone(final_op)
        self.assertEqual(final_op.status, OperationStatus.COMPLETED)
        self.assertEqual(final_op.progress_percent, 100.0)
        self.assertEqual(final_op.result, {"status": "success", "result_val": 42})

    def test_concurrency_lock_rejects_overlapping_operation_on_same_project(self):
        release_event = time.sleep

        def slow_task(*args, cancellation_token=None, progress_callback=None, **kwargs):
            time.sleep(0.3)
            return {"done": True}

        op1 = self.manager.submit("proj_busy", "op1", slow_task)
        self.assertIn(op1.status, (OperationStatus.QUEUED, OperationStatus.RUNNING))

        # Attempting second operation on same project must raise OperationAlreadyRunningError
        with self.assertRaises(OperationAlreadyRunningError):
            self.manager.submit("proj_busy", "op2", slow_task)

        # Wait for op1 to finish
        time.sleep(0.4)
        op2 = self.manager.submit("proj_busy", "op2", slow_task)
        self.assertIsNotNone(op2)

    def test_cancel_running_operation(self):
        def cancellable_task(*args, cancellation_token: CancellationToken = None, progress_callback=None, **kwargs):
            for _ in range(20):
                if cancellation_token and cancellation_token.is_cancelled:
                    return {"cancelled": True}
                time.sleep(0.05)
            return {"done": True}

        op = self.manager.submit("proj_cancel", "long_op", cancellable_task)
        time.sleep(0.05)

        success, msg = self.manager.cancel_operation(op.id)
        self.assertTrue(success)

        time.sleep(0.2)
        curr = self.manager.get_operation(op.id)
        self.assertEqual(curr.status, OperationStatus.CANCELLED)

    def test_list_operations_filtering(self):
        def quick_task(*args, **kwargs):
            return {}

        op1 = self.manager.submit("proj_a", "op1", quick_task)
        time.sleep(0.05)
        op2 = self.manager.submit("proj_b", "op2", quick_task)
        time.sleep(0.05)

        all_ops = self.manager.list_operations()
        self.assertGreaterEqual(len(all_ops), 2)

        proj_a_ops = self.manager.list_operations(project_id="proj_a")
        self.assertEqual(len(proj_a_ops), 1)
        self.assertEqual(proj_a_ops[0].project_id, "proj_a")


if __name__ == "__main__":
    unittest.main()
