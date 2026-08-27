"""Voice Project Asynchronous Operations Manager (Phase 12-13 Hardened).

Manages background project operations (plan, check_resources, render, render_beat,
evaluate, prepare_mix, mix, master, export, finalize), tracking progress, cooperative
cancellation, persistence to operations/{id}.yaml, and concurrency serialization per project.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from enum import Enum
import logging
import os
from pathlib import Path
import threading
from typing import Any, Callable
import uuid
import yaml

from pydantic import BaseModel, Field

from services.tts.base import CancellationToken

logger = logging.getLogger(__name__)


class _BoolCallable:
    """A boolean-like object that is also callable.

    Allows task code to use both forms without error:
      if token.is_cancelled: ...        # attribute / property form
      if token.is_cancelled(): ...      # method-call form
    """

    __slots__ = ("_token",)

    def __init__(self, token: CancellationToken) -> None:
        self._token = token

    def __bool__(self) -> bool:
        return self._token._cancelled

    def __call__(self) -> bool:
        return self._token._cancelled

    def __repr__(self) -> str:
        return repr(self._token._cancelled)


class _TaskCancellationProxy:
    """Wraps CancellationToken so tasks can use .is_cancelled as both attribute and callable.

    Injected as ``cancellation_token`` kwarg into submitted task functions, replacing the
    raw CancellationToken that only supports the method-call form ``token.is_cancelled()``.
    """

    def __init__(self, token: CancellationToken) -> None:
        self._token = token
        self.is_cancelled: _BoolCallable = _BoolCallable(token)

    def cancel(self) -> None:
        self._token.cancel()


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLING = "cancelling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_OPERATION_STATUSES = {
    OperationStatus.COMPLETED,
    OperationStatus.FAILED,
    OperationStatus.CANCELLED,
    OperationStatus.INTERRUPTED,
}


class OperationType(str, Enum):
    PLAN = "plan"
    CHECK_RESOURCES = "check_resources"
    RENDER = "render"
    RENDER_BEAT = "render_beat"
    EVALUATE = "evaluate"
    PREPARE_MIX = "prepare_mix"
    MIX = "mix"
    MASTER = "master"
    EXPORT = "export"
    FINALIZE = "finalize"


class OperationAlreadyRunningError(Exception):
    """Raised when an operation is already active on the target project."""

    def __init__(self, project_id: str, existing_job_id: str, operation: str):
        super().__init__(
            f"Operation '{operation}' (job_id: {existing_job_id}) is already active on project '{project_id}'."
        )
        self.project_id = project_id
        self.existing_job_id = existing_job_id
        self.operation = operation


class OperationProgress(BaseModel):
    """Standardized normalized progress payload for background operations."""

    stage: str
    percent: float = 0.0
    beat_id: str | None = None
    child_job_id: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceProjectOperation(BaseModel):
    """Data transfer model for a tracked Voice Project operation."""

    id: str
    project_id: str
    operation: str
    status: OperationStatus = OperationStatus.QUEUED
    cancellation_requested: bool = False
    stage: str | None = None
    beat_id: str | None = None
    child_job_id: str | None = None
    progress_percent: float = 0.0
    message: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    class Config:
        arbitrary_types_allowed = True

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VoiceProjectOperationManager:
    """Thread-safe manager for asynchronous Voice Project operations with YAML persistence."""

    def __init__(self, max_workers: int = 4, operations_dir: Path | str | None = None):
        self._operations: dict[str, VoiceProjectOperation] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._project_active_op: dict[str, str] = {}  # project_id -> job_id
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="VoiceProjectOp")

        # Resolve operations directory
        if operations_dir:
            self.operations_dir = Path(operations_dir)
        else:
            data_dir = os.getenv("CHATTERBOX_API_DATA_DIR")
            if data_dir:
                self.operations_dir = Path(data_dir) / "operations"
            else:
                self.operations_dir = Path("projects/operations")

        try:
            self.operations_dir.mkdir(parents=True, exist_ok=True)
            self._load_and_recover_persisted_operations()
        except Exception as e:
            logger.warning("Failed to initialize operations directory '%s': %s", self.operations_dir, e)

    def _load_and_recover_persisted_operations(self) -> None:
        """Load operations from disk on startup and recover any interrupted states."""
        if not self.operations_dir.exists():
            return

        with self._lock:
            for yaml_path in self.operations_dir.glob("vp_op_*.yaml"):
                try:
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    op = VoiceProjectOperation.model_validate(data)

                    # Startup recovery: If previous server run crashed during active op, mark INTERRUPTED
                    if op.status in (OperationStatus.QUEUED, OperationStatus.RUNNING, OperationStatus.CANCELLING):
                        logger.info(
                            "Recovering interrupted operation '%s' (project: %s, previous status: %s)",
                            op.id,
                            op.project_id,
                            op.status.value,
                        )
                        op.status = OperationStatus.INTERRUPTED
                        op.error = {
                            "code": "OPERATION_INTERRUPTED",
                            "message": "Operation was interrupted by server restart or shutdown.",
                        }
                        op.updated_at = datetime.now(timezone.utc).isoformat()
                        self._save_to_disk(op)

                    self._operations[op.id] = op
                except Exception as exc:
                    logger.warning("Failed to load operation file '%s': %s", yaml_path, exc)

    def _save_to_disk(self, op: VoiceProjectOperation) -> None:
        """Atomically persist operation state to YAML file."""
        if not self.operations_dir.exists():
            return
        target_file = self.operations_dir / f"{op.id}.yaml"
        temp_file = target_file.with_suffix(f".tmp_{uuid.uuid4().hex[:6]}")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(op.to_dict(), f, sort_keys=False, allow_unicode=True)
            temp_file.replace(target_file)
        except Exception as exc:
            logger.warning("Failed to persist operation '%s' to '%s': %s", op.id, target_file, exc)
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError:
                    pass

    def submit(
        self,
        project_id: str,
        operation: str,
        task_fn: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> VoiceProjectOperation:
        """Submit a background project task with project-level concurrency serialization."""
        with self._lock:
            active_job_id = self._project_active_op.get(project_id)
            if active_job_id:
                active_op = self._operations.get(active_job_id)
                if active_op and active_op.status in (
                    OperationStatus.QUEUED,
                    OperationStatus.RUNNING,
                    OperationStatus.CANCELLING,
                ):
                    raise OperationAlreadyRunningError(
                        project_id=project_id,
                        existing_job_id=active_job_id,
                        operation=active_op.operation,
                    )

            job_id = f"vp_op_{uuid.uuid4().hex[:12]}"
            token = CancellationToken()

            op = VoiceProjectOperation(
                id=job_id,
                project_id=project_id,
                operation=operation,
                status=OperationStatus.QUEUED,
                progress_percent=0.0,
            )

            self._operations[job_id] = op
            self._tokens[job_id] = token
            self._project_active_op[project_id] = job_id
            self._save_to_disk(op)

            # Capture QUEUED snapshot inside the lock before worker runs
            queued_snapshot = op.model_copy()

        # Submit background task wrapper to ThreadPoolExecutor
        self._executor.submit(self._run_task, job_id, project_id, operation, token, task_fn, args, kwargs)
        return queued_snapshot

    def _rollback_project_stage_on_cancel(self, project_id: str) -> None:
        """Restore project stage to last_stable_stage on operation cancellation."""
        try:
            from services.voice_project_dependencies import get_voice_project_store
            store = get_voice_project_store()
            if store.project_exists(project_id):
                state = store.get_project_state(project_id, recover_transient=False)
                if state.stage != state.last_stable_stage:
                    logger.info(
                        "Rolling back project '%s' stage from '%s' to '%s' after cancellation.",
                        project_id,
                        state.stage.value,
                        state.last_stable_stage.value,
                    )
                    state.stage = state.last_stable_stage
                    state.error = "Operation was cancelled by user."
                    store.save_project_state(state)
        except Exception as e:
            logger.warning("Failed to rollback project stage for '%s' on cancellation: %s", project_id, e)

    def _run_task(
        self,
        job_id: str,
        project_id: str,
        operation: str,
        token: CancellationToken,
        task_fn: Callable[..., Any],
        args: tuple,
        kwargs: dict,
    ) -> None:
        """Background worker execution loop with progress reporting and cancellation handling."""
        # 1. Early Cancellation Check (e.g. cancelled while still in queue)
        if token.is_cancelled():
            logger.info("Operation '%s' (%s) cancelled before task execution started.", job_id, operation)
            self._update_op(
                job_id,
                status=OperationStatus.CANCELLED,
                progress_percent=100.0,
                error={"code": "OPERATION_CANCELLED", "message": "Operation was cancelled before execution started."},
            )
            self._rollback_project_stage_on_cancel(project_id)
            with self._lock:
                if self._project_active_op.get(project_id) == job_id:
                    del self._project_active_op[project_id]
            return

        self._update_op(job_id, status=OperationStatus.RUNNING, progress_percent=5.0)

        def progress_callback(
            stage_or_progress: str | OperationProgress | dict[str, Any],
            percent: float | None = None,
            meta_or_beat: Any = None,
            **extra: Any,
        ):
            """Flexible normalized progress callback."""
            if isinstance(stage_or_progress, OperationProgress):
                self._update_op(
                    job_id,
                    stage=stage_or_progress.stage,
                    progress_percent=max(0.0, min(100.0, stage_or_progress.percent)),
                    beat_id=stage_or_progress.beat_id,
                    child_job_id=stage_or_progress.child_job_id,
                    message=stage_or_progress.message,
                )
            elif isinstance(stage_or_progress, dict):
                stage = stage_or_progress.get("stage", "running")
                pct = float(stage_or_progress.get("percent", percent or 0.0))
                self._update_op(
                    job_id,
                    stage=stage,
                    progress_percent=max(0.0, min(100.0, pct)),
                    beat_id=stage_or_progress.get("beat_id"),
                    child_job_id=stage_or_progress.get("child_job_id"),
                    message=stage_or_progress.get("message"),
                )
            else:
                stage = str(stage_or_progress)
                pct = float(percent if percent is not None else 0.0)
                beat_id = None
                child_job_id = None
                msg = None
                if isinstance(meta_or_beat, dict):
                    beat_id = meta_or_beat.get("beat_id")
                    child_job_id = meta_or_beat.get("child_job_id")
                    msg = meta_or_beat.get("message")
                elif isinstance(meta_or_beat, str):
                    beat_id = meta_or_beat

                if "beat_id" in extra:
                    beat_id = extra["beat_id"]
                if "child_job_id" in extra:
                    child_job_id = extra["child_job_id"]
                if "message" in extra:
                    msg = extra["message"]

                self._update_op(
                    job_id,
                    stage=stage,
                    progress_percent=max(0.0, min(100.0, pct)),
                    beat_id=beat_id,
                    child_job_id=child_job_id,
                    message=msg,
                )

        # Inject progress and cancellation kwargs if task function accepts them
        import inspect
        proxy = _TaskCancellationProxy(token)
        task_kwargs = dict(kwargs)
        try:
            sig = inspect.signature(task_fn)
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            if "cancellation_token" in sig.parameters or has_var_keyword:
                task_kwargs["cancellation_token"] = proxy
            if "progress_callback" in sig.parameters or has_var_keyword:
                task_kwargs["progress_callback"] = progress_callback
        except Exception:
            task_kwargs["cancellation_token"] = proxy
            task_kwargs["progress_callback"] = progress_callback

        try:
            res = task_fn(*args, **task_kwargs)

            if token.is_cancelled():
                self._update_op(
                    job_id,
                    status=OperationStatus.CANCELLED,
                    progress_percent=100.0,
                    error={"code": "OPERATION_CANCELLED", "message": "Operation was cancelled by user."},
                )
                self._rollback_project_stage_on_cancel(project_id)
            else:
                result_dict = (
                    res.to_dict()
                    if hasattr(res, "to_dict")
                    else res
                    if isinstance(res, dict)
                    else {"status": "success"}
                )
                self._update_op(
                    job_id,
                    status=OperationStatus.COMPLETED,
                    progress_percent=100.0,
                    result=result_dict,
                )
        except Exception as exc:
            if token.is_cancelled():
                logger.info("Operation '%s' cancelled during exception handling.", job_id)
                self._update_op(
                    job_id,
                    status=OperationStatus.CANCELLED,
                    progress_percent=100.0,
                    error={"code": "OPERATION_CANCELLED", "message": "Operation was cancelled by user."},
                )
                self._rollback_project_stage_on_cancel(project_id)
            else:
                logger.exception("VoiceProject operation '%s' (%s) failed: %s", job_id, operation, exc)
                err_code = getattr(exc, "code", type(exc).__name__)
                self._update_op(
                    job_id,
                    status=OperationStatus.FAILED,
                    error={
                        "code": err_code,
                        "message": str(exc),
                    },
                )
        finally:
            with self._lock:
                if self._project_active_op.get(project_id) == job_id:
                    del self._project_active_op[project_id]

    def _update_op(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            op = self._operations.get(job_id)
            if not op:
                return
            for k, v in kwargs.items():
                if hasattr(op, k):
                    # Guard: beat_id / child_job_id must be str | None — coerce if passed as dict
                    if k in ("beat_id", "child_job_id") and isinstance(v, dict):
                        v = v.get(k) or v.get("id") or None
                    setattr(op, k, v)
            op.updated_at = datetime.now(timezone.utc).isoformat()
            self._save_to_disk(op)

    def get_operation(self, job_id: str) -> VoiceProjectOperation | None:
        """Retrieve operation status by ID."""
        with self._lock:
            return self._operations.get(job_id)

    def list_operations(
        self,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[VoiceProjectOperation]:
        """List recent operations, optionally filtered by project ID."""
        with self._lock:
            ops = list(self._operations.values())
            if project_id:
                ops = [op for op in ops if op.project_id == project_id]
            ops.sort(key=lambda o: o.created_at, reverse=True)
            return ops[:limit]

    def cancel_operation(self, job_id: str) -> tuple[bool, str]:
        """Request cooperative cancellation of a queued or running operation.

        Marks the operation as CANCELLING and signals the cancellation token.
        Crucially, does NOT release the active project lock immediately; the lock
        remains held until the background worker observes cancellation and safely terminates.
        """
        with self._lock:
            op = self._operations.get(job_id)
            if not op:
                return False, f"Operation '{job_id}' not found."

            if op.status in TERMINAL_OPERATION_STATUSES:
                return False, f"Operation '{job_id}' is already in terminal state '{op.status.value}'."

            if op.status == OperationStatus.CANCELLING or op.cancellation_requested:
                return True, f"Operation '{job_id}' cancellation already in progress."

            token = self._tokens.get(job_id)
            if token:
                token.cancel()

            # Mark CANCELLING intermediate state — do NOT delete _project_active_op yet!
            op.cancellation_requested = True
            op.status = OperationStatus.CANCELLING
            op.updated_at = datetime.now(timezone.utc).isoformat()
            op.error = {"code": "OPERATION_CANCELLED", "message": "Operation cancellation requested by user."}
            self._save_to_disk(op)

            return True, f"Operation '{job_id}' cancellation requested."
