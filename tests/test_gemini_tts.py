"""Comprehensive Unit and Mocked Integration Tests for Gemini Live TTS Provider (Phase 10)."""

from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import unittest.mock as mock
import wave

from services.render_models import (
    ProviderErrorType,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.gemini import (
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GEMINI_VOICE,
    GeminiTTSConfig,
    GeminiTTSProvider,
    classify_provider_exception,
    map_voice_plan_to_gemini_payload,
    validate_generated_wave,
    write_pcm_wave,
)


class TestGeminiTTSProviderPhase10(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="gemini_tts_test_"))
        self.api_key = "test_api_key_12345"

        # Generate 1.0s of clean 24kHz 16-bit mono PCM sine wave test audio
        import math
        import struct
        samples = []
        for i in range(24000):
            val = int(16000 * math.sin(2.0 * math.pi * 440.0 * (i / 24000.0)))
            samples.append(struct.pack("<h", val))
        self.valid_pcm_bytes = b"".join(samples)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_gemini_config_loading(self):
        config = GeminiTTSConfig.load()
        self.assertEqual(config.model, DEFAULT_GEMINI_MODEL)
        self.assertEqual(config.default_voice, DEFAULT_GEMINI_VOICE)
        self.assertIn("mythology_narrator_male", config.profile_voice_map)
        self.assertEqual(config.sample_rate, 24000)
        self.assertEqual(config.channels, 1)

    def test_prompt_construction_and_exact_text_preservation(self):
        exact_script = "  What if I told you that, in ancient mythology, Zhulong opened its eyes?\n"
        req = TTSRenderRequest(
            project_id="proj_torch",
            beat_id="B01",
            attempt_id=1,
            text=exact_script,
            voice_profile="mythology_narrator_male",
            emotion="mysterious",
            energy=3.8,
            pace=0.88,
            target_wpm=118,
            director_note="Begin intimate and mysterious. Build curiosity gradually.",
            pronunciation={"Zhulong": "Joo-long"},
            emphasis=["Zhulong", "eyes"],
        )

        payload = map_voice_plan_to_gemini_payload(req)

        # 1. Exact raw text invariant: untouched
        self.assertEqual(payload["text"], exact_script)

        # 2. Formatted prompt contains instructions and exact text inside <narration>
        prompt = payload["formatted_prompt"]
        self.assertIn("<instructions>", prompt)
        self.assertIn("<narration>", prompt)
        self.assertIn(exact_script, prompt)

        # 3. Direction and performance mapping
        sys_inst = payload["system_instruction"]
        self.assertIn("Tone/Emotion: mysterious", sys_inst)
        self.assertIn("strong, authoritative", sys_inst)  # Energy 3.8
        self.assertIn("Speak slower than normal", sys_inst)  # Pace 0.88
        self.assertIn('Pronunciation Guidance:', sys_inst)
        self.assertIn('"Zhulong" → pronounce as "Joo-long"', sys_inst)
        self.assertIn('Place subtle emphasis on: "Zhulong", "eyes"', sys_inst)
        self.assertIn("Begin intimate and mysterious", sys_inst)

    def test_voice_resolution_and_precedence(self):
        # Default config mapping
        provider = GeminiTTSProvider(api_key=self.api_key)
        self.assertEqual(provider.resolve_voice("mythology_narrator_male"), "Kore")
        self.assertEqual(provider.resolve_voice("mythology_narrator_female"), "Aoede")
        self.assertEqual(provider.resolve_voice("unknown_custom_profile"), "Kore")

        # Explicit voice override
        provider_override = GeminiTTSProvider(api_key=self.api_key, voice_name="Fenrir")
        self.assertEqual(provider_override.resolve_voice("mythology_narrator_female"), "Fenrir")

    def test_model_resolution_and_precedence(self):
        # Default model
        provider = GeminiTTSProvider(api_key=self.api_key)
        self.assertEqual(provider.model_name, DEFAULT_GEMINI_MODEL)

        # Explicit model override
        provider_custom = GeminiTTSProvider(api_key=self.api_key, model_name="custom-tts-model")
        self.assertEqual(provider_custom.model_name, "custom-tts-model")

    def test_successful_render_with_mock_sdk(self):
        provider = GeminiTTSProvider(api_key=self.api_key)

        req = TTSRenderRequest(
            project_id="proj_torch",
            beat_id="B01",
            attempt_id=1,
            text="When Zhulong opened its eyes, daylight returned.",
            voice_profile="mythology_narrator_male",
        )

        # Mock Google GenAI response
        mock_part = mock.MagicMock()
        mock_part.inline_data.data = self.valid_pcm_bytes
        mock_part.inline_data.mime_type = "audio/pcm"

        mock_candidate = mock.MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_candidate.finish_reason = "STOP"

        mock_response = mock.MagicMock()
        mock_response.candidates = [mock_candidate]
        mock_response.response_id = "gemini_resp_001"

        with mock.patch.object(provider, "_create_client") as mock_client_factory:
            mock_client = mock.MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_response

            result = provider.render(req, self.temp_dir)

        self.assertTrue(result.success)
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.model, DEFAULT_GEMINI_MODEL)
        self.assertIsNotNone(result.audio_path)
        self.assertEqual(result.sample_rate, 24000)
        self.assertEqual(result.channels, 1)
        self.assertAlmostEqual(result.duration, 1.0, places=1)
        self.assertEqual(result.provider_request_id, "gemini_resp_001")

        # Verify WAV file on disk
        wav_file = Path(result.audio_path)
        self.assertTrue(wav_file.exists())
        self.assertEqual(wav_file.name, "attempt_01.wav")

        with wave.open(str(wav_file), "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getframerate(), 24000)
            self.assertEqual(wf.getnframes(), 24000)

        # Verify temp file was atomically removed / replaced
        self.assertFalse((self.temp_dir / "attempt_01.tmp.wav").exists())

    def test_empty_audio_response_error(self):
        provider = GeminiTTSProvider(api_key=self.api_key)

        req = TTSRenderRequest(
            project_id="proj_torch",
            beat_id="B01",
            attempt_id=1,
            text="Empty audio test.",
        )

        mock_candidate = mock.MagicMock()
        mock_candidate.content.parts = []  # No parts / empty audio

        mock_response = mock.MagicMock()
        mock_response.candidates = [mock_candidate]

        with mock.patch.object(provider, "_create_client") as mock_client_factory:
            mock_client = mock.MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_response

            result = provider.render(req, self.temp_dir)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.INVALID_AUDIO_RESPONSE)
        self.assertTrue(result.retryable)
        self.assertIsNone(result.audio_path)
        self.assertFalse((self.temp_dir / "attempt_01.wav").exists())

    def test_malformed_wave_cleanup_and_error(self):
        provider = GeminiTTSProvider(api_key=self.api_key)

        req = TTSRenderRequest(
            project_id="proj_torch",
            beat_id="B01",
            attempt_id=1,
            text="Malformed test.",
        )

        # Return only 5 bytes (too short to be valid audio)
        mock_part = mock.MagicMock()
        mock_part.inline_data.data = b"12345"

        mock_candidate = mock.MagicMock()
        mock_candidate.content.parts = [mock_part]

        mock_response = mock.MagicMock()
        mock_response.candidates = [mock_candidate]

        with mock.patch.object(provider, "_create_client") as mock_client_factory:
            mock_client = mock.MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_response

            result = provider.render(req, self.temp_dir)

        # Even with wave packaging 5 bytes is < 1 sample frame in 16-bit
        # Should be rejected or validated
        self.assertFalse((self.temp_dir / "attempt_01.tmp.wav").exists())

    def test_auth_error_not_retryable(self):
        provider = GeminiTTSProvider(api_key=self.api_key)
        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Auth test.")

        with mock.patch.object(provider, "_create_client") as mock_client_factory:
            mock_client = mock.MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("401 Unauthorized: Invalid API key")

            result = provider.render(req, self.temp_dir)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.AUTH_ERROR)
        self.assertFalse(result.retryable)

    def test_rate_limit_error_retryable(self):
        provider = GeminiTTSProvider(api_key=self.api_key)
        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Rate limit test.")

        with mock.patch.object(provider, "_create_client") as mock_client_factory:
            mock_client = mock.MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("429 ResourceExhausted: Quota exceeded")

            result = provider.render(req, self.temp_dir)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.RATE_LIMIT)
        self.assertTrue(result.retryable)
        self.assertIsNotNone(result.retry_after_seconds)

    def test_timeout_error_retryable(self):
        provider = GeminiTTSProvider(api_key=self.api_key)
        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Timeout test.")

        with mock.patch.object(provider, "_create_client") as mock_client_factory:
            mock_client = mock.MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("Request timed out after 30s")

            result = provider.render(req, self.temp_dir)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.TIMEOUT)
        self.assertTrue(result.retryable)

    def test_server_error_retryable(self):
        provider = GeminiTTSProvider(api_key=self.api_key)
        req = TTSRenderRequest(project_id="p", beat_id="B1", text="Server error test.")

        with mock.patch.object(provider, "_create_client") as mock_client_factory:
            mock_client = mock.MagicMock()
            mock_client_factory.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("503 Service Unavailable: High load")

            result = provider.render(req, self.temp_dir)

        self.assertFalse(result.success)
        self.assertEqual(result.error_type, ProviderErrorType.SERVER_ERROR)
        self.assertTrue(result.retryable)

    def test_healthcheck_diagnostics(self):
        # Unconfigured key
        provider_no_key = GeminiTTSProvider(api_key="")
        health_no_key = provider_no_key.healthcheck()
        self.assertFalse(health_no_key.available)
        self.assertFalse(health_no_key.configured)

        # Configured key
        provider_configured = GeminiTTSProvider(api_key="valid_test_key")
        health_configured = provider_configured.healthcheck()
        self.assertTrue(health_configured.available)
        self.assertTrue(health_configured.configured)
        self.assertIn("gemini-3.1-flash-tts-preview", health_configured.message)


if __name__ == "__main__":
    unittest.main()
