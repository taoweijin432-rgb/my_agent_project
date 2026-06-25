import logging
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
    GenerationGateResolveRequest,
    GenerationJobDetail,
    GenerationJobListResponse,
    GenerationRecordDetail,
    GenerationRecordListResponse,
    KnowledgeDocumentDeleteResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentUpsertRequest,
    KnowledgeDocumentUpsertResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
)
from app.services.excel_exporter import build_excel
from app.services.generation_execution import (
    GenerationExecutionResult,
    execute_generation,
)
from app.services.generator import (
    GenerationGateError,
    OutputValidationError,
    TestCaseGenerator,
)
from app.services.generation_jobs import (
    GenerationJobQueue,
    GenerationJobQueueFullError,
    GenerationJobQueueUnavailableError,
    InMemoryGenerationJobQueue,
    RedisRQGenerationJobQueue,
)
from app.services.history import (
    GenerationGateAlreadyResolvedError,
)
from app.services.llm import LLMClient, LLMError, MissingApiKeyError
from app.services.rag import ChromaUnavailableError, RagService
from app.services.stores import (
    GenerationHistoryRepository,
    GenerationJobRepository,
    create_generation_history_store,
    create_generation_job_store,
)

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
def _history_store() -> GenerationHistoryRepository:
    return create_generation_history_store(_settings())


@lru_cache
def _generation_job_store() -> GenerationJobRepository:
    return create_generation_job_store(_settings())


@lru_cache
def _generation_job_queue() -> GenerationJobQueue:
    settings = _settings()
    if settings.generation_job_queue_backend == "rq":
        return RedisRQGenerationJobQueue(settings, _generation_job_store())
    return InMemoryGenerationJobQueue(settings, _execute_generation_job)


def _generator() -> TestCaseGenerator:
    return TestCaseGenerator(settings=_settings(), llm=_llm_client(), rag=_rag_service)


@router.post("/test-cases/generate", response_model=GenerateResponse, tags=["test-cases"])
def generate_test_cases(request: GenerateRequest, http_request: Request) -> GenerateResponse:
    request_id = getattr(http_request.state, "request_id", None)
    try:
        return _execute_generation(request, request_id=request_id).response
    except (MissingApiKeyError, LLMError, GenerationGateError, OutputValidationError) as exc:
        raise _generation_http_exception(exc) from exc


@router.post(
    "/test-cases/generation-jobs",
    response_model=GenerationJobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["test-cases"],
)
def submit_generation_job(request: GenerateRequest) -> GenerationJobDetail:
    try:
        return _generation_job_queue().submit(request)
    except GenerationJobQueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except GenerationJobQueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/test-cases/generation-jobs",
    response_model=GenerationJobListResponse,
    tags=["test-cases"],
)
def list_generation_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["queued", "running", "succeeded", "failed"] | None = Query(
        default=None,
        alias="status",
    ),
) -> GenerationJobListResponse:
    jobs = _generation_job_queue().list_jobs(
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return GenerationJobListResponse(jobs=jobs, limit=limit, offset=offset)


@router.get(
    "/test-cases/generation-jobs/{job_id}",
    response_model=GenerationJobDetail,
    tags=["test-cases"],
)
def get_generation_job(job_id: str) -> GenerationJobDetail:
    job = _generation_job_queue().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Generation job not found.")
    return job


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
    "/knowledge/documents",
    response_model=KnowledgeDocumentListResponse,
    tags=["knowledge"],
)
def list_knowledge_documents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> KnowledgeDocumentListResponse:
    documents, total = _rag_service().list_documents(limit=limit, offset=offset)
    return KnowledgeDocumentListResponse(
        documents=documents,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/knowledge/documents/upsert",
    response_model=KnowledgeDocumentUpsertResponse,
    tags=["knowledge"],
)
def upsert_knowledge_document(
    request: KnowledgeDocumentUpsertRequest,
) -> KnowledgeDocumentUpsertResponse:
    added_chunks, replaced_chunks, version = _rag_service().upsert_document(
        request.document,
        chunk_size=request.chunk_size,
    )
    return KnowledgeDocumentUpsertResponse(
        source=request.document.source,
        version=version,
        added_chunks=added_chunks,
        replaced_chunks=replaced_chunks,
    )


@router.delete(
    "/knowledge/documents",
    response_model=KnowledgeDocumentDeleteResponse,
    tags=["knowledge"],
)
def delete_knowledge_document(
    source: str = Query(..., min_length=1),
) -> KnowledgeDocumentDeleteResponse:
    deleted_chunks = _rag_service().delete_document(source)
    return KnowledgeDocumentDeleteResponse(source=source, deleted_chunks=deleted_chunks)


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
    "/generation-gates",
    response_model=GenerationRecordListResponse,
    tags=["history"],
)
def list_generation_gates(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["pending", "approved", "rejected", "all"] = Query(
        default="pending",
        alias="status",
    ),
) -> GenerationRecordListResponse:
    gate_status = None if status_filter == "all" else status_filter
    records = _history_store().list_gate_records(
        limit=limit,
        offset=offset,
        gate_status=gate_status,
    )
    return GenerationRecordListResponse(records=records, limit=limit, offset=offset)


@router.post(
    "/generation-gates/{record_id}/resolve",
    response_model=GenerationRecordDetail,
    tags=["history"],
)
def resolve_generation_gate(
    record_id: str,
    request: GenerationGateResolveRequest,
) -> GenerationRecordDetail:
    try:
        record = _history_store().resolve_gate_record(
            record_id,
            decision=request.decision,
            resolved_by=request.resolved_by,
            comment=request.comment,
        )
    except GenerationGateAlreadyResolvedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if record is None:
        raise HTTPException(status_code=404, detail="Generation gate record not found.")
    return record


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


def _execute_generation_job(
    request: GenerateRequest,
    job_id: str,
) -> tuple[GenerateResponse, str | None]:
    result = _execute_generation(request, request_id=job_id)
    return result.response, result.record_id


def _execute_generation(
    request: GenerateRequest,
    *,
    request_id: str | None,
) -> GenerationExecutionResult:
    return execute_generation(
        request,
        request_id=request_id,
        generator_factory=_generator,
        history_store_factory=_history_store,
        logger=logger,
    )


def _generation_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, MissingApiKeyError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, LLMError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, GenerationGateError):
        return HTTPException(status_code=409, detail=exc.to_detail())
    if isinstance(exc, OutputValidationError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _content_disposition(filename: str) -> str:
    ascii_filename = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\", ";"} else "_"
        for char in filename
    ).strip()
    if not ascii_filename:
        ascii_filename = DEFAULT_EXPORT_FILENAME
    encoded_filename = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
