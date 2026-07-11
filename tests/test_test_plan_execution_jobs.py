import time

from app.core.config import Settings
from app.models.test_plan import TestExecutionReport as ExecutionReport
from app.models.test_plan import TestPlan as Plan
from app.models.test_plan import TestPlanExecutionRequest as PlanExecutionRequest
from app.models.test_plan import TestReportStatus as ReportStatus
from app.services.test_plan_execution_jobs import (
    InMemoryTestPlanExecutionJobQueue,
    RedisRQTestPlanExecutionJobQueue,
    TestPlanExecutionJobQueueUnavailableError as QueueUnavailableError,
)
from app.services.test_plan_execution_store import TestPlanExecutionJobStore as JobStore
from app.workers import test_plan_execution_rq


def _request() -> PlanExecutionRequest:
    return PlanExecutionRequest(
        plan=Plan(id="plan-1", title="测试计划"),
        http_base_url="http://testserver",
    )


def _report() -> ExecutionReport:
    return ExecutionReport(
        id="report-plan-1",
        plan_id="plan-1",
        status=ReportStatus.passed,
    )


def test_test_plan_execution_job_queue_runs_successful_job() -> None:
    queue = InMemoryTestPlanExecutionJobQueue(
        Settings(generation_job_max_workers=1, generation_job_max_queue_size=2),
        lambda _: _report(),
    )
    try:
        submitted = queue.submit(_request())
        detail = _wait_for_status(queue, submitted.id, "succeeded")
        jobs = queue.list_jobs(status="succeeded")

        assert submitted.status == "queued"
        assert detail.report is not None
        assert detail.report.status == ReportStatus.passed
        assert jobs[0].id == submitted.id
    finally:
        queue.shutdown()


def test_test_plan_execution_job_queue_records_failure() -> None:
    def fail(_: PlanExecutionRequest) -> ExecutionReport:
        raise RuntimeError("adapter failed")

    queue = InMemoryTestPlanExecutionJobQueue(
        Settings(generation_job_max_workers=1, generation_job_max_queue_size=2),
        fail,
    )
    try:
        submitted = queue.submit(_request())
        detail = _wait_for_status(queue, submitted.id, "failed")

        assert detail.error is not None
        assert detail.error.code == "execution_failed"
        assert "adapter failed" in detail.error.message
    finally:
        queue.shutdown()


def test_test_plan_execution_job_queue_persists_to_store(tmp_path) -> None:
    settings = Settings(
        generation_job_max_workers=1,
        generation_job_max_queue_size=2,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    queue = InMemoryTestPlanExecutionJobQueue(settings, lambda _: _report(), store=store)
    try:
        submitted = queue.submit(_request())
        _wait_for_status(queue, submitted.id, "succeeded")

        persisted = JobStore(settings).get_job(submitted.id)
        assert persisted is not None
        assert persisted.status == "succeeded"
        assert persisted.report is not None
    finally:
        queue.shutdown()


def test_test_plan_execution_job_queue_recovers_stale_jobs_on_startup(tmp_path) -> None:
    settings = Settings(
        generation_job_max_workers=1,
        generation_job_max_queue_size=2,
        generation_job_stale_after_seconds=60,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    created = store.create_job(_request())
    store.mark_running(created.id)
    with store._connect() as connection:
        connection.execute(
            "UPDATE test_plan_execution_jobs SET started_epoch = 1 WHERE id = ?",
            (created.id,),
        )
        connection.commit()

    queue = InMemoryTestPlanExecutionJobQueue(settings, lambda _: _report(), store=store)
    try:
        recovered = store.get_job(created.id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.error is not None
        assert recovered.error.code == "test_plan_execution_job_stale"
    finally:
        queue.shutdown()


def test_redis_rq_test_plan_execution_job_queue_enqueues_persisted_job(tmp_path) -> None:
    settings = Settings(
        generation_job_max_queue_size=2,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    rq_queue = _FakeRQQueue()
    queue = RedisRQTestPlanExecutionJobQueue.__new__(RedisRQTestPlanExecutionJobQueue)
    queue.settings = settings
    queue.max_queue_size = settings.generation_job_max_queue_size
    queue.store = store
    queue._redis_error_type = RuntimeError
    queue._queue = rq_queue

    submitted = queue.submit(_request())

    persisted = store.get_job(submitted.id)
    assert persisted is not None
    assert persisted.status == "queued"
    assert rq_queue.calls[0]["func"] == (
        "app.workers.test_plan_execution_rq.run_test_plan_execution_job"
    )
    assert rq_queue.calls[0]["args"] == (submitted.id,)
    assert rq_queue.calls[0]["job_id"] == submitted.id


def test_redis_rq_test_plan_execution_job_queue_marks_failed_when_enqueue_fails(
    tmp_path,
) -> None:
    settings = Settings(
        generation_job_max_queue_size=2,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    queue = RedisRQTestPlanExecutionJobQueue.__new__(RedisRQTestPlanExecutionJobQueue)
    queue.settings = settings
    queue.max_queue_size = settings.generation_job_max_queue_size
    queue.store = store
    queue._redis_error_type = RuntimeError
    queue._queue = _FailingRQQueue()

    try:
        queue.submit(_request())
    except QueueUnavailableError:
        pass
    else:
        raise AssertionError("expected queue unavailable")

    jobs = store.list_jobs(status="failed")
    assert len(jobs) == 1
    assert jobs[0].error is not None
    assert jobs[0].error.code == "queue_unavailable"


def test_test_plan_execution_rq_worker_runs_persisted_job(monkeypatch, tmp_path) -> None:
    settings = Settings(generation_history_db_path=str(tmp_path / "app.sqlite3"))
    store = JobStore(settings)
    created = store.create_job(_request())
    monkeypatch.setattr(test_plan_execution_rq, "get_settings", lambda: settings)

    report_id = test_plan_execution_rq.run_test_plan_execution_job(created.id)

    detail = store.get_job(created.id)
    assert detail is not None
    assert detail.status == "succeeded"
    assert detail.report is not None
    assert detail.report.id == report_id


class _FakeRQQueue:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_call(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class _FailingRQQueue:
    def enqueue_call(self, **kwargs):
        raise RuntimeError("redis unavailable")


def _wait_for_status(
    queue: InMemoryTestPlanExecutionJobQueue,
    job_id: str,
    status: str,
):
    deadline = time.time() + 2
    while time.time() < deadline:
        detail = queue.get_job(job_id)
        if detail and detail.status == status:
            return detail
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {status}")
