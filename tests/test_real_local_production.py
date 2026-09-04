"""Opt-in Real-Runtime Production Validation Test Suite (Phase 21).

Tests the full canonical pipeline against real local inference when available,
and skips cleanly when models, JobManager, or hardware requirements are absent.
"""

import os
from pathlib import Path
import tempfile
import unittest

from services.local_runtime_service import LocalRuntimeService
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
        caps = self.runtime_service.get_capabilities()
        if not opt_in or not cached_nano or not caps.available:
            self.skipTest(
                "Real local model test requires CHATTERBOX_REAL_PRODUCTION_TEST=1 and cached 'nano' model; skipping."
            )

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
        self.assertEqual(report.status, "completed")
        self.assertIn(report.verdict, (ValidationVerdict.PASS, ValidationVerdict.PASS_WITH_WARNINGS))


if __name__ == "__main__":
    unittest.main()
