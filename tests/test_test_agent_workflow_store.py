from pathlib import Path
import sqlite3
import time

from app.core.config import Settings
from app.models.test_plan import (
    TestAgentWorkflowJobError as WorkflowJobError,
    TestAgentWorkflowRequest as WorkflowRequest,
    TestAgentWorkflowResult as WorkflowResult,
    TestAgentWorkflowTiming as WorkflowTiming,
    TestAgentWorkflowStageTiming as WorkflowStageTiming,
    TestExecutionReport as ExecutionReport,
    TestPlan as Plan,
    TestPlanGenerationRequest as PlanGenerationRequest,
    TestReportStatus as ReportStatus,
)
from app.services.test_agent_workflow_store import TestAgentWorkflowJobStore as JobStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(generation_history_db_path=str(tmp_path / "app.sqlite3"))


def _request() -> WorkflowRequest:
    return WorkflowRequest(
        generation_request=PlanGenerationRequest(description="退款接口需要覆盖幂等冲突。"),
        http_base_url="http://testserver",
    )


def _result() -> WorkflowResult:
    plan = Plan(id="plan-1", title="退款测试计划")
    return WorkflowResult(
        plan=plan,
        report=ExecutionReport(
            id="report-plan-1",
            plan_id=plan.id,
            status=ReportStatus.passed,
        ),
        timing=WorkflowTiming(
            total_ms=25.5,
            stages=[
                WorkflowStageTiming(
                    name="plan_generation",
                    started_at="2026-07-10T00:00:00+00:00",
                    finished_at="2026-07-10T00:00:00.020000+00:00",
                    duration_ms=20,
                ),
                WorkflowStageTiming(
                    name="tool_execution",
                    started_at="2026-07-10T00:00:00.020000+00:00",
                    finished_at="2026-07-10T00:00:00.025000+00:00",
                    duration_ms=5,
                ),
                WorkflowStageTiming(
                    name="report_build",
                    started_at="2026-07-10T00:00:00.025000+00:00",
                    finished_at="2026-07-10T00:00:00.025500+00:00",
                    duration_ms=0.5,
                ),
            ],
        ),
    )


def test_test_agent_workflow_store_persists_successful_job(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())

    store.mark_running(created.id)
    store.mark_succeeded(created.id, _result())

    detail = store.get_job(created.id)
    jobs = store.list_jobs(status="succeeded")

    assert detail is not None
    assert detail.status == "succeeded"
    assert detail.result is not None
    assert detail.result.plan.id == "plan-1"
    assert detail.result.report.status == ReportStatus.passed
    assert detail.timing.workflow_total_ms == 25.5
    assert detail.timing.plan_generation_ms == 20
    assert detail.timing.tool_execution_ms == 5
    assert detail.timing.report_build_ms == 0.5
    assert jobs[0].id == created.id


def test_test_agent_workflow_store_reads_legacy_result_without_timing(
    tmp_path: Path,
) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())
    store.mark_running(created.id)
    finished_epoch = time.time()
    with sqlite3.connect(tmp_path / "app.sqlite3") as connection:
        connection.execute(
            """
            UPDATE test_agent_workflow_jobs
            SET status = 'succeeded',
                result_json = ?,
                finished_at = '2026-07-10T00:00:02+00:00',
                finished_epoch = ?,
                updated_at = '2026-07-10T00:00:02+00:00'
            WHERE id = ?
            """,
            (
                '{"plan":{"id":"plan-legacy","title":"旧计划"},'
                '"report":{"id":"report-legacy","plan_id":"plan-legacy",'
                '"status":"passed"}}',
                finished_epoch,
                created.id,
            ),
        )
        connection.commit()

    detail = store.get_job(created.id)

    assert detail is not None
    assert detail.result is not None
    assert detail.result.timing.total_ms is None
    assert detail.timing.workflow_total_ms is None


def test_test_agent_workflow_store_persists_failed_job(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())

    store.mark_failed(
        created.id,
        WorkflowJobError(code="workflow_failed", message="llm timeout"),
    )

    detail = store.get_job(created.id)

    assert detail is not None
    assert detail.status == "failed"
    assert detail.error is not None
    assert detail.error.code == "workflow_failed"


def test_test_agent_workflow_store_returns_request_and_active_count(
    tmp_path: Path,
) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())

    request = store.get_request(created.id)
    active_count = store.count_active_jobs()
    counts = store.count_jobs_by_status()

    assert request is not None
    assert request.generation_request.description == "退款接口需要覆盖幂等冲突。"
    assert active_count == 1
    assert counts == {"queued": 1}


def test_test_agent_workflow_store_creates_active_index(tmp_path: Path) -> None:
    JobStore(_settings(tmp_path))

    with sqlite3.connect(tmp_path / "app.sqlite3") as connection:
        rows = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'index'
              AND tbl_name = 'test_agent_workflow_jobs'
            """
        ).fetchall()

    assert "idx_test_agent_workflow_jobs_active" in {str(row[0]) for row in rows}


def test_test_agent_workflow_store_fails_stale_running_jobs(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())
    store.mark_running(created.id)
    with sqlite3.connect(tmp_path / "app.sqlite3") as connection:
        connection.execute(
            """
            UPDATE test_agent_workflow_jobs
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
    assert detail.error.code == "test_agent_workflow_job_stale"


def test_test_agent_workflow_store_fails_stale_queued_jobs(tmp_path: Path) -> None:
    store = JobStore(_settings(tmp_path))
    created = store.create_job(_request())
    with sqlite3.connect(tmp_path / "app.sqlite3") as connection:
        connection.execute(
            """
            UPDATE test_agent_workflow_jobs
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
    assert detail.error.code == "test_agent_workflow_job_stale"
    assert "queued or running" in detail.error.message
