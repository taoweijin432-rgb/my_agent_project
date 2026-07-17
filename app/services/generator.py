from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from pydantic import ValidationError

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    GenerationReview,
    GenerationUsage,
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
RagDependency = RagService | Callable[[], RagService]


class OutputValidationError(RuntimeError):
    """Raised when model output cannot be converted into the expected schema."""

    def __init__(self, message: str, *, usage: GenerationUsage | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class GenerationGateError(RuntimeError):
    """Raised when a workflow gate requires human intervention."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        gate: str,
        action_required: str,
        usage: GenerationUsage | None = None,
        review: GenerationReview | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.gate = gate
        self.action_required = action_required
        self.usage = usage
        self.review = review

    def to_detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "gate": self.gate,
            "message": str(self),
            "action_required": self.action_required,
            "usage": self.usage.model_dump(mode="json") if self.usage else None,
            "review": self.review.model_dump(mode="json") if self.review else None,
        }


class GenerationBudgetExceededError(GenerationGateError):
    """Raised before LLM invocation when the prompt exceeds configured limits."""

    def __init__(self, message: str, *, usage: GenerationUsage | None = None):
        super().__init__(
            message,
            code="budget_exceeded",
            gate="budget",
            action_required="human_confirmation",
            usage=usage,
        )


class GenerationQualityGateError(GenerationGateError):
    """Raised when Reviewer output is below a required quality threshold."""

    def __init__(
        self,
        message: str,
        *,
        usage: GenerationUsage | None = None,
        review: GenerationReview | None = None,
    ):
        super().__init__(
            message,
            code="quality_gate_failed",
            gate="quality",
            action_required="human_review",
            usage=usage,
            review=review,
        )


class GenerationWorkflowRunner(Protocol):
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        pass


class TestCaseGenerator:
    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        rag: RagDependency,
        runner: GenerationWorkflowRunner | None = None,
    ):
        self.settings = settings
        self.llm = llm
        self.rag = rag
        self.runner = runner or _build_generation_workflow_runner(settings, llm, rag)

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        return self.runner.generate(request)


def _build_generation_workflow_runner(
    settings: Settings,
    llm: LLMClient,
    rag: RagDependency,
) -> GenerationWorkflowRunner:
    if settings.agent_workflow_backend == "local":
        return LocalGenerationWorkflowRunner(settings=settings, llm=llm, rag=rag)
    if settings.agent_workflow_backend == "langgraph":
        return LangGraphGenerationWorkflowRunner(settings=settings, llm=llm, rag=rag)
    raise RuntimeError(
        "AGENT_WORKFLOW_BACKEND must be 'local' or 'langgraph', "
        f"got {settings.agent_workflow_backend!r}."
    )


def _workflow_node(
    *,
    name: str,
    action: Callable[[GenerationWorkflowState], None],
    summary: str | Callable[[GenerationWorkflowState], str],
    trace: Callable[[GenerationWorkflowState], dict[str, Any]] | None = None,
) -> WorkflowNode[GenerationWorkflowState]:
    return WorkflowNode(
        name=name,
        action=action,
        summary=summary,
        trace=trace or _trace_for_node(name),
    )


def _trace_for_node(
    name: str,
) -> Callable[[GenerationWorkflowState], dict[str, Any]] | None:
    return {
        "analyze_requirement": _trace_analyze_requirement,
        "retrieve_knowledge": _trace_retrieve_knowledge,
        "retrieve_rewritten_knowledge": _trace_retrieve_knowledge,
        "route_after_retrieval": _trace_retrieval_route,
        "rewrite_query": _trace_rewrite_query,
        "plan_test_strategy": _trace_test_strategy,
        "build_prompt": _trace_build_prompt,
        "call_llm": _trace_call_llm,
        "validate_output": _trace_validate_output,
        "post_process_cases": _trace_post_process_cases,
        "review_cases": _trace_review_cases,
        "route_after_review": _trace_review_route,
        "check_quality_gate": _trace_quality_gate,
        "estimate_usage": _trace_estimate_usage,
    }.get(name)


def _trace_analyze_requirement(state: GenerationWorkflowState) -> dict[str, Any]:
    analysis = _require_value(state.analysis, "analysis")
    return {
        "description_length": analysis.description_length,
        "requested_case_count": analysis.requested_case_count,
        "user_focus_types": [item.value for item in analysis.user_focus_types],
        "detected_risk_types": [item.value for item in analysis.detected_risk_types],
    }


def _trace_retrieve_knowledge(state: GenerationWorkflowState) -> dict[str, Any]:
    return {
        "query_preview": _preview(state.knowledge_query),
        "top_k": state.request.knowledge_top_k,
        "retrieval_attempts": state.retrieval_attempts,
        "retrieved_chunks": len(state.contexts),
        "sources": _unique_sources(state.contexts),
    }


def _trace_retrieval_route(state: GenerationWorkflowState) -> dict[str, Any]:
    if state.request.knowledge_top_k <= 0:
        decision = "accept"
        reason = "rag_disabled"
    elif state.retrieval_retry_requested:
        decision = "rewrite_query"
        reason = "insufficient_context"
    elif not state.contexts:
        decision = "accept"
        reason = "context_unavailable"
    else:
        decision = "accept"
        reason = "context_available"
    return {
        "decision": decision,
        "reason": reason,
        "retrieved_chunks": len(state.contexts),
        "top_k": state.request.knowledge_top_k,
    }


def _trace_rewrite_query(state: GenerationWorkflowState) -> dict[str, Any]:
    return {
        "rewritten_query_preview": _preview(state.rewritten_query),
        "rewritten_query_length": len(state.rewritten_query or ""),
    }


def _trace_test_strategy(state: GenerationWorkflowState) -> dict[str, Any]:
    plan = _require_value(state.plan, "plan")
    return {
        "target_types": [item.value for item in plan.target_types],
        "risk_note_count": len(plan.risk_notes),
        "context_sources": plan.context_sources,
    }


def _trace_build_prompt(state: GenerationWorkflowState) -> dict[str, Any]:
    messages = state.prompt_messages[-1] if state.prompt_messages else []
    return {
        "attempt": state.attempt,
        "message_count": len(messages),
        "prompt_characters": sum(len(message.get("content", "")) for message in messages),
        "has_correction": bool(state.correction),
    }


def _trace_budget_gate(
    state: GenerationWorkflowState,
    settings: Settings,
) -> dict[str, Any]:
    usage = state.usage or estimate_generation_usage(
        settings,
        state.prompt_messages,
        state.completion_payloads,
    )
    return {
        "prompt_tokens_estimate": usage.prompt_tokens_estimate,
        "completion_tokens_estimate": usage.completion_tokens_estimate,
        "total_tokens_estimate": usage.total_tokens_estimate,
        "max_prompt_tokens": settings.agent_budget_max_prompt_tokens,
        "max_estimated_cost": settings.agent_budget_max_estimated_cost,
        "estimated_cost": usage.estimated_cost,
        "currency": usage.currency,
    }


def _trace_call_llm(state: GenerationWorkflowState) -> dict[str, Any]:
    return {
        "attempt": state.attempt,
        "payload_keys": list(state.payload.keys()) if state.payload else [],
        "completion_payload_count": len(state.completion_payloads),
    }


def _trace_validate_output(state: GenerationWorkflowState) -> dict[str, Any]:
    return {
        "attempt": state.attempt,
        "validated_cases": len(state.cases),
    }


def _trace_post_process_cases(state: GenerationWorkflowState) -> dict[str, Any]:
    return {
        "final_cases": len(state.cases),
        "max_cases": state.request.max_cases,
    }


def _trace_review_cases(state: GenerationWorkflowState) -> dict[str, Any]:
    review = _require_value(state.review, "review")
    return {
        "passed": review.passed,
        "score": review.score,
        "grade": review.grade,
        "retry_recommended": review.retry_recommended,
        "warning_count": len(review.warnings),
        "missing_target_types": [item.value for item in review.missing_target_types],
        "missing_acceptance_keywords": review.missing_acceptance_keywords,
    }


def _trace_review_route(state: GenerationWorkflowState) -> dict[str, Any]:
    review = _require_value(state.review, "review")
    if state.retry_requested:
        decision = "retry"
        reason = _review_retry_reason(review)
    elif review.retry_recommended:
        decision = "accept"
        reason = "retry_disabled_or_budget_exhausted"
    else:
        decision = "accept"
        reason = "review_passed"
    return {
        "decision": decision,
        "reason": reason,
        "review_score": review.score,
        "review_passed": review.passed,
        "retry_recommended": review.retry_recommended,
        "missing_target_type_count": len(review.missing_target_types),
        "missing_acceptance_keyword_count": len(review.missing_acceptance_keywords),
    }


def _trace_quality_gate(state: GenerationWorkflowState) -> dict[str, Any]:
    review = _require_value(state.review, "review")
    return {
        "review_score": review.score,
        "grade": review.grade,
        "passed": review.passed,
    }


def _trace_estimate_usage(state: GenerationWorkflowState) -> dict[str, Any]:
    usage = _require_value(state.usage, "usage")
    return {
        "prompt_tokens_estimate": usage.prompt_tokens_estimate,
        "completion_tokens_estimate": usage.completion_tokens_estimate,
        "total_tokens_estimate": usage.total_tokens_estimate,
        "estimated_cost": usage.estimated_cost,
        "currency": usage.currency,
    }


def _preview(value: str | None, *, max_length: int = 160) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 3]}..."


class LocalGenerationWorkflowRunner:
    def __init__(self, settings: Settings, llm: LLMClient, rag: RagDependency):
        self.settings = settings
        self.llm = llm
        self.rag = rag

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        workflow = WorkflowRecorder(backend="local")
        state = GenerationWorkflowState(request=request)

        workflow.run_node(
            _workflow_node(
                name="analyze_requirement",
                action=_analyze_requirement_node,
                summary=_summarize_requirement_analysis,
            ),
            state,
        )
        workflow.run_node(
            _workflow_node(
                name="retrieve_knowledge",
                action=lambda current: _retrieve_knowledge_node(current, self.rag),
                summary=lambda current: f"retrieved_chunks={len(current.contexts)}",
            ),
            state,
        )
        workflow.run_node(
            _workflow_node(
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
                _workflow_node(
                    name="rewrite_query",
                    action=_rewrite_query_node,
                    summary=lambda current: (
                        f"rewritten_query_length={len(current.rewritten_query or '')}"
                    ),
                ),
                state,
            )
            workflow.run_node(
                _workflow_node(
                    name="retrieve_rewritten_knowledge",
                    action=lambda current: _retrieve_knowledge_node(current, self.rag),
                    summary=lambda current: f"retrieved_chunks={len(current.contexts)}",
                ),
                state,
            )
            state.retrieval_retry_requested = False
        workflow.run_node(
            _workflow_node(
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
                _workflow_node(
                    name="build_prompt",
                    action=_build_prompt_node,
                    summary=lambda current: (
                        f"messages={len(current.prompt_messages[-1])}, "
                        f"attempt={current.attempt}"
                    ),
                ),
                state,
            )
            workflow.run_node(
                _workflow_node(
                    name="check_budget",
                    action=lambda current: _check_budget_node(
                        current,
                        self.settings,
                    ),
                    summary=_summarize_budget_gate,
                    trace=lambda current: _trace_budget_gate(current, self.settings),
                ),
                state,
            )
            try:
                workflow.run_node(
                    _workflow_node(
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
                    _workflow_node(
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
                    _workflow_node(
                        name="post_process_cases",
                        action=_post_process_cases_node,
                        summary=lambda current: f"final_cases={len(current.cases)}",
                    ),
                    state,
                )
                if self.settings.agent_review_enabled:
                    workflow.run_node(
                        _workflow_node(
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
                        _workflow_node(
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
                    if self.settings.agent_review_require_pass:
                        workflow.run_node(
                            _workflow_node(
                                name="check_quality_gate",
                                action=lambda current: _check_quality_gate_node(
                                    current,
                                    self.settings,
                                ),
                                summary=_summarize_quality_gate,
                            ),
                            state,
                        )
                workflow.run_node(
                    _workflow_node(
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
                        workflow_backend=self.settings.agent_workflow_backend,
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


class LangGraphGenerationWorkflowRunner:
    def __init__(self, settings: Settings, llm: LLMClient, rag: RagDependency):
        state_graph, end = _load_langgraph_graph()
        self.settings = settings
        self.llm = llm
        self.rag = rag
        self.max_attempts = settings.llm_max_retries + 1
        self.graph = self._build_graph(state_graph, end)

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        workflow = WorkflowRecorder(backend="langgraph")
        state = GenerationWorkflowState(request=request)
        result = self.graph.invoke(
            {
                "state": state,
                "workflow": workflow,
                "validation_failed": False,
            }
        )
        return _build_generate_response(
            state=result["state"],
            workflow=result["workflow"],
            request=request,
            settings=self.settings,
        )

    def _build_graph(self, state_graph: Any, end: Any) -> Any:
        graph = state_graph(dict)
        graph.add_node(
            "analyze_requirement",
            self._recorded_node(
                "analyze_requirement",
                _analyze_requirement_node,
                _summarize_requirement_analysis,
            ),
        )
        graph.add_node(
            "retrieve_knowledge",
            self._recorded_node(
                "retrieve_knowledge",
                lambda state: _retrieve_knowledge_node(state, self.rag),
                lambda state: f"retrieved_chunks={len(state.contexts)}",
            ),
        )
        graph.add_node(
            "route_after_retrieval",
            self._recorded_node(
                "route_after_retrieval",
                lambda state: _route_after_retrieval_node(state, self.settings),
                _summarize_retrieval_route,
            ),
        )
        graph.add_node(
            "rewrite_query",
            self._recorded_node(
                "rewrite_query",
                _rewrite_query_node,
                lambda state: f"rewritten_query_length={len(state.rewritten_query or '')}",
            ),
        )
        graph.add_node("retrieve_rewritten_knowledge", self._retrieve_rewritten_node)
        graph.add_node(
            "plan_test_strategy",
            self._recorded_node(
                "plan_test_strategy",
                _plan_test_strategy_node,
                _summarize_test_strategy,
            ),
        )
        graph.add_node("start_attempt", self._start_attempt_node)
        graph.add_node(
            "build_prompt",
            self._recorded_node(
                "build_prompt",
                _build_prompt_node,
                lambda state: (
                    f"messages={len(state.prompt_messages[-1])}, "
                    f"attempt={state.attempt}"
                ),
            ),
        )
        graph.add_node(
            "check_budget",
            self._recorded_node(
                "check_budget",
                lambda state: _check_budget_node(state, self.settings),
                _summarize_budget_gate,
                trace=lambda state: _trace_budget_gate(state, self.settings),
            ),
        )
        graph.add_node("call_llm", self._call_llm_graph_node)
        graph.add_node("validate_output", self._validate_output_graph_node)
        graph.add_node(
            "post_process_cases",
            self._recorded_node(
                "post_process_cases",
                _post_process_cases_node,
                lambda state: f"final_cases={len(state.cases)}",
            ),
        )
        graph.add_node(
            "review_cases",
            self._recorded_node(
                "review_cases",
                lambda state: _review_cases_node(state, self.settings),
                _summarize_review,
            ),
        )
        graph.add_node(
            "route_after_review",
            self._recorded_node(
                "route_after_review",
                lambda state: _route_after_review_node(
                    state,
                    self.settings,
                    max_attempts=self.max_attempts,
                ),
                _summarize_review_route,
            ),
        )
        graph.add_node(
            "check_quality_gate",
            self._recorded_node(
                "check_quality_gate",
                lambda state: _check_quality_gate_node(state, self.settings),
                _summarize_quality_gate,
            ),
        )
        graph.add_node(
            "estimate_usage",
            self._recorded_node(
                "estimate_usage",
                lambda state: _estimate_usage_node(state, self.settings),
                lambda state: (
                    "total_tokens_estimate="
                    f"{_require_value(state.usage, 'usage').total_tokens_estimate}"
                ),
            ),
        )
        graph.add_node("output_validation_failed", self._output_validation_failed_node)

        graph.set_entry_point("analyze_requirement")
        graph.add_edge("analyze_requirement", "retrieve_knowledge")
        graph.add_edge("retrieve_knowledge", "route_after_retrieval")
        graph.add_conditional_edges(
            "route_after_retrieval",
            self._route_after_retrieval,
            {
                "rewrite": "rewrite_query",
                "continue": "plan_test_strategy",
            },
        )
        graph.add_edge("rewrite_query", "retrieve_rewritten_knowledge")
        graph.add_edge("retrieve_rewritten_knowledge", "plan_test_strategy")
        graph.add_edge("plan_test_strategy", "start_attempt")
        graph.add_edge("start_attempt", "build_prompt")
        graph.add_edge("build_prompt", "check_budget")
        graph.add_edge("check_budget", "call_llm")
        graph.add_edge("call_llm", "validate_output")
        graph.add_conditional_edges(
            "validate_output",
            self._route_after_validation,
            {
                "retry": "start_attempt",
                "failed": "output_validation_failed",
                "continue": "post_process_cases",
            },
        )
        graph.add_conditional_edges(
            "post_process_cases",
            self._route_after_post_process,
            {
                "review": "review_cases",
                "finish": "estimate_usage",
            },
        )
        graph.add_edge("review_cases", "route_after_review")
        graph.add_conditional_edges(
            "route_after_review",
            self._route_after_review,
            {
                "retry": "start_attempt",
                "quality_gate": "check_quality_gate",
                "finish": "estimate_usage",
            },
        )
        graph.add_edge("check_quality_gate", "estimate_usage")
        graph.add_edge("estimate_usage", end)
        graph.add_edge("output_validation_failed", end)
        return graph.compile()

    def _recorded_node(
        self,
        name: str,
        action: Callable[[GenerationWorkflowState], None],
        summary: str | Callable[[GenerationWorkflowState], str],
        trace: Callable[[GenerationWorkflowState], dict[str, Any]] | None = None,
    ) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def run(payload: dict[str, Any]) -> dict[str, Any]:
            payload["workflow"].run_node(
                _workflow_node(name=name, action=action, summary=summary, trace=trace),
                payload["state"],
            )
            return payload

        return run

    def _retrieve_rewritten_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["workflow"].run_node(
            _workflow_node(
                name="retrieve_rewritten_knowledge",
                action=lambda state: _retrieve_knowledge_node(state, self.rag),
                summary=lambda state: f"retrieved_chunks={len(state.contexts)}",
                trace=_trace_retrieve_knowledge,
            ),
            payload["state"],
        )
        payload["state"].retrieval_retry_requested = False
        return payload

    def _start_attempt_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = payload["state"]
        state.attempt += 1
        state.retry_requested = False
        state.review = None
        payload["validation_failed"] = False
        return payload

    def _call_llm_graph_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = payload["state"]
        try:
            payload["workflow"].run_node(
                _workflow_node(
                    name="call_llm",
                    action=lambda current: _call_llm_node(current, self.llm),
                    summary=lambda current: (
                        f"attempt={current.attempt}, "
                        f"keys={list(current.payload.keys()) if current.payload else []}"
                    ),
                    trace=_trace_call_llm,
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
        return payload

    def _validate_output_graph_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = payload["state"]
        payload["validation_failed"] = False
        try:
            payload["workflow"].run_node(
                _workflow_node(
                    name="validate_output",
                    action=_validate_output_node,
                    summary=lambda current: (
                        f"validated_cases={len(current.cases)}, "
                        f"attempt={current.attempt}"
                    ),
                    trace=_trace_validate_output,
                ),
                state,
            )
        except ValidationError as exc:
            state.last_error = exc
            state.correction = str(exc)
            payload["validation_failed"] = True
        return payload

    def _output_validation_failed_node(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = payload["state"]
        usage = estimate_generation_usage(
            self.settings,
            state.prompt_messages,
            state.completion_payloads,
        )
        raise OutputValidationError(
            f"LLM output did not match schema: {state.last_error}",
            usage=usage,
        ) from state.last_error

    def _route_after_retrieval(self, payload: dict[str, Any]) -> str:
        return "rewrite" if payload["state"].retrieval_retry_requested else "continue"

    def _route_after_validation(self, payload: dict[str, Any]) -> str:
        if not payload.get("validation_failed"):
            return "continue"
        if payload["state"].attempt < self.max_attempts:
            return "retry"
        return "failed"

    def _route_after_post_process(self, payload: dict[str, Any]) -> str:
        return "review" if self.settings.agent_review_enabled else "finish"

    def _route_after_review(self, payload: dict[str, Any]) -> str:
        if payload["state"].retry_requested:
            return "retry"
        if self.settings.agent_review_require_pass:
            return "quality_gate"
        return "finish"


def _load_langgraph_graph() -> tuple[Any, Any]:
    try:
        from langgraph.graph import END, StateGraph
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "AGENT_WORKFLOW_BACKEND=langgraph requires the 'langgraph' package. "
            "Install LangGraph before enabling this backend."
        ) from exc
    return StateGraph, END


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
    rag: RagDependency,
) -> None:
    query = state.rewritten_query or state.request.description
    state.knowledge_query = query
    state.retrieval_attempts += 1
    if state.request.knowledge_top_k <= 0:
        state.contexts = []
        return
    state.contexts = _resolve_rag(rag).search(
        query,
        top_k=state.request.knowledge_top_k,
    )


def _resolve_rag(rag: RagDependency) -> RagService:
    if callable(rag):
        return rag()
    return rag


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


def _check_budget_node(
    state: GenerationWorkflowState,
    settings: Settings,
) -> None:
    usage = estimate_generation_usage(
        settings,
        state.prompt_messages,
        state.completion_payloads,
    )
    state.usage = usage
    prompt_limit = settings.agent_budget_max_prompt_tokens
    if prompt_limit > 0 and usage.prompt_tokens_estimate > prompt_limit:
        raise GenerationBudgetExceededError(
            "Generation requires human confirmation: "
            f"prompt_tokens_estimate={usage.prompt_tokens_estimate} "
            f"exceeds AGENT_BUDGET_MAX_PROMPT_TOKENS={prompt_limit}.",
            usage=usage,
        )

    cost_limit = settings.agent_budget_max_estimated_cost
    if (
        cost_limit > 0
        and usage.estimated_cost is not None
        and usage.estimated_cost > cost_limit
    ):
        raise GenerationBudgetExceededError(
            "Generation requires human confirmation: "
            f"estimated_cost={usage.estimated_cost} exceeds "
            f"AGENT_BUDGET_MAX_ESTIMATED_COST={cost_limit}.",
            usage=usage,
        )


def _summarize_budget_gate(state: GenerationWorkflowState) -> str:
    usage = _require_value(state.usage, "usage")
    return (
        "decision=accept, "
        f"prompt_tokens_estimate={usage.prompt_tokens_estimate}, "
        f"estimated_cost={usage.estimated_cost}"
    )


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
        retrieved_contexts=state.contexts,
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
        reason = _review_retry_reason(review)
        return f"decision=retry, reason={reason}"
    if review.retry_recommended:
        return "decision=accept, reason=retry_disabled_or_budget_exhausted"
    return "decision=accept, reason=review_passed"


def _review_retry_reason(review: GenerationReview) -> str:
    if review.missing_target_types or review.missing_acceptance_keywords:
        return "coverage_repair"
    return "review_feedback"


def _check_quality_gate_node(
    state: GenerationWorkflowState,
    settings: Settings,
) -> None:
    review = _require_value(state.review, "review")
    if review.passed:
        return
    usage = estimate_generation_usage(
        settings,
        state.prompt_messages,
        state.completion_payloads,
    )
    state.usage = usage
    raise GenerationQualityGateError(
        "Generation requires human review: "
        f"review_score={review.score}, grade={review.grade}, "
        f"warnings={','.join(review.warnings) or 'none'}.",
        usage=usage,
        review=review,
    )


def _summarize_quality_gate(state: GenerationWorkflowState) -> str:
    review = _require_value(state.review, "review")
    return f"decision=accept, review_score={review.score}, grade={review.grade}"


def _estimate_usage_node(
    state: GenerationWorkflowState,
    settings: Settings,
) -> None:
    state.usage = estimate_generation_usage(
        settings,
        state.prompt_messages,
        state.completion_payloads,
    )


def _build_generate_response(
    *,
    state: GenerationWorkflowState,
    workflow: WorkflowRecorder,
    request: GenerateRequest,
    settings: Settings,
) -> GenerateResponse:
    return GenerateResponse(
        cases=state.cases,
        metadata=GenerationMetadata(
            model=settings.zhipu_chat_model,
            attempts=state.attempt,
            retrieved_chunks=len(state.contexts),
            retrieved_sources=_unique_sources(state.contexts),
            prompt_version=PROMPT_TEMPLATE_VERSION,
            workflow_backend=settings.agent_workflow_backend,
            usage=_require_value(state.usage, "usage"),
            review=state.review,
            workflow_steps=workflow.steps,
        ),
        retrieved_context=state.contexts if request.include_context else [],
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
