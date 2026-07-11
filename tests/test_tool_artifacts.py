import os
from pathlib import Path
from uuid import uuid4

from app.core.config import get_settings
from app.services.tool_artifacts import ToolArtifactStore
from scripts.cleanup_tool_artifacts import main


def test_tool_artifact_store_writes_safe_relative_path(tmp_path: Path) -> None:
    store = ToolArtifactStore(
        "artifacts",
        max_bytes=100,
        project_root=tmp_path,
    )

    path = store.write_text(
        prefix="TP/001",
        filename="../output.txt",
        content="hello",
    )

    artifact_path = tmp_path / path
    assert path.startswith("artifacts/TP-001-")
    assert artifact_path.read_text(encoding="utf-8") == "hello"


def test_tool_artifact_store_truncates_large_content(tmp_path: Path) -> None:
    store = ToolArtifactStore(
        "artifacts",
        max_bytes=10,
        project_root=tmp_path,
    )

    path = store.write_text(prefix="TP-001", filename="output.txt", content="x" * 100)

    content = (tmp_path / path).read_text(encoding="utf-8")
    assert "[artifact truncated]" in content


def test_tool_artifact_store_cleans_expired_artifacts(tmp_path: Path) -> None:
    store = ToolArtifactStore("artifacts", project_root=tmp_path)
    old_path = store.write_text(prefix="old", filename="output.txt", content="old")
    fresh_path = store.write_text(prefix="fresh", filename="output.txt", content="fresh")
    old_dir = (tmp_path / old_path).parent
    old_timestamp = 1
    os.utime(old_dir, (old_timestamp, old_timestamp))

    removed = store.cleanup_expired(retention_seconds=60)

    assert removed == [str(old_dir.relative_to(tmp_path))]
    assert not old_dir.exists()
    assert (tmp_path / fresh_path).exists()


def test_cleanup_tool_artifacts_main_prints_json(monkeypatch, tmp_path, capsys) -> None:
    artifact_dir = f"data/test-artifacts-cleanup-{uuid4().hex}"
    monkeypatch.setenv("TEST_TOOL_ARTIFACT_DIR", artifact_dir)
    monkeypatch.setenv("TEST_TOOL_ARTIFACT_RETENTION_SECONDS", "60")
    get_settings.cache_clear()
    store = ToolArtifactStore(artifact_dir)
    old_path = store.write_text(prefix="old", filename="output.txt", content="old")
    old_dir = Path(old_path).parent
    os.utime(old_dir, (1, 1))

    try:
        assert main(["--json"]) == 0
    finally:
        get_settings.cache_clear()

    output = capsys.readouterr().out
    assert '"removed_count": 1' in output
