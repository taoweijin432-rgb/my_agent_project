import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_PATH = (
    PROJECT_ROOT / "data" / "ops-drills" / "monitoring-rollout-evidence.json"
)
REQUIRED_ALERTMANAGER_RECEIVERS = (
    "ai-testcase-generator-default",
    "ai-testcase-generator-critical",
    "ai-testcase-generator-warning",
)
PLACEHOLDER_MARKERS = (
    "example.",
    "example-",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "placeholder",
    "replace-",
    "todo",
    "your-",
)


@dataclass(frozen=True)
class RolloutCheck:
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


def build_rollout_report(
    payload: dict[str, Any],
    *,
    min_observation_hours: float,
    allow_placeholder_values: bool = False,
) -> dict[str, Any]:
    checks = [
        _check_environment(payload),
        _check_observed_at(payload),
        _check_url(
            payload,
            "prometheus.url",
            allow_placeholder_values=allow_placeholder_values,
        ),
        _check_bool(payload, "prometheus.ready", True),
        _check_exact(payload, "prometheus.scrape_job", "ai-testcase-generator"),
        _check_exact(payload, "prometheus.target_health", "up"),
        _check_bool(payload, "prometheus.required_alerts_loaded", True),
        _check_bool(payload, "prometheus.required_metrics_present", True),
        _check_url(
            payload,
            "alertmanager.url",
            allow_placeholder_values=allow_placeholder_values,
        ),
        _check_bool(payload, "alertmanager.ready", True),
        _check_receivers(payload),
        _check_bool(payload, "alertmanager.critical_notification_delivered", True),
        _check_bool(payload, "alertmanager.warning_notification_delivered", True),
        _check_bool(payload, "alertmanager.resolved_notification_delivered", True),
        _check_bool(payload, "security.metrics_endpoint_requires_api_key", True),
        _check_bool(payload, "security.prometheus_scrapes_metrics_proxy", True),
        _check_bool(payload, "security.metrics_proxy_injects_api_key", True),
        _check_bool(payload, "security.public_metrics_endpoint_exposed", False),
        _check_bool(payload, "security.secret_values_committed", False),
        _check_min_number(
            payload,
            "calibration.observation_window_hours",
            min_observation_hours,
        ),
        _check_bool(payload, "calibration.queue_thresholds_reviewed", True),
        _check_bool(payload, "calibration.llm_thresholds_reviewed", True),
        _check_bool(payload, "calibration.http_5xx_threshold_reviewed", True),
        _check_bool(payload, "calibration.no_unresolved_critical_alerts", True),
        _check_bool(payload, "evidence.monitoring_stack_smoke_ok", True),
        _check_string(payload, "evidence.queue_alert_sample_summary_path"),
        _check_url(
            payload,
            "evidence.dashboard_url",
            allow_placeholder_values=allow_placeholder_values,
        ),
        _check_string(payload, "evidence.notification_drill_reference"),
    ]
    failed = [check for check in checks if not check.ok]
    return {
        "ok": not failed,
        "check_count": len(checks),
        "failed_count": len(failed),
        "checks": [asdict(check) for check in checks],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = _load_json(args.evidence_path)
    except Exception as exc:
        report = _error_report(
            "evidence-load",
            f"{type(exc).__name__}: {exc}",
        )
    else:
        report = build_rollout_report(
            payload,
            min_observation_hours=args.min_observation_hours,
            allow_placeholder_values=args.allow_placeholder_values,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(report)
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate production/pre-production monitoring rollout evidence.",
    )
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=DEFAULT_EVIDENCE_PATH,
        help="Monitoring rollout evidence JSON file.",
    )
    parser.add_argument(
        "--min-observation-hours",
        type=float,
        default=24.0,
        help="Minimum queue/alert observation window before production rollout.",
    )
    parser.add_argument(
        "--allow-placeholder-values",
        action="store_true",
        help="Allow example URLs and placeholders; intended only for template checks.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def print_text(report: dict[str, Any]) -> None:
    print("Monitoring rollout report")
    print(f"ok: {str(report['ok']).lower()}")
    print(f"checks: {report['check_count']}")
    print(f"failed: {report['failed_count']}")
    for check in report["checks"]:
        status = "ok" if check["ok"] else "failed"
        print(f"  {check['name']}: {status} - {check['detail']}")


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError("evidence JSON root must be an object")
    return payload


def _error_report(name: str, detail: str) -> dict[str, Any]:
    return {
        "ok": False,
        "check_count": 1,
        "failed_count": 1,
        "checks": [
            asdict(
                RolloutCheck(
                    name=name,
                    ok=False,
                    detail=detail,
                )
            )
        ],
    }


def _check_environment(payload: dict[str, Any]) -> RolloutCheck:
    value = _get(payload, "environment")
    blocked = {"dev", "development", "local", "test", "example"}
    ok = isinstance(value, str) and bool(value.strip()) and value.lower() not in blocked
    return RolloutCheck(
        name="environment",
        ok=ok,
        detail=(
            "environment is deployment-like"
            if ok
            else "environment must be a non-local deployment name"
        ),
        data={"value": value},
    )


def _check_observed_at(payload: dict[str, Any]) -> RolloutCheck:
    value = _get(payload, "observed_at")
    ok = False
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            ok = False
        else:
            ok = True
    return RolloutCheck(
        name="observed-at",
        ok=ok,
        detail=(
            "observed_at is an ISO timestamp"
            if ok
            else "observed_at must be an ISO timestamp"
        ),
        data={"value": value},
    )


def _check_url(
    payload: dict[str, Any],
    path: str,
    *,
    allow_placeholder_values: bool,
) -> RolloutCheck:
    value = _get(payload, path)
    parsed = urlparse(value) if isinstance(value, str) else None
    has_valid_shape = bool(parsed and parsed.scheme in {"http", "https"} and parsed.netloc)
    has_placeholder = isinstance(value, str) and _has_placeholder(value)
    ok = has_valid_shape and (allow_placeholder_values or not has_placeholder)
    detail = f"{path} is a concrete URL"
    if not has_valid_shape:
        detail = f"{path} must be an http(s) URL"
    elif has_placeholder and not allow_placeholder_values:
        detail = f"{path} must not use example, local, or placeholder values"
    return RolloutCheck(
        name=_check_name(path),
        ok=ok,
        detail=detail,
        data={"value": value},
    )


def _check_bool(
    payload: dict[str, Any],
    path: str,
    expected: bool,
) -> RolloutCheck:
    value = _get(payload, path)
    ok = value is expected
    return RolloutCheck(
        name=_check_name(path),
        ok=ok,
        detail=(
            f"{path} is {str(expected).lower()}"
            if ok
            else f"{path} must be {str(expected).lower()}"
        ),
        data={"value": value},
    )


def _check_exact(
    payload: dict[str, Any],
    path: str,
    expected: str,
) -> RolloutCheck:
    value = _get(payload, path)
    ok = value == expected
    return RolloutCheck(
        name=_check_name(path),
        ok=ok,
        detail=f"{path} matches {expected}" if ok else f"{path} must be {expected}",
        data={"value": value},
    )


def _check_receivers(payload: dict[str, Any]) -> RolloutCheck:
    value = _get(payload, "alertmanager.receivers")
    receivers = set(value) if isinstance(value, list) else set()
    missing = sorted(set(REQUIRED_ALERTMANAGER_RECEIVERS) - receivers)
    return RolloutCheck(
        name="alertmanager-receivers",
        ok=not missing,
        detail=(
            "required Alertmanager receivers are configured"
            if not missing
            else f"missing receivers: {', '.join(missing)}"
        ),
        data={"missing": missing, "receivers": sorted(receivers)},
    )


def _check_min_number(
    payload: dict[str, Any],
    path: str,
    minimum: float,
) -> RolloutCheck:
    value = _get(payload, path)
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= minimum
    return RolloutCheck(
        name=_check_name(path),
        ok=ok,
        detail=(
            f"{path} is at least {minimum:g}"
            if ok
            else f"{path} must be a number >= {minimum:g}"
        ),
        data={"value": value, "minimum": minimum},
    )


def _check_string(payload: dict[str, Any], path: str) -> RolloutCheck:
    value = _get(payload, path)
    ok = isinstance(value, str) and bool(value.strip())
    return RolloutCheck(
        name=_check_name(path),
        ok=ok,
        detail=f"{path} is present" if ok else f"{path} must be a non-empty string",
        data={"value": value},
    )


def _get(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _check_name(path: str) -> str:
    return path.replace(".", "-").replace("_", "-")


def _has_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


if __name__ == "__main__":
    raise SystemExit(main())
