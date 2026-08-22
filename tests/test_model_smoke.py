"""Real model checkpoint inference smoke test (runs only when checkpoint is present and CHATTERBOX_RUN_SMOKE=1 or pytest -m model_smoke)."""

import os
import tempfile
import unittest
from pathlib import Path

import torch
import torchaudio as ta

from config.constants import PROJECT_ROOT
from services.model_registry import is_model_cached
from services.model_runtime import ModelRuntime
from services.synthesis import synthesize_chunk_tensor

# Pytest marker support
try:
    import pytest
    model_smoke_mark = pytest.mark.model_smoke
except ImportError:
    def model_smoke_mark(func):
        return func


class RealModelSmokeTestCase(unittest.TestCase):
    """End-to-end smoke test on real model weights to verify tensor shapes and audio validity."""

    @classmethod
    def setUpClass(cls):
        cls.models_dir = PROJECT_ROOT / "models"
        cls.has_nano = is_model_cached("nano", cls.models_dir)

    @model_smoke_mark
    def test_nano_real_inference_smoke(self):
        """Smoke test: Load real Chatterbox Nano, synthesize a short sentence, verify WAV properties."""
        if not os.environ.get("CHATTERBOX_RUN_SMOKE") and not os.environ.get("RUN_MODEL_SMOKE"):
            self.skipTest(
                "Bỏ qua smoke test model thật trong test suite mặc định để tối ưu tốc độ CI. "
                "Chạy riêng bằng lệnh 'CHATTERBOX_RUN_SMOKE=1 ./run_chatterbox_api.sh --test' hoặc 'pytest -m model_smoke'."
            )

        if not self.has_nano:
            self.skipTest("Bỏ qua: Checkpoint 'nano' chưa được tải về trong thư mục models/.")

        runtime = ModelRuntime(default_device="cpu")
        try:
            model, sr = runtime.load_model("nano", device="cpu", keep_in_cache=False)
            self.assertIsNotNone(model)
            self.assertEqual(sr, 24000)

            # Generate short phrase
            text = "Hello world, Chatterbox audio smoke test."
            params = {"temperature": 0.6, "seed": 42}
            wav = synthesize_chunk_tensor(model, "nano", text, params, device="cpu")

            self.assertIsInstance(wav, torch.Tensor)
            self.assertEqual(wav.dim(), 2)  # (1, num_samples)
            self.assertEqual(wav.shape[0], 1)
            num_samples = wav.shape[-1]

            duration_s = num_samples / sr
            # Verification: Duration is non-trivial (>0.2s) and not silent
            self.assertGreater(duration_s, 0.2, f"Audio duration quá ngắn: {duration_s}s")
            self.assertFalse(torch.isnan(wav).any(), "Audio chứa giá trị NaN")

            # Verify WAV file saving and re-reading
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp_f:
                ta.save(tmp_f.name, wav, sr)
                self.assertGreater(os.path.getsize(tmp_f.name), 44)
                loaded_wav, loaded_sr = ta.load(tmp_f.name)
                self.assertEqual(loaded_sr, 24000)
                self.assertEqual(loaded_wav.shape, wav.shape)

        finally:
            runtime.unload_all()


if __name__ == "__main__":
    unittest.main()
