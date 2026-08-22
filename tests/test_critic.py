"""
Unit tests for the AI Voice Critic router and statistics analysis.
"""

from __future__ import annotations

import unittest
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import torch
from fastapi.testclient import TestClient

import api_app
from job_store import AudioJob
from routers.critic import analyze_audio_signals, generate_feedback


class CriticTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"
        cls.temp_dir = tempfile.TemporaryDirectory()
        api_app.API_DATA_DIR = Path(cls.temp_dir.name)
        cls.client_context = TestClient(api_app.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def test_audio_analysis_signals(self):
        """Verify signal calculations (loudness, pitch variation, duration) on dummy wave."""
        import numpy as np
        import soundfile as sf
        
        # Create a simple pitch-changing sine wave file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_wav = Path(f.name)
            
        try:
            sr = 24000
            t = np.linspace(0, 1.0, sr, endpoint=False)
            y = 0.5 * np.sin(2 * np.pi * 440 * t)
            sf.write(str(temp_wav), y, sr)
            
            stats = analyze_audio_signals(temp_wav)
            self.assertIn("duration", stats)
            self.assertIn("loudness", stats)
            self.assertIn("pitch_std", stats)
            self.assertGreater(stats["duration"], 0.9)
        finally:
            temp_wav.unlink(missing_ok=True)

    def test_critic_endpoint_evaluation(self):
        """Test the full evaluation API flow including transcribing and enqueuing TTS coach feedback."""
        import numpy as np
        import soundfile as sf

        with patch("services.job_manager.execute_model_inference", return_value=(torch.zeros(1, 240), 24000)), \
             patch("routers.critic.analyze_audio_signals", return_value={"duration": 2.0, "loudness": -18.5, "pitch_mean": 220.0, "pitch_std": 35.0}), \
             patch("routers.critic.transcribe_audio_whisper", return_value="Hello world, this is a test."):
             
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                dummy_wav = Path(f.name)
            try:
                sf.write(str(dummy_wav), np.zeros(24000), 24000)
                
                with open(dummy_wav, "rb") as audio_f:
                    response = self.client.post(
                        "/api/v1/voice-critic/evaluate",
                        files={"audio_file": ("test.wav", audio_f)},
                        data={
                            "reference_text": "Hello world, this is a test.",
                            "coach_character_id": "char_coach"
                        }
                    )
                
                self.assertEqual(response.status_code, 202)
                data = response.json()
                self.assertEqual(data["status"], "completed")
                self.assertIn("markdown_report", data)
                self.assertIn("evaluation", data)
                self.assertIn("overall_score", data["evaluation"])
                self.assertIn("passed", data["evaluation"])
                self.assertIn("feedback_job_id", data)
                self.assertIn("feedback_audio_url", data)
                self.assertEqual(data["transcription"], "Hello world, this is a test.")
                self.assertIn("Độ diễn cảm", data["markdown_report"])
            finally:
                dummy_wav.unlink(missing_ok=True)
