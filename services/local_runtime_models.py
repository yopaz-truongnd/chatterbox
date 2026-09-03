"""Local Runtime Domain Models (Phase 17).

Typed contracts for LocalRuntimeCapabilities and PreflightIssue
used by LocalRuntimeService, the REST router, and the MCP adapter.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LocalRuntimeCapabilities(BaseModel):
    """Snapshot of what the local runtime can actually do right now."""

    available: bool
    """True when JobManager is running and accepting new jobs."""

    loaded_models: list[str] = Field(default_factory=list)
    """Model IDs currently resident in memory (ready for inference)."""

    cached_models: list[str] = Field(default_factory=list)
    """Model IDs whose checkpoints exist on disk (loadable without network)."""

    supported_languages: list[str] = Field(default_factory=lambda: ["en"])
    """Language codes supported by at least one cached model."""

    supported_voice_modes: list[str] = Field(default_factory=lambda: ["tts", "voice_clone"])
    """Synthesis modes exposed by the runtime."""

    device: str = "cpu"
    """Compute device in use: 'cuda:0' | 'mps' | 'cpu'."""

    memory_estimate_mb: float | None = None
    """Approximate VRAM/RAM consumed by loaded models, in megabytes."""

    max_concurrent_jobs: int = 1
    """Maximum simultaneous inference jobs the runtime will accept."""

    supported_output_formats: list[str] = Field(default_factory=lambda: ["wav"])
    """Audio formats the runtime can produce natively without post-processing."""

    warnings: list[str] = Field(default_factory=list)
    """Non-fatal advisories (low disk, no GPU, etc.)."""


class PreflightIssue(BaseModel):
    """A single pre-production check result."""

    severity: str
    """'error' (blocks production) or 'warning' (advisory only)."""

    code: str
    """Stable machine-readable error code for programmatic handling."""

    message: str
    """Human-readable description of the issue."""

    field: str | None = None
    """Optional field name that caused the issue (e.g. 'requested_formats')."""
