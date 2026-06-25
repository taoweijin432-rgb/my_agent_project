from dataclasses import dataclass

from app.core.config import Settings
from scripts.check_generation_queue import (
    build_snapshot,
    build_database_snapshot,
    evaluate_health,
    main,
)


@dataclass
class FakeJobStore:
    counts: dict[str, int]

    def count_jobs_by_status(self) -> dict[str, int]:
        return self.counts


def test_database_snapshot_counts_active_jobs() -> None:
    snapshot = build_database_snapshot(
        Settings(database_backend="sqlite"),
        FakeJobStore({"queued": 2, "running": 1, "failed": 3}),
    )

    assert snapshot == {
        "backend": "sqlite",
        "jobs_by_status": {"queued": 2, "running": 1, "failed": 3},
        "active_count": 3,
    }


def test_health_reports_rq_database_mismatch() -> None:
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
        "Database active jobs exceed Redis/RQ active jobs (database=2, rq=1)."
    ]


def test_health_warns_about_rq_failed_registry() -> None:
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
    assert health.warnings == ["RQ failed registry contains 2 job(s)."]


def test_build_snapshot_keeps_database_counts_when_rq_is_unavailable(
    monkeypatch,
) -> None:
    def fail(_: Settings) -> dict:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("scripts.check_generation_queue.build_rq_snapshot", fail)

    snapshot = build_snapshot(
        Settings(generation_job_queue_backend="rq", rq_queue_name="generation"),
        FakeJobStore({"queued": 1}),
    )

    assert snapshot["database"]["active_count"] == 1
    assert snapshot["queue"] == {
        "backend": "rq",
        "active": False,
        "name": "generation",
        "error": "RuntimeError: redis unavailable",
    }
    assert snapshot["health"]["ok"] is False
    assert snapshot["health"]["errors"] == [
        "Redis/RQ inspection failed: RuntimeError: redis unavailable"
    ]


def test_main_exits_nonzero_on_mismatch(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.check_generation_queue.build_snapshot",
        lambda: {
            "database": {
                "backend": "sqlite",
                "jobs_by_status": {"queued": 1},
                "active_count": 1,
            },
            "queue": {
                "backend": "rq",
                "name": "generation",
                "queued": 0,
                "started": 0,
                "finished": 0,
                "failed": 0,
                "deferred": 0,
                "scheduled": 0,
                "worker_count": 0,
                "workers": [],
            },
            "health": {
                "ok": False,
                "warnings": [],
                "errors": ["Database active jobs exceed Redis/RQ active jobs."],
            },
        },
    )

    assert main(["--fail-on-mismatch"]) == 1
    assert "ok: false" in capsys.readouterr().out


def test_main_reports_inspection_failure_without_traceback(monkeypatch, capsys) -> None:
    def fail() -> dict:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr("scripts.check_generation_queue.build_snapshot", fail)

    assert main([]) == 2
    output = capsys.readouterr().out
    assert "Generation queue check failed" in output
    assert "RuntimeError: redis unavailable" in output


def test_main_exits_nonzero_when_rq_inspection_fails(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.check_generation_queue.build_snapshot",
        lambda: {
            "database": {
                "backend": "sqlite",
                "jobs_by_status": {},
                "active_count": 0,
            },
            "queue": {
                "backend": "rq",
                "active": False,
                "name": "generation",
                "error": "ConnectionError: redis unavailable",
            },
            "health": {
                "ok": False,
                "warnings": [],
                "errors": [
                    "Redis/RQ inspection failed: ConnectionError: redis unavailable"
                ],
            },
        },
    )

    assert main(["--json"]) == 2
    assert "ConnectionError: redis unavailable" in capsys.readouterr().out
