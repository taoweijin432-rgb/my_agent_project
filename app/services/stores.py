from importlib import import_module
from typing import Any, Protocol

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
from app.models.test_plan import (
    TestAgentWorkflowJobDetail,
    TestAgentWorkflowJobError,
    TestAgentWorkflowJobSummary,
    TestAgentWorkflowRequest,
    TestAgentWorkflowResult,
    TestExecutionReport,
    TestPlanExecutionJobDetail,
    TestPlanExecutionJobError,
    TestPlanExecutionJobSummary,
    TestPlanExecutionRequest,
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

    def count_records_by_status(self) -> dict[str, int]:
        pass

    def count_gate_records_by_status(self) -> dict[str, int]:
        pass

    def summarize_usage(self) -> dict[str, Any]:
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


class TestPlanExecutionJobRepository(Protocol):
    def create_job(
        self,
        request: TestPlanExecutionRequest,
    ) -> TestPlanExecutionJobDetail:
        pass

    def get_request(self, job_id: str) -> TestPlanExecutionRequest | None:
        pass

    def count_active_jobs(self) -> int:
        pass

    def count_jobs_by_status(self) -> dict[str, int]:
        pass

    def get_job(self, job_id: str) -> TestPlanExecutionJobDetail | None:
        pass

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[TestPlanExecutionJobSummary]:
        pass

    def mark_running(self, job_id: str) -> None:
        pass

    def mark_succeeded(self, job_id: str, report: TestExecutionReport) -> None:
        pass

    def mark_failed(
        self,
        job_id: str,
        error: TestPlanExecutionJobError,
    ) -> None:
        pass

    def fail_stale_active_jobs(self, *, stale_after_seconds: int) -> list[str]:
        pass

    def fail_stale_running_jobs(self, *, stale_after_seconds: int) -> list[str]:
        pass


class TestAgentWorkflowJobRepository(Protocol):
    def create_job(
        self,
        request: TestAgentWorkflowRequest,
    ) -> TestAgentWorkflowJobDetail:
        pass

    def get_request(self, job_id: str) -> TestAgentWorkflowRequest | None:
        pass

    def count_active_jobs(self) -> int:
        pass

    def count_jobs_by_status(self) -> dict[str, int]:
        pass

    def get_job(self, job_id: str) -> TestAgentWorkflowJobDetail | None:
        pass

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[TestAgentWorkflowJobSummary]:
        pass

    def mark_running(self, job_id: str) -> None:
        pass

    def mark_succeeded(self, job_id: str, result: TestAgentWorkflowResult) -> None:
        pass

    def mark_failed(
        self,
        job_id: str,
        error: TestAgentWorkflowJobError,
    ) -> None:
        pass

    def fail_stale_active_jobs(self, *, stale_after_seconds: int) -> list[str]:
        pass

    def fail_stale_running_jobs(self, *, stale_after_seconds: int) -> list[str]:
        pass


def create_generation_history_store(settings: Settings) -> GenerationHistoryRepository:
    backend = settings.database_backend.strip().lower()
    if backend == "sqlite":
        store_class = _load_store_class("app.services.history", "GenerationHistoryStore")
        return store_class(settings)
    if backend == "mysql":
        store_class = _load_store_class(
            "app.services.mysql_stores",
            "MySQLGenerationHistoryStore",
        )
        return store_class(settings)
    raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'mysql'.")


def create_generation_job_store(settings: Settings) -> GenerationJobRepository:
    backend = settings.database_backend.strip().lower()
    if backend == "sqlite":
        store_class = _load_store_class(
            "app.services.generation_job_store",
            "GenerationJobStore",
        )
        return store_class(settings)
    if backend == "mysql":
        store_class = _load_store_class(
            "app.services.mysql_stores",
            "MySQLGenerationJobStore",
        )
        return store_class(settings)
    raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'mysql'.")


def create_test_plan_execution_job_store(
    settings: Settings,
) -> TestPlanExecutionJobRepository:
    backend = settings.database_backend.strip().lower()
    if backend == "sqlite":
        store_class = _load_store_class(
            "app.services.test_plan_execution_store",
            "TestPlanExecutionJobStore",
        )
        return store_class(settings)
    if backend == "mysql":
        store_class = _load_store_class(
            "app.services.mysql_stores",
            "MySQLTestPlanExecutionJobStore",
        )
        return store_class(settings)
    raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'mysql'.")


def create_test_agent_workflow_job_store(
    settings: Settings,
) -> TestAgentWorkflowJobRepository:
    backend = settings.database_backend.strip().lower()
    if backend == "sqlite":
        store_class = _load_store_class(
            "app.services.test_agent_workflow_store",
            "TestAgentWorkflowJobStore",
        )
        return store_class(settings)
    if backend == "mysql":
        store_class = _load_store_class(
            "app.services.mysql_stores",
            "MySQLTestAgentWorkflowJobStore",
        )
        return store_class(settings)
    raise ValueError("DATABASE_BACKEND must be 'sqlite' or 'mysql'.")


def _load_store_class(module_name: str, class_name: str) -> Any:
    return getattr(import_module(module_name), class_name)
