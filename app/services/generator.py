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
from app.services.llm import LLMClient
from app.services.prompt import PROMPT_TEMPLATE_VERSION, build_generation_messages
from app.services.rag import RagService


class OutputValidationError(RuntimeError):
    """Raised when model output cannot be converted into the expected schema."""


class TestCaseGenerator:
    def __init__(self, settings: Settings, llm: LLMClient, rag: RagService):
        self.settings = settings
        self.llm = llm
        self.rag = rag

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        contexts = self.rag.search(request.description, top_k=request.knowledge_top_k)
        correction: str | None = None
        last_error: Exception | None = None

        for attempt in range(1, self.settings.llm_max_retries + 2):
            messages = build_generation_messages(request, contexts, correction=correction)
            payload = _normalize_payload(self.llm.generate_json(messages))
            try:
                collection = TestCaseCollection.model_validate(payload)
                cases = _post_process_cases(collection.cases, max_cases=request.max_cases)
                return GenerateResponse(
                    cases=cases,
                    metadata=GenerationMetadata(
                        model=self.settings.zhipu_chat_model,
                        attempts=attempt,
                        retrieved_chunks=len(contexts),
                        retrieved_sources=_unique_sources(contexts),
                        prompt_version=PROMPT_TEMPLATE_VERSION,
                    ),
                    retrieved_context=contexts if request.include_context else [],
                )
            except ValidationError as exc:
                last_error = exc
                correction = str(exc)

        raise OutputValidationError(f"LLM output did not match schema: {last_error}") from last_error


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
