import json
import subprocess
from pathlib import Path

import pytest

from scripts import smoke_service_mode_dependency_jitter
from scripts.smoke_service_mode_dependency_jitter import (
    ServiceModeDependencyJitterConfig,
    ServiceModeDependencyJitterError,
    main,
    run_dependency_jitter_smoke,
)


class FakeDockerRunner:
    def __init__(self, *, redis_outage_returns_success: bool = False) -> None:
        self.redis_down = False
        self.mysql_down = False
        self.redis_outage_returns_success = redis_outage_returns_success
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if "stop" in command:
            service = command[-1]
            if service == "redis":
                self.redis_down = True
            if service == "mysql":
                self.mysql_down = True
            return _completed(command, 0, stdout=f"stopped {service}")
        if "up" in command:
            if command[-1] == "redis":
                self.redis_down = False
            if command[-1] == "mysql":
                self.mysql_down = False
            if "redis" in command and "mysql" in command:
                self.redis_down = False
                self.mysql_down = False
            return _completed(command, 0, stdout="started")
        if "scripts/check_readiness.py" in command:
            if self.redis_down or self.mysql_down:
                return _completed(command, 1, stdout='{"ready": false}')
            return _completed(command, 0, stdout='{"ready": true}')
        if "scripts/check_queue_alerts.py" in command:
            if self.redis_down:
                if self.redis_outage_returns_success:
                    return _completed(command, 0, stdout='{"ok": true}')
                return _completed(
                    command,
                    1,
                    stdout=(
                        '{"ok": false, "alerts": [{"code": "snapshot_failed", '
                        '"message": "ConnectionError redis down"}]}'
                    ),
                )
            if self.mysql_down:
                return _completed(
                    command,
                    1,
                    stdout=(
                        '{"ok": false, "alerts": [{"code": "snapshot_failed", '
                        '"message": "OperationalError mysql down"}]}'
                    ),
                )
            return _completed(command, 0, stdout='{"ok": true, "alerts": []}')
        if "scripts/smoke_service_mode_workflow_load.py" in command:
            return _completed(command, 0, stdout=json.dumps(_load_summary()))
        return _completed(command, 0)


def test_dependency_jitter_stops_recovers_and_runs_loads() -> None:
    runner = FakeDockerRunner()

    result = run_dependency_jitter_smoke(_config(), runner=runner)

    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]] == [
        "start-service-mode",
        "baseline-readiness",
        "baseline-queue-alerts",
        "baseline-load",
        "redis-stop",
        "redis-outage-queue-alerts",
        "redis-restart",
        "redis-recovered-readiness",
        "redis-recovered-queue-alerts",
        "redis-recovery-load",
        "mysql-stop",
        "mysql-outage-queue-alerts",
        "mysql-restart",
        "mysql-recovered-readiness",
        "mysql-recovered-queue-alerts",
        "mysql-recovery-load",
        "final-queue-alerts",
    ]
    assert [load["name"] for load in result["loads"]] == [
        "baseline-load",
        "redis-recovery-load",
        "mysql-recovery-load",
    ]
    start_command = runner.commands[0]
    assert start_command[:6] == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.mysql-rq.yml",
    ]
    assert "--scale" in start_command
    assert "worker=2" in start_command
    assert all("exec" in command or "stop" in command or "up" in command for command in runner.commands)
    assert runner.redis_down is False
    assert runner.mysql_down is False


def test_dependency_jitter_can_probe_only_redis_without_starting_services() -> None:
    runner = FakeDockerRunner()

    result = run_dependency_jitter_smoke(
        _config(include_mysql=False, start_services=False),
        runner=runner,
    )

    assert result["ok"] is True
    names = [step["name"] for step in result["steps"]]
    assert "start-service-mode" not in names
    assert "mysql-stop" not in names
    assert "redis-recovery-load" in names
    assert runner.redis_down is False


def test_dependency_jitter_restarts_dependency_when_outage_assertion_fails() -> None:
    runner = FakeDockerRunner(redis_outage_returns_success=True)

    with pytest.raises(ServiceModeDependencyJitterError):
        run_dependency_jitter_smoke(
            _config(include_mysql=False, start_services=False),
            runner=runner,
        )

    assert runner.redis_down is False
    assert any(command[-1] == "redis" and "up" in command for command in runner.commands)


def test_dependency_jitter_requires_component() -> None:
    with pytest.raises(ServiceModeDependencyJitterError):
        run_dependency_jitter_smoke(
            _config(include_redis=False, include_mysql=False),
            runner=FakeDockerRunner(),
        )


def test_main_writes_output_json(monkeypatch, tmp_path, capsys) -> None:
    output_path = tmp_path / "jitter.json"

    monkeypatch.setattr(
        smoke_service_mode_dependency_jitter,
        "run_dependency_jitter_smoke",
        lambda *_args, **_kwargs: {
            "ok": True,
            "steps": [],
            "loads": [],
        },
    )

    exit_code = main(["--output-json", str(output_path), "--json"])

    assert exit_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["ok"] is True
    assert '"ok": true' in capsys.readouterr().out


def _config(**overrides: object) -> ServiceModeDependencyJitterConfig:
    values = {
        "project_root": Path("/tmp/project"),
        "retry_interval_seconds": 0.0,
        "recover_retries": 1,
        "baseline_rounds": 1,
        "baseline_jobs_per_round": 1,
        "recovery_rounds": 1,
        "recovery_jobs_per_round": 1,
    }
    values.update(overrides)
    return ServiceModeDependencyJitterConfig(**values)


def _load_summary() -> dict:
    return {
        "ok": True,
        "job_count": 1,
        "jobs_by_status": {"succeeded": 1},
        "report_status_counts": {"incomplete": 1},
        "throughput": {"elapsed_seconds": 1.0, "jobs_per_second": 1.0},
        "timing_summary_ms": {},
        "queue_alert_reports": [
            {
                "alerts": [],
                "metrics": {
                    "test_agent_workflow": {
                        "worker_count": 2,
                    }
                },
            }
        ],
    }


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
