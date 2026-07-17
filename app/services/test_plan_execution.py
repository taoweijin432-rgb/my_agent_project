import time

from app.core.config import Settings
from app.models.test_plan import (
    TestExecutionReport,
    TestPlanExecutionRequest,
    TestPlanStepExecutionRequest,
    TestToolType,
    ToolRun,
)
from app.services.test_report import build_execution_report
from app.services.stage_metrics import record_stage_duration
from app.services.tool_adapters import HTTPToolAdapter, PytestToolAdapter
from app.services.tool_artifacts import ToolArtifactStore
from app.services.tool_execution import ToolAdapter, ToolExecutionService


class TestPlanExecutionConfigurationError(ValueError):
    pass


def execute_test_plan_step_request(
    request: TestPlanStepExecutionRequest,
    settings: Settings,
) -> ToolRun:
    started_at = time.perf_counter()
    try:
        run = build_tool_execution_service(settings, request.http_base_url).execute_step(
            request.step
        )
    except Exception:
        record_stage_duration(
            workflow="test_plan_step_execution",
            stage="tool_execution",
            status="failed",
            duration_ms=_elapsed_ms(started_at),
        )
        raise
    record_stage_duration(
        workflow="test_plan_step_execution",
        stage="tool_execution",
        status=str(run.status.value),
        duration_ms=_elapsed_ms(started_at),
    )
    return run


def execute_test_plan_request(
    request: TestPlanExecutionRequest,
    settings: Settings,
) -> TestExecutionReport:
    tool_execution_started_at = time.perf_counter()
    try:
        tool_runs = build_tool_execution_service(
            settings, request.http_base_url
        ).execute_plan(request.plan)
    except Exception:
        record_stage_duration(
            workflow="test_plan_execution",
            stage="tool_execution",
            status="failed",
            duration_ms=_elapsed_ms(tool_execution_started_at),
        )
        raise
    record_stage_duration(
        workflow="test_plan_execution",
        stage="tool_execution",
        status="succeeded",
        duration_ms=_elapsed_ms(tool_execution_started_at),
    )
    report_build_started_at = time.perf_counter()
    report = build_execution_report(request.plan, tool_runs)
    record_stage_duration(
        workflow="test_plan_execution",
        stage="report_build",
        status=str(report.status.value),
        duration_ms=_elapsed_ms(report_build_started_at),
    )
    return report


def build_tool_execution_service(
    settings: Settings,
    http_base_url: str,
) -> ToolExecutionService:
    _validate_http_base_url_allowed(settings, http_base_url)
    artifact_store = ToolArtifactStore(
        settings.test_tool_artifact_dir,
        max_bytes=settings.test_tool_artifact_max_bytes,
    )
    adapters: dict[TestToolType, ToolAdapter] = {
        TestToolType.http: HTTPToolAdapter(
            base_url=http_base_url,
            artifact_store=artifact_store,
            allowed_headers=settings.test_tool_http_allowed_headers,
        ),
    }
    if settings.test_tool_pytest_enabled:
        adapters[TestToolType.pytest] = PytestToolAdapter(
            allowed_paths=settings.test_tool_pytest_allowed_paths,
            artifact_store=artifact_store,
            timeout_seconds=settings.test_tool_pytest_timeout_seconds,
            env_allowlist=settings.test_tool_pytest_env_allowlist,
        )
    return ToolExecutionService(adapters=adapters)


def _validate_http_base_url_allowed(settings: Settings, http_base_url: str) -> None:
    allowlist = [item.rstrip("/") for item in settings.test_tool_http_base_url_allowlist]
    if not allowlist:
        return
    if http_base_url.rstrip("/") not in allowlist:
        raise TestPlanExecutionConfigurationError(
            "http_base_url is not allowed by TEST_TOOL_HTTP_BASE_URL_ALLOWLIST."
        )


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)
