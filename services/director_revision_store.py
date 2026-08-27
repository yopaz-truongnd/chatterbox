"""Atomic project-level revision history and explicit invalidation state."""

from __future__ import annotations

from pathlib import Path
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

            state = self.get_state(event.project_id)
            state.affected_beats = list(dict.fromkeys(state.affected_beats + ([event.beat_id] if event.beat_id else [])))
            state.invalidated_artifacts = list(dict.fromkeys(state.invalidated_artifacts + event.affected_artifacts))
            state.required_reproduction_steps = list(
                dict.fromkeys(state.required_reproduction_steps + event.required_reproduction_steps)
            )
            state.final_approval_invalidated = state.final_approval_invalidated or event.approval_required
            self._atomic_yaml(state_path, state.model_dump(mode="json"))

    def clear_reproduced(self, project_id: str) -> None:
        with self._lock, self.project_store.get_project_lock(project_id):
            _, state_path = self._paths(project_id)
            self._atomic_yaml(state_path, DirectorRevisionState().model_dump(mode="json"))
