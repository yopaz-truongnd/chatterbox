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

from job_store import AudioJob, JobPhase, JobStatus, JobStore, JobType
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
        """Delete job records and files safely."""
        # 1. Cancel if active
        self.cancel_job(job_id)

        output_path: str | None = None
        with self._jobs_lock:
            job = self._jobs.pop(job_id, None)
            if job and job.output_path:
                output_path = job.output_path
            self.store.delete(job_id)

        if output_path:
            Path(output_path).unlink(missing_ok=True)

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

        # Check in-process test mode
        in_process = (os.getenv("CHATTERBOX_IN_PROCESS", "0") == "1")

        try:
            if job.type == "long-text":
                with self._execution_lock:
                    success, err_msg = self._run_long_text(job, output_path, in_process)
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
            self._update_job_status(job_id, status="failed", phase="failed", completed_at=now_iso(), error=str(exc))
        finally:
            for input_path in job.input_paths:
                Path(input_path).unlink(missing_ok=True)
            clear_accelerator_cache()

    def _run_long_text(self, job: AudioJob, output_path: Path, in_process: bool) -> tuple[bool, str | None]:
        """Split text, synthesize chunks sequentially, and merge into single WAV."""
        params = job.params
        text = params.get("text", "")
        min_chars = int(params.get("min_chars", 200))
        max_chars = int(params.get("max_chars", 500))
        pause_duration = float(params.get("pause_duration", 0.6))
        sub_model = params.get("model", "nano")

        from utils.text_cleaner import split_text_preserving_content
        chunks = split_text_preserving_content(text, min_chars, max_chars)
        total_chunks = len(chunks)
        if total_chunks == 0:
            return False, "Văn bản rỗng sau khi phân tách"

        temp_dir = self.data_dir / "chunks" / job.id
        temp_dir.mkdir(parents=True, exist_ok=True)
        chunk_wav_paths: list[Path] = []
        t0_start = time.time()

        try:
            for i, chunk in enumerate(chunks):
                refreshed = self.get_job(job.id)
                if refreshed and refreshed.status == "cancelled":
                    return False, "Người dùng đã hủy tác vụ"

                pct = int((i / total_chunks) * 80)
                self._update_job_status(job.id, phase="generating_tokens", progress_percent=pct)

                chunk_out = temp_dir / f"chunk_{i:04d}.wav"
                chunk_params = {**params, "text": chunk["text"]}

                if in_process:
                    wav, sr = execute_model_inference(sub_model, chunk_params, self.device)
                    save_audio_wav(chunk_out, wav, sr)
                else:
                    ok, err, _ = run_isolated_subprocess(
                        job_id=f"{job.id}_{i}",
                        job_type=sub_model,
                        params=chunk_params,
                        output_path=chunk_out,
                        device=self.device,
                        cpu_threads=self.cpu_threads,
                        project_dir=self.project_dir,
                        data_dir=self.data_dir,
                        timeout_seconds=self.timeout_seconds,
                        register_proc_callback=self._register_proc,
                        unregister_proc_callback=self._unregister_proc,
                    )
                    if not ok or not chunk_out.exists():
                        return False, f"Lỗi ở đoạn {i+1}/{total_chunks}: {err}"

                chunk_wav_paths.append(chunk_out)

            # Merge all chunks
            self._update_job_status(job.id, phase="merging_audio", progress_percent=85)
            tensors = []
            target_sr = 24000
            for p in chunk_wav_paths:
                w, err = load_and_resample_audio(p, target_sr)
                if w is not None:
                    tensors.append(w)

            merged_speech = merge_speech_segments(tensors, pause_duration=pause_duration, target_sr=target_sr)

            # Optional BGM mixing with explicit warning capture
            bgm_path = params.get("bgm_audio_path")
            bgm_vol = float(params.get("bgm_volume", 0.15))
            warning_msg = None
            if bgm_path and Path(bgm_path).exists():
                merged_speech, warning_msg = mix_background_music(merged_speech, bgm_path, bgm_vol, target_sr)
                if warning_msg:
                    logger.warning(f"[Long-Text] {warning_msg}")

            save_audio_wav(output_path, merged_speech, target_sr)

            total_time = round(time.time() - t0_start, 3)
            audio_dur = round(merged_speech.shape[-1] / target_sr, 3)
            rtf = round(total_time / max(0.01, audio_dur), 3)

            benchmark_data = {
                "device": self.device,
                "model_type": sub_model,
                "total_chunks": total_chunks,
                "inference_seconds": total_time,
                "audio_duration_seconds": audio_dur,
                "realtime_factor": rtf,
                "faster_than_realtime": round(audio_dur / max(0.01, total_time), 2),
            }
            if warning_msg:
                benchmark_data["warning"] = warning_msg

            self._update_job_status(
                job.id,
                benchmark=benchmark_data,
                duration_seconds=audio_dur,
                progress_percent=100,
                phase="completed",
            )
            return True, None
        finally:
            if temp_dir.exists():
                for f in temp_dir.glob("*.wav"):
                    f.unlink(missing_ok=True)
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass
