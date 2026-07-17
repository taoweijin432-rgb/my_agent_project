import subprocess
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.test_plan import (
    TestExecutionReport as ExecutionReport,
    TestPlanExecutionJobDetail as ExecutionJobDetail,
    TestPlanExecutionJobStatus as ExecutionJobStatus,
    TestReportStatus as ReportStatus,
    TestToolType as ToolType,
    ToolRun,
    ToolRunStatus as RunStatus,
)
from scripts.smoke_rq_mysql_worker_stability import (
    DockerStabilityConfig,
    RQMySQLWorkerStabilitySmokeError,
    run_docker_stability_smoke,
    run_submitter_smoke,
)


def test_submitter_smoke_counts_passed_failed_reports_and_artifacts() -> None:
    result = run_submitter_smoke(
        Settings(database_backend="mysql", generation_job_queue_backend="rq"),
        job_count=4,
        failure_count=1,
        poll_interval_seconds=0.01,
        queue_factory=lambda _: FakeExecutionQueue(),
        alert_report_builder=lambda _: _alert_ok(),
    )

    assert result["ok"] is True
    assert result["job_count"] == 4
    assert result["total_job_count"] == 4
    assert result["rounds"] == 1
    assert result["jobs_per_round"] == 4
    assert result["job_status_counts"] == {"succeeded": 4}
    assert result["report_status_counts"] == {"failed": 1, "passed": 3}
    assert result["tool_status_counts"] == {"failed": 1, "passed": 3}
    assert result["artifact_count"] == 4
    assert result["queue_alert_status"]["ok"] is True
    assert result["configured_database_backend"] == "mysql"
    assert result["execution_job_store_backend"] == "mysql"


def test_submitter_smoke_runs_multiple_rounds_and_alert_checks() -> None:
    alert_builder = FakeAlertBuilder()

    result = run_submitter_smoke(
        Settings(database_backend="mysql", generation_job_queue_backend="rq"),
        jobs_per_round=3,
        failure_count=1,
        rounds=2,
        worker_count=2,
        poll_interval_seconds=0.01,
        queue_factory=lambda _: FakeExecutionQueue(),
        alert_report_builder=alert_builder,
    )

    assert result["ok"] is True
    assert result["job_count"] == 6
    assert result["jobs_per_round"] == 3
    assert result["rounds"] == 2
    assert result["worker_count"] == 2
    assert result["report_status_counts"] == {"failed": 2, "passed": 4}
    assert result["tool_status_counts"] == {"failed": 2, "passed": 4}
    assert result["artifact_count"] == 6
    assert len(result["round_results"]) == 2
    assert [round_result["job_count"] for round_result in result["round_results"]] == [
        3,
        3,
    ]
    assert alert_builder.call_count == 2


def test_submitter_smoke_requires_rq_mysql_settings() -> None:
    with pytest.raises(RQMySQLWorkerStabilitySmokeError):
        run_submitter_smoke(
            Settings(database_backend="sqlite", generation_job_queue_backend="rq"),
            queue_factory=lambda _: FakeExecutionQueue(),
            alert_report_builder=lambda _: _alert_ok(),
        )


def test_docker_stability_smoke_starts_worker_and_cleans_up() -> None:
    runner = FakeDockerRunner()

    result = run_docker_stability_smoke(
        DockerStabilityConfig(
            project_root=Path("/tmp/project"),
            worker_container_name="worker-smoke",
            job_count=4,
            failure_count=1,
            timeout_seconds=30,
        ),
        runner=runner,
    )

    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]] == [
        "start-services",
        "init-mysql",
        "start-worker",
        "submit-and-poll",
        "cleanup-worker",
    ]
    submit_command = _command_containing(runner.commands, "--submit-only")
    assert "scripts/smoke_rq_mysql_worker_stability.py" in submit_command
    assert "--job-count" in submit_command
    assert "--jobs-per-round" in submit_command
    assert "4" in submit_command
    assert "--rounds" in submit_command
    assert "--worker-count" in submit_command
    assert "TEST_TOOL_PYTEST_ENABLED=true" in submit_command
    assert "TEST_TOOL_PYTEST_ALLOWED_PATHS=scripts" in submit_command
    assert ["docker", "rm", "-f", "worker-smoke"] in runner.commands


def test_docker_stability_smoke_starts_multiple_workers() -> None:
    runner = FakeDockerRunner()

    result = run_docker_stability_smoke(
        DockerStabilityConfig(
            project_root=Path("/tmp/project"),
            worker_container_name="worker-smoke",
            job_count=3,
            failure_count=1,
            rounds=2,
            worker_count=2,
            timeout_seconds=30,
        ),
        runner=runner,
    )

    assert result["ok"] is True
    assert result["worker_container_names"] == ["worker-smoke-1", "worker-smoke-2"]
    assert [step["name"] for step in result["steps"]] == [
        "start-services",
        "init-mysql",
        "start-worker-1",
        "start-worker-2",
        "submit-and-poll",
        "cleanup-worker-1",
        "cleanup-worker-2",
    ]
    assert _command_containing(runner.commands, "worker-smoke-1")[:4] == [
        "docker",
        "compose",
        "--profile",
        "mysql",
    ]
    assert _command_containing(runner.commands, "worker-smoke-2")[:4] == [
        "docker",
        "compose",
        "--profile",
        "mysql",
    ]
    submit_command = _command_containing(runner.commands, "--submit-only")
    assert "--rounds" in submit_command
    assert "2" in submit_command
    assert "--jobs-per-round" in submit_command
    assert "3" in submit_command
    assert "--worker-count" in submit_command
    assert ["docker", "rm", "-f", "worker-smoke-1"] in runner.commands
    assert ["docker", "rm", "-f", "worker-smoke-2"] in runner.commands


def test_docker_stability_smoke_cleans_worker_when_submit_fails() -> None:
    runner = FakeDockerRunner(fail_submit=True)

    with pytest.raises(RQMySQLWorkerStabilitySmokeError):
        run_docker_stability_smoke(
            DockerStabilityConfig(
                project_root=Path("/tmp/project"),
                worker_container_name="worker-smoke",
                start_services=False,
                initialize_mysql=False,
            ),
            runner=runner,
        )

    assert ["docker", "rm", "-f", "worker-smoke"] in runner.commands


def test_docker_stability_smoke_cleans_all_workers_when_submit_fails() -> None:
    runner = FakeDockerRunner(fail_submit=True)

    with pytest.raises(RQMySQLWorkerStabilitySmokeError):
        run_docker_stability_smoke(
            DockerStabilityConfig(
                project_root=Path("/tmp/project"),
                worker_container_name="worker-smoke",
                worker_count=2,
                start_services=False,
                initialize_mysql=False,
            ),
            runner=runner,
        )

    assert ["docker", "rm", "-f", "worker-smoke-1"] in runner.commands
    assert ["docker", "rm", "-f", "worker-smoke-2"] in runner.commands


class FakeExecutionQueue:
    def __init__(self) -> None:
        self.requests = {}

    def submit(self, request):
        job_id = f"job-{len(self.requests) + 1}"
        self.requests[job_id] = request
        return _detail(job_id, request, status=ExecutionJobStatus.queued)

    def get_job(self, job_id: str):
        request = self.requests[job_id]
        report_status = (
            ReportStatus.failed
            if "fail_expected" in request.plan.steps[0].tool_args["keyword"]
            else ReportStatus.passed
        )
        tool_status = (
            RunStatus.failed
            if report_status == ReportStatus.failed
            else RunStatus.passed
        )
        report = ExecutionReport(
            id=f"report-{job_id}",
            plan_id=request.plan.id,
            status=report_status,
            tool_runs=[
                ToolRun(
                    id=f"run-{job_id}",
                    plan_step_id=request.plan.steps[0].id,
                    tool=ToolType.pytest,
                    status=tool_status,
                    artifact_paths=[f"artifact-{job_id}.txt"],
                )
            ],
        )
        return _detail(
            job_id,
            request,
            status=ExecutionJobStatus.succeeded,
            report=report,
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
        if "scripts/smoke_rq_mysql_worker_stability.py" in command:
            if self.fail_submit:
                return _completed(command, 1, stdout='{"ok": false}')
            return _completed(
                command,
                0,
                stdout=(
                    '{"ok": true, "job_count": 4, "rounds": 1, '
                    '"worker_count": 1, '
                    '"report_status_counts": {"failed": 1, "passed": 3}}'
                ),
            )
        if command[:3] == ["docker", "rm", "-f"]:
            return _completed(command, 0, stdout=command[-1])
        return _completed(command, 0, stdout="ok")


def _detail(
    job_id: str,
    request,
    *,
    status: ExecutionJobStatus,
    report: ExecutionReport | None = None,
) -> ExecutionJobDetail:
    return ExecutionJobDetail(
        id=job_id,
        status=status,
        created_at="2026-07-13T00:00:00Z",
        updated_at="2026-07-13T00:00:01Z",
        request=request,
        report=report,
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
            "test_plan_execution": {
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
