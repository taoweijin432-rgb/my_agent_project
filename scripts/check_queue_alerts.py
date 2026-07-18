import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings, get_settings
from scripts import check_generation_queue
from scripts import check_test_agent_workflow_queue
from scripts import check_test_plan_execution_queue


SnapshotBuilder = Callable[[Settings], dict[str, Any]]
QUEUE_BUILDERS: dict[str, SnapshotBuilder] = {
    "generation": check_generation_queue.build_snapshot,
    "test_agent_workflow": check_test_agent_workflow_queue.build_snapshot,
    "test_plan_execution": check_test_plan_execution_queue.build_snapshot,
}


@dataclass(frozen=True)
class QueueAlertThresholds:
    max_active_jobs: int | None = None
    max_rq_queued: int | None = None
    max_rq_started: int | None = None
    max_rq_failed: int | None = 0
    max_worker_heartbeat_age_seconds: int | None = 900
    require_worker: bool = False


@dataclass(frozen=True)
class QueueAlert:
    queue: str
    severity: str
    code: str
    message: str


def build_alert_report(
    settings: Settings | None = None,
    *,
    thresholds: QueueAlertThresholds | None = None,
    queue_names: list[str] | None = None,
    now: datetime | None = None,
    builders: dict[str, SnapshotBuilder] | None = None,
) -> dict[str, Any]:
    effective_settings = settings or get_settings()
    effective_thresholds = thresholds or QueueAlertThresholds()
    selected_names = queue_names or list(QUEUE_BUILDERS)
    selected_builders = builders or QUEUE_BUILDERS
    observed_at = now or datetime.now(timezone.utc)
    snapshots: dict[str, dict[str, Any]] = {}
    metrics: dict[str, dict[str, int | str | None]] = {}
    alerts: list[QueueAlert] = []

    for queue_name in selected_names:
        builder = selected_builders.get(queue_name)
        if builder is None:
            alerts.append(
                QueueAlert(
                    queue=queue_name,
                    severity="error",
                    code="unknown_queue",
                    message=f"Unknown queue alert target: {queue_name}",
                )
            )
            continue
        try:
            snapshot = builder(effective_settings)
        except Exception as exc:
            alerts.append(
                QueueAlert(
                    queue=queue_name,
                    severity="error",
                    code="snapshot_failed",
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        snapshots[queue_name] = snapshot
        metrics[queue_name] = extract_metrics(snapshot)
        alerts.extend(
            evaluate_snapshot(
                queue_name,
                snapshot,
                thresholds=effective_thresholds,
                now=observed_at,
            )
        )

    alert_payload = [asdict(alert) for alert in alerts]
    return {
        "ok": not any(alert.severity == "error" for alert in alerts),
        "generated_at": observed_at.isoformat(),
        "thresholds": asdict(effective_thresholds),
        "metrics": metrics,
        "alerts": alert_payload,
        "snapshots": snapshots,
    }


def evaluate_snapshot(
    queue_name: str,
    snapshot: dict[str, Any],
    *,
    thresholds: QueueAlertThresholds,
    now: datetime,
) -> list[QueueAlert]:
    alerts: list[QueueAlert] = []
    health = snapshot.get("health") or {}
    for message in health.get("errors") or []:
        alerts.append(_alert(queue_name, "error", "queue_health_error", str(message)))
    for message in health.get("warnings") or []:
        alerts.append(_alert(queue_name, "warning", "queue_health_warning", str(message)))

    database = snapshot.get("database") or {}
    queue = snapshot.get("queue") or {}
    _check_limit(
        alerts,
        queue_name=queue_name,
        code="active_jobs_exceeded",
        label="database active jobs",
        value=int(database.get("active_count") or 0),
        limit=thresholds.max_active_jobs,
    )
    _check_limit(
        alerts,
        queue_name=queue_name,
        code="rq_queued_exceeded",
        label="RQ queued jobs",
        value=int(queue.get("queued") or 0),
        limit=thresholds.max_rq_queued,
    )
    _check_limit(
        alerts,
        queue_name=queue_name,
        code="rq_started_exceeded",
        label="RQ started jobs",
        value=int(queue.get("started") or 0),
        limit=thresholds.max_rq_started,
    )
    _check_limit(
        alerts,
        queue_name=queue_name,
        code="rq_failed_exceeded",
        label="RQ failed registry jobs",
        value=int(queue.get("failed") or 0),
        limit=thresholds.max_rq_failed,
    )

    if thresholds.require_worker and queue.get("backend") == "rq":
        if int(queue.get("worker_count") or 0) == 0:
            alerts.append(
                _alert(
                    queue_name,
                    "error",
                    "worker_required",
                    "Redis/RQ backend is enabled but no worker is registered.",
                )
            )

    if thresholds.max_worker_heartbeat_age_seconds is not None:
        alerts.extend(
            _worker_heartbeat_alerts(
                queue_name,
                queue.get("workers") or [],
                max_age_seconds=thresholds.max_worker_heartbeat_age_seconds,
                now=now,
            )
        )
    return alerts


def extract_metrics(snapshot: dict[str, Any]) -> dict[str, int | str | None]:
    database = snapshot.get("database") or {}
    queue = snapshot.get("queue") or {}
    return {
        "database_backend": str(database.get("backend") or ""),
        "configured_database_backend": database.get("configured_database_backend"),
        "database_active_jobs": int(database.get("active_count") or 0),
        "rq_backend": str(queue.get("backend") or ""),
        "rq_active": int(bool(queue.get("active"))),
        "rq_queued": int(queue.get("queued") or 0),
        "rq_started": int(queue.get("started") or 0),
        "rq_deferred": int(queue.get("deferred") or 0),
        "rq_scheduled": int(queue.get("scheduled") or 0),
        "rq_failed": int(queue.get("failed") or 0),
        "rq_finished": int(queue.get("finished") or 0),
        "worker_count": int(queue.get("worker_count") or 0),
    }


def print_text(report: dict[str, Any]) -> None:
    print("Queue alert report")
    print(f"ok: {str(report['ok']).lower()}")
    print("Metrics")
    for queue_name, metrics in sorted(report["metrics"].items()):
        print(f"  {queue_name}:")
        for key, value in sorted(metrics.items()):
            print(f"    {key}: {value}")
    print("Alerts")
    if not report["alerts"]:
        print("  none")
        return
    for alert in report["alerts"]:
        print(
            "  "
            f"[{alert['severity']}] {alert['queue']} {alert['code']}: "
            f"{alert['message']}"
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
    report = build_alert_report(
        thresholds=thresholds,
        queue_names=_queue_names(args.queue),
    )
    report_json = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output_json:
        _write_json_report(args.output_json, report_json)
    if args.json:
        print(report_json)
    else:
        print_text(report)

    has_errors = any(alert["severity"] == "error" for alert in report["alerts"])
    has_warnings = any(alert["severity"] == "warning" for alert in report["alerts"])
    if has_errors or (args.fail_on_warning and has_warnings):
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate queue snapshots against configurable alert thresholds.",
    )
    parser.add_argument(
        "--queue",
        choices=("all", "generation", "test-agent-workflow", "test-plan-execution"),
        default="all",
    )
    parser.add_argument("--max-active-jobs", type=int)
    parser.add_argument("--max-rq-queued", type=int)
    parser.add_argument("--max-rq-started", type=int)
    parser.add_argument("--max-rq-failed", type=int, default=0)
    parser.add_argument("--max-worker-heartbeat-age-seconds", type=int, default=900)
    parser.add_argument("--require-worker", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Write the JSON report to a file for drill evidence archival.",
    )
    return parser.parse_args(argv)


def _write_json_report(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{content}\n", encoding="utf-8")


def _queue_names(value: str) -> list[str]:
    if value == "all":
        return ["generation", "test_agent_workflow", "test_plan_execution"]
    if value == "test-agent-workflow":
        return ["test_agent_workflow"]
    if value == "test-plan-execution":
        return ["test_plan_execution"]
    return [value]


def _check_limit(
    alerts: list[QueueAlert],
    *,
    queue_name: str,
    code: str,
    label: str,
    value: int,
    limit: int | None,
) -> None:
    if limit is None or value <= limit:
        return
    alerts.append(
        _alert(
            queue_name,
            "error",
            code,
            f"{label}={value} exceeds threshold {limit}.",
        )
    )


def _worker_heartbeat_alerts(
    queue_name: str,
    workers: list[dict[str, Any]],
    *,
    max_age_seconds: int,
    now: datetime,
) -> list[QueueAlert]:
    alerts: list[QueueAlert] = []
    for worker in workers:
        name = str(worker.get("name") or "unknown")
        raw_heartbeat = worker.get("last_heartbeat")
        if raw_heartbeat is None:
            alerts.append(
                _alert(
                    queue_name,
                    "warning",
                    "worker_heartbeat_missing",
                    f"Worker {name} has no last_heartbeat.",
                )
            )
            continue
        heartbeat = _parse_datetime(str(raw_heartbeat))
        if heartbeat is None:
            alerts.append(
                _alert(
                    queue_name,
                    "warning",
                    "worker_heartbeat_invalid",
                    f"Worker {name} has invalid last_heartbeat: {raw_heartbeat}",
                )
            )
            continue
        age_seconds = (now - heartbeat).total_seconds()
        if age_seconds > max_age_seconds:
            alerts.append(
                _alert(
                    queue_name,
                    "error",
                    "worker_heartbeat_stale",
                    f"Worker {name} heartbeat age {age_seconds:.0f}s exceeds "
                    f"threshold {max_age_seconds}s.",
                )
            )
    return alerts


def _parse_datetime(value: str) -> datetime | None:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _alert(
    queue_name: str,
    severity: str,
    code: str,
    message: str,
) -> QueueAlert:
    return QueueAlert(queue=queue_name, severity=severity, code=code, message=message)


if __name__ == "__main__":
    raise SystemExit(main())
