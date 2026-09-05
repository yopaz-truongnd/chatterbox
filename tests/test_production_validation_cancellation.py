"""Unit tests for Phase 21 production cancellation and recovery validation."""

from pathlib import Path
import tempfile
import unittest

from services.production_validation_models import ProductionValidationRequest
from services.production_validation_service import ProductionValidationService
from services.tts.base import CancellationToken
from services.tts.fake import FakeTTSProvider
from services.voice_project_store import VoiceProjectStore


class TestProductionValidationCancellation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceProjectStore(Path(self.tmp.name) / "projects")
        self.provider = FakeTTSProvider()
        self.service = ProductionValidationService(
            store=self.store,
            execution_port=self.provider,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_cancellation_during_validation(self):
        token = CancellationToken()
        token.cancel()  # Pre-cancelled token

        req = ProductionValidationRequest(
            script_text="High upon the mountain the winds blew.",
            provider="fake",
            model="nano",
            output_formats=["wav"],
            run_cancellation_tests=True,
        )

        report = self.service.validate(req, cancellation_token=token)
        # Should have stopped and recorded cancellation
        cancelled_step = any(s.status == "cancelled" for s in report.steps)
        self.assertTrue(cancelled_step or report.status in ("failed", "cancelled"))

    def test_opt_in_cancellation_safety_check(self):
        req = ProductionValidationRequest(
            script_text="The Titan stood against the storm.\n\nHe refused to surrender.",
            provider="fake",
            model="nano",
            output_formats=["wav"],
            run_incremental_reproduction=False,
            run_cancellation_tests=True,
        )
        report = self.service.validate(req)
        self.assertEqual(report.status, "completed")
        self.assertTrue(report.cancellation_recovery_passed)


if __name__ == "__main__":
    unittest.main()
