import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings
from app.services.readiness import build_readiness_report, format_readiness_text


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_readiness_report(get_settings())
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_readiness_text(report))
    return 0 if report["ready"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check API runtime readiness without starting an HTTP client.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
