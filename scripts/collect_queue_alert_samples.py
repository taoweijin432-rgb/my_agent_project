import argparse
import json
import math
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

from scripts import check_queue_alerts
from scripts.check_queue_alerts import QueueAlertThresholds


ReportBuilder = Callable[..., dict[str, Any]]
Sleep = Callable[[float], None]
MAX_METRIC_KEYS = (
    "database_active_jobs",
    "rq_queued",
    "rq_started",
    "rq_deferred",
    "rq_scheduled",
    "rq_failed",
    "rq_finished",
    "worker_count",
)


def collect_alert_samples(
    *,
    output_jsonl: Path,
    sample_count: int,
    interval_seconds: float,
    thresholds: QueueAlertThresholds,
    queue_names: list[str] | None,
    fail_on_warning: bool,
    headroom_ratio: float = 0.25,
    minimum_headroom: int = 1,
    report_builder: ReportBuilder = check_queue_alerts.build_alert_report,
    sleep: Sleep = time.sleep,
) -> dict[str, Any]:
    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")
    if interval_seconds < 0:
        raise ValueError("interval_seconds must be non-negative")
    if headroom_ratio < 0:
        raise ValueError("headroom_ratio must be non-negative")
    if minimum_headroom < 0:
        raise ValueError("minimum_headroom must be non-negative")

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    with output_jsonl.open("w", encoding="utf-8") as handle:
        for sample_index in range(1, sample_count + 1):
            report = report_builder(
                thresholds=thresholds,
                queue_names=queue_names,
            )
            reports.append(report)
            sample = {
                "sample_index": sample_index,
                "sample_count": sample_count,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "report": report,
            }
            handle.write(json.dumps(sample, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            handle.flush()
            if sample_index < sample_count and interval_seconds > 0:
                sleep(interval_seconds)

    return build_sample_summary(
        reports,
        output_jsonl=output_jsonl,
        thresholds=thresholds,
        fail_on_warning=fail_on_warning,
        headroom_ratio=headroom_ratio,
        minimum_headroom=minimum_headroom,
    )


def build_sample_summary(
    reports: list[dict[str, Any]],
    *,
    output_jsonl: Path | None = None,
    thresholds: QueueAlertThresholds | None = None,
    fail_on_warning: bool = False,
    headroom_ratio: float = 0.25,
    minimum_headroom: int = 1,
) -> dict[str, Any]:
    alert_counts_by_severity: Counter[str] = Counter()
    alert_counts_by_code: Counter[str] = Counter()
    alert_counts_by_queue: Counter[str] = Counter()
    observed_metrics: dict[str, dict[str, Any]] = {}
    observed_at_values: list[str] = []

    for report in reports:
        generated_at = report.get("generated_at")
        if generated_at:
            observed_at_values.append(str(generated_at))
        for queue_name, metrics in (report.get("metrics") or {}).items():
            queue_metrics = observed_metrics.setdefault(
                str(queue_name),
                {
                    "sample_count": 0,
                    "max": {key: 0 for key in MAX_METRIC_KEYS},
                    "min_worker_count": None,
                },
            )
            queue_metrics["sample_count"] += 1
            for key in MAX_METRIC_KEYS:
                value = _as_int((metrics or {}).get(key))
                queue_metrics["max"][key] = max(queue_metrics["max"][key], value)
            worker_count = _as_int((metrics or {}).get("worker_count"))
            current_min = queue_metrics["min_worker_count"]
            queue_metrics["min_worker_count"] = (
                worker_count if current_min is None else min(current_min, worker_count)
            )
        for alert in report.get("alerts") or []:
            severity = str(alert.get("severity") or "unknown")
            code = str(alert.get("code") or "unknown")
            queue = str(alert.get("queue") or "unknown")
            alert_counts_by_severity[severity] += 1
            alert_counts_by_code[code] += 1
            alert_counts_by_queue[queue] += 1

    has_errors = alert_counts_by_severity.get("error", 0) > 0
    has_warnings = alert_counts_by_severity.get("warning", 0) > 0
    return {
        "ok": not has_errors and not (fail_on_warning and has_warnings),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(reports),
        "observed_at_start": min(observed_at_values) if observed_at_values else None,
        "observed_at_end": max(observed_at_values) if observed_at_values else None,
        "output_jsonl": str(output_jsonl) if output_jsonl else None,
        "thresholds": (
            thresholds.__dict__ if thresholds is not None else None
        ),
        "fail_on_warning": fail_on_warning,
        "observed_metrics": observed_metrics,
        "alert_counts": {
            "by_severity": dict(sorted(alert_counts_by_severity.items())),
            "by_code": dict(sorted(alert_counts_by_code.items())),
            "by_queue": dict(sorted(alert_counts_by_queue.items())),
        },
        "candidate_thresholds": _candidate_thresholds(
            observed_metrics,
            headroom_ratio=headroom_ratio,
            minimum_headroom=minimum_headroom,
        ),
        "calibration_note": (
            "Candidate thresholds are observed maxima plus headroom for backlog "
            "metrics; validate against a full business cycle before production alerting."
        ),
    }


def print_text(summary: dict[str, Any]) -> None:
    print("Queue alert sample summary")
    print(f"ok: {str(summary['ok']).lower()}")
    print(f"samples: {summary['sample_count']}")
    print(f"output_jsonl: {summary['output_jsonl']}")
    print("Observed maxima")
    for queue_name, metrics in sorted(summary["observed_metrics"].items()):
        maxima = metrics["max"]
        print(
            f"  {queue_name}: "
            f"active={maxima['database_active_jobs']}, "
            f"queued={maxima['rq_queued']}, "
            f"started={maxima['rq_started']}, "
            f"failed={maxima['rq_failed']}, "
            f"workers_min={metrics['min_worker_count']}"
        )
    print("Alerts")
    severity_counts = summary["alert_counts"]["by_severity"]
    if not severity_counts:
        print("  none")
    else:
        for severity, count in sorted(severity_counts.items()):
            print(f"  {severity}: {count}")
    print("Candidate thresholds")
    for queue_name, thresholds in sorted(summary["candidate_thresholds"].items()):
        print(
            f"  {queue_name}: "
            f"max_active_jobs={thresholds['max_active_jobs']}, "
            f"max_rq_queued={thresholds['max_rq_queued']}, "
            f"max_rq_started={thresholds['max_rq_started']}, "
            f"max_rq_failed={thresholds['max_rq_failed']}"
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    thresholds = QueueAlertThresholds(
        max_active_jobs=args.max_active_jobs,
        max_rq_queued=args.max_rq_queued,
        max_rq_started=args.max_rq_started,
        max_rq_failed=args.max_rq_failed,
        max_worker_heartbeat_age_seconds=args.max_worker_heartbeat_age_seconds,
        require_worker=args.require_worker,
    )
    summary = collect_alert_samples(
        output_jsonl=args.output_jsonl or _default_output_jsonl(),
        sample_count=args.samples,
        interval_seconds=args.interval_seconds,
        thresholds=thresholds,
        queue_names=check_queue_alerts._queue_names(args.queue),
        fail_on_warning=args.fail_on_warning,
        headroom_ratio=args.headroom_ratio,
        minimum_headroom=args.minimum_headroom,
        report_builder=check_queue_alerts.build_alert_report,
    )
    summary_json = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_summary_json:
        args.output_summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_summary_json.write_text(f"{summary_json}\n", encoding="utf-8")
    if args.json:
        print(summary_json)
    else:
        print_text(summary)

    has_errors = summary["alert_counts"]["by_severity"].get("error", 0) > 0
    has_warnings = summary["alert_counts"]["by_severity"].get("warning", 0) > 0
    if has_errors or (args.fail_on_warning and has_warnings):
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect queue alert samples over time for threshold calibration.",
    )
    parser.add_argument(
        "--queue",
        choices=("all", "generation", "test-agent-workflow", "test-plan-execution"),
        default="all",
    )
    parser.add_argument("--samples", type=_positive_int, default=3)
    parser.add_argument("--interval-seconds", type=_non_negative_float, default=60.0)
    parser.add_argument("--max-active-jobs", type=int)
    parser.add_argument("--max-rq-queued", type=int)
    parser.add_argument("--max-rq-started", type=int)
    parser.add_argument("--max-rq-failed", type=int, default=0)
    parser.add_argument("--max-worker-heartbeat-age-seconds", type=int, default=900)
    parser.add_argument("--require-worker", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--headroom-ratio", type=_non_negative_float, default=0.25)
    parser.add_argument("--minimum-headroom", type=_non_negative_int, default=1)
    parser.add_argument("--json", action="store_true", help="Print summary JSON.")
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        help="Write raw queue alert samples as JSONL.",
    )
    parser.add_argument(
        "--output-summary-json",
        type=Path,
        help="Write the final summary JSON.",
    )
    return parser.parse_args(argv)


def _candidate_thresholds(
    observed_metrics: dict[str, dict[str, Any]],
    *,
    headroom_ratio: float,
    minimum_headroom: int,
) -> dict[str, dict[str, int]]:
    candidates: dict[str, dict[str, int]] = {}
    for queue_name, metrics in observed_metrics.items():
        maxima = metrics["max"]
        candidates[queue_name] = {
            "max_active_jobs": _with_headroom(
                maxima["database_active_jobs"],
                headroom_ratio=headroom_ratio,
                minimum_headroom=minimum_headroom,
            ),
            "max_rq_queued": _with_headroom(
                maxima["rq_queued"],
                headroom_ratio=headroom_ratio,
                minimum_headroom=minimum_headroom,
            ),
            "max_rq_started": _with_headroom(
                maxima["rq_started"],
                headroom_ratio=headroom_ratio,
                minimum_headroom=minimum_headroom,
            ),
            "max_rq_failed": maxima["rq_failed"],
        }
    return candidates


def _with_headroom(
    value: int,
    *,
    headroom_ratio: float,
    minimum_headroom: int,
) -> int:
    if value <= 0:
        return 0
    return value + max(minimum_headroom, math.ceil(value * headroom_ratio))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _default_output_jsonl() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "data" / "ops-drills" / f"queue-alert-samples-{stamp}.jsonl"


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


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


if __name__ == "__main__":
    raise SystemExit(main())
