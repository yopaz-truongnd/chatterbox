"""Unit tests for Voice Project Cancellation, Concurrency, and Recovery (Phase 12-13 Hardening)."""

import os
from pathlib import Path
import tempfile
import time
import unittest

from services.render_models import ProjectStatus
from services.tts.base import CancellationToken
from services.voice_project_models import InvalidProjectStateError
from services.voice_project_operations import (
    OperationAlreadyRunningError,
    OperationStatus,
    VoiceProjectOperationManager,
)
from services.voice_project_store import VoiceProjectStore


class TestVoiceProjectCancellation(unittest.TestCase):
    """Test cancellation propagation, concurrency serialization, and state recovery."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.ops_dir = Path(self.temp_dir.name) / "operations"
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        self.manager = VoiceProjectOperationManager(max_workers=2, operations_dir=self.ops_dir)
        self.store = VoiceProjectStore(root_dir=Path(self.temp_dir.name) / "projects")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cancel_running_operation_holds_lock_until_worker_exits(self):
        executed_iterations = 0

        def cancellable_task(*args, cancellation_token: CancellationToken = None, **kwargs):
            nonlocal executed_iterations
            for _ in range(20):
                if cancellation_token and cancellation_token.is_cancelled():
                    return {"cancelled": True}
                executed_iterations += 1
                time.sleep(0.03)
            return {"done": True}

        op = self.manager.submit("proj_hold_lock", "long_op", cancellable_task)
        time.sleep(0.05)

        # Cancel while running
        success, msg = self.manager.cancel_operation(op.id)
        self.assertTrue(success)

        # Immediately attempting a second submit on the same project MUST be rejected
        # because the background worker is still cleaning up and holds project active lock
        with self.assertRaises(OperationAlreadyRunningError):
            self.manager.submit("proj_hold_lock", "second_op", cancellable_task)

        # Wait for worker to observe token cancellation and exit
        for _ in range(50):
            curr = self.manager.get_operation(op.id)
            if curr and curr.status == OperationStatus.CANCELLED:
                break
            time.sleep(0.03)

        final_op = self.manager.get_operation(op.id)
        self.assertEqual(final_op.status, OperationStatus.CANCELLED)

        # Now that worker has cleanly exited, a new operation CAN be submitted
        new_op = self.manager.submit("proj_hold_lock", "second_op", lambda *a, **k: {"ok": True})
        self.assertIsNotNone(new_op)

    def test_startup_recovery_marks_interrupted_operations(self):
        # Create an operation file manually simulating an active running operation when server crashed
        fake_op_id = "vp_op_crashed_123"
        fake_op_file = self.ops_dir / f"{fake_op_id}.yaml"
        fake_content = (
            f"id: {fake_op_id}\n"
            "project_id: crashed_project\n"
            "operation: render\n"
            "status: running\n"
            "progress_percent: 45.0\n"
            "created_at: '2026-01-01T00:00:00Z'\n"
            "updated_at: '2026-01-01T00:00:00Z'\n"
        )
        with open(fake_op_file, "w", encoding="utf-8") as f:
            f.write(fake_content)

        # Initialize a new manager pointing to the same operations directory
        recovered_manager = VoiceProjectOperationManager(max_workers=2, operations_dir=self.ops_dir)
        recovered_op = recovered_manager.get_operation(fake_op_id)

        self.assertIsNotNone(recovered_op)
        self.assertEqual(recovered_op.status, OperationStatus.INTERRUPTED)
        self.assertEqual(recovered_op.error["code"], "OPERATION_INTERRUPTED")


if __name__ == "__main__":
    unittest.main()
