import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import torch
from fastapi.testclient import TestClient

import api_app
import character_api


class RecordingExecutor:
    def __init__(self):
        self.calls = []

    def __call__(self, job_type, params, device):
        self.calls.append({"job_type": job_type, "params": params, "device": device})
        return torch.zeros(1, 240), 24000


class CharacterApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["CHATTERBOX_IN_PROCESS"] = "1"
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp_dir.name)
        api_app.API_DATA_DIR = cls.root / "api"
        character_api.configure_storage(cls.root / "character-data")
        cls.client_context = TestClient(api_app.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.temp_dir.cleanup()

    def setUp(self):
        if api_app.job_manager:
            api_app.job_manager._job_queue.join()
            with api_app.job_manager._jobs_lock:
                api_app.job_manager._jobs.clear()
        with character_api.characters_lock:
            character_api.characters.clear()
        shutil.rmtree(character_api.CHARACTER_DATA_DIR, ignore_errors=True)
        character_api.CHARACTER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        character_api.save_characters()

    def create_character(self, **overrides):
        payload = {
            "name": "Sarah",
            "description": "Calm support voice",
            "language": "en",
            "tags": ["female", "calm", "calm"],
            "notes": "Neutral support style",
            "voice": {
                "expressiveness": 0.6,
                "pace": 0.4,
                "stability": 0.9,
                "seed": 42,
            },
        }
        payload.update(overrides)
        response = self.client.post("/api/v1/characters", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def wait_for_job(self, job_id, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.client.get(f"/api/v1/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            job = response.json()
            if job["status"] in {"completed", "failed"}:
                return job
            time.sleep(0.02)
        self.fail(f"Job {job_id} did not finish within {timeout} seconds")

    def test_character_is_json_only_and_does_not_accept_model(self):
        character = self.create_character()

        self.assertFalse(character["has_reference_audio"])
        self.assertIsNone(character["reference_audio_url"])
        self.assertNotIn("model", character)
        self.assertEqual(character["tags"], ["female", "calm"])
        self.assertTrue(character_api.CHARACTERS_FILE.exists())

        rejected = self.client.post(
            "/api/v1/characters",
            json={"name": "Invalid", "model": "turbo"},
        )
        self.assertEqual(rejected.status_code, 422)

    def test_desktop_gui_character_is_persisted_for_api_use(self):
        source_audio = self.root / "gui-reference.wav"
        source_audio.write_bytes(b"gui-reference")

        character = character_api.create_character_from_audio(
            "GUI Voice",
            source_audio,
            character_api.VoiceProfile(expressiveness=0.8, pace=0.3, stability=0.6, seed=7),
        )
        character_api.load_characters()

        response = self.client.get(f"/api/v1/characters/{character['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "GUI Voice")
        self.assertEqual(response.json()["voice"]["seed"], 7)
        managed_path, _ = character_api.resolve_character_voice(character["id"])
        self.assertNotEqual(Path(managed_path), source_audio)
        self.assertEqual(Path(managed_path).read_bytes(), b"gui-reference")

    def test_desktop_gui_character_without_reference_audio(self):
        character = character_api.create_character_from_audio(
            "GUI Voice No Ref",
            None,
            character_api.VoiceProfile(expressiveness=0.5, pace=0.5, stability=0.7, seed=0),
            language="vi",
        )
        character_api.load_characters()

        response = self.client.get(f"/api/v1/characters/{character['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], "GUI Voice No Ref")
        self.assertEqual(response.json()["language"], "vi")
        self.assertFalse(response.json()["has_reference_audio"])
        managed_path, voice = character_api.resolve_character_voice(character["id"])
        self.assertIsNone(managed_path)
        self.assertEqual(voice["expressiveness"], 0.5)

    def test_default_character_setting_and_voice_resolution(self):
        source_audio = self.root / "default-reference.wav"
        source_audio.write_bytes(b"default-reference")

        character = character_api.create_character_from_audio(
            "Default Voice",
            source_audio,
            character_api.VoiceProfile(expressiveness=0.9, pace=0.4, stability=0.8, seed=123),
        )

        res = self.client.patch(f"/api/v1/characters/{character['id']}", json={"is_default": True})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertTrue(res.json()["is_default"])

        # When character_id is None, resolve_character_voice should automatically pick the default character
        ref_path, voice = character_api.resolve_character_voice(None)
        self.assertIsNotNone(ref_path)
        self.assertEqual(Path(ref_path).read_bytes(), b"default-reference")
        self.assertEqual(voice["expressiveness"], 0.9)
        self.assertEqual(voice["seed"], 123)

    def test_character_patch_updates_only_requested_voice_fields(self):
        character = self.create_character()

        response = self.client.patch(
            f"/api/v1/characters/{character['id']}",
            json={"name": "Sarah Updated", "voice": {"pace": 0.8}},
        )

        self.assertEqual(response.status_code, 200)
        updated = response.json()
        self.assertEqual(updated["name"], "Sarah Updated")
        self.assertEqual(updated["voice"]["pace"], 0.8)
        self.assertEqual(updated["voice"]["expressiveness"], 0.6)
        self.assertEqual(updated["voice"]["stability"], 0.9)
        self.assertEqual(updated["voice"]["seed"], 42)

    def test_reference_audio_can_be_added_downloaded_and_removed(self):
        character = self.create_character()
        reference_url = f"/api/v1/characters/{character['id']}/reference-audio"

        added = self.client.patch(
            f"/api/v1/characters/{character['id']}",
            files={"reference_audio": ("voice.wav", b"reference-bytes", "audio/wav")},
        )
        self.assertEqual(added.status_code, 200, added.text)
        self.assertTrue(added.json()["has_reference_audio"])
        self.assertEqual(self.client.get(reference_url).content, b"reference-bytes")

    def test_tts_character_id_applies_reference_and_voice_profile(self):
        character = self.create_character()
        self.client.patch(
            f"/api/v1/characters/{character['id']}",
            files={"reference_audio": ("voice.wav", b"reference-bytes", "audio/wav")},
        )
        recorder = RecordingExecutor()

        with patch("services.job_manager.execute_model_inference", new=recorder):
            response = self.client.post(
                "/api/v1/tts/standard",
                data={"text": "Hello from Sarah.", "character_id": character["id"]},
            )
            self.assertEqual(response.status_code, 202, response.text)
            completed = self.wait_for_job(response.json()["id"])

        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["params"]["character_id"], character["id"])
        self.assertEqual(completed["params"]["exaggeration"], 0.6)
        self.assertEqual(completed["params"]["cfg_weight"], 0.4)
        self.assertEqual(completed["params"]["temperature"], 0.57)
        self.assertEqual(completed["params"]["seed"], 42)
        prompt_path = recorder.calls[0]["params"]["audio_prompt_path"]
        self.assertIn(character["id"], prompt_path)
        self.assertTrue(Path(prompt_path).exists())

    def test_uploaded_prompt_overrides_character_reference(self):
        character = self.create_character()
        self.client.patch(
            f"/api/v1/characters/{character['id']}",
            files={"reference_audio": ("character.wav", b"character-reference", "audio/wav")},
        )
        persistent_reference, _ = character_api.resolve_character_voice(character["id"])
        recorder = RecordingExecutor()

        with patch("services.job_manager.execute_model_inference", new=recorder):
            response = self.client.post(
                "/api/v1/tts",
                data={"text": "Use request audio.", "character_id": character["id"]},
                files={"audio_prompt": ("override.wav", b"request-reference", "audio/wav")},
            )
            completed = self.wait_for_job(response.json()["id"])

        self.assertEqual(completed["status"], "completed")
        used_prompt = recorder.calls[0]["params"]["audio_prompt_path"]
        self.assertNotEqual(used_prompt, persistent_reference)
        self.assertFalse(Path(used_prompt).exists())
        self.assertTrue(Path(persistent_reference).exists())

    def test_missing_character_is_rejected_before_job_submission(self):
        response = self.client.post(
            "/api/v1/tts",
            data={"text": "Missing character.", "character_id": "char_missing"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/api/v1/jobs").json()["count"], 0)

    def test_delete_character_removes_metadata_and_reference(self):
        character = self.create_character()
        self.client.patch(
            f"/api/v1/characters/{character['id']}",
            files={"reference_audio": ("voice.wav", b"reference-bytes", "audio/wav")},
        )
        reference_path, _ = character_api.resolve_character_voice(character["id"])

        response = self.client.delete(f"/api/v1/characters/{character['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/characters/{character['id']}").status_code, 404)
        self.assertFalse(Path(reference_path).exists())


if __name__ == "__main__":
    unittest.main()
