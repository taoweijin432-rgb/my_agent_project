import urllib.request

from scripts.run_metrics_proxy import fetch_metrics
from scripts.smoke_monitoring_stack import (
    build_summary,
    evaluate_metric_names,
    evaluate_prometheus_rules,
    evaluate_prometheus_targets,
    run_monitoring_stack_smoke,
)


def test_evaluate_prometheus_targets_requires_up_job_target() -> None:
    payload = {
        "data": {
            "activeTargets": [
                {
                    "health": "down",
                    "labels": {"job": "ai-testcase-generator"},
                },
                {
                    "health": "up",
                    "labels": {"job": "other"},
                },
            ]
        }
    }

    check = evaluate_prometheus_targets(payload, job_name="ai-testcase-generator")

    assert check.ok is False
    assert check.data == {"matched": 1, "up": 0}


def test_evaluate_prometheus_rules_checks_required_alerts() -> None:
    payload = {
        "data": {
            "groups": [
                {
                    "rules": [
                        {"type": "alerting", "name": "AITestcaseServiceNotReady"},
                        {"type": "recording", "name": "ignored"},
                    ]
                }
            ]
        }
    }

    check = evaluate_prometheus_rules(
        payload,
        required_alerts=[
            "AITestcaseServiceNotReady",
            "AITestcaseRQNoWorkerForActiveJobs",
        ],
    )

    assert check.ok is False
    assert check.data == {
        "missing": ["AITestcaseRQNoWorkerForActiveJobs"],
        "loaded_alert_count": 1,
    }


def test_evaluate_metric_names_checks_required_metrics() -> None:
    check = evaluate_metric_names(
        {"data": ["ai_testcase_ready", "ai_testcase_job_count"]},
        required_metrics=["ai_testcase_ready", "ai_testcase_job_count"],
    )

    assert check.ok is True
    assert check.data == {"missing": [], "metric_count": 2}


def test_run_monitoring_stack_smoke_builds_success_summary() -> None:
    def fetch_text(url: str) -> str:
        assert url.endswith("/-/ready")
        return "ready"

    def fetch_json(url: str) -> dict:
        if url.endswith("/api/v1/targets"):
            return {
                "data": {
                    "activeTargets": [
                        {
                            "health": "up",
                            "labels": {"job": "ai-testcase-generator"},
                        }
                    ]
                }
            }
        if url.endswith("/api/v1/rules"):
            return {
                "data": {
                    "groups": [
                        {
                            "rules": [
                                {
                                    "type": "alerting",
                                    "name": "AITestcaseServiceNotReady",
                                }
                            ]
                        }
                    ]
                }
            }
        return {"data": ["ai_testcase_ready"]}

    summary = run_monitoring_stack_smoke(
        prometheus_url="http://prometheus",
        alertmanager_url="http://alertmanager",
        job_name="ai-testcase-generator",
        required_alerts=["AITestcaseServiceNotReady"],
        required_metrics=["ai_testcase_ready"],
        timeout_seconds=0,
        interval_seconds=0,
        fetch_json=fetch_json,
        fetch_text=fetch_text,
        sleep=lambda _: None,
    )

    assert summary["ok"] is True
    assert [check["name"] for check in summary["checks"]] == [
        "prometheus-ready",
        "alertmanager-ready",
        "prometheus-target-up",
        "prometheus-rules-loaded",
        "prometheus-metrics-present",
    ]


def test_fetch_metrics_injects_api_key(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return b"ai_testcase_ready 1\n"

    captured: dict[str, urllib.request.Request] = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    payload = fetch_metrics(
        upstream_url="http://api/metrics",
        api_key="service-key",
        timeout_seconds=3,
    )

    assert payload == b"ai_testcase_ready 1\n"
    assert captured["timeout"] == 3
    assert captured["request"].headers["X-api-key"] == "service-key"


def test_build_summary_fails_when_any_check_fails() -> None:
    summary = build_summary(
        [
            evaluate_metric_names({"data": ["a"]}, required_metrics=["a"]),
            evaluate_metric_names({"data": []}, required_metrics=["a"]),
        ]
    )

    assert summary["ok"] is False
