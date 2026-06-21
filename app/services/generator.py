from typing import Any, TypeVar

from pydantic import ValidationError

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    TestCase,
    TestCaseCollection,
)
from app.services.agent_workflow import (
    GenerationWorkflowState,
    WorkflowNode,
    WorkflowRecorder,
    analyze_requirement,
    plan_test_generation,
)
from app.services.llm import LLMClient
from app.services.llm import LLMError
from app.services.prompt import PROMPT_TEMPLATE_VERSION, build_generation_messages
from app.services.query_rewrite import rewrite_knowledge_query
from app.services.rag import RagService
from app.services.reviewer import build_review_feedback, review_generated_cases
from app.services.usage import estimate_generation_usage


T = TypeVar("T")


class OutputValidationError(RuntimeError):
    """Raised when model output cannot be converted into the expected schema."""

    def __init__(self, message: str, *, usage=None):
        super().__init__(message)
        self.usage = usage


class TestCaseGenerator:
    def __init__(self, settings: Settings, llm: LLMClient, rag: RagService):
        self.settings = settings
        self.llm = llm
        self.rag = rag

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        workflow = WorkflowRecorder()
        state = GenerationWorkflowState(request=request)

        workflow.run_node(
            WorkflowNode(
                name="analyze_requirement",
                action=_analyze_requirement_node,
                summary=_summarize_requirement_analysis,
            ),
            state,
        )
        workflow.run_node(
            WorkflowNode(
                name="retrieve_knowledge",
                action=lambda current: _retrieve_knowledge_node(current, self.rag),
                summary=lambda current: f"retrieved_chunks={len(current.contexts)}",
            ),
            state,
        )
        workflow.run_node(
            WorkflowNode(
                name="route_after_retrieval",
                action=lambda current: _route_after_retrieval_node(
                    current,
                    self.settings,
                ),
                summary=_summarize_retrieval_route,
            ),
            state,
        )
        if state.retrieval_retry_requested:
            workflow.run_node(
                WorkflowNode(
                    name="rewrite_query",
                    action=_rewrite_query_node,
                    summary=lambda current: (
                        f"rewritten_query_length={len(current.rewritten_query or '')}"
                    ),
                ),
                state,
            )
            workflow.run_node(
                WorkflowNode(
                    name="retrieve_rewritten_knowledge",
                    action=lambda current: _retrieve_knowledge_node(current, self.rag),
                    summary=lambda current: f"retrieved_chunks={len(current.contexts)}",
                ),
                state,
            )
            state.retrieval_retry_requested = False
        workflow.run_node(
            WorkflowNode(
                name="plan_test_strategy",
                action=_plan_test_strategy_node,
                summary=_summarize_test_strategy,
            ),
            state,
        )

        max_attempts = self.settings.llm_max_retries + 1
        for attempt in range(1, self.settings.llm_max_retries + 2):
            state.attempt = attempt
            state.retry_requested = False
            state.review = None
            workflow.run_node(
                WorkflowNode(
                    name="build_prompt",
                    action=_build_prompt_node,
                    summary=lambda current: (
                        f"messages={len(current.prompt_messages[-1])}, "
                        f"attempt={current.attempt}"
                    ),
                ),
                state,
            )
            try:
                workflow.run_node(
                    WorkflowNode(
                        name="call_llm",
                        action=lambda current: _call_llm_node(current, self.llm),
                        summary=lambda current: (
                            f"attempt={current.attempt}, "
                            f"keys={list(current.payload.keys()) if current.payload else []}"
                        ),
                    ),
                    state,
                )
            except LLMError as exc:
                exc.usage = estimate_generation_usage(
                    self.settings,
                    state.prompt_messages,
                    state.completion_payloads,
                )
                raise
            try:
                workflow.run_node(
                    WorkflowNode(
                        name="validate_output",
                        action=_validate_output_node,
                        summary=lambda current: (
                            f"validated_cases={len(current.cases)}, "
                            f"attempt={current.attempt}"
                        ),
                    ),
                    state,
                )
                workflow.run_node(
                    WorkflowNode(
                        name="post_process_cases",
                        action=_post_process_cases_node,
                        summary=lambda current: f"final_cases={len(current.cases)}",
                    ),
                    state,
                )
                if self.settings.agent_review_enabled:
                    workflow.run_node(
                        WorkflowNode(
                            name="review_cases",
                            action=lambda current: _review_cases_node(
                                current,
                                self.settings,
                            ),
                            summary=_summarize_review,
                        ),
                        state,
                    )
                    workflow.run_node(
                        WorkflowNode(
                            name="route_after_review",
                            action=lambda current: _route_after_review_node(
                                current,
                                self.settings,
                                max_attempts=max_attempts,
                            ),
                            summary=_summarize_review_route,
                        ),
                        state,
                    )
                    if state.retry_requested:
                        continue
                workflow.run_node(
                    WorkflowNode(
                        name="estimate_usage",
                        action=lambda current: _estimate_usage_node(
                            current,
                            self.settings,
                        ),
                        summary=lambda current: (
                            "total_tokens_estimate="
                            f"{_require_value(current.usage, 'usage').total_tokens_estimate}"
                        ),
                    ),
                    state,
                )
                return GenerateResponse(
                    cases=state.cases,
                    metadata=GenerationMetadata(
                        model=self.settings.zhipu_chat_model,
                        attempts=state.attempt,
                        retrieved_chunks=len(state.contexts),
                        retrieved_sources=_unique_sources(state.contexts),
                        prompt_version=PROMPT_TEMPLATE_VERSION,
                        usage=_require_value(state.usage, "usage"),
                        review=state.review,
                        workflow_steps=workflow.steps,
                    ),
                    retrieved_context=state.contexts if request.include_context else [],
                )
            except ValidationError as exc:
                state.last_error = exc
                state.correction = str(exc)
        usage = estimate_generation_usage(
            self.settings,
            state.prompt_messages,
            state.completion_payloads,
        )
        raise OutputValidationError(
            f"LLM output did not match schema: {state.last_error}",
            usage=usage,
        ) from state.last_error


def _analyze_requirement_node(state: GenerationWorkflowState) -> None:
    state.analysis = analyze_requirement(state.request)


def _summarize_requirement_analysis(state: GenerationWorkflowState) -> str:
    analysis = _require_value(state.analysis, "analysis")
    return (
        f"description_length={analysis.description_length}, "
        f"requested_case_count={analysis.requested_case_count}, "
        f"detected_risk_types={[item.value for item in analysis.detected_risk_types]}"
    )


def _retrieve_knowledge_node(
    state: GenerationWorkflowState,
    rag: RagService,
) -> None:
    query = state.rewritten_query or state.request.description
    state.knowledge_query = query
    state.retrieval_attempts += 1
    state.contexts = rag.search(
        query,
        top_k=state.request.knowledge_top_k,
    )


def _route_after_retrieval_node(
    state: GenerationWorkflowState,
    settings: Settings,
) -> None:
    state.retrieval_retry_requested = (
        settings.agent_query_rewrite_enabled
        and state.request.knowledge_top_k > 0
        and len(state.contexts) < settings.agent_query_rewrite_min_chunks
        and state.rewritten_query is None
    )


def _summarize_retrieval_route(state: GenerationWorkflowState) -> str:
    if state.request.knowledge_top_k <= 0:
        return "decision=accept, reason=rag_disabled"
    if state.retrieval_retry_requested:
        return "decision=rewrite_query, reason=insufficient_context"
    if not state.contexts:
        return "decision=accept, reason=context_unavailable"
    return "decision=accept, reason=context_available"


def _rewrite_query_node(state: GenerationWorkflowState) -> None:
    analysis = _require_value(state.analysis, "analysis")
    state.rewritten_query = rewrite_knowledge_query(state.request, analysis)


def _plan_test_strategy_node(state: GenerationWorkflowState) -> None:
    analysis = _require_value(state.analysis, "analysis")
    state.plan = plan_test_generation(analysis, state.contexts)


def _summarize_test_strategy(state: GenerationWorkflowState) -> str:
    plan = _require_value(state.plan, "plan")
    return (
        f"target_types={[item.value for item in plan.target_types]}, "
        f"context_sources={len(plan.context_sources)}"
    )


def _build_prompt_node(state: GenerationWorkflowState) -> None:
    plan = _require_value(state.plan, "plan")
    messages = build_generation_messages(
        state.request,
        state.contexts,
        correction=state.correction,
        strategy=plan.to_prompt_text(),
    )
    state.prompt_messages.append(messages)


def _call_llm_node(state: GenerationWorkflowState, llm: LLMClient) -> None:
    if not state.prompt_messages:
        raise RuntimeError("prompt_messages is required before calling LLM")
    state.payload = _normalize_payload(llm.generate_json(state.prompt_messages[-1]))
    state.completion_payloads.append(state.payload)


def _validate_output_node(state: GenerationWorkflowState) -> None:
    payload = _require_value(state.payload, "payload")
    collection = TestCaseCollection.model_validate(payload)
    state.cases = collection.cases


def _post_process_cases_node(state: GenerationWorkflowState) -> None:
    state.cases = _post_process_cases(
        state.cases,
        max_cases=state.request.max_cases,
    )


def _review_cases_node(
    state: GenerationWorkflowState,
    settings: Settings,
) -> None:
    state.review = review_generated_cases(
        request=state.request,
        cases=state.cases,
        model=settings.zhipu_chat_model,
        attempt=state.attempt,
        retrieved_chunks=len(state.contexts),
        retrieved_sources=_unique_sources(state.contexts),
        min_score=settings.agent_review_min_score,
    )


def _summarize_review(state: GenerationWorkflowState) -> str:
    review = _require_value(state.review, "review")
    warnings = ",".join(review.warnings) or "none"
    return (
        f"passed={review.passed}, score={review.score}, "
        f"grade={review.grade}, warnings={warnings}"
    )


def _route_after_review_node(
    state: GenerationWorkflowState,
    settings: Settings,
    *,
    max_attempts: int,
) -> None:
    review = _require_value(state.review, "review")
    can_retry = state.attempt < max_attempts
    state.retry_requested = (
        settings.agent_review_retry_enabled
        and review.retry_recommended
        and can_retry
    )
    if state.retry_requested:
        state.correction = build_review_feedback(review)


def _summarize_review_route(state: GenerationWorkflowState) -> str:
    review = _require_value(state.review, "review")
    if state.retry_requested:
        return "decision=retry, reason=review_feedback"
    if review.retry_recommended:
        return "decision=accept, reason=retry_disabled_or_budget_exhausted"
    return "decision=accept, reason=review_passed"


def _estimate_usage_node(
    state: GenerationWorkflowState,
    settings: Settings,
) -> None:
    state.usage = estimate_generation_usage(
        settings,
        state.prompt_messages,
        state.completion_payloads,
    )


def _require_value(value: T | None, name: str) -> T:
    if value is None:
        raise RuntimeError(f"{name} is required in workflow state")
    return value


def _normalize_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"cases": payload}
    if not isinstance(payload, dict):
        return {"cases": payload}
    if "cases" in payload:
        return payload
    for alias in ("test_cases", "testcases", "items", "data"):
        value = payload.get(alias)
        if isinstance(value, list):
            return {"cases": value}
    return payload


def _post_process_cases(cases: list[TestCase], *, max_cases: int) -> list[TestCase]:
    unique_cases: list[TestCase] = []
    seen_titles: set[str] = set()
    for case in cases:
        title_key = case.title.strip().lower()
        if title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        unique_cases.append(case)
        if len(unique_cases) >= max_cases:
            break

    for index, case in enumerate(unique_cases, start=1):
        case.id = f"TC-{index:03d}"
    return unique_cases


def _unique_sources(contexts: list[Any]) -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()
    for context in contexts:
        source = str(getattr(context, "source", "")).strip()
        if not source or source in seen:
            continue
        seen.add(source)
        sources.append(source)
    return sources
