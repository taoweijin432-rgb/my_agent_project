import httpx
import pytest

from app.models.test_plan import TestPlan as Plan
from app.models.test_plan import TestPlanExecutionRequest as PlanExecutionRequest
from app.models.test_plan import TestPlanStepExecutionRequest as StepExecutionRequest
from app.models.test_plan import TestPlanStep as PlanStep
from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import ToolRun
from app.models.test_plan import ToolRunStatus
from app.services.stage_metrics import get_stage_metrics_snapshot, reset_stage_metrics
from app.services import test_plan_execution as execution_module
from app.services.test_plan_execution import (
    execute_test_plan_request,
    execute_test_plan_step_request,
)
from app.services.test_report import build_execution_report
from app.services.tool_adapters import HTTPToolAdapter
from app.services.tool_execution import ToolExecutionService


@pytest.fixture(autouse=True)
def clear_stage_metrics() -> None:
    reset_stage_metrics()
    yield
    reset_stage_metrics()


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
    assert "skipped 步骤 TP-001 未计入需求覆盖" in report.recommendations[0]
    assert report.reason_classifications == {
        "TP-001": "manual_confirmation_required",
    }


def test_test_plan_execution_request_records_stage_metrics(monkeypatch) -> None:
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
    tool_run = ToolRun(
        id="run-1",
        plan_step_id="TP-001",
        tool=ToolType.http,
        status=ToolRunStatus.passed,
        output_summary="GET /api/v1/refunds returned 200; expected [200].",
    )

    class FakeExecutionService:
        def execute_plan(self, _plan):
            return [tool_run]

        def execute_step(self, _step):
            return tool_run

    monkeypatch.setattr(
        execution_module,
        "build_tool_execution_service",
        lambda _settings, _http_base_url: FakeExecutionService(),
    )

    report = execute_test_plan_request(
        PlanExecutionRequest(plan=plan, http_base_url="http://testserver"),
        execution_module.Settings(),
    )
    run = execute_test_plan_step_request(
        StepExecutionRequest(
            step=plan.steps[0],
            http_base_url="http://testserver",
        ),
        execution_module.Settings(),
    )

    assert report.status.value == "passed"
    assert run.status == ToolRunStatus.passed

    snapshot = get_stage_metrics_snapshot()
    assert snapshot["total_count"] == 3
    assert {
        (item["workflow"], item["stage"], item["status"], item["count"])
        for item in snapshot["stages"]
    } == {
        ("test_plan_execution", "tool_execution", "succeeded", 1),
        ("test_plan_execution", "report_build", "passed", 1),
        ("test_plan_step_execution", "tool_execution", "passed", 1),
    }
