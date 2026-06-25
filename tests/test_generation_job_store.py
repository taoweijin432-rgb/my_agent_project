from pathlib import Path

from app.core.config import Settings
from app.models.test_case import (
    GenerateRequest,
    GenerateResponse,
    GenerationJobError,
    GenerationMetadata,
    TestCase as CaseModel,
    TestCaseType as CaseType,
)
from app.services.generation_job_store import GenerationJobStore


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


def test_generation_job_store_records_successful_job(tmp_path: Path) -> None:
    store = GenerationJobStore(
        Settings(generation_history_db_path=str(tmp_path / "jobs.sqlite3"))
    )

    submitted = store.create_job(_request(), queue_backend="rq")
    store.set_queue_job_id(submitted.id, "rq-job-1")
    store.mark_running(submitted.id, worker_id="worker-1")
    store.mark_succeeded(submitted.id, response=_response(), record_id="record-1")

    detail = store.get_job(submitted.id)
    jobs = store.list_jobs(status="succeeded")

    assert submitted.status == "queued"
    assert detail is not None
    assert detail.status == "succeeded"
    assert detail.started_at is not None
    assert detail.finished_at is not None
    assert detail.record_id == "record-1"
    assert detail.response is not None
    assert detail.response.cases[0].title == "JWT 登录成功"
    assert [job.id for job in jobs] == [submitted.id]
    assert store.count_active_jobs() == 0


def test_generation_job_store_records_failed_job(tmp_path: Path) -> None:
    store = GenerationJobStore(
        Settings(generation_history_db_path=str(tmp_path / "jobs.sqlite3"))
    )

    submitted = store.create_job(_request(), queue_backend="rq")
    store.mark_failed(
        submitted.id,
        error=GenerationJobError(
            code="queue_submit_failed",
            message="redis unavailable",
            status_code=503,
        ),
    )

    detail = store.get_job(submitted.id)
    failed_jobs = store.list_jobs(status="failed")

    assert detail is not None
    assert detail.status == "failed"
    assert detail.error is not None
    assert detail.error.code == "queue_submit_failed"
    assert detail.error.status_code == 503
    assert [job.id for job in failed_jobs] == [submitted.id]


def test_generation_job_store_counts_jobs_by_status(tmp_path: Path) -> None:
    store = GenerationJobStore(
        Settings(generation_history_db_path=str(tmp_path / "jobs.sqlite3"))
    )

    queued = store.create_job(_request(), queue_backend="rq")
    running = store.create_job(_request(), queue_backend="rq")
    failed = store.create_job(_request(), queue_backend="rq")
    store.mark_running(running.id, worker_id="worker-1")
    store.mark_failed(
        failed.id,
        error=GenerationJobError(
            code="generation_failed",
            message="failed",
            status_code=500,
        ),
    )

    assert queued.status == "queued"
    assert store.count_jobs_by_status() == {
        "failed": 1,
        "queued": 1,
        "running": 1,
    }
    assert store.count_active_jobs() == 2


def test_generation_job_store_marks_stale_running_jobs_failed(tmp_path: Path) -> None:
    store = GenerationJobStore(
        Settings(generation_history_db_path=str(tmp_path / "jobs.sqlite3"))
    )
    stale = store.create_job(_request(), queue_backend="rq")
    fresh = store.create_job(_request(), queue_backend="rq")
    store.mark_running(stale.id, worker_id="worker-1")
    store.mark_running(fresh.id, worker_id="worker-1")
    with store._connect() as connection:
        connection.execute(
            """
            UPDATE generation_jobs
            SET started_epoch = started_epoch - 3600,
                updated_at = '2000-01-01T00:00:00+00:00'
            WHERE id = ?
            """,
            (stale.id,),
        )
        connection.commit()

    stale_ids = store.fail_stale_running_jobs(stale_after_seconds=1800)

    stale_detail = store.get_job(stale.id)
    fresh_detail = store.get_job(fresh.id)

    assert stale_ids == [stale.id]
    assert stale_detail is not None
    assert stale_detail.status == "failed"
    assert stale_detail.error is not None
    assert stale_detail.error.code == "generation_job_stale"
    assert stale_detail.finished_at is not None
    assert fresh_detail is not None
    assert fresh_detail.status == "running"
