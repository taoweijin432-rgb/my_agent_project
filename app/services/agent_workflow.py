import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

from app.models.test_case import (
    GenerateRequest,
    GenerationReview,
    GenerationUsage,
    KnowledgeChunk,
    TestCase,
    TestCaseType,
    WorkflowStep,
)


StateT = TypeVar("StateT")
T = TypeVar("T")


@dataclass(frozen=True)
class RequirementAnalysis:
    description_length: int
    requested_case_count: int
    user_focus_types: list[TestCaseType] = field(default_factory=list)
    detected_risk_types: list[TestCaseType] = field(default_factory=list)


@dataclass(frozen=True)
class TestGenerationPlan:
    target_types: list[TestCaseType]
    risk_notes: list[str]
    context_sources: list[str]

    def to_prompt_text(self) -> str:
        target_types = ", ".join(item.value for item in self.target_types)
        sources = ", ".join(self.context_sources) if self.context_sources else "无"
        notes = "\n".join(f"- {item}" for item in self.risk_notes) or "- 无额外风险提示"
        return (
            f"目标覆盖类型：{target_types or '自动判断'}\n"
            f"可用知识来源：{sources}\n"
            f"风险提示：\n{notes}"
        )


@dataclass
class GenerationWorkflowState:
    request: GenerateRequest
    analysis: RequirementAnalysis | None = None
    contexts: list[KnowledgeChunk] = field(default_factory=list)
    knowledge_query: str | None = None
    rewritten_query: str | None = None
    retrieval_attempts: int = 0
    retrieval_retry_requested: bool = False
    plan: TestGenerationPlan | None = None
    attempt: int = 0
    correction: str | None = None
    prompt_messages: list[list[dict[str, str]]] = field(default_factory=list)
    completion_payloads: list[Any] = field(default_factory=list)
    payload: dict[str, Any] | None = None
    cases: list[TestCase] = field(default_factory=list)
    usage: GenerationUsage | None = None
    review: GenerationReview | None = None
    retry_requested: bool = False
    last_error: Exception | None = None


@dataclass(frozen=True)
class WorkflowNode(Generic[StateT]):
    name: str
    action: Callable[[StateT], None]
    summary: str | Callable[[StateT], str]


class WorkflowRecorder:
    def __init__(self) -> None:
        self.steps: list[WorkflowStep] = []

    def run(
        self,
        name: str,
        action: Callable[[], T],
        *,
        summary: str | Callable[[T], str],
    ) -> T:
        started = time.perf_counter()
        try:
            result = action()
        except Exception as exc:
            self.steps.append(
                WorkflowStep(
                    name=name,
                    status="failed",
                    summary=f"{type(exc).__name__}: {exc}",
                    duration_ms=_elapsed_ms(started),
                )
            )
            raise

        step_summary = summary(result) if callable(summary) else summary
        self.steps.append(
            WorkflowStep(
                name=name,
                status="success",
                summary=step_summary,
                duration_ms=_elapsed_ms(started),
            )
        )
        return result

    def run_node(self, node: WorkflowNode[StateT], state: StateT) -> None:
        started = time.perf_counter()
        try:
            node.action(state)
            step_summary = node.summary(state) if callable(node.summary) else node.summary
        except Exception as exc:
            self.steps.append(
                WorkflowStep(
                    name=node.name,
                    status="failed",
                    summary=f"{type(exc).__name__}: {exc}",
                    duration_ms=_elapsed_ms(started),
                )
            )
            raise

        self.steps.append(
            WorkflowStep(
                name=node.name,
                status="success",
                summary=step_summary,
                duration_ms=_elapsed_ms(started),
            )
        )


def analyze_requirement(request: GenerateRequest) -> RequirementAnalysis:
    user_focus_types = request.focus_types or []
    detected = _detect_risk_types(request.description)
    return RequirementAnalysis(
        description_length=len(request.description),
        requested_case_count=request.max_cases,
        user_focus_types=user_focus_types,
        detected_risk_types=detected,
    )


def plan_test_generation(
    analysis: RequirementAnalysis,
    contexts: list[KnowledgeChunk],
) -> TestGenerationPlan:
    target_types = _unique_types(
        analysis.user_focus_types
        or [
            TestCaseType.functional,
            TestCaseType.boundary,
            TestCaseType.exception,
            TestCaseType.permission,
            *analysis.detected_risk_types,
        ]
    )
    risk_notes = _risk_notes(analysis, contexts)
    context_sources = _unique_sources(contexts)
    return TestGenerationPlan(
        target_types=target_types,
        risk_notes=risk_notes,
        context_sources=context_sources,
    )


def _detect_risk_types(description: str) -> list[TestCaseType]:
    text = description.lower()
    detected: list[TestCaseType] = []
    keyword_map = {
        TestCaseType.security: ("权限", "token", "jwt", "注入", "加密", "越权", "安全"),
        TestCaseType.performance: ("性能", "并发", "吞吐", "响应时间", "超时"),
        TestCaseType.compatibility: ("浏览器", "兼容", "移动端", "系统版本"),
    }
    for case_type, keywords in keyword_map.items():
        if any(keyword in text for keyword in keywords):
            detected.append(case_type)
    return detected


def _risk_notes(
    analysis: RequirementAnalysis,
    contexts: list[KnowledgeChunk],
) -> list[str]:
    notes: list[str] = []
    if analysis.description_length > 1200:
        notes.append("需求描述较长，优先拆分主流程、异常流和权限边界。")
    if not contexts:
        notes.append("知识库未召回上下文，生成时只能基于用户输入和显式假设。")
    if TestCaseType.security in analysis.detected_risk_types:
        notes.append("需求涉及安全或权限，应覆盖越权、Token/JWT、输入注入等风险。")
    if TestCaseType.performance in analysis.detected_risk_types:
        notes.append("需求涉及性能，应补充并发、超时和响应时间相关用例。")
    if TestCaseType.compatibility in analysis.detected_risk_types:
        notes.append("需求涉及兼容性，应覆盖不同终端、浏览器或系统版本。")
    return notes


def _unique_types(values: list[TestCaseType]) -> list[TestCaseType]:
    result: list[TestCaseType] = []
    seen: set[TestCaseType] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _unique_sources(contexts: list[KnowledgeChunk]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for context in contexts:
        source = context.source.strip()
        if not source or source in seen:
            continue
        seen.add(source)
        result.append(source)
    return result


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
