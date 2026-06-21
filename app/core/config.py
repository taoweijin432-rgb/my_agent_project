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
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    request_log_enabled: bool = True
    generation_history_enabled: bool = True
    generation_history_db_path: str = "data/app.sqlite3"
    cors_allow_origins: list[str] = field(
        default_factory=lambda: _get_csv(None, DEFAULT_CORS_ALLOW_ORIGINS)
    )
    cors_allow_credentials: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in PRODUCTION_ENV_NAMES


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
    if _is_weak_secret(settings.app_api_key):
        errors.append(
            "APP_API_KEY must be configured with a non-placeholder value of at least 16 characters."
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
    if not settings.rate_limit_enabled:
        errors.append("RATE_LIMIT_ENABLED must be true in production.")
    if not settings.request_log_enabled:
        errors.append("REQUEST_LOG_ENABLED must be true in production.")
    if not settings.generation_history_enabled:
        errors.append("GENERATION_HISTORY_ENABLED must be true in production.")
    if settings.generation_history_db_path.strip() in {"", ":memory:"}:
        errors.append("GENERATION_HISTORY_DB_PATH must point to a persistent database file.")
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
