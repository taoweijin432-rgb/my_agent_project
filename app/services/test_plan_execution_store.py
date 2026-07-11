import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import PROJECT_ROOT, Settings
from app.models.test_plan import (
    TestExecutionReport,
    TestPlanExecutionJobDetail,
    TestPlanExecutionJobError,
    TestPlanExecutionJobSummary,
    TestPlanExecutionRequest,
)


class TestPlanExecutionJobStore:
    def __init__(self, settings: Settings) -> None:
        self.db_path = _resolve_db_path(settings.generation_history_db_path)
        self.retention_seconds = settings.generation_job_retention_seconds
        self._lock = threading.Lock()
        self._initialize()

    def create_job(self, request: TestPlanExecutionRequest) -> TestPlanExecutionJobDetail:
        now = _utc_now()
        job_id = uuid4().hex
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO test_plan_execution_jobs (
                        id, status, created_at, updated_at, created_epoch, request_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        "queued",
                        now,
                        now,
                        time.time(),
                        _json_dumps(request.model_dump(mode="json")),
                    ),
                )
                connection.commit()
        job = self.get_job(job_id)
        if job is None:
            raise RuntimeError("failed to create test plan execution job")
        return job

    def get_request(self, job_id: str) -> TestPlanExecutionRequest | None:
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT request_json
                    FROM test_plan_execution_jobs
                    WHERE id = ?
                    """,
                    (job_id,),
                ).fetchone()
        if row is None:
            return None
        return TestPlanExecutionRequest.model_validate(json.loads(row["request_json"]))

    def count_active_jobs(self) -> int:
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM test_plan_execution_jobs
                    WHERE status IN ('queued', 'running')
                    """
                ).fetchone()
        return int(row["count"]) if row is not None else 0

    def get_job(self, job_id: str) -> TestPlanExecutionJobDetail | None:
        with self._lock:
            self._cleanup_expired_locked()
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT id, status, created_at, updated_at, started_at, finished_at,
                           request_json, report_json, error_json
                    FROM test_plan_execution_jobs
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
    ) -> list[TestPlanExecutionJobSummary]:
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
                           error_json
                    FROM test_plan_execution_jobs
                    {where}
                    ORDER BY created_epoch DESC
                    LIMIT ? OFFSET ?
                    """,
                    params,
                ).fetchall()
        return [_summary_from_row(row) for row in rows]

    def mark_running(self, job_id: str) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE test_plan_execution_jobs
                    SET status = 'running',
                        started_at = COALESCE(started_at, ?),
                        started_epoch = COALESCE(started_epoch, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, time.time(), now, job_id),
                )
                connection.commit()

    def mark_succeeded(self, job_id: str, report: TestExecutionReport) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE test_plan_execution_jobs
                    SET status = 'succeeded',
                        report_json = ?,
                        finished_at = ?,
                        finished_epoch = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _json_dumps(report.model_dump(mode="json")),
                        now,
                        time.time(),
                        now,
                        job_id,
                    ),
                )
                connection.commit()

    def mark_failed(self, job_id: str, error: TestPlanExecutionJobError) -> None:
        now = _utc_now()
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE test_plan_execution_jobs
                    SET status = 'failed',
                        error_json = ?,
                        finished_at = COALESCE(finished_at, ?),
                        finished_epoch = COALESCE(finished_epoch, ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        _json_dumps(error.model_dump(mode="json")),
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
        error = TestPlanExecutionJobError(
            code="test_plan_execution_job_stale",
            message=(
                "Test plan execution job was marked failed because it stayed running "
                f"for more than {stale_after_seconds} seconds."
            ),
        )
        with self._lock:
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT id
                    FROM test_plan_execution_jobs
                    WHERE status = 'running'
                      AND (
                        (started_epoch IS NOT NULL AND started_epoch < ?)
                        OR (started_epoch IS NULL AND updated_at < ?)
                      )
                    """,
                    (cutoff_epoch, _utc_from_epoch(cutoff_epoch)),
                ).fetchall()
                job_ids = [str(row["id"]) for row in rows]
                if not job_ids:
                    return []
                connection.executemany(
                    """
                    UPDATE test_plan_execution_jobs
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

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._connect() as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS test_plan_execution_jobs (
                        id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        created_epoch REAL NOT NULL,
                        started_epoch REAL,
                        finished_epoch REAL,
                        request_json TEXT NOT NULL,
                        report_json TEXT,
                        error_json TEXT
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_test_plan_execution_jobs_created_epoch
                    ON test_plan_execution_jobs (created_epoch DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_test_plan_execution_jobs_status
                    ON test_plan_execution_jobs (status)
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
                DELETE FROM test_plan_execution_jobs
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


def _summary_from_row(row: sqlite3.Row) -> TestPlanExecutionJobSummary:
    return TestPlanExecutionJobSummary(
        id=row["id"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=_error_from_raw(row["error_json"]),
    )


def _detail_from_row(row: sqlite3.Row) -> TestPlanExecutionJobDetail:
    return TestPlanExecutionJobDetail(
        **_summary_from_row(row).model_dump(),
        request=TestPlanExecutionRequest.model_validate(json.loads(row["request_json"])),
        report=_report_from_raw(row["report_json"]),
    )


def _error_from_raw(raw: str | None) -> TestPlanExecutionJobError | None:
    if not raw:
        return None
    return TestPlanExecutionJobError.model_validate(json.loads(raw))


def _report_from_raw(raw: str | None) -> TestExecutionReport | None:
    if not raw:
        return None
    return TestExecutionReport.model_validate(json.loads(raw))


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
