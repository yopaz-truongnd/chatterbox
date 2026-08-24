"""Gemini TTS Provider Adapter (Phase 8).

Handles centralized mapping of VoicePlan direction (emotion, energy, pace,
director_note, pronunciation, emphasis) into Gemini TTS prompt/payload.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import wave

from services.render_models import (
    ProviderCapabilities,
    ProviderHealth,
    TTSRenderRequest,
    TTSRenderResult,
)
from services.tts.base import TTSProvider


def map_voice_plan_to_gemini_payload(request: TTSRenderRequest) -> dict[str, Any]:
    """Centralized mapping of VoicePlan direction to Gemini TTS payload."""
    # Build director instruction prompt
    instructions: list[str] = []

    if request.emotion:
        instructions.append(f"Emotion/Tone: {request.emotion}")
    if request.energy is not None:
        instructions.append(f"Energy Level (1-5): {request.energy:.1f}")
    if request.pace is not None:
        instructions.append(f"Pace Multiplier: {request.pace:.2f}")
    if request.target_wpm:
        instructions.append(f"Target Pacing: {request.target_wpm} WPM")
    if request.director_note:
        instructions.append(f"Director Note: {request.director_note}")

    if request.pronunciation:
        pron_lines = [f"'{term}': pronounce as '{hint}'" for term, hint in request.pronunciation.items()]
        instructions.append(f"Pronunciation Guides: {'; '.join(pron_lines)}")

    if request.emphasis:
        instructions.append(f"Emphasize words: {', '.join(request.emphasis)}")

    system_instruction = "\n".join(instructions)

    payload_text = request.provider_payload_text or request.text

    return {
        "text": payload_text,
        "voice_profile": request.voice_profile,
        "language": request.language,
        "system_instruction": system_instruction,
        "parameters": {
            "pace": request.pace or 1.0,
            "energy": request.energy or 3.0,
        },
    }


class GeminiTTSProvider(TTSProvider):
    """Gemini TTS Provider adapter with centralized direction mapping."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "flash-tts",
        sample_rate: int = 24000,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model_name
        self.sample_rate = sample_rate

    def healthcheck(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(
                available=False,
                provider_name="gemini",
                message="GEMINI_API_KEY environment variable is not set",
                details={"model": self.model_name},
            )
        return ProviderHealth(
            available=True,
            provider_name="gemini",
            message=f"Gemini TTS Provider ready with model {self.model_name}",
            details={"model": self.model_name, "sample_rate": self.sample_rate},
        )

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_emotion=True,
            supports_pace=True,
            supports_pronunciation=True,
            supports_director_notes=True,
            supports_ssml=False,
            supports_seed=True,
        )

    def render(self, request: TTSRenderRequest, output_dir: Path) -> TTSRenderResult:
        if not self.api_key:
            return TTSRenderResult(
                success=False,
                provider="gemini",
                model=self.model_name,
                audio_path=None,
                error="GEMINI_API_KEY is not configured",
                retryable=False,
            )

        payload = map_voice_plan_to_gemini_payload(request)
        output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"attempt_{request.attempt_id:02d}.wav"
        audio_path = output_dir / filename

        # Live Gemini TTS audio rendering endpoint is not yet connected;
        # do not return fake success when no audio file is produced.
        return TTSRenderResult(
            success=False,
            provider="gemini",
            model=self.model_name,
            audio_path=None,
            error="Gemini TTS live audio rendering is not yet implemented",
            raw_metadata={"payload": payload},
            retryable=False,
        )
