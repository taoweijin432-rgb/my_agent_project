from pathlib import Path

from scripts.smoke_test_plan_execution_runtime import main, run_runtime_smoke


def test_runtime_smoke_covers_retention_backpressure_and_worker(tmp_path: Path) -> None:
    result = run_runtime_smoke(base_dir=tmp_path, job_count=3, timeout_seconds=5)

    assert result["ok"] is True
    assert result["retention"]["expired_job_deleted"] is True
    assert result["retention"]["active_job_retained"] is True
    assert result["backpressure"]["queue_full_rejected"] is True
    assert result["backpressure"]["accepted_job_status"] == "queued"
    assert result["worker"]["succeeded_job_count"] == 3
    assert result["worker"]["recovered_job_count"] == 1


def test_runtime_smoke_main_outputs_json(capsys, tmp_path: Path) -> None:
    assert main(["--base-dir", str(tmp_path), "--job-count", "2", "--json"]) == 0

    output = capsys.readouterr().out
    assert '"ok": true' in output
    assert '"queue_full_rejected": true' in output
    assert '"succeeded_job_count": 2' in output


def test_runtime_smoke_main_reports_invalid_job_count(capsys, tmp_path: Path) -> None:
    assert main(["--base-dir", str(tmp_path), "--job-count", "0", "--json"]) == 1

    output = capsys.readouterr().out
    assert '"ok": false' in output
    assert "job_count must be greater than zero" in output
