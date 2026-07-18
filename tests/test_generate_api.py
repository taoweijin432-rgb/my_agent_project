from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import routes
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationGateDetail,
    GenerationGateResolveRequest,
    GenerationGateResolution,
    GenerationJobDetail,
    GenerationRecordDetail,
    GenerationRecordSummary,
    GenerationMetadata,
    GenerationUsage,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.generation_jobs import GenerationJobQueueFullError
from app.services.generator import GenerationBudgetExceededError, OutputValidationError
from app.services.llm import LLMError, MissingApiKeyError


@pytest.fixture(autouse=True)
def fake_history_store(monkeypatch):
    store = FakeHistoryStore()
    monkeypatch.setattr(routes, "_history_store", lambda: store)
    return store


@pytest.fixture(autouse=True)
def fake_generation_job_queue(monkeypatch):
    queue = FakeGenerationJobQueue()
    monkeypatch.setattr(routes, "_generation_job_queue", lambda: queue)
    return queue


class FakeGenerator:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return self.response


class FakeHistoryStore:
    def __init__(self):
        self.successes = []
        self.failures = []
        self.records = []

    def record_success(self, request, response, *, duration_ms, request_id=None):
        self.successes.append((request, response, duration_ms, request_id))
        return "record-success"

    def record_failure(
        self,
        request,
        error,
        *,
        duration_ms,
        request_id=None,
        usage=None,
        gate=None,
    ):
        self.failures.append((request, error, duration_ms, request_id, usage, gate))
        return "record-failed"

    def list_records(self, *, limit=20, offset=0, status=None):
        records = self.records
        if status:
            records = [record for record in records if record.status == status]
        return records[offset : offset + limit]

    def get_record(self, record_id):
        for record in self.records:
            if record.id == record_id:
                return GenerationRecordDetail(
                    **record.model_dump(),
                    request={"description": "生成 JWT 登录测试用例"},
                    response=_response() if record.status == "success" else None,
                )
        return None

    def list_gate_records(self, *, limit=20, offset=0, gate_status="pending"):
        records = [record for record in self.records if record.gate is not None]
        if gate_status:
            records = [
                record
                for record in records
                if (record.gate_resolution.status if record.gate_resolution else "pending")
                == gate_status
            ]
        return records[offset : offset + limit]

    def resolve_gate_record(
        self,
        record_id,
        *,
        decision,
        resolved_by=None,
        comment=None,
    ):
        for index, record in enumerate(self.records):
            if record.id != record_id or record.gate is None:
                continue
            updated = GenerationRecordSummary(
                **{
                    **record.model_dump(),
                    "gate_resolution": GenerationGateResolution(
                        status=decision,
                        resolved_at="2026-06-21T00:02:00+00:00",
                        resolved_by=resolved_by,
                        comment=comment,
                    ),
                }
            )
            self.records[index] = updated
            return GenerationRecordDetail(
                **updated.model_dump(),
                request={"description": "鐢熸垚澶辫触鐢ㄤ緥"},
                response=None,
            )
        return None


class FakeGenerationJobQueue:
    def __init__(self):
        self.jobs = []
        self.full = False

    def submit(self, request):
        if self.full:
            raise GenerationJobQueueFullError("Generation job queue is full. Retry later.")
        job = GenerationJobDetail(
            id=f"job-{len(self.jobs) + 1}",
            status="queued",
            created_at="2026-06-22T00:00:00+00:00",
            updated_at="2026-06-22T00:00:00+00:00",
            request=request,
        )
        self.jobs.append(job)
        return job

    def get_job(self, job_id):
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def list_jobs(self, *, limit=20, offset=0, status=None):
        jobs = self.jobs
        if status:
            jobs = [job for job in jobs if job.status == status]
        return jobs[offset : offset + limit]


def _response() -> GenerateResponse:
    return GenerateResponse(
        cases=[
            CaseModel(
                id="TC-001",
                title="JWT 登录成功",
                precondition="管理员账号存在",
                steps=["输入账号密码", "点击登录"],
                expected=["登录成功"],
                type=CaseType.functional,
            )
        ],
        metadata=GenerationMetadata(
            model="fake-model",
            attempts=1,
            retrieved_chunks=1,
            retrieved_sources=["knowledge_export/api/auth_permissions.md"],
            prompt_version="test-case-generation-v1",
        ),
    )


def _http_request(request_id: str | None = None):
    return SimpleNamespace(state=SimpleNamespace(request_id=request_id))


def _json(model):
    return model.model_dump(mode="json")


def test_generate_api_success(monkeypatch, fake_history_store) -> None:
    generator = FakeGenerator(response=_response())
    monkeypatch.setattr(routes, "_generator", lambda: generator)

    response = routes.generate_test_cases(
        GenerateRequest.model_validate(
            {"description": "生成 JWT 登录测试用例", "max_cases": 3}
        ),
        _http_request(),
    )

    payload = _json(response)
    assert payload["cases"][0]["id"] == "TC-001"
    assert payload["cases"][0]["title"] == "JWT 登录成功"
    assert payload["metadata"]["retrieved_sources"] == [
        "knowledge_export/api/auth_permissions.md"
    ]
    assert payload["metadata"]["prompt_version"] == "test-case-generation-v1"
    assert payload["metadata"]["usage"]["total_tokens_estimate"] >= 0
    assert generator.requests[0].description == "生成 JWT 登录测试用例"
    assert len(fake_history_store.successes) == 1
    assert fake_history_store.successes[0][0].description == "生成 JWT 登录测试用例"


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (MissingApiKeyError("missing key"), 503),
        (LLMError("upstream failed"), 502),
        (
            GenerationBudgetExceededError(
                "budget exceeded",
                usage=GenerationUsage(prompt_tokens_estimate=10),
            ),
            409,
        ),
        (OutputValidationError("invalid output"), 502),
    ],
)
def test_generate_api_error_mapping(monkeypatch, fake_history_store, error, status_code) -> None:
    monkeypatch.setattr(routes, "_generator", lambda: FakeGenerator(error=error))

    with pytest.raises(HTTPException) as exc_info:
        routes.generate_test_cases(
            GenerateRequest.model_validate({"description": "生成 JWT 登录测试用例"}),
            _http_request(),
        )

    assert exc_info.value.status_code == status_code
    detail = exc_info.value.detail
    if isinstance(error, GenerationBudgetExceededError):
        assert detail["code"] == "budget_exceeded"
        assert detail["gate"] == "budget"
        assert detail["message"] == str(error)
        assert detail["action_required"] == "human_confirmation"
        assert detail["usage"]["prompt_tokens_estimate"] == 10
    else:
        assert detail == str(error)
    assert len(fake_history_store.failures) == 1
    assert fake_history_store.failures[0][1] == str(error)
    if isinstance(error, GenerationBudgetExceededError):
        assert fake_history_store.failures[0][5]["code"] == "budget_exceeded"


def test_generate_api_redacts_sensitive_error_detail_and_history(
    monkeypatch,
    fake_history_store,
) -> None:
    error = LLMError(
        "upstream failed api_key=secret-api-key Authorization: Bearer secret-token"
    )
    monkeypatch.setattr(routes, "_generator", lambda: FakeGenerator(error=error))

    with pytest.raises(HTTPException) as exc_info:
        routes.generate_test_cases(
            GenerateRequest.model_validate({"description": "生成 JWT 登录测试用例"}),
            _http_request(),
        )

    detail = exc_info.value.detail
    stored_error = fake_history_store.failures[0][1]
    assert "secret-api-key" not in detail
    assert "secret-token" not in detail
    assert "secret-api-key" not in stored_error
    assert "secret-token" not in stored_error
    assert "api_key=[redacted]" in detail
    assert "[redacted]" in detail
    assert detail == stored_error


def test_generate_api_redacts_sensitive_gate_detail(monkeypatch, fake_history_store) -> None:
    error = GenerationBudgetExceededError(
        "budget exceeded password=secret-password",
        usage=GenerationUsage(prompt_tokens_estimate=10),
    )
    monkeypatch.setattr(routes, "_generator", lambda: FakeGenerator(error=error))

    with pytest.raises(HTTPException) as exc_info:
        routes.generate_test_cases(
            GenerateRequest.model_validate({"description": "生成 JWT 登录测试用例"}),
            _http_request(),
        )

    detail = exc_info.value.detail
    stored_gate = fake_history_store.failures[0][5]
    assert "secret-password" not in detail["message"]
    assert "secret-password" not in stored_gate["message"]
    assert detail["message"] == "budget exceeded password=[redacted]"
    assert stored_gate["message"] == "budget exceeded password=[redacted]"


def test_generation_job_api(fake_generation_job_queue) -> None:
    submitted = routes.submit_generation_job(
        GenerateRequest.model_validate(
            {"description": "生成 JWT 登录测试用例", "max_cases": 3}
        )
    )
    listing = routes.list_generation_jobs(limit=20, offset=0, status_filter="queued")
    detail = routes.get_generation_job("job-1")
    with pytest.raises(HTTPException) as missing:
        routes.get_generation_job("missing")

    assert submitted.id == "job-1"
    assert submitted.status == "queued"
    assert submitted.request.description == "生成 JWT 登录测试用例"
    assert listing.jobs[0].id == "job-1"
    assert detail.id == "job-1"
    assert missing.value.status_code == 404


def test_generation_job_api_returns_429_when_queue_is_full(fake_generation_job_queue) -> None:
    fake_generation_job_queue.full = True

    with pytest.raises(HTTPException) as exc_info:
        routes.submit_generation_job(
            GenerateRequest.model_validate(
                {"description": "生成 JWT 登录测试用例", "max_cases": 3}
            )
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Generation job queue is full. Retry later."


def test_generation_record_list_and_detail(fake_history_store) -> None:
    fake_history_store.records = [
        GenerationRecordSummary(
            id="record-1",
            created_at="2026-06-21T00:00:00+00:00",
            request_id="req-1",
            status="success",
            description="生成 JWT 登录测试用例",
            duration_ms=123.4,
            model="fake-model",
            attempts=1,
            retrieved_chunks=1,
            retrieved_sources=["knowledge_export/api/auth_permissions.md"],
            case_count=1,
        ),
        GenerationRecordSummary(
            id="record-2",
            created_at="2026-06-21T00:01:00+00:00",
            request_id="req-2",
            status="failed",
            description="生成失败用例",
            duration_ms=12.3,
            case_count=0,
            error="upstream failed",
            gate=GenerationGateDetail(
                code="quality_gate_failed",
                gate="quality",
                message="needs review",
                action_required="human_review",
            ),
        ),
    ]

    listing = routes.list_generation_records(limit=20, offset=0, status_filter="success")
    gates = routes.list_generation_gates(limit=20, offset=0, status_filter="pending")
    approved_before = routes.list_generation_gates(
        limit=20,
        offset=0,
        status_filter="approved",
    )
    resolved_gate = routes.resolve_generation_gate(
        "record-2",
        GenerationGateResolveRequest.model_validate(
            {
                "decision": "approved",
                "resolved_by": "qa-owner",
                "comment": "allowed for import",
            }
        ),
    )
    gates_after_resolve = routes.list_generation_gates(
        limit=20,
        offset=0,
        status_filter="pending",
    )
    approved_after = routes.list_generation_gates(
        limit=20,
        offset=0,
        status_filter="approved",
    )
    all_gates = routes.list_generation_gates(limit=20, offset=0, status_filter="all")
    with pytest.raises(HTTPException) as missing_gate:
        routes.resolve_generation_gate(
            "missing",
            GenerationGateResolveRequest.model_validate({"decision": "rejected"}),
        )
    detail = routes.get_generation_record("record-1")
    with pytest.raises(HTTPException) as missing:
        routes.get_generation_record("missing")

    listing_payload = _json(listing)
    gates_payload = _json(gates)
    approved_before_payload = _json(approved_before)
    resolved_gate_payload = _json(resolved_gate)
    gates_after_resolve_payload = _json(gates_after_resolve)
    approved_after_payload = _json(approved_after)
    all_gates_payload = _json(all_gates)
    detail_payload = _json(detail)

    assert listing_payload["records"][0]["id"] == "record-1"
    assert listing_payload["records"][0]["status"] == "success"
    assert gates_payload["records"][0]["id"] == "record-2"
    assert gates_payload["records"][0]["gate"]["code"] == "quality_gate_failed"
    assert gates_payload["records"][0]["gate_resolution"] is None
    assert approved_before_payload["records"] == []
    assert resolved_gate_payload["gate_resolution"]["status"] == "approved"
    assert resolved_gate_payload["gate_resolution"]["resolved_by"] == "qa-owner"
    assert resolved_gate_payload["gate_resolution"]["comment"] == "allowed for import"
    assert gates_after_resolve_payload["records"] == []
    assert approved_after_payload["records"][0]["id"] == "record-2"
    assert all_gates_payload["records"][0]["id"] == "record-2"
    assert missing_gate.value.status_code == 404
    assert detail_payload["request"]["description"] == "生成 JWT 登录测试用例"
    assert detail_payload["response"]["cases"][0]["title"] == "JWT 登录成功"
    assert detail_payload["usage"]["total_tokens_estimate"] == 0
    assert missing.value.status_code == 404
