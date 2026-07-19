import argparse
import json
import os
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from scripts.check_queue_alerts import QueueAlertThresholds
from scripts.collect_queue_alert_samples import build_sample_summary
from scripts.smoke_service_mode_workflow_load import (
    DEFAULT_DESCRIPTION,
    TIMING_FIELDS,
    run_workflow_load_smoke,
)


LoadRunner = Callable[..., dict[str, Any]]
Sleep = Callable[[float], None]


def collect_service_mode_calibration(
    *,
    output_jsonl: Path,
    api_url: str,
    api_key: str,
    sample_count: int,
    interval_seconds: float,
    jobs_per_sample: int,
    description: str,
    poll_interval_seconds: float,
    job_timeout_seconds: float,
    queue_thresholds: QueueAlertThresholds,
    fail_on_warning: bool,
    headroom_ratio: float,
    minimum_headroom: int,
    fail_over_max_queue_wait_ms: float | None = None,
    fail_over_max_job_total_ms: float | None = None,
    fail_under_throughput_jobs_per_second: float | None = None,
    load_runner: LoadRunner | None = None,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    _validate_inputs(
        sample_count=sample_count,
        interval_seconds=interval_seconds,
        jobs_per_sample=jobs_per_sample,
        headroom_ratio=headroom_ratio,
        minimum_headroom=minimum_headroom,
    )

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if load_runner is None:
        load_runner = run_workflow_load_smoke
    load_summaries: list[dict[str, Any]] = []
    queue_reports: list[dict[str, Any]] = []
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for sample_index in range(1, sample_count + 1):
            load_summary = load_runner(
                api_url=api_url,
                api_key=api_key,
                rounds=1,
                jobs_per_round=jobs_per_sample,
                description=description,
                poll_interval_seconds=poll_interval_seconds,
                job_timeout_seconds=job_timeout_seconds,
                round_delay_seconds=0,
                queue_thresholds=queue_thresholds,
                queue_alert_check=True,
                sample_queue_after_submit=True,
                fail_over_max_queue_wait_ms=fail_over_max_queue_wait_ms,
                fail_over_max_job_total_ms=fail_over_max_job_total_ms,
                fail_under_throughput_jobs_per_second=(
                    fail_under_throughput_jobs_per_second
                ),
            )
            load_summaries.append(load_summary)
            sample_queue_reports = _queue_reports_from_load(load_summary)
            queue_reports.extend(sample_queue_reports)
            sample = {
                "sample_index": sample_index,
                "sample_count": sample_count,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "load": load_summary,
                "queue_reports": sample_queue_reports,
            }
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            handle.flush()
            if sample_index < sample_count and interval_seconds > 0:
                sleep(interval_seconds)

    queue_summary = build_sample_summary(
        queue_reports,
        output_jsonl=output_jsonl,
        thresholds=queue_thresholds,
        fail_on_warning=fail_on_warning,
        headroom_ratio=headroom_ratio,
        minimum_headroom=minimum_headroom,
    )
    load_summary = build_load_summary(load_summaries)
    has_load_failures = any(not summary.get("ok") for summary in load_summaries)
    return {
        "ok": queue_summary["ok"] and not has_load_failures,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "api_url": api_url,
        "sample_count": sample_count,
        "jobs_per_sample": jobs_per_sample,
        "output_jsonl": str(output_jsonl),
        "queue_summary": queue_summary,
        "load_summary": load_summary,
        "calibration_note": (
            "Candidate thresholds are based on service-mode workload samples; "
            "validate against a full business cycle before production alerting."
        ),
    }


def build_load_summary(load_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    jobs: list[dict[str, Any]] = []
    jobs_by_status: Counter[str] = Counter()
    report_status_counts: Counter[str] = Counter()
    throughputs: list[float] = []
    failures: list[str] = []

    for index, summary in enumerate(load_summaries, start=1):
        jobs.extend(summary.get("jobs") or [])
        jobs_by_status.update(summary.get("jobs_by_status") or {})
        report_status_counts.update(summary.get("report_status_counts") or {})
        throughput = (summary.get("throughput") or {}).get("jobs_per_second")
        if throughput is not None:
            throughputs.append(float(throughput))
        for failure in summary.get("failures") or []:
            failures.append(f"sample {index}: {failure}")

    return {
        "sample_count": len(load_summaries),
        "job_count": len(jobs),
        "jobs_by_status": dict(jobs_by_status),
        "report_status_counts": dict(report_status_counts),
        "timing_summary_ms": _timing_summary(jobs),
        "throughput_jobs_per_second": _number_summary(throughputs),
        "failures": failures,
    }


def _queue_reports_from_load(load_summary: dict[str, Any]) -> list[dict[str, Any]]:
    reports = load_summary.get("queue_alert_reports") or []
    if not reports:
        return [
            {
                "ok": False,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "metrics": {},
                "alerts": [
                    {
                        "queue": "all",
                        "severity": "error",
                        "code": "missing_queue_report",
                        "message": (
                            "Load summary did not include queue alert reports."
                        ),
                    }
                ],
                "snapshots": {},
            }
        ]
    return list(reports)


def _timing_summary(jobs: list[dict[str, Any]]) -> dict[str, dict[str, float] | None]:
    summary: dict[str, dict[str, float] | None] = {}
    for field in TIMING_FIELDS:
        values = [
            float((job.get("timing") or {}).get(field))
            for job in jobs
            if (job.get("timing") or {}).get(field) is not None
        ]
        summary[field] = _number_summary(values)
    return summary


def _number_summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    return {
        "avg": round(sum(values) / len(values), 3),
        "max": round(max(values), 3),
        "min": round(min(values), 3),
    }


def print_text(summary: dict[str, Any]) -> None:
    print("Service-mode calibration summary")
    print(f"ok: {str(summary['ok']).lower()}")
    print(f"samples: {summary['sample_count']}")
    print(f"jobs: {summary['load_summary']['job_count']}")
    print(f"jobs_by_status: {summary['load_summary']['jobs_by_status']}")
    print(f"queue_alerts: {summary['queue_summary']['alert_counts']}")
    print("Candidate thresholds")
    for queue_name, thresholds in sorted(
        summary["queue_summary"]["candidate_thresholds"].items()
    ):
        print(
            f"  {queue_name}: "
            f"max_active_jobs={thresholds['max_active_jobs']}, "
            f"max_rq_queued={thresholds['max_rq_queued']}, "
            f"max_rq_started={thresholds['max_rq_started']}, "
            f"max_rq_failed={thresholds['max_rq_failed']}"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    queue_thresholds = QueueAlertThresholds(
        max_active_jobs=args.max_active_jobs,
        max_rq_queued=args.max_rq_queued,
        max_rq_started=args.max_rq_started,
        max_rq_failed=args.max_rq_failed,
        max_worker_heartbeat_age_seconds=args.max_worker_heartbeat_age_seconds,
        require_worker=args.require_worker,
    )
    api_key = args.api_key or _default_api_key()
    summary = collect_service_mode_calibration(
        output_jsonl=args.output_jsonl or _default_output_jsonl(),
        api_url=args.api_url,
        api_key=api_key,
        sample_count=args.samples,
        interval_seconds=args.interval_seconds,
        jobs_per_sample=args.jobs_per_sample,
        description=args.description,
        poll_interval_seconds=args.poll_interval_seconds,
        job_timeout_seconds=args.job_timeout_seconds,
        queue_thresholds=queue_thresholds,
        fail_on_warning=args.fail_on_warning,
        headroom_ratio=args.headroom_ratio,
        minimum_headroom=args.minimum_headroom,
        fail_over_max_queue_wait_ms=args.fail_over_max_queue_wait_ms,
        fail_over_max_job_total_ms=args.fail_over_max_job_total_ms,
        fail_under_throughput_jobs_per_second=(
            args.fail_under_throughput_jobs_per_second
        ),
    )
    summary_json = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_summary_json:
        args.output_summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_summary_json.write_text(f"{summary_json}\n", encoding="utf-8")
    if args.json:
        print(summary_json)
    else:
        print_text(summary)
    return 0 if summary["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run repeated service-mode workflow load samples and summarize "
            "queue alert threshold candidates."
        ),
    )
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key")
    parser.add_argument("--samples", type=_positive_int, default=3)
    parser.add_argument("--interval-seconds", type=_non_negative_float, default=60.0)
    parser.add_argument("--jobs-per-sample", type=_positive_int, default=4)
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument("--poll-interval-seconds", type=_positive_float, default=0.5)
    parser.add_argument("--job-timeout-seconds", type=_positive_float, default=60.0)
    parser.add_argument("--max-active-jobs", type=int)
    parser.add_argument("--max-rq-queued", type=int)
    parser.add_argument("--max-rq-started", type=int)
    parser.add_argument("--max-rq-failed", type=int, default=0)
    parser.add_argument("--max-worker-heartbeat-age-seconds", type=int, default=900)
    parser.add_argument("--require-worker", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--headroom-ratio", type=_non_negative_float, default=0.25)
    parser.add_argument("--minimum-headroom", type=_non_negative_int, default=1)
    parser.add_argument("--fail-over-max-queue-wait-ms", type=float)
    parser.add_argument("--fail-over-max-job-total-ms", type=float)
    parser.add_argument("--fail-under-throughput-jobs-per-second", type=float)
    parser.add_argument("--output-jsonl", type=Path)
    parser.add_argument("--output-summary-json", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _default_api_key() -> str:
    env_key = os.environ.get("APP_API_KEY")
    if env_key:
        return env_key
    keys = get_settings().accepted_api_keys
    if not keys:
        raise RuntimeError("Provide --api-key or APP_API_KEY.")
    return keys[0]


def _default_output_jsonl() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "data" / "ops-drills" / f"service-mode-calibration-{stamp}.jsonl"


def _validate_inputs(
    *,
    sample_count: int,
    interval_seconds: float,
    jobs_per_sample: int,
    headroom_ratio: float,
    minimum_headroom: int,
) -> None:
    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")
    if jobs_per_sample < 1:
        raise ValueError("jobs_per_sample must be at least 1")
    if headroom_ratio < 0:
        raise ValueError("headroom_ratio must be non-negative")
    if minimum_headroom < 0:
        raise ValueError("minimum_headroom must be non-negative")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
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
