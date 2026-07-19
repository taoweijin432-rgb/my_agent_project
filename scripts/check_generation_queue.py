import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.core.config import Settings, get_settings
from app.services.stores import GenerationJobRepository, create_generation_job_store


ACTIVE_STATUSES = ("queued", "running")
RQ_ACTIVE_REGISTRIES = ("queued", "started", "deferred", "scheduled")
GENERATION_RQ_FUNCTION = "app.workers.generation_rq.run_generation_job"


@dataclass(frozen=True)
class QueueHealth:
    ok: bool
    warnings: list[str]
    errors: list[str]


def build_database_snapshot(
    settings: Settings,
    store: GenerationJobRepository | None = None,
) -> dict[str, Any]:
    job_store = store or create_generation_job_store(settings)
    counts = job_store.count_jobs_by_status()
    active_count = sum(counts.get(status, 0) for status in ACTIVE_STATUSES)
    return {
        "backend": settings.database_backend,
        "jobs_by_status": counts,
        "active_count": active_count,
    }


def build_rq_snapshot(settings: Settings) -> dict[str, Any]:
    try:
        from redis import Redis
        from rq import Queue, Worker
        from rq.registry import (
            DeferredJobRegistry,
            FailedJobRegistry,
            FinishedJobRegistry,
            ScheduledJobRegistry,
            StartedJobRegistry,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("Redis/RQ dependencies are not installed.") from exc

    connection = Redis.from_url(settings.redis_url)
    connection.ping()
    queue = Queue(settings.rq_queue_name, connection=connection)
    registries = {
        "started": StartedJobRegistry(queue.name, connection=connection),
        "finished": FinishedJobRegistry(queue.name, connection=connection),
        "failed": FailedJobRegistry(queue.name, connection=connection),
        "deferred": DeferredJobRegistry(queue.name, connection=connection),
        "scheduled": ScheduledJobRegistry(queue.name, connection=connection),
    }
    workers = [
        _worker_snapshot(worker)
        for worker in Worker.all(connection=connection)
        if _worker_is_relevant(worker, queue.name)
    ]
    fetch_job = queue.fetch_job
    function_counts = {
        "queued": _count_jobs_for_function(
            queue.get_job_ids(),
            fetch_job,
            GENERATION_RQ_FUNCTION,
        ),
        **{
            name: _count_jobs_for_function(
                registry.get_job_ids(),
                fetch_job,
                GENERATION_RQ_FUNCTION,
            )
            for name, registry in registries.items()
        },
    }
    total_counts = {
        "queued": _count_value(queue),
        **{
            name: _count_value(registry)
            for name, registry in registries.items()
        },
    }
    return {
        "backend": "rq",
        "active": True,
        "name": queue.name,
        "function": GENERATION_RQ_FUNCTION,
        **function_counts,
        "total": total_counts,
        "workers": workers,
        "worker_count": len(workers),
    }


def build_snapshot(
    settings: Settings | None = None,
    store: GenerationJobRepository | None = None,
) -> dict[str, Any]:
    effective_settings = settings or get_settings()
    database = build_database_snapshot(effective_settings, store)
    snapshot: dict[str, Any] = {
        "database": database,
        "queue": {
            "backend": effective_settings.generation_job_queue_backend,
            "active": False,
        },
    }
    if effective_settings.generation_job_queue_backend == "rq":
        try:
            snapshot["queue"] = build_rq_snapshot(effective_settings)
        except Exception as exc:
            snapshot["queue"] = {
                "backend": "rq",
                "active": False,
                "name": effective_settings.rq_queue_name,
                "function": GENERATION_RQ_FUNCTION,
                "error": f"{type(exc).__name__}: {exc}",
            }
    snapshot["health"] = evaluate_health(database, snapshot["queue"]).__dict__
    return snapshot


def evaluate_health(database: dict[str, Any], queue: dict[str, Any]) -> QueueHealth:
    warnings: list[str] = []
    errors: list[str] = []
    counts = database.get("jobs_by_status") or {}
    database_active = int(database.get("active_count") or 0)

    if queue.get("backend") == "rq" and queue.get("error"):
        errors.append(f"Redis/RQ inspection failed: {queue['error']}")
        return QueueHealth(ok=False, warnings=warnings, errors=errors)

    if queue.get("backend") != "rq" or not queue.get("active", True):
        if database_active:
            warnings.append(
                "Database has active generation jobs while Redis/RQ backend is not active."
            )
        return QueueHealth(ok=not errors, warnings=warnings, errors=errors)

    rq_active = sum(int(queue.get(name) or 0) for name in RQ_ACTIVE_REGISTRIES)
    failed_count = int(queue.get("failed") or 0)
    if failed_count:
        warnings.append(f"RQ failed registry contains {failed_count} job(s).")

    if database_active > rq_active:
        errors.append(
            "Database active jobs exceed Redis/RQ active jobs "
            f"(database={database_active}, rq={rq_active})."
        )
    if database_active == 0 and rq_active > 0:
        errors.append(
            "Redis/RQ has active jobs but the database has no queued/running jobs "
            f"(rq={rq_active})."
        )
    if counts.get("running", 0) and int(queue.get("started") or 0) == 0:
        warnings.append(
            "Database has running jobs but RQ started registry is empty; "
            "check worker heartbeat and stale job recovery."
        )
    if rq_active and int(queue.get("worker_count") or 0) == 0:
        warnings.append("Redis/RQ has active jobs but no live worker was found.")

    return QueueHealth(ok=not errors, warnings=warnings, errors=errors)


def print_text(snapshot: dict[str, Any]) -> None:
    database = snapshot["database"]
    queue = snapshot["queue"]
    health = snapshot["health"]

    print("Generation queue snapshot")
    print("Database")
    print(f"  backend: {database['backend']}")
    print(f"  active_jobs: {database['active_count']}")
    print("  jobs_by_status:")
    for status, count in sorted(database["jobs_by_status"].items()):
        print(f"    {status}: {count}")

    print("Queue")
    print(f"  backend: {queue['backend']}")
    if queue.get("backend") == "rq":
        print(f"  name: {queue['name']}")
        print(f"  function: {queue.get('function') or '-'}")
        if queue.get("error"):
            print(f"  error: {queue['error']}")
        else:
            for field in (
                "queued",
                "started",
                "finished",
                "failed",
                "deferred",
                "scheduled",
                "worker_count",
            ):
                print(f"  {field}: {queue[field]}")
            if queue.get("total"):
                print("  total_queue_counts:")
                for field, count in sorted(queue["total"].items()):
                    print(f"    {field}: {count}")
            if queue["workers"]:
                print("  workers:")
                for worker in queue["workers"]:
                    print(
                        "    "
                        f"{worker['name']} state={worker['state']} "
                        f"queues={','.join(worker['queues']) or '-'} "
                        f"last_heartbeat={worker['last_heartbeat'] or '-'}"
                    )
    else:
        print("  active: false")

    print("Health")
    print(f"  ok: {str(health['ok']).lower()}")
    for warning in health["warnings"]:
        print(f"  warning: {warning}")
    for error in health["errors"]:
        print(f"  error: {error}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect generation queue health.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--fail-on-mismatch",
        action="store_true",
        help="Exit with status 1 when database and Redis/RQ active job counts disagree.",
    )
    args = parser.parse_args(argv)

    try:
        snapshot = build_snapshot()
    except Exception as exc:
        error_snapshot = {
            "health": {
                "ok": False,
                "warnings": [],
                "errors": [f"{type(exc).__name__}: {exc}"],
            }
        }
        if args.json:
            print(
                json.dumps(
                    error_snapshot,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print("Generation queue check failed")
            print(f"  error: {type(exc).__name__}: {exc}")
        return 2

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(snapshot)

    if snapshot["queue"].get("error"):
        return 2
    if args.fail_on_mismatch and snapshot["health"]["errors"]:
        return 1
    return 0


def _count_value(value: object) -> int:
    count = getattr(value, "count", None)
    if count is not None:
        return int(count() if callable(count) else count)
    get_job_ids = getattr(value, "get_job_ids", None)
    if get_job_ids is not None:
        return len(get_job_ids())
    return len(value)  # type: ignore[arg-type]


def _count_jobs_for_function(
    job_ids: list[str],
    fetch_job: Callable[[str], Any],
    function_name: str,
) -> int:
    count = 0
    for job_id in job_ids:
        job = fetch_job(str(job_id))
        if job is not None and getattr(job, "func_name", None) == function_name:
            count += 1
    return count


def _worker_snapshot(worker: object) -> dict[str, Any]:
    state = getattr(worker, "state", None)
    if state is None and hasattr(worker, "get_state"):
        state = worker.get_state()
    return {
        "name": str(getattr(worker, "name", "")),
        "state": str(state or "unknown"),
        "queues": _worker_queue_names(worker),
        "current_job_id": getattr(worker, "current_job_id", None),
        "last_heartbeat": _serialize_datetime(
            getattr(worker, "last_heartbeat", None)
        ),
    }


def _worker_is_relevant(worker: object, queue_name: str) -> bool:
    queue_names = _worker_queue_names(worker)
    return not queue_names or queue_name in queue_names


def _worker_queue_names(worker: object) -> list[str]:
    if hasattr(worker, "queue_names"):
        return [str(name) for name in worker.queue_names()]
    queues = getattr(worker, "queues", None) or []
    return [str(getattr(queue, "name", queue)) for queue in queues]


def _serialize_datetime(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
