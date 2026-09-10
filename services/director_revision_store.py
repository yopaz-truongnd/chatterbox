"""Atomic project-level revision history and explicit invalidation state."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import threading
import uuid
import yaml

from services.director_review_models import DirectorRevisionEvent, DirectorRevisionState
from services.voice_project_store import VoiceProjectStore


class DirectorRevisionStore:
    def __init__(self, project_store: VoiceProjectStore):
        self.project_store = project_store
        self._lock = threading.RLock()

    def _paths(self, project_id: str) -> tuple[Path, Path]:
        project_dir = self.project_store.get_project_dir(project_id)
        return project_dir / "revision-history.yaml", project_dir / "revision-state.yaml"

    @staticmethod
    def _atomic_yaml(path: Path, data: dict) -> None:
        pending = path.with_suffix(f".tmp_{uuid.uuid4().hex[:8]}.yaml")
        try:
            pending.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
            pending.replace(path)
        finally:
            if pending.exists():
                pending.unlink()

    def list_events(self, project_id: str) -> list[DirectorRevisionEvent]:
        history_path, _ = self._paths(project_id)
        if not history_path.exists():
            return []
        data = yaml.safe_load(history_path.read_text(encoding="utf-8")) or {}
        return [DirectorRevisionEvent.model_validate(item) for item in data.get("events", [])]

    def get_state(self, project_id: str) -> DirectorRevisionState:
        _, state_path = self._paths(project_id)
        if not state_path.exists():
            return DirectorRevisionState()
        return DirectorRevisionState.model_validate(yaml.safe_load(state_path.read_text(encoding="utf-8")) or {})

    def append(self, event: DirectorRevisionEvent) -> None:
        with self._lock, self.project_store.get_project_lock(event.project_id):
            events = self.list_events(event.project_id)
            events.append(event)
            history_path, state_path = self._paths(event.project_id)
            self._atomic_yaml(history_path, {"version": 1, "events": [item.model_dump(mode="json") for item in events]})

            self._atomic_yaml(state_path, self._state_from(events).model_dump(mode="json"))

    @staticmethod
    def _state_from(events: list[DirectorRevisionEvent]) -> DirectorRevisionState:
        pending = [event for event in events if event.status == "pending"]
        beats = [beat for event in pending for beat in (event.affected_beats or ([event.beat_id] if event.beat_id else []))]
        return DirectorRevisionState(
            pending_revision_ids=[event.revision_id for event in pending],
            affected_beats=list(dict.fromkeys(beats)),
            invalidated_artifacts=list(dict.fromkeys(a for event in pending for a in event.affected_artifacts)),
            required_reproduction_steps=list(dict.fromkeys(s for event in pending for s in event.required_reproduction_steps)),
            final_approval_invalidated=any(event.approval_required for event in pending),
        )

    def mark_reproduced(self, project_id: str, revision_ids: list[str]) -> None:
        with self._lock, self.project_store.get_project_lock(project_id):
            events = self.list_events(project_id)
            wanted = set(revision_ids)
            now = datetime.now(timezone.utc).isoformat()
            for event in events:
                if event.revision_id in wanted and event.status == "pending":
                    event.status = "reproduced"
                    event.reproduced_at = now
            history_path, state_path = self._paths(project_id)
            self._atomic_yaml(history_path, {"version": 1, "events": [item.model_dump(mode="json") for item in events]})
            self._atomic_yaml(state_path, self._state_from(events).model_dump(mode="json"))

    def clear_reproduced(self, project_id: str) -> None:
        state = self.get_state(project_id)
        self.mark_reproduced(project_id, state.pending_revision_ids)
