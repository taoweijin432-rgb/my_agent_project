from pathlib import Path
import sqlite3

from app.core.config import Settings
from app.models.test_plan import TestExecutionReport as ExecutionReport
from app.models.test_plan import TestPlan as Plan
from app.models.test_plan import TestPlanExecutionJobError as ExecutionJobError
from app.models.test_plan import TestPlanExecutionRequest as PlanExecutionRequest
from app.models.test_plan import TestReportStatus as ReportStatus
from app.services.test_plan_execution_store import TestPlanExecutionJobStore as JobStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(generation_history_db_path=str(tmp_path / "app.sqlite3"))


def _request() -> PlanExecutionRequest:
    return PlanExecutionRequest(
        plan=Plan(id="plan-1", title="测试计划"),
        http_base_url="http://testserver",
    )


def _report() -> ExecutionReport:
    return ExecutionReport(
        id="report-plan-1",
        plan_id="plan-1",
        status=ReportStatus.passed,
    )


def test_test_plan_execution_store_persists_successful_job(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())

    store.mark_running(created.id)
    store.mark_succeeded(created.id, _report())

    detail = store.get_job(created.id)
    jobs = store.list_jobs(status="succeeded")

    assert detail is not None
    assert detail.status == "succeeded"
    assert detail.report is not None
    assert detail.report.status == ReportStatus.passed
    assert jobs[0].id == created.id


def test_test_plan_execution_store_persists_failed_job(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())

    store.mark_failed(
        created.id,
        ExecutionJobError(code="execution_failed", message="adapter failed"),
    )

    detail = store.get_job(created.id)

    assert detail is not None
    assert detail.status == "failed"
    assert detail.error is not None
    assert detail.error.code == "execution_failed"


def test_test_plan_execution_store_returns_request_and_active_count(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())

    request = store.get_request(created.id)
    active_count = store.count_active_jobs()
    counts = store.count_jobs_by_status()

    assert request is not None
    assert request.plan.id == "plan-1"
    assert active_count == 1
    assert counts == {"queued": 1}


def test_test_plan_execution_store_fails_stale_running_jobs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    store = JobStore(settings)
    created = store.create_job(_request())
    store.mark_running(created.id)
    with sqlite3.connect(tmp_path / "app.sqlite3") as connection:
        connection.execute(
            """
            UPDATE test_plan_execution_jobs
            SET started_epoch = 1
            WHERE id = ?
            """,
            (created.id,),
        )
        connection.commit()

    stale_ids = store.fail_stale_running_jobs(stale_after_seconds=60)
    detail = store.get_job(created.id)

    assert stale_ids == [created.id]
    assert detail is not None
    assert detail.status == "failed"
    assert detail.error is not None
    assert detail.error.code == "test_plan_execution_job_stale"


def test_test_plan_execution_store_fails_stale_queued_jobs(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())
    with sqlite3.connect(tmp_path / "app.sqlite3") as connection:
        connection.execute(
            """
            UPDATE test_plan_execution_jobs
            SET created_epoch = 1
            WHERE id = ?
            """,
            (created.id,),
        )
        connection.commit()

    running_only_ids = store.fail_stale_running_jobs(stale_after_seconds=60)
    stale_ids = store.fail_stale_active_jobs(stale_after_seconds=60)
    detail = store.get_job(created.id)

    assert running_only_ids == []
    assert stale_ids == [created.id]
    assert detail is not None
    assert detail.status == "failed"
    assert detail.error is not None
    assert detail.error.code == "test_plan_execution_job_stale"
    assert "queued or running" in detail.error.message
