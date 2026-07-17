import json
from pathlib import Path

from app.core.config import Settings
from scripts.smoke_test_plan_execution_worker import main, run_worker_smoke


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_backend="sqlite",
        generation_history_db_path=str(tmp_path / "jobs.sqlite3"),
        generation_job_queue_backend="in_memory",
        generation_job_max_workers=2,
        generation_job_max_queue_size=10,
        generation_job_stale_after_seconds=60,
    )


def test_worker_smoke_recovers_stale_job_and_processes_multiple_jobs(
    tmp_path: Path,
) -> None:
    result = run_worker_smoke(
        _settings(tmp_path),
        stale_after_seconds=60,
        backdate_seconds=120,
        job_count=3,
        timeout_seconds=2,
    )

    assert result["ok"] is True
    assert result["worker_backend"] == "in_memory"
    assert result["job_count"] == 3
    assert len(result["succeeded_job_ids"]) == 3
    assert result["recovery"]["recovered_job_ids"] == [
        result["recovery"]["stale_job_id"]
    ]
    assert result["recovery"]["fresh_status_before_cleanup"] == "running"
    assert result["jobs_by_status_after_smoke"] == {"failed": 2, "succeeded": 3}


def test_worker_smoke_main_prints_json(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--db-path",
            str(tmp_path / "jobs.sqlite3"),
            "--job-count",
            "2",
            "--stale-after-seconds",
            "60",
            "--backdate-seconds",
            "120",
            "--timeout-seconds",
            "2",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["job_count"] == 2
    assert payload["jobs_by_status_after_smoke"] == {"failed": 2, "succeeded": 2}


def test_worker_smoke_main_reports_invalid_backdate(capsys) -> None:
    code = main(
        [
            "--job-count",
            "1",
            "--stale-after-seconds",
            "60",
            "--backdate-seconds",
            "30",
            "--json",
        ]
    )

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "backdate_seconds must be greater" in payload["error"]
