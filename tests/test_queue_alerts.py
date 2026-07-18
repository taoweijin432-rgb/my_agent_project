from datetime import datetime, timezone

from app.core.config import Settings
from scripts import check_queue_alerts
from scripts.check_queue_alerts import (
    QueueAlertThresholds,
    build_alert_report,
    evaluate_snapshot,
    extract_metrics,
    main,
    _queue_names,
)


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)


def test_extract_metrics_from_generation_snapshot() -> None:
    metrics = extract_metrics(_snapshot(active=2, queued=1, started=1, failed=0))

    assert metrics["database_active_jobs"] == 2
    assert metrics["rq_queued"] == 1
    assert metrics["rq_started"] == 1
    assert metrics["rq_failed"] == 0
    assert metrics["worker_count"] == 1


def test_evaluate_snapshot_promotes_health_errors_and_thresholds() -> None:
    alerts = evaluate_snapshot(
        "generation",
        _snapshot(
            active=3,
            queued=2,
            started=1,
            failed=1,
            errors=["Database active jobs exceed Redis/RQ active jobs."],
            warnings=["RQ failed registry contains 1 job(s)."],
        ),
        thresholds=QueueAlertThresholds(
            max_active_jobs=2,
            max_rq_queued=1,
            max_rq_started=0,
            max_rq_failed=0,
        ),
        now=NOW,
    )

    codes = [alert.code for alert in alerts]
    assert "queue_health_error" in codes
    assert "queue_health_warning" in codes
    assert "active_jobs_exceeded" in codes
    assert "rq_queued_exceeded" in codes
    assert "rq_started_exceeded" in codes
    assert "rq_failed_exceeded" in codes


def test_evaluate_snapshot_detects_stale_worker_heartbeat() -> None:
    alerts = evaluate_snapshot(
        "generation",
        _snapshot(worker_heartbeat="2026-07-13T11:50:00+00:00"),
        thresholds=QueueAlertThresholds(max_worker_heartbeat_age_seconds=60),
        now=NOW,
    )

    assert [alert.code for alert in alerts] == ["worker_heartbeat_stale"]
    assert alerts[0].severity == "error"


def test_evaluate_snapshot_can_require_worker() -> None:
    snapshot = _snapshot(worker_count=0, workers=[])

    alerts = evaluate_snapshot(
        "generation",
        snapshot,
        thresholds=QueueAlertThresholds(require_worker=True),
        now=NOW,
    )

    assert [alert.code for alert in alerts] == ["worker_required"]


def test_build_alert_report_uses_selected_builders() -> None:
    report = build_alert_report(
        Settings(database_backend="sqlite"),
        thresholds=QueueAlertThresholds(max_rq_failed=0),
        queue_names=["generation"],
        now=NOW,
        builders={"generation": lambda _: _snapshot(failed=1)},
    )

    assert report["ok"] is False
    assert report["metrics"]["generation"]["rq_failed"] == 1
    assert report["alerts"][0]["code"] == "queue_health_warning"
    assert report["alerts"][1]["code"] == "rq_failed_exceeded"
    assert "generation" in report["snapshots"]


def test_queue_names_include_test_agent_workflow() -> None:
    assert _queue_names("all") == [
        "generation",
        "test_agent_workflow",
        "test_plan_execution",
    ]
    assert _queue_names("test-agent-workflow") == ["test_agent_workflow"]


def test_main_exits_nonzero_for_error_alert(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        check_queue_alerts,
        "build_alert_report",
        lambda **_: {
            "ok": False,
            "metrics": {},
            "alerts": [
                {
                    "queue": "generation",
                    "severity": "error",
                    "code": "rq_failed_exceeded",
                    "message": "failed",
                }
            ],
        },
    )

    assert main(["--json"]) == 1
    assert "rq_failed_exceeded" in capsys.readouterr().out


def test_main_can_fail_on_warning(monkeypatch) -> None:
    monkeypatch.setattr(
        check_queue_alerts,
        "build_alert_report",
        lambda **_: {
            "ok": True,
            "metrics": {},
            "alerts": [
                {
                    "queue": "generation",
                    "severity": "warning",
                    "code": "queue_health_warning",
                    "message": "warning",
                }
            ],
        },
    )

    assert main([]) == 0
    assert main(["--fail-on-warning"]) == 1


def test_main_writes_output_json(monkeypatch, tmp_path) -> None:
    output_path = tmp_path / "queue-alerts.json"
    monkeypatch.setattr(
        check_queue_alerts,
        "build_alert_report",
        lambda **_: {
            "ok": True,
            "generated_at": "2026-07-13T12:00:00+00:00",
            "metrics": {"generation": {"rq_failed": 0}},
            "alerts": [],
            "snapshots": {},
        },
    )

    assert main(["--json", "--output-json", str(output_path)]) == 0

    content = output_path.read_text(encoding="utf-8")
    assert '"ok": true' in content
    assert '"rq_failed": 0' in content


def _snapshot(
    *,
    active: int = 0,
    queued: int = 0,
    started: int = 0,
    failed: int = 0,
    worker_count: int = 1,
    workers: list[dict] | None = None,
    worker_heartbeat: str = "2026-07-13T11:59:30+00:00",
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    if workers is None:
        workers = (
            [
                {
                    "name": "worker-1",
                    "state": "idle",
                    "queues": ["generation"],
                    "last_heartbeat": worker_heartbeat,
                }
            ]
            if worker_count
            else []
        )
    health_warnings = list(warnings or [])
    if failed and not warnings:
        health_warnings.append(f"RQ failed registry contains {failed} job(s).")
    return {
        "database": {
            "backend": "mysql",
            "jobs_by_status": {"queued": active},
            "active_count": active,
        },
        "queue": {
            "backend": "rq",
            "active": True,
            "name": "generation",
            "queued": queued,
            "started": started,
            "finished": 0,
            "failed": failed,
            "deferred": 0,
            "scheduled": 0,
            "worker_count": worker_count,
            "workers": workers,
        },
        "health": {
            "ok": not errors,
            "errors": errors or [],
            "warnings": health_warnings,
        },
    }
