import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import routes
from app.core.config import get_settings
from app.models.test_plan import TestPlan as Plan
from app.models.test_plan import TestPlanExecutionRequest as PlanExecutionRequest
from app.models.test_plan import TestPlanExecutionJobDetail as ExecutionJobDetail
from app.models.test_plan import TestPlanExecutionJobSummary as ExecutionJobSummary
from app.models.test_plan import TestPlanGenerationRequest as PlanGenerationRequest
from app.models.test_plan import TestPlanStep as PlanStep
from app.models.test_plan import TestPlanStepExecutionRequest as StepExecutionRequest
from app.models.test_plan import TestToolType as ToolType
from app.models.test_plan import ToolRun, ToolRunStatus
from app.services.llm import LLMError


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    routes._settings.cache_clear()
    yield
    get_settings.cache_clear()
    routes._settings.cache_clear()


class FakeToolExecutionService:
    def __init__(self):
        self.steps = []
        self.plans = []

    def execute_step(self, step: PlanStep) -> ToolRun:
        self.steps.append(step)
        return _tool_run(step.id, step.tool, ToolRunStatus.passed)

    def execute_plan(self, plan: Plan) -> list[ToolRun]:
        self.plans.append(plan)
        return [
            _tool_run(step.id, step.tool, ToolRunStatus.passed)
            for step in plan.steps
        ]


class FakeExecutionJobQueue:
    def __init__(self):
        self.submitted = []
        self.jobs = [
            ExecutionJobSummary(
                id="job-1",
                status="queued",
                created_at="2026-07-10T00:00:00+00:00",
                updated_at="2026-07-10T00:00:00+00:00",
            )
        ]

    def submit(self, request: PlanExecutionRequest) -> ExecutionJobDetail:
        self.submitted.append(request)
        return ExecutionJobDetail(
            **self.jobs[0].model_dump(),
            request=request,
        )

    def list_jobs(self, *, limit=20, offset=0, status=None):
        jobs = self.jobs
        if status:
            jobs = [job for job in jobs if job.status == status]
        return jobs[offset : offset + limit]

    def get_job(self, job_id: str):
        if job_id == "job-1":
            return ExecutionJobDetail(
                **self.jobs[0].model_dump(),
                request=_plan_execution_request(),
            )
        return None


class FakePlanGenerator:
    def __init__(self, plan: Plan | None = None, error: Exception | None = None):
        self.plan = plan
        self.error = error
        self.requests = []

    def generate(self, request: PlanGenerationRequest) -> Plan:
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.plan or Plan(id="plan-fake", title="fake plan")


def _tool_run(step_id: str, tool: ToolType, status: ToolRunStatus) -> ToolRun:
    return ToolRun(
        id=f"run-{step_id}",
        plan_step_id=step_id,
        tool=tool,
        status=status,
        exit_code=0,
        output_summary="ok",
    )


def _http_step() -> PlanStep:
    return PlanStep(
        id="TP-001",
        title="验证创建退款",
        objective="调用创建退款接口",
        requirement_ids=["REFUND-001"],
        tool=ToolType.http,
        tool_args={"path": "/api/v1/refunds"},
    )


def _plan_execution_request() -> PlanExecutionRequest:
    return PlanExecutionRequest(
        plan=Plan(id="plan-1", title="退款计划", steps=[_http_step()]),
        http_base_url="http://testserver",
    )


def _pytest_step() -> PlanStep:
    return PlanStep(
        id="TP-PYTEST-001",
        title="运行 pytest",
        objective="运行指定自动化测试",
        tool=ToolType.pytest,
        tool_args={"test_path": "tests/test_tool_adapters.py"},
    )


def test_generate_test_plan_uses_rule_based_generator_by_default() -> None:
    plan = routes.generate_test_plan(
        PlanGenerationRequest(description="登录页面验证码错误时展示明确错误。")
    )

    assert plan.id.startswith("plan-")
    assert plan.steps[0].id == "TP-001"
    assert plan.steps[0].tool == ToolType.playwright


def test_generate_test_plan_passes_llm_options_to_generator(monkeypatch) -> None:
    seen = {}
    generator = FakePlanGenerator()

    def fake_generator(*, use_llm: bool, allow_llm_fallback: bool):
        seen["use_llm"] = use_llm
        seen["allow_llm_fallback"] = allow_llm_fallback
        return generator

    monkeypatch.setattr(routes, "_test_plan_generator", fake_generator)

    plan = routes.generate_test_plan(
        PlanGenerationRequest(
            description="退款接口需要覆盖幂等冲突。",
            use_llm=True,
            allow_llm_fallback=False,
        )
    )

    assert plan.id == "plan-fake"
    assert seen == {"use_llm": True, "allow_llm_fallback": False}
    assert generator.requests[0].description == "退款接口需要覆盖幂等冲突。"


def test_generate_test_plan_maps_llm_errors(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "_test_plan_generator",
        lambda **_: FakePlanGenerator(error=LLMError("upstream failed")),
    )

    with pytest.raises(HTTPException) as exc_info:
        routes.generate_test_plan(
            PlanGenerationRequest(
                description="退款接口需要覆盖幂等冲突。",
                use_llm=True,
                allow_llm_fallback=False,
            )
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "upstream failed"


def test_execute_test_plan_step_routes_to_tool_execution_service(monkeypatch) -> None:
    service = FakeToolExecutionService()
    base_urls = []
    monkeypatch.setattr(
        routes,
        "_tool_execution_service",
        lambda base_url: base_urls.append(base_url) or service,
    )

    result = routes.execute_test_plan_step(
        StepExecutionRequest(step=_http_step(), http_base_url="http://testserver/")
    )

    assert result.status == ToolRunStatus.passed
    assert result.plan_step_id == "TP-001"
    assert service.steps[0].id == "TP-001"
    assert base_urls == ["http://testserver"]


def test_execute_test_plan_returns_execution_report(monkeypatch) -> None:
    service = FakeToolExecutionService()
    monkeypatch.setattr(routes, "_tool_execution_service", lambda _: service)
    plan = Plan(id="plan-1", title="退款计划", steps=[_http_step()])

    report = routes.execute_test_plan(
        PlanExecutionRequest(plan=plan, http_base_url="http://testserver")
    )

    assert report.status.value == "passed"
    assert report.plan_id == "plan-1"
    assert report.requirement_coverage == {"REFUND-001": True}
    assert service.plans[0].id == "plan-1"


def test_submit_test_plan_execution_job_routes_to_queue(monkeypatch) -> None:
    queue = FakeExecutionJobQueue()
    monkeypatch.setattr(routes, "_test_plan_execution_job_queue", lambda: queue)

    job = routes.submit_test_plan_execution_job(_plan_execution_request())

    assert job.id == "job-1"
    assert job.status == "queued"
    assert queue.submitted[0].plan.id == "plan-1"


def test_list_and_get_test_plan_execution_jobs(monkeypatch) -> None:
    queue = FakeExecutionJobQueue()
    monkeypatch.setattr(routes, "_test_plan_execution_job_queue", lambda: queue)

    listing = routes.list_test_plan_execution_jobs(
        limit=20,
        offset=0,
        status_filter="queued",
    )
    detail = routes.get_test_plan_execution_job("job-1")
    with pytest.raises(HTTPException) as missing:
        routes.get_test_plan_execution_job("missing")

    assert listing.jobs[0].id == "job-1"
    assert detail.id == "job-1"
    assert missing.value.status_code == 404


def test_execute_test_plan_request_rejects_invalid_base_url() -> None:
    with pytest.raises(ValidationError):
        StepExecutionRequest(step=_http_step(), http_base_url="ftp://testserver")

    with pytest.raises(ValidationError):
        PlanExecutionRequest(
            plan=Plan(id="plan-1", title="退款计划"),
            http_base_url="http://testserver?token=bad",
        )


def test_tool_execution_service_does_not_register_pytest_by_default() -> None:
    service = routes._tool_execution_service("http://testserver")

    assert ToolType.pytest not in service.adapters
    result = service.execute_step(_pytest_step())
    assert result.status == ToolRunStatus.blocked
    assert "No adapter registered" in result.output_summary


def test_tool_execution_service_registers_pytest_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("TEST_TOOL_PYTEST_ENABLED", "true")
    monkeypatch.setenv("TEST_TOOL_PYTEST_ALLOWED_PATHS", "tests,generated_tests")
    monkeypatch.setenv("TEST_TOOL_PYTEST_TIMEOUT_SECONDS", "5")
    get_settings.cache_clear()
    routes._settings.cache_clear()

    service = routes._tool_execution_service("http://testserver")

    assert ToolType.pytest in service.adapters


def test_tool_execution_service_rejects_disallowed_http_base_url(monkeypatch) -> None:
    monkeypatch.setenv("TEST_TOOL_HTTP_BASE_URL_ALLOWLIST", "http://allowed.test")
    get_settings.cache_clear()
    routes._settings.cache_clear()

    with pytest.raises(HTTPException) as exc_info:
        routes._tool_execution_service("http://blocked.test")

    assert exc_info.value.status_code == 400
    assert "not allowed" in exc_info.value.detail
