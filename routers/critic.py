"""
Voice Critic Router - Analyzes pronunciation, pace, expressiveness, and volume.
Generates text feedback and reads it back via auto-triggered TTS.
"""

from __future__ import annotations

import os
import uuid
import re
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, status, Request

import numpy as np
import librosa
import pyloudnorm as pyln

from character_api import resolve_character_voice
from routers.tts import save_upload, resolve_character_prompt

router = APIRouter(prefix="/api/v1/voice-critic", tags=["critic"])

_whisper_model = None

def transcribe_audio_whisper(audio_path: Path) -> str:
    """Load Whisper tiny model dynamically to transcribe speech."""
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


def analyze_audio_signals(audio_path: Path) -> dict:
    """Analyze pitch variance, loudness, and duration of the audio."""
    y, sr = librosa.load(str(audio_path), sr=None)
    
    # 1. Loudness calculation
    meter = pyln.Meter(sr)
    try:
        loudness = meter.integrated_loudness(y)
    except Exception:
        loudness = -20.0
        
    # 2. Pitch (F0) variance
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), sr=sr
    )
    valid_f0 = f0[~np.isnan(f0)]
    if len(valid_f0) > 0:
        pitch_mean = float(np.mean(valid_f0))
        pitch_std = float(np.std(valid_f0))
    else:
        pitch_mean = 0.0
        pitch_std = 0.0
        
    duration = librosa.get_duration(y=y, sr=sr)
    
    return {
        "duration": duration,
        "loudness": loudness,
        "pitch_mean": pitch_mean,
        "pitch_std": pitch_std,
    }


def generate_feedback(stats: dict, transcription: str, reference_text: str | None = None) -> tuple[str, str]:
    """Generate detailed markdown feedback and a short spoken version for TTS."""
    duration = stats["duration"]
    loudness = stats["loudness"]
    pitch_std = stats["pitch_std"]
    
    # 1. Evaluate Loudness
    if loudness > -12:
        loudness_eval = "Âm lượng nói hơi lớn. Bạn nên nói nhỏ hơn hoặc đứng xa micro hơn một chút."
        loudness_short = "Nói hơi to."
    elif loudness < -26:
        loudness_eval = "Âm lượng nói hơi nhỏ. Bạn nên nói to hơn hoặc đứng gần micro hơn."
        loudness_short = "Nói hơi nhỏ."
    else:
        loudness_eval = "Âm lượng nói vừa phải, đạt tiêu chuẩn tốt."
        loudness_short = "Âm lượng tốt."

    # 2. Evaluate Pitch Variance (Expressiveness)
    if pitch_std > 50:
        express_eval = "Giọng đọc rất diễn cảm, có sự lên bổng xuống trầm tốt, thu hút người nghe."
        express_short = "Diễn cảm tốt."
    elif pitch_std < 15:
        express_eval = "Giọng đọc hơi đều đều (monotone), thiếu điểm nhấn cảm xúc. Bạn nên nhấn mạnh hơn vào các từ khóa chính."
        express_short = "Giọng đọc đều đều."
    else:
        express_eval = "Độ diễn cảm ở mức trung bình, tương đối tự nhiên."
        express_short = "Diễn cảm tự nhiên."

    # 3. Speech Rate (Pace)
    words = transcription.split()
    word_count = len(words)
    wpm = (word_count / duration) * 60 if duration > 0 else 0
    
    if wpm > 160:
        pace_eval = f"Tốc độ đọc khá nhanh ({int(wpm)} từ/phút). Bạn nên nói chậm lại một chút để người nghe dễ theo dõi."
        pace_short = "Đọc hơi nhanh."
    elif wpm < 90 and word_count > 2:
        pace_eval = f"Tốc độ đọc hơi chậm ({int(wpm)} từ/phút). Bạn có thể tăng nhẹ tốc độ đọc để câu nói mạch lạc hơn."
        pace_short = "Đọc hơi chậm."
    else:
        pace_eval = f"Tốc độ đọc vừa phải ({int(wpm)} từ/phút), rất dễ nghe."
        pace_short = "Tốc độ đọc vừa phải."

    # 4. Pronunciation & Text Comparison
    text_eval = ""
    missing_words = []
    if reference_text:
        ref_words = re.findall(r'\b\w+\b', reference_text.lower())
        hyp_words = re.findall(r'\b\w+\b', transcription.lower())
        
        missing_words = [w for w in ref_words if w not in hyp_words]
        if missing_words and len(ref_words) > 0:
            error_ratio = len(missing_words) / len(ref_words)
            if error_ratio > 0.3:
                text_eval = f"Có nhiều từ bị đọc thiếu hoặc đọc sai so với kịch bản gốc (thiếu khoảng {len(missing_words)} từ, ví dụ: '{', '.join(missing_words[:3])}')."
            else:
                text_eval = f"Phát âm khá chuẩn xác so với kịch bản, chỉ lệch hoặc thiếu một vài từ nhỏ (như '{', '.join(missing_words[:3])}')."
        else:
            text_eval = "Phát âm hoàn hảo, khớp hoàn toàn với kịch bản gốc."
    else:
        text_eval = "Không có kịch bản đối chiếu, hệ thống đã nhận diện được nội dung bạn nói."

    report = f"""### 🎙️ Kết Quả Đánh Giá Giọng Đọc

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

    # Spoken feedback formulation
    spoken_feedback = f"Nhận xét giọng đọc của bạn: {loudness_short} {express_short} {pace_short}."
    if reference_text and len(missing_words) > 0:
        spoken_feedback += " Có một số từ đọc sai hoặc bị thiếu so với kịch bản."
    else:
        spoken_feedback += " Mọi từ ngữ đều được phát âm rất rõ ràng."

    return report, spoken_feedback


@router.post("/evaluate", status_code=status.HTTP_202_ACCEPTED)
async def evaluate_voice_job(
    audio_file: UploadFile | None = File(None),
    job_id: str | None = Form(None),
    reference_text: str | None = Form(None),
    coach_character_id: str | None = Form(None),
) -> dict:
    from api_app import job_manager, RECOMMENDED_MODEL

    if not audio_file and not job_id:
        raise HTTPException(
            status_code=400,
            detail="Bạn phải cung cấp ít nhất một file âm thanh 'audio_file' hoặc ID tác vụ cũ 'job_id'."
        )

    # 1. Resolve Audio Path
    temp_path = None
    if job_id:
        job = job_manager.get_job(job_id)
        if not job or job.status != "completed" or not job.output_path:
            raise HTTPException(
                status_code=400,
                detail=f"Tác vụ với ID '{job_id}' không hợp lệ hoặc chưa hoàn tất thành công."
            )
        audio_path = Path(job.output_path)
        if not reference_text and "text" in job.params:
            reference_text = job.params["text"]
    else:
        # Save upload file
        critic_job_id = f"critic_upload_{uuid.uuid4().hex}"
        saved_str = await save_upload(audio_file, critic_job_id, "source")
        audio_path = Path(saved_str)
        temp_path = audio_path  # Keep track to delete it later

    try:
        # 2. Analyze audio signals
        stats = analyze_audio_signals(audio_path)
        
        # 3. Transcribe speech using Whisper
        transcription = transcribe_audio_whisper(audio_path)
        
        # 4. Generate report & spoken text
        report, spoken_feedback = generate_feedback(stats, transcription, reference_text)
        
        # 5. Submit TTS job for the feedback speech (if a coach is specified or defaults)
        coach_id = coach_character_id or "char_coach"
        try:
            audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(coach_id, None, f"coach_{uuid.uuid4().hex}")
        except Exception:
            # Fallback
            audio_prompt_path, input_paths, voice_profile = None, [], None
            
        feedback_job_id = f"coach_{uuid.uuid4().hex}"
        params = {
            "text": spoken_feedback,
            "character_id": coach_id,
            "audio_prompt_path": audio_prompt_path,
            "temperature": 0.7,
            "seed": 0,
            "top_k": 1000,
            "top_p": 0.95,
            "repetition_penalty": 1.2,
        }
        
        # Enqueue the TTS feedback job
        selected_model = RECOMMENDED_MODEL
        feedback_job = job_manager.submit_job(selected_model, params, input_paths)
        
        return {
            "status": "completed",
            "stats": stats,
            "transcription": transcription,
            "markdown_report": report,
            "spoken_feedback": spoken_feedback,
            "feedback_job_id": feedback_job.id,
            "feedback_audio_url": f"/api/v1/jobs/{feedback_job.id}/audio",
        }
    finally:
        # Cleanup uploaded temp file if we created one
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
