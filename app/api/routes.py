import logging
import time
from functools import lru_cache
from secrets import compare_digest
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings
from app.models.test_case import (
    ExportRequest,
    GenerateRequest,
    GenerateResponse,
    GenerationRecordDetail,
    GenerationRecordListResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
)
from app.services.excel_exporter import build_excel
from app.services.generator import OutputValidationError, TestCaseGenerator
from app.services.history import GenerationHistoryStore
from app.services.llm import LLMClient, LLMError, MissingApiKeyError
from app.services.rag import ChromaUnavailableError, RagService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
logger = logging.getLogger("app.history")


def require_api_key(api_key: str | None = Depends(api_key_header)) -> None:
    settings = _settings()
    if not settings.app_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="APP_API_KEY is not configured.",
        )
    if not api_key or not compare_digest(api_key, settings.app_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )


router = APIRouter(dependencies=[Depends(require_api_key)])
DEFAULT_EXPORT_FILENAME = "test-cases.xlsx"


@lru_cache
def _settings() -> Settings:
    return get_settings()


@lru_cache
def _rag_service() -> RagService:
    try:
        return RagService(_settings())
    except ChromaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@lru_cache
def _llm_client() -> LLMClient:
    return LLMClient(_settings())


@lru_cache
def _history_store() -> GenerationHistoryStore:
    return GenerationHistoryStore(_settings())


def _generator() -> TestCaseGenerator:
    return TestCaseGenerator(settings=_settings(), llm=_llm_client(), rag=_rag_service())


@router.post("/test-cases/generate", response_model=GenerateResponse, tags=["test-cases"])
def generate_test_cases(request: GenerateRequest, http_request: Request) -> GenerateResponse:
    start = time.perf_counter()
    request_id = getattr(http_request.state, "request_id", None)
    try:
        response = _generator().generate(request)
        duration_ms = (time.perf_counter() - start) * 1000
        _record_generation_success(
            request,
            response,
            duration_ms=duration_ms,
            request_id=request_id,
        )
        return response
    except MissingApiKeyError as exc:
        _record_generation_failure(request, exc, start=start, request_id=request_id)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        _record_generation_failure(request, exc, start=start, request_id=request_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OutputValidationError as exc:
        _record_generation_failure(request, exc, start=start, request_id=request_id)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/test-cases/export", tags=["test-cases"])
def export_test_cases(request: ExportRequest) -> StreamingResponse:
    stream = build_excel(request.cases)
    filename = request.filename or DEFAULT_EXPORT_FILENAME
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.post("/knowledge/ingest", response_model=IngestResponse, tags=["knowledge"])
def ingest_knowledge(request: IngestRequest) -> IngestResponse:
    service = _rag_service()
    added = service.ingest_documents(request.documents, chunk_size=request.chunk_size)
    return IngestResponse(added_chunks=added)


@router.post("/knowledge/query", response_model=QueryResponse, tags=["knowledge"])
def query_knowledge(request: QueryRequest) -> QueryResponse:
    service = _rag_service()
    chunks = service.search(request.query, top_k=request.top_k)
    return QueryResponse(chunks=chunks)


@router.get(
    "/generation-records",
    response_model=GenerationRecordListResponse,
    tags=["history"],
)
def list_generation_records(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["success", "failed"] | None = Query(default=None, alias="status"),
) -> GenerationRecordListResponse:
    records = _history_store().list_records(
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return GenerationRecordListResponse(records=records, limit=limit, offset=offset)


@router.get(
    "/generation-records/{record_id}",
    response_model=GenerationRecordDetail,
    tags=["history"],
)
def get_generation_record(record_id: str) -> GenerationRecordDetail:
    record = _history_store().get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Generation record not found.")
    return record


def _record_generation_success(
    request: GenerateRequest,
    response: GenerateResponse,
    *,
    duration_ms: float,
    request_id: str | None,
) -> None:
    try:
        _history_store().record_success(
            request,
            response,
            duration_ms=duration_ms,
            request_id=request_id,
        )
    except Exception:
        logger.exception("failed to persist generation success record")


def _record_generation_failure(
    request: GenerateRequest,
    exc: Exception,
    *,
    start: float,
    request_id: str | None,
) -> None:
    try:
        duration_ms = (time.perf_counter() - start) * 1000
        _history_store().record_failure(
            request,
            str(exc),
            duration_ms=duration_ms,
            request_id=request_id,
        )
    except Exception:
        logger.exception("failed to persist generation failure record")


def _content_disposition(filename: str) -> str:
    ascii_filename = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\", ";"} else "_"
        for char in filename
    ).strip()
    if not ascii_filename:
        ascii_filename = DEFAULT_EXPORT_FILENAME
    encoded_filename = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
