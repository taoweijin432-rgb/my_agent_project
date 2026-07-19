import json
from importlib import import_module

from scripts.check_queue_alerts import QueueAlertThresholds
from scripts.collect_service_mode_calibration import (
    build_load_summary,
    collect_service_mode_calibration,
    main,
)


calibration_module = import_module("scripts.collect_service_mode_calibration")


def test_collect_service_mode_calibration_writes_samples_and_summary(tmp_path) -> None:
    output_jsonl = tmp_path / "calibration.jsonl"
    calls: list[dict] = []

    def run_load(**kwargs):
        calls.append(kwargs)
        return _load_summary(
            job_id=f"job-{len(calls)}",
            queued=len(calls),
            started=1 if len(calls) == 2 else 0,
        )

    slept: list[float] = []
    summary = collect_service_mode_calibration(
        output_jsonl=output_jsonl,
        api_url="http://api",
        api_key="key",
        sample_count=2,
        interval_seconds=0.5,
        jobs_per_sample=1,
        description="人工确认",
        poll_interval_seconds=0.01,
        job_timeout_seconds=1,
        queue_thresholds=QueueAlertThresholds(require_worker=True),
        fail_on_warning=False,
        headroom_ratio=0.25,
        minimum_headroom=1,
        load_runner=run_load,
        sleep=slept.append,
    )

    lines = output_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["sample_index"] == 1
    assert calls[0]["rounds"] == 1
    assert calls[0]["jobs_per_round"] == 1
    assert calls[0]["queue_alert_check"] is True
    assert calls[0]["sample_queue_after_submit"] is True
    assert slept == [0.5]
    assert summary["ok"] is True
    assert summary["load_summary"]["job_count"] == 2
    assert summary["load_summary"]["jobs_by_status"] == {"succeeded": 2}
    assert (
        summary["queue_summary"]["observed_metrics"]["test_agent_workflow"]["max"][
            "rq_queued"
        ]
        == 2
    )
    assert summary["queue_summary"]["candidate_thresholds"]["test_agent_workflow"][
        "max_rq_queued"
    ] == 3


def test_collect_service_mode_calibration_fails_when_load_fails(tmp_path) -> None:
    summary = collect_service_mode_calibration(
        output_jsonl=tmp_path / "calibration.jsonl",
        api_url="http://api",
        api_key="key",
        sample_count=1,
        interval_seconds=0,
        jobs_per_sample=1,
        description="人工确认",
        poll_interval_seconds=0.01,
        job_timeout_seconds=1,
        queue_thresholds=QueueAlertThresholds(),
        fail_on_warning=False,
        headroom_ratio=0.25,
        minimum_headroom=1,
        load_runner=lambda **_: _load_summary(
            job_id="failed-job",
            ok=False,
            status="failed",
            failures=["boom"],
        ),
        sleep=lambda _: None,
    )

    assert summary["ok"] is False
    assert summary["load_summary"]["failures"] == ["sample 1: boom"]


def test_build_load_summary_aggregates_timings() -> None:
    summary = build_load_summary(
        [
            _load_summary(job_id="job-1", queue_wait_ms=10),
            _load_summary(job_id="job-2", queue_wait_ms=30),
        ]
    )

    assert summary["job_count"] == 2
    assert summary["timing_summary_ms"]["queue_wait_ms"] == {
        "avg": 20.0,
        "max": 30.0,
        "min": 10.0,
    }
    assert summary["throughput_jobs_per_second"] == {
        "avg": 1.0,
        "max": 1.0,
        "min": 1.0,
    }


def test_main_writes_summary_json(monkeypatch, tmp_path, capsys) -> None:
    output_jsonl = tmp_path / "calibration.jsonl"
    output_summary = tmp_path / "calibration-summary.json"

    monkeypatch.setattr(
        calibration_module,
        "_default_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        calibration_module,
        "run_workflow_load_smoke",
        lambda **_: _load_summary(job_id="job-1"),
    )

    exit_code = main(
        [
            "--samples",
            "1",
            "--interval-seconds",
            "0",
            "--jobs-per-sample",
            "1",
            "--output-jsonl",
            str(output_jsonl),
            "--output-summary-json",
            str(output_summary),
            "--json",
        ]
    )

    assert exit_code == 0
    assert output_jsonl.exists()
    assert json.loads(output_summary.read_text(encoding="utf-8"))["ok"] is True
    assert '"ok": true' in capsys.readouterr().out


def _load_summary(
    *,
    job_id: str,
    ok: bool = True,
    status: str = "succeeded",
    queued: int = 0,
    started: int = 0,
    queue_wait_ms: float = 10,
    failures: list[str] | None = None,
) -> dict:
    return {
        "ok": ok,
        "job_count": 1,
        "jobs_by_status": {status: 1},
        "report_status_counts": {"incomplete": 1},
        "throughput": {"elapsed_seconds": 1.0, "jobs_per_second": 1.0},
        "timing_summary_ms": {},
        "failures": failures or [],
        "jobs": [
            {
                "id": job_id,
                "status": status,
                "report_status": "incomplete",
                "timing": {
                    "queue_wait_ms": queue_wait_ms,
                    "job_runtime_ms": 20,
                    "job_total_ms": queue_wait_ms + 20,
                    "workflow_total_ms": 15,
                    "plan_generation_ms": 5,
                    "tool_execution_ms": 5,
                    "report_build_ms": 5,
                },
            }
        ],
        "queue_alert_reports": [
            {
                "ok": True,
                "generated_at": "2026-07-19T00:00:00+00:00",
                "thresholds": {},
                "metrics": {
                    "test_agent_workflow": {
                        "database_backend": "mysql",
                        "configured_database_backend": "mysql",
                        "database_active_jobs": 0,
                        "rq_backend": "rq",
                        "rq_active": 1,
                        "rq_queued": queued,
                        "rq_started": started,
                        "rq_deferred": 0,
                        "rq_scheduled": 0,
                        "rq_failed": 0,
                        "rq_finished": 1,
                        "worker_count": 2,
                    }
                },
                "alerts": [],
                "snapshots": {},
            }
        ],
    }
