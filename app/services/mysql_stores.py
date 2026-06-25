import json
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationGateDetail,
    GenerationGateResolution,
    GenerationJobDetail,
    GenerationJobError,
    GenerationJobSummary,
    GenerationRecordDetail,
    GenerationRecordSummary,
    GenerationUsage,
)
from app.services.history import GenerationGateAlreadyResolvedError
from app.services.quality import score_generation_quality


class MySQLDependencyError(RuntimeError):
    pass


class MySQLConfigurationError(RuntimeError):
    pass


class MySQLGenerationHistoryStore:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.generation_history_enabled
        self.database_url = settings.database_url
        if not self.database_url:
            raise MySQLConfigurationError(
                "DATABASE_URL must be configured when DATABASE_BACKEND=mysql."
            )

    def record_success(
        self,
        request: GenerateRequest,
        response: GenerateResponse,
        *,
        duration_ms: float,
        request_id: str | None = None,
    ) -> str | None:
        if not self.enabled:
            return None

        record_id = uuid4().hex
        created_at = _utc_now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO generation_records (
                        id, created_at, request_id, status, description, request_json,
                        response_json, error, duration_ms, model, attempts,
                        retrieved_chunks, retrieved_sources_json, case_count, usage_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record_id,
                        created_at,
                        request_id,
                        "success",
                        request.description,
                        _json_dumps(request.model_dump(mode="json")),
                        _json_dumps(response.model_dump(mode="json")),
                        None,
                        duration_ms,
                        response.metadata.model,
                        response.metadata.attempts,
                        response.metadata.retrieved_chunks,
                        _json_dumps(response.metadata.retrieved_sources),
                        len(response.cases),
                        _json_dumps(response.metadata.usage.model_dump(mode="json")),
                    ),
                )
            connection.commit()
        return record_id

    def record_failure(
        self,
        request: GenerateRequest,
        error: str,
        *,
        duration_ms: float,
        request_id: str | None = None,
        usage: GenerationUsage | None = None,
        gate: GenerationGateDetail | dict | None = None,
    ) -> str | None:
        if not self.enabled:
            return None

        record_id = uuid4().hex
        created_at = _utc_now()
        gate_detail = _gate_from_value(gate)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO generation_records (
                        id, created_at, request_id, status, description, request_json,
                        response_json, error, duration_ms, model, attempts,
                        retrieved_chunks, retrieved_sources_json, case_count, usage_json,
                        gate_detail_json, gate_status
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        record_id,
                        created_at,
                        request_id,
                        "failed",
                        request.description,
                        _json_dumps(request.model_dump(mode="json")),
                        None,
                        error,
                        duration_ms,
                        None,
                        None,
                        None,
                        _json_dumps([]),
                        0,
                        _json_dumps((usage or GenerationUsage()).model_dump(mode="json")),
                        _json_dumps(gate_detail.model_dump(mode="json"))
                        if gate_detail
                        else None,
                        "pending" if gate_detail else None,
                    ),
                )
            connection.commit()
        return record_id

    def list_records(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationRecordSummary]:
        if not self.enabled:
            return []

        params: list[object] = []
        where = ""
        if status:
            where = "WHERE status = %s"
            params.append(status)
        params.extend([limit, offset])
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, created_at, request_id, status, description, duration_ms,
                           model, attempts, retrieved_chunks, retrieved_sources_json,
                           case_count, error, usage_json, gate_detail_json, gate_status,
                           gate_resolved_at, gate_resolved_by, gate_resolution_comment
                    FROM generation_records
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [_record_summary_from_row(row) for row in rows]

    def list_gate_records(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        gate_status: str | None = "pending",
    ) -> list[GenerationRecordSummary]:
        if not self.enabled:
            return []

        params: list[object] = []
        where = "WHERE gate_detail_json IS NOT NULL"
        if gate_status:
            where = f"{where} AND gate_status = %s"
            params.append(gate_status)
        params.extend([limit, offset])
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, created_at, request_id, status, description, duration_ms,
                           model, attempts, retrieved_chunks, retrieved_sources_json,
                           case_count, error, usage_json, gate_detail_json, gate_status,
                           gate_resolved_at, gate_resolved_by, gate_resolution_comment
                    FROM generation_records
                    {where}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return [_record_summary_from_row(row) for row in rows]

    def get_record(self, record_id: str) -> GenerationRecordDetail | None:
        if not self.enabled:
            return None

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, created_at, request_id, status, description, duration_ms,
                           model, attempts, retrieved_chunks, retrieved_sources_json,
                           case_count, error, request_json, response_json, usage_json,
                           gate_detail_json, gate_status, gate_resolved_at,
                           gate_resolved_by, gate_resolution_comment
                    FROM generation_records
                    WHERE id = %s
                    """,
                    (record_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None

        summary = _record_summary_from_row(row)
        response_raw = row["response_json"]
        response = (
            GenerateResponse.model_validate(_json_value(response_raw, {}))
            if response_raw
            else None
        )
        request = GenerateRequest.model_validate(_json_value(row["request_json"], {}))
        quality = score_generation_quality(request, response) if response else None
        return GenerationRecordDetail(
            **summary.model_dump(),
            request=request,
            response=response,
            quality=quality,
        )

    def resolve_gate_record(
        self,
        record_id: str,
        *,
        decision: str,
        resolved_by: str | None = None,
        comment: str | None = None,
    ) -> GenerationRecordDetail | None:
        if not self.enabled:
            return None
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")

        resolved_at = _utc_now()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE generation_records
                    SET gate_status = %s,
                        gate_resolved_at = %s,
                        gate_resolved_by = %s,
                        gate_resolution_comment = %s
                    WHERE id = %s
                      AND gate_detail_json IS NOT NULL
                      AND COALESCE(gate_status, 'pending') = 'pending'
                    """,
                    (decision, resolved_at, resolved_by, comment, record_id),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        """
                        SELECT gate_detail_json, gate_status
                        FROM generation_records
                        WHERE id = %s
                        """,
                        (record_id,),
                    )
                    existing = cursor.fetchone()
                    if existing is None or existing["gate_detail_json"] is None:
                        return None
                    current_status = existing["gate_status"] or "pending"
                    raise GenerationGateAlreadyResolvedError(
                        f"Generation gate record is already {current_status}."
                    )
            connection.commit()

        return self.get_record(record_id)

    def _connect(self):
        return _connect(self.database_url)


class MySQLGenerationJobStore:
    def __init__(self, settings: Settings) -> None:
        self.database_url = settings.database_url
        self.retention_seconds = settings.generation_job_retention_seconds
        if not self.database_url:
            raise MySQLConfigurationError(
                "DATABASE_URL must be configured when DATABASE_BACKEND=mysql."
            )

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
        with self._connect() as connection:
            self._cleanup_expired(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO generation_jobs (
                        id, queue_backend, queue_job_id, status, created_at,
                        updated_at, created_epoch, request_json
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE generation_jobs
                    SET queue_job_id = %s, updated_at = %s
                    WHERE id = %s
                    """,
                    (queue_job_id, now, job_id),
                )
            connection.commit()

    def get_job(self, job_id: str) -> GenerationJobDetail | None:
        with self._connect() as connection:
            self._cleanup_expired(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, status, created_at, updated_at, started_at, finished_at,
                           request_json, response_json, record_id, error_json
                    FROM generation_jobs
                    WHERE id = %s
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
            connection.commit()
        return _job_detail_from_row(row) if row is not None else None

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
            where = "WHERE status = %s"
            params.append(status)
        params.extend([limit, offset])
        with self._connect() as connection:
            self._cleanup_expired(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, status, created_at, updated_at, started_at, finished_at,
                           record_id, error_json
                    FROM generation_jobs
                    {where}
                    ORDER BY created_epoch DESC
                    LIMIT %s OFFSET %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
            connection.commit()
        return [_job_summary_from_row(row) for row in rows]

    def count_active_jobs(self) -> int:
        with self._connect() as connection:
            self._cleanup_expired(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM generation_jobs
                    WHERE status IN ('queued', 'running')
                    """
                )
                row = cursor.fetchone()
            connection.commit()
        return int(row["count"]) if row is not None else 0

    def count_jobs_by_status(self) -> dict[str, int]:
        with self._connect() as connection:
            self._cleanup_expired(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM generation_jobs
                    GROUP BY status
                    """
                )
                rows = cursor.fetchall()
            connection.commit()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def mark_running(self, job_id: str, *, worker_id: str | None = None) -> None:
        now = _utc_now()
        now_epoch = time.time()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE generation_jobs
                    SET status = 'running',
                        started_at = COALESCE(started_at, %s),
                        started_epoch = COALESCE(started_epoch, %s),
                        updated_at = %s,
                        worker_id = %s,
                        attempts = attempts + 1
                    WHERE id = %s
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
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE generation_jobs
                    SET status = 'succeeded',
                        response_json = %s,
                        record_id = %s,
                        finished_at = %s,
                        finished_epoch = %s,
                        updated_at = %s
                    WHERE id = %s
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
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE generation_jobs
                    SET status = 'failed',
                        error_json = %s,
                        record_id = COALESCE(%s, record_id),
                        finished_at = COALESCE(finished_at, %s),
                        finished_epoch = COALESCE(finished_epoch, %s),
                        updated_at = %s
                    WHERE id = %s
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
        error = GenerationJobError(
            code="generation_job_stale",
            message=(
                "Generation job was marked failed because it stayed running "
                f"for more than {stale_after_seconds} seconds."
            ),
            status_code=500,
        )
        cutoff_time = _utc_from_epoch(cutoff_epoch)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM generation_jobs
                    WHERE status = 'running'
                      AND (
                        (started_epoch IS NOT NULL AND started_epoch < %s)
                        OR (started_epoch IS NULL AND updated_at < %s)
                      )
                    """,
                    (cutoff_epoch, cutoff_time),
                )
                job_ids = [str(row["id"]) for row in cursor.fetchall()]
                if job_ids:
                    placeholders = ", ".join(["%s"] * len(job_ids))
                    cursor.execute(
                        f"""
                        UPDATE generation_jobs
                        SET status = 'failed',
                            error_json = %s,
                            finished_at = %s,
                            finished_epoch = %s,
                            updated_at = %s
                        WHERE id IN ({placeholders})
                        """,
                        (
                            _json_dumps(error.model_dump(mode="json")),
                            now,
                            now_epoch,
                            now,
                            *job_ids,
                        ),
                    )
            connection.commit()
        return job_ids

    def get_request(self, job_id: str) -> GenerateRequest | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT request_json FROM generation_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return GenerateRequest.model_validate(_json_value(row["request_json"], {}))

    def _cleanup_expired(self, connection) -> None:
        if self.retention_seconds <= 0:
            return
        cutoff = time.time() - self.retention_seconds
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM generation_jobs
                WHERE finished_epoch IS NOT NULL
                  AND finished_epoch < %s
                """,
                (cutoff,),
            )

    def _connect(self):
        return _connect(self.database_url)


def _connect(database_url: str):
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ModuleNotFoundError as exc:
        raise MySQLDependencyError(
            "PyMySQL is not installed. Install requirements-mysql.txt before "
            "using DATABASE_BACKEND=mysql."
        ) from exc
    return pymysql.connect(**_parse_mysql_url(database_url), cursorclass=DictCursor)


def _parse_mysql_url(database_url: str) -> dict[str, object]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise MySQLConfigurationError(
            "DATABASE_URL must start with mysql:// or mysql+pymysql://."
        )
    database = parsed.path.lstrip("/")
    if not database:
        raise MySQLConfigurationError("DATABASE_URL must include a database name.")
    query = parse_qs(parsed.query)
    charset = query.get("charset", ["utf8mb4"])[0]
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": charset,
        "autocommit": False,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc_from_epoch(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


def _to_text(value: object | None) -> str | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat()
    if value is None:
        return None
    return str(value)


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_value(value: object | None, default: object) -> object:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _usage_from_value(value: object | None) -> GenerationUsage:
    try:
        return GenerationUsage.model_validate(_json_value(value, {}))
    except (TypeError, ValueError, json.JSONDecodeError):
        return GenerationUsage()


def _gate_from_value(
    value: GenerationGateDetail | dict | None,
) -> GenerationGateDetail | None:
    if value is None:
        return None
    if isinstance(value, GenerationGateDetail):
        return value
    return GenerationGateDetail.model_validate(value)


def _gate_from_raw(value: object | None) -> GenerationGateDetail | None:
    if value is None:
        return None
    try:
        return GenerationGateDetail.model_validate(_json_value(value, {}))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _gate_resolution_from_row(row: dict[str, object]) -> GenerationGateResolution | None:
    if row.get("gate_detail_json") is None:
        return None
    return GenerationGateResolution(
        status=row.get("gate_status") or "pending",
        resolved_at=_to_text(row.get("gate_resolved_at")),
        resolved_by=_to_text(row.get("gate_resolved_by")),
        comment=_to_text(row.get("gate_resolution_comment")),
    )


def _record_summary_from_row(row: dict[str, object]) -> GenerationRecordSummary:
    return GenerationRecordSummary(
        id=str(row["id"]),
        created_at=_to_text(row["created_at"]) or "",
        request_id=_to_text(row.get("request_id")),
        status=row["status"],
        description=str(row["description"]),
        duration_ms=float(row["duration_ms"]),
        model=_to_text(row.get("model")),
        attempts=row.get("attempts"),
        retrieved_chunks=row.get("retrieved_chunks"),
        retrieved_sources=[
            str(item) for item in _json_value(row.get("retrieved_sources_json"), [])
        ],
        case_count=int(row["case_count"]),
        error=_to_text(row.get("error")),
        usage=_usage_from_value(row.get("usage_json")),
        gate=_gate_from_raw(row.get("gate_detail_json")),
        gate_resolution=_gate_resolution_from_row(row),
    )


def _job_summary_from_row(row: dict[str, object]) -> GenerationJobSummary:
    return GenerationJobSummary(
        id=str(row["id"]),
        status=row["status"],
        created_at=_to_text(row["created_at"]) or "",
        updated_at=_to_text(row["updated_at"]) or "",
        started_at=_to_text(row.get("started_at")),
        finished_at=_to_text(row.get("finished_at")),
        record_id=_to_text(row.get("record_id")),
        error=_job_error_from_value(row.get("error_json")),
    )


def _job_detail_from_row(row: dict[str, object]) -> GenerationJobDetail:
    return GenerationJobDetail(
        **_job_summary_from_row(row).model_dump(),
        request=GenerateRequest.model_validate(_json_value(row["request_json"], {})),
        response=_response_from_value(row.get("response_json")),
    )


def _job_error_from_value(value: object | None) -> GenerationJobError | None:
    if value is None:
        return None
    return GenerationJobError.model_validate(_json_value(value, {}))


def _response_from_value(value: object | None) -> GenerateResponse | None:
    if value is None:
        return None
    return GenerateResponse.model_validate(_json_value(value, {}))
