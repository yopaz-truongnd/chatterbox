"""Unified Audio Candidate Evaluator & Quality Policy (Phase 10B).

Provides canonical, shared evaluation across Batch Studio and Voice Director:
- Signal QC & auto-fix: Reuses services.audio (evaluate_audio_signal, auto_fix_audio_signal).
- Content QC: Reuses services.critic (evaluate_speech_content via Whisper ASR).
- Direction QC: Additive evaluation for pacing, target WPM, and duration tolerances.
- Configurable scoring profiles (default 60/40 vs voice_director 50/30/20).
- Deterministic candidate ranking and adaptive retry policies.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any, Sequence
import wave
from pydantic import BaseModel, Field
import torch

from services.audio import (
    auto_fix_audio_signal,
    evaluate_audio_signal,
    load_and_resample_audio,
    save_audio_wav,
)
from services.critic import evaluate_speech_content

logger = logging.getLogger(__name__)

# Canonical scoring weights by profile
SCORING_PROFILES: dict[str, dict[str, float]] = {
    "default": {
        "content": 0.60,
        "signal": 0.40,
        "direction": 0.00,
    },
    "voice_director": {
        "content": 0.50,
        "signal": 0.30,
        "direction": 0.20,
    },
}

# Canonical thresholds
DEFAULT_THRESHOLDS = {
    "max_wer": 0.15,
    "min_accuracy": 85.0,
    "min_score_pass": 75.0,
    "max_duration_deviation": 0.35,
    "extreme_duration_deviation": 0.50,
    "min_wpm": 50,
    "max_wpm": 260,
}


class CandidateEvaluation(BaseModel):
    """Canonical evaluation result for an audio candidate attempt."""
    model_config = {"arbitrary_types_allowed": True}

    passed: bool
    score: float
    profile: str = "default"
    audio_path: str = ""
    duration: float = 0.0
    sample_rate: int = 24000
    channels: int = 1
    fixed_tensor: Any | None = None

    signal: dict[str, Any] = Field(default_factory=dict)
    content: dict[str, Any] = Field(default_factory=dict)
    direction: dict[str, Any] | None = None

    retry_recommended: bool = False
    retry_reason: str | None = None
    retry_adjustment: dict[str, Any] | None = None
    fixable: bool = False
    needs_review: bool = False
    actions_taken: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def evaluate_direction_layer(
    duration: float,
    reference_text: str,
    target_wpm: int | None = None,
    pace: float | None = None,
    emotion: str | None = None,
    energy: float | None = None,
) -> dict[str, Any]:
    """Additive Direction QC evaluation comparing actual delivery against StoryBeat targets."""
    words = [w for w in reference_text.split() if w.strip()]
    word_count = len(words)
    effective_wpm = target_wpm or 138
    effective_pace = pace or 1.0

    # Calculate expected duration
    base_duration = (word_count / max(60, effective_wpm)) * 60.0
    expected_duration = max(0.5, round(base_duration / max(0.5, effective_pace), 2))

    actual_wpm = int(round((word_count / max(0.1, duration)) * 60.0))

    duration_deviation = abs(duration - expected_duration) / max(0.1, expected_duration)
    wpm_deviation = abs(actual_wpm - effective_wpm) / max(1, effective_wpm)

    issues: list[str] = []
    warnings: list[str] = []
    passed = True

    # Extreme failure thresholds
    if duration < expected_duration * 0.50:
        issues.append(f"Speech duration critically fast ({duration:.2f}s vs expected {expected_duration:.2f}s)")
        passed = False
    elif duration > expected_duration * 1.75:
        issues.append(f"Speech duration critically slow ({duration:.2f}s vs expected {expected_duration:.2f}s)")
        passed = False
    elif duration_deviation > DEFAULT_THRESHOLDS["max_duration_deviation"]:
        min_dur = round(expected_duration * (1.0 - DEFAULT_THRESHOLDS["max_duration_deviation"]), 2)
        max_dur = round(expected_duration * (1.0 + DEFAULT_THRESHOLDS["max_duration_deviation"]), 2)
        if duration < expected_duration:
            warnings.append(f"Beat rendered slightly fast ({duration:.2f}s < min {min_dur:.2f}s)")
        else:
            warnings.append(f"Beat rendered slightly slow ({duration:.2f}s > max {max_dur:.2f}s)")

    if actual_wpm < DEFAULT_THRESHOLDS["min_wpm"] or actual_wpm > DEFAULT_THRESHOLDS["max_wpm"]:
        issues.append(f"Extreme WPM pacing detected ({actual_wpm} WPM)")
        passed = False

    # Calculate direction score (0 - 100)
    dur_score = max(0.0, 100.0 - (duration_deviation * 100.0))
    wpm_score = max(0.0, 100.0 - (wpm_deviation * 80.0))
    direction_score = round(0.6 * dur_score + 0.4 * wpm_score, 1)

    return {
        "passed": passed,
        "score": direction_score,
        "actual_wpm": actual_wpm,
        "target_wpm": effective_wpm,
        "expected_duration": expected_duration,
        "actual_duration": round(duration, 2),
        "duration_deviation": round(duration_deviation, 3),
        "issues": issues,
        "warnings": warnings,
    }


def compute_retry_policy(
    signal_eval: dict[str, Any],
    content_eval: dict[str, Any],
    direction_eval: dict[str, Any] | None,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    """Determine deterministic retry recommendations and direction adjustments."""
    # 1. Content Omissions / Hallucinations
    missing_words = content_eval.get("missing_words", [])
    if missing_words:
        terms_str = ", ".join(f"'{w}'" for w in missing_words[:3])
        return (
            True,
            f"Content omission detected: missing {terms_str}",
            {"director_note": f"Articulate clearly and ensure all words are spoken: {terms_str}"},
        )

    repeated_words = content_eval.get("repeated_words", [])
    if repeated_words:
        terms_str = ", ".join(f"'{w}'" for w in repeated_words[:3])
        return (
            True,
            f"Stutter or repetition detected on {terms_str}",
            {"director_note": "Deliver line cleanly with natural continuous flow."},
        )

    # 2. Severe Signal Issues (Clipping or Silence)
    if not signal_eval.get("passed", True) and not signal_eval.get("fixable", False):
        if signal_eval.get("peak", 0.0) >= 0.99:
            return (
                True,
                "Severe audio clipping",
                {"energy_adjustment": -0.5, "director_note": "Reduce vocal projection and peak volume."},
            )
        return (
            True,
            "Critical audio signal defect",
            {"director_note": "Ensure clear, audible vocal tone."},
        )

    # 3. Severe Direction / Pacing Issues
    if direction_eval and not direction_eval.get("passed", True):
        actual_wpm = direction_eval.get("actual_wpm", 138)
        target_wpm = direction_eval.get("target_wpm", 138)
        if actual_wpm > target_wpm * 1.5:
            return (
                True,
                f"Delivery was too fast ({actual_wpm} WPM vs target {target_wpm} WPM)",
                {"pace_multiplier": 0.88, "director_note": "Slow down pacing and let phrases breathe."},
            )
        if actual_wpm < target_wpm * 0.6:
            return (
                True,
                f"Delivery was too slow ({actual_wpm} WPM vs target {target_wpm} WPM)",
                {"pace_multiplier": 1.12, "director_note": "Increase energy and speak with more momentum."},
            )

    return False, None, None


class AudioCandidateEvaluator:
    """Canonical evaluator for audio candidates across all Chatterbox workflows."""

    def __init__(self, profile: str = "default", auto_fix_signal: bool = True):
        self.profile = profile if profile in SCORING_PROFILES else "default"
        self.weights = SCORING_PROFILES[self.profile]
        self.auto_fix_signal = auto_fix_signal

    def evaluate(
        self,
        audio_source: str | Path | torch.Tensor,
        reference_text: str,
        direction: dict[str, Any] | None = None,
        pronunciation: dict[str, str] | None = None,
        sample_rate: int = 24000,
    ) -> CandidateEvaluation:
        """Evaluate audio candidate with unified signal, content, and optional direction layers."""
        audio_path_str = ""
        tensor: torch.Tensor | None = None
        sr = sample_rate

        if isinstance(audio_source, (str, Path)):
            audio_path = Path(audio_source)
            audio_path_str = str(audio_path)
            tensor, err = load_and_resample_audio(audio_path, target_sr=sample_rate)
        elif isinstance(audio_source, torch.Tensor):
            tensor = audio_source
        else:
            raise ValueError(f"Unsupported audio source type: {type(audio_source)}")

        if tensor is None or tensor.numel() == 0:
            return CandidateEvaluation(
                passed=False,
                score=0.0,
                profile=self.profile,
                audio_path=audio_path_str,
                issues=["Empty or unreadable audio source"],
            )

        duration = round(float(tensor.shape[-1]) / float(sr), 3)
        channels = tensor.shape[0] if tensor.dim() > 1 else 1

        # 1. Layer 1: Signal QC
        if self.profile == "default":
            # Canonical standard signal thresholds for Batch Studio
            initial_signal = evaluate_audio_signal(
                tensor,
                sample_rate=sr,
                min_rms_db=-28.0,
                max_rms_db=-14.0,
                max_silence_edge_s=0.15,
            )
        else:
            # Tolerant signal thresholds for Voice Director narration
            initial_signal = evaluate_audio_signal(
                tensor,
                sample_rate=sr,
                min_rms_db=-38.0,
                max_rms_db=-10.0,
                max_silence_edge_s=0.35,
            )
        final_signal = initial_signal
        actions_taken: list[str] = []

        if self.auto_fix_signal and not initial_signal.get("passed") and initial_signal.get("fixable"):
            fixed_tensor, actions_taken, final_signal = auto_fix_audio_signal(tensor, sample_rate=sr)
            if final_signal.get("passed"):
                tensor = fixed_tensor
                duration = round(float(tensor.shape[-1]) / float(sr), 3)
                # If audio was loaded from path, persist auto-fixed audio back
                if audio_path_str:
                    save_audio_wav(Path(audio_path_str), tensor, sr)

        # 2. Layer 2: Content QC (ASR Speech Critic)
        target_wpm = direction.get("target_wpm") if direction else None
        content_eval = evaluate_speech_content(
            audio_source=tensor,
            sr=sr,
            reference_text=reference_text,
            target_wpm=target_wpm,
        )

        # Check pronunciation risk flags
        if pronunciation:
            risk_flags = []
            transcription = content_eval.get("transcription", "").lower()
            for term in pronunciation.keys():
                if term.lower() in reference_text.lower() and term.lower() not in transcription:
                    risk_flags.append(term)
            content_eval["pronunciation_risk_flags"] = risk_flags

        # 3. Layer 3: Direction QC (Optional / Voice Director)
        direction_eval = None
        if direction is not None or self.profile == "voice_director":
            direction_eval = evaluate_direction_layer(
                duration=duration,
                reference_text=reference_text,
                target_wpm=direction.get("target_wpm") if direction else 138,
                pace=direction.get("pace") if direction else 1.0,
                emotion=direction.get("emotion") if direction else None,
                energy=direction.get("energy") if direction else None,
            )

        # 4. Scoring Synthesis
        signal_score = 100.0 if final_signal.get("passed", True) else 35.0
        content_score = float(content_eval.get("score", 100.0))
        direction_score = float(direction_eval.get("score", 100.0)) if direction_eval else 100.0

        w_content = self.weights["content"]
        w_signal = self.weights["signal"]
        w_direction = self.weights["direction"]

        total_score = round(
            (content_score * w_content) + (signal_score * w_signal) + (direction_score * w_direction),
            1,
        )

        # 5. Verdict & Threshold Checks
        issues: list[str] = []
        warnings: list[str] = []

        issues.extend(final_signal.get("issues", []))
        warnings.extend(final_signal.get("warnings", []))

        issues.extend(content_eval.get("issues", []))
        warnings.extend(content_eval.get("warnings", []))

        if direction_eval:
            issues.extend(direction_eval.get("issues", []))
            warnings.extend(direction_eval.get("warnings", []))

        signal_passed = bool(final_signal.get("passed", False))
        content_passed = bool(content_eval.get("passed", False))
        direction_passed = bool(direction_eval.get("passed", True)) if direction_eval else True

        passed = signal_passed and content_passed and direction_passed and (total_score >= DEFAULT_THRESHOLDS["min_score_pass"])

        # 6. Retry Policy
        retry_rec, retry_reason, retry_adj = compute_retry_policy(
            final_signal, content_eval, direction_eval
        )

        needs_review = not passed and not retry_rec

        # Package signal metadata structure compatible with both single & batch workflows
        signal_meta = dict(final_signal)
        signal_meta["initial"] = initial_signal
        signal_meta["actions"] = actions_taken
        signal_meta["final"] = final_signal

        return CandidateEvaluation(
            passed=passed,
            score=total_score,
            profile=self.profile,
            audio_path=audio_path_str,
            duration=duration,
            sample_rate=sr,
            channels=channels,
            fixed_tensor=tensor,
            signal=signal_meta,
            content=content_eval,
            direction=direction_eval,
            retry_recommended=retry_rec,
            retry_reason=retry_reason,
            retry_adjustment=retry_adj,
            fixable=bool(initial_signal.get("fixable", False)),
            needs_review=needs_review,
            actions_taken=actions_taken,
            issues=issues,
            warnings=warnings,
        )


def rank_candidates(
    evaluations: Sequence[CandidateEvaluation],
) -> list[CandidateEvaluation]:
    """Deterministic tie-breaking candidate ranking:

    1. passed (True > False)
    2. overall score (descending)
    3. content accuracy / WER (higher accuracy > lower accuracy)
    4. lower duration deviation
    5. earlier candidate order
    """
    def rank_key(cand_eval: CandidateEvaluation) -> tuple:
        passed_val = 1 if cand_eval.passed else 0
        score_val = cand_eval.score
        content_acc = cand_eval.content.get("accuracy_percent", 0.0)
        dur_dev = cand_eval.direction.get("duration_deviation", 0.0) if cand_eval.direction else 0.0
        return (passed_val, score_val, content_acc, -dur_dev)

    return sorted(evaluations, key=rank_key, reverse=True)
