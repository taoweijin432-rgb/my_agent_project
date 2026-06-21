import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.api.routes import require_api_key
from app.main import app
from app.models.test_case import (
    GenerateResponse,
    GenerationGateDetail,
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


client = TestClient(app)


@pytest.fixture(autouse=True)
def bypass_api_key() -> None:
    app.dependency_overrides[require_api_key] = lambda: None
    yield
    app.dependency_overrides.pop(require_api_key, None)


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


def test_generate_api_success(monkeypatch, fake_history_store) -> None:
    generator = FakeGenerator(response=_response())
    monkeypatch.setattr(routes, "_generator", lambda: generator)

    response = client.post(
        "/api/v1/test-cases/generate",
        json={"description": "生成 JWT 登录测试用例", "max_cases": 3},
    )

    assert response.status_code == 200
    payload = response.json()
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

    response = client.post(
        "/api/v1/test-cases/generate",
        json={"description": "生成 JWT 登录测试用例"},
    )

    assert response.status_code == status_code
    detail = response.json()["detail"]
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


def test_generation_job_api(fake_generation_job_queue) -> None:
    submitted = client.post(
        "/api/v1/test-cases/generation-jobs",
        json={"description": "生成 JWT 登录测试用例", "max_cases": 3},
    )
    listing = client.get("/api/v1/test-cases/generation-jobs?status=queued")
    detail = client.get("/api/v1/test-cases/generation-jobs/job-1")
    missing = client.get("/api/v1/test-cases/generation-jobs/missing")

    assert submitted.status_code == 202
    assert submitted.json()["id"] == "job-1"
    assert submitted.json()["status"] == "queued"
    assert submitted.json()["request"]["description"] == "生成 JWT 登录测试用例"
    assert listing.status_code == 200
    assert listing.json()["jobs"][0]["id"] == "job-1"
    assert detail.status_code == 200
    assert detail.json()["id"] == "job-1"
    assert missing.status_code == 404


def test_generation_job_api_returns_429_when_queue_is_full(fake_generation_job_queue) -> None:
    fake_generation_job_queue.full = True

    response = client.post(
        "/api/v1/test-cases/generation-jobs",
        json={"description": "生成 JWT 登录测试用例", "max_cases": 3},
    )

    assert response.status_code == 429
    assert response.json()["detail"] == "Generation job queue is full. Retry later."


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

    listing = client.get("/api/v1/generation-records?status=success")
    gates = client.get("/api/v1/generation-gates")
    approved_before = client.get("/api/v1/generation-gates?status=approved")
    resolved_gate = client.post(
        "/api/v1/generation-gates/record-2/resolve",
        json={
            "decision": "approved",
            "resolved_by": "qa-owner",
            "comment": "allowed for import",
        },
    )
    gates_after_resolve = client.get("/api/v1/generation-gates")
    approved_after = client.get("/api/v1/generation-gates?status=approved")
    all_gates = client.get("/api/v1/generation-gates?status=all")
    missing_gate = client.post(
        "/api/v1/generation-gates/missing/resolve",
        json={"decision": "rejected"},
    )
    detail = client.get("/api/v1/generation-records/record-1")
    missing = client.get("/api/v1/generation-records/missing")

    assert listing.status_code == 200
    assert listing.json()["records"][0]["id"] == "record-1"
    assert listing.json()["records"][0]["status"] == "success"
    assert gates.status_code == 200
    assert gates.json()["records"][0]["id"] == "record-2"
    assert gates.json()["records"][0]["gate"]["code"] == "quality_gate_failed"
    assert gates.json()["records"][0]["gate_resolution"] is None
    assert approved_before.status_code == 200
    assert approved_before.json()["records"] == []
    assert resolved_gate.status_code == 200
    assert resolved_gate.json()["gate_resolution"]["status"] == "approved"
    assert resolved_gate.json()["gate_resolution"]["resolved_by"] == "qa-owner"
    assert resolved_gate.json()["gate_resolution"]["comment"] == "allowed for import"
    assert gates_after_resolve.status_code == 200
    assert gates_after_resolve.json()["records"] == []
    assert approved_after.status_code == 200
    assert approved_after.json()["records"][0]["id"] == "record-2"
    assert all_gates.status_code == 200
    assert all_gates.json()["records"][0]["id"] == "record-2"
    assert missing_gate.status_code == 404
    assert detail.status_code == 200
    assert detail.json()["request"]["description"] == "生成 JWT 登录测试用例"
    assert detail.json()["response"]["cases"][0]["title"] == "JWT 登录成功"
    assert detail.json()["usage"]["total_tokens_estimate"] == 0
    assert missing.status_code == 404
