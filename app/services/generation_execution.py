import logging
import time
from collections.abc import Callable
from typing import NamedTuple

from app.models.test_case import GenerateRequest, GenerateResponse
from app.services.generator import (
    GenerationGateError,
    OutputValidationError,
    TestCaseGenerator,
)
from app.services.llm import LLMError, MissingApiKeyError
from app.services.stores import GenerationHistoryRepository


class GenerationExecutionResult(NamedTuple):
    response: GenerateResponse
    record_id: str | None


GeneratorFactory = Callable[[], TestCaseGenerator]
HistoryStoreFactory = Callable[[], GenerationHistoryRepository]


def execute_generation(
    request: GenerateRequest,
    *,
    request_id: str | None,
    generator_factory: GeneratorFactory,
    history_store_factory: HistoryStoreFactory,
    logger: logging.Logger,
) -> GenerationExecutionResult:
    start = time.perf_counter()
    try:
        response = generator_factory().generate(request)
    except (MissingApiKeyError, LLMError, GenerationGateError, OutputValidationError) as exc:
        record_id = _record_generation_failure(
            request,
            exc,
            start=start,
            request_id=request_id,
            history_store_factory=history_store_factory,
            logger=logger,
        )
        setattr(exc, "record_id", record_id)
        raise

    duration_ms = (time.perf_counter() - start) * 1000
    record_id = _record_generation_success(
        request,
        response,
        duration_ms=duration_ms,
        request_id=request_id,
        history_store_factory=history_store_factory,
        logger=logger,
    )
    return GenerationExecutionResult(response=response, record_id=record_id)


def _record_generation_success(
    request: GenerateRequest,
    response: GenerateResponse,
    *,
    duration_ms: float,
    request_id: str | None,
    history_store_factory: HistoryStoreFactory,
    logger: logging.Logger,
) -> str | None:
    try:
        return history_store_factory().record_success(
            request,
            response,
            duration_ms=duration_ms,
            request_id=request_id,
        )
    except Exception:
        logger.exception("failed to persist generation success record")
        return None


def _record_generation_failure(
    request: GenerateRequest,
    exc: Exception,
    *,
    start: float,
    request_id: str | None,
    history_store_factory: HistoryStoreFactory,
    logger: logging.Logger,
) -> str | None:
    try:
        duration_ms = (time.perf_counter() - start) * 1000
        return history_store_factory().record_failure(
            request,
            str(exc),
            duration_ms=duration_ms,
            request_id=request_id,
            usage=getattr(exc, "usage", None),
            gate=exc.to_detail() if isinstance(exc, GenerationGateError) else None,
        )
    except Exception:
        logger.exception("failed to persist generation failure record")
        return None
