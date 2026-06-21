from typing import Any

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
    WorkflowRecorder,
    analyze_requirement,
    plan_test_generation,
)
from app.services.llm import LLMClient
from app.services.llm import LLMError
from app.services.prompt import PROMPT_TEMPLATE_VERSION, build_generation_messages
from app.services.rag import RagService
from app.services.usage import estimate_generation_usage


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
        analysis = workflow.run(
            "analyze_requirement",
            lambda: analyze_requirement(request),
            summary=lambda result: (
                f"description_length={result.description_length}, "
                f"requested_case_count={result.requested_case_count}, "
                f"detected_risk_types={[item.value for item in result.detected_risk_types]}"
            ),
        )
        contexts = workflow.run(
            "retrieve_knowledge",
            lambda: self.rag.search(request.description, top_k=request.knowledge_top_k),
            summary=lambda result: f"retrieved_chunks={len(result)}",
        )
        plan = workflow.run(
            "plan_test_strategy",
            lambda: plan_test_generation(analysis, contexts),
            summary=lambda result: (
                f"target_types={[item.value for item in result.target_types]}, "
                f"context_sources={len(result.context_sources)}"
            ),
        )
        correction: str | None = None
        last_error: Exception | None = None
        prompt_messages: list[list[dict[str, str]]] = []
        completion_payloads: list[Any] = []

        for attempt in range(1, self.settings.llm_max_retries + 2):
            messages = workflow.run(
                "build_prompt",
                lambda: build_generation_messages(
                    request,
                    contexts,
                    correction=correction,
                    strategy=plan.to_prompt_text(),
                ),
                summary=lambda result: f"messages={len(result)}, attempt={attempt}",
            )
            prompt_messages.append(messages)
            try:
                payload = workflow.run(
                    "call_llm",
                    lambda: _normalize_payload(self.llm.generate_json(messages)),
                    summary=lambda result: (
                        f"attempt={attempt}, keys={list(result.keys()) if isinstance(result, dict) else []}"
                    ),
                )
            except LLMError as exc:
                exc.usage = estimate_generation_usage(
                    self.settings,
                    prompt_messages,
                    completion_payloads,
                )
                raise
            completion_payloads.append(payload)
            try:
                collection = workflow.run(
                    "validate_output",
                    lambda: TestCaseCollection.model_validate(payload),
                    summary=lambda result: f"validated_cases={len(result.cases)}, attempt={attempt}",
                )
                cases = workflow.run(
                    "post_process_cases",
                    lambda: _post_process_cases(collection.cases, max_cases=request.max_cases),
                    summary=lambda result: f"final_cases={len(result)}",
                )
                usage = workflow.run(
                    "estimate_usage",
                    lambda: estimate_generation_usage(
                        self.settings,
                        prompt_messages,
                        completion_payloads,
                    ),
                    summary=lambda result: f"total_tokens_estimate={result.total_tokens_estimate}",
                )
                return GenerateResponse(
                    cases=cases,
                    metadata=GenerationMetadata(
                        model=self.settings.zhipu_chat_model,
                        attempts=attempt,
                        retrieved_chunks=len(contexts),
                        retrieved_sources=_unique_sources(contexts),
                        prompt_version=PROMPT_TEMPLATE_VERSION,
                        usage=usage,
                        workflow_steps=workflow.steps,
                    ),
                    retrieved_context=contexts if request.include_context else [],
                )
            except ValidationError as exc:
                last_error = exc
                correction = str(exc)
        usage = estimate_generation_usage(
            self.settings,
            prompt_messages,
            completion_payloads,
        )
        raise OutputValidationError(
            f"LLM output did not match schema: {last_error}",
            usage=usage,
        ) from last_error


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
