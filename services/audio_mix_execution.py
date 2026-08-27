"""Audio Mixing Execution Port Protocol (Phase 14).

Defines the universal execution interface for multi-track audio rendering,
allowing seamless swapping between Pure Python WAV mixer and FFmpeg backend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from services.audio_mix_models import MixPlan
from services.tts.base import CancellationToken, ProgressCallback


@runtime_checkable
class AudioMixExecutionPort(Protocol):
    """Execution port for multi-track audio mixing."""

    def mix(
        self,
        plan: MixPlan,
        proj_dir: Path | str,
        output_path: Path | str,
        progress_callback: ProgressCallback | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> Path:
        """Render multi-track MixPlan to an output audio file."""
        ...
