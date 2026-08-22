"""
Voice Critic Router - Exposes endpoint for voice quality analysis and spoken critique generation.
Delegates audio calculations and transcribing to services/critic.py.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, Form, HTTPException, status

from services.critic import analyze_audio_signals, transcribe_audio_whisper, generate_feedback
from routers.tts import save_upload, resolve_character_prompt

router = APIRouter(prefix="/api/v1/voice-critic", tags=["critic"])


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
        # 2. Analyze audio signals via service
        stats = analyze_audio_signals(audio_path)
        
        # 3. Transcribe speech using Whisper via service
        transcription = transcribe_audio_whisper(audio_path)
        
        # 4. Generate report, spoken text & structured evaluation via service
        report, spoken_feedback, structured_result = generate_feedback(stats, transcription, reference_text)
        
        # 5. Submit TTS job for the feedback speech
        coach_id = coach_character_id or "char_coach"
        try:
            audio_prompt_path, input_paths, voice_profile = await resolve_character_prompt(coach_id, None, f"coach_{uuid.uuid4().hex}")
        except Exception:
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
            "evaluation": structured_result,
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
