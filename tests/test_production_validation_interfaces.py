"""Interface parity and contract tests for Phase 21 REST, MCP, and CLI."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from fastapi.testclient import TestClient

from api_app import app
from mcp_adapter.runtime_tools import (
    handle_validate_runtime,
    handle_validation_cancel,
    handle_validation_report,
    handle_validation_status,
)
from services.voice_cli import main as cli_main


class TestProductionValidationInterfaces(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_rest_validation_lifecycle(self):
        # 1. Start synchronous validation with fake provider
        payload = {
            "script_text": "Prometheus brought the sacred flame to mortal hands.",
            "provider": "fake",
            "model": "nano",
            "output_formats": ["wav"],
            "run_incremental_reproduction": False,
        }
        res = self.client.post("/api/v1/voice-runtime/validations", json=payload)
        self.assertEqual(res.status_code, 202)
        data = res.json()
        val_id = data.get("validation_id")
        self.assertIsNotNone(val_id)
        self.assertIsNotNone(data.get("operation_id"))

        # 2. Get status
        deadline = time.monotonic() + 10
        while True:
            res_stat = self.client.get(f"/api/v1/voice-runtime/validations/{val_id}")
            if res_stat.json().get("status") in {"completed", "failed", "cancelled"}:
                break
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.03)
        self.assertEqual(res_stat.status_code, 200)
        self.assertEqual(res_stat.json().get("validation_id"), val_id)
        self.assertEqual(res_stat.json().get("status"), "completed")

        # 3. Get full report
        res_rep = self.client.get(f"/api/v1/voice-runtime/validations/{val_id}/report")
        self.assertEqual(res_rep.status_code, 200)
        self.assertEqual(res_rep.json().get("validation_id"), val_id)

        # 4. Cancel endpoint
        res_canc = self.client.post(f"/api/v1/voice-runtime/validations/{val_id}/cancel")
        self.assertEqual(res_canc.status_code, 200)

    def test_mcp_validation_tools(self):
        args = {
            "script_text": "The gods feasted atop Olympus while the earth trembled.",
            "provider": "fake",
            "model": "nano",
            "output_formats": ["wav"],
            "run_incremental_reproduction": False,
        }
        # 1. Start validation
        val_res = handle_validate_runtime(args)
        self.assertFalse(val_res.get("isError", True))
        data = json.loads(val_res["content"][0]["text"])
        val_id = data.get("validation_id")
        self.assertIsNotNone(val_id)

        # 2. Status
        stat_res = handle_validation_status({"validation_id": val_id})
        self.assertFalse(stat_res.get("isError", True))

        # 3. Report
        rep_res = handle_validation_report({"validation_id": val_id})
        self.assertFalse(rep_res.get("isError", True))

        # 4. Cancel
        canc_res = handle_validation_cancel({"validation_id": val_id})
        self.assertFalse(canc_res.get("isError", True))

    def test_cli_production_validate(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("A single spark lit the darkest night on earth.")
            f.flush()
            script_path = f.name

        try:
            exit_code = cli_main([
                "production", "validate",
                "--script", script_path,
                "--provider", "fake",
                "--json",
            ])
            self.assertEqual(exit_code, 0)
        finally:
            Path(script_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
