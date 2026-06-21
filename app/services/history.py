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
    GenerationRecordDetail,
    GenerationRecordSummary,
)
from app.services.quality import score_generation_quality


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
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO generation_records (
                        id, created_at, request_id, status, description, request_json,
                        response_json, error, duration_ms, model, attempts,
                        retrieved_chunks, retrieved_sources_json, case_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ) -> str | None:
        if not self.enabled:
            return None

        record_id = uuid4().hex
        created_at = _utc_now()
        request_json = _json_dumps(request.model_dump(mode="json"))
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO generation_records (
                        id, created_at, request_id, status, description, request_json,
                        response_json, error, duration_ms, model, attempts,
                        retrieved_chunks, retrieved_sources_json, case_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                       case_count, error
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
                       case_count, error, request_json, response_json
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
                        case_count INTEGER NOT NULL
                    )
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
    )
