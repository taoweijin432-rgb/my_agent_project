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


def test_tool_artifact_store_resolves_returned_artifact_path(tmp_path: Path) -> None:
    store = ToolArtifactStore("artifacts", project_root=tmp_path)
    path = store.write_text(prefix="TP-001", filename="output.txt", content="hello")

    resolved = store.resolve_path(path)

    assert resolved == tmp_path / path


def test_tool_artifact_store_rejects_paths_outside_artifact_root(tmp_path: Path) -> None:
    store = ToolArtifactStore("artifacts", project_root=tmp_path)
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text("secret", encoding="utf-8")

    try:
        store.resolve_path("secret.txt")
    except ValueError as exc:
        assert "artifact root" in str(exc)
    else:
        raise AssertionError("resolve_path should reject files outside artifact root")


def test_tool_artifact_store_rejects_missing_or_directory_paths(tmp_path: Path) -> None:
    store = ToolArtifactStore("artifacts", project_root=tmp_path)
    path = store.write_text(prefix="TP-001", filename="output.txt", content="hello")
    artifact_dir = Path(path).parent.as_posix()

    try:
        store.resolve_path(f"{path}.missing")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("resolve_path should reject missing artifacts")

    try:
        store.resolve_path(artifact_dir)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("resolve_path should reject artifact directories")


def test_tool_artifact_store_truncates_large_content(tmp_path: Path) -> None:
    store = ToolArtifactStore(
        "artifacts",
        max_bytes=10,
        project_root=tmp_path,
    )

    path = store.write_text(prefix="TP-001", filename="output.txt", content="x" * 100)

    content = (tmp_path / path).read_text(encoding="utf-8")
    assert "[artifact truncated]" in content


def test_tool_artifact_store_redacts_sensitive_content(tmp_path: Path) -> None:
    store = ToolArtifactStore("artifacts", project_root=tmp_path)

    path = store.write_text(
        prefix="TP-001",
        filename="output.txt",
        content="\n".join(
            [
                "Authorization: Bearer secret-token",
                "Set-Cookie: session=secret-cookie; HttpOnly",
                '{"access_token":"secret-access","password":"secret-password"}',
                "ZHIPU_API_KEY=secret-zhipu-key",
                "DATABASE_URL=mysql://agent:secret-db-password@mysql:3306/agent",
                "status=visible",
            ]
        ),
    )

    content = (tmp_path / path).read_text(encoding="utf-8")
    assert "secret-token" not in content
    assert "secret-cookie" not in content
    assert "secret-access" not in content
    assert "secret-password" not in content
    assert "secret-zhipu-key" not in content
    assert "secret-db-password" not in content
    assert "Authorization: [redacted]" in content
    assert '"access_token":"[redacted]"' in content
    assert "DATABASE_URL=mysql://agent:[redacted]@mysql:3306/agent" in content
    assert "status=visible" in content


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
