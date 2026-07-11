import pytest
from fastapi import HTTPException

from app.api import routes
from app.core.config import Settings


def test_require_api_key_accepts_any_configured_key(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "_settings",
        lambda: Settings(
            app_api_key="primary-service-key",
            app_api_keys=["next-service-key", "emergency-service-key"],
        ),
    )

    routes.require_api_key("primary-service-key")
    routes.require_api_key("next-service-key")
    routes.require_api_key("emergency-service-key")


def test_require_api_key_rejects_unknown_key(monkeypatch) -> None:
    monkeypatch.setattr(
        routes,
        "_settings",
        lambda: Settings(app_api_keys=["current-service-key"]),
    )

    with pytest.raises(HTTPException) as error:
        routes.require_api_key("old-service-key")

    assert error.value.status_code == 401
    assert error.value.detail == "Invalid API key."


def test_require_api_key_fails_closed_without_configured_keys(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_settings", lambda: Settings())

    with pytest.raises(HTTPException) as error:
        routes.require_api_key("any-service-key")

    assert error.value.status_code == 503
    assert error.value.detail == "APP_API_KEY or APP_API_KEYS is not configured."
