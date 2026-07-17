import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from app.core.config import Settings
from app.models.test_plan import (
    TestAgentWorkflowJobDetail,
    TestAgentWorkflowJobError,
    TestAgentWorkflowJobStatus,
    TestAgentWorkflowJobSummary,
    TestAgentWorkflowRequest,
    TestAgentWorkflowResult,
)
from app.services.stores import (
    TestAgentWorkflowJobRepository,
    create_test_agent_workflow_job_store,
)
from app.services.test_agent_workflow import TestAgentWorkflowExecutionError
from app.services.test_agent_workflow_metrics import (
    build_test_agent_workflow_job_timing,
)


TestAgentWorkflowRunner = Callable[[TestAgentWorkflowRequest], TestAgentWorkflowResult]


class TestAgentWorkflowJobQueueFullError(RuntimeError):
    pass


class TestAgentWorkflowJobQueueUnavailableError(RuntimeError):
    pass


class TestAgentWorkflowJobQueue(Protocol):
    def submit(self, request: TestAgentWorkflowRequest) -> TestAgentWorkflowJobDetail:
        pass

    def get_job(self, job_id: str) -> TestAgentWorkflowJobDetail | None:
        pass

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[TestAgentWorkflowJobSummary]:
        pass


@dataclass
class _TestAgentWorkflowJobRecord:
    id: str
    request: TestAgentWorkflowRequest
    status: str
    created_at: str
    updated_at: str
    created_epoch: float
    started_at: str | None = None
    finished_at: str | None = None
    finished_epoch: float | None = None
    result: TestAgentWorkflowResult | None = None
    error: TestAgentWorkflowJobError | None = None


class InMemoryTestAgentWorkflowJobQueue:
    def __init__(
        self,
        settings: Settings,
        runner: TestAgentWorkflowRunner,
        store: TestAgentWorkflowJobRepository | None = None,
    ) -> None:
        self.max_queue_size = settings.generation_job_max_queue_size
        self.retention_seconds = settings.generation_job_retention_seconds
        self._runner = runner
        self.store = store
        if self.store:
            self.store.fail_stale_active_jobs(
                stale_after_seconds=settings.generation_job_stale_after_seconds
            )
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=self.max_queue_size)
        self._jobs: dict[str, _TestAgentWorkflowJobRecord] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"test-agent-workflow-worker-{index}",
                daemon=True,
            )
            for index in range(1, settings.generation_job_max_workers + 1)
        ]
        for worker in self._workers:
            worker.start()

    def submit(self, request: TestAgentWorkflowRequest) -> TestAgentWorkflowJobDetail:
        with self._lock:
            if self._shutdown:
                raise TestAgentWorkflowJobQueueFullError(
                    "Test agent workflow queue is shutting down."
                )
            self._cleanup_expired_locked()
            if self.store:
                detail = self.store.create_job(request)
                job = _record_from_detail(detail)
            else:
                now = _utc_now()
                job = _TestAgentWorkflowJobRecord(
                    id=uuid4().hex,
                    request=request,
                    status="queued",
                    created_at=now,
                    updated_at=now,
                    created_epoch=time.time(),
                )
            self._jobs[job.id] = job
            try:
                self._queue.put_nowait(job.id)
            except queue.Full as exc:
                del self._jobs[job.id]
                if self.store:
                    self.store.mark_failed(
                        job.id,
                        TestAgentWorkflowJobError(
                            code="queue_full",
                            message="Test agent workflow queue is full. Retry later.",
                        ),
                    )
                raise TestAgentWorkflowJobQueueFullError(
                    "Test agent workflow queue is full. Retry later."
                ) from exc
            return _detail_from_record(job)

    def get_job(self, job_id: str) -> TestAgentWorkflowJobDetail | None:
        if self.store:
            return self.store.get_job(job_id)
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
    ) -> list[TestAgentWorkflowJobSummary]:
        if self.store:
            return self.store.list_jobs(limit=limit, offset=offset, status=status)
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
        request = self._mark_running(job_id)
        if request is None:
            return
        try:
            result = self._runner(request)
        except TestAgentWorkflowExecutionError as exc:
            self._mark_failed(job_id, _error_from_execution_error(exc))
            return
        except Exception as exc:
            self._mark_failed(
                job_id,
                TestAgentWorkflowJobError(
                    code="workflow_failed",
                    message=f"{type(exc).__name__}: {exc}",
                ),
            )
            return
        self._mark_succeeded(job_id, result)

    def _mark_running(self, job_id: str) -> TestAgentWorkflowRequest | None:
        now = _utc_now()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.status = "running"
            job.started_at = now
            job.updated_at = now
            if self.store:
                self.store.mark_running(job_id)
            return job.request

    def _mark_succeeded(self, job_id: str, result: TestAgentWorkflowResult) -> None:
        now = _utc_now()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.result = result
            job.finished_at = now
            job.finished_epoch = time.time()
            job.updated_at = now
            if self.store:
                self.store.mark_succeeded(job_id, result)

    def _mark_failed(
        self,
        job_id: str,
        error: TestAgentWorkflowJobError,
    ) -> None:
        now = _utc_now()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "failed"
            job.error = error
            job.finished_at = now
            job.finished_epoch = time.time()
            job.updated_at = now
            if self.store:
                self.store.mark_failed(job_id, error)

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


class RedisRQTestAgentWorkflowJobQueue:
    def __init__(
        self,
        settings: Settings,
        store: TestAgentWorkflowJobRepository | None = None,
    ) -> None:
        self.settings = settings
        self.max_queue_size = settings.generation_job_max_queue_size
        self.store = store or create_test_agent_workflow_job_store(settings)
        self.store.fail_stale_active_jobs(
            stale_after_seconds=settings.generation_job_stale_after_seconds
        )
        try:
            from redis import Redis
            from redis.exceptions import RedisError
            from rq import Queue
        except ModuleNotFoundError as exc:
            raise TestAgentWorkflowJobQueueUnavailableError(
                "Redis/RQ dependencies are not installed. Install redis and rq."
            ) from exc

        self._redis_error_type = RedisError
        self._connection = Redis.from_url(settings.redis_url)
        self._queue = Queue(
            settings.rq_queue_name,
            connection=self._connection,
            default_timeout=settings.rq_job_timeout_seconds,
        )

    def submit(self, request: TestAgentWorkflowRequest) -> TestAgentWorkflowJobDetail:
        if self.store.count_active_jobs() >= self.max_queue_size:
            raise TestAgentWorkflowJobQueueFullError(
                "Test agent workflow queue is full. Retry later."
            )

        job = self.store.create_job(request)
        try:
            self._queue.enqueue_call(
                func="app.workers.test_agent_workflow_rq.run_test_agent_workflow_job",
                args=(job.id,),
                job_id=job.id,
                timeout=self.settings.rq_job_timeout_seconds,
                result_ttl=self.settings.rq_result_ttl_seconds,
                failure_ttl=self.settings.rq_failure_ttl_seconds,
            )
        except self._redis_error_type as exc:
            self.store.mark_failed(
                job.id,
                TestAgentWorkflowJobError(
                    code="queue_unavailable",
                    message=str(exc),
                ),
            )
            raise TestAgentWorkflowJobQueueUnavailableError(
                "Test agent workflow queue is unavailable. Retry later."
            ) from exc
        except Exception as exc:
            self.store.mark_failed(
                job.id,
                TestAgentWorkflowJobError(
                    code="queue_submit_failed",
                    message=str(exc) or exc.__class__.__name__,
                ),
            )
            raise TestAgentWorkflowJobQueueUnavailableError(
                "Test agent workflow queue submit failed. Retry later."
            ) from exc

        persisted = self.store.get_job(job.id)
        return persisted or job

    def get_job(self, job_id: str) -> TestAgentWorkflowJobDetail | None:
        return self.store.get_job(job_id)

    def list_jobs(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> list[TestAgentWorkflowJobSummary]:
        return self.store.list_jobs(limit=limit, offset=offset, status=status)


def _summary_from_record(
    record: _TestAgentWorkflowJobRecord,
) -> TestAgentWorkflowJobSummary:
    return TestAgentWorkflowJobSummary(
        id=record.id,
        status=TestAgentWorkflowJobStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error=record.error,
        timing=build_test_agent_workflow_job_timing(
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            result=record.result,
        ),
    )


def _detail_from_record(
    record: _TestAgentWorkflowJobRecord,
) -> TestAgentWorkflowJobDetail:
    return TestAgentWorkflowJobDetail(
        **_summary_from_record(record).model_dump(),
        request=record.request,
        result=record.result,
    )


def _record_from_detail(
    detail: TestAgentWorkflowJobDetail,
) -> _TestAgentWorkflowJobRecord:
    return _TestAgentWorkflowJobRecord(
        id=detail.id,
        request=detail.request,
        status=detail.status,
        created_at=detail.created_at,
        updated_at=detail.updated_at,
        created_epoch=time.time(),
        started_at=detail.started_at,
        finished_at=detail.finished_at,
        result=detail.result,
        error=detail.error,
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_from_execution_error(
    exc: TestAgentWorkflowExecutionError,
) -> TestAgentWorkflowJobError:
    return TestAgentWorkflowJobError(
        code=exc.error_code,
        message=str(exc),
        stage=exc.stage,
        timing=exc.timing,
    )
