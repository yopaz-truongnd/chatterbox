"""Voice Quality Control (QC) Service (Phase 9).

Performs 3-layer automated evaluation:
1. Signal QC (loudness, peak ceiling, clipping, silence ratio)
2. Content QC (Whisper/STT accuracy, missing words, hallucinations, proper noun risks)
3. Direction QC (WPM, pacing, duration tolerance vs StoryBeat direction)

Provides deterministic retry policies and candidate selection.
"""

from __future__ import annotations

import math
from pathlib import Path
import re
from typing import Any
import wave

from services.render_models import (
    BeatQCResult,
    ContentQCResult,
    DirectionQCResult,
    QCVerdict,
    RenderAttempt,
    SignalQCResult,
)
from services.voice_plan import Beat
from services.critic import evaluate_speech_content


# QC Weights
SIGNAL_WEIGHT = 0.30
CONTENT_WEIGHT = 0.50
DIRECTION_WEIGHT = 0.20


def evaluate_signal_qc(audio_path: str | Path) -> SignalQCResult:
    """Layer 1: Signal QC analyzing amplitude, clipping, silence, and duration."""
    path = Path(audio_path)
    if not path.exists():
        return SignalQCResult(
            passed=False,
            duration=0.0,
            peak_dbfs=-100.0,
            rms_dbfs=-100.0,
            clipping_detected=True,
            silence_ratio=1.0,
            issues=["Audio file does not exist"],
        )

    try:
        with wave.open(str(path), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            raw_bytes = wf.readframes(n_frames)

        duration = n_frames / max(1, framerate)
        if duration <= 0.05:
            return SignalQCResult(
                passed=False,
                duration=duration,
                issues=["Audio duration is zero or too short (<50ms)"],
            )

        # Decode 16-bit PCM samples
        if sampwidth == 2:
            import struct
            fmt = f"<{n_frames * n_channels}h"
            samples = struct.unpack(fmt, raw_bytes)
            max_val = 32768.0
        else:
            # Fallback
            samples = [0]
            max_val = 1.0

        if not samples:
            return SignalQCResult(passed=False, duration=duration, issues=["Empty audio samples"])

        abs_samples = [abs(s) / max_val for s in samples]
        peak = max(abs_samples)
        peak_dbfs = 20.0 * math.log10(max(1e-6, peak))

        # RMS calculation
        sum_sq = sum(s ** 2 for s in abs_samples)
        rms = math.sqrt(sum_sq / len(samples))
        rms_dbfs = 20.0 * math.log10(max(1e-6, rms))

        # Silence ratio (samples below -50dB)
        silence_threshold = 10.0 ** (-50.0 / 20.0)
        silent_count = sum(1 for s in abs_samples if s < silence_threshold)
        silence_ratio = silent_count / len(samples)

        clipping_detected = peak >= 0.999 or any(abs(s) >= 32765 for s in samples[:1000] if sampwidth == 2 and samples[0] == 32767)

        issues: list[str] = []
        warnings: list[str] = []

        if clipping_detected:
            issues.append(f"Severe clipping detected (peak {peak_dbfs:.1f} dBFS)")
        if rms_dbfs < -45.0:
            issues.append(f"Audio is nearly silent or too quiet (RMS {rms_dbfs:.1f} dBFS)")
        elif rms_dbfs > -10.0:
            warnings.append(f"Audio is slightly hot/loud (RMS {rms_dbfs:.1f} dBFS)")

        if silence_ratio > 0.65:
            issues.append(f"Excessive silence detected ({silence_ratio * 100:.1f}%)")

        passed = len(issues) == 0

        return SignalQCResult(
            passed=passed,
            duration=round(duration, 3),
            peak_dbfs=round(peak_dbfs, 2),
            rms_dbfs=round(rms_dbfs, 2),
            clipping_detected=clipping_detected,
            silence_ratio=round(silence_ratio, 3),
            issues=issues,
            warnings=warnings,
        )
    except Exception as exc:
        return SignalQCResult(
            passed=False,
            duration=0.0,
            issues=[f"Signal inspection failed: {exc}"],
        )


def evaluate_content_qc(
    audio_path: str | Path,
    reference_script: str,
    target_wpm: float | None = None,
    pronunciation_overrides: dict[str, str] | None = None,
) -> ContentQCResult:
    """Layer 2: Content QC comparing speech transcript against original Beat script text."""
    path = Path(audio_path)
    if not path.exists():
        return ContentQCResult(
            passed=False,
            wer=1.0,
            accuracy_percent=0.0,
            issues=["Audio file not found for content QC"],
        )

    # Use existing speech content evaluator from services/critic.py
    eval_res = evaluate_speech_content(
        audio_source=path,
        reference_text=reference_script,
        target_wpm=target_wpm,
    )

    transcription = eval_res.get("transcription", "")
    accuracy = float(eval_res.get("accuracy_percent", 100.0))
    wer = round(max(0.0, 1.0 - (accuracy / 100.0)), 3)
    missing = eval_res.get("missing_words", [])
    repeated = eval_res.get("repeated_words", [])
    actual_wpm = float(eval_res.get("actual_wpm", 138.0))
    issues = list(eval_res.get("issues", []))
    warnings = list(eval_res.get("warnings", []))

    # Pronunciation risk check: verify required proper nouns appear in transcript
    risk_flags: list[str] = []
    if pronunciation_overrides:
        hyp_lower = transcription.lower()
        for proper_noun in pronunciation_overrides.keys():
            # Check if proper noun or its phonetic parts exist
            noun_norm = proper_noun.lower()
            if noun_norm not in hyp_lower:
                risk_flags.append(f"Proper noun '{proper_noun}' might be mispronounced or omitted in transcript")
                warnings.append(f"Pronunciation check flag: {proper_noun}")

    passed = len(issues) == 0 and accuracy >= 70.0 and wer <= 0.30

    return ContentQCResult(
        passed=passed,
        wer=wer,
        accuracy_percent=accuracy,
        transcription=transcription,
        missing_words=missing,
        repeated_words=repeated,
        actual_wpm=actual_wpm,
        target_wpm=target_wpm,
        pronunciation_risk_flags=risk_flags,
        issues=issues,
        warnings=warnings,
    )


def evaluate_direction_qc(
    beat: Beat,
    actual_duration: float,
    actual_wpm: float,
) -> DirectionQCResult:
    """Layer 3: Direction QC evaluating duration tolerance and pace vs StoryBeat direction."""
    words = beat.script.text.split()
    word_count = max(1, len(words))

    # Target pace & target WPM
    voice_dir = beat.voice
    pace = voice_dir.pace or 1.0
    target_wpm = voice_dir.target_wpm or 138.0

    # Expected duration
    expected_dur = (word_count / (target_wpm / 60.0)) / pace
    # Add tolerance of +/- 35%
    dur_min = max(0.4, expected_dur * 0.65)
    dur_max = max(1.2, expected_dur * 1.45)

    issues: list[str] = []
    warnings: list[str] = []

    if actual_duration < dur_min:
        warnings.append(f"Beat rendered too fast ({actual_duration:.2f}s < min {dur_min:.2f}s)")
    elif actual_duration > dur_max:
        warnings.append(f"Beat rendered too slow ({actual_duration:.2f}s > max {dur_max:.2f}s)")

    passed = len(issues) == 0

    return DirectionQCResult(
        passed=passed,
        expected_duration_range=(round(dur_min, 2), round(dur_max, 2)),
        actual_duration=round(actual_duration, 2),
        expected_wpm=round(target_wpm, 1),
        actual_wpm=round(actual_wpm, 1),
        issues=issues,
        warnings=warnings,
    )


def evaluate_beat_qc(
    beat: Beat,
    audio_path: str | Path,
    attempt_id: int = 1,
    max_retries: int = 3,
    pronunciation_overrides: dict[str, str] | None = None,
) -> BeatQCResult:
    """Run full 3-layer Voice QC on a rendered StoryBeat audio attempt."""
    # 1. Signal QC
    signal_res = evaluate_signal_qc(audio_path)

    # 2. Content QC
    target_wpm = float(beat.voice.target_wpm) if beat.voice and beat.voice.target_wpm else None
    content_res = evaluate_content_qc(
        audio_path=audio_path,
        reference_script=beat.script.text,
        target_wpm=target_wpm,
        pronunciation_overrides=pronunciation_overrides,
    )

    # 3. Direction QC
    direction_res = evaluate_direction_qc(
        beat=beat,
        actual_duration=signal_res.duration,
        actual_wpm=content_res.actual_wpm,
    )

    # Compute overall QC score (0 - 100)
    sig_score = 100.0 if signal_res.passed else max(0.0, 100.0 - 30.0 * len(signal_res.issues))
    cnt_score = max(0.0, min(100.0, content_res.accuracy_percent - (15.0 * len(content_res.issues))))
    dir_score = 100.0 if direction_res.passed else 70.0

    qc_score = round(
        (sig_score * SIGNAL_WEIGHT) + (cnt_score * CONTENT_WEIGHT) + (dir_score * DIRECTION_WEIGHT),
        1,
    )

    # Determine Verdict & Retry Adjustment
    verdict: QCVerdict
    retry_reason: str | None = None
    retry_adjustment: dict[str, Any] | None = None

    if signal_res.passed and content_res.passed and direction_res.passed:
        verdict = QCVerdict.PASS
    else:
        # Failure detected
        all_issues = signal_res.issues + content_res.issues + direction_res.issues
        retry_reason = "; ".join(all_issues) if all_issues else "Quality score below threshold"

        if attempt_id < max_retries:
            verdict = QCVerdict.RETRY
            # Deterministic adjustment
            retry_adjustment = {}
            if content_res.missing_words or content_res.wer > 0.15:
                retry_adjustment["director_note"] = "Enunciate clearly and preserve every word without omission."
            if signal_res.clipping_detected:
                retry_adjustment["energy_adjustment"] = -0.5
            if direction_res.actual_duration > direction_res.expected_duration_range[1]:
                retry_adjustment["pace_multiplier"] = 1.10
            elif direction_res.actual_duration < direction_res.expected_duration_range[0]:
                retry_adjustment["pace_multiplier"] = 0.90
        else:
            # Exceeded retry budget
            if any(signal_res.clipping_detected or "silent" in i.lower() for i in signal_res.issues):
                verdict = QCVerdict.FAIL
            else:
                verdict = QCVerdict.NEEDS_REVIEW

    return BeatQCResult(
        beat_id=beat.id,
        attempt_id=attempt_id,
        signal=signal_res,
        content=content_res,
        direction=direction_res,
        verdict=verdict,
        qc_score=qc_score,
        retry_reason=retry_reason,
        retry_adjustment=retry_adjustment,
    )


def select_best_candidate(attempts: list[RenderAttempt]) -> RenderAttempt | None:
    """Deterministically select the best attempt among passing or candidate attempts.
    
    Ranking:
    1. Status is PASSED over others
    2. Highest QC score
    3. Lowest WER
    4. Lowest clipping risk
    5. Earliest attempt number
    """
    if not attempts:
        return None

    passed_attempts = [a for a in attempts if a.status == "passed" and a.qc_result]
    pool = passed_attempts if passed_attempts else [a for a in attempts if a.qc_result]

    if not pool:
        return attempts[-1]

    def _sort_key(att: RenderAttempt):
        qc = att.qc_result
        if not qc:
            return (0, 1.0, 100.0, -att.attempt)
        score = qc.qc_score
        wer = qc.content.wer
        peak = qc.signal.peak_dbfs
        return (score, -wer, -peak, -att.attempt)

    pool.sort(key=_sort_key, reverse=True)
    return pool[0]
