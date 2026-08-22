"""Lightweight In-Memory Event Log & Long-Polling Event Bus.

Zero-dependency, thread-safe, 0 CPU idle wait using threading.Condition and collections.deque.
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any

logger = logging.getLogger("chatterbox.event_bus")


class LocalEventBus:
    """In-memory ring buffer event bus with condition-based long polling."""

    def __init__(self, maxlen: int = 500) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._events: collections.deque[dict[str, Any]] = collections.deque(maxlen=maxlen)
        self._next_id = 1

    def emit(
        self,
        event_type: str,
        project_id: str | None = None,
        job_id: str | None = None,
        status: str | None = None,
        progress: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Emit an event thread-safely and notify all waiting long-poll listeners."""
        with self._condition:
            event = {
                "id": self._next_id,
                "type": event_type,
                "project_id": project_id,
                "job_id": job_id,
                "status": status,
                "progress": progress,
                "timestamp": int(time.time()),
                "data": data or {},
            }
            self._next_id += 1
            self._events.append(event)
            self._condition.notify_all()
            return event

    def get_events(
        self,
        after_id: int = 0,
        project_id: str | None = None,
        wait_seconds: float = 0.0,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieve events strictly newer than after_id with optional condition-wait long polling."""
        wait_seconds = max(0.0, min(float(wait_seconds or 0.0), 30.0))
        deadline = time.time() + wait_seconds

        with self._condition:
            # 1. Check if any events already match
            matched = self._filter_events(after_id=after_id, project_id=project_id, limit=limit)
            if matched or wait_seconds <= 0.0:
                return matched

            # 2. Condition wait without CPU spin loop
            while not matched:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)
                matched = self._filter_events(after_id=after_id, project_id=project_id, limit=limit)

            return matched

    def _filter_events(
        self,
        after_id: int,
        project_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Filter current deque for events with id > after_id."""
        res = []
        for ev in self._events:
            if ev["id"] > after_id:
                if project_id is None or ev.get("project_id") == project_id:
                    res.append(ev)
                    if len(res) >= limit:
                        break
        return res

    def clear(self) -> None:
        """Clear all events (used for test teardown)."""
        with self._condition:
            self._events.clear()
            self._next_id = 1


# Singleton Event Bus instance
event_bus = LocalEventBus(maxlen=500)
