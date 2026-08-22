"""
Batch Runner Service - Orchestrates execution of batch and long-text jobs.
Saves job manager code length and resolves responsibilities cleanly.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from job_store import AudioJob
from services.audio import load_and_resample_audio, merge_speech_segments, mix_background_music, save_audio_wav
from services.inference import run_isolated_subprocess

logger = logging.getLogger("chatterbox.batch_runner")


class BatchRunner:
    def __init__(self, job_manager):
        self.jm = job_manager

    def run_batch_job(self, job: AudioJob, output_path: Path, in_process: bool) -> tuple[bool, str | None]:
        """Execute all lines in a batch or long-text job loading the model ONCE."""
        params = job.params
        sub_model = params.get("model", "nano")
        pause_duration = float(params.get("pause_duration", 0.8))
        bgm_path = params.get("bgm_audio_path")
        bgm_vol = float(params.get("bgm_volume", 0.15))
        export_srt = bool(params.get("export_srt", True))
        chunks_dir = self.jm.data_dir / "chunks" / job.id
        chunks_dir.mkdir(parents=True, exist_ok=True)

        if job.type == "long-text":
            from utils.text_cleaner import split_text_preserving_content
            text = params.get("text", "")
            min_chars = int(params.get("min_chars", 200))
            max_chars = int(params.get("max_chars", 500))
            raw_chunks = split_text_preserving_content(text, min_chars, max_chars)
            lines = [{"idx": i, "text": c["text"], **params} for i, c in enumerate(raw_chunks)]
        else:
            lines = params.get("lines", [])

        total_lines = len(lines)
        if total_lines == 0:
            return False, "Kịch bản rỗng sau khi xử lý (0 dòng)"

        pause_durations_list = [float(item.get("pause_duration", pause_duration)) for item in lines]
        normalize_loudness_flag = bool(params.get("normalize_loudness", True))
        crossfade_ms_val = int(params.get("crossfade_ms", 30))
        bgm_ducking_flag = bool(params.get("bgm_ducking", True))
        stop_on_error = bool(params.get("stop_on_error", False))
        keep_original_timeline = bool(params.get("keep_original_timeline", False))

        batch_params = {
            **params,
            "lines": lines,
            "model": sub_model,
            "chunks_dir": str(chunks_dir),
            "merge": True,
            "pause_duration": pause_duration,
            "pause_durations": pause_durations_list,
            "bgm_audio_path": bgm_path,
            "bgm_volume": bgm_vol,
            "export_srt": export_srt,
            "normalize_loudness": normalize_loudness_flag,
            "crossfade_ms": crossfade_ms_val,
            "bgm_ducking": bgm_ducking_flag,
            "stop_on_error": stop_on_error,
            "keep_original_timeline": keep_original_timeline,
        }

        if in_process:
            successful_segments: list[tuple[Path, float, int]] = []
            lines_results = []
            t0_start = time.time()

            for i, line_item in enumerate(lines):
                line_idx = line_item.get("idx", i)
                line_out = chunks_dir / f"line_{line_idx:04d}.wav"
                line_pause = float(line_item.get("pause_duration", pause_duration))
                t0_line = time.time()
                try:
                    import services.job_manager
                    wav, sr = services.job_manager.execute_model_inference(sub_model, line_item, self.jm.device)
                    save_audio_wav(line_out, wav, sr)
                    dur = round(wav.shape[-1] / sr, 3)
                    successful_segments.append((line_out, line_pause, line_idx))
                    lines_results.append({
                        "idx": line_idx,
                        "status": "completed",
                        "audio_path": str(line_out),
                        "duration_seconds": dur,
                        "inference_seconds": round(time.time() - t0_line, 3),
                        "text": line_item.get("text", ""),
                        "pause_duration": line_pause,
                        "original_start_seconds": line_item.get("start_seconds"),
                        "original_end_seconds": line_item.get("end_seconds"),
                    })
                except Exception as exc:
                    lines_results.append({
                        "idx": line_idx,
                        "status": "failed",
                        "audio_path": None,
                        "duration_seconds": 0.0,
                        "inference_seconds": round(time.time() - t0_line, 3),
                        "text": line_item.get("text", ""),
                        "pause_duration": line_pause,
                        "error": str(exc),
                        "original_start_seconds": line_item.get("start_seconds"),
                        "original_end_seconds": line_item.get("end_seconds"),
                    })
                    if stop_on_error:
                        break

            total_dur = 0.0
            if successful_segments:
                tensors = []
                successful_pauses = []
                target_sr = 24000
                for p, p_pause, _ in successful_segments:
                    w, _ = load_and_resample_audio(p, target_sr)
                    if w is not None:
                        tensors.append(w)
                        successful_pauses.append(p_pause)

                if tensors:
                    merged_speech = merge_speech_segments(
                        tensors,
                        pause_duration=pause_duration,
                        pause_durations=successful_pauses,
                        target_sr=target_sr,
                        normalize=normalize_loudness_flag,
                        crossfade_ms=crossfade_ms_val,
                    )
                    if bgm_path and Path(bgm_path).exists():
                        merged_speech, _ = mix_background_music(
                            merged_speech,
                            bgm_path,
                            bgm_volume=bgm_vol,
                            target_sr=target_sr,
                            ducking=bgm_ducking_flag,
                        )

                    save_audio_wav(output_path, merged_speech, target_sr)
                    total_dur = round(merged_speech.shape[-1] / target_sr, 3)

            current_time = 0.0
            srt_lines = []
            slot_warnings = []

            def fmt_srt(t: float) -> str:
                t = max(0.0, t)
                hrs = int(t // 3600)
                mins = int((t % 3600) // 60)
                secs = int(t % 60)
                ms = int((t - int(t)) * 1000)
                return f"{hrs:02d}:{mins:02d}:{secs:02d},{ms:03d}"

            for idx, item in enumerate(lines_results):
                if item.get("status") == "failed":
                    item["start_seconds"] = 0.0
                    item["end_seconds"] = 0.0
                    continue

                p_len = item.get("pause_duration", pause_duration)

                if keep_original_timeline and item.get("original_start_seconds") is not None and item.get("original_end_seconds") is not None:
                    # Strict original timeline
                    start_s = float(item["original_start_seconds"])
                    end_s = float(item["original_end_seconds"])
                    slot_dur = max(0.01, end_s - start_s)
                    actual_dur = float(item["duration_seconds"])
                    if actual_dur > slot_dur:
                        slot_warnings.append(
                            f"Dòng {item['idx']+1}: Audio sinh ra ({actual_dur}s) dài hơn thời lượng timeline gốc ({slot_dur}s)"
                        )
                    item["start_seconds"] = round(start_s, 3)
                    item["end_seconds"] = round(end_s, 3)
                else:
                    start_s = current_time
                    end_s = start_s + item["duration_seconds"]
                    current_time = end_s + p_len

                    item["start_seconds"] = round(start_s, 3)
                    item["end_seconds"] = round(end_s, 3)

                if export_srt:
                    srt_lines.append(f"{idx+1}\n{fmt_srt(start_s)} --> {fmt_srt(end_s)}\n{item['text']}\n")

            if export_srt and srt_lines:
                with open(output_path.with_suffix(".srt"), "w", encoding="utf-8") as f:
                    f.write("\n".join(srt_lines))

            total_time = round(time.time() - t0_start, 3)
            rtf = round(total_time / max(0.01, total_dur), 3) if total_dur > 0 else 0.0
            ftr = round(total_dur / max(0.01, total_time), 2) if total_time > 0 else 0.0

            benchmark_data = {
                "device": self.jm.device,
                "model_type": sub_model,
                "total_lines": total_lines,
                "completed_lines": len([r for r in lines_results if r.get("status") == "completed"]),
                "failed_lines": len([r for r in lines_results if r.get("status") == "failed"]),
                "total_seconds": total_time,
                "audio_duration_seconds": total_dur,
                "realtime_factor": rtf,
                "faster_than_realtime": ftr,
                "slot_warnings": slot_warnings,
                "lines_results": lines_results,
            }
            has_failures = any(r.get("status") == "failed" for r in lines_results)
            if has_failures and len(successful_segments) == 0:
                self.jm._update_job_status(
                    job.id,
                    benchmark=benchmark_data,
                    duration_seconds=0.0,
                    progress_percent=100,
                    phase="failed",
                    status="failed",
                    error="Toàn bộ các dòng trong kịch bản đều thất bại",
                )
                return False, "Toàn bộ các dòng trong kịch bản đều thất bại"

            self.jm._update_job_status(
                job.id,
                benchmark=benchmark_data,
                duration_seconds=total_dur,
                progress_percent=100,
                phase="completed",
                output_path=str(output_path) if output_path.exists() else None,
            )
            return True, None

        else:
            ok, err, bm = run_isolated_subprocess(
                job_id=job.id,
                job_type="batch",
                params=batch_params,
                output_path=output_path,
                device=self.jm.device,
                cpu_threads=self.jm.cpu_threads,
                project_dir=self.jm.project_dir,
                data_dir=self.jm.data_dir,
                timeout_seconds=self.jm.timeout_seconds,
                progress_callback=lambda ph, pct, msg: self.jm._update_job_status(job.id, phase=ph, progress_percent=pct),
                line_progress_callback=lambda lp: self.jm._handle_line_progress(job.id, lp),
                benchmark_callback=lambda bm_data: self.jm._update_job_status(job.id, benchmark=bm_data, duration_seconds=bm_data.get("audio_duration_seconds")),
                register_proc_callback=self.jm._register_proc,
                unregister_proc_callback=self.jm._unregister_proc,
            )
            return ok, err
