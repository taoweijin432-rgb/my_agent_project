import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationGateDetail,
    GenerationJobDetail,
    GenerationJobError,
    GenerationJobSummary,
)
from app.services.generator import (
    GenerationGateError,
    OutputValidationError,
)
from app.services.llm import LLMError, MissingApiKeyError
from app.services.stores import GenerationJobRepository, create_generation_job_store


logger = logging.getLogger("app.generation_jobs")
GenerationJobRunner = Callable[[GenerateRequest, str], tuple[GenerateResponse, str | None]]


class GenerationJobQueueFullError(RuntimeError):
    pass


class GenerationJobQueueUnavailableError(RuntimeError):
    pass


class GenerationJobQueue(Protocol):
    def submit(self, request: GenerateRequest) -> GenerationJobDetail:
        pass

    def get_job(self, job_id: str) -> GenerationJobDetail | None:
        pass

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationJobSummary]:
        pass


@dataclass
class _GenerationJobRecord:
    id: str
    request: GenerateRequest
    status: str
    created_at: str
    updated_at: str
    created_epoch: float
    started_at: str | None = None
    finished_at: str | None = None
    finished_epoch: float | None = None
    response: GenerateResponse | None = None
    record_id: str | None = None
    error: GenerationJobError | None = None


class InMemoryGenerationJobQueue:
    def __init__(self, settings: Settings, runner: GenerationJobRunner) -> None:
        self.max_queue_size = settings.generation_job_max_queue_size
        self.retention_seconds = settings.generation_job_retention_seconds
        self._runner = runner
        self._queue: queue.Queue[str | None] = queue.Queue(
            maxsize=settings.generation_job_max_queue_size
        )
        self._jobs: dict[str, _GenerationJobRecord] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"generation-job-worker-{index}",
                daemon=True,
            )
            for index in range(1, settings.generation_job_max_workers + 1)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, request: GenerateRequest) -> GenerationJobDetail:
        now = _utc_now()
        now_epoch = time.time()
        job = _GenerationJobRecord(
            id=uuid4().hex,
            request=request,
            status="queued",
            created_at=now,
            updated_at=now,
            created_epoch=now_epoch,
        )
        with self._lock:
            if self._shutdown:
                raise GenerationJobQueueFullError("Generation job queue is shutting down.")
            self._cleanup_expired_locked()
            self._jobs[job.id] = job
            try:
                self._queue.put_nowait(job.id)
            except queue.Full as exc:
                del self._jobs[job.id]
                raise GenerationJobQueueFullError(
                    "Generation job queue is full. Retry later."
                ) from exc
            return _detail_from_record(job)

    def get_job(self, job_id: str) -> GenerationJobDetail | None:
        with self._lock:
            self._cleanup_expired_locked()
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return _detail_from_record(job)

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationJobSummary]:
        with self._lock:
            self._cleanup_expired_locked()
            jobs = list(self._jobs.values())
            if status:
                jobs = [job for job in jobs if job.status == status]
            jobs.sort(key=lambda job: job.created_epoch, reverse=True)
            return [_summary_from_record(job) for job in jobs[offset : offset + limit]]

    def shutdown(self, *, timeout: float = 2.0) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        for _ in self._workers:
            self._queue.put(None)
        for worker in self._workers:
            worker.join(timeout=timeout)

    def _worker_loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id is None:
                    return
                self._run_job(job_id)
            finally:
                self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        job = self._mark_running(job_id)
        if job is None:
            return
        try:
            response, record_id = self._runner(job.request, job.id)
        except Exception as exc:
            if isinstance(
                exc,
                (GenerationGateError, MissingApiKeyError, LLMError, OutputValidationError),
            ):
                logger.info("generation job failed", extra={"job_id": job_id})
            else:
                logger.exception("generation job failed", extra={"job_id": job_id})
            self._mark_failed(
                job_id,
                _error_from_exception(exc),
                record_id=getattr(exc, "record_id", None),
            )
            return
        self._mark_succeeded(job_id, response=response, record_id=record_id)

    def _mark_running(self, job_id: str) -> _GenerationJobRecord | None:
        now = _utc_now()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status = "running"
            job.started_at = now
            job.updated_at = now
            return job

    def _mark_succeeded(
        self,
        job_id: str,
        *,
        response: GenerateResponse,
        record_id: str | None,
    ) -> None:
        now = _utc_now()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.response = response
            job.record_id = record_id
            job.finished_at = now
            job.finished_epoch = time.time()
            job.updated_at = now

    def _mark_failed(
        self,
        job_id: str,
        error: GenerationJobError,
        *,
        record_id: str | None,
    ) -> None:
        now = _utc_now()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = error
            job.record_id = record_id
            job.finished_at = now
            job.finished_epoch = time.time()
            job.updated_at = now

    def _cleanup_expired_locked(self) -> None:
        if self.retention_seconds <= 0:
            return
        cutoff = time.time() - self.retention_seconds
        expired_ids = [
            job_id
            for job_id, job in self._jobs.items()
            if job.finished_epoch is not None and job.finished_epoch < cutoff
        ]
        for job_id in expired_ids:
            del self._jobs[job_id]


class RedisRQGenerationJobQueue:
    def __init__(
        self,
        settings: Settings,
        store: GenerationJobRepository | None = None,
    ) -> None:
        self.settings = settings
        self.max_queue_size = settings.generation_job_max_queue_size
        self.store = store or create_generation_job_store(settings)
        try:
            from redis import Redis
            from redis.exceptions import RedisError
            from rq import Queue
        except ModuleNotFoundError as exc:
            raise GenerationJobQueueUnavailableError(
                "Redis/RQ dependencies are not installed. Install redis and rq."
            ) from exc

        self._redis_error_type = RedisError
        self._connection = Redis.from_url(settings.redis_url)
        self._queue = Queue(
            settings.rq_queue_name,
            connection=self._connection,
            default_timeout=settings.rq_job_timeout_seconds,
        )

    def submit(self, request: GenerateRequest) -> GenerationJobDetail:
        if self.store.count_active_jobs() >= self.max_queue_size:
            raise GenerationJobQueueFullError("Generation job queue is full. Retry later.")

        job = self.store.create_job(request, queue_backend="rq")
        try:
            rq_job = self._queue.enqueue_call(
                func="app.workers.generation_rq.run_generation_job",
                args=(job.id,),
                job_id=job.id,
                timeout=self.settings.rq_job_timeout_seconds,
                result_ttl=self.settings.rq_result_ttl_seconds,
                failure_ttl=self.settings.rq_failure_ttl_seconds,
            )
        except self._redis_error_type as exc:
            self.store.mark_failed(
                job.id,
                error=GenerationJobError(
                    code="queue_unavailable",
                    message=str(exc),
                    status_code=503,
                ),
            )
            raise GenerationJobQueueUnavailableError(
                "Generation job queue is unavailable. Retry later."
            ) from exc
        except Exception as exc:
            self.store.mark_failed(
                job.id,
                error=GenerationJobError(
                    code="queue_submit_failed",
                    message=str(exc) or exc.__class__.__name__,
                    status_code=503,
                ),
            )
            raise GenerationJobQueueUnavailableError(
                "Generation job queue submit failed. Retry later."
            ) from exc

        self.store.set_queue_job_id(job.id, rq_job.id)
        persisted = self.store.get_job(job.id)
        return persisted or job

    def get_job(self, job_id: str) -> GenerationJobDetail | None:
        return self.store.get_job(job_id)

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[GenerationJobSummary]:
        return self.store.list_jobs(limit=limit, offset=offset, status=status)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary_from_record(job: _GenerationJobRecord) -> GenerationJobSummary:
    return GenerationJobSummary(
        id=job.id,
        status=job.status,
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        record_id=job.record_id,
        error=job.error,
    )


def _detail_from_record(job: _GenerationJobRecord) -> GenerationJobDetail:
    return GenerationJobDetail(
        **_summary_from_record(job).model_dump(),
        request=job.request,
        response=job.response,
    )


def _error_from_exception(exc: Exception) -> GenerationJobError:
    if isinstance(exc, GenerationGateError):
        return GenerationJobError(
            code=exc.code,
            message=str(exc),
            status_code=409,
            gate=GenerationGateDetail.model_validate(exc.to_detail()),
        )
    if isinstance(exc, MissingApiKeyError):
        return GenerationJobError(
            code="missing_api_key",
            message=str(exc),
            status_code=503,
        )
    if isinstance(exc, LLMError):
        return GenerationJobError(
            code="llm_error",
            message=str(exc),
            status_code=502,
        )
    if isinstance(exc, OutputValidationError):
        return GenerationJobError(
            code="output_validation_failed",
            message=str(exc),
            status_code=502,
        )
    return GenerationJobError(
        code="generation_job_failed",
        message=str(exc) or exc.__class__.__name__,
        status_code=500,
    )
