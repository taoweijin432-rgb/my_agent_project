import pytest

from app.core.config import Settings, get_settings, validate_production_settings


@pytest.fixture(autouse=True)
def clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_reads_cors_origins_from_csv(monkeypatch) -> None:
    monkeypatch.setenv(
        "CORS_ALLOW_ORIGINS",
        "https://qa.example.com, https://admin.example.com",
    )

    settings = get_settings()

    assert settings.cors_allow_origins == [
        "https://qa.example.com",
        "https://admin.example.com",
    ]


def test_settings_reads_app_environment(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")

    settings = get_settings()

    assert settings.app_env == "production"
    assert settings.is_production is True


def test_settings_disables_credentials_when_cors_origin_is_wildcard(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", "*")
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")

    settings = get_settings()

    assert settings.cors_allow_origins == ["*"]
    assert settings.cors_allow_credentials is False


def test_settings_falls_back_for_invalid_llm_numeric_values(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MAX_RETRIES", "-1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "0")
    monkeypatch.setenv("LLM_PROMPT_PRICE_PER_1K_TOKENS", "-1")
    monkeypatch.setenv("LLM_COMPLETION_PRICE_PER_1K_TOKENS", "invalid")

    settings = get_settings()

    assert settings.llm_max_retries == 2
    assert settings.llm_timeout_seconds == 60
    assert settings.llm_prompt_price_per_1k_tokens == 0
    assert settings.llm_completion_price_per_1k_tokens == 0


def test_settings_reads_llm_cost_configuration(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROMPT_PRICE_PER_1K_TOKENS", "0.01")
    monkeypatch.setenv("LLM_COMPLETION_PRICE_PER_1K_TOKENS", "0.02")
    monkeypatch.setenv("LLM_COST_CURRENCY", "CNY")

    settings = get_settings()

    assert settings.llm_prompt_price_per_1k_tokens == 0.01
    assert settings.llm_completion_price_per_1k_tokens == 0.02
    assert settings.llm_cost_currency == "CNY"


def test_settings_reads_embedding_configuration(monkeypatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "sentence_transformers")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", ".model_cache/huggingface")
    monkeypatch.setenv("EMBEDDING_DEVICE", "cpu")
    monkeypatch.setenv("EMBEDDING_LOCAL_FILES_ONLY", "true")

    settings = get_settings()

    assert settings.embedding_provider == "sentence_transformers"
    assert settings.embedding_model == "BAAI/bge-small-zh-v1.5"
    assert settings.embedding_cache_dir == ".model_cache/huggingface"
    assert settings.embedding_device == "cpu"
    assert settings.embedding_local_files_only is True


def test_settings_reads_rate_limit_configuration(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "10")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setenv("REQUEST_LOG_ENABLED", "false")

    settings = get_settings()

    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_requests == 10
    assert settings.rate_limit_window_seconds == 30
    assert settings.request_log_enabled is False


def test_settings_falls_back_for_invalid_rate_limit_values(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "0")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "-1")

    settings = get_settings()

    assert settings.rate_limit_requests == 60
    assert settings.rate_limit_window_seconds == 60


def test_settings_reads_generation_history_configuration(monkeypatch) -> None:
    monkeypatch.setenv("GENERATION_HISTORY_ENABLED", "false")
    monkeypatch.setenv("GENERATION_HISTORY_DB_PATH", "data/history-test.sqlite3")

    settings = get_settings()

    assert settings.generation_history_enabled is False
    assert settings.generation_history_db_path == "data/history-test.sqlite3"


def test_production_validation_is_disabled_for_development_defaults() -> None:
    assert validate_production_settings(Settings()) == []


def test_production_validation_rejects_unsafe_defaults() -> None:
    errors = validate_production_settings(Settings(app_env="production"))

    assert any("APP_API_KEY" in error for error in errors)
    assert any("ZHIPU_API_KEY" in error for error in errors)
    assert any("localhost origins" in error for error in errors)
    assert any("EMBEDDING_PROVIDER" in error and "hash" in error for error in errors)


def test_production_validation_accepts_hardened_settings() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="production",
            app_api_key="prod-service-key-1234567890",
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=True,
            generation_history_db_path="data/app.sqlite3",
        )
    )

    assert errors == []


def test_production_validation_rejects_disabled_runtime_guards() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="prod",
            app_api_key="prod-service-key-1234567890",
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=False,
            rate_limit_enabled=False,
            request_log_enabled=False,
            generation_history_enabled=False,
            generation_history_db_path=":memory:",
        )
    )

    assert any("EMBEDDING_LOCAL_FILES_ONLY" in error for error in errors)
    assert any("RATE_LIMIT_ENABLED" in error for error in errors)
    assert any("REQUEST_LOG_ENABLED" in error for error in errors)
    assert any("GENERATION_HISTORY_ENABLED" in error for error in errors)
    assert any("GENERATION_HISTORY_DB_PATH" in error for error in errors)
