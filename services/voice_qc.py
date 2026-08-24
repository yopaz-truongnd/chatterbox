"""Voice Quality Control (QC) Service (Phase 9 & Phase 10B).

Thin adapter layer integrating with canonical AudioCandidateEvaluator:
- Reuses services.audio.evaluate_audio_signal for Signal QC.
- Reuses services.critic.evaluate_speech_content for Content QC.
- Integrates Direction QC layer and maps to BeatQCResult.
- Provides deterministic candidate ranking and retry adjustment.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import wave

from services.audio import evaluate_audio_signal, load_and_resample_audio
from services.audio_candidate_evaluator import (
    AudioCandidateEvaluator,
    CandidateEvaluation,
    evaluate_direction_layer,
    rank_candidates,
)
from services.critic import evaluate_speech_content
from services.render_models import (
    BeatQCResult,
    ContentQCResult,
    DirectionQCResult,
    QCVerdict,
    RenderAttempt,
    SignalQCResult,
)
from services.voice_plan import Beat


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

    tensor, err = load_and_resample_audio(path, target_sr=24000)
    if tensor is None or tensor.numel() == 0:
        return SignalQCResult(
            passed=False,
            duration=0.0,
            peak_dbfs=-100.0,
            rms_dbfs=-100.0,
            clipping_detected=True,
            silence_ratio=1.0,
            issues=[err or "Empty audio samples"],
        )

    eval_dict = evaluate_audio_signal(
        tensor,
        sample_rate=24000,
        min_rms_db=-38.0,
        max_rms_db=-10.0,
        max_silence_edge_s=0.35,
    )

    # Calculate silence ratio
    duration = eval_dict["duration_seconds"]
    lead = eval_dict.get("leading_silence_s", 0.0)
    trail = eval_dict.get("trailing_silence_s", 0.0)
    silence_ratio = round((lead + trail) / max(0.01, duration), 3) if duration > 0 else 1.0

    peak = eval_dict.get("peak", 0.0)
    peak_dbfs = round(20.0 * math.log10(max(1e-6, peak)), 2)
    rms_dbfs = eval_dict.get("rms_db", -100.0)

    clipping_detected = peak >= 0.995 or any("clipping" in i.lower() for i in eval_dict.get("issues", []))

    issues = list(eval_dict.get("issues", []))
    warnings = list(eval_dict.get("warnings", []))

    if silence_ratio > 0.65 and "Audio is silent" not in "".join(issues):
        issues.append(f"Excessive silence detected ({silence_ratio * 100:.1f}%)")

    passed = eval_dict.get("passed", False) and len(issues) == 0

    return SignalQCResult(
        passed=passed,
        duration=round(duration, 3),
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        clipping_detected=clipping_detected,
        silence_ratio=silence_ratio,
        issues=issues,
        warnings=warnings,
    )


def evaluate_content_qc(
    audio_path: str | Path,
    reference_script: str,
    target_wpm: float | None = None,
    pronunciation_overrides: dict[str, str] | None = None,
) -> ContentQCResult:
    """Layer 2: Content QC comparing Whisper ASR transcription against reference script."""
    eval_dict = evaluate_speech_content(
        audio_source=audio_path,
        sr=24000,
        reference_text=reference_script,
        target_wpm=target_wpm,
    )

    accuracy = float(eval_dict.get("accuracy_percent", 100.0))
    missing = eval_dict.get("missing_words", [])
    repeated = eval_dict.get("repeated_words", [])
    transcription = eval_dict.get("transcription", "")
    actual_wpm = int(eval_dict.get("actual_wpm", target_wpm or 138))

    ref_words = [w for w in reference_script.split() if w.strip()]
    ref_count = max(1, len(ref_words))
    wer = round(len(missing) / float(ref_count), 3)

    issues: list[str] = []
    warnings: list[str] = list(eval_dict.get("warnings", []))

    if missing:
        issues.append(f"Missing words: {', '.join(missing[:5])}")
    if repeated:
        issues.append(f"Repeated words: {', '.join(repeated[:5])}")

    # Check pronunciation risks
    proper_noun_risks: list[str] = []
    if pronunciation_overrides:
        for term in pronunciation_overrides:
            if term.lower() in reference_script.lower() and term.lower() not in transcription.lower():
                proper_noun_risks.append(term)
                warnings.append(f"Pronunciation term '{term}' may be mispronounced or missing")

    passed = (accuracy >= 85.0) and (wer <= 0.15) and (len(missing) == 0)

    return ContentQCResult(
        passed=passed,
        accuracy_percent=round(accuracy, 1),
        wer=wer,
        missing_words=missing,
        repeated_words=repeated,
        pronunciation_risk_flags=proper_noun_risks,
        transcription=transcription,
        actual_wpm=float(actual_wpm),
        target_wpm=float(target_wpm or 138),
        issues=issues,
        warnings=warnings,
    )


def evaluate_direction_qc(
    beat: Beat,
    actual_duration: float,
    actual_wpm: int | float,
) -> DirectionQCResult:
    """Layer 3: Direction QC comparing actual audio delivery vs StoryBeat direction."""
    target_wpm = beat.voice.target_wpm if beat.voice and beat.voice.target_wpm else 138
    pace = beat.voice.pace if beat.voice and beat.voice.pace else 1.0

    dir_dict = evaluate_direction_layer(
        duration=actual_duration,
        reference_text=beat.script.text,
        target_wpm=target_wpm,
        pace=pace,
        emotion=beat.voice.emotion if beat.voice else None,
        energy=beat.voice.energy if beat.voice else None,
    )

    expected_duration = dir_dict["expected_duration"]
    duration_tolerance = 0.35
    min_dur = round(expected_duration * (1.0 - duration_tolerance), 2)
    max_dur = round(expected_duration * (1.0 + duration_tolerance), 2)

    return DirectionQCResult(
        passed=dir_dict["passed"],
        expected_duration_range=(min_dur, max_dur),
        actual_duration=round(actual_duration, 2),
        expected_wpm=float(target_wpm),
        actual_wpm=float(actual_wpm),
        issues=dir_dict["issues"],
        warnings=dir_dict["warnings"],
    )


def evaluate_beat_qc(
    beat: Beat,
    audio_path: str | Path,
    attempt_id: int = 1,
    max_retries: int = 3,
    pronunciation_overrides: dict[str, str] | None = None,
) -> BeatQCResult:
    """Run canonical 3-layer Voice QC on a rendered StoryBeat audio attempt via AudioCandidateEvaluator."""
    evaluator = AudioCandidateEvaluator(profile="voice_director", auto_fix_signal=False)

    direction_params = {
        "target_wpm": beat.voice.target_wpm if beat.voice and beat.voice.target_wpm else 138,
        "pace": beat.voice.pace if beat.voice and beat.voice.pace else 1.0,
        "emotion": beat.voice.emotion if beat.voice else None,
        "energy": beat.voice.energy if beat.voice else None,
    }

    # Run evaluation ONCE (single Whisper ASR pass, single signal pass)
    cand_eval = evaluator.evaluate(
        audio_source=audio_path,
        reference_text=beat.script.text,
        direction=direction_params,
        pronunciation=pronunciation_overrides,
        sample_rate=24000,
    )

    # 1. Map directly to SignalQCResult from cand_eval.signal (Zero duplicate DSP)
    sig_data = cand_eval.signal
    duration = cand_eval.duration
    lead = sig_data.get("leading_silence_s", 0.0)
    trail = sig_data.get("trailing_silence_s", 0.0)
    silence_ratio = round((lead + trail) / max(0.01, duration), 3) if duration > 0 else 1.0
    peak = sig_data.get("peak", 0.0)
    peak_dbfs = round(20.0 * math.log10(max(1e-6, peak)), 2)
    rms_dbfs = sig_data.get("rms_db", -100.0)
    clipping_detected = peak >= 0.995 or any("clipping" in i.lower() for i in sig_data.get("issues", []))

    signal_res = SignalQCResult(
        passed=bool(sig_data.get("passed", False)),
        duration=duration,
        peak_dbfs=peak_dbfs,
        rms_dbfs=rms_dbfs,
        clipping_detected=clipping_detected,
        silence_ratio=silence_ratio,
        issues=list(sig_data.get("issues", [])),
        warnings=list(sig_data.get("warnings", [])),
    )

    # 2. Map directly to ContentQCResult from cand_eval.content (Zero duplicate Whisper ASR)
    cnt_data = cand_eval.content
    accuracy = float(cnt_data.get("accuracy_percent", 100.0))
    missing = list(cnt_data.get("missing_words", []))
    repeated = list(cnt_data.get("repeated_words", []))
    transcription = cnt_data.get("transcription", "")
    actual_wpm = float(cnt_data.get("actual_wpm", direction_params["target_wpm"]))
    ref_words = [w for w in beat.script.text.split() if w.strip()]
    wer = round(len(missing) / float(max(1, len(ref_words))), 3)

    pron_risks = list(cnt_data.get("pronunciation_risk_flags", []))
    if not pron_risks and pronunciation_overrides:
        for term in pronunciation_overrides:
            if term.lower() in beat.script.text.lower() and term.lower() not in transcription.lower():
                pron_risks.append(term)

    content_res = ContentQCResult(
        passed=bool(cnt_data.get("passed", False)),
        accuracy_percent=round(accuracy, 1),
        wer=wer,
        missing_words=missing,
        repeated_words=repeated,
        pronunciation_risk_flags=pron_risks,
        transcription=transcription,
        actual_wpm=actual_wpm,
        target_wpm=float(direction_params["target_wpm"]),
        issues=list(cnt_data.get("issues", [])),
        warnings=list(cnt_data.get("warnings", [])),
    )

    # 3. Map directly to DirectionQCResult from cand_eval.direction
    dir_data = cand_eval.direction or {}
    expected_dur = dir_data.get("expected_duration", duration)
    min_dur = round(expected_dur * 0.65, 2)
    max_dur = round(expected_dur * 1.35, 2)

    direction_res = DirectionQCResult(
        passed=bool(dir_data.get("passed", True)),
        expected_duration_range=(min_dur, max_dur),
        actual_duration=round(duration, 2),
        expected_wpm=float(direction_params["target_wpm"]),
        actual_wpm=float(dir_data.get("actual_wpm", actual_wpm)),
        issues=list(dir_data.get("issues", [])),
        warnings=list(dir_data.get("warnings", [])),
    )

    verdict: QCVerdict
    retry_reason: str | None = None
    retry_adjustment: dict[str, Any] | None = None

    if cand_eval.passed:
        verdict = QCVerdict.PASS
        retry_reason = None
        retry_adjustment = None
    else:
        all_issues = cand_eval.issues or (signal_res.issues + content_res.issues + direction_res.issues)
        retry_reason = "; ".join(all_issues) if all_issues else "Quality score below threshold"

        if attempt_id < max_retries:
            verdict = QCVerdict.RETRY
            retry_adjustment = cand_eval.retry_adjustment or {}
            if not retry_adjustment:
                if content_res.missing_words or content_res.wer > 0.15:
                    retry_adjustment["director_note"] = "Enunciate clearly and preserve every word without omission."
                if signal_res.clipping_detected:
                    retry_adjustment["energy_adjustment"] = -0.5
                if direction_res.actual_duration > direction_res.expected_duration_range[1]:
                    retry_adjustment["pace_multiplier"] = 1.10
                elif direction_res.actual_duration < direction_res.expected_duration_range[0]:
                    retry_adjustment["pace_multiplier"] = 0.90
        else:
            retry_adjustment = None
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
        qc_score=cand_eval.score,
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
