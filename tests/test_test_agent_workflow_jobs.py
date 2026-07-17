import time

from app.core.config import Settings
from app.models.test_plan import (
    TestAgentWorkflowRequest as WorkflowRequest,
    TestAgentWorkflowResult as WorkflowResult,
    TestAgentWorkflowStage as WorkflowStage,
    TestAgentWorkflowTiming as WorkflowTiming,
    TestAgentWorkflowStageTiming as WorkflowStageTiming,
    TestExecutionReport as ExecutionReport,
    TestPlan as Plan,
    TestPlanGenerationRequest as PlanGenerationRequest,
    TestReportStatus as ReportStatus,
)
from app.services.test_agent_workflow_jobs import (
    InMemoryTestAgentWorkflowJobQueue,
    RedisRQTestAgentWorkflowJobQueue,
    TestAgentWorkflowJobQueueUnavailableError as QueueUnavailableError,
)
from app.services.test_agent_workflow import TestAgentWorkflowExecutionError
from app.services.test_agent_workflow_store import TestAgentWorkflowJobStore as JobStore
from app.workers import test_agent_workflow_rq


def _request() -> WorkflowRequest:
    return WorkflowRequest(
        generation_request=PlanGenerationRequest(description="退款接口需要覆盖幂等冲突。"),
        http_base_url="http://testserver",
    )


def _result() -> WorkflowResult:
    plan = Plan(id="plan-1", title="测试计划")
    return WorkflowResult(
        plan=plan,
        report=ExecutionReport(
            id="report-plan-1",
            plan_id=plan.id,
            status=ReportStatus.passed,
        ),
        timing=WorkflowTiming(
            total_ms=12.3,
            stages=[
                WorkflowStageTiming(
                    name="plan_generation",
                    started_at="2026-07-10T00:00:00+00:00",
                    finished_at="2026-07-10T00:00:00.010000+00:00",
                    duration_ms=10,
                ),
                WorkflowStageTiming(
                    name="tool_execution",
                    started_at="2026-07-10T00:00:00.010000+00:00",
                    finished_at="2026-07-10T00:00:00.012000+00:00",
                    duration_ms=2,
                ),
                WorkflowStageTiming(
                    name="report_build",
                    started_at="2026-07-10T00:00:00.012000+00:00",
                    finished_at="2026-07-10T00:00:00.012300+00:00",
                    duration_ms=0.3,
                ),
            ],
        ),
    )


def test_test_agent_workflow_job_queue_runs_successful_job() -> None:
    queue = InMemoryTestAgentWorkflowJobQueue(
        Settings(generation_job_max_workers=1, generation_job_max_queue_size=2),
        lambda _: _result(),
    )
    try:
        submitted = queue.submit(_request())
        detail = _wait_for_status(queue, submitted.id, "succeeded")
        jobs = queue.list_jobs(status="succeeded")

        assert submitted.status == "queued"
        assert detail.result is not None
        assert detail.result.report.status == ReportStatus.passed
        assert detail.timing.workflow_total_ms == 12.3
        assert detail.timing.plan_generation_ms == 10
        assert jobs[0].id == submitted.id
    finally:
        queue.shutdown()


def test_test_agent_workflow_job_queue_records_failure() -> None:
    def fail(_: WorkflowRequest) -> WorkflowResult:
        raise RuntimeError("llm timeout")

    queue = InMemoryTestAgentWorkflowJobQueue(
        Settings(generation_job_max_workers=1, generation_job_max_queue_size=2),
        fail,
    )
    try:
        submitted = queue.submit(_request())
        detail = _wait_for_status(queue, submitted.id, "failed")

        assert detail.error is not None
        assert detail.error.code == "workflow_failed"
        assert "llm timeout" in detail.error.message
    finally:
        queue.shutdown()


def test_test_agent_workflow_job_queue_records_stage_failure() -> None:
    def fail(_: WorkflowRequest) -> WorkflowResult:
        raise _stage_timeout_error()

    queue = InMemoryTestAgentWorkflowJobQueue(
        Settings(generation_job_max_workers=1, generation_job_max_queue_size=2),
        fail,
    )
    try:
        submitted = queue.submit(_request())
        detail = _wait_for_status(queue, submitted.id, "failed")

        assert detail.error is not None
        assert detail.error.code == "plan_generation_timeout"
        assert detail.error.stage == WorkflowStage.plan_generation
        assert detail.error.timing.stages[0].status == "failed"
        assert detail.error.timing.stages[0].error_code == "plan_generation_timeout"
    finally:
        queue.shutdown()


def test_test_agent_workflow_job_queue_persists_to_store(tmp_path) -> None:
    settings = Settings(
        generation_job_max_workers=1,
        generation_job_max_queue_size=2,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    queue = InMemoryTestAgentWorkflowJobQueue(settings, lambda _: _result(), store=store)
    try:
        submitted = queue.submit(_request())
        _wait_for_status(queue, submitted.id, "succeeded")

        persisted = JobStore(settings).get_job(submitted.id)
        assert persisted is not None
        assert persisted.status == "succeeded"
        assert persisted.result is not None
    finally:
        queue.shutdown()


def test_test_agent_workflow_job_queue_recovers_stale_jobs_on_startup(tmp_path) -> None:
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
            "UPDATE test_agent_workflow_jobs SET started_epoch = 1 WHERE id = ?",
            (created.id,),
        )
        connection.commit()

    queue = InMemoryTestAgentWorkflowJobQueue(settings, lambda _: _result(), store=store)
    try:
        recovered = store.get_job(created.id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.error is not None
        assert recovered.error.code == "test_agent_workflow_job_stale"
    finally:
        queue.shutdown()


def test_test_agent_workflow_job_queue_recovers_stale_queued_jobs_on_startup(
    tmp_path,
) -> None:
    settings = Settings(
        generation_job_max_workers=1,
        generation_job_max_queue_size=2,
        generation_job_stale_after_seconds=60,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    created = store.create_job(_request())
    with store._connect() as connection:
        connection.execute(
            "UPDATE test_agent_workflow_jobs SET created_epoch = 1 WHERE id = ?",
            (created.id,),
        )
        connection.commit()

    queue = InMemoryTestAgentWorkflowJobQueue(settings, lambda _: _result(), store=store)
    try:
        recovered = store.get_job(created.id)
        assert recovered is not None
        assert recovered.status == "failed"
        assert recovered.error is not None
        assert recovered.error.code == "test_agent_workflow_job_stale"
        assert "queued or running" in recovered.error.message
    finally:
        queue.shutdown()


def test_redis_rq_test_agent_workflow_job_queue_enqueues_persisted_job(tmp_path) -> None:
    settings = Settings(
        generation_job_max_queue_size=2,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    rq_queue = _FakeRQQueue()
    queue = RedisRQTestAgentWorkflowJobQueue.__new__(RedisRQTestAgentWorkflowJobQueue)
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
        "app.workers.test_agent_workflow_rq.run_test_agent_workflow_job"
    )
    assert rq_queue.calls[0]["args"] == (submitted.id,)
    assert rq_queue.calls[0]["job_id"] == submitted.id


def test_redis_rq_test_agent_workflow_job_queue_marks_failed_when_enqueue_fails(
    tmp_path,
) -> None:
    settings = Settings(
        generation_job_max_queue_size=2,
        generation_history_db_path=str(tmp_path / "app.sqlite3"),
    )
    store = JobStore(settings)
    queue = RedisRQTestAgentWorkflowJobQueue.__new__(RedisRQTestAgentWorkflowJobQueue)
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


def test_test_agent_workflow_rq_worker_runs_persisted_job(monkeypatch, tmp_path) -> None:
    settings = Settings(generation_history_db_path=str(tmp_path / "app.sqlite3"))
    store = JobStore(settings)
    created = store.create_job(_request())
    monkeypatch.setattr(test_agent_workflow_rq, "get_settings", lambda: settings)

    report_id = test_agent_workflow_rq.run_test_agent_workflow_job(created.id)

    detail = store.get_job(created.id)
    assert detail is not None
    assert detail.status == "succeeded"
    assert detail.result is not None
    assert detail.result.report.id == report_id


def test_test_agent_workflow_rq_worker_records_stage_failure(
    monkeypatch,
    tmp_path,
) -> None:
    settings = Settings(generation_history_db_path=str(tmp_path / "app.sqlite3"))
    store = JobStore(settings)
    created = store.create_job(_request())
    monkeypatch.setattr(test_agent_workflow_rq, "get_settings", lambda: settings)
    monkeypatch.setattr(
        test_agent_workflow_rq,
        "execute_test_agent_workflow_request",
        lambda _request, _settings: (_ for _ in ()).throw(_stage_timeout_error()),
    )

    report_id = test_agent_workflow_rq.run_test_agent_workflow_job(created.id)

    detail = store.get_job(created.id)
    assert report_id is None
    assert detail is not None
    assert detail.status == "failed"
    assert detail.error is not None
    assert detail.error.code == "plan_generation_timeout"
    assert detail.error.stage == WorkflowStage.plan_generation


class _FakeRQQueue:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_call(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class _FailingRQQueue:
    def enqueue_call(self, **kwargs):
        raise RuntimeError("redis unavailable")


def _stage_timeout_error() -> TestAgentWorkflowExecutionError:
    return TestAgentWorkflowExecutionError(
        stage=WorkflowStage.plan_generation,
        error_code="plan_generation_timeout",
        cause=TimeoutError("llm timeout"),
        timing=WorkflowTiming(
            total_ms=1200,
            stages=[
                WorkflowStageTiming(
                    name=WorkflowStage.plan_generation,
                    started_at="2026-07-10T00:00:00+00:00",
                    finished_at="2026-07-10T00:00:01.200000+00:00",
                    duration_ms=1200,
                    status="failed",
                    error_code="plan_generation_timeout",
                )
            ],
        ),
    )


def _wait_for_status(
    queue: InMemoryTestAgentWorkflowJobQueue,
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
