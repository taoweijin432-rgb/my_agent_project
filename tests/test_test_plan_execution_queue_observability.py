from dataclasses import dataclass

from app.core.config import Settings
from scripts.check_test_plan_execution_queue import (
    TEST_PLAN_EXECUTION_RQ_FUNCTION,
    _count_jobs_for_function,
    build_database_snapshot,
    build_snapshot,
    evaluate_health,
    main,
)


@dataclass
class FakeExecutionJobStore:
    counts: dict[str, int]

    def count_jobs_by_status(self) -> dict[str, int]:
        return self.counts


@dataclass
class FakeRQJob:
    func_name: str


def test_database_snapshot_counts_test_plan_execution_active_jobs() -> None:
    snapshot = build_database_snapshot(
        Settings(database_backend="sqlite"),
        FakeExecutionJobStore({"queued": 2, "running": 1, "failed": 3}),
    )

    assert snapshot == {
        "backend": "sqlite",
        "configured_database_backend": "sqlite",
        "jobs_by_status": {"queued": 2, "running": 1, "failed": 3},
        "active_count": 3,
    }


def test_rq_count_filters_test_plan_execution_function() -> None:
    jobs = {
        "execution-1": FakeRQJob(TEST_PLAN_EXECUTION_RQ_FUNCTION),
        "generation-1": FakeRQJob("app.workers.generation_rq.run_generation_job"),
        "execution-2": FakeRQJob(TEST_PLAN_EXECUTION_RQ_FUNCTION),
    }

    count = _count_jobs_for_function(
        ["execution-1", "generation-1", "missing", "execution-2"],
        jobs.get,
        TEST_PLAN_EXECUTION_RQ_FUNCTION,
    )

    assert count == 2


def test_health_reports_test_plan_execution_rq_database_mismatch() -> None:
    health = evaluate_health(
        {"active_count": 2, "jobs_by_status": {"queued": 2}},
        {
            "backend": "rq",
            "queued": 1,
            "started": 0,
            "deferred": 0,
            "scheduled": 0,
            "failed": 0,
            "worker_count": 1,
        },
    )

    assert not health.ok
    assert health.errors == [
        "Database active test plan execution jobs exceed Redis/RQ active "
        "test plan execution jobs (database=2, rq=1)."
    ]


def test_health_warns_about_test_plan_execution_rq_failed_registry() -> None:
    health = evaluate_health(
        {"active_count": 0, "jobs_by_status": {"failed": 1}},
        {
            "backend": "rq",
            "queued": 0,
            "started": 0,
            "deferred": 0,
            "scheduled": 0,
            "failed": 2,
            "worker_count": 0,
        },
    )

    assert health.ok
    assert health.warnings == [
        "RQ failed registry contains 2 test plan execution job(s)."
    ]


def test_build_snapshot_keeps_execution_database_counts_when_rq_is_unavailable(
    monkeypatch,
) -> None:
    def fail(_: Settings) -> dict:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("scripts.check_test_plan_execution_queue.build_rq_snapshot", fail)

    snapshot = build_snapshot(
        Settings(generation_job_queue_backend="rq", rq_queue_name="generation"),
        FakeExecutionJobStore({"queued": 1}),
    )

    assert snapshot["database"]["active_count"] == 1
    assert snapshot["queue"] == {
        "backend": "rq",
        "active": False,
        "name": "generation",
        "function": TEST_PLAN_EXECUTION_RQ_FUNCTION,
        "error": "RuntimeError: redis unavailable",
    }
    assert snapshot["health"]["ok"] is False
    assert snapshot["health"]["errors"] == [
        "Redis/RQ inspection failed: RuntimeError: redis unavailable"
    ]


def test_test_plan_execution_queue_main_exits_nonzero_on_mismatch(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        "scripts.check_test_plan_execution_queue.build_snapshot",
        lambda: {
            "database": {
                "backend": "sqlite",
                "configured_database_backend": "sqlite",
                "jobs_by_status": {"queued": 1},
                "active_count": 1,
            },
            "queue": {
                "backend": "rq",
                "name": "generation",
                "function": TEST_PLAN_EXECUTION_RQ_FUNCTION,
                "queued": 0,
                "started": 0,
                "finished": 0,
                "failed": 0,
                "deferred": 0,
                "scheduled": 0,
                "worker_count": 0,
                "workers": [],
                "total": {},
            },
            "health": {
                "ok": False,
                "warnings": [],
                "errors": [
                    "Database active test plan execution jobs exceed Redis/RQ "
                    "active test plan execution jobs."
                ],
            },
        },
    )

    assert main(["--fail-on-mismatch"]) == 1
    assert "ok: false" in capsys.readouterr().out
