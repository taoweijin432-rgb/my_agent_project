import json
from pathlib import Path
from typing import Any

from scripts import check_monitoring_metrics


def test_monitoring_metrics_report_passes_with_repo_alert_rules() -> None:
    report = check_monitoring_metrics.build_monitoring_report()

    assert report["ok"] is True
    assert not report["prometheus"]["missing"]
    assert not report["alert_rules"]["missing"]
    assert not report["prometheus_config"]["missing"]
    assert not report["alertmanager_config"]["missing"]
    assert "business stage duration histogram" in report["prometheus"]["present"]
    assert "stage p95 expression" in report["alert_rules"]["present"]
    assert "metrics proxy target" in report["prometheus_config"]["present"]
    assert "critical receiver" in report["alertmanager_config"]["present"]


def test_monitoring_metrics_report_detects_missing_prometheus_series() -> None:
    report = check_monitoring_metrics.build_monitoring_report(
        prometheus_text="ai_testcase_ready 1\n",
        rules_text=_rules_text_with_all_required_alerts(),
        prometheus_config_text=_prometheus_config_text_with_all_required_items(),
        alertmanager_config_text=_alertmanager_config_text_with_all_required_items(),
    )

    assert report["ok"] is False
    assert "LLM call counter" in report["prometheus"]["missing"]
    assert "business stage duration histogram" in report["prometheus"]["missing"]
    assert not report["alert_rules"]["missing"]
    assert not report["prometheus_config"]["missing"]
    assert not report["alertmanager_config"]["missing"]


def test_monitoring_metrics_report_detects_missing_prometheus_config() -> None:
    report = check_monitoring_metrics.build_monitoring_report(
        rules_text=_rules_text_with_all_required_alerts(),
        prometheus_config_text="scrape_configs: []\n",
        alertmanager_config_text=_alertmanager_config_text_with_all_required_items(),
    )

    assert report["ok"] is False
    assert "metrics proxy target" in report["prometheus_config"]["missing"]
    assert "alert rules file" in report["prometheus_config"]["missing"]
    assert not report["alertmanager_config"]["missing"]


def test_monitoring_metrics_main_returns_nonzero_for_missing_alert_rules(
    tmp_path: Path,
    capsys: Any,
) -> None:
    rules_path = tmp_path / "prometheus-alert-rules.yml"
    rules_path.write_text("groups: []\n", encoding="utf-8")

    exit_code = check_monitoring_metrics.main(
        ["--rules-path", str(rules_path), "--json"]
    )

    captured = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert captured["ok"] is False
    assert "service readiness alert" in captured["alert_rules"]["missing"]
    assert not captured["prometheus"]["missing"]
    assert not captured["prometheus_config"]["missing"]
    assert not captured["alertmanager_config"]["missing"]


def _rules_text_with_all_required_alerts() -> str:
    return "\n".join(
        needle for _, needle in check_monitoring_metrics.REQUIRED_ALERT_RULES
    )


def _prometheus_config_text_with_all_required_items() -> str:
    return "\n".join(
        needle for _, needle in check_monitoring_metrics.REQUIRED_PROMETHEUS_CONFIG
    )


def _alertmanager_config_text_with_all_required_items() -> str:
    return "\n".join(
        needle for _, needle in check_monitoring_metrics.REQUIRED_ALERTMANAGER_CONFIG
    )
