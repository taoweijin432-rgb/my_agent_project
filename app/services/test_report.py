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
    recommendations = _recommendations(status, tool_runs)
    return TestExecutionReport(
        id=f"report-{plan.id}",
        plan_id=plan.id,
        status=status,
        summary=_summary(plan, tool_runs),
        tool_runs=tool_runs,
        requirement_coverage=requirement_coverage,
        defects=defects,
        recommendations=recommendations,
    )


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


def _recommendations(status: TestReportStatus, tool_runs: list[ToolRun]) -> list[str]:
    recommendations: list[str] = []
    if any(tool_run.status == ToolRunStatus.blocked for tool_run in tool_runs):
        recommendations.append("先处理 blocked 步骤的环境、参数或 adapter 配置问题。")
    if any(tool_run.status == ToolRunStatus.failed for tool_run in tool_runs):
        recommendations.append("优先复查 failed 步骤对应的接口响应、断言和业务规则。")
    if any(tool_run.status == ToolRunStatus.skipped for tool_run in tool_runs):
        recommendations.append("skipped 步骤未计入需求覆盖，需要人工确认或补自动化 adapter。")
    if status.value == "incomplete":
        recommendations.append("仍有 queued/running 或未执行步骤，报告结论不能作为最终验收。")
    return recommendations


def _summary(plan: TestPlan, tool_runs: list[ToolRun]) -> str:
    counts: dict[str, int] = {}
    for tool_run in tool_runs:
        counts[tool_run.status.value] = counts.get(tool_run.status.value, 0) + 1
    parts = ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
    return f"{plan.title}: executed {len(tool_runs)}/{len(plan.steps)} step(s); {parts or 'no runs'}."
