from app.models.test_plan import TestPlan as Plan
from app.models.test_plan import TestPlanStep as PlanStep
from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import ToolRun, ToolRunStatus
from app.services.tool_execution import ToolExecutionService


class FakeAdapter:
    def __init__(self, status: ToolRunStatus = ToolRunStatus.passed):
        self.status = status
        self.steps = []

    def run(self, step: PlanStep) -> ToolRun:
        self.steps.append(step)
        return ToolRun(
            id="run-fake",
            plan_step_id=step.id,
            tool=step.tool,
            status=self.status,
            exit_code=0 if self.status == ToolRunStatus.passed else 1,
            output_summary="fake adapter result",
        )


def _step(step_id: str, tool: ToolType) -> PlanStep:
    return PlanStep(
        id=step_id,
        title=f"{step_id} title",
        objective=f"{step_id} objective",
        tool=tool,
    )


def test_tool_execution_service_routes_step_to_registered_adapter() -> None:
    adapter = FakeAdapter()
    service = ToolExecutionService(adapters={ToolType.http: adapter})

    result = service.execute_step(_step("TP-001", ToolType.http))

    assert result.status == ToolRunStatus.passed
    assert result.plan_step_id == "TP-001"
    assert adapter.steps[0].id == "TP-001"


def test_tool_execution_service_skips_manual_step() -> None:
    service = ToolExecutionService()

    result = service.execute_step(_step("TP-001", ToolType.manual))

    assert result.status == ToolRunStatus.skipped
    assert result.tool == ToolType.manual
    assert "Manual step" in result.output_summary


def test_tool_execution_service_blocks_unregistered_tool() -> None:
    service = ToolExecutionService()

    result = service.execute_step(_step("TP-001", ToolType.pytest))

    assert result.status == ToolRunStatus.blocked
    assert result.tool == ToolType.pytest
    assert "No adapter registered" in result.output_summary


def test_tool_execution_service_executes_plan_steps_in_order() -> None:
    adapter = FakeAdapter()
    service = ToolExecutionService(adapters={ToolType.http: adapter})
    plan = Plan(
        id="plan-1",
        title="计划",
        steps=[
            _step("TP-001", ToolType.http),
            _step("TP-002", ToolType.manual),
        ],
    )

    results = service.execute_plan(plan)

    assert [result.plan_step_id for result in results] == ["TP-001", "TP-002"]
    assert [result.status for result in results] == [
        ToolRunStatus.passed,
        ToolRunStatus.skipped,
    ]
