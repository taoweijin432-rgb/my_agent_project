from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_env_example_contains_required_production_settings() -> None:
    content = (PROJECT_ROOT / ".env.runtime.example").read_text(encoding="utf-8")

    required_keys = [
        "APP_ENV=production",
        "APP_API_KEY=",
        "ZHIPU_API_KEY=",
        "CORS_ALLOW_ORIGINS=",
        "EMBEDDING_PROVIDER=sentence_transformers",
        "EMBEDDING_LOCAL_FILES_ONLY=true",
        "RATE_LIMIT_ENABLED=true",
        "REQUEST_LOG_ENABLED=true",
        "GENERATION_HISTORY_ENABLED=true",
        "GENERATION_HISTORY_DB_PATH=data/app.sqlite3",
    ]

    for key in required_keys:
        assert key in content
    assert "QvSH" not in content


def test_docker_compose_uses_runtime_env_and_persistent_volumes() -> None:
    content = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert ".env.runtime" in content
    assert "./data:/app/data" in content
    assert "./.model_cache/huggingface:/app/.model_cache/huggingface" in content
    assert "restart: unless-stopped" in content
    assert "http://127.0.0.1:8000/health" in content


def test_dockerfile_has_healthcheck() -> None:
    content = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "HEALTHCHECK" in content
    assert "http://127.0.0.1:8000/health" in content
