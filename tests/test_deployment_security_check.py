import json
from pathlib import Path
from typing import Any

from scripts import check_deployment_security


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_deployment_security_report_passes_for_complete_evidence() -> None:
    report = check_deployment_security.build_security_report(
        _complete_evidence(),
        min_audit_retention_days=90,
    )

    assert report["ok"] is True
    assert report["failed_count"] == 0
    assert {check["name"] for check in report["checks"]} >= {
        "ingress-tls-enforced",
        "authentication-external-identity-provider-enabled",
        "authorization-rbac-enforced-at-gateway-or-platform",
        "audit-audit-retention-days",
        "secrets-secret-manager-enabled",
        "cors-allowed-origins",
    }


def test_deployment_security_report_detects_missing_security_controls() -> None:
    payload = _complete_evidence()
    payload["ingress"]["public_entrypoint_url"] = "http://app.ops.internal"
    payload["ingress"]["tls_enforced"] = False
    payload["authentication"]["external_identity_provider_enabled"] = False
    payload["authorization"]["rbac_enforced_at_gateway_or_platform"] = False
    payload["audit"]["audit_retention_days"] = 7
    payload["secrets"]["real_secrets_committed"] = True
    payload["cors"]["allowed_origins"] = ["*"]

    report = check_deployment_security.build_security_report(
        payload,
        min_audit_retention_days=90,
    )

    failed_names = {
        check["name"] for check in report["checks"] if check["ok"] is False
    }
    assert report["ok"] is False
    assert failed_names >= {
        "ingress-public-entrypoint-url",
        "ingress-tls-enforced",
        "authentication-external-identity-provider-enabled",
        "authorization-rbac-enforced-at-gateway-or-platform",
        "audit-audit-retention-days",
        "secrets-real-secrets-committed",
        "cors-allowed-origins",
    }


def test_deployment_security_main_accepts_template_when_placeholders_allowed(
    capsys: Any,
) -> None:
    template_path = (
        PROJECT_ROOT / "docs" / "security" / "deployment-security-evidence.example.json"
    )

    exit_code = check_deployment_security.main(
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


def test_deployment_security_main_rejects_template_without_placeholder_flag(
    capsys: Any,
) -> None:
    template_path = (
        PROJECT_ROOT / "docs" / "security" / "deployment-security-evidence.example.json"
    )

    exit_code = check_deployment_security.main(
        ["--evidence-path", str(template_path), "--json"]
    )

    captured = json.loads(capsys.readouterr().out)
    failed_names = {
        check["name"] for check in captured["checks"] if check["ok"] is False
    }
    assert exit_code == 1
    assert failed_names == {
        "ingress-public-entrypoint-url",
        "cors-allowed-origins",
    }


def test_deployment_security_main_reports_missing_evidence_file(capsys: Any) -> None:
    exit_code = check_deployment_security.main(
        ["--evidence-path", "/tmp/missing-deployment-security.json", "--json"]
    )

    captured = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert captured["ok"] is False
    assert captured["checks"][0]["name"] == "evidence-load"


def _complete_evidence() -> dict[str, Any]:
    return {
        "environment": "production",
        "observed_at": "2026-07-20T00:00:00Z",
        "ingress": {
            "public_entrypoint_url": "https://ai-testcase.ops.internal",
            "tls_enforced": True,
            "hsts_enabled": True,
            "gateway_enabled": True,
            "gateway_rate_limit_enabled": True,
            "gateway_request_size_limit_enabled": True,
            "gateway_access_logs_enabled": True,
            "waf_or_ip_allowlist_enabled": True,
        },
        "authentication": {
            "api_key_required": True,
            "dual_api_key_rotation_tested": True,
            "no_anonymous_business_endpoints": True,
            "external_identity_provider_enabled": True,
        },
        "authorization": {
            "rbac_enforced_at_gateway_or_platform": True,
            "project_or_tenant_isolation_defined": True,
            "admin_operations_restricted": True,
            "knowledge_base_access_scoped": True,
        },
        "audit": {
            "request_logs_enabled": True,
            "centralized_log_sink_configured": True,
            "audit_retention_days": 90,
            "request_id_propagation_verified": True,
            "sensitive_data_redaction_verified": True,
        },
        "secrets": {
            "secret_manager_enabled": True,
            "env_files_excluded_from_git": True,
            "real_secrets_committed": False,
            "rotation_owner": "platform-team",
        },
        "cors": {
            "allowed_origins": ["https://qa.ops.internal"],
            "wildcard_allowed": False,
            "credentials_allowed": False,
        },
        "tools": {
            "http_base_url_allowlist_configured": True,
            "pytest_adapter_disabled_or_scoped": True,
            "allowed_headers_minimal": True,
        },
        "validation": {
            "production_startup_validation_passed": True,
            "release_checks_passed": True,
            "secret_scan_passed": True,
            "readiness_check_passed": True,
        },
    }
