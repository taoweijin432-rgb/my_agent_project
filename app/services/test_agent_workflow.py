from collections.abc import Callable
from datetime import datetime, timezone
import time
from typing import Any
from typing import TypeVar

from app.core.config import Settings
from app.models.test_plan import (
    TestAgentWorkflowRequest,
    TestAgentWorkflowResult,
    TestAgentWorkflowStage,
    TestAgentWorkflowStageTiming,
    TestAgentWorkflowTiming,
)
from app.services.llm import LLMClient
from app.services.stage_metrics import record_stage_duration
from app.services.test_plan_execution import build_tool_execution_service
from app.services.test_plan_generator import LLMTestPlanGenerator, TestPlanGenerator
from app.services.test_report import build_execution_report


T = TypeVar("T")


class TestAgentWorkflowExecutionError(RuntimeError):
    __test__ = False

    def __init__(
        self,
        *,
        stage: TestAgentWorkflowStage,
        error_code: str,
        cause: Exception,
        timing: TestAgentWorkflowTiming,
    ) -> None:
        self.stage = stage
        self.error_code = error_code
        self.cause = cause
        self.timing = timing
        super().__init__(f"{type(cause).__name__}: {cause}")


def execute_test_agent_workflow_request(
    request: TestAgentWorkflowRequest,
    settings: Settings,
) -> TestAgentWorkflowResult:
    workflow_started_at = time.perf_counter()
    stage_timings: list[TestAgentWorkflowStageTiming] = []
    generator = _build_generator(request, settings)
    plan = _run_stage(
        TestAgentWorkflowStage.plan_generation,
        lambda: generator.generate(request.generation_request),
        stage_timings,
        workflow_started_at,
        details_factory=lambda: _plan_generation_details(generator),
    )
    execution_service = build_tool_execution_service(settings, request.http_base_url)
    tool_runs = _run_stage(
        TestAgentWorkflowStage.tool_execution,
        lambda: execution_service.execute_plan(plan),
        stage_timings,
        workflow_started_at,
    )
    report = _run_stage(
        TestAgentWorkflowStage.report_build,
        lambda: build_execution_report(plan, tool_runs),
        stage_timings,
        workflow_started_at,
    )
    return TestAgentWorkflowResult(
        plan=plan,
        report=report,
        timing=TestAgentWorkflowTiming(
            total_ms=_elapsed_ms(workflow_started_at),
            stages=stage_timings,
        ),
    )


def _build_generator(
    request: TestAgentWorkflowRequest,
    settings: Settings,
) -> TestPlanGenerator | LLMTestPlanGenerator:
    if not request.generation_request.use_llm:
        return TestPlanGenerator()
    return LLMTestPlanGenerator(
        LLMClient(settings),
        allow_fallback=request.generation_request.allow_llm_fallback,
    )


def _run_stage(
    name: TestAgentWorkflowStage,
    operation: Callable[[], T],
    timings: list[TestAgentWorkflowStageTiming],
    workflow_started_at: float,
    details_factory: Callable[[], dict[str, Any]] | None = None,
) -> T:
    started_perf = time.perf_counter()
    started_at = _utc_now()
    try:
        result = operation()
    except Exception as exc:
        error_code = _stage_error_code(name, exc)
        duration_ms = _elapsed_ms(started_perf)
        timings.append(
            TestAgentWorkflowStageTiming(
                name=name,
                started_at=started_at,
                finished_at=_utc_now(),
                duration_ms=duration_ms,
                status="failed",
                error_code=error_code,
                details=_stage_details(details_factory),
            )
        )
        record_stage_duration(
            workflow="test_agent_workflow",
            stage=name.value,
            status="failed",
            duration_ms=duration_ms,
        )
        raise TestAgentWorkflowExecutionError(
            stage=name,
            error_code=error_code,
            cause=exc,
            timing=TestAgentWorkflowTiming(
                total_ms=_elapsed_ms(workflow_started_at),
                stages=timings,
            ),
        ) from exc
    duration_ms = _elapsed_ms(started_perf)
    timings.append(
        TestAgentWorkflowStageTiming(
            name=name,
            started_at=started_at,
            finished_at=_utc_now(),
            duration_ms=duration_ms,
            details=_stage_details(details_factory),
        )
    )
    record_stage_duration(
        workflow="test_agent_workflow",
        stage=name.value,
        status="succeeded",
        duration_ms=duration_ms,
    )
    return result


def _stage_details(
    details_factory: Callable[[], dict[str, Any]] | None,
) -> dict[str, Any]:
    if details_factory is None:
        return {}
    try:
        return details_factory()
    except Exception as exc:
        return {"details_error": type(exc).__name__}


def _plan_generation_details(
    generator: TestPlanGenerator | LLMTestPlanGenerator,
) -> dict[str, Any]:
    if not isinstance(generator, LLMTestPlanGenerator):
        return {}

    details: dict[str, Any] = {
        "used_llm": True,
        "used_fallback": generator.last_used_fallback,
    }
    llm_metrics = getattr(generator.llm, "last_call_metrics", None)
    if llm_metrics is not None:
        details["llm"] = llm_metrics.to_safe_dict()
    return details


def _stage_error_code(stage: TestAgentWorkflowStage, exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}".lower()
    suffix = "timeout" if "timeout" in text or "timed out" in text else "failed"
    return f"{stage.value}_{suffix}"


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
