import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings
from app.models.test_case import GenerateRequest, GenerationJobError
from app.services.stores import GenerationJobRepository, create_generation_job_store


class RecoverySmokeError(RuntimeError):
    pass


def run_recovery_smoke(
    settings: Settings,
    *,
    stale_after_seconds: int | None = None,
    backdate_seconds: int = 120,
    cleanup: bool = True,
    store: GenerationJobRepository | None = None,
) -> dict[str, Any]:
    threshold = stale_after_seconds or settings.generation_job_stale_after_seconds
    if threshold <= 0:
        raise RecoverySmokeError("stale_after_seconds must be greater than zero.")
    if backdate_seconds <= threshold:
        raise RecoverySmokeError(
            "backdate_seconds must be greater than stale_after_seconds."
        )

    job_store = store or create_generation_job_store(settings)
    stale_job = job_store.create_job(
        _request("stale"),
        queue_backend=settings.generation_job_queue_backend,
        queue_job_id="recovery-smoke-stale",
    )
    fresh_job = job_store.create_job(
        _request("fresh"),
        queue_backend=settings.generation_job_queue_backend,
        queue_job_id="recovery-smoke-fresh",
    )
    job_store.mark_running(stale_job.id, worker_id="recovery-smoke")
    job_store.mark_running(fresh_job.id, worker_id="recovery-smoke")
    _backdate_started_job(
        job_store,
        backend=settings.database_backend,
        job_id=stale_job.id,
        backdate_seconds=backdate_seconds,
    )

    recovered_ids = job_store.fail_stale_running_jobs(stale_after_seconds=threshold)
    stale_detail = job_store.get_job(stale_job.id)
    fresh_detail = job_store.get_job(fresh_job.id)

    if stale_detail is None or fresh_detail is None:
        raise RecoverySmokeError("smoke jobs were not readable after recovery.")
    if stale_job.id not in recovered_ids:
        raise RecoverySmokeError("stale running job was not recovered.")
    if fresh_job.id in recovered_ids:
        raise RecoverySmokeError("fresh running job was incorrectly recovered.")
    if stale_detail.status != "failed":
        raise RecoverySmokeError(f"stale job status is {stale_detail.status!r}.")
    if stale_detail.error is None or stale_detail.error.code != "generation_job_stale":
        raise RecoverySmokeError("stale job error code was not generation_job_stale.")
    if fresh_detail.status != "running":
        raise RecoverySmokeError(f"fresh job status is {fresh_detail.status!r}.")

    cleanup_status = "skipped"
    if cleanup:
        job_store.mark_failed(
            fresh_job.id,
            error=GenerationJobError(
                code="recovery_smoke_cleanup",
                message="Recovery smoke cleaned up its fresh running control job.",
                status_code=500,
            ),
        )
        cleanup_status = "fresh_job_marked_failed"

    counts_after_cleanup = job_store.count_jobs_by_status()
    return {
        "ok": True,
        "backend": settings.database_backend,
        "queue_backend": settings.generation_job_queue_backend,
        "stale_after_seconds": threshold,
        "backdate_seconds": backdate_seconds,
        "stale_job_id": stale_job.id,
        "fresh_job_id": fresh_job.id,
        "recovered_job_ids": recovered_ids,
        "stale_status": stale_detail.status,
        "fresh_status_before_cleanup": fresh_detail.status,
        "cleanup": cleanup_status,
        "jobs_by_status_after_cleanup": counts_after_cleanup,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.backend == "sqlite" and args.db_path is None:
            with tempfile.TemporaryDirectory(
                prefix="generation-recovery-smoke-"
            ) as tmp:
                settings = _build_settings(
                    backend=args.backend,
                    db_path=str(Path(tmp) / "jobs.sqlite3"),
                    database_url=args.database_url,
                    queue_backend=args.queue_backend,
                    stale_after_seconds=args.stale_after_seconds,
                )
                result = run_recovery_smoke(
                    settings,
                    stale_after_seconds=args.stale_after_seconds,
                    backdate_seconds=args.backdate_seconds,
                    cleanup=not args.no_cleanup,
                )
        else:
            settings = _build_settings(
                backend=args.backend,
                db_path=args.db_path,
                database_url=args.database_url,
                queue_backend=args.queue_backend,
                stale_after_seconds=args.stale_after_seconds,
            )
            result = run_recovery_smoke(
                settings,
                stale_after_seconds=args.stale_after_seconds,
                backdate_seconds=args.backdate_seconds,
                cleanup=not args.no_cleanup,
            )
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL generation-recovery-smoke: {payload['error']}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "PASS generation-recovery-smoke: "
            f"backend={result['backend']} recovered={len(result['recovered_job_ids'])} "
            f"cleanup={result['cleanup']}"
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify stale generation job recovery without TestClient, Redis, or LLM calls."
        ),
    )
    parser.add_argument("--backend", choices=("sqlite", "mysql"), default="sqlite")
    parser.add_argument(
        "--db-path",
        help="SQLite database path. Defaults to an isolated temporary file.",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="MySQL DATABASE_URL. Defaults to the DATABASE_URL environment variable.",
    )
    parser.add_argument(
        "--queue-backend",
        default="rq",
        help="Stored queue backend label for smoke jobs. Defaults to rq.",
    )
    parser.add_argument("--stale-after-seconds", type=int, default=60)
    parser.add_argument("--backdate-seconds", type=int, default=120)
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Leave the fresh control job running after validation.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def _build_settings(
    *,
    backend: str,
    db_path: str | None,
    database_url: str | None,
    queue_backend: str,
    stale_after_seconds: int,
) -> Settings:
    if backend == "mysql" and not database_url:
        raise RecoverySmokeError(
            "DATABASE_URL is required for --backend mysql. "
            "Pass --database-url or set DATABASE_URL."
        )
    return Settings(
        database_backend=backend,
        database_url=database_url,
        generation_history_db_path=db_path or "data/recovery-smoke.sqlite3",
        generation_job_queue_backend=queue_backend,
        generation_job_stale_after_seconds=stale_after_seconds,
        generation_job_retention_seconds=86400,
    )


def _request(label: str) -> GenerateRequest:
    return GenerateRequest(
        description=f"Recovery smoke {label} login generation job",
        max_cases=3,
    )


def _backdate_started_job(
    store: GenerationJobRepository,
    *,
    backend: str,
    job_id: str,
    backdate_seconds: int,
) -> None:
    started_epoch = time.time() - backdate_seconds
    updated_at = datetime.fromtimestamp(started_epoch, timezone.utc).isoformat()
    connect = getattr(store, "_connect", None)
    if connect is None:
        raise RecoverySmokeError("job store does not expose a database connection.")

    if backend == "sqlite":
        with connect() as connection:
            connection.execute(
                """
                UPDATE generation_jobs
                SET started_epoch = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (started_epoch, updated_at, job_id),
            )
            connection.commit()
        return

    if backend == "mysql":
        with connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE generation_jobs
                    SET started_epoch = %s,
                        updated_at = %s
                    WHERE id = %s
                    """,
                    (started_epoch, updated_at, job_id),
                )
            connection.commit()
        return

    raise RecoverySmokeError(f"unsupported backend {backend!r}.")


if __name__ == "__main__":
    raise SystemExit(main())
