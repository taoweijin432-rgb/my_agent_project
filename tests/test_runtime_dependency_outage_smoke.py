import subprocess
from pathlib import Path

import pytest

from scripts.smoke_runtime_dependency_outage import (
    RuntimeDependencyOutageConfig,
    RuntimeDependencyOutageSmokeError,
    run_outage_smoke,
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
            services = set(command[command.index("-d") + 1 :])
            if "redis" in services:
                self.redis_down = False
            if "mysql" in services:
                self.mysql_down = False
            return _completed(command, 0, stdout="started")
        if "scripts/check_generation_queue.py" in command:
            if self.redis_down:
                if self.redis_outage_returns_success:
                    return _completed(command, 0, stdout='{"health":{"ok":true}}')
                return _completed(
                    command,
                    2,
                    stdout=(
                        '{"health":{"ok":false,"errors":['
                        '"Redis/RQ inspection failed: ConnectionError: redis down"'
                        "]}}"
                    ),
                )
            if self.mysql_down:
                return _completed(
                    command,
                    2,
                    stdout='{"health":{"ok":false,"errors":["OperationalError mysql down"]}}',
                )
            return _completed(command, 0, stdout='{"health":{"ok":true}}')
        return _completed(command, 0)


def test_outage_smoke_stops_and_recovers_redis_and_mysql() -> None:
    runner = FakeDockerRunner()
    result = run_outage_smoke(_config(), runner=runner)

    assert result["ok"] is True
    assert [step["name"] for step in result["steps"]] == [
        "start-services",
        "baseline",
        "redis-stop",
        "redis-outage",
        "redis-restart",
        "redis-recovered",
        "mysql-stop",
        "mysql-outage",
        "mysql-restart",
        "mysql-recovered",
    ]
    check_commands = [
        command
        for command in runner.commands
        if "scripts/check_generation_queue.py" in command
    ]
    assert check_commands
    assert all("--no-deps" in command for command in check_commands)
    assert all("DATABASE_BACKEND=mysql" in command for command in check_commands)
    assert all("GENERATION_JOB_QUEUE_BACKEND=rq" in command for command in check_commands)
    assert runner.redis_down is False
    assert runner.mysql_down is False


def test_outage_smoke_can_probe_only_redis() -> None:
    runner = FakeDockerRunner()
    result = run_outage_smoke(
        _config(include_mysql=False, start_services=False),
        runner=runner,
    )

    assert result["ok"] is True
    names = [step["name"] for step in result["steps"]]
    assert names == ["baseline", "redis-stop", "redis-outage", "redis-restart", "redis-recovered"]
    assert not any(command[-1] == "mysql" and "stop" in command for command in runner.commands)


def test_outage_smoke_restarts_redis_when_outage_assertion_fails() -> None:
    runner = FakeDockerRunner(redis_outage_returns_success=True)

    with pytest.raises(RuntimeDependencyOutageSmokeError):
        run_outage_smoke(
            _config(include_mysql=False, start_services=False),
            runner=runner,
        )

    assert runner.redis_down is False
    assert any(command[-1] == "redis" and "up" in command for command in runner.commands)


def test_outage_smoke_requires_at_least_one_component() -> None:
    with pytest.raises(RuntimeDependencyOutageSmokeError):
        run_outage_smoke(
            _config(include_redis=False, include_mysql=False),
            runner=FakeDockerRunner(),
        )


def _config(**overrides: object) -> RuntimeDependencyOutageConfig:
    values = {
        "project_root": Path("/tmp/project"),
        "retry_interval_seconds": 0.0,
        "recover_retries": 1,
    }
    values.update(overrides)
    return RuntimeDependencyOutageConfig(**values)


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
