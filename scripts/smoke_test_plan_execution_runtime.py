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
    TestExecutionReport,
    TestPlan,
    TestPlanExecutionJobError,
    TestPlanExecutionRequest,
    TestPlanStep,
    TestReportStatus,
    TestToolType,
)
from app.services.test_plan_execution_jobs import (
    InMemoryTestPlanExecutionJobQueue,
    TestPlanExecutionJobQueueFullError,
)
from app.services.test_plan_execution_store import TestPlanExecutionJobStore
from scripts.smoke_test_plan_execution_worker import run_worker_smoke


class TestPlanExecutionRuntimeSmokeError(RuntimeError):
    pass


def run_runtime_smoke(
    *,
    base_dir: Path,
    job_count: int = 8,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    if job_count <= 0:
        raise TestPlanExecutionRuntimeSmokeError("job_count must be greater than zero.")
    if timeout_seconds <= 0:
        raise TestPlanExecutionRuntimeSmokeError("timeout_seconds must be greater than zero.")

    base_dir.mkdir(parents=True, exist_ok=True)
    retention = _run_retention_probe(base_dir / "retention.sqlite3")
    backpressure = _run_backpressure_probe(base_dir / "backpressure.sqlite3")
    worker = run_worker_smoke(
        _settings(
            db_path=base_dir / "worker.sqlite3",
            queue_size=max(job_count + 1, 2),
            workers=2,
            retention_seconds=86400,
            stale_after_seconds=60,
        ),
        stale_after_seconds=60,
        backdate_seconds=120,
        job_count=job_count,
        timeout_seconds=timeout_seconds,
    )
    return {
        "ok": True,
        "backend": "sqlite",
        "queue_backend": "in_memory",
        "retention": retention,
        "backpressure": backpressure,
        "worker": {
            "job_count": worker["job_count"],
            "succeeded_job_count": len(worker["succeeded_job_ids"]),
            "recovered_job_count": len(worker["recovery"]["recovered_job_ids"]),
            "jobs_by_status_after_smoke": worker["jobs_by_status_after_smoke"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.base_dir is None:
            with tempfile.TemporaryDirectory(prefix="test-plan-execution-runtime-") as tmp:
                result = run_runtime_smoke(
                    base_dir=Path(tmp),
                    job_count=args.job_count,
                    timeout_seconds=args.timeout_seconds,
                )
        else:
            result = run_runtime_smoke(
                base_dir=Path(args.base_dir),
                job_count=args.job_count,
                timeout_seconds=args.timeout_seconds,
            )
    except Exception as exc:
        payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"FAIL test-plan-execution-runtime-smoke: {payload['error']}")
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "PASS test-plan-execution-runtime-smoke: "
            f"jobs={result['worker']['job_count']} "
            f"retention_deleted={result['retention']['expired_job_deleted']} "
            f"queue_full={result['backpressure']['queue_full_rejected']}"
        )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify test plan execution runtime governance without Redis/MySQL.",
    )
    parser.add_argument(
        "--base-dir",
        help="Directory for isolated SQLite stores. Defaults to a temporary directory.",
    )
    parser.add_argument("--job-count", type=int, default=8)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args(argv)


def _run_retention_probe(db_path: Path) -> dict[str, Any]:
    store = TestPlanExecutionJobStore(
        _settings(
            db_path=db_path,
            queue_size=2,
            workers=1,
            retention_seconds=1,
            stale_after_seconds=60,
        )
    )
    expired = store.create_job(_request("retention-expired"))
    active = store.create_job(_request("retention-active"))
    store.mark_failed(
        expired.id,
        TestPlanExecutionJobError(
            code="retention_probe_expired",
            message="Expired retention probe job.",
        ),
    )
    store.mark_failed(
        active.id,
        TestPlanExecutionJobError(
            code="retention_probe_active",
            message="Active retention probe job.",
        ),
    )
    _backdate_finished_job(store, job_id=expired.id, backdate_seconds=10)

    counts = store.count_jobs_by_status()
    expired_after_cleanup = store.get_job(expired.id)
    active_after_cleanup = store.get_job(active.id)
    if expired_after_cleanup is not None:
        raise TestPlanExecutionRuntimeSmokeError("expired finished job was not cleaned up.")
    if active_after_cleanup is None:
        raise TestPlanExecutionRuntimeSmokeError("active finished job was incorrectly cleaned up.")
    return {
        "expired_job_deleted": True,
        "active_job_retained": True,
        "jobs_by_status_after_cleanup": counts,
    }


def _run_backpressure_probe(db_path: Path) -> dict[str, Any]:
    settings = _settings(
        db_path=db_path,
        queue_size=1,
        workers=0,
        retention_seconds=86400,
        stale_after_seconds=60,
    )
    store = TestPlanExecutionJobStore(settings)
    queue = InMemoryTestPlanExecutionJobQueue(
        settings,
        lambda request: _report_for_request(request, status=TestReportStatus.passed),
        store=store,
    )
    accepted = queue.submit(_request("backpressure-accepted"))
    rejected = False
    try:
        queue.submit(_request("backpressure-rejected"))
    except TestPlanExecutionJobQueueFullError:
        rejected = True

    if not rejected:
        raise TestPlanExecutionRuntimeSmokeError("queue full condition was not rejected.")
    accepted_detail = store.get_job(accepted.id)
    counts = store.count_jobs_by_status()
    if accepted_detail is None or accepted_detail.status != "queued":
        raise TestPlanExecutionRuntimeSmokeError("accepted queue control job was not queued.")
    if counts.get("failed", 0) != 1:
        raise TestPlanExecutionRuntimeSmokeError("rejected job was not persisted as failed.")
    return {
        "queue_full_rejected": True,
        "accepted_job_status": accepted_detail.status,
        "jobs_by_status_after_backpressure": counts,
    }


def _settings(
    *,
    db_path: Path,
    queue_size: int,
    workers: int,
    retention_seconds: int,
    stale_after_seconds: int,
) -> Settings:
    return Settings(
        database_backend="sqlite",
        generation_history_db_path=str(db_path),
        generation_job_queue_backend="in_memory",
        generation_job_max_workers=workers,
        generation_job_max_queue_size=queue_size,
        generation_job_retention_seconds=retention_seconds,
        generation_job_stale_after_seconds=stale_after_seconds,
    )


def _request(label: str) -> TestPlanExecutionRequest:
    step = TestPlanStep(
        id="TP-001",
        title=f"Runtime smoke step {label}",
        objective="Verify runtime governance behavior.",
        requirement_ids=[f"REQ-{label}"],
        tool=TestToolType.manual,
        success_criteria=["Runtime smoke completed."],
    )
    return TestPlanExecutionRequest(
        plan=TestPlan(
            id=f"plan-{label}",
            title=f"Runtime smoke plan {label}",
            steps=[step],
        ),
        http_base_url="http://testserver",
    )


def _report_for_request(
    request: TestPlanExecutionRequest,
    *,
    status: TestReportStatus,
) -> TestExecutionReport:
    return TestExecutionReport(
        id=f"report-{request.plan.id}",
        plan_id=request.plan.id,
        status=status,
        summary=f"{request.plan.title}: runtime smoke report.",
    )


def _backdate_finished_job(
    store: TestPlanExecutionJobStore,
    *,
    job_id: str,
    backdate_seconds: int,
) -> None:
    finished_epoch = time.time() - backdate_seconds
    updated_at = datetime.fromtimestamp(finished_epoch, timezone.utc).isoformat()
    with store._connect() as connection:
        connection.execute(
            """
            UPDATE test_plan_execution_jobs
            SET finished_epoch = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (finished_epoch, updated_at, updated_at, job_id),
        )
        connection.commit()


if __name__ == "__main__":
    raise SystemExit(main())
