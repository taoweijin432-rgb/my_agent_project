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
