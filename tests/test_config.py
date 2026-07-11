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


def test_settings_reads_multiple_api_keys(monkeypatch) -> None:
    monkeypatch.setenv("APP_API_KEY", "primary-service-key")
    monkeypatch.setenv(
        "APP_API_KEYS",
        "primary-service-key, next-service-key , emergency-service-key",
    )

    settings = get_settings()

    assert settings.app_api_key == "primary-service-key"
    assert settings.app_api_keys == [
        "primary-service-key",
        "next-service-key",
        "emergency-service-key",
    ]
    assert settings.accepted_api_keys == [
        "primary-service-key",
        "next-service-key",
        "emergency-service-key",
    ]


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


def test_settings_reads_agent_review_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_REVIEW_ENABLED", "false")
    monkeypatch.setenv("AGENT_REVIEW_RETRY_ENABLED", "true")
    monkeypatch.setenv("AGENT_REVIEW_MIN_SCORE", "75")
    monkeypatch.setenv("AGENT_REVIEW_REQUIRE_PASS", "true")

    settings = get_settings()

    assert settings.agent_review_enabled is False
    assert settings.agent_review_retry_enabled is True
    assert settings.agent_review_min_score == 75
    assert settings.agent_review_require_pass is True


def test_settings_reads_agent_budget_gate_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_BUDGET_MAX_PROMPT_TOKENS", "1200")
    monkeypatch.setenv("AGENT_BUDGET_MAX_ESTIMATED_COST", "0.25")
    monkeypatch.setenv("AGENT_WORKFLOW_BACKEND", "local")

    settings = get_settings()

    assert settings.agent_budget_max_prompt_tokens == 1200
    assert settings.agent_budget_max_estimated_cost == 0.25
    assert settings.agent_workflow_backend == "local"


def test_settings_defaults_to_langgraph_workflow_backend() -> None:
    settings = get_settings()

    assert settings.agent_workflow_backend == "langgraph"


def test_settings_reads_generation_job_queue_configuration(monkeypatch) -> None:
    monkeypatch.setenv("GENERATION_JOB_QUEUE_BACKEND", "rq")
    monkeypatch.setenv("GENERATION_JOB_MAX_WORKERS", "4")
    monkeypatch.setenv("GENERATION_JOB_MAX_QUEUE_SIZE", "250")
    monkeypatch.setenv("GENERATION_JOB_RETENTION_SECONDS", "7200")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/1")
    monkeypatch.setenv("RQ_QUEUE_NAME", "generation-test")
    monkeypatch.setenv("RQ_JOB_TIMEOUT_SECONDS", "1200")
    monkeypatch.setenv("RQ_RESULT_TTL_SECONDS", "1800")
    monkeypatch.setenv("RQ_FAILURE_TTL_SECONDS", "3600")
    monkeypatch.setenv("GENERATION_JOB_STALE_AFTER_SECONDS", "2400")

    settings = get_settings()

    assert settings.generation_job_queue_backend == "rq"
    assert settings.generation_job_max_workers == 4
    assert settings.generation_job_max_queue_size == 250
    assert settings.generation_job_retention_seconds == 7200
    assert settings.redis_url == "redis://127.0.0.1:6379/1"
    assert settings.rq_queue_name == "generation-test"
    assert settings.rq_job_timeout_seconds == 1200
    assert settings.rq_result_ttl_seconds == 1800
    assert settings.rq_failure_ttl_seconds == 3600
    assert settings.generation_job_stale_after_seconds == 2400


def test_settings_reads_test_tool_pytest_configuration(monkeypatch) -> None:
    monkeypatch.setenv(
        "TEST_TOOL_HTTP_BASE_URL_ALLOWLIST",
        "http://127.0.0.1:8000, http://localhost:8000",
    )
    monkeypatch.setenv("TEST_TOOL_ARTIFACT_DIR", "data/custom-artifacts")
    monkeypatch.setenv("TEST_TOOL_ARTIFACT_MAX_BYTES", "4096")
    monkeypatch.setenv("TEST_TOOL_ARTIFACT_RETENTION_SECONDS", "3600")
    monkeypatch.setenv("TEST_TOOL_PYTEST_ENABLED", "true")
    monkeypatch.setenv("TEST_TOOL_PYTEST_ALLOWED_PATHS", "tests,generated_tests")
    monkeypatch.setenv("TEST_TOOL_PYTEST_TIMEOUT_SECONDS", "30")

    settings = get_settings()

    assert settings.test_tool_http_base_url_allowlist == [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    assert settings.test_tool_artifact_dir == "data/custom-artifacts"
    assert settings.test_tool_artifact_max_bytes == 4096
    assert settings.test_tool_artifact_retention_seconds == 3600
    assert settings.test_tool_pytest_enabled is True
    assert settings.test_tool_pytest_allowed_paths == ["tests", "generated_tests"]
    assert settings.test_tool_pytest_timeout_seconds == 30


def test_settings_reads_agent_query_rewrite_configuration(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_QUERY_REWRITE_ENABLED", "false")
    monkeypatch.setenv("AGENT_QUERY_REWRITE_MIN_CHUNKS", "2")

    settings = get_settings()

    assert settings.agent_query_rewrite_enabled is False
    assert settings.agent_query_rewrite_min_chunks == 2


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
    monkeypatch.setenv("REQUEST_LOG_FORMAT", "json")

    settings = get_settings()

    assert settings.rate_limit_enabled is False
    assert settings.rate_limit_requests == 10
    assert settings.rate_limit_window_seconds == 30
    assert settings.request_log_enabled is False
    assert settings.request_log_format == "json"


def test_settings_falls_back_for_invalid_rate_limit_values(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "0")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "-1")

    settings = get_settings()

    assert settings.rate_limit_requests == 60
    assert settings.rate_limit_window_seconds == 60


def test_settings_reads_generation_history_configuration(monkeypatch) -> None:
    monkeypatch.setenv("GENERATION_HISTORY_ENABLED", "false")
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("DATABASE_URL", "mysql://qa:secret@localhost:3306/agent")
    monkeypatch.setenv("GENERATION_HISTORY_DB_PATH", "data/history-test.sqlite3")

    settings = get_settings()

    assert settings.generation_history_enabled is False
    assert settings.database_backend == "sqlite"
    assert settings.database_url == "mysql://qa:secret@localhost:3306/agent"
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


def test_production_validation_accepts_hardened_app_api_keys() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="production",
            app_api_keys=[
                "prod-service-key-current-123456",
                "prod-service-key-next-123456",
            ],
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=True,
            generation_history_db_path="data/app.sqlite3",
        )
    )

    assert errors == []


def test_production_validation_rejects_weak_api_keys_in_list() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="production",
            app_api_keys=["prod-service-key-current-123456", "example-next-key"],
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=True,
            generation_history_db_path="data/app.sqlite3",
        )
    )

    assert any("APP_API_KEY" in error and "APP_API_KEYS" in error for error in errors)


def test_production_validation_rejects_disabled_runtime_guards() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="prod",
            app_api_key="prod-service-key-1234567890",
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=False,
            agent_review_enabled=False,
            rate_limit_enabled=False,
            request_log_enabled=False,
            request_log_format="plain",
            generation_history_enabled=False,
            generation_history_db_path=":memory:",
        )
    )

    assert any("EMBEDDING_LOCAL_FILES_ONLY" in error for error in errors)
    assert any("AGENT_REVIEW_ENABLED" in error for error in errors)
    assert any("RATE_LIMIT_ENABLED" in error for error in errors)
    assert any("REQUEST_LOG_ENABLED" in error for error in errors)
    assert any("REQUEST_LOG_FORMAT" in error for error in errors)
    assert any("GENERATION_HISTORY_ENABLED" in error for error in errors)
    assert any("GENERATION_HISTORY_DB_PATH" in error for error in errors)


def test_production_validation_rejects_unknown_workflow_backend() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="prod",
            app_api_key="prod-service-key-1234567890",
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=True,
            generation_history_db_path="data/app.sqlite3",
            agent_workflow_backend="unknown",
        )
    )

    assert any("AGENT_WORKFLOW_BACKEND" in error for error in errors)


def test_production_validation_rejects_unknown_database_backend() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="prod",
            app_api_key="prod-service-key-1234567890",
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=True,
            database_backend="oracle",
            generation_history_db_path="data/app.sqlite3",
        )
    )

    assert any("DATABASE_BACKEND" in error for error in errors)


def test_production_validation_requires_database_url_for_mysql() -> None:
    errors = validate_production_settings(
        Settings(
            app_env="prod",
            app_api_key="prod-service-key-1234567890",
            zhipu_api_key="prod-zhipu-key-1234567890",
            cors_allow_origins=["https://qa.example.com"],
            embedding_provider="sentence_transformers",
            embedding_local_files_only=True,
            database_backend="mysql",
            database_url=None,
        )
    )

    assert any("DATABASE_URL" in error for error in errors)
