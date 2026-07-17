import argparse
import json
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
from app.models.test_plan import (
    TestPlan,
    TestPlanExecutionJobDetail,
    TestPlanExecutionJobError,
    TestPlanExecutionRequest,
    TestPlanStep,
    TestToolType,
)
from app.services.test_plan_execution import execute_test_plan_request
from app.services.test_plan_execution_jobs import InMemoryTestPlanExecutionJobQueue
from app.services.test_plan_execution_store import TestPlanExecutionJobStore


class TestPlanExecutionWorkerSmokeError(RuntimeError):
    pass


def run_worker_smoke(
    settings: Settings,
    *,
    stale_after_seconds: int | None = None,
    backdate_seconds: int = 120,
    job_count: int = 5,
    timeout_seconds: float = 10.0,
    store: TestPlanExecutionJobStore | None = None,
) -> dict[str, Any]:
    threshold = stale_after_seconds or settings.generation_job_stale_after_seconds
    if settings.generation_job_queue_backend != "in_memory":
        raise TestPlanExecutionWorkerSmokeError(
            "worker smoke uses the in_memory test plan execution queue."
        )
    if threshold <= 0:
        raise TestPlanExecutionWorkerSmokeError(
            "stale_after_seconds must be greater than zero."
        )
    if backdate_seconds <= threshold:
        raise TestPlanExecutionWorkerSmokeError(
            "backdate_seconds must be greater than stale_after_seconds."
        )
    if job_count <= 0:
        raise TestPlanExecutionWorkerSmokeError("job_count must be greater than zero.")
    if timeout_seconds <= 0:
        raise TestPlanExecutionWorkerSmokeError(
            "timeout_seconds must be greater than zero."
        )
    if settings.generation_job_max_queue_size < job_count:
        raise TestPlanExecutionWorkerSmokeError(
            "GENERATION_JOB_MAX_QUEUE_SIZE must be at least job_count."
        )

    job_store = store or TestPlanExecutionJobStore(settings)
    recovery = _run_recovery_probe(
        job_store,
        stale_after_seconds=threshold,
        backdate_seconds=backdate_seconds,
    )

    queue = InMemoryTestPlanExecutionJobQueue(
        settings,
        lambda request: execute_test_plan_request(request, settings),
        store=job_store,
    )
    submitted_ids: list[str] = []
    completed: list[TestPlanExecutionJobDetail] = []
    try:
        for index in range(1, job_count + 1):
            submitted = queue.submit(_request(f"stability-{index}"))
            submitted_ids.append(submitted.id)

        completed = [
            _wait_for_terminal_job(
                job_store,
                job_id,
                timeout_seconds=timeout_seconds,
            )
            for job_id in submitted_ids
        ]
    finally:
        queue.shutdown()

    failed = [job for job in completed if job.status != "succeeded"]
    if failed:
        raise TestPlanExecutionWorkerSmokeError(
            f"{len(failed)} worker smoke job(s) did not succeed."
        )
    missing_reports = [job.id for job in completed if job.report is None]
    if missing_reports:
        raise TestPlanExecutionWorkerSmokeError(
            f"worker smoke job(s) missing reports: {', '.join(missing_reports)}"
        )

    counts_after_smoke = job_store.count_jobs_by_status()
    return {
        "ok": True,
        "backend": "sqlite",
        "worker_backend": "in_memory",
        "configured_queue_backend": settings.generation_job_queue_backend,
        "stale_after_seconds": threshold,
        "backdate_seconds": backdate_seconds,
        "job_count": job_count,
        "submitted_job_ids": submitted_ids,
        "succeeded_job_ids": [job.id for job in completed],
        "recovery": recovery,
        "jobs_by_status_after_smoke": counts_after_smoke,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.db_path is None:
            with tempfile.TemporaryDirectory(
                prefix="test-plan-execution-worker-smoke-"
            ) as tmp:
                settings = _build_settings(
                    db_path=str(Path(tmp) / "jobs.sqlite3"),
                    job_count=args.job_count,
                    workers=args.workers,
                    stale_after_seconds=args.stale_after_seconds,
                )
                result = run_worker_smoke(
                    settings,
                    stale_after_seconds=args.stale_after_seconds,
                    backdate_seconds=args.backdate_seconds,
                    job_count=args.job_count,
                    timeout_seconds=args.timeout_seconds,
                )
        else:
            settings = _build_settings(
                db_path=args.db_path,
                job_count=args.job_count,
                workers=args.workers,
                stale_after_seconds=args.stale_after_seconds,
            )
            result = run_worker_smoke(
                settings,
                stale_after_seconds=args.stale_after_seconds,
                backdate_seconds=args.backdate_seconds,
                job_count=args.job_count,
                timeout_seconds=args.timeout_seconds,
            )
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL test-plan-execution-worker-smoke: {payload['error']}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "PASS test-plan-execution-worker-smoke: "
            f"jobs={result['job_count']} "
            f"recovered={len(result['recovery']['recovered_job_ids'])}"
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify test plan execution worker stability without TestClient, Redis, "
            "or LLM calls."
        ),
    )
    parser.add_argument(
        "--db-path",
        help="SQLite database path. Defaults to an isolated temporary file.",
    )
    parser.add_argument("--job-count", type=int, default=5)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--stale-after-seconds", type=int, default=60)
    parser.add_argument("--backdate-seconds", type=int, default=120)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def _build_settings(
    *,
    db_path: str,
    job_count: int,
    workers: int,
    stale_after_seconds: int,
) -> Settings:
    return Settings(
        database_backend="sqlite",
        generation_history_db_path=db_path,
        generation_job_queue_backend="in_memory",
        generation_job_max_workers=max(workers, 1),
        generation_job_max_queue_size=max(job_count + 1, 2),
        generation_job_stale_after_seconds=stale_after_seconds,
        generation_job_retention_seconds=86400,
    )


def _run_recovery_probe(
    store: TestPlanExecutionJobStore,
    *,
    stale_after_seconds: int,
    backdate_seconds: int,
) -> dict[str, Any]:
    stale_job = store.create_job(_request("stale"))
    fresh_job = store.create_job(_request("fresh"))
    store.mark_running(stale_job.id)
    store.mark_running(fresh_job.id)
    _backdate_started_job(
        store,
        job_id=stale_job.id,
        backdate_seconds=backdate_seconds,
    )

    recovered_ids = store.fail_stale_running_jobs(
        stale_after_seconds=stale_after_seconds
    )
    stale_detail = store.get_job(stale_job.id)
    fresh_detail = store.get_job(fresh_job.id)

    if stale_detail is None or fresh_detail is None:
        raise TestPlanExecutionWorkerSmokeError(
            "smoke jobs were not readable after recovery."
        )
    if stale_job.id not in recovered_ids:
        raise TestPlanExecutionWorkerSmokeError(
            "stale running job was not recovered."
        )
    if fresh_job.id in recovered_ids:
        raise TestPlanExecutionWorkerSmokeError(
            "fresh running job was incorrectly recovered."
        )
    if stale_detail.status != "failed":
        raise TestPlanExecutionWorkerSmokeError(
            f"stale job status is {stale_detail.status!r}."
        )
    if (
        stale_detail.error is None
        or stale_detail.error.code != "test_plan_execution_job_stale"
    ):
        raise TestPlanExecutionWorkerSmokeError(
            "stale job error code was not test_plan_execution_job_stale."
        )
    if fresh_detail.status != "running":
        raise TestPlanExecutionWorkerSmokeError(
            f"fresh job status is {fresh_detail.status!r}."
        )

    store.mark_failed(
        fresh_job.id,
        TestPlanExecutionJobError(
            code="recovery_smoke_cleanup",
            message="Recovery smoke cleaned up its fresh running control job.",
        ),
    )
    return {
        "stale_job_id": stale_job.id,
        "fresh_job_id": fresh_job.id,
        "recovered_job_ids": recovered_ids,
        "stale_status": stale_detail.status,
        "fresh_status_before_cleanup": fresh_detail.status,
        "cleanup": "fresh_job_marked_failed",
    }


def _wait_for_terminal_job(
    store: TestPlanExecutionJobStore,
    job_id: str,
    *,
    timeout_seconds: float,
) -> TestPlanExecutionJobDetail:
    deadline = time.time() + timeout_seconds
    last_detail: TestPlanExecutionJobDetail | None = None
    while time.time() < deadline:
        detail = store.get_job(job_id)
        if detail is not None:
            last_detail = detail
            if detail.status in {"succeeded", "failed"}:
                return detail
        time.sleep(0.02)
    status = last_detail.status if last_detail is not None else "missing"
    raise TestPlanExecutionWorkerSmokeError(
        f"job {job_id} did not finish before timeout; last_status={status}."
    )


def _request(label: str) -> TestPlanExecutionRequest:
    step = TestPlanStep(
        id="TP-001",
        title=f"Worker smoke step {label}",
        objective="Verify the worker can complete a persisted execution job.",
        requirement_ids=[f"REQ-{label}"],
        tool=TestToolType.manual,
        success_criteria=["Worker returns a persisted execution report."],
    )
    return TestPlanExecutionRequest(
        plan=TestPlan(
            id=f"plan-{label}",
            title=f"Worker smoke plan {label}",
            steps=[step],
        ),
        http_base_url="http://testserver",
    )


def _backdate_started_job(
    store: TestPlanExecutionJobStore,
    *,
    job_id: str,
    backdate_seconds: int,
) -> None:
    started_epoch = time.time() - backdate_seconds
    updated_at = datetime.fromtimestamp(started_epoch, timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute(
            """
            UPDATE test_plan_execution_jobs
            SET started_epoch = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (started_epoch, updated_at, job_id),
        )
        connection.commit()


if __name__ == "__main__":
    raise SystemExit(main())
