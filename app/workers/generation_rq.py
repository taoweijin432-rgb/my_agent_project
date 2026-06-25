import logging
import socket

from app.core.config import get_settings
from app.services.generation_execution import execute_generation
from app.services.generation_jobs import _error_from_exception
from app.services.generator import TestCaseGenerator
from app.services.llm import LLMClient
from app.services.rag import RagService
from app.services.stores import (
    create_generation_history_store,
    create_generation_job_store,
)


logger = logging.getLogger("app.generation_worker")


def recover_stale_generation_jobs() -> list[str]:
    settings = get_settings()
    store = create_generation_job_store(settings)
    job_ids = store.fail_stale_running_jobs(
        stale_after_seconds=settings.generation_job_stale_after_seconds
    )
    if job_ids:
        logger.warning(
            "marked stale generation jobs failed",
            extra={"job_ids": ",".join(job_ids), "count": len(job_ids)},
        )
    return job_ids


def run_generation_job(job_id: str) -> str | None:
    settings = get_settings()
    store = create_generation_job_store(settings)
    request = store.get_request(job_id)
    if request is None:
        logger.warning("generation job not found", extra={"job_id": job_id})
        return None

    store.mark_running(job_id, worker_id=socket.gethostname())
    try:
        result = execute_generation(
            request,
            request_id=job_id,
            generator_factory=lambda: TestCaseGenerator(
                settings=settings,
                llm=LLMClient(settings),
                rag=lambda: RagService(settings),
            ),
            history_store_factory=lambda: create_generation_history_store(settings),
            logger=logger,
        )
    except Exception as exc:
        if getattr(exc, "record_id", None) is None:
            logger.exception("generation job failed", extra={"job_id": job_id})
        else:
            logger.info("generation job failed", extra={"job_id": job_id})
        store.mark_failed(
            job_id,
            error=_error_from_exception(exc),
            record_id=getattr(exc, "record_id", None),
        )
        return getattr(exc, "record_id", None)

    store.mark_succeeded(
        job_id,
        response=result.response,
        record_id=result.record_id,
    )
    return result.record_id
