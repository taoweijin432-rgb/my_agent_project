import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any


DEFAULT_REQUIRED_ALERTS = (
    "AITestcaseServiceNotReady",
    "AITestcaseReadinessCheckError",
    "AITestcaseQueuedJobsBacklog",
    "AITestcaseRQFailedRegistryNotEmpty",
    "AITestcaseRQNoWorkerForActiveJobs",
    "AITestcaseHTTP5xxRateHigh",
)
DEFAULT_REQUIRED_METRICS = (
    "ai_testcase_ready",
    "ai_testcase_readiness_check_status",
    "ai_testcase_job_count",
    "ai_testcase_rq_worker_count",
    "ai_testcase_http_requests_total",
)


@dataclass(frozen=True)
class SmokeCheck:
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


def run_monitoring_stack_smoke(
    *,
    prometheus_url: str,
    alertmanager_url: str,
    job_name: str,
    required_alerts: list[str],
    required_metrics: list[str],
    timeout_seconds: float,
    interval_seconds: float,
    fetch_json: Callable[[str], dict[str, Any]] = None,
    fetch_text: Callable[[str], str] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    json_fetcher = fetch_json or _fetch_json
    text_fetcher = fetch_text or _fetch_text
    checks: list[SmokeCheck] = [
        _check_text_ready(
            "prometheus-ready",
            _join_url(prometheus_url, "/-/ready"),
            text_fetcher,
        ),
        _check_text_ready(
            "alertmanager-ready",
            _join_url(alertmanager_url, "/-/ready"),
            text_fetcher,
        ),
    ]
    checks.append(
        _wait_for_check(
            name="prometheus-target-up",
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            sleep=sleep,
            check=lambda: evaluate_prometheus_targets(
                json_fetcher(_join_url(prometheus_url, "/api/v1/targets")),
                job_name=job_name,
            ),
        )
    )
    checks.append(
        _wait_for_check(
            name="prometheus-rules-loaded",
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            sleep=sleep,
            check=lambda: evaluate_prometheus_rules(
                json_fetcher(_join_url(prometheus_url, "/api/v1/rules")),
                required_alerts=required_alerts,
            ),
        )
    )
    checks.append(
        _wait_for_check(
            name="prometheus-metrics-present",
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            sleep=sleep,
            check=lambda: evaluate_metric_names(
                json_fetcher(
                    _join_url(prometheus_url, "/api/v1/label/__name__/values")
                ),
                required_metrics=required_metrics,
            ),
        )
    )
    return build_summary(checks)


def evaluate_prometheus_targets(
    payload: dict[str, Any],
    *,
    job_name: str,
) -> SmokeCheck:
    targets = (payload.get("data") or {}).get("activeTargets") or []
    matched = [
        target
        for target in targets
        if (target.get("labels") or {}).get("job") == job_name
    ]
    up_targets = [target for target in matched if target.get("health") == "up"]
    if up_targets:
        return SmokeCheck(
            name="prometheus-target-up",
            ok=True,
            detail=f"{len(up_targets)} target(s) are up for job {job_name}",
            data={"matched": len(matched), "up": len(up_targets)},
        )
    return SmokeCheck(
        name="prometheus-target-up",
        ok=False,
        detail=f"no up targets found for job {job_name}",
        data={"matched": len(matched), "up": 0},
    )


def evaluate_prometheus_rules(
    payload: dict[str, Any],
    *,
    required_alerts: list[str],
) -> SmokeCheck:
    groups = (payload.get("data") or {}).get("groups") or []
    alert_names = {
        rule.get("name")
        for group in groups
        for rule in group.get("rules") or []
        if rule.get("type") == "alerting"
    }
    missing = sorted(set(required_alerts) - alert_names)
    return SmokeCheck(
        name="prometheus-rules-loaded",
        ok=not missing,
        detail=(
            "required alert rules are loaded"
            if not missing
            else f"missing alert rules: {', '.join(missing)}"
        ),
        data={"missing": missing, "loaded_alert_count": len(alert_names)},
    )


def evaluate_metric_names(
    payload: dict[str, Any],
    *,
    required_metrics: list[str],
) -> SmokeCheck:
    metric_names = set(payload.get("data") or [])
    missing = sorted(set(required_metrics) - metric_names)
    return SmokeCheck(
        name="prometheus-metrics-present",
        ok=not missing,
        detail=(
            "required metrics are present"
            if not missing
            else f"missing metrics: {', '.join(missing)}"
        ),
        data={"missing": missing, "metric_count": len(metric_names)},
    )


def build_summary(checks: list[SmokeCheck]) -> dict[str, Any]:
    return {
        "ok": all(check.ok for check in checks),
        "checks": [asdict(check) for check in checks],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_monitoring_stack_smoke(
        prometheus_url=args.prometheus_url,
        alertmanager_url=args.alertmanager_url,
        job_name=args.job_name,
        required_alerts=args.required_alert,
        required_metrics=args.required_metric,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=args.interval_seconds,
    )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(summary)
    return 0 if summary["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test the local Prometheus/Alertmanager monitoring stack.",
    )
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:9090")
    parser.add_argument("--alertmanager-url", default="http://127.0.0.1:9093")
    parser.add_argument("--job-name", default="ai-testcase-generator")
    parser.add_argument(
        "--required-alert",
        action="append",
        default=list(DEFAULT_REQUIRED_ALERTS),
    )
    parser.add_argument(
        "--required-metric",
        action="append",
        default=list(DEFAULT_REQUIRED_METRICS),
    )
    parser.add_argument("--timeout-seconds", type=float, default=90)
    parser.add_argument("--interval-seconds", type=float, default=2)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def print_text(summary: dict[str, Any]) -> None:
    print("Monitoring stack smoke")
    print(f"ok: {str(summary['ok']).lower()}")
    for check in summary["checks"]:
        status = "ok" if check["ok"] else "failed"
        print(f"  {check['name']}: {status} - {check['detail']}")


def _wait_for_check(
    *,
    name: str,
    timeout_seconds: float,
    interval_seconds: float,
    sleep: Callable[[float], None],
    check: Callable[[], SmokeCheck],
) -> SmokeCheck:
    deadline = time.time() + timeout_seconds
    while True:
        try:
            current = check()
        except Exception as exc:
            current = SmokeCheck(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}")
        if current.ok or time.time() >= deadline:
            return current
        sleep(interval_seconds)


def _check_text_ready(
    name: str,
    url: str,
    fetch_text: Callable[[str], str],
) -> SmokeCheck:
    try:
        text = fetch_text(url)
    except Exception as exc:
        return SmokeCheck(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}")
    return SmokeCheck(name=name, ok=True, detail=text.strip() or "ready")


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"Accept": "text/plain"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8", errors="replace")


def _join_url(base_url: str, path: str) -> str:
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


if __name__ == "__main__":
    raise SystemExit(main())
