"""TTS Provider Factory (Phase 10A & 10B).

Creates and configures TTSExecutionPort instances based on requested provider name:
1. chatterbox-http (default for CLI and external clients, uses model='auto' by default)
2. chatterbox-job (for in-process server execution without HTTP loopback)
3. gemini (optional cloud TTS provider)
4. fake (deterministic test provider)
"""

from __future__ import annotations

import os
from typing import Any

from services.tts.base import TTSExecutionPort
from services.tts.chatterbox_http import ChatterboxHttpProvider
from services.tts.chatterbox_job import ChatterboxJobProvider, JobExecutionGateway
from services.tts.fake import FakeTTSProvider
from services.tts.gemini import GeminiTTSProvider

DEFAULT_PROVIDER_NAME = "chatterbox-http"


def create_tts_provider(
    provider_name: str | None = None,
    model: str | None = None,
    voice: str | None = None,
    gateway: JobExecutionGateway | None = None,
    **kwargs: Any,
) -> TTSExecutionPort:
    """Factory creating configured TTSExecutionPort adapter with canonical provider priority."""
    p_name = (provider_name or os.environ.get("CHATTERBOX_DEFAULT_PROVIDER") or DEFAULT_PROVIDER_NAME).lower().strip()

    if p_name in ("fake", "fake-tts", "test"):
        return FakeTTSProvider(**kwargs)

    if p_name in ("gemini", "google", "gemini-tts"):
        return GeminiTTSProvider(
            model_name=model,
            voice_name=voice,
            **kwargs,
        )

    if p_name in ("chatterbox-job", "job", "in-process", "in_process"):
        if gateway is None:
            raise ValueError(
                "chatterbox-job requires an injected JobExecutionGateway and cannot be created without a gateway"
            )
        return ChatterboxJobProvider(
            gateway=gateway,
            default_model=model or "nano",
            **kwargs,
        )

    if p_name in ("chatterbox-http", "http", "local"):
        return ChatterboxHttpProvider(
            default_model=model or "auto",
            **kwargs,
        )

    raise ValueError(f"Unknown TTS provider: {p_name}")
