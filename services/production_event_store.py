"""Production Event Store (Phase 20).

Append-only JSONL event log per project/series with:
- Atomic appends via fcntl.flock file locking
- Bounded retention (rotate when > 1000 events, keep latest 1000)
- Corruption-tolerant loading (skip malformed lines)
- All timestamps UTC
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Any

from services.production_event_models import ProductionEvent

logger = logging.getLogger(__name__)

_MAX_EVENTS = 1000
_ROTATE_THRESHOLD = 1000


def _default_root() -> Path:
    data_dir = os.getenv("CHATTERBOX_API_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "projects"
    return Path("projects")


def _project_events_path(root: Path, project_id: str) -> Path:
    return root / project_id / "events.jsonl"


def _series_events_path(root: Path, series_id: str) -> Path:
    return root / "series" / series_id / "events.jsonl"


# ==========================================
# Low-level I/O helpers
# ==========================================


def _load_events_from_file(path: Path) -> list[dict[str, Any]]:
    """Load events from JSONL, skipping any malformed lines (corruption-tolerant)."""
    events: list[dict[str, Any]] = []
    if not path.exists():
        return events
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed event line in %s", path)
    except OSError as exc:
        logger.warning("Could not read events file %s: %s", path, exc)
    return events


def _atomic_append(path: Path, record: dict[str, Any]) -> None:
    """Atomically append one JSON record to the JSONL file using flock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _rotate_if_needed(path: Path) -> None:
    """Rotate the JSONL file when it exceeds _ROTATE_THRESHOLD, keeping latest _MAX_EVENTS."""
    if not path.exists():
        return
    events = _load_events_from_file(path)
    if len(events) <= _ROTATE_THRESHOLD:
        return
    kept = events[-_MAX_EVENTS:]
    tmp_path = path.with_suffix(f".tmp_rotate")
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                for evt in kept:
                    fh.write(json.dumps(evt, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        tmp_path.replace(path)
        logger.info("Rotated event log %s: kept %d / %d events", path, len(kept), len(events))
    except OSError as exc:
        logger.warning("Failed to rotate event log %s: %s", path, exc)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


# ==========================================
# Public API
# ==========================================


class ProductionEventStore:
    """Append-only JSONL event store for project and series events."""

    def __init__(self, root_dir: Path | str | None = None):
        self.root_dir = Path(root_dir) if root_dir else _default_root()

    # ---- Project events ----

    def append_project_event(self, event: ProductionEvent) -> None:
        """Append a production event for a specific project."""
        if not event.project_id:
            raise ValueError("ProductionEvent must have project_id set for project append.")
        path = _project_events_path(self.root_dir, event.project_id)
        _atomic_append(path, event.to_dict())
        _rotate_if_needed(path)

    def load_project_events(
        self,
        project_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Load events for a project, optionally capped at `limit` most recent."""
        path = _project_events_path(self.root_dir, project_id)
        events = _load_events_from_file(path)
        if limit is not None:
            events = events[-limit:]
        return events

    # ---- Series events ----

    def append_series_event(self, event: ProductionEvent) -> None:
        """Append a production event for a series."""
        if not event.series_id:
            raise ValueError("ProductionEvent must have series_id set for series append.")
        path = _series_events_path(self.root_dir, event.series_id)
        _atomic_append(path, event.to_dict())
        _rotate_if_needed(path)

    def load_series_events(
        self,
        series_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Load events for a series, optionally capped at `limit` most recent."""
        path = _series_events_path(self.root_dir, series_id)
        events = _load_events_from_file(path)
        if limit is not None:
            events = events[-limit:]
        return events


# Module-level singleton
_GLOBAL_EVENT_STORE: ProductionEventStore | None = None


def get_production_event_store(root_dir: Path | str | None = None) -> ProductionEventStore:
    """Return the process-wide ProductionEventStore singleton."""
    global _GLOBAL_EVENT_STORE
    if _GLOBAL_EVENT_STORE is None:
        _GLOBAL_EVENT_STORE = ProductionEventStore(root_dir)
    return _GLOBAL_EVENT_STORE
