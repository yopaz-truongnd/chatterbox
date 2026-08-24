"""Chatterbox In-Process Job TTS Provider Adapter (Phase 10A & 10B).

Provides direct in-memory integration with JobManager when running inside the FastAPI server process:
- Uses JobExecutionGateway interface to decouple from global singletons.
- Avoids HTTP localhost network loopback and avoids duplicate model loading.
- Normalizes multilingual language tags (language_id) and applies pronunciation dictionary.
- Cancels orphan jobs upon timeout to prevent resource leak and repeat synthesis.
- Protects against self-deadlock when invoked in-process.
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


class DefaultJobManagerGateway:
    """Default gateway adapter wrapping api_app.job_manager."""

    def __init__(self, job_manager: Any = None):
        self._jm = job_manager

    def _get_jm(self) -> Any:
        if self._jm is not None:
            return self._jm
        try:
            import api_app
            return getattr(api_app, "job_manager", None)
        except Exception:
            return None

    def submit_job(self, model: str, params: dict[str, Any], input_paths: list[str]) -> Any:
        jm = self._get_jm()
        if jm is None:
            raise RuntimeError("In-process JobManager is not available")
        return jm.submit_job(model, params, input_paths)

    def get_job(self, job_id: str) -> Any:
        jm = self._get_jm()
        if jm is None:
            return None
        return jm.get_job(job_id)

    def cancel_job(self, job_id: str) -> tuple[bool, str]:
        jm = self._get_jm()
        if jm is None:
            return False, "JobManager is not available"
        return jm.cancel_job(job_id)


class ChatterboxJobProvider(TTSProvider):
    """In-process Chatterbox provider communicating directly with JobManager via gateway."""

    def __init__(
        self,
        gateway: JobExecutionGateway | None = None,
        default_model: str = "nano",
        timeout_seconds: float = 300.0,
        poll_interval_seconds: float = 0.1,
    ):
        self.gateway = gateway or DefaultJobManagerGateway()
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def healthcheck(self) -> ProviderHealth:
        try:
            if hasattr(self.gateway, "_get_jm"):
                jm = self.gateway._get_jm()
                if jm is None:
                    return ProviderHealth(
                        available=False,
                        configured=True,
                        connectivity_checked=True,
                        provider_name="chatterbox-job",
                        message="In-process JobManager is not initialized",
                    )
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
            supports_pace=True,
            supports_pronunciation=True,
            supports_director_notes=False,
            supports_ssml=False,
            supports_seed=True,
        )

    def render(
        self,
        request: TTSRenderRequest,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSRenderResult:
        if cancellation_token and cancellation_token.is_cancelled():
            return TTSRenderResult(
                success=False,
                provider="chatterbox-job",
                model=self.default_model,
                audio_path=None,
                error="Render cancelled by cancellation token",
                retryable=False,
            )

        start_time = time.time()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        final_wav_path = output_dir / f"attempt_{request.attempt_id:02d}.wav"
        temp_wav_path = output_dir / f"attempt_{request.attempt_id:02d}.tmp.wav"

        # 1. Format text with pronunciation substitution if present
        synth_text = request.text
        if request.pronunciation:
            synth_text = apply_pronunciation_dict(request.text, request.pronunciation)

        params: dict[str, Any] = {
            "text": synth_text,
            "character_id": request.voice_profile if not request.voice_profile.startswith("mythology_") else None,
            "temperature": round(0.4 + (request.energy / 5.0) * 0.5, 2) if request.energy is not None else 0.65,
            "top_p": 0.95,
            "repetition_penalty": 1.2,
        }

        # If multilingual model, attach language_id
        if self.default_model == "multilingual":
            params["language_id"] = normalize_language_id(request.language)

        # 2. Check for self-deadlock if called on the JobManager worker thread
        jm_instance = None
        if hasattr(self.gateway, "_get_jm"):
            jm_instance = self.gateway._get_jm()
        elif hasattr(self.gateway, "_worker_thread"):
            jm_instance = self.gateway

        if jm_instance and getattr(jm_instance, "_worker_thread", None) == threading.current_thread():
            # Running inside the worker thread itself: execute synchronously to prevent deadlock
            try:
                from services.inference import execute_model_inference
                output_wav = execute_model_inference(
                    model_type=self.default_model,
                    params=params,
                    input_paths=[],
                    output_dir=output_dir,
                )
                if not output_wav or not Path(output_wav).exists():
                    return TTSRenderResult(
                        success=False,
                        provider="chatterbox-job",
                        model=self.default_model,
                        audio_path=None,
                        error="Synchronous inference produced no output file",
                        error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                        retryable=True,
                    )
                shutil.copyfile(Path(output_wav), temp_wav_path)
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
                    provider_request_id="sync_direct",
                    raw_metadata={"latency_seconds": round(time.time() - start_time, 3), "in_process_sync": True},
                )
            except Exception as exc:
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    error=f"Direct sync inference failed: {exc}",
                    error_type=ProviderErrorType.SERVER_ERROR,
                    retryable=True,
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

        # 4. Poll in-memory Job
        while (time.time() - start_time) < self.timeout_seconds:
            if cancellation_token and cancellation_token.is_cancelled():
                self.gateway.cancel_job(job_id)
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    provider_request_id=job_id,
                    error="Render cancelled by caller",
                    retryable=False,
                )

            j = self.gateway.get_job(job_id)
            if not j:
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    provider_request_id=job_id,
                    error=f"Job {job_id} not found in gateway",
                    error_type=ProviderErrorType.SERVER_ERROR,
                    retryable=False,
                )

            status = getattr(j, "status", "unknown")
            phase = getattr(j, "phase", status)
            progress = float(getattr(j, "progress_percent", 0.0))

            if progress_callback:
                progress_callback(phase, progress, {"job_id": job_id, "status": status})

            if status in ("completed", "succeeded"):
                output_path_str = getattr(j, "output_path", None)
                if not output_path_str or not Path(output_path_str).exists():
                    return TTSRenderResult(
                        success=False,
                        provider="chatterbox-job",
                        model=self.default_model,
                        audio_path=None,
                        provider_request_id=job_id,
                        error="Job completed but output file is missing",
                        error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                        retryable=True,
                    )

                # Copy to temp WAV
                src_wav = Path(output_path_str)
                shutil.copyfile(src_wav, temp_wav_path)

                # Validate WAV
                is_valid, duration, s_rate, channels, val_err = validate_generated_wave(temp_wav_path)
                if not is_valid:
                    temp_wav_path.unlink(missing_ok=True)
                    return TTSRenderResult(
                        success=False,
                        provider="chatterbox-job",
                        model=self.default_model,
                        audio_path=None,
                        provider_request_id=job_id,
                        error=f"Generated audio validation failed: {val_err}",
                        error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                        retryable=True,
                    )

                temp_wav_path.replace(final_wav_path)
                latency = round(time.time() - start_time, 3)

                return TTSRenderResult(
                    success=True,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=str(final_wav_path),
                    duration=duration,
                    sample_rate=s_rate,
                    channels=channels,
                    provider_request_id=job_id,
                    raw_metadata={"latency_seconds": latency, "in_process": True},
                )

            if status in ("failed", "error"):
                err_msg = getattr(j, "error", "Job failed during in-process execution")
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    provider_request_id=job_id,
                    error=err_msg,
                    error_type=ProviderErrorType.SERVER_ERROR,
                    retryable=False,
                )

            if status == "cancelled":
                return TTSRenderResult(
                    success=False,
                    provider="chatterbox-job",
                    model=self.default_model,
                    audio_path=None,
                    provider_request_id=job_id,
                    error="Job cancelled",
                    error_type=ProviderErrorType.BAD_REQUEST,
                    retryable=False,
                )

            time.sleep(self.poll_interval_seconds)

        # Timeout reached: best-effort cancel orphan job
        self.gateway.cancel_job(job_id)

        return TTSRenderResult(
            success=False,
            provider="chatterbox-job",
            model=self.default_model,
            audio_path=None,
            provider_request_id=job_id,
            error=f"Job {job_id} timed out after {self.timeout_seconds}s",
            error_type=ProviderErrorType.TIMEOUT,
            retryable=True,
        )
