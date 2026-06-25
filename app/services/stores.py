from typing import Protocol

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationJobDetail,
    GenerationJobError,
    GenerationJobSummary,
    GenerationGateDetail,
    GenerationRecordDetail,
    GenerationRecordSummary,
    GenerationUsage,
)


class GenerationHistoryRepository(Protocol):
    def record_success(
        self,
        request: GenerateRequest,
        response: GenerateResponse,
        *,
        duration_ms: float,
        request_id: str | None = None,
    ) -> str | None:
        pass

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
        pass

    def list_records(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationRecordSummary]:
        pass

    def list_gate_records(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        gate_status: str | None = "pending",
    ) -> list[GenerationRecordSummary]:
        pass

    def get_record(self, record_id: str) -> GenerationRecordDetail | None:
        pass

    def resolve_gate_record(
        self,
        record_id: str,
        *,
        decision: str,
        resolved_by: str | None = None,
        comment: str | None = None,
    ) -> GenerationRecordDetail | None:
        pass


class GenerationJobRepository(Protocol):
    def create_job(
        self,
        request: GenerateRequest,
        *,
        queue_backend: str,
        queue_job_id: str | None = None,
    ) -> GenerationJobDetail:
        pass

    def set_queue_job_id(self, job_id: str, queue_job_id: str) -> None:
        pass

    def get_job(self, job_id: str) -> GenerationJobDetail | None:
        pass

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationJobSummary]:
        pass

    def count_active_jobs(self) -> int:
        pass

    def count_jobs_by_status(self) -> dict[str, int]:
        pass

    def mark_running(self, job_id: str, *, worker_id: str | None = None) -> None:
        pass

    def mark_succeeded(
        self,
        job_id: str,
        *,
        response: GenerateResponse,
        record_id: str | None,
    ) -> None:
        pass

    def mark_failed(
        self,
        job_id: str,
        *,
        error: GenerationJobError,
        record_id: str | None = None,
    ) -> None:
        pass

    def fail_stale_running_jobs(self, *, stale_after_seconds: int) -> list[str]:
        pass

    def get_request(self, job_id: str) -> GenerateRequest | None:
        pass


def create_generation_history_store(settings: Settings) -> GenerationHistoryRepository:
    backend = settings.database_backend.strip().lower()
    if backend == "sqlite":
        from app.services.history import GenerationHistoryStore

        return GenerationHistoryStore(settings)
    if backend == "mysql":
        from app.services.mysql_stores import MySQLGenerationHistoryStore

        return MySQLGenerationHistoryStore(settings)
    raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'mysql'.")


def create_generation_job_store(settings: Settings) -> GenerationJobRepository:
    backend = settings.database_backend.strip().lower()
    if backend == "sqlite":
        from app.services.generation_job_store import GenerationJobStore

        return GenerationJobStore(settings)
    if backend == "mysql":
        from app.services.mysql_stores import MySQLGenerationJobStore

        return MySQLGenerationJobStore(settings)
    raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'mysql'.")
