import httpx

from app.models.test_plan import TestPlan as Plan
from app.models.test_plan import TestPlanStep as PlanStep
from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import ToolRunStatus
from app.services.test_report import build_execution_report
from app.services.tool_adapters import HTTPToolAdapter
from app.services.tool_execution import ToolExecutionService


def test_http_plan_step_executes_and_builds_passed_report() -> None:
    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True})),
    )
    service = ToolExecutionService(adapters={ToolType.http: adapter})
    plan = Plan(
        id="plan-1",
        title="退款接口测试计划",
        steps=[
            PlanStep(
                id="TP-001",
                title="验证创建退款",
                objective="调用创建退款接口",
                requirement_ids=["REFUND-001"],
                tool=ToolType.http,
                tool_args={
                    "method": "POST",
                    "path": "/api/v1/refunds",
                    "expected_status": 200,
                    "json": {"idempotency_key": "k-1"},
                },
            )
        ],
    )

    runs = service.execute_plan(plan)
    report = build_execution_report(plan, runs)

    assert [run.status for run in runs] == [ToolRunStatus.passed]
    assert report.status.value == "passed"
    assert report.requirement_coverage == {"REFUND-001": True}
    assert report.defects == []
    assert "executed 1/1 step" in report.summary


def test_failed_http_step_is_reported_as_defect() -> None:
    adapter = HTTPToolAdapter(
        base_url="http://testserver",
        transport=httpx.MockTransport(lambda _: httpx.Response(500)),
    )
    service = ToolExecutionService(adapters={ToolType.http: adapter})
    plan = Plan(
        id="plan-1",
        title="退款接口测试计划",
        steps=[
            PlanStep(
                id="TP-001",
                title="验证创建退款",
                objective="调用创建退款接口",
                requirement_ids=["REFUND-001"],
                tool=ToolType.http,
                tool_args={"path": "/api/v1/refunds", "expected_status": 200},
            )
        ],
    )

    report = build_execution_report(plan, service.execute_plan(plan))

    assert report.status.value == "failed"
    assert report.requirement_coverage == {"REFUND-001": False}
    assert report.defects == ["TP-001: GET /api/v1/refunds returned 500; expected [200]."]
    assert "复查 failed" in report.recommendations[0]


def test_skipped_manual_step_does_not_count_as_requirement_coverage() -> None:
    plan = Plan(
        id="plan-1",
        title="人工验收计划",
        steps=[
            PlanStep(
                id="TP-001",
                title="人工确认审计记录",
                objective="人工确认审计记录完整",
                requirement_ids=["AUDIT-001"],
                tool=ToolType.manual,
            )
        ],
    )

    report = build_execution_report(plan, ToolExecutionService().execute_plan(plan))

    assert report.status.value == "incomplete"
    assert report.requirement_coverage == {"AUDIT-001": False}
    assert "skipped 步骤未计入需求覆盖" in report.recommendations[0]
