import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Pattern


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 1_000_000
SKIP_SUFFIXES = {
    ".db",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".webp",
    ".zip",
}
SKIP_PATH_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "build",
    "dist",
    "htmlcov",
    "node_modules",
}
PLACEHOLDER_MARKERS = (
    "changeme",
    "ci-service-key",
    "current-strong-service-api-key",
    "dummy",
    "example",
    "fake",
    "next-strong-service-api-key",
    "placeholder",
    "redacted",
    "release-check-key",
    "replace-with",
    "strong-service-api-key",
    "test",
    "your_",
    "your-",
)
TEST_PLACEHOLDER_MARKERS = (
    "secret",
    "token",
    "password",
)


@dataclass(frozen=True)
class SecretRule:
    name: str
    pattern: Pattern[str]
    group: str | int = 0


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    rule: str
    preview: str


SECRET_RULES = [
    SecretRule(
        name="private_key",
        pattern=re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----"),
    ),
    SecretRule(
        name="openai_api_key",
        pattern=re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{20,}\b"),
    ),
    SecretRule(
        name="github_token",
        pattern=re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    ),
    SecretRule(
        name="aws_access_key",
        pattern=re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    SecretRule(
        name="slack_token",
        pattern=re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    ),
    SecretRule(
        name="jwt",
        pattern=re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
    ),
    SecretRule(
        name="secret_assignment",
        pattern=re.compile(
            r"\b(?P<key>[A-Z0-9_]*(?:API_KEY|PASSWORD|SECRET|TOKEN)|DATABASE_URL)"
            r"\b\s*[:=]\s*(?P<value>[^\s#'\",]+)"
        ),
        group="value",
    ),
]


def scan_paths(paths: list[Path], *, root: Path = PROJECT_ROOT) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for path in paths:
        if not _should_scan(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        except OSError:
            continue
        relative_path = _relative_path(path, root)
        for line_number, line in enumerate(content.splitlines(), start=1):
            findings.extend(_scan_line(relative_path, line_number, line))
    return findings


def discover_paths(*, root: Path = PROJECT_ROOT) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return [root / line for line in result.stdout.splitlines() if line]
    return [path for path in root.rglob("*") if path.is_file()]


def build_summary(findings: list[SecretFinding], *, scanned_files: int) -> dict:
    return {
        "ok": not findings,
        "scanned_files": scanned_files,
        "finding_count": len(findings),
        "findings": [asdict(finding) for finding in findings],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.root.resolve()
    paths = [path.resolve() for path in args.path] if args.path else discover_paths(root=root)
    scanned_paths = [path for path in paths if _should_scan(path)]
    findings = scan_paths(scanned_paths, root=root)
    summary = build_summary(findings, scanned_files=len(scanned_paths))
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print_text(summary)
    return 0 if summary["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan repository files for high-confidence committed secrets.",
    )
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--path", type=Path, action="append")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def print_text(summary: dict) -> None:
    print("Secret scan")
    print(f"ok: {str(summary['ok']).lower()}")
    print(f"scanned_files: {summary['scanned_files']}")
    print(f"finding_count: {summary['finding_count']}")
    for finding in summary["findings"]:
        print(
            f"  {finding['path']}:{finding['line']} "
            f"{finding['rule']} {finding['preview']}"
        )


def _scan_line(path: str, line_number: int, line: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for rule in SECRET_RULES:
        for match in rule.pattern.finditer(line):
            value = str(match.group(rule.group))
            if _is_allowed_value(path, value):
                continue
            findings.append(
                SecretFinding(
                    path=path,
                    line=line_number,
                    rule=rule.name,
                    preview=_preview(value),
                )
            )
    return findings


def _should_scan(path: Path) -> bool:
    if path.suffix.lower() in SKIP_SUFFIXES:
        return False
    if any(part in SKIP_PATH_PARTS for part in path.parts):
        return False
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return False
    except OSError:
        return False
    return True


def _is_allowed_value(path: str, value: str) -> bool:
    normalized = value.strip().strip("'\"").lower()
    if not normalized:
        return True
    if normalized.startswith("...") or normalized.startswith("{"):
        return True
    if normalized.startswith("${") or "secrets." in normalized:
        return True
    if any(marker in normalized for marker in PLACEHOLDER_MARKERS):
        return True
    if path.startswith("tests/") and any(
        marker in normalized for marker in TEST_PLACEHOLDER_MARKERS
    ):
        return True
    return False


def _preview(value: str) -> str:
    cleaned = value.strip().strip("'\"")
    if len(cleaned) <= 8:
        return "***"
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
