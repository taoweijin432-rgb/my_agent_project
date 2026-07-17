import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings, get_settings
from app.models.test_case import RequirementPoint
from app.models.test_plan import (
    TestAgentWorkflowJobDetail,
    TestAgentWorkflowRequest,
    TestPlanGenerationRequest,
    ToolRunStatus,
)
from app.services.test_agent_workflow_jobs import (
    RedisRQTestAgentWorkflowJobQueue,
    TestAgentWorkflowJobQueue,
)
from scripts.check_queue_alerts import QueueAlertThresholds, build_alert_report


DEFAULT_DATABASE_URL = (
    "mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4"
)
DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_QUEUE_NAME = "test-agent-workflow-compose-smoke"
DEFAULT_HTTP_BASE_URL = "http://api:8000"
TERMINAL_JOB_STATUSES = {"succeeded", "failed"}


Runner = Callable[..., subprocess.CompletedProcess[str]]
QueueFactory = Callable[[Settings], TestAgentWorkflowJobQueue]
AlertReportBuilder = Callable[[Settings], dict[str, Any]]


class WorkflowRQMySQLSmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class DockerWorkflowSmokeConfig:
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
    http_base_url: str = DEFAULT_HTTP_BASE_URL
    app_data_mount: str = "smoke-data"
    model_cache_mount: str = "smoke-model-cache"
    job_count: int = 3
    rounds: int = 1
    worker_count: int = 1
    timeout_seconds: float = 180.0
    poll_interval_seconds: float = 1.0
    max_queue_wait_ms: float | None = None
    min_throughput_jobs_per_second: float | None = None
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


def run_docker_workflow_smoke(
    config: DockerWorkflowSmokeConfig,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    _validate_parameters(
        config.job_count,
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
                    [
                        "up",
                        "-d",
                        config.redis_service,
                        config.mysql_service,
                        config.api_service,
                    ],
                    "start-services",
                    runner,
                )
            )
            steps.append(_wait_for_api(config, runner))
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
    job_count: int = 3,
    jobs_per_round: int | None = None,
    rounds: int = 1,
    worker_count: int = 1,
    http_base_url: str = DEFAULT_HTTP_BASE_URL,
    timeout_seconds: float = 180.0,
    poll_interval_seconds: float = 1.0,
    max_queue_wait_ms: float | None = None,
    min_throughput_jobs_per_second: float | None = None,
    queue_factory: QueueFactory | None = None,
    alert_report_builder: AlertReportBuilder | None = None,
) -> dict[str, object]:
    effective_jobs_per_round = jobs_per_round if jobs_per_round is not None else job_count
    _validate_parameters(
        effective_jobs_per_round,
        rounds=rounds,
        worker_count=worker_count,
    )
    if timeout_seconds <= 0:
        raise WorkflowRQMySQLSmokeError("timeout_seconds must be greater than zero.")
    if poll_interval_seconds <= 0:
        raise WorkflowRQMySQLSmokeError(
            "poll_interval_seconds must be greater than zero."
        )
    _validate_throughput_thresholds(
        max_queue_wait_ms=max_queue_wait_ms,
        min_throughput_jobs_per_second=min_throughput_jobs_per_second,
    )
    if settings.database_backend != "mysql":
        raise WorkflowRQMySQLSmokeError("DATABASE_BACKEND must be mysql.")
    if settings.generation_job_queue_backend != "rq":
        raise WorkflowRQMySQLSmokeError("GENERATION_JOB_QUEUE_BACKEND must be rq.")

    factory = queue_factory or (
        lambda current_settings: RedisRQTestAgentWorkflowJobQueue(current_settings)
    )
    queue = factory(settings)
    queue_alert_builder = alert_report_builder or _build_queue_alert_report
    started_at = time.perf_counter()
    round_results: list[dict[str, Any]] = []
    all_job_ids: list[str] = []
    job_status_counts: Counter[str] = Counter()
    report_status_counts: Counter[str] = Counter()
    tool_status_counts: Counter[str] = Counter()
    artifact_count = 0
    covered_requirement_count = 0
    timing_samples: dict[str, list[float]] = _empty_timing_samples()

    for round_index in range(rounds):
        round_started_at = time.perf_counter()
        submitted = [
            queue.submit(
                _request_for_index(
                    round_index * effective_jobs_per_round + index,
                    http_base_url=http_base_url,
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
        summary = _summarize_details(details)
        alert_status = _summarize_queue_alert_report(queue_alert_builder(settings))
        if not alert_status["ok"]:
            raise WorkflowRQMySQLSmokeError(
                "Queue alert check failed after round "
                f"{round_index + 1}: {alert_status['alerts']}"
            )

        _merge_counts(job_status_counts, summary["job_status_counts"])
        _merge_counts(report_status_counts, summary["report_status_counts"])
        _merge_counts(tool_status_counts, summary["tool_status_counts"])
        artifact_count += int(summary["artifact_count"])
        covered_requirement_count += int(summary["covered_requirement_count"])
        _extend_timing_samples(timing_samples, summary["timing_samples"])

        round_duration_seconds = _duration_since(round_started_at)
        round_results.append(
            {
                "round": round_index + 1,
                "duration_seconds": round_duration_seconds,
                "job_count": summary["job_count"],
                "job_ids": summary["job_ids"],
                "job_status_counts": summary["job_status_counts"],
                "report_status_counts": summary["report_status_counts"],
                "tool_status_counts": summary["tool_status_counts"],
                "artifact_count": summary["artifact_count"],
                "covered_requirement_count": summary["covered_requirement_count"],
                "timing_summary_ms": summary["timing_summary_ms"],
                "throughput": _throughput_summary(
                    job_count=summary["job_count"],
                    worker_count=worker_count,
                    total_duration_seconds=round_duration_seconds,
                    timing_summary_ms=summary["timing_summary_ms"],
                    round_durations_seconds=[round_duration_seconds],
                ),
                "queue_alert_status": alert_status,
            }
        )

    total_duration_seconds = _duration_since(started_at)
    timing_summary_ms = _summarize_timing_samples(timing_samples)
    result = {
        "ok": True,
        "rounds": rounds,
        "jobs_per_round": effective_jobs_per_round,
        "job_count": len(all_job_ids),
        "total_job_count": len(all_job_ids),
        "worker_count": worker_count,
        "http_base_url": http_base_url,
        "job_ids": all_job_ids,
        "job_status_counts": dict(sorted(job_status_counts.items())),
        "report_status_counts": dict(sorted(report_status_counts.items())),
        "tool_status_counts": dict(sorted(tool_status_counts.items())),
        "artifact_count": artifact_count,
        "covered_requirement_count": covered_requirement_count,
        "timing_summary_ms": timing_summary_ms,
        "throughput": _throughput_summary(
            job_count=len(all_job_ids),
            worker_count=worker_count,
            total_duration_seconds=total_duration_seconds,
            timing_summary_ms=timing_summary_ms,
            round_durations_seconds=[
                float(round_result["duration_seconds"]) for round_result in round_results
            ],
        ),
        "per_round_duration_seconds": [
            round_result["duration_seconds"] for round_result in round_results
        ],
        "total_duration_seconds": total_duration_seconds,
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
        "configured_database_backend": settings.database_backend,
        "workflow_job_store_backend": settings.database_backend,
    }
    _enforce_throughput_thresholds(
        result,
        max_queue_wait_ms=max_queue_wait_ms,
        min_throughput_jobs_per_second=min_throughput_jobs_per_second,
    )
    return result


def _wait_for_terminal_jobs(
    queue: TestAgentWorkflowJobQueue,
    job_ids: list[str],
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> list[TestAgentWorkflowJobDetail]:
    deadline = time.time() + timeout_seconds
    details_by_id: dict[str, TestAgentWorkflowJobDetail] = {}
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
    raise WorkflowRQMySQLSmokeError(
        f"Timed out waiting for terminal jobs. states={states} missing={missing}"
    )


def _summarize_details(details: list[TestAgentWorkflowJobDetail]) -> dict[str, Any]:
    job_status_counts = Counter(_status_value(detail.status) for detail in details)
    failed_jobs = [
        detail.id
        for detail in details
        if _status_value(detail.status) != "succeeded"
    ]
    if failed_jobs:
        raise WorkflowRQMySQLSmokeError(
            f"Workflow job(s) failed unexpectedly: {failed_jobs}"
        )

    results = [detail.result for detail in details]
    if any(result is None for result in results):
        missing = [detail.id for detail in details if detail.result is None]
        raise WorkflowRQMySQLSmokeError(f"Job(s) missing workflow results: {missing}")

    concrete_results = [result for result in results if result is not None]
    report_status_counts = Counter(
        _status_value(result.report.status) for result in concrete_results
    )
    tool_status_counts: Counter[str] = Counter()
    artifact_count = 0
    covered_requirement_count = 0
    timing_samples = _empty_timing_samples()
    empty_plans: list[str] = []
    for detail, result in zip(details, concrete_results, strict=True):
        _append_timing_samples(timing_samples, detail)
        if not result.plan.steps:
            empty_plans.append(detail.id)
        for covered in result.report.requirement_coverage.values():
            if covered:
                covered_requirement_count += 1
        for tool_run in result.report.tool_runs:
            tool_status_counts[_status_value(tool_run.status)] += 1
            artifact_count += len(tool_run.artifact_paths)

    if empty_plans:
        raise WorkflowRQMySQLSmokeError(f"Job(s) produced empty plans: {empty_plans}")
    if report_status_counts.get("passed", 0) != len(details):
        raise WorkflowRQMySQLSmokeError(
            f"Expected all reports to pass, got {dict(report_status_counts)}."
        )
    if tool_status_counts.get(ToolRunStatus.passed.value, 0) < len(details):
        raise WorkflowRQMySQLSmokeError(
            f"Expected at least one passed tool run per job, got {dict(tool_status_counts)}."
        )
    if artifact_count < len(details):
        raise WorkflowRQMySQLSmokeError(
            f"Expected at least one artifact per job, got {artifact_count}."
        )
    if covered_requirement_count < len(details):
        raise WorkflowRQMySQLSmokeError(
            "Expected at least one covered requirement per workflow job, got "
            f"{covered_requirement_count}."
        )

    return {
        "ok": True,
        "job_count": len(details),
        "job_ids": [detail.id for detail in details],
        "job_status_counts": dict(sorted(job_status_counts.items())),
        "report_status_counts": dict(sorted(report_status_counts.items())),
        "tool_status_counts": dict(sorted(tool_status_counts.items())),
        "artifact_count": artifact_count,
        "covered_requirement_count": covered_requirement_count,
        "timing_samples": timing_samples,
        "timing_summary_ms": _summarize_timing_samples(timing_samples),
    }


def _empty_timing_samples() -> dict[str, list[float]]:
    return {
        "queue_wait_ms": [],
        "job_runtime_ms": [],
        "job_total_ms": [],
        "workflow_total_ms": [],
        "plan_generation_ms": [],
        "tool_execution_ms": [],
        "report_build_ms": [],
    }


def _append_timing_samples(
    samples: dict[str, list[float]],
    detail: TestAgentWorkflowJobDetail,
) -> None:
    for name in samples:
        value = getattr(detail.timing, name)
        if value is not None:
            samples[name].append(float(value))


def _extend_timing_samples(
    target: dict[str, list[float]],
    source: object,
) -> None:
    if not isinstance(source, dict):
        return
    for name in target:
        values = source.get(name, [])
        if isinstance(values, list):
            target[name].extend(float(value) for value in values)


def _summarize_timing_samples(
    samples: dict[str, list[float]],
) -> dict[str, dict[str, float | int | None]]:
    return {name: _timing_stats(values) for name, values in samples.items()}


def _throughput_summary(
    *,
    job_count: int,
    worker_count: int,
    total_duration_seconds: float,
    timing_summary_ms: dict[str, dict[str, float | int | None]],
    round_durations_seconds: list[float],
) -> dict[str, float | int | None]:
    jobs_per_second = _rate(job_count, total_duration_seconds)
    avg_round_duration = (
        round(sum(round_durations_seconds) / len(round_durations_seconds), 3)
        if round_durations_seconds
        else None
    )
    max_round_duration = (
        round(max(round_durations_seconds), 3) if round_durations_seconds else None
    )
    return {
        "job_count": job_count,
        "worker_count": worker_count,
        "jobs_per_second": jobs_per_second,
        "jobs_per_worker_per_second": _rate(jobs_per_second, worker_count)
        if jobs_per_second is not None
        else None,
        "avg_round_duration_seconds": avg_round_duration,
        "max_round_duration_seconds": max_round_duration,
        "max_queue_wait_ms": _timing_max(timing_summary_ms, "queue_wait_ms"),
        "max_job_runtime_ms": _timing_max(timing_summary_ms, "job_runtime_ms"),
        "max_workflow_total_ms": _timing_max(timing_summary_ms, "workflow_total_ms"),
    }


def _rate(numerator: float | int, denominator: float | int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 3)


def _timing_max(
    timing_summary_ms: dict[str, dict[str, float | int | None]],
    name: str,
) -> float | None:
    value = timing_summary_ms.get(name, {}).get("max")
    return float(value) if isinstance(value, int | float) else None


def _timing_stats(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "avg": None, "max": None}
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 3),
        "max": round(max(values), 3),
    }


def _request_for_index(index: int, *, http_base_url: str) -> TestAgentWorkflowRequest:
    requirement_id = f"REQ-WORKFLOW-SMOKE-{index + 1:03d}"
    requirement = RequirementPoint(
        id=requirement_id,
        title=f"API 健康检查 {index + 1:03d}",
        description="GET /health 200 API 健康检查必须返回成功。",
        keywords=["GET", "/health", "200", "API"],
        priority="high",
        source="smoke/test-agent-workflow-rq-mysql",
    )
    generation_request = TestPlanGenerationRequest(
        description=(
            "Docker RQ MySQL workflow smoke: GET /health 200 API 健康检查。"
        ),
        source="smoke/test-agent-workflow-rq-mysql",
        requirements=[requirement],
        context=[],
        max_steps=1,
        use_llm=False,
        allow_llm_fallback=True,
    )
    return TestAgentWorkflowRequest(
        generation_request=generation_request,
        http_base_url=http_base_url,
    )


def _run_init_mysql(config: DockerWorkflowSmokeConfig, runner: Runner) -> StepResult:
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
    config: DockerWorkflowSmokeConfig,
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


def _run_submitter(
    config: DockerWorkflowSmokeConfig,
    runner: Runner,
) -> dict[str, Any]:
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
            "scripts/smoke_test_agent_workflow_rq_mysql.py",
            "--submit-only",
            "--json",
            "--job-count",
            str(config.job_count),
            "--jobs-per-round",
            str(config.job_count),
            "--rounds",
            str(config.rounds),
            "--worker-count",
            str(config.worker_count),
            "--http-base-url",
            config.http_base_url,
            "--timeout-seconds",
            str(config.timeout_seconds),
            "--poll-interval-seconds",
            str(config.poll_interval_seconds),
            *(
                [
                    "--fail-over-max-queue-wait-ms",
                    str(config.max_queue_wait_ms),
                ]
                if config.max_queue_wait_ms is not None
                else []
            ),
            *(
                [
                    "--fail-under-throughput-jobs-per-second",
                    str(config.min_throughput_jobs_per_second),
                ]
                if config.min_throughput_jobs_per_second is not None
                else []
            ),
        ],
        "submit-and-poll",
        runner,
    )
    try:
        payload = json.loads(step.stdout_tail)
    except json.JSONDecodeError as exc:
        raise WorkflowRQMySQLSmokeError(
            f"submit-and-poll did not return JSON: {step.stdout_tail}"
        ) from exc
    if not payload.get("ok"):
        raise WorkflowRQMySQLSmokeError(f"submit-and-poll failed: {payload}")
    return {"step": step, "payload": payload}


def _wait_for_api(config: DockerWorkflowSmokeConfig, runner: Runner) -> StepResult:
    script = (
        "import sys,time,urllib.request\n"
        f"url={config.http_base_url.rstrip('/') + '/health'!r}\n"
        f"deadline=time.time()+{int(config.timeout_seconds)}\n"
        "last=''\n"
        "while time.time()<deadline:\n"
        "    try:\n"
        "        urllib.request.urlopen(url, timeout=3).read()\n"
        "        sys.exit(0)\n"
        "    except Exception as exc:\n"
        "        last=f'{type(exc).__name__}: {exc}'\n"
        "        time.sleep(1)\n"
        "print(last, file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    return _run_compose(
        config,
        [
            "run",
            "--rm",
            "-T",
            "--no-deps",
            config.api_service,
            "python",
            "-c",
            script,
        ],
        "wait-api-health",
        runner,
    )


def _remove_worker(
    config: DockerWorkflowSmokeConfig,
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
    config: DockerWorkflowSmokeConfig,
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
        raise WorkflowRQMySQLSmokeError(
            f"{name} failed with exit={step.returncode}: "
            f"{step.stdout_tail}\n{step.stderr_tail}"
        )
    return step


def _compose_command(
    config: DockerWorkflowSmokeConfig,
    args: list[str],
) -> list[str]:
    command = ["docker", "compose"]
    if config.profile:
        command.extend(["--profile", config.profile])
    command.extend(args)
    return command


def _container_env_args(config: DockerWorkflowSmokeConfig) -> list[str]:
    values = {
        "DATABASE_BACKEND": "mysql",
        "DATABASE_URL": config.database_url,
        "GENERATION_JOB_QUEUE_BACKEND": "rq",
        "REDIS_URL": config.redis_url,
        "RQ_QUEUE_NAME": config.queue_name,
        "GENERATION_JOB_MAX_QUEUE_SIZE": str(
            max(config.job_count * config.rounds + config.worker_count + 4, 10)
        ),
        "RQ_JOB_TIMEOUT_SECONDS": str(max(int(config.timeout_seconds), 60)),
        "TEST_TOOL_HTTP_BASE_URL_ALLOWLIST": config.http_base_url.rstrip("/"),
        "TEST_TOOL_HTTP_ALLOWED_HEADERS": "Accept,Content-Type,X-Request-ID",
        "TEST_TOOL_ARTIFACT_DIR": "data/test-artifacts/test-agent-workflow-smoke",
    }
    args: list[str] = []
    for key, value in values.items():
        args.extend(["-e", f"{key}={value}"])
    return args


def _compose_environment(config: DockerWorkflowSmokeConfig) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_DATA_MOUNT": config.app_data_mount,
            "MODEL_CACHE_MOUNT": config.model_cache_mount,
        }
    )
    return env


def _validate_parameters(
    job_count: int,
    *,
    rounds: int,
    worker_count: int,
) -> None:
    if job_count <= 0:
        raise WorkflowRQMySQLSmokeError("job_count must be greater than zero.")
    if rounds <= 0:
        raise WorkflowRQMySQLSmokeError("rounds must be greater than zero.")
    if worker_count <= 0:
        raise WorkflowRQMySQLSmokeError("worker_count must be greater than zero.")


def _validate_throughput_thresholds(
    *,
    max_queue_wait_ms: float | None,
    min_throughput_jobs_per_second: float | None,
) -> None:
    if max_queue_wait_ms is not None and max_queue_wait_ms < 0:
        raise WorkflowRQMySQLSmokeError("max_queue_wait_ms must not be negative.")
    if (
        min_throughput_jobs_per_second is not None
        and min_throughput_jobs_per_second < 0
    ):
        raise WorkflowRQMySQLSmokeError(
            "min_throughput_jobs_per_second must not be negative."
        )


def _enforce_throughput_thresholds(
    result: dict[str, object],
    *,
    max_queue_wait_ms: float | None,
    min_throughput_jobs_per_second: float | None,
) -> None:
    throughput = result.get("throughput")
    if not isinstance(throughput, dict):
        raise WorkflowRQMySQLSmokeError("Missing throughput summary.")
    if max_queue_wait_ms is not None:
        actual = throughput.get("max_queue_wait_ms")
        if not isinstance(actual, int | float):
            raise WorkflowRQMySQLSmokeError("Missing max_queue_wait_ms throughput metric.")
        if float(actual) > max_queue_wait_ms:
            raise WorkflowRQMySQLSmokeError(
                f"max_queue_wait_ms {actual} exceeded threshold {max_queue_wait_ms}."
            )
    if min_throughput_jobs_per_second is not None:
        actual = throughput.get("jobs_per_second")
        if not isinstance(actual, int | float):
            raise WorkflowRQMySQLSmokeError("Missing jobs_per_second throughput metric.")
        if float(actual) < min_throughput_jobs_per_second:
            raise WorkflowRQMySQLSmokeError(
                "jobs_per_second "
                f"{actual} below threshold {min_throughput_jobs_per_second}."
            )


def _default_worker_name() -> str:
    return f"my-agent-project-workflow-smoke-{uuid4().hex[:8]}"


def _worker_names(config: DockerWorkflowSmokeConfig) -> list[str]:
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
        queue_names=["test_agent_workflow"],
    )


def _summarize_queue_alert_report(report: dict[str, Any]) -> dict[str, Any]:
    alerts = list(report.get("alerts") or [])
    return {
        "ok": bool(report.get("ok")),
        "alert_count": len(alerts),
        "alerts": alerts,
        "metrics": report.get("metrics") or {},
    }


def _merge_counts(counter: Counter[str], values: object) -> None:
    if not isinstance(values, dict):
        raise WorkflowRQMySQLSmokeError(f"Expected count dict, got {values!r}")
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
                rounds=args.rounds,
                worker_count=args.worker_count,
                http_base_url=args.http_base_url,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                max_queue_wait_ms=args.fail_over_max_queue_wait_ms,
                min_throughput_jobs_per_second=args.fail_under_throughput_jobs_per_second,
            )
        else:
            config = DockerWorkflowSmokeConfig(
                project_root=Path(args.project_root).resolve(),
                profile=args.profile,
                worker_container_name=args.worker_container_name,
                database_url=args.database_url,
                redis_url=args.redis_url,
                queue_name=args.queue_name,
                http_base_url=args.http_base_url,
                app_data_mount=args.app_data_mount,
                model_cache_mount=args.model_cache_mount,
                job_count=jobs_per_round,
                rounds=args.rounds,
                worker_count=args.worker_count,
                timeout_seconds=args.timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                max_queue_wait_ms=args.fail_over_max_queue_wait_ms,
                min_throughput_jobs_per_second=args.fail_under_throughput_jobs_per_second,
                command_timeout_seconds=args.command_timeout_seconds,
                start_services=not args.no_start_services,
                initialize_mysql=not args.no_init_mysql,
            )
            result = run_docker_workflow_smoke(config)
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL test-agent-workflow-rq-mysql-smoke: {payload['error']}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if args.submit_only:
            print(
                "PASS test-agent-workflow-rq-mysql-submit: "
                f"jobs={result['job_count']} rounds={result['rounds']} "
                f"reports={result['report_status_counts']} "
                f"throughput={result.get('throughput')}"
            )
        else:
            submit = result.get("submit") if isinstance(result, dict) else None
            print(
                "PASS test-agent-workflow-rq-mysql-smoke: "
                f"workers={result.get('worker_count')} submit={submit}"
            )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Docker Redis/RQ + MySQL smoke for test agent workflow jobs.",
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
    parser.add_argument("--http-base-url", default=DEFAULT_HTTP_BASE_URL)
    parser.add_argument("--app-data-mount", default="smoke-data")
    parser.add_argument("--model-cache-mount", default="smoke-model-cache")
    parser.add_argument(
        "--job-count",
        type=int,
        default=None,
        help="Backward-compatible alias for --jobs-per-round.",
    )
    parser.add_argument("--jobs-per-round", type=int)
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--worker-count", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=1.0)
    parser.add_argument(
        "--fail-over-max-queue-wait-ms",
        type=float,
        default=None,
        help="Fail if observed max workflow queue wait exceeds this threshold.",
    )
    parser.add_argument(
        "--fail-under-throughput-jobs-per-second",
        type=float,
        default=None,
        help="Fail if observed aggregate workflow throughput is below this threshold.",
    )
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
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
