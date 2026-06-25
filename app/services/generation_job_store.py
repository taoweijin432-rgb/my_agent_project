import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import PROJECT_ROOT, Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationJobDetail,
    GenerationJobError,
    GenerationJobSummary,
)


class GenerationJobStore:
    def __init__(self, settings: Settings) -> None:
        self.db_path = _resolve_db_path(settings.generation_history_db_path)
        self.retention_seconds = settings.generation_job_retention_seconds
        self._lock = threading.Lock()
        self._initialize()

    def create_job(
        self,
        request: GenerateRequest,
        *,
        queue_backend: str,
        queue_job_id: str | None = None,
    ) -> GenerationJobDetail:
        now = _utc_now()
        now_epoch = time.time()
        job_id = uuid4().hex
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO generation_jobs (
                        id, queue_backend, queue_job_id, status, created_at,
                        updated_at, created_epoch, request_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        queue_backend,
                        queue_job_id,
                        "queued",
                        now,
                        now,
                        now_epoch,
                        _json_dumps(request.model_dump(mode="json")),
                    ),
                )
                connection.commit()
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("failed to create generation job")
        return job

    def set_queue_job_id(self, job_id: str, queue_job_id: str) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE generation_jobs
                    SET queue_job_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (queue_job_id, now, job_id),
                )
                connection.commit()

    def get_job(self, job_id: str) -> GenerationJobDetail | None:
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT id, status, created_at, updated_at, started_at, finished_at,
                           request_json, response_json, record_id, error_json
                    FROM generation_jobs
                    WHERE id = ?
                    """,
                    (job_id,),
                ).fetchone()
        return _detail_from_row(row) if row is not None else None

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationJobSummary]:
        params: list[object] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.extend([limit, offset])
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                rows = connection.execute(
                    f"""
                    SELECT id, status, created_at, updated_at, started_at, finished_at,
                           record_id, error_json
                    FROM generation_jobs
                    {where}
                    ORDER BY created_epoch DESC
                    LIMIT ? OFFSET ?
                    """,
                    params,
                ).fetchall()
        return [_summary_from_row(row) for row in rows]

    def count_active_jobs(self) -> int:
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM generation_jobs
                    WHERE status IN ('queued', 'running')
                    """
                ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_jobs_by_status(self) -> dict[str, int]:
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM generation_jobs
                    GROUP BY status
                    """
                ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def mark_running(self, job_id: str, *, worker_id: str | None = None) -> None:
        now = _utc_now()
        now_epoch = time.time()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE generation_jobs
                    SET status = 'running',
                        started_at = COALESCE(started_at, ?),
                        started_epoch = COALESCE(started_epoch, ?),
                        updated_at = ?,
                        worker_id = ?,
                        attempts = attempts + 1
                    WHERE id = ?
                    """,
                    (now, now_epoch, now, worker_id, job_id),
                )
                connection.commit()

    def mark_succeeded(
        self,
        job_id: str,
        *,
        response: GenerateResponse,
        record_id: str | None,
    ) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE generation_jobs
                    SET status = 'succeeded',
                        response_json = ?,
                        record_id = ?,
                        finished_at = ?,
                        finished_epoch = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _json_dumps(response.model_dump(mode="json")),
                        record_id,
                        now,
                        time.time(),
                        now,
                        job_id,
                    ),
                )
                connection.commit()

    def mark_failed(
        self,
        job_id: str,
        *,
        error: GenerationJobError,
        record_id: str | None = None,
    ) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE generation_jobs
                    SET status = 'failed',
                        error_json = ?,
                        record_id = COALESCE(?, record_id),
                        finished_at = COALESCE(finished_at, ?),
                        finished_epoch = COALESCE(finished_epoch, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _json_dumps(error.model_dump(mode="json")),
                        record_id,
                        now,
                        time.time(),
                        now,
                        job_id,
                    ),
                )
                connection.commit()

    def fail_stale_running_jobs(self, *, stale_after_seconds: int) -> list[str]:
        if stale_after_seconds <= 0:
            return []

        now_epoch = time.time()
        cutoff_epoch = now_epoch - stale_after_seconds
        now = _utc_now()
        cutoff = _utc_from_epoch(cutoff_epoch)
        error = GenerationJobError(
            code="generation_job_stale",
            message=(
                "Generation job was marked failed because it stayed running "
                f"for more than {stale_after_seconds} seconds."
            ),
            status_code=500,
        )
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT id
                    FROM generation_jobs
                    WHERE status = 'running'
                      AND (
                        (started_epoch IS NOT NULL AND started_epoch < ?)
                        OR (started_epoch IS NULL AND updated_at < ?)
                      )
                    """,
                    (cutoff_epoch, cutoff),
                ).fetchall()
                job_ids = [str(row["id"]) for row in rows]
                if not job_ids:
                    return []
                connection.executemany(
                    """
                    UPDATE generation_jobs
                    SET status = 'failed',
                        error_json = ?,
                        finished_at = ?,
                        finished_epoch = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    [
                        (
                            _json_dumps(error.model_dump(mode="json")),
                            now,
                            now_epoch,
                            now,
                            job_id,
                        )
                        for job_id in job_ids
                    ],
                )
                connection.commit()
        return job_ids

    def get_request(self, job_id: str) -> GenerateRequest | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_json FROM generation_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return GenerateRequest.model_validate(json.loads(row["request_json"]))

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS generation_jobs (
                        id TEXT PRIMARY KEY,
                        queue_backend TEXT NOT NULL,
                        queue_job_id TEXT,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        created_epoch REAL NOT NULL,
                        started_epoch REAL,
                        finished_epoch REAL,
                        request_json TEXT NOT NULL,
                        response_json TEXT,
                        error_json TEXT,
                        record_id TEXT,
                        worker_id TEXT,
                        attempts INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                _ensure_column(
                    connection,
                    table="generation_jobs",
                    column="started_epoch",
                    definition="REAL",
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_generation_jobs_created_epoch
                    ON generation_jobs (created_epoch DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_generation_jobs_status
                    ON generation_jobs (status)
                    """
                )
                connection.commit()

    def _cleanup_expired_locked(self) -> None:
        if self.retention_seconds <= 0:
            return
        cutoff = time.time() - self.retention_seconds
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM generation_jobs
                WHERE finished_epoch IS NOT NULL
                  AND finished_epoch < ?
                """,
                (cutoff,),
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection


def _resolve_db_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_from_epoch(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _ensure_column(
    connection: sqlite3.Connection,
    *,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _summary_from_row(row: sqlite3.Row) -> GenerationJobSummary:
    return GenerationJobSummary(
        id=row["id"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        record_id=row["record_id"],
        error=_error_from_raw(row["error_json"]),
    )


def _detail_from_row(row: sqlite3.Row) -> GenerationJobDetail:
    return GenerationJobDetail(
        **_summary_from_row(row).model_dump(),
        request=GenerateRequest.model_validate(json.loads(row["request_json"])),
        response=_response_from_raw(row["response_json"]),
    )


def _error_from_raw(raw: str | None) -> GenerationJobError | None:
    if not raw:
        return None
    return GenerationJobError.model_validate(json.loads(raw))


def _response_from_raw(raw: str | None) -> GenerateResponse | None:
    if not raw:
        return None
    return GenerateResponse.model_validate(json.loads(raw))
