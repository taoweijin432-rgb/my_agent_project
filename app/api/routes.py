import logging
from functools import lru_cache
from secrets import compare_digest
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings
from app.models.test_case import (
    CoverageGapKnowledgeRequest,
    CoverageGapKnowledgeUpsertResponse,
    CoverageEvaluationRequest,
    CoverageEvaluationResponse,
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
    PytestExportRequest,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
)
from app.models.test_plan import (
    TestAgentWorkflowJobDetail,
    TestAgentWorkflowJobListResponse,
    TestAgentWorkflowRequest,
    TestAgentWorkflowResult,
    TestExecutionReport,
    TestExecutionReportExportRequest,
    TestPlan,
    TestPlanExecutionRequest,
    TestPlanExecutionJobDetail,
    TestPlanExecutionJobListResponse,
    TestPlanGenerationRequest,
    TestPlanStepExecutionRequest,
    ToolRun,
)
from app.services.coverage import (
    build_coverage_gap_knowledge_document,
    evaluate_requirement_coverage,
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
from app.services.metrics import build_metrics_snapshot, format_prometheus_metrics
from app.services.pytest_exporter import build_pytest_template
from app.services.rag import ChromaUnavailableError, RagService
from app.services.stores import (
    GenerationHistoryRepository,
    GenerationJobRepository,
    create_generation_history_store,
    create_generation_job_store,
    create_test_agent_workflow_job_store,
    create_test_plan_execution_job_store,
)
from app.services.test_plan_execution import (
    TestPlanExecutionConfigurationError,
    build_tool_execution_service,
    execute_test_plan_request as run_test_plan_execution_request,
)
from app.services.test_agent_workflow import (
    execute_test_agent_workflow_request as run_test_agent_workflow_request,
)
from app.services.test_report import build_execution_report, export_execution_report
from app.services.test_plan_generator import (
    LLMTestPlanGenerator,
    TestPlanGenerator,
    TestPlanOutputValidationError,
)
from app.services.test_plan_execution_jobs import (
    InMemoryTestPlanExecutionJobQueue,
    RedisRQTestPlanExecutionJobQueue,
    TestPlanExecutionJobQueue,
    TestPlanExecutionJobQueueFullError,
    TestPlanExecutionJobQueueUnavailableError,
)
from app.services.test_agent_workflow_jobs import (
    InMemoryTestAgentWorkflowJobQueue,
    RedisRQTestAgentWorkflowJobQueue,
    TestAgentWorkflowJobQueue,
    TestAgentWorkflowJobQueueFullError,
    TestAgentWorkflowJobQueueUnavailableError,
)
from app.services.tool_execution import ToolExecutionService
from app.services.tool_artifacts import ToolArtifactStore

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
logger = logging.getLogger("app.history")


def require_api_key(api_key: str | None = Depends(api_key_header)) -> None:
    settings = _settings()
    accepted_api_keys = settings.accepted_api_keys
    if not accepted_api_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="APP_API_KEY or APP_API_KEYS is not configured.",
        )
    matched = False
    if api_key:
        for key in accepted_api_keys:
            matched = compare_digest(api_key, key) or matched
    if not matched:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )


router = APIRouter(dependencies=[Depends(require_api_key)])
DEFAULT_EXPORT_FILENAME = "test-cases.xlsx"
DEFAULT_PYTEST_EXPORT_FILENAME = "test_generated_cases.py"
DEFAULT_TEST_REPORT_MARKDOWN_FILENAME = "test-execution-report.md"
DEFAULT_TEST_REPORT_JSON_FILENAME = "test-execution-report.json"


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


def _tool_execution_service(http_base_url: str) -> ToolExecutionService:
    try:
        return build_tool_execution_service(_settings(), http_base_url)
    except TestPlanExecutionConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _tool_artifact_store() -> ToolArtifactStore:
    settings = _settings()
    return ToolArtifactStore(
        settings.test_tool_artifact_dir,
        max_bytes=settings.test_tool_artifact_max_bytes,
    )


def _test_plan_generator(
    *,
    use_llm: bool,
    allow_llm_fallback: bool,
) -> TestPlanGenerator | LLMTestPlanGenerator:
    if not use_llm:
        return TestPlanGenerator()
    return LLMTestPlanGenerator(
        _llm_client(),
        allow_fallback=allow_llm_fallback,
    )


@lru_cache
def _test_plan_execution_job_queue() -> TestPlanExecutionJobQueue:
    settings = _settings()
    if settings.generation_job_queue_backend == "rq":
        return RedisRQTestPlanExecutionJobQueue(
            settings,
            create_test_plan_execution_job_store(settings),
        )
    store = create_test_plan_execution_job_store(settings)
    return InMemoryTestPlanExecutionJobQueue(
        settings,
        _execute_test_plan_request,
        store=store,
    )


@lru_cache
def _test_agent_workflow_job_queue() -> TestAgentWorkflowJobQueue:
    settings = _settings()
    if settings.generation_job_queue_backend == "rq":
        return RedisRQTestAgentWorkflowJobQueue(
            settings,
            create_test_agent_workflow_job_store(settings),
        )
    store = create_test_agent_workflow_job_store(settings)
    return InMemoryTestAgentWorkflowJobQueue(
        settings,
        _execute_test_agent_workflow_request,
        store=store,
    )


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


@router.post("/test-cases/export/pytest", tags=["test-cases"])
def export_pytest_template(request: PytestExportRequest) -> StreamingResponse:
    stream = build_pytest_template(request)
    filename = request.filename or DEFAULT_PYTEST_EXPORT_FILENAME
    return StreamingResponse(
        stream,
        media_type="text/x-python; charset=utf-8",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.post(
    "/evaluation/coverage",
    response_model=CoverageEvaluationResponse,
    tags=["evaluation"],
)
def evaluate_coverage(
    request: CoverageEvaluationRequest,
) -> CoverageEvaluationResponse:
    return evaluate_requirement_coverage(request)


@router.post(
    "/test-plans/generate",
    response_model=TestPlan,
    tags=["test-plans"],
)
def generate_test_plan(request: TestPlanGenerationRequest) -> TestPlan:
    try:
        return _test_plan_generator(
            use_llm=request.use_llm,
            allow_llm_fallback=request.allow_llm_fallback,
        ).generate(request)
    except MissingApiKeyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (LLMError, TestPlanOutputValidationError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/test-plans/execute-step",
    response_model=ToolRun,
    tags=["test-plans"],
)
def execute_test_plan_step(request: TestPlanStepExecutionRequest) -> ToolRun:
    return _tool_execution_service(request.http_base_url).execute_step(request.step)


@router.post(
    "/test-plans/execute",
    response_model=TestExecutionReport,
    tags=["test-plans"],
)
def execute_test_plan(request: TestPlanExecutionRequest) -> TestExecutionReport:
    tool_runs = _tool_execution_service(request.http_base_url).execute_plan(request.plan)
    return build_execution_report(request.plan, tool_runs)


@router.post("/test-plans/reports/export", tags=["test-plans"])
def export_test_plan_report(request: TestExecutionReportExportRequest) -> Response:
    content = export_execution_report(request.report, request.format)
    filename = request.filename or (
        DEFAULT_TEST_REPORT_JSON_FILENAME
        if request.format == "json"
        else DEFAULT_TEST_REPORT_MARKDOWN_FILENAME
    )
    media_type = (
        "application/json; charset=utf-8"
        if request.format == "json"
        else "text/markdown; charset=utf-8"
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.post(
    "/test-plans/execution-jobs",
    response_model=TestPlanExecutionJobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["test-plans"],
)
def submit_test_plan_execution_job(
    request: TestPlanExecutionRequest,
) -> TestPlanExecutionJobDetail:
    try:
        return _test_plan_execution_job_queue().submit(request)
    except TestPlanExecutionJobQueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except TestPlanExecutionJobQueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/test-plans/execution-jobs",
    response_model=TestPlanExecutionJobListResponse,
    tags=["test-plans"],
)
def list_test_plan_execution_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["queued", "running", "succeeded", "failed"] | None = Query(
        default=None,
        alias="status",
    ),
) -> TestPlanExecutionJobListResponse:
    jobs = _test_plan_execution_job_queue().list_jobs(
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return TestPlanExecutionJobListResponse(jobs=jobs, limit=limit, offset=offset)


@router.get(
    "/test-plans/execution-jobs/{job_id}",
    response_model=TestPlanExecutionJobDetail,
    tags=["test-plans"],
)
def get_test_plan_execution_job(job_id: str) -> TestPlanExecutionJobDetail:
    job = _test_plan_execution_job_queue().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Test plan execution job not found.")
    return job


@router.post(
    "/test-agent/workflow-jobs",
    response_model=TestAgentWorkflowJobDetail,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["test-agent"],
)
def submit_test_agent_workflow_job(
    request: TestAgentWorkflowRequest,
) -> TestAgentWorkflowJobDetail:
    try:
        return _test_agent_workflow_job_queue().submit(request)
    except TestAgentWorkflowJobQueueFullError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except TestAgentWorkflowJobQueueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get(
    "/test-agent/workflow-jobs",
    response_model=TestAgentWorkflowJobListResponse,
    tags=["test-agent"],
)
def list_test_agent_workflow_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: Literal["queued", "running", "succeeded", "failed"] | None = Query(
        default=None,
        alias="status",
    ),
) -> TestAgentWorkflowJobListResponse:
    jobs = _test_agent_workflow_job_queue().list_jobs(
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return TestAgentWorkflowJobListResponse(jobs=jobs, limit=limit, offset=offset)


@router.get(
    "/test-agent/workflow-jobs/{job_id}",
    response_model=TestAgentWorkflowJobDetail,
    tags=["test-agent"],
)
def get_test_agent_workflow_job(job_id: str) -> TestAgentWorkflowJobDetail:
    job = _test_agent_workflow_job_queue().get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Test agent workflow job not found.")
    return job


@router.get(
    "/test-plans/artifacts/{artifact_path:path}",
    tags=["test-plans"],
)
def get_test_plan_artifact(artifact_path: str) -> FileResponse:
    try:
        path = _tool_artifact_store().resolve_path(artifact_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Artifact not found.") from exc
    return FileResponse(str(path), media_type="text/plain; charset=utf-8", filename=path.name)


@router.get("/operations/metrics", tags=["operations"])
def get_operations_metrics() -> dict:
    return build_metrics_snapshot(_settings())


@router.get("/operations/metrics/prometheus", tags=["operations"])
def get_operations_prometheus_metrics() -> Response:
    snapshot = build_metrics_snapshot(_settings())
    return Response(
        content=format_prometheus_metrics(snapshot),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.post(
    "/evaluation/coverage/gaps/knowledge",
    response_model=CoverageGapKnowledgeUpsertResponse,
    tags=["evaluation"],
)
def upsert_coverage_gap_knowledge(
    request: CoverageGapKnowledgeRequest,
) -> CoverageGapKnowledgeUpsertResponse:
    try:
        document, gap_count = build_coverage_gap_knowledge_document(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    added_chunks, replaced_chunks, version = _rag_service().upsert_document(
        document,
        chunk_size=request.chunk_size,
    )
    return CoverageGapKnowledgeUpsertResponse(
        source=document.source,
        version=version,
        added_chunks=added_chunks,
        replaced_chunks=replaced_chunks,
        gap_count=gap_count,
        document_type=document.document_type,
        module=document.module,
        tags=document.tags,
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


def _execute_test_plan_request(request: TestPlanExecutionRequest) -> TestExecutionReport:
    return run_test_plan_execution_request(request, _settings())


def _execute_test_agent_workflow_request(
    request: TestAgentWorkflowRequest,
) -> TestAgentWorkflowResult:
    return run_test_agent_workflow_request(request, _settings())


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
