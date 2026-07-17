import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.middleware import add_request_middleware
from app.services.http_metrics import get_http_metrics_snapshot, reset_http_metrics


@pytest.fixture(autouse=True)
def clear_settings_caches() -> None:
    get_settings.cache_clear()
    reset_http_metrics()
    yield
    reset_http_metrics()
    get_settings.cache_clear()


def create_middleware_test_app() -> FastAPI:
    app = FastAPI()
    add_request_middleware(app, get_settings())

    @app.post("/api/v1/ping")
    async def api_ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def request_asgi(
    app,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict | None = None,
) -> httpx.Response:
    return asyncio.run(_request_asgi(app, method, path, headers=headers, json_body=json_body))


async def _request_asgi(
    app,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None,
    json_body: dict | None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.request(method, path, headers=headers, json=json_body)


def test_api_rate_limit_returns_429_after_configured_limit(monkeypatch) -> None:
    monkeypatch.setenv("APP_API_KEY", "test-secret")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")
    app = create_middleware_test_app()

    headers = {"X-API-Key": "test-secret"}
    payload = {"message": "ok"}
    first = request_asgi(app, "POST", "/api/v1/ping", headers=headers, json_body=payload)
    second = request_asgi(app, "POST", "/api/v1/ping", headers=headers, json_body=payload)
    limited = request_asgi(app, "POST", "/api/v1/ping", headers=headers, json_body=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert limited.status_code == 429
    assert limited.json()["detail"] == "Rate limit exceeded."
    assert limited.headers["retry-after"] == "60"
    assert limited.headers["x-request-id"]
    assert float(limited.headers["x-process-time-ms"]) >= 0
    metrics = get_http_metrics_snapshot()
    assert metrics["total_count"] == 3
    assert [
        (item["method"], item["route"], item["status_code"], item["count"])
        for item in metrics["requests"]
    ] == [
        ("POST", "/api/v1/ping", 200, 2),
        ("POST", "/api/v1/ping", 429, 1),
    ]


def test_health_endpoint_is_not_rate_limited(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")
    app = create_middleware_test_app()

    responses = [request_asgi(app, "GET", "/health") for _ in range(3)]

    assert [response.status_code for response in responses] == [200, 200, 200]


def test_request_id_header_is_preserved(monkeypatch) -> None:
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")
    app = create_middleware_test_app()

    response = request_asgi(app, "GET", "/health", headers={"X-Request-ID": "req-test-001"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "req-test-001"
    assert float(response.headers["x-process-time-ms"]) >= 0
    metrics = get_http_metrics_snapshot()
    assert metrics["requests"][0]["route"] == "/health"
