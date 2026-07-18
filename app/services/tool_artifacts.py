import re
import shutil
import time
from pathlib import Path
from uuid import uuid4

from app.core.config import PROJECT_ROOT
from app.services.redaction import redact_sensitive_text


class ToolArtifactStore:
    def __init__(
        self,
        root_dir: str | Path,
        *,
        max_bytes: int = 200000,
        project_root: Path = PROJECT_ROOT,
    ):
        self.project_root = project_root.resolve()
        self.root_dir = _resolve_artifact_root(root_dir, self.project_root)
        self.max_bytes = max_bytes

    def write_text(self, *, prefix: str, filename: str, content: str) -> str:
        safe_prefix = _safe_name(prefix) or "artifact"
        safe_filename = _safe_name(filename) or "output.txt"
        artifact_dir = self.root_dir / f"{safe_prefix}-{uuid4().hex[:12]}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        path = artifact_dir / safe_filename
        path.write_text(
            _truncate(redact_sensitive_text(content), self.max_bytes),
            encoding="utf-8",
        )
        return _display_path(path, self.project_root)

    def resolve_path(self, artifact_path: str | Path) -> Path:
        raw_path = Path(str(artifact_path))
        if raw_path.is_absolute() or ".." in raw_path.parts:
            raise ValueError("artifact path must be a safe project-relative path")

        path = (self.project_root / raw_path).resolve()
        if not _is_under(path, self.root_dir):
            raise ValueError("artifact path must stay inside artifact root")
        if not path.is_file():
            raise FileNotFoundError(str(artifact_path))
        return path

    def cleanup_expired(self, *, retention_seconds: int) -> list[str]:
        if retention_seconds <= 0 or not self.root_dir.exists():
            return []
        cutoff = time.time() - retention_seconds
        removed: list[str] = []
        for path in self.root_dir.iterdir():
            if path.stat().st_mtime >= cutoff:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(_display_path(path, self.project_root))
        return removed


def _resolve_artifact_root(root_dir: str | Path, project_root: Path) -> Path:
    path = Path(root_dir)
    if not path.is_absolute():
        path = project_root / path
    resolved = path.resolve()
    if project_root not in resolved.parents and resolved != project_root:
        raise ValueError("artifact root must stay inside project root")
    return resolved


def _is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return cleaned.strip(".-")[:120]


def _truncate(content: str, max_bytes: int) -> str:
    raw = content.encode("utf-8")
    if len(raw) <= max_bytes:
        return content
    truncated = raw[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n\n[artifact truncated]\n"


def _display_path(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)
