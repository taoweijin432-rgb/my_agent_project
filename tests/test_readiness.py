import json
from pathlib import Path

from app.core.config import Settings, get_settings
from app.services.readiness import (
    build_readiness_report,
    readiness_status_code,
)
from scripts.check_readiness import main


class FakeJobStore:
    def __init__(self, counts: dict[str, int] | None = None, error: Exception | None = None):
        self.counts = counts or {}
        self.error = error

    def count_jobs_by_status(self) -> dict[str, int]:
        if self.error:
            raise self.error
        return self.counts


def _settings(tmp_path: Path, *, queue_backend: str = "in_memory") -> Settings:
    return Settings(
        chroma_path=str(tmp_path / "chroma"),
        embedding_cache_dir=str(tmp_path / "model-cache"),
        generation_history_db_path=str(tmp_path / "db" / "app.sqlite3"),
        generation_job_queue_backend=queue_backend,
        zhipu_api_key=None,
    )


def test_readiness_report_allows_development_without_llm_key(tmp_path: Path) -> None:
    report = build_readiness_report(
        _settings(tmp_path),
        job_store=FakeJobStore({"queued": 1}),
    )

    assert report["ready"] is True
    assert readiness_status_code(report) == 200
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["database"]["data"] == {
        "backend": "sqlite",
        "jobs_by_status": {"queued": 1},
    }
    assert checks["queue"]["status"] == "ok"
    assert checks["llm_configuration"]["status"] == "warn"


def test_readiness_report_fails_when_runtime_path_is_not_writable(
    tmp_path: Path,
) -> None:
    def fail_path(label: str, path: Path) -> str | None:
        if label == "CHROMA_PATH":
            return f"{path} is not writable"
        return None

    report = build_readiness_report(
        _settings(tmp_path),
        job_store=FakeJobStore(),
        path_checker=fail_path,
    )

    assert report["ready"] is False
    assert readiness_status_code(report) == 503
    assert any(
        check["name"] == "runtime_path:CHROMA_PATH" and check["status"] == "error"
        for check in report["checks"]
    )


def test_readiness_report_fails_when_database_is_unreachable(tmp_path: Path) -> None:
    report = build_readiness_report(
        _settings(tmp_path),
        job_store=FakeJobStore(error=RuntimeError("database unavailable")),
    )

    assert report["ready"] is False
    database = next(check for check in report["checks"] if check["name"] == "database")
    assert database["status"] == "error"
    assert "database unavailable" in database["detail"]


def test_readiness_report_fails_when_rq_redis_is_unreachable(tmp_path: Path) -> None:
    def fail_redis(_: str) -> None:
        raise RuntimeError("redis unavailable")

    report = build_readiness_report(
        _settings(tmp_path, queue_backend="rq"),
        job_store=FakeJobStore(),
        redis_ping=fail_redis,
    )

    assert report["ready"] is False
    queue = next(check for check in report["checks"] if check["name"] == "queue")
    assert queue["status"] == "error"
    assert "redis unavailable" in queue["detail"]


def test_check_readiness_main_prints_json(monkeypatch, tmp_path, capsys) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", str(tmp_path / "model-cache"))
    monkeypatch.setenv("GENERATION_HISTORY_DB_PATH", str(tmp_path / "db" / "app.sqlite3"))
    monkeypatch.setenv("GENERATION_JOB_QUEUE_BACKEND", "in_memory")

    try:
        code = main(["--json"])
    finally:
        get_settings.cache_clear()

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready"] is True
    assert payload["status"] == "ready"
