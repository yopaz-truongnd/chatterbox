"""Unit tests for Production Events store (Phase 20)."""

from pathlib import Path
import tempfile
import unittest

from services.production_event_models import ProductionEvent, ProductionEventType
from services.production_event_store import ProductionEventStore


class TestProductionEvents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = ProductionEventStore(root_dir=Path(self.tmp.name) / "projects")

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_and_load_project_events(self):
        evt1 = ProductionEvent(
            project_id="proj_evt_01",
            event_type=ProductionEventType.WORKFLOW_STARTED,
            message="Workflow initiated",
        )
        evt2 = ProductionEvent(
            project_id="proj_evt_01",
            event_type=ProductionEventType.STEP_COMPLETED,
            step="render",
            message="Render finished",
        )

        self.store.append_project_event(evt1)
        self.store.append_project_event(evt2)

        loaded = self.store.load_project_events("proj_evt_01")
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["event_type"], "workflow_started")
        self.assertEqual(loaded[1]["step"], "render")

    def test_corruption_tolerant_loading_skips_bad_lines(self):
        pid = "proj_corrupt"
        events_file = self.store.root_dir / pid / "events.jsonl"
        events_file.parent.mkdir(parents=True, exist_ok=True)

        with open(events_file, "w", encoding="utf-8") as fh:
            fh.write('{"event_id": "evt_1", "event_type": "workflow_started", "message": "ok"}\n')
            fh.write('THIS IS NOT VALID JSON\n')
            fh.write('{"event_id": "evt_2", "event_type": "step_completed", "message": "ok2"}\n')

        loaded = self.store.load_project_events(pid)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["event_id"], "evt_1")
        self.assertEqual(loaded[1]["event_id"], "evt_2")

    def test_event_limit(self):
        pid = "proj_limit"
        for i in range(10):
            self.store.append_project_event(
                ProductionEvent(
                    project_id=pid,
                    event_type=ProductionEventType.STEP_PROGRESS,
                    progress_percent=float(i * 10),
                    message=f"Progress {i}",
                )
            )

        recent_3 = self.store.load_project_events(pid, limit=3)
        self.assertEqual(len(recent_3), 3)
        self.assertEqual(recent_3[-1]["progress_percent"], 90.0)
