import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import get_settings
from app.main import create_app


CASE = {
    "id": "TC-001",
    "title": "登录成功",
    "precondition": "用户已注册",
    "steps": ["输入手机号", "输入验证码", "点击登录"],
    "expected": ["登录成功"],
    "type": "functional",
}


@pytest.fixture(autouse=True)
def clear_settings_caches() -> None:
    get_settings.cache_clear()
    routes._settings.cache_clear()
    yield
    get_settings.cache_clear()
    routes._settings.cache_clear()


def test_api_rate_limit_returns_429_after_configured_limit(monkeypatch) -> None:
    monkeypatch.setenv("APP_API_KEY", "test-secret")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")
    client = TestClient(create_app())

    headers = {"X-API-Key": "test-secret"}
    first = client.post("/api/v1/test-cases/export", headers=headers, json={"cases": [CASE]})
    second = client.post("/api/v1/test-cases/export", headers=headers, json={"cases": [CASE]})
    limited = client.post("/api/v1/test-cases/export", headers=headers, json={"cases": [CASE]})

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Rate limit exceeded."
    assert limited.headers["Retry-After"] == "60"
    assert limited.headers["X-Request-ID"]
    assert float(limited.headers["X-Process-Time-ms"]) >= 0


def test_health_endpoint_is_not_rate_limited(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")
    client = TestClient(create_app())

    responses = [client.get("/health") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 200]


def test_request_id_header_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")
    client = TestClient(create_app())

    response = client.get("/health", headers={"X-Request-ID": "req-test-001"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-001"
    assert float(response.headers["X-Process-Time-ms"]) >= 0
