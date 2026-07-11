import pytest
from pydantic import ValidationError

from app.models.test_plan import HTTPToolArgs
from app.models.test_plan import PytestToolArgs
from app.models.test_plan import TestPlanExecutionJobStatus as ExecutionJobStatus
from app.models.test_plan import TestPlanExecutionJobSummary as ExecutionJobSummary
from app.models.test_plan import TestReportStatus as ReportStatus
from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import ToolRun, ToolRunStatus, summarize_report_status


def _tool_run(status: ToolRunStatus) -> ToolRun:
    return ToolRun(
        id=f"run-{status.value}",
        plan_step_id="step-1",
        tool=ToolType.pytest,
        status=status,
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], ReportStatus.incomplete),
        ([ToolRunStatus.queued], ReportStatus.incomplete),
        ([ToolRunStatus.running, ToolRunStatus.passed], ReportStatus.incomplete),
        ([ToolRunStatus.passed, ToolRunStatus.failed], ReportStatus.failed),
        ([ToolRunStatus.passed, ToolRunStatus.blocked], ReportStatus.blocked),
        ([ToolRunStatus.passed, ToolRunStatus.skipped], ReportStatus.passed),
        ([ToolRunStatus.skipped], ReportStatus.incomplete),
        ([ToolRunStatus.failed, ToolRunStatus.blocked], ReportStatus.failed),
    ],
)
def test_summarize_report_status_prioritizes_actionable_states(
    statuses: list[ToolRunStatus],
    expected: ReportStatus,
) -> None:
    assert summarize_report_status([_tool_run(status) for status in statuses]) == expected


def test_http_tool_args_normalizes_endpoint_hint_and_statuses() -> None:
    args = HTTPToolArgs(
        endpoint_hint="POST /api/v1/refunds",
        headers={"X-Test": "yes"},
        expected_status=[200, 201],
    )

    assert args.resolved_method == "POST"
    assert args.resolved_path == "/api/v1/refunds"
    assert args.expected_statuses == {200, 201}


def test_http_tool_args_rejects_external_url() -> None:
    with pytest.raises(ValidationError):
        HTTPToolArgs(path="https://example.com/api")


def test_pytest_tool_args_requires_safe_test_path_field() -> None:
    args = PytestToolArgs(path="tests/test_tool_adapters.py", maxfail=2)

    assert args.resolved_test_path == "tests/test_tool_adapters.py"
    assert args.maxfail == 2

    with pytest.raises(ValidationError):
        PytestToolArgs(maxfail=0)


def test_test_plan_execution_job_status_is_strict_enum() -> None:
    summary = ExecutionJobSummary(
        id="job-1",
        status="queued",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
    )

    assert summary.status == ExecutionJobStatus.queued

    with pytest.raises(ValidationError):
        ExecutionJobSummary(
            id="job-1",
            status="done",
            created_at="2026-07-10T00:00:00+00:00",
            updated_at="2026-07-10T00:00:00+00:00",
        )
