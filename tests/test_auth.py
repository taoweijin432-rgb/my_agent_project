from fastapi.testclient import TestClient

from app.api import routes
from app.core.config import Settings
from app.main import app


client = TestClient(app)


CASE = {
    "id": "TC-001",
    "title": "登录成功",
    "precondition": "用户已注册",
    "steps": ["输入手机号", "输入验证码", "点击登录"],
    "expected": ["登录成功"],
    "type": "functional",
}


def test_health_endpoint_is_public(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_settings", lambda: Settings(app_api_key=None))

    response = client.get("/health")

    assert response.status_code == 200


def test_business_endpoint_fails_closed_when_api_key_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_settings", lambda: Settings(app_api_key=None))

    response = client.post("/api/v1/test-cases/export", json={"cases": [CASE]})

    assert response.status_code == 503
    assert response.json()["detail"] == "APP_API_KEY is not configured."


def test_business_endpoint_requires_valid_api_key(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_settings", lambda: Settings(app_api_key="test-secret"))

    missing = client.post("/api/v1/test-cases/export", json={"cases": [CASE]})
    wrong = client.post(
        "/api/v1/test-cases/export",
        headers={"X-API-Key": "wrong-secret"},
        json={"cases": [CASE]},
    )
    accepted = client.post(
        "/api/v1/test-cases/export",
        headers={"X-API-Key": "test-secret"},
        json={"cases": [CASE]},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert accepted.status_code == 200
