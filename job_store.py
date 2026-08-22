"""SQLite job persistence and TTL cleanup for Chatterbox API."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

JobStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]
JobType = Literal["tts", "turbo", "nano", "multilingual", "voice-conversion", "long-text", "batch"]
JobPhase = Literal[
    "queued",
    "loading_model",
    "generating_tokens",
    "generating_audio",
    "merging_audio",
    "completed",
    "failed",
    "cancelled",
]


@dataclass
class AudioJob:
    id: str
    type: JobType
    params: dict
    input_paths: list[str]
    status: JobStatus = "queued"
    phase: JobPhase = "queued"
    progress_percent: int = 0
    created_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    output_path: str | None = None
    duration_seconds: float | None = None
    benchmark: dict | None = None

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("input_paths", None)
        data.pop("output_path", None)
        data["params"] = _sanitize_public_payload(self.params)
        data["audio_url"] = f"/api/v1/jobs/{self.id}/audio" if self.status == "completed" else None
        if self.type in ("batch", "long-text") or "lines" in self.params:
            if self.benchmark and "lines_results" in self.benchmark:
                data["lines_results"] = [
                    {
                        **_sanitize_public_payload(r),
                        "audio_url": (f"/api/v1/jobs/{self.id}/lines/{r['idx']}" if r.get("status") == "completed" else None),
                    }
                    for r in self.benchmark["lines_results"]
                ]
            elif "lines_results" in self.params:
                data["lines_results"] = _sanitize_public_payload(self.params["lines_results"])
            data["srt_url"] = f"/api/v1/jobs/{self.id}/srt" if self.status == "completed" else None
            data["zip_url"] = f"/api/v1/jobs/{self.id}/zip" if self.status == "completed" else None
        if data.get("benchmark"):
            data["benchmark"] = _sanitize_public_payload(data["benchmark"])
        return _sanitize_public_payload(data)


def _sanitize_public_payload(obj: Any) -> Any:
    """Recursively strip internal filesystem paths and sensitive server directories."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            if k.endswith("_path") or k in ("path", "chunks_dir", "meta_path", "config_file"):
                continue
            cleaned[k] = _sanitize_public_payload(v)
        return cleaned
    elif isinstance(obj, list):
        return [_sanitize_public_payload(item) for item in obj]
    return obj


def delete_job_artifacts(data_dir: Path, job_id: str, output_path: str | None = None) -> int:
    """Safely delete all generated artifacts for a job (wav, srt, zip, json metadata, chunks, configs)."""
    import shutil
    deleted_bytes = 0
    paths_to_delete: list[Path] = [
        data_dir / "outputs" / f"{job_id}.wav",
        data_dir / "outputs" / f"{job_id}.srt",
        data_dir / "outputs" / f"{job_id}.zip",
        data_dir / "outputs" / f"{job_id}.json",
        data_dir / "configs" / f"{job_id}.json",
    ]
    if output_path:
        p = Path(output_path)
        if p not in paths_to_delete:
            paths_to_delete.append(p)

    for p in paths_to_delete:
        if p.exists() and p.is_file():
            try:
                deleted_bytes += p.stat().st_size
                p.unlink(missing_ok=True)
            except Exception:
                pass

    chunks_dir = data_dir / "chunks" / job_id
    if chunks_dir.exists() and chunks_dir.is_dir():
        try:
            for child in chunks_dir.rglob("*"):
                if child.is_file():
                    deleted_bytes += child.stat().st_size
            shutil.rmtree(chunks_dir, ignore_errors=True)
        except Exception:
            pass

    return deleted_bytes


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS jobs (
                            id TEXT PRIMARY KEY,
                            type TEXT NOT NULL,
                            status TEXT NOT NULL,
                            phase TEXT NOT NULL,
                            progress_percent INTEGER DEFAULT 0,
                            params_json TEXT NOT NULL,
                            input_paths_json TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            started_at TEXT,
                            completed_at TEXT,
                            error TEXT,
                            output_path TEXT,
                            duration_seconds REAL,
                            benchmark_json TEXT
                        )
                    """)
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at)")
            finally:
                conn.close()

    def save(self, job: AudioJob) -> None:
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO jobs (
                            id, type, status, phase, progress_percent,
                            params_json, input_paths_json, created_at, started_at,
                            completed_at, error, output_path, duration_seconds, benchmark_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            status=excluded.status,
                            phase=excluded.phase,
                            progress_percent=excluded.progress_percent,
                            params_json=excluded.params_json,
                            started_at=excluded.started_at,
                            completed_at=excluded.completed_at,
                            error=excluded.error,
                            output_path=excluded.output_path,
                            duration_seconds=excluded.duration_seconds,
                            benchmark_json=excluded.benchmark_json
                        """,
                        (
                            job.id,
                            job.type,
                            job.status,
                            job.phase,
                            job.progress_percent,
                            json.dumps(job.params, ensure_ascii=False),
                            json.dumps(job.input_paths, ensure_ascii=False),
                            job.created_at,
                            job.started_at,
                            job.completed_at,
                            job.error,
                            job.output_path,
                            job.duration_seconds,
                            json.dumps(job.benchmark, ensure_ascii=False) if job.benchmark else None,
                        ),
                    )
            finally:
                conn.close()

    def get(self, job_id: str) -> AudioJob | None:
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
                if row is None:
                    return None
                return self._row_to_job(row)
            finally:
                conn.close()

    def list_jobs(self, status: JobStatus | None = None, limit: int = 100) -> list[AudioJob]:
        with self._lock:
            conn = self._get_conn()
            try:
                if status:
                    rows = conn.execute(
                        "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                        (status, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
                return [self._row_to_job(row) for row in rows]
            finally:
                conn.close()

    def delete(self, job_id: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
                    return cursor.rowcount > 0
            finally:
                conn.close()

    def cleanup_expired(self, retention_days: int = 3, data_dir: Path | None = None) -> tuple[int, int]:
        """Delete jobs and all associated audio/subtitle/chunk/archive files older than retention_days."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        deleted_count = 0
        deleted_bytes = 0
        target_data_dir = data_dir or self.db_path.parent

        with self._lock:
            conn = self._get_conn()
            try:
                with conn:
                    rows = conn.execute(
                        "SELECT id, output_path FROM jobs WHERE created_at < ? AND status IN ('completed', 'failed', 'cancelled')",
                        (cutoff,),
                    ).fetchall()

                    for row in rows:
                        jid = row["id"]
                        out_p = row["output_path"]
                        deleted_bytes += delete_job_artifacts(target_data_dir, jid, out_p)
                        conn.execute("DELETE FROM jobs WHERE id = ?", (jid,))
                        deleted_count += 1
            finally:
                conn.close()
        return deleted_count, deleted_bytes

    def _row_to_job(self, row: sqlite3.Row) -> AudioJob:
        return AudioJob(
            id=row["id"],
            type=row["type"],
            status=row["status"],
            phase=row["phase"],
            progress_percent=row["progress_percent"],
            params=json.loads(row["params_json"]) if row["params_json"] else {},
            input_paths=json.loads(row["input_paths_json"]) if row["input_paths_json"] else [],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            output_path=row["output_path"],
            duration_seconds=row["duration_seconds"],
            benchmark=json.loads(row["benchmark_json"]) if row["benchmark_json"] else None,
        )
