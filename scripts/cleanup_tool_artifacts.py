import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.core.config import get_settings
from app.services.tool_artifacts import ToolArtifactStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean expired tool execution artifacts.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    parser.add_argument(
        "--retention-seconds",
        type=int,
        default=None,
        help="Override TEST_TOOL_ARTIFACT_RETENTION_SECONDS.",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    retention_seconds = (
        args.retention_seconds
        if args.retention_seconds is not None
        else settings.test_tool_artifact_retention_seconds
    )
    store = ToolArtifactStore(
        settings.test_tool_artifact_dir,
        max_bytes=settings.test_tool_artifact_max_bytes,
    )
    removed = store.cleanup_expired(retention_seconds=retention_seconds)
    payload = {
        "artifact_dir": settings.test_tool_artifact_dir,
        "retention_seconds": retention_seconds,
        "removed_count": len(removed),
        "removed": removed,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("Tool artifact cleanup")
        print(f"  artifact_dir: {payload['artifact_dir']}")
        print(f"  retention_seconds: {payload['retention_seconds']}")
        print(f"  removed_count: {payload['removed_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
