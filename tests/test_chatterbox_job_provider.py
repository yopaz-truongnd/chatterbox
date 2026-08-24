"""Unit tests for in-process ChatterboxJobProvider and JobExecutionGateway (Phase 10A & 10B)."""

from __future__ import annotations

import io
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import wave

from services.render_models import (
    ProviderErrorType,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.base import CancellationToken
from services.tts.chatterbox_job import ChatterboxJobProvider, JobExecutionGateway


class FakeJob:
    def __init__(self, job_id: str, status: str = "completed", output_path: str | None = None, error: str | None = None):
        self.id = job_id
        self.status = status
        self.phase = status
        self.progress_percent = 100.0 if status == "completed" else 0.0
        self.output_path = output_path
        self.error = error


class FakeGateway:
    def __init__(self, output_wav_path: str):
        self.output_wav_path = output_wav_path
        self.submitted_params: list[dict] = []
        self.jobs: dict[str, FakeJob] = {}
        self.cancelled_jobs: set[str] = set()

    def submit_job(self, model: str, params: dict, input_paths: list[str]) -> FakeJob:
        self.submitted_params.append(params)
        job_id = f"job_inproc_{len(self.jobs) + 1}"
        job = FakeJob(job_id=job_id, status="completed", output_path=self.output_wav_path)
        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> FakeJob | None:
        return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> tuple[bool, str]:
        self.cancelled_jobs.add(job_id)
        if job_id in self.jobs:
            self.jobs[job_id].status = "cancelled"
        return True, "Cancelled"


class SlowFakeGateway(FakeGateway):
    def submit_job(self, model: str, params: dict, input_paths: list[str]) -> FakeJob:
        job_id = f"job_slow_{len(self.jobs) + 1}"
        job = FakeJob(job_id=job_id, status="queued", output_path=self.output_wav_path)
        self.jobs[job_id] = job
        return job


class TestChatterboxJobProviderPhase10A(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="cb_job_test_"))
        
        # Build 1s of valid 24kHz 16-bit mono WAV file on disk
        self.sample_wav = self.temp_dir / "sample_output.wav"
        with wave.open(str(self.sample_wav), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            samples = []
            for i in range(24000):
                val = int(12000 * math.sin(2.0 * math.pi * 440.0 * (i / 24000.0)))
                samples.append(struct.pack("<h", val))
            wf.writeframes(b"".join(samples))

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_job_provider_with_fake_gateway_success(self):
        gateway = FakeGateway(output_wav_path=str(self.sample_wav))
        provider = ChatterboxJobProvider(gateway=gateway, default_model="nano")

        req = TTSRenderRequest(
            project_id="torch_dragon",
            beat_id="B01",
            attempt_id=1,
            text="Direct in-process execution",
            voice_profile="mythology_narrator_male",
            energy=3.0,
        )

        render_output_dir = self.temp_dir / "renders" / "B01"
        result = provider.render(req, render_output_dir)

        self.assertTrue(result.success)
        self.assertEqual(result.provider, "chatterbox-job")
        self.assertEqual(result.model, "nano")
        self.assertEqual(result.provider_request_id, "job_inproc_1")
        self.assertTrue(Path(result.audio_path).exists())

    def test_job_provider_multilingual_language_id(self):
        gateway = FakeGateway(output_wav_path=str(self.sample_wav))
        provider = ChatterboxJobProvider(gateway=gateway, default_model="multilingual")

        req = TTSRenderRequest(
            project_id="torch_dragon",
            beat_id="B01",
            attempt_id=1,
            text="Multilingual test",
            language="en-US",
        )

        result = provider.render(req, self.temp_dir)
        self.assertTrue(result.success)
        self.assertEqual(gateway.submitted_params[0]["language_id"], "en")

    def test_job_provider_pronunciation_dict_applied(self):
        gateway = FakeGateway(output_wav_path=str(self.sample_wav))
        provider = ChatterboxJobProvider(gateway=gateway, default_model="nano")

        req = TTSRenderRequest(
            project_id="torch_dragon",
            beat_id="B01",
            attempt_id=1,
            text="The beast Zhulong woke up.",
            pronunciation={"Zhulong": "Joo-long"},
        )

        result = provider.render(req, self.temp_dir)
        self.assertTrue(result.success)
        self.assertEqual(gateway.submitted_params[0]["text"], "The beast Joo-long woke up.")

    def test_job_provider_timeout_cancels_orphan_job(self):
        gateway = SlowFakeGateway(output_wav_path=str(self.sample_wav))
        provider = ChatterboxJobProvider(
            gateway=gateway,
            default_model="nano",
            timeout_seconds=0.03,
            poll_interval_seconds=0.01,
        )

        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Timeout test")
        result = provider.render(req, self.temp_dir)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.TIMEOUT)
        self.assertIn("job_slow_1", gateway.cancelled_jobs)

    def test_job_provider_cancellation(self):
        gateway = FakeGateway(output_wav_path=str(self.sample_wav))
        provider = ChatterboxJobProvider(gateway=gateway, default_model="nano")

        token = CancellationToken()
        token.cancel()

        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Cancel test")
        result = provider.render(req, self.temp_dir, cancellation_token=token)

        self.assertFalse(result.success)
        self.assertIn("cancelled", result.error.lower())


if __name__ == "__main__":
    unittest.main()
