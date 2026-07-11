import json
from pathlib import Path

from app.core.config import Settings
from scripts.smoke_recover_stale_generation_jobs import main, run_recovery_smoke


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_backend="sqlite",
        generation_history_db_path=str(tmp_path / "jobs.sqlite3"),
        generation_job_queue_backend="rq",
        generation_job_stale_after_seconds=60,
    )


def test_recovery_smoke_recovers_only_stale_job_and_cleans_up(tmp_path: Path) -> None:
    result = run_recovery_smoke(
        _settings(tmp_path),
        stale_after_seconds=60,
        backdate_seconds=120,
    )

    assert result["ok"] is True
    assert result["backend"] == "sqlite"
    assert result["queue_backend"] == "rq"
    assert len(result["recovered_job_ids"]) == 1
    assert result["recovered_job_ids"] == [result["stale_job_id"]]
    assert result["stale_status"] == "failed"
    assert result["fresh_status_before_cleanup"] == "running"
    assert result["cleanup"] == "fresh_job_marked_failed"
    assert result["jobs_by_status_after_cleanup"] == {"failed": 2}


def test_recovery_smoke_main_prints_json(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--db-path",
            str(tmp_path / "jobs.sqlite3"),
            "--stale-after-seconds",
            "60",
            "--backdate-seconds",
            "120",
            "--json",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["fresh_status_before_cleanup"] == "running"
    assert payload["jobs_by_status_after_cleanup"] == {"failed": 2}


def test_recovery_smoke_main_reports_missing_mysql_url(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    code = main(["--backend", "mysql", "--json"])

    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "DATABASE_URL is required" in payload["error"]
