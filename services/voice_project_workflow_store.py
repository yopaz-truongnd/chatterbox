"""Voice Project Workflow Store (Phase 15).

Provides thread-safe atomic filesystem persistence for VoiceWorkflowState records
stored under workflows/{workflow_id}.yaml.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import Any
import uuid
import yaml

from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowStatus

logger = logging.getLogger(__name__)


class VoiceProjectWorkflowStore:
    """YAML repository for workflow state management."""

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
        self._lock = threading.RLock()
        self._recover_interrupted_workflows()

    def _recover_interrupted_workflows(self) -> None:
        """Startup recovery: mark active workflows interrupted if server crashed."""
        with self._lock:
            for yaml_file in self.root_dir.glob("vwf_*.yaml"):
                try:
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    wf = VoiceWorkflowState.from_dict(data)
                    if wf.status in (WorkflowStatus.QUEUED, WorkflowStatus.RUNNING):
                        logger.info("Recovering interrupted workflow '%s'", wf.workflow_id)
                        wf.status = WorkflowStatus.INTERRUPTED
                        wf.error = {
                            "code": "WORKFLOW_INTERRUPTED",
                            "message": "Workflow execution was interrupted by server shutdown/restart.",
                        }
                        self.save_workflow(wf)
                except Exception as e:
                    logger.warning("Failed to recover workflow '%s': %s", yaml_file, e)

    def save_workflow(self, state: VoiceWorkflowState) -> None:
        """Atomically persist workflow state to workflows/{workflow_id}.yaml."""
        with self._lock:
            self.root_dir.mkdir(parents=True, exist_ok=True)
            target_path = self.root_dir / f"{state.workflow_id}.yaml"

            # Terminal State Protection: never allow non-terminal writes to overwrite terminal states (e.g. CANCELLED)
            if target_path.exists() and state.status not in (WorkflowStatus.CANCELLED, WorkflowStatus.FAILED, WorkflowStatus.COMPLETED):
                try:
                    with open(target_path, "r", encoding="utf-8") as f:
                        existing_data = yaml.safe_load(f) or {}
                    existing_status = existing_data.get("status")
                    if existing_status in (WorkflowStatus.CANCELLED.value, WorkflowStatus.FAILED.value, WorkflowStatus.COMPLETED.value):
                        return
                except Exception:
                    pass

            temp_path = target_path.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}.yaml")
            try:
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(state.to_yaml())
                temp_path.replace(target_path)
            except Exception as exc:
                logger.warning("Failed to save workflow '%s': %s", state.workflow_id, exc)
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass

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
