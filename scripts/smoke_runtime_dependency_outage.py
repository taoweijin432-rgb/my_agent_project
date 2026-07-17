import argparse
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = (
    "mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4"
)
DEFAULT_REDIS_URL = "redis://redis:6379/0"
DEFAULT_QUEUE_NAME = "generation-compose-smoke"


Runner = Callable[..., subprocess.CompletedProcess[str]]


class RuntimeDependencyOutageSmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeDependencyOutageConfig:
    project_root: Path = PROJECT_ROOT
    profile: str = "mysql"
    api_service: str = "api"
    redis_service: str = "redis"
    mysql_service: str = "mysql"
    database_url: str = DEFAULT_DATABASE_URL
    redis_url: str = DEFAULT_REDIS_URL
    queue_name: str = DEFAULT_QUEUE_NAME
    app_data_mount: str = "smoke-data"
    model_cache_mount: str = "smoke-model-cache"
    include_redis: bool = True
    include_mysql: bool = True
    start_services: bool = True
    recover_retries: int = 12
    retry_interval_seconds: float = 2.0
    command_timeout_seconds: int = 120


@dataclass(frozen=True)
class StepResult:
    name: str
    expected: str
    returncode: int
    ok: bool
    stdout_tail: str
    stderr_tail: str


def run_outage_smoke(
    config: RuntimeDependencyOutageConfig,
    *,
    runner: Runner = subprocess.run,
) -> dict[str, object]:
    if not config.include_redis and not config.include_mysql:
        raise RuntimeDependencyOutageSmokeError(
            "At least one dependency outage probe must be enabled."
        )
    if config.recover_retries < 1:
        raise RuntimeDependencyOutageSmokeError("recover_retries must be >= 1.")
    if config.retry_interval_seconds < 0:
        raise RuntimeDependencyOutageSmokeError(
            "retry_interval_seconds must be >= 0."
        )

    steps: list[StepResult] = []
    if config.start_services:
        steps.append(
            _run_compose(
                config,
                ["up", "-d", config.redis_service, config.mysql_service],
                name="start-services",
                expected="success",
                runner=runner,
            )
        )

    steps.append(
        _run_queue_check_with_retries(
            config,
            name="baseline",
            expected_success=True,
            runner=runner,
        )
    )

    if config.include_redis:
        steps.extend(_run_single_outage_probe(config, "redis", runner=runner))
    if config.include_mysql:
        steps.extend(_run_single_outage_probe(config, "mysql", runner=runner))

    return {
        "ok": all(step.ok for step in steps),
        "profile": config.profile,
        "queue_name": config.queue_name,
        "database_url_host": _database_url_host(config.database_url),
        "probed": {
            "redis": config.include_redis,
            "mysql": config.include_mysql,
        },
        "steps": [asdict(step) for step in steps],
    }


def _run_single_outage_probe(
    config: RuntimeDependencyOutageConfig,
    component: str,
    *,
    runner: Runner,
) -> list[StepResult]:
    service = _service_for_component(config, component)
    expected_fragments = _expected_error_fragments(component)
    steps: list[StepResult] = []
    steps.append(
        _run_compose(
            config,
            ["stop", service],
            name=f"{component}-stop",
            expected="success",
            runner=runner,
        )
    )
    try:
        steps.append(
            _run_queue_check(
                config,
                name=f"{component}-outage",
                expected_success=False,
                expected_fragments=expected_fragments,
                runner=runner,
            )
        )
    finally:
        steps.append(
            _run_compose(
                config,
                ["up", "-d", service],
                name=f"{component}-restart",
                expected="success",
                runner=runner,
            )
        )
    steps.append(
        _run_queue_check_with_retries(
            config,
            name=f"{component}-recovered",
            expected_success=True,
            runner=runner,
        )
    )
    return steps


def _run_queue_check_with_retries(
    config: RuntimeDependencyOutageConfig,
    *,
    name: str,
    expected_success: bool,
    runner: Runner,
) -> StepResult:
    last_error: RuntimeDependencyOutageSmokeError | None = None
    attempts = config.recover_retries if expected_success else 1
    for attempt in range(attempts):
        try:
            return _run_queue_check(
                config,
                name=name,
                expected_success=expected_success,
                expected_fragments=(),
                runner=runner,
            )
        except RuntimeDependencyOutageSmokeError as exc:
            last_error = exc
            if attempt + 1 == attempts:
                break
            time.sleep(config.retry_interval_seconds)
    raise last_error or RuntimeDependencyOutageSmokeError(
        f"{name} did not produce a result."
    )


def _run_queue_check(
    config: RuntimeDependencyOutageConfig,
    *,
    name: str,
    expected_success: bool,
    expected_fragments: Sequence[str],
    runner: Runner,
) -> StepResult:
    result = _run_command(
        _queue_check_command(config),
        config,
        runner=runner,
    )
    output = f"{result.stdout}\n{result.stderr}"
    if expected_success:
        ok = result.returncode == 0
        expected = "success"
    else:
        ok = result.returncode != 0 and _contains_any(output, expected_fragments)
        expected = "failure"
    step = StepResult(
        name=name,
        expected=expected,
        returncode=result.returncode,
        ok=ok,
        stdout_tail=_tail(result.stdout),
        stderr_tail=_tail(result.stderr),
    )
    if not step.ok:
        raise RuntimeDependencyOutageSmokeError(
            f"{name} expected {expected}, got exit={result.returncode}: "
            f"{_tail(output)}"
        )
    return step


def _run_compose(
    config: RuntimeDependencyOutageConfig,
    args: list[str],
    *,
    name: str,
    expected: str,
    runner: Runner,
) -> StepResult:
    result = _run_command(_compose_command(config, args), config, runner=runner)
    ok = result.returncode == 0
    step = StepResult(
        name=name,
        expected=expected,
        returncode=result.returncode,
        ok=ok,
        stdout_tail=_tail(result.stdout),
        stderr_tail=_tail(result.stderr),
    )
    if not step.ok:
        raise RuntimeDependencyOutageSmokeError(
            f"{name} expected {expected}, got exit={result.returncode}: "
            f"{_tail(result.stdout + result.stderr)}"
        )
    return step


def _run_command(
    command: list[str],
    config: RuntimeDependencyOutageConfig,
    *,
    runner: Runner,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        cwd=config.project_root,
        env=_compose_environment(config),
        check=False,
        capture_output=True,
        text=True,
        timeout=config.command_timeout_seconds,
    )


def _queue_check_command(config: RuntimeDependencyOutageConfig) -> list[str]:
    return _compose_command(
        config,
        [
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "-e",
            "DATABASE_BACKEND=mysql",
            "-e",
            f"DATABASE_URL={config.database_url}",
            "-e",
            "GENERATION_JOB_QUEUE_BACKEND=rq",
            "-e",
            f"REDIS_URL={config.redis_url}",
            "-e",
            f"RQ_QUEUE_NAME={config.queue_name}",
            config.api_service,
            "python",
            "scripts/check_generation_queue.py",
            "--json",
            "--fail-on-mismatch",
        ],
    )


def _compose_command(
    config: RuntimeDependencyOutageConfig,
    args: list[str],
) -> list[str]:
    command = ["docker", "compose"]
    if config.profile:
        command.extend(["--profile", config.profile])
    command.extend(args)
    return command


def _compose_environment(config: RuntimeDependencyOutageConfig) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_DATA_MOUNT": config.app_data_mount,
            "MODEL_CACHE_MOUNT": config.model_cache_mount,
        }
    )
    return env


def _service_for_component(
    config: RuntimeDependencyOutageConfig,
    component: str,
) -> str:
    if component == "redis":
        return config.redis_service
    if component == "mysql":
        return config.mysql_service
    raise RuntimeDependencyOutageSmokeError(f"Unsupported component: {component}")


def _expected_error_fragments(component: str) -> tuple[str, ...]:
    if component == "redis":
        return (
            "Redis/RQ inspection failed",
            "ConnectionError",
            "redis",
        )
    if component == "mysql":
        return (
            "OperationalError",
            "Connection refused",
            "Can't connect",
            "mysql",
        )
    return ()


def _contains_any(output: str, fragments: Sequence[str]) -> bool:
    lowered = output.lower()
    return any(fragment.lower() in lowered for fragment in fragments)


def _tail(value: str, *, limit: int = 600) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[-limit:]


def _database_url_host(database_url: str) -> str:
    without_scheme = database_url.split("://", 1)[-1]
    host_part = without_scheme.rsplit("@", 1)[-1]
    return host_part.split("/", 1)[0]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = RuntimeDependencyOutageConfig(
        project_root=Path(args.project_root).resolve(),
        profile=args.profile,
        api_service=args.api_service,
        redis_service=args.redis_service,
        mysql_service=args.mysql_service,
        database_url=args.database_url,
        redis_url=args.redis_url,
        queue_name=args.queue_name,
        app_data_mount=args.app_data_mount,
        model_cache_mount=args.model_cache_mount,
        include_redis=args.component in {"all", "redis"},
        include_mysql=args.component in {"all", "mysql"},
        start_services=not args.no_start_services,
        recover_retries=args.recover_retries,
        retry_interval_seconds=args.retry_interval_seconds,
        command_timeout_seconds=args.command_timeout_seconds,
    )
    try:
        result = run_outage_smoke(config)
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL runtime-dependency-outage-smoke: {payload['error']}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "PASS runtime-dependency-outage-smoke: "
            f"redis={config.include_redis} mysql={config.include_mysql} "
            f"steps={len(result['steps'])}"
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stop Redis/MySQL briefly, verify queue checks fail clearly, then "
            "restore services and verify recovery."
        ),
    )
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Compose project root. Defaults to the repository root.",
    )
    parser.add_argument("--profile", default="mysql")
    parser.add_argument("--api-service", default="api")
    parser.add_argument("--redis-service", default="redis")
    parser.add_argument("--mysql-service", default="mysql")
    parser.add_argument("--database-url", default=DEFAULT_DATABASE_URL)
    parser.add_argument("--redis-url", default=DEFAULT_REDIS_URL)
    parser.add_argument("--queue-name", default=DEFAULT_QUEUE_NAME)
    parser.add_argument("--app-data-mount", default="smoke-data")
    parser.add_argument("--model-cache-mount", default="smoke-model-cache")
    parser.add_argument(
        "--component",
        choices=("all", "redis", "mysql"),
        default="all",
        help="Dependency outage probe to run.",
    )
    parser.add_argument(
        "--no-start-services",
        action="store_true",
        help="Do not run `docker compose up -d redis mysql` before the baseline check.",
    )
    parser.add_argument("--recover-retries", type=int, default=12)
    parser.add_argument("--retry-interval-seconds", type=float, default=2.0)
    parser.add_argument("--command-timeout-seconds", type=int, default=120)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
