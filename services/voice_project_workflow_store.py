"""Voice Project Workflow Store (Phase 15).

Provides thread-safe atomic filesystem persistence for VoiceWorkflowState records
stored under workflows/{workflow_id}.yaml.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import Any, Callable
import uuid
import yaml

from services.voice_project_models import InvalidProjectStateError
from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)


class VoiceProjectWorkflowStore:
    """YAML repository for workflow state management."""

    _locks_guard = threading.Lock()
    _root_locks: dict[str, threading.RLock] = {}

    def __init__(self, root_dir: Path | str | None = None):
        if root_dir:
            self.root_dir = Path(root_dir)
        else:
            data_dir = os.getenv("CHATTERBOX_API_DATA_DIR")
            if data_dir:
                self.root_dir = Path(data_dir) / "workflows"
            else:
                self.root_dir = Path("projects/workflows")

        self.root_dir.mkdir(parents=True, exist_ok=True)
        root_key = str(self.root_dir.resolve())
        with self._locks_guard:
            self._lock = self._root_locks.setdefault(root_key, threading.RLock())
        self._recovery_done = False

    def recover_interrupted_workflows(self) -> None:
        """Startup recovery: mark active workflows interrupted if server crashed."""
        with self._lock:
            if self._recovery_done:
                return
            self._recovery_done = True
            for yaml_file in self.root_dir.glob("vwf_*.yaml"):
                try:
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    wf = VoiceWorkflowState.from_dict(data)
                    if wf.status == WorkflowStatus.CANCELLING:
                        logger.info("Completing interrupted cancellation for workflow '%s'", wf.workflow_id)
                        wf.status = WorkflowStatus.CANCELLED
                        wf.error = None
                        wf.suggested_action = "Workflow cancellation completed during startup recovery."
                        self.save_workflow(wf)
                    elif wf.status in (WorkflowStatus.QUEUED, WorkflowStatus.RUNNING):
                        logger.info("Recovering interrupted workflow '%s'", wf.workflow_id)
                        wf.status = WorkflowStatus.INTERRUPTED
                        wf.error = {
                            "code": "WORKFLOW_INTERRUPTED",
                            "message": "Workflow execution was interrupted by server shutdown/restart.",
                        }
                        self.save_workflow(wf)
                except Exception as e:
                    logger.warning("Failed to recover workflow '%s': %s", yaml_file, e)

    def save_workflow(self, state: VoiceWorkflowState) -> bool:
        """Atomically persist workflow state to workflows/{workflow_id}.yaml."""
        with self._lock:
            self.root_dir.mkdir(parents=True, exist_ok=True)
            target_path = self.root_dir / f"{state.workflow_id}.yaml"

            if target_path.exists():
                with open(target_path, "r", encoding="utf-8") as f:
                    existing_status = (yaml.safe_load(f) or {}).get("status")
                immutable = {
                    WorkflowStatus.CANCELLED.value,
                    WorkflowStatus.FAILED.value,
                    WorkflowStatus.COMPLETED.value,
                }
                if existing_status in immutable:
                    return False
                if existing_status == WorkflowStatus.CANCELLING.value and state.status not in (
                    WorkflowStatus.CANCELLING,
                    WorkflowStatus.CANCELLED,
                ):
                    return False

            temp_path = target_path.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}.yaml")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(state.to_yaml())
                    f.flush()
                    os.fsync(f.fileno())
                temp_path.replace(target_path)
                return True
            except Exception:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                raise

    def transition_workflow(
        self,
        workflow_id: str,
        expected_status: WorkflowStatus,
        mutate: Callable[[VoiceWorkflowState], None],
    ) -> VoiceWorkflowState:
        """Atomically validate and mutate a workflow state."""
        with self._lock:
            state = self.get_workflow(workflow_id)
            if not state:
                raise ValueError(f"Workflow '{workflow_id}' not found.")
            if state.status != expected_status:
                raise InvalidProjectStateError(
                    f"Workflow '{workflow_id}' is in status '{state.status.value}', expected '{expected_status.value}'."
                )
            mutate(state)
            if not self.save_workflow(state):
                raise InvalidProjectStateError(f"Workflow '{workflow_id}' changed concurrently.")
            return state

    def reopen_for_revision_approval(self, workflow_id: str, mutate: Callable[[VoiceWorkflowState], None]) -> VoiceWorkflowState:
        """Atomically reopen only a completed workflow for a rebuilt-master approval gate."""
        with self._lock:
            state = self.get_workflow(workflow_id)
            if not state:
                raise ValueError(f"Workflow '{workflow_id}' not found.")
            if state.status != WorkflowStatus.COMPLETED:
                raise InvalidProjectStateError(
                    f"Workflow '{workflow_id}' must be completed before revision approval can be requested."
                )
            mutate(state)
            target = self.root_dir / f"{workflow_id}.yaml"
            pending = target.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}.yaml")
            try:
                with open(pending, "w", encoding="utf-8") as f:
                    f.write(state.to_yaml())
                    f.flush()
                    os.fsync(f.fileno())
                pending.replace(target)
            finally:
                if pending.exists():
                    pending.unlink()
            return state

    def get_workflow(self, workflow_id: str) -> VoiceWorkflowState | None:
        """Load workflow state by ID."""
        with self._lock:
            target_path = self.root_dir / f"{workflow_id}.yaml"
            if not target_path.exists():
                return None
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                return VoiceWorkflowState.from_dict(data)
            except Exception as exc:
                logger.warning("Failed to parse workflow '%s': %s", target_path, exc)
                return None

    def list_workflows(self, limit: int = 50) -> list[VoiceWorkflowState]:
        """List all managed workflow states."""
        workflows = []
        with self._lock:
            for p in sorted(self.root_dir.glob("vwf_*.yaml"), reverse=True):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    workflows.append(VoiceWorkflowState.from_dict(data))
                    if len(workflows) >= limit:
                        break
                except Exception:
                    continue
        return workflows
