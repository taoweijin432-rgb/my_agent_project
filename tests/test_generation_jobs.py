import threading
import time

import pytest

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationMetadata,
    GenerationUsage,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.generation_jobs import (
    GenerationJobQueueFullError,
    InMemoryGenerationJobQueue,
)
from app.services.generator import GenerationBudgetExceededError


def _request() -> GenerateRequest:
    return GenerateRequest(description="生成 JWT 登录测试用例", max_cases=3)


def _response() -> GenerateResponse:
    return GenerateResponse(
        cases=[
            CaseModel(
                id="TC-001",
                title="JWT 登录成功",
                precondition="管理员账号存在",
                steps=["输入账号密码", "点击登录"],
                expected=["登录成功"],
                type=CaseType.functional,
            )
        ],
        metadata=GenerationMetadata(
            model="fake-model",
            attempts=1,
            retrieved_chunks=0,
        ),
    )


def test_generation_job_queue_runs_successful_job() -> None:
    def runner(request: GenerateRequest, job_id: str):
        assert request.description == "生成 JWT 登录测试用例"
        assert job_id
        return _response(), "record-1"

    queue = InMemoryGenerationJobQueue(
        Settings(
            generation_job_max_workers=1,
            generation_job_max_queue_size=2,
            generation_job_retention_seconds=60,
        ),
        runner,
    )
    try:
        submitted = queue.submit(_request())
        detail = _wait_for_status(queue, submitted.id, "succeeded")
        jobs = queue.list_jobs(status="succeeded")

        assert submitted.status == "queued"
        assert detail is not None
        assert detail.response is not None
        assert detail.response.cases[0].title == "JWT 登录成功"
        assert detail.record_id == "record-1"
        assert detail.started_at is not None
        assert detail.finished_at is not None
        assert [job.id for job in jobs] == [submitted.id]
    finally:
        queue.shutdown()


def test_generation_job_queue_records_gate_failure() -> None:
    def runner(request: GenerateRequest, job_id: str):
        error = GenerationBudgetExceededError(
            "budget exceeded",
            usage=GenerationUsage(prompt_tokens_estimate=100),
        )
        error.record_id = "record-failed"
        raise error

    queue = InMemoryGenerationJobQueue(
        Settings(
            generation_job_max_workers=1,
            generation_job_max_queue_size=2,
            generation_job_retention_seconds=60,
        ),
        runner,
    )
    try:
        submitted = queue.submit(_request())
        detail = _wait_for_status(queue, submitted.id, "failed")

        assert detail is not None
        assert detail.error is not None
        assert detail.record_id == "record-failed"
        assert detail.error.code == "budget_exceeded"
        assert detail.error.status_code == 409
        assert detail.error.gate is not None
        assert detail.error.gate.usage is not None
        assert detail.error.gate.usage.prompt_tokens_estimate == 100
    finally:
        queue.shutdown()


def test_generation_job_queue_applies_backpressure_when_queue_is_full() -> None:
    started = threading.Event()
    release = threading.Event()

    def runner(request: GenerateRequest, job_id: str):
        started.set()
        release.wait(timeout=2)
        return _response(), None

    queue = InMemoryGenerationJobQueue(
        Settings(
            generation_job_max_workers=1,
            generation_job_max_queue_size=1,
            generation_job_retention_seconds=60,
        ),
        runner,
    )
    try:
        queue.submit(_request())
        assert started.wait(timeout=1)
        queue.submit(_request())

        with pytest.raises(GenerationJobQueueFullError):
            queue.submit(_request())
    finally:
        release.set()
        queue.shutdown()


def _wait_for_status(
    queue: InMemoryGenerationJobQueue,
    job_id: str,
    status: str,
):
    for _ in range(100):
        detail = queue.get_job(job_id)
        if detail is not None and detail.status == status:
            return detail
        time.sleep(0.01)
    return queue.get_job(job_id)
