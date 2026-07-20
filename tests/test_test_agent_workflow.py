import pytest

from app.core.config import Settings
from app.models.test_case import RequirementPoint
from app.models.test_plan import (
    TestAgentWorkflowRequest as WorkflowRequest,
    TestAgentWorkflowStage as WorkflowStage,
    TestPlanGenerationRequest as PlanGenerationRequest,
)
from app.services.stage_metrics import get_stage_metrics_snapshot, reset_stage_metrics
from app.services.llm import LLMCallAttemptMetrics, LLMCallMetrics
from app.services import test_agent_workflow as workflow_module
from app.services.test_agent_workflow import (
    TestAgentWorkflowExecutionError,
    execute_test_agent_workflow_request,
)
from app.services.test_plan_generator import LLMTestPlanGenerator


@pytest.fixture(autouse=True)
def clear_stage_metrics() -> None:
    reset_stage_metrics()
    yield
    reset_stage_metrics()


def test_test_agent_workflow_result_records_stage_timings(tmp_path) -> None:
    request = WorkflowRequest(
        generation_request=PlanGenerationRequest(
            description="GET /health 200 API 健康检查必须返回成功。",
            requirements=[
                RequirementPoint(
                    id="REQ-HEALTH-001",
                    title="API 健康检查",
                    description="GET /health 200 API 健康检查必须返回成功。",
                    keywords=["GET", "/health", "200"],
                )
            ],
            max_steps=1,
        ),
        http_base_url="http://testserver",
    )

    result = execute_test_agent_workflow_request(
        request,
        Settings(test_tool_artifact_dir="data/test-artifacts/test-workflow-timing"),
    )

    assert result.timing.total_ms is not None
    assert result.timing.total_ms >= 0
    assert [stage.name for stage in result.timing.stages] == [
        WorkflowStage.plan_generation,
        WorkflowStage.tool_execution,
        WorkflowStage.report_build,
    ]
    assert all(stage.duration_ms >= 0 for stage in result.timing.stages)

    snapshot = get_stage_metrics_snapshot()
    assert snapshot["total_count"] == 3
    assert [item["stage"] for item in snapshot["stages"]] == [
        "plan_generation",
        "report_build",
        "tool_execution",
    ]
    assert snapshot["stages"][0]["workflow"] == "test_agent_workflow"
    assert snapshot["stages"][0]["status"] == "succeeded"


def test_test_agent_workflow_records_llm_stage_details(monkeypatch) -> None:
    class ObservableLLM:
        settings = Settings(zhipu_chat_model="fake-model")

        def __init__(self) -> None:
            self.last_call_metrics = LLMCallMetrics(
                model="fake-model",
                base_url="https://llm.example.test",
                timeout_seconds=5,
                max_retries=1,
                retry_backoff_seconds=0,
                attempts=(
                    LLMCallAttemptMetrics(
                        attempt=1,
                        duration_ms=12.5,
                        status="succeeded",
                    ),
                ),
            )

        def generate_json(self, _messages):
            return {
                "title": "人工验收测试计划",
                "steps": [
                    {
                        "title": "人工验收导出报告",
                        "objective": "确认导出报告内容满足需求",
                        "requirement_ids": ["REQ-MANUAL-001"],
                        "test_types": ["functional"],
                        "priority": "medium",
                        "tool": "manual",
                        "success_criteria": ["报告可人工验收"],
                    }
                ],
            }

    monkeypatch.setattr(
        workflow_module,
        "_build_generator",
        lambda _request, _settings: LLMTestPlanGenerator(ObservableLLM()),
    )

    request = WorkflowRequest(
        generation_request=PlanGenerationRequest(
            description="导出报告需要人工验收。",
            requirements=[
                RequirementPoint(
                    id="REQ-MANUAL-001",
                    title="导出报告",
                    description="导出报告需要人工验收。",
                    keywords=["导出", "报告"],
                )
            ],
            use_llm=True,
            max_steps=1,
        ),
        http_base_url="http://testserver",
    )

    result = execute_test_agent_workflow_request(request, Settings())

    plan_generation = result.timing.stages[0]
    assert plan_generation.name == WorkflowStage.plan_generation
    assert plan_generation.details["used_llm"] is True
    assert plan_generation.details["used_fallback"] is False
    assert plan_generation.details["llm"]["attempt_count"] == 1
    assert plan_generation.details["llm"]["total_duration_ms"] == 12.5

    snapshot = get_stage_metrics_snapshot()
    assert snapshot["total_count"] == 3
    assert {
        (item["stage"], item["status"]) for item in snapshot["stages"]
    } == {
        ("plan_generation", "succeeded"),
        ("tool_execution", "succeeded"),
        ("report_build", "succeeded"),
    }


def test_test_agent_workflow_failure_records_failed_stage_timing(monkeypatch) -> None:
    class FailingGenerator:
        def generate(self, _request):
            raise TimeoutError("llm timeout")

    monkeypatch.setattr(
        workflow_module,
        "_build_generator",
        lambda _request, _settings: FailingGenerator(),
    )
    request = WorkflowRequest(
        generation_request=PlanGenerationRequest(
            description="退款接口需要使用真实 LLM 生成计划。",
            use_llm=True,
            allow_llm_fallback=False,
        ),
        http_base_url="http://testserver",
    )

    with pytest.raises(TestAgentWorkflowExecutionError) as raised:
        execute_test_agent_workflow_request(request, Settings())

    error = raised.value
    assert error.stage == WorkflowStage.plan_generation
    assert error.error_code == "plan_generation_timeout"
    assert error.timing.total_ms is not None
    assert error.timing.stages[0].name == WorkflowStage.plan_generation
    assert error.timing.stages[0].status == "failed"
    assert error.timing.stages[0].error_code == "plan_generation_timeout"

    snapshot = get_stage_metrics_snapshot()
    assert snapshot["total_count"] == 1
    assert snapshot["stages"] == [
        {
            "workflow": "test_agent_workflow",
            "stage": "plan_generation",
            "status": "failed",
            "count": 1,
            "duration_seconds": snapshot["stages"][0]["duration_seconds"],
        }
    ]


def test_test_agent_workflow_failure_records_plan_validation_failure(monkeypatch) -> None:
    class CoverageGapLLM:
        settings = Settings(zhipu_chat_model="fake-model")

        def generate_json(self, _messages):
            return {
                "title": "退款测试计划",
                "steps": [
                    {
                        "title": "验证创建退款",
                        "requirement_ids": ["REFUND-001"],
                        "tool": "http",
                        "tool_args": {
                            "method": "POST",
                            "path": "/api/v1/refunds",
                            "expected_status": 201,
                        },
                    }
                ],
            }

    monkeypatch.setattr(
        workflow_module,
        "_build_generator",
        lambda _request, _settings: LLMTestPlanGenerator(
            CoverageGapLLM(),
            allow_fallback=False,
        ),
    )

    request = WorkflowRequest(
        generation_request=PlanGenerationRequest(
            description="退款接口需要覆盖创建和审计。",
            requirements=[
                RequirementPoint(
                    id="REFUND-001",
                    title="创建退款 API",
                    description="POST /api/v1/refunds 创建退款。",
                    keywords=["POST /api/v1/refunds", "201"],
                ),
                RequirementPoint(
                    id="REFUND-002",
                    title="退款审计查询 API",
                    description="GET /api/v1/refunds/rf_001/audit 返回 200。",
                    keywords=["GET /api/v1/refunds/rf_001/audit", "200"],
                ),
            ],
            use_llm=True,
            allow_llm_fallback=False,
        ),
        http_base_url="http://testserver",
    )

    with pytest.raises(TestAgentWorkflowExecutionError) as raised:
        execute_test_agent_workflow_request(request, Settings())

    error = raised.value
    assert error.stage == WorkflowStage.plan_generation
    assert error.error_code == "plan_generation_failed"
    assert "missing requirement coverage" in str(error.cause)

    snapshot = get_stage_metrics_snapshot()
    assert snapshot["total_count"] == 1
    assert snapshot["stages"][0]["stage"] == "plan_generation"
    assert snapshot["stages"][0]["status"] == "failed"
