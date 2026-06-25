import pytest

from app.models.test_case import GenerateRequest, KnowledgeChunk, TestCaseType as CaseType
from app.services.agent_workflow import (
    GenerationWorkflowState,
    WorkflowNode,
    WorkflowRecorder,
    analyze_requirement,
    plan_test_generation,
)


def test_analyze_requirement_detects_risk_types() -> None:
    analysis = analyze_requirement(
        GenerateRequest(description="JWT 登录需要防止越权，并关注并发性能。")
    )

    assert CaseType.security in analysis.detected_risk_types
    assert CaseType.performance in analysis.detected_risk_types


def test_plan_test_generation_uses_focus_types_when_provided() -> None:
    request = GenerateRequest(
        description="生成登录测试用例",
        focus_types=[CaseType.security],
    )
    analysis = analyze_requirement(request)
    plan = plan_test_generation(
        analysis,
        [
            KnowledgeChunk(
                content="JWT 登录规则",
                source="knowledge/api/auth.md",
                document_type="api",
                module="auth",
            )
        ],
    )

    assert plan.target_types == [CaseType.security]
    assert plan.context_sources == ["knowledge/api/auth.md"]
    assert "security" in plan.to_prompt_text()


def test_workflow_recorder_records_success_and_failure() -> None:
    recorder = WorkflowRecorder()

    result = recorder.run("ok_node", lambda: 3, summary=lambda value: f"value={value}")
    with pytest.raises(ValueError):
        recorder.run("bad_node", lambda: (_ for _ in ()).throw(ValueError("bad")), summary="bad")

    assert result == 3
    assert recorder.steps[0].name == "ok_node"
    assert recorder.steps[0].status == "success"
    assert recorder.steps[0].summary == "value=3"
    assert recorder.steps[1].name == "bad_node"
    assert recorder.steps[1].status == "failed"
    assert "ValueError" in recorder.steps[1].summary


def test_workflow_node_mutates_state_and_records_trace() -> None:
    recorder = WorkflowRecorder()
    state = GenerationWorkflowState(
        request=GenerateRequest(description="生成登录测试用例")
    )

    def append_context(current: GenerationWorkflowState) -> None:
        current.contexts.append(
            KnowledgeChunk(
                content="登录接口规则",
                source="knowledge/api/login.md",
            )
        )

    recorder.run_node(
        WorkflowNode(
            name="append_context",
            action=append_context,
            summary=lambda current: f"contexts={len(current.contexts)}",
        ),
        state,
    )

    assert state.contexts[0].source == "knowledge/api/login.md"
    assert recorder.steps[0].name == "append_context"
    assert recorder.steps[0].status == "success"
    assert recorder.steps[0].summary == "contexts=1"


def test_workflow_recorder_adds_backend_and_trace_details() -> None:
    recorder = WorkflowRecorder(backend="langgraph")
    state = GenerationWorkflowState(
        request=GenerateRequest(description="生成登录测试用例")
    )

    recorder.run_node(
        WorkflowNode(
            name="trace_node",
            action=lambda current: current.contexts.append(
                KnowledgeChunk(content="登录规则", source="knowledge/login.md")
            ),
            summary="ok",
            trace=lambda current: {
                "context_count": len(current.contexts),
                "source": current.contexts[0].source,
            },
        ),
        state,
    )

    step = recorder.steps[0]
    assert step.backend == "langgraph"
    assert step.trace == {
        "context_count": 1,
        "source": "knowledge/login.md",
    }
