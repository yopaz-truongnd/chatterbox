"""Unit tests for Phase 21 Production Validation models."""

import unittest
from services.production_validation_models import (
    ProductionValidationArtifact,
    ProductionValidationBeatMetric,
    ProductionValidationFailure,
    ProductionValidationMetric,
    ProductionValidationReport,
    ProductionValidationRequest,
    ProductionValidationStep,
    ValidationVerdict,
)


class TestProductionValidationModels(unittest.TestCase):
    def test_request_defaults(self):
        req = ProductionValidationRequest()
        self.assertEqual(req.provider, "local")
        self.assertIsNone(req.model)
        self.assertEqual(req.language, "en")
        self.assertEqual(req.output_formats, ["wav", "mp3"])
        self.assertTrue(req.require_final_approval)
        self.assertTrue(req.require_narration_acceptance)
        self.assertTrue(req.run_incremental_reproduction)
        self.assertFalse(req.run_cancellation_tests)

    def test_step_lifecycle(self):
        step = ProductionValidationStep(name="preflight", status="running")
        self.assertEqual(step.name, "preflight")
        self.assertEqual(step.status, "running")
        step.status = "passed"
        step.duration_ms = 120.5
        self.assertEqual(step.status, "passed")
        self.assertEqual(step.duration_ms, 120.5)

    def test_beat_metric_serialization(self):
        bm = ProductionValidationBeatMetric(
            beat_id="beat_001",
            text_length=120,
            duration_ms=4500.0,
            render_duration_ms=1200.0,
            attempt_count=1,
            selected_attempt=1,
            qc_score=0.92,
            qc_verdict="PASSED",
            provider="local",
            model="nano",
        )
        data = bm.model_dump(mode="json")
        self.assertEqual(data["beat_id"], "beat_001")
        self.assertEqual(data["qc_score"], 0.92)
        self.assertEqual(data["qc_verdict"], "PASSED")

    def test_artifact_and_failure(self):
        art = ProductionValidationArtifact(
            artifact_id="final_wav",
            file_name="FINAL.wav",
            file_path="exports/FINAL.wav",
            sha256="abc123def456",
            size_bytes=102400,
            format="wav",
            duration_ms=5000.0,
            sample_rate=24000,
            loudness_lufs=-14.2,
            verified_lineage=True,
        )
        self.assertTrue(art.verified_lineage)
        self.assertEqual(art.format, "wav")

        fail = ProductionValidationFailure(
            step_name="render",
            code="TIMEOUT",
            message="Render timed out",
            recoverable=True,
        )
        self.assertTrue(fail.recoverable)
        self.assertEqual(fail.code, "TIMEOUT")

    def test_report_serialization_and_verdict(self):
        rep = ProductionValidationReport(
            validation_id="val_test123",
            status="completed",
            verdict=ValidationVerdict.PASS,
            started_at="2026-09-04T00:00:00Z",
            provider="local",
            model="nano",
            device="cpu",
            project_id="vproj_123",
            beat_count=4,
            qc_pass_count=4,
        )
        data = rep.model_dump(mode="json")
        self.assertEqual(data["verdict"], "PASS")
        self.assertEqual(data["beat_count"], 4)
        restored = ProductionValidationReport.model_validate(data)
        self.assertEqual(restored.validation_id, "val_test123")
        self.assertEqual(restored.verdict, ValidationVerdict.PASS)


if __name__ == "__main__":
    unittest.main()
