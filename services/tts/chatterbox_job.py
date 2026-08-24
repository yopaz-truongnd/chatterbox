"""Chatterbox In-Process Job TTS Provider Adapter (Phase 10A & 10B).

Provides direct in-memory integration with JobManager when running inside the FastAPI server process:
- Uses JobExecutionGateway interface to decouple from global singletons.
- Avoids HTTP localhost network loopback and avoids duplicate model loading.
- Normalizes multilingual language tags (language_id) and applies pronunciation dictionary.
- Cancels orphan jobs upon timeout to prevent resource leak and repeat synthesis.
- Protects against self-deadlock when invoked on the JobManager worker thread via gateway.execute_sync().
- Supports progress callbacks and cancellation tokens.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import threading
import time
from typing import Any, Protocol, runtime_checkable
import wave

from services.narration_planner import apply_pronunciation_dict
from services.render_models import (
    ProviderCapabilities,
    ProviderErrorType,
    ProviderHealth,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.base import CancellationToken, ProgressCallback, TTSProvider
from services.tts.chatterbox_http import normalize_language_id
from services.tts.gemini import validate_generated_wave

logger = logging.getLogger(__name__)


@runtime_checkable
class JobExecutionGateway(Protocol):
    """Execution gateway protocol wrapping JobManager."""

    def submit_job(self, model: str, params: dict[str, Any], input_paths: list[str]) -> Any:
        """Submit an inference job to JobManager."""
        ...

    def get_job(self, job_id: str) -> Any:
        """Retrieve job status by ID."""
        ...

    def cancel_job(self, job_id: str) -> tuple[bool, str]:
        """Cancel a pending or running job."""
        ...

    def execute_sync(
        self,
        model: str,
        params: dict[str, Any],
        output_path: Path | str,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, str | None]:
        """Execute model inference synchronously within JobManager execution owner."""
        ...

    def is_worker_thread(self) -> bool:
        """Check if current thread is the JobManager audio worker thread."""
        ...


class DefaultJobManagerGateway:
    """Gateway adapter delegating execution exclusively to an injected JobManager."""

    def __init__(self, job_manager: Any):
        if job_manager is None:
            raise ValueError("DefaultJobManagerGateway requires an injected JobManager instance")
        self._jm = job_manager

    def submit_job(self, model: str, params: dict[str, Any], input_paths: list[str]) -> Any:
        return self._jm.submit_job(model, params, input_paths)

    def get_job(self, job_id: str) -> Any:
        return self._jm.get_job(job_id)

    def cancel_job(self, job_id: str) -> tuple[bool, str]:
        return self._jm.cancel_job(job_id)

    def execute_sync(
        self,
        model: str,
        params: dict[str, Any],
        output_path: Path | str,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[bool, str | None]:
        if hasattr(self._jm, "execute_sync"):
            def _cb(phase: str, pct: float, msg: str) -> None:
                if progress_callback:
                    progress_callback(phase, pct, {"message": msg})
            return self._jm.execute_sync(model, params, Path(output_path), _cb)
        return False, "JobManager does not implement execute_sync"

    def is_worker_thread(self) -> bool:
        worker_th = getattr(self._jm, "_worker_thread", None)
        return worker_th is not None and worker_th == threading.current_thread()


class ChatterboxJobProvider(TTSProvider):
    """In-process Chatterbox provider communicating directly with JobManager via gateway."""

    def __init__(
        self,
        gateway: JobExecutionGateway,
        default_model: str = "nano",
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 0.1,
    ):
        if gateway is None:
            raise ValueError("ChatterboxJobProvider requires an injected JobExecutionGateway")
        self.gateway = gateway
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def healthcheck(self) -> ProviderHealth:
        try:
            return ProviderHealth(
                available=True,
                configured=True,
                connectivity_checked=True,
                provider_name="chatterbox-job",
                message="In-process Chatterbox JobProvider is ready",
                details={"default_model": self.default_model},
            )
        except Exception as exc:
            return ProviderHealth(
                available=False,
                configured=True,
                connectivity_checked=True,
                provider_name="chatterbox-job",
                message=f"Failed to check JobManager health: {exc}",
            )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_emotion=False,
            supports_pace=False,
            supports_pronunciation=True,
            supports_director_notes=False,
            supports_ssml=False,
            supports_seed=True,
        )

    def render(
        self,
        request: TTSRenderRequest,
        output_dir: str | Path,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSRenderResult:
        """Render a single StoryBeat using in-process JobManager via JobExecutionGateway."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()

        if cancellation_token and cancellation_token.is_cancelled():
            return TTSRenderResult(
                success=False,
                provider="chatterbox-job",
                model=self.default_model,
                audio_path=None,
                error="Render cancelled before submission",
                error_type=ProviderErrorType.TIMEOUT,
                retryable=False,
            )

        # 1. Prepare parameters
        synth_text = request.text
        if request.pronunciation:
            synth_text = apply_pronunciation_dict(request.text, request.pronunciation)

        params: dict[str, Any] = {
            "text": synth_text,
            "project_id": request.project_id,
            "beat_id": request.beat_id,
        }

        if request.energy is not None:
            params["temperature"] = round(0.4 + (request.energy / 5.0) * 0.5, 2)
        if request.voice_profile and not request.voice_profile.startswith("mythology_"):
            params["character_id"] = request.voice_profile

        # If multilingual model, attach language_id
        if self.default_model == "multilingual":
            params["language_id"] = normalize_language_id(request.language)

        temp_wav_path = output_dir / f"attempt_{request.attempt_id:02d}_inproc_tmp.wav"
        final_wav_path = output_dir / f"attempt_{request.attempt_id:02d}.wav"

        # 2. Check for self-deadlock if called on the JobManager worker thread
        if hasattr(self.gateway, "is_worker_thread") and self.gateway.is_worker_thread():
            ok, err_msg = self.gateway.execute_sync(
                model=self.default_model,
                params=params,
                output_path=temp_wav_path,
                progress_callback=progress_callback,
                cancellation_token=cancellation_token,
            )
            if not ok or not temp_wav_path.exists():
                temp_wav_path.unlink(missing_ok=True)
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    error=f"Gateway synchronous execution failed: {err_msg}",
                    error_type=ProviderErrorType.SERVER_ERROR,
                    retryable=True,
                )

            is_valid, duration, s_rate, channels, val_err = validate_generated_wave(temp_wav_path)
            if not is_valid:
                temp_wav_path.unlink(missing_ok=True)
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    error=f"Generated audio validation failed: {val_err}",
                    error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                    retryable=True,
                )

            temp_wav_path.replace(final_wav_path)
            return TTSRenderResult(
                success=True,
                provider="chatterbox-job",
                model=self.default_model,
                audio_path=str(final_wav_path),
                duration=duration,
                sample_rate=s_rate,
                channels=channels,
                provider_request_id="sync_gateway",
                raw_metadata={"latency_seconds": round(time.time() - start_time, 3), "in_process_sync": True},
            )

        # 3. Submit Job to Gateway
        try:
            job = self.gateway.submit_job(self.default_model, params, [])
            job_id = getattr(job, "id", None) or getattr(job, "job_id", "unknown_job")
        except Exception as exc:
            return TTSRenderResult(
                success=False,
                provider="chatterbox-job",
                model=self.default_model,
                audio_path=None,
                error=f"Failed to submit in-process job: {exc}",
                error_type=ProviderErrorType.SERVER_ERROR,
                retryable=True,
            )

        # 4. Poll Job via Gateway
        poll_start = time.time()
        completed_job = None

        while (time.time() - poll_start) < self.timeout_seconds:
            if cancellation_token and cancellation_token.is_cancelled():
                self.gateway.cancel_job(job_id)
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    error="Render cancelled by caller",
                    error_type=ProviderErrorType.TIMEOUT,
                    retryable=False,
                )

            curr_job = self.gateway.get_job(job_id)
            if curr_job:
                status = getattr(curr_job, "status", "unknown")
                phase = getattr(curr_job, "phase", status)
                progress = float(getattr(curr_job, "progress_percent", 0.0) or 0.0)

                if progress_callback:
                    progress_callback(phase, progress, {"job_id": job_id, "status": status})

                if status in ("completed", "succeeded"):
                    completed_job = curr_job
                    break
                if status in ("failed", "error"):
                    return TTSRenderResult(
                        success=False,
                        provider="chatterbox-job",
                        model=self.default_model,
                        audio_path=None,
                        error=getattr(curr_job, "error", "In-process job failed"),
                        error_type=ProviderErrorType.SERVER_ERROR,
                        retryable=True,
                    )
                if status == "cancelled":
                    return TTSRenderResult(
                        success=False,
                        provider="chatterbox-job",
                        model=self.default_model,
                        audio_path=None,
                        error="In-process job was cancelled",
                        error_type=ProviderErrorType.TIMEOUT,
                        retryable=False,
                    )

            time.sleep(self.poll_interval_seconds)

        if not completed_job:
            # Timeout reached: best-effort cancel orphan job via gateway
            try:
                self.gateway.cancel_job(job_id)
            except Exception:
                pass

            return TTSRenderResult(
                success=False,
                provider="chatterbox-job",
                model=self.default_model,
                audio_path=None,
                error=f"In-process job {job_id} timed out after {self.timeout_seconds}s",
                error_type=ProviderErrorType.TIMEOUT,
                retryable=True,
            )

        # 5. Retrieve audio output path from completed job
        src_audio_path = getattr(completed_job, "output_path", None)
        if not src_audio_path or not Path(src_audio_path).exists():
            return TTSRenderResult(
                success=False,
                provider="chatterbox-job",
                model=self.default_model,
                audio_path=None,
                error=f"Job completed but output audio was not found at {src_audio_path}",
                error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                retryable=True,
            )

        # Copy to project attempt destination
        shutil.copyfile(Path(src_audio_path), final_wav_path)

        # Validate audio wave
        is_valid, duration, sample_rate, channels, val_err = validate_generated_wave(final_wav_path)
        if not is_valid:
            final_wav_path.unlink(missing_ok=True)
            return TTSRenderResult(
                success=False,
                provider="chatterbox-job",
                model=self.default_model,
                audio_path=None,
                error=f"Generated audio validation failed: {val_err}",
                error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                retryable=True,
            )

        latency = round(time.time() - start_time, 3)
        return TTSRenderResult(
            success=True,
            provider="chatterbox-job",
            model=self.default_model,
            audio_path=str(final_wav_path),
            duration=duration,
            sample_rate=sample_rate,
            channels=channels,
            provider_request_id=job_id,
            raw_metadata={"latency_seconds": latency},
        )
