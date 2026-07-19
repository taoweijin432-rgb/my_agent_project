import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from scripts.check_queue_alerts import (
    QueueAlertThresholds,
    build_alert_report,
)


SubmitJob = Callable[[str, str, dict[str, Any], int], dict[str, Any]]
GetJob = Callable[[str, str, str, int], dict[str, Any]]
QueueReportBuilder = Callable[..., dict[str, Any]]

DEFAULT_DESCRIPTION = "高风险上线需要人工确认审批记录。"
TERMINAL_STATUSES = {"succeeded", "failed"}
TIMING_FIELDS = (
    "queue_wait_ms",
    "job_runtime_ms",
    "job_total_ms",
    "workflow_total_ms",
    "plan_generation_ms",
    "tool_execution_ms",
    "report_build_ms",
)


def run_workflow_load_smoke(
    *,
    api_url: str,
    api_key: str,
    rounds: int,
    jobs_per_round: int,
    description: str,
    poll_interval_seconds: float,
    job_timeout_seconds: float,
    round_delay_seconds: float,
    queue_thresholds: QueueAlertThresholds,
    queue_alert_check: bool,
    sample_queue_after_submit: bool = False,
    fail_over_max_queue_wait_ms: float | None = None,
    fail_over_max_job_total_ms: float | None = None,
    fail_under_throughput_jobs_per_second: float | None = None,
    submit_job: SubmitJob | None = None,
    get_job: GetJob | None = None,
    queue_report_builder: QueueReportBuilder = build_alert_report,
) -> dict[str, Any]:
    if submit_job is None:
        submit_job = submit_workflow_job
    if get_job is None:
        get_job = get_workflow_job

    started = time.perf_counter()
    jobs: list[dict[str, Any]] = []
    round_summaries: list[dict[str, Any]] = []
    queue_alert_reports: list[dict[str, Any]] = []
    failures: list[str] = []

    for round_index in range(1, rounds + 1):
        submitted_jobs: list[dict[str, Any]] = []
        for _ in range(jobs_per_round):
            submitted = submit_job(
                api_url,
                api_key,
                _workflow_payload(description),
                int(job_timeout_seconds),
            )
            submitted_jobs.append(submitted)

        if queue_alert_check and sample_queue_after_submit:
            queue_report = {
                **queue_report_builder(thresholds=queue_thresholds),
                "round": round_index,
                "sample_phase": "after_submit",
            }
            queue_alert_reports.append(queue_report)
            if not queue_report.get("ok"):
                failures.append(
                    f"queue alert check failed after submit in round {round_index}"
                )

        completed_jobs = [
            wait_for_workflow_job(
                api_url,
                api_key,
                str(job["id"]),
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=job_timeout_seconds,
                get_job=get_job,
            )
            for job in submitted_jobs
        ]
        jobs.extend(completed_jobs)
        round_summaries.append(_round_summary(round_index, completed_jobs))

        if queue_alert_check:
            queue_report = queue_report_builder(thresholds=queue_thresholds)
            queue_alert_reports.append(queue_report)
            if not queue_report.get("ok"):
                failures.append(f"queue alert check failed after round {round_index}")

        if round_index < rounds and round_delay_seconds > 0:
            time.sleep(round_delay_seconds)

    elapsed_seconds = max(time.perf_counter() - started, 0.001)
    failures.extend(
        _gate_failures(
            jobs,
            elapsed_seconds=elapsed_seconds,
            fail_over_max_queue_wait_ms=fail_over_max_queue_wait_ms,
            fail_over_max_job_total_ms=fail_over_max_job_total_ms,
            fail_under_throughput_jobs_per_second=(
                fail_under_throughput_jobs_per_second
            ),
        )
    )
    return {
        "ok": not failures,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_url": api_url,
        "rounds": rounds,
        "jobs_per_round": jobs_per_round,
        "job_count": len(jobs),
        "jobs_by_status": dict(Counter(str(job.get("status")) for job in jobs)),
        "report_status_counts": _report_status_counts(jobs),
        "timing_summary_ms": _timing_summary(jobs),
        "throughput": {
            "elapsed_seconds": round(elapsed_seconds, 3),
            "jobs_per_second": round(len(jobs) / elapsed_seconds, 6),
        },
        "rounds_summary": round_summaries,
        "queue_alert_reports": queue_alert_reports,
        "thresholds": {
            "queue_alert": asdict(queue_thresholds),
            "fail_over_max_queue_wait_ms": fail_over_max_queue_wait_ms,
            "fail_over_max_job_total_ms": fail_over_max_job_total_ms,
            "fail_under_throughput_jobs_per_second": (
                fail_under_throughput_jobs_per_second
            ),
        },
        "failures": failures,
        "jobs": [_job_summary(job) for job in jobs],
    }


def submit_workflow_job(
    api_url: str,
    api_key: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    return _request_json(
        f"{_normalize_api_url(api_url)}/api/v1/test-agent/workflow-jobs",
        api_key=api_key,
        method="POST",
        payload=payload,
        timeout_seconds=timeout_seconds,
    )


def get_workflow_job(
    api_url: str,
    api_key: str,
    job_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    return _request_json(
        f"{_normalize_api_url(api_url)}/api/v1/test-agent/workflow-jobs/{job_id}",
        api_key=api_key,
        method="GET",
        payload=None,
        timeout_seconds=timeout_seconds,
    )


def wait_for_workflow_job(
    api_url: str,
    api_key: str,
    job_id: str,
    *,
    poll_interval_seconds: float,
    timeout_seconds: float,
    get_job: GetJob = get_workflow_job,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_detail: dict[str, Any] | None = None
    while time.monotonic() <= deadline:
        last_detail = get_job(api_url, api_key, job_id, int(timeout_seconds))
        if str(last_detail.get("status")) in TERMINAL_STATUSES:
            return last_detail
        time.sleep(poll_interval_seconds)
    return {
        **(last_detail or {"id": job_id}),
        "status": "failed",
        "error": {
            "code": "service_mode_workflow_job_timeout",
            "message": f"Timed out waiting for workflow job {job_id}.",
        },
    }


def print_text(summary: dict[str, Any]) -> None:
    print("Service-mode workflow load smoke")
    print(f"ok: {str(summary['ok']).lower()}")
    print(f"jobs: {summary['job_count']}")
    print(f"jobs_by_status: {summary['jobs_by_status']}")
    print(f"report_status_counts: {summary['report_status_counts']}")
    print(f"throughput_jobs_per_second: {summary['throughput']['jobs_per_second']}")
    for field, values in summary["timing_summary_ms"].items():
        print(f"{field}: avg={values['avg']} max={values['max']}")
    if summary["failures"]:
        print("Failures")
        for failure in summary["failures"]:
            print(f"  - {failure}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = args.api_key or _default_api_key()
    queue_thresholds = QueueAlertThresholds(
        max_active_jobs=args.max_active_jobs,
        max_rq_queued=args.max_rq_queued,
        max_rq_started=args.max_rq_started,
        max_rq_failed=args.max_rq_failed,
        max_worker_heartbeat_age_seconds=args.max_worker_heartbeat_age_seconds,
        require_worker=args.require_worker,
    )
    summary = run_workflow_load_smoke(
        api_url=args.api_url,
        api_key=api_key,
        rounds=args.rounds,
        jobs_per_round=args.jobs_per_round,
        description=args.description,
        poll_interval_seconds=args.poll_interval_seconds,
        job_timeout_seconds=args.job_timeout_seconds,
        round_delay_seconds=args.round_delay_seconds,
        queue_thresholds=queue_thresholds,
        queue_alert_check=not args.skip_queue_alert_check,
        sample_queue_after_submit=args.sample_queue_after_submit,
        fail_over_max_queue_wait_ms=args.fail_over_max_queue_wait_ms,
        fail_over_max_job_total_ms=args.fail_over_max_job_total_ms,
        fail_under_throughput_jobs_per_second=(
            args.fail_under_throughput_jobs_per_second
        ),
    )
    summary_json = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(f"{summary_json}\n", encoding="utf-8")
    if args.json:
        print(summary_json)
    else:
        print_text(summary)
    return 0 if summary["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Submit deterministic Test Agent workflow jobs through the running API "
            "and verify service-mode worker throughput."
        ),
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key")
    parser.add_argument("--rounds", type=_positive_int, default=2)
    parser.add_argument("--jobs-per-round", type=_positive_int, default=3)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--poll-interval-seconds", type=_positive_float, default=0.5)
    parser.add_argument("--job-timeout-seconds", type=_positive_float, default=60.0)
    parser.add_argument("--round-delay-seconds", type=_non_negative_float, default=0.0)
    parser.add_argument("--max-active-jobs", type=int)
    parser.add_argument("--max-rq-queued", type=int)
    parser.add_argument("--max-rq-started", type=int)
    parser.add_argument("--max-rq-failed", type=int, default=0)
    parser.add_argument("--max-worker-heartbeat-age-seconds", type=int, default=900)
    parser.add_argument("--require-worker", action="store_true")
    parser.add_argument("--skip-queue-alert-check", action="store_true")
    parser.add_argument("--sample-queue-after-submit", action="store_true")
    parser.add_argument("--fail-over-max-queue-wait-ms", type=float)
    parser.add_argument("--fail-over-max-job-total-ms", type=float)
    parser.add_argument("--fail-under-throughput-jobs-per-second", type=float)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Write the JSON summary to a file.",
    )
    return parser.parse_args(argv)


def _workflow_payload(description: str) -> dict[str, Any]:
    return {
        "generation_request": {
            "description": description,
            "max_steps": 1,
            "use_llm": False,
        },
        "http_base_url": "http://127.0.0.1:8000",
    }


def _request_json(
    url: str,
    *,
    api_key: str,
    method: str,
    payload: dict[str, Any] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
        },
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
        return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc


def _default_api_key() -> str:
    env_key = os.environ.get("APP_API_KEY")
    if env_key:
        return env_key
    keys = get_settings().accepted_api_keys
    if not keys:
        raise RuntimeError("Provide --api-key or APP_API_KEY.")
    return keys[0]


def _gate_failures(
    jobs: list[dict[str, Any]],
    *,
    elapsed_seconds: float,
    fail_over_max_queue_wait_ms: float | None,
    fail_over_max_job_total_ms: float | None,
    fail_under_throughput_jobs_per_second: float | None,
) -> list[str]:
    failures: list[str] = []
    non_succeeded = [job for job in jobs if job.get("status") != "succeeded"]
    if non_succeeded:
        failures.append(f"{len(non_succeeded)} workflow job(s) did not succeed.")

    timing = _timing_summary(jobs)
    if fail_over_max_queue_wait_ms is not None:
        max_queue_wait = timing.get("queue_wait_ms", {}).get("max")
        if max_queue_wait is not None and max_queue_wait > fail_over_max_queue_wait_ms:
            failures.append(
                f"max queue_wait_ms {max_queue_wait} exceeds "
                f"{fail_over_max_queue_wait_ms}."
            )
    if fail_over_max_job_total_ms is not None:
        max_job_total = timing.get("job_total_ms", {}).get("max")
        if max_job_total is not None and max_job_total > fail_over_max_job_total_ms:
            failures.append(
                f"max job_total_ms {max_job_total} exceeds "
                f"{fail_over_max_job_total_ms}."
            )
    if fail_under_throughput_jobs_per_second is not None:
        throughput = len(jobs) / max(elapsed_seconds, 0.001)
        if throughput < fail_under_throughput_jobs_per_second:
            failures.append(
                f"throughput {throughput:.6f} jobs/s is below "
                f"{fail_under_throughput_jobs_per_second}."
            )
    return failures


def _round_summary(round_index: int, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "round": round_index,
        "job_count": len(jobs),
        "jobs_by_status": dict(Counter(str(job.get("status")) for job in jobs)),
        "timing_summary_ms": _timing_summary(jobs),
    }


def _report_status_counts(jobs: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for job in jobs:
        report = ((job.get("result") or {}).get("report") or {})
        counter[str(report.get("status") or "missing")] += 1
    return dict(counter)


def _timing_summary(jobs: list[dict[str, Any]]) -> dict[str, dict[str, float] | None]:
    summary: dict[str, dict[str, float] | None] = {}
    for field in TIMING_FIELDS:
        values = [
            float((job.get("timing") or {}).get(field))
            for job in jobs
            if (job.get("timing") or {}).get(field) is not None
        ]
        if not values:
            summary[field] = None
            continue
        summary[field] = {
            "avg": round(sum(values) / len(values), 3),
            "max": round(max(values), 3),
            "min": round(min(values), 3),
        }
    return summary


def _job_summary(job: dict[str, Any]) -> dict[str, Any]:
    report = ((job.get("result") or {}).get("report") or {})
    return {
        "id": job.get("id"),
        "status": job.get("status"),
        "error": job.get("error"),
        "report_status": report.get("status"),
        "timing": job.get("timing"),
    }


def _normalize_api_url(value: str) -> str:
    return value.rstrip("/")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
