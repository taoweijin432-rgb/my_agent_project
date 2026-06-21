from functools import lru_cache
from secrets import compare_digest
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings
from app.models.test_case import (
    ExportRequest,
    GenerateRequest,
    GenerateResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
)
from app.services.excel_exporter import build_excel
from app.services.generator import OutputValidationError, TestCaseGenerator
from app.services.llm import LLMClient, LLMError, MissingApiKeyError
from app.services.rag import ChromaUnavailableError, RagService

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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


def _generator() -> TestCaseGenerator:
    return TestCaseGenerator(settings=_settings(), llm=_llm_client(), rag=_rag_service())


@router.post("/test-cases/generate", response_model=GenerateResponse, tags=["test-cases"])
def generate_test_cases(request: GenerateRequest) -> GenerateResponse:
    try:
        return _generator().generate(request)
    except MissingApiKeyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OutputValidationError as exc:
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


def _content_disposition(filename: str) -> str:
    ascii_filename = "".join(
        char if 32 <= ord(char) < 127 and char not in {'"', "\\", ";"} else "_"
        for char in filename
    ).strip()
    if not ascii_filename:
        ascii_filename = DEFAULT_EXPORT_FILENAME
    encoded_filename = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"
