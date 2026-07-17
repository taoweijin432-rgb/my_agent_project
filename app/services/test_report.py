import re

from app.models.test_plan import (
    TestExecutionReport,
    TestPlan,
    TestReportStatus,
    ToolRun,
    ToolRunStatus,
    summarize_report_status,
)


def build_execution_report(
    plan: TestPlan,
    tool_runs: list[ToolRun],
) -> TestExecutionReport:
    status = summarize_report_status(tool_runs)
    requirement_coverage = _requirement_coverage(plan, tool_runs)
    defects = _defects_from_runs(tool_runs)
    reason_classifications = _reason_classifications(tool_runs)
    recommendations = _recommendations(status, tool_runs, reason_classifications)
    return TestExecutionReport(
        id=f"report-{plan.id}",
        plan_id=plan.id,
        status=status,
        summary=_summary(plan, tool_runs, status, requirement_coverage),
        tool_runs=tool_runs,
        requirement_coverage=requirement_coverage,
        defects=defects,
        reason_classifications=reason_classifications,
        recommendations=recommendations,
    )


def export_execution_report(
    report: TestExecutionReport,
    export_format: str,
) -> str:
    if export_format == "json":
        return report.model_dump_json(indent=2)
    if export_format == "markdown":
        return render_execution_report_markdown(report)
    raise ValueError(f"Unsupported report export format: {export_format}")


def render_execution_report_markdown(report: TestExecutionReport) -> str:
    lines = [
        f"# Test Execution Report: {report.id}",
        "",
        f"- Plan: `{_markdown_inline(report.plan_id)}`",
        f"- Status: `{report.status.value}`",
        f"- Summary: {_markdown_inline(report.summary or '-')}",
        "",
        "## Requirement Coverage",
        "",
    ]
    if report.requirement_coverage:
        lines.extend(
            [
                "| Requirement | Covered |",
                "| --- | --- |",
                *[
                    f"| {_markdown_cell(requirement_id)} | {'yes' if covered else 'no'} |"
                    for requirement_id, covered in sorted(report.requirement_coverage.items())
                ],
            ]
        )
    else:
        lines.append("- No requirement coverage recorded.")

    lines.extend(["", "## Tool Runs", ""])
    if report.tool_runs:
        lines.extend(
            [
                "| Run | Step | Tool | Status | Exit | Output | Artifacts |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for tool_run in report.tool_runs:
            artifact_text = ", ".join(tool_run.artifact_paths) or "-"
            exit_text = "-" if tool_run.exit_code is None else str(tool_run.exit_code)
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(tool_run.id),
                        _markdown_cell(tool_run.plan_step_id),
                        _markdown_cell(tool_run.tool.value),
                        _markdown_cell(tool_run.status.value),
                        _markdown_cell(exit_text),
                        _markdown_cell(tool_run.output_summary or "-"),
                        _markdown_cell(artifact_text),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- No tool runs recorded.")

    lines.extend(["", "## Defects", ""])
    lines.extend(_markdown_list(report.defects, "No defects recorded."))
    lines.extend(["", "## Reason Classifications", ""])
    if report.reason_classifications:
        lines.extend(
            [
                "| Step | Reason |",
                "| --- | --- |",
                *[
                    f"| {_markdown_cell(step_id)} | {_markdown_cell(reason)} |"
                    for step_id, reason in sorted(report.reason_classifications.items())
                ],
            ]
        )
    else:
        lines.append("- No reason classifications recorded.")
    lines.extend(["", "## Recommendations", ""])
    lines.extend(_markdown_list(report.recommendations, "No recommendations recorded."))
    lines.append("")
    return "\n".join(lines)


def _requirement_coverage(
    plan: TestPlan,
    tool_runs: list[ToolRun],
) -> dict[str, bool]:
    run_by_step_id = {tool_run.plan_step_id: tool_run for tool_run in tool_runs}
    coverage: dict[str, bool] = {}
    for step in plan.steps:
        run = run_by_step_id.get(step.id)
        step_passed = run is not None and run.status == ToolRunStatus.passed
        for requirement_id in step.requirement_ids:
            coverage[requirement_id] = coverage.get(requirement_id, False) or step_passed
    return coverage


def _defects_from_runs(tool_runs: list[ToolRun]) -> list[str]:
    return [
        f"{tool_run.plan_step_id}: {tool_run.output_summary}"
        for tool_run in tool_runs
        if tool_run.status == ToolRunStatus.failed
    ]


def _reason_classifications(tool_runs: list[ToolRun]) -> dict[str, str]:
    return {
        tool_run.plan_step_id: _reason_classification(tool_run)
        for tool_run in tool_runs
        if tool_run.status in {ToolRunStatus.failed, ToolRunStatus.blocked, ToolRunStatus.skipped}
    }


def _reason_classification(tool_run: ToolRun) -> str:
    text = " ".join([tool_run.output_summary, " ".join(tool_run.command)]).lower()
    if tool_run.status == ToolRunStatus.blocked:
        if "adapter" in text or "not registered" in text:
            return "adapter_missing"
        return "blocked_environment"
    if tool_run.status == ToolRunStatus.skipped:
        if "manual" in text or "confirmation" in text or tool_run.tool.value == "manual":
            return "manual_confirmation_required"
        return "skipped_not_executed"
    if "json assertion failed" in text:
        return "response_assertion_mismatch"
    if "assert" in text:
        return "assertion_mismatch"
    actual_status, expected_statuses = _http_status_facts(text)
    if actual_status == 504 or "timeout" in text or "timed out" in text:
        return "timeout"
    if actual_status == 401 or "token" in text or "unauthorized" in text:
        return "auth_failure"
    if actual_status == 403:
        return "permission_denied"
    if actual_status == 409:
        return "conflict"
    if actual_status == 422 or _contains_validation_error_marker(text):
        return "validation_error"
    if actual_status is not None and actual_status >= 500:
        return "upstream_unavailable"
    if actual_status is not None and 403 in expected_statuses and 200 <= actual_status < 300:
        return "permission_not_enforced"
    if actual_status is not None:
        return "http_status_mismatch"
    if "http 4" in text or "http 5" in text:
        return "http_status_mismatch"
    return "tool_execution_error"


def _contains_validation_error_marker(text: str) -> bool:
    return any(
        marker in text
        for marker in ("validation", "invalid", "校验", "参数")
    )


def _http_status_facts(text: str) -> tuple[int | None, set[int]]:
    match = re.search(r"returned\s+(\d{3});\s+expected\s+\[([^\]]*)\]", text)
    if match is None:
        return None, set()
    expected_statuses: set[int] = set()
    for item in match.group(2).split(","):
        stripped = item.strip()
        if stripped.isdigit():
            expected_statuses.add(int(stripped))
    return int(match.group(1)), expected_statuses


def _recommendations(
    status: TestReportStatus,
    tool_runs: list[ToolRun],
    reason_classifications: dict[str, str],
) -> list[str]:
    recommendations: list[str] = []
    for tool_run in tool_runs:
        if tool_run.status not in {
            ToolRunStatus.failed,
            ToolRunStatus.blocked,
            ToolRunStatus.skipped,
        }:
            continue
        recommendations.append(
            _recommendation_for_run(
                tool_run,
                reason_classifications.get(tool_run.plan_step_id, ""),
            )
        )
    if status.value == "incomplete":
        recommendations.append("仍有 queued/running 或未执行步骤，报告结论不能作为最终验收。")
    return recommendations


def _recommendation_for_run(tool_run: ToolRun, reason: str) -> str:
    step_id = tool_run.plan_step_id
    if tool_run.status == ToolRunStatus.blocked:
        if reason == "adapter_missing":
            return f"先处理 blocked 步骤 {step_id} 的 adapter 注册、启用配置和运行环境。"
        return f"先处理 blocked 步骤 {step_id} 的环境、参数或依赖配置问题。"
    if tool_run.status == ToolRunStatus.skipped:
        if reason == "manual_confirmation_required":
            return f"skipped 步骤 {step_id} 未计入需求覆盖，需要人工确认审批记录或补自动化 adapter。"
        return f"skipped 步骤 {step_id} 未计入需求覆盖，需要确认跳过原因或补自动化 adapter。"
    if reason == "timeout":
        return f"优先复查 failed 步骤 {step_id} 的超时、重试和上游耗时配置。"
    if reason == "conflict":
        return f"优先复查 failed 步骤 {step_id} 的幂等、冲突处理和状态一致性。"
    if reason == "permission_denied":
        return f"优先复查 failed 步骤 {step_id} 的权限配置、身份上下文和访问策略。"
    if reason == "permission_not_enforced":
        return f"优先修复 failed 步骤 {step_id} 的权限校验缺失，确认越权访问被拒绝。"
    if reason == "upstream_unavailable":
        return f"优先复查 failed 步骤 {step_id} 的上游服务可用性、依赖健康和降级策略。"
    if reason == "auth_failure":
        return f"优先复查 failed 步骤 {step_id} 的认证 token、过期处理和鉴权配置。"
    if reason == "validation_error":
        return f"优先复查 failed 步骤 {step_id} 的请求参数、字段校验和错误提示。"
    if reason == "response_assertion_mismatch":
        return f"优先复查 failed 步骤 {step_id} 的响应字段、JSON 断言和业务状态一致性。"
    if reason == "assertion_mismatch":
        return f"优先复查 failed 步骤 {step_id} 的断言、接口响应和业务规则。"
    return f"优先复查 failed 步骤 {step_id} 的接口响应、断言和业务规则。"


def _summary(
    plan: TestPlan,
    tool_runs: list[ToolRun],
    status: TestReportStatus,
    requirement_coverage: dict[str, bool],
) -> str:
    counts: dict[str, int] = {}
    for tool_run in tool_runs:
        counts[tool_run.status.value] = counts.get(tool_run.status.value, 0) + 1
    ordered_statuses = [
        ToolRunStatus.passed,
        ToolRunStatus.failed,
        ToolRunStatus.blocked,
        ToolRunStatus.skipped,
    ]
    parts = [
        f"{tool_status.value}={counts.get(tool_status.value, 0)}"
        for tool_status in ordered_statuses
    ]
    parts.extend(
        f"{tool_status.value}={counts[tool_status.value]}"
        for tool_status in (ToolRunStatus.queued, ToolRunStatus.running)
        if tool_status.value in counts
    )
    covered_count = sum(1 for covered in requirement_coverage.values() if covered)
    requirement_count = len(requirement_coverage)
    return (
        f"{plan.title}: status={status.value}; "
        f"executed {len(tool_runs)}/{len(plan.steps)} step(s); "
        f"coverage={covered_count}/{requirement_count} requirement(s); "
        f"{', '.join(parts)}."
    )


def _markdown_list(items: list[str], empty_text: str) -> list[str]:
    if not items:
        return [f"- {empty_text}"]
    return [f"- {_markdown_inline(item)}" for item in items]


def _markdown_cell(value: str) -> str:
    return _markdown_inline(value).replace("|", "\\|")


def _markdown_inline(value: str) -> str:
    return str(value).replace("\n", " ").strip()
