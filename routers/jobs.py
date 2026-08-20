"""Job query, cancellation, deletion, audio download, and batch merge router."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

import torch
import torchaudio as ta
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from job_store import AudioJob, JobStatus
from services.audio import load_and_resample_audio, merge_speech_segments, mix_background_music, save_audio_wav

router = APIRouter(tags=["jobs"])


@router.get("/api/v1/jobs")
def list_jobs(job_status: Annotated[JobStatus | None, Query(alias="status")] = None) -> dict:
    from api_app import job_manager
    if not job_manager:
        return {"jobs": [], "count": 0}
    jobs = [job.public_dict() for job in job_manager.list_jobs(status=job_status, limit=100)]
    return {"jobs": jobs, "count": len(jobs)}


@router.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    from api_app import job_manager
    if not job_manager:
        raise HTTPException(status_code=404, detail="Hệ thống chưa sẵn sàng")
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    return job.public_dict()


@router.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    from api_app import job_manager
    if not job_manager:
        raise HTTPException(status_code=404, detail="Hệ thống chưa sẵn sàng")
    success, msg = job_manager.cancel_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=msg)
    return {"id": job_id, "status": "cancelled", "message": msg}


@router.delete("/api/v1/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    from api_app import job_manager
    if not job_manager:
        raise HTTPException(status_code=404, detail="Hệ thống chưa sẵn sàng")
    existing = job_manager.get_job(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    job_manager.delete_job(job_id)
    return {"id": job_id, "deleted": True}


@router.get("/api/v1/jobs/{job_id}/audio")
def download_audio(job_id: str) -> FileResponse:
    from api_app import job_manager
    if not job_manager:
        raise HTTPException(status_code=404, detail="Hệ thống chưa sẵn sàng")
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    if job.status != "completed" or not job.output_path:
        raise HTTPException(status_code=409, detail=f"Job chưa hoàn tất: {job.status}")
    output_path = Path(job.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=410, detail="File âm thanh không còn tồn tại")
    return FileResponse(output_path, media_type="audio/wav", filename=f"chatterbox-{job_id}.wav")


@router.get("/api/v1/jobs/{job_id}/lines/{line_idx}")
def download_line_audio(job_id: str, line_idx: int) -> FileResponse:
    from api_app import API_DATA_DIR, job_manager
    if not job_manager:
        raise HTTPException(status_code=404, detail="Hệ thống chưa sẵn sàng")
    line_path = API_DATA_DIR / "chunks" / job_id / f"line_{line_idx:04d}.wav"
    if not line_path.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file audio cho dòng {line_idx}")
    return FileResponse(line_path, media_type="audio/wav", filename=f"chatterbox-{job_id}-line-{line_idx}.wav")


@router.get("/api/v1/jobs/{job_id}/srt")
def download_job_srt(job_id: str) -> FileResponse:
    from api_app import API_DATA_DIR, job_manager
    if not job_manager:
        raise HTTPException(status_code=404, detail="Hệ thống chưa sẵn sàng")
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    srt_path = API_DATA_DIR / "outputs" / f"{job_id}.srt"
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy phụ đề SRT cho tác vụ này")
    return FileResponse(srt_path, media_type="text/plain", filename=f"chatterbox-{job_id}.srt")


@router.get("/api/v1/jobs/{job_id}/zip")
@router.get("/api/v1/jobs/{job_id}/export.zip")
def download_job_zip(job_id: str) -> FileResponse:
    import json
    import os
    import zipfile
    from api_app import API_DATA_DIR, job_manager

    if not job_manager:
        raise HTTPException(status_code=404, detail="Hệ thống chưa sẵn sàng")
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    if job.status != "completed":
        raise HTTPException(status_code=409, detail=f"Job chưa hoàn tất: {job.status}")

    zip_path = API_DATA_DIR / "outputs" / f"{job_id}.zip"
    srt_path = Path(job.output_path).with_suffix(".srt") if job.output_path else (API_DATA_DIR / "outputs" / f"{job_id}.srt")
    if not srt_path.exists():
        srt_path = API_DATA_DIR / "outputs" / f"{job_id}.srt"
    chunks_dir = API_DATA_DIR / "chunks" / job_id

    # 1. Check if existing ZIP is up to date with all source artifacts
    sources: list[Path] = []
    if job.output_path and Path(job.output_path).exists():
        sources.append(Path(job.output_path))
    if srt_path.exists():
        sources.append(srt_path)
    if chunks_dir.exists():
        sources.extend(list(chunks_dir.glob("line_*.wav")))
    meta_path = API_DATA_DIR / "outputs" / f"{job_id}.json"
    if meta_path.exists():
        sources.append(meta_path)

    latest_source_mtime = max((s.stat().st_mtime for s in sources), default=0.0)
    if zip_path.exists() and zip_path.stat().st_size > 0 and zip_path.stat().st_mtime >= latest_source_mtime:
        return FileResponse(zip_path, media_type="application/zip", filename=f"chatterbox-{job_id}-package.zip")

    # 2. Build ZIP atomically using temporary file to prevent corruption under concurrent requests
    tmp_zip = zip_path.with_suffix(f".tmp_{uuid.uuid4().hex[:8]}")
    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if job.output_path and Path(job.output_path).exists():
                zf.write(job.output_path, arcname="merged.wav")

            if srt_path.exists():
                zf.write(srt_path, arcname="subtitles.srt")

            if chunks_dir.exists():
                for line_file in sorted(chunks_dir.glob("line_*.wav")):
                    zf.write(line_file, arcname=f"lines/{line_file.name}")

            manifest = {
                "id": job.id,
                "type": job.type,
                "status": job.status,
                "duration_seconds": job.duration_seconds,
                "created_at": job.created_at,
                "completed_at": job.completed_at,
                "params": job.params,
                "benchmark": job.benchmark,
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        os.replace(tmp_zip, zip_path)
    except Exception:
        tmp_zip.unlink(missing_ok=True)
        raise

    return FileResponse(zip_path, media_type="application/zip", filename=f"chatterbox-{job_id}-package.zip")



@router.post("/api/v1/audio/merge", tags=["audio"])
@router.post("/api/v1/batch/merge", tags=["audio"])
async def merge_audio_jobs(
    request: Request,
    job_ids: Annotated[str | None, Form()] = None,
    pause_duration: Annotated[float, Form(ge=0.0, le=5.0)] = 0.8,
    bgm_file: Annotated[UploadFile | None, File()] = None,
    bgm_volume: Annotated[float, Form(ge=0.0, le=1.0)] = 0.15,
) -> dict:
    """Ghép nối nhiều đoạn audio từ các job TTS thành 1 file hoàn chỉnh kèm khoảng lặng và nhạc nền BGM."""
    from api_app import API_DATA_DIR, job_manager

    content_type = request.headers.get("content-type", "")
    target_job_ids = []
    if "application/json" in content_type:
        try:
            body = await request.json()
            target_job_ids = body.get("job_ids", [])
            if "pause_duration" in body:
                pause_duration = float(body["pause_duration"])
            if "bgm_volume" in body:
                bgm_volume = float(body["bgm_volume"])
        except Exception:
            pass
    elif job_ids:
        target_job_ids = [j.strip() for j in job_ids.split(",") if j.strip()]

    if not target_job_ids:
        raise HTTPException(status_code=400, detail="Danh sách job_ids không được để trống")

    chunks = []
    target_sr = 24000
    for jid in target_job_ids:
        job = job_manager.get_job(jid) if job_manager else None
        if not job or job.status != "completed" or not job.output_path:
            continue
        wav, err = load_and_resample_audio(job.output_path, target_sr)
        if wav is not None:
            chunks.append(wav)

    if not chunks:
        raise HTTPException(status_code=404, detail="Không tìm thấy file audio hợp lệ từ các job đã chọn")

    merged_speech = merge_speech_segments(chunks, pause_duration=pause_duration, target_sr=target_sr)

    # Optional BGM mixing with explicit warning capture
    warning_msg = None
    if bgm_file is not None and bgm_file.filename:
        from routers.tts import save_upload
        bgm_temp = await save_upload(bgm_file, uuid.uuid4().hex, "bgm")
        try:
            merged_speech, warning_msg = mix_background_music(merged_speech, bgm_temp, bgm_volume, target_sr)
        finally:
            Path(bgm_temp).unlink(missing_ok=True)

    merge_id = f"merge_{uuid.uuid4().hex[:10]}"
    out_file = API_DATA_DIR / "outputs" / f"{merge_id}.wav"
    save_audio_wav(out_file, merged_speech, target_sr)

    total_duration = round(merged_speech.shape[-1] / target_sr, 2)
    now_iso_str = job_manager.now_iso() if hasattr(job_manager, "now_iso") else ""
    from datetime import UTC, datetime
    if not now_iso_str:
        now_iso_str = datetime.now(UTC).isoformat()

    merge_job = AudioJob(
        id=merge_id,
        type="tts",
        params={"merged_from_count": len(chunks), "pause_duration": pause_duration},
        input_paths=[],
        status="completed",
        phase="completed",
        progress_percent=100,
        created_at=now_iso_str,
        completed_at=now_iso_str,
        output_path=str(out_file),
        duration_seconds=total_duration,
    )
    if job_manager:
        job_manager.save_completed_job(merge_job)

    result = {
        "id": merge_id,
        "audio_url": f"/api/v1/jobs/{merge_id}/audio",
        "duration_seconds": total_duration,
        "chunks_count": len(chunks),
        "message": f"Đã ghép thành công {len(chunks)} đoạn audio thành 1 file hoàn chỉnh ({total_duration}s)!",
    }
    if warning_msg:
        result["warning"] = warning_msg
    return result
