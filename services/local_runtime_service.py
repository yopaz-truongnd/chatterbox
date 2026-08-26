"""Local Runtime Service (Phase 17).

Provides two responsibilities without loading models:
  1. get_capabilities() — Inspect actual runtime state (JobManager, ModelRuntime,
     disk cache) and return a typed LocalRuntimeCapabilities snapshot.
  2. run_production_preflight() — Validate all preconditions before starting a
     workflow. Returns a list of PreflightIssue objects (empty = all clear).

Design constraints:
- NEVER makes HTTP requests to 127.0.0.1 or any loopback address.
- NEVER loads a model as a side-effect of introspection.
- Business logic lives here; the router and MCP adapter are thin adapters.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from services.local_runtime_models import LocalRuntimeCapabilities, PreflightIssue
from services.model_registry import (
    MODEL_REGISTRY,
    is_model_cached,
    is_multilingual_cached,
)

logger = logging.getLogger(__name__)

# Minimum free disk space to warn about (bytes)
_DISK_WARN_BYTES = 500 * 1024 * 1024  # 500 MB


def _get_job_manager() -> Any | None:
    """Return the process-wide JobManager instance without importing at module load time."""
    try:
        import api_app  # type: ignore[import]
        return getattr(api_app, "job_manager", None)
    except Exception:
        return None


def _get_model_runtime() -> Any | None:
    """Return the global ModelRuntime without triggering model loading."""
    try:
        from services.model_runtime import model_runtime
        return model_runtime
    except Exception:
        return None


class LocalRuntimeService:
    """Stateless service exposing runtime capability inspection and production preflight."""

    # ------------------------------------------------------------------ #
    # 1. Capabilities                                                       #
    # ------------------------------------------------------------------ #

    def get_capabilities(self) -> LocalRuntimeCapabilities:
        """Inspect actual runtime state without loading models.

        Reads from the live JobManager singleton and ModelRuntime cache; never
        performs inference or network I/O.
        """
        warnings: list[str] = []

        # --- JobManager availability ---
        jm = _get_job_manager()
        available = jm is not None

        if not available:
            warnings.append(
                "JobManager is not running. Start the FastAPI server to enable local TTS."
            )

        # --- ModelRuntime inspection ---
        runtime = _get_model_runtime()
        loaded_models: list[str] = []
        device = "cpu"
        memory_estimate_mb: float | None = None

        if runtime is not None:
            try:
                active = runtime.active_model_name
                if active:
                    loaded_models = [active]
                device = getattr(runtime, "device", "cpu") or "cpu"

                # Attempt memory estimate (CUDA only)
                try:
                    import torch
                    if torch.cuda.is_available() and str(device).startswith("cuda"):
                        reserved = torch.cuda.memory_reserved(device)
                        memory_estimate_mb = round(reserved / (1024 * 1024), 1)
                except Exception:
                    pass
            except Exception as exc:
                logger.debug("Could not inspect ModelRuntime: %s", exc)

        # --- Disk cache inspection ---
        models_dir = Path(os.environ.get("HF_HUB_CACHE", "models"))
        cached_models: list[str] = []
        for model_id in MODEL_REGISTRY:
            if is_model_cached(model_id, models_dir):
                cached_models.append(model_id)

        # --- Language support ---
        supported_languages = ["en"]
        if "multilingual" in cached_models:
            # Multilingual model supports 23+ languages; report common set
            supported_languages = [
                "en", "zh", "ja", "ko", "fr", "de", "es", "pt", "it",
                "nl", "pl", "ru", "tr", "ar", "vi", "th", "id", "hi",
                "cs", "ro", "hu", "uk", "el",
            ]

        # --- Voice modes ---
        supported_voice_modes = ["tts"]
        if "voice-conversion" in cached_models:
            supported_voice_modes.append("voice_clone")

        # --- Output formats ---
        supported_output_formats = ["wav"]
        if shutil.which("ffmpeg"):
            supported_output_formats += ["mp3", "ogg", "flac"]

        # --- Concurrent job capacity ---
        max_concurrent_jobs = 1
        if jm is not None:
            try:
                max_concurrent_jobs = getattr(jm, "max_workers", 1) or 1
            except Exception:
                pass

        # --- GPU warnings ---
        try:
            import torch
            if not torch.cuda.is_available() and str(device) not in ("mps",):
                warnings.append(
                    "No GPU detected. Running on CPU — inference will be significantly slower."
                )
        except Exception:
            pass

        return LocalRuntimeCapabilities(
            available=available,
            loaded_models=loaded_models,
            cached_models=cached_models,
            supported_languages=supported_languages,
            supported_voice_modes=supported_voice_modes,
            device=device,
            memory_estimate_mb=memory_estimate_mb,
            max_concurrent_jobs=max_concurrent_jobs,
            supported_output_formats=supported_output_formats,
            warnings=warnings,
        )

    # ------------------------------------------------------------------ #
    # 2. Production Preflight                                              #
    # ------------------------------------------------------------------ #

    def run_production_preflight(
        self,
        project_id: str,
        provider: str = "local",
        requested_formats: list[str] | None = None,
    ) -> list[PreflightIssue]:
        """Check all preconditions before starting a production workflow.

        Returns a list of PreflightIssue objects. An empty list means all checks
        passed. Issues with severity='error' must be resolved before production
        can proceed; 'warning' issues are advisory.

        Checks performed (in order):
          1. Project directory exists
          2. Project output directory is writable
          3. ffmpeg availability when non-WAV formats are requested
          4. Sufficient free disk space
          5. At least one model checkpoint cached on disk
          6. Provider-specific availability
          7. JobManager is accepting jobs (for 'local' provider)
        """
        issues: list[PreflightIssue] = []
        requested_formats = [f.lower() for f in (requested_formats or [])]

        # 1. Project directory existence
        from services.voice_project_dependencies import get_voice_project_store
        try:
            store = get_voice_project_store()
            if not store.project_exists(project_id):
                issues.append(PreflightIssue(
                    severity="error",
                    code="PROJECT_NOT_FOUND",
                    message=f"Voice project '{project_id}' does not exist.",
                    field="project_id",
                ))
                # Cannot continue further checks without the project
                return issues
        except Exception as exc:
            issues.append(PreflightIssue(
                severity="error",
                code="PROJECT_STORE_ERROR",
                message=f"Cannot access project store: {exc}",
                field="project_id",
            ))
            return issues

        # 2. Output directory writability
        try:
            project_dir = store.get_project_dir(project_id)
            output_dir = project_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)

            test_file = output_dir / ".preflight_write_test"
            try:
                test_file.write_bytes(b"")
                test_file.unlink(missing_ok=True)
            except OSError:
                issues.append(PreflightIssue(
                    severity="error",
                    code="OUTPUT_DIR_NOT_WRITABLE",
                    message=f"Output directory '{output_dir}' is not writable.",
                    field="output_dir",
                ))
        except Exception as exc:
            issues.append(PreflightIssue(
                severity="error",
                code="OUTPUT_DIR_ERROR",
                message=f"Cannot create or access output directory: {exc}",
                field="output_dir",
            ))

        # 3. ffmpeg check for non-WAV formats
        non_wav_formats = [f for f in requested_formats if f != "wav"]
        if non_wav_formats:
            if not shutil.which("ffmpeg"):
                issues.append(PreflightIssue(
                    severity="error",
                    code="FFMPEG_MISSING",
                    message=(
                        f"Requested output format(s) {non_wav_formats} require ffmpeg, "
                        "but ffmpeg was not found on PATH. Install ffmpeg or request 'wav' only."
                    ),
                    field="requested_formats",
                ))

        # 4. Disk space check
        try:
            check_path = store.get_project_dir(project_id)
            stat = shutil.disk_usage(str(check_path))
            if stat.free < _DISK_WARN_BYTES:
                free_mb = round(stat.free / (1024 * 1024), 1)
                issues.append(PreflightIssue(
                    severity="warning",
                    code="LOW_DISK_SPACE",
                    message=(
                        f"Only {free_mb} MB of free disk space available on project volume. "
                        "Audio render may fail if disk fills up during production."
                    ),
                    field=None,
                ))
        except Exception:
            pass  # disk check is advisory; don't block on failure

        # 5. Model checkpoint presence
        models_dir = Path(os.environ.get("HF_HUB_CACHE", "models"))
        cached = [m for m in MODEL_REGISTRY if is_model_cached(m, models_dir)]
        if not cached:
            issues.append(PreflightIssue(
                severity="error",
                code="NO_MODELS_CACHED",
                message=(
                    "No model checkpoints found in the local models/ directory. "
                    "Download at least one model (e.g. 'nano') before running production."
                ),
                field=None,
            ))

        # 6. Provider-specific checks
        normalized_provider = (provider or "local").lower().strip()

        if normalized_provider in ("local", "chatterbox-job", "in-process", "job"):
            # 7. JobManager availability
            jm = _get_job_manager()
            if jm is None:
                issues.append(PreflightIssue(
                    severity="error",
                    code="JOB_MANAGER_UNAVAILABLE",
                    message=(
                        "The local TTS JobManager is not running. "
                        "Start the FastAPI server before launching production."
                    ),
                    field="provider",
                ))
            else:
                # Check that JobManager is accepting (not shut down)
                try:
                    is_alive = getattr(jm, "_running", True)
                    if is_alive is False:
                        issues.append(PreflightIssue(
                            severity="error",
                            code="JOB_MANAGER_NOT_ACCEPTING",
                            message="JobManager is present but no longer accepting jobs (shutdown in progress).",
                            field="provider",
                        ))
                except Exception:
                    pass

        elif normalized_provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                issues.append(PreflightIssue(
                    severity="error",
                    code="GEMINI_API_KEY_MISSING",
                    message=(
                        "Provider 'gemini' requires GEMINI_API_KEY or GOOGLE_API_KEY environment variable."
                    ),
                    field="provider",
                ))

        elif normalized_provider not in ("fake", "fake-tts", "test"):
            issues.append(PreflightIssue(
                severity="error",
                code="UNKNOWN_PROVIDER",
                message=f"Unknown TTS provider '{provider}'. Supported: 'local', 'gemini', 'fake'.",
                field="provider",
            ))

        return issues
