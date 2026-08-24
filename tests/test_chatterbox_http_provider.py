"""Unit tests for ChatterboxHttpProvider and Provider Factory (Phase 10A & 10B)."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
import unittest.mock as mock
import urllib.error
import urllib.parse
import wave

from services.render_models import (
    ProviderErrorType,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.base import CancellationToken
from services.tts.chatterbox_http import ChatterboxHttpProvider, normalize_language_id
from services.tts.fake import FakeTTSProvider
from services.tts.gemini import GeminiTTSProvider
from services.tts.provider_factory import create_tts_provider


class TestChatterboxHttpProviderPhase10A(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="cb_http_test_"))
        
        # Build 1s of valid 24kHz 16-bit mono WAV bytes
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            samples = []
            for i in range(24000):
                val = int(12000 * math.sin(2.0 * math.pi * 440.0 * (i / 24000.0)))
                samples.append(struct.pack("<h", val))
            wf.writeframes(b"".join(samples))
        self.valid_wav_bytes = buf.getvalue()

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_provider_factory_canonical_priority(self):
        # Default should be chatterbox-http with auto model
        p_default = create_tts_provider()
        self.assertIsInstance(p_default, ChatterboxHttpProvider)
        self.assertEqual(p_default.default_model, "auto")

        # Explicit gemini
        p_gemini = create_tts_provider("gemini")
        self.assertIsInstance(p_gemini, GeminiTTSProvider)

        # Explicit fake
        p_fake = create_tts_provider("fake")
        self.assertIsInstance(p_fake, FakeTTSProvider)

    def test_http_provider_initialization_and_capabilities(self):
        provider = ChatterboxHttpProvider(base_url="http://127.0.0.1:8000", default_model="auto")
        self.assertEqual(provider.base_url, "http://127.0.0.1:8000")
        caps = provider.capabilities()
        self.assertFalse(caps.supports_emotion)
        self.assertFalse(caps.supports_pace)
        self.assertTrue(caps.supports_pronunciation)
        self.assertFalse(caps.supports_director_notes)

        with self.assertRaisesRegex(ValueError, "Unknown TTS provider"):
            create_tts_provider("typo-provider")

    def test_http_4xx_submit_error_is_not_retryable(self):
        provider = ChatterboxHttpProvider(base_url="http://127.0.0.1:8000")
        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Invalid request")
        error = urllib.error.HTTPError(
            url="http://127.0.0.1:8000/api/v1/tts",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=io.BytesIO(b'{"detail":"invalid"}'),
        )

        with mock.patch("urllib.request.urlopen", side_effect=error):
            result = provider.render(req, self.temp_dir)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.BAD_REQUEST)
        self.assertFalse(result.retryable)

    def test_http_healthcheck(self):
        provider = ChatterboxHttpProvider(base_url="http://127.0.0.1:8000")

        # Mock healthy response
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp

        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            health = provider.healthcheck()
            self.assertTrue(health.available)
            self.assertTrue(health.connectivity_checked)

        # Mock connection error
        with mock.patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            health = provider.healthcheck()
            self.assertFalse(health.available)
            self.assertIn("Cannot connect", health.message)

    def test_http_auto_model_endpoint_selection(self):
        provider = ChatterboxHttpProvider(
            base_url="http://127.0.0.1:8000",
            default_model="auto",
            poll_interval_seconds=0.01,
            timeout_seconds=5.0,
        )

        req = TTSRenderRequest(
            project_id="auto_proj",
            beat_id="B01",
            attempt_id=1,
            text="Testing auto hardware selection on server.",
        )

        submit_resp = mock.MagicMock()
        submit_resp.status = 202
        submit_resp.read.return_value = json.dumps({"id": "job_auto_1", "status": "queued"}).encode("utf-8")
        submit_resp.__enter__.return_value = submit_resp

        poll_done = mock.MagicMock()
        poll_done.status = 200
        poll_done.read.return_value = json.dumps({"status": "completed", "progress_percent": 100.0}).encode("utf-8")
        poll_done.__enter__.return_value = poll_done

        audio_resp = mock.MagicMock()
        audio_resp.status = 200
        audio_resp.read.return_value = self.valid_wav_bytes
        audio_resp.__enter__.return_value = audio_resp

        with mock.patch("urllib.request.urlopen", side_effect=[submit_resp, poll_done, audio_resp]) as mock_open:
            result = provider.render(req, self.temp_dir)
            submit_call = mock_open.call_args_list[0]
            req_obj = submit_call[0][0]
            # Route to /api/v1/tts without hardcoding /nano
            self.assertEqual(req_obj.full_url, "http://127.0.0.1:8000/api/v1/tts")

        self.assertTrue(result.success)

    def test_http_multilingual_language_id_and_normalization(self):
        provider = ChatterboxHttpProvider(
            base_url="http://127.0.0.1:8000",
            default_model="multilingual",
            poll_interval_seconds=0.01,
            timeout_seconds=5.0,
        )

        self.assertEqual(normalize_language_id("en-US"), "en")
        self.assertEqual(normalize_language_id("vi_VN"), "vi")
        self.assertEqual(normalize_language_id("zh-CN"), "zh")

        req = TTSRenderRequest(
            project_id="mtl_proj",
            beat_id="B01",
            attempt_id=1,
            text="Multilingual speech test",
            language="en-US",
        )

        submit_resp = mock.MagicMock()
        submit_resp.status = 202
        submit_resp.read.return_value = json.dumps({"id": "job_mtl_1", "status": "queued"}).encode("utf-8")
        submit_resp.__enter__.return_value = submit_resp

        poll_done = mock.MagicMock()
        poll_done.status = 200
        poll_done.read.return_value = json.dumps({"status": "completed", "progress_percent": 100.0}).encode("utf-8")
        poll_done.__enter__.return_value = poll_done

        audio_resp = mock.MagicMock()
        audio_resp.status = 200
        audio_resp.read.return_value = self.valid_wav_bytes
        audio_resp.__enter__.return_value = audio_resp

        with mock.patch("urllib.request.urlopen", side_effect=[submit_resp, poll_done, audio_resp]) as mock_open:
            result = provider.render(req, self.temp_dir)
            submit_call = mock_open.call_args_list[0]
            req_obj = submit_call[0][0]
            self.assertEqual(req_obj.full_url, "http://127.0.0.1:8000/api/v1/tts/multilingual")
            body_str = urllib.parse.unquote(req_obj.data.decode("utf-8"))
            self.assertIn("language_id=en", body_str)

        self.assertTrue(result.success)

    def test_http_pronunciation_dictionary_application(self):
        provider = ChatterboxHttpProvider(
            base_url="http://127.0.0.1:8000",
            default_model="nano",
            poll_interval_seconds=0.01,
            timeout_seconds=5.0,
        )

        req = TTSRenderRequest(
            project_id="pron_proj",
            beat_id="B01",
            attempt_id=1,
            text="The dragon Zhulong appeared.",
            pronunciation={"Zhulong": "Joo-long"},
        )

        submit_resp = mock.MagicMock()
        submit_resp.status = 202
        submit_resp.read.return_value = json.dumps({"id": "job_pron_1", "status": "queued"}).encode("utf-8")
        submit_resp.__enter__.return_value = submit_resp

        poll_done = mock.MagicMock()
        poll_done.status = 200
        poll_done.read.return_value = json.dumps({"status": "completed", "progress_percent": 100.0}).encode("utf-8")
        poll_done.__enter__.return_value = poll_done

        audio_resp = mock.MagicMock()
        audio_resp.status = 200
        audio_resp.read.return_value = self.valid_wav_bytes
        audio_resp.__enter__.return_value = audio_resp

        with mock.patch("urllib.request.urlopen", side_effect=[submit_resp, poll_done, audio_resp]) as mock_open:
            result = provider.render(req, self.temp_dir)
            submit_call = mock_open.call_args_list[0]
            req_obj = submit_call[0][0]
            body_str = urllib.parse.unquote_plus(req_obj.data.decode("utf-8"))
            self.assertIn("The dragon Joo-long appeared.", body_str)

        self.assertTrue(result.success)

    def test_http_timeout_cancels_orphan_job(self):
        provider = ChatterboxHttpProvider(
            base_url="http://127.0.0.1:8000",
            poll_interval_seconds=0.01,
            timeout_seconds=0.04,
        )

        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Timeout test")

        submit_resp = mock.MagicMock()
        submit_resp.status = 202
        submit_resp.read.return_value = json.dumps({"id": "job_timeout_orphan", "status": "queued"}).encode("utf-8")
        submit_resp.__enter__.return_value = submit_resp

        poll_queued = mock.MagicMock()
        poll_queued.status = 200
        poll_queued.read.return_value = json.dumps({"status": "queued", "progress_percent": 0.0}).encode("utf-8")
        poll_queued.__enter__.return_value = poll_queued

        cancel_resp = mock.MagicMock()
        cancel_resp.status = 200
        cancel_resp.__enter__.return_value = cancel_resp

        with mock.patch("urllib.request.urlopen", side_effect=[submit_resp, poll_queued, poll_queued, poll_queued, cancel_resp]) as mock_open:
            result = provider.render(req, self.temp_dir)

            # Check that a cancel POST request was sent to /api/v1/jobs/job_timeout_orphan/cancel
            cancel_calls = [
                c for c in mock_open.call_args_list
                if hasattr(c[0][0], "full_url") and "/cancel" in c[0][0].full_url
            ]
            self.assertTrue(len(cancel_calls) >= 1)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.TIMEOUT)
        self.assertTrue(result.retryable)

    def test_http_cancellation_token(self):
        provider = ChatterboxHttpProvider(
            base_url="http://127.0.0.1:8000",
            poll_interval_seconds=0.01,
            timeout_seconds=5.0,
        )

        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Cancel test")
        token = CancellationToken()
        token.cancel()

        result = provider.render(req, self.temp_dir, cancellation_token=token)
        self.assertFalse(result.success)
        self.assertIn("cancelled", result.error.lower())


if __name__ == "__main__":
    unittest.main()
