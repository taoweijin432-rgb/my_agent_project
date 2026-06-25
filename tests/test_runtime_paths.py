from scripts.check_runtime_paths import main


def test_runtime_path_check_creates_and_checks_runtime_directories(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RUNTIME_PATH_CHECK_ENABLED", raising=False)
    monkeypatch.setenv("CHROMA_PATH", "runtime/chroma")
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", "runtime/model-cache")
    monkeypatch.setenv("DATABASE_BACKEND", "sqlite")
    monkeypatch.setenv("GENERATION_HISTORY_DB_PATH", "runtime/db/app.sqlite3")

    main()

    assert (tmp_path / "runtime" / "chroma").is_dir()
    assert (tmp_path / "runtime" / "model-cache").is_dir()
    assert (tmp_path / "runtime" / "db").is_dir()


def test_runtime_path_check_can_be_disabled(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUNTIME_PATH_CHECK_ENABLED", "false")
    monkeypatch.setenv("CHROMA_PATH", "runtime/chroma")
    monkeypatch.setenv("EMBEDDING_CACHE_DIR", "runtime/model-cache")

    main()

    assert not (tmp_path / "runtime").exists()
