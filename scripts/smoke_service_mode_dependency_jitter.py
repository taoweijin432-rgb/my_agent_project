import argparse
import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.mysql-rq.yml")
DEFAULT_DESCRIPTION = "高风险上线需要人工确认审批记录。"

Runner = Callable[..., subprocess.CompletedProcess[str]]


class ServiceModeDependencyJitterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceModeDependencyJitterConfig:
    project_root: Path = PROJECT_ROOT
    compose_files: tuple[str, ...] = DEFAULT_COMPOSE_FILES
    profile: str = "mysql"
    api_service: str = "api"
    worker_service: str = "worker"
    redis_service: str = "redis"
    mysql_service: str = "mysql"
    worker_count: int = 2
    include_redis: bool = True
    include_mysql: bool = True
    start_services: bool = True
    baseline_rounds: int = 1
    baseline_jobs_per_round: int = 2
    recovery_rounds: int = 1
    recovery_jobs_per_round: int = 2
    description: str = DEFAULT_DESCRIPTION
    max_rq_failed: int = 0
    max_worker_heartbeat_age_seconds: int = 900
    fail_over_max_queue_wait_ms: float | None = 60000.0
    fail_over_max_job_total_ms: float | None = 120000.0
    fail_under_throughput_jobs_per_second: float | None = 0.01
    recover_retries: int = 12
    retry_interval_seconds: float = 2.0
    command_timeout_seconds: int = 180


@dataclass(frozen=True)
class StepResult:
    name: str
    expected: str
    returncode: int
    ok: bool
    stdout_tail: str
    stderr_tail: str


@dataclass(frozen=True)
class LoadResult:
    name: str
    ok: bool
    job_count: int
    jobs_by_status: dict[str, int]
    report_status_counts: dict[str, int]
    throughput: dict[str, Any]
    timing_summary_ms: dict[str, Any]
    worker_counts: list[int]
    alert_counts: list[int]
    summary: dict[str, Any]


def run_dependency_jitter_smoke(
    config: ServiceModeDependencyJitterConfig,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    _validate_config(config)
    steps: list[StepResult] = []
    loads: list[LoadResult] = []

    if config.start_services:
        steps.append(_start_service_mode(config, runner=runner))

    steps.append(
        _run_with_retries(
            config,
            lambda: _run_readiness_check(
                config,
                name="baseline-readiness",
                expected_success=True,
                runner=runner,
            ),
        )
    )
    steps.append(
        _run_with_retries(
            config,
            lambda: _run_queue_alert_check(
                config,
                name="baseline-queue-alerts",
                expected_success=True,
                runner=runner,
            ),
        )
    )
    baseline_load, baseline_step = _run_load_smoke(
        config,
        name="baseline-load",
        rounds=config.baseline_rounds,
        jobs_per_round=config.baseline_jobs_per_round,
        runner=runner,
    )
    loads.append(baseline_load)
    steps.append(baseline_step)

    if config.include_redis:
        steps.extend(
            _run_single_dependency_probe(
                config,
                "redis",
                loads=loads,
                runner=runner,
            )
        )
    if config.include_mysql:
        steps.extend(
            _run_single_dependency_probe(
                config,
                "mysql",
                loads=loads,
                runner=runner,
            )
        )

    steps.append(
        _run_with_retries(
            config,
            lambda: _run_queue_alert_check(
                config,
                name="final-queue-alerts",
                expected_success=True,
                runner=runner,
            ),
        )
    )

    return {
        "ok": all(step.ok for step in steps) and all(load.ok for load in loads),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compose_files": list(config.compose_files),
        "profile": config.profile,
        "worker_count": config.worker_count,
        "probed": {
            "redis": config.include_redis,
            "mysql": config.include_mysql,
        },
        "steps": [asdict(step) for step in steps],
        "loads": [asdict(load) for load in loads],
    }


def _run_single_dependency_probe(
    config: ServiceModeDependencyJitterConfig,
    component: str,
    *,
    loads: list[LoadResult],
    runner: Runner,
) -> list[StepResult]:
    service = _service_for_component(config, component)
    steps: list[StepResult] = []
    steps.append(
        _run_compose_step(
            config,
            ["stop", service],
            name=f"{component}-stop",
            expected="success",
            runner=runner,
        )
    )
    try:
        steps.append(
            _run_queue_alert_check(
                config,
                name=f"{component}-outage-queue-alerts",
                expected_success=False,
                expected_fragments=_expected_error_fragments(component),
                runner=runner,
            )
        )
    finally:
        steps.append(
            _run_compose_step(
                config,
                ["up", "-d", service],
                name=f"{component}-restart",
                expected="success",
                runner=runner,
            )
        )

    steps.append(
        _run_with_retries(
            config,
            lambda: _run_readiness_check(
                config,
                name=f"{component}-recovered-readiness",
                expected_success=True,
                runner=runner,
            ),
        )
    )
    steps.append(
        _run_with_retries(
            config,
            lambda: _run_queue_alert_check(
                config,
                name=f"{component}-recovered-queue-alerts",
                expected_success=True,
                runner=runner,
            ),
        )
    )
    recovery_load, recovery_step = _run_load_smoke(
        config,
        name=f"{component}-recovery-load",
        rounds=config.recovery_rounds,
        jobs_per_round=config.recovery_jobs_per_round,
        runner=runner,
    )
    loads.append(recovery_load)
    steps.append(recovery_step)
    return steps


def _start_service_mode(
    config: ServiceModeDependencyJitterConfig,
    *,
    runner: Runner,
) -> StepResult:
    return _run_compose_step(
        config,
        [
            "up",
            "-d",
            "--scale",
            f"{config.worker_service}={config.worker_count}",
            config.mysql_service,
            config.redis_service,
            config.api_service,
            config.worker_service,
        ],
        name="start-service-mode",
        expected="success",
        runner=runner,
    )


def _run_readiness_check(
    config: ServiceModeDependencyJitterConfig,
    *,
    name: str,
    expected_success: bool,
    runner: Runner,
) -> StepResult:
    return _run_api_step(
        config,
        ["python", "scripts/check_readiness.py", "--json"],
        name=name,
        expected_success=expected_success,
        expected_fragments=(),
        runner=runner,
    )


def _run_queue_alert_check(
    config: ServiceModeDependencyJitterConfig,
    *,
    name: str,
    expected_success: bool,
    runner: Runner,
    expected_fragments: Sequence[str] = (),
) -> StepResult:
    return _run_api_step(
        config,
        [
            "python",
            "scripts/check_queue_alerts.py",
            "--json",
            "--require-worker",
            "--max-rq-failed",
            str(config.max_rq_failed),
            "--max-worker-heartbeat-age-seconds",
            str(config.max_worker_heartbeat_age_seconds),
        ],
        name=name,
        expected_success=expected_success,
        expected_fragments=expected_fragments,
        runner=runner,
    )


def _run_load_smoke(
    config: ServiceModeDependencyJitterConfig,
    *,
    name: str,
    rounds: int,
    jobs_per_round: int,
    runner: Runner,
) -> tuple[LoadResult, StepResult]:
    command = [
        "python",
        "scripts/smoke_service_mode_workflow_load.py",
        "--rounds",
        str(rounds),
        "--jobs-per-round",
        str(jobs_per_round),
        "--description",
        config.description,
        "--require-worker",
        "--max-rq-failed",
        str(config.max_rq_failed),
        "--max-worker-heartbeat-age-seconds",
        str(config.max_worker_heartbeat_age_seconds),
        "--json",
    ]
    _append_optional_threshold(command, "--fail-over-max-queue-wait-ms", config.fail_over_max_queue_wait_ms)
    _append_optional_threshold(command, "--fail-over-max-job-total-ms", config.fail_over_max_job_total_ms)
    _append_optional_threshold(
        command,
        "--fail-under-throughput-jobs-per-second",
        config.fail_under_throughput_jobs_per_second,
    )
    result = _run_command(_api_exec_command(config, command), config, runner=runner)
    step = _step_from_result(name, "success", result)
    if not step.ok:
        raise ServiceModeDependencyJitterError(
            f"{name} expected success, got exit={result.returncode}: "
            f"{_tail(result.stdout + result.stderr)}"
        )
    summary = _parse_json_output(name, result.stdout)
    load = _load_result_from_summary(name, summary)
    if not load.ok:
        raise ServiceModeDependencyJitterError(
            f"{name} returned ok=false: {summary.get('failures')}"
        )
    return load, step


def _run_api_step(
    config: ServiceModeDependencyJitterConfig,
    command: list[str],
    *,
    name: str,
    expected_success: bool,
    expected_fragments: Sequence[str],
    runner: Runner,
) -> StepResult:
    result = _run_command(_api_exec_command(config, command), config, runner=runner)
    output = f"{result.stdout}\n{result.stderr}"
    if expected_success:
        step = _step_from_result(name, "success", result)
    else:
        step = StepResult(
            name=name,
            expected="failure",
            returncode=result.returncode,
            ok=result.returncode != 0 and _contains_any(output, expected_fragments),
            stdout_tail=_tail(result.stdout),
            stderr_tail=_tail(result.stderr),
        )
    if not step.ok:
        raise ServiceModeDependencyJitterError(
            f"{name} expected {step.expected}, got exit={result.returncode}: "
            f"{_tail(output)}"
        )
    return step


def _run_compose_step(
    config: ServiceModeDependencyJitterConfig,
    args: list[str],
    *,
    name: str,
    expected: str,
    runner: Runner,
) -> StepResult:
    result = _run_command(_compose_command(config, args), config, runner=runner)
    step = _step_from_result(name, expected, result)
    if not step.ok:
        raise ServiceModeDependencyJitterError(
            f"{name} expected {expected}, got exit={result.returncode}: "
            f"{_tail(result.stdout + result.stderr)}"
        )
    return step


def _run_with_retries(
    config: ServiceModeDependencyJitterConfig,
    action: Callable[[], StepResult],
) -> StepResult:
    last_error: ServiceModeDependencyJitterError | None = None
    for attempt in range(config.recover_retries):
        try:
            return action()
        except ServiceModeDependencyJitterError as exc:
            last_error = exc
            if attempt + 1 == config.recover_retries:
                break
            time.sleep(config.retry_interval_seconds)
    raise last_error or ServiceModeDependencyJitterError("retry action failed")


def _run_command(
    command: list[str],
    config: ServiceModeDependencyJitterConfig,
    *,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        cwd=config.project_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=config.command_timeout_seconds,
    )


def _compose_command(
    config: ServiceModeDependencyJitterConfig,
    args: list[str],
) -> list[str]:
    command = ["docker", "compose"]
    for compose_file in config.compose_files:
        command.extend(["-f", compose_file])
    if config.profile:
        command.extend(["--profile", config.profile])
    command.extend(args)
    return command


def _api_exec_command(
    config: ServiceModeDependencyJitterConfig,
    command: list[str],
) -> list[str]:
    return _compose_command(config, ["exec", "-T", config.api_service, *command])


def _step_from_result(
    name: str,
    expected: str,
    result: subprocess.CompletedProcess[str],
) -> StepResult:
    return StepResult(
        name=name,
        expected=expected,
        returncode=result.returncode,
        ok=result.returncode == 0,
        stdout_tail=_tail(result.stdout),
        stderr_tail=_tail(result.stderr),
    )


def _load_result_from_summary(name: str, summary: dict[str, Any]) -> LoadResult:
    return LoadResult(
        name=name,
        ok=bool(summary.get("ok")),
        job_count=int(summary.get("job_count") or 0),
        jobs_by_status=dict(summary.get("jobs_by_status") or {}),
        report_status_counts=dict(summary.get("report_status_counts") or {}),
        throughput=dict(summary.get("throughput") or {}),
        timing_summary_ms=dict(summary.get("timing_summary_ms") or {}),
        worker_counts=[
            int((report.get("metrics") or {}).get("test_agent_workflow", {}).get("worker_count") or 0)
            for report in summary.get("queue_alert_reports") or []
        ],
        alert_counts=[
            len(report.get("alerts") or [])
            for report in summary.get("queue_alert_reports") or []
        ],
        summary=summary,
    )


def _parse_json_output(name: str, output: str) -> dict[str, Any]:
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ServiceModeDependencyJitterError(
            f"{name} did not return valid JSON: {_tail(output)}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ServiceModeDependencyJitterError(f"{name} returned non-object JSON.")
    return parsed


def _append_optional_threshold(
    command: list[str],
    option: str,
    value: float | None,
) -> None:
    if value is not None:
        command.extend([option, str(value)])


def _service_for_component(
    config: ServiceModeDependencyJitterConfig,
    component: str,
) -> str:
    if component == "redis":
        return config.redis_service
    if component == "mysql":
        return config.mysql_service
    raise ServiceModeDependencyJitterError(f"Unsupported component: {component}")


def _expected_error_fragments(component: str) -> tuple[str, ...]:
    if component == "redis":
        return ("snapshot_failed", "redis", "ConnectionError")
    if component == "mysql":
        return ("snapshot_failed", "mysql", "OperationalError", "Can't connect")
    return ()


def _contains_any(output: str, fragments: Sequence[str]) -> bool:
    lowered = output.lower()
    return any(fragment.lower() in lowered for fragment in fragments)


def _tail(value: str, *, limit: int = 800) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[-limit:]


def _validate_config(config: ServiceModeDependencyJitterConfig) -> None:
    if not config.include_redis and not config.include_mysql:
        raise ServiceModeDependencyJitterError(
            "At least one dependency jitter probe must be enabled."
        )
    if not config.compose_files:
        raise ServiceModeDependencyJitterError("At least one compose file is required.")
    if config.worker_count < 1:
        raise ServiceModeDependencyJitterError("worker_count must be >= 1.")
    for field_name, value in (
        ("baseline_rounds", config.baseline_rounds),
        ("baseline_jobs_per_round", config.baseline_jobs_per_round),
        ("recovery_rounds", config.recovery_rounds),
        ("recovery_jobs_per_round", config.recovery_jobs_per_round),
        ("recover_retries", config.recover_retries),
    ):
        if value < 1:
            raise ServiceModeDependencyJitterError(f"{field_name} must be >= 1.")
    if config.retry_interval_seconds < 0:
        raise ServiceModeDependencyJitterError("retry_interval_seconds must be >= 0.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = ServiceModeDependencyJitterConfig(
        project_root=Path(args.project_root).resolve(),
        compose_files=tuple(args.compose_file or DEFAULT_COMPOSE_FILES),
        profile=args.profile,
        api_service=args.api_service,
        worker_service=args.worker_service,
        redis_service=args.redis_service,
        mysql_service=args.mysql_service,
        worker_count=args.worker_count,
        include_redis=args.component in {"all", "redis"},
        include_mysql=args.component in {"all", "mysql"},
        start_services=not args.no_start_services,
        baseline_rounds=args.baseline_rounds,
        baseline_jobs_per_round=args.baseline_jobs_per_round,
        recovery_rounds=args.recovery_rounds,
        recovery_jobs_per_round=args.recovery_jobs_per_round,
        description=args.description,
        max_rq_failed=args.max_rq_failed,
        max_worker_heartbeat_age_seconds=args.max_worker_heartbeat_age_seconds,
        fail_over_max_queue_wait_ms=args.fail_over_max_queue_wait_ms,
        fail_over_max_job_total_ms=args.fail_over_max_job_total_ms,
        fail_under_throughput_jobs_per_second=(
            args.fail_under_throughput_jobs_per_second
        ),
        recover_retries=args.recover_retries,
        retry_interval_seconds=args.retry_interval_seconds,
        command_timeout_seconds=args.command_timeout_seconds,
    )
    try:
        result = run_dependency_jitter_smoke(config)
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.output_json:
            args.output_json.parent.mkdir(parents=True, exist_ok=True)
            args.output_json.write_text(
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n",
                encoding="utf-8",
            )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL service-mode-dependency-jitter-smoke: {payload['error']}")
        return 1

    result_json = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(f"{result_json}\n", encoding="utf-8")
    if args.json:
        print(result_json)
    else:
        print(
            "PASS service-mode-dependency-jitter-smoke: "
            f"worker_count={config.worker_count} loads={len(result['loads'])}"
        )
    return 0 if result["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Exercise service-mode API/worker MySQL/RQ dependency jitter by "
            "stopping Redis/MySQL, verifying queue checks fail clearly, then "
            "recovering and running workflow load."
        ),
    )
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument(
        "--compose-file",
        action="append",
        default=None,
        help="Compose file. Repeat to pass multiple files.",
    )
    parser.add_argument("--profile", default="mysql")
    parser.add_argument("--api-service", default="api")
    parser.add_argument("--worker-service", default="worker")
    parser.add_argument("--redis-service", default="redis")
    parser.add_argument("--mysql-service", default="mysql")
    parser.add_argument("--worker-count", type=int, default=2)
    parser.add_argument(
        "--component",
        choices=("all", "redis", "mysql"),
        default="all",
        help="Dependency jitter probe to run.",
    )
    parser.add_argument("--no-start-services", action="store_true")
    parser.add_argument("--baseline-rounds", type=int, default=1)
    parser.add_argument("--baseline-jobs-per-round", type=int, default=2)
    parser.add_argument("--recovery-rounds", type=int, default=1)
    parser.add_argument("--recovery-jobs-per-round", type=int, default=2)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--max-rq-failed", type=int, default=0)
    parser.add_argument("--max-worker-heartbeat-age-seconds", type=int, default=900)
    parser.add_argument("--fail-over-max-queue-wait-ms", type=float, default=60000.0)
    parser.add_argument("--fail-over-max-job-total-ms", type=float, default=120000.0)
    parser.add_argument(
        "--fail-under-throughput-jobs-per-second",
        type=float,
        default=0.01,
    )
    parser.add_argument("--recover-retries", type=int, default=12)
    parser.add_argument("--retry-interval-seconds", type=float, default=2.0)
    parser.add_argument("--command-timeout-seconds", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
