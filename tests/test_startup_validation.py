import pytest

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_create_app_rejects_invalid_production_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_API_KEY", "short")
    monkeypatch.setenv("ZHIPU_API_KEY", "short")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")

    with pytest.raises(RuntimeError, match="Invalid production configuration"):
        create_app()


def test_create_app_accepts_hardened_production_configuration(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("APP_API_KEY", "prod-service-key-1234567890")
    monkeypatch.setenv("ZHIPU_API_KEY", "prod-zhipu-key-1234567890")
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "https://qa.example.com")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("EMBEDDING_LOCAL_FILES_ONLY", "true")
    monkeypatch.setenv(
        "TEST_TOOL_HTTP_BASE_URL_ALLOWLIST",
        "https://api-under-test.example.com",
    )
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "true")
    monkeypatch.setenv("GENERATION_HISTORY_ENABLED", "true")
    monkeypatch.setenv("GENERATION_HISTORY_DB_PATH", "data/app.sqlite3")

    app = create_app()

    assert app.title == "AI Test Case Generator"
