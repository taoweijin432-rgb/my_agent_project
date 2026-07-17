import logging
import socket

from app.core.config import get_settings
from app.models.test_plan import TestPlanExecutionJobError
from app.services.test_plan_execution import execute_test_plan_request
from app.services.stores import create_test_plan_execution_job_store


logger = logging.getLogger("app.test_plan_execution_worker")


def recover_stale_test_plan_execution_jobs() -> list[str]:
    settings = get_settings()
    store = create_test_plan_execution_job_store(settings)
    job_ids = store.fail_stale_active_jobs(
        stale_after_seconds=settings.generation_job_stale_after_seconds
    )
    if job_ids:
        logger.warning(
            "marked stale test plan execution jobs failed",
            extra={"job_ids": ",".join(job_ids), "count": len(job_ids)},
        )
    return job_ids


def run_test_plan_execution_job(job_id: str) -> str | None:
    settings = get_settings()
    store = create_test_plan_execution_job_store(settings)
    request = store.get_request(job_id)
    if request is None:
        logger.warning("test plan execution job not found", extra={"job_id": job_id})
        return None

    store.mark_running(job_id)
    try:
        report = execute_test_plan_request(request, settings)
    except Exception as exc:
        logger.exception(
            "test plan execution job failed",
            extra={"job_id": job_id, "worker_id": socket.gethostname()},
        )
        store.mark_failed(
            job_id,
            TestPlanExecutionJobError(
                code="execution_failed",
                message=f"{type(exc).__name__}: {exc}",
            ),
        )
        return None

    store.mark_succeeded(job_id, report)
    return report.id
