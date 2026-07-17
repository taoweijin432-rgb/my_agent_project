import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings, get_settings
from app.models.test_plan import (
    TestPlan,
    TestPlanExecutionJobDetail,
    TestPlanExecutionRequest,
    TestPlanStep,
    TestReportStatus,
    TestToolType,
)
from app.services.test_plan_execution_jobs import (
    RedisRQTestPlanExecutionJobQueue,
    TestPlanExecutionJobQueue,
)
from scripts.check_queue_alerts import QueueAlertThresholds, build_alert_report


DEFAULT_DATABASE_URL = (
    "mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4"
)
DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_QUEUE_NAME = "generation-compose-smoke"
PYTEST_TARGET = "scripts/pytest_worker_stability_target.py"
TERMINAL_JOB_STATUSES = {"succeeded", "failed"}


Runner = Callable[..., subprocess.CompletedProcess[str]]
QueueFactory = Callable[[Settings], TestPlanExecutionJobQueue]
AlertReportBuilder = Callable[[Settings], dict[str, Any]]


class RQMySQLWorkerStabilitySmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerStabilityConfig:
    project_root: Path = PROJECT_ROOT
    profile: str = "mysql"
    api_service: str = "api"
    worker_service: str = "worker"
    redis_service: str = "redis"
    mysql_service: str = "mysql"
    worker_container_name: str = ""
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = DEFAULT_REDIS_URL
    queue_name: str = DEFAULT_QUEUE_NAME
    app_data_mount: str = "smoke-data"
    model_cache_mount: str = "smoke-model-cache"
    job_count: int = 6
    failure_count: int = 2
    rounds: int = 1
    worker_count: int = 1
    timeout_seconds: float = 180.0
    poll_interval_seconds: float = 1.0
    sleep_seconds: float = 0.5
    command_timeout_seconds: int = 240
    start_services: bool = True
    initialize_mysql: bool = True


@dataclass(frozen=True)
class StepResult:
    name: str
    returncode: int
    ok: bool
    stdout_tail: str
    stderr_tail: str


def run_docker_stability_smoke(
    config: DockerStabilityConfig,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    _validate_stability_parameters(
        config.job_count,
        config.failure_count,
        rounds=config.rounds,
        worker_count=config.worker_count,
    )
    steps: list[StepResult] = []
    worker_names = _worker_names(config)
    started_worker_names: list[str] = []

    try:
        if config.start_services:
            steps.append(
                _run_compose(
                    config,
                    ["up", "-d", config.redis_service, config.mysql_service],
                    "start-services",
                    runner,
                )
            )
        if config.initialize_mysql:
            steps.append(_run_init_mysql(config, runner))

        for index, worker_name in enumerate(worker_names, start=1):
            steps.append(
                _run_worker(
                    config,
                    worker_name,
                    runner,
                    index=index,
                    total=len(worker_names),
                )
            )
            started_worker_names.append(worker_name)
        submit_result = _run_submitter(config, runner)
        steps.append(submit_result["step"])
    finally:
        for index, worker_name in enumerate(started_worker_names, start=1):
            steps.append(
                _remove_worker(
                    config,
                    worker_name,
                    runner,
                    index=index,
                    total=len(started_worker_names),
                )
            )

    submit_payload = submit_result.get("payload") if "submit_result" in locals() else None
    return {
        "ok": all(step.ok for step in steps) and bool(submit_payload),
        "worker_container_names": worker_names,
        "worker_count": len(worker_names),
        "steps": [asdict(step) for step in steps],
        "submit": submit_payload,
    }


def run_submitter_smoke(
    settings: Settings,
    *,
    job_count: int = 6,
    jobs_per_round: int | None = None,
    failure_count: int = 2,
    rounds: int = 1,
    worker_count: int = 1,
    timeout_seconds: float = 180.0,
    poll_interval_seconds: float = 1.0,
    queue_factory: QueueFactory | None = None,
    alert_report_builder: AlertReportBuilder | None = None,
) -> dict[str, object]:
    effective_jobs_per_round = jobs_per_round if jobs_per_round is not None else job_count
    _validate_stability_parameters(
        effective_jobs_per_round,
        failure_count,
        rounds=rounds,
        worker_count=worker_count,
    )
    if timeout_seconds <= 0:
        raise RQMySQLWorkerStabilitySmokeError("timeout_seconds must be greater than zero.")
    if poll_interval_seconds <= 0:
        raise RQMySQLWorkerStabilitySmokeError(
            "poll_interval_seconds must be greater than zero."
        )
    if settings.database_backend != "mysql":
        raise RQMySQLWorkerStabilitySmokeError("DATABASE_BACKEND must be mysql.")
    if settings.generation_job_queue_backend != "rq":
        raise RQMySQLWorkerStabilitySmokeError(
            "GENERATION_JOB_QUEUE_BACKEND must be rq."
        )

    factory = queue_factory or (lambda current_settings: RedisRQTestPlanExecutionJobQueue(current_settings))
    queue = factory(settings)
    queue_alert_builder = alert_report_builder or _build_queue_alert_report
    started_at = time.perf_counter()
    round_results: list[dict[str, object]] = []
    all_job_ids: list[str] = []
    job_status_counts: Counter[str] = Counter()
    report_status_counts: Counter[str] = Counter()
    tool_status_counts: Counter[str] = Counter()
    artifact_count = 0

    for round_index in range(rounds):
        round_started_at = time.perf_counter()
        submitted = [
            queue.submit(
                _request_for_index(
                    round_index * effective_jobs_per_round + index,
                    failure_count=failure_count,
                    local_index=index,
                )
            )
            for index in range(effective_jobs_per_round)
        ]
        job_ids = [job.id for job in submitted]
        all_job_ids.extend(job_ids)
        details = _wait_for_terminal_jobs(
            queue,
            job_ids,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        summary = _summarize_details(
            details,
            expected_failure_reports=failure_count,
        )
        alert_status = _summarize_queue_alert_report(queue_alert_builder(settings))
        if not alert_status["ok"]:
            raise RQMySQLWorkerStabilitySmokeError(
                "Queue alert check failed after round "
                f"{round_index + 1}: {alert_status['alerts']}"
            )

        _merge_counts(job_status_counts, summary["job_status_counts"])
        _merge_counts(report_status_counts, summary["report_status_counts"])
        _merge_counts(tool_status_counts, summary["tool_status_counts"])
        artifact_count += int(summary["artifact_count"])

        round_results.append(
            {
                "round": round_index + 1,
                "duration_seconds": _duration_since(round_started_at),
                "job_count": summary["job_count"],
                "job_ids": summary["job_ids"],
                "job_status_counts": summary["job_status_counts"],
                "report_status_counts": summary["report_status_counts"],
                "tool_status_counts": summary["tool_status_counts"],
                "artifact_count": summary["artifact_count"],
                "queue_alert_status": alert_status,
            }
        )

    result = {
        "ok": True,
        "rounds": rounds,
        "jobs_per_round": effective_jobs_per_round,
        "job_count": len(all_job_ids),
        "total_job_count": len(all_job_ids),
        "worker_count": worker_count,
        "failure_count_per_round": failure_count,
        "expected_failure_report_count": rounds * failure_count,
        "job_ids": all_job_ids,
        "job_status_counts": dict(sorted(job_status_counts.items())),
        "report_status_counts": dict(sorted(report_status_counts.items())),
        "tool_status_counts": dict(sorted(tool_status_counts.items())),
        "artifact_count": artifact_count,
        "per_round_duration_seconds": [
            round_result["duration_seconds"] for round_result in round_results
        ],
        "total_duration_seconds": _duration_since(started_at),
        "round_results": round_results,
        "queue_alert_status": {
            "ok": all(
                bool(round_result["queue_alert_status"]["ok"])
                for round_result in round_results
            ),
            "rounds": [
                round_result["queue_alert_status"] for round_result in round_results
            ],
        },
    }
    result["configured_database_backend"] = settings.database_backend
    result["execution_job_store_backend"] = settings.database_backend
    return result


def _wait_for_terminal_jobs(
    queue: TestPlanExecutionJobQueue,
    job_ids: list[str],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> list[TestPlanExecutionJobDetail]:
    deadline = time.time() + timeout_seconds
    details_by_id: dict[str, TestPlanExecutionJobDetail] = {}
    while time.time() < deadline:
        for job_id in job_ids:
            detail = queue.get_job(job_id)
            if detail is not None:
                details_by_id[job_id] = detail
        if len(details_by_id) == len(job_ids) and all(
            _status_value(detail.status) in TERMINAL_JOB_STATUSES
            for detail in details_by_id.values()
        ):
            return [details_by_id[job_id] for job_id in job_ids]
        time.sleep(poll_interval_seconds)

    states = {
        job_id: _status_value(detail.status)
        for job_id, detail in details_by_id.items()
    }
    missing = [job_id for job_id in job_ids if job_id not in details_by_id]
    raise RQMySQLWorkerStabilitySmokeError(
        f"Timed out waiting for terminal jobs. states={states} missing={missing}"
    )


def _summarize_details(
    details: list[TestPlanExecutionJobDetail],
    *,
    expected_failure_reports: int,
) -> dict[str, object]:
    job_status_counts = Counter(_status_value(detail.status) for detail in details)
    failed_jobs = [
        detail.id
        for detail in details
        if _status_value(detail.status) != "succeeded"
    ]
    if failed_jobs:
        raise RQMySQLWorkerStabilitySmokeError(
            f"Execution job(s) failed unexpectedly: {failed_jobs}"
        )

    reports = [detail.report for detail in details]
    if any(report is None for report in reports):
        missing = [detail.id for detail in details if detail.report is None]
        raise RQMySQLWorkerStabilitySmokeError(f"Job(s) missing reports: {missing}")

    concrete_reports = [report for report in reports if report is not None]
    report_status_counts = Counter(
        _status_value(report.status) for report in concrete_reports
    )
    tool_status_counts: Counter[str] = Counter()
    artifact_count = 0
    for report in concrete_reports:
        for tool_run in report.tool_runs:
            tool_status_counts[_status_value(tool_run.status)] += 1
            artifact_count += len(tool_run.artifact_paths)

    if report_status_counts.get("failed", 0) != expected_failure_reports:
        raise RQMySQLWorkerStabilitySmokeError(
            "Unexpected failed report count: "
            f"{report_status_counts.get('failed', 0)} != {expected_failure_reports}"
        )
    if report_status_counts.get("passed", 0) == 0:
        raise RQMySQLWorkerStabilitySmokeError("No passed reports were produced.")
    if artifact_count < len(details):
        raise RQMySQLWorkerStabilitySmokeError(
            f"Expected at least one artifact per job, got {artifact_count}."
        )

    return {
        "ok": True,
        "job_count": len(details),
        "job_ids": [detail.id for detail in details],
        "job_status_counts": dict(sorted(job_status_counts.items())),
        "report_status_counts": dict(sorted(report_status_counts.items())),
        "tool_status_counts": dict(sorted(tool_status_counts.items())),
        "artifact_count": artifact_count,
    }


def _request_for_index(
    index: int,
    *,
    failure_count: int,
    local_index: int | None = None,
) -> TestPlanExecutionRequest:
    failure_index = index if local_index is None else local_index
    if failure_index < failure_count:
        keyword = "worker_stability_fail_expected"
        expected_status = TestReportStatus.failed
    elif index % 2 == 0:
        keyword = "worker_stability_pass_slow"
        expected_status = TestReportStatus.passed
    else:
        keyword = "worker_stability_pass_fast"
        expected_status = TestReportStatus.passed

    step_id = f"WS-{index + 1:03d}"
    step = TestPlanStep(
        id=step_id,
        title=f"Worker stability {keyword}",
        objective=f"Produce a {expected_status.value} pytest tool run.",
        requirement_ids=[f"REQ-WORKER-STABILITY-{index + 1:03d}"],
        tool=TestToolType.pytest,
        tool_args={
            "test_path": PYTEST_TARGET,
            "keyword": keyword,
            "maxfail": 1,
        },
        success_criteria=[f"Report status should be {expected_status.value}."],
    )
    plan = TestPlan(
        id=f"worker-stability-plan-{index + 1:03d}",
        title=f"Worker stability plan {index + 1:03d}",
        steps=[step],
    )
    return TestPlanExecutionRequest(plan=plan, http_base_url="http://testserver")


def _run_init_mysql(config: DockerStabilityConfig, runner: Runner) -> StepResult:
    return _run_compose(
        config,
        [
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "-e",
            "DATABASE_BACKEND=mysql",
            "-e",
            f"DATABASE_URL={config.database_url}",
            config.api_service,
            "python",
            "scripts/init_mysql.py",
        ],
        "init-mysql",
        runner,
    )


def _run_worker(
    config: DockerStabilityConfig,
    worker_name: str,
    runner: Runner,
    *,
    index: int,
    total: int,
) -> StepResult:
    return _run_compose(
        config,
        [
            "run",
            "-d",
            "--name",
            worker_name,
            "--no-deps",
            *_container_env_args(config),
            config.worker_service,
        ],
        _worker_step_name("start-worker", index=index, total=total),
        runner,
    )


def _run_submitter(config: DockerStabilityConfig, runner: Runner) -> dict[str, object]:
    step = _run_compose(
        config,
        [
            "run",
            "--rm",
            "-T",
            "--no-deps",
            *_container_env_args(config),
            config.api_service,
            "python",
            "scripts/smoke_rq_mysql_worker_stability.py",
            "--submit-only",
            "--json",
            "--job-count",
            str(config.job_count),
            "--jobs-per-round",
            str(config.job_count),
            "--failure-count",
            str(config.failure_count),
            "--rounds",
            str(config.rounds),
            "--worker-count",
            str(config.worker_count),
            "--timeout-seconds",
            str(config.timeout_seconds),
            "--poll-interval-seconds",
            str(config.poll_interval_seconds),
        ],
        "submit-and-poll",
        runner,
    )
    try:
        payload = json.loads(step.stdout_tail)
    except json.JSONDecodeError as exc:
        raise RQMySQLWorkerStabilitySmokeError(
            f"submit-and-poll did not return JSON: {step.stdout_tail}"
        ) from exc
    if not payload.get("ok"):
        raise RQMySQLWorkerStabilitySmokeError(
            f"submit-and-poll failed: {payload}"
        )
    return {"step": step, "payload": payload}


def _remove_worker(
    config: DockerStabilityConfig,
    worker_name: str,
    runner: Runner,
    *,
    index: int,
    total: int,
) -> StepResult:
    result = runner(
        ["docker", "rm", "-f", worker_name],
        cwd=config.project_root,
        env=_compose_environment(config),
        check=False,
        capture_output=True,
        text=True,
        timeout=config.command_timeout_seconds,
    )
    return StepResult(
        name=_worker_step_name("cleanup-worker", index=index, total=total),
        returncode=result.returncode,
        ok=result.returncode == 0,
        stdout_tail=_tail(result.stdout),
        stderr_tail=_tail(result.stderr),
    )


def _run_compose(
    config: DockerStabilityConfig,
    args: list[str],
    name: str,
    runner: Runner,
) -> StepResult:
    result = runner(
        _compose_command(config, args),
        cwd=config.project_root,
        env=_compose_environment(config),
        check=False,
        capture_output=True,
        text=True,
        timeout=config.command_timeout_seconds,
    )
    step = StepResult(
        name=name,
        returncode=result.returncode,
        ok=result.returncode == 0,
        stdout_tail=_tail(result.stdout, limit=4000),
        stderr_tail=_tail(result.stderr),
    )
    if not step.ok:
        raise RQMySQLWorkerStabilitySmokeError(
            f"{name} failed with exit={step.returncode}: "
            f"{step.stdout_tail}\n{step.stderr_tail}"
        )
    return step


def _compose_command(config: DockerStabilityConfig, args: list[str]) -> list[str]:
    command = ["docker", "compose"]
    if config.profile:
        command.extend(["--profile", config.profile])
    command.extend(args)
    return command


def _container_env_args(config: DockerStabilityConfig) -> list[str]:
    values = {
        "DATABASE_BACKEND": "mysql",
        "DATABASE_URL": config.database_url,
        "GENERATION_JOB_QUEUE_BACKEND": "rq",
        "REDIS_URL": config.redis_url,
        "RQ_QUEUE_NAME": config.queue_name,
        "GENERATION_JOB_MAX_QUEUE_SIZE": str(
            max(config.job_count + config.worker_count + 4, 10)
        ),
        "RQ_JOB_TIMEOUT_SECONDS": str(max(int(config.timeout_seconds), 60)),
        "TEST_TOOL_PYTEST_ENABLED": "true",
        "TEST_TOOL_PYTEST_ALLOWED_PATHS": "scripts",
        "TEST_TOOL_PYTEST_TIMEOUT_SECONDS": str(max(int(config.timeout_seconds), 30)),
        "TEST_TOOL_PYTEST_ENV_ALLOWLIST": (
            "PATH,PYTHONPATH,WORKER_STABILITY_SLEEP_SECONDS"
        ),
        "TEST_TOOL_ARTIFACT_DIR": "data/test-artifacts/worker-stability",
        "WORKER_STABILITY_SLEEP_SECONDS": str(config.sleep_seconds),
    }
    args: list[str] = []
    for key, value in values.items():
        args.extend(["-e", f"{key}={value}"])
    return args


def _compose_environment(config: DockerStabilityConfig) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_DATA_MOUNT": config.app_data_mount,
            "MODEL_CACHE_MOUNT": config.model_cache_mount,
        }
    )
    return env


def _validate_stability_parameters(
    job_count: int,
    failure_count: int,
    *,
    rounds: int,
    worker_count: int,
) -> None:
    _validate_counts(job_count, failure_count)
    if rounds <= 0:
        raise RQMySQLWorkerStabilitySmokeError("rounds must be greater than zero.")
    if worker_count <= 0:
        raise RQMySQLWorkerStabilitySmokeError("worker_count must be greater than zero.")


def _validate_counts(job_count: int, failure_count: int) -> None:
    if job_count <= 0:
        raise RQMySQLWorkerStabilitySmokeError("job_count must be greater than zero.")
    if failure_count < 0:
        raise RQMySQLWorkerStabilitySmokeError("failure_count must be >= 0.")
    if failure_count >= job_count:
        raise RQMySQLWorkerStabilitySmokeError("failure_count must be less than job_count.")


def _default_worker_name() -> str:
    return f"my_agent_project-test-plan-stability-{uuid4().hex[:8]}"


def _worker_names(config: DockerStabilityConfig) -> list[str]:
    base_name = config.worker_container_name or _default_worker_name()
    if config.worker_count == 1:
        return [base_name]
    return [f"{base_name}-{index}" for index in range(1, config.worker_count + 1)]


def _worker_step_name(prefix: str, *, index: int, total: int) -> str:
    if total == 1:
        return prefix
    return f"{prefix}-{index}"


def _build_queue_alert_report(settings: Settings) -> dict[str, Any]:
    return build_alert_report(
        settings,
        thresholds=QueueAlertThresholds(
            max_active_jobs=0,
            max_rq_queued=0,
            max_rq_started=0,
            max_rq_failed=0,
            max_worker_heartbeat_age_seconds=3600,
            require_worker=True,
        ),
        queue_names=["test_plan_execution"],
    )


def _summarize_queue_alert_report(report: dict[str, Any]) -> dict[str, object]:
    alerts = list(report.get("alerts") or [])
    return {
        "ok": bool(report.get("ok")),
        "alert_count": len(alerts),
        "alerts": alerts,
        "metrics": report.get("metrics") or {},
    }


def _merge_counts(counter: Counter[str], values: object) -> None:
    if not isinstance(values, dict):
        raise RQMySQLWorkerStabilitySmokeError(f"Expected count dict, got {values!r}")
    for key, value in values.items():
        counter[str(key)] += int(value)


def _duration_since(started_at: float) -> float:
    elapsed = time.perf_counter() - started_at
    return round(max(elapsed, 0.001), 3)


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value))


def _tail(value: str, *, limit: int = 800) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[-limit:]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    jobs_per_round = _resolve_jobs_per_round(args)
    try:
        if args.submit_only:
            result = run_submitter_smoke(
                get_settings(),
                jobs_per_round=jobs_per_round,
                failure_count=args.failure_count,
                rounds=args.rounds,
                worker_count=args.worker_count,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        else:
            config = DockerStabilityConfig(
                project_root=Path(args.project_root).resolve(),
                profile=args.profile,
                worker_container_name=args.worker_container_name,
                database_url=args.database_url,
                redis_url=args.redis_url,
                queue_name=args.queue_name,
                app_data_mount=args.app_data_mount,
                model_cache_mount=args.model_cache_mount,
                job_count=jobs_per_round,
                failure_count=args.failure_count,
                rounds=args.rounds,
                worker_count=args.worker_count,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                sleep_seconds=args.sleep_seconds,
                command_timeout_seconds=args.command_timeout_seconds,
                start_services=not args.no_start_services,
                initialize_mysql=not args.no_init_mysql,
            )
            result = run_docker_stability_smoke(config)
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL rq-mysql-worker-stability-smoke: {payload['error']}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.submit_only:
            print(
                "PASS rq-mysql-worker-stability-submit: "
                f"jobs={result['job_count']} rounds={result['rounds']} "
                f"reports={result['report_status_counts']}"
            )
        else:
            submit = result.get("submit") if isinstance(result, dict) else None
            print(
                "PASS rq-mysql-worker-stability-smoke: "
                f"workers={result.get('worker_count')} submit={submit}"
            )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a Docker Redis/RQ + MySQL worker stability smoke for test plan "
            "execution jobs."
        ),
    )
    parser.add_argument(
        "--submit-only",
        action="store_true",
        help="Submit and poll jobs in the current process; used inside the API container.",
    )
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--profile", default="mysql")
    parser.add_argument("--worker-container-name", default="")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--redis-url", default=DEFAULT_REDIS_URL)
    parser.add_argument("--queue-name", default=DEFAULT_QUEUE_NAME)
    parser.add_argument("--app-data-mount", default="smoke-data")
    parser.add_argument("--model-cache-mount", default="smoke-model-cache")
    parser.add_argument(
        "--job-count",
        type=int,
        default=None,
        help="Backward-compatible alias for --jobs-per-round.",
    )
    parser.add_argument("--jobs-per-round", type=int)
    parser.add_argument("--failure-count", type=int, default=2)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--command-timeout-seconds", type=int, default=240)
    parser.add_argument("--no-start-services", action="store_true")
    parser.add_argument("--no-init-mysql", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def _resolve_jobs_per_round(args: argparse.Namespace) -> int:
    if args.jobs_per_round is not None:
        return int(args.jobs_per_round)
    if args.job_count is not None:
        return int(args.job_count)
    return 6


if __name__ == "__main__":
    raise SystemExit(main())
