"""TTS Provider Protocol and Abstract Base Class (Phase 8)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from services.render_models import (
    ProviderCapabilities,
    ProviderHealth,
    TTSRenderRequest,
    TTSRenderResult,
)


class TTSProvider(ABC):
    """Abstract interface for all Text-To-Speech Providers."""

    @abstractmethod
    def healthcheck(self) -> ProviderHealth:
        """Verify API keys, connectivity, and model readiness."""
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return supported capabilities of the provider."""
        raise NotImplementedError

    @abstractmethod
    def render(self, request: TTSRenderRequest, output_dir: Path) -> TTSRenderResult:
        """Render speech for a single StoryBeat request and output WAV file."""
        raise NotImplementedError
