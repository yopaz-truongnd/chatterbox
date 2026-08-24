"""Voice Project Storage & Workspace Persistence Service (Phase 11).

Provides thread-safe, atomic filesystem storage for VoiceProject workspaces:
- Enforces strict project ID format validation to prevent path traversal.
- Manages project-level threading locks for concurrent execution safety.
- Handles atomic YAML and text writes via temporary files and rename.
- Tracks dependency hashes (source, voice-plan, resource-report, render-manifest).
- Detects artifact staleness and supports transient state crash recovery.
"""

from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
import re
import threading
from typing import Any
import uuid
import yaml

from services.director_critic import DirectorCritiqueResult
from services.render_models import (
    ProjectArtifacts,
    ProjectState,
    ProjectStatus,
    RenderManifest,
)
from services.resource_models import ResourceReport
from services.voice_plan import VoicePlan
from services.voice_project_models import (
    StaleArtifactError,
    VoiceProjectAlreadyExists,
    VoiceProjectNotFound,
    compute_file_sha256,
    compute_string_sha256,
)
from services.voice_renderer import load_render_manifest, save_render_manifest

logger = logging.getLogger(__name__)

PROJECT_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")
DEFAULT_PROJECTS_DIR = "projects"


class VoiceProjectStore:
    """Filesystem repository for VoiceProject workspaces with atomic writes and locking."""

    def __init__(self, root_dir: Path | str | None = None):
        self.root_dir = Path(root_dir or os.getenv("CHATTERBOX_VOICE_PROJECTS_DIR") or DEFAULT_PROJECTS_DIR)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._project_locks: dict[str, threading.RLock] = {}
        self._global_lock = threading.RLock()

    def get_project_lock(self, project_id: str) -> threading.RLock:
        """Retrieve a re-entrant lock for a specific project ID."""
        self.validate_project_id(project_id)
        with self._global_lock:
            if project_id not in self._project_locks:
                self._project_locks[project_id] = threading.RLock()
            return self._project_locks[project_id]

    @staticmethod
    def validate_project_id(project_id: str) -> None:
        """Enforce strict project ID characters to prevent path traversal."""
        if not project_id or not PROJECT_ID_REGEX.match(project_id):
            raise ValueError(
                f"Invalid project_id '{project_id}'. Must be non-empty and match pattern '^[a-zA-Z0-9_-]+$'."
            )

    def get_project_dir(self, project_id: str) -> Path:
        """Get canonical directory path for a project ID."""
        self.validate_project_id(project_id)
        return self.root_dir / project_id

    # ==========================================
    # Atomic File Helpers
    # ==========================================

    @staticmethod
    def _atomic_write_text(file_path: Path, content: str) -> None:
        """Write string content atomically via temporary file and rename."""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_name(f".tmp_{file_path.name}_{uuid.uuid4().hex[:8]}")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp_path.replace(file_path)

    @staticmethod
    def _atomic_write_yaml(file_path: Path, data: dict[str, Any]) -> None:
        """Write dictionary as YAML atomically."""
        yaml_content = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        VoiceProjectStore._atomic_write_text(file_path, yaml_content)

    # ==========================================
    # Workspace & State Management
    # ==========================================

    def create_workspace(
        self,
        project_id: str,
        script_text: str,
        title: str | None = None,
        language: str = "en",
        config: dict[str, Any] | None = None,
    ) -> ProjectState:
        """Create new project workspace, persist source script, and initialize state."""
        self.validate_project_id(project_id)
        if not script_text or not script_text.strip():
            raise ValueError("Source script text cannot be empty.")

        with self.get_project_lock(project_id):
            proj_dir = self.get_project_dir(project_id)
            if proj_dir.exists():
                raise VoiceProjectAlreadyExists(f"Project '{project_id}' already exists at {proj_dir}")
            proj_dir.mkdir(parents=True)
            (proj_dir / "source").mkdir(parents=True, exist_ok=True)
            (proj_dir / "renders").mkdir(parents=True, exist_ok=True)
            (proj_dir / "qc").mkdir(parents=True, exist_ok=True)
            (proj_dir / "logs").mkdir(parents=True, exist_ok=True)

            # Persist source script
            script_path = proj_dir / "source" / "script.txt"
            self._atomic_write_text(script_path, script_text)
            source_hash = compute_string_sha256(script_text)

            # Initialize and persist project.yaml
            state = ProjectState(
                version=1,
                project_id=project_id,
                title=title or project_id,
                language=language,
                source_script_path="source/script.txt",
                stage=ProjectStatus.NEW,
                last_stable_stage=ProjectStatus.NEW,
                artifacts=ProjectArtifacts(source_sha256=source_hash),
            )
            state_path = proj_dir / "project.yaml"
            self._atomic_write_yaml(state_path, state.to_dict())
            return state

    def get_project_state(self, project_id: str, recover_transient: bool = False) -> ProjectState:
        """Load project.yaml with optional transient state crash recovery."""
        self.validate_project_id(project_id)
        proj_dir = self.get_project_dir(project_id)
        state_path = proj_dir / "project.yaml"

        if not state_path.exists():
            raise VoiceProjectNotFound(f"Project '{project_id}' not found at {proj_dir}")

        with open(state_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        state = ProjectState.from_dict(data)

        # Recover from transient state if process crashed during active operations
        transient_stages = (
            ProjectStatus.PLANNING,
            ProjectStatus.RESOURCE_CHECKING,
            ProjectStatus.RENDERING,
            ProjectStatus.QC_PENDING,
        )
        if recover_transient and state.stage in transient_stages:
            logger.warning(
                "Project '%s' was loaded in transient state '%s'; rolling back to '%s'",
                project_id,
                state.stage,
                state.last_stable_stage,
            )
            state.stage = state.last_stable_stage
            state.error = f"Recovered from interrupted operation"
            self.save_project_state(state)

        return state

    def recover_transient_state(self, project_id: str) -> ProjectState:
        """Explicitly recover project from any interrupted transient state."""
        return self.get_project_state(project_id, recover_transient=True)

    def save_project_state(self, state: ProjectState) -> None:
        """Atomically persist updated ProjectState to project.yaml."""
        self.validate_project_id(state.project_id)
        with self.get_project_lock(state.project_id):
            proj_dir = self.get_project_dir(state.project_id)
            state.updated_at = datetime.utcnow().isoformat()
            state_path = proj_dir / "project.yaml"
            self._atomic_write_yaml(state_path, state.to_dict())

    def read_source_script(self, project_id: str) -> str:
        """Read source/script.txt from disk."""
        self.validate_project_id(project_id)
        proj_dir = self.get_project_dir(project_id)
        script_path = proj_dir / "source" / "script.txt"
        if not script_path.exists():
            raise VoiceProjectNotFound(f"Source script missing for project '{project_id}' at {script_path}")
        with open(script_path, "r", encoding="utf-8") as f:
            return f.read()

    def update_source_script(self, project_id: str, new_script_text: str) -> ProjectState:
        """Update source/script.txt, recalculate source hash, and invalidate downstream artifacts."""
        self.validate_project_id(project_id)
        if not new_script_text or not new_script_text.strip():
            raise ValueError("Script text cannot be empty.")

        with self.get_project_lock(project_id):
            state = self.get_project_state(project_id)
            proj_dir = self.get_project_dir(project_id)

            script_path = proj_dir / "source" / "script.txt"
            self._atomic_write_text(script_path, new_script_text)
            new_source_hash = compute_string_sha256(new_script_text)

            # Invalidate downstream planning & resource artifact hashes
            state.artifacts.source_sha256 = new_source_hash
            state.artifacts.voice_plan_source_sha256 = ""
            state.artifacts.voice_plan_sha256 = ""
            state.artifacts.resource_report_voice_plan_sha256 = ""
            state.artifacts.resource_report_sha256 = ""
            state.artifacts.render_manifest_voice_plan_sha256 = ""
            state.artifacts.render_manifest_resource_report_sha256 = ""
            state.artifacts.render_manifest_sha256 = ""

            # Reset lifecycle stage to NEW
            state.stage = ProjectStatus.NEW
            state.last_stable_stage = ProjectStatus.NEW
            state.error = None

            self.save_project_state(state)
            return state

    # ==========================================
    # Planning & Resource Artifacts
    # ==========================================

    def save_voice_plan(
        self,
        project_id: str,
        plan: VoicePlan,
        critique: DirectorCritiqueResult | None = None,
    ) -> None:
        """Save voice-plan.yaml and director-critique.yaml, updating artifact dependency hashes."""
        self.validate_project_id(project_id)
        with self.get_project_lock(project_id):
            proj_dir = self.get_project_dir(project_id)
            plan_path = proj_dir / "voice-plan.yaml"
            self._atomic_write_text(plan_path, plan.to_yaml())
            plan_hash = compute_file_sha256(plan_path)

            if critique:
                critique_path = proj_dir / "director-critique.yaml"
                critique_dict = critique.model_dump(mode="json") if hasattr(critique, "model_dump") else (critique.to_dict() if hasattr(critique, "to_dict") else dict(critique))
                self._atomic_write_yaml(critique_path, critique_dict)

            state = self.get_project_state(project_id)
            source_hash = state.artifacts.source_sha256 or compute_file_sha256(proj_dir / "source" / "script.txt")

            state.artifacts.voice_plan_source_sha256 = source_hash
            state.artifacts.voice_plan_sha256 = plan_hash
            state.stage = ProjectStatus.PLANNED
            state.last_stable_stage = ProjectStatus.PLANNED
            state.error = None

            self.save_project_state(state)

    def load_voice_plan(self, project_id: str) -> VoicePlan | None:
        """Load voice-plan.yaml if present."""
        self.validate_project_id(project_id)
        proj_dir = self.get_project_dir(project_id)
        plan_path = proj_dir / "voice-plan.yaml"
        if not plan_path.exists():
            return None
        with open(plan_path, "r", encoding="utf-8") as f:
            return VoicePlan.from_yaml(f.read())

    def save_resource_report(self, project_id: str, report: ResourceReport) -> None:
        """Save resource-report.yaml and update dependency hashes and gate stage."""
        self.validate_project_id(project_id)
        with self.get_project_lock(project_id):
            proj_dir = self.get_project_dir(project_id)
            report_path = proj_dir / "resource-report.yaml"
            self._atomic_write_text(report_path, report.to_yaml())
            report_hash = compute_file_sha256(report_path)

            state = self.get_project_state(project_id)
            plan_hash = state.artifacts.voice_plan_sha256 or compute_file_sha256(proj_dir / "voice-plan.yaml")

            state.artifacts.resource_report_voice_plan_sha256 = plan_hash
            state.artifacts.resource_report_sha256 = report_hash

            if report.readiness.render_blocked:
                state.stage = ProjectStatus.RESOURCE_BLOCKED
            else:
                state.stage = ProjectStatus.READY_TO_RENDER

            state.last_stable_stage = state.stage
            state.error = None

            self.save_project_state(state)

    def load_resource_report(self, project_id: str) -> ResourceReport | None:
        """Load resource-report.yaml if present."""
        self.validate_project_id(project_id)
        proj_dir = self.get_project_dir(project_id)
        report_path = proj_dir / "resource-report.yaml"
        if not report_path.exists():
            return None
        with open(report_path, "r", encoding="utf-8") as f:
            return ResourceReport.from_yaml(f.read())

    def load_manifest(self, project_id: str) -> RenderManifest:
        """Load render-manifest.yaml for project workspace."""
        self.validate_project_id(project_id)
        proj_dir = self.get_project_dir(project_id)
        return load_render_manifest(proj_dir)

    def save_manifest(self, project_id: str, manifest: RenderManifest) -> None:
        """Atomically save render manifest and record its dependency hashes."""
        self.validate_project_id(project_id)
        with self.get_project_lock(project_id):
            proj_dir = self.get_project_dir(project_id)
            manifest_path = proj_dir / "render-manifest.yaml"
            self._atomic_write_text(manifest_path, manifest.to_yaml())

            state = self.get_project_state(project_id)
            state.artifacts.render_manifest_voice_plan_sha256 = state.artifacts.voice_plan_sha256
            state.artifacts.render_manifest_resource_report_sha256 = state.artifacts.resource_report_sha256
            state.artifacts.render_manifest_sha256 = compute_file_sha256(manifest_path)
            self.save_project_state(state)

    # ==========================================
    # Staleness Verification
    # ==========================================

    def check_staleness(self, project_id: str, for_render: bool = False) -> tuple[bool, str | None]:
        """Check if project artifacts are stale relative to dependencies.
        
        Returns (is_stale, reason).
        """
        self.validate_project_id(project_id)
        state = self.get_project_state(project_id)
        proj_dir = self.get_project_dir(project_id)

        # 1. Check Source Script on disk vs recorded hash
        script_path = proj_dir / "source" / "script.txt"
        if script_path.exists():
            disk_source_hash = compute_file_sha256(script_path)
            if state.artifacts.source_sha256 and disk_source_hash != state.artifacts.source_sha256:
                return True, "Source script has been modified on disk"

        # 2. Check VoicePlan vs Source Script hash
        plan_path = proj_dir / "voice-plan.yaml"
        if plan_path.exists():
            if state.artifacts.voice_plan_sha256 and compute_file_sha256(plan_path) != state.artifacts.voice_plan_sha256:
                return True, "VoicePlan has been modified on disk (re-plan required)"
            if state.artifacts.voice_plan_source_sha256 != state.artifacts.source_sha256:
                return True, "VoicePlan is stale relative to current source script (re-plan required)"

        # 3. Check Resource Report vs VoicePlan hash (required during rendering)
        if for_render:
            report_path = proj_dir / "resource-report.yaml"
            if not report_path.exists():
                return True, "Resource report is missing (check-resources required)"
            if state.artifacts.resource_report_sha256 and compute_file_sha256(report_path) != state.artifacts.resource_report_sha256:
                return True, "Resource report has been modified on disk (check-resources required)"
            if state.artifacts.resource_report_voice_plan_sha256 != state.artifacts.voice_plan_sha256:
                return True, "Resource report is stale relative to current VoicePlan (check-resources required)"

            manifest_path = proj_dir / "render-manifest.yaml"
            if manifest_path.exists() and state.artifacts.render_manifest_sha256:
                if compute_file_sha256(manifest_path) != state.artifacts.render_manifest_sha256:
                    return True, "Render manifest has been modified on disk"
                if state.artifacts.render_manifest_voice_plan_sha256 != state.artifacts.voice_plan_sha256:
                    return True, "Render manifest is stale relative to current VoicePlan"
                if state.artifacts.render_manifest_resource_report_sha256 != state.artifacts.resource_report_sha256:
                    return True, "Render manifest is stale relative to current resource report"

        return False, None
