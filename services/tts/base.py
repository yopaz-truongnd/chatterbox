"""TTS Execution Port Protocol and Provider Base Classes (Phase 8 & Phase 10A)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from services.render_models import (
    ProviderCapabilities,
    ProviderHealth,
    TTSRenderRequest,
    TTSRenderResult,
)


class CancellationToken:
    """Lightweight cooperative cancellation token."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


ProgressCallback = Callable[[str, float, dict[str, Any]], None]


@runtime_checkable
class TTSExecutionPort(Protocol):
    """Universal execution port contract for TTS rendering."""

    def healthcheck(self) -> ProviderHealth:
        """Verify API keys, connectivity, and model readiness."""
        ...

    def capabilities(self) -> ProviderCapabilities:
        """Return supported capabilities of the provider."""
        ...

    def render(
        self,
        request: TTSRenderRequest,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSRenderResult:
        """Render speech for a single StoryBeat request and output WAV file."""
        ...


class TTSProvider(ABC):
    """Abstract interface for all Text-To-Speech Providers implementing TTSExecutionPort."""

    @abstractmethod
    def healthcheck(self) -> ProviderHealth:
        """Verify API keys, connectivity, and model readiness."""
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return supported capabilities of the provider."""
        raise NotImplementedError

    @abstractmethod
    def render(
        self,
        request: TTSRenderRequest,
        output_dir: Path,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TTSRenderResult:
        """Render speech for a single StoryBeat request and output WAV file."""
        raise NotImplementedError

