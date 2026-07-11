import pytest
from fastapi import HTTPException

from app.api import routes
from app.core.config import Settings, get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_health_endpoint_is_public(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(routes, "_settings", lambda: Settings(app_api_key=None))
    app = create_app()
    health_route = next(route for route in app.routes if getattr(route, "path", None) == "/health")

    assert health_route.endpoint() == {
        "status": "ok",
        "service": "AI Test Case Generator",
    }


def test_business_endpoint_fails_closed_when_api_key_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_settings", lambda: Settings(app_api_key=None))

    with pytest.raises(HTTPException) as exc_info:
        routes.require_api_key(None)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "APP_API_KEY or APP_API_KEYS is not configured."


def test_business_endpoint_requires_valid_api_key(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_settings", lambda: Settings(app_api_key="test-secret"))

    with pytest.raises(HTTPException) as missing:
        routes.require_api_key(None)
    with pytest.raises(HTTPException) as wrong:
        routes.require_api_key("wrong-secret")

    routes.require_api_key("test-secret")
    assert missing.value.status_code == 401
    assert wrong.value.status_code == 401
