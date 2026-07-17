from datetime import datetime, timezone

from app.models.test_plan import (
    TestAgentWorkflowJobTiming,
    TestAgentWorkflowResult,
    TestAgentWorkflowStage,
)


def build_test_agent_workflow_job_timing(
    *,
    created_at: str | None,
    started_at: str | None,
    finished_at: str | None,
    result: TestAgentWorkflowResult | None = None,
) -> TestAgentWorkflowJobTiming:
    created_epoch = _parse_epoch(created_at)
    started_epoch = _parse_epoch(started_at)
    finished_epoch = _parse_epoch(finished_at)
    stage_durations = _stage_durations(result)
    return TestAgentWorkflowJobTiming(
        queue_wait_ms=_elapsed_ms(created_epoch, started_epoch),
        job_runtime_ms=_elapsed_ms(started_epoch, finished_epoch),
        job_total_ms=_elapsed_ms(created_epoch, finished_epoch),
        workflow_total_ms=_rounded_ms(result.timing.total_ms)
        if result and result.timing.total_ms is not None
        else None,
        plan_generation_ms=stage_durations.get(TestAgentWorkflowStage.plan_generation),
        tool_execution_ms=stage_durations.get(TestAgentWorkflowStage.tool_execution),
        report_build_ms=stage_durations.get(TestAgentWorkflowStage.report_build),
    )


def _stage_durations(
    result: TestAgentWorkflowResult | None,
) -> dict[TestAgentWorkflowStage, float]:
    if result is None:
        return {}
    return {
        stage.name: _rounded_ms(stage.duration_ms)
        for stage in result.timing.stages
    }


def _parse_epoch(value: str | None) -> float | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _elapsed_ms(
    start_epoch: float | None,
    end_epoch: float | None,
) -> float | None:
    if start_epoch is None or end_epoch is None:
        return None
    return _rounded_ms(max((end_epoch - start_epoch) * 1000, 0.0))


def _rounded_ms(value: float) -> float:
    return round(float(value), 3)
