import json
from pathlib import Path
from typing import Any

from scripts import check_monitoring_rollout


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_monitoring_rollout_report_passes_for_complete_evidence() -> None:
    report = check_monitoring_rollout.build_rollout_report(
        _complete_evidence(),
        min_observation_hours=24,
    )

    assert report["ok"] is True
    assert report["failed_count"] == 0
    assert {check["name"] for check in report["checks"]} >= {
        "prometheus-target-health",
        "alertmanager-receivers",
        "security-public-metrics-endpoint-exposed",
        "calibration-observation-window-hours",
    }


def test_monitoring_rollout_report_detects_missing_rollout_proof() -> None:
    payload = _complete_evidence()
    payload["prometheus"]["target_health"] = "down"
    payload["alertmanager"]["critical_notification_delivered"] = False
    payload["security"]["public_metrics_endpoint_exposed"] = True
    payload["calibration"]["observation_window_hours"] = 2
    payload["evidence"]["dashboard_url"] = "https://grafana.example.internal/d/demo"

    report = check_monitoring_rollout.build_rollout_report(
        payload,
        min_observation_hours=24,
    )

    failed_names = {
        check["name"] for check in report["checks"] if check["ok"] is False
    }
    assert report["ok"] is False
    assert failed_names >= {
        "prometheus-target-health",
        "alertmanager-critical-notification-delivered",
        "security-public-metrics-endpoint-exposed",
        "calibration-observation-window-hours",
        "evidence-dashboard-url",
    }


def test_monitoring_rollout_main_accepts_template_when_placeholders_allowed(
    capsys: Any,
) -> None:
    template_path = (
        PROJECT_ROOT
        / "docs"
        / "monitoring"
        / "monitoring-rollout-evidence.example.json"
    )

    exit_code = check_monitoring_rollout.main(
        [
            "--evidence-path",
            str(template_path),
            "--allow-placeholder-values",
            "--json",
        ]
    )

    captured = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert captured["ok"] is True


def test_monitoring_rollout_main_rejects_template_without_placeholder_flag(
    capsys: Any,
) -> None:
    template_path = (
        PROJECT_ROOT
        / "docs"
        / "monitoring"
        / "monitoring-rollout-evidence.example.json"
    )

    exit_code = check_monitoring_rollout.main(
        ["--evidence-path", str(template_path), "--json"]
    )

    captured = json.loads(capsys.readouterr().out)
    failed_names = {
        check["name"] for check in captured["checks"] if check["ok"] is False
    }
    assert exit_code == 1
    assert failed_names == {
        "prometheus-url",
        "alertmanager-url",
        "evidence-dashboard-url",
    }


def test_monitoring_rollout_main_reports_missing_evidence_file(capsys: Any) -> None:
    exit_code = check_monitoring_rollout.main(
        ["--evidence-path", "/tmp/missing-monitoring-rollout.json", "--json"]
    )

    captured = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert captured["ok"] is False
    assert captured["checks"][0]["name"] == "evidence-load"


def _complete_evidence() -> dict[str, Any]:
    return {
        "environment": "production",
        "observed_at": "2026-07-20T00:00:00Z",
        "prometheus": {
            "url": "https://prometheus.ops.internal",
            "ready": True,
            "scrape_job": "ai-testcase-generator",
            "target_health": "up",
            "required_alerts_loaded": True,
            "required_metrics_present": True,
        },
        "alertmanager": {
            "url": "https://alertmanager.ops.internal",
            "ready": True,
            "receivers": [
                "ai-testcase-generator-default",
                "ai-testcase-generator-critical",
                "ai-testcase-generator-warning",
            ],
            "critical_notification_delivered": True,
            "warning_notification_delivered": True,
            "resolved_notification_delivered": True,
        },
        "security": {
            "metrics_endpoint_requires_api_key": True,
            "prometheus_scrapes_metrics_proxy": True,
            "metrics_proxy_injects_api_key": True,
            "public_metrics_endpoint_exposed": False,
            "secret_values_committed": False,
        },
        "calibration": {
            "observation_window_hours": 24,
            "queue_thresholds_reviewed": True,
            "llm_thresholds_reviewed": True,
            "http_5xx_threshold_reviewed": True,
            "no_unresolved_critical_alerts": True,
        },
        "evidence": {
            "monitoring_stack_smoke_ok": True,
            "queue_alert_sample_summary_path": (
                "data/ops-drills/queue-alert-summary-20260720-prod.json"
            ),
            "dashboard_url": "https://grafana.ops.internal/d/ai-testcase-generator",
            "notification_drill_reference": "OPS-123",
        },
    }
