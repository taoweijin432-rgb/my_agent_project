import ast
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORS_ALLOW_ORIGINS = (
    "http://127.0.0.1:8000,"
    "http://localhost:8000,"
    "http://127.0.0.1:5173,"
    "http://localhost:5173"
)
PRODUCTION_ENV_NAMES = {"prod", "production"}


def _load_legacy_config() -> dict[str, str]:
    config_path = PROJECT_ROOT / ".env" / "config.py"
    if not config_path.exists():
        return {}

    tree = ast.parse(config_path.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        value = ast.literal_eval(node.value)
        if isinstance(value, str):
            values[node.targets[0].id] = value
    return values


def _get_config_value(
    legacy: dict[str, str],
    key: str,
    *,
    aliases: tuple[str, ...] = (),
    default: str | None = None,
) -> str | None:
    for name in (key, *aliases):
        value = os.getenv(name)
        if value:
            return value
    for name in (key, *aliases):
        value = legacy.get(name)
        if value:
            return value
    return default


def _get_int(value: str | None, default: int, *, minimum: int | None = None) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    if minimum is not None and parsed < minimum:
        return default
    return parsed


def _get_float(value: str | None, default: float, *, minimum: float | None = None) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    if minimum is not None and parsed < minimum:
        return default
    return parsed


def _get_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _get_csv(value: str | None, default: str) -> list[str]:
    raw = value or default
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


@dataclass(frozen=True)
class Settings:
    app_name: str = "AI Test Case Generator"
    app_env: str = "development"
    app_api_key: str | None = None
    app_api_keys: list[str] = field(default_factory=list)
    zhipu_api_key: str | None = None
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_chat_model: str = "glm-4-flash"
    chroma_path: str = "data/chroma"
    chroma_collection: str = "test_knowledge"
    embedding_provider: str = "hash"
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_cache_dir: str = ".model_cache/huggingface"
    embedding_device: str = "cpu"
    embedding_local_files_only: bool = False
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 0.0
    llm_prompt_price_per_1k_tokens: float = 0.0
    llm_completion_price_per_1k_tokens: float = 0.0
    llm_cost_currency: str = "CNY"
    agent_review_enabled: bool = True
    agent_review_retry_enabled: bool = False
    agent_review_min_score: int = 50
    agent_review_require_pass: bool = False
    agent_query_rewrite_enabled: bool = True
    agent_query_rewrite_min_chunks: int = 1
    agent_budget_max_prompt_tokens: int = 0
    agent_budget_max_estimated_cost: float = 0.0
    agent_workflow_backend: str = "langgraph"
    generation_job_queue_backend: str = "in_memory"
    generation_job_max_workers: int = 2
    generation_job_max_queue_size: int = 100
    generation_job_retention_seconds: int = 3600
    redis_url: str = "redis://127.0.0.1:6379/0"
    rq_queue_name: str = "generation"
    rq_job_timeout_seconds: int = 900
    rq_result_ttl_seconds: int = 3600
    rq_failure_ttl_seconds: int = 86400
    generation_job_stale_after_seconds: int = 1800
    test_tool_http_base_url_allowlist: list[str] = field(default_factory=list)
    test_tool_http_allowed_headers: list[str] = field(
        default_factory=lambda: ["Accept", "Content-Type", "X-Request-ID"]
    )
    test_tool_artifact_dir: str = "data/test-artifacts"
    test_tool_artifact_max_bytes: int = 200000
    test_tool_artifact_retention_seconds: int = 604800
    test_tool_pytest_enabled: bool = False
    test_tool_pytest_allowed_paths: list[str] = field(default_factory=lambda: ["tests"])
    test_tool_pytest_timeout_seconds: int = 60
    test_tool_pytest_env_allowlist: list[str] = field(
        default_factory=lambda: ["PATH", "PYTHONPATH"]
    )
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    request_log_enabled: bool = True
    request_log_format: str = "text"
    database_backend: str = "sqlite"
    database_url: str | None = None
    mysql_connect_timeout_seconds: int = 10
    mysql_read_timeout_seconds: int = 30
    mysql_write_timeout_seconds: int = 30
    generation_history_enabled: bool = True
    generation_history_db_path: str = "data/app.sqlite3"
    cors_allow_origins: list[str] = field(
        default_factory=lambda: _get_csv(None, DEFAULT_CORS_ALLOW_ORIGINS)
    )
    cors_allow_credentials: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in PRODUCTION_ENV_NAMES

    @property
    def accepted_api_keys(self) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        for raw_key in [self.app_api_key, *self.app_api_keys]:
            if raw_key is None:
                continue
            key = raw_key.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
        return keys


@lru_cache
def get_settings() -> Settings:
    legacy = _load_legacy_config()
    cors_allow_origins = _get_csv(
        _get_config_value(
            legacy,
            "CORS_ALLOW_ORIGINS",
            default=DEFAULT_CORS_ALLOW_ORIGINS,
        ),
        DEFAULT_CORS_ALLOW_ORIGINS,
    )
    cors_allow_credentials = _get_bool(
        _get_config_value(legacy, "CORS_ALLOW_CREDENTIALS"),
        False,
    )
    if "*" in cors_allow_origins and cors_allow_credentials:
        cors_allow_credentials = False

    return Settings(
        app_env=(
            _get_config_value(
                legacy,
                "APP_ENV",
                aliases=("ENVIRONMENT",),
                default="development",
            )
            or "development"
        ).strip().lower(),
        app_api_key=_get_config_value(
            legacy,
            "APP_API_KEY",
            aliases=("SERVICE_API_KEY",),
        ),
        app_api_keys=_get_csv(
            _get_config_value(
                legacy,
                "APP_API_KEYS",
                aliases=("SERVICE_API_KEYS",),
            ),
            "",
        ),
        zhipu_api_key=_get_config_value(
            legacy,
            "ZHIPU_API_KEY",
            aliases=("BIGMODEL_API_KEY", "DEEPSEEK_API_KEY"),
        ),
        zhipu_base_url=(
            _get_config_value(
                legacy,
                "ZHIPU_BASE_URL",
                aliases=("BIGMODEL_BASE_URL", "DEEPSEEK_BASE_URL"),
                default="https://open.bigmodel.cn/api/paas/v4",
            )
            or "https://open.bigmodel.cn/api/paas/v4"
        ).rstrip("/"),
        zhipu_chat_model=_get_config_value(
            legacy,
            "ZHIPU_CHAT_MODEL",
            aliases=("BIGMODEL_CHAT_MODEL", "DEEPSEEK_CHAT_MODEL"),
            default="glm-4-flash",
        )
        or "glm-4-flash",
        chroma_path=_get_config_value(legacy, "CHROMA_PATH", default="data/chroma")
        or "data/chroma",
        chroma_collection=_get_config_value(
            legacy,
            "CHROMA_COLLECTION",
            default="test_knowledge",
        )
        or "test_knowledge",
        embedding_provider=(
            _get_config_value(legacy, "EMBEDDING_PROVIDER", default="hash") or "hash"
        ).strip().lower(),
        embedding_model=_get_config_value(
            legacy,
            "EMBEDDING_MODEL",
            default="BAAI/bge-small-zh-v1.5",
        )
        or "BAAI/bge-small-zh-v1.5",
        embedding_cache_dir=_get_config_value(
            legacy,
            "EMBEDDING_CACHE_DIR",
            default=".model_cache/huggingface",
        )
        or ".model_cache/huggingface",
        embedding_device=_get_config_value(legacy, "EMBEDDING_DEVICE", default="cpu")
        or "cpu",
        embedding_local_files_only=_get_bool(
            _get_config_value(legacy, "EMBEDDING_LOCAL_FILES_ONLY"),
            False,
        ),
        llm_timeout_seconds=_get_int(
            _get_config_value(legacy, "LLM_TIMEOUT_SECONDS"),
            60,
            minimum=1,
        ),
        llm_max_retries=_get_int(
            _get_config_value(legacy, "LLM_MAX_RETRIES"),
            2,
            minimum=0,
        ),
        llm_retry_backoff_seconds=_get_float(
            _get_config_value(legacy, "LLM_RETRY_BACKOFF_SECONDS"),
            0.0,
            minimum=0.0,
        ),
        llm_prompt_price_per_1k_tokens=_get_float(
            _get_config_value(legacy, "LLM_PROMPT_PRICE_PER_1K_TOKENS"),
            0.0,
            minimum=0.0,
        ),
        llm_completion_price_per_1k_tokens=_get_float(
            _get_config_value(legacy, "LLM_COMPLETION_PRICE_PER_1K_TOKENS"),
            0.0,
            minimum=0.0,
        ),
        llm_cost_currency=_get_config_value(
            legacy,
            "LLM_COST_CURRENCY",
            default="CNY",
        )
        or "CNY",
        agent_review_enabled=_get_bool(
            _get_config_value(legacy, "AGENT_REVIEW_ENABLED"),
            True,
        ),
        agent_review_retry_enabled=_get_bool(
            _get_config_value(legacy, "AGENT_REVIEW_RETRY_ENABLED"),
            False,
        ),
        agent_review_min_score=min(
            100,
            _get_int(
                _get_config_value(legacy, "AGENT_REVIEW_MIN_SCORE"),
                50,
                minimum=0,
            ),
        ),
        agent_review_require_pass=_get_bool(
            _get_config_value(legacy, "AGENT_REVIEW_REQUIRE_PASS"),
            False,
        ),
        agent_query_rewrite_enabled=_get_bool(
            _get_config_value(legacy, "AGENT_QUERY_REWRITE_ENABLED"),
            True,
        ),
        agent_query_rewrite_min_chunks=_get_int(
            _get_config_value(legacy, "AGENT_QUERY_REWRITE_MIN_CHUNKS"),
            1,
            minimum=1,
        ),
        agent_budget_max_prompt_tokens=_get_int(
            _get_config_value(legacy, "AGENT_BUDGET_MAX_PROMPT_TOKENS"),
            0,
            minimum=0,
        ),
        agent_budget_max_estimated_cost=_get_float(
            _get_config_value(legacy, "AGENT_BUDGET_MAX_ESTIMATED_COST"),
            0.0,
            minimum=0.0,
        ),
        agent_workflow_backend=(
            _get_config_value(legacy, "AGENT_WORKFLOW_BACKEND", default="langgraph")
            or "langgraph"
        ).strip().lower(),
        generation_job_queue_backend=(
            _get_config_value(
                legacy,
                "GENERATION_JOB_QUEUE_BACKEND",
                default="in_memory",
            )
            or "in_memory"
        ).strip().lower(),
        generation_job_max_workers=_get_int(
            _get_config_value(legacy, "GENERATION_JOB_MAX_WORKERS"),
            2,
            minimum=1,
        ),
        generation_job_max_queue_size=_get_int(
            _get_config_value(legacy, "GENERATION_JOB_MAX_QUEUE_SIZE"),
            100,
            minimum=1,
        ),
        generation_job_retention_seconds=_get_int(
            _get_config_value(legacy, "GENERATION_JOB_RETENTION_SECONDS"),
            3600,
            minimum=60,
        ),
        redis_url=_get_config_value(
            legacy,
            "REDIS_URL",
            default="redis://127.0.0.1:6379/0",
        )
        or "redis://127.0.0.1:6379/0",
        rq_queue_name=_get_config_value(
            legacy,
            "RQ_QUEUE_NAME",
            default="generation",
        )
        or "generation",
        rq_job_timeout_seconds=_get_int(
            _get_config_value(legacy, "RQ_JOB_TIMEOUT_SECONDS"),
            900,
            minimum=1,
        ),
        rq_result_ttl_seconds=_get_int(
            _get_config_value(legacy, "RQ_RESULT_TTL_SECONDS"),
            3600,
            minimum=0,
        ),
        rq_failure_ttl_seconds=_get_int(
            _get_config_value(legacy, "RQ_FAILURE_TTL_SECONDS"),
            86400,
            minimum=0,
        ),
        generation_job_stale_after_seconds=_get_int(
            _get_config_value(legacy, "GENERATION_JOB_STALE_AFTER_SECONDS"),
            1800,
            minimum=0,
        ),
        test_tool_http_base_url_allowlist=_get_csv(
            _get_config_value(legacy, "TEST_TOOL_HTTP_BASE_URL_ALLOWLIST"),
            "",
        ),
        test_tool_http_allowed_headers=_get_csv(
            _get_config_value(legacy, "TEST_TOOL_HTTP_ALLOWED_HEADERS"),
            "Accept,Content-Type,X-Request-ID",
        ),
        test_tool_artifact_dir=_get_config_value(
            legacy,
            "TEST_TOOL_ARTIFACT_DIR",
            default="data/test-artifacts",
        )
        or "data/test-artifacts",
        test_tool_artifact_max_bytes=_get_int(
            _get_config_value(legacy, "TEST_TOOL_ARTIFACT_MAX_BYTES"),
            200000,
            minimum=1024,
        ),
        test_tool_artifact_retention_seconds=_get_int(
            _get_config_value(legacy, "TEST_TOOL_ARTIFACT_RETENTION_SECONDS"),
            604800,
            minimum=0,
        ),
        test_tool_pytest_enabled=_get_bool(
            _get_config_value(legacy, "TEST_TOOL_PYTEST_ENABLED"),
            False,
        ),
        test_tool_pytest_allowed_paths=_get_csv(
            _get_config_value(legacy, "TEST_TOOL_PYTEST_ALLOWED_PATHS"),
            "tests",
        ),
        test_tool_pytest_timeout_seconds=_get_int(
            _get_config_value(legacy, "TEST_TOOL_PYTEST_TIMEOUT_SECONDS"),
            60,
            minimum=1,
        ),
        test_tool_pytest_env_allowlist=_get_csv(
            _get_config_value(legacy, "TEST_TOOL_PYTEST_ENV_ALLOWLIST"),
            "PATH,PYTHONPATH",
        ),
        rate_limit_enabled=_get_bool(
            _get_config_value(legacy, "RATE_LIMIT_ENABLED"),
            True,
        ),
        rate_limit_requests=_get_int(
            _get_config_value(legacy, "RATE_LIMIT_REQUESTS"),
            60,
            minimum=1,
        ),
        rate_limit_window_seconds=_get_int(
            _get_config_value(legacy, "RATE_LIMIT_WINDOW_SECONDS"),
            60,
            minimum=1,
        ),
        request_log_enabled=_get_bool(
            _get_config_value(legacy, "REQUEST_LOG_ENABLED"),
            True,
        ),
        request_log_format=(
            _get_config_value(legacy, "REQUEST_LOG_FORMAT", default="text") or "text"
        ).strip().lower(),
        database_backend=(
            _get_config_value(legacy, "DATABASE_BACKEND", default="sqlite") or "sqlite"
        ).strip().lower(),
        database_url=_get_config_value(legacy, "DATABASE_URL"),
        mysql_connect_timeout_seconds=_get_int(
            _get_config_value(legacy, "MYSQL_CONNECT_TIMEOUT_SECONDS"),
            10,
            minimum=1,
        ),
        mysql_read_timeout_seconds=_get_int(
            _get_config_value(legacy, "MYSQL_READ_TIMEOUT_SECONDS"),
            30,
            minimum=1,
        ),
        mysql_write_timeout_seconds=_get_int(
            _get_config_value(legacy, "MYSQL_WRITE_TIMEOUT_SECONDS"),
            30,
            minimum=1,
        ),
        generation_history_enabled=_get_bool(
            _get_config_value(legacy, "GENERATION_HISTORY_ENABLED"),
            True,
        ),
        generation_history_db_path=_get_config_value(
            legacy,
            "GENERATION_HISTORY_DB_PATH",
            default="data/app.sqlite3",
        )
        or "data/app.sqlite3",
        cors_allow_origins=cors_allow_origins,
        cors_allow_credentials=cors_allow_credentials,
    )


def validate_startup_settings(settings: Settings) -> None:
    errors = validate_production_settings(settings)
    if not errors:
        return
    details = "\n".join(f"- {error}" for error in errors)
    raise RuntimeError(f"Invalid production configuration:\n{details}")


def validate_production_settings(settings: Settings) -> list[str]:
    if not settings.is_production:
        return []

    errors: list[str] = []
    api_keys = settings.accepted_api_keys
    weak_api_keys = [key for key in api_keys if _is_weak_secret(key)]
    if not api_keys:
        errors.append(
            "APP_API_KEY or APP_API_KEYS must be configured with at least one non-placeholder value of at least 16 characters."
        )
    elif weak_api_keys:
        errors.append(
            "APP_API_KEY and APP_API_KEYS entries must use non-placeholder values of at least 16 characters."
        )
    if _is_weak_secret(settings.zhipu_api_key):
        errors.append(
            "ZHIPU_API_KEY must be configured with a non-placeholder value of at least 16 characters."
        )
    if not settings.cors_allow_origins:
        errors.append("CORS_ALLOW_ORIGINS must contain at least one production origin.")
    if "*" in settings.cors_allow_origins:
        errors.append("CORS_ALLOW_ORIGINS must not include '*' in production.")
    local_origins = [
        origin
        for origin in settings.cors_allow_origins
        if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")
    ]
    if local_origins:
        errors.append("CORS_ALLOW_ORIGINS must not use localhost origins in production.")
    non_https_origins = [
        origin
        for origin in settings.cors_allow_origins
        if origin != "*" and not origin.startswith("https://")
    ]
    if non_https_origins:
        errors.append("CORS_ALLOW_ORIGINS must use https:// origins in production.")
    provider = settings.embedding_provider.strip().lower().replace("-", "_")
    if provider == "hash":
        errors.append("EMBEDDING_PROVIDER must not be 'hash' in production.")
    if provider not in {"hash", "sentence_transformers", "sentence_transformer"}:
        errors.append("EMBEDDING_PROVIDER must be 'sentence_transformers' in production.")
    if provider in {"sentence_transformers", "sentence_transformer"} and not settings.embedding_local_files_only:
        errors.append(
            "EMBEDDING_LOCAL_FILES_ONLY should be true in production; download models before deploy."
        )
    if not settings.test_tool_http_base_url_allowlist:
        errors.append(
            "TEST_TOOL_HTTP_BASE_URL_ALLOWLIST must contain at least one allowed base URL in production."
        )
    if not settings.rate_limit_enabled:
        errors.append("RATE_LIMIT_ENABLED must be true in production.")
    if not settings.request_log_enabled:
        errors.append("REQUEST_LOG_ENABLED must be true in production.")
    if settings.request_log_format not in {"text", "json"}:
        errors.append("REQUEST_LOG_FORMAT must be 'text' or 'json'.")
    if not settings.agent_review_enabled:
        errors.append("AGENT_REVIEW_ENABLED must be true in production.")
    if not 0 <= settings.agent_review_min_score <= 100:
        errors.append("AGENT_REVIEW_MIN_SCORE must be between 0 and 100.")
    if not settings.generation_history_enabled:
        errors.append("GENERATION_HISTORY_ENABLED must be true in production.")
    if settings.database_backend not in {"sqlite", "mysql"}:
        errors.append("DATABASE_BACKEND must be 'sqlite' or 'mysql'.")
    if settings.database_backend == "mysql" and not settings.database_url:
        errors.append("DATABASE_URL must be configured when DATABASE_BACKEND=mysql.")
    if settings.database_backend == "mysql" and (
        settings.mysql_connect_timeout_seconds < 1
        or settings.mysql_read_timeout_seconds < 1
        or settings.mysql_write_timeout_seconds < 1
    ):
        errors.append(
            "MYSQL_CONNECT_TIMEOUT_SECONDS, MYSQL_READ_TIMEOUT_SECONDS, and MYSQL_WRITE_TIMEOUT_SECONDS must be positive when DATABASE_BACKEND=mysql."
        )
    if (
        settings.database_backend == "sqlite"
        and settings.generation_history_db_path.strip() in {"", ":memory:"}
    ):
        errors.append("GENERATION_HISTORY_DB_PATH must point to a persistent database file.")
    if settings.generation_job_queue_backend not in {"in_memory", "rq"}:
        errors.append("GENERATION_JOB_QUEUE_BACKEND must be 'in_memory' or 'rq'.")
    if settings.agent_workflow_backend not in {"local", "langgraph"}:
        errors.append("AGENT_WORKFLOW_BACKEND must be 'local' or 'langgraph'.")
    if settings.generation_job_queue_backend == "rq" and not settings.redis_url:
        errors.append("REDIS_URL must be configured when GENERATION_JOB_QUEUE_BACKEND=rq.")
    return errors


def _is_weak_secret(value: str | None) -> bool:
    if not value or len(value.strip()) < 16:
        return True
    lowered = value.strip().lower()
    placeholders = (
        "replace-with",
        "your-",
        "changeme",
        "dummy",
        "example",
        "test-service-key",
        "test-zhipu-key",
    )
    return any(token in lowered for token in placeholders)
