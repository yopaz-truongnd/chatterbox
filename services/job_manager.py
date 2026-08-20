"""Deadlock-free job manager, worker queue, and startup recovery service."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from job_store import AudioJob, JobPhase, JobStatus, JobStore, JobType, delete_job_artifacts
from services.audio import load_and_resample_audio, merge_speech_segments, mix_background_music, save_audio_wav
from services.inference import execute_model_inference, run_isolated_subprocess
from utils.platform_tools import clear_accelerator_cache

logger = logging.getLogger("chatterbox.job_manager")


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class JobManager:
    def __init__(self, data_dir: Path, project_dir: Path, device: str, cpu_threads: int, timeout_seconds: int = 240):
        self.data_dir = data_dir
        self.project_dir = project_dir
        self.device = device
        self.cpu_threads = cpu_threads
        self.timeout_seconds = timeout_seconds

        self.db_path = self.data_dir / "jobs.db"
        self.store = JobStore(self.db_path)

        # Separate explicit locks - NEVER nest locks
        self._jobs_lock = threading.Lock()
        self._proc_lock = threading.Lock()
        self._execution_lock = threading.Lock()

        self._jobs: dict[str, AudioJob] = {}
        self._active_procs: dict[str, subprocess.Popen] = {}
        self._job_queue: queue.Queue[str] = queue.Queue()

        self._worker_thread: threading.Thread | None = None
        self._running = False

    def startup(self) -> None:
        """Initialize store, recover uncompleted jobs, and start worker thread."""
        self.data_dir.joinpath("inputs").mkdir(parents=True, exist_ok=True)
        self.data_dir.joinpath("outputs").mkdir(parents=True, exist_ok=True)
        self.data_dir.joinpath("chunks").mkdir(parents=True, exist_ok=True)
        self.data_dir.joinpath("configs").mkdir(parents=True, exist_ok=True)

        # 1. Recover uncompleted jobs left from previous server crash/restart
        past_jobs = self.store.list_jobs(limit=200)
        recovered_count = 0
        with self._jobs_lock:
            for job in past_jobs:
                if job.status in ("queued", "processing"):
                    job.status = "failed"
                    job.phase = "failed"
                    job.completed_at = now_iso()
                    job.error = "Tiến trình server đã khởi động lại trước khi tác vụ hoàn thành (API restarted before job completed)"
                    self.store.save(job)
                    recovered_count += 1
                self._jobs[job.id] = job

        if recovered_count > 0:
            logger.info(f"[JobManager] 🔄 Đã cập nhật {recovered_count} job cũ chưa hoàn tất sang trạng thái 'failed'.")

        # 2. Start worker thread
        self._running = True
        self._worker_thread = threading.Thread(target=self._worker_loop, name="chatterbox-audio-worker", daemon=True)
        self._worker_thread.start()

    def shutdown(self) -> None:
        """Gracefully terminate any active subprocesses on server shutdown."""
        self._running = False
        with self._proc_lock:
            for jid, proc in list(self._active_procs.items()):
                try:
                    proc.terminate()
                    proc.wait(timeout=1.0)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            self._active_procs.clear()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def submit_job(self, job_type: JobType, params: dict, input_paths: list[str]) -> AudioJob:
        """Create and queue a new audio job in a deadlock-free manner."""
        job = AudioJob(
            id=uuid.uuid4().hex,
            type=job_type,
            params=params,
            input_paths=input_paths,
            status="queued",
            phase="queued",
            created_at=now_iso(),
        )

        with self._jobs_lock:
            self._jobs[job.id] = job
            self.store.save(job)

        self._job_queue.put(job.id)
        return job

    def get_job(self, job_id: str) -> AudioJob | None:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = self.store.get(job_id)
                if job:
                    self._jobs[job_id] = job
            return job

    def list_jobs(self, status: JobStatus | None = None, limit: int = 100) -> list[AudioJob]:
        return self.store.list_jobs(status=status, limit=limit)

    def cancel_job(self, job_id: str) -> tuple[bool, str]:
        """Cancel an active or queued job without deadlocking, terminating all parent and child chunk processes."""
        procs_to_kill: list[subprocess.Popen] = []

        # 1. Inspect state under jobs_lock
        with self._jobs_lock:
            job = self._jobs.get(job_id) or self.store.get(job_id)
            if job is None:
                return False, "Không tìm thấy job"

            if job.status in ("completed", "failed", "cancelled"):
                return True, f"Job đã ở trạng thái {job.status}"

            # Mark cancelled
            job.status = "cancelled"
            job.phase = "cancelled"
            job.completed_at = now_iso()
            job.error = "Người dùng đã hủy tác vụ"
            self.store.save(job)
            self._jobs[job_id] = job

        # 2. Terminate all matching parent and child processes outside of jobs_lock
        with self._proc_lock:
            for jid, proc in list(self._active_procs.items()):
                if jid == job_id or jid.startswith(f"{job_id}_"):
                    procs_to_kill.append(proc)

        for proc in procs_to_kill:
            try:
                proc.terminate()
                time.sleep(0.3)
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass

        return True, "Đã hủy tác vụ thành công"

    def save_completed_job(self, job: AudioJob) -> None:
        """Register a pre-completed job (such as a batch merge) cleanly into store and memory cache."""
        with self._jobs_lock:
            self._jobs[job.id] = job
            self.store.save(job)

    def delete_job(self, job_id: str) -> bool:
        """Delete job records and all associated artifacts safely."""
        # 1. Cancel if active
        self.cancel_job(job_id)

        output_path: str | None = None
        with self._jobs_lock:
            job = self._jobs.pop(job_id, None)
            if job and job.output_path:
                output_path = job.output_path
            self.store.delete(job_id)

        delete_job_artifacts(self.data_dir, job_id, output_path)
        return True

    def _update_job_status(self, job_id: str, **changes: Any) -> None:
        """Atomic update to in-memory job and SQLite store."""
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in changes.items():
                    setattr(job, k, v)
                self.store.save(job)

    def _register_proc(self, job_id: str, proc: subprocess.Popen) -> None:
        with self._proc_lock:
            self._active_procs[job_id] = proc

    def _unregister_proc(self, job_id: str) -> None:
        with self._proc_lock:
            self._active_procs.pop(job_id, None)

    def _worker_loop(self) -> None:
        while self._running:
            try:
                job_id = self._job_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._process_single_job(job_id)
            except Exception as exc:
                logger.error(f"[Worker] Uncaught exception processing {job_id}: {exc}", exc_info=True)
                self._update_job_status(job_id, status="failed", phase="failed", completed_at=now_iso(), error=str(exc))
            finally:
                self._job_queue.task_done()

    def _process_single_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job or job.status == "cancelled":
            return

        self._update_job_status(job_id, status="processing", phase="loading_model", progress_percent=5, started_at=now_iso())
        output_path = self.data_dir / "outputs" / f"{job.id}.wav"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Check in-process test mode
        in_process = (os.getenv("CHATTERBOX_IN_PROCESS", "0") == "1")

        try:
            if job.type in ("long-text", "batch"):
                with self._execution_lock:
                    success, err_msg = self._run_batch_job(job, output_path, in_process)
            elif in_process:
                with self._execution_lock:
                    wav, sr = execute_model_inference(job.type, job.params, self.device)
                    save_audio_wav(output_path, wav, sr)
                    dur = round(wav.shape[-1] / sr, 3)
                    self._update_job_status(job_id, duration_seconds=dur, phase="completed", progress_percent=100)
                    success, err_msg = True, None
            else:
                with self._execution_lock:
                    success, err_msg, benchmark = run_isolated_subprocess(
                        job_id=job.id,
                        job_type=job.type,
                        params=job.params,
                        output_path=output_path,
                        device=self.device,
                        cpu_threads=self.cpu_threads,
                        project_dir=self.project_dir,
                        data_dir=self.data_dir,
                        timeout_seconds=self.timeout_seconds,
                        progress_callback=lambda ph, pct, msg: self._update_job_status(job.id, phase=ph, progress_percent=pct),
                        line_progress_callback=lambda lp: self._handle_line_progress(job.id, lp),
                        benchmark_callback=lambda bm: self._update_job_status(job.id, benchmark=bm, duration_seconds=bm.get("audio_duration_seconds")),
                        register_proc_callback=self._register_proc,
                        unregister_proc_callback=self._unregister_proc,
                    )

            # Check if user cancelled during execution
            refreshed = self.get_job(job_id)
            if refreshed and refreshed.status == "cancelled":
                return

            if success and output_path.exists():
                self._update_job_status(
                    job_id,
                    status="completed",
                    phase="completed",
                    progress_percent=100,
                    completed_at=now_iso(),
                    output_path=str(output_path),
                )
            else:
                self._update_job_status(
                    job_id,
                    status="failed",
                    phase="failed",
                    completed_at=now_iso(),
                    error=err_msg or "Lỗi không xác định",
                )
        except Exception as exc:
            logger.error(f"[JobManager] Error executing {job_id}: {exc}", exc_info=True)
            self._update_job_status(job_id, status="failed", phase="failed", completed_at=now_iso(), error=str(exc))
        finally:
            for input_path in job.input_paths:
                Path(input_path).unlink(missing_ok=True)
            clear_accelerator_cache()

    def _handle_line_progress(self, job_id: str, line_data: dict) -> None:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if job:
                if job.benchmark is None:
                    job.benchmark = {}
                if "lines_results" not in job.benchmark:
                    job.benchmark["lines_results"] = []
                idx = line_data.get("line_idx")
                status = line_data.get("line_status") or line_data.get("status", "completed")
                dur = line_data.get("line_duration") or line_data.get("duration_seconds", 0.0)
                err = line_data.get("error")

                found = False
                for r in job.benchmark["lines_results"]:
                    if r.get("idx") == idx:
                        r["status"] = status
                        r["duration_seconds"] = dur
                        if err is not None:
                            r["error"] = err
                        found = True
                        break
                if not found:
                    entry = {
                        "idx": idx,
                        "status": status,
                        "duration_seconds": dur,
                    }
                    if err is not None:
                        entry["error"] = err
                    job.benchmark["lines_results"].append(entry)
                self.store.save(job)

    def _run_batch_job(self, job: AudioJob, output_path: Path, in_process: bool) -> tuple[bool, str | None]:
        """Execute all lines in a batch or long-text job loading the model ONCE."""
        params = job.params
        sub_model = params.get("model", "nano")
        pause_duration = float(params.get("pause_duration", 0.8))
        bgm_path = params.get("bgm_audio_path")
        bgm_vol = float(params.get("bgm_volume", 0.15))
        export_srt = bool(params.get("export_srt", True))
        chunks_dir = self.data_dir / "chunks" / job.id
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
                    wav, sr = execute_model_inference(sub_model, line_item, self.device)
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
                    # Strict original timeline: keep timestamps strictly as imported
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
                "device": self.device,
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
            if has_failures and len(chunk_wav_paths) == 0:
                self._update_job_status(
                    job.id,
                    benchmark=benchmark_data,
                    duration_seconds=0.0,
                    progress_percent=100,
                    phase="failed",
                    status="failed",
                    error="Toàn bộ các dòng trong kịch bản đều thất bại",
                )
                return False, "Toàn bộ các dòng trong kịch bản đều thất bại"

            self._update_job_status(
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
                device=self.device,
                cpu_threads=self.cpu_threads,
                project_dir=self.project_dir,
                data_dir=self.data_dir,
                timeout_seconds=self.timeout_seconds,
                progress_callback=lambda ph, pct, msg: self._update_job_status(job.id, phase=ph, progress_percent=pct),
                line_progress_callback=lambda lp: self._handle_line_progress(job.id, lp),
                benchmark_callback=lambda bm_data: self._update_job_status(job.id, benchmark=bm_data, duration_seconds=bm_data.get("audio_duration_seconds")),
                register_proc_callback=self._register_proc,
                unregister_proc_callback=self._unregister_proc,
            )
            return ok, err
