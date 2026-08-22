"""Real-Time Event Stream & Long-Polling Router.

Provides zero-dependency, condition-based long polling over in-memory ring buffer events.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from services.event_bus import event_bus

router = APIRouter(tags=["events"])


@router.get("/api/v1/events")
def get_global_events(
    after_id: Annotated[int, Query(description="Retrieve events with ID strictly greater than after_id")] = 0,
    wait: Annotated[float, Query(description="Wait timeout in seconds (0 for immediate return, max 30s)")] = 0.0,
    wait_seconds: Annotated[float | None, Query(description="Alias for wait")] = None,
    project_id: Annotated[str | None, Query(description="Optional filter by project ID")] = None,
    limit: Annotated[int, Query(description="Max events to return (max 100)")] = 50,
) -> dict[str, Any]:
    """Retrieve event log with zero-CPU condition-based long polling."""
    timeout = wait_seconds if wait_seconds is not None else wait
    events = event_bus.get_events(
        after_id=after_id,
        project_id=project_id,
        wait_seconds=timeout,
        limit=min(limit, 100),
    )
    last_id = max([ev["id"] for ev in events], default=after_id)
    return {
        "events": events,
        "count": len(events),
        "last_event_id": last_id,
    }


@router.get("/api/v1/projects/{project_id}/events")
def get_project_events(
    project_id: str,
    after_id: Annotated[int, Query(description="Retrieve events with ID strictly greater than after_id")] = 0,
    wait: Annotated[float, Query(description="Wait timeout in seconds (0 for immediate return, max 30s)")] = 0.0,
    wait_seconds: Annotated[float | None, Query(description="Alias for wait")] = None,
    limit: Annotated[int, Query(description="Max events to return (max 100)")] = 50,
) -> dict[str, Any]:
    """Retrieve event log filtered for a specific project with long polling."""
    timeout = wait_seconds if wait_seconds is not None else wait
    events = event_bus.get_events(
        after_id=after_id,
        project_id=project_id,
        wait_seconds=timeout,
        limit=min(limit, 100),
    )
    last_id = max([ev["id"] for ev in events], default=after_id)
    return {
        "project_id": project_id,
        "events": events,
        "count": len(events),
        "last_event_id": last_id,
    }
