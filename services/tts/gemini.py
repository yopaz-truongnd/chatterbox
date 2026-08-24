"""Gemini Live TTS Provider Adapter (Phase 10).

Integrates official Google GenAI SDK (google-genai) for real audio generation:
- Exact-text preservation with clear instruction delimiters.
- Centralized mapping of emotion, energy, pace, target WPM, pronunciation, and emphasis.
- Configurable voice profile mapping.
- Safe temp-file writing, PCM-to-WAV encoding, and strict WAV validation.
- Comprehensive error taxonomy (ProviderErrorType) and deterministic retryability.
"""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
import struct
import time
from typing import Any
import wave
import yaml
from pydantic import BaseModel, Field

from services.render_models import (
    ProviderCapabilities,
    ProviderErrorType,
    ProviderHealth,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.base import CancellationToken, ProgressCallback, TTSProvider

logger = logging.getLogger(__name__)


# ==========================================
# 1. Provider Configuration & Models
# ==========================================

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_GEMINI_VOICE = "Kore"

DEFAULT_PROFILE_VOICE_MAP = {
    "mythology_narrator_male": "Kore",
    "mythology_narrator_female": "Aoede",
    "mythology_narrator_elder": "Puck",
    "mythology_narrator_deep": "Fenrir",
}


class GeminiTTSConfig(BaseModel):
    """Typed configuration model for Gemini TTS Provider."""

    model: str = DEFAULT_GEMINI_MODEL
    default_voice: str = DEFAULT_GEMINI_VOICE
    profile_voice_map: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_PROFILE_VOICE_MAP))
    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2
    timeout_seconds: float = 30.0

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> GeminiTTSConfig:
        """Load configuration from rules/tts-providers.yaml or defaults."""
        if not config_path:
            config_path = Path(__file__).resolve().parent.parent.parent / "rules" / "tts-providers.yaml"
        else:
            config_path = Path(config_path)

        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                gemini_data = data.get("providers", {}).get("gemini", {})
                if gemini_data:
                    profiles = gemini_data.get("profiles", {})
                    profile_map = {}
                    for p_name, p_val in profiles.items():
                        if isinstance(p_val, dict) and "voice" in p_val:
                            profile_map[p_name] = p_val["voice"]
                        elif isinstance(p_val, str):
                            profile_map[p_name] = p_val

                    return cls(
                        model=gemini_data.get("default_model", DEFAULT_GEMINI_MODEL),
                        default_voice=gemini_data.get("default_voice", DEFAULT_GEMINI_VOICE),
                        profile_voice_map=profile_map or dict(DEFAULT_PROFILE_VOICE_MAP),
                        sample_rate=gemini_data.get("sample_rate", 24000),
                        channels=gemini_data.get("channels", 1),
                        sample_width=gemini_data.get("sample_width", 2),
                        timeout_seconds=float(gemini_data.get("timeout_seconds", 30.0)),
                    )
            except Exception as exc:
                logger.warning("Failed to parse TTS provider config at %s: %s", config_path, exc)

        return cls()


# ==========================================
# 2. Audio Writing & Validation Helpers
# ==========================================

def write_pcm_wave(
    path: Path,
    pcm_data: bytes,
    channels: int = 1,
    rate: int = 24000,
    sample_width: int = 2,
) -> None:
    """Write raw PCM or existing WAV audio bytes safely to a standard WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    # If the payload is already a valid WAV container (starts with RIFF...WAVE)
    if len(pcm_data) >= 12 and pcm_data[:4] == b"RIFF" and pcm_data[8:12] == b"WAVE":
        with open(path, "wb") as f:
            f.write(pcm_data)
        return

    # Raw PCM stream -> package into WAV container
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)


def validate_generated_wave(path: Path) -> tuple[bool, float, int, int, str | None]:
    """Strictly validate generated WAV file integrity and extract duration/sample-rate/channels.

    Returns (is_valid, duration, sample_rate, channels, error_message).
    """
    if not path.exists():
        return False, 0.0, 0, 0, f"File does not exist: {path}"

    if path.stat().st_size <= 44:
        return False, 0.0, 0, 0, f"File is too small to contain valid audio data ({path.stat().st_size} bytes)"

    try:
        with wave.open(str(path), "rb") as wf:
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            nframes = wf.getnframes()
            if nframes == 0:
                return False, 0.0, sample_rate, channels, "WAV contains 0 audio frames"
            if sample_rate <= 0:
                return False, 0.0, sample_rate, channels, f"Invalid sample rate: {sample_rate}"
            duration = round(nframes / float(sample_rate), 3)
            if duration <= 0.0:
                return False, 0.0, sample_rate, channels, f"Invalid duration: {duration}s"
            return True, duration, sample_rate, channels, None
    except Exception as exc:
        return False, 0.0, 0, 0, f"Malformed WAV container: {exc}"


# ==========================================
# 3. Prompt & Instruction Construction
# ==========================================

def _map_energy_to_description(energy: float | None) -> str:
    """Map numeric energy rating (1-5) to natural language performance description."""
    if energy is None:
        return "balanced, engaging delivery"
    if energy < 1.5:
        return "very restrained, quiet, and intimate delivery"
    if energy < 2.5:
        return "subtle, grounded, and steady delivery"
    if energy < 3.5:
        return "moderate, energetic, and engaging delivery"
    if energy < 4.5:
        return "strong, authoritative, and powerful delivery"
    return "high intensity, dramatic, and commanding delivery"


def _map_pace_to_description(pace: float | None, target_wpm: int | None) -> str:
    """Map pace multiplier and target WPM to clear natural language instructions."""
    wpm_str = f"approximately {target_wpm} words per minute" if target_wpm else "measured pacing"
    if pace is None or (0.90 <= pace <= 1.10):
        return f"Speak at a natural, measured storytelling pace ({wpm_str})."
    if pace < 0.90:
        return f"Speak slower than normal, deliberate and unhurried ({wpm_str})."
    return f"Speak slightly faster than normal, with lively momentum ({wpm_str})."


def map_voice_plan_to_gemini_payload(request: TTSRenderRequest) -> dict[str, Any]:
    """Centralized mapping of VoicePlan direction to structured Gemini TTS prompt/payload.

    CRITICAL INVARIANT: request.text is preserved byte-for-byte in the payload.
    """
    system_lines: list[str] = [
        "SCENE / PERFORMANCE INSTRUCTIONS",
        "Read the supplied narration exactly as written inside the <narration> tags.",
        "Do NOT improvise, omit, or alter any words, spelling, or punctuation.",
        "",
        "Performance Delivery:",
    ]

    if request.emotion:
        system_lines.append(f"- Tone/Emotion: {request.emotion}")

    system_lines.append(f"- Energy: {_map_energy_to_description(request.energy)}")
    system_lines.append(f"- Pace: {_map_pace_to_description(request.pace, request.target_wpm)}")

    if request.pronunciation:
        system_lines.append("")
        system_lines.append("Pronunciation Guidance:")
        for term, hint in request.pronunciation.items():
            system_lines.append(f"- \"{term}\" → pronounce as \"{hint}\"")

    if request.emphasis:
        system_lines.append("")
        emp_str = ", ".join(f'"{e}"' for e in request.emphasis)
        system_lines.append(f"Place subtle emphasis on: {emp_str}")

    if request.director_note:
        system_lines.append("")
        system_lines.append(f"Director Note:\n{request.director_note}")

    system_instruction = "\n".join(system_lines)

    # Delimit narration text clearly while preserving exact script text
    content_text = f"<instructions>\n{system_instruction}\n</instructions>\n\n<narration>\n{request.text}\n</narration>"

    return {
        "text": request.text,  # MUST PRESERVE RAW SCRIPT EXACTLY
        "formatted_prompt": content_text,
        "voice_profile": request.voice_profile,
        "language": request.language,
        "system_instruction": system_instruction,
        "parameters": {
            "pace": request.pace or 1.0,
            "energy": request.energy or 3.0,
            "target_wpm": request.target_wpm or 138,
        },
    }


# ==========================================
# 4. Error Taxonomy & Exception Classification
# ==========================================

def classify_provider_exception(exc: Exception) -> tuple[ProviderErrorType, bool, float | None, str]:
    """Classify SDK / network exceptions into deterministic error taxonomy and retryability."""
    msg = str(exc)
    err_lower = msg.lower()

    # Rate limiting (429)
    if "429" in msg or "resource_exhausted" in err_lower or "rate limit" in err_lower or "quota" in err_lower:
        retry_after = 5.0
        return ProviderErrorType.RATE_LIMIT, True, retry_after, f"Gemini API rate limit exceeded: {msg}"

    # Authentication errors (401, 403)
    if "401" in msg or "403" in msg or "unauthenticated" in err_lower or "permission_denied" in err_lower or "api_key" in err_lower:
        return ProviderErrorType.AUTH_ERROR, False, None, f"Gemini API authentication failed: {msg}"

    # Model not found (404)
    if "404" in msg or "not_found" in err_lower or "model" in err_lower and "not found" in err_lower:
        return ProviderErrorType.MODEL_NOT_FOUND, False, None, f"Gemini model not found or unavailable: {msg}"

    # Bad request (400)
    if "400" in msg or "invalid_argument" in err_lower or "bad request" in err_lower:
        return ProviderErrorType.BAD_REQUEST, False, None, f"Gemini API bad request: {msg}"

    # Timeouts
    if "timeout" in err_lower or "timed out" in err_lower or "deadline_exceeded" in err_lower:
        return ProviderErrorType.TIMEOUT, True, 2.0, f"Gemini API request timed out: {msg}"

    # Server errors (500, 502, 503, 504)
    if any(code in msg for code in ("500", "502", "503", "504")) or "internal" in err_lower or "unavailable" in err_lower:
        return ProviderErrorType.SERVER_ERROR, True, 3.0, f"Gemini server error: {msg}"

    # Network / Connection errors
    if "connection" in err_lower or "network" in err_lower or "reset" in err_lower:
        return ProviderErrorType.NETWORK_ERROR, True, 2.0, f"Network error connecting to Gemini API: {msg}"

    # Unknown
    return ProviderErrorType.UNKNOWN, False, None, f"Unexpected Gemini error: {msg}"


# ==========================================
# 5. Gemini TTS Provider Implementation
# ==========================================

class GeminiTTSProvider(TTSProvider):
    """Gemini TTS Provider adapter with Google GenAI SDK (google-genai) integration."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        voice_name: str | None = None,
        config: GeminiTTSConfig | None = None,
        sample_rate: int | None = None,
    ):
        self.config = config or GeminiTTSConfig.load()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = (
            model_name
            or os.environ.get("GEMINI_TTS_MODEL")
            or self.config.model
        )
        self.voice_name = (
            voice_name
            or os.environ.get("GEMINI_TTS_VOICE")
            or self.config.default_voice
        )
        self.sample_rate = sample_rate or self.config.sample_rate

    def _get_sdk(self) -> Any:
        """Lazy load Google GenAI SDK."""
        try:
            from google import genai
            return genai
        except ImportError:
            return None

    def healthcheck(self) -> ProviderHealth:
        """Evaluate provider configuration and SDK availability (no live quota consumed)."""
        genai = self._get_sdk()
        if genai is None:
            return ProviderHealth(
                available=False,
                configured=bool(self.api_key),
                connectivity_checked=False,
                provider_name="gemini",
                message="google-genai package is not installed. Please install 'google-genai'.",
                details={"model": self.model_name},
            )

        if not self.api_key:
            return ProviderHealth(
                available=False,
                configured=False,
                connectivity_checked=False,
                provider_name="gemini",
                message="GEMINI_API_KEY environment variable is not set",
                details={"model": self.model_name, "default_voice": self.voice_name},
            )

        return ProviderHealth(
            available=True,
            configured=True,
            connectivity_checked=False,
            provider_name="gemini",
            message=f"Gemini TTS Provider ready with model {self.model_name} and voice {self.voice_name}",
            details={
                "model": self.model_name,
                "voice": self.voice_name,
                "sample_rate": self.sample_rate,
                "profile_mappings_count": len(self.config.profile_voice_map),
            },
        )

    def capabilities(self) -> ProviderCapabilities:
        """Return truthful capability profile of the Gemini TTS adapter."""
        return ProviderCapabilities(
            supports_emotion=True,
            supports_pace=True,
            supports_pronunciation=True,
            supports_director_notes=True,
            supports_ssml=False,
            supports_seed=False,
        )

    def resolve_voice(self, voice_profile: str) -> str:
        """Resolve VoicePlan voice profile to Gemini prebuilt voice name with fallback."""
        if self.voice_name and self.voice_name != self.config.default_voice:
            return self.voice_name
        return self.config.profile_voice_map.get(voice_profile, self.config.default_voice)

    def _create_client(self) -> Any:
        """Instantiate Google GenAI Client."""
        genai = self._get_sdk()
        if genai is None:
            raise RuntimeError("google-genai package is not installed.")
        return genai.Client(api_key=self.api_key)

    def _request_audio(
        self,
        client: Any,
        model: str,
        voice_name: str,
        formatted_prompt: str,
        system_instruction: str,
        timeout: float,
    ) -> Any:
        """Execute Google GenAI TTS audio generation API request."""
        from google.genai import types

        # Build SpeechConfig with prebuilt voice
        voice_cfg = types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
        )
        speech_cfg = types.SpeechConfig(voice_config=voice_cfg)

        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=speech_cfg,
            system_instruction=system_instruction,
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
        )

        response = client.models.generate_content(
            model=model,
            contents=formatted_prompt,
            config=config,
        )
        return response

    def _extract_pcm(self, response: Any) -> tuple[bytes | None, str | None, dict[str, Any]]:
        """Extract raw audio / PCM bytes and request metadata from Google GenAI response."""
        req_id = getattr(response, "response_id", None) or getattr(response, "id", None)
        raw_meta: dict[str, Any] = {
            "model": self.model_name,
        }

        # Check candidate parts
        candidates = getattr(response, "candidates", None)
        if candidates and len(candidates) > 0:
            candidate = candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason:
                raw_meta["finish_reason"] = str(finish_reason)

            content = getattr(candidate, "content", None)
            if content and hasattr(content, "parts"):
                for part in content.parts:
                    inline_data = getattr(part, "inline_data", None)
                    if inline_data and hasattr(inline_data, "data"):
                        data = inline_data.data
                        if data:
                            raw_meta["mime_type"] = getattr(inline_data, "mime_type", "audio/wav")
                            raw_meta["audio_byte_length"] = len(data)
                            return data, req_id, raw_meta

        # Fallback check for output audio fields (e.g. interactions or raw response)
        if hasattr(response, "audio") and response.audio:
            return response.audio, req_id, raw_meta

        return None, req_id, raw_meta

    def render(
        self,
        request: TTSRenderRequest,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSRenderResult:
        """Render narration beat into validated WAV audio using Gemini TTS API."""
        if cancellation_token and cancellation_token.is_cancelled():
            return TTSRenderResult(
                success=False,
                provider="gemini",
                model=self.model_name,
                audio_path=None,
                error="Render cancelled by cancellation token",
                retryable=False,
            )

        if progress_callback:
            progress_callback("submitting", 10.0, {"model": self.model_name})

        start_time = time.time()

        # 1. Validate API Key
        if not self.api_key:
            return TTSRenderResult(
                success=False,
                provider="gemini",
                model=self.model_name,
                audio_path=None,
                error="GEMINI_API_KEY is not configured",
                error_type=ProviderErrorType.AUTH_ERROR,
                retryable=False,
            )

        # 2. Check SDK installation
        if self._get_sdk() is None:
            return TTSRenderResult(
                success=False,
                provider="gemini",
                model=self.model_name,
                audio_path=None,
                error="google-genai package is not installed",
                error_type=ProviderErrorType.AUTH_ERROR,
                retryable=False,
            )

        # 3. Setup paths
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        final_wav_path = output_dir / f"attempt_{request.attempt_id:02d}.wav"
        temp_wav_path = output_dir / f"attempt_{request.attempt_id:02d}.tmp.wav"

        # 4. Resolve voice and payload
        voice = self.resolve_voice(request.voice_profile)
        payload = map_voice_plan_to_gemini_payload(request)

        # Clean up any leftover temp file
        if temp_wav_path.exists():
            try:
                temp_wav_path.unlink()
            except Exception:
                pass

        # 5. Call API and handle errors with taxonomy
        try:
            client = self._create_client()
            response = self._request_audio(
                client=client,
                model=self.model_name,
                voice_name=voice,
                formatted_prompt=payload["formatted_prompt"],
                system_instruction=payload["system_instruction"],
                timeout=self.config.timeout_seconds,
            )

            audio_bytes, req_id, raw_meta = self._extract_pcm(response)

            if not audio_bytes or len(audio_bytes) == 0:
                return TTSRenderResult(
                    success=False,
                    provider="gemini",
                    model=self.model_name,
                    audio_path=None,
                    error="Gemini TTS returned empty audio payload",
                    error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                    retryable=True,
                    raw_metadata=raw_meta,
                )

            # 6. Write PCM / audio safely to temp file
            write_pcm_wave(
                path=temp_wav_path,
                pcm_data=audio_bytes,
                channels=self.config.channels,
                rate=self.config.sample_rate,
                sample_width=self.config.sample_width,
            )

            # 7. Strictly validate written WAV file
            is_valid, duration, s_rate, channels, val_err = validate_generated_wave(temp_wav_path)
            if not is_valid:
                if temp_wav_path.exists():
                    temp_wav_path.unlink(missing_ok=True)
                return TTSRenderResult(
                    success=False,
                    provider="gemini",
                    model=self.model_name,
                    audio_path=None,
                    error=f"Generated audio validation failed: {val_err}",
                    error_type=ProviderErrorType.INVALID_AUDIO_RESPONSE,
                    retryable=True,
                    raw_metadata=raw_meta,
                )

            # 8. Atomic rename temp WAV to final destination
            temp_wav_path.replace(final_wav_path)

            latency = round(time.time() - start_time, 3)
            raw_meta["voice"] = voice
            raw_meta["latency_seconds"] = latency

            logger.info(
                "Successfully rendered beat %s attempt %d with Gemini (%s, voice: %s, duration: %.2fs)",
                request.beat_id, request.attempt_id, self.model_name, voice, duration,
            )

            return TTSRenderResult(
                success=True,
                provider="gemini",
                model=self.model_name,
                audio_path=str(final_wav_path),
                duration=duration,
                sample_rate=s_rate,
                channels=channels,
                provider_request_id=req_id,
                raw_metadata=raw_meta,
            )

        except Exception as exc:
            # Clean up temp file on failure
            if temp_wav_path.exists():
                try:
                    temp_wav_path.unlink(missing_ok=True)
                except Exception:
                    pass

            err_type, retryable, retry_after, err_msg = classify_provider_exception(exc)
            logger.error("Gemini TTS render failed for beat %s attempt %d: %s", request.beat_id, request.attempt_id, err_msg)

            return TTSRenderResult(
                success=False,
                provider="gemini",
                model=self.model_name,
                audio_path=None,
                error=err_msg,
                error_type=err_type,
                retryable=retryable,
                retry_after_seconds=retry_after,
                raw_metadata={"voice": voice, "model": self.model_name},
            )

