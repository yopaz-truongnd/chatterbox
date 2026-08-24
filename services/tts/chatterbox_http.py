"""Chatterbox HTTP TTS Provider Adapter (Phase 10A & 10B).

Connects to the local Chatterbox FastAPI server runtime over REST:
- Uses POST /api/v1/tts endpoints to submit async inference jobs.
- Allows server hardware auto-selection (model='auto') by default.
- Normalizes multilingual language tags and passes language_id.
- Applies pronunciation substitution if present while preserving request.text contract.
- Cancels orphan jobs best-effort on timeout.
- Downloads generated WAV audio, validates file integrity, and saves to attempt destination.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
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
from services.tts.gemini import validate_generated_wave

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_POLL_INTERVAL = 0.5


def _map_model_name(model: str | None) -> str:
    """Normalize and map requested model name or preset. Defaults to 'auto'."""
    if not model or model.lower() in ("auto", "default", "recommended"):
        return "auto"
    m_lower = model.lower()
    if "fast" in m_lower or "nano" in m_lower:
        return "nano"
    if "expressive" in m_lower or "turbo" in m_lower:
        return "turbo"
    if "standard" in m_lower:
        return "standard"
    if "multilingual" in m_lower or "mtl" in m_lower:
        return "multilingual"
    return model


def normalize_language_id(language: str | None) -> str:
    """Normalize language code e.g. en-US -> en, vi-VN -> vi, zh-CN -> zh."""
    if not language:
        return "en"
    clean = language.strip().replace("_", "-").split("-")[0].lower()
    return clean or "en"


class ChatterboxHttpProvider(TTSProvider):
    """Local Chatterbox HTTP REST Provider adapter."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str = "auto",
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
    ):
        self.base_url = (base_url or os.environ.get("CHATTERBOX_API_URL") or DEFAULT_API_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("CHATTERBOX_API_KEY")
        self.default_model = default_model or "auto"
        self.timeout_seconds = timeout_seconds or float(
            os.environ.get("CHATTERBOX_PROVIDER_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)
        )
        self.poll_interval_seconds = poll_interval_seconds or float(
            os.environ.get("CHATTERBOX_PROVIDER_POLL_INTERVAL", DEFAULT_POLL_INTERVAL)
        )

    def _get_headers(self) -> dict[str, str]:
        headers = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def healthcheck(self) -> ProviderHealth:
        """Verify local Chatterbox API server connectivity and status."""
        health_url = f"{self.base_url}/health"
        headers = self._get_headers()

        try:
            req = urllib.request.Request(health_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status in (200, 204):
                    return ProviderHealth(
                        available=True,
                        configured=True,
                        connectivity_checked=True,
                        provider_name="chatterbox-http",
                        message=f"Local Chatterbox API server is healthy at {self.base_url}",
                        details={"base_url": self.base_url, "default_model": self.default_model},
                    )
        except Exception:
            pass

        # Try presets endpoint as fallback healthcheck
        try:
            req = urllib.request.Request(f"{self.base_url}/api/v1/presets/quality", headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status in (200, 204):
                    return ProviderHealth(
                        available=True,
                        configured=True,
                        connectivity_checked=True,
                        provider_name="chatterbox-http",
                        message=f"Local Chatterbox API server reachable at {self.base_url}",
                        details={"base_url": self.base_url, "default_model": self.default_model},
                    )
        except Exception as exc:
            return ProviderHealth(
                available=False,
                configured=True,
                connectivity_checked=True,
                provider_name="chatterbox-http",
                message=f"Cannot connect to local Chatterbox API at {self.base_url}: {exc}",
                details={"base_url": self.base_url},
            )

        return ProviderHealth(
            available=False,
            configured=True,
            connectivity_checked=True,
            provider_name="chatterbox-http",
            message=f"Local Chatterbox API returned unexpected response at {self.base_url}",
            details={"base_url": self.base_url},
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

    def _submit_job(
        self, request: TTSRenderRequest, model: str
    ) -> tuple[str | None, str | None, ProviderErrorType | None, bool]:
        """Submit TTS job via multipart/form-data or urlencoded POST request.
        
        Returns (job_id, error_message).
        """
        if model in ("nano", "turbo", "standard", "multilingual"):
            endpoint = f"{self.base_url}/api/v1/tts/{model}"
        else:
            endpoint = f"{self.base_url}/api/v1/tts"

        # Apply pronunciation substitutions if requested
        synth_text = request.text
        if request.pronunciation:
            synth_text = apply_pronunciation_dict(request.text, request.pronunciation)

        payload: dict[str, Any] = {
            "text": synth_text,
        }

        if model != "auto":
            payload["model"] = model

        # Multilingual endpoint requires language_id
        if model == "multilingual" or endpoint.endswith("/multilingual"):
            payload["language_id"] = normalize_language_id(request.language)

        # Temperature / pacing mappings if applicable
        if request.energy is not None:
            payload["temperature"] = round(0.4 + (request.energy / 5.0) * 0.5, 2)
        if request.voice_profile and not request.voice_profile.startswith("mythology_"):
            payload["character_id"] = request.voice_profile

        # Encode form data
        data = urllib.parse.urlencode(payload).encode("utf-8")
        headers = self._get_headers()
        headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                if resp.status in (200, 201, 202):
                    body = json.loads(resp.read().decode("utf-8"))
                    job_id = body.get("id")
                    if not job_id:
                        return None, f"Response missing job ID: {body}"
                    return job_id, None, None, False
                retryable = resp.status == 429 or resp.status >= 500
                error_type = ProviderErrorType.RATE_LIMIT if resp.status == 429 else (
                    ProviderErrorType.SERVER_ERROR if resp.status >= 500 else ProviderErrorType.BAD_REQUEST
                )
                return None, f"HTTP request failed with status {resp.status}", error_type, retryable
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or exc.code >= 500
            error_type = ProviderErrorType.RATE_LIMIT if exc.code == 429 else (
                ProviderErrorType.SERVER_ERROR if exc.code >= 500 else ProviderErrorType.BAD_REQUEST
            )
            return None, f"HTTP Error {exc.code}: {err_body}", error_type, retryable
        except Exception as exc:
            return None, f"Connection error submitting job: {exc}", ProviderErrorType.NETWORK_ERROR, True

    def _poll_job(
        self,
        job_id: str,
        progress_callback: ProgressCallback | None,
        cancellation_token: CancellationToken | None,
    ) -> tuple[bool, str | None, str | None]:
        """Poll job until completion, failure, cancellation, or timeout.
        
        Cancels job on server upon cancellation or timeout.
        Returns (success, status, error_message).
        """
        start_time = time.time()
        job_url = f"{self.base_url}/api/v1/jobs/{job_id}"
        headers = self._get_headers()

        while (time.time() - start_time) < self.timeout_seconds:
            # Check cancellation
            if cancellation_token and cancellation_token.is_cancelled():
                try:
                    cancel_req = urllib.request.Request(
                        f"{self.base_url}/api/v1/jobs/{job_id}/cancel",
                        headers=headers,
                        method="POST",
                    )
                    urllib.request.urlopen(cancel_req, timeout=3.0)
                except Exception:
                    pass
                return False, "cancelled", "Render cancelled by caller"

            try:
                req = urllib.request.Request(job_url, headers=headers, method="GET")
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    if resp.status == 200:
                        job_data = json.loads(resp.read().decode("utf-8"))
                        status = job_data.get("status", "unknown")
                        phase = job_data.get("phase", status)
                        progress = float(job_data.get("progress_percent", 0.0))

                        if progress_callback:
                            progress_callback(phase, progress, {"job_id": job_id, "status": status})

                        if status in ("completed", "succeeded"):
                            return True, status, None
                        if status in ("failed", "error"):
                            return False, status, job_data.get("error", "Job failed on server")
                        if status == "cancelled":
                            return False, status, "Job was cancelled on server"
            except Exception as exc:
                logger.warning("Error polling job %s: %s", job_id, exc)

            time.sleep(self.poll_interval_seconds)

        # Timeout reached: best-effort cancel orphan job on server
        try:
            cancel_req = urllib.request.Request(
                f"{self.base_url}/api/v1/jobs/{job_id}/cancel",
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(cancel_req, timeout=3.0)
        except Exception:
            pass

        return False, "timeout", f"Job {job_id} timed out after {self.timeout_seconds}s"

    def _download_audio(self, job_id: str, target_path: Path) -> tuple[bool, str | None]:
        """Download generated audio WAV file from server."""
        audio_url = f"{self.base_url}/api/v1/jobs/{job_id}/audio"
        headers = self._get_headers()
        req = urllib.request.Request(audio_url, headers=headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                if resp.status == 200:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(target_path, "wb") as f:
                        f.write(resp.read())
                    return True, None
                return False, f"Failed to download audio: status {resp.status}"
        except Exception as exc:
            return False, f"Error downloading audio for job {job_id}: {exc}"

    def render(
        self,
        request: TTSRenderRequest,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSRenderResult:
        """Render narration beat by submitting async job to Chatterbox API server and downloading WAV."""
        if cancellation_token and cancellation_token.is_cancelled():
            return TTSRenderResult(
                success=False,
                provider="chatterbox-http",
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

        # Resolve model
        selected_model = _map_model_name(self.default_model)

        # 1. Submit Job
        if progress_callback:
            progress_callback("submitting", 5.0, {"model": selected_model})

        job_id, submit_err, submit_error_type, submit_retryable = self._submit_job(request, selected_model)
        if submit_err or not job_id:
            return TTSRenderResult(
                success=False,
                provider="chatterbox-http",
                model=selected_model,
                audio_path=None,
                error=submit_err or "Failed to submit TTS job",
                error_type=submit_error_type or ProviderErrorType.SERVER_ERROR,
                retryable=submit_retryable,
            )

        # 2. Poll Job
        success, job_status, poll_err = self._poll_job(job_id, progress_callback, cancellation_token)
        if not success:
            err_type = ProviderErrorType.TIMEOUT if job_status == "timeout" else ProviderErrorType.SERVER_ERROR
            retryable = (job_status == "timeout")
            return TTSRenderResult(
                success=False,
                provider="chatterbox-http",
                model=selected_model,
                audio_path=None,
                provider_request_id=job_id,
                error=poll_err or f"Job {job_id} failed with status {job_status}",
                error_type=err_type,
                retryable=retryable,
            )

        # 3. Download Audio to Temp File
        dl_ok, dl_err = self._download_audio(job_id, temp_wav_path)
        if not dl_ok:
            if temp_wav_path.exists():
                temp_wav_path.unlink(missing_ok=True)
            return TTSRenderResult(
                success=False,
                provider="chatterbox-http",
                model=selected_model,
                audio_path=None,
                provider_request_id=job_id,
                error=dl_err or "Failed to download generated audio",
                error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                retryable=True,
            )

        # 4. Strictly Validate WAV
        is_valid, duration, s_rate, channels, val_err = validate_generated_wave(temp_wav_path)
        if not is_valid:
            if temp_wav_path.exists():
                temp_wav_path.unlink(missing_ok=True)
            return TTSRenderResult(
                success=False,
                provider="chatterbox-http",
                model=selected_model,
                audio_path=None,
                provider_request_id=job_id,
                error=f"Downloaded WAV validation failed: {val_err}",
                error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                retryable=True,
            )

        # 5. Atomic Rename
        temp_wav_path.replace(final_wav_path)
        latency = round(time.time() - start_time, 3)

        return TTSRenderResult(
            success=True,
            provider="chatterbox-http",
            model=selected_model,
            audio_path=str(final_wav_path),
            duration=duration,
            sample_rate=s_rate,
            channels=channels,
            provider_request_id=job_id,
            raw_metadata={
                "local_job_id": job_id,
                "latency_seconds": latency,
                "endpoint": self.base_url,
            },
        )
