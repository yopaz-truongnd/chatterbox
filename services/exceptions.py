"""Domain exception hierarchy for Chatterbox TTS & Audio Services."""

from __future__ import annotations


class ChatterboxError(Exception):
    """Base exception for all Chatterbox errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(ChatterboxError):
    """Raised when user request parameters or script files are invalid."""
    pass


class ModelNotFoundError(ChatterboxError):
    """Raised when an unknown model name or unsupported model alias is requested."""
    pass


class CheckpointMissingError(ModelNotFoundError):
    """Raised when requested model weights are missing on disk and offline mode is active."""
    pass


class InferenceError(ChatterboxError):
    """Raised when model synthesis or voice conversion fails during inference."""
    pass


class OutOfMemoryError(InferenceError):
    """Raised when CPU/GPU runs out of memory during generation."""
    pass


class AudioProcessingError(ChatterboxError):
    """Raised when audio loading, merging, normalization, or BGM mixing fails."""
    pass


class JobTimeoutError(ChatterboxError):
    """Raised when a job exceeds the maximum allowed processing or inactivity timeout."""
    pass


class CharacterNotFoundError(ChatterboxError):
    """Raised when a specified character ID does not exist in the store."""
    pass
