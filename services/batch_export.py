"""Batch Export Service for SRT, VTT, ZIP packaging, and Audio Merging."""

from __future__ import annotations

import json
import logging
import os
import uuid
import wave
import zipfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("chatterbox.batch_export")


def seconds_to_srt_time(seconds: float) -> str:
    """Format seconds into HH:MM:SS,mmm timestamp."""
    millis = int(round(seconds * 1000))
    hours = millis // (3600 * 1000)
    millis %= (3600 * 1000)
    minutes = millis // (60 * 1000)
    millis %= (60 * 1000)
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def seconds_to_vtt_time(seconds: float) -> str:
    """Format seconds into HH:MM:SS.mmm timestamp."""
    millis = int(round(seconds * 1000))
    hours = millis // (3600 * 1000)
    millis %= (3600 * 1000)
    minutes = millis // (60 * 1000)
    millis %= (60 * 1000)
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def build_srt_subtitles(lines_results: list[dict[str, Any]]) -> str:
    """Build valid SRT format text from lines results."""
    entries = []
    current_time = 0.0
    counter = 1

    for item in lines_results:
        if item.get("status") != "completed":
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue

        dur = float(item.get("duration_seconds") or 0.0)
        pause = float(item.get("pause_duration") or 0.5)

        start_s = item.get("start_seconds")
        end_s = item.get("end_seconds")

        if start_s is not None and end_s is not None:
            t_start = float(start_s)
            t_end = float(end_s)
        else:
            t_start = current_time
            t_end = current_time + dur
            current_time = t_end + pause

        entries.append(
            f"{counter}\n"
            f"{seconds_to_srt_time(t_start)} --> {seconds_to_srt_time(t_end)}\n"
            f"{text}\n"
        )
        counter += 1

    return "\n".join(entries)


def build_vtt_subtitles(lines_results: list[dict[str, Any]]) -> str:
    """Build valid WebVTT format text from lines results."""
    entries = ["WEBVTT\n"]
    current_time = 0.0
    counter = 1

    for item in lines_results:
        if item.get("status") != "completed":
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue

        dur = float(item.get("duration_seconds") or 0.0)
        pause = float(item.get("pause_duration") or 0.5)

        start_s = item.get("start_seconds")
        end_s = item.get("end_seconds")

        if start_s is not None and end_s is not None:
            t_start = float(start_s)
            t_end = float(end_s)
        else:
            t_start = current_time
            t_end = current_time + dur
            current_time = t_end + pause

        entries.append(
            f"{counter}\n"
            f"{seconds_to_vtt_time(t_start)} --> {seconds_to_vtt_time(t_end)}\n"
            f"{text}\n"
        )
        counter += 1

    return "\n".join(entries)


def export_batch_srt_file(lines_results: list[dict[str, Any]], output_path: Path) -> Path:
    """Write SRT subtitle file to destination path."""
    content = build_srt_subtitles(lines_results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def export_batch_vtt_file(lines_results: list[dict[str, Any]], output_path: Path) -> Path:
    """Write WebVTT subtitle file to destination path."""
    content = build_vtt_subtitles(lines_results)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


def create_batch_zip_package(
    job_id: str,
    output_zip_path: Path,
    manifest_data: dict[str, Any],
    merged_audio_path: Path | None = None,
    srt_path: Path | None = None,
    chunks_dir: Path | None = None,
) -> Path:
    """Create atomic ZIP export containing merged audio, SRT, line audio chunks, and manifest."""
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_zip = output_zip_path.with_suffix(f".tmp_{uuid.uuid4().hex[:8]}")

    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if merged_audio_path and merged_audio_path.exists():
                zf.write(merged_audio_path, arcname="merged.wav")

            if srt_path and srt_path.exists():
                zf.write(srt_path, arcname="subtitles.srt")

            if chunks_dir and chunks_dir.exists():
                for line_file in sorted(chunks_dir.glob("line_*.wav")):
                    zf.write(line_file, arcname=f"lines/{line_file.name}")

            zf.writestr("manifest.json", json.dumps(manifest_data, ensure_ascii=False, indent=2))

        os.replace(tmp_zip, output_zip_path)
        return output_zip_path
    except Exception:
        tmp_zip.unlink(missing_ok=True)
        raise


def merge_wav_files(file_paths: list[str | Path], output_path: str | Path, silence_sec: float = 0.5) -> bool:
    """Merge multiple WAV audio files sequentially with silence padding."""
    valid_paths = [Path(p) for p in file_paths if p and Path(p).exists()]
    if not valid_paths:
        return False

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    try:
        with wave.open(str(valid_paths[0]), "rb") as first:
            params = first.getparams()
            framerate = first.getframerate()
            nchannels = first.getnchannels()
            sampwidth = first.getsampwidth()

        silence_frames = int(framerate * float(silence_sec))
        silence_bytes = b"\x00" * (silence_frames * nchannels * sampwidth)

        with wave.open(str(out_p), "wb") as outfile:
            outfile.setparams(params)
            for idx, wpath in enumerate(valid_paths):
                with wave.open(str(wpath), "rb") as infile:
                    outfile.writeframes(infile.readframes(infile.getnframes()))
                if idx < len(valid_paths) - 1 and silence_sec > 0:
                    outfile.writeframes(silence_bytes)
        return True
    except Exception as e:
        logger.error("Could not merge WAV files: %s", e)
        return False
