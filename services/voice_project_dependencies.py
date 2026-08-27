"""Voice Project Server Dependency Wiring (Phase 12-13 Hardened).

Provides composition roots and dependency injection factories for FastAPI REST API
and MCP Agent servers, strictly enforcing in-process JobExecutionGateway for 'local' TTS
with zero silent fallbacks to HTTP loopback or FakeTTSProvider in production.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from services.tts.base import TTSExecutionPort
from services.tts.chatterbox_job import ChatterboxJobProvider, DefaultJobManagerGateway
from services.tts.fake import FakeTTSProvider
from services.tts.gemini import GeminiTTSProvider
from services.voice_project_operations import VoiceProjectOperationManager
from services.voice_project_service import VoiceProjectService
from services.voice_project_store import VoiceProjectStore
from services.voice_renderer import ProviderUnavailableError

# Shared OperationManager singleton across the server process
_GLOBAL_OPERATION_MANAGER: VoiceProjectOperationManager | None = None
_GLOBAL_WORKFLOW_SERVICE: Any | None = None


def get_voice_project_store(root_dir: str | Path | None = None) -> VoiceProjectStore:
    """Provide configured VoiceProjectStore instance."""
    if root_dir:
        base_dir = Path(root_dir)
    else:
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
        data_dir = os.getenv("CHATTERBOX_API_DATA_DIR")
        ops_dir = Path(data_dir) / "operations" if data_dir else Path("projects/operations")
        _GLOBAL_OPERATION_MANAGER = VoiceProjectOperationManager(max_workers=4, operations_dir=ops_dir)
    return _GLOBAL_OPERATION_MANAGER


def resolve_server_tts_provider(
    provider_name: str = "local",
    model: str | None = None,
    voice: str | None = None,
) -> TTSExecutionPort:
    """Resolve TTS Execution Port for server process, guaranteeing strict provider resolution.

    - 'local': Uses DefaultJobManagerGateway wrapping in-process JobManager. Fails loudly with
      ProviderUnavailableError if JobManager is not initialized. No silent fallback to HTTP or Fake.
    - 'gemini': Uses GeminiTTSProvider with cloud credentials.
    - 'fake': Explicit test mock provider (only selected when provider='fake').
    """
    normalized_name = (provider_name or "local").lower().strip()

    if normalized_name in ("local", "chatterbox-job", "in-process", "job"):
        jm = None
        try:
            import api_app
            jm = getattr(api_app, "job_manager", None)
        except Exception:
            jm = None

        if jm is None:
            raise ProviderUnavailableError(
                "Local TTS provider requires the in-process JobManager runtime which is not currently available. "
                "Ensure the FastAPI server is running or explicitly select provider='fake' for test suites."
            )

        gateway = DefaultJobManagerGateway(jm)
        return ChatterboxJobProvider(gateway=gateway, default_model=model or "nano")

    if normalized_name == "gemini":
        return GeminiTTSProvider(model_name=model, voice_name=voice)

    if normalized_name in ("fake", "fake-tts", "test"):
        return FakeTTSProvider()

    raise ProviderUnavailableError(
        f"Unsupported or unconfigured TTS provider '{provider_name}'. Supported providers: 'local', 'gemini', 'fake'."
    )


def get_voice_project_service(
    provider_name: str = "local",
    store: VoiceProjectStore | None = None,
    execution_port: TTSExecutionPort | None = None,
) -> VoiceProjectService:
    """Create VoiceProjectService configured for server execution."""
    actual_store = store or get_voice_project_store()
    actual_port = execution_port
    if actual_port is None:
        try:
            actual_port = resolve_server_tts_provider(provider_name)
        except Exception:
            actual_port = None

    return VoiceProjectService(
        store=actual_store,
        execution_port=actual_port,
        provider_name=provider_name,
    )


def get_voice_project_workflow_service() -> Any:
    """Provide the process-wide workflow orchestrator used by REST and MCP adapters."""
    global _GLOBAL_WORKFLOW_SERVICE
    if _GLOBAL_WORKFLOW_SERVICE is None:
        # Local import avoids a module cycle: the workflow service uses the
        # project dependency functions above for its own composition.
        from services.voice_project_workflow import VoiceProjectWorkflowService

        _GLOBAL_WORKFLOW_SERVICE = VoiceProjectWorkflowService()
    return _GLOBAL_WORKFLOW_SERVICE


def get_director_review_service(store: VoiceProjectStore | None = None) -> Any:
    from services.director_review_service import DirectorReviewService
    return DirectorReviewService(store or get_voice_project_store())


def get_director_revision_service(
    provider_name: str = "local", store: VoiceProjectStore | None = None,
) -> Any:
    from services.director_revision_service import DirectorRevisionService
    actual_store = store or get_voice_project_store()
    return DirectorRevisionService(get_voice_project_service(provider_name=provider_name, store=actual_store))


def get_director_resource_service(store: VoiceProjectStore | None = None) -> Any:
    from services.director_resource_service import DirectorResourceService
    actual_store = store or get_voice_project_store()
    return DirectorResourceService(get_voice_project_service(store=actual_store))
