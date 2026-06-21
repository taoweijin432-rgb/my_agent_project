import argparse
import os
import sys
import traceback
from argparse import Namespace
from pathlib import Path

import uvicorn


def parse_args(argv: list[str] | None = None) -> Namespace:
    parser = argparse.ArgumentParser(description="Run the FastAPI service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--log-to-file",
        action="store_true",
        help="Write stdout and stderr to logs/server.*.log.",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    project_root = Path(__file__).resolve().parents[1]
    log_dir = project_root / "logs"
    os.chdir(project_root)
    sys.path.insert(0, str(project_root))
    if args.log_to_file:
        log_dir.mkdir(parents=True, exist_ok=True)
        sys.stdout = (log_dir / "server.out.log").open(
            "a",
            encoding="utf-8",
            buffering=1,
        )
        sys.stderr = (log_dir / "server.err.log").open(
            "a",
            encoding="utf-8",
            buffering=1,
        )

    print(f"Starting service at http://{args.host}:{args.port}", flush=True)

    try:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=args.port,
            log_level="info",
            reload=args.reload,
        )
    except BaseException:
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "server-bootstrap-error.log").open("a", encoding="utf-8") as file:
            traceback.print_exc(file=file)
        raise


if __name__ == "__main__":
    main()
