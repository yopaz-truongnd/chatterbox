"""Opt-in Real-Runtime Production Validation Test Suite (Phase 21).

Tests the full canonical pipeline against real local inference when available,
and skips cleanly when models, JobManager, or hardware requirements are absent.
"""

import os
from pathlib import Path
import tempfile
import unittest

from services.local_runtime_service import LocalRuntimeService
from services.job_manager import JobManager
from services.model_registry import MODEL_REGISTRY, is_model_cached
from services.production_validation_models import (
    ProductionValidationRequest,
    ValidationVerdict,
)
from services.production_validation_service import ProductionValidationService
from services.tts.fake import FakeTTSProvider
from services.voice_project_store import VoiceProjectStore


class TestRealLocalProduction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = VoiceProjectStore(Path(self.tmp.name) / "projects")
        self.runtime_service = LocalRuntimeService()

    def tearDown(self):
        self.tmp.cleanup()

    def test_production_validation_with_fake_runtime(self):
        """Always-passing baseline production validation using FakeTTSProvider."""
        service = ProductionValidationService(
            store=self.store,
            execution_port=FakeTTSProvider(),
        )
        req = ProductionValidationRequest(
            script_text="The Titan gazed down upon the sleeping valleys.\n\nHe brought the flame.",
            provider="fake",
            model="nano",
            output_formats=["wav"],
            run_incremental_reproduction=True,
        )
        report = service.validate(req)
        self.assertEqual(report.status, "completed")
        self.assertIn(report.verdict, (ValidationVerdict.PASS, ValidationVerdict.PASS_WITH_WARNINGS))

    def test_real_local_production_opt_in(self):
        """Opt-in test with real local model inference; skips cleanly if unavailable."""
        models_dir = Path(os.environ.get("HF_HUB_CACHE", "models"))
        cached_nano = is_model_cached("nano", models_dir)

        opt_in = os.environ.get("CHATTERBOX_REAL_PRODUCTION_TEST") == "1"
        if not opt_in or not cached_nano:
            self.skipTest(
                "Real local model test requires CHATTERBOX_REAL_PRODUCTION_TEST=1 and cached 'nano' model; skipping."
            )

        import api_app

        manager = JobManager(Path(self.tmp.name) / "jobs", Path.cwd(), api_app.DEVICE, api_app.CPU_THREADS)
        previous_manager, api_app.job_manager = api_app.job_manager, manager
        manager.startup()
        try:
            self.assertTrue(self.runtime_service.get_capabilities().available)
            service = ProductionValidationService(store=self.store)
            req = ProductionValidationRequest(
                script_text=(
                    "High atop the mountain of Olympus, the cold wind whispered.\n\n"
                    "Prometheus touched the reed to the hearth, and light returned."
                ),
                provider="local",
                model="nano",
                language="en",
                output_formats=["wav"],
                run_incremental_reproduction=True,
            )
            report = service.validate(req)
            job_errors = [job.error for job in manager.list_jobs() if job.error]
            self.assertEqual(
                report.status,
                "completed",
                f"{report.model_dump_json(indent=2)}\nJob errors: {job_errors}",
            )
            self.assertIn(report.verdict, (ValidationVerdict.PASS, ValidationVerdict.PASS_WITH_WARNINGS))
        finally:
            manager.shutdown()
            api_app.job_manager = previous_manager


if __name__ == "__main__":
    unittest.main()
