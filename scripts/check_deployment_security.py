import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_PATH = (
    PROJECT_ROOT / "data" / "ops-drills" / "deployment-security-evidence.json"
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
class SecurityCheck:
    name: str
    ok: bool
    detail: str
    data: dict[str, Any] | None = None


def build_security_report(
    payload: dict[str, Any],
    *,
    min_audit_retention_days: int,
    allow_placeholder_values: bool = False,
) -> dict[str, Any]:
    checks = [
        _check_environment(payload),
        _check_observed_at(payload),
        _check_url(
            payload,
            "ingress.public_entrypoint_url",
            allow_placeholder_values=allow_placeholder_values,
        ),
        _check_bool(payload, "ingress.tls_enforced", True),
        _check_bool(payload, "ingress.hsts_enabled", True),
        _check_bool(payload, "ingress.gateway_enabled", True),
        _check_bool(payload, "ingress.gateway_rate_limit_enabled", True),
        _check_bool(payload, "ingress.gateway_request_size_limit_enabled", True),
        _check_bool(payload, "ingress.gateway_access_logs_enabled", True),
        _check_bool(payload, "ingress.waf_or_ip_allowlist_enabled", True),
        _check_bool(payload, "authentication.api_key_required", True),
        _check_bool(payload, "authentication.dual_api_key_rotation_tested", True),
        _check_bool(payload, "authentication.no_anonymous_business_endpoints", True),
        _check_bool(payload, "authentication.external_identity_provider_enabled", True),
        _check_bool(payload, "authorization.rbac_enforced_at_gateway_or_platform", True),
        _check_bool(payload, "authorization.project_or_tenant_isolation_defined", True),
        _check_bool(payload, "authorization.admin_operations_restricted", True),
        _check_bool(payload, "authorization.knowledge_base_access_scoped", True),
        _check_bool(payload, "audit.request_logs_enabled", True),
        _check_bool(payload, "audit.centralized_log_sink_configured", True),
        _check_min_number(
            payload,
            "audit.audit_retention_days",
            min_audit_retention_days,
        ),
        _check_bool(payload, "audit.request_id_propagation_verified", True),
        _check_bool(payload, "audit.sensitive_data_redaction_verified", True),
        _check_bool(payload, "secrets.secret_manager_enabled", True),
        _check_bool(payload, "secrets.env_files_excluded_from_git", True),
        _check_bool(payload, "secrets.real_secrets_committed", False),
        _check_string(payload, "secrets.rotation_owner"),
        _check_https_origins(
            payload,
            "cors.allowed_origins",
            allow_placeholder_values=allow_placeholder_values,
        ),
        _check_bool(payload, "cors.wildcard_allowed", False),
        _check_bool(payload, "cors.credentials_allowed", False),
        _check_bool(payload, "tools.http_base_url_allowlist_configured", True),
        _check_bool(payload, "tools.pytest_adapter_disabled_or_scoped", True),
        _check_bool(payload, "tools.allowed_headers_minimal", True),
        _check_bool(payload, "validation.production_startup_validation_passed", True),
        _check_bool(payload, "validation.release_checks_passed", True),
        _check_bool(payload, "validation.secret_scan_passed", True),
        _check_bool(payload, "validation.readiness_check_passed", True),
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
        report = build_security_report(
            payload,
            min_audit_retention_days=args.min_audit_retention_days,
            allow_placeholder_values=args.allow_placeholder_values,
        )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(report)
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate public/pre-production deployment security evidence.",
    )
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=DEFAULT_EVIDENCE_PATH,
        help="Deployment security evidence JSON file.",
    )
    parser.add_argument(
        "--min-audit-retention-days",
        type=int,
        default=90,
        help="Minimum centralized audit/request log retention.",
    )
    parser.add_argument(
        "--allow-placeholder-values",
        action="store_true",
        help="Allow example URLs and placeholders; intended only for template checks.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def print_text(report: dict[str, Any]) -> None:
    print("Deployment security report")
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
                SecurityCheck(
                    name=name,
                    ok=False,
                    detail=detail,
                )
            )
        ],
    }


def _check_environment(payload: dict[str, Any]) -> SecurityCheck:
    value = _get(payload, "environment")
    blocked = {"dev", "development", "local", "test", "example"}
    ok = isinstance(value, str) and bool(value.strip()) and value.lower() not in blocked
    return SecurityCheck(
        name="environment",
        ok=ok,
        detail=(
            "environment is deployment-like"
            if ok
            else "environment must be a non-local deployment name"
        ),
        data={"value": value},
    )


def _check_observed_at(payload: dict[str, Any]) -> SecurityCheck:
    value = _get(payload, "observed_at")
    ok = False
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            ok = False
        else:
            ok = True
    return SecurityCheck(
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
) -> SecurityCheck:
    value = _get(payload, path)
    parsed = urlparse(value) if isinstance(value, str) else None
    has_valid_shape = bool(parsed and parsed.scheme == "https" and parsed.netloc)
    has_placeholder = isinstance(value, str) and _has_placeholder(value)
    ok = has_valid_shape and (allow_placeholder_values or not has_placeholder)
    detail = f"{path} is a concrete HTTPS URL"
    if not has_valid_shape:
        detail = f"{path} must be an https URL"
    elif has_placeholder and not allow_placeholder_values:
        detail = f"{path} must not use example, local, or placeholder values"
    return SecurityCheck(
        name=_check_name(path),
        ok=ok,
        detail=detail,
        data={"value": value},
    )


def _check_https_origins(
    payload: dict[str, Any],
    path: str,
    *,
    allow_placeholder_values: bool,
) -> SecurityCheck:
    value = _get(payload, path)
    origins = value if isinstance(value, list) else []
    invalid = [
        origin
        for origin in origins
        if not _is_concrete_https_url(
            origin,
            allow_placeholder_values=allow_placeholder_values,
        )
    ]
    ok = bool(origins) and not invalid
    return SecurityCheck(
        name=_check_name(path),
        ok=ok,
        detail=(
            "CORS origins are concrete HTTPS URLs"
            if ok
            else "CORS origins must be non-empty concrete HTTPS URLs"
        ),
        data={"invalid": invalid, "origins": origins},
    )


def _check_bool(payload: dict[str, Any], path: str, expected: bool) -> SecurityCheck:
    value = _get(payload, path)
    ok = value is expected
    return SecurityCheck(
        name=_check_name(path),
        ok=ok,
        detail=(
            f"{path} is {str(expected).lower()}"
            if ok
            else f"{path} must be {str(expected).lower()}"
        ),
        data={"value": value},
    )


def _check_min_number(
    payload: dict[str, Any],
    path: str,
    minimum: int,
) -> SecurityCheck:
    value = _get(payload, path)
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and value >= minimum
    return SecurityCheck(
        name=_check_name(path),
        ok=ok,
        detail=(
            f"{path} is at least {minimum:g}"
            if ok
            else f"{path} must be a number >= {minimum:g}"
        ),
        data={"value": value, "minimum": minimum},
    )


def _check_string(payload: dict[str, Any], path: str) -> SecurityCheck:
    value = _get(payload, path)
    ok = isinstance(value, str) and bool(value.strip()) and not _has_placeholder(value)
    return SecurityCheck(
        name=_check_name(path),
        ok=ok,
        detail=(
            f"{path} is present"
            if ok
            else f"{path} must be a non-placeholder string"
        ),
        data={"value": value},
    )


def _get(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_concrete_https_url(
    value: Any,
    *,
    allow_placeholder_values: bool,
) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    return allow_placeholder_values or not _has_placeholder(value)


def _check_name(path: str) -> str:
    return path.replace(".", "-").replace("_", "-")


def _has_placeholder(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in PLACEHOLDER_MARKERS)


if __name__ == "__main__":
    raise SystemExit(main())
