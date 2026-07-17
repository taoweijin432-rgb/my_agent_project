from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _active_requirement_lines(content: str) -> str:
    return "\n".join(
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )


def test_runtime_env_example_contains_required_production_settings() -> None:
    content = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    required_keys = [
        "APP_ENV=development",
        "APP_API_KEY=",
        "APP_API_KEYS=",
        "ZHIPU_API_KEY=",
        "CORS_ALLOW_ORIGINS=",
        "EMBEDDING_PROVIDER=hash",
        "EMBEDDING_LOCAL_FILES_ONLY=false",
        "LLM_PROMPT_PRICE_PER_1K_TOKENS=",
        "LLM_COMPLETION_PRICE_PER_1K_TOKENS=",
        "LLM_COST_CURRENCY=",
        "AGENT_REVIEW_ENABLED=true",
        "AGENT_REVIEW_RETRY_ENABLED=false",
        "AGENT_REVIEW_MIN_SCORE=50",
        "AGENT_REVIEW_REQUIRE_PASS=false",
        "AGENT_QUERY_REWRITE_ENABLED=true",
        "AGENT_QUERY_REWRITE_MIN_CHUNKS=1",
        "AGENT_BUDGET_MAX_PROMPT_TOKENS=0",
        "AGENT_BUDGET_MAX_ESTIMATED_COST=0",
        "AGENT_WORKFLOW_BACKEND=langgraph",
        "GENERATION_JOB_QUEUE_BACKEND=rq",
        "REDIS_URL=redis://redis:6379/0",
        "RQ_QUEUE_NAME=generation",
        "RQ_JOB_TIMEOUT_SECONDS=",
        "RQ_RESULT_TTL_SECONDS=",
        "RQ_FAILURE_TTL_SECONDS=",
        "GENERATION_JOB_STALE_AFTER_SECONDS=",
        "RATE_LIMIT_ENABLED=true",
        "REQUEST_LOG_ENABLED=true",
        "REQUEST_LOG_FORMAT=text",
        "DATABASE_BACKEND=sqlite",
        "MYSQL_CONNECT_TIMEOUT_SECONDS=10",
        "MYSQL_READ_TIMEOUT_SECONDS=30",
        "MYSQL_WRITE_TIMEOUT_SECONDS=30",
        "MYSQL_ROOT_PASSWORD=",
        "MYSQL_DATABASE=agent",
        "MYSQL_USER=agent_user",
        "MYSQL_PASSWORD=",
        "API_HOST_PORT=8000",
        "APP_DATA_MOUNT=./data",
        "GENERATION_HISTORY_ENABLED=true",
        "GENERATION_HISTORY_DB_PATH=data/app.sqlite3",
        "RUNTIME_PATH_CHECK_ENABLED=true",
    ]

    for key in required_keys:
        assert key in content
    assert "QvSH" not in content


def test_docker_compose_uses_runtime_env_and_persistent_volumes() -> None:
    content = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert ".env.runtime" in content
    assert "IMAGE_TAG" in content
    assert "INSTALLER" in content
    assert "API_HOST_PORT" in content
    assert "REDIS_HOST_PORT" not in content
    assert "127.0.0.1:${REDIS_HOST_PORT" not in content
    assert "APP_DATA_MOUNT" in content
    assert "MODEL_CACHE_MOUNT" in content
    assert "redis:7-alpine" in content
    assert "redis-server" in content
    assert "redis-cli" in content
    assert "mysql:8.0" in content
    assert "profiles:" in content
    assert "mysqladmin ping" in content
    assert "mysql-data:/var/lib/mysql" in content
    assert "worker:" in content
    assert "python" in content
    assert "scripts/run_generation_worker.py" in content
    assert "scripts/check_runtime_paths.py" in content
    assert "disable: true" in content
    assert "${APP_DATA_MOUNT:-./data}:/app/data" in content
    assert "${MODEL_CACHE_MOUNT:-./.model_cache/huggingface}:/app/.model_cache/huggingface" in content
    assert "restart: unless-stopped" in content
    assert "http://127.0.0.1:8000/health" in content


def test_dockerfile_has_healthcheck() -> None:
    content = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "HEALTHCHECK" in content
    assert "http://127.0.0.1:8000/health" in content
    assert "requirements.txt" in content
    assert "constraints.txt" in content
    assert "COPY migrations ./migrations" in content
    assert "scripts/check_runtime_paths.py" in content


def test_smoke_mode_reuses_unified_compose_and_requirements() -> None:
    content = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")
    resolved_requirements = _active_requirement_lines(requirements)

    assert "ai-testcase-generator:${IMAGE_TAG:-local}" in content
    assert "APP_DATA_MOUNT" in content
    assert "MODEL_CACHE_MOUNT" in content
    assert "smoke-data:" in content
    assert "smoke-model-cache:" in content
    assert "-c constraints.txt" in requirements
    assert "fastapi" in resolved_requirements
    assert "redis" in resolved_requirements
    assert "rq" in resolved_requirements
    assert "langgraph" in resolved_requirements
    assert "chromadb" in resolved_requirements
    assert "PyMySQL" in resolved_requirements
    assert "ruff" in resolved_requirements
    assert "torch" not in resolved_requirements


def test_unified_requirements_omit_large_semantic_embedding_deps() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "semantic embedding dependencies" in requirements
    assert "sentence-transformers" not in _active_requirement_lines(requirements)
    assert "torch" not in _active_requirement_lines(requirements)
    assert "cuda" not in requirements.lower()


def test_mysql_compose_defines_mysql_service_and_backend_override() -> None:
    content = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "mysql:" in content
    assert "mysql:8.0" in content
    assert "profiles:" in content
    assert "MYSQL_HOST_PORT" not in content
    assert "127.0.0.1:${MYSQL_HOST_PORT" not in content
    assert "mysql-data:/var/lib/mysql" in content
    assert "migrations/mysql/001_initial.sql" in content
    assert "mysqladmin ping" in content
    assert "REQUIREMENTS_FILE" not in content
    assert "MYSQL_ROOT_PASSWORD:" in content
    assert "MYSQL_DATABASE:" in content
    assert "MYSQL_USER:" in content
    assert "MYSQL_PASSWORD:" in content
    assert "MYSQL_ROOT_PASSWORD=" in env_example
    assert "MYSQL_DATABASE=agent" in env_example
    assert "MYSQL_USER=agent_user" in env_example
    assert "MYSQL_PASSWORD=" in env_example
    assert "MYSQL_CONNECT_TIMEOUT_SECONDS=10" in env_example
    assert "MYSQL_READ_TIMEOUT_SECONDS=30" in env_example
    assert "MYSQL_WRITE_TIMEOUT_SECONDS=30" in env_example
    assert "DATABASE_URL=mysql://agent_user:your_agent_password@mysql:3306/agent?charset=utf8mb4" in env_example


def test_mysql_operations_doc_covers_backup_and_restore() -> None:
    content = (PROJECT_ROOT / "docs" / "mysql-operations.md").read_text(encoding="utf-8")

    assert "--profile mysql" in content
    assert "migrations/mysql/001_initial.sql" in content
    assert "mysqldump --single-transaction" in content
    assert "--no-tablespaces" in content
    assert "exec -T mysql" in content
    assert "COMPOSE_PROJECT_NAME=agent_restore_test" in content
    assert "agent_restore_test_mysql-data" in content
    assert "generation_records" in content
    assert "generation_jobs" in content
    assert "MYSQL_CONNECT_TIMEOUT_SECONDS" in content
    assert "connect_timeout" in content
    assert "不要在不确认数据价值的情况下执行 `docker compose down -v`" in content


def test_ci_workflow_runs_release_checks_and_manual_llm_smoke() -> None:
    content = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "ubuntu-latest" in content
    assert "python-version: \"3.12\"" in content
    assert "requirements.txt" in content
    assert "python -m ruff check app scripts tests" in content
    assert "npm test" in content
    assert "python scripts/run_release_checks.py" in content
    assert "workflow_dispatch" in content
    assert "run_llm_smoke" in content
    assert "secrets.ZHIPU_API_KEY" in content
    assert "--include-llm-smoke" in content
