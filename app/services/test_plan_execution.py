from app.core.config import Settings
from app.models.test_plan import (
    TestExecutionReport,
    TestPlanExecutionRequest,
    TestPlanStepExecutionRequest,
    TestToolType,
    ToolRun,
)
from app.services.test_report import build_execution_report
from app.services.tool_adapters import HTTPToolAdapter, PytestToolAdapter
from app.services.tool_artifacts import ToolArtifactStore
from app.services.tool_execution import ToolAdapter, ToolExecutionService


class TestPlanExecutionConfigurationError(ValueError):
    pass


def execute_test_plan_step_request(
    request: TestPlanStepExecutionRequest,
    settings: Settings,
) -> ToolRun:
    return build_tool_execution_service(settings, request.http_base_url).execute_step(
        request.step
    )


def execute_test_plan_request(
    request: TestPlanExecutionRequest,
    settings: Settings,
) -> TestExecutionReport:
    tool_runs = build_tool_execution_service(settings, request.http_base_url).execute_plan(
        request.plan
    )
    return build_execution_report(request.plan, tool_runs)


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
        ),
    }
    if settings.test_tool_pytest_enabled:
        adapters[TestToolType.pytest] = PytestToolAdapter(
            allowed_paths=settings.test_tool_pytest_allowed_paths,
            artifact_store=artifact_store,
            timeout_seconds=settings.test_tool_pytest_timeout_seconds,
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
