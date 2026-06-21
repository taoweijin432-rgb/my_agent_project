import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.api.routes import require_api_key
from app.main import app
from app.models.test_case import (
    GenerateResponse,
    GenerationMetadata,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.generator import OutputValidationError
from app.services.llm import LLMError, MissingApiKeyError


client = TestClient(app)


@pytest.fixture(autouse=True)
def bypass_api_key() -> None:
    app.dependency_overrides[require_api_key] = lambda: None
    yield
    app.dependency_overrides.pop(require_api_key, None)


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


def test_generate_api_success(monkeypatch) -> None:
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
    assert generator.requests[0].description == "生成 JWT 登录测试用例"


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (MissingApiKeyError("missing key"), 503),
        (LLMError("upstream failed"), 502),
        (OutputValidationError("invalid output"), 502),
    ],
)
def test_generate_api_error_mapping(monkeypatch, error, status_code) -> None:
    monkeypatch.setattr(routes, "_generator", lambda: FakeGenerator(error=error))

    response = client.post(
        "/api/v1/test-cases/generate",
        json={"description": "生成 JWT 登录测试用例"},
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)
