"""SQLite job persistence and TTL cleanup for Chatterbox API."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

JobStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]
JobType = Literal["tts", "turbo", "nano", "multilingual", "voice-conversion", "long-text"]
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
        data["params"] = {key: value for key, value in self.params.items() if not key.endswith("_path")}
        data["audio_url"] = f"/api/v1/jobs/{self.id}/audio" if self.status == "completed" else None
        return data


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_conn() as conn:
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
            conn.commit()

    def save(self, job: AudioJob) -> None:
        with self._lock, self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    id, type, status, phase, progress_percent,
                    params_json, input_paths_json, created_at,
                    started_at, completed_at, error, output_path,
                    duration_seconds, benchmark_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            conn.commit()

    def get(self, job_id: str) -> AudioJob | None:
        with self._lock, self._get_conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_job(row)

    def list_jobs(self, status: JobStatus | None = None, limit: int = 100) -> list[AudioJob]:
        with self._lock, self._get_conn() as conn:
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

    def delete(self, job_id: str) -> bool:
        with self._lock, self._get_conn() as conn:
            cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def cleanup_expired(self, retention_days: int = 3) -> tuple[int, int]:
        """Delete jobs and audio files older than retention_days."""
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        deleted_count = 0
        deleted_bytes = 0

        with self._lock, self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, output_path FROM jobs WHERE created_at < ? AND status IN ('completed', 'failed', 'cancelled')",
                (cutoff,),
            ).fetchall()

            for row in rows:
                if row["output_path"]:
                    p = Path(row["output_path"])
                    if p.exists():
                        try:
                            deleted_bytes += p.stat().st_size
                            p.unlink(missing_ok=True)
                        except Exception:
                            pass
                conn.execute("DELETE FROM jobs WHERE id = ?", (row["id"],))
                deleted_count += 1

            conn.commit()
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
