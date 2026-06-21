import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import PROJECT_ROOT, Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationGateDetail,
    GenerationGateResolution,
    GenerationRecordDetail,
    GenerationRecordSummary,
    GenerationUsage,
)
from app.services.quality import score_generation_quality


class GenerationGateAlreadyResolvedError(RuntimeError):
    pass


class GenerationHistoryStore:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.generation_history_enabled
        self.db_path = _resolve_db_path(settings.generation_history_db_path)
        self._lock = threading.Lock()
        if self.enabled:
            self._initialize()

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
        request_json = _json_dumps(request.model_dump(mode="json"))
        response_json = _json_dumps(response.model_dump(mode="json"))
        retrieved_sources = _json_dumps(response.metadata.retrieved_sources)
        usage_json = _json_dumps(response.metadata.usage.model_dump(mode="json"))
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO generation_records (
                        id, created_at, request_id, status, description, request_json,
                        response_json, error, duration_ms, model, attempts,
                        retrieved_chunks, retrieved_sources_json, case_count, usage_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        created_at,
                        request_id,
                        "success",
                        request.description,
                        request_json,
                        response_json,
                        None,
                        duration_ms,
                        response.metadata.model,
                        response.metadata.attempts,
                        response.metadata.retrieved_chunks,
                        retrieved_sources,
                        len(response.cases),
                        usage_json,
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
        request_json = _json_dumps(request.model_dump(mode="json"))
        usage_json = _json_dumps((usage or GenerationUsage()).model_dump(mode="json"))
        gate_detail = _gate_from_value(gate)
        gate_detail_json = (
            _json_dumps(gate_detail.model_dump(mode="json")) if gate_detail else None
        )
        gate_status = "pending" if gate_detail else None
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO generation_records (
                        id, created_at, request_id, status, description, request_json,
                        response_json, error, duration_ms, model, attempts,
                        retrieved_chunks, retrieved_sources_json, case_count, usage_json,
                        gate_detail_json, gate_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record_id,
                        created_at,
                        request_id,
                        "failed",
                        request.description,
                        request_json,
                        None,
                        error,
                        duration_ms,
                        None,
                        None,
                        None,
                        "[]",
                        0,
                        usage_json,
                        gate_detail_json,
                        gate_status,
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
            where = "WHERE status = ?"
            params.append(status)
        params.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, created_at, request_id, status, description, duration_ms,
                       model, attempts, retrieved_chunks, retrieved_sources_json,
                       case_count, error, usage_json, gate_detail_json, gate_status,
                       gate_resolved_at, gate_resolved_by, gate_resolution_comment
                FROM generation_records
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [_summary_from_row(row) for row in rows]

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
            where = f"{where} AND gate_status = ?"
            params.append(gate_status)
        params.extend([limit, offset])
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, created_at, request_id, status, description, duration_ms,
                       model, attempts, retrieved_chunks, retrieved_sources_json,
                       case_count, error, usage_json, gate_detail_json, gate_status,
                       gate_resolved_at, gate_resolved_by, gate_resolution_comment
                FROM generation_records
                {where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [_summary_from_row(row) for row in rows]

    def get_record(self, record_id: str) -> GenerationRecordDetail | None:
        if not self.enabled:
            return None

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, created_at, request_id, status, description, duration_ms,
                       model, attempts, retrieved_chunks, retrieved_sources_json,
                       case_count, error, request_json, response_json, usage_json,
                       gate_detail_json, gate_status, gate_resolved_at,
                       gate_resolved_by, gate_resolution_comment
                FROM generation_records
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()
        if row is None:
            return None

        summary = _summary_from_row(row)
        response_json = row["response_json"]
        response = (
            GenerateResponse.model_validate(json.loads(response_json))
            if response_json
            else None
        )
        request = GenerateRequest.model_validate(json.loads(row["request_json"]))
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
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT gate_detail_json, gate_status
                    FROM generation_records
                    WHERE id = ?
                    """,
                    (record_id,),
                ).fetchone()
                if row is None or row["gate_detail_json"] is None:
                    return None

                current_status = row["gate_status"] or "pending"
                if current_status != "pending":
                    raise GenerationGateAlreadyResolvedError(
                        f"Generation gate record is already {current_status}."
                    )

                connection.execute(
                    """
                    UPDATE generation_records
                    SET gate_status = ?,
                        gate_resolved_at = ?,
                        gate_resolved_by = ?,
                        gate_resolution_comment = ?
                    WHERE id = ?
                    """,
                    (decision, resolved_at, resolved_by, comment, record_id),
                )
                connection.commit()

        return self.get_record(record_id)

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS generation_records (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        request_id TEXT,
                        status TEXT NOT NULL,
                        description TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        response_json TEXT,
                        error TEXT,
                        duration_ms REAL NOT NULL,
                        model TEXT,
                        attempts INTEGER,
                        retrieved_chunks INTEGER,
                        retrieved_sources_json TEXT NOT NULL,
                        case_count INTEGER NOT NULL,
                        usage_json TEXT NOT NULL DEFAULT '{}',
                        gate_detail_json TEXT,
                        gate_status TEXT,
                        gate_resolved_at TEXT,
                        gate_resolved_by TEXT,
                        gate_resolution_comment TEXT
                    )
                    """
                )
                _ensure_column(
                    connection,
                    table="generation_records",
                    column="usage_json",
                    definition="TEXT NOT NULL DEFAULT '{}'",
                )
                _ensure_column(
                    connection,
                    table="generation_records",
                    column="gate_detail_json",
                    definition="TEXT",
                )
                _ensure_column(
                    connection,
                    table="generation_records",
                    column="gate_status",
                    definition="TEXT",
                )
                _ensure_column(
                    connection,
                    table="generation_records",
                    column="gate_resolved_at",
                    definition="TEXT",
                )
                _ensure_column(
                    connection,
                    table="generation_records",
                    column="gate_resolved_by",
                    definition="TEXT",
                )
                _ensure_column(
                    connection,
                    table="generation_records",
                    column="gate_resolution_comment",
                    definition="TEXT",
                )
                connection.execute(
                    """
                    UPDATE generation_records
                    SET gate_status = 'pending'
                    WHERE gate_detail_json IS NOT NULL
                      AND gate_status IS NULL
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_generation_records_created_at
                    ON generation_records (created_at DESC)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_generation_records_status
                    ON generation_records (status)
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_generation_records_gate_status
                    ON generation_records (gate_status)
                    """
                )
                connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection


def _resolve_db_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads_list(raw: str) -> list[str]:
    value = json.loads(raw or "[]")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _usage_from_raw(raw: str | None) -> GenerationUsage:
    if not raw:
        return GenerationUsage()
    try:
        return GenerationUsage.model_validate(json.loads(raw))
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


def _gate_from_raw(raw: str | None) -> GenerationGateDetail | None:
    if not raw:
        return None
    try:
        return GenerationGateDetail.model_validate(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _gate_resolution_from_row(row: sqlite3.Row) -> GenerationGateResolution | None:
    if _row_value(row, "gate_detail_json") is None:
        return None
    return GenerationGateResolution(
        status=_row_value(row, "gate_status") or "pending",
        resolved_at=_row_value(row, "gate_resolved_at"),
        resolved_by=_row_value(row, "gate_resolved_by"),
        comment=_row_value(row, "gate_resolution_comment"),
    )


def _row_value(row: sqlite3.Row, key: str) -> object | None:
    if key not in row.keys():
        return None
    return row[key]


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


def _summary_from_row(row: sqlite3.Row) -> GenerationRecordSummary:
    return GenerationRecordSummary(
        id=row["id"],
        created_at=row["created_at"],
        request_id=row["request_id"],
        status=row["status"],
        description=row["description"],
        duration_ms=row["duration_ms"],
        model=row["model"],
        attempts=row["attempts"],
        retrieved_chunks=row["retrieved_chunks"],
        retrieved_sources=_json_loads_list(row["retrieved_sources_json"]),
        case_count=row["case_count"],
        error=row["error"],
        usage=_usage_from_raw(row["usage_json"]),
        gate=_gate_from_raw(row["gate_detail_json"]),
        gate_resolution=_gate_resolution_from_row(row),
    )
