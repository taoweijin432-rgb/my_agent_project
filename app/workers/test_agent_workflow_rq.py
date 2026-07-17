import logging
import socket

from app.core.config import get_settings
from app.models.test_plan import TestAgentWorkflowJobError
from app.services.stores import create_test_agent_workflow_job_store
from app.services.test_agent_workflow import (
    TestAgentWorkflowExecutionError,
    execute_test_agent_workflow_request,
)


logger = logging.getLogger("app.test_agent_workflow_worker")


def recover_stale_test_agent_workflow_jobs() -> list[str]:
    settings = get_settings()
    store = create_test_agent_workflow_job_store(settings)
    job_ids = store.fail_stale_active_jobs(
        stale_after_seconds=settings.generation_job_stale_after_seconds
    )
    if job_ids:
        logger.warning(
            "marked stale test agent workflow jobs failed",
            extra={"job_ids": ",".join(job_ids), "count": len(job_ids)},
        )
    return job_ids


def run_test_agent_workflow_job(job_id: str) -> str | None:
    settings = get_settings()
    store = create_test_agent_workflow_job_store(settings)
    request = store.get_request(job_id)
    if request is None:
        logger.warning("test agent workflow job not found", extra={"job_id": job_id})
        return None

    store.mark_running(job_id)
    try:
        result = execute_test_agent_workflow_request(request, settings)
    except TestAgentWorkflowExecutionError as exc:
        logger.exception(
            "test agent workflow stage failed",
            extra={
                "job_id": job_id,
                "worker_id": socket.gethostname(),
                "stage": exc.stage.value,
                "error_code": exc.error_code,
            },
        )
        store.mark_failed(
            job_id,
            TestAgentWorkflowJobError(
                code=exc.error_code,
                message=str(exc),
                stage=exc.stage,
                timing=exc.timing,
            ),
        )
        return None
    except Exception as exc:
        logger.exception(
            "test agent workflow job failed",
            extra={"job_id": job_id, "worker_id": socket.gethostname()},
        )
        store.mark_failed(
            job_id,
            TestAgentWorkflowJobError(
                code="workflow_failed",
                message=f"{type(exc).__name__}: {exc}",
            ),
        )
        return None

    store.mark_succeeded(job_id, result)
    return result.report.id
