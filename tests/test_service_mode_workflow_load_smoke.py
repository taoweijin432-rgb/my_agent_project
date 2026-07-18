import json

from scripts import smoke_service_mode_workflow_load
from scripts.check_queue_alerts import QueueAlertThresholds
from scripts.smoke_service_mode_workflow_load import (
    main,
    run_workflow_load_smoke,
)


def test_run_workflow_load_smoke_summarizes_success() -> None:
    submitted_ids: list[str] = []

    def submit_job(*_, **__):
        job_id = f"job-{len(submitted_ids) + 1}"
        submitted_ids.append(job_id)
        return {"id": job_id, "status": "queued"}

    def get_job(_api_url, _api_key, job_id, _timeout_seconds):
        return _job(job_id, queue_wait_ms=10 + len(submitted_ids))

    summary = run_workflow_load_smoke(
        api_url="http://api",
        api_key="key",
        rounds=2,
        jobs_per_round=2,
        description="人工确认",
        poll_interval_seconds=0.01,
        job_timeout_seconds=1,
        round_delay_seconds=0,
        queue_thresholds=QueueAlertThresholds(require_worker=True),
        queue_alert_check=True,
        submit_job=submit_job,
        get_job=get_job,
        queue_report_builder=lambda **_: {"ok": True, "alerts": [], "metrics": {}},
    )

    assert summary["ok"] is True
    assert summary["job_count"] == 4
    assert summary["jobs_by_status"] == {"succeeded": 4}
    assert summary["report_status_counts"] == {"incomplete": 4}
    assert summary["queue_alert_reports"] == [
        {"ok": True, "alerts": [], "metrics": {}},
        {"ok": True, "alerts": [], "metrics": {}},
    ]
    assert summary["timing_summary_ms"]["job_total_ms"]["max"] == 100


def test_run_workflow_load_smoke_fails_latency_gate() -> None:
    summary = run_workflow_load_smoke(
        api_url="http://api",
        api_key="key",
        rounds=1,
        jobs_per_round=1,
        description="人工确认",
        poll_interval_seconds=0.01,
        job_timeout_seconds=1,
        round_delay_seconds=0,
        queue_thresholds=QueueAlertThresholds(),
        queue_alert_check=False,
        fail_over_max_queue_wait_ms=5,
        submit_job=lambda *_, **__: {"id": "job-1", "status": "queued"},
        get_job=lambda *_, **__: _job("job-1", queue_wait_ms=10),
    )

    assert summary["ok"] is False
    assert "queue_wait_ms" in summary["failures"][0]


def test_main_writes_output_json(monkeypatch, tmp_path, capsys) -> None:
    output_path = tmp_path / "service-mode-smoke.json"

    monkeypatch.setattr(
        smoke_service_mode_workflow_load,
        "_default_api_key",
        lambda: "key",
    )
    monkeypatch.setattr(
        smoke_service_mode_workflow_load,
        "run_workflow_load_smoke",
        lambda **_: {
            "ok": True,
            "job_count": 1,
            "jobs_by_status": {"succeeded": 1},
            "report_status_counts": {"incomplete": 1},
            "throughput": {"jobs_per_second": 1.0},
            "timing_summary_ms": {},
            "failures": [],
        },
    )

    exit_code = main(["--output-json", str(output_path), "--json"])

    assert exit_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["ok"] is True
    assert '"job_count": 1' in capsys.readouterr().out


def _job(job_id: str, *, queue_wait_ms: float) -> dict:
    return {
        "id": job_id,
        "status": "succeeded",
        "result": {
            "report": {
                "status": "incomplete",
            }
        },
        "timing": {
            "queue_wait_ms": queue_wait_ms,
            "job_runtime_ms": 20,
            "job_total_ms": 100,
            "workflow_total_ms": 15,
            "plan_generation_ms": 5,
            "tool_execution_ms": 5,
            "report_build_ms": 5,
        },
    }
