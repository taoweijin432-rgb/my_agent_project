import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.test_plan import (
    TestAgentWorkflowJobDetail as WorkflowJobDetail,
    TestAgentWorkflowJobStatus as WorkflowJobStatus,
    TestAgentWorkflowJobTiming as WorkflowJobTiming,
    TestAgentWorkflowResult as WorkflowResult,
    TestAgentWorkflowStageTiming as WorkflowStageTiming,
    TestAgentWorkflowTiming as WorkflowTiming,
    TestExecutionReport as ExecutionReport,
    TestPlan as Plan,
    TestPlanStep as PlanStep,
    TestReportStatus as ReportStatus,
    TestToolType as ToolType,
    ToolRun,
    ToolRunStatus as RunStatus,
)
from scripts.smoke_test_agent_workflow_rq_mysql import (
    DockerWorkflowSmokeConfig,
    WorkflowRQMySQLSmokeError,
    run_docker_workflow_smoke,
    run_submitter_smoke,
)


def test_submitter_smoke_counts_workflow_reports_and_artifacts() -> None:
    result = run_submitter_smoke(
        Settings(database_backend="mysql", generation_job_queue_backend="rq"),
        job_count=3,
        poll_interval_seconds=0.01,
        queue_factory=lambda _: FakeWorkflowQueue(),
        alert_report_builder=lambda _: _alert_ok(),
    )

    assert result["ok"] is True
    assert result["job_count"] == 3
    assert result["total_job_count"] == 3
    assert result["rounds"] == 1
    assert result["jobs_per_round"] == 3
    assert result["job_status_counts"] == {"succeeded": 3}
    assert result["report_status_counts"] == {"passed": 3}
    assert result["tool_status_counts"] == {"passed": 3}
    assert result["artifact_count"] == 3
    assert result["covered_requirement_count"] == 3
    assert result["timing_summary_ms"]["plan_generation_ms"]["count"] == 3
    assert result["timing_summary_ms"]["plan_generation_ms"]["avg"] == 10
    assert result["throughput"]["job_count"] == 3
    assert result["throughput"]["worker_count"] == 1
    assert result["throughput"]["jobs_per_second"] > 0
    assert result["throughput"]["max_queue_wait_ms"] == 1000
    assert result["throughput"]["max_job_runtime_ms"] == 1000
    assert result["queue_alert_status"]["ok"] is True
    assert result["configured_database_backend"] == "mysql"
    assert result["workflow_job_store_backend"] == "mysql"


def test_submitter_smoke_runs_multiple_rounds_and_alert_checks() -> None:
    alert_builder = FakeAlertBuilder()

    result = run_submitter_smoke(
        Settings(database_backend="mysql", generation_job_queue_backend="rq"),
        jobs_per_round=2,
        rounds=2,
        worker_count=2,
        poll_interval_seconds=0.01,
        queue_factory=lambda _: FakeWorkflowQueue(),
        alert_report_builder=alert_builder,
    )

    assert result["ok"] is True
    assert result["job_count"] == 4
    assert result["jobs_per_round"] == 2
    assert result["rounds"] == 2
    assert result["worker_count"] == 2
    assert result["report_status_counts"] == {"passed": 4}
    assert result["tool_status_counts"] == {"passed": 4}
    assert result["artifact_count"] == 4
    assert result["covered_requirement_count"] == 4
    assert len(result["round_results"]) == 2
    assert [round_result["job_count"] for round_result in result["round_results"]] == [
        2,
        2,
    ]
    assert all("throughput" in round_result for round_result in result["round_results"])
    assert alert_builder.call_count == 2


def test_submitter_smoke_can_fail_on_queue_wait_threshold() -> None:
    with pytest.raises(WorkflowRQMySQLSmokeError, match="max_queue_wait_ms"):
        run_submitter_smoke(
            Settings(database_backend="mysql", generation_job_queue_backend="rq"),
            job_count=1,
            poll_interval_seconds=0.01,
            max_queue_wait_ms=999,
            queue_factory=lambda _: FakeWorkflowQueue(),
            alert_report_builder=lambda _: _alert_ok(),
        )


def test_submitter_smoke_can_fail_on_throughput_threshold() -> None:
    with pytest.raises(WorkflowRQMySQLSmokeError, match="jobs_per_second"):
        run_submitter_smoke(
            Settings(database_backend="mysql", generation_job_queue_backend="rq"),
            job_count=1,
            poll_interval_seconds=0.01,
            min_throughput_jobs_per_second=1_000_000_000,
            queue_factory=lambda _: FakeWorkflowQueue(),
            alert_report_builder=lambda _: _alert_ok(),
        )


def test_submitter_smoke_requires_rq_mysql_settings() -> None:
    with pytest.raises(WorkflowRQMySQLSmokeError):
        run_submitter_smoke(
            Settings(database_backend="sqlite", generation_job_queue_backend="rq"),
            queue_factory=lambda _: FakeWorkflowQueue(),
            alert_report_builder=lambda _: _alert_ok(),
        )


def test_docker_workflow_smoke_starts_api_worker_and_cleans_up() -> None:
    runner = FakeDockerRunner()

    result = run_docker_workflow_smoke(
        DockerWorkflowSmokeConfig(
            project_root=Path("/tmp/project"),
            worker_container_name="workflow-smoke",
            job_count=3,
            timeout_seconds=30,
        ),
        runner=runner,
    )

    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]] == [
        "start-services",
        "wait-api-health",
        "init-mysql",
        "start-worker",
        "submit-and-poll",
        "cleanup-worker",
    ]
    start_command = _command_containing(runner.commands, "up")
    assert "redis" in start_command
    assert "mysql" in start_command
    assert "api" in start_command
    submit_command = _command_containing(runner.commands, "--submit-only")
    assert "scripts/smoke_test_agent_workflow_rq_mysql.py" in submit_command
    assert "--job-count" in submit_command
    assert "--jobs-per-round" in submit_command
    assert "--http-base-url" in submit_command
    assert "3" in submit_command
    assert "TEST_TOOL_HTTP_BASE_URL_ALLOWLIST=http://api:8000" in submit_command
    assert ["docker", "rm", "-f", "workflow-smoke"] in runner.commands


def test_docker_workflow_smoke_starts_multiple_workers() -> None:
    runner = FakeDockerRunner()

    result = run_docker_workflow_smoke(
        DockerWorkflowSmokeConfig(
            project_root=Path("/tmp/project"),
            worker_container_name="workflow-smoke",
            job_count=2,
            rounds=2,
            worker_count=2,
            max_queue_wait_ms=5000,
            min_throughput_jobs_per_second=0.01,
            timeout_seconds=30,
        ),
        runner=runner,
    )

    assert result["ok"] is True
    assert result["worker_container_names"] == ["workflow-smoke-1", "workflow-smoke-2"]
    assert [step["name"] for step in result["steps"]] == [
        "start-services",
        "wait-api-health",
        "init-mysql",
        "start-worker-1",
        "start-worker-2",
        "submit-and-poll",
        "cleanup-worker-1",
        "cleanup-worker-2",
    ]
    assert _command_containing(runner.commands, "workflow-smoke-1")[:4] == [
        "docker",
        "compose",
        "--profile",
        "mysql",
    ]
    assert _command_containing(runner.commands, "workflow-smoke-2")[:4] == [
        "docker",
        "compose",
        "--profile",
        "mysql",
    ]
    submit_command = _command_containing(runner.commands, "--submit-only")
    assert "--fail-over-max-queue-wait-ms" in submit_command
    assert "--fail-under-throughput-jobs-per-second" in submit_command
    assert ["docker", "rm", "-f", "workflow-smoke-1"] in runner.commands
    assert ["docker", "rm", "-f", "workflow-smoke-2"] in runner.commands


def test_docker_workflow_smoke_cleans_worker_when_submit_fails() -> None:
    runner = FakeDockerRunner(fail_submit=True)

    with pytest.raises(WorkflowRQMySQLSmokeError):
        run_docker_workflow_smoke(
            DockerWorkflowSmokeConfig(
                project_root=Path("/tmp/project"),
                worker_container_name="workflow-smoke",
                start_services=False,
                initialize_mysql=False,
            ),
            runner=runner,
        )

    assert ["docker", "rm", "-f", "workflow-smoke"] in runner.commands


class FakeWorkflowQueue:
    def __init__(self) -> None:
        self.requests = {}

    def submit(self, request):
        job_id = f"workflow-job-{len(self.requests) + 1}"
        self.requests[job_id] = request
        return _detail(job_id, request, status=WorkflowJobStatus.queued)

    def get_job(self, job_id: str):
        request = self.requests[job_id]
        requirement = request.generation_request.requirements[0]
        plan = Plan(
            id=f"plan-{job_id}",
            title="Workflow smoke plan",
            source=request.generation_request.source,
            requirements=[requirement],
            steps=[
                PlanStep(
                    id="TP-001",
                    title="API 健康检查",
                    objective="GET /health 200 API 健康检查必须返回成功。",
                    requirement_ids=[requirement.id],
                    tool=ToolType.http,
                    tool_args={
                        "method": "GET",
                        "path": "/health",
                        "expected_status": 200,
                    },
                    success_criteria=["返回 200"],
                )
            ],
        )
        report = ExecutionReport(
            id=f"report-{job_id}",
            plan_id=plan.id,
            status=ReportStatus.passed,
            tool_runs=[
                ToolRun(
                    id=f"run-{job_id}",
                    plan_step_id="TP-001",
                    tool=ToolType.http,
                    status=RunStatus.passed,
                    artifact_paths=[f"artifact-{job_id}.txt"],
                )
            ],
            requirement_coverage={requirement.id: True},
        )
        return _detail(
            job_id,
            request,
            status=WorkflowJobStatus.succeeded,
            result=WorkflowResult(
                plan=plan,
                report=report,
                timing=WorkflowTiming(
                    total_ms=12.3,
                    stages=[
                        WorkflowStageTiming(
                            name="plan_generation",
                            started_at="2026-07-13T00:00:00Z",
                            finished_at="2026-07-13T00:00:00.010000Z",
                            duration_ms=10,
                        ),
                        WorkflowStageTiming(
                            name="tool_execution",
                            started_at="2026-07-13T00:00:00.010000Z",
                            finished_at="2026-07-13T00:00:00.012000Z",
                            duration_ms=2,
                        ),
                        WorkflowStageTiming(
                            name="report_build",
                            started_at="2026-07-13T00:00:00.012000Z",
                            finished_at="2026-07-13T00:00:00.012300Z",
                            duration_ms=0.3,
                        ),
                    ],
                ),
            ),
        )

    def list_jobs(self, *, limit=20, offset=0, status=None):
        return []


class FakeAlertBuilder:
    def __init__(self) -> None:
        self.call_count = 0

    def __call__(self, _settings):
        self.call_count += 1
        return _alert_ok()


class FakeDockerRunner:
    def __init__(self, *, fail_submit: bool = False) -> None:
        self.fail_submit = fail_submit
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if "scripts/smoke_test_agent_workflow_rq_mysql.py" in command:
            if self.fail_submit:
                return _completed(command, 1, stdout='{"ok": false}')
            return _completed(
                command,
                0,
                stdout=(
                    '{"ok": true, "job_count": 3, "rounds": 1, '
                    '"worker_count": 1, '
                    '"report_status_counts": {"passed": 3}}'
                ),
            )
        if command[:3] == ["docker", "rm", "-f"]:
            return _completed(command, 0, stdout=command[-1])
        return _completed(command, 0, stdout="ok")


def _detail(
    job_id: str,
    request,
    *,
    status: WorkflowJobStatus,
    result: WorkflowResult | None = None,
) -> WorkflowJobDetail:
    timing = (
        WorkflowJobTiming(
            queue_wait_ms=1000,
            job_runtime_ms=1000,
            job_total_ms=2000,
            workflow_total_ms=12.3,
            plan_generation_ms=10,
            tool_execution_ms=2,
            report_build_ms=0.3,
        )
        if result is not None
        else WorkflowJobTiming()
    )
    return WorkflowJobDetail(
        id=job_id,
        status=status,
        created_at="2026-07-13T00:00:00Z",
        updated_at="2026-07-13T00:00:02Z",
        started_at="2026-07-13T00:00:01Z" if result is not None else None,
        finished_at="2026-07-13T00:00:02Z" if result is not None else None,
        timing=timing,
        request=request,
        result=result,
    )


def _completed(
    command: list[str],
    returncode: int,
    *,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _alert_ok() -> dict:
    return {
        "ok": True,
        "alerts": [],
        "metrics": {
            "test_agent_workflow": {
                "database_active_jobs": 0,
                "rq_queued": 0,
                "rq_started": 0,
                "rq_failed": 0,
                "worker_count": 1,
            }
        },
    }


def _command_containing(commands: list[list[str]], value: str) -> list[str]:
    for command in commands:
        if value in command:
            return command
    raise AssertionError(f"No command contains {value!r}")
