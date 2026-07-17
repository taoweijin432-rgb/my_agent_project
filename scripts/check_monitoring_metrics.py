import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.metrics import format_prometheus_metrics


DEFAULT_ALERT_RULES_PATH = (
    PROJECT_ROOT / "docs" / "monitoring" / "prometheus-alert-rules.yml"
)
DEFAULT_PROMETHEUS_CONFIG_PATH = (
    PROJECT_ROOT / "docs" / "monitoring" / "prometheus-scrape-example.yml"
)
DEFAULT_ALERTMANAGER_CONFIG_PATH = (
    PROJECT_ROOT / "docs" / "monitoring" / "alertmanager-route-example.yml"
)
REQUIRED_PROMETHEUS_SERIES = (
    ("readiness gauge", "ai_testcase_ready 1"),
    ("readiness check status", "ai_testcase_readiness_check_status"),
    ("LLM call counter", "ai_testcase_llm_call_total"),
    ("LLM attempt counter", "ai_testcase_llm_attempt_total"),
    ("LLM retry counter", "ai_testcase_llm_retry_total"),
    ("LLM duration histogram", "ai_testcase_llm_call_duration_seconds_bucket"),
    ("business stage counter", "ai_testcase_stage_total"),
    ("business stage duration histogram", "ai_testcase_stage_duration_seconds_bucket"),
    ("job count gauge", "ai_testcase_job_count"),
    ("job active count gauge", "ai_testcase_job_active_count"),
    ("generation history count gauge", "ai_testcase_generation_record_count"),
    ("generation gate count gauge", "ai_testcase_generation_gate_count"),
    ("generation usage token gauge", "ai_testcase_generation_usage_tokens"),
    ("generation cost gauge", "ai_testcase_generation_estimated_cost"),
    ("RQ registry gauge", "ai_testcase_rq_registry_jobs"),
    ("RQ worker gauge", "ai_testcase_rq_worker_count"),
    ("HTTP request counter", "ai_testcase_http_requests_total"),
    ("HTTP duration histogram", "ai_testcase_http_request_duration_seconds_bucket"),
)
REQUIRED_ALERT_RULES = (
    ("service readiness alert", "AITestcaseServiceNotReady"),
    ("readiness expression", "ai_testcase_ready == 0"),
    ("LLM failure alert", "AITestcaseLLMCallFailuresObserved"),
    ("LLM failure expression", 'ai_testcase_llm_call_total{status="failed"}'),
    ("stage failure alert", "AITestcaseStageFailuresObserved"),
    (
        "stage failure expression",
        'ai_testcase_stage_total{status=~"failed|blocked"}',
    ),
    ("stage p95 alert", "AITestcaseStageP95LatencyHigh"),
    ("stage p95 expression", "histogram_quantile(0.95"),
    ("stage duration bucket", "ai_testcase_stage_duration_seconds_bucket"),
    ("job backlog alert", "AITestcaseQueuedJobsBacklog"),
    ("generation failure alert", "AITestcaseGenerationFailuresObserved"),
    ("generation gate alert", "AITestcaseGenerationGatePending"),
    ("RQ failed registry alert", "AITestcaseRQFailedRegistryNotEmpty"),
    ("RQ no worker alert", "AITestcaseRQNoWorkerForActiveJobs"),
    ("HTTP 5xx alert", "AITestcaseHTTP5xxRateHigh"),
)
REQUIRED_PROMETHEUS_CONFIG = (
    ("scrape job", "job_name: ai-testcase-generator"),
    ("metrics proxy target", "ai-testcase-metrics-proxy:9100"),
    ("proxy metrics path", "metrics_path: /metrics"),
    ("alert rules file", "prometheus-alert-rules.yml"),
    ("alertmanager target", "alertmanager:9093"),
    ("service label", "service: ai-testcase-generator"),
    ("environment label", "environment: staging"),
)
REQUIRED_ALERTMANAGER_CONFIG = (
    ("default receiver", "ai-testcase-generator-default"),
    ("critical receiver", "ai-testcase-generator-critical"),
    ("warning receiver", "ai-testcase-generator-warning"),
    ("critical matcher", 'severity="critical"'),
    ("warning matcher", 'severity="warning"'),
    ("service not ready inhibition", 'alertname="AITestcaseServiceNotReady"'),
    ("service grouping", "service"),
    ("environment grouping", "environment"),
)


def build_monitoring_report(
    *,
    rules_path: Path = DEFAULT_ALERT_RULES_PATH,
    prometheus_config_path: Path = DEFAULT_PROMETHEUS_CONFIG_PATH,
    alertmanager_config_path: Path = DEFAULT_ALERTMANAGER_CONFIG_PATH,
    prometheus_text: str | None = None,
    rules_text: str | None = None,
    prometheus_config_text: str | None = None,
    alertmanager_config_text: str | None = None,
) -> dict[str, Any]:
    rendered_prometheus = prometheus_text or format_prometheus_metrics(
        build_synthetic_snapshot()
    )
    rendered_rules = (
        rules_text
        if rules_text is not None
        else rules_path.read_text(encoding="utf-8")
    )
    rendered_prometheus_config = (
        prometheus_config_text
        if prometheus_config_text is not None
        else prometheus_config_path.read_text(encoding="utf-8")
    )
    rendered_alertmanager_config = (
        alertmanager_config_text
        if alertmanager_config_text is not None
        else alertmanager_config_path.read_text(encoding="utf-8")
    )
    metrics = _evaluate_requirements(
        rendered_prometheus,
        REQUIRED_PROMETHEUS_SERIES,
    )
    alert_rules = _evaluate_requirements(rendered_rules, REQUIRED_ALERT_RULES)
    prometheus_config = _evaluate_requirements(
        rendered_prometheus_config,
        REQUIRED_PROMETHEUS_CONFIG,
    )
    alertmanager_config = _evaluate_requirements(
        rendered_alertmanager_config,
        REQUIRED_ALERTMANAGER_CONFIG,
    )
    return {
        "ok": (
            not metrics["missing"]
            and not alert_rules["missing"]
            and not prometheus_config["missing"]
            and not alertmanager_config["missing"]
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prometheus": {
            "line_count": _content_line_count(rendered_prometheus),
            **metrics,
        },
        "alert_rules": {
            "path": str(rules_path),
            **alert_rules,
        },
        "prometheus_config": {
            "path": str(prometheus_config_path),
            **prometheus_config,
        },
        "alertmanager_config": {
            "path": str(alertmanager_config_path),
            **alertmanager_config,
        },
    }


def build_synthetic_snapshot() -> dict[str, Any]:
    return {
        "ready": True,
        "llm": {
            "configured": True,
            "model": "glm-4-flash",
            "timeout_seconds": 60,
            "max_retries": 2,
            "runtime": {
                "calls": [
                    {
                        "model": "glm-4-flash",
                        "status": "succeeded",
                        "error_code": "none",
                        "count": 3,
                        "retry_count": 1,
                        "duration_seconds": {
                            "sum": 1.25,
                            "buckets": {
                                "0.5": 2,
                                "1": 3,
                                "+Inf": 3,
                            },
                        },
                    }
                ],
                "attempts": [
                    {
                        "model": "glm-4-flash",
                        "status": "succeeded",
                        "error_code": "none",
                        "count": 4,
                    }
                ],
            },
        },
        "stages": {
            "total_count": 2,
            "stages": [
                {
                    "workflow": "test_agent_workflow",
                    "stage": "plan_generation",
                    "status": "succeeded",
                    "count": 1,
                    "duration_seconds": {
                        "sum": 0.42,
                        "buckets": {
                            "0.5": 1,
                            "+Inf": 1,
                        },
                    },
                },
                {
                    "workflow": "test_agent_workflow",
                    "stage": "tool_execution",
                    "status": "failed",
                    "count": 1,
                    "duration_seconds": {
                        "sum": 2.1,
                        "buckets": {
                            "5": 1,
                            "+Inf": 1,
                        },
                    },
                },
            ],
        },
        "jobs": {
            "generation": {
                "active_count": 1,
                "by_status": {
                    "queued": 1,
                    "running": 0,
                    "succeeded": 2,
                    "failed": 0,
                },
            },
            "test_plan_execution": {
                "active_count": 0,
                "by_status": {
                    "queued": 0,
                    "running": 0,
                    "succeeded": 1,
                    "failed": 0,
                },
            },
            "test_agent_workflow": {
                "active_count": 0,
                "by_status": {
                    "queued": 0,
                    "running": 0,
                    "succeeded": 1,
                    "failed": 0,
                },
            },
        },
        "history": {
            "generation_records": {
                "total_count": 3,
                "by_status": {
                    "success": 2,
                    "failed": 1,
                },
            },
            "generation_gates": {
                "total_count": 2,
                "pending_count": 1,
                "by_status": {
                    "pending": 1,
                    "approved": 1,
                    "rejected": 0,
                },
            },
            "usage": {
                "tokens": [
                    {
                        "status": "success",
                        "token_type": "total_tokens_estimate",
                        "value": 1200,
                    }
                ],
                "estimated_cost": [
                    {
                        "status": "success",
                        "currency": "CNY",
                        "value": 0.12,
                    }
                ],
            },
        },
        "queue": {
            "backend": "rq",
            "active": True,
            "worker_count": 1,
            "registries": {
                "queued": 1,
                "started": 0,
                "deferred": 0,
                "scheduled": 0,
                "failed": 0,
                "finished": 2,
            },
        },
        "readiness": {
            "checks": [
                {
                    "name": "configuration",
                    "status": "ok",
                },
                {
                    "name": "database",
                    "status": "ok",
                },
            ],
        },
        "http": {
            "requests": [
                {
                    "method": "GET",
                    "route": "/health",
                    "status_code": 200,
                    "status_class": "2xx",
                    "count": 5,
                    "duration_seconds": {
                        "sum": 0.24,
                        "buckets": {
                            "0.025": 3,
                            "0.1": 5,
                            "+Inf": 5,
                        },
                    },
                }
            ],
        },
    }


def print_text(report: Mapping[str, Any]) -> None:
    print("Monitoring metrics report")
    print(f"ok: {str(report['ok']).lower()}")
    _print_section("Prometheus series", report["prometheus"])
    _print_section("Alert rules", report["alert_rules"])
    _print_section("Prometheus config", report["prometheus_config"])
    _print_section("Alertmanager config", report["alertmanager_config"])


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_monitoring_report(
        rules_path=args.rules_path,
        prometheus_config_path=args.prometheus_config_path,
        alertmanager_config_path=args.alertmanager_config_path,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(report)
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate local Prometheus metrics output and alert rules coverage.",
    )
    parser.add_argument(
        "--rules-path",
        type=Path,
        default=DEFAULT_ALERT_RULES_PATH,
        help="Prometheus alert rules template to validate.",
    )
    parser.add_argument(
        "--prometheus-config-path",
        type=Path,
        default=DEFAULT_PROMETHEUS_CONFIG_PATH,
        help="Prometheus scrape/rule/alerting example config to validate.",
    )
    parser.add_argument(
        "--alertmanager-config-path",
        type=Path,
        default=DEFAULT_ALERTMANAGER_CONFIG_PATH,
        help="Alertmanager routing example config to validate.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def _evaluate_requirements(
    content: str,
    requirements: tuple[tuple[str, str], ...],
) -> dict[str, list[str]]:
    present = [name for name, needle in requirements if needle in content]
    missing = [name for name, needle in requirements if needle not in content]
    return {
        "present": present,
        "missing": missing,
    }


def _content_line_count(content: str) -> int:
    return sum(1 for line in content.splitlines() if line.strip())


def _print_section(title: str, section: Any) -> None:
    print(title)
    for item in section.get("present", []):
        print(f"  present: {item}")
    missing = section.get("missing") or []
    if not missing:
        print("  missing: none")
        return
    for item in missing:
        print(f"  missing: {item}")


if __name__ == "__main__":
    raise SystemExit(main())
