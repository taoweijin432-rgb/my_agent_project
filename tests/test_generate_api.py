import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.api.routes import require_api_key
from app.main import app
from app.models.test_case import (
    GenerateResponse,
    GenerationRecordDetail,
    GenerationRecordSummary,
    GenerationMetadata,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
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

    def record_failure(self, request, error, *, duration_ms, request_id=None, usage=None):
        self.failures.append((request, error, duration_ms, request_id, usage))
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
        (GenerationBudgetExceededError("budget exceeded"), 409),
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
    assert response.json()["detail"] == str(error)
    assert len(fake_history_store.failures) == 1
    assert fake_history_store.failures[0][1] == str(error)


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
        ),
    ]

    listing = client.get("/api/v1/generation-records?status=success")
    detail = client.get("/api/v1/generation-records/record-1")
    missing = client.get("/api/v1/generation-records/missing")

    assert listing.status_code == 200
    assert listing.json()["records"][0]["id"] == "record-1"
    assert listing.json()["records"][0]["status"] == "success"
    assert detail.status_code == 200
    assert detail.json()["request"]["description"] == "生成 JWT 登录测试用例"
    assert detail.json()["response"]["cases"][0]["title"] == "JWT 登录成功"
    assert detail.json()["usage"]["total_tokens_estimate"] == 0
    assert missing.status_code == 404
