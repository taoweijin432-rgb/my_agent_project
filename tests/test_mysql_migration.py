from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_mysql_initial_schema_contains_runtime_tables() -> None:
    schema = (PROJECT_ROOT / "migrations" / "mysql" / "001_initial.sql").read_text(
        encoding="utf-8"
    )

    required_fragments = [
        "CREATE TABLE IF NOT EXISTS generation_records",
        "CREATE TABLE IF NOT EXISTS generation_jobs",
        "request_json json NOT NULL",
        "response_json json",
        "usage_json json NOT NULL",
        "error_json json",
        "CHECK (status IN ('success', 'failed'))",
        "CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))",
        "DEFAULT CHARSET=utf8mb4",
        "idx_generation_records_created_at",
        "idx_generation_records_gate_status",
        "idx_generation_jobs_active",
    ]

    for fragment in required_fragments:
        assert fragment in schema


def test_mysql_init_script_uses_optional_pymysql_dependency() -> None:
    script = (PROJECT_ROOT / "scripts" / "init_mysql.py").read_text(encoding="utf-8")
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(
        encoding="utf-8"
    )

    assert "DATABASE_URL is required" in script
    assert "import pymysql" in script
    assert "requirements.txt" in script
    assert "mysql:// or mysql+pymysql://" in script
    assert "PyMySQL" in requirements
