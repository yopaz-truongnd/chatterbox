"""Unit tests for in-process ChatterboxJobProvider and JobExecutionGateway (Phase 10A & 10B)."""

from __future__ import annotations

import io
import math
from pathlib import Path
import shutil
import struct
import tempfile
import threading
import unittest
import unittest.mock as mock
import wave

from services.render_models import (
    ProviderErrorType,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.base import CancellationToken
from services.tts.chatterbox_job import ChatterboxJobProvider, DefaultJobManagerGateway, JobExecutionGateway
from services.tts.provider_factory import create_tts_provider


class FakeJob:
    def __init__(self, job_id: str, status: str = "completed", output_path: str | None = None, error: str | None = None):
        self.id = job_id
        self.status = status
        self.phase = status
        self.progress_percent = 100.0 if status == "completed" else 0.0
        self.output_path = output_path
        self.error = error


class FakeGateway:
    def __init__(self, output_wav_path: str, is_worker: bool = False):
        self.output_wav_path = output_wav_path
        self.submitted_params: list[dict] = []
        self.jobs: dict[str, FakeJob] = {}
        self.cancelled_jobs: set[str] = set()
        self._is_worker = is_worker
        self.sync_executions: list[dict] = []

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

    def execute_sync(
        self,
        model: str,
        params: dict,
        output_path: Path | str,
        progress_callback=None,
        cancellation_token=None,
    ) -> tuple[bool, str | None]:
        self.sync_executions.append({"model": model, "params": params, "output_path": str(output_path)})
        shutil.copyfile(self.output_wav_path, output_path)
        if progress_callback:
            progress_callback("completed", 100.0, {"status": "completed"})
        return True, None

    def is_worker_thread(self) -> bool:
        return self._is_worker


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

        self.assertTrue(result.success, result.error)
        self.assertEqual(result.provider, "chatterbox-job")
        self.assertEqual(result.model, "nano")
        self.assertEqual(result.provider_request_id, "job_inproc_1")
        self.assertTrue(Path(result.audio_path).exists())

    def test_factory_fails_fast_when_chatterbox_job_has_no_gateway(self):
        with self.assertRaisesRegex(ValueError, "requires an injected JobExecutionGateway"):
            create_tts_provider("chatterbox-job")

        gateway = FakeGateway(output_wav_path=str(self.sample_wav))
        provider = create_tts_provider("chatterbox-job", gateway=gateway)
        self.assertIsInstance(provider, ChatterboxJobProvider)

    def test_default_job_manager_gateway_integration(self):
        class MockJobManager:
            def __init__(self, sample_wav):
                self.sample_wav = sample_wav
                self.executed = False
                self._worker_thread = threading.current_thread()

            def execute_sync(self, model, params, output_path, cb):
                self.executed = True
                shutil.copyfile(self.sample_wav, output_path)
                return True, None

        mock_jm = MockJobManager(self.sample_wav)
        gateway = DefaultJobManagerGateway(mock_jm)
        self.assertTrue(gateway.is_worker_thread())

        out_dest = self.temp_dir / "sync_test.wav"
        ok, err = gateway.execute_sync("nano", {"text": "test"}, out_dest)
        self.assertTrue(ok)
        self.assertTrue(mock_jm.executed)
        self.assertTrue(out_dest.exists())

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

    def test_job_provider_worker_thread_uses_gateway_execute_sync(self):
        # Gateway reports caller is on worker thread
        gateway = FakeGateway(output_wav_path=str(self.sample_wav), is_worker=True)
        provider = ChatterboxJobProvider(gateway=gateway, default_model="nano")
        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Worker thread direct render")

        result = provider.render(req, self.temp_dir / "worker_render")

        self.assertTrue(result.success, result.error)
        self.assertEqual(len(gateway.sync_executions), 1)
        self.assertEqual(gateway.sync_executions[0]["model"], "nano")
        self.assertEqual(len(gateway.submitted_params), 0)  # Did NOT submit child queue job


if __name__ == "__main__":
    unittest.main()
