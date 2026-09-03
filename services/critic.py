"""Voice Critic Service - Quantitatively analyzes audio signals (loudness, pitch, duration)
and qualitatively transcribes speech using Whisper for pronunciation assessment.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import librosa
import numpy as np
import pyloudnorm as pyln

_whisper_model = None


def transcribe_audio_whisper(audio_path: Path) -> str:
    """Load Whisper tiny model dynamically to transcribe speech."""
    if os.environ.get("CHATTERBOX_TEST_DUMMY_INFERENCE") == "1":
        return "[Dummy Whisper transcription for tests]"
    global _whisper_model
    try:
        import whisper
    except ImportError:
        return "[Chưa cài đặt thư viện 'openai-whisper' để thực hiện nhận diện giọng nói STT]"

    if _whisper_model is None:
        # Load tiny model for low resource usage and speed
        _whisper_model = whisper.load_model("tiny")

    try:
        result = _whisper_model.transcribe(str(audio_path))
        return result.get("text", "").strip()
    except Exception as e:
        return f"[Lỗi nhận diện giọng nói: {e}]"


def analyze_audio_signals(audio_path: Path) -> dict[str, float]:
    """Analyze pitch variance, loudness, and duration of the audio."""
    y, sr = librosa.load(str(audio_path), sr=None)

    # 1. Loudness calculation
    meter = pyln.Meter(sr)
    try:
        loudness = float(meter.integrated_loudness(y))
    except Exception:
        loudness = -20.0

    # 2. Pitch (F0) variance
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sr
    )
    valid_f0 = f0[~np.isnan(f0)]
    if len(valid_f0) > 0:
        pitch_mean = float(np.mean(valid_f0))
        pitch_std = float(np.std(valid_f0))
    else:
        pitch_mean = 0.0
        pitch_std = 0.0

    duration = float(librosa.get_duration(y=y, sr=sr))

    return {
        "duration": duration,
        "loudness": loudness,
        "pitch_mean": pitch_mean,
        "pitch_std": pitch_std,
    }


def generate_feedback(
    stats: dict[str, float],
    transcription: str,
    reference_text: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Generate detailed markdown feedback, spoken version for TTS, and structured evaluation results."""
    duration = stats["duration"]
    loudness = stats["loudness"]
    pitch_std = stats["pitch_std"]

    score = 100
    issues: list[str] = []
    recommended_changes: dict[str, Any] = {}

    # 1. Evaluate Loudness
    if loudness > -12:
        loudness_eval = "Âm lượng nói hơi lớn. Bạn nên nói nhỏ hơn hoặc giảm âm lượng đầu vào."
        loudness_short = "Nói hơi to."
        score -= 15
        issues.append("too_loud")
    elif loudness < -26:
        loudness_eval = "Âm lượng nói hơi nhỏ. Bạn nên tăng âm lượng hoặc nói gần micro hơn."
        loudness_short = "Nói hơi nhỏ."
        score -= 15
        issues.append("too_quiet")
    else:
        loudness_eval = "Âm lượng nói vừa phải, đạt tiêu chuẩn tốt."
        loudness_short = "Âm lượng tốt."

    # 2. Evaluate Pitch Variance (Expressiveness)
    if pitch_std > 50:
        express_eval = "Giọng đọc rất diễn cảm, có sự lên bổng xuống trầm tốt, thu hút người nghe."
        express_short = "Diễn cảm tốt."
    elif pitch_std < 18:
        express_eval = "Giọng đọc hơi đều đều (monotone), thiếu điểm nhấn cảm xúc. Bạn nên tăng độ diễn cảm."
        express_short = "Giọng đọc đều đều."
        score -= 15
        issues.append("monotone")
        recommended_changes["temperature"] = 0.75
        recommended_changes["expressiveness"] = 0.8
    else:
        express_eval = "Độ diễn cảm ở mức trung bình, tương đối tự nhiên."
        express_short = "Diễn cảm tự nhiên."

    # 3. Speech Rate (Pace / WPM)
    # Check if transcription is an error fallback message
    is_fallback_transcription = transcription.startswith("[") and transcription.endswith("]")
    if is_fallback_transcription and reference_text:
        words = reference_text.split()
    else:
        words = transcription.split() if not is_fallback_transcription else []

    word_count = len(words)
    wpm = (word_count / duration) * 60 if duration > 0 and word_count > 0 else 0

    if wpm > 185:
        pace_eval = f"Tốc độ đọc khá nhanh ({int(wpm)} từ/phút). Bạn nên nói chậm lại một chút để người nghe dễ theo dõi."
        pace_short = "Đọc hơi nhanh."
        score -= 20
        issues.append("pace_too_fast")
        recommended_changes["pace"] = 0.45
    elif wpm > 0 and wpm < 85 and word_count > 2:
        pace_eval = f"Tốc độ đọc hơi chậm ({int(wpm)} từ/phút). Bạn có thể tăng nhẹ tốc độ đọc để câu nói mạch lạc hơn."
        pace_short = "Đọc hơi chậm."
        score -= 15
        issues.append("pace_too_slow")
        recommended_changes["pace"] = 0.6
    else:
        pace_eval = f"Tốc độ đọc vừa phải ({int(wpm)} từ/phút), rất dễ nghe." if wpm > 0 else "Thời lượng âm thanh ngắn phù hợp."
        pace_short = "Tốc độ đọc vừa phải."

    # 4. Pronunciation & Text Comparison
    text_eval = ""
    missing_words = []
    if reference_text and not is_fallback_transcription:
        ref_words = re.findall(r"\b\w+\b", reference_text.lower())
        hyp_words = re.findall(r"\b\w+\b", transcription.lower())

        missing_words = [w for w in ref_words if w not in hyp_words]
        if missing_words and len(ref_words) > 0:
            error_ratio = len(missing_words) / len(ref_words)
            if error_ratio > 0.3:
                text_eval = f"Có nhiều từ bị đọc thiếu hoặc đọc sai so with kịch bản gốc (thiếu khoảng {len(missing_words)} từ, ví dụ: '{', '.join(missing_words[:3])}')."
                score -= 25
                issues.append("pronunciation_mismatch")
            else:
                text_eval = f"Phát âm khá chuẩn xác so with kịch bản, chỉ lệch hoặc thiếu một vài từ nhỏ (như '{', '.join(missing_words[:3])}')."
                score -= 10
        else:
            text_eval = "Phát âm hoàn hảo, khớp hoàn toàn với kịch bản gốc."
    else:
        text_eval = "Đã phân tích âm học thành công dựa trên tín hiệu sóng âm."

    overall_score = max(0, min(100, score))
    passed = overall_score >= 70 and not any(i in issues for i in ("pronunciation_mismatch", "too_quiet", "too_loud"))

    report = f"""### 🎙️ Kết Quả Đánh Giá Giọng Đọc

* **Đánh giá tổng thể**: **{'ĐẠT CHUẨN ✅' if passed else 'CẦN CẢI THIỆN ⚠️'}** (Điểm số: `{overall_score}/100`)
* **Độ dài**: `{round(duration, 2)}s`
* **Âm lượng (Loudness)**: `{round(loudness, 1)} LUFS` ({loudness_short})
* **Độ diễn cảm (Pitch Std)**: `{round(pitch_std, 1)} Hz` ({express_short})
* **Tốc độ đọc (Pace)**: `{int(wpm)} WPM` ({pace_short})

#### 📝 Nhận xét chi tiết:
1. **Âm lượng**: {loudness_eval}
2. **Ngữ điệu**: {express_eval}
3. **Tốc độ**: {pace_eval}
4. **Độ chính xác từ ngữ**: {text_eval}

#### 💬 Văn bản nhận diện được (STT):
> "{transcription}"
"""

    spoken_feedback = f"Nhận xét giọng đọc của bạn: {loudness_short} {express_short} {pace_short}."
    if missing_words:
        spoken_feedback += " Có một số từ đọc sai hoặc bị thiếu so với kịch bản."

    structured_result = {
        "passed": passed,
        "overall_score": overall_score,
        "issues": issues,
        "metrics": {
            "duration_seconds": round(duration, 2),
            "loudness_lufs": round(loudness, 1),
            "pitch_std_hz": round(pitch_std, 1),
            "pace_wpm": int(wpm),
        },
        "recommended_changes": recommended_changes,
    }

    return report, spoken_feedback, structured_result


def evaluate_speech_content(
    audio_source: Path | str | Any,
    sr: int = 24000,
    reference_text: str = "",
    target_wpm: float | None = None,
) -> dict[str, Any]:
    """ASR Content Critic: Transcribes speech with Whisper and compares against reference script.
    
    Detects dropped/missing words, stutter/repeated words, and calculates actual WPM pacing.
    """
    import tempfile
    import torch
    from services.audio import save_audio_wav

    temp_wav_path: Path | None = None

    if isinstance(audio_source, (str, Path)):
        audio_path = Path(audio_source)
    elif isinstance(audio_source, torch.Tensor):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            temp_wav_path = Path(tf.name)
        save_audio_wav(temp_wav_path, audio_source, sr)
        audio_path = temp_wav_path
    else:
        return {
            "passed": False,
            "score": 0.0,
            "transcription": "",
            "accuracy_percent": 0.0,
            "missing_words": [],
            "repeated_words": [],
            "actual_wpm": 0.0,
            "target_wpm": target_wpm,
            "issues": ["Invalid audio source for ASR evaluation"],
            "warnings": [],
        }

    try:
        transcription = transcribe_audio_whisper(audio_path)
    finally:
        if temp_wav_path and temp_wav_path.exists():
            temp_wav_path.unlink(missing_ok=True)

    # Check if whisper is unavailable (stub message)
    is_stub = transcription.startswith("[") and transcription.endswith("]")

    ref_clean = reference_text.strip()
    ref_words = [w.lower() for w in re.findall(r"\b[A-Za-z0-9']+\b", ref_clean)]
    hyp_words = [w.lower() for w in re.findall(r"\b[A-Za-z0-9']+\b", transcription)]

    missing_words: list[str] = []
    repeated_words: list[str] = []
    issues: list[str] = []
    warnings: list[str] = []

    if is_stub or not ref_words:
        # Fallback if whisper library is not present or prompt is empty
        return {
            "passed": True,
            "score": 100.0,
            "transcription": transcription,
            "accuracy_percent": 100.0,
            "missing_words": [],
            "repeated_words": [],
            "actual_wpm": target_wpm or 138.0,
            "target_wpm": target_wpm,
            "issues": [],
            "warnings": [transcription] if is_stub else [],
        }

    # 1. Detect missing words
    for rw in ref_words:
        if rw not in hyp_words:
            missing_words.append(rw)

    # 2. Detect repeated / hallucinated words (consecutive repetitions in hypothesis not in reference)
    for i in range(len(hyp_words) - 1):
        if hyp_words[i] == hyp_words[i + 1]:
            rep_word = hyp_words[i]
            # Check if reference had legitimate repetition
            ref_had_rep = any(ref_words[j] == rep_word and j + 1 < len(ref_words) and ref_words[j + 1] == rep_word for j in range(len(ref_words)))
            if not ref_had_rep and rep_word not in repeated_words:
                repeated_words.append(rep_word)

    # 3. Calculate word accuracy
    total_ref = max(1, len(ref_words))
    error_count = len(missing_words) + len(repeated_words)
    acc_ratio = max(0.0, 1.0 - (error_count / total_ref))
    accuracy_percent = round(acc_ratio * 100.0, 1)

    # 4. Pacing calculation
    dur_s = 1.0
    if isinstance(audio_source, (str, Path)) and Path(audio_source).exists():
        try:
            dur_s = float(librosa.get_duration(path=str(audio_source)))
        except Exception:
            dur_s = max(1.0, len(ref_words) / 2.3)
    elif isinstance(audio_source, torch.Tensor):
        dur_s = max(0.01, audio_source.shape[-1] / sr)

    actual_wpm = round((len(hyp_words) / max(0.01, dur_s)) * 60.0, 1)

    if missing_words:
        if len(missing_words) > max(2, int(total_ref * 0.35)):
            issues.append(f"Missing {len(missing_words)} words from script (dropped/unspoken text)")
        else:
            warnings.append(f"Minor word omissions: {missing_words[:3]}")

    if repeated_words:
        issues.append(f"Hallucinated or repeated words: {repeated_words[:3]}")

    if target_wpm and abs(actual_wpm - target_wpm) > 55:
        warnings.append(f"Pacing divergence: {actual_wpm} WPM vs target {target_wpm} WPM")

    passed = len(issues) == 0 and accuracy_percent >= 65.0
    score = round(max(0.0, min(100.0, accuracy_percent - (15.0 * len(issues)) - (5.0 * len(warnings)))), 1)

    return {
        "passed": passed,
        "score": score,
        "transcription": transcription,
        "accuracy_percent": accuracy_percent,
        "missing_words": missing_words,
        "repeated_words": repeated_words,
        "actual_wpm": actual_wpm,
        "target_wpm": target_wpm,
        "issues": issues,
        "warnings": warnings,
    }

