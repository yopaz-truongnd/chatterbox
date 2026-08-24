"""Voice Project Server Dependency Wiring (Phase 12).

Provides composition roots and dependency injection factories for FastAPI REST API
and MCP Agent servers, guaranteeing in-process JobManager execution for 'local' TTS.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.tts.base import TTSExecutionPort
from services.tts.chatterbox_job import ChatterboxJobProvider
from services.tts.fake import FakeTTSProvider
from services.tts.gemini import GeminiTTSProvider
from services.tts.provider_factory import create_tts_provider
from services.voice_project_operations import VoiceProjectOperationManager
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore

# Shared OperationManager singleton across REST and MCP
_GLOBAL_OPERATION_MANAGER: VoiceProjectOperationManager | None = None


def get_voice_project_store(root_dir: str | Path | None = None) -> VoiceProjectStore:
    """Provide configured VoiceProjectStore instance."""
    if root_dir:
        base_dir = Path(root_dir)
    else:
        # Check environment or default to ./projects
        data_dir = os.getenv("CHATTERBOX_API_DATA_DIR")
        if data_dir:
            base_dir = Path(data_dir) / "projects"
        else:
            base_dir = Path("projects")
    return VoiceProjectStore(root_dir=base_dir)


def get_voice_project_operation_manager() -> VoiceProjectOperationManager:
    """Provide shared VoiceProjectOperationManager singleton."""
    global _GLOBAL_OPERATION_MANAGER
    if _GLOBAL_OPERATION_MANAGER is None:
        _GLOBAL_OPERATION_MANAGER = VoiceProjectOperationManager(max_workers=4)
    return _GLOBAL_OPERATION_MANAGER


def resolve_server_tts_provider(
    provider_name: str = "local",
    model: str | None = None,
    voice: str | None = None,
) -> TTSExecutionPort:
    """Resolve TTS Execution Port for server process, ensuring local uses in-process JobManager."""
    normalized_name = (provider_name or "local").lower().strip()

    if normalized_name in ("local", "chatterbox-job", "in-process", "job"):
        # Resolve JobManager from api_app singleton
        gateway = None
        try:
            import api_app
            gateway = getattr(api_app, "job_manager", None)
        except Exception:
            gateway = None

        if gateway is not None:
            return ChatterboxJobProvider(gateway=gateway, default_model=model or "nano")
        if os.getenv("CHATTERBOX_IN_PROCESS") == "1" or os.getenv("CHATTERBOX_TEST_MODE") == "1":
            return FakeTTSProvider()
        return create_tts_provider("chatterbox-http", model=model, voice=voice)

    if normalized_name == "gemini":
        return GeminiTTSProvider(model_name=model, voice_name=voice)

    if normalized_name in ("fake", "fake-tts", "test"):
        return FakeTTSProvider()

    # Fallback to general factory
    return create_tts_provider(normalized_name, model=model, voice=voice)


def get_voice_project_service(
    provider_name: str = "local",
    store: VoiceProjectStore | None = None,
    execution_port: TTSExecutionPort | None = None,
) -> VoiceProjectService:
    """Create VoiceProjectService configured for server/MCP execution."""
    actual_store = store or get_voice_project_store()
    actual_port = execution_port or resolve_server_tts_provider(provider_name)
    return VoiceProjectService(
        store=actual_store,
        execution_port=actual_port,
        provider_name=provider_name,
    )
