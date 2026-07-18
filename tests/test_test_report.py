import json

import pytest

from app.models.test_plan import (
    TestExecutionReport as ExecutionReport,
    TestPlan as Plan,
    TestReportStatus as ReportStatus,
    TestPlanStep as PlanStep,
    TestToolType as ToolType,
    ToolRun,
    ToolRunStatus,
)
from app.services.test_report import (
    build_execution_report,
    export_execution_report,
    render_execution_report_markdown,
)


def _report() -> ExecutionReport:
    return ExecutionReport(
        id="report-plan-login",
        plan_id="plan-login",
        status=ReportStatus.failed,
        summary="登录测试计划: executed 2/2 step(s); failed=1, passed=1.",
        requirement_coverage={"REQ-001": True, "REQ-002": False},
        tool_runs=[
            ToolRun(
                id="run-1",
                plan_step_id="TP-001",
                tool=ToolType.http,
                status=ToolRunStatus.passed,
                command=["GET", "/login"],
                exit_code=0,
                output_summary="HTTP 200",
                artifact_paths=["data/test-artifacts/run-1/output.txt"],
            ),
            ToolRun(
                id="run-2",
                plan_step_id="TP-002",
                tool=ToolType.pytest,
                status=ToolRunStatus.failed,
                command=["pytest", "tests/test_login.py"],
                exit_code=1,
                output_summary="assert failed | token expired",
            ),
        ],
        defects=["TP-002: assert failed"],
        recommendations=["优先复查 failed 步骤 TP-002。"],
    )


def test_render_execution_report_markdown_includes_evidence_sections() -> None:
    markdown = render_execution_report_markdown(_report())

    assert markdown.startswith("# Test Execution Report: report-plan-login")
    assert "| REQ-001 | yes |" in markdown
    assert "| REQ-002 | no |" in markdown
    assert "| run-1 | TP-001 | http | passed | 0 | HTTP 200 | data/test-artifacts/run-1/output.txt |" in markdown
    assert "assert failed \\| token expired" in markdown
    assert "- TP-002: assert failed" in markdown
    assert "- 优先复查 failed 步骤 TP-002。" in markdown


def test_export_execution_report_json_uses_report_schema() -> None:
    payload = json.loads(export_execution_report(_report(), "json"))

    assert payload["id"] == "report-plan-login"
    assert payload["status"] == "failed"
    assert payload["tool_runs"][1]["tool"] == "pytest"


def test_build_execution_report_redacts_sensitive_tool_output() -> None:
    plan = Plan(
        id="plan-redaction",
        title="redaction plan",
        steps=[
            PlanStep(
                id="TP-001",
                title="HTTP step",
                objective="HTTP step",
                requirement_ids=["REQ-001"],
                tool=ToolType.http,
            )
        ],
    )

    report = build_execution_report(
        plan,
        [
            ToolRun(
                id="run-1",
                plan_step_id="TP-001",
                tool=ToolType.http,
                status=ToolRunStatus.failed,
                output_summary=(
                    "POST /login returned 401; expected [200]. "
                    "Authorization: Bearer secret-token password=secret-password"
                ),
            )
        ],
    )
    payload = report.model_dump_json()

    assert "secret-token" not in payload
    assert "secret-password" not in payload
    assert "[redacted]" in report.tool_runs[0].output_summary
    assert "[redacted]" in report.defects[0]


def test_export_execution_report_redacts_sensitive_values() -> None:
    report = ExecutionReport(
        id="report-redaction",
        plan_id="plan-redaction",
        status=ReportStatus.failed,
        summary="Cookie: session=secret-cookie",
        tool_runs=[
            ToolRun(
                id="run-1",
                plan_step_id="TP-001",
                tool=ToolType.http,
                status=ToolRunStatus.failed,
                output_summary="api_key=secret-api-key",
            )
        ],
        defects=["TP-001: access_token=secret-access"],
        recommendations=["Rotate password=secret-password"],
    )

    markdown = export_execution_report(report, "markdown")
    json_payload = export_execution_report(report, "json")

    for raw_secret in [
        "secret-cookie",
        "secret-api-key",
        "secret-access",
        "secret-password",
    ]:
        assert raw_secret not in markdown
        assert raw_secret not in json_payload
    assert "[redacted]" in markdown
    assert "[redacted]" in json_payload


def test_export_execution_report_rejects_unknown_format() -> None:
    with pytest.raises(ValueError):
        export_execution_report(_report(), "html")


@pytest.mark.parametrize(
    ("output_summary", "expected_reason"),
    [
        ("GET /jobs/1 returned 504; expected [200].", "timeout"),
        ("GET /audit returned 503; expected [200].", "upstream_unavailable"),
        ("GET /payments/1 returned 409; expected [200].", "conflict"),
        ("GET /exports/1 returned 403; expected [200].", "permission_denied"),
        ("GET /admin/users returned 200; expected [403].", "permission_not_enforced"),
        ("PUT /api/v1/profile returned 422; expected [200].", "validation_error"),
        (
            'GET /refunds/1 returned 200; expected [200]. '
            'JSON assertion failed: path amount expected "100.00" but got "99.00".',
            "response_assertion_mismatch",
        ),
        ("HTTP 401 token expired", "auth_failure"),
    ],
)
def test_build_execution_report_classifies_http_failure_reasons(
    output_summary: str,
    expected_reason: str,
) -> None:
    plan = Plan(
        id="plan-http-reason",
        title="HTTP reason plan",
        steps=[
            PlanStep(
                id="TP-001",
                title="HTTP step",
                objective="HTTP step",
                requirement_ids=["REQ-001"],
                tool=ToolType.http,
            )
        ],
    )
    report = build_execution_report(
        plan,
        [
            ToolRun(
                id="run-1",
                plan_step_id="TP-001",
                tool=ToolType.http,
                status=ToolRunStatus.failed,
                output_summary=output_summary,
            )
        ],
    )

    assert report.reason_classifications == {"TP-001": expected_reason}


def test_build_execution_report_recommends_validation_error_next_action() -> None:
    plan = Plan(
        id="plan-validation-reason",
        title="validation reason plan",
        steps=[
            PlanStep(
                id="TP-001",
                title="Profile validation step",
                objective="Profile validation step",
                requirement_ids=["REQ-001"],
                tool=ToolType.http,
            )
        ],
    )
    report = build_execution_report(
        plan,
        [
            ToolRun(
                id="run-1",
                plan_step_id="TP-001",
                tool=ToolType.http,
                status=ToolRunStatus.failed,
                output_summary="PUT /api/v1/profile returned 422; expected [200].",
            )
        ],
    )

    assert report.reason_classifications == {"TP-001": "validation_error"}
    assert report.recommendations == [
        "优先复查 failed 步骤 TP-001 的请求参数、字段校验和错误提示。"
    ]


def test_build_execution_report_recommends_response_assertion_next_action() -> None:
    plan = Plan(
        id="plan-response-assertion",
        title="response assertion plan",
        steps=[
            PlanStep(
                id="TP-001",
                title="Refund amount assertion step",
                objective="Refund amount assertion step",
                requirement_ids=["REQ-001"],
                tool=ToolType.http,
            )
        ],
    )
    report = build_execution_report(
        plan,
        [
            ToolRun(
                id="run-1",
                plan_step_id="TP-001",
                tool=ToolType.http,
                status=ToolRunStatus.failed,
                output_summary=(
                    'GET /refunds/1 returned 200; expected [200]. '
                    'JSON assertion failed: path amount expected "100.00" but got "99.00".'
                ),
            )
        ],
    )

    assert report.reason_classifications == {"TP-001": "response_assertion_mismatch"}
    assert report.recommendations == [
        "优先复查 failed 步骤 TP-001 的响应字段、JSON 断言和业务状态一致性。"
    ]
