"""Voice Project Asynchronous Operations Manager (Phase 12).

Manages background project operations (plan, check_resources, render, render_beat, evaluate),
tracking progress, cooperative cancellation, and concurrency serialization per project.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from enum import Enum
import logging
import threading
from typing import Any, Callable
import uuid

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
        # is_cancelled works as: bool(proxy.is_cancelled) AND proxy.is_cancelled()
        self.is_cancelled: _BoolCallable = _BoolCallable(token)

    def cancel(self) -> None:
        self._token.cancel()


class OperationStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationType(str, Enum):
    PLAN = "plan"
    CHECK_RESOURCES = "check_resources"
    RENDER = "render"
    RENDER_BEAT = "render_beat"
    EVALUATE = "evaluate"


class OperationAlreadyRunningError(Exception):
    """Raised when an operation is already active on the target project."""

    def __init__(self, project_id: str, existing_job_id: str, operation: str):
        super().__init__(
            f"Operation '{operation}' (job_id: {existing_job_id}) is already running on project '{project_id}'."
        )
        self.project_id = project_id
        self.existing_job_id = existing_job_id
        self.operation = operation


class VoiceProjectOperation(BaseModel):
    """Data transfer model for a tracked Voice Project operation."""

    id: str
    project_id: str
    operation: str
    status: OperationStatus = OperationStatus.QUEUED
    stage: str | None = None
    beat_id: str | None = None
    child_job_id: str | None = None
    progress_percent: float = 0.0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    class Config:
        arbitrary_types_allowed = True

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VoiceProjectOperationManager:
    """Thread-safe in-memory manager for asynchronous Voice Project operations."""

    def __init__(self, max_workers: int = 4):
        self._operations: dict[str, VoiceProjectOperation] = {}
        self._tokens: dict[str, CancellationToken] = {}
        self._project_active_op: dict[str, str] = {}  # project_id -> job_id
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="VoiceProjectOp")

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
                if active_op and active_op.status in (OperationStatus.QUEUED, OperationStatus.RUNNING):
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
            # Capture QUEUED snapshot here — inside the lock, before the executor runs.
            # The live `op` object in _operations will be mutated by the background thread;
            # the snapshot returned to callers always reflects the QUEUED state at submission time.
            queued_snapshot = op.model_copy()

        # Submit background task wrapper
        self._executor.submit(self._run_task, job_id, project_id, operation, token, task_fn, args, kwargs)
        return queued_snapshot

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
        self._update_op(job_id, status=OperationStatus.RUNNING, progress_percent=5.0)

        def progress_callback(stage: str, percent: float, beat_id: str | None = None, child_job_id: str | None = None):
            self._update_op(
                job_id,
                stage=stage,
                progress_percent=max(0.0, min(100.0, percent)),
                beat_id=beat_id,
                child_job_id=child_job_id,
            )

        # Inject progress and cancellation kwargs if task function accepts them.
        # Use _TaskCancellationProxy so tasks can access is_cancelled both as attribute
        # (if token.is_cancelled: ...) and as callable (if token.is_cancelled(): ...).
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
                    error={"code": "OPERATION_CANCELLED", "message": "Operation was cancelled by user"},
                )
            else:
                result_dict = res.to_dict() if hasattr(res, "to_dict") else res if isinstance(res, dict) else {"status": "success"}
                self._update_op(
                    job_id,
                    status=OperationStatus.COMPLETED,
                    progress_percent=100.0,
                    result=result_dict,
                )
        except Exception as exc:
            logger.exception("VoiceProject operation '%s' (%s) failed: %s", job_id, operation, exc)
            err_code = type(exc).__name__
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
                    # Guard: beat_id / child_job_id must be str | None — coerce if caller
                    # accidentally passes a dict (e.g. {'beat_id': 'B01'}).
                    if k in ("beat_id", "child_job_id") and isinstance(v, dict):
                        v = v.get(k) or v.get("id") or None
                    setattr(op, k, v)
            op.updated_at = datetime.now(timezone.utc).isoformat()

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
        """Request cooperative cancellation of a queued or running operation."""
        with self._lock:
            op = self._operations.get(job_id)
            if not op:
                return False, f"Operation '{job_id}' not found."

            if op.status in (OperationStatus.COMPLETED, OperationStatus.FAILED, OperationStatus.CANCELLED):
                return False, f"Operation '{job_id}' is already in terminal state '{op.status.value}'."

            token = self._tokens.get(job_id)
            if token:
                token.cancel()

            op.status = OperationStatus.CANCELLED
            op.updated_at = datetime.now(timezone.utc).isoformat()
            op.error = {"code": "OPERATION_CANCELLED", "message": "Operation cancellation requested by user"}

            if self._project_active_op.get(op.project_id) == job_id:
                del self._project_active_op[op.project_id]

            return True, f"Operation '{job_id}' cancelled."
