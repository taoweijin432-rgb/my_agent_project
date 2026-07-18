from typing import Protocol
from uuid import uuid4

from app.models.test_plan import TestPlan, TestPlanStep, TestToolType, ToolRun, ToolRunStatus
from app.services.redaction import redact_sensitive_text


class ToolAdapter(Protocol):
    def run(self, step: TestPlanStep) -> ToolRun:
        pass


class ToolExecutionService:
    def __init__(self, adapters: dict[TestToolType, ToolAdapter] | None = None):
        self.adapters = adapters or {}

    def execute_step(self, step: TestPlanStep) -> ToolRun:
        if step.tool == TestToolType.manual:
            return _non_executable_run(
                step,
                status=ToolRunStatus.skipped,
                summary="Manual step requires human execution.",
            )

        adapter = self.adapters.get(step.tool)
        if adapter is None:
            return _non_executable_run(
                step,
                status=ToolRunStatus.blocked,
                summary=f"No adapter registered for tool: {step.tool.value}.",
            )
        return adapter.run(step)

    def execute_plan(self, plan: TestPlan) -> list[ToolRun]:
        return [self.execute_step(step) for step in plan.steps]


def _non_executable_run(
    step: TestPlanStep,
    *,
    status: ToolRunStatus,
    summary: str,
) -> ToolRun:
    return ToolRun(
        id=f"run-{uuid4().hex[:12]}",
        plan_step_id=step.id,
        tool=step.tool,
        status=status,
        exit_code=None,
        output_summary=redact_sensitive_text(summary),
    )
