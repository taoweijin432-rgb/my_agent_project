import json

from scripts import collect_queue_alert_samples
from scripts.collect_queue_alert_samples import (
    build_sample_summary,
    collect_alert_samples,
    main,
)
from scripts.check_queue_alerts import QueueAlertThresholds


def test_collect_alert_samples_writes_jsonl_and_summarizes_thresholds(tmp_path) -> None:
    output_jsonl = tmp_path / "queue-alert-samples.jsonl"
    calls: list[dict] = []
    reports = [
        _report(queued=2, started=1, active=3),
        _report(
            queued=4,
            started=0,
            active=5,
            alerts=[
                {
                    "queue": "generation",
                    "severity": "error",
                    "code": "rq_queued_exceeded",
                    "message": "queued",
                }
            ],
        ),
    ]

    def build_report(**kwargs):
        calls.append(kwargs)
        return reports[len(calls) - 1]

    slept: list[float] = []
    summary = collect_alert_samples(
        output_jsonl=output_jsonl,
        sample_count=2,
        interval_seconds=0.5,
        thresholds=QueueAlertThresholds(max_rq_queued=3),
        queue_names=["generation"],
        fail_on_warning=False,
        headroom_ratio=0.25,
        minimum_headroom=1,
        report_builder=build_report,
        sleep=slept.append,
    )

    lines = output_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["sample_index"] == 1
    assert calls[0]["queue_names"] == ["generation"]
    assert slept == [0.5]
    assert summary["ok"] is False
    assert summary["observed_metrics"]["generation"]["max"]["rq_queued"] == 4
    assert summary["observed_metrics"]["generation"]["max"]["database_active_jobs"] == 5
    assert summary["candidate_thresholds"]["generation"]["max_rq_queued"] == 5
    assert summary["candidate_thresholds"]["generation"]["max_active_jobs"] == 7
    assert summary["alert_counts"]["by_code"] == {"rq_queued_exceeded": 1}


def test_build_sample_summary_can_fail_on_warning() -> None:
    summary = build_sample_summary(
        [
            _report(
                alerts=[
                    {
                        "queue": "generation",
                        "severity": "warning",
                        "code": "queue_health_warning",
                        "message": "warning",
                    }
                ]
            )
        ],
        fail_on_warning=True,
    )

    assert summary["ok"] is False
    assert summary["alert_counts"]["by_severity"] == {"warning": 1}


def test_main_writes_summary_json(monkeypatch, tmp_path, capsys) -> None:
    output_jsonl = tmp_path / "samples.jsonl"
    output_summary = tmp_path / "summary.json"
    reports = [_report()]

    def build_report(**_):
        return reports.pop(0)

    monkeypatch.setattr(
        collect_queue_alert_samples.check_queue_alerts,
        "build_alert_report",
        build_report,
    )

    exit_code = main(
        [
            "--samples",
            "1",
            "--interval-seconds",
            "0",
            "--output-jsonl",
            str(output_jsonl),
            "--output-summary-json",
            str(output_summary),
            "--json",
        ]
    )

    assert exit_code == 0
    assert output_jsonl.exists()
    assert output_summary.exists()
    assert '"ok": true' in capsys.readouterr().out


def _report(
    *,
    queued: int = 0,
    started: int = 0,
    active: int = 0,
    failed: int = 0,
    worker_count: int = 1,
    alerts: list[dict] | None = None,
) -> dict:
    return {
        "ok": not alerts,
        "generated_at": "2026-07-18T04:00:00+00:00",
        "thresholds": {},
        "metrics": {
            "generation": {
                "database_backend": "mysql",
                "configured_database_backend": "mysql",
                "database_active_jobs": active,
                "rq_backend": "rq",
                "rq_active": 1,
                "rq_queued": queued,
                "rq_started": started,
                "rq_deferred": 0,
                "rq_scheduled": 0,
                "rq_failed": failed,
                "rq_finished": 0,
                "worker_count": worker_count,
            }
        },
        "alerts": alerts or [],
        "snapshots": {},
    }
