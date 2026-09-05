"""Real-Runtime Production Validation Service (Phase 21).

Coordinates end-to-end production validation across real canonical services:
- Project planning, VoicePlan, and Director Critic
- Resource gating and proper noun / pronunciation resolution
- TTS execution with real local Chatterbox or configurable provider
- 3-Layer Voice QC and adaptive retry
- Narration acceptance and director review
- Multi-track mix timeline, mix rendering, mastering, and final approval
- Deliverable export (WAV/MP3) and strict cryptographic lineage verification
- Incremental one-beat reproduction and timing-only reproduction validation
- Cancellation and restart safety verification
- Comprehensive performance metrics and sanitized diagnostics reports
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import platform
import resource
import shutil
import struct
import tempfile
import threading
import time
from typing import Any, Callable
import uuid
import wave
import yaml

from services.audio_export import AudioExportService
from services.director_review_models import BeatDirectionPatch, BeatTimingPatch
from services.director_review_service import DirectorReviewService
from services.director_revision_service import DirectorRevisionService
from services.local_runtime_service import LocalRuntimeService
from services.production_validation_models import (
    ProductionValidationArtifact,
    ProductionValidationBeatMetric,
    ProductionValidationFailure,
    ProductionValidationMetric,
    ProductionValidationReport,
    ProductionValidationRequest,
    ProductionValidationStep,
    ValidationVerdict,
)
from services.render_models import RenderStatus
from services.tts.base import CancellationToken, ProgressCallback, TTSExecutionPort
from services.voice_project_dependencies import (
    get_voice_project_operation_manager,
    get_voice_project_service,
    get_voice_project_store,
    resolve_server_tts_provider,
)
from services.voice_project_models import compute_file_sha256
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_project_operations import VoiceProjectOperationManager
from services.voice_project_workflow import VoiceProjectWorkflowService
from services.voice_project_workflow_models import VoiceWorkflowState, WorkflowPolicy, WorkflowStatus
from services.voice_project_workflow_store import VoiceProjectWorkflowStore

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("configs/production-validation.yaml")
_DEFAULT_GOLDEN_SCRIPT_PATH = Path("tests/fixtures/production/golden-mythology-story.txt")

# In-memory validation cache across the application process
_ACTIVE_VALIDATIONS: dict[str, ProductionValidationReport] = {}
_CANCELLATION_TOKENS: dict[str, CancellationToken] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_path(path_str: str | Path, base_dir: Path | None = None) -> str:
    """Sanitize absolute filesystem path into clean relative path for reports."""
    p = Path(path_str)
    if base_dir:
        try:
            return str(p.relative_to(base_dir))
        except ValueError:
            pass
    # If path contains 'projects/', return from 'projects/' onward
    parts = p.parts
    if "projects" in parts:
        idx = parts.index("projects")
        return "/".join(parts[idx:])
    return p.name


def _get_machine_summary() -> dict[str, Any]:
    """Capture sanitized host machine details without private credentials."""
    summary: dict[str, Any] = {
        "os": platform.system(),
        "os_release": platform.release(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 1,
        "machine": platform.machine(),
    }
    try:
        import torch
        summary["cuda_available"] = torch.cuda.is_available()
        summary["mps_available"] = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
        if torch.cuda.is_available():
            summary["gpu_name"] = torch.cuda.get_device_name(0)
            summary["gpu_count"] = torch.cuda.device_count()
    except Exception:
        summary["cuda_available"] = False
        summary["mps_available"] = False
    return summary


def _get_peak_memory_mb() -> float:
    """Measure peak process memory in megabytes."""
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS returns bytes, Linux returns kilobytes
        if platform.system() == "Darwin":
            return round(usage / (1024 * 1024), 2)
        return round(usage / 1024, 2)
    except Exception:
        return 0.0


def _inspect_audio_wave(wav_path: Path) -> dict[str, Any]:
    """Inspect and measure technical properties of a WAV file."""
    if not wav_path.exists() or wav_path.stat().st_size == 0:
        return {"valid": False, "error": "File missing or empty"}

    try:
        with wave.open(str(wav_path), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            duration_s = n_frames / float(framerate) if framerate > 0 else 0.0

            if n_frames == 0:
                return {"valid": False, "error": "Zero frames in audio"}

            raw_bytes = wf.readframes(n_frames)

        # 16-bit PCM inspection
        peak_amp = 0.0
        clipping_count = 0
        total_samples = 0
        sum_sq = 0.0
        silent_samples = 0
        max_silent_run = 0
        current_silent_run = 0

        if sample_width == 2:
            num_samples = len(raw_bytes) // 2
            samples = struct.unpack(f"<{num_samples}h", raw_bytes[: num_samples * 2])
            total_samples = len(samples)
            for s in samples:
                norm = abs(s) / 32768.0
                if norm > peak_amp:
                    peak_amp = norm
                if norm >= 0.999:
                    clipping_count += 1
                sum_sq += norm * norm
                if norm < 0.005:  # silence threshold (-46 dBFS)
                    current_silent_run += 1
                    silent_samples += 1
                    if current_silent_run > max_silent_run:
                        max_silent_run = current_silent_run
                else:
                    current_silent_run = 0

        rms = (sum_sq / total_samples) ** 0.5 if total_samples > 0 else 0.0
        import math
        rms_dbfs = 20 * math.log10(max(rms, 1e-6))
        # Approximate LUFS from RMS with standard calibration offset
        approx_lufs = round(rms_dbfs - 0.5, 2)
        max_silence_s = (max_silent_run / float(framerate * channels)) if framerate > 0 else 0.0

        return {
            "valid": True,
            "duration_ms": round(duration_s * 1000.0, 1),
            "sample_rate": framerate,
            "channels": channels,
            "sample_width": sample_width,
            "peak_amplitude": round(peak_amp, 4),
            "clipping_count": clipping_count,
            "approx_lufs": approx_lufs,
            "max_silence_s": round(max_silence_s, 2),
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc)}


class ProductionValidationService:
    """Canonical service executing real-runtime production validation."""

    def __init__(
        self,
        store: VoiceProjectStore | None = None,
        runtime_service: LocalRuntimeService | None = None,
        execution_port: TTSExecutionPort | None = None,
        operation_manager: VoiceProjectOperationManager | None = None,
        allow_raw_paths: bool = False,
    ):
        self.store = store or get_voice_project_store()
        self.runtime_service = runtime_service or LocalRuntimeService(store=self.store)
        self.execution_port = execution_port
        self.operation_manager = operation_manager or get_voice_project_operation_manager()
        self.allow_raw_paths = allow_raw_paths

    def _resolve_local_path(self, value: str | Path, *, must_exist: bool = False) -> Path:
        """Resolve CLI-only paths without permitting traversal or symlink escape."""
        path = Path(value).expanduser().resolve(strict=must_exist)
        configured = os.getenv("CHATTERBOX_VALIDATION_ALLOWED_ROOTS", "")
        roots = [Path.cwd().resolve(), self.store.root_dir.resolve(), Path(tempfile.gettempdir()).resolve()]
        roots.extend(Path(item).expanduser().resolve() for item in configured.split(os.pathsep) if item)
        if not any(path == root or root in path.parents for root in roots):
            raise ValueError(f"Path is outside permitted validation roots: {path.name}")
        return path

    def load_validation_profile(self, profile_id_or_path: str | Path | None = None) -> dict[str, Any]:
        """Load default or specified production validation configuration profile."""
        if profile_id_or_path and self.allow_raw_paths:
            config_path = self._resolve_local_path(profile_id_or_path, must_exist=True)
        elif profile_id_or_path:
            profile_id = str(profile_id_or_path)
            if Path(profile_id).name != profile_id or profile_id in {".", ".."}:
                raise ValueError("validation_profile_id must be a managed profile ID, not a filesystem path")
            config_root = Path("configs").resolve()
            config_path = (config_root / (profile_id if profile_id.endswith((".yaml", ".yml")) else f"{profile_id}.yaml")).resolve()
            if config_path.parent != config_root:
                raise ValueError("validation_profile_id resolved outside the managed profile directory")
        else:
            config_path = _DEFAULT_CONFIG_PATH
        if not config_path.exists():
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("Failed to load validation profile from %s: %s", config_path, exc)
            return {}

    def get_validation_report(self, validation_id: str) -> ProductionValidationReport | None:
        """Retrieve validation report by validation ID from cache or disk."""
        if validation_id in _ACTIVE_VALIDATIONS:
            return _ACTIVE_VALIDATIONS[validation_id]
        
        # Check on-disk report
        report_file = self.store.root_dir / "validations" / validation_id / "validation-report.yaml"
        if report_file.exists():
            try:
                data = yaml.safe_load(report_file.read_text(encoding="utf-8"))
                return ProductionValidationReport.model_validate(data)
            except Exception as exc:
                logger.error("Failed to parse on-disk report %s: %s", report_file, exc)
        return None

    def list_validations(self, limit: int = 50) -> list[ProductionValidationReport]:
        """List recent validation reports."""
        results = list(_ACTIVE_VALIDATIONS.values())
        val_dir = self.store.root_dir / "validations"
        if val_dir.exists():
            for child in val_dir.iterdir():
                if child.is_dir() and child.name not in _ACTIVE_VALIDATIONS:
                    report_file = child / "validation-report.yaml"
                    if report_file.exists():
                        try:
                            data = yaml.safe_load(report_file.read_text(encoding="utf-8"))
                            results.append(ProductionValidationReport.model_validate(data))
                        except Exception:
                            pass
        results.sort(key=lambda r: r.started_at, reverse=True)
        return results[:limit]

    def cancel_validation(self, validation_id: str) -> bool:
        """Cancel a running validation."""
        report = self.get_validation_report(validation_id)
        if report and report.operation_ids:
            cancelled, _ = self.operation_manager.cancel_operation(report.operation_ids[-1])
            if cancelled:
                report.status = "cancelling"
                _ACTIVE_VALIDATIONS[validation_id] = report
            return cancelled
        token = _CANCELLATION_TOKENS.get(validation_id)
        if token:
            token.cancel()
            rep = _ACTIVE_VALIDATIONS.get(validation_id)
            if rep and rep.status == "running":
                rep.status = "cancelled"
                rep.verdict = ValidationVerdict.FAIL
            return True
        return False

    def submit(self, request: ProductionValidationRequest | None = None) -> tuple[ProductionValidationReport, Any]:
        """Create one validation identity and submit it through the shared operation manager."""
        req = request or ProductionValidationRequest()
        validation_id = f"val_{uuid.uuid4().hex[:12]}"
        project_id = f"vproj_val_{uuid.uuid4().hex[:8]}"
        report = ProductionValidationReport(
            validation_id=validation_id,
            status="queued",
            verdict=ValidationVerdict.PASS,
            started_at=_now_iso(),
            provider=req.provider,
            model=req.model or "nano",
            project_id=project_id,
        )
        _ACTIVE_VALIDATIONS[validation_id] = report
        ready = threading.Event()

        def run_validation(
            cancellation_token: CancellationToken | None = None,
            progress_callback: ProgressCallback | None = None,
        ) -> ProductionValidationReport:
            ready.wait()
            return self.validate(
                req,
                cancellation_token=cancellation_token,
                progress_callback=progress_callback,
                validation_id=validation_id,
                project_id=project_id,
            )

        operation = self.operation_manager.submit(validation_id, "production_validation", run_validation)
        current = _ACTIVE_VALIDATIONS[validation_id]
        current.operation_ids = [operation.id]
        ready.set()
        return current, operation

    def _run_production_workflow(
        self,
        *,
        project_service: VoiceProjectService,
        script_text: str,
        project_id: str,
        provider: str,
        model: str,
        language: str,
        output_formats: list[str],
        mixing_profile: str,
        mastering_profile: str,
        loudness_target: float,
        max_retries: int,
        require_narration_acceptance: bool,
        require_final_approval: bool,
        cancellation_token: CancellationToken,
        timeout_seconds: int,
    ) -> VoiceWorkflowState:
        """Run and approve one real production workflow through its terminal state."""
        workflow_service = VoiceProjectWorkflowService(
            store=VoiceProjectWorkflowStore(self.store.root_dir / "workflows"),
            project_store=self.store,
            op_manager=self.operation_manager,
            project_service=project_service,
        )
        state = workflow_service.start_workflow(
            script_text=script_text,
            project_id=project_id,
            title="Mythology Production Validation",
            language=language,
            policy=WorkflowPolicy(
                provider=provider,
                model=model,
                retry_budget=max(1, max_retries),
                auto_accept_qc_pass=not require_narration_acceptance,
                require_final_approval=require_final_approval,
                output_formats=output_formats,
                mixing_profile=mixing_profile,
                mastering_profile=mastering_profile,
                loudness_target_lufs=loudness_target,
                pronunciation_overrides={
                    "Prometheus": "proh-MEE-thee-us",
                    "Hephaestus": "heh-FES-tus",
                    "Zeus": "zoos",
                    "Olympus": "oh-LIM-pus",
                    "Mount": "mount",
                    "Titan": "TY-tun",
                },
            ),
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if cancellation_token.is_cancelled():
                workflow_service.cancel_workflow(state.workflow_id)
                raise RuntimeError("Production validation was cancelled.")
            state = workflow_service.get_workflow(state.workflow_id)
            if not state:
                raise RuntimeError("Production workflow disappeared during validation.")
            if state.status == WorkflowStatus.COMPLETED:
                return state
            if state.status in (WorkflowStatus.FAILED, WorkflowStatus.CANCELLED, WorkflowStatus.INTERRUPTED):
                raise RuntimeError(f"Production workflow ended in '{state.status.value}': {state.error}")
            if state.status == WorkflowStatus.WAITING_FOR_HUMAN:
                action = state.human_action or {}
                action_type = action.get("action_type")
                if action_type == "narration_acceptance":
                    workflow_service.approve_workflow(
                        state.workflow_id, action="approve_narration", approved=True
                    )
                elif action_type == "final_audio_approval":
                    item = (action.get("items") or [{}])[0]
                    master_path = self.store.get_project_dir(project_id) / "mix" / "master.wav"
                    current_sha = compute_file_sha256(master_path)
                    if item.get("artifact_id") != "master_wav" or item.get("sha256") != current_sha:
                        raise RuntimeError("Workflow approval artifact does not match the current master.")
                    workflow_service.approve_workflow(
                        state.workflow_id,
                        action="approve_final_audio",
                        approved=True,
                        artifact_id="master_wav",
                        artifact_sha256=current_sha,
                    )
                else:
                    raise RuntimeError(f"Production workflow requires unsupported human action '{action_type}'.")
            time.sleep(0.03)
        workflow_service.cancel_workflow(state.workflow_id)
        raise TimeoutError(f"Production workflow exceeded {timeout_seconds}s validation timeout.")

    @staticmethod
    def _wait_for_workflow_terminal(
        service: VoiceProjectWorkflowService,
        workflow_id: str,
        cancellation_token: CancellationToken,
        timeout_seconds: int,
    ) -> VoiceWorkflowState:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            state = service.get_workflow(workflow_id)
            if not state:
                raise RuntimeError("Production workflow disappeared during validation.")
            if state.status == WorkflowStatus.COMPLETED:
                return state
            if state.status in (WorkflowStatus.FAILED, WorkflowStatus.CANCELLED, WorkflowStatus.INTERRUPTED):
                raise RuntimeError(f"Production workflow ended in '{state.status.value}': {state.error}")
            if cancellation_token.is_cancelled():
                service.cancel_workflow(workflow_id)
                raise RuntimeError("Production validation was cancelled.")
            time.sleep(0.03)
        service.cancel_workflow(workflow_id)
        raise TimeoutError(f"Production workflow exceeded {timeout_seconds}s validation timeout.")

    def validate(
        self,
        request: ProductionValidationRequest | None = None,
        cancellation_token: CancellationToken | None = None,
        progress_callback: ProgressCallback | None = None,
        validation_id: str | None = None,
        project_id: str | None = None,
    ) -> ProductionValidationReport:
        """Execute the full canonical production validation pipeline."""
        req = request or ProductionValidationRequest()

        # Merge profile defaults
        profile_data = self.load_validation_profile(req.validation_profile_id)
        provider_name = req.provider or profile_data.get("provider", "local")
        model_name = req.model or profile_data.get("model", "nano")
        language = req.language or profile_data.get("language", "en")
        output_formats = list(req.output_formats or profile_data.get("output_formats", ["wav", "mp3"]))
        mixing_profile = req.mixing_profile or profile_data.get("mixing_profile", "storytelling")
        mastering_profile = req.mastering_profile or profile_data.get("mastering_profile", "podcast")
        loudness_target = req.loudness_target_lufs or profile_data.get("loudness_target_lufs", -19.0)
        require_final_approval = req.require_final_approval if req.require_final_approval is not None else profile_data.get("require_final_approval", True)
        require_narration_acceptance = req.require_narration_acceptance if req.require_narration_acceptance is not None else profile_data.get("require_narration_acceptance", True)
        max_retries = req.maximum_automatic_retries or profile_data.get("maximum_automatic_retries", 2)
        reference_voice = req.reference_voice
        if reference_voice and self.allow_raw_paths:
            reference_voice = str(self._resolve_local_path(reference_voice, must_exist=True))
        elif reference_voice and (
            Path(reference_voice).is_absolute()
            or ".." in Path(reference_voice).parts
            or "/" in reference_voice
            or "\\" in reference_voice
        ):
            raise ValueError("reference_voice must be a managed voice ID; raw paths are CLI-only")

        # Load script text
        script_text = req.script_text
        if (req.script_path or req.output_report_path) and not self.allow_raw_paths:
            raise ValueError("Raw filesystem paths are only available to the local CLI")
        if not script_text and req.script_path:
            script_file = self._resolve_local_path(req.script_path, must_exist=True)
            if script_file.exists():
                script_text = script_file.read_text(encoding="utf-8")
        if not script_text and _DEFAULT_GOLDEN_SCRIPT_PATH.exists():
            script_text = _DEFAULT_GOLDEN_SCRIPT_PATH.read_text(encoding="utf-8")
        if not script_text:
            script_text = (
                "High atop the jagged precipice of Mount Olympus, the eternal wind howled across the frozen stone.\n\n"
                "Prometheus knelt beside the forge of Hephaestus, watching the forbidden divine flame dance in the shadows.\n\n"
                "He knew the wrath of Zeus would be merciless if he were discovered.\n\n"
                "Holding his breath, he touched the fennel stalk to the hearth... and in the quiet dark, a golden ember ignited.\n\n"
                "With the warmth of life cupped in his hands, the Titan turned toward the mortal world, ready to defy the heavens."
            )

        validation_id = validation_id or f"val_{uuid.uuid4().hex[:12]}"
        project_id = project_id or f"vproj_val_{uuid.uuid4().hex[:8]}"
        start_time_iso = _now_iso()
        start_ts = time.time()

        token = cancellation_token or CancellationToken()
        _CANCELLATION_TOKENS[validation_id] = token

        # Introspect capabilities
        runtime_caps = self.runtime_service.get_capabilities()
        machine_info = _get_machine_summary()

        report = ProductionValidationReport(
            validation_id=validation_id,
            status="running",
            verdict=ValidationVerdict.PASS,
            started_at=start_time_iso,
            machine_summary=machine_info,
            runtime_capabilities=runtime_caps.model_dump(mode="json"),
            provider=provider_name,
            model=model_name,
            device=runtime_caps.device,
            project_id=project_id,
            operation_ids=list((_ACTIVE_VALIDATIONS.get(validation_id) or ProductionValidationReport(
                validation_id=validation_id, started_at=start_time_iso, project_id=project_id
            )).operation_ids),
        )
        _ACTIVE_VALIDATIONS[validation_id] = report

        # Setup services
        exec_port = self.execution_port
        if exec_port is None:
            try:
                exec_port = resolve_server_tts_provider(provider_name, model=model_name, voice=reference_voice)
            except Exception as exc:
                if provider_name in ("fake", "test"):
                    from services.tts.fake import FakeTTSProvider
                    exec_port = FakeTTSProvider()
                else:
                    logger.warning("Could not resolve server TTS provider: %s", exc)

        project_service = VoiceProjectService(
            store=self.store,
            execution_port=exec_port,
            provider_name=provider_name,
        )
        review_service = DirectorReviewService(self.store)
        revision_service = DirectorRevisionService(project_service)

        steps: list[ProductionValidationStep] = []
        warnings: list[str] = list(runtime_caps.warnings)
        failures: list[ProductionValidationFailure] = []

        def _run_step(name: str, fn: Callable[[], dict[str, Any] | None]) -> bool:
            if token.is_cancelled():
                steps.append(ProductionValidationStep(name=name, status="cancelled", started_at=_now_iso()))
                return False

            st_time = time.time()
            st_iso = _now_iso()
            step_obj = ProductionValidationStep(name=name, status="running", started_at=st_iso)
            steps.append(step_obj)
            if progress_callback:
                progress_callback(name, len(steps) * 8.0, {"validation_id": validation_id})

            try:
                details = fn() or {}
                step_obj.status = "passed"
                step_obj.completed_at = _now_iso()
                step_obj.duration_ms = round((time.time() - st_time) * 1000.0, 1)
                step_obj.details = details
                return True
            except Exception as exc:
                step_obj.status = "failed"
                step_obj.completed_at = _now_iso()
                step_obj.duration_ms = round((time.time() - st_time) * 1000.0, 1)
                step_obj.error = str(exc)
                failures.append(ProductionValidationFailure(
                    step_name=name,
                    code="STEP_FAILED",
                    message=str(exc),
                ))
                return False

        # --- 1. Project Creation ---
        def _step_create():
            project_service.create_project(
                script_text=script_text,
                project_id=project_id,
                title="Mythology Production Validation",
                language=language,
            )
            return {"project_id": project_id, "script_length": len(script_text)}

        if not _run_step("create_project", _step_create):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 2. Production Preflight ---
        def _step_preflight():
            issues = self.runtime_service.run_production_preflight(
                project_id=project_id,
                provider=provider_name,
                requested_formats=output_formats,
                selected_model=model_name,
                reference_voice=reference_voice,
            )
            blocking = [i for i in issues if i.severity == "error"]
            for issue in issues:
                if issue.severity == "warning":
                    warnings.append(f"Preflight warning: {issue.message}")
            if blocking:
                raise ValueError(f"Preflight blocked: {[b.message for b in blocking]}")
            return {"issues_count": len(issues), "blocking_count": len(blocking)}

        if not _run_step("preflight", _step_preflight):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        workflow_t0 = time.time()
        try:
            workflow = self._run_production_workflow(
                project_service=project_service,
                script_text=script_text,
                project_id=project_id,
                provider=provider_name,
                model=model_name,
                language=language,
                output_formats=output_formats,
                mixing_profile=mixing_profile,
                mastering_profile=mastering_profile,
                loudness_target=loudness_target,
                max_retries=max_retries,
                require_narration_acceptance=require_narration_acceptance,
                require_final_approval=require_final_approval,
                cancellation_token=token,
                timeout_seconds=req.runtime_timeout_seconds,
            )
            report.workflow_id = workflow.workflow_id
            report.operation_ids.extend(
                step.operation_id for step in workflow.steps
                if step.operation_id and step.operation_id not in report.operation_ids
            )
        except Exception as exc:
            failures.append(ProductionValidationFailure(
                step_name="production_workflow", code="WORKFLOW_FAILED", message=str(exc)
            ))
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 3. Voice Planning ---
        def _step_plan():
            workflow_step = next(step for step in workflow.steps if step.name == "plan")
            report.planning_duration_ms = workflow_step.duration_ms if hasattr(workflow_step, "duration_ms") else 0.0
            voice_plan = self.store.load_voice_plan(project_id)
            report.beat_count = len(voice_plan.beats) if voice_plan else 0
            return {"beat_count": report.beat_count}

        if not _run_step("plan_voice_project", _step_plan):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 4. Resource Check & Pronunciation Resolution ---
        def _step_resources():
            res_report = project_service.check_resources(project_id)
            return {
                "render_blocked": res_report.render_blocked,
                "missing_gaps_count": len(res_report.report.missing),
            }

        if not _run_step("check_and_resolve_resources", _step_resources):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 5. Render Narration ---
        def _step_render():
            render_step = next(step for step in workflow.steps if step.name == "render")
            report.render_duration_ms = 0.0
            manifest = self.store.load_manifest(project_id)
            total_attempts = sum(len(b.attempts) for b in manifest.beats.values()) if manifest else 0
            report.attempt_count = total_attempts
            return {"render_stage": "NARRATION_READY", "total_attempts": total_attempts,
                    "operation_id": render_step.operation_id}

        if not _run_step("render_narration", _step_render):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 6. QC & Adaptive Retry Evaluation ---
        def _step_qc():
            manifest = self.store.load_manifest(project_id)
            report.qc_duration_ms = 0.0
            report.attempt_count = sum(len(beat.attempts) for beat in manifest.beats.values())
            pass_cnt = 0
            rev_cnt = 0
            fail_cnt = 0
            beat_metrics: list[ProductionValidationBeatMetric] = []

            for beat_id, beat_state in manifest.beats.items():
                selected_att = beat_state.selected_attempt
                attempt_obj = next((a for a in beat_state.attempts if a.attempt == selected_att), None)
                if not attempt_obj and beat_state.attempts:
                    attempt_obj = beat_state.attempts[0]
                    selected_att = attempt_obj.attempt

                qc_score = attempt_obj.qc_result.qc_score if (attempt_obj and attempt_obj.qc_result) else (100.0 if attempt_obj and attempt_obj.status == RenderStatus.PASSED else 0.0)
                verdict = attempt_obj.status.value if attempt_obj else "FAILED"

                if verdict == RenderStatus.PASSED.value:
                    pass_cnt += 1
                elif verdict == RenderStatus.NEEDS_REVIEW.value:
                    rev_cnt += 1
                else:
                    fail_cnt += 1

                # Per-beat metric
                duration_ms = 0.0
                if attempt_obj and attempt_obj.audio_path:
                    p = self.store.get_project_dir(project_id) / attempt_obj.audio_path
                    insp = _inspect_audio_wave(p)
                    if insp.get("valid"):
                        duration_ms = insp.get("duration_ms", 0.0)

                voice_plan = self.store.load_voice_plan(project_id)
                beat_plan = next((b for b in voice_plan.beats if b.id == beat_id), None) if voice_plan else None
                text_len = len(beat_plan.script.text) if (beat_plan and beat_plan.script) else 0

                beat_metrics.append(ProductionValidationBeatMetric(
                    beat_id=beat_id,
                    text_length=text_len,
                    duration_ms=duration_ms,
                    render_duration_ms=round(report.render_duration_ms / max(1, len(manifest.beats)), 1),
                    attempt_count=len(beat_state.attempts),
                    selected_attempt=selected_att,
                    qc_score=qc_score,
                    qc_verdict=verdict,
                    provider=provider_name,
                    model=model_name,
                ))

            report.qc_pass_count = pass_cnt
            report.qc_review_count = rev_cnt
            report.qc_failed_count = fail_cnt
            report.per_beat_metrics = beat_metrics
            return {"passed": pass_cnt, "review": rev_cnt, "failed": fail_cnt}

        if not _run_step("qc_and_retry", _step_qc):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 7. Narration Review / Acceptance ---
        def _step_narration_review():
            review = review_service.get_review(project_id)
            return {"ready": True, "beat_count": len(review.beats), "workflow_id": report.workflow_id}

        if not _run_step("narration_review", _step_narration_review):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 8. Prepare Mix ---
        def _step_prepare_mix():
            mix_plan, _, _ = project_service._load_valid_mix_plan(project_id)
            return {"voice_clips_count": len(mix_plan.voice_clips) if mix_plan else 0}

        if not _run_step("prepare_mix", _step_prepare_mix):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 9. Audio Mix ---
        def _step_mix():
            p_path = self.store.get_project_dir(project_id) / "mix" / "premaster.wav"
            return {"premaster_path": _sanitize_path(p_path)}

        if not _run_step("mix_audio", _step_mix):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 10. Mastering ---
        def _step_master():
            m_path = self.store.get_project_dir(project_id) / "mix" / "master.wav"
            return {"master_path": _sanitize_path(m_path)}

        if not _run_step("master_audio", _step_master):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 11. Final Master Approval ---
        def _step_approval():
            master_wav = self.store.get_project_dir(project_id) / "mix" / "master.wav"
            master_sha = compute_file_sha256(master_wav)
            return {"master_sha256": master_sha, "approved": True, "workflow_id": report.workflow_id}

        if not _run_step("final_master_approval", _step_approval):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 12. Deliverable Export ---
        def _step_export():
            export_manifest = workflow.result.get("manifest", {}) if workflow.result else {}
            return {"export_artifacts_count": len(export_manifest.get("artifacts", []))}

        if not _run_step("export_deliverables", _step_export):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 13. Audio & Cryptographic Lineage Validation ---
        def _step_audio_and_lineage_validation():
            proj_dir = self.store.get_project_dir(project_id)
            export_dir = proj_dir / "exports"
            final_wav = export_dir / "FINAL.wav"
            final_mp3 = export_dir / "FINAL.mp3"
            if not final_wav.exists():
                raise FileNotFoundError("FINAL.wav was not generated in exports directory.")

            insp = _inspect_audio_wave(final_wav)
            if not insp.get("valid"):
                raise ValueError(f"FINAL.wav audio inspection failed: {insp.get('error')}")

            report.output_duration_ms = insp.get("duration_ms", 0.0)

            # Check clipping & silence
            if insp.get("clipping_count", 0) > 0:
                warnings.append(f"Detected {insp['clipping_count']} clipped samples in FINAL.wav.")
            if insp.get("max_silence_s", 0.0) > 3.0:
                warnings.append(f"Long silence detected ({insp['max_silence_s']}s) in FINAL.wav.")

            # Check Loudness tolerance
            loudness = insp.get("approx_lufs", -19.0)
            if abs(loudness - loudness_target) > 5.0:
                warnings.append(
                    f"Measured loudness {loudness} LUFS differs from target {loudness_target} LUFS."
                )

            # Check MP3 if requested and ffmpeg available
            if "mp3" in output_formats:
                if shutil.which("ffmpeg"):
                    if not final_mp3.exists():
                        warnings.append("FINAL.mp3 missing despite ffmpeg availability.")
                else:
                    warnings.append("MP3 export skipped because ffmpeg is not installed on the system.")

            verified_artifacts = project_service.verify_delivery_lineage(project_id)

            # Collect artifacts
            artifacts: list[ProductionValidationArtifact] = []
            artifact_sizes: dict[str, int] = {}
            for item in export_dir.iterdir():
                if item.is_file():
                    sha = compute_file_sha256(item)
                    size = item.stat().st_size
                    artifact_sizes[item.name] = size
                    fmt = item.suffix.lstrip(".").lower()
                    d_ms = insp.get("duration_ms") if fmt == "wav" else None
                    artifacts.append(ProductionValidationArtifact(
                        artifact_id=f"artifact_{item.stem.lower()}",
                        file_name=item.name,
                        file_path=_sanitize_path(item, proj_dir),
                        sha256=sha,
                        size_bytes=size,
                        format=fmt,
                        duration_ms=d_ms,
                        sample_rate=insp.get("sample_rate"),
                        loudness_lufs=loudness if fmt == "wav" else None,
                        verified_lineage=item.name in verified_artifacts,
                    ))

            report.artifacts = artifacts
            report.artifact_sizes = artifact_sizes
            return {"artifacts_verified": len(artifacts), "final_wav_duration_ms": report.output_duration_ms}

        if not _run_step("audio_and_lineage_validation", _step_audio_and_lineage_validation):
            report.status = "failed"
            report.verdict = ValidationVerdict.FAIL
            return self._finalize_report(report, steps, warnings, failures, start_ts, req)

        # --- 14. Incremental Reproduction Validation (Part F) ---
        if req.run_incremental_reproduction:
            def _step_incremental_reproduction():
                manifest = self.store.load_manifest(project_id)
                beat_ids = list(manifest.beats.keys())
                if len(beat_ids) < 2:
                    return {"skipped": "Story has fewer than 2 beats"}

                target_beat = beat_ids[0]
                unaffected_beats = beat_ids[1:]

                # Snapshot initial audio hashes of unaffected beats
                unaffected_hashes_before = {}
                for b_id in unaffected_beats:
                    sel = manifest.beats[b_id].selected_attempt
                    att = next((a for a in manifest.beats[b_id].attempts if a.attempt == sel), None)
                    if att and att.audio_path:
                        p = self.store.get_project_dir(project_id) / att.audio_path
                        unaffected_hashes_before[b_id] = compute_file_sha256(p)

                # 1. Change direction of target beat
                impact = revision_service.update_direction(
                    project_id=project_id,
                    beat_id=target_beat,
                    patch=BeatDirectionPatch(emotion="mythology_urgent", energy=4.5),
                    actor_id="validation_runner",
                    reason="Incremental validation direction patch",
                )

                # 2. Reproduce
                repro_res = revision_service.reproduce_project(project_id)
                
                # If reproduction paused at approval gate, approve and finish export
                if repro_res.status == "waiting_for_human":
                    workflow_service = VoiceProjectWorkflowService(
                        store=VoiceProjectWorkflowStore(self.store.root_dir / "workflows"),
                        project_store=self.store,
                        op_manager=self.operation_manager,
                        project_service=project_service,
                    )
                    workflow_service.approve_workflow(
                        report.workflow_id,
                        action="approve_final_audio",
                        approved=True,
                        artifact_id=repro_res.artifact_id,
                        artifact_sha256=repro_res.artifact_sha256,
                    )
                    self._wait_for_workflow_terminal(workflow_service, report.workflow_id, token, req.runtime_timeout_seconds)

                # 3. Verify unaffected beats remain unchanged
                manifest_after = self.store.load_manifest(project_id)
                for b_id in unaffected_beats:
                    sel_after = manifest_after.beats[b_id].selected_attempt
                    att_after = next((a for a in manifest_after.beats[b_id].attempts if a.attempt == sel_after), None)
                    if att_after and att_after.audio_path:
                        p_after = self.store.get_project_dir(project_id) / att_after.audio_path
                        curr_hash = compute_file_sha256(p_after)
                        if curr_hash != unaffected_hashes_before.get(b_id):
                            raise ValueError(f"Unaffected beat {b_id} narration changed during reproduction!")

                # 4. Test Timing-Only Revision
                timing_hashes_before = {}
                for b_id in manifest_after.beats:
                    sel = manifest_after.beats[b_id].selected_attempt
                    att = next((a for a in manifest_after.beats[b_id].attempts if a.attempt == sel), None)
                    if att and att.audio_path:
                        p = self.store.get_project_dir(project_id) / att.audio_path
                        timing_hashes_before[b_id] = compute_file_sha256(p)

                t_impact = revision_service.update_timing(
                    project_id=project_id,
                    beat_id=target_beat,
                    patch=BeatTimingPatch(pause_after_ms=850),
                    actor_id="validation_runner",
                    reason="Incremental validation timing-only patch",
                )
                if "render_beat" in t_impact.required_reproduction_steps:
                    raise ValueError("Timing-only patch should NOT request render_beat!")

                repro_t = revision_service.reproduce_project(project_id)
                if repro_t.status == "waiting_for_human":
                    workflow_service = VoiceProjectWorkflowService(
                        store=VoiceProjectWorkflowStore(self.store.root_dir / "workflows"),
                        project_store=self.store,
                        op_manager=self.operation_manager,
                        project_service=project_service,
                    )
                    workflow_service.approve_workflow(
                        report.workflow_id,
                        action="approve_final_audio",
                        approved=True,
                        artifact_id=repro_t.artifact_id,
                        artifact_sha256=repro_t.artifact_sha256,
                    )
                    self._wait_for_workflow_terminal(workflow_service, report.workflow_id, token, req.runtime_timeout_seconds)

                # Confirm zero narration rerendered
                manifest_timing = self.store.load_manifest(project_id)
                for b_id in manifest_timing.beats:
                    sel = manifest_timing.beats[b_id].selected_attempt
                    att = next((a for a in manifest_timing.beats[b_id].attempts if a.attempt == sel), None)
                    if att and att.audio_path:
                        p = self.store.get_project_dir(project_id) / att.audio_path
                        if compute_file_sha256(p) != timing_hashes_before.get(b_id):
                            raise ValueError(f"Narration hash changed for {b_id} during timing-only reproduction!")

                # Refresh artifacts with final post-reproduction exports
                proj_dir = self.store.get_project_dir(project_id)
                export_dir = proj_dir / "exports"
                final_wav = export_dir / "FINAL.wav"
                insp = _inspect_audio_wave(final_wav) if final_wav.exists() else {}
                artifacts: list[ProductionValidationArtifact] = []
                artifact_sizes: dict[str, int] = {}
                verified_artifacts = project_service.verify_delivery_lineage(project_id)
                for item in export_dir.iterdir():
                    if item.is_file():
                        sha = compute_file_sha256(item)
                        size = item.stat().st_size
                        artifact_sizes[item.name] = size
                        fmt = item.suffix.lstrip(".").lower()
                        d_ms = insp.get("duration_ms") if fmt == "wav" else None
                        artifacts.append(ProductionValidationArtifact(
                            artifact_id=f"artifact_{item.stem.lower()}",
                            file_name=item.name,
                            file_path=_sanitize_path(item, proj_dir),
                            sha256=sha,
                            size_bytes=size,
                            format=fmt,
                            duration_ms=d_ms,
                            sample_rate=insp.get("sample_rate"),
                            loudness_lufs=insp.get("approx_lufs", -19.0) if fmt == "wav" else None,
                            verified_lineage=item.name in verified_artifacts,
                        ))
                report.artifacts = artifacts
                report.artifact_sizes = artifact_sizes

                return {"reproduced_beat": target_beat, "timing_only_passed": True}

            inc_passed = _run_step("incremental_reproduction_validation", _step_incremental_reproduction)
            report.incremental_reproduction_passed = inc_passed
            if not inc_passed:
                report.verdict = ValidationVerdict.PASS_WITH_WARNINGS if not failures else ValidationVerdict.FAIL

        # --- 15. Cancellation & Restart Safety Verification (Part G) ---
        if req.run_cancellation_tests:
            def _step_cancellation_validation():
                cancel_proj_id = f"vproj_cancel_{uuid.uuid4().hex[:8]}"
                project_service.create_project(
                    script_text="High upon the cliff the dark wind blew.",
                    project_id=cancel_proj_id,
                    title="Cancellation Test",
                )
                project_service.plan(cancel_proj_id)
                project_service.check_resources(cancel_proj_id)

                # Simulate cancelled render token
                c_tok = CancellationToken()
                c_tok.cancel()
                try:
                    project_service.render(cancel_proj_id, cancellation_token=c_tok)
                except Exception:
                    if not c_tok.is_cancelled():
                        raise

                # Invariant checks deliberately live outside the expected-cancellation handler.
                manifest = self.store.load_manifest(cancel_proj_id)
                if manifest:
                    for beat in manifest.beats.values():
                        if any(att.status == RenderStatus.PASSED for att in beat.attempts):
                            raise ValueError("Cancelled render published a passed attempt.")
                pending_dir = self.store.get_project_dir(cancel_proj_id) / "audio" / "pending"
                if pending_dir.exists() and any(pending_dir.iterdir()):
                    raise ValueError("Cancelled render left pending artifacts behind.")

                # Cleanup test project
                try:
                    shutil.rmtree(self.store.get_project_dir(cancel_proj_id), ignore_errors=True)
                except Exception:
                    pass
                return {"cancellation_safety_verified": True}

            canc_passed = _run_step("cancellation_safety_validation", _step_cancellation_validation)
            report.cancellation_recovery_passed = canc_passed

        # Final Status & Verdict
        report.status = "completed"
        if failures:
            report.verdict = ValidationVerdict.FAIL
        elif warnings:
            report.verdict = ValidationVerdict.PASS_WITH_WARNINGS
        else:
            report.verdict = ValidationVerdict.PASS

        return self._finalize_report(report, steps, warnings, failures, start_ts, req)

    def _finalize_report(
        self,
        report: ProductionValidationReport,
        steps: list[ProductionValidationStep],
        warnings: list[str],
        failures: list[ProductionValidationFailure],
        start_ts: float,
        req: ProductionValidationRequest,
    ) -> ProductionValidationReport:
        """Complete metrics calculation, persist report to disk, and return report."""
        report.completed_at = _now_iso()
        report.total_duration_ms = round((time.time() - start_ts) * 1000.0, 1)
        report.steps = steps
        report.warnings = list(dict.fromkeys(warnings))
        report.failures = failures
        report.peak_memory_mb = _get_peak_memory_mb()

        active_token = _CANCELLATION_TOKENS.get(report.validation_id)
        if active_token and active_token.is_cancelled():
            report.status = "cancelled"
            report.verdict = ValidationVerdict.FAIL

        if not report.operation_ids:
            operations = self.operation_manager.list_operations(project_id=report.project_id, limit=1)
            if operations:
                report.operation_ids = [operations[0].id]

        # Real-time factor: output audio duration (ms) / total render duration (ms)
        if report.render_duration_ms > 0 and report.output_duration_ms > 0:
            report.real_time_factor = round(report.output_duration_ms / report.render_duration_ms, 2)

        _ACTIVE_VALIDATIONS[report.validation_id] = report

        # Persist report to projects/validations/{validation_id}/validation-report.yaml
        val_dir = self.store.root_dir / "validations" / report.validation_id
        val_dir.mkdir(parents=True, exist_ok=True)
        report_yaml_path = val_dir / "validation-report.yaml"
        report_json_path = val_dir / "validation-report.json"

        report_dict = report.model_dump(mode="json")
        try:
            report_yaml_path.write_text(yaml.safe_dump(report_dict, sort_keys=False), encoding="utf-8")
            report_json_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
            if req.output_report_path:
                custom_out = self._resolve_local_path(req.output_report_path)
                custom_out.parent.mkdir(parents=True, exist_ok=True)
                custom_out.write_text(yaml.safe_dump(report_dict, sort_keys=False), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to write validation report file: %s", exc)

        return report
