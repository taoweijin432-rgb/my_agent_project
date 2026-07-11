import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from app.core.config import PROJECT_ROOT, Settings, validate_production_settings
from app.services.stores import GenerationJobRepository, create_generation_job_store


CheckStatus = Literal["ok", "warn", "error"]
PathChecker = Callable[[str, Path], str | None]
RedisPing = Callable[[str], None]


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: CheckStatus
    detail: str
    data: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
        }
        if self.data:
            payload["data"] = self.data
        return payload


def build_readiness_report(
    settings: Settings,
    *,
    job_store: GenerationJobRepository | None = None,
    path_checker: PathChecker | None = None,
    redis_ping: RedisPing | None = None,
) -> dict[str, Any]:
    checks: list[ReadinessCheck] = []
    checks.extend(_configuration_checks(settings))
    checks.extend(
        _runtime_path_checks(settings, path_checker=path_checker or _check_writable_path)
    )
    checks.append(_database_check(settings, job_store=job_store))
    checks.append(_queue_check(settings, redis_ping=redis_ping or _ping_redis))
    checks.append(_llm_configuration_check(settings))

    ready = all(check.status != "error" for check in checks)
    return {
        "ready": ready,
        "status": "ready" if ready else "not_ready",
        "service": settings.app_name,
        "environment": settings.app_env,
        "checks": [check.as_dict() for check in checks],
    }


def readiness_status_code(report: dict[str, Any]) -> int:
    return 200 if report.get("ready") else 503


def format_readiness_text(report: dict[str, Any]) -> str:
    lines = [
        "Readiness check",
        f"  service: {report['service']}",
        f"  environment: {report['environment']}",
        f"  status: {report['status']}",
        "Checks",
    ]
    for check in report["checks"]:
        lines.append(f"  {check['status']} {check['name']}: {check['detail']}")
    return "\n".join(lines)


def _configuration_checks(settings: Settings) -> list[ReadinessCheck]:
    errors = validate_production_settings(settings)
    if errors:
        return [
            ReadinessCheck(
                name="configuration",
                status="error",
                detail="production configuration is invalid",
                data={"errors": errors},
            )
        ]
    return [
        ReadinessCheck(
            name="configuration",
            status="ok",
            detail="startup configuration is valid",
        )
    ]


def _runtime_path_checks(
    settings: Settings,
    *,
    path_checker: PathChecker,
) -> list[ReadinessCheck]:
    checks: list[ReadinessCheck] = []
    for label, path in _runtime_paths(settings):
        error = path_checker(label, path)
        checks.append(
            ReadinessCheck(
                name=f"runtime_path:{label}",
                status="error" if error else "ok",
                detail=error or f"{path} is writable",
            )
        )
    return checks


def _runtime_paths(settings: Settings) -> list[tuple[str, Path]]:
    paths = [
        ("CHROMA_PATH", _resolve_runtime_path(settings.chroma_path)),
        ("EMBEDDING_CACHE_DIR", _resolve_runtime_path(settings.embedding_cache_dir)),
    ]
    if settings.database_backend == "sqlite":
        history_path = _resolve_runtime_path(settings.generation_history_db_path)
        paths.append(("GENERATION_HISTORY_DB_PATH parent", history_path.parent))
    return paths


def _database_check(
    settings: Settings,
    *,
    job_store: GenerationJobRepository | None,
) -> ReadinessCheck:
    try:
        store = job_store or create_generation_job_store(settings)
        counts = store.count_jobs_by_status()
    except Exception as exc:
        return ReadinessCheck(
            name="database",
            status="error",
            detail=f"{type(exc).__name__}: {exc}",
            data={"backend": settings.database_backend},
        )
    return ReadinessCheck(
        name="database",
        status="ok",
        detail=f"{settings.database_backend} generation job store is reachable",
        data={"backend": settings.database_backend, "jobs_by_status": counts},
    )


def _queue_check(settings: Settings, *, redis_ping: RedisPing) -> ReadinessCheck:
    backend = settings.generation_job_queue_backend
    if backend == "in_memory":
        return ReadinessCheck(
            name="queue",
            status="ok",
            detail="in_memory queue is available in this process",
            data={"backend": backend},
        )
    if backend != "rq":
        return ReadinessCheck(
            name="queue",
            status="error",
            detail="GENERATION_JOB_QUEUE_BACKEND must be 'in_memory' or 'rq'",
            data={"backend": backend},
        )

    try:
        redis_ping(settings.redis_url)
    except Exception as exc:
        return ReadinessCheck(
            name="queue",
            status="error",
            detail=f"Redis/RQ backend is unreachable: {type(exc).__name__}: {exc}",
            data={"backend": backend, "queue": settings.rq_queue_name},
        )
    return ReadinessCheck(
        name="queue",
        status="ok",
        detail="Redis/RQ backend is reachable",
        data={"backend": backend, "queue": settings.rq_queue_name},
    )


def _llm_configuration_check(settings: Settings) -> ReadinessCheck:
    if settings.zhipu_api_key:
        return ReadinessCheck(
            name="llm_configuration",
            status="ok",
            detail="ZHIPU_API_KEY is configured",
        )
    return ReadinessCheck(
        name="llm_configuration",
        status="warn",
        detail="ZHIPU_API_KEY is not configured; generation calls will fail",
    )


def _ping_redis(redis_url: str) -> None:
    try:
        from redis import Redis
    except ModuleNotFoundError as exc:
        raise RuntimeError("Redis dependency is not installed.") from exc

    Redis.from_url(redis_url).ping()


def _check_writable_path(label: str, path: Path) -> str | None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"{label}={path} cannot be created: {exc}"

    if not path.is_dir():
        return f"{label}={path} is not a directory."

    try:
        with tempfile.NamedTemporaryFile(
            prefix=".readiness-write-test-",
            dir=path,
            delete=True,
        ) as temp_file:
            temp_file.write(b"ok")
            temp_file.flush()
    except OSError as exc:
        return f"{label}={path} is not writable: {exc}"
    return None


def _resolve_runtime_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path
