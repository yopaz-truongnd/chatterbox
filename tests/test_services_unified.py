"""Comprehensive unit tests for unified services, model registry, script parser, batch export, and character portability."""

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import torch

import api_app
import character_api
from chatterbox.version import __version__
from job_store import AudioJob, JobStore
from services.batch_export import (
    build_srt_subtitles,
    build_vtt_subtitles,
    create_batch_zip_package,
    export_batch_srt_file,
    export_batch_vtt_file,
    merge_wav_files,
    seconds_to_srt_time,
    seconds_to_vtt_time,
)
from services.exceptions import (
    AudioProcessingError,
    ChatterboxError,
    InferenceError,
    ModelNotFoundError,
    ValidationError,
)
from services.model_registry import (
    MODEL_NAMES,
    MODEL_REGISTRY,
    check_model_preflight,
    get_model_disk_size_bytes,
    get_model_spec,
    is_model_cached,
    list_registered_models,
    resolve_model_id,
)
from services.model_runtime import ModelRuntime
from services.script_parser import (
    parse_batch_file,
    parse_csv_script,
    parse_srt_script,
    parse_vtt_script,
    split_script_text,
)
from services.synthesis import (
    normalize_synthesis_params,
    set_synthesis_seed,
    split_text,
    synthesize_chunk_tensor,
)


class UnifiedServicesTestCase(unittest.TestCase):
    def test_version_consistency(self):
        self.assertEqual(__version__, "1.4.0")
        self.assertEqual(api_app.app.version, "1.4.0")

    def test_model_registry_resolution_and_specs(self):
        # Canonical resolution
        self.assertEqual(resolve_model_id("nano"), "nano")
        self.assertEqual(resolve_model_id("Chatterbox Nano (110M - Light/CPU)"), "nano")
        self.assertEqual(resolve_model_id("turbo"), "turbo")
        self.assertEqual(resolve_model_id("Chatterbox Turbo (350M - Fast)"), "turbo")
        self.assertEqual(resolve_model_id("standard"), "standard")
        self.assertEqual(resolve_model_id("tts"), "standard")
        self.assertEqual(resolve_model_id("Multilingual TTS"), "multilingual")
        self.assertEqual(resolve_model_id("vc"), "voice-conversion")

        # Spec capabilities
        nano_spec = get_model_spec("nano")
        self.assertIsNotNone(nano_spec)
        self.assertTrue(nano_spec.supports_paralinguistic)
        self.assertEqual(nano_spec.param_size, "110M")

        std_spec = get_model_spec("standard")
        self.assertIsNotNone(std_spec)
        self.assertTrue(std_spec.supports_exaggeration)
        self.assertTrue(std_spec.supports_cfg)

        mtl_spec = get_model_spec("multilingual")
        self.assertIsNotNone(mtl_spec)
        self.assertTrue(mtl_spec.supports_languages)

    def test_model_registry_list_and_preflight(self):
        with tempfile.TemporaryDirectory() as temp_d:
            models_dir = Path(temp_d) / "models"
            models_dir.mkdir()

            # Empty directory preflight
            preflight = check_model_preflight("nano", models_dir)
            self.assertFalse(preflight["valid"])
            self.assertFalse(preflight["cached"])

            # Create mock cached folder
            nano_dir = models_dir / "models--ResembleAI--chatterbox-nano"
            nano_dir.mkdir()
            (nano_dir / "weight.safetensors").write_bytes(b"0" * (2 * 1024 * 1024))

            preflight_after = check_model_preflight("nano", models_dir)
            self.assertTrue(preflight_after["valid"])
            self.assertTrue(preflight_after["cached"])
            self.assertGreater(preflight_after["size_bytes"], 1024 * 1024)

            models_list = list_registered_models(models_dir, active_model="nano")
            self.assertEqual(len(models_list), len(MODEL_NAMES))
            nano_item = next(m for m in models_list if m["name"] == "nano")
            self.assertTrue(nano_item["cached_on_disk"])
            self.assertTrue(nano_item["loaded_in_memory"])

    def test_synthesis_parameter_normalization(self):
        raw = {"temperature": 3.5, "exaggeration": -0.5, "top_p": 1.5}
        norm = normalize_synthesis_params("standard", raw)
        self.assertEqual(norm["temperature"], 2.0)  # Clipped
        self.assertEqual(norm["exaggeration"], 0.0)  # Clipped
        self.assertEqual(norm["top_p"], 1.0)        # Clipped
        self.assertEqual(norm["cfg_weight"], 0.5)   # Default filled from registry

    def test_synthesis_text_splitting(self):
        text = "Câu thứ nhất. Câu thứ hai! Câu thứ ba? Đoạn văn dài."
        chunks = split_text(text, max_len=25)
        self.assertGreaterEqual(len(chunks), 2)
        for c in chunks:
            self.assertLessEqual(len(c), 35)

    def test_script_parser_modes(self):
        # 1. Delimiter
        text = "Line 1 === Line 2 === Line 3"
        lines = split_script_text(text, split_mode="delimiter", custom_delimiter="===")
        self.assertEqual(lines, ["Line 1", "Line 2", "Line 3"])

        # 2. Sentence
        text = "First sentence. Second sentence! Third sentence?"
        lines = split_script_text(text, split_mode="sentence")
        self.assertEqual(lines, ["First sentence.", "Second sentence!", "Third sentence?"])

        # 3. Paragraph
        text = "Paragraph 1\n\nParagraph 2\n\nParagraph 3"
        lines = split_script_text(text, split_mode="paragraph")
        self.assertEqual(lines, ["Paragraph 1", "Paragraph 2", "Paragraph 3"])

    def test_script_parser_srt_and_vtt(self):
        srt_sample = (
            "1\n00:00:01,000 --> 00:00:03,500\nHello from SRT\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nSecond dialogue line\n"
        )
        parsed_srt = parse_srt_script(srt_sample)
        self.assertEqual(len(parsed_srt), 2)
        self.assertEqual(parsed_srt[0]["text"], "Hello from SRT")
        self.assertEqual(parsed_srt[0]["start_timestamp"], "00:00:01,000")

        vtt_sample = (
            "WEBVTT\n\n"
            "00:01.000 --> 00:03.500\nHello from VTT\n\n"
            "00:04.000 --> 00:06.000\nSecond VTT line\n"
        )
        parsed_vtt = parse_vtt_script(vtt_sample)
        self.assertEqual(len(parsed_vtt), 2)
        self.assertEqual(parsed_vtt[0]["text"], "Hello from VTT")

    def test_script_parser_csv(self):
        csv_sample = "id,speech_text,speaker\n1,Hello world,Alice\n2,Good morning,Bob"
        extracted = parse_csv_script(csv_sample)
        self.assertEqual(extracted, ["Hello world", "Good morning"])

    def test_batch_export_subtitles_and_zip(self):
        lines_res = [
            {"idx": 0, "status": "completed", "text": "First line", "duration_seconds": 2.0, "pause_duration": 0.5},
            {"idx": 1, "status": "completed", "text": "Second line", "duration_seconds": 1.5, "pause_duration": 0.5},
        ]
        srt = build_srt_subtitles(lines_res)
        self.assertIn("1\n00:00:00,000 --> 00:00:02,000\nFirst line", srt)
        self.assertIn("2\n00:00:02,500 --> 00:00:04,000\nSecond line", srt)

        vtt = build_vtt_subtitles(lines_res)
        self.assertTrue(vtt.startswith("WEBVTT\n"))
        self.assertIn("00:00:00.000 --> 00:00:02.000\nFirst line", vtt)

        with tempfile.TemporaryDirectory() as temp_d:
            d = Path(temp_d)
            zip_out = d / "export.zip"
            manifest = {"job_id": "test_123", "status": "completed"}
            created_zip = create_batch_zip_package(
                job_id="test_123",
                output_zip_path=zip_out,
                manifest_data=manifest,
            )
            self.assertTrue(created_zip.exists())
            with zipfile.ZipFile(created_zip, "r") as zf:
                self.assertIn("manifest.json", zf.namelist())
                read_manifest = json.loads(zf.read("manifest.json"))
                self.assertEqual(read_manifest["job_id"], "test_123")

    def test_character_zip_export_and_import(self):
        with tempfile.TemporaryDirectory() as temp_d:
            storage_dir = Path(temp_d)
            character_api.configure_storage(storage_dir)

            # Create character
            char = character_api.create_character_from_audio(
                name="Export Hero",
                voice=character_api.VoiceProfile(expressiveness=0.8, pace=0.6, stability=0.7, seed=42),
                language="en",
            )
            cid = char["id"]

            # Export character ZIP
            export_dir = storage_dir / cid / "export"
            export_dir.mkdir(parents=True, exist_ok=True)
            zip_path = export_dir / f"character_{cid}.zip"

            meta = dict(char)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("character.json", json.dumps(meta, indent=2))

            self.assertTrue(zip_path.exists())

            # Read back zip content to simulate import
            with zipfile.ZipFile(zip_path, "r") as zf:
                self.assertIn("character.json", zf.namelist())
                imported_meta = json.loads(zf.read("character.json"))
                self.assertEqual(imported_meta["name"], "Export Hero")
                self.assertEqual(imported_meta["voice"]["expressiveness"], 0.8)

    def test_benchmark_store_recording_and_listing(self):
        with tempfile.TemporaryDirectory() as temp_d:
            store = JobStore(Path(temp_d) / "jobs.db")
            store.record_benchmark(
                job_id="job_001",
                model="nano",
                device="cpu",
                total_seconds=1.2,
                audio_duration_seconds=5.0,
                realtime_factor=0.24,
                faster_than_realtime=4.16,
            )
            store.record_benchmark(
                job_id="job_002",
                model="turbo",
                device="mps",
                total_seconds=0.8,
                audio_duration_seconds=4.0,
                realtime_factor=0.20,
                faster_than_realtime=5.0,
            )

            bms = store.list_benchmarks(limit=10)
            self.assertEqual(len(bms), 2)
            self.assertEqual(bms[0]["job_id"], "job_002")  # Ordered by created_at DESC
            self.assertEqual(bms[1]["job_id"], "job_001")

            nano_only = store.list_benchmarks(model="nano")
            self.assertEqual(len(nano_only), 1)
            self.assertEqual(nano_only[0]["model"], "nano")

    def test_model_runtime_cache_key_generation(self):
        self.assertEqual(ModelRuntime.build_cache_key("nano", "cpu"), "nano@cpu")
        self.assertEqual(ModelRuntime.build_cache_key("turbo", "mps"), "turbo@mps")
        self.assertEqual(ModelRuntime.build_cache_key("multilingual", "cpu", variant="v2"), "multilingual:v2@cpu")
        self.assertEqual(ModelRuntime.build_cache_key("multilingual", "cuda", variant="v3"), "multilingual:v3@cuda")

    def test_model_runtime_device_switching_and_variant_isolation(self):
        runtime = ModelRuntime(default_device="cpu")

        # Mock classes for different devices and variants
        class MockModel:
            def __init__(self, tag):
                self.tag = tag
                self.sr = 24000
                self.conds = {"v": 1}

        with patch("services.model_runtime.select_device", side_effect=lambda d: d), \
             patch("chatterbox.tts_turbo.ChatterboxTurboTTS.from_pretrained") as mock_turbo:
            mock_turbo.side_effect = lambda dev, nano=False: MockModel(f"nano_{dev}")

            # 1. Load on CPU
            inst_cpu, _ = runtime.load_model("nano", device="cpu")
            self.assertEqual(runtime.active_cache_key, "nano@cpu")
            self.assertEqual(inst_cpu.tag, "nano_cpu")

            # 2. Request on MPS -> Must NOT return CPU instance!
            inst_mps, _ = runtime.load_model("nano", device="mps")
            self.assertEqual(runtime.active_cache_key, "nano@mps")
            self.assertEqual(inst_mps.tag, "nano_mps")
            self.assertIsNot(inst_cpu, inst_mps)

            # 3. Request CPU again -> Must hit cache and return original CPU instance
            inst_cpu_again, _ = runtime.load_model("nano", device="cpu")
            self.assertEqual(runtime.active_cache_key, "nano@cpu")
            self.assertIs(inst_cpu, inst_cpu_again)

        with patch("chatterbox.mtl_tts.ChatterboxMultilingualTTS.from_pretrained") as mock_mtl:
            mock_mtl.side_effect = lambda dev, t3_model="v3": MockModel(f"mtl_{t3_model}_{dev}")

            # 4. Load Multilingual V2 on CPU
            inst_v2, _ = runtime.load_model("multilingual", device="cpu", extra_args={"ver": "v2"})
            self.assertEqual(runtime.active_cache_key, "multilingual:v2@cpu")
            self.assertEqual(inst_v2.tag, "mtl_v2_cpu")

            # 5. Load Multilingual V3 on CPU -> Must NOT return V2 instance!
            inst_v3, _ = runtime.load_model("multilingual", device="cpu", extra_args={"ver": "v3"})
            self.assertEqual(runtime.active_cache_key, "multilingual:v3@cpu")
            self.assertEqual(inst_v3.tag, "mtl_v3_cpu")
            self.assertIsNot(inst_v2, inst_v3)

            # 6. Unload multilingual cleans both variants
            runtime.unload_model("multilingual")
            self.assertIsNone(runtime.active_cache_key)
            self.assertNotIn("multilingual:v2@cpu", runtime._loaded_models)
            self.assertNotIn("multilingual:v3@cpu", runtime._loaded_models)


if __name__ == "__main__":
    unittest.main()
