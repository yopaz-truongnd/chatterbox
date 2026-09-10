"""Production Validation Data Contracts and Models (Phase 21).

Typed Pydantic models for real-runtime production validation requests, steps,
per-beat metrics, lineage artifacts, failures, and execution reports.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ValidationVerdict(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class ProductionValidationRequest(BaseModel):
    """Configuration and target parameters for a production validation run."""
    model_config = ConfigDict(extra="ignore")

    validation_profile_id: str | None = None
    script_path: str | None = None
    script_text: str | None = None
    provider: str = "local"
    model: str | None = None
    language: str = "en"
    voice_mode: str = "tts"
    reference_voice: str | None = None
    output_formats: list[str] = Field(default_factory=lambda: ["wav", "mp3"])
    mixing_profile: str | None = None
    mastering_profile: str | None = None
    loudness_target_lufs: float = -14.0
    require_narration_acceptance: bool = True
    require_final_approval: bool = True
    maximum_automatic_retries: int = 2
    minimum_free_disk_bytes: int = 524288000
    expected_duration_range_ms: dict[str, int] = Field(
        default_factory=lambda: {"min": 5000, "max": 180000}
    )
    runtime_timeout_seconds: int = 300
    run_incremental_reproduction: bool = True
    run_cancellation_tests: bool = False
    output_report_path: str | None = None


class ProductionValidationStep(BaseModel):
    """Tracked execution step during validation."""
    model_config = ConfigDict(extra="ignore")

    name: str
    status: str = "pending"  # pending, running, passed, failed, skipped, cancelled
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ProductionValidationBeatMetric(BaseModel):
    """Detailed performance and QC metrics for a single story beat."""
    model_config = ConfigDict(extra="ignore")

    beat_id: str
    text_length: int
    duration_ms: float
    render_duration_ms: float
    attempt_count: int
    selected_attempt: int | None = None
    qc_score: float = 0.0
    qc_verdict: str = "UNKNOWN"
    provider: str = "local"
    model: str = "nano"


class ProductionValidationMetric(BaseModel):
    """Aggregate duration, resource, and execution performance metrics."""
    model_config = ConfigDict(extra="ignore")

    validation_id: str
    started_at: str
    completed_at: str | None = None
    total_duration_ms: float = 0.0
    planning_duration_ms: float = 0.0
    render_duration_ms: float = 0.0
    qc_duration_ms: float = 0.0
    mix_duration_ms: float = 0.0
    master_duration_ms: float = 0.0
    export_duration_ms: float = 0.0
    beat_count: int = 0
    attempt_count: int = 0
    retry_count: int = 0
    qc_pass_count: int = 0
    qc_review_count: int = 0
    qc_failed_count: int = 0
    output_duration_ms: float = 0.0
    real_time_factor: float | None = None
    peak_memory_mb: float | None = None
    peak_gpu_memory_mb: float | None = None


class ProductionValidationArtifact(BaseModel):
    """Metadata and lineage verification details for a generated audio deliverable."""
    model_config = ConfigDict(extra="ignore")

    artifact_id: str
    file_name: str
    file_path: str  # Sanitized path relative to project
    sha256: str
    size_bytes: int
    format: str
    duration_ms: float | None = None
    sample_rate: int | None = None
    loudness_lufs: float | None = None
    verified_lineage: bool = True


class ProductionValidationFailure(BaseModel):
    """Structured failure record with error taxonomy."""
    model_config = ConfigDict(extra="ignore")

    step_name: str
    code: str
    message: str
    recoverable: bool = False


class ProductionValidationReport(BaseModel):
    """Comprehensive production validation report without private paths or secrets."""
    model_config = ConfigDict(extra="ignore")

    validation_id: str
    status: str = "running"  # running, completed, failed, cancelled
    verdict: ValidationVerdict = ValidationVerdict.PASS
    started_at: str
    completed_at: str | None = None
    total_duration_ms: float = 0.0
    machine_summary: dict[str, Any] = Field(default_factory=dict)
    runtime_capabilities: dict[str, Any] = Field(default_factory=dict)
    provider: str = "local"
    model: str = "nano"
    device: str = "cpu"
    project_id: str
    workflow_id: str | None = None
    operation_ids: list[str] = Field(default_factory=list)
    beat_count: int = 0
    attempt_count: int = 0
    retry_count: int = 0
    qc_pass_count: int = 0
    qc_review_count: int = 0
    qc_failed_count: int = 0
    planning_duration_ms: float = 0.0
    render_duration_ms: float = 0.0
    qc_duration_ms: float = 0.0
    mix_duration_ms: float = 0.0
    master_duration_ms: float = 0.0
    export_duration_ms: float = 0.0
    output_duration_ms: float = 0.0
    real_time_factor: float | None = None
    peak_memory_mb: float | None = None
    peak_gpu_memory_mb: float | None = None
    artifact_sizes: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    failures: list[ProductionValidationFailure] = Field(default_factory=list)
    steps: list[ProductionValidationStep] = Field(default_factory=list)
    per_beat_metrics: list[ProductionValidationBeatMetric] = Field(default_factory=list)
    artifacts: list[ProductionValidationArtifact] = Field(default_factory=list)
    incremental_reproduction_passed: bool | None = None
    cancellation_recovery_passed: bool | None = None
